# -*- coding: utf-8 -*-
"""
3.0 第 2 項：播放器面板，字幕疊在真的影片畫面上。

Tk 版的「預覽」是 Canvas 畫的假畫面（`gui/preview_panel.py`），從來沒看過
字幕疊在真的影片上。這裡用 `QGraphicsView`＋`QGraphicsVideoItem`：影片是場
景裡的一個項目，字幕是疊在它上面的另一個文字項目，所以字幕跟著影片縮放、
不會被原生影片視窗蓋掉（`QVideoWidget` 在部分平台是原生子視窗，疊不上東
西）。

「這一刻顯示哪一句」交給 `subtitle/cuetime.py`（核心層、零 GUI 依賴），時
間軸之後也用同一個。

這一階段還沒做：套用 config 的字幕樣式（字型、位置、顏色）、與字幕清單雙
向同步、鍵盤快捷鍵。見 `docs/ROADMAP_3.0.md` 第 2 項。
"""
import os

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, QUrl, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QFileDialog, QGraphicsItem, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSlider, QVBoxLayout,
    QWidget,
)

from subtitle.cuetime import CueIndex
from subtitle.importer import load_subtitle_file

# 字幕離畫面底部的距離，占畫面高度的比例（與燒錄預設的下邊距同一個量級）。
BOTTOM_MARGIN_RATIO = 0.06
# 字級占畫面高度的比例：720p 約 36px，與燒錄預設相近。
FONT_HEIGHT_RATIO = 0.05


def format_clock(ms):
    """毫秒 → 「分:秒.十分之一秒」，播放器時間顯示用。"""
    ms = max(0, int(ms))
    minutes, rest = divmod(ms, 60000)
    return f"{minutes:02d}:{rest // 1000:02d}.{(rest % 1000) // 100}"


class OutlinedText(QGraphicsItem):
    """
    白字黑邊的字幕文字，多行各自置中。

    不用 `QGraphicsSimpleTextItem.setPen`：那個描邊是畫在字的**上面**，黑
    邊把白字吃掉一半，截圖上幾乎讀不出來（實際踩到）。這裡先用粗黑筆描
    外框、再把白字填在上面——跟燒錄出來的字幕同一種畫法。
    """

    def __init__(self):
        super().__init__()
        self._text = ""
        self._font = QFont()
        self._outline = 3.0
        self._path = QPainterPath()
        self._rect = QRectF()

    def text(self):
        return self._text

    def font(self):
        return QFont(self._font)

    def setText(self, text):  # noqa: N802 —— 與 Qt 項目同名，呼叫端不用改
        self._text = text or ""
        self._rebuild()

    def setFont(self, font):  # noqa: N802
        self._font = QFont(font)
        # 描邊粗細跟著字級走：字大邊也要粗，不然大字的邊細得像沒有。
        self._outline = max(2.0, font.pixelSize() / 12.0)
        self._rebuild()

    def _rebuild(self):
        self.prepareGeometryChange()
        metrics = QFontMetricsF(self._font)
        lines = self._text.split("\n") if self._text else []
        widest = max((metrics.horizontalAdvance(ln) for ln in lines), default=0.0)
        path = QPainterPath()
        for i, line in enumerate(lines):
            x = (widest - metrics.horizontalAdvance(line)) / 2
            path.addText(QPointF(x, metrics.ascent() + i * metrics.lineSpacing()),
                         self._font, line)
        self._path = path
        height = metrics.lineSpacing() * len(lines) if lines else 0.0
        pad = self._outline
        self._rect = QRectF(-pad, -pad, widest + 2 * pad, height + 2 * pad)
        self.update()

    def boundingRect(self):  # noqa: N802
        return self._rect

    def paint(self, painter, _option, _widget=None):
        if not self._text:
            return
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(0, 0, 0), self._outline * 2)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.strokePath(self._path, pen)
        painter.fillPath(self._path, QBrush(QColor(255, 255, 255)))


class _VideoView(QGraphicsView):
    """影片＋字幕疊加層；視窗大小改變時讓影片塞滿、字幕重新定位。"""

    resized = Signal()

    def resizeEvent(self, event):  # noqa: N802 —— Qt 的命名
        super().resizeEvent(event)
        self.resized.emit()


