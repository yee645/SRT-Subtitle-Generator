# -*- coding: utf-8 -*-
"""
④輸出與發佈的「成品加工：品牌套版」（3.0 第 11 項第十四階段）。

跟一般版的「品牌套版」視窗同一套：同一份設定（config 的 branding）、同一個函式
（`subtitle.branding.apply_branding`）、同一個建議檔名（來源檔名加「_套版」，同名加編號、不覆蓋）。
一般版是另開的視窗，這裡直接放在④輸出頁「輸出」框的下面。

來源影片留空＝②字幕頁開著的影片；也可以另外選。④燒錄完硬字幕之後，來源會自動填成剛燒好的那一支
（建議順序：燒錄→套版）——一般版是把燒錄版「設為目前影片」；這裡不換②的影片（②還帶著字幕，換成燒錄
版畫面上會疊兩層字），只換套版的來源。

片頭、片尾、浮水印至少設一項。套版在背景用 ffmpeg 跑，輸出到一半不能停（一般版也不能）。
設定只記在這次開啟的設定裡（Qt 預覽版不寫 config.json）。
"""
import os
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QSpinBox, QVBoxLayout,
)

from subtitle import branding
from subtitle.burner import ffmpeg_available
from subtitle.errors import describe_exception
from subtitle.pipeline import unique_path

VIDEO_FILTER = "影片檔 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v);;所有檔案 (*)"
IMAGE_FILTER = "圖片檔 (*.png *.jpg *.jpeg *.webp *.bmp);;所有檔案 (*)"
NOTE = ("幫影片接上片頭、片尾，疊上浮水印（Logo），設定一次、之後每支沿用。建議順序：燒錄→套版；"
        "④燒錄完，來源會自動換成剛燒好的那一支。輸出成新檔（來源檔名加「_套版」），原檔不動；輸出到一半不能停。")
IDLE = "設定好片頭／片尾／浮水印其中至少一項後，按「輸出套版影片」。"
NO_SOURCE = "沒有來源影片：請先在②字幕頁開影片，或在「來源影片」另外選一支。"
NO_FFMPEG = "找不到 ffmpeg，品牌套版需要它：請先在一般版按「自動安裝 ffmpeg」（兩版共用）。"
NOTHING_SET = "請至少設定片頭、片尾或浮水印其中一項。"
OTHER_BUSY = "上面的輸出還在跑，等它做完再套版。"
PATH_ROWS = (("intro_path", "片頭", VIDEO_FILTER, "選擇片頭影片"), ("outro_path", "片尾", VIDEO_FILTER, "選擇片尾影片"),
             ("watermark_path", "浮水印", IMAGE_FILTER, "選擇浮水印圖片"))


class BrandingWorker(QObject):
    """背景執行緒跑 branding.apply_branding。busy 由畫面那邊（主執行緒）放下。"""

    progress = Signal(float, str)
    finished = Signal(str)
    failed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False

    def start(self, source, output, settings):
        self.busy = True
        threading.Thread(target=self._run, args=(source, output, settings), daemon=True).start()

    def _run(self, source, output, settings):
        try:
            path = branding.apply_branding(source, output, settings=settings,
                                           progress_cb=lambda r, m: self.progress.emit(float(r), str(m)))
        except Exception as exc:  # noqa: BLE001 —— 背景執行緒的例外一律送回畫面上講
            self.failed.emit(exc)
            return
        self.finished.emit(str(path))


