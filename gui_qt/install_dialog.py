# -*- coding: utf-8 -*-
"""
一鍵安裝 ffmpeg、文字辨識（3.0 第 11 項第二十九階段）：一般版 `gui/ffmpeg_dialog.py`、`gui/tesseract_dialog.py`
搬過來。

下載與安裝本身原封沿用核心（`subtitle/ffmpeg_setup.install_ffmpeg`、`subtitle/tesseract_setup.install_selected`）：
裝到程式自己的資料夾，不需要管理員權限、不改系統設定，裝完對這個行程立即生效（不用重開），兩版共用同一份。

**會連到外面的**：只有下載——ffmpeg 從 GitHub（BtbN/FFmpeg-Builds）下載壓縮檔；文字辨識引擎先問 GitHub 的發行頁
（UB-Mannheim/tesseract）要下載連結再下載安裝檔，語言檔從 GitHub（tesseract-ocr/tessdata_fast）下載。不會送出
任何影片、字幕、畫面或設定。按〔開始安裝〕之前畫面上就寫著。

視窗不擋住主視窗；下載在背景跑，安裝中關視窗先問（下載不會因為關視窗而停，跟一般版一樣）。
"""
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton,
    QVBoxLayout,
)

from subtitle import ffmpeg_setup, ocrengine
from subtitle import tesseract_setup as ts
from subtitle.errors import describe_exception

FFMPEG_TITLE = "自動安裝 ffmpeg"
FFMPEG_INTRO = ("將下載 ffmpeg（約 80~100 MB，只需一次）並安裝到程式自己的資料夾——不需要管理員權限、不會改動"
                "系統設定，安裝完成後立即可用（兩版共用）。")
FFMPEG_SENDS = "會連到外面的只有下載：從 GitHub 下載 ffmpeg 壓縮檔。不會送出任何影片、字幕或設定。"
FFMPEG_HINT = "按「開始安裝」後請保持網路連線。"
OCR_TITLE = "安裝文字辨識（OCR）"
OCR_INTRO = ("螢幕翻譯要用到文字辨識。安裝到程式自己的資料夾——不需要管理員權限、不會改動系統設定，裝完立即可用"
             "（兩版共用）。辨識在這台電腦上跑，畫面不會被傳出去。")
OCR_SENDS = ("會連到外面的只有下載：引擎先問 GitHub 的發行頁要下載連結再下載安裝檔，語言檔從 GitHub 下載。"
             "不會送出任何畫面、文字或設定。")
OCR_ENGINE_NOTE = "自動安裝引擎目前只支援 Windows；其他系統請用套件管理員安裝 tesseract（例如 apt install tesseract-ocr）。"
NOTHING_CHOSEN = "請至少勾選一項要安裝的東西。"
FAILED = "安裝失敗，可重試或改手動安裝："
RETRY = "重試安裝"
DEFAULT_LANGS = ("eng", "jpn", "chi_tra")  # 跟一般版一樣：介面是中文的，來源語言最常見的是英文與日文
LANG_COLUMNS = 3


def failure_text(exc):
    """安裝失敗時狀態列那一句：核心的 SetupError 本身就講得出下一步，原樣用；其他的翻成白話（原因＋解法）。"""
    if isinstance(exc, ts.SetupError):
        return f"{FAILED}{exc}"
    err = describe_exception(exc)
    parts = [str(err)]
    if err.cause:
        parts.append(err.cause)
    if err.solution:
        parts.append(err.solution)
    if err.kind == "generic" and err.details:
        parts.append(f"技術細節：{err.details}")
    return FAILED + "。".join(p.rstrip("。") for p in parts) + "。"


class InstallWorker(QObject):
    """背景執行緒跑一個安裝函式 `job(progress_cb)`。busy 由畫面那邊（主執行緒）收到結果時才放下。"""

    progress = Signal(float, str)
    finished = Signal(object)
    failed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False

    def start(self, job):
        self.busy = True
        threading.Thread(target=self._run, args=(job,), daemon=True).start()

    def _run(self, job):
        try:
            result = job(lambda r, m: self.progress.emit(float(r if r is not None else -1.0), str(m or "")))
        except Exception as exc:  # noqa: BLE001 —— 背景執行緒的例外一律送回畫面上講
            self.failed.emit(exc)
            return
        self.finished.emit(result)


