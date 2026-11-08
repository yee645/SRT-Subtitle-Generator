# -*- coding: utf-8 -*-
"""
生成字幕（3.0 第 11 項第六階段）：播放列的「生成字幕…」打開這個小視窗。

生成本身跟一般版同一套（`subtitle/pipeline.generate_cues`：Whisper 語音轉寫或文字稿對齊 → 智慧斷句 →
自動修正詞庫），用一般版「轉寫設定」裡的模型、提示詞、金鑰與快取。這裡多做的幾件事：

* **開始前寫清楚會不會送出去**（`pipeline.generation_plan`）：本地 Whisper 什麼都不送；OpenAI 模式寫明
  送聲音（文字稿對齊時文字稿也會當提示詞送）、照用量收費。OpenAI 模式沒有金鑰就不能按開始。
* **會換掉目前的字幕**：有還沒存的修改，按開始時先問（存檔／放棄／取消）。
* **取消**：Whisper 沒辦法從中間打斷，取消後辨識在背景跑完才真的停，結果不套用；跑完之前不能再按開始。
* 生成完整份換掉（還沒有字幕檔，「存字幕」會問存到哪，建議跟影片同名）。選的語言與做法只記在這次
  開啟的設定裡：Qt 預覽版不寫回 config.json。
"""
import os
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar,
    QPushButton, QRadioButton, QVBoxLayout,
)

from subtitle import pipeline
from subtitle.errors import describe_exception
from subtitle.transcriber import LANGUAGE_LABELS

MODE_LABELS = (("transcribe", "語音轉寫（Whisper 聽聲音）"), ("align", "文字稿對齊（已有講稿，只對時間）"))
NO_KEY = "轉寫設定是用 OpenAI，但還沒有金鑰：請先在一般版（不加 --qt）的「轉寫設定」填好，或改回本地 Whisper。"


class GenerateWorker(QObject):
    """背景執行緒跑 pipeline.generate_cues；進度與結果用訊號送回主執行緒。"""

    progress = Signal(float, str)
    finished = Signal(object, int)  # (字幕, 自動修正了幾處)
    failed = Signal(object)         # 例外
    cancelled = Signal()            # 取消後背景跑完了（結果丟掉）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        self._cancel = threading.Event()

    def start(self, media_path, config, mode, transcript):
        self.busy = True
        self._cancel.clear()
        threading.Thread(target=self._run, args=(media_path, config, mode, transcript), daemon=True).start()

    def cancel(self):
        self._cancel.set()

    @property
    def cancelling(self):
        return self.busy and self._cancel.is_set()

    def _run(self, media_path, config, mode, transcript):
        def report(message, ratio=None):
            if not self._cancel.is_set():
                self.progress.emit(-1.0 if ratio is None else float(ratio), str(message))

        try:
            cues, corrected = pipeline.generate_cues(media_path, config, mode, transcript, report)
        except Exception as exc:  # noqa: BLE001 —— 背景執行緒：什麼錯都要送回去說
            self.busy = False
            if self._cancel.is_set():
                self.cancelled.emit()
            else:
                self.failed.emit(exc)
            return
        self.busy = False
        if self._cancel.is_set():
            self.cancelled.emit()
            return
        self.finished.emit(cues, int(corrected))


