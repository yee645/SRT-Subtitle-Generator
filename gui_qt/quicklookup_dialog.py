# -*- coding: utf-8 -*-
"""
即時查譯（3.0 第 11 項第二十三階段）：一般版 `gui/quicktranslate_panel.py` 的「查譯」與「生字本」兩頁。

在本程式任何文字框（②的逐句校對、①的搜尋框…）選取一段外文，鬆開滑鼠（或放開 Shift 選字的鍵）
就翻譯；也可以按〔翻譯選取內容〕，沒選字時翻②字幕清單選中的那一句。核心同一套：
`subtitle/quicktranslate.py`（正規化、值不值得送、快取、呼叫 OpenAI）、`subtitle/screentranslate.is_secret`
（像密碼的不送）、`subtitle/quicklookup.py`（生字本、略過原因）。

**會送出去的**：只有選取的那一段文字，送到 OpenAI（用一般版「轉寫設定」的金鑰，照用量收費），面板最上面
寫明。不送：檔名、整份字幕、其他檔案；像密碼或金鑰的內容、密碼欄位裡的字都不送（寧可漏翻、不可誤送）。
面板收起來時選字不會觸發。

跟一般版不同的地方：
- 觸發方式：Tk 聽 `<<Selection>>` 再等滑鼠放開；Qt 在整個程式的事件裡看「放開滑鼠／放開按鍵時，
  那個文字框（或焦點所在的文字框）有沒有選取」，面板自己的框不算，去抖動一樣用 `debounce_ms`。密碼欄位（QLineEdit 不是一般顯示模式）略過。
- 沒有金鑰時的說明指向一般版的「轉寫設定」（Qt 預覽版還沒有填金鑰的地方）。
- 設定只記在這次開啟的設定裡（第 19 項之前不寫 config.json）。**生字本照樣寫**：它是查譯的結果、
  不是設定，跟一般版存在同一個檔（config.json 旁邊的 quicktranslate_vocab.json），兩版看到的是同一本。

朗讀、監聽剪貼簿、框選螢幕翻譯、全域熱鍵是第 17 列之後的階段。
關閉＝收起來（快取與生字本都留著），再按一次〔即時查譯…〕原地打開。
"""
import os
import threading

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

import config as config_module
from subtitle import quicklookup as ql
from subtitle import quicktranslate as qt
from subtitle import screentranslate as st
from subtitle.translator import LANGUAGE_LABELS

TITLE = "即時查譯（選字即翻）"
HINT = ("在本程式任何文字框（②的逐句校對、①的搜尋框…）選取一段外文，鬆開滑鼠就自動翻譯。"
        "會送出去的只有選取的那段文字，送到 OpenAI（照用量收費，短句約千分之一美元）；"
        "同樣的字句直接用快取，不重複計費。像密碼或金鑰的內容、密碼欄位裡的字不會送。")
INITIAL = ("還沒有查過任何內容。到②的逐句校對框、或任何文字框，用滑鼠選取一段外文試試。"
           "也可以先點②字幕清單的某一句，再按「翻譯選取內容」。")
WAITING = "等待選取。"
LOADING = "翻譯中…（通常 1～2 秒，視 OpenAI 回應速度）"
DONE_SAVED = "翻譯完成。查過的詞已存入生字本。"
DONE = "翻譯完成。"
CACHED = "翻譯完成（快取結果，這次不計費）。"
EXPLAIN_OFF = "已關閉關鍵詞解說。勾選「附關鍵詞解說」後，下一次查譯會一併標出值得學的詞（同一次呼叫順帶回傳，不另外計費）。"
NO_TERMS = "這段文字太短或太簡單，這次沒有值得特別解說的詞。"
NOKEY_STATUS = "尚未填入 OpenAI API 金鑰，選取暫時不會觸發翻譯。"
NOKEY_BODY = ("即時查譯需要連網呼叫 OpenAI API。目前沒有填過 API 金鑰，所以這個功能還不能用。\n\n"
              "想啟用：到 platform.openai.com 申請金鑰，在一般版（不加 --qt）的「轉寫設定」貼進「API 金鑰」欄位"
              "（不必勾選「改用 OpenAI API」），再回來這裡。查譯用的是最便宜的文字模型，選一句話約千分之一美元。")
