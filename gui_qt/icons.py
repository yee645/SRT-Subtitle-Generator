# -*- coding: utf-8 -*-
"""
剪輯器版面（E 系列）用的圖示：自己畫的 SVG，24 格、線條 1.6px，不引用第三方圖示庫（授權單純、打包不多帶檔案）。

每個圖示只用 `currentColor`，畫的時候換成主題的顏色（`subtitle/designtokens.py`）。規格見 `docs/ROADMAP_EDITOR.md`。
"""
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_HEAD = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
         'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">')

# 名稱 → SVG 內容（不含外框）。
PATHS = {
    "logo": '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M7 15h4M13 15h4M7 11.5h10"/>',
    "media": '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M3 9h18M8 4v5M16 4v5"/>'
             '<path d="M10.5 12.5v4l3.5-2z" fill="currentColor"/>',
    "subtitles": '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M7 15h3.5M13 15h4M7 11.5h6M15.5 11.5H17"/>',
    "smart": '<path d="M12 3.5l1.7 4.3 4.3 1.7-4.3 1.7L12 15.5l-1.7-4.3L6 9.5l4.3-1.7z"/>'
             '<path d="M18 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8zM5.5 15.5l.6 1.4 1.4.6-1.4.6-.6 1.4-.6-1.4L3.5 17.5l1.4-.6z"/>',
    "health": '<path d="M12 20s-7.5-4.4-7.5-10A4.2 4.2 0 0 1 12 7.4 4.2 4.2 0 0 1 19.5 10c0 5.6-7.5 10-7.5 10z"/>'
              '<path d="M7.5 12h2.5l1.2-2 1.8 4 1.2-2h2.3"/>',
    "export": '<path d="M12 15V4M7.5 8.5 12 4l4.5 4.5"/><path d="M5 14v4.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V14"/>',
    "undo": '<path d="M9 7 5 11l4 4"/><path d="M5 11h9.5a4.5 4.5 0 0 1 0 9H12"/>',
    "redo": '<path d="m15 7 4 4-4 4"/><path d="M19 11H9.5a4.5 4.5 0 0 0 0 9H12"/>',
    "save": '<path d="M5 4h11l3 3v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z"/><path d="M8 4v5h7V4M8 20v-6h8v6"/>',
    "open": '<path d="M3.5 7.5A1.5 1.5 0 0 1 5 6h4l2 2h8a1.5 1.5 0 0 1 1.5 1.5V17a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 17z"/>',
    "project": '<rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    "translate": '<path d="M4 6h9M8.5 4v2M6 6c.5 3 2.5 5.5 5.5 7M11 6c-.6 3.4-3 6.2-6.5 8"/>'
                 '<path d="m12.5 20 3.5-9 3.5 9M13.8 17h4.4"/>',
    "key": '<circle cx="8" cy="14" r="4"/><path d="m11 11 8.5-8.5M16 6l2.5 2.5M14 8l2 2"/>',
    "help": '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.5a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.4"/>'
            '<circle cx="12" cy="16.8" r=".6" fill="currentColor"/>',
    "moon": '<path d="M19.5 14.5A8 8 0 0 1 9.5 4.5a8 8 0 1 0 10 10z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4'
           'M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
    "play": '<path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/>',
    "step_back": '<path d="M6.5 5.5v13"/><path d="M18 6v12l-8.5-6z" fill="currentColor"/>',
    "step_forward": '<path d="M17.5 5.5v13"/><path d="M6 6v12l8.5-6z" fill="currentColor"/>',
    "pause": '<path d="M8 5.5v13M16 5.5v13" stroke-width="3"/>',
    "zoom_in": '<circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 5 5M8 10.5h5M10.5 8v5"/>',
    "zoom_out": '<circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 5 5M8 10.5h5"/>',
    "fit": '<path d="M4 9V5h4M20 9V5h-4M4 15v4h4M20 15v4h-4"/><path d="M8 12h8M10 10l-2 2 2 2M14 10l2 2-2 2"/>',
    "delete": '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 12.5h9l1-12.5M10.5 11v5M13.5 11v5"/>',
    "cut": '<circle cx="6.5" cy="17.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/><path d="M8.3 15.7 17 4M15.7 15.7 7 4"/>',
    "music": '<path d="M9 17.5V5.5l10-2v12"/><circle cx="6.5" cy="17.5" r="2.5"/><circle cx="16.5" cy="15.5" r="2.5"/>',
    "image": '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><circle cx="9" cy="10" r="1.8"/>'
             '<path d="m4 18 5-5 3.5 3.5L15 14l5 4.5"/>',
    "wave": '<path d="M3 12h2M7 8v8M10 5v14M13 9v6M16 6.5v11M19 10v4M21 12h0"/>',
    "batch": '<path d="m12 3.5 8.5 4.5-8.5 4.5L3.5 8z"/><path d="m3.5 12 8.5 4.5 8.5-4.5M3.5 16l8.5 4.5 8.5-4.5"/>',
    "film": '<rect x="3.5" y="4" width="17" height="16" rx="2"/><path d="M7.5 4v16M16.5 4v16M3.5 8h4M3.5 12h4M3.5 16h4'
            'M16.5 8h4M16.5 12h4M16.5 16h4"/>',
    "generate": '<path d="M12 4a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V7a3 3 0 0 1 3-3z"/><path d="M6 11.5a6 6 0 0 0 12 0M12 17.5V20"/>',
    "inspector": '<path d="M5 6h8M17 6h2M5 12h2M11 12h8M5 18h10M19 18h0"/><circle cx="15" cy="6" r="2"/>'
                 '<circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    "picture": '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5v17" /><path d="M12 3.5a8.5 8.5 0 0 1 0 17z" fill="currentColor"/>',
    "split": '<path d="M12 3.5v17"/><path d="M8.5 7H5v10h3.5M15.5 7H19v10h-3.5"/>',
    "magnet": '<path d="M6 4.5v7a6 6 0 0 0 12 0v-7h-3.5v7a2.5 2.5 0 0 1-5 0v-7z"/><path d="M6 8.5h3.5M14.5 8.5H18"/>',
    "chevron_down": '<path d="m6 9 6 6 6-6" stroke-width="2.2"/>',
    "chevron_up": '<path d="m6 15 6-6 6 6" stroke-width="2.2"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5" stroke-width="2.8"/>',
}


