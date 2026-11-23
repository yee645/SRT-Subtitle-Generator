# -*- coding: utf-8 -*-
"""
自動修正詞庫的增刪規則（3.0 第 11 項第三十三階段）。

一般版「尋找取代」視窗下面的「自動修正詞庫（每次生成字幕後自動套用）」：〔把目前取代存為規則〕〔刪除選取規則〕。
套用本身在 `subtitle/textedit.apply_corrections`（生成字幕時 `pipeline.generate_cues` 自動做，兩版共用），清單整理在
`textedit.normalize_correction_rules`。這裡只放「存一條、刪一條、清單上怎麼寫」，Qt 版用；一般版不改。

跟一般版一樣：同一個「尋找」再存一次＝換掉舊的那條，移到最後；「換成」可以留空（＝刪掉那幾個字）。
比一般版多一個檢查：詞庫滿了（`MAX_CORRECTION_RULES` 條）不再加——一般版會照樣加進去，但下次讀設定時整理清單
會把最新的那條截掉，等於沒存，使用者看不出來。

零 GUI 依賴、不 import config。
"""
from __future__ import annotations

from .textedit import MAX_CORRECTION_RULES, normalize_correction_rules

NEED_FIND = "請先填入「尋找」欄位。"
NEED_SELECTION = "請先在清單中選取要刪除的規則。"
FULL = f"自動修正詞庫已經有 {MAX_CORRECTION_RULES} 條（上限），請先刪掉用不到的再存。"


def rule_label(rule) -> str:
    """清單上一條規則的寫法（同一般版）：「錯字 → 正確字（區分大小寫）」，換成空白寫（刪除）。"""
    case = "（區分大小寫）" if rule.get("case") else ""
    target = rule.get("replace") if rule.get("replace") else "（刪除）"
    return f"{rule.get('find')} → {target}{case}"


def save_rule(rules, find, replace, case):
    """
    把一組取代存成規則：回傳 (新的規則清單, 錯誤訊息)。

    「尋找」去頭尾空白後不能是空的；同一個「尋找」的舊規則拿掉、新的放最後；詞庫滿了（而且不是換掉舊的）不加。
    錯誤時規則清單原樣（整理過）回傳。
    """
    current = normalize_correction_rules(rules)
    find = str(find or "").strip()
    if not find:
        return current, NEED_FIND
    kept = [r for r in current if r["find"] != find]
    if len(kept) >= MAX_CORRECTION_RULES:
        return current, FULL
    kept.append({"find": find, "replace": str(replace or ""), "case": bool(case)})
    return kept, ""


def delete_rule(rules, index):
    """刪掉第 index 條（清單上的順序）：回傳 (新的規則清單, 錯誤訊息)。沒選或超出範圍＝NEED_SELECTION。"""
    current = normalize_correction_rules(rules)
    if index is None or not 0 <= int(index) < len(current):
        return current, NEED_SELECTION
    return current[:int(index)] + current[int(index) + 1:], ""