class BrandingBox(QGroupBox):
    """「成品加工：品牌套版」那一框。other_busy：上面的輸出是不是還在跑（一次只跑一件）。"""

    def __init__(self, player, other_busy=None, parent=None):
        super().__init__("成品加工：品牌套版（片頭／片尾／浮水印）", parent)
        self.player = player
        self.config = player._config
        self.other_busy = other_busy
        self.last_output = ""
        settings = branding.resolve_branding_settings(self.config)

        layout = QVBoxLayout(self)
        note = QLabel(NOTE)
        note.setWordWrap(True)
        layout.addWidget(note)
        grid = QGridLayout()
        grid.addWidget(QLabel("來源影片"), 0, 0)
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("留空＝②字幕頁開著的影片")
        self.source_btn = QPushButton("瀏覽…")
        self.source_btn.clicked.connect(lambda: self._browse(self.source_edit, "選擇來源影片", VIDEO_FILTER))
        self.source_clear = QPushButton("清除")
        self.source_clear.clicked.connect(self.source_edit.clear)
        grid.addWidget(self.source_edit, 0, 1)
        grid.addWidget(self.source_btn, 0, 2)
        grid.addWidget(self.source_clear, 0, 3)
        self.path_edits, self.path_btns = {}, {}
        for row, (key, label, file_filter, title) in enumerate(PATH_ROWS, start=1):
            edit = QLineEdit(settings[key])
            edit.setPlaceholderText("留空＝不套用")
            edit.textChanged.connect(self.collect_settings)
            browse = QPushButton("瀏覽…")
            browse.clicked.connect(lambda _c=False, e=edit, t=title, f=file_filter: self._browse(e, t, f))
            clear = QPushButton("清除")
            clear.clicked.connect(edit.clear)
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(edit, row, 1)
            grid.addWidget(browse, row, 2)
            grid.addWidget(clear, row, 3)
            self.path_edits[key] = edit
            self.path_btns[key] = (browse, clear)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        row = QHBoxLayout()
        self.position_combo = QComboBox()
        for key, label in branding.POSITION_LABELS.items():
            self.position_combo.addItem(label, key)
        self.position_combo.setCurrentIndex(max(0, self.position_combo.findData(settings["watermark_position"])))
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(5, 50)
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setValue(int(round(settings["watermark_scale"] * 100)))
        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setRange(0.1, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setDecimals(2)
        self.opacity_spin.setValue(settings["watermark_opacity"])
        self.margin_spin = QSpinBox()
        self.margin_spin.setRange(0, 200)
        self.margin_spin.setSingleStep(4)
        self.margin_spin.setSuffix(" px")
        self.margin_spin.setValue(int(round(settings["watermark_margin"])))
        self.position_combo.currentIndexChanged.connect(self.collect_settings)
        for spin in (self.scale_spin, self.opacity_spin, self.margin_spin):
            spin.valueChanged.connect(self.collect_settings)
        for label, widget in (("浮水印位置", self.position_combo), ("大小（佔畫面寬）", self.scale_spin),
                              ("不透明度", self.opacity_spin), ("邊緣留白", self.margin_spin)):
            row.addWidget(QLabel(label))
            row.addWidget(widget)
        row.addStretch(1)
        layout.addLayout(row)

        row = QHBoxLayout()
        self.run_btn = QPushButton("輸出套版影片")
        self.run_btn.clicked.connect(self.start)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        self.status_label = QLabel(IDLE)
        self.status_label.setWordWrap(True)
        row.addWidget(self.run_btn)
        row.addWidget(self.progress_bar)
        row.addWidget(self.status_label, 1)
        layout.addLayout(row)

        self.worker = BrandingWorker(self)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)

    # ----- 設定 -----
    def _browse(self, edit, title, file_filter):
        start = os.path.dirname(edit.text().strip() or self.player.media_path or "")
        path, _ = QFileDialog.getOpenFileName(self, title, start, file_filter)
        if path:
            edit.setText(path)

    def collect_settings(self, *_args):
        """畫面上的值寫進這次開啟的設定（branding，跟一般版同一個區塊），回傳夾過範圍的那一份。"""
        self.config["branding"] = {
            **{key: edit.text().strip() for key, edit in self.path_edits.items()},
            "watermark_position": self.position_combo.currentData(),
            "watermark_opacity": round(self.opacity_spin.value(), 2),
            "watermark_scale": self.scale_spin.value() / 100.0,
            "watermark_margin": float(self.margin_spin.value()),
        }
        return branding.resolve_branding_settings(self.config)

    def source_path(self):
        """這次要套版的影片：另外選的優先，沒有就用②開著的。"""
        return self.source_edit.text().strip() or (self.player.media_path or "")

    def set_source(self, path):
        """④燒錄完叫：來源換成剛燒好的那一支。"""
        self.source_edit.setText(path or "")

    # ----- 輸出 -----
    def busy(self):
        return self.worker.busy

    def start(self):
        if self.busy():
            return False
        if callable(self.other_busy) and self.other_busy():
            return self._refuse(OTHER_BUSY)
        source = self.source_path()
        if not source or not os.path.exists(source):
            return self._refuse(NO_SOURCE)
        if not ffmpeg_available():
            return self._refuse(NO_FFMPEG)
        settings = self.collect_settings()
        if not (branding.has_intro_or_outro(settings) or branding.has_watermark(settings)):
            return self._refuse(NOTHING_SET)
        output = unique_path(branding.suggest_output_path(source))
        self.worker.start(source, output, settings)
        self.progress_bar.setValue(0)
        self._set_busy(True)
        self.status_label.setText(f"套版中（輸出到一半不能停）：{os.path.basename(source)}")
        return True

    def _refuse(self, text):
        self.status_label.setText(text)
        return False

    def _set_busy(self, busy):
        self.progress_bar.setVisible(busy)
        self.run_btn.setEnabled(not busy)
        self.run_btn.setText("套版中…" if busy else "輸出套版影片")
        widgets = [self.source_edit, self.source_btn, self.source_clear, self.position_combo, self.scale_spin,
                   self.opacity_spin, self.margin_spin, *self.path_edits.values()]
        for pair in self.path_btns.values():
            widgets.extend(pair)
        for widget in widgets:
            widget.setEnabled(not busy)

    def _on_progress(self, ratio, message):
        self.progress_bar.setValue(int(max(0.0, min(ratio, 1.0)) * 1000))
        if message:
            self.status_label.setText(f"套版中：{message}")

    def _on_failed(self, exc):
        self.worker.busy = False
        self._set_busy(False)
        err = describe_exception(exc)
        detail = f"（{err.details}）" if err.details and err.details != str(err) else ""
        self.status_label.setText(f"套版失敗：{err}{detail}")

    def _on_finished(self, path):
        self.last_output = path
        self.worker.busy = False
        self._set_busy(False)
        self.status_label.setText(f"套版完成：{path}")
