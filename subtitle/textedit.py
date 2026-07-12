# -*- coding: utf-8 -*-
"""
字幕文字批次編輯：尋找與取代。

自動字幕最花時間的是校對——同一個錯字（人名、產品名、同音錯字）
往往整集重複出現，逐句修改效率極差。本模組提供跨字幕的尋找與取代，
供 GUI 對話框使用；比對為字面文字（不支援萬用字元），可選擇是否
區分大小寫（中日韓文字不受大小寫影響）。

本模組不依賴任何 GUI 元件，可獨立測試。
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping

# 自動修正規則清單的上限（防呆，避免設定檔異常膨脹拖慢生成）。
MAX_CORRECTION_RULES = 200


def _build_pattern(term: str, case_sensitive: bool) -> re.Pattern:
    """把字面搜尋字串編成正則（跳脫特殊字元；預設不分大小寫）。"""
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(re.escape(term), flags)


def find_in_cues(cues: Iterable[Mapping], term: str,
                 case_sensitive: bool = False) -> list:
    """
    回傳文字包含搜尋字串的 cue 索引清單（依原順序）。

    搜尋字串為空白時回傳空清單。
    """
    term = term or ""
    if not term:
        return []
    pattern = _build_pattern(term, case_sensitive)
    return [index for index, cue in enumerate(cues)
            if pattern.search(cue.get("text") or "")]


def count_occurrences(cues: Iterable[Mapping], term: str,
                      case_sensitive: bool = False) -> int:
    """回傳搜尋字串在所有字幕文字中出現的總次數。"""
    if not term:
        return 0
    pattern = _build_pattern(term, case_sensitive)
    return sum(len(pattern.findall(cue.get("text") or "")) for cue in cues)


def replace_in_cues(cues: list, term: str, replacement: str,
                    case_sensitive: bool = False,
                    only_indices: Iterable[int] | None = None) -> tuple:
    """
    在字幕清單中把搜尋字串全部換成取代文字。

    參數：
        cues: cue 清單（不會被修改；回傳的是新清單）。
        term: 要尋找的字面文字（空字串不做任何事）。
        replacement: 取代後的文字（可為空字串＝刪除該詞）。
        case_sensitive: 是否區分大小寫（僅影響拉丁字母）。
        only_indices: 僅在這些索引的 cue 內取代；None＝全部。
    回傳：
        (新的 cue 清單, 實際取代的次數)。未命中的 cue 沿用原 dict，
        命中的 cue 為淺複製並更新 text，其餘欄位（時間軸等）不變。
    """
    term = term or ""
    if not term:
        return list(cues), 0
    pattern = _build_pattern(term, case_sensitive)
    allowed = set(only_indices) if only_indices is not None else None
    # re.sub 的取代字串會解讀 \g<...> 等跳脫序列，字面取代需先跳脫。
    literal = replacement.replace("\\", "\\\\")

    result = []
    total = 0
    for index, cue in enumerate(cues):
        text = cue.get("text") or ""
        if (allowed is None or index in allowed) and pattern.search(text):
            new_text, count = pattern.subn(literal, text)
            updated = dict(cue)
            updated["text"] = new_text
            # 逐字時間軸同步取代（逐字動態字幕以 words 組字）。
            # 跨字詞的比對（如「厲害」分屬兩個字）無法在單字層命中；
            # 同步不完整時直接移除逐字資料，讓該句退回整句顯示，
            # 確保動態字幕不會出現取代前的舊字。
            if cue.get("words"):
                word_hits = 0
                new_words = []
                for word in cue["words"]:
                    replaced, hits = pattern.subn(literal, word["word"])
                    word_hits += hits
                    new_words.append(dict(word, word=replaced))
                if word_hits == count:
                    updated["words"] = new_words
                else:
                    updated.pop("words", None)
            result.append(updated)
            total += count
        else:
            result.append(cue)
    return result, total


# ---------------------------------------------------------------------------
# 自動修正詞庫：把取代規則記下來，之後每次轉錄完自動套用
# ---------------------------------------------------------------------------

def normalize_correction_rules(raw) -> list:
    """
    整理設定檔中的自動修正規則清單，回傳乾淨的
    [{"find": str, "replace": str, "case": bool}, ...]。

    去除空 find、重複 find（保留最後一筆＝最新設定），數量設上限。
    """
    rules = {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, Mapping):
            continue
        find = str(item.get("find") or "").strip()
        if not find:
            continue
        rules[find] = {
            "find": find,
            "replace": str(item.get("replace") or ""),
            "case": bool(item.get("case")),
        }
    return list(rules.values())[:MAX_CORRECTION_RULES]


def apply_corrections(cues: list, rules) -> tuple:
    """
    依序套用自動修正規則（語音辨識的慣性錯字：人名、產品名、同音字），
    回傳 (新的 cue 清單, 總取代次數)。

    規則由 normalize_correction_rules 整理；轉錄完成後自動呼叫，
    使用者修過一次的錯字之後每一集都自動修正。
    """
    total = 0
    for rule in normalize_correction_rules(rules):
        cues, count = replace_in_cues(
            cues, rule["find"], rule["replace"], rule["case"])
        total += count
    return cues, total
