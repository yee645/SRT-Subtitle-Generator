# -*- coding: utf-8 -*-
"""
3.0 時間軸（ROADMAP_3.0 第 4 項第一階段）：縮圖列、波形、字幕塊、播放頭。

資料全部來自零 GUI 依賴的核心層——`subtitle/waveform.py`（峰值表）、
`subtitle/filmstrip.py`（縮圖條）、字幕 cue 清單——這裡只負責畫與互動：

- 場景寬度 = 片長 × 每秒像素數（`px_per_sec`）；橫向捲動交給 QGraphicsView。
- 波形與縮圖列是自繪項目，**只畫露出來的那一段**（`option.exposedRect`），
  一小時的片子拉到最近也不會一次畫幾十萬欄。
- Ctrl＋滾輪縮放，滑鼠底下那一秒維持在原地；一般滾輪照常捲動。
- 點一下或按住拖曳 → `seekRequested(毫秒)`；播放頭跑出畫面時自動捲過去。
- 背景抽波形與縮圖（Python 執行緒＋Qt 訊號跨執行緒排隊回主執行緒）；換片子
  時舊的工作被取消，晚到的結果用「第幾次載入」的編號丟掉，不會畫錯片子。

第二階段（選取與拖曳改時間）：

- 點字幕塊 → 選取（高亮）並跳到那句開頭；點字幕列的空白處 → 取消選取、照常跳轉。
- 滑鼠移到字幕塊左右邊 `EDGE_PX` 像素內，游標變成左右箭頭；按住拖曳改那一邊
  的時間，放開才送出 `cueTimesChanged(第幾句, 開始, 結束)`；拖曳中按 Esc 放棄。
- 能拖到哪裡由 `subtitle/cueedit.py` 決定（不重疊鄰句、至少 0.1 秒、不出片
  頭片尾、靠近播放頭或鄰句的邊會吸附），這裡只換算像素與畫。
"""

from __future__ import annotations

import math
import os
import shutil
import threading

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsLineItem, QGraphicsRectItem,
                               QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView)

from subtitle import cueedit
from subtitle import filmstrip as filmstrip_mod
from subtitle import waveform as waveform_mod

# 列高（像素）
RULER_H = 22
THUMB_H = 54
WAVE_H = 64
CUE_H = 34
GAP = 2
ROW_Y = {
    "ruler": 0,
    "thumbs": RULER_H + GAP,
    "wave": RULER_H + GAP + THUMB_H + GAP,
    "cues": RULER_H + GAP + THUMB_H + GAP + WAVE_H + GAP,
}
TOTAL_H = ROW_Y["cues"] + CUE_H

CACHE_ROOT = ""  # 空字串＝程式工作目錄

FFMPEG_MISSING = "需要 ffmpeg——在一般版按「自動安裝 ffmpeg」即可，兩版共用"

MIN_PX_PER_SEC = 2.0
MAX_PX_PER_SEC = 400.0
DEFAULT_PX_PER_SEC = 40.0
ZOOM_STEP = 1.25

EDGE_PX = 6   # 字幕塊左右邊多少像素內算「抓到邊」
SNAP_PX = 8   # 離吸附點（播放頭、鄰句的邊）多少像素內就貼上去

# 刻度間距候選（秒）：挑讓兩個標籤之間至少 MIN_LABEL_PX 的最小那個。
TICK_STEPS = (0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600)
MIN_LABEL_PX = 70


def tick_step(px_per_sec):
    """依縮放倍率挑刻度間距（秒）。"""
    for step in TICK_STEPS:
        if step * px_per_sec >= MIN_LABEL_PX:
            return step
    return TICK_STEPS[-1]


def ticks(start, end, px_per_sec):
    """[start, end] 秒之間的刻度時間（依 tick_step 對齊）。"""
    step = tick_step(px_per_sec)
    first = math.ceil(max(start, 0) / step - 1e-9)
    out = []
    k = first
    while k * step <= end + 1e-9:
        out.append(round(k * step, 3))
        k += 1
    return out


def tick_label(seconds, step):
    """刻度標籤：一秒以下的間距帶一位小數。"""
    minutes, secs = divmod(seconds, 60)
    if step < 1:
        return f"{int(minutes)}:{secs:04.1f}"
    return f"{int(minutes)}:{int(round(secs)):02d}"