class PlayerPanel(QWidget):
    """播放器面板：開影片、載字幕、播放／暫停、拖曳跳轉，字幕疊在畫面上。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._index = CueIndex([])
        self._subtitle_path = ""

        self.scene = QGraphicsScene(self)
        self.view = _VideoView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setBackgroundBrush(QBrush(QColor(0, 0, 0)))
        self.view.setFrameShape(QGraphicsView.NoFrame)

        self.video_item = QGraphicsVideoItem()
        self.scene.addItem(self.video_item)
        self.subtitle_item = OutlinedText()
        self.subtitle_item.setZValue(1)
        self.subtitle_item.setVisible(False)
        self.scene.addItem(self.subtitle_item)

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_item)

        self.open_btn = QPushButton("開啟影片")
        self.subs_btn = QPushButton("載入字幕")
        self.play_btn = QPushButton("播放")
        self.play_btn.setEnabled(False)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        self.time_label = QLabel(format_clock(0) + " / " + format_clock(0))
        self.info_label = QLabel("還沒開啟影片。")

        controls = QHBoxLayout()
        for w in (self.open_btn, self.subs_btn, self.play_btn):
            controls.addWidget(w)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.view, 1)
        layout.addLayout(controls)
        layout.addWidget(self.info_label)

        self.open_btn.clicked.connect(self._choose_video)
        self.subs_btn.clicked.connect(self._choose_subtitles)
        self.play_btn.clicked.connect(self.toggle_play)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.errorOccurred.connect(self._on_error)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self.video_item.nativeSizeChanged.connect(lambda _size: self._layout())
        self.view.resized.connect(self._layout)

    # ---- 對外 ----------------------------------------------------------

    def open_video(self, path):
        self.player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
        self.play_btn.setEnabled(True)
        self.slider.setEnabled(True)
        self.info_label.setText(f"影片：{os.path.basename(path)}" + self._subs_note())

    def set_cues(self, cues, source=""):
        """換一份字幕；畫面上的那句立刻跟著更新（不必等下一格）。"""
        self._index = CueIndex(cues)
        self._subtitle_path = source
        self._show_at(self.player.position())
        name = os.path.basename(self.player.source().toLocalFile())
        self.info_label.setText((f"影片：{name}" if name else "還沒開啟影片。")
                                + self._subs_note())

    def load_subtitles(self, path):
        data = load_subtitle_file(path)
        self.set_cues(data["cues"], path)
        return data

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def current_subtitle_text(self):
        """畫面上此刻疊著的字幕（沒有就是空字串）。給測試與之後的時間軸用。"""
        return self.subtitle_item.text() if self.subtitle_item.isVisible() else ""

    # ---- 內部 ----------------------------------------------------------

    def _subs_note(self):
        if not len(self._index):
            return "　字幕：尚未載入"
        name = os.path.basename(self._subtitle_path) if self._subtitle_path else "（目前的字幕）"
        return f"　字幕：{name}，{len(self._index)} 句"

    def _choose_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "開啟影片", "", "影片 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v);;所有檔案 (*)")
        if path:
            self.open_video(path)

    def _choose_subtitles(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "載入字幕", "", "字幕 (*.srt *.vtt)")
        if not path:
            return
        try:
            self.load_subtitles(path)
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "載入字幕", str(exc))

    def _on_position(self, ms):
        if not self.slider.isSliderDown():
            self.slider.setValue(ms)
        self.time_label.setText(
            f"{format_clock(ms)} / {format_clock(self.player.duration())}")
        self._show_at(ms)

    def _on_duration(self, ms):
        self.slider.setRange(0, ms)
        self._on_position(self.player.position())

    def _on_state(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_btn.setText("暫停" if playing else "播放")

    def _on_media_status(self, status):
        # 剛載入時是「停止」狀態，停止狀態下跳轉不會出畫格，畫面一片黑、
        # 只有字幕（截圖實際看到）。載入好就進「暫停」：第一格出現，之後
        # 拖曳跳轉也看得到畫面。
        if (status == QMediaPlayer.MediaStatus.LoadedMedia
                and self.player.playbackState() == QMediaPlayer.PlaybackState.StoppedState):
            self.player.pause()

    def _on_error(self, _err, message):
        self.info_label.setText(f"無法播放：{message}")

    def _show_at(self, ms):
        cue = self._index.at(ms / 1000.0)
        text = cue["text"] if cue else ""
        if text != self.subtitle_item.text() or bool(text) != self.subtitle_item.isVisible():
            self.subtitle_item.setText(text)
            self.subtitle_item.setVisible(bool(text))
            self._place_subtitle()

    def _video_rect(self):
        """影片在場景裡實際占的矩形（保持比例、置中）。"""
        view = QSizeF(self.view.viewport().size())
        native = self.video_item.nativeSize()
        if native.isEmpty():
            return QRectF(0, 0, view.width(), view.height())
        fitted = native.scaled(view, Qt.KeepAspectRatio)
        return QRectF((view.width() - fitted.width()) / 2,
                      (view.height() - fitted.height()) / 2,
                      fitted.width(), fitted.height())

    def _layout(self):
        view = self.view.viewport().size()
        self.scene.setSceneRect(0, 0, view.width(), view.height())
        self.video_item.setPos(0, 0)
        self.video_item.setSize(QSizeF(view))
        self._place_subtitle()

    def _place_subtitle(self):
        rect = self._video_rect()
        font = QFont(self.subtitle_item.font())
        font.setPixelSize(max(12, int(rect.height() * FONT_HEIGHT_RATIO)))
        self.subtitle_item.setFont(font)
        box = self.subtitle_item.boundingRect()
        # 外框從 (-描邊, -描邊) 開始（描邊留白），置中要扣掉這段偏移，否則
        # 字幕會往左上偏幾個像素（測試量到偏 2.7px）。
        x = rect.left() + (rect.width() - box.width()) / 2 - box.left()
        y = rect.bottom() - rect.height() * BOTTOM_MARGIN_RATIO - box.height() - box.top()
        self.subtitle_item.setPos(x, y)
