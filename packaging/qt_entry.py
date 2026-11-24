# -*- coding: utf-8 -*-
"""
3.0 新介面打包用的進入點（PyInstaller 的入口腳本）。

不用 `main.py`：3.0.0 起它的預設雖然也是新介面，但沒有 PySide6 時會改開一般版，而且從 `main.py` 進來
會把整個一般版（Tk）一起打包進去。這裡直接進 `gui_qt`，自檢模式（`--selftest`）照樣可用。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui_qt.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
