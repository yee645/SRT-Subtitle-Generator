# -*- coding: utf-8 -*-
"""
①「素材準備」的批次一鍵完成（3.0 第 11 項第二十二階段）：一般版主視窗選了兩個以上檔案時出現的〔批次一鍵完成〕。

多支影片（或音訊）用同一份設定依序跑：生成字幕 → 照④的輸出設定匯出／燒錄。核心同一個
`subtitle.pipeline.run_batch`：一支失敗不中斷整批；文字稿對齊時每支用旁邊同名的 .txt。

跟一般版一樣的：設定（轉寫設定、④的輸出設定 automation、②的字幕樣式）、檔名（`影片.srt`、
`影片_subtitled.mp4`，同名加編號不覆蓋）、做完列出每支成功或失敗與輸出了哪些檔。

比一般版多的：
- **開始前寫清楚會不會送出去**（`pipeline.generation_plan`）。用 OpenAI 時會把每一支的聲音送出去，
  所以多問一次（寫明幾支、送什麼）；不同意就不開始。本地 Whisper 什麼都不送。
- 開始前先檢查：檔案在不在、文字稿對齊時哪幾支旁邊沒有 .txt、有沒有勾任何輸出、燒錄要的 ffmpeg、
  OpenAI 的金鑰——一次講清楚，而不是跑到那一支才失敗。
- **停止**：做完正在跑的這一支就停（Whisper 與 ffmpeg 都沒辦法從中間打斷），沒處理的照實列出。
- 做完的任何一支都能〔在②開啟〕（影片＋它剛匯出的字幕），接著校對；一般版是自動換成最後一支。
  不會自動換掉②正在做的東西。

不擋住主視窗（非強制回應）。語言只記在這次開啟的設定裡（Qt 預覽版不寫 config.json）。
"""
import os
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QRadioButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout,
)

from subtitle import pipeline
from subtitle.burner import ffmpeg_available
from subtitle.errors import describe_exception
from subtitle.transcriber import LANGUAGE_LABELS

TITLE = "批次一鍵完成：多支影片依序生成字幕、匯出、燒錄"
MODE_LABELS = (("transcribe", "語音轉寫（Whisper 聽聲音）"),
               ("align", "文字稿對齊（每一支用旁邊同名的 .txt 講稿）"))
MEDIA_FILTER = ("影片或音訊 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.mp3 *.wav *.m4a *.aac *.flac *.ogg);;"
                "所有檔案 (*)")
NO_FILES = "先加入要處理的影片或音訊（可以一次選好幾個）。"
NO_FFMPEG = "勾了「燒錄硬字幕影片」但找不到 ffmpeg：請先在一般版按「自動安裝 ffmpeg」（兩版共用），或到④取消燒錄。"
NO_KEY = "轉寫設定是用 OpenAI，但還沒有金鑰：請先在一般版（不加 --qt）的「轉寫設定」填好，或改回本地 Whisper。"
DECLINED = "沒有開始：沒有同意把聲音送到 OpenAI。"
SETTINGS_NOTE = "模型、提示詞與金鑰照一般版的「轉寫設定」；輸出格式、燒錄與輸出資料夾照④的「輸出設定」，要改請到④。"


class BatchWorker(QObject):
    """背景執行緒跑 pipeline.run_batch；停止＝做完這一支就不再開始下一支。busy 由畫面那邊放下。"""

    progress = Signal(float, str)
    finished = Signal(object)  # run_batch 的結果
    failed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        self._stop = threading.Event()

    def start(self, paths, config, mode):
        self.busy = True
        self._stop.clear()
        threading.Thread(target=self._run, args=(list(paths), config, mode), daemon=True).start()

    def stop(self):
        self._stop.set()

    @property
    def stopping(self):
        return self.busy and self._stop.is_set()

    def _run(self, paths, config, mode):
        def report(message, ratio=None):
            self.progress.emit(-1.0 if ratio is None else float(ratio), str(message))

        try:
            results = pipeline.run_batch(paths, config, mode=mode, transcript="", report=report,
                                         should_stop=self._stop.is_set)
        except Exception as exc:  # noqa: BLE001 —— 背景執行緒的例外一律送回畫面上講
            self.failed.emit(exc)
            return
        self.finished.emit(results)


