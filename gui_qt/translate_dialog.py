# -*- coding: utf-8 -*-
"""
翻譯字幕（3.0 第 11 項第三階段）：逐句校對的「翻譯字幕…」打開這個小視窗。

翻譯本身跟一般版同一套（`subtitle/translator.py`：同一把 OpenAI 金鑰、同一個模型、同樣分批、
解析失敗的句子沿用原文）。這裡只多做一般版沒有的幾件事：

* **送出前寫清楚會送什麼**：幾句、幾個字的字幕文字；時間、檔名、影片與聲音都不送。
  沒有金鑰就不能按開始，說去哪裡填（預覽版沒有設定頁）。
* **翻到一半可以停**：每一批送出前看一下有沒有按「停止」，停了就什麼都不改。
* **翻完整份是一步復原**（Ctrl+Z 一次退回，逐字時間軸也回來）。翻的時候字幕若被改過（照理
  視窗擋著改不了，這裡再保險一次），就不套用、說原因，免得蓋掉。
* 選的語言與模式只記在這次開啟的設定裡：Qt 預覽版不寫回 config.json。

一般版翻譯視窗裡的「多語字幕包」（一次輸出好幾個語言的檔案）這一階段先不搬。
"""
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QRadioButton, QVBoxLayout,
)

from subtitle import translator

MODE_LABELS = (("bilingual", "雙語（原文在上、譯文在下）"), ("replace", "只留譯文（取代原文）"))
NO_KEY = "還沒有 OpenAI API 金鑰：請先在一般版（不加 --qt）的「轉寫設定」填好，再回來翻譯。"


class _Stopped(Exception):
    """使用者按了停止：在下一批送出前丟出來，整個翻譯就此結束、什麼都不改。"""


class TranslateWorker(QObject):
    """背景執行緒跑 translator.translate_cues；進度與結果用訊號送回主執行緒。"""

    progress = Signal(float, str)
    finished = Signal(object, str)  # (新的字幕清單, 最後一句進度訊息：含幾句沿用原文)
    failed = Signal(str)
    stopped = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        self._stop = threading.Event()

    def start(self, cues, settings, api_key):
        self.busy = True
        self._stop.clear()
        threading.Thread(target=self._run, args=([dict(c) for c in cues], dict(settings), api_key),
                         daemon=True).start()

    def stop(self):
        self._stop.set()

    def _run(self, cues, settings, api_key):
        last = [""]

        def report(ratio, message):
            if self._stop.is_set():
                raise _Stopped()
            last[0] = str(message)
            self.progress.emit(float(ratio), str(message))

        try:
            result = translator.translate_cues(cues, settings, api_key, progress_cb=report)
        except _Stopped:
            self.busy = False
            self.stopped.emit()
            return
        except Exception as exc:  # noqa: BLE001 —— 背景執行緒：什麼錯都要送回去說
            self.busy = False
            self.failed.emit(str(exc))
            return
        self.busy = False
        if self._stop.is_set():  # 最後一批回來前才按停止：照樣不改
            self.stopped.emit()
            return
        self.finished.emit(result, last[0])


