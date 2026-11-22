# -*- coding: utf-8 -*-
"""
框選覆蓋層與截圖（3.0 第 11 項第二十五階段）：一般版 `gui/region_overlay.py` 的 Qt 版。

**叫出來 → 拖 → 放開**。做法是「先截整個螢幕、拿截圖當覆蓋層的底」：呼叫端先把面板收起來、等畫面更新完
（`SETTLE_MS`），截下整個螢幕；覆蓋層把這張圖鋪滿、整片調暗，拖出來的那塊顯示原本亮度；放開之後從**同一張圖**裁出
那一塊。

為什麼不用半透明視窗：2026-11-22 在 Xvfb 實測，沒有合成器（compositor）的 X11 上半透明視窗畫出來是**整片黑**，
使用者根本看不到要框什麼（一般版 Tk 的 `-alpha` 也是同樣的限制，最差變成不透明）。鋪截圖的做法不靠合成器，
而且覆蓋層永遠不會被截進去（截圖在覆蓋層出現之前就截好了）。

**取消一定要留路**：Esc、按右鍵、視窗被關掉都算取消，而且一定回報（`cancelled`）。

截圖用 `QScreen.grabWindow`（在 Xvfb／xcb 實測可用，一套程式碼三個平台），**Windows／macOS 沒有實測**；
高 DPI 時截圖是實際像素，裁切照倍率換算（`crop_image`）。
截到的圖存成 BMP 交給原封不動的 `subtitle/screentranslate.capture_and_recognize` → `ocrengine`（在這台電腦辨識，
畫面不送出去）。抓回來整塊同一個顏色（全螢幕獨佔的遊戲、Wayland 不給截）一樣用 `screencap.looks_flat` 擋下、
講原因。整張截圖只放在記憶體裡、用完就丟；存到暫存檔的只有裁出來的那一塊（辨識完就刪）。截圖只能在主執行緒做，
所以主執行緒截好、裁好 `QImage`，背景只負責存檔與辨識。
"""
import os

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from subtitle import screencap

DIM_ALPHA = 82            # 覆蓋層的暗度（0～255）：太暗看不清底下，太亮看不出正在框選
MARQUEE = QColor("#2f8fef")  # 選取框顏色：深淺主題下都看得見的亮藍
SETTLE_MS = 120           # 收起面板之後、截整個螢幕之前，等畫面更新完的毫秒數


class RegionOverlay(QWidget):
    """蓋住 `screen` 的框選層，底下鋪 `background`（整個螢幕的截圖）。`selected` 送出 (left, top, width, height)（全域邏輯座標）。"""

    selected = Signal(tuple)
    cancelled = Signal()

    def __init__(self, screen=None, background=None, parent=None):
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.target_screen = screen or QGuiApplication.primaryScreen()
        self.background = background
        self.setGeometry(self.target_screen.geometry())
        self._origin = None
        self._current = None
        self._done = False

    def start(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def marquee(self):
        """目前拖出來的範圍（覆蓋層自己的座標）；還沒拖就是 None。"""
        if self._origin is None or self._current is None:
            return None
        # 跟放開時截的範圍用同一個算法（QRect(p1, p2) 會多算一個像素）
        return QRect(*screencap.normalize_region(self._origin.x(), self._origin.y(), self._current.x(), self._current.y()))

    # ----- 畫 -----
    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        has_background = self.background is not None and not self.background.isNull()
        if has_background:
            painter.drawImage(self.rect(), self.background)
        else:
            painter.fillRect(self.rect(), QColor(40, 40, 40))  # 截不到圖：至少框得到（裁出來會講擷取結果是空的）
        painter.fillRect(self.rect(), QColor(0, 0, 0, DIM_ALPHA))
        rect = self.marquee()
        if rect is not None:
            if has_background:  # 框裡面顯示原本亮度，看得清楚底下的字
                painter.drawImage(rect, self.background, _image_rect(self.background, self.rect(), rect))
            painter.setPen(QPen(MARQUEE, 2))
            painter.drawRect(rect)
        painter.end()

    # ----- 拖 -----
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.RightButton:
            self.cancel()
            return
        if event.button() == Qt.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self.update()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._origin is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() != Qt.LeftButton or self._origin is None:
            return
        end = event.position().toPoint()
        top_left = self.geometry().topLeft()
        region = screencap.normalize_region(self._origin.x() + top_left.x(), self._origin.y() + top_left.y(),
                                            end.x() + top_left.x(), end.y() + top_left.y())
        self._finish(region)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.cancel()
            return
        super().keyPressEvent(event)

    # ----- 結束 -----
    def _finish(self, region):
        if self._done:
            return
        self._done = True
        self.close()  # 截圖早就截好了：直接收起來、回報範圍
        self.selected.emit(tuple(region))

    def cancel(self):
        if self._done:
            return
        self._done = True
        self.cancelled.emit()
        self.close()

    def closeEvent(self, event):  # noqa: N802 —— 被關掉（例如 Alt+F4）也算取消
        if not self._done:
            self._done = True
            self.cancelled.emit()
        super().closeEvent(event)


def screen_bounds(screen):
    g = screen.geometry()
    return (g.x(), g.y(), g.width(), g.height())


def _image_rect(image, widget_rect, rect):
    """覆蓋層上的一塊（邏輯座標）對應到截圖上的哪一塊（實際像素；高 DPI 時兩者差一個倍率）。"""
    sx = image.width() / max(1, widget_rect.width())
    sy = image.height() / max(1, widget_rect.height())
    return QRect(round(rect.x() * sx), round(rect.y() * sy), round(rect.width() * sx), round(rect.height() * sy))


def grab_screen(screen):
    """在主執行緒截整個螢幕，回傳 QImage（實際像素）。"""
    return screen.grabWindow(0).toImage()


def crop_image(image, screen, region):
    """從整個螢幕的截圖裁出 `region`（全域邏輯座標）。截不到圖（空的 QImage）裁出來也是空的，存檔時講原因。"""
    g = screen.geometry()
    left, top, width, height = region
    rect = _image_rect(image, QRect(0, 0, g.width(), g.height()), QRect(left - g.x(), top - g.y(), width, height))
    return image.copy(rect)


def grab_region(screen, region):
    """截一塊畫面（整個螢幕截下來再裁）；真的截圖測試用這個。"""
    return crop_image(grab_screen(screen), screen, region)


def image_capture(image):
    """
    包成 `screentranslate.capture_and_recognize` 要的 capture 函式：把主執行緒截好的圖存成 BMP。

    跟 `screencap.capture_region` 一樣檢查：存不下來或太小 → 「擷取結果是空的」；整塊同一個顏色 → 講原因。
    """
    def capture(region, out_path, config=None, bounds=None):
        if image is None or not image.save(out_path, "BMP"):  # 空的 QImage 存不下來
            raise screencap.CaptureError(screencap.EMPTY_CAPTURE_MESSAGE)
        if not os.path.isfile(out_path) or os.path.getsize(out_path) < 64:
            raise screencap.CaptureError(screencap.EMPTY_CAPTURE_MESSAGE)
        if screencap.looks_flat(out_path, config):
            raise screencap.CaptureError(screencap.FLAT_CAPTURE_MESSAGE)
        return out_path
    return capture

