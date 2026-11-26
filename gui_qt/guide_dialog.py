# -*- coding: utf-8 -*-
"""
新介面導覽（3.0 第 11 項第三十五階段，第 19 列（五））：一般版「新版介面速覽」（`gui/whatsnew_dialog.py`）的 Qt 版。

內容與「該不該跳」的規則在 `subtitle/qtguide.py`。這裡只是視窗：

* 第一次打開 Qt 版（`main()` 開好主視窗之後）跳一次；測試建的視窗、自檢模式不跳。
* 一段可以捲的純文字＋「不再顯示這個導覽」＋〔開始使用〕。關掉（按鈕、右上角的 ×、Esc）時把選擇回報給主視窗，
  主視窗寫進這次開啟的設定 `qt_guide_seen`（關掉 Qt 版時存）。
* 狀態列右邊〔新介面導覽…〕隨時可以再打開（這時勾不勾都照樣記）。
* 不擋住主視窗：邊看邊點得到它講的按鈕。
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout

from subtitle import qtguide
from updater import APP_VERSION


class GuideDialog(QDialog):
    """新介面導覽。關掉時送出 closedWith(勾了「不再顯示」沒有)。"""

    closedWith = Signal(bool)

    def __init__(self, parent=None, body=None, title=None):
        """body／title 不給＝四頁籤的新介面導覽；剪輯器版面給自己的介紹（subtitle/editorguide.py，E-7b）。"""
        super().__init__(parent)
        self.setModal(False)
        self.setWindowTitle(title or "新介面導覽")
        self.body = QPlainTextEdit()
        self.body.setReadOnly(True)
        self.body.setPlainText(qtguide.body_text(APP_VERSION) if body is None else body)
        self.never_box = QCheckBox("不再顯示這個導覽")
        self.start_btn = QPushButton("開始使用")
        self.start_btn.setDefault(True)
        row = QHBoxLayout()
        row.addWidget(self.never_box)
        row.addStretch(1)
        row.addWidget(self.start_btn)
        layout = QVBoxLayout(self)
        layout.addWidget(self.body, 1)
        layout.addLayout(row)
        self.resize(720, 620)
        self.setMinimumSize(600, 480)
        self.start_btn.clicked.connect(self.accept)
        # 按鈕（accept）、×（QDialog 的 closeEvent 會 reject）、Esc（reject）都走 finished，各一次；
        # 只接 closeEvent 的話 Esc 關掉不會記
        self.finished.connect(lambda _result: self.closedWith.emit(self.never_box.isChecked()))

    def showEvent(self, event):  # noqa: N802 —— Qt 的命名
        self.body.verticalScrollBar().setValue(0)  # 每次從頭看
        super().showEvent(event)
