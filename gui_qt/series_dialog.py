# -*- coding: utf-8 -*-
"""
系列一致性比對視窗（3.0 第 11 項第二十七階段）：一般版 `gui/series_dialog.py` 搬過來。

批次製作時每一支單獨看都沒問題，彼此之間卻可能不一致——連看同一系列時某一集突然要調大音量、某一集畫面
明顯偏暗、某一集解析度掉下來。以整批的中位數為基準，找出偏離整批的那幾支。核心同一個
`subtitle/seriescheck.py`（量測、比對、報告文字都一樣），同一份設定（config 的 seriescheck）、同樣的範圍；
只記在這次開啟的設定裡（Qt 預覽版不寫 config.json）。

跟③健檢的差別：健檢拿固定門檻看一支影片合不合格；這裡比的是多支影片彼此之間一不一致，所以另開一個視窗、
不併進健檢的分級報告（一般版同樣的理由）。

比一般版多的：「加入②開著的影片」一鍵把目前的影片放進清單；清單會記著（關掉視窗再開還在，跟一般版放在
健檢中心對象區的那份清單一樣只記在畫面上）。比對在背景跑，關掉視窗不會中斷，比完再打開就看得到報告。

全在本機用 ffmpeg 量測，不改原始檔、什麼都不送出去。
"""
import os
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDoubleSpinBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout,
)

from subtitle import seriescheck as sc
from subtitle.burner import ffmpeg_available
from subtitle.errors import describe_exception

TITLE = "系列一致性：比對同一批影片彼此之間是否一致"
MEDIA_FILTER = "影片與音訊檔 (*.mp4 *.mkv *.mov *.avi *.flv *.mp3 *.wav *.m4a *.aac);;所有檔案 (*)"  # 跟一般版一樣
HINT = "加入同一系列的多支影片後按「開始比對」，掃描不會改動原始檔案。"
TOLERANCE_NOTE = ("以整批的中位數為基準，找出偏離整批的那幾支——整批一致但整批都偏暗時不會標記"
                  "（那是風格，不是失誤）。")
NEED_TWO = ("系列一致性檢查需要至少 2 支影片才有比較基準。若想檢查單一支影片本身合不合格，"
            "請改用「③健檢中心」的「開始健檢」。")
NO_FFMPEG = "找不到 ffmpeg，系列一致性檢查需要它才能量測：請先在一般版按「自動安裝 ffmpeg」（兩版共用）。"
NO_PLAYER_MEDIA = "②還沒開影片（或檔案找不到了）。"
RUNNING = "比對中…"
SAVE_NAME = "系列一致性檢查.txt"  # 跟一般版的預設檔名一樣
# (設定鍵, 標籤, 單位, 下限, 上限, 一格, 小數位)——範圍、一格跟一般版的 Spinbox 一樣
TOLERANCES = (
    ("loudness_tolerance", "響度差異：", "LU", 0.5, 8.0, 0.5, 1),
    ("luma_tolerance", "亮度差異：", "（0～255）", 10.0, 80.0, 5.0, 0),
    ("cast_tolerance", "色調差異：", "", 3.0, 30.0, 1.0, 0),
)


def issue_count(result):
    """報告裡在整批之間不一致的項目數（一般版同一個算法：不是「通過」的都算）。"""
    return len([f for f in (result or {}).get("findings", []) if f["level"] != sc.LEVEL_GOOD])


def summary_text(result):
    count = issue_count(result)
    if count:
        return f"比對完成：{count} 項在整批之間不一致，詳見報告。"
    return "比對完成：整批各項指標彼此一致。"


class SeriesWorker(QObject):
    """背景執行緒跑 `seriescheck.analyze_series`。busy 由畫面那邊（主執行緒）收到結果時才放下。"""

    progress = Signal(float, str)
    finished = Signal(object)
    failed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False

    def start(self, paths, config):
        self.busy = True
        threading.Thread(target=self._run, args=(list(paths), dict(config)), daemon=True).start()

    def _run(self, paths, config):
        try:
            result = sc.analyze_series(paths, config,
                                       progress_cb=lambda r, m: self.progress.emit(float(r), str(m)))
        except Exception as exc:  # noqa: BLE001 —— 背景執行緒的例外一律送回畫面上講
            self.failed.emit(exc)
            return
        self.finished.emit(result)


