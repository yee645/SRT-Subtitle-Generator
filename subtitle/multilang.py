# -*- coding: utf-8 -*-
"""
多語字幕包：一份校對好的母帶字幕，一次翻成多國語言並各自輸出可上傳的檔。

調研（中英文皆搜）的數字很直接：YouTube 官方說明指出**平均一位創作者
超過三分之二的觀看時間來自居住地區以外的觀眾**，而上傳多語言內容的
創作者**超過 25% 的觀看時間來自非影片主要語言的觀眾**。

英文調研則直接寫出了正確的作業流程：

    「從**一份校對好的母帶檔案**開始：先產生原文字幕、**在那裡把錯誤
      全部修好**、再**把那份 SRT 批次翻成每一個目標語言**、抽查、
      然後輸出各平台需要的格式。」

以及規模化時的關鍵限制：「影片一多，手動一支一支上傳翻譯**根本行不通**」。

本工具的前半段已經很完整——轉錄、編修、自動修正詞庫、術語一致性檢查
（v1.41.0）都是在把那份**母帶**修乾淨。缺的正是後半段：

| 既有的翻譯功能（v1.18.0） | 差在哪 |
|---------------------------|--------|
| 一次只能翻**一種**語言 | 要五種語言就得重跑五次 |
| 只有 GUI 入口 | 十支影片＝十次手動操作，正是調研說的「行不通」 |
| 產出的是**雙語**字幕（原文+譯文上下行） | 那是給**燒錄**用的；上傳到 YouTube 每個語言要的是**單語**檔 |

最後一點特別容易被忽略：拿雙語字幕去當英文字幕上傳，英文觀眾會看到
每一句都黏著看不懂的中文。所以本模組產出的一律是**單語**（replace）
字幕，與燒錄用的雙語模式分開。

另外做了一項省錢的處理：**重複的句子只送一次 API**。字幕裡「對」「嗯」
「我們繼續」這類短句會重複很多次，逐句送等於重複付費；去重後只送一次
再攤回原本的位置，譯文完全一致而且更省。

本模組不重新實作翻譯，一律呼叫既有的 `translator.translate_texts`。

零 GUI 依賴，供 CLI 批次與翻譯視窗共用。
"""

from __future__ import annotations

import os
import re
from typing import Callable, Optional

from subtitle.translator import LANGUAGE_LABELS, translate_texts

# 使用者可調參數（config["multilang"]）。
DEFAULT_MULTILANG = {
    # 目標語言清單（逗號或空白分隔的語言代碼）。
    "languages": "en,ja",
    # 略過與影片原文相同的語言——翻成自己沒有意義，還要多付一次錢。
    "skip_source": True,
    # 重複的句子只送一次 API（譯文相同，純粹省錢）。
    "dedupe": True,
}


