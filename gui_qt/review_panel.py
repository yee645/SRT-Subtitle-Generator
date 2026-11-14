# -*- coding: utf-8 -*-
"""
①素材與剪輯頁的「審片助手」（3.0 第 11 項第十六階段：分析與段落清單）。

跟一般版的審片助手同一套判定（`subtitle/review.py`：冷場、重複拍攝、口頭禪多、精彩），同一份偵測設定
（config 的 review，範圍一樣）。不一樣的地方：

* **不重新轉錄**。一般版自己跑一次 Whisper；這裡分析②字幕頁現在的字幕（跟時間軸「剪點：審片建議」同
  一個來源，`cutmarks.words_from_cues`：字幕帶逐字資料就用逐字，沒有就一句當一個字）。不會多送一次聲音
  出去；清單講的就是校對過的句子。還沒有字幕就請先到②生成或載入。
* 音量（精彩偵測用）在背景用 ffmpeg 現量，全在本機；量不到（沒開影片、沒有 ffmpeg）就只看語速與文字，
  畫面上講明。
* 點清單或色條上的一段，②的播放器跳到那一段的開頭。

保留／捨棄只記在這一頁，下面「輸出」那一框照它輸出（第十七階段）：

* **粗剪影片**（保留的段落接起來）、**精彩合輯**（只接標了精彩的段落）：跟一般版同一個函式
  （`review.cut_rough_video`）、同樣的檔名（`_粗剪`、`_精彩合輯`，同名加編號，不覆蓋）、同樣可以一併剪掉
  口頭禪字。背景用 ffmpeg 跑，輸出到一半不能停（一般版也不能），關視窗先問。
* 比一般版多的：②有字幕時，影片旁邊放一份**對齊到剪後時間的字幕**（同名 .srt）。做好後問要不要在②換成
  這一支——換的話字幕也換成對齊好的那一份（一般版只換影片，字幕要自己重做）。
* **匯出** EDL、審片標記字幕、CSV 清單、HTML 審片報告：同一般版的函式與檔名。分析之後②的字幕又改過：清單是舊的，畫面上講明，
請重新分析。偵測設定只記在這次開啟的設定裡（Qt 預覽版不寫 config.json）；時間軸的「審片建議」剪點讀同
一份，按「開始分析」時跟著重算。

還沒有的（頁面上寫明，請先用一般版）：章節、發佈包、廣告插入點、封面候選、直式短片。
"""
import os
import threading

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QRadioButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from subtitle import cutmarks, exporter, review
from subtitle.burner import ffmpeg_available
from subtitle.errors import describe_exception
from subtitle.pipeline import resolve_output_dir, unique_path

PAGE_NOTE = ("審片助手：讀文字快速找可用片段。分析②字幕頁現在的字幕（不重新轉錄、不送任何東西出去），自動標出"
             "冷場、重複拍攝、口頭禪多與精彩；冷場與重複拍攝預設捨棄。點一段，②的播放器跳到那裡。"
             "看完清單，下面「輸出」照保留的段落輸出粗剪影片、精彩合輯，或匯出 EDL／審片標記字幕／CSV／HTML 報告。"
             "章節與發佈包、廣告插入點、封面候選、直式短片還在一般版（之後的階段搬過來）；剪停頓、剪重複、"
             "審片建議的剪點在②的時間軸上。")
SETTINGS_HINT = ("敏感度 >1 更容易標記精彩、<1 更嚴格；情緒詞以逗號或空白分隔，附加於內建詞庫；口頭禪字連寫"
                 "（逐字比對）；權重 0＝停用該訊號、1＝預設。")
NO_CUES = "②字幕頁還沒有字幕：請先到②按「生成字幕…」或「載入字幕」，再回來分析。"
IDLE = "按「開始分析」：分析②現在的字幕。"
STALE = "②的字幕在分析之後改過了：下面的清單是改之前的，請重新分析。"
NO_LOUDNESS = "量不到音量（沒開影片或沒有 ffmpeg）：精彩只看語速與文字。"
NO_MEDIA = "②字幕頁還沒開影片：請先到②按「開啟影片」。"
NO_FFMPEG = "找不到 ffmpeg，輸出影片需要它：請先在一般版按「自動安裝 ffmpeg」（兩版共用）。"
NO_KEPT = "沒有任何保留的段落可以輸出：請先在清單把要留的段落標成保留。"
NO_HIGHLIGHT = "這支素材沒有偵測到精彩片段：可以在清單手動確認內容，或改用「輸出粗剪影片」。"
NO_BASE = "不知道要存到哪裡：請先到②開影片或載入字幕（輸出檔放在它旁邊，或「輸出設定」指定的資料夾）。"
OUTPUT_NOTE = ("粗剪＝保留的段落接起來；精彩合輯＝只接標了「精彩」的段落。輸出成新檔（原檔不動），②有字幕時旁邊放一份"
               "對齊到剪後時間的字幕；輸出到一半不能停。")
