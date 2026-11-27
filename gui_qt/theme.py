# -*- coding: utf-8 -*-
"""
剪輯器版面（E 系列）的外觀：照 `subtitle/designtokens.py` 的色票產生調色盤與樣式表。

樣式表只套在 `EditorWindow` 上（連同它開出來的小視窗），四頁籤的舊視窗照舊用 `gui_qt.app.apply_theme`。
調色盤要整個程式換（時間軸、清單這些自己畫的元件照調色盤取色），所以兩個都要給。
"""
import os
import tempfile

from PySide6.QtGui import QColor, QPalette

from subtitle.designtokens import FONT_PX, RADIUS, TOKENS

_ASSET_DIR = None


def tokens(theme):
    return TOKENS[theme if theme in TOKENS else "light"]


def palette(theme):
    """照色票做的調色盤（Fusion 用）。"""
    t = tokens(theme)
    c = {k: QColor(v) for k, v in t.items()}
    pal = QPalette()
    for role, color in (
        (QPalette.Window, c["bg.panel"]), (QPalette.WindowText, c["text.primary"]),
        (QPalette.Base, c["bg.raised"]), (QPalette.AlternateBase, c["bg.panel"]),
        (QPalette.ToolTipBase, c["bg.raised"]), (QPalette.ToolTipText, c["text.primary"]),
        (QPalette.Text, c["text.primary"]), (QPalette.Button, c["bg.raised"]),
        (QPalette.ButtonText, c["text.primary"]), (QPalette.BrightText, c["danger"]),
        (QPalette.Link, c["accent"]), (QPalette.Highlight, c["accent"]),
        (QPalette.HighlightedText, c["accent.text"]), (QPalette.PlaceholderText, c["text.muted"]),
        (QPalette.Light, c["bg.hover"]), (QPalette.Midlight, c["bg.hover"]),
        (QPalette.Mid, c["border"]), (QPalette.Dark, c["bg.window"]), (QPalette.Shadow, c["bg.window"]),
    ):
        pal.setColor(role, color)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, c["text.muted"])
    return pal


def assets(theme):
    """
    樣式表要用的小圖（下拉箭頭、勾勾）：照主題的顏色畫成 PNG，放在這次執行的暫存資料夾（樣式表只能用檔案路徑）。
    回傳 {名稱: 路徑}，路徑一律用正斜線（Windows 的反斜線在樣式表裡會被當成跳脫字元）。
    """
    global _ASSET_DIR
    from gui_qt import icons

    if _ASSET_DIR is None or not os.path.isdir(_ASSET_DIR):
        _ASSET_DIR = tempfile.mkdtemp(prefix="srtgen_theme_")
    t = tokens(theme)
    out = {}
    for name, icon_name, color in (("down", "chevron_down", t["text.secondary"]),
                                   ("up", "chevron_up", t["text.secondary"]),
                                   ("check", "check", t["accent.text"])):
        path = os.path.join(_ASSET_DIR, f"{theme}_{name}.png")
        if not os.path.exists(path):
            icons.pixmap(icon_name, color, 32).save(path, "PNG")
        out[name] = path.replace(os.sep, "/")
    return out


