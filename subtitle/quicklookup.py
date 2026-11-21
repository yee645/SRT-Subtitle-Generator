# -*- coding: utf-8 -*-
"""
即時查譯面板兩版共用的純邏輯（3.0 第 11 項第二十三階段，從 `gui/quicktranslate_panel.py` 抽出來）。

一般版的即時查譯面板把「生字本怎麼存」「選到的字為什麼略過」這些不碰畫面的邏輯寫在 Tk 檔裡；
Qt 版要一樣的行為，抽到這裡兩邊共用，一般版改成從這裡 import（名稱、行為、文字都不變）。

- 生字本：載入、存檔、去重合併、刪除、匯出 CSV。檔案格式不變（JSON 清單，每筆 word／meaning），
  兩版讀寫同一個檔。路徑由呼叫端給（核心不 import config）。
- 略過原因：`looks_translatable()` 說不送的時候，該講哪一句（太長／已經是中文／太短或沒有字）。
- 譯文區塊的標題（目標語言是中文時叫「中文翻譯」）。

零 GUI 依賴。
"""

from __future__ import annotations

import csv
import json
import logging

from subtitle.punctstyle import cjk_ratio
from subtitle.translator import LANGUAGE_LABELS

logger = logging.getLogger(__name__)

VOCAB_FILENAME = "quicktranslate_vocab.json"  # 放在 config.json 旁邊（本機保存，不進 git）

_CHINESE_CODES = ("zh-TW", "zh-CN")

C15_ALREADY_CHINESE = "已略過：選取內容已是中文。"
C16_TOO_SHORT_OR_EMPTY = "已略過：選取內容太短或沒有可翻的文字。"
C22_VOCAB_EMPTY = "生字本還是空的。查譯幾句附關鍵詞的外文，就會自動收詞進來。"


def C14_TOO_LONG(max_chars: int) -> str:
    return (f"已略過：選取超過 {max_chars} 字"
            "（快速查譯是查詞句用的，整批翻譯請用「翻譯字幕」）。")


def C20_EXPORTED(n: int, path: str) -> str:
    return f"已匯出 {n} 個詞到 {path}。"


def vocab_status_text(n: int) -> str:
    return f"生字本共 {n} 個詞。" if n else C22_VOCAB_EMPTY


def dst_label(target_language: str) -> str:
    """『中文翻譯』區塊標題：目標語言非中文時動態換成「◯◯翻譯」。"""
    if target_language in _CHINESE_CODES:
        return "中文翻譯"
    return f"{LANGUAGE_LABELS.get(target_language, target_language)}翻譯"


def classify_skip_reason(source: str, settings: dict) -> str:
    """
    `looks_translatable()` 回傳 False 時，判斷該顯示哪一句略過訊息。

    只在已知 `not looks_translatable(source, settings)` 的前提下呼叫；判斷順序與 `looks_translatable`
    內部一致（太長 → 已是中文 → 其餘歸類為「太短或沒有可翻的文字」，涵蓋太短與純數字／純標點兩種情況）。
    """
    length = len(source)
    if length > settings["max_chars"]:
        return C14_TOO_LONG(settings["max_chars"])
    target = settings.get("target_language", "")
    if (length >= settings["min_chars"] and target.startswith("zh")
            and cjk_ratio(source) >= 0.15):
        return C15_ALREADY_CHINESE
    return C16_TOO_SHORT_OR_EMPTY


# ---------------------------------------------------------------------------
# 生字本

def load_vocab(path: str) -> list:
    """讀取生字本 JSON；檔案不存在或壞掉一律回傳空清單，不丟例外。"""
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [dict(word=str(row["word"]), meaning=str(row["meaning"]))
            for row in data
            if isinstance(row, dict) and row.get("word") and row.get("meaning")]


def save_vocab(vocab: list, path: str) -> bool:
    """存生字本；存不進去只記警告、回傳 False（查譯本身不該因為存檔失敗而中斷）。"""
    try:
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(vocab, fp, ensure_ascii=False, indent=2)
    except OSError:
        logger.warning("生字本存檔失敗：%s", path)
        return False
    return True


def add_vocab_terms(vocab: list, terms: list) -> tuple:
    """
    把關鍵詞併入生字本，回傳 `(新清單, 是否有變動)`。

    同一個詞（完全相同字串）只留第一次查到的意思，避免使用者反覆查同一個詞時生字本被灌成一長串重複列。
    """
    existing = {row["word"] for row in vocab}
    merged = list(vocab)
    changed = False
    for term in terms or []:
        word = str(term.get("word") or "").strip()
        meaning = str(term.get("meaning") or "").strip()
        if not word or not meaning or word in existing:
            continue
        merged.append({"word": word, "meaning": meaning})
        existing.add(word)
        changed = True
    return merged, changed


def remove_vocab_words(vocab: list, words) -> list:
    """回傳移除指定詞句之後的生字本清單（`words` 為要刪除的詞句集合）。"""
    drop = set(words)
    return [row for row in vocab if row["word"] not in drop]


def write_vocab_csv(vocab: list, path: str) -> None:
    """匯出生字本 CSV（UTF-8 BOM，Excel 與 Anki 皆可直接匯入）。"""
    with open(path, "w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(["詞句", "意思"])
        for row in vocab:
            writer.writerow([row["word"], row["meaning"]])