def _palette_colors(view):
    pal = view.palette()
    base = pal.color(pal.ColorRole.Base)
    text = pal.color(pal.ColorRole.Text)
    dark = base.lightness() < 128
    return {
        "bg": base,
        "row": base.darker(115) if not dark else base.lighter(125),
        "text": text,
        "tick": QColor(text.red(), text.green(), text.blue(), 140),
        "wave": QColor("#3f9be0") if dark else QColor("#1f6fb2"),
        "cue": QColor("#c9892f") if dark else QColor("#e0a040"),
        "cue_sel": QColor("#ffd27a") if dark else QColor("#ffc85a"),
        "cue_sel_pen": QColor("#ffffff") if dark else QColor("#1a1a1a"),
        "cue_text": QColor("#101010"),
        "playhead": QColor("#e0403a"),
        "note": QColor(text.red(), text.green(), text.blue(), 170),
    }


class _Row(QGraphicsItem):
    """一整列（寬度隨片長）；子類別實作 paint_range 只畫露出來的區間。"""

    def __init__(self, timeline, y, height):
        super().__init__()
        self.timeline = timeline
        self.row_y = y
        self.row_h = height
        self.setFlag(QGraphicsItem.ItemUsesExtendedStyleOption, True)

    def boundingRect(self):  # noqa: N802
        return QRectF(0, self.row_y, self.timeline.scene_width(), self.row_h)

    def update_geometry(self):
        self.prepareGeometryChange()
        self.update()

    def paint(self, painter, option, _widget=None):
        rect = option.exposedRect.intersected(self.boundingRect())
        if rect.isEmpty():
            return
        colors = self.timeline.colors
        painter.fillRect(rect, colors["row"])
        self.paint_range(painter, rect, colors)

    def paint_note(self, painter, text, colors):
        """在列的可見範圍左邊寫一行狀態（載入中、沒有音軌…）。"""
        left = self.timeline.visible_range()[0] * self.timeline.px_per_sec
        painter.setPen(colors["note"])
        painter.drawText(QRectF(left + 8, self.row_y, 600, self.row_h),
                         Qt.AlignVCenter | Qt.AlignLeft, text)

    def paint_range(self, painter, rect, colors):
        raise NotImplementedError


class RulerRow(_Row):
    def paint_range(self, painter, rect, colors):
        pps = self.timeline.px_per_sec
        step = tick_step(pps)
        painter.setPen(QPen(colors["tick"], 1))
        font = QFont(painter.font())
        font.setPixelSize(11)
        painter.setFont(font)
        for t in ticks(rect.left() / pps - step, rect.right() / pps + step, pps):
            x = t * pps
            painter.drawLine(QPointF(x, self.row_y + self.row_h - 7),
                             QPointF(x, self.row_y + self.row_h))
            painter.setPen(colors["text"])
            painter.drawText(QPointF(x + 3, self.row_y + 13), tick_label(t, step))
            painter.setPen(QPen(colors["tick"], 1))


class WaveRow(_Row):
    def paint_range(self, painter, rect, colors):
        peaks = self.timeline.peaks
        if peaks is None:
            self.paint_note(painter, self.timeline.wave_note, colors)
            return
        left, right = int(math.floor(rect.left())), int(math.ceil(rect.right()))
        columns = self.timeline.wave_columns(left, right)
        mid = self.row_y + self.row_h / 2
        half = self.row_h / 2 - 2
        painter.setPen(QPen(colors["wave"], 1))
        for i, (lo, hi) in enumerate(columns):
            if lo == 0 and hi == 0:
                continue
            x = left + i + 0.5
            painter.drawLine(QPointF(x, mid - hi / 32768.0 * half),
                             QPointF(x, mid - lo / 32768.0 * half))


class ThumbRow(_Row):
    def paint_range(self, painter, rect, colors):
        strip = self.timeline.filmstrip
        if strip is None:
            self.paint_note(painter, self.timeline.thumb_note, colors)
            return
        slot_w = self.timeline.thumb_slot_width()
        pps = self.timeline.px_per_sec
        first = int(math.floor(rect.left() / slot_w))
        last = int(math.ceil(rect.right() / slot_w))
        end = self.timeline.duration or strip.duration
        for k in range(max(first, 0), last + 1):
            x = k * slot_w
            center = (x + slot_w / 2) / pps
            if end and center > end:  # 片尾之後留空
                break
            frame = strip.nearest(center)
            if frame is None:
                continue
            pixmap = self.timeline.thumb_pixmap(frame[1])
            if pixmap is None or pixmap.isNull():
                continue
            target = QRectF(x, self.row_y, slot_w, self.row_h)
            painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))