AUTO_PAUSED = "連續 3 次翻譯失敗，已先暫停自動翻譯，避免每選一次就失敗一次。問題排除後重新勾選「選取後自動翻譯」即可。"
NOTHING_SELECTED = "沒有選取內容。先選取一段文字，或點②字幕清單的一句再按此鈕。"
SECRET_BLOCKED = "這段內容看起來像密碼或金鑰，不會送去翻譯。需要的話仍可複製。"
NOTHING_TO_COPY = "還沒有可以複製的內容。"
VOCAB_HINT = ("查譯時的關鍵詞會自動收進這裡（本機保存，不佔 API 費用；跟一般版是同一本）。"
              "匯出的 CSV 前欄是詞、後欄是意思，可直接匯入 Anki 做記憶卡。")
FAILURE_LIMIT = 3
_TEXT_WIDGETS = (QLineEdit, QPlainTextEdit, QTextEdit)


def vocab_path():
    """生字本的檔：config.json 旁邊（跟一般版同一個；呼叫當下才算，測試換掉 CONFIG_PATH 會跟著走）。"""
    return os.path.join(os.path.dirname(os.path.abspath(config_module.CONFIG_PATH)) or ".", ql.VOCAB_FILENAME)


def text_widget_of(obj):
    """事件落在哪個文字框：文字框本身，或它的 viewport（滑鼠事件送到 viewport）。不是就回傳 None。"""
    if isinstance(obj, _TEXT_WIDGETS):
        return obj
    parent = obj.parent() if isinstance(obj, QWidget) else None
    if isinstance(parent, (QPlainTextEdit, QTextEdit)) and obj is parent.viewport():
        return parent
    return None


def selected_text_of(widget):
    """文字框目前選取的字；不是文字框、是密碼欄位、沒選取都回傳空字串。"""
    if isinstance(widget, QLineEdit):
        if widget.echoMode() != QLineEdit.Normal:
            return ""  # 密碼欄位：選了也不拿
        return widget.selectedText()
    if isinstance(widget, (QPlainTextEdit, QTextEdit)):
        # Qt 用 U+2029 當段落分隔
        return widget.textCursor().selectedText().replace("\u2029", "\n").replace("\u2028", "\n")
    return ""


class LookupWorker(QObject):
    """背景執行緒呼叫 translate_snippet；結果帶著請求編號送回（舊的請求作廢）。"""

    finished = Signal(int, str, object)  # (請求編號, 原文, 結果)
    failed = Signal(int, str, object)

    def start(self, request_id, source, api_key, settings, cache):
        threading.Thread(target=self._run, args=(request_id, source, api_key, dict(settings), cache),
                         daemon=True).start()

    def _run(self, request_id, source, api_key, settings, cache):
        try:
            result = qt.translate_snippet(source, api_key, settings=settings, cache=cache)
        except Exception as exc:  # noqa: BLE001 —— 背景執行緒的例外一律送回畫面上講
            self.failed.emit(request_id, source, exc)
            return
        self.finished.emit(request_id, source, result)


