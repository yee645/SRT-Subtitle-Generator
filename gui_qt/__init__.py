# -*- coding: utf-8 -*-
"""
3.0 預覽版的 Qt（PySide6）介面。

與 `gui/`（Tk 版）並列，兩者都只呼叫 `subtitle/` 核心、共用同一份
`config.json`。Tk 版仍是預設；這裡用 `python main.py --qt` 開。見
`docs/ROADMAP_3.0.md`「遷移策略」與第 1 項。

2.x 的零依賴規則只放掉在這個資料夾：`gui/` 與 `subtitle/` 不得 import
這裡或 PySide6（`tests/test_qt_skeleton.py` 會擋）。
"""