def summary_text(results):
    """一般版同一句總結；停止後沒處理的另外講。"""
    ok = sum(1 for r in results if r["ok"])
    skipped = sum(1 for r in results if r.get("skipped"))
    failed = len(results) - ok - skipped
    text = f"批次完成：成功 {ok}、失敗 {failed}（共 {len(results)} 個檔案）"
    if skipped:
        text += f"，按了停止，其中 {skipped} 個沒有處理"
    return text + "。"


def outputs_of(result):
    """一支成功的結果輸出了哪些檔（匯出的字幕＋燒錄的影片）。"""
    if not result["ok"]:
        return []
    outputs = list(result["result"]["exports"])
    if result["result"]["burned"]:
        outputs.append(result["result"]["burned"])
    return outputs


class BatchDialog(QDialog):
    """批次一鍵完成。`player` 是②的播放器（這次開啟的設定、〔在②開啟〕都在那邊）。"""

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.player = player
        self.config_data = player._config
        self.results = []
        self.setWindowTitle(TITLE)
        self.setModal(False)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("要處理的檔案（依序處理，一支失敗不影響其他支）："))
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list.setMinimumHeight(110)
        layout.addWidget(self.file_list)
        row = QHBoxLayout()
        self.add_btn = QPushButton("加入檔案…")
        self.add_current_btn = QPushButton("加入②開著的")
        self.remove_btn = QPushButton("移除選取")
        self.clear_btn = QPushButton("清空")
        for button in (self.add_btn, self.add_current_btn, self.remove_btn, self.clear_btn):
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)

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
        language = str((self.config_data.get("transcription") or {}).get("language") or "auto")
        at = self.language_box.findData(language)
        self.language_box.setCurrentIndex(at if at >= 0 else 0)
        form = QFormLayout()
        form.addRow("做法：", modes)
        form.addRow("語言：", self.language_box)
        layout.addLayout(form)

        self.notice = QLabel()
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.result_tree = QTreeWidget()
        self.result_tree.setHeaderLabels(["檔案", "結果"])
        self.result_tree.setColumnWidth(0, 300)
        self.result_tree.setMinimumHeight(120)
        layout.addWidget(self.result_tree, 1)

        buttons = QHBoxLayout()
        self.start_btn = QPushButton("開始批次")
        self.start_btn.setDefault(True)
        self.stop_btn = QPushButton("停止（做完這一支就停）")
        self.open_btn = QPushButton("在②開啟這支")
        self.open_btn.setToolTip("把選取的那一支（影片＋它剛匯出的字幕）開在②，接著校對")
        self.close_btn = QPushButton("關閉")
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.stop_btn)
        buttons.addWidget(self.open_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

        self.worker = BatchWorker(self)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.add_btn.clicked.connect(lambda _c=False: self.add_files(self._ask_files()))
        self.add_current_btn.clicked.connect(lambda _c=False: self.add_files([self.player.media_path]))
        self.remove_btn.clicked.connect(lambda _c=False: self.remove_selected())
        self.clear_btn.clicked.connect(lambda _c=False: self.clear_files())
        self.mode_group.buttonToggled.connect(lambda *_a: self.refresh())
        self.language_box.currentIndexChanged.connect(lambda *_a: self.refresh())
        self.file_list.itemSelectionChanged.connect(self.refresh)
        self.result_tree.itemSelectionChanged.connect(self.refresh)
        self.result_tree.itemDoubleClicked.connect(lambda *_a: self.open_selected())
        self.start_btn.clicked.connect(lambda _c=False: self.start())
        self.stop_btn.clicked.connect(lambda _c=False: self.stop())
        self.open_btn.clicked.connect(lambda _c=False: self.open_selected())
        self.close_btn.clicked.connect(self.close)
        self.resize(720, 640)
        self.refresh()

    # ----- 檔案 -----
    def files(self):
        return [self.file_list.item(i).data(Qt.UserRole) for i in range(self.file_list.count())]

    def add_files(self, paths):
        """加進清單（已經在的不重複加、空的略過）。回傳加了幾個。"""
        have = set(self.files())
        added = 0
        for path in paths or []:
            if not path:
                continue
            path = os.path.abspath(path)
            if path in have:
                continue
            item = self._file_item(path)
            self.file_list.addItem(item)
            have.add(path)
            added += 1
        self.refresh()
        return added

    def _file_item(self, path):
        item = QListWidgetItem(f"{os.path.basename(path)}　（{os.path.dirname(path)}）")
        item.setData(Qt.UserRole, path)
        item.setToolTip(path)
        return item

    def remove_selected(self):
        for item in self.file_list.selectedItems():
            self.file_list.takeItem(self.file_list.row(item))
        self.refresh()

    def clear_files(self):
        self.file_list.clear()
        self.refresh()

    # ----- 設定與說明 -----
    def mode(self):
        return next(value for value, button in self.mode_buttons.items() if button.isChecked())

    def run_config(self):
        """這次要用的設定：這次開啟的設定（含④的輸出設定），語言換成這裡選的。"""
        config = dict(self.config_data)
        config["transcription"] = dict(config.get("transcription") or {}, language=self.language_box.currentData())
        config["automation"] = dict(config.get("automation") or {})
        return config

    def missing_transcripts(self):
        """文字稿對齊時，旁邊沒有同名 .txt 的那幾支。"""
        return [p for p in self.files() if not pipeline.find_sidecar_transcript(p)]

    def send_text(self, plan):
        what = "、".join(plan["sends"])
        return (f"用 OpenAI 轉寫：會把這 {len(self.files())} 支的{what}逐支送到 OpenAI，OpenAI 照用量收費。"
                "檔名、字幕與其他檔案都不會送。")

    def refresh(self):
        """照檔案、做法與設定重寫說明，決定哪些鈕能按。"""
        config = self.run_config()
        plan = pipeline.generation_plan(config, self.mode())
        busy = self.worker.busy
        lines = []
        if plan["api"]:
            lines.append(self.send_text(plan))
            if not plan["has_key"]:
                lines.append(NO_KEY)
        else:
            lines.append(f"在這台電腦上用 Whisper（模型 {plan['model']}）辨識，聲音不會送出去。")
        lines.append("每一支會輸出：" + pipeline.describe_output_plan(config))
        if self.mode() == "align" and self.files():
            missing = self.missing_transcripts()
            if missing:
                lines.append("這幾支旁邊沒有同名的 .txt 講稿：" + "、".join(os.path.basename(p) for p in missing))
        lines.append(SETTINGS_NOTE)
        self.notice.setText("\n".join(lines))

        for widget in (self.add_btn, self.remove_btn, self.clear_btn, self.language_box, *self.mode_buttons.values()):
            widget.setEnabled(not busy)
        self.add_current_btn.setEnabled(not busy and bool(self.player.media_path))
        self.remove_btn.setEnabled(not busy and bool(self.file_list.selectedItems()))
        self.clear_btn.setEnabled(not busy and self.file_list.count() > 0)
        self.start_btn.setEnabled(not busy and self.file_list.count() > 0)
        self.stop_btn.setEnabled(busy and not self.worker.stopping)
        self.open_btn.setEnabled(not busy and self.selected_result() is not None)
        self.progress_bar.setVisible(busy)

    # ----- 問使用者（測試換掉這幾個） -----
    def _ask_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "加入要批次處理的檔案", "", MEDIA_FILTER)
        return paths

    def _ask_send(self, text):
        return QMessageBox.question(self, "會送到 OpenAI", text + "\n\n要開始嗎？") == QMessageBox.Yes

    def ask_close_while_running(self):
        return QMessageBox.question(self, "批次還在跑", self.close_question()) == QMessageBox.Yes

    # ----- 跑 -----
    def running(self):
        return self.worker.busy

    def _refuse(self, text):
        self.status_label.setText(text)
        return False

    def start(self):
        """開始批次（背景跑）。回傳有沒有開始。"""
        if self.worker.busy:
            return False
        paths = self.files()
        if not paths:
            return self._refuse(NO_FILES)
        missing = [p for p in paths if not os.path.isfile(p)]
        if missing:
            return self._refuse("找不到這幾個檔案：" + "、".join(missing))
        config = self.run_config()
        mode = self.mode()
        automation = config["automation"]
        if not pipeline.enabled_export_formats(automation) and not automation.get("burn_video"):
            return self._refuse(pipeline.describe_output_plan(config))
        if automation.get("burn_video") and not ffmpeg_available():
            return self._refuse(NO_FFMPEG)
        if mode == "align":
            lacking = self.missing_transcripts()
            if lacking:
                return self._refuse("文字稿對齊要每一支旁邊都有同名的 .txt 講稿，這幾支沒有："
                                    + "、".join(os.path.basename(p) for p in lacking))
        plan = pipeline.generation_plan(config, mode)
        if plan["api"]:
            if not plan["has_key"]:
                return self._refuse(NO_KEY)
            if not self._ask_send(self.send_text(plan)):
                return self._refuse(DECLINED)
        # 記住這次選的語言——只記在這次開啟的設定裡，不寫回 config.json
        self.config_data["transcription"] = dict(config["transcription"])
        self.results = []
        self.result_tree.clear()
        self.progress_bar.setValue(0)
        self.status_label.setText(f"開始批次（{len(paths)} 個檔案）…")
        self.worker.start(paths, config, mode)
        self.refresh()
        return True

    def stop(self):
        """停止：做完正在跑的這一支就不再開始下一支。"""
        if self.worker.busy and not self.worker.stopping:
            self.worker.stop()
            self.status_label.setText("會在這一支做完之後停（辨識與燒錄沒辦法從中間打斷），沒處理的會列出來。")
            self.refresh()

    def _on_progress(self, ratio, message):
        if ratio >= 0:
            self.progress_bar.setValue(int(max(0.0, min(ratio, 1.0)) * 1000))
        if message and not self.worker.stopping:
            self.status_label.setText(message)

    def _on_failed(self, exc):
        self.worker.busy = False
        err = describe_exception(exc)
        detail = f"（{err.details}）" if err.details and err.details != str(err) else ""
        self.status_label.setText(f"批次失敗：{err}{detail}")
        self.refresh()

    def _on_finished(self, results):
        self.worker.busy = False
        self.results = list(results)
        self.result_tree.clear()
        for index, result in enumerate(self.results):
            name = os.path.basename(result["path"])
            if result["ok"]:
                text = "✔ 成功"
            elif result.get("skipped"):
                text = "— 沒有處理（按了停止）"
            else:
                text = f"✘ {result['error']}"
            item = QTreeWidgetItem([name, text])
            item.setData(0, Qt.UserRole, index)
            item.setToolTip(0, result["path"])
            item.setToolTip(1, text)
            for path in outputs_of(result):
                child = QTreeWidgetItem([f"→ {os.path.basename(path)}", os.path.dirname(path)])
                child.setData(0, Qt.UserRole, index)
                child.setToolTip(0, path)
                item.addChild(child)
            self.result_tree.addTopLevelItem(item)
            item.setExpanded(True)
        self.progress_bar.setValue(1000)
        tip = "選一支成功的按〔在②開啟這支〕接著校對。" if any(r["ok"] for r in self.results) else ""
        self.status_label.setText(summary_text(self.results) + tip)
        self.refresh()

    # ----- 在②開啟 -----
    def selected_result(self):
        """結果清單選的那一支（要成功的才算）；沒選回傳 None。"""
        items = self.result_tree.selectedItems()
        if not items:
            return None
        index = items[0].data(0, Qt.UserRole)
        if index is None or not (0 <= index < len(self.results)) or not self.results[index]["ok"]:
            return None
        return self.results[index]

    def open_selected(self):
        """把選的那一支開在②：影片＋它剛匯出的 .srt（沒匯出 .srt 就用生成的字幕，算還沒存）。"""
        result = self.selected_result()
        if result is None or self.worker.busy:
            return False
        if not os.path.exists(result["path"]):
            return self._refuse(f"找不到這支影片：{result['path']}")
        if not self.player._maybe_drop_project() or not self.player.maybe_discard():
            return self._refuse("沒有開：②目前的專案或字幕還有沒存的修改。")
        self.player.open_video(result["path"])
        srt = next((p for p in result["result"]["exports"] if p.lower().endswith(".srt") and os.path.exists(p)), "")
        if srt:
            self.player.load_subtitles(srt)
        else:
            self.player.set_generated_cues([dict(c) for c in result["result"]["cues"]])
        self.status_label.setText(f"已在②開啟：{os.path.basename(result['path'])}"
                                  + (f"（字幕：{os.path.basename(srt)}）" if srt else "（字幕還沒存成檔）"))
        return True

    # ----- 關閉 -----
    def close_question(self):
        return ("批次還在跑。\n\n現在關掉的話，後面還沒開始的不會做；正在處理的這一支可能不完整"
                "（燒錄到一半的影片請不要拿來用，要的話重開之後再跑一次）。還是要關嗎？")

    def closeEvent(self, event):  # noqa: N802
        if self.worker.busy:
            if not self.ask_close_while_running():
                event.ignore()
                return
            self.stop()
        super().closeEvent(event)