class QuickLookupDialog(QDialog):
    """即時查譯面板。`player` 是②的播放器（這次開啟的設定、字幕都在那邊），`cue_panel` 是②的字幕清單。"""

    def __init__(self, player, cue_panel=None, parent=None):
        super().__init__(parent)
        self.player = player
        self.cue_panel = cue_panel
        self.config_data = player._config
        self.settings = qt.resolve_quicktranslate_settings(self.config_data)
        self.cache = qt.TranslationCache(capacity=self.settings["cache_size"])
        self.vocab = ql.load_vocab(vocab_path())
        self._request_id = 0
        self._last_success_source = None
        self._failures = 0
        self._last_selection = ""   # 最近一次在文字框裡選到的字（按鈕會搶走焦點，所以先記著）
        self._watching = False
        self._pending_widget = None
        self.setWindowTitle(TITLE)
        self.setModal(False)
        prefs = self.config_data.get("quicktranslate") or {}

        layout = QVBoxLayout(self)
        hint = QLabel(HINT)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        # ----- 查譯 -----
        page = QWidget()
        page_layout = QVBoxLayout(page)
        src_box = QGroupBox("原文")
        self.src_text = QPlainTextEdit()
        self.src_text.setReadOnly(True)
        self.src_text.setMaximumHeight(80)
        QVBoxLayout(src_box).addWidget(self.src_text)
        page_layout.addWidget(src_box)
        self.dst_box = QGroupBox(ql.dst_label(self.settings["target_language"]))
        self.dst_text = QPlainTextEdit()
        self.dst_text.setReadOnly(True)
        QVBoxLayout(self.dst_box).addWidget(self.dst_text)
        page_layout.addWidget(self.dst_box, 1)
        term_box = QGroupBox("值得學的關鍵詞")
        self.term_text = QPlainTextEdit()
        self.term_text.setReadOnly(True)
        QVBoxLayout(term_box).addWidget(self.term_text)
        page_layout.addWidget(term_box, 1)
        self.status_label = QLabel(WAITING)
        self.status_label.setWordWrap(True)
        page_layout.addWidget(self.status_label)

        row = QHBoxLayout()
        row.addWidget(QLabel("複製："))
        self.copy_src_btn = QPushButton("原文")
        self.copy_dst_btn = QPushButton("譯文")
        row.addWidget(self.copy_src_btn)
        row.addWidget(self.copy_dst_btn)
        row.addStretch(1)
        page_layout.addLayout(row)

        row = QHBoxLayout()
        self.translate_btn = QPushButton("翻譯選取內容")
        self.translate_btn.setFocusPolicy(Qt.NoFocus)  # 按下去不要把焦點從文字框搶走
        self.auto_box = QCheckBox("選取後自動翻譯")
        self.auto_box.setChecked(bool(prefs.get("auto_translate", True)))
        self.explain_box = QCheckBox("附關鍵詞解說")
        self.explain_box.setChecked(self.settings["explain"])
        row.addWidget(self.translate_btn)
        row.addWidget(self.auto_box)
        row.addWidget(self.explain_box)
        row.addStretch(1)
        page_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("翻譯成："))
        self.language_box = QComboBox()
        for code, label in LANGUAGE_LABELS.items():
            self.language_box.addItem(label, code)
        at = self.language_box.findData(self.settings["target_language"])
        self.language_box.setCurrentIndex(at if at >= 0 else self.language_box.findData("zh-TW"))
        row.addWidget(self.language_box)
        self.save_vocab_box = QCheckBox("查過的存入生字本")
        self.save_vocab_box.setChecked(bool(prefs.get("save_to_vocab", True)))
        self.topmost_box = QCheckBox("視窗置頂")
        self.topmost_box.setChecked(bool(prefs.get("topmost", True)))
        row.addWidget(self.save_vocab_box)
        row.addWidget(self.topmost_box)
        row.addStretch(1)
        page_layout.addLayout(row)
        self.tabs.addTab(page, "查譯")

        # ----- 生字本 -----
        page = QWidget()
        page_layout = QVBoxLayout(page)
        vocab_hint = QLabel(VOCAB_HINT)
        vocab_hint.setWordWrap(True)
        page_layout.addWidget(vocab_hint)
        self.vocab_table = QTableWidget(0, 2)
        self.vocab_table.setHorizontalHeaderLabels(["詞句", "意思"])
        self.vocab_table.verticalHeader().setVisible(False)
        self.vocab_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.vocab_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.vocab_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        page_layout.addWidget(self.vocab_table, 1)
        row = QHBoxLayout()
        self.export_btn = QPushButton("匯出 CSV…")
        self.delete_btn = QPushButton("刪除選取")
        self.clear_btn = QPushButton("清空生字本")
        for button in (self.export_btn, self.delete_btn, self.clear_btn):
            row.addWidget(button)
        row.addStretch(1)
        page_layout.addLayout(row)
        self.vocab_status = QLabel()
        page_layout.addWidget(self.vocab_status)
        self.tabs.addTab(page, "生字本")

        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(self.settings["debounce_ms"])  # 一般版同一個去抖動延遲
        self.debounce.timeout.connect(self._on_debounce)
        self.worker = LookupWorker(self)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.translate_btn.clicked.connect(lambda _c=False: self.translate_selection())
        self.copy_src_btn.clicked.connect(lambda _c=False: self.copy("src"))
        self.copy_dst_btn.clicked.connect(lambda _c=False: self.copy("dst"))
        self.auto_box.toggled.connect(lambda _on: self._write_settings())
        self.explain_box.toggled.connect(lambda _on: self._write_settings())
        self.save_vocab_box.toggled.connect(lambda _on: self._write_settings())
        self.language_box.currentIndexChanged.connect(lambda _i: self._on_language_changed())
        self.topmost_box.toggled.connect(lambda _on: self._apply_topmost())
        self.export_btn.clicked.connect(lambda _c=False: self.export_vocab())
        self.delete_btn.clicked.connect(lambda _c=False: self.delete_vocab())
        self.clear_btn.clicked.connect(lambda _c=False: self.clear_vocab())
        self.vocab_table.itemSelectionChanged.connect(self._refresh_vocab_buttons)

        self._has_key = None
        self._apply_topmost(write=False)
        self._refresh_key_state(force=True)
        self._refresh_vocab()
        self.resize(560, 720)

    # ----- 顯示／收起 -----
    def open(self):  # noqa: A003 —— 跟 QDialog.open 同名：這裡是「打開面板」
        """打開（或從收起來的狀態原地打開）：重讀金鑰與生字本，開始看選取。"""
        self.vocab = ql.load_vocab(vocab_path())
        self._refresh_vocab()
        self._refresh_key_state()
        if not self._watching:
            QApplication.instance().installEventFilter(self)
            self._watching = True
        self.show()
        self.raise_()
        self.activateWindow()

    def hideEvent(self, event):  # noqa: N802 —— 收起來：不再看選取（選字不會觸發）
        if self._watching:
            QApplication.instance().removeEventFilter(self)
            self._watching = False
        self.debounce.stop()
        super().hideEvent(event)

    def watching(self):
        return self._watching

    # ----- 設定 -----
    def current_settings(self):
        settings = dict(self.settings)
        settings["target_language"] = self.language_box.currentData()
        settings["explain"] = self.explain_box.isChecked()
        return settings

    def _write_settings(self):
        """寫進這次開啟的設定（quicktranslate；別的項目留著）。不寫 config.json。"""
        data = dict(self.config_data.get("quicktranslate") or {})
        data.update({"target_language": self.language_box.currentData(), "explain": self.explain_box.isChecked(),
                     "auto_translate": self.auto_box.isChecked(), "save_to_vocab": self.save_vocab_box.isChecked(),
                     "topmost": self.topmost_box.isChecked()})
        self.config_data["quicktranslate"] = data

    def _on_language_changed(self):
        self.dst_box.setTitle(ql.dst_label(self.language_box.currentData()))
        self._write_settings()

    def _apply_topmost(self, write=True):
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.topmost_box.isChecked())
        if visible:
            self.show()  # 換 flag 會把視窗收起來
        if write:
            self._write_settings()

    def api_key(self):
        """每次要送之前重讀：一般版填好金鑰、這次開啟的設定換了就跟著走。"""
        return str((self.config_data.get("transcription") or {}).get("api_key") or "").strip()

    def _refresh_key_state(self, force=False):
        has_key = bool(self.api_key())
        if not force and has_key == self._has_key:
            return
        self._has_key = has_key
        self.auto_box.setEnabled(has_key)
        if has_key:
            self._show(src="", dst=INITIAL, terms="", status=WAITING)
        else:
            self._show(src="", dst=NOKEY_BODY, terms="", status=NOKEY_STATUS)

    def _show(self, src=None, dst=None, terms=None, status=None):
        for widget, text in ((self.src_text, src), (self.dst_text, dst), (self.term_text, terms)):
            if text is not None:
                widget.setPlainText(text)
        if status is not None:
            self.status_label.setText(status)

    # ----- 觸發 -----
    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() in (QEvent.MouseButtonRelease, QEvent.KeyRelease):
            widget = text_widget_of(obj) or text_widget_of(QApplication.focusWidget())
            if widget is not None and widget.window() is not self:  # 面板自己的框不算
                text = selected_text_of(widget)
                if text.strip():
                    self._last_selection = text
                    self._pending_widget = widget
                    if self.auto_box.isChecked() and self.auto_box.isEnabled():
                        self.debounce.start()
        return False

    def _on_debounce(self):
        if not self.auto_box.isChecked() or not self.api_key():
            return  # 沒有金鑰：靜默略過（狀態列已經寫了）
        widget, self._pending_widget = self._pending_widget, None
        try:
            text = selected_text_of(widget) if widget is not None else ""
        except RuntimeError:  # 框在去抖動期間被關掉了
            text = ""
        self.submit(text, manual=False)  # 去抖動期間取消選取：空字串，submit 不送

    def translate_selection(self):
        """〔翻譯選取內容〕：最近選到的字；沒有就翻②字幕清單選中的那一句。"""
        self._refresh_key_state()
        if not self.api_key():
            self.status_label.setText(NOKEY_STATUS)
            return False
        text = self._last_selection
        if not text.strip() and self.cue_panel is not None:
            index = self.cue_panel.selected_index()
            if index is not None and 0 <= index < len(self.player.cues):
                text = str(self.player.cues[index].get("text") or "")
        if not text.strip():
            self.status_label.setText(NOTHING_SELECTED)
            return False
        return self.submit(text, manual=True)

    def submit(self, raw_text, manual):
        """送出一段文字（快取命中直接顯示；沒命中才在背景送 OpenAI）。回傳有沒有開始送或顯示快取。"""
        settings = self.current_settings()
        source = qt.normalize_snippet(raw_text)
        if not source:
            if manual:
                self.status_label.setText(NOTHING_SELECTED)
            return False
        if st.is_secret(source):  # 所有路徑都經過這裡：寧可漏翻、不可誤送
            self.status_label.setText(SECRET_BLOCKED)
            return False
        if not qt.looks_translatable(source, settings):
            self.status_label.setText(ql.classify_skip_reason(source, settings))
            return False
        if not manual and source == self._last_success_source:
            return False  # 跟上次翻好的一樣：連快取都不查
        hit = self.cache.get(source, settings["target_language"], settings["explain"])
        if hit is not None:
            result = dict(hit, cached=True)
            self._last_success_source = source
            self._failures = 0
            self._show_result(result, source)
            return True
        api_key = self.api_key()
        if not api_key:
            self.status_label.setText(NOKEY_STATUS)
            return False
        self._show(src=source, dst="", terms="", status=LOADING)
        self._request_id += 1
        self.worker.start(self._request_id, source, api_key, settings, self.cache)
        return True

    def _on_finished(self, request_id, source, result):
        if request_id != self._request_id:
            return  # 已經有更新的選取取代了它
        self._last_success_source = source
        self._failures = 0
        self._show_result(result, source)

    def _on_failed(self, request_id, source, exc):
        if request_id != self._request_id:
            return
        reason = str(exc).strip()
        reason = reason.splitlines()[0] if reason else "未知錯誤"
        self._failures += 1
        self.status_label.setText(f"翻譯失敗：{reason}。稍後選取同一段文字、或按「翻譯選取內容」重試。")
        if self._failures >= FAILURE_LIMIT:
            self._failures = 0
            if self.auto_box.isChecked():
                self.auto_box.setChecked(False)
                self.status_label.setText(AUTO_PAUSED)

    def _show_result(self, result, source):
        terms = result.get("terms") or []
        if terms:
            term_text = "\n".join(f"・「{t['word']}」：{t['meaning']}" for t in terms)
        elif not self.explain_box.isChecked():
            term_text = EXPLAIN_OFF
        else:
            term_text = NO_TERMS
        saved = False
        if terms and self.save_vocab_box.isChecked():
            self.vocab, saved = ql.add_vocab_terms(self.vocab, terms)
            if saved:
                ql.save_vocab(self.vocab, vocab_path())
                self._refresh_vocab()
        status = CACHED if result.get("cached") else DONE_SAVED if saved else DONE
        self._show(src=result.get("source", source), dst=result.get("translation", ""), terms=term_text,
                   status=status)

    # ----- 複製 -----
    def copy(self, which):
        widget = self.src_text if which == "src" else self.dst_text
        text = widget.toPlainText().strip()
        if not text or text in (INITIAL, NOKEY_BODY):
            self.status_label.setText(NOTHING_TO_COPY)
            return False
        QApplication.clipboard().setText(text)
        self.status_label.setText(f"已複製{'原文' if which == 'src' else '譯文'}。")
        return True

    # ----- 生字本 -----
    def _refresh_vocab(self):
        self.vocab_table.setRowCount(len(self.vocab))
        for row, entry in enumerate(self.vocab):
            self.vocab_table.setItem(row, 0, QTableWidgetItem(entry["word"]))
            self.vocab_table.setItem(row, 1, QTableWidgetItem(entry["meaning"]))
        self.vocab_status.setText(ql.vocab_status_text(len(self.vocab)))
        self._refresh_vocab_buttons()

    def _refresh_vocab_buttons(self):
        has = bool(self.vocab)
        self.export_btn.setEnabled(has)
        self.clear_btn.setEnabled(has)
        self.delete_btn.setEnabled(bool(self.vocab_table.selectionModel().selectedRows()))

    def _ask_clear(self, n):
        return QMessageBox.question(self, "清空生字本",
                                    f"確定刪除全部 {n} 個詞？此動作無法復原（建議先匯出 CSV 備份）。") == QMessageBox.Yes

    def _ask_export_path(self):
        path, _ = QFileDialog.getSaveFileName(self, "匯出生字本 CSV", "quicktranslate_vocab.csv", "CSV 檔 (*.csv)")
        return path

    def delete_vocab(self):
        rows = sorted({i.row() for i in self.vocab_table.selectionModel().selectedRows()})
        if not rows:
            return False
        words = {self.vocab[r]["word"] for r in rows if r < len(self.vocab)}
        self.vocab = ql.remove_vocab_words(self.vocab, words)
        ql.save_vocab(self.vocab, vocab_path())
        self._refresh_vocab()
        return True

    def clear_vocab(self):
        if not self.vocab:
            self.vocab_status.setText(ql.C22_VOCAB_EMPTY)
            return False
        if not self._ask_clear(len(self.vocab)):
            return False
        self.vocab = []
        ql.save_vocab(self.vocab, vocab_path())
        self._refresh_vocab()
        return True

    def export_vocab(self):
        if not self.vocab:
            self.vocab_status.setText(ql.C22_VOCAB_EMPTY)
            return ""
        path = self._ask_export_path()
        if not path:
            return ""
        try:
            ql.write_vocab_csv(self.vocab, path)
        except OSError as exc:
            self.vocab_status.setText(f"匯出失敗：{exc}")
            return ""
        self.vocab_status.setText(ql.C20_EXPORTED(len(self.vocab), path))
        return path
