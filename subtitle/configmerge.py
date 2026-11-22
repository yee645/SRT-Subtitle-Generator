# -*- coding: utf-8 -*-
"""
Qt 版存設定時的「只寫自己改過的區塊」（3.0 第 11 項第二十八階段）。

一般版（Tk）與 Qt 版共用同一個 config.json，而且可以同時開著。Qt 版一開就把整份設定讀進記憶體；如果關掉時把
記憶體裡那整份直接寫回去，一般版在這段期間存的東西（例如換了習慣設定、改了翻譯語言）就會被 Qt 開啟當下的舊值
蓋掉。所以存檔時做三方合併，以**最上層的區塊**為單位（`subtitle_style`、`automation`、`seriescheck`…）：

- 這次開啟期間 Qt 沒動過的區塊：用磁碟上現在的（一般版剛存的就留著）；
- Qt 動過的區塊：用 Qt 的；
- Qt 拿掉的區塊：從磁碟上拿掉（目前沒有這種情況，照規則處理）。

同一個區塊兩邊都改了的話 Qt 的勝出（後存的算數）——跟一般版自己兩個視窗先後存的結果一樣。

零 GUI 依賴、不 import `config`：讀檔、寫檔由呼叫端做，這裡只算要寫什麼。
"""
from __future__ import annotations

import copy

_MISSING = object()


def changed_sections(base: dict, current: dict) -> list:
    """`current` 跟開啟當下的 `base` 比，哪些最上層的區塊不一樣（新增、改過、拿掉都算），照名稱排序。"""
    base = base or {}
    current = current or {}
    keys = set(base) | set(current)
    return sorted(k for k in keys if base.get(k, _MISSING) != current.get(k, _MISSING))


def merge_for_save(disk: dict, base: dict, current: dict) -> dict:
    """
    要寫回去的設定：以磁碟上現在的 `disk` 為底，只換上 `current` 相對 `base` 改過的區塊。

    回傳新的 dict（深拷貝，不動三個輸入）。
    """
    merged = copy.deepcopy(disk or {})
    current = current or {}
    for key in changed_sections(base, current):
        if key in current:
            merged[key] = copy.deepcopy(current[key])
        else:
            merged.pop(key, None)
    return merged