CUT_KINDS = {"roughcut": ("粗剪", "_粗剪"), "highlight": ("精彩合輯", "_精彩合輯")}
# (鍵, 按鈕文字, 檔名後綴, 副檔名)：跟一般版的匯出同名
EXPORTS = (("edl", "匯出 EDL（進剪輯軟體）", "_粗剪", ".edl"), ("srt", "匯出審片標記字幕", "_審片標記", ".srt"),
           ("csv", "匯出 CSV 清單", "_審片清單", ".csv"), ("html", "匯出 HTML 審片報告", "_審片報告", ".html"))
LIST_TITLE = "段落清單（雙擊或空白鍵切換保留／捨棄）"
FILTERS = (("all", "全部"), ("highlight", "只看精彩"), ("review", "只看待審視"))
COLUMNS = ("保留", "#", "時間", "秒數", "標記", "內容")
LEGEND = ("highlight", "normal", "review", "silence")
# (設定鍵, 標籤, 最小, 最大, 一步, 小數位, 單位)：範圍跟一般版、跟 review.resolve_settings 的夾限一樣
SPINS = (("silence_gap", "冷場門檻", 0.5, 10.0, 0.5, 1, " 秒"), ("segment_gap", "段落切分停頓", 0.4, 5.0, 0.2, 1, " 秒"),
         ("highlight_sensitivity", "精彩敏感度", 0.2, 3.0, 0.1, 1, " 倍"),
         ("take_similarity", "重複判定相似度", 0.5, 0.95, 0.05, 2, ""))
WEIGHTS = (("weight_energy", "音量"), ("weight_pace", "語速"), ("weight_excite", "情緒詞"),
           ("weight_exclaim", "驚嘆句"))


def clock(seconds):
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


def cue_signature(cues):
    """字幕有沒有變：只看起訖與文字（分析只用這些）。"""
    return tuple((round(float(c["start"]), 3), round(float(c["end"]), 3), str(c.get("text", "")))
                 for c in cues or ())


def suggested_keep(item):
    """系統建議：講話的段落保留，除非是重複拍攝；冷場捨棄（同一般版的「套用建議」）。"""
    return item["kind"] == "speech" and not set(item["tags"]) & {review.TAG_SILENCE, review.TAG_REPEATED}


class ReviewWorker(QObject):
    """背景執行緒：量音量（ffmpeg）＋分段標記。busy 由畫面那邊（主執行緒）放下。"""

    progress = Signal(float, str)
    finished = Signal(object)
    failed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False

    def start(self, media_path, cues, duration, config):
        self.busy = True
        threading.Thread(target=self._run, args=(media_path, [dict(c) for c in cues], float(duration or 0.0),
                                                 dict(config)), daemon=True).start()

    def _run(self, media_path, cues, duration, config):
        try:
            settings = review.resolve_settings(config)
            words = cutmarks.words_from_cues(cues)
            loudness = []
            if media_path and os.path.exists(media_path):
                self.progress.emit(0.1, "正在分析音量能量（偵測精彩片段）…")
                loudness = review.compute_loudness(media_path, voice_band=settings["voice_band"])
            self.progress.emit(0.9, "正在分析段落與標記…")
            items = review.analyze(words, media_duration=duration, loudness=loudness, settings=settings)
            if not duration and items:
                duration = max(i["end"] for i in items)
        except Exception as exc:  # noqa: BLE001 —— 背景執行緒的例外一律送回畫面上講
            self.failed.emit(exc)
            return
        self.finished.emit({"items": items, "duration": duration, "loudness": bool(loudness),
                            "signature": cue_signature(cues)})


