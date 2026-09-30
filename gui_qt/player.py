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

字幕的字型、字級、顏色、邊框、上下位置與重點字照 config 的字幕樣式，位置與
大小由 `subtitle/exporter.py` 的 `burn_layout` 算——與燒錄用同一套規則，預
覽長得跟燒出來的一樣（水平一律置中，因為燒錄就是這樣）。

畫面下方是時間軸（`gui_qt/timeline.py`，第 4 項）：縮圖、波形、字幕塊、播
放頭，跟播放器雙向同步——播放時播放頭跟著走，點時間軸就跳過去。點字幕塊跳
到那句開頭；拖字幕塊的左右邊改時間，放開後回寫到 `self.cues`，畫面上的字幕立
刻照新時間顯示。改時間可以復原／重做（Ctrl+Z／Ctrl+Y），存回載入的 .srt／.vtt
（Ctrl+S，第一次覆蓋前留一份 `.bak`）；有沒存的修改時，換字幕或關視窗會先問。

時間軸上方的「剪點」選單（第 5 項）：選停頓跳剪／重複片段／審片建議，就把那種
自動剪輯會剪掉的段落畫在時間軸上（`subtitle/cutmarks.py`，照一般版剪片用的同一
份程式算、同一份 config 參數），旁邊一行寫幾處、剪掉幾秒。字幕的時間一改，剪點
跟著重算。只是看，不會剪片也不改字幕。

