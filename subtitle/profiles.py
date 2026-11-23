# -*- coding: utf-8 -*-
"""
習慣設定（樣式組合）與斷句設定的規則（3.0 第 11 項第三十一階段）。

一組習慣設定＝一份字幕樣式（`subtitle_style`）＋一份斷句設定（`segmentation`），存在設定檔的 `presets`，
選用中的名稱在 `active_preset`。一般版的規則寫在 `gui/app.py`（夾限、另存、刪除至少留一組），這裡抽出來給
Qt 版用，規則一樣（測試把邊界一一驗過）：

* `clean_segmentation`：斷句設定的夾限（中文 4～40 字、英文 10～90 字母、最短 0.3 秒起且不超過最長、最長
  不超過 15 秒、停頓 0.2～2 秒、時間軸微調 ±10 秒）；壞掉的值退回原本的。
* `check_new_name`：另存的名字不能空白；已經有的要先問要不要覆蓋。
* `after_delete`：至少要留一組；刪掉之後改用名字排第一的那一組。

`make_profile`、`describe_preset_state` 在 `config.py`（一般版也用），這裡不 import config。

零 GUI 依賴、不 import config。
"""
from __future__ import annotations

SEGMENTATION_DEFAULTS = {
    "max_chars_cjk": 18,
    "max_chars_latin": 45,
    "min_duration": 1.0,
    "max_duration": 7.0,
    "pause_gap": 0.5,
    "time_offset": 0.0,
}

# (鍵, 介面上的名字, 最小, 最大, 一格, 單位)；範圍跟一般版的斷句設定區一樣
SEGMENTATION_FIELDS = (
    ("max_chars_cjk", "中文單行上限", 4, 40, 1, "字"),
    ("max_chars_latin", "英文單行上限", 10, 90, 1, "字母"),
    ("min_duration", "最短秒數", 0.3, 5.0, 0.1, "秒"),
    ("max_duration", "最長秒數", 2.0, 15.0, 0.5, "秒"),
    ("pause_gap", "停頓秒數", 0.2, 2.0, 0.1, "秒"),
    ("time_offset", "時間軸微調", -10.0, 10.0, 0.1, "秒（正值整體延後、負值整體提前）"),
)

EMPTY_NAME = "樣式名稱不可為空白。"
KEEP_ONE = "至少需保留一組習慣設定，無法刪除。"


def _number(value, fallback, kind):
    try:
        return kind(value)
    except (TypeError, ValueError):
        return kind(fallback)


def clean_segmentation(seg, base=None) -> dict:
    """
    斷句設定夾限，規則跟一般版 `_read_segmentation_from_ui` 一樣。

    `base` 是壞掉的值要退回去的那一份（一般版是設定裡原本的值）；沒給就用預設值。其他不認得的鍵原樣留著。
    """
    fallback = dict(SEGMENTATION_DEFAULTS)
    fallback.update({k: v for k, v in (base or {}).items() if k in SEGMENTATION_DEFAULTS})
    seg = dict(seg or {})
    out = dict(seg)
    cjk = _number(seg.get("max_chars_cjk", fallback["max_chars_cjk"]), fallback["max_chars_cjk"], float)
    latin = _number(seg.get("max_chars_latin", fallback["max_chars_latin"]), fallback["max_chars_latin"], float)
    min_dur = _number(seg.get("min_duration", fallback["min_duration"]), fallback["min_duration"], float)
    max_dur = _number(seg.get("max_duration", fallback["max_duration"]), fallback["max_duration"], float)
    pause = _number(seg.get("pause_gap", fallback["pause_gap"]), fallback["pause_gap"], float)
    offset = _number(seg.get("time_offset", fallback["time_offset"]), fallback["time_offset"], float)
    out["max_chars_cjk"] = max(4, min(int(cjk), 40))
    out["max_chars_latin"] = max(10, min(int(latin), 90))
    out["min_duration"] = max(0.3, min(min_dur, max_dur))
    out["max_duration"] = max(out["min_duration"], min(max_dur, 15.0))
    out["pause_gap"] = max(0.2, min(pause, 2.0))
    out["time_offset"] = max(-10.0, min(offset, 10.0))
    return out


def preset_names(presets) -> list:
    """下拉選單的順序：照名字排（跟一般版一樣）。"""
    return sorted((presets or {}).keys())


def check_new_name(name, presets):
    """
    另存新樣式的名字：回傳 (整理過的名字, 錯誤訊息, 是否會覆蓋)。

    錯誤訊息不是空字串就不能存；會覆蓋時要先問使用者。
    """
    name = (name or "").strip()
    if not name:
        return "", EMPTY_NAME, False
    return name, "", name in (presets or {})


def after_delete(presets, name):
    """
    刪掉 `name` 之後要選哪一組：回傳 (新的 presets, 改選的名字, 錯誤訊息)。

    只剩一組時不能刪（錯誤訊息＝KEEP_ONE，presets 原樣）；沒有這組也原樣回傳、錯誤訊息空、改選的名字是 None。
    """
    presets = dict(presets or {})
    if name not in presets:
        return presets, None, ""
    if len(presets) <= 1:
        return presets, None, KEEP_ONE
    del presets[name]
    return presets, preset_names(presets)[0], ""