class CutWorker(QObject):
    """背景執行緒：照保留的段落剪出影片，②有字幕就在旁邊放一份對齊好的。busy 由畫面那邊放下。"""

    progress = Signal(float, str)
    finished = Signal(object)  # {"kind", "output", "subtitles"（沒有字幕時是空字串）, "dropped"}
    failed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False

    def start(self, kind, media_path, items, output, drop_fillers, cues):
        self.busy = True
        threading.Thread(target=self._run, args=(kind, media_path, [dict(i) for i in items], output,
                                                 bool(drop_fillers), [dict(c) for c in cues]), daemon=True).start()

    def _run(self, kind, media_path, items, output, drop_fillers, cues):
        try:
            review.cut_rough_video(media_path, items, output, drop_filler_words=drop_fillers,
                                   progress_cb=lambda r, m: self.progress.emit(float(r), str(m)))
            subtitles, dropped = "", 0
            if cues:
                keep = review.kept_ranges(items, drop_filler_words=drop_fillers)
                aligned, dropped = cutmarks.remap_cues(cues, keep)
                if aligned:
                    subtitles = os.path.splitext(output)[0] + ".srt"
                    exporter.export(aligned, subtitles)
        except Exception as exc:  # noqa: BLE001 —— 背景執行緒的例外一律送回畫面上講
            self.failed.emit(exc)
            return
        self.finished.emit({"kind": kind, "output": output, "subtitles": subtitles, "dropped": dropped})


class SegmentStrip(QWidget):
    """整支素材的彩色條：一段一塊，顏色照分類；捨棄的畫淡。點一塊送出是第幾段。"""

    clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.items, self.total, self.current = [], 0.0, -1
        self.setToolTip("素材時間軸（點色塊跳到段落）")

    def set_items(self, items, total, current=-1):
        self.items, self.total, self.current = list(items), float(total or 0.0), current
        self.update()

    def spans(self):
        """每一段的 (左, 右) 像素（至少 2px 寬，短的段落也點得到）。"""
        total = max(self.total, max((i["end"] for i in self.items), default=0.0), 0.1)
        width = max(self.width(), 1)
        result = []
        for item in self.items:
            x0 = item["start"] / total * width
            result.append((x0, max(item["end"] / total * width, x0 + 2.0)))
        return result

    def index_at(self, x):
        hits = [n for n, (x0, x1) in enumerate(self.spans()) if x0 <= x < x1]
        return hits[-1] if hits else -1

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().color(QPalette.AlternateBase))
        for n, ((x0, x1), item) in enumerate(zip(self.spans(), self.items)):
            color = QColor(review.CATEGORY_COLORS[review.categorize(item)])
            if not item["keep"]:
                color.setAlpha(70)
            painter.fillRect(int(x0), 2, max(int(x1) - int(x0), 2), self.height() - 4, color)
            if n == self.current:
                painter.setPen(self.palette().color(QPalette.Text))
                painter.drawRect(int(x0), 1, max(int(x1) - int(x0), 2) - 1, self.height() - 3)
        painter.end()

    def mousePressEvent(self, event):  # noqa: N802
        index = self.index_at(event.position().x())
        if index >= 0:
            self.clicked.emit(index)


