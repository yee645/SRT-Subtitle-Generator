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

**多語字幕包**（第七階段）：一份字幕一次翻成好幾個語言，每個語言存一個上傳用的**單語** .srt
（`影片.en.srt`），跟一般版、CLI 同一段（`subtitle/multilang.write_language_pack`）。送出前寫明每個
語言送幾句（重複的只送一次）、幾個字、幾個語言；資料夾裡已經有同名的檔先問要不要蓋掉；某個語言失敗
不影響其他語言；中途停止時，已經存好的檔照樣留著、寫明存了哪幾個。目前的字幕不會改。
"""
import os
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QRadioButton, QVBoxLayout,
)

from subtitle import multilang, translator

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


class PackWorker(QObject):
    """背景執行緒跑 multilang.write_language_pack；按停止就在下一批送出前停。"""

    progress = Signal(float, str)
    finished = Signal(object)  # write_language_pack 的結果（含 stopped）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        self._stop = threading.Event()

    def start(self, cues, languages, api_key, media_path, out_dir, batch_size, dedupe, style):
        self.busy = True
        self._stop.clear()
        args = ([dict(c) for c in cues], list(languages), api_key, media_path, out_dir, batch_size, dedupe,
                dict(style or {}))
        threading.Thread(target=self._run, args=args, daemon=True).start()

    def stop(self):
        self._stop.set()

    def _run(self, cues, languages, api_key, media_path, out_dir, batch_size, dedupe, style):
        def report(ratio, message):
            if self._stop.is_set():
                raise multilang.PackStopped()
            self.progress.emit(float(ratio), str(message))

        result = multilang.write_language_pack(cues, languages, api_key, media_path, out_dir,
                                               batch_size=batch_size, dedupe=dedupe, style=style or None,
                                               progress_cb=report)
        # 最後一個語言存好之後才按停止：檔都存好了，result 照實說存好了
        self.busy = False
        self.finished.emit(result)


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
        self.pack_worker = PackWorker(self)
        self.last_pack = None  # 上一次多語字幕包的結果（write_language_pack 的格式）

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

        pack_cfg = multilang.resolve_multilang_settings(player._config)
        self.pack_edit = QLineEdit(pack_cfg["languages"])
        self.pack_edit.setPlaceholderText("語言代碼，逗號分隔，例如 en,ja,ko")
        self.pack_btn = QPushButton("輸出多語字幕包…")
        self.pack_dedupe = QCheckBox("重複的句子只送一次（省費用，譯文一樣）")
        self.pack_dedupe.setChecked(pack_cfg["dedupe"])
        self.pack_note = QLabel()
        self.pack_note.setWordWrap(True)
        pack_box = QGroupBox("多語字幕包（上傳用：每個語言存一個單語 .srt）")
        pack_row = QHBoxLayout()
        pack_row.addWidget(QLabel("語言："))
        pack_row.addWidget(self.pack_edit, 1)
        pack_row.addWidget(self.pack_btn)
        pack_layout = QVBoxLayout(pack_box)
        pack_layout.addLayout(pack_row)
        pack_layout.addWidget(self.pack_dedupe)
        pack_layout.addWidget(self.pack_note)

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
        layout.addWidget(pack_box)
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
        self.pack_btn.clicked.connect(self.start_pack)
        self.pack_edit.textChanged.connect(lambda *_a: self.refresh())
        self.pack_dedupe.toggled.connect(lambda *_a: self.refresh())
        self.pack_worker.progress.connect(self._on_progress)
        self.pack_worker.finished.connect(self._on_pack_finished)
        self.refresh()

    # ---- 對外 ----------------------------------------------------------

    def api_key(self):
        return str((self.player._config.get("transcription") or {}).get("api_key") or "").strip()

    def settings(self):
        mode = next(value for value, button in self.mode_buttons.items() if button.isChecked())
        batch = translator.resolve_translate_settings(self.player._config)["batch_size"]
        return {"target_language": self.language_box.currentData(), "mode": mode, "batch_size": batch}

    def pack_languages(self):
        """要輸出的語言（整理過：去重、跟原文同一種的略過）。"""
        source = str((self.player._config.get("transcription") or {}).get("language") or "").strip()
        skip = multilang.resolve_multilang_settings(self.player._config)["skip_source"]
        return multilang.parse_languages(self.pack_edit.text(), source_language=source, skip_source=skip)

    def busy(self):
        return self.worker.busy or self.pack_worker.busy

    def refresh(self):
        """照目前的字幕與金鑰重寫說明、決定能不能按開始。"""
        summary = translator.outgoing_summary(self.player.cues)
        busy = self.busy()
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

        languages = self.pack_languages()
        if not self.player.cues or not self.api_key():
            self.pack_note.setText("每個語言一個單語檔，可以直接在 YouTube Studio 逐一上傳；上面的雙語是給燒錄用的。")
        elif not languages:
            self.pack_note.setText("填語言代碼，例如 en,ja,ko（跟原文同一種的會略過）。")
        else:
            pack = multilang.pack_summary(self.player.cues, languages, self.pack_dedupe.isChecked())
            names = "、".join(multilang.language_label(code) for code in languages)
            base = os.path.splitext(os.path.basename(self.player.media_path or "字幕"))[0]
            self.pack_note.setText(
                f"會把 {pack['lines']} 句字幕的文字（約 {pack['chars']} 個字）各送一次去翻 {pack['languages']} 個"
                f"語言（{names}），一共約 {pack['total_chars']} 個字，OpenAI 照用量收費。存成「{base}.{languages[0]}.srt」"
                "這樣的檔，放在你選的資料夾；目前的字幕不會改。")
        self.pack_btn.setEnabled(ready and bool(languages) and not busy)
        self.pack_edit.setEnabled(not busy)
        self.pack_dedupe.setEnabled(not busy)
        if not busy and not self.status.text():
            self.status.setText(f"一共 {len(self.player.cues)} 句。")

    def start(self):
        """開始翻譯（背景跑）。回傳是否開始了。"""
        if self.busy() or not self.player.cues or not self.api_key():
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

    def start_pack(self):
        """輸出多語字幕包：先問資料夾（已經有同名的檔先問要不要蓋掉），再背景跑。回傳是否開始了。"""
        if not self.pack_btn.isEnabled():
            return False
        languages = self.pack_languages()
        out_dir = self._ask_folder()
        if not out_dir:
            return False
        media = self.player.media_path or "字幕"
        existing = [os.path.basename(multilang.pack_path(media, code, out_dir)) for code in languages
                    if os.path.exists(multilang.pack_path(media, code, out_dir))]
        if existing and not self._ask_overwrite(existing):
            self.status.setText("沒有輸出：資料夾裡已經有同名的檔，換一個資料夾再試。")
            return False
        # 記住這次填的——只記在這次開啟的設定裡，不寫回 config.json
        self.player._config["multilang"] = dict(self.player._config.get("multilang") or {},
                                                languages=self.pack_edit.text(),
                                                dedupe=self.pack_dedupe.isChecked())
        batch = translator.resolve_translate_settings(self.player._config)["batch_size"]
        self.progress.setValue(0)
        self.status.setText("準備送出…")
        self.pack_worker.start(self.player.cues, languages, self.api_key(), media, out_dir, batch,
                               self.pack_dedupe.isChecked(), self.player._config.get("subtitle_style"))
        self.refresh()
        return True

    def stop(self):
        """停止：還沒送出的那幾批就不送了，已經翻好的也不套用（多語字幕包已經存好的檔照樣留著）。"""
        if self.worker.busy:
            self.worker.stop()
            self.stop_btn.setEnabled(False)
            self.status.setText("停止中：等這一批回來就停…")
        if self.pack_worker.busy:
            self.pack_worker.stop()
            self.stop_btn.setEnabled(False)
            self.status.setText("停止中：等這一批回來就停；已經存好的語言照樣留著…")

    def closeEvent(self, event):  # noqa: N802 —— Qt 的命名
        self.stop()  # 翻到一半關掉＝停止，結果不套用（多語字幕包已經存好的檔照樣留著）
        super().closeEvent(event)

    # ---- 內部 ----------------------------------------------------------

    def _ask_folder(self):
        """問多語字幕包要存到哪個資料夾；取消回傳空字串。測試換掉這一個。"""
        start = os.path.dirname(self.player.media_path) if self.player.media_path else ""
        return QFileDialog.getExistingDirectory(self, "多語字幕包要存到哪個資料夾", start)

    def _ask_overwrite(self, names):
        """資料夾裡已經有同名的檔：問要不要蓋掉。測試換掉這一個。"""
        answer = QMessageBox.question(self, "多語字幕包", "這個資料夾裡已經有：\n" + "\n".join(names)
                                      + "\n\n要蓋掉嗎？")
        return answer == QMessageBox.Yes

    def _on_pack_finished(self, result):
        self.last_pack = result
        languages = list(result["paths"]) + list(result["failed"]) + list(result["skipped"])
        lines = []
        if result["paths"]:
            folder = os.path.dirname(next(iter(result["paths"].values())))
            files = "、".join(os.path.basename(p) for p in result["paths"].values())
            lines.append(f"存好 {len(result['paths'])} 個：{files}（在 {folder}）")
        for code, reason in result["failed"].items():
            lines.append(f"{multilang.language_label(code)}失敗：{reason}（其他語言不受影響，可以單獨再跑）")
        if result["stopped"]:
            lines.insert(0, "已停止。")
            if result["skipped"]:
                skipped = "、".join(multilang.language_label(c) for c in result["skipped"])
                lines.append(f"沒做：{skipped}（停止時正在翻的那個沒有存）")
        elif not result["failed"]:
            lines.insert(0, f"多語字幕包完成：{len(languages)} 個語言都存好了，每個都是單語字幕，可以直接上傳。")
        self.progress.setValue(100 if not result["stopped"] else self.progress.value())
        self.status.setText("\n".join(lines))
        self.refresh()

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
