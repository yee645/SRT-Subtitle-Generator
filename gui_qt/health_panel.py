# -*- coding: utf-8 -*-
"""
③健檢中心（3.0 第 11 項第八階段：先搬影片與字幕的檢查；第九階段：字幕類的「修復此項」）。

檢查與報告跟一般版同一份（`subtitle/healthcheck.py`，原 `gui/health_aggregator.py`）：同樣的項目、同樣
的門檻、同樣的「一定要修／建議修／通過」與準備度評級。這一頁檢查的對象就是②字幕頁開著的影片與字幕
（按「開始健檢」時現拿：逐句校對改到一半的會先套用，報告講的是現在的句子）。

這一階段還沒有的（頁面上寫明，請先用一般版）：
* 發佈文字（標題／說明欄／標籤）、章節、封面圖、系列一致性這四種對象——它們要另外填或選，下一階段搬。
* 要輸出新影音檔的修復（音訊修復版、修剪頭尾、拉平音量）——下一階段搬。

字幕類的修復（延長過快字幕、修重疊、標點、同步、術語）直接改②的字幕：整批是一步，②字幕頁按「復原」
（Ctrl+Z）就還原；改完自動重新健檢。健檢之後字幕又改過的話不修（結果講的是舊句子），請先重新健檢。

勾選哪幾項只記在這次開啟的設定裡（跟一般版同一個區塊，切去一般版前不會寫進 config.json：Qt 預覽版不
寫設定檔）。這一頁看不到的三項（發佈資訊、封面、章節）原本的勾選不動。
"""
import os
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton,
    QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from subtitle import healthcheck as hc
from subtitle.errors import describe_exception
from subtitle.preflight import LEVEL_BAD, LEVEL_GOOD, LEVEL_WARN

# 這一階段搬過來的項目：只看影片與字幕的（要另外填發佈文字、章節或選封面圖的下一階段才搬）
LATER_KEYS = frozenset(c.key for c in hc.CHECK_DEFS
                       if c.needs_publish_text or c.needs_images or c.needs_chapters_text)
STAGE_CHECKS = tuple(c for c in hc.CHECK_DEFS if c.key not in LATER_KEYS)

LEVEL_LABELS = (("一定要修", LEVEL_BAD), ("建議修", LEVEL_WARN), ("通過", LEVEL_GOOD))
LEVEL_ICONS = {LEVEL_BAD: "✘", LEVEL_WARN: "⚠", LEVEL_GOOD: "✔"}
CHECK_COLUMNS = 3

PAGE_NOTE = ("檢查②字幕頁開著的影片與字幕：音訊、畫質、曝光、音量、節奏、字幕（CPS／行數／重疊）、"
             "廣告友善度、開場、可讀性、標點、語音同步、片尾、工商揭露、術語、檔名，跟一般版同一套門檻。"
             "字幕類的問題可以直接按「修復此項」。要輸出新影音檔的修復（音訊、修剪、音量），以及發佈文字、章節、"
             "封面圖、系列一致性的檢查，還在一般版（之後的階段搬過來）。")
NOTHING = "先在②字幕頁開影片或載入字幕，這裡才有東西可以檢查。"
NONE_CHECKED = "請至少勾一項要跑的檢查。"
DETAIL_EMPTY = "（點上面一筆結果看詳情與建議）"
FIX_DEFAULT = "修復此項"
FIX_CUE_NOTE = "直接改②的字幕（整批一步，②字幕頁按「復原」就還原），改完自動重新健檢。"
FIX_MEDIA_NOTE = "這項要輸出一個新的影音檔，還在一般版（之後的階段搬過來）。"
FIX_STALE = "字幕在健檢之後又改過了，結果講的是舊的句子：請先按「開始健檢」重新檢查，再修復。"
FIX_NOTHING = "沒有可修復的內容（可能空檔不足，或已經符合規範）。"


