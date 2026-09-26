# -*- coding: utf-8 -*-
"""
3.0 預覽版主視窗（第 1 項第一階段：骨架）。

這一階段只立地基：主視窗、四個階段頁籤、狀態列、深淺主題。頁籤裡先放
「這一頁還在 Tk 版」的說明，之後每搬一頁就換掉一頁（見
`docs/ROADMAP_3.0.md` 第 1、11 項）。

**頁籤名稱與 Tk 版一字不差**：2.x 花了好幾版讓使用者記住「① 素材與剪輯
→ ② 字幕 → ③ 健檢中心 → ④ 輸出與發佈」，換工具包不是重新命名的理由。
測試會拿 `gui/app.py` 的原始碼比對。

設定只讀不寫：骨架沒有任何值要存，貿然寫回可能蓋掉 Tk 版同時開著時改
的東西。要寫的那一天再處理兩邊同時開的問題。
"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QTabWidget, QVBoxLayout, QWidget,
)

import config
from updater import APP_VERSION

# (頁籤名稱, 還沒搬過來時頁面上的說明)。名稱必須與 gui/app.py 的
# notebook.add(..., text=...) 相同。
STAGES = [
    ("① 素材與剪輯", "選影片、剪停頓、剪重複片段、審片、匯入既有字幕。"),
    ("② 字幕", "生成字幕、逐句校對、翻譯、樣式。"),
    ("③ 健檢中心", "上架前的 18 項檢查與一鍵修復。"),
    ("④ 輸出與發佈", "匯出、燒錄、發佈資料、成品加工。"),
]

WINDOW_TITLE = f"SRT 字幕生成器 3.0 預覽版（v{APP_VERSION}）"

# 與 Tk 版的預設視窗同一個量級；之後放進時間軸時再依實測調整。
DEFAULT_SIZE = (1280, 800)

NOT_YET_TEXT = (
    "這一頁還沒搬到 3.0 預覽版。\n\n"
    "現在要用這些功能，請開一般版（直接執行程式、不加 --qt）：\n"
    "兩個版本讀同一份設定檔，做到一半可以換過去接著做。"
)


def theme_scheme(theme):
    """config 的 theme 字串 → Qt 的色彩配置。不認得的值一律當淺色（同 Tk 版）。"""
    return Qt.ColorScheme.Dark if theme == "dark" else Qt.ColorScheme.Light


def dark_palette():
    """Fusion 樣式用的深色調色盤（顏色取自 Qt 官方範例的常見深色配置）。"""
    base, window, text = QColor(35, 35, 35), QColor(53, 53, 53), QColor(230, 230, 230)
    disabled = QColor(127, 127, 127)
    pal = QPalette()
    for role, color in (
        (QPalette.Window, window), (QPalette.WindowText, text),
        (QPalette.Base, base), (QPalette.AlternateBase, window),
        (QPalette.ToolTipBase, window), (QPalette.ToolTipText, text),
        (QPalette.Text, text), (QPalette.Button, window),
        (QPalette.ButtonText, text), (QPalette.BrightText, QColor(255, 80, 80)),
        (QPalette.Link, QColor(90, 160, 240)),
        (QPalette.Highlight, QColor(42, 130, 218)),
        (QPalette.HighlightedText, QColor(255, 255, 255)),
        (QPalette.PlaceholderText, disabled),
    ):
        pal.setColor(role, color)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, disabled)
    return pal


def apply_theme(app, theme):
    """
    套用深淺主題。

    Fusion 樣式＋**明確的調色盤**。只呼叫 `setColorScheme` 不夠：它要平台
    的主題外掛配合，offscreen 平台上實測完全不變（深色設定下底色亮度還是
    239），Windows 原生樣式在某些版本也不跟。自己給調色盤，三個平台結果
    一樣。
    """
    app.setStyle("Fusion")
    scheme = theme_scheme(theme)
    app.styleHints().setColorScheme(scheme)
    app.setPalette(dark_palette() if scheme == Qt.ColorScheme.Dark
                   else app.style().standardPalette())


def _placeholder_page(summary):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(24, 24, 24, 24)
    title = QLabel(summary)
    title.setWordWrap(True)
    body = QLabel(NOT_YET_TEXT)
    body.setWordWrap(True)
    layout.addWidget(title)
    layout.addWidget(body)
    layout.addStretch(1)
    return page


class MainWindow(QMainWindow):
    """3.0 預覽版主視窗。"""

    def __init__(self, config_data=None):
        super().__init__()
        self.config_data = config_data if config_data is not None else config.load_config()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(*DEFAULT_SIZE)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        for name, summary in STAGES:
            self.tabs.addTab(_placeholder_page(summary), name)
        self.setCentralWidget(self.tabs)
        self.statusBar().showMessage(
            "3.0 預覽版：目前只有外框，功能請先用一般版。")


def main(argv=None):
    """建立並執行 Qt 版。回傳事件迴圈的結束碼。"""
    argv = list(sys.argv if argv is None else argv)
    app = QApplication.instance() or QApplication(argv[:1])
    data = config.load_config()
    apply_theme(app, data.get("theme", "light"))
    win = MainWindow(data)
    win.show()
    return app.exec()
