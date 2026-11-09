# -*- coding: utf-8 -*-
"""
③健檢中心（3.0 第 11 項第八階段：先搬影片與字幕的檢查；第九、十階段：「修復此項」；第十一階段：
發佈文字與章節）。

檢查與報告跟一般版同一份（`subtitle/healthcheck.py`，原 `gui/health_aggregator.py`）：同樣的項目、同樣
的門檻、同樣的「一定要修／建議修／通過」與準備度評級。這一頁檢查的對象就是②字幕頁開著的影片與字幕
（按「開始健檢」時現拿：逐句校對改到一半的會先套用，報告講的是現在的句子）。

這一階段還沒有的（頁面上寫明，請先用一般版）：
* 封面圖、系列一致性這兩種對象——之後的階段搬。

發佈文字（標題／說明欄／標籤）與章節在「發佈文字與章節」那塊另外貼（選填，填什麼檢什麼；只放在畫面上、
不存檔，跟一般版一樣）。「一鍵修正章節」直接改章節框的文字（在章節框按 Ctrl+Z 就還原），改完自動重新
健檢；健檢之後章節框又改過的話不修。

字幕類的修復（延長過快字幕、修重疊、標點、同步、術語）直接改②的字幕：整批是一步，②字幕頁按「復原」
（Ctrl+Z）就還原；改完自動重新健檢。健檢之後字幕又改過的話不修（結果講的是舊句子），請先重新健檢。

影音類的修復（音訊修復版、修剪頭尾、拉平音量）在背景用 ffmpeg 另外輸出一個新檔（原檔不動，檔名跟一般版
一樣，同名就加編號）。做好後問要不要在②換成修復版：換的話跟②「開影片」一樣（專案有沒存的變更先問；素材軌
與畫面調整會清掉，字幕留著）。修剪版的字幕時間不會跟著往前移，問的時候寫明。輸出到一半不能停（一般版也不
能），關視窗時先問。健檢之後②換過影片的話不修，請先重新健檢。修「整體響度」那筆時一併做響度正規化（預設
沒勾，照預設輸出聲音不會變大），只在那一次、不改記著的設定，畫面上寫明。

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
LATER_KEYS = frozenset(c.key for c in hc.CHECK_DEFS if c.needs_images)  # 封面圖：之後的階段
STAGE_CHECKS = tuple(c for c in hc.CHECK_DEFS if c.key not in LATER_KEYS)

LEVEL_LABELS = (("一定要修", LEVEL_BAD), ("建議修", LEVEL_WARN), ("通過", LEVEL_GOOD))
LEVEL_ICONS = {LEVEL_BAD: "✘", LEVEL_WARN: "⚠", LEVEL_GOOD: "✔"}
CHECK_COLUMNS = 3

PAGE_NOTE = ("檢查②字幕頁開著的影片與字幕：音訊、畫質、曝光、音量、節奏、字幕（CPS／行數／重疊）、"
             "廣告友善度、開場、可讀性、標點、語音同步、片尾、工商揭露、術語、檔名，跟一般版同一套門檻；"
             "發佈文字與章節在下面另外貼。可以直接按「修復此項」：字幕類直接改②的字幕，影音類另外輸出一個"
             "修復版，章節直接改章節框。封面圖、系列一致性的檢查還在一般版（之後的階段搬過來）。")
PUBLISH_CLOSED = "▸ 發佈文字與章節（選填，填什麼檢什麼；點一下展開）"
PUBLISH_OPEN = "▾ 發佈文字與章節（選填，填什麼檢什麼；點一下收合）"
PUBLISH_NOTE = ("標籤用逗號分隔，就是 YouTube 後台那一欄的填法。說明欄上限算的是位元組，中文一個字佔 3 個。"
                "這裡貼的只放在畫面上、不存檔。")
NOTHING = "先在②字幕頁開影片或載入字幕，或在下面貼發佈文字、章節，這裡才有東西可以檢查。"
NONE_CHECKED = "請至少勾一項要跑的檢查。"
DETAIL_EMPTY = "（點上面一筆結果看詳情與建議）"
FIX_DEFAULT = "修復此項"
FIX_CUE_NOTE = "直接改②的字幕（整批一步，②字幕頁按「復原」就還原），改完自動重新健檢。"
FIX_MEDIA_NOTE = "另外輸出一個修復版（原檔不動），做好後問要不要在②換成它。輸出到一半不能停。"
FIX_LOUD_NOTE = ("這筆是整體響度：這次會一併做響度正規化，聲音才會真的變大（一般版要另外到進階設定勾，"
                 "預設沒勾）。")
FIX_STALE_MEDIA = "②在健檢之後換過影片了，結果講的是之前那支：請先按「開始健檢」重新檢查，再修復。"
FIX_NO_MEDIA = "②還沒開影片（或檔案找不到了），沒有東西可以修。"
FIX_NO_FFMPEG = "找不到 ffmpeg，輸出修復版需要它：請先在一般版按「自動安裝 ffmpeg」（兩版共用）。"
FIX_STALE = "字幕在健檢之後又改過了，結果講的是舊的句子：請先按「開始健檢」重新檢查，再修復。"
FIX_TEXT_NOTE = "直接改上面的章節文字（在章節框按 Ctrl+Z 就還原），改完自動重新健檢。"
FIX_STALE_TEXT = "章節文字在健檢之後又改過了，結果講的是舊的：請先按「開始健檢」重新檢查，再修正。"
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

    def start(self, media_path, cues, config, keys, publish=None):
        self.busy = True
        threading.Thread(target=self._run, args=(media_path, cues, config, keys, publish), daemon=True).start()

    def _run(self, media_path, cues, config, keys, publish):
        try:
            result = hc.run_health_scan(media_path, cues, config, keys,
                                        progress_cb=lambda r, m: self.progress.emit(float(r), str(m)),
                                        publish=publish)
        except Exception as exc:  # noqa: BLE001 —— 背景執行緒的例外一律送回畫面上講
            self.failed.emit(exc)
            return
        self.finished.emit(result)


class MediaFixWorker(QObject):
    """背景執行緒跑 healthcheck.apply_media_fix（ffmpeg 輸出修復版）。busy 同樣由畫面那邊放下。"""

    progress = Signal(float, str)
    finished = Signal(str)     # 輸出的檔案
    failed = Signal(object)    # 例外（FixError＝前置條件不足，訊息可以直接給人看）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False

    def start(self, fix_key, media_path, output_path, config, raw):
        self.busy = True
        threading.Thread(target=self._run, args=(fix_key, media_path, output_path, config, raw),
                         daemon=True).start()

    def _run(self, fix_key, media_path, output_path, config, raw):
        try:
            path = hc.apply_media_fix(fix_key, media_path, output_path, config, raw,
                                      progress_cb=lambda r, m: self.progress.emit(float(r), str(m)))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(exc)
            return
        self.finished.emit(str(path))


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
        layout.addWidget(self._build_publish())

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
        self._fix_key, self._fix_output = None, ""  # 正在輸出的影音修復與輸出檔
        self.last_fixed = ""       # 最近一次輸出的修復版
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
        self.fixer = MediaFixWorker(self)
        self.fixer.progress.connect(self._on_fix_progress)
        self.fixer.finished.connect(self._on_fix_finished)
        self.fixer.failed.connect(self._on_fix_failed)
        self._pending_media = ""  # 這次健檢的影片
        self._scan_media = ""     # 目前結果是哪支影片的（影音修復前比對）
        self._pending_publish = self._scan_publish = {}  # 同上，發佈文字與章節（修正章節前比對）
        player.cuesChanged.connect(self.refresh_target)
        self.refresh_target()
        self._update_fix()

    # ----- 發佈文字與章節 -----
    def _build_publish(self):
        from PySide6.QtWidgets import QFormLayout, QLineEdit, QToolButton
        wrap = QWidget()
        outer = QVBoxLayout(wrap)
        outer.setContentsMargins(0, 0, 0, 0)
        self.publish_toggle = QToolButton()
        self.publish_toggle.setText(PUBLISH_CLOSED)
        self.publish_toggle.setAutoRaise(True)
        self.publish_toggle.clicked.connect(lambda: self.show_publish(not self.publish_body.isVisible()))
        outer.addWidget(self.publish_toggle)
        self.publish_body = QWidget()
        form = QFormLayout(self.publish_body)
        self.publish_title = QLineEdit()
        self.publish_title.setPlaceholderText("影片標題")
        self.publish_desc = QPlainTextEdit()
        self.publish_desc.setPlaceholderText("說明欄（整段貼上）")
        self.publish_tags = QLineEdit()
        self.publish_tags.setPlaceholderText("標籤一, 標籤二, 標籤三")
        self.publish_chapters = QPlainTextEdit()
        self.publish_chapters.setPlaceholderText("0:00 開場\n1:30 第一段")
        for edit in (self.publish_desc, self.publish_chapters):
            edit.setFixedHeight(72)
        form.addRow("標題", self.publish_title)
        form.addRow("說明欄", self.publish_desc)
        form.addRow("標籤", self.publish_tags)
        form.addRow("章節", self.publish_chapters)
        note = QLabel(PUBLISH_NOTE)
        note.setWordWrap(True)
        form.addRow(note)
        self.publish_body.setVisible(False)
        outer.addWidget(self.publish_body)
        return wrap

    def show_publish(self, shown=True):
        self.publish_body.setVisible(shown)
        self.publish_toggle.setText(PUBLISH_OPEN if shown else PUBLISH_CLOSED)

    def publish_text(self):
        """{"title","description","tags","chapters_text"}：跟一般版對象區同一個格式。"""
        return {"title": self.publish_title.text(), "description": self.publish_desc.toPlainText(),
                "tags": self.publish_tags.text(), "chapters_text": self.publish_chapters.toPlainText()}

    @staticmethod
    def _has_text(publish):
        return hc.has_publish_text(publish) or bool((publish.get("chapters_text") or "").strip())

    # ----- 對象 -----
    def refresh_target(self):
        """上方那行：要檢查的是哪支影片、幾句字幕（切到這頁、字幕改了都會更新）。"""
        media = self.player.media_path
        parts = [f"影片：{os.path.basename(media)}" if media else "影片：還沒開（需要影片的項目會略過）"]
        count = len(self.player.cues)
        parts.append(f"字幕：{count} 句" if count else "字幕：沒有（字幕類的項目會略過）")
        if hasattr(self, "publish_title") and self._has_text(self.publish_text()):
            parts.append("另外貼了發佈文字或章節")
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
        return self.worker.busy or self.fixer.busy

    def fixing(self):
        return self.fixer.busy

    def start_scan(self):
        if self.busy():
            return False
        if callable(self.before_scan):
            self.before_scan()
        self.refresh_target()
        media, cues = self.player.media_path, [dict(c) for c in self.player.cues]
        publish = self.publish_text()
        if not media and not cues and not self._has_text(publish):
            self.status_label.setText(NOTHING)
            return False
        keys = self.selected_keys()
        if not keys:
            self.status_label.setText(NONE_CHECKED)
            return False
        self.remember_selection()
        # 先讓背景開始（算「忙」），再灰掉按鈕：修復鈕看的是「忙不忙」。進度與結果是排隊送回來的，
        # 一定在這幾行之後才處理。
        self.worker.start(media, cues, dict(self.config), keys, publish)
        self._pending_media, self._pending_publish = media, publish
        self.progress_bar.setValue(0)
        self._set_busy(True)
        self.status_label.setText(f"{self._fix_note}健檢進行中…")
        return True

    def _set_busy(self, busy, label="健檢中…"):
        self.run_btn.setEnabled(not busy)
        self.run_btn.setText(label if busy else "開始健檢")
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
        self._scan_media, self._scan_publish = self._pending_media, self._pending_publish
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
        self.fix_btn.setEnabled((key in hc.CUE_FIX_KEYS or key in hc.MEDIA_FIX_KEYS or key in hc.TEXT_FIX_KEYS)
                                and not self.busy())
        note = (FIX_CUE_NOTE if key in hc.CUE_FIX_KEYS else FIX_MEDIA_NOTE if key in hc.MEDIA_FIX_KEYS
                else FIX_TEXT_NOTE if key in hc.TEXT_FIX_KEYS else "")
        if self._loudness_row():
            note += FIX_LOUD_NOTE
        self.fix_note.setText(note)

    def _loudness_row(self):
        """
        正在看的是「整體響度」那筆嗎。這筆的修復是音訊修復版，但響度正規化預設沒勾，照預設輸出聲音不會變大
        （一般版的建議寫著要另外勾）。這裡修這筆時就一併做——只在這一次，不改記著的設定。
        """
        row = self._current_row or {}
        return row.get("fix_key") == "audiofix" and row.get("source") == "音訊健檢" and row.get("title") == "整體響度"

    def apply_fix(self):
        """
        修右邊正在看的那一筆。字幕類：套用到②的字幕（一步復原）、重新健檢，回傳有沒有改。
        影音類：開始在背景輸出修復版，回傳有沒有開始。
        """
        key = (self._current_row or {}).get("fix_key")
        if self.busy() or self.last_result is None:
            return False
        if key in hc.MEDIA_FIX_KEYS:
            return self._start_media_fix(key)
        if key in hc.TEXT_FIX_KEYS:
            return self._apply_text_fix(key)
        if key not in hc.CUE_FIX_KEYS:
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

    def _apply_text_fix(self, key):
        """一鍵修正章節：新文字寫進章節框（Ctrl+Z 可以還原）、重新健檢。"""
        if self.publish_chapters.toPlainText() != (self._scan_publish or {}).get("chapters_text", ""):
            self.status_label.setText(FIX_STALE_TEXT)
            return False
        try:
            text, changes, message = hc.apply_text_fix(key, dict(self.config), self.last_result.get("raw") or {})
        except hc.FixError as exc:
            self.status_label.setText(str(exc))
            return False
        if not changes:
            self.status_label.setText(message)
            return False
        self.show_publish(True)  # 看得到被改了什麼
        cursor = self.publish_chapters.textCursor()
        cursor.select(cursor.SelectionType.Document)
        cursor.insertText(text)  # 用游標換、不用 setPlainText：這樣章節框的 Ctrl+Z 還原得回來
        self._fix_note = f"{message}（在章節框按 Ctrl+Z 就還原）"
        if not self.start_scan():
            self.status_label.setText(f"{self._take_fix_note()}沒有重新健檢：{self.status_label.text()}")
        return True

    def _start_media_fix(self, key):
        media = self.player.media_path
        if not media or not os.path.exists(media):
            self.status_label.setText(FIX_NO_MEDIA)
            return False
        if media != self._scan_media:
            self.status_label.setText(FIX_STALE_MEDIA)
            return False
        from subtitle.burner import ffmpeg_available
        if not ffmpeg_available():
            self.status_label.setText(FIX_NO_FFMPEG)
            return False
        try:
            output = hc.suggest_fix_output_path(key, media)
        except hc.FixError as exc:
            self.status_label.setText(str(exc))
            return False
        self._fix_key, self._fix_output = key, output
        config = dict(self.config)
        if self._loudness_row():
            config["audiofix"] = dict(config.get("audiofix") or {}, loudnorm=True)
        self.fixer.start(key, media, output, config, self.last_result.get("raw") or {})
        self.progress_bar.setValue(0)
        self._set_busy(True, "輸出修復版中…")
        self.status_label.setText(f"正在輸出修復版：{os.path.basename(output)}（原檔不動）")
        return True

    def _on_fix_progress(self, ratio, message):
        self.progress_bar.setValue(int(max(0.0, min(ratio, 1.0)) * 1000))
        if message:
            self.status_label.setText(f"輸出修復版：{message}")

    def _on_fix_failed(self, exc):
        self.fixer.busy = False
        self._set_busy(False)
        self.copy_btn.setEnabled(self.last_result is not None)
        if isinstance(exc, hc.FixError):  # 前置條件不足（例如沒有偵測到頭尾廢秒）：一般版同一句
            self.status_label.setText(str(exc))
        else:
            self.status_label.setText(f"修復失敗：{describe_exception(exc)}")

    def _on_fix_finished(self, path):
        self.fixer.busy = False
        self._set_busy(False)
        self.copy_btn.setEnabled(self.last_result is not None)
        done = f"修復版已輸出：{os.path.basename(path)}（在 {os.path.dirname(path)}）。"
        self.last_fixed = path
        self.status_label.setText(done)
        if not self._ask_adopt(path, self._fix_key):
            return
        if not self.player._maybe_drop_project():  # 跟②「開影片」一樣：專案有沒存的變更先問
            self.status_label.setText(done + "②沒有換（專案的變更還沒處理）。")
            return
        self.player.open_video(path)
        self.refresh_target()
        self.status_label.setText(done + "②已換成修復版，按「開始健檢」就是修好之後的結果。")

    def adopt_question(self, path, key):
        """問要不要在②換成修復版的那段話（修剪版另外寫明字幕時間不會跟著移）。"""
        text = (f"已輸出：{os.path.basename(path)}\n\n要在②換成這個修復版嗎？建議先播放或試聽確認結果。\n"
                "換的話跟②「開影片」一樣：素材軌與畫面調整會清掉，字幕留著；選「否」只是輸出檔案。")
        if key == "trim" and self.player.cues:
            text += "\n\n注意：修剪版剪掉了開頭，②的字幕時間不會跟著往前移，換了之後要自己對時間。"
        return text

    def _ask_adopt(self, path, key):
        from PySide6.QtWidgets import QMessageBox
        answer = QMessageBox.question(self, "修復完成", self.adopt_question(path, key))
        return answer == QMessageBox.Yes

    def close_question(self):
        return (f"修復版（{os.path.basename(self._fix_output)}）還在輸出。\n\n現在關掉的話這個檔可能不完整，"
                "請不要拿它來用（要的話重開之後再修復一次）。還是要關嗎？")

    def ask_close_while_fixing(self):
        """關視窗時修復版還在輸出：問要不要關。回傳 True＝可以關。"""
        from PySide6.QtWidgets import QMessageBox
        answer = QMessageBox.question(self, "修復版還在輸出", self.close_question())
        return answer == QMessageBox.Yes

    def report_text(self):
        return hc.format_health_report(self.last_result) if self.last_result else ""

    def copy_report(self):
        text = self.report_text()
        if text:
            QGuiApplication.clipboard().setText(text)
            self.status_label.setText("報告已複製，可以貼到記事本或傳給別人。")
