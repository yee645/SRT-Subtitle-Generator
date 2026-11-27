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

第四階段（整句移動與鍵盤微調）：

- 按住字幕塊的身體拖超過 `MOVE_START_PX` → 整句前後移動（長度不變），游標是抓
  手；沒拖動就放開＝點選（放開時才跳到那句開頭）。
- 選取後 ←／→ 整句移動 `NUDGE_SEC`，按住 Shift 移動 `NUDGE_BIG_SEC`。
- 都走同一個 `cueTimesChanged`，所以復原／重做與存檔不用另外處理。

第 5 項第一階段（剪點可視化）：

- `set_cut_marks(剪點)`：`subtitle/cutmarks.py` 算出來「會剪掉的那幾段」畫成半透明
  紅色區塊，蓋過縮圖、波形與字幕列（被剪到的字幕看得出來），兩側畫剪點線；尺規列
  底下一條紅線，拉遠時也找得到。滑鼠停在上面顯示原因與剪掉幾秒。
- 只是畫：滑鼠照舊由時間軸自己處理（點擊、拖曳字幕不受影響），也不改字幕。

第 5 項第二階段（剪點可停用、可拖）：

- 字幕列底下多一條**剪點列**，每段剪點一個方塊：啟用是實心紅、停用是虛線空框（上面
  的半透明區塊也跟著變成只剩虛線，看得出「這段不剪」）。
- 點方塊 → `cutMarkToggled(第幾段, 是否啟用)`；按住左右邊拖 → 放開時送出
  `cutMarkChanged(第幾段, 開始, 結束)`，拖曳中按 Esc 放棄。能拖到哪裡由
  `cutmarks.drag_mark_edge` 決定；靠近播放頭或字幕的邊會吸附（剪在句子剛好結束
  的地方最常用）。
- 剪點的微調與字幕的時間分開：剪點列上的操作不會動到字幕。

第 7 項第二階段（疊加軌與音樂軌）：

- 剪點列底下多兩列：**疊加**（B-roll／圖片）與**音樂**，每段素材一個方塊，長度照
  `assemble.item_span`（跟輸出時一樣：超出片尾的剪掉、循環的音樂到片尾）。
- 點方塊 → 選取並跳到它開始的地方（`trackItemSelected`）；按住身體拖 → 前後移動，放開時
  送出 `trackItemMoved(哪一軌, 第幾段, 新的開始秒數)`。能放到哪裡由
  `assemble.clamp_at` 決定；靠近播放頭、字幕或別段素材的邊會吸附。拖曳中按 Esc 放棄。
- 選取後按 Delete（或 Backspace）→ `trackItemDeleteRequested`；真的刪不刪由播放器決定。

