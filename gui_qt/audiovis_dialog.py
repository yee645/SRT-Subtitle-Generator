# -*- coding: utf-8 -*-
"""
①「素材準備」的音訊轉影片小視窗（3.0 第 11 項第二十一階段）：一般版 `gui/audiovis_dialog.py` 搬過來。

Podcast、訪談錄音這類素材手上只有音訊，平台卻要上傳影片：把音訊轉成附波形或頻譜的 mp4，
可選擇疊在背景圖（例如節目封面）上。核心同一個 `subtitle.audiovis.render_audio_video`、同一份設定
（config 的 audiovis）、同樣的範圍。只記在這次開啟的設定裡（Qt 預覽版不寫 config.json）。

比一般版多的：
- 轉好之後可以直接在②開啟（同一條時間軸，原本對著音訊做的字幕照樣對得上）；
- 「頻譜」不吃顏色，選頻譜時顏色那格灰掉；顏色格式不對時講出來，而不是默默換成預設；
- 輸出位置跟 Qt 其他輸出一樣：放在來源旁邊，「輸出設定」指定了資料夾就放那裡；同名加編號不覆蓋。

不擋住主視窗（非強制回應）。轉換在背景跑，全在本機，什麼都不送出去。
"""
import os
import re
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QSpinBox, QVBoxLayout,
)

from subtitle import audiovis
from subtitle.burner import ffmpeg_available
from subtitle.errors import describe_exception
from subtitle.pipeline import resolve_output_dir, unique_path

TITLE = "音訊轉影片：波形／頻譜視覺化"
MODES = (("waveform", "波形"), ("spectrum", "頻譜"))
SUFFIX = "_視覺化影片.mp4"  # 跟一般版 suggest_output_path 同一個後綴
HINT = "選好音訊素材後按「輸出視覺化影片」；轉好的影片可以直接在②開啟，接著生成字幕、校對、燒錄。"
BG_NOTE = "有背景圖時，視覺化縮成下緣一條色帶疊加（例如節目封面）；背景圖會裁切置中填滿整個畫面。留空輸出純黑底。"
NO_SOURCE = "請選擇有效的來源音訊。"
NO_FFMPEG = "找不到 ffmpeg，轉換視覺化影片需要它：請先在一般版按「自動安裝 ffmpeg」（兩版共用）。"
NO_BACKGROUND = "找不到背景圖片：{path}（要純黑底的話按「清除」）。"
BAD_COLOR = "顏色要寫成 #RRGGBB（例如 #3fa9f5）。"
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
AUDIO_FILTER = "音訊檔 (*.mp3 *.wav *.m4a *.aac *.flac *.ogg);;所有檔案 (*)"
IMAGE_FILTER = "圖片檔 (*.png *.jpg *.jpeg *.bmp);;所有檔案 (*)"


def output_path_for(source, config):
    """輸出到哪：來源旁邊（「輸出設定」指定了資料夾就放那裡），檔名加「_視覺化影片」，同名加編號。"""
    folder = resolve_output_dir(source, (config or {}).get("automation") or {})
    os.makedirs(folder, exist_ok=True)
    base = os.path.splitext(os.path.basename(source))[0]
    return unique_path(os.path.join(folder, base + SUFFIX))


class RenderWorker(QObject):
    """背景執行緒：一般版同一個 `render_audio_video`。busy 由畫面那邊放下。"""

    progress = Signal(float, str)
    finished = Signal(str)
    failed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False

    def start(self, source, output, settings):
        self.busy = True
        threading.Thread(target=self._run, args=(source, output, dict(settings)), daemon=True).start()

    def _run(self, source, output, settings):
        try:
            audiovis.render_audio_video(source, output, settings=settings,
                                        progress_cb=lambda r, m: self.progress.emit(float(r), str(m)))
        except Exception as exc:  # noqa: BLE001 —— 背景執行緒的例外一律送回畫面上講
            self.failed.emit(exc)
            return
        self.finished.emit(output)


