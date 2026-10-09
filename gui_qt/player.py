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

剪點可以微調（第 5 項第二階段）：時間軸最下面的剪點列點一下停用／啟用、拖左右邊調
整範圍。微調記在 `self.cut_overrides`（依剪點的 key），字幕改了、剪點重算時，停頓
本身沒變的剪點會保留微調；「還原剪點」清掉目前這種來源的微調。剪點的微調不進字幕的
復原／重做（兩件事分開：Ctrl+Z 只退字幕的時間）。

「照剪點輸出…」（第 5 項第三階段）：照啟用中的剪點（含停用與拖過的範圍）剪出一支新
影片，旁邊放一份對齊到剪後時間軸的字幕（同檔名 .srt）。剪片在背景執行緒跑
（`cutmarks.render`，跟一般版的跳剪同一個裁切引擎），進度寫在剪點那一行；原始影片
與目前的字幕都不動。

代理檔（第 6 項）：短邊 1080 以上的影片，編輯時換成短邊 540、關鍵影格密的代理檔播
（`subtitle/proxy.py`），跳轉快很多；快取裡沒有就先用原檔、背景做一份，做好了在同一
個位置無縫換過去。縮圖、波形、剪點與「照剪點輸出」一律用原檔，時間以原檔的片長為準。
「編輯用代理檔」可以關掉（讀 config 的 `qt_proxy`，預設開；Qt 預覽版還不寫回
config.json，關掉只算這一次）。

素材軌（第 7 項第二階段）：「加入畫面…」「加入音樂…」在播放頭的位置放一段疊加的影片
／圖片或背景音樂，畫在時間軸的兩條素材軌上，可以拖位置、選取後按 Delete 刪；「輸出多
軌…」照這份時間軸（`subtitle/assemble.py`）把原檔連同素材合成一支新影片，字幕原封不
動放一份同檔名 .srt。換一支影片素材軌就清掉。

修頭尾與素材屬性（第 7 項第三階段）：時間軸上拖素材的左右邊修頭尾；選取一段素材後，
「素材屬性」那一行可以改音樂的音量／循環到片尾／講話時壓低，與畫面的位置（蓋滿或四
個角落的小畫面）／帶聲音。改了先用 `assemble.normalize` 檢查，不合理就不收。

疊加預覽（第 7 項第四階段）：播放時照輸出的位置把畫面素材疊在影片上、字幕底下
（`gui_qt/overlay_preview.py`）；圖片照實畫，影片素材每秒換一格（不是連續播放）。
「預覽畫面素材」可以關掉。音樂還不會跟著播、素材的修改拖不進復原。

跟剪點一起輸出（第 7 項第五階段）：時間軸上顯示著剪點、而且有啟用的剪點時，「輸出多
軌…」照剪點一起剪（`assemble.apply_cuts`）：主軌只留沒剪掉的部分，畫面素材蓋到剪掉的
地方那一截跟著裁掉、其餘平移，音樂平移後一路播（不跟著一跳一跳）；字幕對齊到剪後的時
間軸。不要剪就把剪點選單切到「不顯示」。

