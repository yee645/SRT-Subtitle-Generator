# -*- coding: utf-8 -*-
"""
3.0 的新介面（Qt／PySide6）。

與 `gui/`（一般版，Tk）並列，兩者都只呼叫 `subtitle/` 核心。3.0.0 起 `python main.py` 預設開這裡
（沒有 PySide6 就開一般版，`--tk` 指名一般版）；打包版的入口是 `packaging/qt_entry.py`。見
`docs/ROADMAP_3.0.md`「遷移策略」與第 12 項。

2.x 的零依賴規則只放掉在這個資料夾：`gui/` 與 `subtitle/` 不得 import
這裡或 PySide6（`tests/test_qt_skeleton.py` 會擋）。
"""
