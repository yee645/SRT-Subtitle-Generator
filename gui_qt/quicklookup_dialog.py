# -*- coding: utf-8 -*-
"""
即時查譯（3.0 第 11 項第二十三階段）：一般版 `gui/quicktranslate_panel.py` 的「查譯」與「生字本」兩頁。

在本程式任何文字框（②的逐句校對、①的搜尋框…）選取一段外文，鬆開滑鼠（或放開 Shift 選字的鍵）
就翻譯；也可以按〔翻譯選取內容〕，沒選字時翻②字幕清單選中的那一句。核心同一套：
`subtitle/quicktranslate.py`（正規化、值不值得送、快取、呼叫 OpenAI）、`subtitle/screentranslate.is_secret`
（像密碼的不送）、`subtitle/quicklookup.py`（生字本、略過原因）。

**會送出去的**：只有選取的那一段文字，送到 OpenAI（用「轉寫與金鑰」的金鑰——跟一般版「轉寫設定」同一把，照用量收費），面板最上面
寫明。不送：檔名、整份字幕、其他檔案；像密碼或金鑰的內容、密碼欄位裡的字都不送（寧可漏翻、不可誤送）。
面板收起來時選字不會觸發。

跟一般版不同的地方：
- 觸發方式：Tk 聽 `<<Selection>>` 再等滑鼠放開；Qt 在整個程式的事件裡看「放開滑鼠／放開按鍵時，
  那個文字框（或焦點所在的文字框）有沒有選取」，面板自己的框不算，去抖動一樣用 `debounce_ms`。密碼欄位（QLineEdit 不是一般顯示模式）略過。
- 沒有金鑰時的說明指向一般版的「轉寫設定」（Qt 預覽版還沒有填金鑰的地方）。
- 設定寫進這次開啟的設定（關掉 Qt 版時只把改過的區塊存回 config.json）。**生字本照樣寫**：它是查譯的結果、
  不是設定，跟一般版存在同一個檔（config.json 旁邊的 quicktranslate_vocab.json），兩版看到的是同一本。

第二十四階段加上：
- **朗讀**原文／譯文（不需要金鑰、不送出去，用這台電腦的語音引擎；核心 `subtitle/speech.py` 原封沿用，
  一次只念一句、太長截掉並講截掉幾個字、念完或失敗講一句）。一般版關掉面板不會停止朗讀，這裡一樣；
  關主視窗才停。
- **監聽剪貼簿**（複製即翻譯，預設關）：在任何軟體複製外文就翻。會送出去的仍然只有那段文字；過
  `subtitle/clipwatch.py` 的篩子——密碼、金鑰、路徑、網址、程式碼不送，並講為什麼沒翻。勾選當下剪貼簿裡
  原本的東西不算；自己按〔複製〕放進去的不算；面板收起來就停；沒金鑰時灰掉。跟一般版一樣定時看
  （`poll_ms`），不用 `QClipboard.dataChanged`——macOS 上別的程式的複製不一定會發這個訊號。

第二十五階段加上 **框選螢幕翻譯**：〔框選螢幕翻譯〕→ 面板先收起來 → 截整個螢幕（`QScreen.grabWindow`，只放記憶體）
→ 鋪著這張截圖的框選層（`gui_qt/region_overlay.py`，Esc／右鍵取消）→ 從同一張圖裁出框的那塊 → 背景交給原封不動的
`screentranslate.capture_and_recognize`（在這台電腦用 tesseract 辨識，**畫面不送出去**，截圖用完就刪）→ 辨識結果
放進原文框（可以改錯字）→ 照 `screentranslate.decide` 決定：讀不到字、像密碼就擋下（仍可朗讀、複製）；其餘等使用者
按〔翻譯辨識結果〕才送（送之前用 `may_send` 對改過的原文再檢查一次）；設定裡打開了自動送出、又辨識得清楚才直接送。
**會送出去的**：只有使用者確認後的那段辨識文字（送到 OpenAI）。沒裝 tesseract：直接打開主視窗的
「安裝文字辨識」視窗（第二十九階段，跟一般版一樣）。

第二十六階段加上 **全域熱鍵**（預設關，預設組合鍵 Ctrl+Alt+F8）：按了就叫出框選（面板沒開也行）。核心
`subtitle/hotkey.py` 沿用（三種狀態、每一種都講一句話）；Qt 的接線在 `gui_qt/hotkey_qt.py`——Windows 用
`RegisterHotKey`＋原生事件過濾器（沒有實測），其他平台退成只在本程式視窗內有效（`QShortcut`）。熱鍵本身不送任何東西出去。
關掉面板熱鍵照樣有效（跟一般版一樣）；關主視窗才取消註冊。
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
from subtitle import clipwatch as cw
from subtitle import hotkey as hk
from subtitle import quicklookup as ql
from subtitle import quicktranslate as qt
from subtitle import screentranslate as st
from subtitle import ocrengine
from subtitle import screencap
from subtitle import speech
from subtitle.translator import LANGUAGE_LABELS

TITLE = "即時查譯（選字即翻）"
CLIP_HINT = ("開啟後，在任何軟體按 Ctrl+C 複製外文就會自動翻譯——本程式之外也能用。"
             "會送出去的只有複製的那段文字（送到 OpenAI）；密碼、金鑰、檔案路徑、網址與程式碼會自動跳過，不會送出。"
             "關掉這個面板就停止監聽。")
NEED_TESSERACT = ("螢幕翻譯要先安裝文字辨識引擎（tesseract）：已經打開「安裝文字辨識」視窗（也可以自行安裝後加入"
                  "系統 PATH），裝完再按一次「框選螢幕翻譯」。")
CLIP_WATCHING = "監聽中——複製外文即翻譯。"
CLIP_STOPPED = "已停止監聽。"
SPEECH_POLL_MS = 300
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
              "想啟用：到 platform.openai.com 申請金鑰，按主視窗右上角的〔轉寫與金鑰…〕貼進「API 金鑰」欄位"
              "（不必勾選「改用 OpenAI API」），再回來這裡。查譯用的是最便宜的文字模型，選一句話約千分之一美元。")
AUTO_PAUSED = "連續 3 次翻譯失敗，已先暫停自動翻譯，避免每選一次就失敗一次。問題排除後重新勾選「選取後自動翻譯」即可。"
NOTHING_SELECTED = "沒有選取內容。先選取一段文字，或點②字幕清單的一句再按此鈕。"
SECRET_BLOCKED = "這段內容看起來像密碼或金鑰，不會送去翻譯。需要的話仍可複製。"
NOTHING_TO_COPY = "還沒有可以複製的內容。"
VOCAB_HINT = ("查譯時的關鍵詞會自動收進這裡（本機保存，不佔 API 費用；跟一般版是同一本）。"
              "匯出的 CSV 前欄是詞、後欄是意思，可直接匯入 Anki 做記憶卡。")
FAILURE_LIMIT = 3
_TEXT_WIDGETS = (QLineEdit, QPlainTextEdit, QTextEdit)


def hotkey_label(combo):
    return f"熱鍵 {combo}"


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


class OcrWorker(QObject):
    """背景執行緒存圖＋辨識；結果帶著編號送回（舊的作廢）。截圖已經在主執行緒做好了。"""

    finished = Signal(int, object)
    failed = Signal(int, object)

    def start(self, ocr_id, region, image, config):
        threading.Thread(target=self._run, args=(ocr_id, region, image, config), daemon=True).start()

    def _run(self, ocr_id, region, image, config):
        from gui_qt import region_overlay as ro
        try:
            result = st.capture_and_recognize(region, config=config, capture=ro.image_capture(image))
        except Exception as exc:  # noqa: BLE001 —— 擷取與辨識的例外訊息本來就寫成使用者看得懂的話
            self.failed.emit(ocr_id, exc)
            return
        self.finished.emit(ocr_id, result)


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
        self.clip_settings = cw.resolve_clipwatch_settings(self.config_data)
        self.hotkey_settings = hk.resolve_hotkey_settings(self.config_data)
        self._hotkey = None
        self._last_clip = None        # 上一次看到的剪貼簿內容：只在「變了」時才動作
        self._speaker = None
        self.screen_settings = st.resolve_screentranslate_settings(self.config_data)
        self._ocr_busy = False
        self._ocr_id = 0
        self._overlay = None
        self._frozen = None      # 框選期間整個螢幕的截圖（只在記憶體，框完就丟）
        self._pending_grab = False  # 面板收起來了、等畫面更新完才截
        self._was_visible = True
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
        row = QHBoxLayout()
        self.screen_btn = QPushButton("框選螢幕翻譯")
        self.ocr_translate_btn = QPushButton("翻譯辨識結果")
        self.ocr_translate_btn.setEnabled(False)
        row.addWidget(self.screen_btn)
        row.addWidget(self.ocr_translate_btn)
        self.hotkey_box = QCheckBox(hotkey_label(self.hotkey_settings["combo"]))
        self.hotkey_box.setToolTip("在別的程式裡按這個組合鍵就能叫出框選（只叫出框選，不會送任何東西出去）")
        self.hotkey_box.setChecked(self.hotkey_settings["enabled"])
        row.addWidget(self.hotkey_box)
        row.addStretch(1)
        page_layout.addLayout(row)
        self.screen_status = QLabel(ql.C30_SCREEN_HINT)
        self.screen_status.setWordWrap(True)
        page_layout.addWidget(self.screen_status)
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
        row.addWidget(QLabel("朗讀："))  # 朗讀／複製不需要金鑰，像密碼被擋下來時也照樣能用
        self.speak_src_btn = QPushButton("原文")
        self.speak_dst_btn = QPushButton("譯文")
        self.speak_stop_btn = QPushButton("停止")
        for button in (self.speak_src_btn, self.speak_dst_btn, self.speak_stop_btn):
            row.addWidget(button)
        row.addSpacing(16)
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

        # 剪貼簿監聽自成一列：它決定的是「要不要讀你複製的每一樣東西」，跟上面「怎麼翻」不是同一層
        row = QHBoxLayout()
        self.clip_box = QCheckBox("監聽剪貼簿（複製即翻譯）")
        self.clip_box.setChecked(self.clip_settings["enabled"])
        self.clip_status = QLabel("")
        row.addWidget(self.clip_box)
        row.addWidget(self.clip_status, 1)
        page_layout.addLayout(row)
        clip_hint = QLabel(CLIP_HINT)
        clip_hint.setWordWrap(True)
        page_layout.addWidget(clip_hint)
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
        self.clip_timer = QTimer(self)
        self.clip_timer.setInterval(self.clip_settings["poll_ms"])
        self.clip_timer.timeout.connect(self._poll_clipboard)
        self.speech_timer = QTimer(self)
        self.speech_timer.setInterval(SPEECH_POLL_MS)
        self.speech_timer.timeout.connect(self._poll_speech)
        self.ocr_worker = OcrWorker(self)
        self.ocr_worker.finished.connect(self._on_ocr_finished)
        self.ocr_worker.failed.connect(self._on_ocr_failed)
        self.screen_btn.clicked.connect(lambda _c=False: self.start_screen_capture())
        self.hotkey_box.toggled.connect(lambda _on: self._on_hotkey_toggled())
        self.ocr_translate_btn.clicked.connect(lambda _c=False: self.translate_ocr())
        self.worker = LookupWorker(self)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.translate_btn.clicked.connect(lambda _c=False: self.translate_selection())
        self.speak_src_btn.clicked.connect(lambda _c=False: self.speak("src"))
        self.speak_dst_btn.clicked.connect(lambda _c=False: self.speak("dst"))
        self.speak_stop_btn.clicked.connect(lambda _c=False: self.stop_speaking())
        self.clip_box.toggled.connect(lambda _on: self._on_clip_toggled())
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
        if self.hotkey_box.isChecked():
            self.enable_hotkey()

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
        if self.clip_box.isChecked() and self.clip_box.isEnabled():
            self._start_clipwatch()  # 勾選狀態留著：下次打開自動恢復
        self.raise_()
        self.activateWindow()

    def hideEvent(self, event):  # noqa: N802 —— 收起來：不再看選取（選字不會觸發）
        if self._watching:
            QApplication.instance().removeEventFilter(self)
            self._watching = False
        self.debounce.stop()
        self._stop_clipwatch()  # 收起來就別再讀剪貼簿（勾選留著）；朗讀不停，跟一般版一樣
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
        """寫進這次開啟的設定（quicktranslate；別的項目留著）。關掉 Qt 版時存回 config.json。"""
        data = dict(self.config_data.get("quicktranslate") or {})
        data.update({"target_language": self.language_box.currentData(), "explain": self.explain_box.isChecked(),
                     "auto_translate": self.auto_box.isChecked(), "save_to_vocab": self.save_vocab_box.isChecked(),
                     "topmost": self.topmost_box.isChecked()})
        self.config_data["quicktranslate"] = data
        clip = dict(self.config_data.get("clipwatch") or {})
        clip.update({"enabled": self.clip_box.isChecked(), "poll_ms": self.clip_settings["poll_ms"],
                     "skip_secrets": self.clip_settings["skip_secrets"], "skip_code": self.clip_settings["skip_code"],
                     "skip_paths": self.clip_settings["skip_paths"]})
        self.config_data["clipwatch"] = clip

    def _on_language_changed(self):
        self.dst_box.setTitle(ql.dst_label(self.language_box.currentData()))
        self._write_settings()

    def _apply_topmost(self, write=True):
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.topmost_box.isChecked())
        if visible:
            self.open()  # 換 flag 會把視窗收起來（hideEvent 停了看選取與監聽）：照「打開」的路重新開始
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
        self.clip_box.setEnabled(has_key)
        if not has_key:  # 沒有金鑰時不讓它空轉讀剪貼簿
            self._stop_clipwatch()
            self.clip_status.setText("")
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
        self.src_text.setReadOnly(True)  # 辨識結果翻好了：原文框回到唯讀
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
        self._last_clip = text  # 自己放進去的不要被監聽當成新複製的再翻一次
        self.status_label.setText(f"已複製{'原文' if which == 'src' else '譯文'}。")
        return True

    # ----- 剪貼簿監聽 -----
    def clipwatching(self):
        return self.clip_timer.isActive()

    def _on_clip_toggled(self):
        if self.clip_box.isChecked():
            if self.isVisible():
                self._start_clipwatch()
        else:
            self._stop_clipwatch()
            self.clip_status.setText(CLIP_STOPPED)
        self._write_settings()

    def _start_clipwatch(self):
        """開始監聽。當下剪貼簿裡的東西先記下來、不翻（多半是稍早複製的，可能是密碼）；從下一次變動才算。"""
        if self.clip_timer.isActive():
            return
        self._last_clip = QApplication.clipboard().text()
        self.clip_status.setText(CLIP_WATCHING)
        self.clip_timer.start()

    def _stop_clipwatch(self):
        self.clip_timer.stop()

    def _poll_clipboard(self):
        """剪貼簿變了才動作；先過篩子，不送的講為什麼。"""
        if not self.clip_box.isChecked() or not self.isVisible() or not self.api_key():
            self._stop_clipwatch()
            return
        current = QApplication.clipboard().text()
        if not current or current == self._last_clip:
            return  # 圖片、檔案、空的：text() 是空字串，不算變動
        self._last_clip = current
        verdict = cw.classify_clipboard(current, self.clip_settings, self.current_settings())
        self.clip_status.setText(cw.format_skip_reason(verdict))
        if verdict["translate"]:
            self.submit(current, manual=False)

    # ----- 朗讀 -----
    def _panel_text(self, which):
        widget = self.src_text if which == "src" else self.dst_text
        text = widget.toPlainText().strip()
        return "" if text in (INITIAL, NOKEY_BODY) else text

    def _make_speaker(self, settings):
        return speech.Speaker(settings=settings)

    def speak(self, which):
        """念原文或譯文（不送出去）；一次只念一句，按第二次會先停掉前一句。"""
        text = self._panel_text(which)
        if not text:
            self.status_label.setText(ql.C34_NOTHING_TO_SPEAK)
            return False
        settings = speech.resolve_speech_settings(self.config_data)
        if not settings["enabled"]:
            self.status_label.setText(ql.C36_SPEECH_OFF)
            return False
        if self._speaker is None:
            self._speaker = self._make_speaker(settings)
        lang = st.guess_speech_lang(text) if which == "src" else self.language_box.currentData()
        try:
            dropped = self._speaker.speak(text, lang)
        except speech.SpeechError as exc:  # 沒有語音引擎時講怎麼裝
            self.status_label.setText(str(exc))
            return False
        self.status_label.setText(ql.speech_started_text("原文" if which == "src" else "譯文", dropped))
        self.speech_timer.start()
        return True

    def _poll_speech(self):
        speaker = self._speaker
        if speaker is None or speaker._proc is None:
            self.speech_timer.stop()
            return
        code = speaker.wait(timeout=0)
        if code is None:
            return  # 還在念
        self.speech_timer.stop()
        if code != 0:
            self.status_label.setText(ql.speech_failed_text(speaker.last_error or speaker._read_stderr()))
        else:
            self.status_label.setText(ql.SPEECH_DONE)

    def stop_speaking(self):
        if self._speaker is not None and self._speaker.is_speaking():
            self._speaker.stop()
            self.speech_timer.stop()
            self.status_label.setText(ql.SPEECH_STOPPED)
            return True
        return False

    # ----- 框選螢幕翻譯 -----
    def ocr_busy(self):
        return self._ocr_busy

    def _target_screen(self):
        return self.screen() or QApplication.primaryScreen()

    def _make_overlay(self, screen, background):
        from gui_qt.region_overlay import RegionOverlay
        return RegionOverlay(screen, background)

    def _grab(self, screen):
        from gui_qt.region_overlay import grab_screen
        return grab_screen(screen)

    def _open_ocr_install(self):
        """開安裝文字辨識的視窗：主視窗那一個（只建一個）；單獨用這個面板時自己建一個。"""
        host = self.parent()
        if host is not None and hasattr(host, "open_ocr_install"):
            return host.open_ocr_install()
        from gui_qt.install_dialog import TesseractInstallDialog
        if getattr(self, "_ocr_install", None) is None:
            self._ocr_install = TesseractInstallDialog(self)
        self._ocr_install.show()
        return self._ocr_install

    def start_screen_capture(self):
        """框選一塊螢幕 → 本機辨識 → 放進原文框。框之前先把面板收起來（不然面板自己會被框進去）。"""
        if self._ocr_busy:
            self.open()
            self.screen_status.setText(ql.C38_OCR_BUSY)
            return False
        if not ocrengine.tesseract_available():
            # 沒裝引擎就直接開安裝視窗（跟一般版一樣），不要讓人先框一次才被告知
            self.open()
            self.screen_status.setText(NEED_TESSERACT)
            self._open_ocr_install()
            return False
        self._ocr_busy = True
        self.screen_btn.setEnabled(False)
        self._was_visible = self.isVisible()
        screen = self._target_screen()
        self.hide()  # 先收起來、等畫面更新完再截，不然面板自己會被截進去
        from gui_qt.region_overlay import SETTLE_MS
        self._pending_grab = True
        QTimer.singleShot(SETTLE_MS, lambda: self._show_overlay(screen))
        return True

    def _show_overlay(self, screen):
        if not self._pending_grab:
            return  # 等的期間關了主視窗
        self._pending_grab = False
        self._frozen = self._grab(screen)
        self._overlay = self._make_overlay(screen, self._frozen)
        self._overlay.selected.connect(lambda region: self._on_region_selected(screen, region))
        self._overlay.cancelled.connect(self._on_region_cancelled)
        self._overlay.start()

    def _on_region_cancelled(self):
        self._overlay = None
        self._frozen = None
        self._ocr_busy = False
        self.screen_btn.setEnabled(True)
        if self._was_visible:
            self.open()
            self.screen_status.setText(ql.C32_OCR_CANCELLED)

    def _on_region_selected(self, screen, region):
        from gui_qt.region_overlay import crop_image
        self._overlay = None
        frozen, self._frozen = self._frozen, None
        self._ocr_id += 1
        g = screen.geometry()
        region = screencap.clamp_region(region, (g.x(), g.y(), g.width(), g.height()))
        try:
            screencap.validate_region(region, self.config_data)  # 太小（只點一下）、太大：講原因、不截
            image = crop_image(frozen, screen, region)
        except screencap.CaptureError as exc:
            self._ocr_busy = False
            self.screen_btn.setEnabled(True)
            self.open()
            self.screen_status.setText(ql.ocr_failed_text(exc))
            return
        self.open()
        self.screen_status.setText(ql.C31_OCR_RUNNING)
        self.ocr_worker.start(self._ocr_id, region, image, self.config_data)

    def _on_ocr_failed(self, ocr_id, exc):
        self._ocr_busy = False
        self.screen_btn.setEnabled(True)
        if ocr_id != self._ocr_id:
            return
        self.screen_status.setText(ql.ocr_failed_text(exc))

    def _on_ocr_finished(self, ocr_id, result):
        self._ocr_busy = False
        self.screen_btn.setEnabled(True)
        if ocr_id != self._ocr_id:
            return
        decision = st.decide(result, self.screen_settings)
        self.tabs.setCurrentIndex(0)
        self.src_text.setPlainText(decision["text"])
        self.src_text.setReadOnly(False)  # 辨識常有錯字：原文框開放修改，改好再送
        if self._has_key:
            self.dst_text.setPlainText("")
        self.term_text.setPlainText("")
        # 結論寫在按鈕下面那一行；下面的狀態清掉，免得留著上一次的「翻譯完成」讓人以為這段也翻好了
        self.screen_status.setText(st.format_status(result, decision))
        self.status_label.setText("")
        if decision["action"] == st.ACTION_BLOCK:
            self.ocr_translate_btn.setEnabled(False)
        else:
            self.ocr_translate_btn.setEnabled(True)
            if decision["action"] == st.ACTION_SEND:
                self.translate_ocr()

    def translate_ocr(self):
        """〔翻譯辨識結果〕：以使用者**改過之後**的原文為準再檢查一次才送。"""
        text = self.src_text.toPlainText()
        ok, why = st.may_send(text)
        if not ok:
            self.status_label.setText(why)
            return False
        if not self.api_key():
            self.status_label.setText(NOKEY_STATUS)
            return False
        self.ocr_translate_btn.setEnabled(False)
        return self.submit(text, manual=True)

    # ----- 全域熱鍵 -----
    def _make_hotkey(self):
        from gui_qt.hotkey_qt import QtHotkey
        return QtHotkey(self.parent() or self)  # 掛在主視窗上：面板收起來也有效

    def hotkey_status(self):
        return self._hotkey.status if self._hotkey is not None else "off"

    def enable_hotkey(self):
        """啟用熱鍵，回傳落在哪一種狀態（global／window-only／unavailable）；每一種都在框選那一列講一句。"""
        if self._hotkey is None:
            self._hotkey = self._make_hotkey()
            self._hotkey.triggered.connect(self._on_hotkey_pressed)
        try:
            status = self._hotkey.enable(self.hotkey_settings["combo"])
        except hk.HotkeyError as exc:
            self.screen_status.setText(str(exc))
            return "unavailable"
        self.screen_status.setText(self._hotkey.describe())
        return status

    def disable_hotkey(self):
        if self._hotkey is not None:
            self._hotkey.disable()

    def _on_hotkey_toggled(self):
        if self.hotkey_box.isChecked():
            self.enable_hotkey()
        else:
            self.disable_hotkey()
            self.screen_status.setText(f"熱鍵 {self.hotkey_settings['combo']} 已關閉。")
        data = dict(self.config_data.get("hotkey") or {})  # 只記在這次開啟的設定
        data.update({"enabled": self.hotkey_box.isChecked(), "combo": self.hotkey_settings["combo"]})
        self.config_data["hotkey"] = data

    def _on_hotkey_pressed(self):
        self.start_screen_capture()  # 面板沒開也行：框完才叫出來，取消就不叫出來

    def shutdown(self):
        """關主視窗：收起面板（不再看選取）、停朗讀、停監聽、收掉框選層。Qt 收主視窗時不會自己把它收起來。"""
        self._was_visible = False  # 框選中（或正要截圖）關主視窗：取消，面板不再叫出來
        if self._overlay is not None:
            self._overlay.cancel()
        elif self._pending_grab:
            self._pending_grab = False
            self._ocr_busy = False
        self.hide()  # hideEvent 會停監聽剪貼簿
        self.disable_hotkey()  # Windows 上要取消註冊，不然程式關了那個組合鍵還被佔著
        self.speech_timer.stop()
        if self._speaker is not None:
            self._speaker.stop()

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
