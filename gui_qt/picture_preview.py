# -*- coding: utf-8 -*-
"""
3.0 第 9 項第二～四階段：播放器上即時預覽畫面調整。

輸出走 ffmpeg（`subtitle/picture.py` 的濾鏡）；預覽不能每一格都叫 ffmpeg，改在 Qt 裡照同一份
數字近似：

* **裁切、旋轉、翻轉**：影片那一項放在一個只露出 `display_size` 那一塊的框裡，再加變換
  （`item_geometry`）：整張畫面放大到裁切範圍剛好填滿那一塊，繞裁切範圍的中心轉、翻。字幕
  與疊加素材照調整完的畫面擺。疊加素材（第三階段）是一張張圖，直接把圖裁好、轉好
  （`apply_to_image`）。
* **亮度、對比、飽和度**：`PictureEffect` 掛在影片那一項上，每畫一格就用 `adjust_image`
  調一次。只用 QPainter 的合成模式（加、反相、取亮），不需要 numpy，整張圖的運算都在 Qt
  的 C++ 裡做。

`adjust_image` 的算法是 ffmpeg `eq` 在 RGB 上的近似（`eq` 是在 YUV 上調：亮度與對比只動
Y、飽和度只動 UV）：

* 對比 c、亮度 b：只動亮度，每個顏色都加上 `(c-1)*(灰-0.5)+b`（0～1 的比例），超出就截掉。
* 飽和度 s：`灰 + s*(x-灰)`，灰是這一點的亮度（`Grayscale8`）。

`tests/test_qt_picture.py` 拿同一張圖分別用 ffmpeg 與這裡調，比顏色差多少。
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QColorSpace, QImage, QPainter, QTransform
from PySide6.QtWidgets import QGraphicsEffect

from subtitle import picture

_FORMAT = QImage.Format_ARGB32_Premultiplied
_OVER = QPainter.CompositionMode_SourceOver
_PLUS = QPainter.CompositionMode_Plus
_DIFF = QPainter.CompositionMode_Difference
_LIGHTEN = QPainter.CompositionMode_Lighten


def _paint(img, mode, source=None, color=None, opacity=1.0):
    """在 img 上畫一層（整張圖或一片純色），用 mode 合成、不透明度 opacity。"""
    painter = QPainter(img)
    painter.setCompositionMode(mode)
    painter.setOpacity(max(0.0, min(1.0, opacity)))
    if source is not None:
        painter.drawImage(0, 0, source)
    else:
        painter.fillRect(img.rect(), color)
    painter.end()


def _invert(img):
    _paint(img, _DIFF, color=QColor(255, 255, 255))


def _add(img, amount):
    """每個顏色加 amount（0～255，可以是負的；負的用「反相、加、反相」做減法）。"""
    amount = int(round(amount))
    if amount > 0:
        _paint(img, _PLUS, color=QColor(min(amount, 255), min(amount, 255), min(amount, 255)))
    elif amount < 0:
        _invert(img)
        _paint(img, _PLUS, color=QColor(min(-amount, 255), min(-amount, 255), min(-amount, 255)))
        _invert(img)


def _scaled(other, scale):
    """other × scale（0～1）的新圖。不能直接用「加」模式的不透明度：Qt 是先加、截到 255，
    再跟原本的混，加到滿的地方會少算。"""
    if scale >= 1.0:
        return other
    out = other.copy()
    _paint(out, _OVER, color=QColor(0, 0, 0), opacity=1.0 - scale)
    return out


def _subtract_image(img, other, scale=1.0):
    """img −＝ scale × other（scale 可以大於 1：拆成幾次，每次最多 1）。"""
    while scale > 1e-3:
        _invert(img)
        _paint(img, _PLUS, source=_scaled(other, scale))
        _invert(img)
        scale -= 1.0


def _plus_image(img, other, scale):
    """img ＋＝ scale × other（scale 可以大於 1：拆成幾次，每次最多 1）。"""
    while scale > 1e-3:
        _paint(img, _PLUS, source=_scaled(other, scale))
        scale -= 1.0


_LINEAR = QColorSpace(QColorSpace.SRgbLinear)


def _gray(img):
    """
    每一點的亮度做成灰圖。Qt 6 轉灰階會先照色彩空間換成線性光再加權；標成線性色彩空間，
    就變成直接把 RGB 數值加權（跟 ffmpeg 的 Y 一樣是在數值上加，係數略有不同）。
    """
    tagged = QImage(img)
    tagged.setColorSpace(_LINEAR)
    gray = tagged.convertToFormat(QImage.Format_Grayscale8).convertToFormat(_FORMAT)
    gray.setColorSpace(QColorSpace())
    return gray


def _blank(img, value=0):
    out = QImage(img.size(), _FORMAT)
    out.fill(QColor(value, value, value))
    return out


def _contrast_brightness(img, contrast, brightness):
    """
    亮度與對比只動亮度（跟 eq 一樣，顏色的濃淡不變）：每個顏色都加上同一個差值
    D＝(c-1)*(灰-128)+b*255*255/219。D 拆成正的部分與負的部分（同一點只有一個不是 0），先加後減，
    中途不會被截掉。
    """
    gray = _gray(img)
    slope = contrast - 1.0
    # eq 的亮度加在 16～235 的 Y 上（219 階），換成 0～255 的顏色要再放大 255/219
    constant = -slope * 128.0 + brightness * 255.0 * 255.0 / 219.0
    up, down = _blank(img), _blank(img)
    if slope >= 0:   # D＝slope*灰＋constant
        _plus_image(up, gray, slope)
        _add(up, constant)                       # 負的截在 0：max(D, 0)
        _add(down, -constant)
        _subtract_image(down, gray, slope)       # max(-D, 0)
    else:            # D＝constant − |slope|*灰
        _add(up, constant)
        _subtract_image(up, gray, -slope)
        _plus_image(down, gray, -slope)
        _add(down, -constant)
    _plus_image(img, up, 1.0)
    _subtract_image(img, down, 1.0)


def _saturation(img, saturation):
    gray = _gray(img)
    if saturation <= 1.0:  # 灰疊上去，不透明度 1-s
        _paint(img, _OVER, source=gray, opacity=1.0 - saturation)
        return
    # x + (s-1)*(x-灰)：x-灰 拆成正的部分 P＝max(x,灰)-灰、負的部分 N＝max(x,灰)-x，
    # 同一個顏色 P、N 至少一個是 0，先加 P 再減 N 不會在中途被截掉
    high = img.copy()
    _paint(high, _LIGHTEN, source=gray)          # max(x, 灰)
    above = high.copy()
    _subtract_image(above, gray)                 # P
    below = high
    _subtract_image(below, img)                  # N
    extra = saturation - 1.0
    _plus_image(img, above, extra)
    _subtract_image(img, below, extra)


def adjust_image(image: QImage, adjust) -> QImage:
    """照調整的亮度、對比、飽和度調一張圖，回傳新的圖（裁切、旋轉、翻轉不在這裡做）。"""
    adj = picture.normalize(adjust)
    img = image.convertToFormat(_FORMAT)
    if img is image:
        img = image.copy()
    if (adj["contrast"], adj["brightness"]) != (1.0, 0.0):
        _contrast_brightness(img, adj["contrast"], adj["brightness"])
    if adj["saturation"] != 1.0:
        _saturation(img, adj["saturation"])
    # 上面幾步會把透明的地方（影片還沒有畫面、補黑邊外面）塗成不透明的：照原圖的透明度遮回去
    painter = QPainter(img)
    painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, image)
    painter.end()
    return img


def has_color(adjust) -> bool:
    """這份調整有沒有動到顏色（沒有就不必掛效果，省每一格的運算）。"""
    adj = picture.normalize(adjust)
    return (adj["brightness"], adj["contrast"], adj["saturation"]) != (0.0, 1.0, 1.0)


def display_size(adjust, native: QSizeF) -> QSizeF:
    """調整完的畫面大小（原畫面 native 先裁，轉 90／270 度時寬高對調）。"""
    adj = picture.normalize(adjust)
    _x, _y, w, h = adj["crop"]
    size = QSizeF(native.width() * w, native.height() * h)
    if adj["rotate"] in (90, 270):
        return QSizeF(size.height(), size.width())
    return size


def item_geometry(adjust, native: QSizeF, target: QRectF):
    """
    影片那一項要設的 (大小, 變換)：調整完的畫面剛好填滿 target（場景座標）。

    整張原畫面放大成「裁切範圍的寬（轉完之後）＝target 的寬」，裁切範圍的中心對到 target 的
    中心，繞那一點轉、翻。超出 target 的部分由外面那一層框切掉。
    """
    adj = picture.normalize(adjust)
    x, y, w, h = adj["crop"]
    shown = display_size(adj, native)
    scale = target.width() / shown.width() if shown.width() > 0 else 1.0
    full = QSizeF(native.width() * scale, native.height() * scale)
    center = target.center()
    t = QTransform()
    t.translate(center.x(), center.y())
    # 先翻再轉，套在點上的順序是「轉 → 翻」（QTransform 的乘法是反過來的）——跟 ffmpeg 一樣
    t.scale(-1 if adj["flip_h"] else 1, -1 if adj["flip_v"] else 1)
    t.rotate(adj["rotate"])
    t.translate(-(x + w / 2) * full.width(), -(y + h / 2) * full.height())
    return full, t


class PictureEffect(QGraphicsEffect):
    """掛在影片那一項上：每一格照調整的顏色重畫（只在有調顏色時掛）。"""

    def __init__(self, adjust=None, parent=None):
        super().__init__(parent)
        self._adjust = picture.changes(adjust)
        self.frames = 0  # 調過幾格（給測試看有沒有真的在調）

    def set_adjust(self, adjust):
        self._adjust = picture.changes(adjust)
        self.update()

    def adjust(self):
        return dict(self._adjust)

    def draw(self, painter):
        if not has_color(self._adjust):
            self.drawSource(painter)
            return
        # 用影片那一項自己的座標取圖（PySide6 拿不到裝置座標的位移），畫回同一個位置；
        # 轉、翻照樣由那一項的變換負責
        pixmap = self.sourcePixmap(Qt.LogicalCoordinates)
        if pixmap.isNull():
            return
        image = adjust_image(pixmap.toImage(), self._adjust)
        self.frames += 1
        painter.drawImage(self.sourceBoundingRect(Qt.LogicalCoordinates), image)


def apply_to_image(image: QImage, adjust) -> QImage:
    """
    一張圖照整份調整（裁、轉、翻、調色）做成預覽用的新圖：疊加素材的圖片與抽出來的預覽格用。
    順序照 ffmpeg：先裁、再轉、再翻、最後調色；裁哪一塊照 `picture.crop_box`（跟輸出同一套取整）。
    """
    adj = picture.normalize(adjust)
    out = image
    if adj["crop"] != picture.DEFAULTS["crop"]:
        out = out.copy(*picture.crop_box(adj, out.width(), out.height()))
    if adj["rotate"]:
        out = out.transformed(QTransform().rotate(adj["rotate"]))
    if adj["flip_h"] or adj["flip_v"]:
        out = out.mirrored(adj["flip_h"], adj["flip_v"])
    if has_color(adj):
        out = adjust_image(out, adj)
    return out


def fitted_rect(view: QSizeF, picture_size: QSizeF) -> QRectF:
    """picture_size 等比放進 view 置中後占的矩形。"""
    if picture_size.isEmpty():
        return QRectF(0, 0, view.width(), view.height())
    fitted = picture_size.scaled(view, Qt.KeepAspectRatio)
    return QRectF((view.width() - fitted.width()) / 2, (view.height() - fitted.height()) / 2,
                  fitted.width(), fitted.height())