還沒做：與字幕清單雙向同步。見 `docs/ROADMAP_3.0.md`。
"""
import os
import threading

from PySide6.QtCore import QObject, QPointF, QRectF, QSizeF, Qt, QUrl, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetricsF, QKeySequence, QPainter, QPainterPath, QPen,
    QShortcut,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGraphicsItem, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSizePolicy, QSlider, QSpinBox, QVBoxLayout,
    QWidget,
)

from gui_qt import timeline as timeline_mod
from gui_qt.overlay_preview import OverlayPreview
from gui_qt.timeline import FFMPEG_MISSING, TimelineLoader, TimelineView
from subtitle import assemble as assemble_mod
from subtitle import cueedit, cutmarks
from subtitle import proxy as proxy_mod
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
        self.cut_overrides = {}  # 使用者對剪點的微調：{key: {"enabled", "start", "end"}}
        self._index = CueIndex([])
        self._subtitle_path = ""
        self._shown = ("", None, 1.0)  # 疊加層目前畫的是什麼：(文字, 片段, 縮放)
        self.cues = []          # 目前的字幕（複本）；時間軸上拖曳改的時間回寫到這裡
        self.history = cueedit.EditHistory()
        self._saved_cues = []   # 上次存檔（或載入）時的樣子：拿來算「改過幾處」
        self._save_note = ""    # 剛存完檔的說明（存到哪、備份在哪），下一次修改就拿掉
        self.media_path = ""    # 開的影片（原檔）；剪片、縮圖、波形都用它
        self.proxy_path = ""    # 目前播的代理檔；空字串＝播原檔
        self.proxy_note = ""    # 代理檔的狀況（寫在影片名稱後面）
        self._orig_duration = 0.0  # 原檔片長（秒）；播代理檔時剪點與輸出照這個算
        self._pending_seek = None  # 換片源（原檔⇄代理檔）後要回到的 (位置 ms, 是否在播)

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
        # 疊加軌的預覽（第 7 項第四階段）：疊在影片上、字幕底下
        self.overlay_preview = OverlayPreview(self.scene, self)

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
        self.proxy_box = QCheckBox("編輯用代理檔")
        self.proxy_box.setToolTip("1080p 以上的影片編輯時改播小一號、好跳轉的版本（第一次開要先做一份，"
                                  "放在 proxy_cache）；輸出一律用原檔")
        self.proxy_box.setChecked(bool(self._config.get("qt_proxy", True)))
        self.proxy_maker = ProxyMaker(self)
        for w in (self.zoom_out_btn, self.zoom_in_btn, self.fit_btn):
            w.setToolTip("時間軸縮放（也可以按住 Ctrl 轉滾輪）")

        self.cut_combo = QComboBox()
        self.cut_combo.addItem("不顯示", "")
        for source in cutmarks.SOURCES:
            self.cut_combo.addItem(cutmarks.SOURCE_LABELS[source], source)
        self.cut_combo.setToolTip("把自動剪輯會剪掉的段落畫在時間軸上（只是看，不會剪片）；"
                                  "參數跟一般版的設定同一份")
        self.cut_label = QLabel("")
        self.cut_reset_btn = QPushButton("還原剪點")
        self.cut_reset_btn.setToolTip("清掉這種剪點的停用與範圍調整，回到自動算出來的樣子")
        self.cut_reset_btn.setEnabled(False)
        self.export_btn = QPushButton("照剪點輸出…")
        self.export_btn.setToolTip("照時間軸上啟用中的剪點剪出一支新影片，旁邊放一份對齊好的字幕；"
                                   "原始影片不動")
        self.export_btn.setEnabled(False)
        self.exporter = CutExporter(self)
        self.last_export = None  # 上一次輸出成功的結果（給測試與提示用）

        # 素材軌（3.0 第 7 項第二階段）：疊加的畫面與背景音樂，照 assemble 的時間軸格式
        self.tracks = {"overlays": [], "music": []}
        self.add_overlay_btn = QPushButton("加入畫面…")
        self.add_overlay_btn.setToolTip("在播放頭的位置疊一段影片或圖片（預設蓋滿整個畫面、不帶聲音）")
        self.add_music_btn = QPushButton("加入音樂…")
        self.add_music_btn.setToolTip("在播放頭的位置放一段背景音樂（預設音量 35%、有人講話時自動壓低）")
        self.remove_track_btn = QPushButton("刪除選取")
        self.remove_track_btn.setToolTip("刪掉時間軸上選取的那段素材（也可以按 Delete）")
        self.track_label = QLabel("")
        self.assemble_btn = QPushButton("輸出多軌…")
        self.assemble_btn.setToolTip("把影片連同素材軌合成一支新影片，旁邊放一份字幕；原始影片不動")
        self.track_exporter = TrackExporter(self)
        self.preview_box = QCheckBox("預覽畫面素材")
        self.preview_box.setToolTip("播放器上照輸出的位置疊出畫面素材：圖片照實畫，影片每秒換一格"
                                    "（不是連續播放）；音樂要輸出才聽得到")
        self.preview_box.setChecked(True)
        # 素材屬性（第三階段）：選取時間軸上的一段素材後才有東西可改
        self.prop_label = QLabel(PROP_HINT)
        self.volume_spin = QSpinBox()
        self.volume_spin.setRange(0, 200)
        self.volume_spin.setSingleStep(5)
        self.volume_spin.setSuffix("%")
        self.volume_spin.setPrefix("音量 ")
        self.volume_spin.setToolTip("配樂的音量（100%＝原本的大小）")
        self.loop_box = QCheckBox("循環到片尾")
        self.loop_box.setToolTip("音樂放完從頭再放，一路到片尾（勾了之後只能修頭）")
        self.duck_box = QCheckBox("講話時壓低")
        self.duck_box.setToolTip("有人講話時自動把音樂壓低（照一般版的閃避設定）")
        self.position_combo = QComboBox()
        for key, label, _rect in assemble_mod.OVERLAY_POSITIONS:
            self.position_combo.addItem(label, key)
        self.position_combo.setToolTip("疊上去的畫面放在哪裡：蓋滿，或四個角落的小畫面")
        self.overlay_audio_box = QCheckBox("帶聲音")
        self.overlay_audio_box.setToolTip("疊加的影片自己的聲音也混進去（預設不帶，只用畫面）")
        self._prop_widgets = {"music": (self.volume_spin, self.loop_box, self.duck_box),
                              "overlays": (self.position_combo, self.overlay_audio_box)}
        self.last_assemble = None  # 上一次多軌輸出成功的結果

        controls = QHBoxLayout()
        for w in (self.open_btn, self.subs_btn, self.play_btn):
            controls.addWidget(w)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time_label)

        footer = QHBoxLayout()
        footer.addWidget(self.info_label, 1)
        footer.addWidget(self.proxy_box)
        footer.addSpacing(12)
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
        cut_row.addWidget(self.cut_reset_btn)
        cut_row.addWidget(self.export_btn)
        layout.addLayout(cut_row)
        # 素材軌與選取那段的屬性擠在同一行：每多一行，1280x800 的影片畫面就矮一截
        # （test_qt_cutedit 守著影片至少 300px 高）。摘要放不下就截掉，滑鼠停著看全文。
        track_row = QHBoxLayout()
        track_row.addWidget(QLabel("素材軌："))
        for w in (self.add_overlay_btn, self.add_music_btn, self.remove_track_btn):
            track_row.addWidget(w)
        track_row.addSpacing(8)
        track_row.addWidget(self.prop_label)
        for widgets in self._prop_widgets.values():
            for w in widgets:
                track_row.addWidget(w)
        track_row.addSpacing(8)
        self.track_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        track_row.addWidget(self.track_label, 1)
        track_row.addWidget(self.preview_box)
        track_row.addWidget(self.assemble_btn)
        layout.addLayout(track_row)
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
        self.cut_reset_btn.clicked.connect(self.reset_cut_marks)
        self.export_btn.clicked.connect(lambda: self.export_cuts())
        self.exporter.progress.connect(self._on_export_progress)
        self.exporter.finished.connect(self._on_export_done)
        self.exporter.failed.connect(self._on_export_failed)
        self.add_overlay_btn.clicked.connect(lambda: self.add_track("overlays"))
        self.add_music_btn.clicked.connect(lambda: self.add_track("music"))
        self.remove_track_btn.clicked.connect(self.remove_selected_track)
        self.assemble_btn.clicked.connect(lambda: self.export_tracks())
        self.track_exporter.progress.connect(self._on_assemble_progress)
        self.track_exporter.finished.connect(self._on_assemble_done)
        self.track_exporter.failed.connect(self._on_assemble_failed)
        self.timeline.trackItemSelected.connect(lambda _k, _i: self._update_track_buttons())
        self.timeline.trackItemChanged.connect(self._on_track_changed)
        self.preview_box.toggled.connect(lambda _on: self.refresh_tracks())
        self.overlay_preview.updated.connect(self.refresh_overlays)
        self.volume_spin.valueChanged.connect(
            lambda v: self.set_track_props(volume=round(v / 100.0, 2)))
        self.loop_box.toggled.connect(lambda on: self.set_track_props(loop=bool(on)))
        self.duck_box.toggled.connect(lambda on: self.set_track_props(duck=bool(on)))
        self.position_combo.currentIndexChanged.connect(
            lambda _i: self.set_track_props(rect=assemble_mod.position_rect(self.position_combo.currentData())))
        self.overlay_audio_box.toggled.connect(lambda on: self.set_track_props(audio=bool(on)))
        self.timeline.trackItemMoved.connect(self._on_track_moved)
        self.timeline.trackItemDeleteRequested.connect(self.remove_track)
        self.timeline.cutMarkToggled.connect(self._on_cut_toggled)
        self.timeline.cutMarkChanged.connect(self._on_cut_changed)
        self.proxy_box.toggled.connect(self._on_proxy_toggled)
        self.proxy_maker.progress.connect(self._on_proxy_progress)
        self.proxy_maker.ready.connect(self._on_proxy_ready)
        self.proxy_maker.failed.connect(self._on_proxy_failed)
        self.loader.peaksReady.connect(self._on_peaks)
        self.loader.filmstripReady.connect(self._on_filmstrip)
        self.loader.failed.connect(self._on_timeline_failed)
        self._update_track_buttons()

    # ---- 對外 ----------------------------------------------------------

    def open_video(self, path):
        path = os.path.abspath(path)
        self.media_path = path
        self.proxy_maker.cancel()
        self.proxy_path, self.proxy_note = "", ""
        self._orig_duration = 0.0
        self._pending_seek = None
        source = self._find_proxy() if self.proxy_box.isChecked() else ""
        self.player.setSource(QUrl.fromLocalFile(source or path))
        self.play_btn.setEnabled(True)
        self.slider.setEnabled(True)
        self._refresh_info()
        # 時間軸：清掉上一支的資料，背景重新抽（舊的工作取消、晚到的結果丟掉）
        self._fitted = False
        self.timeline.reset("正在分析波形…", "正在抽縮圖…")
        self.loader.load(os.path.abspath(path))
        # 素材軌的位置是照上一支的片長放的，換片子就清掉
        self.tracks = {"overlays": [], "music": []}
        self.refresh_tracks()

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
            self.cut_reset_btn.setEnabled(False)
            self._update_export_button()
            return
        duration = self.media_duration()
        plan = cutmarks.plan(source, self.cues, duration, self._config)
        plan["marks"] = cutmarks.apply_overrides(plan["marks"], self.cut_overrides)
        self.cut_plan = cutmarks.recount(plan)
        self.timeline.set_cut_marks(self.cut_plan["marks"])
        self.cut_reset_btn.setEnabled(any(
            m.get("edited") or not m.get("enabled", True) for m in self.cut_plan["marks"]))
        text = cutmarks.summary(self.cut_plan)
        if self.cut_plan["marks"] and not duration:
            text += "　還沒開影片：片尾的空白先不算"
        if not self.exporter.busy:  # 輸出中這一行寫進度，別蓋掉
            self.cut_label.setText(text)
        self._update_export_button()

    def _update_export_button(self):
        ready = (self.cut_plan is not None and self.media_duration() > 0
                 and any(m.get("enabled", True) for m in self.cut_plan["marks"]))
        self.export_btn.setEnabled(ready and not self.exporter.busy)
        if hasattr(self, "preview_box") and not self.track_exporter.busy:  # 建構到一半時素材軌還沒建好
            # 剪點變了，多軌輸出會剪掉幾處跟著變
            self.track_label.setText(self._track_summary())
            self.track_label.setToolTip(self.track_label.text())

    def export_cuts(self, output_path=None):
        """
        照啟用中的剪點輸出。output_path 省略時先問要存到哪。回傳是否開始輸出
        （結果由 _on_export_done／_on_export_failed 處理）。
        """
        if self.exporter.busy or self.cut_plan is None:
            return False
        media = self.media_path  # 播的可能是代理檔，剪一律用原檔
        try:
            plan = cutmarks.export_plan(self.cut_plan["marks"], self.media_duration(), self.cues)
        except ValueError as exc:
            self._show_export_error(str(exc))
            return False
        if output_path is None:
            output_path = self._ask_export_path(cutmarks.suggest_output_path(media))
            if not output_path:
                return False
        self.cut_label.setText(f"正在輸出 {os.path.basename(output_path)}…")
        self.exporter.start(media, plan, output_path)
        self._update_export_button()
        return True

    def _ask_export_path(self, suggested):
        path, _ = QFileDialog.getSaveFileName(self, "照剪點輸出", suggested, "MP4 影片 (*.mp4);;所有檔案 (*)")
        return path

    def _show_export_error(self, message):
        QMessageBox.warning(self, "照剪點輸出", message)

    def _on_export_progress(self, ratio, _message):
        self.cut_label.setText(f"正在輸出…{int(round(ratio * 100))}%")

    def _on_export_done(self, result):
        self.last_export = result
        note = f"已輸出 {os.path.basename(result['output'])}（剪掉 {result['cut_count']} 處、" \
               f"{result['removed_seconds']:.1f} 秒）"
        if result["subtitles"]:
            note += f"＋{os.path.basename(result['subtitles'])}"
            if result["dropped"]:
                note += f"（{result['dropped']} 句整句被剪掉）"
        self.cut_label.setText(note)
        self._update_export_button()

    def _on_export_failed(self, message):
        self._update_export_button()
        self.refresh_cut_marks()
        self._show_export_error(f"沒有輸出成功：{message}")

    # ---- 素材軌（3.0 第 7 項第二階段） ------------------------------------

    def refresh_tracks(self, note=None):
        """把素材軌畫到時間軸上，順便更新那一行的說明與按鈕。"""
        self.timeline.set_tracks(self.tracks["overlays"], self.tracks["music"])
        self.refresh_overlays()
        if not self.track_exporter.busy:  # 輸出中這一行寫進度，別蓋掉
            self.track_label.setText(note if note is not None else self._track_summary())
            self.track_label.setToolTip(self.track_label.text())
        self._update_track_buttons()

    def _track_summary(self):
        overlays, music = len(self.tracks["overlays"]), len(self.tracks["music"])
        if not overlays and not music:
            return ""
        parts = []
        if overlays:
            parts.append(f"畫面 {overlays} 段")
        if music:
            parts.append(f"音樂 {music} 段")
        note = "　畫面在播放器上預覽（影片每秒換一格）" if overlays and self.preview_box.isChecked() else ""
        if music:
            note += "　音樂還不會跟著播"
        cuts = self._track_cut_count()
        # 寫在段數後面：這一行太長時尾巴會被截掉，要剪的事不能被截掉
        cut_note = f"（會照剪點一起剪掉 {cuts} 處）" if cuts else ""
        return "、".join(parts) + cut_note + note + "，按「輸出多軌…」合成"

    def _track_cut_count(self):
        """多軌輸出會一起剪掉幾處：時間軸上顯示著剪點時，啟用中的那幾段；沒顯示就是 0。"""
        if self.cut_plan is None:
            return 0
        return sum(1 for m in self.cut_plan["marks"] if m.get("enabled", True))

    def refresh_overlays(self, ms=None):
        """照目前的位置把該出現的畫面素材疊到播放器上（關掉「預覽畫面素材」就全拿掉）。"""
        if not hasattr(self, "preview_box"):  # 建構到一半（版面先排）：素材軌還沒建好
            return
        seconds = (self.player.position() if ms is None else ms) / 1000.0
        native = self.video_item.nativeSize()
        self.overlay_preview.show(self.tracks["overlays"], seconds, self.media_duration(), self._video_rect(),
                                  None if native.isEmpty() else (native.width(), native.height()),
                                  enabled=self.preview_box.isChecked())

    def _update_track_buttons(self):
        ready = bool(self.media_path) and self.media_duration() > 0
        idle = not self.track_exporter.busy
        self.add_overlay_btn.setEnabled(ready and idle)
        self.add_music_btn.setEnabled(ready and idle)
        self.remove_track_btn.setEnabled(idle and self.timeline.track_selected is not None)
        self.assemble_btn.setEnabled(ready and idle and any(self.tracks.values()))
        self._show_track_props()

    def _show_track_props(self):
        """照選取的那段素材填屬性那一行（填的時候不送出修改）；沒選取時只寫怎麼用。"""
        selected = self.timeline.track_selected
        kind = selected[0] if selected and selected[1] < len(self.tracks.get(selected[0], ())) else None
        item = self.tracks[kind][selected[1]] if kind else None
        idle = not self.track_exporter.busy
        for name, widgets in self._prop_widgets.items():
            for w in widgets:
                w.setVisible(name == kind)
                w.setEnabled(idle)
        self.prop_label.setText(os.path.basename(item["path"]) if item else PROP_HINT)
        if not item:
            return
        for widgets in self._prop_widgets.values():
            for w in widgets:
                w.blockSignals(True)
        try:
            if kind == "music":
                self.volume_spin.setValue(int(round(float(item.get("volume", 1.0)) * 100)))
                self.loop_box.setChecked(bool(item.get("loop")))
                self.duck_box.setChecked(bool(item.get("duck")))
            else:
                where = assemble_mod.overlay_position(item)
                self.position_combo.setCurrentIndex(max(self.position_combo.findData(where), 0))
                image = assemble_mod.is_image(item["path"])
                self.overlay_audio_box.setChecked(bool(item.get("audio")) and not image)
                # 圖片沒有聲音可帶
                self.overlay_audio_box.setEnabled(idle and not image)
        finally:
            for widgets in self._prop_widgets.values():
                for w in widgets:
                    w.blockSignals(False)

    def set_track_props(self, **changes):
        """
        改選取的那段素材的屬性（volume／loop／duck／rect／audio）。回傳是否改了；沒選取、
        輸出中、或改了會不合理（normalize 不收）就不改。
        """
        selected = self.timeline.track_selected
        if not selected or self.track_exporter.busy:
            return False
        kind, index = selected
        if not 0 <= index < len(self.tracks.get(kind, ())):
            return False
        item = dict(self.tracks[kind][index], **changes)
        try:
            assemble_mod.normalize({"main": [{"path": self.media_path or "x", "out": self.media_duration()}],
                                    kind: [item]})
        except assemble_mod.AssembleError as exc:
            self._show_track_error(str(exc))
            self._show_track_props()
            return False
        if item == self.tracks[kind][index]:
            return False
        self.tracks[kind][index] = item
        self.refresh_tracks()
        return True

    def _on_track_changed(self, kind, index, item):
        """時間軸上修了頭尾：照新的 dict 改（輸出中不改，放回原樣）。"""
        if 0 <= index < len(self.tracks.get(kind, ())) and not self.track_exporter.busy:
            self.tracks[kind][index] = dict(item)
        self.refresh_tracks()

    def add_track(self, kind, path=None):
        """
        在播放頭的位置加一段素材（kind："overlays"／"music"）。path 省略時先問要哪個檔。
        回傳是否加成功；讀不出來（沒有畫面的檔放畫面軌、沒有聲音的檔放音樂軌、量不到
        長度）就說清楚、不加。
        """
        if kind not in assemble_mod.TRACK_KINDS:
            raise ValueError(f"不認得的軌：{kind!r}")
        total = self.media_duration()
        if not self.media_path or total <= 0 or self.track_exporter.busy:
            return False
        if path is None:
            path = self._ask_track_file(kind)
            if not path:
                return False
        path = os.path.abspath(path)
        at = self.player.position() / 1000.0
        if not os.path.isfile(path):
            self._show_track_error(f"找不到 {os.path.basename(path)}")
            return False
        try:
            info = assemble_mod.probe_media(path)
            if kind == "overlays" and not info["video"]:
                raise assemble_mod.AssembleError(f"{os.path.basename(path)} 沒有畫面，不能放畫面軌")
            if kind == "music" and not info["audio"]:
                raise assemble_mod.AssembleError(f"{os.path.basename(path)} 沒有聲音，不能放音樂軌")
            seconds = assemble_mod.probe_seconds(path)
            make = assemble_mod.new_overlay if kind == "overlays" else assemble_mod.new_music
            item = make(path, at, total, seconds)
        except (assemble_mod.AssembleError, OSError) as exc:
            self._show_track_error(str(exc))
            return False
        self.tracks[kind].append(item)
        self.refresh_tracks()
        self.timeline.select_track_item(kind, len(self.tracks[kind]) - 1, seek=False)
        return True

    def remove_track(self, kind, index):
        if self.track_exporter.busy or not 0 <= index < len(self.tracks.get(kind, ())):
            return False
        del self.tracks[kind][index]
        self.timeline.select_track_item(kind, -1, seek=False)
        self.refresh_tracks()
        return True

    def remove_selected_track(self):
        selected = self.timeline.track_selected
        return self.remove_track(*selected) if selected else False

    def _on_track_moved(self, kind, index, at):
        if 0 <= index < len(self.tracks.get(kind, ())) and not self.track_exporter.busy:
            self.tracks[kind][index]["at"] = assemble_mod.clamp_at(at, self.media_duration())
            self.refresh_tracks()
        else:
            self.refresh_tracks()  # 輸出中不改：拖過去的放回原位

    def timeline_for_export(self):
        """目前的多軌時間軸（assemble 的格式）：主軌是整支原檔（播的可能是代理檔）。"""
        return {"main": [{"path": self.media_path, "in": 0.0, "out": self.media_duration()}],
                "overlays": [dict(x) for x in self.tracks["overlays"]],
                "music": [dict(x) for x in self.tracks["music"]]}

    def export_tracks(self, output_path=None):
        """照素材軌合成輸出。output_path 省略時先問要存到哪。回傳是否開始輸出。"""
        if self.track_exporter.busy or not self.media_path or not any(self.tracks.values()):
            return False
        timeline, cues, info = self.timeline_for_export(), self.cues, {"cut_count": 0, "dropped": 0}
        try:
            if self._track_cut_count():
                plan = cutmarks.export_plan(self.cut_plan["marks"], self.media_duration(), self.cues)
                keep = assemble_mod.usable_keep(plan["keep"])
                timeline = assemble_mod.apply_cuts(timeline, keep)
                cues, dropped = cutmarks.remap_cues(self.cues, keep)
                info = {"cut_count": plan["cut_count"], "dropped": dropped}
            assemble_mod.normalize(timeline)
        except ValueError as exc:  # AssembleError 也是 ValueError
            self._show_track_error(str(exc))
            return False
        if output_path is None:
            root, _ext = os.path.splitext(self.media_path)
            output_path = self._ask_assemble_path(root + "_多軌.mp4")
            if not output_path:
                return False
        self.track_label.setText(f"正在輸出 {os.path.basename(output_path)}…")
        self.track_exporter.start(timeline, output_path, cues, dict(self._config), info)
        self._update_track_buttons()
        return True

    def _ask_track_file(self, kind):
        if kind == "overlays":
            title, filters = "加入畫面", "影片或圖片 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v " \
                + " ".join("*" + e for e in assemble_mod.IMAGE_EXTS) + ");;所有檔案 (*)"
        else:
            title, filters = "加入音樂", "聲音或影片 (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus " \
                "*.mp4 *.mov *.mkv);;所有檔案 (*)"
        path, _ = QFileDialog.getOpenFileName(self, title, os.path.dirname(self.media_path or ""), filters)
        return path

    def _ask_assemble_path(self, suggested):
        path, _ = QFileDialog.getSaveFileName(self, "輸出多軌", suggested, "MP4 影片 (*.mp4);;所有檔案 (*)")
        return path

    def _show_track_error(self, message):
        QMessageBox.warning(self, "素材軌", message)

    def _on_assemble_progress(self, ratio, _message):
        self.track_label.setText(f"正在輸出多軌…{int(round(ratio * 100))}%")

    def _on_assemble_done(self, result):
        self.last_assemble = result
        note = f"已輸出 {os.path.basename(result['output'])}"
        if result.get("cut_count"):
            note += f"（剪掉 {result['cut_count']} 處）"
        if result["subtitles"]:
            note += f"＋{os.path.basename(result['subtitles'])}"
            if result.get("dropped"):
                note += f"（{result['dropped']} 句整句被剪掉）"
        self.refresh_tracks(note)

    def _on_assemble_failed(self, message):
        self.refresh_tracks()
        self._show_track_error(f"沒有輸出成功：{message}")

    def reset_cut_marks(self):
        """清掉目前這種來源的剪點微調（停用、調過的範圍），回到自動算出來的樣子。"""
        source = self.cut_combo.currentData()
        if source:
            prefix = f"{source}:"
            self.cut_overrides = {k: v for k, v in self.cut_overrides.items()
                                  if not k.startswith(prefix)}
        self.refresh_cut_marks()

    def _cut_override(self, index):
        if self.cut_plan is None or not 0 <= index < len(self.cut_plan["marks"]):
            return None
        return self.cut_overrides.setdefault(self.cut_plan["marks"][index]["key"], {})

    def _on_cut_toggled(self, index, enabled):
        change = self._cut_override(index)
        if change is not None:
            change["enabled"] = bool(enabled)
            self.refresh_cut_marks()

    def _on_cut_changed(self, index, start, end):
        change = self._cut_override(index)
        if change is not None:
            change["start"], change["end"] = float(start), float(end)
            self.refresh_cut_marks()

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
        name = os.path.basename(self.media_path)
        video = f"影片：{name}" if name else "還沒開啟影片。"
        if name and self.proxy_note:
            video += f"（{self.proxy_note}）"
        self.info_label.setText(video + self._subs_note())
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
        self.refresh_overlays(ms)
        self.timeline.set_position(ms)

    def _on_duration(self, ms):
        self.slider.setRange(0, ms)
        self.timeline.set_duration(self.media_duration())
        if ms > 0 and not self._fitted:
            # 一開片子先讓整支塞滿時間軸，要細看再拉近
            self._fitted = True
            self.timeline.zoom_to_fit()
        self._on_position(self.player.position())
        self.refresh_cut_marks()  # 知道片長之後，片尾的空白才算得出來
        self._update_track_buttons()

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
        if status != QMediaPlayer.MediaStatus.LoadedMedia:
            return
        if self._pending_seek is not None:
            # 剛從原檔換成代理檔（或反過來）：回到換之前的位置，原本在播就接著播
            ms, playing = self._pending_seek
            self._pending_seek = None
            self.player.pause()
            self.player.setPosition(ms)
            if playing:
                self.player.play()
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.StoppedState:
            self.player.pause()

    def _on_error(self, _err, message):
        if self.proxy_path:
            # 代理檔播不了（壞掉、被刪）：退回原檔，不要讓使用者看著一片黑
            self.proxy_maker.cancel()
            self.proxy_note = f"代理檔播不了（{message}），改用原檔"
            self._swap_source("")
            self._refresh_info()
            return
        self.info_label.setText(f"無法播放：{message}")

    # ---- 代理檔 --------------------------------------------------------

    def media_duration(self):
        """原檔的片長（秒）。播代理檔時照原檔量到的，兩者可能差幾十毫秒。"""
        if self.proxy_path and self._orig_duration > 0:
            return self._orig_duration
        return max(self.player.duration(), 0) / 1000.0

    def _proxy_cache_dir(self):
        root = timeline_mod.CACHE_ROOT
        return os.path.join(root, proxy_mod.CACHE_DIR) if root else proxy_mod.CACHE_DIR

    def _find_proxy(self):
        """
        快取裡已經有代理檔就回傳它（並記下要播它）；沒有就背景做一份，回傳空字串（先播原檔）。
        """
        found = proxy_mod.cached_proxy(self.media_path, self._proxy_cache_dir())
        info = proxy_mod.probe_video(self.media_path) if found else None
        if found and info and info["duration"] > 0:
            self.proxy_path = found
            self._orig_duration = info["duration"]
            self.proxy_note = "編輯用代理檔，輸出用原檔"
            return found
        self.proxy_note = "正在準備代理檔…"
        self.proxy_maker.load(self.media_path, self._proxy_cache_dir())
        return ""

    def _swap_source(self, proxy_path):
        """換成代理檔（proxy_path）或換回原檔（空字串），停在同一個位置、保持播放狀態。"""
        if proxy_path == self.proxy_path:
            return
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self._pending_seek = (self.player.position(), playing)
        self.proxy_path = proxy_path
        self.player.setSource(QUrl.fromLocalFile(proxy_path or self.media_path))

    def _on_proxy_toggled(self, on):
        # 只記在這次開啟的設定裡：Qt 預覽版不寫回 config.json（跟一般版同時開時會互相蓋掉，
        # 見 test_qt_skeleton），要等兩邊的設定寫法說好了才記得住。
        self._config["qt_proxy"] = bool(on)
        if not self.media_path:
            return
        if on:
            self.proxy_note = ""
            found = self._find_proxy()
            if found:
                self.proxy_path = ""  # _find_proxy 先記了；交給 _swap_source 真的換
                self._swap_source(found)
        else:
            self.proxy_maker.cancel()
            self.proxy_note = ""
            self._swap_source("")
        self._refresh_info()

    def _on_proxy_progress(self, gen, ratio):
        if gen == self.proxy_maker.generation:
            self.proxy_note = f"正在做代理檔 {int(ratio * 100)}%，先用原檔"
            self._refresh_info()

    def _on_proxy_ready(self, gen, path, duration):
        if gen != self.proxy_maker.generation or not self.proxy_box.isChecked():
            return
        if not path:  # 不到 1080p，原檔就夠快
            self.proxy_note = ""
        else:
            self._orig_duration = duration
            self.proxy_note = "編輯用代理檔，輸出用原檔"
            self._swap_source(path)
        self._refresh_info()

    def _on_proxy_failed(self, gen, message):
        if gen == self.proxy_maker.generation:
            self.proxy_note = f"代理檔沒做成（{message}），用原檔編輯"
            self._refresh_info()

    def shutdown(self):
        """關視窗前：停掉還在做的代理檔與預覽抽格（不留下做一半的 ffmpeg）。"""
        self.proxy_maker.stop()
        self.overlay_preview.stop()

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
        self.refresh_overlays()

    def _place_subtitle(self):
        place_subtitle(self.subtitle_item, self._video_rect(), self._style)


class ProxyMaker(QObject):
    """
    在背景執行緒做代理檔。每次 load() 是新的一次，舊的取消、晚到的結果（編號不是
    最新的）丟掉——跟時間軸的 TimelineLoader 同一套作法。
    """

    progress = Signal(int, float)
    ready = Signal(int, str, float)  # 編號、代理檔路徑（空字串＝不需要）、原檔片長
    failed = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.generation = 0
        self._cancel = threading.Event()
        self._thread = None

    def load(self, media_path, cache_dir):
        self.cancel()
        self._cancel = threading.Event()
        self.generation += 1
        gen, cancel = self.generation, self._cancel
        self._thread = threading.Thread(target=self._run, args=(gen, cancel, media_path, cache_dir),
                                        daemon=True)
        self._thread.start()
        return gen

    def cancel(self):
        """取消還在做的，並換編號：取消前一刻剛好送出的結果也會被當成舊的丟掉。"""
        self._cancel.set()
        self.generation += 1

    def stop(self, timeout=5.0):
        """取消並等背景工作收尾（ffmpeg 每半秒回報一次進度，取消最慢半秒內生效）。"""
        self.cancel()
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self, gen, cancel, media_path, cache_dir):
        try:
            info = proxy_mod.probe_video(media_path)
            path = proxy_mod.load_proxy(
                media_path, cache_dir, info=info, cancel=cancel.is_set,
                progress_cb=lambda ratio: None if cancel.is_set() else self.progress.emit(gen, ratio))
        except proxy_mod.ProxyCancelled:
            return
        except (proxy_mod.ProxyError, OSError) as exc:
            if not cancel.is_set():
                self.failed.emit(gen, str(exc))
            return
        if not cancel.is_set():
            self.ready.emit(gen, path or "", float(info["duration"]) if info else 0.0)


class CutExporter(QObject):
    """
    在背景執行緒照剪點剪片（ffmpeg 要跑一陣子，不能卡住畫面）；進度與結果用訊號
    送回主執行緒。影片剪好後，對齊好的字幕存成同檔名的 .srt。
    """

    progress = Signal(float, str)
    finished = Signal(object)  # {"output", "subtitles"（沒有字幕時 None）, "dropped", "cut_count", …}
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False

    def start(self, media_path, plan, output_path):
        self.busy = True
        threading.Thread(target=self._run, args=(media_path, plan, output_path), daemon=True).start()

    def _run(self, media_path, plan, output_path):
        try:
            cutmarks.render(media_path, plan, output_path,
                            lambda ratio, message: self.progress.emit(float(ratio), str(message)))
            subtitles = None
            if plan["cues"]:
                subtitles = os.path.splitext(output_path)[0] + ".srt"
                cueedit.save_cues(plan["cues"], subtitles)
            result = dict(plan, output=output_path, subtitles=subtitles)
        except (OSError, ValueError, RuntimeError) as exc:
            self.busy = False
            self.failed.emit(str(exc))
            return
        self.busy = False
        self.finished.emit(result)


PROP_HINT = "（點時間軸上的素材可改屬性）"


class TrackExporter(QObject):
    """
    在背景執行緒照多軌時間軸合成（assemble.render）；進度與結果用訊號送回主執行緒。
    字幕存一份同檔名的 .srt（沒剪就原封不動；跟剪點一起輸出時，呼叫端先對齊好再傳進來）。
    """

    progress = Signal(float, str)
    finished = Signal(object)  # {"output", "subtitles"（沒有字幕時 None）, "duration", …}
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False

    def start(self, timeline, output_path, cues, config, info=None):
        self.busy = True
        threading.Thread(target=self._run, args=(timeline, output_path, [dict(c) for c in cues or []],
                                                 config, dict(info or {})), daemon=True).start()

    def _run(self, timeline, output_path, cues, config, info):
        try:
            result = assemble_mod.render(
                timeline, output_path,
                lambda ratio, message: self.progress.emit(float(ratio), str(message)), config)
            subtitles = None
            if cues:
                subtitles = os.path.splitext(output_path)[0] + ".srt"
                cueedit.save_cues(cues, subtitles)
            result = dict(result, subtitles=subtitles, **info)
        except (OSError, ValueError, RuntimeError) as exc:
            self.busy = False
            self.failed.emit(str(exc))
            return
        self.busy = False
        self.finished.emit(result)


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
