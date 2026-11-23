# -*- coding: utf-8 -*-
"""
背景查新版本（3.0 第 11 項第三十階段）。查法與提示文字在 `subtitle/updatecheck.py`；提示列在 `gui_qt/app.py`。

會送出去的：向 GitHub API 查最新 Release 的一般連線請求，不含任何檔案、字幕、設定或帳號資訊（`updatecheck.SENDS`）。
"""
import threading

from PySide6.QtCore import QObject, Signal

from subtitle import updatecheck


class UpdateWorker(QObject):
    """背景執行緒跑 `updatecheck.fetch_latest`；查到比目前新的版本發 `finished(info)`，否則發 `finished(None)`。"""

    finished = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False

    def start(self, current):
        if self.busy:
            return False
        self.busy = True
        threading.Thread(target=self._run, args=(current,), daemon=True).start()
        return True

    def _run(self, current):
        info = updatecheck.fetch_latest(current)
        self.busy = False
        self.finished.emit(info)
