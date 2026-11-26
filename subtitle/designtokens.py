# -*- coding: utf-8 -*-
"""
剪輯器版面改版（E 系列）的設計基準：色票、間距、圓角、字級，以及對比度的算法。

只放資料與純計算（零 GUI 依賴、不 import config），新介面的樣式表（`gui_qt/theme.py`）照這裡的名稱取色，
測試也拿這裡的對比度算法檢查每一組「字 × 底」。規格與每個顏色的用途寫在 `docs/ROADMAP_EDITOR.md` 第三節。
"""

THEMES = ("dark", "light")

# 同一組名稱、兩套顏色；程式只用名稱。
TOKENS = {
    "dark": {
        "bg.window": "#141519",
        "bg.panel": "#1d1e23",
        "bg.raised": "#272930",
        "bg.hover": "#30333b",
        "border": "#2f3138",
        "text.primary": "#e9eaee",
        "text.secondary": "#a3a7b0",
        "text.muted": "#6c707a",
        "accent": "#20b6c4",
        "accent.hover": "#3cc6d3",
        "accent.text": "#0b1416",
        "accent.soft": "#173a3f",
        "danger": "#e5534b",
        "warning": "#d9a441",
        "warning.bg": "#3a2f18",
        "track.subtitle": "#c9902f",
        "track.video": "#3f72b0",
        "track.audio": "#3a9a72",
        "track.overlay": "#8a67cc",
        "track.cut": "#d9534f",
        "preview.bg": "#000000",
    },
    "light": {
        "bg.window": "#e6e8ec",
        "bg.panel": "#ffffff",
        "bg.raised": "#f2f3f5",
        "bg.hover": "#e4e6ea",
        "border": "#d4d7dd",
        "text.primary": "#1c1e22",
        "text.secondary": "#555a63",
        "text.muted": "#9298a2",
        "accent": "#0a7f8b",
        "accent.hover": "#086f79",
        "accent.text": "#ffffff",
        "accent.soft": "#d6eff1",
        "danger": "#c9372f",
        "warning": "#8a5a00",
        "warning.bg": "#fdf3d7",
        "track.subtitle": "#d9a03c",
        "track.video": "#5b8fd0",
        "track.audio": "#4fb08a",
        "track.overlay": "#9f80dd",
        "track.cut": "#e06a66",
        "preview.bg": "#0f1012",
    },
}

SPACING = (4, 8, 12, 16, 24)
PANEL_PADDING = 12
PANEL_GAP = 2          # 面板之間的縫，露出 bg.window
RADIUS = {"control": 6, "panel": 8, "clip": 4}
FONT_PX = {"ui": 13, "small": 12, "title": 13, "timecode": 14}

# 需要 ≥ 4.5:1 的「字 × 底」組合（WCAG AA 一般字級）。text.muted 只用在停用與提示，不在這裡。
TEXT_PAIRS = (
    ("text.primary", "bg.window"), ("text.primary", "bg.panel"), ("text.primary", "bg.raised"),
    ("text.primary", "bg.hover"),
    ("text.secondary", "bg.panel"), ("text.secondary", "bg.raised"),
    ("accent.text", "accent"), ("accent.text", "accent.hover"),
    ("warning", "warning.bg"),
)
MIN_CONTRAST = 4.5


def token(theme, name):
    """取一個顏色；不認得的主題當淺色（同 `gui_qt.app.theme_scheme`），不認得的名稱丟 KeyError。"""
    return TOKENS[theme if theme in TOKENS else "light"][name]


def _channel(c):
    c /= 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color):
    """WCAG 2.x 的相對亮度（0＝黑、1＝白）。"""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"不是 #rrggbb：{hex_color!r}")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(fg, bg):
    """WCAG 對比度（1～21）。"""
    a, b = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def contrast_report(theme):
    """[(字, 底, 對比度)]，照 TEXT_PAIRS 的順序。"""
    t = TOKENS[theme]
    return [(fg, bg, round(contrast(t[fg], t[bg]), 2)) for fg, bg in TEXT_PAIRS]
