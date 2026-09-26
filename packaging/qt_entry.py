# -*- coding: utf-8 -*-
"""
3.0 預覽版打包用的進入點（PyInstaller 的入口腳本）。

不用 `main.py`：那支的預設是 Tk 版，雙擊 Qt 預覽版的 exe 卻開出 Tk 版會
讓人以為打包錯了；而且從 `main.py` 進來會把整個 Tk 版一起打包進去。這裡
直接進 `gui_qt`，自檢模式（`--selftest`）照樣可用。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui_qt.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