class HealthWorker(QObject):
    """背景執行緒跑 healthcheck.run_health_scan；進度與結果用訊號送回主執行緒。"""

    progress = Signal(float, str)
    finished = Signal(object)  # run_health_scan 的結果
    failed = Signal(object)    # 例外

    def __init__(self, parent=None):
        super().__init__(parent)
        # 由畫面那邊（主執行緒）收到結果時才放下：在背景放下的話，結果還沒畫上去就「不忙」了
        self.busy = False

    def start(self, media_path, cues, config, keys):
        self.busy = True
        threading.Thread(target=self._run, args=(media_path, cues, config, keys), daemon=True).start()

    def _run(self, media_path, cues, config, keys):
        try:
            result = hc.run_health_scan(media_path, cues, config, keys,
                                        progress_cb=lambda r, m: self.progress.emit(float(r), str(m)))
        except Exception as exc:  # noqa: BLE001 —— 背景執行緒的例外一律送回畫面上講
            self.failed.emit(exc)
            return
        self.finished.emit(result)


class HealthPanel(QWidget):
    """③健檢中心頁：勾選要跑的項目 → 開始健檢 → 結果依「一定要修／建議修／通過」分組。"""

    def __init__(self, player, before_scan=None, parent=None):
        super().__init__(parent)
        self.player = player
        self.before_scan = before_scan  # 開始前先叫：逐句校對編輯框裡改到一半的先套用
        self.config = player._config    # 跟播放器同一份（這次開啟的設定）
        self.last_result = None
        self._findings = []  # 清單上每一列對應的結果，列上記著編號

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        note = QLabel(PAGE_NOTE)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.target_label = QLabel()
        self.target_label.setWordWrap(True)
        layout.addWidget(self.target_label)

        box = QGroupBox("要跑哪些檢查（這次開啟會記住）")
        grid = QGridLayout(box)
        chosen = hc.default_selected_keys(self.config)
        self.check_boxes = {}
        index = 0
        for check in STAGE_CHECKS:
            if check.always_on:
                continue
            cb = QCheckBox(check.label)
            cb.setChecked(check.key in chosen)
            grid.addWidget(cb, index // CHECK_COLUMNS, index % CHECK_COLUMNS)
            self.check_boxes[check.key] = cb
            index += 1
        # 檔名一律跟著跑（有開影片才有意義）：畫成停用的勾選，讓人知道這項還在
        self.filename_box = QCheckBox("檔名（有開影片就一併檢查）")
        self.filename_box.setChecked(True)
        self.filename_box.setEnabled(False)
        grid.addWidget(self.filename_box, index // CHECK_COLUMNS, index % CHECK_COLUMNS)
        layout.addWidget(box)

        row = QHBoxLayout()
        self.run_btn = QPushButton("開始健檢")
        self.run_btn.clicked.connect(self.start_scan)
        self.copy_btn = QPushButton("複製報告")
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self.copy_report)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        row.addWidget(self.run_btn)
        row.addWidget(self.copy_btn)
        row.addWidget(self.progress_bar, 1)
        layout.addLayout(row)
        layout.addWidget(self.status_label)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["狀態／項目", "來源"])
        self.tree.setColumnWidth(0, 460)
        self.tree.currentItemChanged.connect(self._on_current)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText(DETAIL_EMPTY)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.detail, 1)
        self.fix_btn = QPushButton(FIX_DEFAULT)
        self.fix_btn.clicked.connect(self.apply_fix)
        self.fix_note = QLabel()
        self.fix_note.setWordWrap(True)
        right_layout.addWidget(self.fix_btn)
        right_layout.addWidget(self.fix_note)
        self._current_row = None  # 右邊正在看的那一筆結果
        self._fix_note = ""       # 修完重新健檢時，狀態列前面先講修了什麼
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.tree)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        layout.addWidget(self.splitter, 1)

        self.worker = HealthWorker(self)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        player.cuesChanged.connect(self.refresh_target)
        self.refresh_target()
        self._update_fix()

    # ----- 對象 -----
    def refresh_target(self):
        """上方那行：要檢查的是哪支影片、幾句字幕（切到這頁、字幕改了都會更新）。"""
        media = self.player.media_path
        parts = [f"影片：{os.path.basename(media)}" if media else "影片：還沒開（需要影片的項目會略過）"]
        count = len(self.player.cues)
        parts.append(f"字幕：{count} 句" if count else "字幕：沒有（字幕類的項目會略過）")
        self.target_label.setText("檢查對象（②字幕頁開著的）：" + "　".join(parts))

    def showEvent(self, event):  # noqa: N802 —— 切到這一頁時更新對象（換影片沒有訊號）
        super().showEvent(event)
        self.refresh_target()

    # ----- 勾選 -----
    def selected_keys(self):
        return {key for key, cb in self.check_boxes.items() if cb.isChecked()}

    def remember_selection(self):
        """記在這次開啟的設定裡；這頁看不到的項目（發佈、封面、章節）維持原本的勾選。"""
        keep = hc.default_selected_keys(self.config) & LATER_KEYS
        hc.save_selected_keys(self.config, self.selected_keys() | keep)

    # ----- 健檢 -----
    def busy(self):
        return self.worker.busy

    def start_scan(self):
        if self.worker.busy:
            return False
        if callable(self.before_scan):
            self.before_scan()
        self.refresh_target()
        media, cues = self.player.media_path, [dict(c) for c in self.player.cues]
        if not media and not cues:
            self.status_label.setText(NOTHING)
            return False
        keys = self.selected_keys()
        if not keys:
            self.status_label.setText(NONE_CHECKED)
            return False
        self.remember_selection()
        # 先讓背景開始（算「忙」），再灰掉按鈕：修復鈕看的是「忙不忙」。進度與結果是排隊送回來的，
        # 一定在這幾行之後才處理。
        self.worker.start(media, cues, dict(self.config), keys)
        self.progress_bar.setValue(0)
        self._set_busy(True)
        self.status_label.setText(f"{self._fix_note}健檢進行中…")
        return True

    def _set_busy(self, busy):
        self.run_btn.setEnabled(not busy)
        self.run_btn.setText("健檢中…" if busy else "開始健檢")
        self.progress_bar.setVisible(busy)
        for cb in self.check_boxes.values():
            cb.setEnabled(not busy)
        if busy:
            self.copy_btn.setEnabled(False)
        self._update_fix()

    def _on_progress(self, ratio, message):
        self.progress_bar.setValue(int(max(0.0, min(ratio, 1.0)) * 1000))
        if message:
            self.status_label.setText(f"{self._fix_note}健檢進行中：{message}")

    def _on_failed(self, exc):
        self.worker.busy = False
        self._set_busy(False)
        self.copy_btn.setEnabled(self.last_result is not None)
        self.status_label.setText(f"{self._take_fix_note()}健檢失敗：{describe_exception(exc)}")

    def _on_finished(self, result):
        self.show_result(result)
        self.worker.busy = False
        self._set_busy(False)

    # ----- 結果 -----
    def show_result(self, result):
        self.last_result = result
        self.tree.clear()
        self._show_row(None)
        self._findings = []
        findings = result.get("findings") or []
        for label, level in LEVEL_LABELS:
            rows = [f for f in findings if f.get("level") == level]
            group = QTreeWidgetItem(self.tree, [f"{label}（{len(rows)}）", ""])
            for row in rows:
                item = QTreeWidgetItem(group, [f"{LEVEL_ICONS.get(level, '・')} {row.get('title', '')}",
                                               row.get("source", "")])
                item.setData(0, Qt.UserRole, len(self._findings))
                self._findings.append((item, row))
            group.setExpanded(level != LEVEL_GOOD)
        skipped = result.get("skipped") or []
        if skipped:
            group = QTreeWidgetItem(self.tree, [f"略過的項目（{len(skipped)}）", ""])
            for text in skipped:
                QTreeWidgetItem(group, [f"・{text}", ""]).setToolTip(0, text)
            group.setExpanded(True)
        self.copy_btn.setEnabled(True)
        counts = result.get("counts") or {}
        grade = result.get("grade", "?")
        if not findings:
            text = "健檢完成：沒有可檢查的項目（看「略過的項目」）。"
        elif result.get("ok"):
            text = f"健檢完成，準備度 {grade}：沒有「一定要修」的項目（建議修 {counts.get(LEVEL_WARN, 0)} 項）。"
        else:
            text = (f"健檢完成，準備度 {grade}：{counts.get(LEVEL_BAD, 0)} 項一定要修、"
                    f"{counts.get(LEVEL_WARN, 0)} 項建議修，詳見下方清單。")
        self.status_label.setText(self._take_fix_note() + text)

    def _take_fix_note(self):
        note, self._fix_note = self._fix_note, ""
        return note

    def finding_items(self):
        """[(清單上的那一列, 那一筆結果)]，照畫面由上而下（測試與之後的修復用）。"""
        return list(self._findings)

    def _on_current(self, item, _previous=None):
        index = item.data(0, Qt.UserRole) if item is not None else None
        # 分組標題、略過的項目沒有編號
        self._show_row(None if index is None else self._findings[index][1])

    def _show_row(self, row):
        self._current_row = row
        self._update_fix()
        if row is None:
            self.detail.clear()
            return
        lines = [f"{LEVEL_ICONS.get(row.get('level'), '・')} [{row.get('source', '')}] {row.get('title', '')}"]
        if row.get("detail"):
            lines += ["", row["detail"]]
        if row.get("advice") and row.get("level") != LEVEL_GOOD:
            lines += ["", f"建議：{row['advice']}"]
        self.detail.setPlainText("\n".join(lines))

    # ----- 修復此項 -----
    def _update_fix(self):
        """右下的修復鈕：字幕類可以按；影音類寫明還在一般版；沒有修復的灰掉。"""
        key = (self._current_row or {}).get("fix_key")
        self.fix_btn.setText(hc.FIX_LABELS.get(key, FIX_DEFAULT) if key else FIX_DEFAULT)
        self.fix_btn.setEnabled(key in hc.CUE_FIX_KEYS and not self.worker.busy)
        self.fix_note.setText(FIX_CUE_NOTE if key in hc.CUE_FIX_KEYS
                              else FIX_MEDIA_NOTE if key in hc.MEDIA_FIX_KEYS else "")

    def apply_fix(self):
        """修右邊正在看的那一筆（字幕類）：套用到②的字幕（一步復原）、重新健檢。回傳有沒有改。"""
        key = (self._current_row or {}).get("fix_key")
        if self.worker.busy or key not in hc.CUE_FIX_KEYS or self.last_result is None:
            return False
        if callable(self.before_scan):
            self.before_scan()
        cues = [dict(c) for c in self.player.cues]
        if cues != list(self.last_result.get("cues") or []):
            self.status_label.setText(FIX_STALE)
            return False
        try:
            new_cues, changed, message = hc.apply_cue_fix(key, cues, dict(self.config),
                                                          self.last_result.get("raw") or {})
        except hc.FixError as exc:
            self.status_label.setText(str(exc))
            return False
        if not changed:
            self.status_label.setText(FIX_NOTHING)
            return False
        try:
            self.player.apply_cues(new_cues)
        except ValueError:
            self.status_label.setText("修復後的句數對不上，沒有套用。")
            return False
        self._fix_note = f"{message}（②字幕頁按「復原」就還原）"
        if not self.start_scan():  # 例如勾選全取消了：修好的照樣留著，講清楚沒重新檢查
            self.status_label.setText(f"{self._take_fix_note()}沒有重新健檢：{self.status_label.text()}")
        return True

    def report_text(self):
        return hc.format_health_report(self.last_result) if self.last_result else ""

    def copy_report(self):
        text = self.report_text()
        if text:
            QGuiApplication.clipboard().setText(text)
            self.status_label.setText("報告已複製，可以貼到記事本或傳給別人。")
