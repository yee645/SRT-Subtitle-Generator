# -*- coding: utf-8 -*-
"""
轉寫與金鑰設定（3.0 第 11 項第三十二階段：切預設前補的缺口）：一般版左欄「轉寫設定」框搬過來。

以前 Qt 版的生成字幕、翻譯、即時查譯、批次都寫「金鑰請到一般版（不加 --qt）的『轉寫設定』填」——切成預設之前
這一塊一定要在 Qt 版裡。頁籤列右上角〔轉寫與金鑰…〕、生成字幕視窗的〔轉寫設定…〕都打開這個視窗。

* 欄位跟一般版一樣：本地模型、語言、改用 OpenAI API、重用轉錄快取、API 金鑰、本地 Python（可瀏覽）、轉寫提示。
  整理規則在 `subtitle/transcribecfg.clean_transcription`（同一般版）。
* **金鑰**：輸入框預設遮住（●），〔顯示〕才看得到全文；旁邊寫金鑰存在哪裡（config.json，跟一般版一樣沒加密）、
  也用在翻譯字幕與即時查譯。
* 最下面一行照現在的勾選講**生成字幕會送什麼出去**（本地 Whisper 什麼都不送；OpenAI 模式送聲音、有提示詞時
  提示詞也送、照用量收費）。
* 按〔套用〕才寫進這次開啟的設定（`player._config["transcription"]`，關掉 Qt 版時存回 config.json）；
  〔取消〕什麼都不改。套用之後，生成、翻譯、即時查譯、批次下一次用的就是這組。
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout,
)

from subtitle import transcribecfg as tc
from subtitle.transcriber import LANGUAGE_LABELS

PYTHON_NOTE = "留空則自動偵測；指向已安裝 openai-whisper 的 python.exe 即可使用本地轉錄。"
PROMPT_NOTE = ("可填入常出現的專有名詞、人名或易聽錯的詞彙（以空白或逗號分隔），用於導正辨識結果。"
               "「文字稿對齊」也會一併使用。")


class TranscriptionDialog(QDialog):
    """轉寫與金鑰設定。cfg＝這次開啟的設定（主視窗的 config_data）。"""

    applied = Signal(str)  # 套用後的一句話（主視窗狀態列用）

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setModal(False)
        self.setWindowTitle("轉寫與金鑰設定")
        self.cfg = cfg
        self.model_box = QComboBox()
        self.model_box.addItems(list(tc.MODELS))
        self.language_box = QComboBox()
        self.language_box.setEditable(True)
        for code in tc.LANGUAGES:
            self.language_box.addItem(f"{code}（{LANGUAGE_LABELS.get(code, code)}）", code)
        self.use_api_box = QCheckBox("改用 OpenAI API")
        self.use_cache_box = QCheckBox("重用轉錄快取（同一支影片、同樣設定不必重跑辨識）")
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("sk-…")
        self.show_key_btn = QPushButton("顯示")
        self.show_key_btn.setCheckable(True)
        self.key_note = QLabel(f"{tc.KEY_STORED}{tc.KEY_USES}")
        self.key_note.setWordWrap(True)
        self.python_edit = QLineEdit()
        self.python_btn = QPushButton("瀏覽…")
        self.python_note = QLabel(PYTHON_NOTE)
        self.python_note.setWordWrap(True)
        self.prompt_edit = QLineEdit()
        self.prompt_note = QLabel(PROMPT_NOTE)
        self.prompt_note.setWordWrap(True)
        self.sends = QLabel()
        self.sends.setWordWrap(True)
        self.apply_btn = QPushButton("套用")
        self.cancel_btn = QPushButton("取消")

        form = QFormLayout()
        form.addRow("本地模型", self.model_box)
        form.addRow("語言", self.language_box)
        form.addRow("", self.use_api_box)
        form.addRow("", self.use_cache_box)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(self.show_key_btn)
        form.addRow("API 金鑰", key_row)
        form.addRow("", self.key_note)
        python_row = QHBoxLayout()
        python_row.addWidget(self.python_edit, 1)
        python_row.addWidget(self.python_btn)
        form.addRow("本地 Python", python_row)
        form.addRow("", self.python_note)
        form.addRow("轉寫提示", self.prompt_edit)
        form.addRow("", self.prompt_note)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.apply_btn)
        buttons.addWidget(self.cancel_btn)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.sends)
        layout.addLayout(buttons)
        self.setMinimumWidth(560)
        for button in (self.show_key_btn, self.python_btn, self.apply_btn, self.cancel_btn):
            button.setAutoDefault(False)

        self.show_key_btn.toggled.connect(self._toggle_key)
        self.python_btn.clicked.connect(lambda _c=False: self.choose_python())
        self.apply_btn.clicked.connect(lambda _c=False: self.apply())
        self.cancel_btn.clicked.connect(self.reject)
        self.use_api_box.toggled.connect(self.refresh)
        self.key_edit.textChanged.connect(self.refresh)
        self.prompt_edit.textChanged.connect(self.refresh)
        self.reload()

    # ---- 對外 ----------------------------------------------------------

    def reload(self):
        """照這次開啟的設定擺好每一格（打開時呼叫）；金鑰回到遮住。"""
        cfg = tc.clean_transcription(self.cfg.get("transcription"))
        self.model_box.setCurrentText(cfg["model"])
        index = self.language_box.findData(cfg["language"])
        if index >= 0:
            self.language_box.setCurrentIndex(index)
        else:
            self.language_box.setEditText(cfg["language"])
        self.use_api_box.setChecked(cfg["use_api"])
        self.use_cache_box.setChecked(cfg["use_cache"])
        self.key_edit.setText(cfg["api_key"])
        self.show_key_btn.setChecked(False)
        self.python_edit.setText(cfg["python_path"])
        self.prompt_edit.setText(cfg["prompt"])
        self.refresh()

    def values(self):
        """畫面上的設定（整理過；其他鍵照原本的留著）。"""
        old = dict(self.cfg.get("transcription") or {})
        raw = dict(old)
        raw.update({
            "model": self.model_box.currentText(),
            "language": self.language(),
            "use_api": self.use_api_box.isChecked(),
            "use_cache": self.use_cache_box.isChecked(),
            "api_key": self.key_edit.text(),
            "python_path": self.python_edit.text(),
            "prompt": self.prompt_edit.text(),
        })
        return tc.clean_transcription(raw, old)

    def language(self):
        """選的語言代碼（自己打的就照打的）。"""
        text = self.language_box.currentText()
        index = self.language_box.findText(text)
        if index >= 0:
            return self.language_box.itemData(index)
        return text.split("（")[0].strip()

    def apply(self):
        """寫進這次開啟的設定（關掉 Qt 版時存回 config.json）。"""
        values = self.values()
        self.cfg["transcription"] = values
        message = ("轉寫設定已套用：" + ("OpenAI API" if values["use_api"] else f"本地 Whisper（{values['model']}）")
                   + f"，金鑰 {tc.mask_key(values['api_key'])}。")
        self.applied.emit(message)
        self.accept()
        return values

    def refresh(self, *_args):
        self.sends.setText(tc.sends_text(self.values()))

    def choose_python(self):
        path = self._ask_python()
        if path:
            self.python_edit.setText(path)
        return path

    # ---- 內部 ----------------------------------------------------------

    def _toggle_key(self, shown):
        self.key_edit.setEchoMode(QLineEdit.Normal if shown else QLineEdit.Password)
        self.show_key_btn.setText("隱藏" if shown else "顯示")

    def _ask_python(self):
        """選 python.exe；取消回空字串。測試換掉這一個。"""
        path, _f = QFileDialog.getOpenFileName(self, "選擇已安裝 whisper 的 python.exe", "",
                                               "Python 執行檔 (python*.exe python*);;所有檔案 (*)")
        return path