class _InstallDialog(QDialog):
    """兩個安裝視窗共用的骨架：說明、會連到哪、狀態、進度條、〔開始安裝〕〔關閉〕。裝好發 `installed`。"""

    installed = Signal(object)

    def __init__(self, title, intro, sends, hint, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(False)
        self.last_result = None
        self.layout_ = QVBoxLayout(self)
        intro_label = QLabel(intro)
        intro_label.setWordWrap(True)
        self.layout_.addWidget(intro_label)
        self.sends_label = QLabel(sends)
        self.sends_label.setWordWrap(True)
        self.layout_.addWidget(self.sends_label)
        self.body = QVBoxLayout()
        self.layout_.addLayout(self.body)
        self.status_label = QLabel(hint)
        self.status_label.setWordWrap(True)
        self.layout_.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(False)
        self.layout_.addWidget(self.progress_bar)
        row = QHBoxLayout()
        self.start_btn = QPushButton("開始安裝")
        self.start_btn.clicked.connect(lambda _c=False: self.start())
        self.close_btn = QPushButton("關閉")
        self.close_btn.clicked.connect(self.close)
        row.addWidget(self.start_btn)
        row.addStretch(1)
        row.addWidget(self.close_btn)
        self.layout_.addLayout(row)
        self.worker = InstallWorker(self)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.resize(500, 0)

    # 子類別提供
    def _job(self):
        raise NotImplementedError

    def _done_text(self, result):
        raise NotImplementedError

    def _set_inputs_enabled(self, enabled):
        pass

    def installing(self):
        return self.worker.busy

    def start(self):
        """開始安裝。回傳有沒有開始。"""
        if self.worker.busy:
            return False
        job = self._job()
        if job is None:
            return False
        self.worker.start(job)
        self.progress_bar.setValue(0)
        self.start_btn.setEnabled(False)
        self.start_btn.setText("安裝中…")
        self._set_inputs_enabled(False)
        return True

    def _on_progress(self, ratio, message):
        if ratio >= 0:
            self.progress_bar.setValue(int(max(0.0, min(ratio, 1.0)) * 1000))
        if message:
            self.status_label.setText(message)

    def _on_failed(self, exc):
        self.worker.busy = False
        self.status_label.setText(failure_text(exc))
        self.start_btn.setEnabled(True)
        self.start_btn.setText(RETRY)
        self._set_inputs_enabled(True)

    def _on_finished(self, result):
        self.worker.busy = False
        self.last_result = result
        self.progress_bar.setValue(1000)
        text = self._done_text(result)
        self.status_label.setText(text)
        self.start_btn.setText("已安裝")
        self.installed.emit(result)
        if self.isVisible():
            self._show_done(text)
            self.close()

    def _show_done(self, text):  # 測試換掉
        QMessageBox.information(self, "安裝完成", text)

    def _ask_close_while_installing(self):  # 測試換掉
        return QMessageBox.question(self, "安裝進行中", "安裝仍在進行，確定要關閉嗎？\n\n"
                                    "（下載會在背景繼續，裝好就能用；要的話之後再開這個視窗看）") == QMessageBox.Yes

    def closeEvent(self, event):  # noqa: N802
        if self.worker.busy and not self._ask_close_while_installing():
            event.ignore()
            return
        super().closeEvent(event)


class FfmpegInstallDialog(_InstallDialog):
    """自動安裝 ffmpeg。"""

    def __init__(self, parent=None):
        super().__init__(FFMPEG_TITLE, FFMPEG_INTRO, FFMPEG_SENDS, FFMPEG_HINT, parent)

    def _job(self):
        return lambda progress: ffmpeg_setup.install_ffmpeg(progress_cb=progress)

    def _done_text(self, result):
        return f"ffmpeg 已安裝到：{result}\n所有影音功能現在即可使用，無需重新啟動。"


class TesseractInstallDialog(_InstallDialog):
    """安裝文字辨識引擎與語言檔：看得到自己缺的是哪一半，也能只補語言檔。"""

    def __init__(self, parent=None, langs=None):
        super().__init__(OCR_TITLE, OCR_INTRO, OCR_SENDS, ts.describe_state(), parent)
        have = ocrengine.tesseract_available()
        self.engine_box = QCheckBox("辨識引擎（已安裝，可略過）" if have else "辨識引擎（約 50~60 MB，只需一次）")
        self.engine_box.setChecked(not have)
        self.body.addWidget(self.engine_box)
        self.engine_note = QLabel(OCR_ENGINE_NOTE)
        self.engine_note.setWordWrap(True)
        self.body.addWidget(self.engine_note)
        box = QGroupBox("語言檔（每個約 2~4 MB）")
        grid = QGridLayout(box)
        installed = ts.installed_languages()
        wanted = set(langs or DEFAULT_LANGS)
        self.lang_boxes = {}
        for index, (code, label) in enumerate(ts.LANGUAGE_LABELS):
            cb = QCheckBox(f"{label}（已安裝）" if code in installed else label)
            cb.setChecked(code in wanted and code not in installed)
            grid.addWidget(cb, index // LANG_COLUMNS, index % LANG_COLUMNS)
            self.lang_boxes[code] = cb
        self.body.addWidget(box)

    def selected_languages(self):
        return [code for code, cb in self.lang_boxes.items() if cb.isChecked()]

    def _set_inputs_enabled(self, enabled):
        self.engine_box.setEnabled(enabled)
        for cb in self.lang_boxes.values():
            cb.setEnabled(enabled)

    def _job(self):
        want_engine, langs = self.engine_box.isChecked(), self.selected_languages()
        if not want_engine and not langs:
            self.status_label.setText(NOTHING_CHOSEN)
            return None
        return lambda progress: ts.install_selected(want_engine, langs, progress_cb=progress)

    def _done_text(self, result):
        return "文字辨識已就緒：\n" + "\n".join(str(p) for p in result or []) + "\n不需要重新啟動，現在就可以用。"
