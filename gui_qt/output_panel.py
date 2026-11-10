# -*- coding: utf-8 -*-
"""
④輸出與發佈（3.0 第 11 項第十三階段：輸出設定、〔完成輸出〕、逐格式匯出）。

跟一般版的「輸出」框同一套：同一份設定（config 的 automation）、同一個函式
（`subtitle.pipeline.export_and_burn`）、同一句「這次會輸出什麼」（`describe_output_plan`）。
輸出的對象是②字幕頁開著的影片與字幕（按下去那一刻現拿：逐句校對改到一半的先套用）。

由上而下三段，順序就是決定的順序：

1. 這次會輸出什麼（設定一改立刻跟著變）＋〔完成輸出（依輸出設定）〕。不跳存檔視窗：檔名跟著影片
   （`影片.srt`、`影片_subtitled.mp4`），同名就加編號、不覆蓋；放在影片旁邊或指定的輸出資料夾。
2. 輸出設定：匯出格式（SRT／VTT／ASS／TXT）、燒錄硬字幕影片、燒錄時響度正規化與目標、輸出資料夾。
3. 只做單獨一件事：匯出一種格式，會另外問要存到哪裡（不必開影片，有字幕就能匯出）。

燒錄在背景用 ffmpeg 跑，輸出到一半不能停（一般版也不能），關視窗時先問。字幕燒在②開著的**原始影片**
上：剪點、素材軌、轉場、畫面調整不會算進去（那些用②的「照剪點輸出…」「輸出多軌…」），頁面上寫明。

設定只記在這次開啟的設定裡（Qt 預覽版不寫 config.json）。

「輸出」框下面是「成品加工：品牌套版」（第十四階段，`gui_qt/branding_box.py`）。燒錄完，套版的來源自動換成
剛燒好的那一支。一次只跑一件：燒錄與套版不同時跑。

還沒有的（頁面上寫明）：配樂助手、發佈資料。
"""
import os
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from subtitle import exporter, pipeline
from subtitle.audio import MAX_TARGET_LUFS, MIN_TARGET_LUFS, clamp_target
from subtitle.burner import ffmpeg_available
from subtitle.errors import describe_exception

FORMATS = tuple(ext.lstrip(".") for ext in pipeline.EXPORT_FORMATS)  # srt、vtt、ass、txt
PAGE_NOTE = ("把②字幕頁開著的字幕輸出成檔案，跟一般版的「輸出」同一套設定與做法。燒錄硬字幕是燒在②開著的"
             "原始影片上：剪點、素材軌、轉場、畫面調整不會算進去（那些請用②的「照剪點輸出…」「輸出多軌…」）。"
             "下面可以接著做品牌套版（片頭／片尾／浮水印）。配樂助手、發佈資料還在一般版（之後的階段搬過來）。")
FINISH_NOTE = "不會問存到哪裡：檔名跟著影片，同名就加編號、不覆蓋舊檔。"
SINGLE_NOTE = "這一列一次只匯出一種格式，會另外問你要存到哪裡；不看上面的勾選，也不必開影片。"
LUFS_NOTE = "LUFS（YouTube 標準 -14；音量偏小的素材建議勾選）"
NO_CUES = "②字幕頁還沒有字幕：請先在②生成字幕或載入字幕檔。"
NO_MEDIA = "②字幕頁還沒開影片（或檔案找不到了）：〔完成輸出〕的檔名與位置跟著影片走，請先開影片；只要字幕檔可以用下面的單獨匯出。"
NO_FFMPEG = "找不到 ffmpeg，燒錄硬字幕需要它：請先在一般版按「自動安裝 ffmpeg」（兩版共用），或取消勾選「燒錄硬字幕影片」。"
CLOSE_QUESTION = "硬字幕影片還在燒錄，現在關掉會留下不完整的檔案。\n\n要等它做完嗎？"
CLOSE_QUESTION_BRANDING = "套版影片還在輸出，現在關掉會留下不完整的檔案。\n\n要等它做完嗎？"
BRANDING_BUSY = "下面的品牌套版還在跑，等它做完再輸出。"
EXPORT_FILTERS = {"srt": "SRT 字幕 (*.srt)", "vtt": "WebVTT 字幕 (*.vtt)", "ass": "ASS 字幕 (*.ass)",
                  "txt": "純文字 (*.txt)"}