class AudioVisDialog(QDialog):
    """音訊轉視覺化影片。`player` 是②的播放器：預設來源取它開著的檔，轉好可以在那裡開。"""

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.player = player
        self.config = player._config
        self.last_output = ""
        self.setWindowTitle(TITLE)
        self.setModal(False)
        settings = audiovis.resolve_audiovis_settings(self.config)

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("來源音訊："))
        self.source_edit = QLineEdit(player.media_path if player.media_path and os.path.exists(player.media_path)
                                     else "")
        self.source_edit.setPlaceholderText("音訊檔（mp3、wav、m4a…；有音訊的影片也可以）")
        row.addWidget(self.source_edit, 1)
        self.source_btn = QPushButton("瀏覽…")
        row.addWidget(self.source_btn)
        layout.addLayout(row)

        self.ffmpeg_label = QLabel(NO_FFMPEG)
        self.ffmpeg_label.setWordWrap(True)
        self.ffmpeg_label.setStyleSheet("color: #b35c00;")
        self.ffmpeg_label.setVisible(not ffmpeg_available())
        layout.addWidget(self.ffmpeg_label)

        box = QGroupBox("視覺化樣式")
        grid = QGridLayout(box)
        grid.addWidget(QLabel("樣式："), 0, 0)
        self.mode_box = QComboBox()
        for key, label in MODES:
            self.mode_box.addItem(label, key)
        self.mode_box.setCurrentIndex([k for k, _l in MODES].index(settings["mode"]))
        grid.addWidget(self.mode_box, 0, 1)
        grid.addWidget(QLabel("波形顏色："), 0, 2)
        self.color_edit = QLineEdit(settings["color"])
        self.color_edit.setMaximumWidth(110)
        self.color_edit.setToolTip("#RRGGBB；只有「波形」用得到")
        grid.addWidget(self.color_edit, 0, 3)
        self.color_btn = QPushButton("選顏色…")
        grid.addWidget(self.color_btn, 0, 4)
        grid.addWidget(QLabel("解析度："), 1, 0)
        size = QHBoxLayout()
        self.width_spin = QSpinBox()
        self.width_spin.setRange(*audiovis._WIDTH_RANGE)
        self.width_spin.setSingleStep(160)
        self.width_spin.setValue(settings["width"])
        self.height_spin = QSpinBox()
        self.height_spin.setRange(*audiovis._HEIGHT_RANGE)
        self.height_spin.setSingleStep(90)
        self.height_spin.setValue(settings["height"])
        size.addWidget(self.width_spin)
        size.addWidget(QLabel("×"))
        size.addWidget(self.height_spin)
        size.addStretch(1)
        grid.addLayout(size, 1, 1, 1, 4)
        layout.addWidget(box)

        bg = QGroupBox("背景圖片")
        bg_layout = QVBoxLayout(bg)
        row = QHBoxLayout()
        self.bg_edit = QLineEdit(settings["background_image"])
        self.bg_edit.setPlaceholderText("留空：純黑底全畫面視覺化")
        row.addWidget(self.bg_edit, 1)
        self.bg_btn = QPushButton("瀏覽…")
        self.bg_clear_btn = QPushButton("清除")
        row.addWidget(self.bg_btn)
        row.addWidget(self.bg_clear_btn)
        bg_layout.addLayout(row)
        bg_note = QLabel(BG_NOTE)
        bg_note.setWordWrap(True)
        bg_layout.addWidget(bg_note)
        layout.addWidget(bg)

        self.status_label = QLabel(HINT)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)
        buttons = QHBoxLayout()
        self.run_btn = QPushButton("輸出視覺化影片")
        self.open_btn = QPushButton("在②開啟")
        self.open_btn.setToolTip("把轉好的影片開在②的播放器（同一條時間軸，字幕照樣對得上）")
        self.close_btn = QPushButton("關閉")
        buttons.addWidget(self.run_btn)
        buttons.addWidget(self.open_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

        self.worker = RenderWorker(self)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.source_btn.clicked.connect(self._choose_source)
        self.bg_btn.clicked.connect(self._choose_background)
        self.bg_clear_btn.clicked.connect(self.bg_edit.clear)
        self.color_btn.clicked.connect(self._choose_color)
        self.mode_box.currentIndexChanged.connect(lambda _i: self._update_buttons())
        self.run_btn.clicked.connect(lambda _c=False: self.start())
        self.open_btn.clicked.connect(lambda _c=False: self.open_in_player())
        self.close_btn.clicked.connect(self.close)
        self._update_buttons()
        self.resize(640, 0)

    # ----- 設定 -----
    def settings(self):
        """畫面上的設定寫進這次開啟的設定（audiovis；別的項目留著），回傳核心整理過的版本。"""
        current = dict(self.config.get("audiovis") or {})
        current.update({"mode": self.mode_box.currentData(), "color": self.color_edit.text().strip(),
                        "width": self.width_spin.value(), "height": self.height_spin.value(),
                        "background_image": self.bg_edit.text().strip()})
        self.config["audiovis"] = current
        return audiovis.resolve_audiovis_settings(self.config)

    def _update_buttons(self):
        busy = self.worker.busy
        waveform = self.mode_box.currentData() == "waveform"
        self.color_edit.setEnabled(waveform and not busy)
        self.color_btn.setEnabled(waveform and not busy)
        for widget in (self.source_edit, self.source_btn, self.mode_box, self.width_spin, self.height_spin,
                       self.bg_edit, self.bg_btn, self.bg_clear_btn, self.run_btn):
            widget.setEnabled(not busy)
        self.open_btn.setEnabled(not busy and bool(self.last_output) and os.path.exists(self.last_output))
        self.progress_bar.setVisible(busy)

    # ----- 選檔（測試換掉這幾個） -----
    def _ask_source_path(self):
        path, _ = QFileDialog.getOpenFileName(self, "選擇來源音訊", "", AUDIO_FILTER)
        return path

    def _ask_background_path(self):
        path, _ = QFileDialog.getOpenFileName(self, "選擇背景圖片", "", IMAGE_FILTER)
        return path

    def _ask_color(self, current):
        color = QColorDialog.getColor(QColor(current), self, "波形顏色")
        return color.name() if color.isValid() else ""

    def _ask_open(self, path):
        return QMessageBox.question(
            self, "轉換完成", f"已輸出視覺化影片：\n{path}\n\n要在②開啟這支影片嗎？"
            "（同一條時間軸：原本對著音訊做的字幕照樣對得上）") == QMessageBox.Yes

    def ask_close_while_rendering(self):
        return QMessageBox.question(self, "還在轉換", self.close_question()) == QMessageBox.Yes

    def _choose_source(self):
        path = self._ask_source_path()
        if path:
            self.source_edit.setText(path)

    def _choose_background(self):
        path = self._ask_background_path()
        if path:
            self.bg_edit.setText(path)

    def _choose_color(self):
        current = self.color_edit.text().strip()
        color = self._ask_color(current if _HEX_RE.match(current) else audiovis.DEFAULT_AUDIOVIS["color"])
        if color:
            self.color_edit.setText(color)

    # ----- 轉換 -----
    def rendering(self):
        return self.worker.busy

    def _refuse(self, text):
        self.status_label.setText(text)
        return False

    def start(self):
        """開始轉換。回傳有沒有開始。"""
        if self.worker.busy:
            return False
        source = self.source_edit.text().strip()
        if not source or not os.path.isfile(source):
            return self._refuse(NO_SOURCE)
        if not ffmpeg_available():
            self.ffmpeg_label.setVisible(True)
            return self._refuse(NO_FFMPEG)
        color = self.color_edit.text().strip()
        if self.mode_box.currentData() == "waveform" and not _HEX_RE.match(color):
            return self._refuse(BAD_COLOR)
        background = self.bg_edit.text().strip()
        if background and not os.path.isfile(background):
            return self._refuse(NO_BACKGROUND.format(path=background))
        settings = self.settings()
        output = output_path_for(source, self.config)
        self.worker.start(source, output, settings)
        self.progress_bar.setValue(0)
        self.status_label.setText(f"正在轉換（{os.path.basename(output)}，原檔不動）…")
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
        self.status_label.setText(f"音訊轉影片失敗：{err}{detail}")
        self._update_buttons()

    def _on_finished(self, output):
        self.worker.busy = False
        self.last_output = output
        self._update_buttons()
        self.status_label.setText(f"轉換完成：{output}")
        if self.isVisible() and self._ask_open(output):
            self.open_in_player()

    def open_in_player(self):
        """把轉好的影片開在②（換影片前照②的規矩先問專案）。回傳有沒有開。"""
        path = self.last_output
        if not path or not os.path.exists(path):
            return False
        if not self.player._maybe_drop_project():
            return False
        self.player.open_video(path)
        self.status_label.setText(f"已在②開啟：{os.path.basename(path)}")
        return True

    # ----- 關閉 -----
    def close_question(self):
        return ("視覺化影片還在轉換。\n\n現在關掉的話這個檔可能不完整，請不要拿它來用"
                "（要的話重開之後再轉一次）。還是要關嗎？")

    def closeEvent(self, event):  # noqa: N802
        if self.worker.busy and not self.ask_close_while_rendering():
            event.ignore()
            return
        super().closeEvent(event)