class SeriesDialog(QDialog):
    """系列一致性比對。`player` 是②的播放器（「加入②開著的影片」用），設定跟它同一份（這次開啟的設定）。"""

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.player = player
        self.config = player._config
        self.last_result = None
        self.setWindowTitle(TITLE)
        self.setModal(False)
        settings = sc.resolve_seriescheck_settings(self.config)

        layout = QVBoxLayout(self)
        self.ffmpeg_label = QLabel(NO_FFMPEG)
        self.ffmpeg_label.setWordWrap(True)
        self.ffmpeg_label.setStyleSheet("color: #b35c00;")
        self.ffmpeg_label.setVisible(not ffmpeg_available())
        layout.addWidget(self.ffmpeg_label)

        files = QGroupBox(f"要比對的影片（同一系列，至少 {sc.MIN_FILES} 支）")
        files_layout = QVBoxLayout(files)
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list.setMinimumHeight(90)
        self.file_list.setMaximumHeight(130)  # 多出來的高度給報告
        files_layout.addWidget(self.file_list)
        row = QHBoxLayout()
        self.add_btn = QPushButton("加入影片…")
        self.add_btn.clicked.connect(lambda _c=False: self.add_files())
        self.add_current_btn = QPushButton("加入②開著的影片")
        self.add_current_btn.clicked.connect(lambda _c=False: self.add_current())
        self.remove_btn = QPushButton("移除選取")
        self.remove_btn.clicked.connect(self.remove_selected)
        self.clear_btn = QPushButton("全部清除")
        self.clear_btn.clicked.connect(self.clear_files)
        for btn in (self.add_btn, self.add_current_btn, self.remove_btn, self.clear_btn):
            row.addWidget(btn)
        row.addStretch(1)
        files_layout.addLayout(row)
        layout.addWidget(files)

        box = QGroupBox("容許差異（這次開啟會記住）")
        box_layout = QVBoxLayout(box)
        row = QHBoxLayout()
        self.spins = {}
        for key, label, unit, low, high, step, decimals in TOLERANCES:
            row.addWidget(QLabel(label))
            spin = QDoubleSpinBox()
            spin.setRange(low, high)
            spin.setSingleStep(step)
            spin.setDecimals(decimals)
            spin.setValue(settings[key])
            row.addWidget(spin)
            if unit:
                row.addWidget(QLabel(unit))
            row.addSpacing(10)
            self.spins[key] = spin
        row.addStretch(1)
        box_layout.addLayout(row)
        note = QLabel(TOLERANCE_NOTE)
        note.setWordWrap(True)
        box_layout.addWidget(note)
        layout.addWidget(box)

        self.status_label = QLabel(HINT)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        report_box = QGroupBox("比對報告")
        report_layout = QVBoxLayout(report_box)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setMinimumHeight(180)
        report_layout.addWidget(self.report)
        layout.addWidget(report_box, 1)

        buttons = QHBoxLayout()
        self.run_btn = QPushButton("開始比對")
        self.run_btn.clicked.connect(lambda _c=False: self.start())
        self.copy_btn = QPushButton("複製報告")
        self.copy_btn.clicked.connect(self.copy_report)
        self.save_btn = QPushButton("另存報告…")
        self.save_btn.clicked.connect(lambda _c=False: self.save_report())
        self.close_btn = QPushButton("關閉")
        self.close_btn.clicked.connect(self.close)
        buttons.addWidget(self.run_btn)
        buttons.addWidget(self.copy_btn)
        buttons.addWidget(self.save_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

        self.worker = SeriesWorker(self)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.file_list.itemSelectionChanged.connect(self._update_buttons)
        self._update_buttons()
        self.resize(720, 640)

    def showEvent(self, event):  # noqa: N802 —— 打開時更新（②換影片沒有訊號）
        super().showEvent(event)
        self._update_buttons()

    # ----- 清單 -----
    def paths(self):
        """清單上的檔案（完整路徑，照加入的順序）。清單只顯示檔名，完整路徑放在提示裡。"""
        return [self.file_list.item(i).data(Qt.UserRole) for i in range(self.file_list.count())]

    def add_paths(self, paths):
        """加入檔案；同一支不重複加。回傳這次真的加進去的支數。"""
        have = set(self.paths())
        added = 0
        for path in paths or []:
            if path and path not in have:
                item = QListWidgetItem(os.path.basename(path))
                item.setData(Qt.UserRole, path)
                item.setToolTip(path)
                self.file_list.addItem(item)
                have.add(path)
                added += 1
        self._update_buttons()
        return added

    def _ask_media_paths(self):  # 測試換掉
        paths, _ = QFileDialog.getOpenFileNames(self, "選擇同系列的影片", "", MEDIA_FILTER)
        return paths

    def add_files(self):
        return self.add_paths(self._ask_media_paths())

    def _current_media(self):
        media = self.player.media_path
        return media if media and os.path.isfile(media) else ""

    def add_current(self):
        media = self._current_media()
        if not media:
            self.status_label.setText(NO_PLAYER_MEDIA)
            return 0
        added = self.add_paths([media])
        self.status_label.setText(f"已加入：{os.path.basename(media)}" if added
                                  else f"{os.path.basename(media)} 已經在清單上了。")
        return added

    def remove_selected(self):
        for item in self.file_list.selectedItems():
            self.file_list.takeItem(self.file_list.row(item))
        self._update_buttons()

    def clear_files(self):
        self.file_list.clear()
        self._update_buttons()

    # ----- 設定 -----
    def settings(self):
        """畫面上的容許差異寫進這次開啟的設定（seriescheck），回傳核心整理過的版本。"""
        self.config["seriescheck"] = {key: spin.value() for key, spin in self.spins.items()}
        return sc.resolve_seriescheck_settings(self.config)

    # ----- 比對 -----
    def busy(self):
        return self.worker.busy

    def _update_buttons(self):
        busy = self.worker.busy
        has = self.file_list.count() > 0
        for widget in (self.add_btn, *self.spins.values()):
            widget.setEnabled(not busy)
        self.add_current_btn.setEnabled(not busy and bool(self._current_media()))
        self.remove_btn.setEnabled(not busy and bool(self.file_list.selectedItems()))
        self.clear_btn.setEnabled(not busy and has)
        self.run_btn.setEnabled(not busy)
        self.run_btn.setText(RUNNING if busy else "開始比對")
        has_report = self.last_result is not None and not busy
        self.copy_btn.setEnabled(has_report)
        self.save_btn.setEnabled(has_report)
        self.progress_bar.setVisible(busy)

    def start(self):
        """開始比對。回傳有沒有開始。"""
        if self.worker.busy:
            return False
        paths = self.paths()
        if len(paths) < sc.MIN_FILES:
            self.status_label.setText(NEED_TWO)
            return False
        if not ffmpeg_available():
            self.ffmpeg_label.setVisible(True)
            self.status_label.setText(NO_FFMPEG)
            return False
        self.settings()
        self.worker.start(paths, self.config)
        self.progress_bar.setValue(0)
        self.status_label.setText(f"正在比對 {len(paths)} 支影片…")
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
        self.status_label.setText(f"比對失敗：{err}{detail}")
        self._update_buttons()

    def _on_finished(self, result):
        self.worker.busy = False
        self.last_result = result
        self.report.setPlainText(sc.format_series_report(result))
        self.status_label.setText(summary_text(result))
        self._update_buttons()

    # ----- 報告 -----
    def report_text(self):
        return sc.format_series_report(self.last_result) if self.last_result is not None else ""

    def copy_report(self):
        text = self.report_text()
        if text:
            QGuiApplication.clipboard().setText(text)
            self.status_label.setText("報告已複製到剪貼簿。")

    def _ask_save_path(self):  # 測試換掉
        path, _ = QFileDialog.getSaveFileName(self, "儲存系列一致性報告", SAVE_NAME, "文字檔 (*.txt)")
        return path

    def save_report(self):
        """另存報告（UTF-8 純文字）。回傳存到哪（沒存就是空字串）。"""
        text = self.report_text()
        if not text:
            return ""
        path = self._ask_save_path()
        if not path:
            return ""
        if not os.path.splitext(path)[1]:
            path += ".txt"
        try:
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(text)
        except OSError as exc:
            self.status_label.setText(f"儲存報告失敗：{describe_exception(exc)}")
            return ""
        self.status_label.setText(f"報告已儲存：{os.path.basename(path)}")
        return path