class OutputWorker(QObject):
    """背景執行緒跑 pipeline.export_and_burn。busy 由畫面那邊（主執行緒）放下。"""

    progress = Signal(float, str)
    finished = Signal(object)  # (exports, burned)
    failed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        self.burning = False  # 這次有沒有燒錄（關視窗時要不要問）

    def start(self, cues, media_path, config):
        self.busy = True
        self.burning = bool(config.get("automation", {}).get("burn_video"))
        threading.Thread(target=self._run, args=(cues, media_path, config), daemon=True).start()

    def _run(self, cues, media_path, config):
        try:
            result = pipeline.export_and_burn(
                cues, media_path, config, report=lambda m, r: self.progress.emit(float(r), str(m)))
        except Exception as exc:  # noqa: BLE001 —— 背景執行緒的例外一律送回畫面上講
            self.failed.emit(exc)
            return
        self.finished.emit(result)


class OutputPanel(QWidget):
    """④輸出與發佈頁：輸出設定 → 完成輸出；或單獨匯出一種格式。"""

    def __init__(self, player, before_output=None, parent=None):
        super().__init__(parent)
        self.player = player
        self.before_output = before_output  # 開始前先叫：逐句校對編輯框裡改到一半的先套用
        self.config = player._config        # 跟播放器同一份（這次開啟的設定）
        self.last_outputs = []              # 最近一次〔完成輸出〕產生的檔案
        automation = self.config.setdefault("automation", {})

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        note = QLabel(PAGE_NOTE)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.target_label = QLabel()
        self.target_label.setWordWrap(True)
        layout.addWidget(self.target_label)

        box = QGroupBox("輸出")
        inner = QVBoxLayout(box)
        # ① 這次會輸出什麼＋主動作
        self.plan_label = QLabel()
        self.plan_label.setWordWrap(True)
        font = self.plan_label.font()
        font.setBold(True)
        self.plan_label.setFont(font)
        inner.addWidget(self.plan_label)
        row = QHBoxLayout()
        self.finish_btn = QPushButton("完成輸出（依輸出設定）")
        self.finish_btn.clicked.connect(self.finish_output)
        row.addWidget(self.finish_btn)
        row.addWidget(QLabel(FINISH_NOTE), 1)
        inner.addLayout(row)

        # ② 輸出設定
        inner.addWidget(self._heading("輸出設定（這次開啟會記住）"))
        row = QHBoxLayout()
        row.addWidget(QLabel("匯出字幕檔："))
        self.format_boxes = {}
        for name in FORMATS:
            cb = QCheckBox(name.upper())
            cb.setChecked(bool(automation.get(f"export_{name}")))
            cb.toggled.connect(self._settings_changed)
            row.addWidget(cb)
            self.format_boxes[name] = cb
        row.addStretch(1)
        inner.addLayout(row)
        row = QHBoxLayout()
        self.burn_box = QCheckBox("燒錄硬字幕影片")
        self.burn_box.setChecked(bool(automation.get("burn_video")))
        self.burn_box.toggled.connect(self._settings_changed)
        self.loudnorm_box = QCheckBox("燒錄時響度正規化")
        self.loudnorm_box.setChecked(bool(automation.get("loudnorm")))
        self.loudnorm_box.toggled.connect(self._settings_changed)
        self.loudnorm_spin = QDoubleSpinBox()
        self.loudnorm_spin.setRange(MIN_TARGET_LUFS, MAX_TARGET_LUFS)
        self.loudnorm_spin.setSingleStep(0.5)
        self.loudnorm_spin.setDecimals(1)
        self.loudnorm_spin.setValue(clamp_target(automation.get("loudnorm_target")))
        self.loudnorm_spin.valueChanged.connect(self._settings_changed)
        for widget in (self.burn_box, self.loudnorm_box, QLabel("目標"), self.loudnorm_spin, QLabel(LUFS_NOTE)):
            row.addWidget(widget)
        row.addStretch(1)
        inner.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("輸出資料夾："))
        self.dir_edit = QLineEdit(str(automation.get("output_dir") or ""))
        self.dir_edit.setPlaceholderText("留空＝放在影片旁邊")
        self.dir_edit.textChanged.connect(self._settings_changed)
        self.dir_btn = QPushButton("選擇…")
        self.dir_btn.clicked.connect(self.choose_dir)
        row.addWidget(self.dir_edit, 1)
        row.addWidget(self.dir_btn)
        inner.addLayout(row)

        # ③ 只做單獨一件事
        inner.addWidget(self._heading("只做單獨一件事"))
        single = QLabel(SINGLE_NOTE)
        single.setWordWrap(True)
        inner.addWidget(single)
        row = QHBoxLayout()
        self.export_btns = {}
        for name in FORMATS:
            btn = QPushButton(f"匯出 {name.upper()}…")
            btn.clicked.connect(lambda _checked=False, n=name: self.export_single(n))
            row.addWidget(btn)
            self.export_btns[name] = btn
        row.addStretch(1)
        inner.addLayout(row)
        layout.addWidget(box)
        from gui_qt.branding_box import BrandingBox
        self.branding = BrandingBox(player, other_busy=self.busy)
        layout.addWidget(self.branding)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.result_box = QPlainTextEdit()
        self.result_box.setReadOnly(True)
        self.result_box.setPlaceholderText("（輸出的檔案會列在這裡）")
        layout.addWidget(self.result_box, 1)

        self.worker = OutputWorker(self)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self._pending_media = ""
        player.cuesChanged.connect(self.refresh)
        self.refresh()

    @staticmethod
    def _heading(text):
        label = QLabel(text)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        label.setContentsMargins(0, 8, 0, 0)
        return label

    # ----- 設定 -----
    def collect_settings(self):
        """畫面上的勾選寫進這次開啟的設定（automation，跟一般版同一個區塊）。"""
        automation = self.config.setdefault("automation", {})
        for name, cb in self.format_boxes.items():
            automation[f"export_{name}"] = cb.isChecked()
        automation["burn_video"] = self.burn_box.isChecked()
        automation["loudnorm"] = self.loudnorm_box.isChecked()
        automation["loudnorm_target"] = clamp_target(self.loudnorm_spin.value())
        automation["output_dir"] = self.dir_edit.text().strip()
        return automation

    def _settings_changed(self, *_args):
        self.collect_settings()
        self.refresh()

    def choose_dir(self):
        start = self.dir_edit.text().strip() or os.path.dirname(self.player.media_path or "")
        path = QFileDialog.getExistingDirectory(self, "選擇輸出資料夾", start)
        if path:
            self.dir_edit.setText(path)

    # ----- 畫面 -----
    def refresh(self):
        """上方對象、那句「這次會輸出什麼」、哪些鈕可以按（切到這頁、字幕或設定改了都會更新）。"""
        media, count = self.player.media_path, len(self.player.cues)
        parts = [f"影片：{os.path.basename(media)}" if media else "影片：還沒開",
                 f"字幕：{count} 句" if count else "字幕：沒有"]
        self.target_label.setText("輸出對象（②字幕頁開著的）：" + "　".join(parts))
        self.plan_label.setText("這次會輸出：" + pipeline.describe_output_plan(self.config, media or None))
        busy = self.busy()
        burn = self.burn_box.isChecked()
        self.loudnorm_box.setEnabled(burn and not busy)
        self.loudnorm_spin.setEnabled(burn and self.loudnorm_box.isChecked() and not busy)
        for widget in (*self.format_boxes.values(), self.burn_box, self.dir_edit, self.dir_btn):
            widget.setEnabled(not busy)
        self.finish_btn.setEnabled(not busy)
        for btn in self.export_btns.values():
            btn.setEnabled(not busy and count > 0)

    def showEvent(self, event):  # noqa: N802 —— 切到這一頁時更新（換影片沒有訊號）
        super().showEvent(event)
        self.refresh()

    def busy(self):
        return self.worker.busy

    def burning(self):
        """有沒有還在輸出的影片（燒錄或套版）：關視窗前要問。"""
        return (self.worker.busy and self.worker.burning) or self.branding.busy()

    # ----- 完成輸出 -----
    def finish_output(self):
        if self.busy():
            return False
        if self.branding.busy():
            return self._refuse(BRANDING_BUSY)
        if callable(self.before_output):
            self.before_output()
        self.collect_settings()
        self.refresh()
        cues = [dict(c) for c in self.player.cues]
        media = self.player.media_path
        automation = self.config["automation"]
        if not cues:
            return self._refuse(NO_CUES)
        if not media or not os.path.exists(media):
            return self._refuse(NO_MEDIA)
        if not pipeline.enabled_export_formats(automation) and not automation.get("burn_video"):
            return self._refuse(pipeline.describe_output_plan(self.config))
        if automation.get("burn_video") and not ffmpeg_available():
            return self._refuse(NO_FFMPEG)
        # 設定給背景一份副本：跑到一半畫面上再改勾選，不影響這一次
        snapshot = dict(self.config, automation=dict(automation),
                        subtitle_style=dict(self.config.get("subtitle_style") or {}))
        self.worker.start(cues, media, snapshot)
        self._pending_media = media
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.finish_btn.setText("輸出中…")
        self.status_label.setText("輸出中…" + ("（燒錄到一半不能停）" if automation.get("burn_video") else ""))
        self.refresh()
        return True

    def _refuse(self, text):
        self.status_label.setText(text)
        return False

    def _on_progress(self, ratio, message):
        self.progress_bar.setValue(int(max(0.0, min(ratio, 1.0)) * 1000))
        if message:
            self.status_label.setText(f"輸出中：{message}")

    def _done(self):
        self.worker.busy = False
        self.progress_bar.setVisible(False)
        self.finish_btn.setText("完成輸出（依輸出設定）")
        self.refresh()

    def _on_failed(self, exc):
        self._done()
        err = describe_exception(exc)
        self.status_label.setText(f"輸出失敗：{err}")
        # 原因、怎麼解、原始訊息寫在下面的框（狀態列只放一句）
        self.result_box.setPlainText("\n\n".join(
            part for part in (err.cause, err.solution, f"技術細節：{err.details}" if err.details else "") if part))

    def _on_finished(self, result):
        exports, burned = result
        outputs = list(exports) + ([burned] if burned else [])
        self.last_outputs = outputs
        self.result_box.setPlainText("\n".join(f"→ {path}" for path in outputs))
        self._done()
        text = f"完成輸出：{os.path.basename(self._pending_media)} 共產生 {len(outputs)} 個檔案。"
        if burned:
            self.branding.set_source(burned)  # 建議順序：燒錄→套版
            text += "下面品牌套版的來源已換成剛燒好的這一支。"
        self.status_label.setText(text)

    # ----- 只匯出一種格式 -----
    def default_export_name(self, name):
        """預設檔名跟著影片；沒開影片就跟著載入的字幕檔；都沒有叫 subtitle。"""
        source = self.player.media_path or getattr(self.player, "_subtitle_path", "") or "subtitle"
        return os.path.splitext(source)[0] + f".{name}"

    def export_single(self, name, path=None):
        """匯出一種格式（沒給路徑就開存檔視窗）。回傳寫出的路徑；取消或失敗回傳空字串。"""
        if self.busy():
            return ""
        if callable(self.before_output):
            self.before_output()
        cues = [dict(c) for c in self.player.cues]
        if not cues:
            self.status_label.setText(NO_CUES)
            return ""
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, f"儲存 {name.upper()} 字幕檔",
                                                  self.default_export_name(name), EXPORT_FILTERS[name])
        if not path:
            return ""
        if not os.path.splitext(path)[1]:
            path += f".{name}"  # 存檔視窗沒補副檔名時補上（格式看副檔名）
        try:
            exporter.export(cues, path, style=self.config.get("subtitle_style"))
        except (OSError, ValueError) as exc:
            self.status_label.setText(f"匯出失敗：無法寫入檔案（{exc}）")
            return ""
        self.status_label.setText(f"已匯出：{path}")
        return path

    # ----- 關視窗 -----
    def ask_close_while_burning(self):
        """燒錄中關視窗：先問。回傳 True＝照樣關。"""
        question = CLOSE_QUESTION if self.worker.busy and self.worker.burning else CLOSE_QUESTION_BRANDING
        answer = QMessageBox.question(self, "還在輸出", question, QMessageBox.Yes | QMessageBox.No,
                                      QMessageBox.Yes)
        return answer == QMessageBox.No