class ReviewPanel(QWidget):
    def __init__(self, player, before_analyze=None, parent=None):
        super().__init__(parent)
        self.player = player
        self.config = player._config
        self.before_analyze = before_analyze
        self.items, self.duration = [], 0.0
        self.visible = []  # 清單第幾列 → items 第幾段
        self.filter = "all"
        self.signature = None
        self.loudness_ok = True
        self._hits, self._hit_pos = [], -1
        settings = review.resolve_settings(self.config)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        note = QLabel(PAGE_NOTE)
        note.setWordWrap(True)
        layout.addWidget(note)

        box = QGroupBox("偵測設定（按「開始分析」套用）")
        grid = QGridLayout(box)
        self.spins = {}
        for col, (key, label, low, high, step, decimals, suffix) in enumerate(SPINS):
            spin = QDoubleSpinBox()
            spin.setRange(low, high)
            spin.setSingleStep(step)
            spin.setDecimals(decimals)
            spin.setSuffix(suffix)
            spin.setValue(settings[key])
            spin.setMaximumWidth(110)
            grid.addWidget(QLabel(label), 0, col * 2)
            grid.addWidget(spin, 0, col * 2 + 1)
            self.spins[key] = spin
        self.excite_edit = QLineEdit(settings["extra_excite_words"])
        self.excite_edit.setPlaceholderText("例：太扯了, 笑死（附加在內建詞庫後面）")
        self.filler_edit = QLineEdit(settings["filler_words"])
        grid.addWidget(QLabel("自訂情緒詞"), 1, 0)
        grid.addWidget(self.excite_edit, 1, 1, 1, 5)
        grid.addWidget(QLabel("口頭禪字"), 1, 6)
        grid.addWidget(self.filler_edit, 1, 7)
        weights = QHBoxLayout()
        weights.addWidget(QLabel("精彩訊號權重"))
        for key, label in WEIGHTS:
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 3.0)
            spin.setSingleStep(0.1)
            spin.setDecimals(1)
            spin.setValue(settings[key])
            weights.addSpacing(8)
            weights.addWidget(QLabel(label))
            weights.addWidget(spin)
            self.spins[key] = spin
        self.voice_band_box = QCheckBox("音量聚焦人聲頻帶")
        self.voice_band_box.setChecked(settings["voice_band"])
        weights.addSpacing(12)
        weights.addWidget(self.voice_band_box)
        weights.addStretch(1)
        grid.addLayout(weights, 2, 0, 1, 9)
        hint = QLabel(SETTINGS_HINT)
        hint.setWordWrap(True)
        grid.addWidget(hint, 3, 0, 1, 9)
        grid.setColumnStretch(8, 1)  # 多的寬度留在最右邊，欄位不被拉寬
        layout.addWidget(box)

        row = QHBoxLayout()
        self.analyze_btn = QPushButton("開始分析")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedWidth(160)
        self.progress_bar.setVisible(False)
        self.status_label = QLabel(IDLE)
        self.status_label.setWordWrap(True)
        row.addWidget(self.analyze_btn)
        row.addWidget(self.progress_bar)
        row.addWidget(self.status_label, 1)
        layout.addLayout(row)
        self.stale_label = QLabel(STALE)
        self.stale_label.setWordWrap(True)
        self.stale_label.setVisible(False)
        layout.addWidget(self.stale_label)

        self.strip = SegmentStrip()
        layout.addWidget(self.strip)
        legend = QHBoxLayout()
        for key in LEGEND:
            mark = QLabel("■")
            mark.setStyleSheet(f"color: {review.CATEGORY_COLORS[key]};")
            legend.addWidget(mark)
            legend.addWidget(QLabel(review.CATEGORY_LABELS[key]))
            legend.addSpacing(10)
        legend.addStretch(1)
        self.stats_label = QLabel("")
        legend.addWidget(self.stats_label)
        layout.addLayout(legend)

        self.list_title = QLabel(LIST_TITLE)
        layout.addWidget(self.list_title)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(COLUMNS))
        self.tree.setHeaderLabels(list(COLUMNS))
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for col, width in enumerate((48, 44, 130, 60, 130)):
            self.tree.setColumnWidth(col, width)
        layout.addWidget(self.tree, 1)

        ops = QHBoxLayout()
        self.toggle_btn = QPushButton("切換保留")
        self.suggest_btn = QPushButton("套用建議")
        self.keep_all_btn = QPushButton("全部保留")
        for w in (self.toggle_btn, self.suggest_btn, self.keep_all_btn):
            ops.addWidget(w)
        ops.addSpacing(14)
        ops.addWidget(QLabel("顯示"))
        self.filter_group = QButtonGroup(self)
        self.filter_buttons = {}
        for key, label in FILTERS:
            button = QRadioButton(label)
            button.setChecked(key == "all")
            self.filter_group.addButton(button)
            self.filter_buttons[key] = button
            button.toggled.connect(lambda on, k=key: on and self.set_filter(k))
            ops.addWidget(button)
        ops.addSpacing(14)
        ops.addWidget(QLabel("關鍵字"))
        self.search_edit = QLineEdit()
        self.search_edit.setFixedWidth(160)
        self.search_btn = QPushButton("搜尋下一個")
        ops.addWidget(self.search_edit)
        ops.addWidget(self.search_btn)
        ops.addStretch(1)
        layout.addLayout(ops)

        out = QGroupBox("輸出")
        out_layout = QVBoxLayout(out)
        out_note = QLabel(OUTPUT_NOTE)
        out_note.setWordWrap(True)
        out_layout.addWidget(out_note)
        row = QHBoxLayout()
        self.cut_buttons = {"roughcut": QPushButton("輸出粗剪影片（自動跳剪）"),
                            "highlight": QPushButton("輸出精彩合輯（短影音素材）")}
        for kind, button in self.cut_buttons.items():
            button.clicked.connect(lambda _c=False, k=kind: self.start_cut(k))
            row.addWidget(button)
        self.fillers_box = QCheckBox("剪除口頭禪字")
        self.fillers_box.setToolTip("粗剪、精彩合輯與 EDL 一併剪掉保留段落裡的口頭禪字（呃、嗯…）；"
                                    "字幕要帶逐字時間才分得出是哪個字")
        self.fillers_box.setChecked(settings["cut_filler_words"])
        row.addWidget(self.fillers_box)
        row.addSpacing(14)
        self.export_buttons = {}
        for key, label, _suffix, _ext in EXPORTS:
            button = QPushButton(label)
            button.clicked.connect(lambda _c=False, k=key: self.export(k))
            self.export_buttons[key] = button
            row.addWidget(button)
        row.addStretch(1)
        out_layout.addLayout(row)
        layout.addWidget(out)
        self.last_cut = None      # 上一次輸出成功的 {"kind", "output", "subtitles", "dropped"}
        self.last_export = ""     # 上一次匯出的檔
        self._cut_output = ""

        self.cutter = CutWorker(self)
        self.cutter.progress.connect(self._on_progress)
        self.cutter.finished.connect(self._on_cut_finished)
        self.cutter.failed.connect(self._on_cut_failed)
        self.fillers_box.toggled.connect(self._on_fillers_toggled)
        self.worker = ReviewWorker(self)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.analyze_btn.clicked.connect(self.start_analysis)
        self.toggle_btn.clicked.connect(self.toggle_selected)
        self.suggest_btn.clicked.connect(self.apply_suggestions)
        self.keep_all_btn.clicked.connect(self.keep_all)
        self.search_btn.clicked.connect(self.search_next)
        self.search_edit.returnPressed.connect(self.search_next)
        # 雙擊當下清單還在處理滑鼠事件：等它處理完再重畫清單
        self.tree.itemDoubleClicked.connect(lambda *_a: QTimer.singleShot(0, self.toggle_selected))
        self.tree.currentItemChanged.connect(self._on_current_changed)
        self.strip.clicked.connect(self.select_segment)
        self.tree.installEventFilter(self)
        player.cuesChanged.connect(self._check_stale)
        self._update_buttons()

    # ----- 設定 -----
    def collect_settings(self):
        """畫面上的偵測參數寫進這次開啟的設定（review，跟一般版同一個區塊；沒在這頁的項目照舊留著）。"""
        current = dict(self.config.get("review") or {})
        current.update({key: round(spin.value(), 2) for key, spin in self.spins.items()})
        current.update({"extra_excite_words": self.excite_edit.text().strip(),
                        "filler_words": self.filler_edit.text().strip(),
                        "voice_band": self.voice_band_box.isChecked()})
        self.config["review"] = current
        return review.resolve_settings(self.config)

    # ----- 分析 -----
    def busy(self):
        return self.worker.busy or self.cutter.busy

    def start_analysis(self):
        if self.busy():
            return False
        if callable(self.before_analyze):
            self.before_analyze()  # 逐句校對改到一半的先套用：分析的是現在的句子
        cues = [c for c in self.player.cues if str(c.get("text", "")).strip()]
        if not cues:
            self.status_label.setText(NO_CUES)
            return False
        self.collect_settings()
        self.player.refresh_cut_marks()  # 時間軸的「審片建議」剪點讀同一份設定：跟著重算
        self.worker.start(self.player.media_path or "", self.player.cues, self.player.media_duration(),
                          self.config)
        self.progress_bar.setValue(0)
        self.status_label.setText("分析中…")
        self._update_buttons()
        return True

    def _on_progress(self, ratio, message):
        self.progress_bar.setValue(int(max(0.0, min(ratio, 1.0)) * 1000))
        if message:
            self.status_label.setText(message)

    def _on_failed(self, exc):
        self.worker.busy = False
        err = describe_exception(exc)
        detail = f"（{err.details}）" if err.details and err.details != str(err) else ""
        self.status_label.setText(f"分析失敗：{err}{detail}")
        self._update_buttons()

    def _on_finished(self, payload):
        self.worker.busy = False
        self.items, self.duration = payload["items"], payload["duration"]
        self.signature, self.loudness_ok = payload["signature"], payload["loudness"]
        self._hits, self._hit_pos = [], -1
        self.repopulate()
        stats = review.summarize(self.items, self.duration)
        dropped = sum(1 for i in self.items if not i["keep"])
        text = (f"分析完成：{stats['segment_count']} 個講話段落、{stats['highlight_count']} 段精彩，"
                f"建議捨棄 {dropped} 段。色條綠色為精彩、琥珀色待審視、灰色冷場。")
        if not self.loudness_ok:
            text += NO_LOUDNESS
        self.status_label.setText(text)
        self._check_stale()
        self._update_buttons()

    def _check_stale(self):
        """分析之後②的字幕改過了沒：改過就講清單是舊的。"""
        self.stale_label.setVisible(self.signature is not None
                                    and self.signature != cue_signature(self.player.cues))

    def stale(self):
        return not self.stale_label.isHidden()

    # ----- 清單 -----
    def visible_indexes(self):
        if self.filter == "all":
            return list(range(len(self.items)))
        return [n for n, item in enumerate(self.items) if review.categorize(item) == self.filter]

    def repopulate(self, select=None):
        """照目前的篩選重畫清單、色條與統計。select：重畫後選取 items 的哪幾段。"""
        self.tree.blockSignals(True)
        self.tree.clear()
        self.visible = self.visible_indexes()
        faded = self.palette().color(QPalette.Disabled, QPalette.Text)
        for index in self.visible:
            item = self.items[index]
            row = QTreeWidgetItem(["✔" if item["keep"] else "✘", str(index + 1),
                                   f"{clock(item['start'])} → {clock(item['end'])}",
                                   f"{item['end'] - item['start']:.1f}", "、".join(item["tags"]), item["text"]])
            category = review.categorize(item)
            for col in range(len(COLUMNS)):
                if col < 5:
                    row.setTextAlignment(col, Qt.AlignCenter)
                if category != "normal":
                    tint = QColor(review.CATEGORY_COLORS[category])
                    tint.setAlpha(55)
                    row.setBackground(col, QBrush(tint))
                if not item["keep"]:
                    row.setForeground(col, QBrush(faded))
            row.setToolTip(5, item["text"])
            self.tree.addTopLevelItem(row)
        chosen = [self.tree.topLevelItem(self.visible.index(n)) for n in select or () if n in self.visible]
        if chosen:
            self.tree.setCurrentItem(chosen[-1])  # 先定目前那一列（會清掉選取），再把每一列選回來
            for row in chosen:
                row.setSelected(True)
        self.tree.blockSignals(False)
        self._refresh_strip()
        if self.items:
            stats = review.summarize(self.items, self.duration)
            self.stats_label.setText(f"保留 {stats['kept_seconds'] / 60.0:.1f} 分｜"
                                     f"精彩 {stats['highlight_seconds'] / 60.0:.1f} 分｜"
                                     f"冷場 {stats['silence_seconds'] / 60.0:.1f} 分｜"
                                     f"口頭禪 {stats['filler_total']} 次")
        else:
            self.stats_label.setText("")
        self._update_buttons()

    def _refresh_strip(self):
        self.strip.set_items(self.items, self.duration, self.current_segment())

    def selected_segments(self):
        """清單上選取的那幾列是 items 的第幾段（照清單順序）。"""
        rows = sorted(self.tree.indexOfTopLevelItem(row) for row in self.tree.selectedItems())
        return [self.visible[r] for r in rows if 0 <= r < len(self.visible)]

    def current_segment(self):
        row = self.tree.indexOfTopLevelItem(self.tree.currentItem()) if self.tree.currentItem() else -1
        return self.visible[row] if 0 <= row < len(self.visible) else -1

    def select_segment(self, index):
        """選取並捲到 items 的第 index 段（被篩掉的話先切回「全部」）；②的播放器跳到它的開頭。"""
        if not 0 <= index < len(self.items):
            return False
        if index not in self.visible:
            self.filter_buttons["all"].setChecked(True)
        row = self.tree.topLevelItem(self.visible.index(index))
        self.tree.clearSelection()
        self.tree.setCurrentItem(row)
        row.setSelected(True)
        self.tree.scrollToItem(row)
        return True

    def _on_current_changed(self, current, _previous):
        self._refresh_strip()
        index = self.current_segment()
        if current is not None and index >= 0 and self.player.media_path:
            self.player.player.setPosition(int(round(self.items[index]["start"] * 1000)))

    def set_filter(self, key):
        if key not in dict(FILTERS):
            raise ValueError(f"不認得的篩選：{key!r}")
        if not self.filter_buttons[key].isChecked():
            self.filter_buttons[key].setChecked(True)  # 會再進來一次
            return
        self.filter = key
        self._hits, self._hit_pos = [], -1
        self.repopulate()

    def toggle_selected(self):
        chosen = self.selected_segments()
        for index in chosen:
            self.items[index]["keep"] = not self.items[index]["keep"]
        if chosen:
            self.repopulate(select=chosen)
        return len(chosen)

    def apply_suggestions(self):
        for item in self.items:
            item["keep"] = suggested_keep(item)
        self.repopulate()
        self.status_label.setText("已套用系統建議（捨棄冷場與重複拍攝）。")

    def keep_all(self):
        for item in self.items:
            item["keep"] = True
        self.repopulate()
        self.status_label.setText("已全部標記為保留。")

    def search_next(self):
        """搜尋關鍵字，逐一跳到命中的段落（只在目前顯示的範圍裡找）。"""
        keyword = self.search_edit.text()
        shown = set(self.visible)
        hits = [n for n in review.search_segments(self.items, keyword) if n in shown]
        if not hits:
            self.status_label.setText(f"目前顯示範圍找不到「{keyword.strip()}」。")
            return -1
        if hits != self._hits:
            self._hits, self._hit_pos = hits, -1
        self._hit_pos = (self._hit_pos + 1) % len(hits)
        index = hits[self._hit_pos]
        self.select_segment(index)
        self.status_label.setText(f"「{keyword.strip()}」第 {self._hit_pos + 1}/{len(hits)} 處：第 {index + 1} 段。")
        return index

    def eventFilter(self, watched, event):  # noqa: N802 —— 清單上按空白鍵：切換保留
        if watched is self.tree and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Space:
            self.toggle_selected()
            return True
        return super().eventFilter(watched, event)

    def _update_buttons(self):
        idle = not self.busy()
        has = bool(self.items)
        self.analyze_btn.setEnabled(idle)
        self.analyze_btn.setText("分析中…" if self.worker.busy else "開始分析")
        self.progress_bar.setVisible(not idle)
        for w in (self.toggle_btn, self.suggest_btn, self.keep_all_btn, self.search_btn, self.search_edit,
                  *self.filter_buttons.values(), *self.cut_buttons.values(), *self.export_buttons.values()):
            w.setEnabled(has and idle)
        self.fillers_box.setEnabled(idle)

    # ----- 輸出 -----
    def _on_fillers_toggled(self, on):
        """「剪除口頭禪字」寫進這次開啟的設定（跟一般版同一項）；時間軸的審片建議剪點讀同一項，跟著重算。"""
        current = dict(self.config.get("review") or {})
        current["cut_filler_words"] = bool(on)
        self.config["review"] = current
        self.player.refresh_cut_marks()

    def default_path(self, suffix, ext):
        """
        輸出檔放哪：②開著的影片旁邊（沒開影片就放字幕檔旁邊），「輸出設定」指定了資料夾就放那裡；
        檔名＝來源檔名＋後綴，同名加編號。沒有影片也沒有字幕檔：回傳空字串。
        """
        source = self.player.media_path or self.player._subtitle_path
        if not source:
            return ""
        folder = resolve_output_dir(source, self.config.get("automation") or {})
        os.makedirs(folder, exist_ok=True)
        base = os.path.splitext(os.path.basename(source))[0]
        return unique_path(os.path.join(folder, f"{base}{suffix}{ext}"))

    def cut_items(self, kind):
        """這次要剪的段落：粗剪照清單的保留／捨棄；精彩合輯只留標了精彩的（不管它現在是不是保留）。"""
        if kind == "highlight":
            return [dict(i, keep=True) for i in self.items if review.TAG_HIGHLIGHT in i["tags"]]
        return [dict(i) for i in self.items]

    def start_cut(self, kind):
        if kind not in CUT_KINDS:
            raise ValueError(f"不認得的輸出：{kind!r}")
        if self.busy() or not self.items:
            return False
        media = self.player.media_path
        if not media or not os.path.exists(media):
            return self._refuse(NO_MEDIA)
        items = self.cut_items(kind)
        if kind == "highlight" and not items:
            return self._refuse(NO_HIGHLIGHT)
        drop_fillers = self.fillers_box.isChecked()
        if not review.kept_ranges(items, drop_filler_words=drop_fillers):
            return self._refuse(NO_KEPT)
        if not ffmpeg_available():
            return self._refuse(NO_FFMPEG)
        label, suffix = CUT_KINDS[kind]
        output = self.default_path(suffix, ".mp4")
        self._cut_output = output
        cues = [c for c in self.player.cues if str(c.get("text", "")).strip()]
        self.cutter.start(kind, media, items, output, drop_fillers, cues)
        self.progress_bar.setValue(0)
        self.status_label.setText(f"正在輸出{label}：{os.path.basename(output)}（原檔不動，輸出到一半不能停）")
        self._update_buttons()
        return True

    def _refuse(self, text):
        self.status_label.setText(text)
        return False

    def _on_cut_failed(self, exc):
        self.cutter.busy = False
        err = describe_exception(exc)
        detail = f"（{err.details}）" if err.details and err.details != str(err) else ""
        self.status_label.setText(f"輸出失敗：{err}{detail}")
        self._update_buttons()

    def _on_cut_finished(self, result):
        self.cutter.busy = False
        self.last_cut = result
        self._update_buttons()
        label = CUT_KINDS[result["kind"]][0]
        done = f"{label}已輸出：{os.path.basename(result['output'])}（在 {os.path.dirname(result['output'])}）"
        if result["subtitles"]:
            done += f"，旁邊有對齊好的字幕 {os.path.basename(result['subtitles'])}"
            if result["dropped"]:
                done += f"（{result['dropped']} 句整句被剪掉）"
        done += "。"
        self.status_label.setText(done)
        if not self._ask_adopt(result):
            return
        if not self.player.maybe_close():  # 專案或字幕有沒存的變更：先問
            self.status_label.setText(done + "②沒有換（還沒存的變更沒有處理）。")
            return
        self.player.open_video(result["output"])
        if result["subtitles"]:
            self.player.load_subtitles(result["subtitles"])
        else:
            self.player.set_cues([])
        self.status_label.setText(done + f"②已換成這支{label}，可以接著上字幕、健檢、輸出。")

    def adopt_question(self, result):
        label = CUT_KINDS[result["kind"]][0]
        subs = ("字幕換成對齊到剪後時間的那一份" if result["subtitles"]
                else "這支沒有對齊的字幕（②的字幕會清掉，要重新生成）")
        return (f"已輸出：{os.path.basename(result['output'])}\n\n要在②換成這支{label}嗎？換了之後可以直接替它上字幕、"
                f"跑健檢或接著輸出。\n換的話跟②「開啟影片」一樣：素材軌與畫面調整會清掉，{subs}；"
                "選「否」只是輸出檔案，②維持不變。")

    def _ask_adopt(self, result):
        return QMessageBox.question(self, f"{CUT_KINDS[result['kind']][0]}完成",
                                    self.adopt_question(result)) == QMessageBox.Yes

    def cutting(self):
        return self.cutter.busy

    def close_question(self):
        return (f"影片（{os.path.basename(self._cut_output)}）還在輸出。\n\n現在關掉的話這個檔可能不完整，"
                "請不要拿它來用（要的話重開之後再輸出一次）。還是要關嗎？")

    def ask_close_while_cutting(self):
        """關視窗時粗剪／合輯還在輸出：問要不要關。回傳 True＝可以關。"""
        return QMessageBox.question(self, "影片還在輸出", self.close_question()) == QMessageBox.Yes

    def export(self, key):
        """匯出 EDL／審片標記字幕／CSV／HTML 報告（同一般版的函式與檔名）。回傳存到哪；沒存回傳空字串。"""
        spec = {k: (suffix, ext) for k, _label, suffix, ext in EXPORTS}
        if key not in spec:
            raise ValueError(f"不認得的匯出：{key!r}")
        if self.busy() or not self.items:
            return ""
        path = self.default_path(*spec[key])
        if not path:
            self.status_label.setText(NO_BASE)
            return ""
        name = os.path.basename(self.player.media_path or self.player._subtitle_path)
        try:
            if key == "edl":
                review.export_edl(self.items, path, clip_name=name, drop_filler_words=self.fillers_box.isChecked())
            elif key == "srt":
                exporter.export(review.build_review_cues(self.items), path)
            elif key == "csv":
                review.export_csv(self.items, path)
            else:
                settings = review.resolve_settings(self.config)
                chapters = review.build_chapters(self.items, min_chapter_seconds=settings["chapter_min_seconds"],
                                                 break_gap=settings["silence_gap"])
                review.export_html_report(self.items, path, source_name=name, media_duration=self.duration,
                                          chapters=chapters)
        except (OSError, ValueError) as exc:
            self.status_label.setText(f"匯出失敗：{exc}")
            return ""
        self.last_export = path
        what = {"edl": "EDL（可匯入 Premiere Pro／DaVinci Resolve，時間軸就是保留的段落）",
                "srt": "審片標記字幕（跟原始素材一起載入剪輯軟體，拉時間軸就看得到【精彩】【冷場】等標記）",
                "csv": "CSV 片段清單", "html": "HTML 審片報告（用瀏覽器開，可以直接傳給剪輯師）"}[key]
        self.status_label.setText(f"已匯出{what}：{path}")
        return path