def resolve_multilang_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出多語字幕包參數，缺漏補齊預設值。"""
    raw = dict(DEFAULT_MULTILANG)
    if config:
        raw.update({k: v for k, v in config.get("multilang", {}).items()
                    if v is not None})
    return {
        "languages": str(raw.get("languages", "") or ""),
        "skip_source": bool(raw.get("skip_source", True)),
        "dedupe": bool(raw.get("dedupe", True)),
    }


def parse_languages(text, source_language: str = "",
                    skip_source: bool = True) -> list:
    """
    把使用者輸入的語言清單整理成乾淨、去重、保序的語言代碼清單。

    語言代碼不限於內建清單——未收錄的代碼 translator 會直接當作語言
    名稱交給模型，所以這裡不擋，只做整理。
    """
    if isinstance(text, (list, tuple)):
        parts = [str(p) for p in text]
    else:
        parts = re.split(r"[,，\s]+", str(text or ""))
    source = (source_language or "").strip().lower()
    seen = set()
    langs = []
    for part in parts:
        code = part.strip()
        if not code:
            continue
        key = code.lower()
        if key in seen:
            continue
        if skip_source and source and key == source:
            continue
        seen.add(key)
        langs.append(code)
    return langs


def language_label(code: str) -> str:
    """語言代碼的顯示名稱；未收錄時直接顯示代碼本身。"""
    return LANGUAGE_LABELS.get(code, code)


def dedupe_texts(texts: list) -> tuple:
    """
    把重複的句子收斂成唯一清單，回傳 (唯一句子, 還原索引)。

    字幕裡「對」「嗯」「我們繼續」這類短句會重複很多次，逐句送 API
    等於重複付費。還原索引讓譯文可以原樣攤回每一個位置。
    """
    unique = []
    index_of = {}
    mapping = []
    for text in texts or []:
        key = text or ""
        if key not in index_of:
            index_of[key] = len(unique)
            unique.append(key)
        mapping.append(index_of[key])
    return (unique, mapping)


def expand_translations(translated: list, mapping: list) -> list:
    """把去重後的譯文依還原索引攤回原本的長度與順序。"""
    out = []
    for index in mapping or []:
        out.append(translated[index] if 0 <= index < len(translated) else "")
    return out


def translate_to_language(cues: list, language: str, api_key: str,
                          batch_size: int = 30, dedupe: bool = True,
                          progress_cb: Optional[Callable] = None) -> list:
    """
    把字幕翻成單一語言，回傳**單語**的新 cue 清單（不含原文）。

    上傳用的字幕每個語言都必須是單語檔——把雙語字幕當英文字幕上傳，
    英文觀眾每一句都會看到黏在一起的原文。

    翻譯本身呼叫既有的 translator.translate_texts，本函式不重新實作。
    回傳的 cue 不含 "words"：翻譯後逐字時間軸已經對不上新文字。
    """
    if not cues:
        return []
    texts = [cue.get("text", "") or "" for cue in cues]

    if dedupe:
        unique, mapping = dedupe_texts(texts)
        done = translate_texts(unique, language, api_key,
                               progress_cb=progress_cb,
                               batch_size=batch_size)
        translated = expand_translations(done, mapping)
    else:
        translated = translate_texts(texts, language, api_key,
                                     progress_cb=progress_cb,
                                     batch_size=batch_size)

    new_cues = []
    for cue, original, target in zip(cues, texts, translated):
        new_cue = {k: v for k, v in cue.items() if k != "words"}
        target = (target or "").strip()
        # 譯文為空時退回原文，避免產生空字幕（沿用 translator 的作法）。
        new_cue["text"] = target if target else original
        new_cues.append(new_cue)
    return new_cues


def build_language_pack(cues: list, languages: list, api_key: str,
                        batch_size: int = 30, dedupe: bool = True,
                        progress_cb: Optional[Callable] = None) -> dict:
    """
    一份母帶字幕翻成多國語言，回傳 {語言代碼: 單語 cue 清單}。

    某一個語言失敗不會中斷其他語言——回傳的 dict 只會少那一個，
    呼叫端可以據此如實回報，而不是整批一起失敗。
    """
    pack = {}
    languages = languages or []
    total = len(languages)
    for index, language in enumerate(languages):
        label = language_label(language)

        def report(ratio, message, _i=index, _label=label):
            if callable(progress_cb):
                overall = (_i + max(0.0, min(ratio, 1.0))) / max(total, 1)
                progress_cb(overall,
                            f"[{_i + 1}/{total}] {_label}：{message}")

        # 每一個語言開始時自己先回報一次，不依賴內層翻譯函式是否回呼——
        # 否則整批只會在最後跳一次，使用者完全看不出進度到哪。
        report(0.0, "開始翻譯…")
        pack[language] = translate_to_language(
            cues, language, api_key, batch_size=batch_size,
            dedupe=dedupe, progress_cb=report)
        report(1.0, "完成")
    return pack


def pack_path(media_path: str, language: str, out_dir: str = "") -> str:
    """
    產生該語言的字幕檔路徑，如「影片.en.srt」。

    語言代碼放在副檔名之前是字幕檔的通用慣例，上傳時一眼就知道
    哪一個檔對應哪一個語言。
    """
    base = os.path.splitext(os.path.basename(media_path or "字幕"))[0]
    folder = out_dir or os.path.dirname(os.path.abspath(media_path or "."))
    return os.path.join(folder, f"{base}.{language}.srt")


def format_pack_report(pack: dict, languages: list, paths: Optional[dict] = None,
                       failed: Optional[dict] = None) -> str:
    """把多語字幕包的結果排成純文字報告（CLI 輸出與 GUI 顯示共用）。"""
    lines = ["===== 多語字幕包（一份母帶翻成多國語言）====="]
    languages = languages or []
    if not languages:
        lines.append("・沒有指定任何目標語言。")
        lines.append("")
        lines.append("請於 config.json 的 multilang.languages 填入語言代碼"
                     "（逗號分隔，如 en,ja,ko），或用 --languages 指定。")
        return "\n".join(lines)

    paths = paths or {}
    failed = failed or {}
    for language in languages:
        label = language_label(language)
        if language in failed:
            lines.append(f"  ✘ {label}（{language}）：{failed[language]}")
            continue
        cues = (pack or {}).get(language) or []
        target = paths.get(language, "")
        lines.append(f"  ✔ {label}（{language}）：{len(cues)} 句"
                     + (f" → {os.path.basename(target)}" if target else ""))

    ok_count = len([l for l in languages if l not in failed])
    lines.append("")
    lines.append(f"共 {ok_count}/{len(languages)} 個語言完成。"
                 "每個檔都是「單語」字幕，可直接在 YouTube Studio "
                 "逐一上傳對應語言。")
    if failed:
        lines.append("失敗的語言不影響其他語言的輸出，可單獨重跑。")
    return "\n".join(lines)