def svg(name, color):
    """一個圖示的完整 SVG（`currentColor` 換成給的顏色）。不認得的名稱丟 KeyError。"""
    return (_HEAD + PATHS[name] + "</svg>").replace("currentColor", color)


def pixmap(name, color, size=20, ratio=1.0):
    """畫成 QPixmap（`ratio`＝裝置像素比，高解析度螢幕畫清楚一點）。"""
    px = max(1, round(size * ratio))
    out = QPixmap(px, px)
    out.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(svg(name, color).encode("utf-8")))
    painter = QPainter(out)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    out.setDevicePixelRatio(ratio)
    return out


def icon(name, color, disabled=None, active=None, size=20):
    """QIcon：一般、停用（`disabled`）、選取／打開（`active`）各一張。高解析度螢幕另畫兩倍大的一份。"""
    out = QIcon()
    for ratio in (1.0, 2.0):
        out.addPixmap(pixmap(name, color, size, ratio), QIcon.Normal, QIcon.Off)
        if disabled:
            out.addPixmap(pixmap(name, disabled, size, ratio), QIcon.Disabled, QIcon.Off)
            out.addPixmap(pixmap(name, disabled, size, ratio), QIcon.Disabled, QIcon.On)
        if active:
            out.addPixmap(pixmap(name, active, size, ratio), QIcon.Normal, QIcon.On)
    return out