第 7 項第三階段（修頭尾）：滑鼠移到素材方塊左右邊 `EDGE_PX` 內游標變成左右箭頭，按住拖
＝修頭或修尾（規則在 `assemble.trim_item`：拖頭時素材的進點跟著動、尾巴不動；拖尾最多
到素材本身的長度）。一樣會吸附、Esc 放棄；放開時送出 `trackItemChanged(哪一軌, 第幾段,
新的 dict)`。循環的音樂一路到片尾，只有頭能修。
"""

from __future__ import annotations

import math
import os
import shutil
import threading

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsLineItem, QGraphicsPathItem, QGraphicsRectItem,
                               QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView, QToolTip, QWidget)

from subtitle import assemble as assemble_mod
from subtitle import cueedit
from subtitle import cutmarks as cutmarks_mod
from subtitle import designtokens
from subtitle import filmstrip as filmstrip_mod
from subtitle import mediabin
from subtitle import waveform as waveform_mod

# 列高（像素）
RULER_H = 22
THUMB_H = 54
WAVE_H = 64
CUE_H = 34
CUT_LANE_H = 20
GAP = 2
ROW_Y = {
    "ruler": 0,
    "thumbs": RULER_H + GAP,
    "wave": RULER_H + GAP + THUMB_H + GAP,
    "cues": RULER_H + GAP + THUMB_H + GAP + WAVE_H + GAP,
}
TRACK_H = 20
ROW_Y["cuts"] = ROW_Y["cues"] + CUE_H + GAP
ROW_Y["overlays"] = ROW_Y["cuts"] + CUT_LANE_H + GAP
ROW_Y["music"] = ROW_Y["overlays"] + TRACK_H + GAP
TOTAL_H = ROW_Y["music"] + TRACK_H
ROW_ORDER = ("ruler", "thumbs", "wave", "cues", "cuts", "overlays", "music")
# 四頁籤的播放器頁用的列高（上面那幾個常數）；剪輯器版面（E-2）的時間軸佔整條下方，軌道加高到主流剪輯軟體的高度
HEIGHTS = {"ruler": RULER_H, "thumbs": THUMB_H, "wave": WAVE_H, "cues": CUE_H, "cuts": CUT_LANE_H,
           "overlays": TRACK_H, "music": TRACK_H}
TALL_HEIGHTS = {"ruler": 24, "thumbs": 60, "wave": 56, "cues": 44, "cuts": 24, "overlays": 32, "music": 32}


def row_layout(heights=None):
    """各列的 (上緣 y, 高度, 總高)：照 ROW_ORDER 由上往下排，列與列之間留 GAP。"""
    heights = dict(HEIGHTS if heights is None else heights)
    y, row_y = 0, {}
    for name in ROW_ORDER:
        row_y[name] = y
        y += heights[name] + GAP
    return row_y, heights, y - GAP


# 軌道標頭（剪輯器版面）：(列, 名稱, 色票裡的軌道色)；尺規那一列不寫
TRACK_HEADERS = (
    ("thumbs", "畫面", "track.video"), ("wave", "聲音", "track.audio"), ("cues", "字幕", "track.subtitle"),
    ("cuts", "剪點", "track.cut"), ("overlays", "疊加", "track.overlay"), ("music", "音樂", "track.audio"),
)
HEADER_TIPS = {
    "thumbs": "畫面：影片的縮圖，點一下跳到那裡",
    "wave": "聲音：影片的音量波形",
    "cues": "字幕：拖邊改時間、拖身體整句移動、←／→ 微調",
    "cuts": None,  # 下面補上 CUT_LANE_NOTE
    "overlays": None,  # 下面補上 TRACK_NOTES
    "music": None,
}
CUT_LANE_NOTE = "剪點列：選了上面的「剪點」之後，點一下方塊停用／啟用、拖左右邊調整範圍"
TRACK_NOTES = {
    "overlays": "疊加軌：按「加入畫面…」從播放頭的位置放 B-roll 或圖片，拖方塊改位置、拖左右邊修頭尾",
    "music": "音樂軌：按「加入音樂…」從播放頭的位置放配樂，拖方塊改位置、拖左右邊修頭尾",
}
TRACK_NAMES = {"overlays": "疊加", "music": "音樂"}
HEADER_TIPS.update(TRACK_NOTES, cuts=CUT_LANE_NOTE)

CACHE_ROOT = ""  # 空字串＝程式工作目錄

FFMPEG_MISSING = "需要 ffmpeg——按主視窗上方的「自動安裝 ffmpeg」即可"

MIN_PX_PER_SEC = 2.0
MAX_PX_PER_SEC = 400.0
DEFAULT_PX_PER_SEC = 40.0
ZOOM_STEP = 1.25

EDGE_PX = 6   # 字幕塊左右邊多少像素內算「抓到邊」
SNAP_PX = 8   # 離吸附點（播放頭、鄰句的邊）多少像素內就貼上去
MOVE_START_PX = 4  # 按住字幕塊身體移動超過這麼多像素才算「整句拖曳」，以內是點選
NUDGE_SEC = 0.1    # ←／→ 微調選取那句一次移動多少秒
NUDGE_BIG_SEC = 1.0  # 按住 Shift 時

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


ZOOM_SLIDER_STEPS = 100


def zoom_to_slider(px_per_sec, steps=ZOOM_SLIDER_STEPS):
    """縮放倍率 → 滑桿位置（0～steps，對數刻度：每一格放大的倍數一樣）。"""
    pps = min(max(float(px_per_sec), MIN_PX_PER_SEC), MAX_PX_PER_SEC)
    return int(round(math.log(pps / MIN_PX_PER_SEC) / math.log(MAX_PX_PER_SEC / MIN_PX_PER_SEC) * steps))


def slider_to_zoom(value, steps=ZOOM_SLIDER_STEPS):
    """滑桿位置 → 縮放倍率（zoom_to_slider 的反函數）。"""
    frac = min(max(value / steps, 0.0), 1.0)
    return MIN_PX_PER_SEC * (MAX_PX_PER_SEC / MIN_PX_PER_SEC) ** frac


def elide(text, font, width):
    """方塊放不下整段字時在尾巴加「…」（E-2；原本是硬切，看不出後面還有字）。"""
    return QFontMetrics(font).elidedText(text, Qt.ElideRight, max(int(width), 0))


def palette_theme(view):
    """時間軸照調色盤的底色判斷深淺（四頁籤與剪輯器版面的調色盤都適用）。"""
    base = view.palette().color(QPalette.ColorRole.Base)
    return "dark" if base.lightness() < 128 else "light"


def _palette_colors(view):
    """時間軸的配色：一律取 `subtitle/designtokens.py` 的色票名稱（E-2 起不寫死色碼）。"""
    t = {k: QColor(v) for k, v in designtokens.TOKENS[palette_theme(view)].items()}
    dark = palette_theme(view) == "dark"

    def alpha(color, a):
        c = QColor(color)
        c.setAlpha(a)
        return c

    return {
        "bg": t["bg.panel"],
        "row": t["bg.raised"],
        "text": t["text.secondary"],
        "tick": t["text.muted"],
        "note": t["text.secondary"],
        "wave": t["track.audio"],
        "cue": t["track.subtitle"],
        "cue_sel": t["track.subtitle"].lighter(122),
        "cue_sel_pen": t["text.primary"],
        "cue_text": t["track.text"],
        "playhead": t["accent"],
        # 剪點：半透明（深色底要濃一點才看得到），邊線與剪點列的方塊不透明
        "cut": alpha(t["track.cut"], 80 if dark else 64),
        "cut_edge": t["track.cut"],
        # 接縫轉場重疊的那幾秒：斜線（跟剪點分得開）
        "seam": t["warning"],
        "overlays": t["track.overlay"],
        "music": t["track.audio"],
        "track_text": t["track.text"],
        "track_sel_pen": t["text.primary"],
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


class CutLaneRow(_Row):
    """剪點列的底色；還沒有剪點時寫一行怎麼用。方塊本身是 _make_cut_item 畫的。"""

    def paint_range(self, painter, rect, colors):
        if not self.timeline.cut_marks and self.timeline.inline_notes:
            self.paint_note(painter, CUT_LANE_NOTE, colors)


class TrackRow(_Row):
    """疊加軌／音樂軌的底色；還沒有素材時寫一行怎麼用。方塊本身是 _make_track_item 畫的。"""

    def __init__(self, timeline, kind):
        super().__init__(timeline, timeline.row_y[kind], timeline.row_h[kind])
        self.kind = kind

    def paint_range(self, painter, rect, colors):
        if not self.timeline.tracks[self.kind] and self.timeline.inline_notes:
            self.paint_note(painter, TRACK_NOTES[self.kind], colors)


class TimelineView(QGraphicsView):
    """時間軸：縮圖、波形、字幕塊、播放頭；點一下跳轉，Ctrl＋滾輪縮放。"""

    seekRequested = Signal(int)
    cueSelected = Signal(int)                    # 第幾句（set_cues 傳進來的清單位置）；-1＝取消選取
    cueTimesChanged = Signal(int, float, float)  # 第幾句、新的開始、新的結束（秒）
    cutMarkToggled = Signal(int, bool)           # 第幾段剪點（set_cut_marks 的順序）、是否啟用
    cutMarkChanged = Signal(int, float, float)   # 第幾段剪點、拖完的開始、結束（秒）
    trackItemSelected = Signal(str, int)          # 哪一軌（"overlays"／"music"）、第幾段；-1＝取消選取
    trackItemMoved = Signal(str, int, float)      # 哪一軌、第幾段、拖完的開始（秒）
    trackItemDeleteRequested = Signal(str, int)   # 選取後按 Delete
    trackItemChanged = Signal(str, int, object)   # 哪一軌、第幾段、修過頭尾的新 dict
    rowsChanged = Signal()                        # 換了列高（軌道標頭跟著重排）
    durationChanged = Signal(float)               # 換片子（片長 0＝沒有影片）
    zoomChanged = Signal(float)                   # 換了縮放（每秒幾像素）
    filesDropped = Signal(object, str, float)     # 拖進來的檔案路徑、落在哪一列（列名；列外是 ""）、第幾秒
    dropPreviewChanged = Signal(str)              # 拖曳中的落點預覽換了：一句話說會怎麼放（拖走或放下是 ""）

    def __init__(self, parent=None, heights=None, inline_notes=True):
        super().__init__(parent)
        # 列高：預設是四頁籤的；剪輯器版面傳 TALL_HEIGHTS。inline_notes＝在空的剪點列、素材軌上寫怎麼用
        # （剪輯器版面改寫在軌道標頭的提示裡，列上保持乾淨）
        self.row_y, self.row_h, self.total_h = row_layout(heights)
        self.inline_notes = inline_notes
        self.last_pick = ""        # 最後選的是字幕（"cue"）還是素材（"track"）：兩種可以同時選著，〔刪除〕刪最後選的
        # 拖檔案進來時的落點預覽（E-8c）：畫著的項目、這一次的落點與計畫、一句話的說明
        self.drop_items, self._drop_key, self._drop_plan, self.drop_hint = [], None, None, ""
        self._drop_chip_right = 0.0
        self.snap_enabled = True   # 拖曳時貼到播放頭、鄰句的邊（剪輯器工具列的〔吸附〕可以關）
        self.duration = 0.0
        self.px_per_sec = DEFAULT_PX_PER_SEC
        self.peaks = None
        self.filmstrip = None
        self.wave_note = "開啟影片後會在這裡畫出波形。"
        self.thumb_note = "開啟影片後會在這裡排出縮圖。"
        self.cues = []             # [(在 set_cues 清單裡的位置, cue)]，只放畫得出來的
        self._source = []          # set_cues 傳進來的整份清單（複本），拖曳規則要看鄰句
        self.selected = -1
        # 拖曳字幕塊：(第幾句, "start"/"end"/"body", 原本的開始, 原本的結束, 按下的秒數,
        # 按下的 x, 是否已經開始動)。抓身體要移動超過 MOVE_START_PX 才算拖（不然是點選）。
        self._edge_drag = None
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
        # 沒按鍵時也要收到滑鼠移動，才能在碰到字幕塊的邊時換游標
        self.viewport().setMouseTracking(True)
        self.setFixedHeight(self.total_h + self.horizontalScrollBar().sizeHint().height() + 2)
        self.colors = _palette_colors(self)

        self.ruler = RulerRow(self, self.row_y["ruler"], self.row_h["ruler"])
        self.thumbs = ThumbRow(self, self.row_y["thumbs"], self.row_h["thumbs"])
        self.wave = WaveRow(self, self.row_y["wave"], self.row_h["wave"])
        self.cut_lane = CutLaneRow(self, self.row_y["cuts"], self.row_h["cuts"])
        for row in (self.ruler, self.thumbs, self.wave, self.cut_lane):
            self.scene_.addItem(row)
        self.cue_bg = QGraphicsRectItem()
        self.cue_bg.setPen(QPen(Qt.NoPen))
        self.scene_.addItem(self.cue_bg)
        self.cue_items = []
        self.cut_marks = []        # set_cut_marks 傳進來的剪點（複本）
        self.cut_items = []        # 每段剪點蓋在上面幾列的半透明區塊
        self.cut_lane_items = []   # 每段剪點在剪點列上的方塊（點、拖的對象）
        self.seam_spans = []       # 接縫轉場在原本時間軸上吃掉的地方（assemble.seam_overlaps）
        self.seam_items = []
        self.seam_label = ""       # 「溶接」「黑場」（寫在提示裡）
        # 拖曳剪點：(第幾段, "start"/"end"/"body", 原本的開始, 原本的結束, 按下的秒數, 按下的 x)
        self._cut_drag = None
        self.tracks = {kind: [] for kind in assemble_mod.TRACK_KINDS}       # set_tracks 傳進來的（複本）
        self.track_items = {kind: [] for kind in assemble_mod.TRACK_KINDS}  # 每段素材的方塊
        self.track_rows = {kind: TrackRow(self, kind) for kind in assemble_mod.TRACK_KINDS}
        for row in self.track_rows.values():
            self.scene_.addItem(row)
        self.track_selected = None  # (哪一軌, 第幾段)
        # 拖曳素材：(哪一軌, 第幾段, 原本的開始, 按下的秒數, 按下的 x, 是否已經開始動)
        self._track_drag = None
        # 修頭尾：(哪一軌, 第幾段, "start"/"end", 原本的 dict, 原本那個邊的秒數, 按下的秒數)
        self._track_trim = None
        self.playhead = QGraphicsLineItem()
        self.playhead.setZValue(10)
        self.scene_.addItem(self.playhead)
        self._relayout()

    # ---- 對外 ----------------------------------------------------------

    def set_row_heights(self, heights, inline_notes=None):
        """換列高（剪輯器版面把軌道加高）；inline_notes 給了就一起換。已經放上去的東西照新的列重排。"""
        self.row_y, self.row_h, self.total_h = row_layout(heights)
        if inline_notes is not None:
            self.inline_notes = inline_notes
        rows = {"ruler": self.ruler, "thumbs": self.thumbs, "wave": self.wave, "cuts": self.cut_lane,
                **self.track_rows}
        for name, row in rows.items():
            row.row_y, row.row_h = self.row_y[name], self.row_h[name]
        self.setFixedHeight(self.total_h + self.horizontalScrollBar().sizeHint().height() + 2)
        self._pixmaps.clear()
        self._relayout()
        self.rowsChanged.emit()

    def scene_width(self):
        return max(self.duration * self.px_per_sec, 1.0)

    def set_duration(self, seconds):
        self.duration = max(float(seconds), 0.0)
        self._relayout()
        self.durationChanged.emit(self.duration)

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

    def set_cut_marks(self, marks):
        """換一組剪點（cutmarks.plan 的 marks；空清單＝不顯示）。"""
        self.cut_marks = [dict(m) for m in (marks or [])
                          if float(m["end"]) > float(m["start"])]
        self._cut_drag = None
        self._build_cut_marks()
        self.cut_lane.update()

    def set_seam_overlaps(self, spans, label=""):
        """
        在剪點列標出接縫轉場吃掉的地方（輸出時前後兩截疊在一起淡換）：[(開始, 結束), ...]，
        空清單＝不標。label 是轉場的名字，寫在滑鼠提示裡。
        """
        self.seam_spans = [(float(a), float(b)) for a, b in (spans or []) if float(b) > float(a)]
        self.seam_label = label
        self._build_seams()

    def seam_rects(self):
        """每一截接縫轉場在剪點列上的矩形（給測試用）。"""
        return [item.rect() for item in self.seam_items]

    def set_tracks(self, overlays, music):
        """換一份疊加軌與音樂軌（assemble 時間軸的 overlays／music）。同一段還在就保留選取。"""
        self.tracks = {"overlays": [dict(x) for x in (overlays or [])],
                       "music": [dict(x) for x in (music or [])]}
        if self.track_selected and self.track_selected[1] >= len(self.tracks[self.track_selected[0]]):
            self.track_selected = None
        self._track_drag = self._track_trim = None
        self._build_tracks()
        for row in self.track_rows.values():
            row.update()

    def track_rects(self, kind):
        """某一軌每段素材的方塊（給測試用；順序同 set_tracks 傳進來的）。"""
        return [item.rect() for item in self.track_items[kind]]

    def track_span(self, kind, index):
        """某一段素材目前佔的 (開始, 結束)；拖曳中回傳拖到的位置。"""
        return assemble_mod.item_span(kind, self.tracks[kind][index], self.duration)

    def track_hit(self, view_pos):
        """
        視窗座標落在哪一軌的哪一段：(哪一軌, 第幾段)，不在方塊上是 None。重疊時後加的
        在上面（跟畫面一致）。
        """
        scene = self.mapToScene(int(view_pos.x()), int(view_pos.y()))
        pps = self.px_per_sec
        for kind in assemble_mod.TRACK_KINDS:
            if not self.row_y[kind] <= scene.y() <= self.row_y[kind] + self.row_h[kind]:
                continue
            t = scene.x() / pps
            for index in range(len(self.tracks[kind]) - 1, -1, -1):
                start, end = self.track_span(kind, index)
                if start <= t <= max(end, start + 2.0 / pps):
                    return kind, index
            return None
        return None

    def track_part(self, view_pos):
        """
        視窗座標落在哪一段素材的哪裡：(哪一軌, 第幾段, "start"/"end"/"body")，不在方塊上
        是 None。抓邊照畫出來的寬度算；不能修的邊（循環音樂的尾巴）算身體。
        """
        hit = self.track_hit(view_pos)
        if hit is None:
            return None
        kind, index = hit
        pps = self.px_per_sec
        t = self.mapToScene(int(view_pos.x()), int(view_pos.y())).x() / pps
        start, end = self.track_span(kind, index)
        part = cueedit.edge_at(start, max(end, start + 2.0 / pps), t, EDGE_PX / pps) or cueedit.BODY
        if part != cueedit.BODY and part not in assemble_mod.trimmable_edges(kind, self.tracks[kind][index]):
            part = cueedit.BODY
        return kind, index, part

    def _track_snap_targets(self, kind, index):
        """拖素材時的吸附點：播放頭、字幕的邊、別段素材的頭尾（兩軌都算）。"""
        targets = [self.position_ms / 1000.0]
        for _i, cue in self.cues:
            targets += [float(cue["start"]), float(cue["end"])]
        for other in assemble_mod.TRACK_KINDS:
            for k in range(len(self.tracks[other])):
                if (other, k) != (kind, index):
                    targets += list(self.track_span(other, k))
        return targets

    # ----- 拖檔案進來（剪輯器版面 E-4：素材庫、檔案總管都行） -----
    def drop_target(self, view_pos):
        """視窗座標 → (落在哪一列, 第幾秒)：列名照 row_y（列外是 ""），秒數夾在 0～片長。"""
        scene = self.mapToScene(int(view_pos.x()), int(view_pos.y()))
        row = next((name for name, top in self.row_y.items()
                    if top <= scene.y() < top + self.row_h.get(name, 0)), "")
        seconds = max(0.0, scene.x() / self.px_per_sec)
        if self.duration > 0:
            seconds = min(seconds, self.duration)
        return row, round(seconds, 3)

    @staticmethod
    def _local_files(event):
        data = event.mimeData()
        if not data.hasUrls():
            return []
        return [u.toLocalFile() for u in data.urls() if u.isLocalFile()]

    def dragEnterEvent(self, event):  # noqa: N802
        paths = self._local_files(event)
        if self.duration > 0 and paths:
            event.acceptProposedAction()
            self.show_drop_preview(paths, event.position().toPoint())
        else:
            event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802
        paths = self._local_files(event)
        if self.duration > 0 and paths:
            event.acceptProposedAction()
            self.show_drop_preview(paths, event.position().toPoint())
        else:
            self.clear_drop_preview()
            event.ignore()

    def dragLeaveEvent(self, event):  # noqa: N802
        self.clear_drop_preview()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):  # noqa: N802
        self.clear_drop_preview()
        paths = self._local_files(event)
        if self.duration <= 0 or not paths:
            event.ignore()
            return
        row, seconds = self.drop_target(event.position().toPoint())
        event.acceptProposedAction()
        self.filesDropped.emit(paths, row, seconds)

    # ----- 拖曳的落點預覽（E-8c） -----
    def show_drop_preview(self, paths, view_pos):
        """
        拖曳中：在會落下的那一秒畫一條直線，會放上去的軌道各畫一個標籤（幾個、從第幾秒）；這一列不收的
        在滑鼠那一列畫紅色標籤。規則跟真的放（`PlayerPanel.drop_files`）是同一套（`mediabin.drop_plan`）。
        回傳 (列, 秒, 計畫)；同一個落點不重畫。
        """
        row, seconds = self.drop_target(view_pos)
        key = (tuple(paths), row, seconds, self.px_per_sec)
        if key == self._drop_key:
            return row, seconds, self._drop_plan
        self.clear_drop_preview(notify=False)
        plan = mediabin.drop_plan(paths, row)
        self._drop_key, self._drop_plan = key, plan
        t = {k: QColor(v) for k, v in designtokens.TOKENS[palette_theme(self)].items()}
        x = seconds * self.px_per_sec
        line = QGraphicsLineItem(x, self.row_y["thumbs"], x, self.total_h)
        line.setPen(QPen(t["accent"], 2))
        line.setZValue(8)
        self.scene_.addItem(line)
        self.drop_items.append(line)
        when = tick_label(seconds, 0.1)
        for track in ("overlays", "music"):
            if plan[track]:
                self._drop_chip(track, x, f"＋{len(plan[track])} 個（從 {when}）", t["accent"], t["accent.text"],
                                "accept")
        if plan["refused"] and row in self.row_y and row != "ruler":
            offset = self._drop_chip_right if plan.get(row) else x
            self._drop_chip(row, offset, mediabin.refused_note(row, plan["refused"]), t["track.cut"],
                            t["track.text"], "refuse")
        self.drop_hint = mediabin.drop_hint(plan, row)
        self.dropPreviewChanged.emit(self.drop_hint)
        return row, seconds, plan

    def _drop_chip(self, row, x, text, bg, fg, kind):
        font = QFont(self.font())
        font.setPixelSize(designtokens.FONT_PX["small"])
        top, height = self.row_y[row], self.row_h[row]
        h = min(height - 4, QFontMetrics(font).height() + 6)
        label = elide(text, font, 320)
        w = QFontMetrics(font).horizontalAdvance(label) + 12
        left = max(0.0, min(x + 4, self.scene_.sceneRect().width() - w))
        rect = QRectF(left, top + (height - h) / 2, w, h)
        path = QPainterPath()
        path.addRoundedRect(rect, designtokens.RADIUS["clip"], designtokens.RADIUS["clip"])
        chip = QGraphicsPathItem(path)
        chip.setBrush(QBrush(bg))
        chip.setPen(QPen(Qt.NoPen))
        chip.setZValue(9)
        chip.setData(0, kind)
        chip.setToolTip(text)
        caption = QGraphicsSimpleTextItem(label, chip)
        caption.setFont(font)
        caption.setBrush(QBrush(fg))
        caption.setPos(rect.left() + 6, rect.top() + (h - QFontMetrics(font).height()) / 2)
        self.scene_.addItem(chip)
        self.drop_items.append(chip)
        self._drop_chip_right = rect.right() + 4
        return chip

    def drop_chips(self):
        """畫著的預覽標籤：[(哪一列, "accept"／"refuse", 字)]（給測試用）。"""
        out = []
        for item in self.drop_items:
            if isinstance(item, QGraphicsPathItem):
                row = next((name for name, top in self.row_y.items()
                            if top <= item.boundingRect().center().y() < top + self.row_h.get(name, 0)), "")
                text = item.childItems()[0].text() if item.childItems() else ""
                out.append((row, item.data(0), text))
        return out

    def clear_drop_preview(self, notify=True):
        for item in self.drop_items:
            self.scene_.removeItem(item)
        had = bool(self.drop_items) or bool(self.drop_hint)
        self.drop_items, self._drop_key, self._drop_plan, self.drop_hint = [], None, None, ""
        if notify and had:
            self.dropPreviewChanged.emit("")

    def select_track_item(self, kind, index, seek=True):
        """選取某一段素材（index -1＝取消）；seek 時跳到它開始的地方。"""
        new = (kind, index) if index >= 0 and 0 <= index < len(self.tracks.get(kind, ())) else None
        changed = new != self.track_selected
        self.track_selected = new
        if new:
            self.last_pick = "track"
        self._build_tracks()
        if changed:
            self.trackItemSelected.emit(kind if new else "", index if new else -1)
        if seek and new:
            ms = int(round(self.track_span(kind, index)[0] * 1000))
            self.set_position(ms)
            self.seekRequested.emit(ms)

    def cut_rects(self):
        """每一段剪點在場景裡的矩形（給測試用；順序同 self.cut_marks）。"""
        return [item.rect() for item in self.cut_items]

    def cut_lane_rects(self):
        """每一段剪點在剪點列上的方塊（給測試用）。"""
        return [item.rect() for item in self.cut_lane_items]

    def cut_hit(self, view_pos):
        """
        視窗座標落在剪點列的哪一段、哪裡：(第幾段, "start"/"end"/"body")，不在方塊上是
        None。只看剪點列；抓邊優先，接縫上抓滑鼠所在的那一段。
        """
        scene = self.mapToScene(int(view_pos.x()), int(view_pos.y()))
        if not self.row_y["cuts"] <= scene.y() <= self.row_y["cuts"] + self.row_h["cuts"]:
            return None
        pps = self.px_per_sec
        t = scene.x() / pps
        hits = []
        for index, mark in enumerate(self.cut_marks):
            start, end = float(mark["start"]), float(mark["end"])
            # 方塊至少 2px 寬（見 _make_cut_item），太窄的剪點照畫出來的寬度算
            end = max(end, start + 2.0 / pps)
            part = cueedit.edge_at(start, end, t, EDGE_PX / pps)
            if part is not None:
                # 兩段剪點接在一起時，接縫左邊按下＝左邊那段的右邊（反之亦然）：
                # 滑鼠落在哪一段裡面就抓哪一段
                inside = start <= t <= end
                hits.append((part == cueedit.BODY, not inside, abs(t - (start + end) / 2), index, part))
        if not hits:
            return None
        hits.sort()
        *_rank, index, part = hits[0]
        return index, part

    def select_cue(self, index, seek=True):
        """選取第 index 句（-1＝取消）；seek 時跳到那句開頭。"""
        if not any(i == index for i, _c in self.cues):
            index = -1
        changed = index != self.selected
        self.selected = index
        if index >= 0:
            self.last_pick = "cue"
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
        if not self.row_y["cues"] <= scene.y() <= self.row_y["cues"] + self.row_h["cues"]:
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
        self.playhead.setLine(x, 0, x, self.total_h)
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
        self.zoomChanged.emit(new)

    def snap_tolerance(self):
        """吸附的距離（秒）：SNAP_PX 換成秒數；關掉吸附時是 0（只有剛好落在吸附點上才算）。"""
        return SNAP_PX / self.px_per_sec if self.snap_enabled else 0.0

    def set_snap(self, enabled):
        self.snap_enabled = bool(enabled)
        return self.snap_enabled

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
        return max(self.row_h["thumbs"] * ratio, 8.0)

    def thumb_pixmap(self, path):
        pixmap = self._pixmaps.get(path)
        if pixmap is None:
            pixmap = QPixmap(path)
            self._pixmaps[path] = pixmap
        return pixmap

    def cue_rects(self):
        """每一句字幕在場景裡的矩形（給測試與拖曳編輯用；順序同 self.cues）。"""
        return [item.rect() for item, _label in self.cue_items]

    def cut_times(self, index):
        """第 index 段剪點目前的 (開始, 結束)。"""
        mark = self.cut_marks[index]
        return float(mark["start"]), float(mark["end"])

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
            # 整個重排：字幕列的底色（cue_bg）與播放頭的筆是在 _relayout 設的，只重畫字幕塊會留著舊的顏色
            # （第三十四階段加了執行中切換深淺色才看到）
            self._relayout()
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
            track = self.track_part(pos)
            if track is not None and track[2] != cueedit.BODY:
                # 素材的邊：修頭／修尾，馬上開始拖
                kind, index, part = track
                if (kind, index) != self.track_selected:
                    self.select_track_item(kind, index, seek=False)
                start, end = self.track_span(kind, index)
                pressed = self.mapToScene(int(pos.x()), 0).x() / self.px_per_sec
                # 照移動量算（不是滑鼠的絕對位置）：抓在邊旁邊幾 px，邊也不會跳過去
                self._track_trim = (kind, index, part, dict(self.tracks[kind][index]),
                                    start if part == cueedit.START else end, pressed)
                self.setFocus(Qt.MouseFocusReason)
                event.accept()
                return
            if track is not None:
                # 素材方塊：先選取；移動超過 MOVE_START_PX 才算拖，沒動就放開＝點選（跳過去）
                kind, index = track[:2]
                if (kind, index) != self.track_selected:
                    self.select_track_item(kind, index, seek=False)
                pressed = self.mapToScene(int(pos.x()), 0).x() / self.px_per_sec
                at = float(self.tracks[kind][index].get("at", 0.0))
                self._track_drag = (kind, index, at, pressed, pos.x(), False)
                self.setFocus(Qt.MouseFocusReason)  # 讓 Esc 與 Delete 收得到
                event.accept()
                return
            if self.track_selected and self._in_track_row(pos):
                self.select_track_item("", -1, seek=False)
            cut = self.cut_hit(pos)
            if cut is not None:
                # 剪點列：抓邊＝拖曳調整範圍；抓身體＝放開時切換停用／啟用
                index, part = cut
                start, end = self.cut_times(index)
                pressed = self.mapToScene(int(pos.x()), 0).x() / self.px_per_sec
                self._cut_drag = (index, part, start, end, pressed, pos.x())
                self.setFocus(Qt.MouseFocusReason)  # 讓 Esc 收得到
                event.accept()
                return
            hit = self.cue_hit(pos)
            if hit is not None:
                # 抓邊：馬上開始拖。抓身體：先選取，移動超過 MOVE_START_PX 才算整句
                # 拖曳；沒動就放開＝點選，放開時才跳到那句開頭（拖曳中播放頭不動，
                # 才能當吸附點）。
                index, part = hit
                start, end = self.cue_times(index)
                if index != self.selected:
                    self.select_cue(index, seek=False)
                pressed = self.mapToScene(int(pos.x()), 0).x() / self.px_per_sec
                self._edge_drag = (index, part, start, end, pressed, pos.x(),
                                   part != cueedit.BODY)
                self._drag_times = (start, end)
                self.setFocus(Qt.MouseFocusReason)  # 讓 Esc 與 ←／→ 收得到
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
        if self._track_trim:
            kind, index, part, item0, edge0, pressed = self._track_trim
            pps = self.px_per_sec
            delta = self.mapToScene(int(pos.x()), 0).x() / pps - pressed
            t = cueedit.snap(edge0 + delta, self._track_snap_targets(kind, index), self.snap_tolerance())
            self.tracks[kind][index] = assemble_mod.trim_item(kind, item0, part, t, self.duration)
            self._refresh_track(kind, index)
            event.accept()
            return
        if self._track_drag:
            kind, index, at0, pressed, press_x, active = self._track_drag
            if not active:
                if abs(pos.x() - press_x) < MOVE_START_PX:
                    event.accept()
                    return
                self._track_drag = (kind, index, at0, pressed, press_x, True)
                self.viewport().setCursor(Qt.ClosedHandCursor)
            pps = self.px_per_sec
            delta = self.mapToScene(int(pos.x()), 0).x() / pps - pressed
            # 吸附：播放頭、字幕的邊、別段素材的頭尾（兩軌都算）
            start0, end0 = assemble_mod.item_span(kind, dict(self.tracks[kind][index], at=at0),
                                                  self.duration)
            targets = self._track_snap_targets(kind, index)
            at = cueedit.snap(at0 + delta, targets, self.snap_tolerance())
            # 尾巴也能吸：頭沒吸到時，看尾巴（at＋原本長度）有沒有靠近吸附點
            if at == at0 + delta:
                length = end0 - start0
                tail = cueedit.snap(at0 + delta + length, targets, self.snap_tolerance())
                at = tail - length
            self.tracks[kind][index]["at"] = assemble_mod.clamp_at(at, self.duration)
            self._refresh_track(kind, index)
            event.accept()
            return
        if self._cut_drag:
            index, part, start0, end0, pressed, _x = self._cut_drag
            if part != cueedit.BODY:
                pps = self.px_per_sec
                delta = self.mapToScene(int(pos.x()), 0).x() / pps - pressed
                base = start0 if part == cueedit.START else end0
                # 吸附：播放頭、字幕的邊（剪在句子剛好結束的地方）
                targets = [self.position_ms / 1000.0]
                for _i, cue in self.cues:
                    targets += [float(cue["start"]), float(cue["end"])]
                t = cueedit.snap(base + delta, targets, self.snap_tolerance())
                marks = list(self.cut_marks)
                marks[index] = dict(marks[index], start=start0, end=end0)
                start, end = cutmarks_mod.drag_mark_edge(marks, index, part, t,
                                                         duration=self.duration or None)
                self.cut_marks[index] = dict(self.cut_marks[index], start=start, end=end)
                self._refresh_cut(index)
            event.accept()
            return
        if self._edge_drag:
            index, part, start0, end0, pressed, press_x, active = self._edge_drag
            if not active:
                if abs(pos.x() - press_x) < MOVE_START_PX:
                    event.accept()
                    return
                self._edge_drag = (index, part, start0, end0, pressed, press_x, True)
                self.viewport().setCursor(Qt.ClosedHandCursor)
            pps = self.px_per_sec
            # 移動的量＝滑鼠移動的量：抓在邊旁邊幾個像素也不會一按就跳到滑鼠上
            delta = self.mapToScene(int(pos.x()), 0).x() / pps - pressed
            common = dict(duration=self.duration or None,
                          snap_to=[self.position_ms / 1000.0], snap_tolerance=self.snap_tolerance())
            if part == cueedit.BODY:
                self._drag_times = cueedit.move_cue(self._source, index, start0 + delta, **common)
            else:
                base = start0 if part == cueedit.START else end0
                self._drag_times = cueedit.drag_edge(self._source, index, part, base + delta, **common)
            self._refresh_cue(index)
            event.accept()
            return
        if self._dragging:
            self._request_seek(pos.x())
            event.accept()
            return
        cut = self.cut_hit(pos)
        hit = self.cue_hit(pos)
        track = self.track_part(pos)
        if track is not None:
            self.viewport().setCursor(Qt.OpenHandCursor if track[2] == cueedit.BODY
                                      else Qt.SizeHorCursor)
        elif cut is not None:
            self.viewport().setCursor(Qt.PointingHandCursor if cut[1] == cueedit.BODY
                                      else Qt.SizeHorCursor)
        elif hit is None:
            self.viewport().unsetCursor()
        elif hit[1] == cueedit.BODY:
            self.viewport().setCursor(Qt.OpenHandCursor)
        else:
            self.viewport().setCursor(Qt.SizeHorCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._dragging = False
        if self._track_trim:
            kind, index, _part, item0, _edge0, _pressed = self._track_trim
            self._track_trim = None
            item = dict(self.tracks[kind][index])
            if item != item0:
                self.trackItemChanged.emit(kind, index, item)
            event.accept()
            return
        if self._track_drag:
            kind, index, at0, _pressed, _x, active = self._track_drag
            self._track_drag = None
            if not active:
                self.select_track_item(kind, index)  # 沒拖動＝點選：跳到它開始的地方
            else:
                at = float(self.tracks[kind][index]["at"])
                if at != at0:
                    self.trackItemMoved.emit(kind, index, at)
                self.viewport().setCursor(Qt.OpenHandCursor)
            event.accept()
            return
        if self._cut_drag:
            index, part, start0, end0, _pressed, press_x = self._cut_drag
            self._cut_drag = None
            if part == cueedit.BODY:
                if abs(event.position().x() - press_x) >= MOVE_START_PX:
                    event.accept()  # 按住身體拖走再放開：不算點一下，不切換
                    return
                enabled = not self.cut_marks[index].get("enabled", True)
                self.cut_marks[index]["enabled"] = enabled
                self._refresh_cut(index)
                self.cutMarkToggled.emit(index, enabled)
            else:
                start, end = self.cut_times(index)
                if (start, end) != (start0, end0):
                    self.cutMarkChanged.emit(index, start, end)
            event.accept()
            return
        if self._edge_drag:
            index, part, start0, end0, _pressed, _x, active = self._edge_drag
            start, end = self._drag_times
            self._edge_drag = self._drag_times = None
            if part == cueedit.BODY and not active:
                self.select_cue(index)  # 沒拖動＝點選：跳到那句開頭
            else:
                self._commit_times(index, (start0, end0), (start, end))
            hit = self.cue_hit(event.position())
            if hit is not None and hit[1] == cueedit.BODY:
                self.viewport().setCursor(Qt.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape and self._track_trim:
            # 修頭尾修到一半反悔：放回原樣，什麼都不送出
            kind, index, _part, item0, _edge0, _pressed = self._track_trim
            self._track_trim = None
            self.tracks[kind][index] = dict(item0)
            self._refresh_track(kind, index)
            event.accept()
            return
        if event.key() == Qt.Key_Escape and self._track_drag:
            # 拖素材拖到一半反悔：回到原本的位置，什麼都不送出
            kind, index, at0, _p, _x, _active = self._track_drag
            self._track_drag = None
            self.tracks[kind][index]["at"] = at0
            self._refresh_track(kind, index)
            event.accept()
            return
        if (event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.track_selected
                and not self._track_drag and not self._track_trim):
            self.trackItemDeleteRequested.emit(*self.track_selected)
            event.accept()
            return
        if event.key() == Qt.Key_Escape and self._cut_drag:
            # 拖剪點拖到一半反悔：回到原本的範圍，什麼都不送出
            index, _part, start0, end0, _p, _x = self._cut_drag
            self._cut_drag = None
            self.cut_marks[index] = dict(self.cut_marks[index], start=start0, end=end0)
            self._refresh_cut(index)
            event.accept()
            return
        if event.key() == Qt.Key_Escape and self._edge_drag:
            # 拖到一半反悔：回到原本的時間，什麼都不送出
            self._edge_drag = self._drag_times = None
            self._build_cues()
            event.accept()
            return
        if (event.key() in (Qt.Key_Left, Qt.Key_Right) and self.selected >= 0
                and not self._edge_drag
                and not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)):
            # ←／→ 微調選取的那句（整句移動，規則同拖曳、不吸附）；Shift 一次移動多一點
            step = NUDGE_BIG_SEC if event.modifiers() & Qt.ShiftModifier else NUDGE_SEC
            step = -step if event.key() == Qt.Key_Left else step
            index = self.selected
            before = self.cue_times(index)
            after = cueedit.move_cue(self._source, index, before[0] + step,
                                     duration=self.duration or None)
            self._commit_times(index, before, after)
            event.accept()
            return
        super().keyPressEvent(event)

    def _commit_times(self, index, before, after):
        """拖曳或微調結束：時間有變就寫回、重畫、送出 cueTimesChanged。"""
        if tuple(after) != tuple(before):
            self._source[index]["start"], self._source[index]["end"] = after
            self._build_cues()
            self.cueTimesChanged.emit(index, after[0], after[1])
        else:
            self._build_cues()

    # ---- 內部 ----------------------------------------------------------

    def _in_track_row(self, view_pos):
        y = self.mapToScene(int(view_pos.x()), int(view_pos.y())).y()
        return any(self.row_y[k] <= y <= self.row_y[k] + self.row_h[k] for k in assemble_mod.TRACK_KINDS)

    def _in_cue_row(self, view_pos):
        y = self.mapToScene(int(view_pos.x()), int(view_pos.y())).y()
        return self.row_y["cues"] <= y <= self.row_y["cues"] + self.row_h["cues"]

    def _request_seek(self, view_x):
        ms = int(round(self.seconds_at(view_x) * 1000))
        self.set_position(ms, follow=False)
        self.seekRequested.emit(ms)

    def _relayout(self):
        width = self.scene_width()
        self.scene_.setSceneRect(0, 0, width, self.total_h)
        # 列與列之間的縫露出面板底色（E-2：原本整片同色，分不出軌道）
        self.setBackgroundBrush(QBrush(self.colors["bg"]))
        for row in (self.ruler, self.thumbs, self.wave, self.cut_lane, *self.track_rows.values()):
            row.update_geometry()
        self.cue_bg.setRect(0, self.row_y["cues"], width, self.row_h["cues"])
        self.cue_bg.setBrush(QBrush(self.colors["row"]))
        self.playhead.setPen(QPen(self.colors["playhead"], 2))
        self._build_cues()
        self._build_cut_marks()
        self._build_seams()
        self._build_tracks()
        self.set_position(self.position_ms, follow=False)

    def _build_cues(self):
        for item, _label in self.cue_items:
            self.scene_.removeItem(item)  # 文字是它的子項目，會一起拿掉
        self.cue_items = [self._make_cue_item(index, cue) for index, cue in self.cues]

    def _build_cut_marks(self):
        for item in self.cut_items:
            self.scene_.removeItem(item)  # 邊線與剪點列的方塊是子項目，會一起拿掉
        built = [self._make_cut_item(m) for m in self.cut_marks]
        self.cut_items = [overlay for overlay, _lane in built]
        self.cut_lane_items = [lane for _overlay, lane in built]

    def _build_seams(self):
        if not hasattr(self, "seam_items"):
            return  # 建構中
        for item in self.seam_items:
            self.scene_.removeItem(item)
        self.seam_items = []
        pps = self.px_per_sec
        for start, end in self.seam_spans:
            rect = QRectF(start * pps, self.row_y["cuts"] + 3, max((end - start) * pps, 2.0), self.row_h["cuts"] - 6)
            item = QGraphicsRectItem(rect)
            item.setBrush(QBrush(self.colors["seam"], Qt.BDiagPattern))
            item.setPen(QPen(self.colors["seam"], 1))
            item.setZValue(2)  # 在剪點方塊底下：拖剪點邊時不擋到
            item.setAcceptedMouseButtons(Qt.NoButton)
            item.setToolTip(f"接縫{self.seam_label}：這 {end - start:.2f} 秒輸出時跟接縫另一邊疊在一起淡換"
                            "（片子會短這麼多）")
            self.scene_.addItem(item)
            self.seam_items.append(item)

    def _refresh_cut(self, index):
        """只重畫一段剪點（拖曳中每次滑鼠移動都會呼叫）。"""
        self.scene_.removeItem(self.cut_items[index])
        self.cut_items[index], self.cut_lane_items[index] = self._make_cut_item(self.cut_marks[index])

    def _make_cut_item(self, mark):
        pps = self.px_per_sec
        start, end = float(mark["start"]), float(mark["end"])
        enabled = mark.get("enabled", True)
        top, bottom = self.row_y["thumbs"], self.row_y["cues"] + self.row_h["cues"]
        # 再短的剪點也至少 2 像素寬，拉到最遠也看得到
        width = max((end - start) * pps, 2.0)
        rect = QRectF(start * pps, top, width, bottom - top)
        item = QGraphicsRectItem(rect)
        # 停用的剪點：不填色、邊線淡一點——看得出「這段本來會剪，現在不剪」
        item.setBrush(QBrush(self.colors["cut"]) if enabled else QBrush(Qt.NoBrush))
        item.setPen(QPen(Qt.NoPen))
        item.setZValue(3)  # 在字幕塊上面（被剪到的字幕看得出來）、播放頭底下
        edge_color = QColor(self.colors["cut_edge"])
        if not enabled:
            edge_color.setAlpha(120)
        edge = QPen(edge_color, 1.5, Qt.DashLine)  # 虛線：跟實線的播放頭（也是紅的）分得出來
        for x in (rect.left(), rect.right()):
            QGraphicsLineItem(x, top, x, bottom, item).setPen(edge)
        if enabled:
            # 尺規列底下的紅線：拉遠時一眼看出哪裡有剪（停用的不畫）
            bar = QGraphicsRectItem(rect.left(), self.row_y["ruler"] + self.row_h["ruler"] - 4, width, 4, item)
            bar.setBrush(QBrush(self.colors["cut_edge"]))
            bar.setPen(QPen(Qt.NoPen))
        reasons = "\n".join(f"・{r}" for r in mark.get("reasons") or ())
        head = (f"剪掉 {end - start:.2f} 秒" if enabled else f"已停用（這 {end - start:.2f} 秒不剪）")
        tip = (f"{head}（{tick_label(start, 0.1)} → {tick_label(end, 0.1)}）"
               + ("（範圍調過）" if mark.get("edited") else "")
               + (f"\n{reasons}" if reasons else ""))
        item.setToolTip(tip)
        # 剪點列上的方塊：點一下停用／啟用、拖左右邊調整
        lane = QGraphicsRectItem(rect.left(), self.row_y["cuts"] + 3, width, self.row_h["cuts"] - 6, item)
        if enabled:
            lane.setBrush(QBrush(self.colors["cut_edge"]))
            lane.setPen(QPen(self.colors["cut_edge"].darker(130), 1))
        else:
            lane.setBrush(QBrush(Qt.NoBrush))
            lane.setPen(QPen(self.colors["cut_edge"], 1, Qt.DashLine))
        lane.setToolTip(tip + ("\n點一下停用（這段不剪）" if enabled else "\n點一下重新啟用")
                        + "；拖左右邊調整範圍")
        if width > 40:
            font = QFont(self.font())
            font.setPixelSize(11)
            label = QGraphicsSimpleTextItem(f"{end - start:.1f}s" if enabled else "不剪", lane)
            label.setFont(font)
            label.setBrush(QBrush(self.colors["track_text"] if enabled else self.colors["cut_edge"]))
            label.setPos(rect.left() + 4, self.row_y["cuts"] + 3)
            lane.setFlag(QGraphicsItem.ItemClipsChildrenToShape, True)
        self.scene_.addItem(item)
        return item, lane

    def _build_tracks(self):
        if not hasattr(self, "track_items"):
            return  # 建構中（_relayout 比軌道先跑）
        for kind in assemble_mod.TRACK_KINDS:
            for item in self.track_items[kind]:
                self.scene_.removeItem(item)
            self.track_items[kind] = [self._make_track_item(kind, i) for i in range(len(self.tracks[kind]))]

    def _refresh_track(self, kind, index):
        """只重畫一段素材（拖曳中每次滑鼠移動都會呼叫）。"""
        self.scene_.removeItem(self.track_items[kind][index])
        self.track_items[kind][index] = self._make_track_item(kind, index)

    def _make_track_item(self, kind, index):
        pps = self.px_per_sec
        data = self.tracks[kind][index]
        start, end = self.track_span(kind, index)
        rect = QRectF(start * pps, self.row_y[kind] + 2, max((end - start) * pps, 2.0), self.row_h[kind] - 4)
        item = QGraphicsRectItem(rect)
        color = self.colors[kind]
        item.setBrush(QBrush(color))
        if self.track_selected == (kind, index):
            item.setPen(QPen(self.colors["track_sel_pen"], 2))
            item.setZValue(2)
        else:
            item.setPen(QPen(color.darker(140), 1))
            item.setZValue(1 + index * 0.001)  # 後加的疊在上面（跟 track_hit 一致）
        name = os.path.basename(str(data.get("path", "")))
        marks = []
        if kind == "music":
            marks.append(f"音量 {int(round(float(data.get('volume', 0)) * 100))}%")
            if data.get("loop"):
                marks.append("循環")
            if data.get("duck"):
                marks.append("講話時壓低")
        else:
            where = assemble_mod.overlay_position(data)
            if where != "full":
                marks.append(dict((k, label) for k, label, _r in assemble_mod.OVERLAY_POSITIONS)
                             .get(where, "自訂位置"))
            if data.get("audio"):
                marks.append("帶聲音")
        tip = (f"{TRACK_NAMES[kind]}：{name}\n{tick_label(start, 0.1)} → {tick_label(end, 0.1)}"
               f"（{end - start:.1f} 秒）" + (f"\n{'、'.join(marks)}" if marks else "")
               + "\n拖方塊改位置、拖左右邊修頭尾；選取後按 Delete 刪除")
        item.setToolTip(tip)
        if rect.width() > 24:
            font = QFont(self.font())
            font.setPixelSize(11)
            label = QGraphicsSimpleTextItem(elide(name + (f"（{'、'.join(marks)}）" if marks else ""), font,
                                                  rect.width() - 8), item)
            label.setFont(font)
            label.setBrush(QBrush(self.colors["track_text"]))
            label.setPos(rect.left() + 4, rect.top() + (rect.height() - 13) / 2)
            item.setFlag(QGraphicsItem.ItemClipsChildrenToShape, True)
        self.scene_.addItem(item)
        return item

    def _refresh_cue(self, index):
        """只重畫一句（拖曳中每次滑鼠移動都會呼叫；上千句時不能每次全部重建）。"""
        for k, (i, cue) in enumerate(self.cues):
            if i == index:
                self.scene_.removeItem(self.cue_items[k][0])
                self.cue_items[k] = self._make_cue_item(index, cue)
                return

    def _make_cue_item(self, index, cue):
        pps = self.px_per_sec
        font = QFont(self.font())
        font.setPixelSize(12)
        start, end = self.cue_times(index)
        rect = QRectF(start * pps, self.row_y["cues"] + 3, max((end - start) * pps, 1.0), self.row_h["cues"] - 6)
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
            label = QGraphicsSimpleTextItem(elide(text, font, rect.width() - 8), item)
            label.setFont(font)
            label.setBrush(QBrush(self.colors["cue_text"]))
            label.setPos(rect.left() + 4, rect.top() + (rect.height() - 14) / 2)
            # 字比方塊長就截掉：子項目裁到父項目的外框
            item.setFlag(QGraphicsItem.ItemClipsChildrenToShape, True)
        return item, label


class TrackHeader(QWidget):
    """
    軌道標頭（剪輯器版面，E-2）：時間軸左邊固定的一欄，每一列寫名稱、左邊一條軌道色；滑過去的提示寫這一列怎麼用
    （原本寫在空的列上）。列的位置跟著 TimelineView 的 row_y／row_h，換列高時重排。
    """

    WIDTH = 72

    def __init__(self, timeline, parent=None):
        super().__init__(parent)
        self.timeline = timeline
        self.setFixedWidth(self.WIDTH)
        self.setMouseTracking(True)
        timeline.rowsChanged.connect(self._sync)
        self._sync()

    def _sync(self):
        self.setFixedHeight(self.timeline.height())
        self.update()

    def row_rect(self, name):
        """某一列在標頭裡的範圍（跟時間軸同高同位置）。"""
        return QRectF(0, self.timeline.row_y[name], self.width() - 6, self.timeline.row_h[name])

    def row_at(self, y):
        for name, _label, _color in TRACK_HEADERS:
            r = self.row_rect(name)
            if r.top() <= y <= r.bottom():
                return name
        return None

    def event(self, event):  # noqa: D401 —— 每一列各自的提示
        if event.type() == QEvent.Type.ToolTip:
            name = self.row_at(event.pos().y())
            if name:
                QToolTip.showText(event.globalPos(), HEADER_TIPS[name], self)
            else:
                QToolTip.hideText()
                event.ignore()
            return True
        return super().event(event)

    def paintEvent(self, _event):  # noqa: N802
        t = designtokens.TOKENS[palette_theme(self.timeline)]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        font = QFont(self.font())
        font.setPixelSize(designtokens.FONT_PX["small"])
        painter.setFont(font)
        for name, label, color in TRACK_HEADERS:
            r = self.row_rect(name)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(t["bg.raised"]))
            painter.drawRoundedRect(r, designtokens.RADIUS["clip"], designtokens.RADIUS["clip"])
            painter.setBrush(QColor(t[color]))
            painter.drawRoundedRect(QRectF(r.left() + 4, r.top() + 4, 3, max(r.height() - 8, 2)), 1.5, 1.5)
            painter.setPen(QColor(t["text.secondary"]))
            painter.drawText(r.adjusted(14, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, label)
        painter.end()


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
        try:
            self._load(gen, cancel, media_path)
        except RuntimeError as exc:
            # 視窗已經關了（物件被刪掉）才做完：結果不要了。其他 RuntimeError 照常拋出
            if "has been deleted" not in str(exc):
                raise

    def _load(self, gen, cancel, media_path):
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