class TranslateDialog(QDialog):
    """翻譯字幕的小視窗。player＝PlayerPanel（字幕、設定、套用與復原都在那邊）。"""

    applied = Signal(str)  # 套用完：給逐句校對那邊寫在下面的一句話

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.setWindowTitle("翻譯字幕")
        self.setWindowModality(Qt.WindowModal)
        self.player = player
        self._snapshot = None
        self.worker = TranslateWorker(self)

        settings = translator.resolve_translate_settings(player._config)
        self.language_box = QComboBox()
        for code, label in translator.LANGUAGE_LABELS.items():
            self.language_box.addItem(label, code)
        self.language_box.setCurrentIndex(self.language_box.findData(settings["target_language"]))
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        modes = QVBoxLayout()
        for value, label in MODE_LABELS:
            button = QRadioButton(label)
            button.setChecked(value == settings["mode"])
            self.mode_group.addButton(button)
            self.mode_buttons[value] = button
            modes.addWidget(button)

        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.start_btn = QPushButton("開始翻譯")
        self.start_btn.setDefault(True)
        self.stop_btn = QPushButton("停止")
        self.close_btn = QPushButton("關閉")

        form = QFormLayout()
        form.addRow("翻成：", self.language_box)
        form.addRow("做法：", modes)
        buttons = QHBoxLayout()
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.stop_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.close_btn)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.notice)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addLayout(buttons)
        self.setMinimumWidth(460)

        self.start_btn.clicked.connect(self.start)
        self.stop_btn.clicked.connect(self.stop)
        self.close_btn.clicked.connect(self.close)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.stopped.connect(self._on_stopped)
        self.refresh()

    # ---- 對外 ----------------------------------------------------------

    def api_key(self):
        return str((self.player._config.get("transcription") or {}).get("api_key") or "").strip()

    def settings(self):
        mode = next(value for value, button in self.mode_buttons.items() if button.isChecked())
        batch = translator.resolve_translate_settings(self.player._config)["batch_size"]
        return {"target_language": self.language_box.currentData(), "mode": mode, "batch_size": batch}

    def refresh(self):
        """照目前的字幕與金鑰重寫說明、決定能不能按開始。"""
        summary = translator.outgoing_summary(self.player.cues)
        busy = self.worker.busy
        if not self.player.cues:
            self.notice.setText("還沒有字幕可以翻。")
        elif not self.api_key():
            self.notice.setText(NO_KEY)
        else:
            self.notice.setText(
                f"按「開始翻譯」會把這 {summary['lines']} 句字幕的文字（約 {summary['chars']} 個字）送到 "
                "OpenAI 翻譯；時間、檔名、影片和聲音都不會送出。用的是一般版「轉寫設定」裡的金鑰，"
                "OpenAI 會照用量收費。譯文是 AI 產生的，建議抽查幾句；翻完按 Ctrl+Z 可以一次退回。")
        ready = bool(self.player.cues) and bool(self.api_key())
        self.start_btn.setEnabled(ready and not busy)
        self.stop_btn.setEnabled(busy)
        self.language_box.setEnabled(not busy)
        for button in self.mode_buttons.values():
            button.setEnabled(not busy)
        if not busy and not self.status.text():
            self.status.setText(f"一共 {len(self.player.cues)} 句。")

    def start(self):
        """開始翻譯（背景跑）。回傳是否開始了。"""
        if self.worker.busy or not self.player.cues or not self.api_key():
            return False
        settings = self.settings()
        # 記住這次選的，下次打開預設就是它——只記在這次開啟的設定裡，不寫回 config.json
        self.player._config["translate"] = dict(self.player._config.get("translate") or {},
                                                target_language=settings["target_language"],
                                                mode=settings["mode"])
        self._snapshot = [dict(c) for c in self.player.cues]
        self.progress.setValue(0)
        self.status.setText("準備送出…")
        self.worker.start(self._snapshot, settings, self.api_key())
        self.refresh()
        return True

    def stop(self):
        """停止：還沒送出的那幾批就不送了，已經翻好的也不套用。"""
        if self.worker.busy:
            self.worker.stop()
            self.stop_btn.setEnabled(False)
            self.status.setText("停止中：等這一批回來就停…")

    def closeEvent(self, event):  # noqa: N802 —— Qt 的命名
        self.stop()  # 翻到一半關掉＝停止，結果不套用
        super().closeEvent(event)

    # ---- 內部 ----------------------------------------------------------

    def _on_progress(self, ratio, message):
        self.progress.setValue(int(round(ratio * 100)))
        self.status.setText(message)

    def _on_finished(self, new_cues, message):
        self.progress.setValue(100)
        if self.player.cues != self._snapshot:
            self.status.setText("翻譯的時候字幕改過了，為了不蓋掉剛剛的修改，這次沒有套用。請再翻一次。")
            self.refresh()
            return
        try:
            count = self.player.apply_cues(new_cues)
        except ValueError as exc:
            self.status.setText(f"沒有套用：{exc}。")
            self.refresh()
            return
        language = self.language_box.currentText()
        mode = "雙語" if self.mode_buttons["bilingual"].isChecked() else "只留譯文"
        text = f"已翻成{language}（{mode}），改了 {count} 句；按 Ctrl+Z 一次全部退回。"
        if "沿用原文" in message:
            text += message.replace("字幕翻譯完成", "") + "。"
        self.status.setText(text)
        self.refresh()
        self.applied.emit(text)
        self.accept()

    def _on_failed(self, message):
        self.status.setText(f"翻譯失敗，字幕沒有改：{message}")
        self.progress.setValue(0)
        self.refresh()

    def _on_stopped(self):
        self.status.setText("已停止，字幕沒有改。")
        self.progress.setValue(0)
        self.refresh()