class GenerateDialog(QDialog):
    """生成字幕的小視窗。player＝PlayerPanel（影片、字幕、這次開啟的設定都在那邊）。"""

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.setWindowTitle("生成字幕")
        self.setWindowModality(Qt.WindowModal)
        self.player = player
        self._snapshot = None
        self._loaded_sidecar = ""
        self.worker = GenerateWorker(self)

        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        modes = QVBoxLayout()
        for value, label in MODE_LABELS:
            button = QRadioButton(label)
            self.mode_group.addButton(button)
            self.mode_buttons[value] = button
            modes.addWidget(button)
        self.mode_buttons["transcribe"].setChecked(True)
        self.language_box = QComboBox()
        for code, label in LANGUAGE_LABELS.items():
            self.language_box.addItem(label, code)
        self.transcript_edit = QPlainTextEdit()
        self.transcript_edit.setPlaceholderText("把講稿貼在這裡（一行一句或整段都可以）")
        self.transcript_edit.setMinimumHeight(110)
        self.transcript_note = QLabel()
        self.transcript_note.setWordWrap(True)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.start_btn = QPushButton("開始生成")
        self.start_btn.setDefault(True)
        self.cancel_btn = QPushButton("取消")
        self.close_btn = QPushButton("關閉")

        form = QFormLayout()
        form.addRow("做法：", modes)
        form.addRow("語言：", self.language_box)
        buttons = QHBoxLayout()
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.cancel_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.close_btn)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.transcript_edit)
        layout.addWidget(self.transcript_note)
        layout.addWidget(self.notice)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addLayout(buttons)
        self.setMinimumWidth(480)

        self.mode_group.buttonToggled.connect(lambda *_a: self.refresh())
        self.language_box.currentIndexChanged.connect(lambda *_a: self.refresh())
        self.transcript_edit.textChanged.connect(self.refresh)
        self.start_btn.clicked.connect(self.start)
        self.cancel_btn.clicked.connect(self.cancel)
        self.close_btn.clicked.connect(self.close)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)

    # ---- 對外 ----------------------------------------------------------

    def mode(self):
        return next(value for value, button in self.mode_buttons.items() if button.isChecked())

    def config(self):
        """生成要用的設定：這次開啟的設定，語言換成這裡選的。"""
        config = dict(self.player._config)
        config["transcription"] = dict(config.get("transcription") or {},
                                       language=self.language_box.currentData())
        return config

    def prepare(self):
        """打開前：照這次開啟的設定擺好語言；對齊用的講稿沒填過就找影片旁同名的 .txt。"""
        if self.worker.busy:
            self.refresh()
            return
        language = str((self.player._config.get("transcription") or {}).get("language") or "auto")
        at = self.language_box.findData(language)
        self.language_box.setCurrentIndex(at if at >= 0 else 0)
        sidecar = pipeline.find_sidecar_transcript(self.player.media_path) if self.player.media_path else None
        if sidecar and (not self.transcript_edit.toPlainText().strip() or self._loaded_sidecar):
            try:
                with open(sidecar, encoding="utf-8") as fh:
                    self.transcript_edit.setPlainText(fh.read())
                self._loaded_sidecar = sidecar
            except (OSError, UnicodeDecodeError):
                self._loaded_sidecar = ""
        elif self._loaded_sidecar:  # 換了影片、旁邊沒有講稿：不要留著上一支的
            self.transcript_edit.setPlainText("")
            self._loaded_sidecar = ""
        self.progress.setValue(0)
        self.status.setText("")
        self.refresh()

    def refresh(self):
        """照做法、設定與目前的字幕重寫說明，決定能不能按開始。"""
        mode = self.mode()
        plan = pipeline.generation_plan(self.config(), mode)
        busy = self.worker.busy
        align = mode == "align"
        self.transcript_edit.setVisible(align)
        self.transcript_note.setVisible(align)
        if self._loaded_sidecar:
            self.transcript_note.setText(f"已帶入影片旁的「{os.path.basename(self._loaded_sidecar)}」，可以再改。")
        else:
            self.transcript_note.setText("影片旁放一個同名的 .txt，打開這裡就會自動帶入。")

        lines = []
        if plan["api"]:
            what = "、".join(plan["sends"])
            lines.append(f"用 OpenAI 轉寫：會把{what}送到 OpenAI，OpenAI 照用量收費。"
                         "檔名、字幕與其他檔案都不會送。")
            if not plan["has_key"]:
                lines.append(NO_KEY)
        else:
            lines.append(f"在這台電腦上用 Whisper（模型 {plan['model']}）辨識，聲音不會送出去。"
                         "第一次用這個模型要先下載；影片越長、模型越大越久。")
        if self.player.cues:
            lines.append(f"生成完會換掉目前的 {len(self.player.cues)} 句字幕。")
        lines.append("模型、提示詞與金鑰照一般版的「轉寫設定」，要改請到一般版。")
        self.notice.setText("\n".join(lines))

        ready = bool(self.player.media_path) and (plan["has_key"] or not plan["api"])
        if align and not self.transcript_edit.toPlainText().strip():
            ready = False
        self.start_btn.setEnabled(ready and not busy)
        self.cancel_btn.setEnabled(busy and not self.worker.cancelling)
        self.language_box.setEnabled(not busy)
        self.transcript_edit.setReadOnly(busy)
        for button in self.mode_buttons.values():
            button.setEnabled(not busy)

    def start(self):
        """開始生成（背景跑）。回傳是否開始了。"""
        if not self.start_btn.isEnabled():  # 跑的時候（含取消後還在收尾）、條件不夠時都是灰的
            return False
        if not self.player.maybe_discard():  # 有還沒存的修改：先問
            self.status.setText("沒有開始：目前的字幕還有沒存的修改。")
            return False
        config = self.config()
        # 記住這次選的語言——只記在這次開啟的設定裡，不寫回 config.json
        self.player._config["transcription"] = dict(config["transcription"])
        self._snapshot = [dict(c) for c in self.player.cues]
        self.progress.setValue(0)
        self.status.setText("準備開始…")
        self.worker.start(self.player.media_path, config, self.mode(), self.transcript_edit.toPlainText())
        self.refresh()
        return True

    def cancel(self):
        """取消：結果不套用。Whisper 沒辦法從中間打斷，背景跑完才真的停。"""
        if self.worker.busy and not self.worker.cancelling:
            self.worker.cancel()
            self.status.setText("已取消，結果不會套用。辨識沒辦法從中間打斷，會在背景跑完才停；"
                                "停之前不能再開始。")
            self.refresh()

    def closeEvent(self, event):  # noqa: N802 —— Qt 的命名
        self.cancel()  # 生成到一半關掉＝取消，結果不套用
        super().closeEvent(event)

    # ---- 內部 ----------------------------------------------------------

    def _on_progress(self, ratio, message):
        if ratio >= 0:
            self.progress.setValue(int(round(min(ratio, 1.0) * 100)))
        self.status.setText(message)

    def _on_finished(self, cues, corrected):
        self.progress.setValue(100)
        if self.player.cues != self._snapshot:
            self.status.setText("生成的時候字幕改過了，為了不蓋掉剛剛的修改，這次沒有套用。請再生成一次。")
            self.refresh()
            return
        self.player.set_generated_cues(cues)
        text = f"生成完成，共 {len(cues)} 句"
        if corrected:
            text += f"（自動修正詞庫改了 {corrected} 處）"
        text += "。還沒存成字幕檔，記得按「存字幕」。"
        self.status.setText(text)
        self.refresh()
        self.player.cuesGenerated.emit(text)  # 逐句校對下面寫這句（這個視窗接著關掉）
        self.accept()

    def _on_failed(self, exc):
        err = describe_exception(exc)
        parts = [f"生成失敗，字幕沒有改：{err}"]
        if err.cause:
            parts.append(f"原因：{err.cause}")
        if err.solution:
            parts.append(f"解法：{err.solution}")
        self.status.setText("\n".join(parts))
        self.progress.setValue(0)
        self.refresh()

    def _on_cancelled(self):
        self.status.setText("已取消，字幕沒有改。")
        self.progress.setValue(0)
        self.refresh()