還沒做：剪點可拖、可單獨停用（第 5 項下一階段）、與字幕清單雙向同步。見
`docs/ROADMAP_3.0.md`。
"""
import os

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, QUrl, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetricsF, QKeySequence, QPainter, QPainterPath, QPen,
    QShortcut,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QGraphicsItem, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSlider, QVBoxLayout,
    QWidget,
)

from gui_qt.timeline import FFMPEG_MISSING, TimelineLoader, TimelineView
from subtitle import cueedit, cutmarks
from subtitle.cuetime import CueIndex
from subtitle.exporter import burn_layout, dynamic_frame, split_emphasis_segments
from subtitle.importer import load_subtitle_file


def format_clock(ms):
    """毫秒 → 「分:秒.十分之一秒」，播放器時間顯示用。"""
    ms = max(0, int(ms))
    minutes, rest = divmod(ms, 60000)
    return f"{minutes:02d}:{rest // 1000:02d}.{(rest % 1000) // 100}"


class OutlinedText(QGraphicsItem):
    """
    有邊框的字幕文字，多行各自置中，可指定文字色、邊框色與寬度、重點字上色。

    不用 `QGraphicsSimpleTextItem.setPen`：那個描邊是畫在字的**上面**，邊框
    把字吃掉一半，截圖上幾乎讀不出來（實際踩到）。這裡先用粗筆描外框、再
    把字填在上面——跟燒錄（libass）同一種畫法：ASS 的 Outline 是字形外擴
    的寬度，所以筆寬是它的兩倍（一半被字蓋住）。
    """

    def __init__(self):
        super().__init__()
        self._text = ""
        self._font = QFont()
        self._outline = 3.0
        self._text_color = QColor(255, 255, 255)
        self._stroke_color = QColor(0, 0, 0)
        self._emphasis_words = []
        self._emphasis_color = QColor(255, 215, 0)
        self._segments = None    # 逐字動態字幕：[(片段, 是否亮起)]；None＝一般整句
        self.pop_scale = 1.0     # word 模式剛出現的字的縮放（place_subtitle 依對齊點套用）
        self._runs = []          # [(QPainterPath, QColor)]
        self._path = QPainterPath()
        self._rect = QRectF()

    def text(self):
        return self._text

    def font(self):
        return QFont(self._font)

    def setText(self, text):  # noqa: N802 —— 與 Qt 項目同名，呼叫端不用改
        self._text = text or ""
        self._rebuild()

    def set_segments(self, segments, scale=1.0):
        """逐字動態字幕：整句分成片段、亮起的片段用重點色（與燒錄的 highlight 同色）。"""
        self._segments = list(segments)
        self._text = "".join(piece for piece, _lit in self._segments)
        self.pop_scale = float(scale)
        self._rebuild()

    def clear_segments(self):
        self._segments = None
        self.pop_scale = 1.0

    def segments(self):
        return list(self._segments) if self._segments is not None else None

    def setFont(self, font):  # noqa: N802
        self._font = QFont(font)
        self._rebuild()

    def set_look(self, text_color, stroke_color, outline_px,
                 emphasis_words=(), emphasis_color="#FFD700"):
        """文字色、邊框色、邊框寬（像素，0＝無邊框）、重點字與其顏色。"""
        self._text_color = QColor(text_color)
        self._stroke_color = QColor(stroke_color)
        self._outline = max(0.0, float(outline_px))
        self._emphasis_words = list(emphasis_words)
        self._emphasis_color = QColor(emphasis_color)
        self._rebuild()

    def _rebuild(self):
        self.prepareGeometryChange()
        metrics = QFontMetricsF(self._font)
        lines = self._text.split("\n") if self._text else []
        widest = max((metrics.horizontalAdvance(ln) for ln in lines), default=0.0)
        runs, whole = [], QPainterPath()
        for i, line in enumerate(lines):
            x = (widest - metrics.horizontalAdvance(line)) / 2
            baseline = metrics.ascent() + i * metrics.lineSpacing()
            if self._segments is not None:
                # 燒錄時逐字動態字幕不套重點字，只有「目前的字」換色
                pieces = self._segments
            elif self._emphasis_words:
                pieces = split_emphasis_segments(line, self._emphasis_words)
            else:
                pieces = [(line, False)]
            for piece, emphasized in pieces:
                path = QPainterPath()
                path.addText(QPointF(x, baseline), self._font, piece)
                runs.append((path, self._emphasis_color if emphasized else self._text_color))
                whole.addPath(path)
                x += metrics.horizontalAdvance(piece)
        self._runs, self._path = runs, whole
        height = metrics.lineSpacing() * len(lines) if lines else 0.0
        pad = self._outline
        self._rect = QRectF(-pad, -pad, widest + 2 * pad, height + 2 * pad)
        self.update()

    def text_rect(self):
        """字本身（不含邊框留白）在項目座標裡的範圍：對齊用。"""
        pad = self._outline
        return self._rect.adjusted(pad, pad, -pad, -pad)

    def boundingRect(self):  # noqa: N802
        return self._rect

    def paint(self, painter, _option, _widget=None):
        if not self._text:
            return
        painter.setRenderHint(QPainter.Antialiasing)
        if self._outline > 0:
            pen = QPen(self._stroke_color, self._outline * 2)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.strokePath(self._path, pen)
        for path, color in self._runs:
            painter.fillPath(path, QBrush(color))


class _VideoView(QGraphicsView):
    """影片＋字幕疊加層；視窗大小改變時讓影片塞滿、字幕重新定位。"""

    resized = Signal()

    def resizeEvent(self, event):  # noqa: N802 —— Qt 的命名
        super().resizeEvent(event)
        self.resized.emit()


class PlayerPanel(QWidget):
    """播放器面板：開影片、載字幕、播放／暫停、拖曳跳轉，字幕疊在畫面上。"""

    def __init__(self, parent=None, style=None, config=None):
        super().__init__(parent)
        self._style = dict(style or {})
        self._config = config if config is not None else {}  # 剪點參數（jumpcut／retakes／review）
        self.cut_plan = None    # 目前畫在時間軸上的剪點（cutmarks.plan 的結果）；None＝不顯示
        self._index = CueIndex([])
        self._subtitle_path = ""
        self._shown = ("", None, 1.0)  # 疊加層目前畫的是什麼：(文字, 片段, 縮放)
        self.cues = []          # 目前的字幕（複本）；時間軸上拖曳改的時間回寫到這裡
        self.history = cueedit.EditHistory()
        self._saved_cues = []   # 上次存檔（或載入）時的樣子：拿來算「改過幾處」
        self._save_note = ""    # 剛存完檔的說明（存到哪、備份在哪），下一次修改就拿掉

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

        self.timeline = TimelineView()
        self.loader = TimelineLoader(self)
        self._fitted = False
        self.undo_btn = QPushButton("復原")
        self.redo_btn = QPushButton("重做")
        self.save_btn = QPushButton("存字幕")
        self.undo_btn.setToolTip("復原上一次改的時間（Ctrl+Z）")
        self.redo_btn.setToolTip("重做（Ctrl+Y 或 Ctrl+Shift+Z）")
        self.save_btn.setToolTip("存回載入的字幕檔（Ctrl+S）；第一次覆蓋前會把原檔留一份 .bak")
        self.zoom_out_btn = QPushButton("拉遠")
        self.zoom_in_btn = QPushButton("拉近")
        self.fit_btn = QPushButton("整支")
        for w in (self.zoom_out_btn, self.zoom_in_btn, self.fit_btn):
            w.setToolTip("時間軸縮放（也可以按住 Ctrl 轉滾輪）")

        self.cut_combo = QComboBox()
        self.cut_combo.addItem("不顯示", "")
        for source in cutmarks.SOURCES:
            self.cut_combo.addItem(cutmarks.SOURCE_LABELS[source], source)
        self.cut_combo.setToolTip("把自動剪輯會剪掉的段落畫在時間軸上（只是看，不會剪片）；"
                                  "參數跟一般版的設定同一份")
        self.cut_label = QLabel("")

        controls = QHBoxLayout()
        for w in (self.open_btn, self.subs_btn, self.play_btn):
            controls.addWidget(w)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time_label)

        footer = QHBoxLayout()
        footer.addWidget(self.info_label, 1)
        for w in (self.undo_btn, self.redo_btn, self.save_btn):
            footer.addWidget(w)
        footer.addSpacing(12)
        for w in (self.zoom_out_btn, self.zoom_in_btn, self.fit_btn):
            footer.addWidget(w)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.view, 1)
        layout.addLayout(controls)
        cut_row = QHBoxLayout()
        cut_row.addWidget(QLabel("剪點："))
        cut_row.addWidget(self.cut_combo)
        cut_row.addWidget(self.cut_label, 1)
        layout.addLayout(cut_row)
        layout.addWidget(self.timeline)
        layout.addLayout(footer)

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
        self.timeline.seekRequested.connect(self.player.setPosition)
        self.timeline.cueTimesChanged.connect(self._on_cue_times)
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn.clicked.connect(self.redo)
        self.save_btn.clicked.connect(self.save)
        # 快捷鍵只在這一頁（焦點在播放器面板裡）有效，其他頁以後有自己的復原。
        for seq, slot in edit_shortcuts(self.undo, self.redo, self.save):
            shortcut = QShortcut(seq, self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
        self._update_edit_buttons()
        self.zoom_out_btn.clicked.connect(self.timeline.zoom_out)
        self.zoom_in_btn.clicked.connect(self.timeline.zoom_in)
        self.fit_btn.clicked.connect(self.timeline.zoom_to_fit)
        self.cut_combo.currentIndexChanged.connect(lambda _i: self.refresh_cut_marks())
        self.loader.peaksReady.connect(self._on_peaks)
        self.loader.filmstripReady.connect(self._on_filmstrip)
        self.loader.failed.connect(self._on_timeline_failed)

    # ---- 對外 ----------------------------------------------------------

    def open_video(self, path):
        self.player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
        self.play_btn.setEnabled(True)
        self.slider.setEnabled(True)
        self.info_label.setText(f"影片：{os.path.basename(path)}" + self._subs_note())
        # 時間軸：清掉上一支的資料，背景重新抽（舊的工作取消、晚到的結果丟掉）
        self._fitted = False
        self.timeline.reset("正在分析波形…", "正在抽縮圖…")
        self.loader.load(os.path.abspath(path))

    def set_cues(self, cues, source=""):
        """換一份字幕；畫面上的那句與時間軸上的字幕塊立刻跟著更新。"""
        self.cues = [dict(c) for c in (cues or [])]
        self.history.clear()
        self._saved_cues = [dict(c) for c in self.cues]
        self._save_note = ""
        self._index = CueIndex(self.cues)
        self._subtitle_path = source
        self.timeline.set_cues(self.cues)
        self._show_at(self.player.position())
        self._refresh_info()
        self.refresh_cut_marks()

    def load_subtitles(self, path):
        data = load_subtitle_file(path)
        self.set_cues(data["cues"], path)
        return data

    def set_style(self, style):
        """換字幕樣式（config 的 subtitle_style）；畫面上那句立刻重畫。"""
        self._style = dict(style or {})
        self._show_at(self.player.position())  # 動態模式可能換了：照新模式重算這一刻
        self._place_subtitle()

    def show_cut_marks(self, source):
        """選要畫哪一種剪點（cutmarks.SOURCES 之一；空字串＝不顯示）。"""
        at = self.cut_combo.findData(source or "")
        if at < 0:
            raise ValueError(f"不認得的剪點來源：{source!r}")
        if at == self.cut_combo.currentIndex():
            self.refresh_cut_marks()
        else:
            self.cut_combo.setCurrentIndex(at)  # 會觸發 refresh_cut_marks

    def refresh_cut_marks(self):
        """照目前的字幕、片長與選單重算剪點，畫到時間軸上。"""
        source = self.cut_combo.currentData()
        if not source:
            self.cut_plan = None
            self.timeline.set_cut_marks([])
            self.cut_label.setText("")
            return
        duration = max(self.player.duration(), 0) / 1000.0
        self.cut_plan = cutmarks.plan(source, self.cues, duration, self._config)
        self.timeline.set_cut_marks(self.cut_plan["marks"])
        text = cutmarks.summary(self.cut_plan)
        if self.cut_plan["marks"] and not duration:
            text += "　還沒開影片：片尾的空白先不算"
        self.cut_label.setText(text)

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def current_subtitle_text(self):
        """畫面上此刻疊著的字幕（沒有就是空字串）。給測試與之後的時間軸用。"""
        return self.subtitle_item.text() if self.subtitle_item.isVisible() else ""

    # ---- 內部 ----------------------------------------------------------

    def unsaved_changes(self):
        """跟上次存檔（或載入）時相比，時間不一樣的句數。"""
        return cueedit.changed_count(self.cues, self._saved_cues)

    def undo(self):
        self._step(self.history.undo(self.cues))

    def redo(self):
        self._step(self.history.redo(self.cues))

    def save(self):
        """存回載入的字幕檔；沒有檔名（或不是 .srt／.vtt）時先問要存到哪。回傳是否存成功。"""
        path = self._subtitle_path
        if not path or os.path.splitext(path)[1].lower() not in (".srt", ".vtt"):
            path = self._ask_save_path(path)
            if not path:
                return False
        try:
            result = cueedit.save_cues(self.cues, path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "存字幕", f"沒有存成功：{exc}")
            return False
        self._subtitle_path = path
        self._saved_cues = [dict(c) for c in self.cues]
        note = f"已存到 {os.path.basename(path)}"
        if result["backup"]:
            note += f"；原檔留在 {os.path.basename(result['backup'])}"
        self._save_note = note
        self._refresh_info()
        return True

    def maybe_discard(self):
        """有沒存的修改時先問：存檔／放棄／取消。回傳 True＝可以繼續（已存或放棄）。"""
        if not self.unsaved_changes():
            return True
        answer = self._ask_discard()
        if answer == "save":
            return self.save()
        return answer == "discard"

    def _subs_note(self):
        if not len(self._index):
            return "　字幕：尚未載入"
        name = os.path.basename(self._subtitle_path) if self._subtitle_path else "（目前的字幕）"
        note = f"　字幕：{name}，{len(self._index)} 句"
        changed = self.unsaved_changes()
        if changed:
            note += f"（時間改過 {changed} 處，尚未存檔）"
        elif self._save_note:
            note += f"（{self._save_note}）"
        return note

    def _refresh_info(self):
        name = os.path.basename(self.player.source().toLocalFile())
        self.info_label.setText((f"影片：{name}" if name else "還沒開啟影片。")
                                + self._subs_note())
        self._update_edit_buttons()

    def _update_edit_buttons(self):
        self.undo_btn.setEnabled(self.history.can_undo())
        self.redo_btn.setEnabled(self.history.can_redo())
        self.save_btn.setEnabled(bool(self.cues))

    def _on_cue_times(self, index, start, end):
        """時間軸上拖了某句的邊：回寫字幕清單，畫面上的那句立刻照新時間顯示。"""
        if not 0 <= index < len(self.cues):
            return
        before = (self.cues[index]["start"], self.cues[index]["end"])
        self.history.record(index, before, (start, end))
        self.cues = cueedit.with_times(self.cues, index, start, end)
        self._after_edit()

    def _step(self, result):
        """套用復原或重做的結果：時間軸重畫並選取改到的那句（看得到剛剛變了什麼）。"""
        if result is None:
            return
        self.cues, index = result
        self.timeline.set_cues(self.cues, keep_selection=True)
        self.timeline.select_cue(index, seek=False)
        self._after_edit()

    def _after_edit(self):
        self._save_note = ""
        self._index = CueIndex(self.cues)
        self._show_at(self.player.position())
        self._refresh_info()
        self.refresh_cut_marks()  # 字幕時間變了，停頓與重講的位置跟著變

    def _ask_save_path(self, suggested):
        base = os.path.splitext(suggested)[0] + ".srt" if suggested else ""
        path, _ = QFileDialog.getSaveFileName(self, "存字幕", base, "SRT 字幕 (*.srt);;WebVTT 字幕 (*.vtt)")
        return path

    def _ask_discard(self):
        """回傳 "save"／"discard"／"cancel"。"""
        box = QMessageBox(self)
        box.setWindowTitle("還沒存檔")
        box.setText(f"字幕的時間改過 {self.unsaved_changes()} 處，還沒存檔。")
        save = box.addButton("存檔", QMessageBox.AcceptRole)
        discard = box.addButton("不存，放棄修改", QMessageBox.DestructiveRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        return "save" if clicked is save else "discard" if clicked is discard else "cancel"

    def _choose_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "開啟影片", "", "影片 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v);;所有檔案 (*)")
        if path:
            self.open_video(path)

    def _choose_subtitles(self):
        if not self.maybe_discard():
            return
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
        self.timeline.set_position(ms)

    def _on_duration(self, ms):
        self.slider.setRange(0, ms)
        self.timeline.set_duration(ms / 1000.0)
        if ms > 0 and not self._fitted:
            # 一開片子先讓整支塞滿時間軸，要細看再拉近
            self._fitted = True
            self.timeline.zoom_to_fit()
        self._on_position(self.player.position())
        self.refresh_cut_marks()  # 知道片長之後，片尾的空白才算得出來

    def _on_peaks(self, gen, peaks):
        if gen == self.loader.generation:
            self.timeline.set_peaks(peaks)

    def _on_filmstrip(self, gen, strip):
        if gen == self.loader.generation:
            self.timeline.set_filmstrip(strip)

    def _on_timeline_failed(self, gen, kind, reason):
        if gen != self.loader.generation:
            return
        if reason == FFMPEG_MISSING:  # 不是片子的問題，講清楚缺什麼
            what = "波形" if kind == "wave" else "縮圖"
            note = f"時間軸的{what}{reason}"
            if kind == "wave":
                self.timeline.set_peaks(None, note)
            else:
                self.timeline.set_filmstrip(None, note)
            return
        if kind == "wave":
            self.timeline.set_peaks(None, f"這支影片沒有可畫的波形（{reason}）")
        else:
            self.timeline.set_filmstrip(None, f"這支影片抽不出縮圖（{reason}）")

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
        seconds = ms / 1000.0
        cue = self._index.at(seconds)
        mode = str(self._style.get("dynamic_mode") or "off")
        frame = dynamic_frame(cue, mode, seconds) if cue else None
        if frame is None:
            state = (cue["text"] if cue else "", None, 1.0)
        else:
            # 逐字動態字幕（karaoke／word）：照燒錄的規則算這一刻顯示什麼
            state = ("".join(p for p, _lit in frame["segments"]),
                     tuple(frame["segments"]), round(frame["scale"], 3))
        if state == self._shown:
            return
        self._shown = state
        text, segments, scale = state
        if segments is None:
            self.subtitle_item.clear_segments()
            self.subtitle_item.setText(text)
        else:
            self.subtitle_item.set_segments(segments, scale)
        self.subtitle_item.setVisible(bool(text))
        self._place_subtitle()

    def current_subtitle_segments(self):
        """逐字動態字幕此刻的片段 [(片段, 是否亮起)]；一般整句時是 None。給測試用。"""
        return self.subtitle_item.segments() if self.subtitle_item.isVisible() else None

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
        place_subtitle(self.subtitle_item, self._video_rect(), self._style)


def edit_shortcuts(undo, redo, save):
    """
    [(按鍵, 動作)]：各平台的標準按鍵，重做再補上 Ctrl+Y 與 Ctrl+Shift+Z（兩種習慣都
    有人用）。**同一組按鍵只註冊一次**——Windows 與部分 Linux 的標準「重做」本來就
    含 Ctrl+Y，重複註冊時 Qt 判定為衝突，兩個都不觸發。
    """
    wanted = (
        (QKeySequence.keyBindings(QKeySequence.StandardKey.Undo), undo),
        (QKeySequence.keyBindings(QKeySequence.StandardKey.Redo)
         + [QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")], redo),
        (QKeySequence.keyBindings(QKeySequence.StandardKey.Save), save),
    )
    out, seen = [], set()
    for sequences, slot in wanted:
        for seq in sequences:
            text = seq.toString(QKeySequence.PortableText)
            if text and text not in seen:
                seen.add(text)
                out.append((seq, slot))
    return out


def ass_font(family, size_px):
    """
    換算成跟 libass 一樣大的 QFont。

    ASS 的 Fontsize 是**整行高度**（字型的上伸＋下伸），Qt 的 pixelSize 是
    字身（em）。直接拿來用，字會比燒錄出來的大兩成左右（跟真的燒錄比對量
    到的）。先用 size_px 當 pixelSize 量出行高，再等比縮回去。
    """
    font = QFont(family)
    font.setPixelSize(max(1, round(size_px)))
    metrics = QFontMetricsF(font)
    line = metrics.ascent() + metrics.descent()
    if line > 0:
        font.setPixelSize(max(1, round(size_px * size_px / line)))
    return font


def place_subtitle(item, rect, style):
    """
    依字幕樣式把 item 擺到影片矩形 rect 裡燒錄時會出現的位置、套上燒錄時的
    大小與顏色。抽成獨立函式，測試才能拿同一套擺法畫在圖上跟真的燒錄比對。
    """
    look = burn_layout(style, rect.width(), rect.height())
    item.setFont(ass_font(look["font_family"], look["font_px"]))
    item.set_look(look["text_color"], look["stroke_color"], look["outline_px"],
                  look["emphasis_words"], look["emphasis_color"])
    # 對齊看的是字本身（不含邊框留白），跟 libass 用字的範圍對齊一樣。
    box = item.text_rect()
    x = rect.left() + look["center_x"] - box.width() / 2 - box.left()
    anchor_y = rect.top() + look["anchor_y"]
    if look["anchor"] == "bottom":
        y = anchor_y - box.height() - box.top()
    elif look["anchor"] == "top":
        y = anchor_y - box.top()
    else:
        y = anchor_y - box.height() / 2 - box.top()
    item.setPos(x, y)
    # word 模式的彈出縮放：以對齊點為中心（置底縮向底邊中央、置頂縮向頂邊中央），
    # 跟 libass 排版時先縮放字形、再依對齊點擺放的結果一樣。
    scale = getattr(item, "pop_scale", 1.0)
    origin_y = {"bottom": box.bottom(), "top": box.top()}.get(look["anchor"], box.center().y())
    item.setTransformOriginPoint(QPointF(box.center().x(), origin_y))
    item.setScale(scale)
