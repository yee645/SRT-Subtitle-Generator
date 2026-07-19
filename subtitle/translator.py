# -*- coding: utf-8 -*-
"""
字幕翻譯模組：把生成好的字幕譯成另一種語言，做出雙語字幕。

調研痛點：YouTube 的自動字幕功能無法直接產生雙語軌，觀眾端的自動翻譯
字幕品質也不穩定——而超過三分之二的 YouTube 觀看時數來自創作者所在
地區以外，字幕語言常是能不能留住海外觀眾的關鍵。目前創作者只能把字幕
檔上傳到另一個第三方翻譯網站，再手動拼成「原文＋譯文」的雙語版本。

本模組重用「轉寫設定」既有的 OpenAI API 金鑰與呼叫慣例（同一組金鑰、
同一套錯誤訊息前綴，讓 errors.py 免費歸類），把字幕依批次丟給 Chat
Completions API 翻譯，輸出雙語（原文+譯文上下行）或取代（僅譯文）
兩種模式的新字幕清單。

零 GUI 依賴，供翻譯對話框與 CLI 共用。
"""

from __future__ import annotations

import json
from typing import Callable, Optional

# 使用者可調參數（config["translate"]）。
DEFAULT_TRANSLATE = {
    "target_language": "en",   # 目標語言代碼
    "mode": "bilingual",       # bilingual＝原文+譯文上下行；replace＝僅保留譯文
    "batch_size": 30,          # 每次 API 請求翻譯的字幕句數
}

# 語言選單（GUI 下拉共用）：代碼 → 顯示名稱。
LANGUAGE_LABELS = {
    "en": "英文", "ja": "日文", "ko": "韓文", "zh-TW": "繁體中文",
    "zh-CN": "簡體中文", "es": "西班牙文", "fr": "法文", "de": "德文",
    "id": "印尼文", "vi": "越南文", "th": "泰文",
}

_MODES = ("bilingual", "replace")
_BATCH_RANGE = (5, 80)

# 翻譯用的聊天模型。轉寫用的 whisper-1 是語音辨識模型、不能拿來做
# 文字翻譯，故另外指定一個文字聊天模型；改版時只需調整此常數。
_CHAT_MODEL = "gpt-4o-mini"


def _clamp_int(value, low, high, fallback):
    try:
        value = int(float(value))
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_translate_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出翻譯參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_TRANSLATE)
    if config:
        raw.update({k: v for k, v in config.get("translate", {}).items()
                    if v is not None})
    mode = raw.get("mode")
    if mode not in _MODES:
        mode = DEFAULT_TRANSLATE["mode"]
    language = raw.get("target_language")
    if language not in LANGUAGE_LABELS:
        language = DEFAULT_TRANSLATE["target_language"]
    return {
        "target_language": language,
        "mode": mode,
        "batch_size": _clamp_int(raw.get("batch_size"), *_BATCH_RANGE,
                                 DEFAULT_TRANSLATE["batch_size"]),
    }


def _notify(progress_cb, ratio, message):
    if callable(progress_cb):
        progress_cb(ratio, message)


def _chunk(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _strip_code_fence(text: str) -> str:
    """去除 API 回應可能夾帶的 ```json ... ``` 圍欄，方便後續 json.loads。"""
    text = (text or "").strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines:
        lines = lines[1:]  # 去掉開頭的 ``` 或 ```json 那一行
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_batch_response(content: str) -> list:
    """把 API 回應內容解析成清單；解析失敗或格式不符時回傳空清單。"""
    text = _strip_code_fence(content)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


def translate_texts(
    texts: list,
    target_language: str,
    api_key: str,
    progress_cb: Optional[Callable[[float, str], None]] = None,
    batch_size: int = 30,
) -> list:
    """
    呼叫 OpenAI API 把字幕文字批次翻成目標語言。

    參數：
        texts: 原文清單（依序對應輸出）。
        target_language: 目標語言代碼（見 LANGUAGE_LABELS，未收錄的代碼
            會直接當作語言名稱交給模型）。
        api_key: 轉寫設定共用的 OpenAI API 金鑰。
        progress_cb: (ratio, message) 進度回呼。
        batch_size: 每次 API 請求的句數。
    回傳：
        與 texts 等長的譯文清單。單句解析失敗或批次長度不符時，
        該筆保留原文並計入 fallback，絕不因此中斷整體流程或漏句。
    """
    if not texts:
        return []
    api_key = (api_key or "").strip()
    if not api_key:
        raise RuntimeError("已啟用 API 模式，但尚未填入 OpenAI API 金鑰。")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "未安裝 openai 函式庫。請執行：pip install openai"
        ) from exc

    client = OpenAI(api_key=api_key)
    language_label = LANGUAGE_LABELS.get(target_language, target_language)

    batches = list(_chunk(texts, max(int(batch_size or 30), 1)))
    total = len(batches)
    results = []
    fallback_count = 0

    for index, batch in enumerate(batches, start=1):
        _notify(progress_cb, (index - 1) / total if total else 0.0,
                f"正在翻譯字幕（第 {index}/{total} 批）...")
        system_prompt = (
            "You are a professional subtitle translator. Translate each "
            f"numbered line in the user's JSON array into {language_label}. "
            "Keep the exact line order and line count — never merge or "
            "split lines. Use a concise, natural subtitle register. "
            "Return ONLY a JSON array of the translated strings, with no "
            "extra text, explanation, or markdown."
        )
        user_prompt = json.dumps(batch, ensure_ascii=False)
        try:
            response = client.chat.completions.create(
                model=_CHAT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            content = response.choices[0].message.content
        except Exception as exc:
            raise RuntimeError(f"呼叫 OpenAI API 失敗：{exc}") from exc

        parsed = _parse_batch_response(content)
        for i, original in enumerate(batch):
            if (i < len(parsed) and isinstance(parsed[i], str)
                    and parsed[i].strip()):
                results.append(parsed[i])
            else:
                results.append(original)
                fallback_count += 1

    done_msg = "字幕翻譯完成"
    if fallback_count:
        done_msg += f"（{fallback_count} 句因格式問題沿用原文）"
    _notify(progress_cb, 1.0, done_msg)
    return results


def translate_cues(
    cues: list,
    settings: dict,
    api_key: str,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> list:
    """
    把整份字幕 cue 清單翻譯成雙語或取代版本，回傳全新的 cue 清單。

    - bilingual：text 改為「原文\\n譯文」（譯文與原文相同或為空時只留原文）。
    - replace：text 改為譯文（譯文為空時退回原文，避免產生空字幕）。
    - 兩種模式輸出的 cue 都不含 "words"：翻譯後逐字時間軸已經對不上
      新文字，下游的逐字動態字幕（karaoke／word 模式）在缺少 words 時
      會自動退回整句顯示，不會出錯或顯示錯亂的逐字動畫。

    不修改傳入的 cues（回傳全新 dict 清單）。
    """
    if not cues:
        return []
    texts = [cue.get("text", "") for cue in cues]
    translated = translate_texts(
        texts, settings["target_language"], api_key,
        progress_cb=progress_cb, batch_size=settings["batch_size"])

    mode = settings.get("mode", "bilingual")
    new_cues = []
    for cue, original, target in zip(cues, texts, translated):
        new_cue = {key: value for key, value in cue.items() if key != "words"}
        target = target or ""
        if mode == "replace":
            new_cue["text"] = target.strip() if target.strip() else original
        else:
            if target.strip() and target != original:
                new_cue["text"] = f"{original}\n{target}"
            else:
                new_cue["text"] = original
        new_cues.append(new_cue)
    return new_cues