class TimelineView(QGraphicsView):
    """時間軸：縮圖、波形、字幕塊、播放頭；點一下跳轉，Ctrl＋滾輪縮放。"""

    seekRequested = Signal(int)
    cueSelected = Signal(int)                    # 第幾句（set_cues 傳進來的清單位置）；-1＝取消選取
    cueTimesChanged = Signal(int, float, float)  # 第幾句、新的開始、新的結束（秒）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.duration = 0.0
        self.px_per_sec = DEFAULT_PX_PER_SEC
        self.peaks = None
        self.filmstrip = None
        self.wave_note = "開啟影片後會在這裡畫出波形。"
        self.thumb_note = "開啟影片後會在這裡排出縮圖。"
        self.cues = []             # [(在 set_cues 清單裡的位置, cue)]，只放畫得出來的
        self._source = []          # set_cues 傳進來的整份清單（複本），拖曳規則要看鄰句
        self.selected = -1
        self._edge_drag = None     # 拖曳中：(第幾句, "start"/"end", 原本的開始, 原本的結束)
        self._drag_times = None    # 拖曳中目前的 (開始, 結束)
        self.position_ms = 0
        self._fit_mode = False
        self._pixmaps = {}
        self._dragging = False

        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setRenderHint(QPainter.Antialiasing, False)
        self.setViewportUpdateMode(QGraphicsView.MinimalViewportUpdate)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setFixedHeight(TOTAL_H + self.horizontalScrollBar().sizeHint().height() + 2)
        self.colors = _palette_colors(self)

        self.ruler = RulerRow(self, ROW_Y["ruler"], RULER_H)
        self.thumbs = ThumbRow(self, ROW_Y["thumbs"], THUMB_H)
        self.wave = WaveRow(self, ROW_Y["wave"], WAVE_H)
        for row in (self.ruler, self.thumbs, self.wave):
            self.scene_.addItem(row)
        self.cue_bg = QGraphicsRectItem()
        self.cue_bg.setPen(QPen(Qt.NoPen))
        self.scene_.addItem(self.cue_bg)
        self.cue_items = []
        self.playhead = QGraphicsLineItem()
        self.playhead.setZValue(10)
        self.scene_.addItem(self.playhead)
        self._relayout()

    # ---- 對外 ----------------------------------------------------------

    def scene_width(self):
        return max(self.duration * self.px_per_sec, 1.0)

    def set_duration(self, seconds):
        self.duration = max(float(seconds), 0.0)
        self._relayout()

    def set_peaks(self, peaks, note=""):
        self.peaks = peaks
        if note:
            self.wave_note = note
        self.wave.update()

    def set_filmstrip(self, strip, note=""):
        self.filmstrip = strip
        self._pixmaps.clear()
        if note:
            self.thumb_note = note
        self.thumbs.update()

    def set_cues(self, cues, keep_selection=False):
        """換一份字幕。keep_selection：同一份字幕改過時間後重畫，選取留著。"""
        self._source = [dict(c) for c in (cues or [])]
        self.cues = [(i, c) for i, c in enumerate(self._source)
                     if float(c.get("end", 0)) > float(c.get("start", 0))]
        if not keep_selection or not any(i == self.selected for i, _c in self.cues):
            self.selected = -1
        self._edge_drag = self._drag_times = None
        self._build_cues()

    def select_cue(self, index, seek=True):
        """選取第 index 句（-1＝取消）；seek 時跳到那句開頭。"""
        if not any(i == index for i, _c in self.cues):
            index = -1
        changed = index != self.selected
        self.selected = index
        self._build_cues()
        if changed:
            self.cueSelected.emit(index)
        if seek and index >= 0:
            ms = int(round(float(self._source[index]["start"]) * 1000))
            self.set_position(ms)
            self.seekRequested.emit(ms)

    def cue_hit(self, view_pos):
        """
        視窗座標落在哪一句的哪裡：(第幾句, "start"/"end"/"body")，不在字幕塊上是
        None。只看字幕列；重疊時開始得晚的那句在上面（與畫面、CueIndex 一致）。
        """
        scene = self.mapToScene(int(view_pos.x()), int(view_pos.y()))
        if not ROW_Y["cues"] <= scene.y() <= ROW_Y["cues"] + CUE_H:
            return None
        pps = self.px_per_sec
        t = scene.x() / pps
        hits = []
        for index, cue in self.cues:
            start, end = float(cue["start"]), float(cue["end"])
            part = cueedit.edge_at(start, end, t, EDGE_PX / pps)
            if part is not None:
                hits.append((start, index, part))
        if not hits:
            return None
        # 抓邊優先（兩句接在一起時，接縫上抓到的是邊不是另一句的身體），
        # 其次開始得最晚的那句。
        hits.sort(key=lambda h: (h[2] != cueedit.BODY, h[0], h[1]))
        _start, index, part = hits[-1]
        return index, part

    def reset(self, note_wave, note_thumbs):
        """換片子：清掉舊的資料，列上寫狀態。"""
        self.peaks = None
        self.filmstrip = None
        self._pixmaps.clear()
        self.wave_note = note_wave
        self.thumb_note = note_thumbs
        self.wave.update()
        self.thumbs.update()

    def set_position(self, ms, follow=True):
        """移動播放頭；follow 時播放頭跑出畫面就捲過去（留 10% 邊界）。"""
        self.position_ms = int(ms)
        x = self.position_ms / 1000.0 * self.px_per_sec
        self.playhead.setLine(x, 0, x, TOTAL_H)
        if follow:
            left, right = self.visible_range()
            if not left * self.px_per_sec <= x <= right * self.px_per_sec:
                width = self.viewport().width()
                self.horizontalScrollBar().setValue(int(x - width * 0.1))

    def set_zoom(self, px_per_sec, anchor_sec=None, anchor_x=None, keep_fit=False):
        """
        換縮放倍率。anchor_sec／anchor_x：縮放後讓這一秒仍落在視窗的 anchor_x
        像素處（Ctrl＋滾輪用滑鼠位置）；省略時保持畫面中央那一秒不動。
        """
        new = min(max(float(px_per_sec), MIN_PX_PER_SEC), MAX_PX_PER_SEC)
        if anchor_sec is None:
            left, right = self.visible_range()
            anchor_sec = (left + right) / 2
            anchor_x = self.viewport().width() / 2
        self.px_per_sec = new
        self._fit_mode = keep_fit  # 使用者自己縮放過就不再自動塞滿
        self._relayout()
        self.horizontalScrollBar().setValue(int(round(anchor_sec * new - anchor_x)))

    def zoom_in(self):
        self.set_zoom(self.px_per_sec * ZOOM_STEP)

    def zoom_out(self):
        self.set_zoom(self.px_per_sec / ZOOM_STEP)

    def zoom_to_fit(self):
        """整支片子剛好塞滿視窗寬度。"""
        if self.duration > 0:
            self.set_zoom(max(self.viewport().width() - 2, 1) / self.duration, 0, 0,
                          keep_fit=True)

    def visible_range(self):
        """目前看得到的時間範圍（秒）。"""
        left = self.horizontalScrollBar().value()
        right = left + self.viewport().width()
        return left / self.px_per_sec, right / self.px_per_sec

    def seconds_at(self, view_x):
        """視窗內 x 像素對應的秒數（夾在 0～片長）。"""
        scene_x = self.mapToScene(int(view_x), 0).x()
        t = scene_x / self.px_per_sec
        return min(max(t, 0.0), self.duration) if self.duration else max(t, 0.0)

    def wave_columns(self, left_px, right_px):
        """場景 x 區間 [left_px, right_px) 每一個像素欄的 (最小, 最大)。"""
        if self.peaks is None or right_px <= left_px:
            return []
        pps = self.px_per_sec
        return waveform_mod.resample(self.peaks, left_px / pps, right_px / pps,
                                     right_px - left_px)

    def thumb_slot_width(self):
        """一格縮圖的寬度：照縮圖的長寬比（沒有縮圖時用 16:9）。"""
        ratio = 16 / 9
        if self.filmstrip is not None and self.filmstrip.frames:
            pixmap = self.thumb_pixmap(self.filmstrip.frames[0][1])
            if pixmap is not None and not pixmap.isNull() and pixmap.height():
                ratio = pixmap.width() / pixmap.height()
        return max(THUMB_H * ratio, 8.0)

    def thumb_pixmap(self, path):
        pixmap = self._pixmaps.get(path)
        if pixmap is None:
            pixmap = QPixmap(path)
            self._pixmaps[path] = pixmap
        return pixmap

    def cue_rects(self):
        """每一句字幕在場景裡的矩形（給測試與拖曳編輯用；順序同 self.cues）。"""
        return [item.rect() for item, _label in self.cue_items]

    def cue_times(self, index):
        """第 index 句目前的 (開始, 結束)；拖曳中回傳拖到的位置。"""
        if self._edge_drag and self._edge_drag[0] == index and self._drag_times:
            return self._drag_times
        cue = self._source[index]
        return float(cue["start"]), float(cue["end"])

    # ---- 事件 ----------------------------------------------------------

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        # 「整支」模式下視窗變寬變窄都重新塞滿（一開片子時視窗常常還沒排好版，
        # 那時量到的寬度不是最後的寬度）。
        if self._fit_mode:
            self.zoom_to_fit()

    def changeEvent(self, event):  # noqa: N802 —— 深淺主題切換時換色
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self.colors = _palette_colors(self)
            self._build_cues()
            self.scene_.update()

    def wheelEvent(self, event):  # noqa: N802
        if event.modifiers() & Qt.ControlModifier:
            x = event.position().x()
            anchor = self.mapToScene(int(x), 0).x() / self.px_per_sec
            factor = ZOOM_STEP if event.angleDelta().y() > 0 else 1 / ZOOM_STEP
            self.set_zoom(self.px_per_sec * factor, anchor, x)
            event.accept()
            return
        # 一般滾輪：橫向捲動（時間軸只有橫的方向可捲）
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - event.angleDelta().y())
        event.accept()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self.duration > 0:
            pos = event.position()
            hit = self.cue_hit(pos)
            if hit is not None and hit[1] != cueedit.BODY:
                index, edge = hit
                start, end = self.cue_times(index)
                if index != self.selected:
                    self.select_cue(index, seek=False)
                self._edge_drag = (index, edge, start, end)
                self._drag_times = (start, end)
                self.setFocus(Qt.MouseFocusReason)  # 讓 Esc 收得到
                event.accept()
                return
            if hit is not None:
                self.select_cue(hit[0])
                event.accept()
                return
            if self._in_cue_row(pos):
                self.select_cue(-1, seek=False)
            self._dragging = True
            self._request_seek(pos.x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        pos = event.position()
        if self._edge_drag:
            index, edge, _s, _e = self._edge_drag
            pps = self.px_per_sec
            t = self.mapToScene(int(pos.x()), 0).x() / pps
            self._drag_times = cueedit.drag_edge(
                self._source, index, edge, t, duration=self.duration or None,
                snap_to=[self.position_ms / 1000.0], snap_tolerance=SNAP_PX / pps)
            self._build_cues()
            event.accept()
            return
        if self._dragging:
            self._request_seek(pos.x())
            event.accept()
            return
        hit = self.cue_hit(pos)
        if hit is not None and hit[1] != cueedit.BODY:
            self.viewport().setCursor(Qt.SizeHorCursor)
        else:
            self.viewport().unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._dragging = False
        if self._edge_drag:
            index, _edge, start0, end0 = self._edge_drag
            start, end = self._drag_times
            self._edge_drag = self._drag_times = None
            if (start, end) != (start0, end0):
                self._source[index]["start"] = start
                self._source[index]["end"] = end
                self._build_cues()
                self.cueTimesChanged.emit(index, start, end)
            else:
                self._build_cues()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape and self._edge_drag:
            # 拖到一半反悔：回到原本的時間，什麼都不送出
            self._edge_drag = self._drag_times = None
            self._build_cues()
            event.accept()
            return
        super().keyPressEvent(event)

    # ---- 內部 ----------------------------------------------------------

    def _in_cue_row(self, view_pos):
        y = self.mapToScene(int(view_pos.x()), int(view_pos.y())).y()
        return ROW_Y["cues"] <= y <= ROW_Y["cues"] + CUE_H

    def _request_seek(self, view_x):
        ms = int(round(self.seconds_at(view_x) * 1000))
        self.set_position(ms, follow=False)
        self.seekRequested.emit(ms)

    def _relayout(self):
        width = self.scene_width()
        self.scene_.setSceneRect(0, 0, width, TOTAL_H)
        for row in (self.ruler, self.thumbs, self.wave):
            row.update_geometry()
        self.cue_bg.setRect(0, ROW_Y["cues"], width, CUE_H)
        self.cue_bg.setBrush(QBrush(self.colors["row"]))
        self.playhead.setPen(QPen(self.colors["playhead"], 2))
        self._build_cues()
        self.set_position(self.position_ms, follow=False)

    def _build_cues(self):
        for item, _label in self.cue_items:
            self.scene_.removeItem(item)  # 文字是它的子項目，會一起拿掉
        self.cue_items = []
        pps = self.px_per_sec
        font = QFont(self.font())
        font.setPixelSize(12)
        for index, cue in self.cues:
            start, end = self.cue_times(index)
            rect = QRectF(start * pps, ROW_Y["cues"] + 3, max((end - start) * pps, 1.0), CUE_H - 6)
            item = QGraphicsRectItem(rect)
            if index == self.selected:
                item.setBrush(QBrush(self.colors["cue_sel"]))
                item.setPen(QPen(self.colors["cue_sel_pen"], 2))
                item.setZValue(2)  # 選取的那句疊在鄰句上面，邊框看得全
            else:
                item.setBrush(QBrush(self.colors["cue"]))
                item.setPen(QPen(self.colors["cue"].darker(140), 1))
                item.setZValue(1)
            item.setToolTip(str(cue.get("text", "")))
            self.scene_.addItem(item)
            label = None
            text = " ".join(str(cue.get("text", "")).split())
            if rect.width() > 24 and text:
                label = QGraphicsSimpleTextItem(text, item)
                label.setFont(font)
                label.setBrush(QBrush(self.colors["cue_text"]))
                label.setPos(rect.left() + 4, rect.top() + (rect.height() - 14) / 2)
                # 字比方塊長就截掉：子項目裁到父項目的外框
                item.setFlag(QGraphicsItem.ItemClipsChildrenToShape, True)
            self.cue_items.append((item, label))


class TimelineLoader(QObject):
    """
    背景抽波形與縮圖。每次 load() 是一個新的「第幾次載入」；舊的工作被取消，
    晚到的結果（編號不是最新的）一律丟掉。
    """

    peaksReady = Signal(int, object)
    filmstripReady = Signal(int, object)
    failed = Signal(int, str, str)  # 編號、哪一種（"wave"／"thumbs"）、原因

    def __init__(self, parent=None, cache_root=None):
        super().__init__(parent)
        self.generation = 0
        self._cancel = threading.Event()
        # 快取放哪：預設與 Tk 版的 transcribe_cache 一樣在程式工作目錄；
        # None＝每次載入時才讀模組的 CACHE_ROOT（測試與自檢把它指到暫存資料夾，
        # 不在 repo 或程式資料夾裡留下快取）。
        self.cache_root = cache_root

    def load(self, media_path):
        self._cancel.set()
        self._cancel = threading.Event()
        self.generation += 1
        gen, cancel = self.generation, self._cancel
        threading.Thread(target=self._run, args=(gen, cancel, media_path),
                         daemon=True).start()
        return gen

    def cancel(self):
        self._cancel.set()

    def _cache(self, name):
        root = CACHE_ROOT if self.cache_root is None else self.cache_root
        return os.path.join(root, name) if root else name

    def _run(self, gen, cancel, media_path):
        if not shutil.which("ffmpeg"):
            for kind in ("wave", "thumbs"):
                self.failed.emit(gen, kind, FFMPEG_MISSING)
            return
        try:
            peaks = waveform_mod.load_peaks(media_path, cache_dir=self._cache(waveform_mod.CACHE_DIR),
                                            cancel=cancel.is_set)
            if not cancel.is_set():
                self.peaksReady.emit(gen, peaks)
        except waveform_mod.WaveformCancelled:
            return
        except (waveform_mod.WaveformError, OSError) as exc:
            if not cancel.is_set():
                self.failed.emit(gen, "wave", str(exc))
        try:
            strip = filmstrip_mod.load_filmstrip(
                media_path, height=THUMB_H * 2, cache_dir=self._cache(filmstrip_mod.CACHE_DIR),
                cancel=cancel.is_set)
            if not cancel.is_set():
                self.filmstripReady.emit(gen, strip)
        except filmstrip_mod.FilmstripCancelled:
            return
        except (filmstrip_mod.FilmstripError, OSError) as exc:
            if not cancel.is_set():
                self.failed.emit(gen, "thumbs", str(exc))