def stylesheet(theme):
    """整個剪輯器視窗的樣式表。"""
    t = tokens(theme)
    a = assets(theme)
    r, rp = RADIUS["control"], RADIUS["panel"]
    return f"""
QMainWindow, #editorRoot {{ background: {t['bg.window']}; }}
QWidget {{ color: {t['text.primary']}; font-size: {FONT_PX['ui']}px; }}
QToolTip {{ background: {t['bg.raised']}; color: {t['text.primary']}; border: 1px solid {t['border']};
            padding: 4px 6px; border-radius: 4px; }}

#topBar {{ background: {t['bg.panel']}; border-bottom: 1px solid {t['border']}; }}
#appName {{ font-weight: 600; font-size: 14px; }}
#projectName {{ color: {t['text.secondary']}; }}
#panel, #leftPanel, #inspector, #previewPanel, #timelinePanel {{ background: {t['bg.panel']}; border-radius: {rp}px; }}
#rail {{ background: {t['bg.panel']}; border-radius: {rp}px; }}
#panelTitle {{ font-weight: 600; font-size: {FONT_PX['title']}px; padding: 2px 0; }}
#sectionTitle {{ color: {t['text.secondary']}; font-size: {FONT_PX['small']}px; font-weight: 600;
                 padding-top: 6px; }}
QLabel[secondary="true"] {{ color: {t['text.secondary']}; font-size: {FONT_PX['small']}px; }}
#timecode {{ font-family: "Consolas", "Menlo", "DejaVu Sans Mono", monospace; font-size: {FONT_PX['timecode']}px;
             color: {t['text.primary']}; }}
#previewView {{ background: {t['preview.bg']}; border-radius: {rp}px; }}

QPushButton {{ background: {t['bg.raised']}; border: 1px solid {t['border']}; border-radius: {r}px;
               padding: 5px 10px; color: {t['text.primary']}; }}
QPushButton:hover {{ background: {t['bg.hover']}; }}
QPushButton:pressed {{ background: {t['border']}; }}
QPushButton:disabled {{ color: {t['text.muted']}; background: {t['bg.panel']}; }}
QPushButton:checked {{ background: {t['accent.soft']}; border-color: {t['accent']}; }}
QPushButton[role="primary"] {{ background: {t['accent']}; color: {t['accent.text']}; border: none;
                               font-weight: 600; padding: 6px 18px; }}
QPushButton[role="primary"]:hover {{ background: {t['accent.hover']}; }}
QPushButton[role="list"] {{ text-align: left; padding: 7px 10px; }}
QPushButton[role="ghost"] {{ background: transparent; border: 1px solid transparent; }}
QPushButton[role="ghost"]:hover {{ background: {t['bg.hover']}; }}
QPushButton[role="ghost"]:disabled {{ background: transparent; }}

QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: {r}px; padding: 4px;
               color: {t['text.primary']}; }}
QToolButton:hover {{ background: {t['bg.hover']}; }}
QToolButton:checked {{ background: {t['accent.soft']}; }}
QToolButton:disabled {{ color: {t['text.muted']}; }}
QToolButton[role="rail"] {{ color: {t['text.secondary']}; font-size: 11px; padding: 6px 2px; }}
QToolButton[role="rail"]:checked {{ color: {t['accent']}; background: {t['accent.soft']}; }}
QToolButton[role="play"] {{ background: {t['accent']}; border-radius: 18px; }}
QToolButton[role="play"]:hover {{ background: {t['accent.hover']}; }}
QToolButton[role="play"]:disabled {{ background: {t['bg.raised']}; }}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {t['bg.raised']}; border: 1px solid {t['border']}; border-radius: {r}px; padding: 3px 6px;
    selection-background-color: {t['accent']}; selection-color: {t['accent.text']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus,
QDoubleSpinBox:focus {{ border-color: {t['accent']}; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 22px; border: none; }}
QComboBox::down-arrow {{ image: url("{a['down']}"); width: 10px; height: 10px; }}
QSpinBox, QDoubleSpinBox {{ padding-right: 18px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right;
    width: 18px; border: none; background: transparent; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;
    width: 18px; border: none; background: transparent; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::down-button:hover {{ background: {t['bg.hover']}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{a['up']}"); width: 8px; height: 8px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{a['down']}"); width: 8px; height: 8px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {t['text.muted']}; border-radius: 3px;
                        background: {t['bg.raised']}; }}
QCheckBox::indicator:hover {{ border-color: {t['accent']}; }}
QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; image: url("{a['check']}"); }}
QCheckBox::indicator:disabled {{ border-color: {t['border']}; background: {t['bg.panel']}; }}
QCheckBox::indicator:checked:disabled {{ background: {t['text.muted']}; border-color: {t['text.muted']}; }}
#vsep {{ background: {t['border']}; }}
QComboBox QAbstractItemView {{ background: {t['bg.raised']}; border: 1px solid {t['border']};
                               selection-background-color: {t['accent.soft']}; selection-color: {t['text.primary']}; }}

QListView, QListWidget, QTreeView, QTreeWidget, QTableView, QTableWidget {{
    background: {t['bg.panel']}; alternate-background-color: {t['bg.raised']}; border: 1px solid {t['border']};
    border-radius: {r}px; selection-background-color: {t['accent.soft']}; selection-color: {t['text.primary']}; }}
/* 匯出視窗左邊的目錄（E-5） */
QListWidget#exportNav {{ background: {t['bg.panel']}; border: none; border-right: 1px solid {t['border']};
                         border-radius: 0; padding: 12px 8px; }}
QListWidget#exportNav::item {{ color: {t['text.secondary']}; padding: 8px 10px; border-radius: {r}px; }}
QListWidget#exportNav::item:hover {{ background: {t['bg.hover']}; }}
QListWidget#exportNav::item:selected {{ background: {t['accent.soft']}; color: {t['text.primary']}; }}
QHeaderView::section {{ background: {t['bg.raised']}; color: {t['text.secondary']}; border: none;
                        border-bottom: 1px solid {t['border']}; padding: 4px 6px; }}
QTableCornerButton::section {{ background: {t['bg.raised']}; border: none; }}

QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {t['border']}; border-radius: 4px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {t['text.muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QSplitter::handle {{ background: {t['bg.window']}; }}
QSplitter::handle:hover {{ background: {t['accent']}; }}

QSlider::groove:horizontal {{ height: 4px; background: {t['border']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {t['text.primary']}; width: 12px; height: 12px; margin: -4px 0;
                              border-radius: 6px; }}
QSlider::handle:horizontal:disabled {{ background: {t['text.muted']}; }}
QSlider::sub-page:horizontal:disabled {{ background: {t['text.muted']}; }}
/* 停用的樣子（E-9a）：字變淡、輸入框退到面板底色，一看就知道現在不能調 */
QLabel:disabled, QCheckBox:disabled, QRadioButton:disabled {{ color: {t['text.muted']}; }}
QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled {{ color: {t['text.muted']}; background: {t['bg.panel']}; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {t['text.secondary']}; padding: 6px 12px;
                border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {t['text.primary']}; border-bottom-color: {t['accent']}; }}
QTabBar::tab:hover {{ color: {t['text.primary']}; }}
QGroupBox {{ border: 1px solid {t['border']}; border-radius: {r}px; margin-top: 14px; padding-top: 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {t['text.secondary']}; }}
QProgressBar {{ background: {t['bg.raised']}; border: 1px solid {t['border']}; border-radius: {r}px;
                text-align: center; height: 14px; }}
QProgressBar::chunk {{ background: {t['accent']}; border-radius: {r}px; }}
QStatusBar {{ background: {t['bg.panel']}; color: {t['text.secondary']}; border-top: 1px solid {t['border']}; }}
QStatusBar::item {{ border: none; }}
QMenu {{ background: {t['bg.raised']}; border: 1px solid {t['border']}; padding: 4px; }}
QMenu::item {{ padding: 5px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {t['accent.soft']}; }}
#ffmpegBanner, #updateBanner {{ background: {t['warning.bg']}; }}
#ffmpegBanner QLabel, #updateBanner QLabel {{ color: {t['warning']}; }}
"""
