# -*- coding: utf-8 -*-
"""
自動修正詞庫（3.0 第 11 項第三十三階段）：一般版「尋找取代」視窗下面那一框搬過來。

語音辨識的慣性錯字（人名、產品名、同音字）修一次就存成規則，之後每次「生成字幕…」自動套用（`pipeline.generate_cues`
裡的 `textedit.apply_corrections`，兩版共用，生成完會說修了幾處）。

* ②逐句校對的「尋找取代」多兩顆：〔存為自動修正〕把現在填的「尋找／換成／區分大小寫」存成一條（同一個「尋找」
  再存＝換掉舊的）；〔自動修正詞庫…〕打開這個小視窗看全部、刪掉用不到的。
* 規則寫進這次開啟的設定（`player._config["corrections"]`），關掉 Qt 版時存回 config.json；一般版是同一本。
* 存規則不會動到現在的字幕——要修現在這份，照樣按〔全部取代〕。

增刪規則在 `subtitle/correctionrules.py`。
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QMessageBox, QPushButton, QVBoxLayout

from subtitle import correctionrules as cr
from subtitle.textedit import normalize_correction_rules

NOTE = ("每次「生成字幕…」完成後，照這裡的規則自動改掉慣性錯字（人名、產品名、同音字），生成視窗會說改了幾處。"
        "新增規則：在「尋找取代」填好要找的字與換成什麼，按〔存為自動修正〕。存規則不會動到現在的字幕。")
EMPTY = "還沒有規則。"


class CorrectionsDialog(QDialog):
    """自動修正詞庫：清單＋〔刪除選取規則〕。cfg＝這次開啟的設定。"""

    changed = Signal(str)  # 規則改了（狀態文字）

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setModal(False)
        self.setWindowTitle("自動修正詞庫")
        self.cfg = cfg
        self.list = QListWidget()
        self.list.setMinimumHeight(180)
        self.note = QLabel(NOTE)
        self.note.setWordWrap(True)
        self.count = QLabel()
        self.delete_btn = QPushButton("刪除選取規則")
        self.close_btn = QPushButton("關閉")
        buttons = QHBoxLayout()
        buttons.addWidget(self.delete_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.close_btn)
        layout = QVBoxLayout(self)
        layout.addWidget(self.note)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.count)
        layout.addLayout(buttons)
        self.setMinimumWidth(420)
        self.delete_btn.clicked.connect(lambda _c=False: self.delete_selected())
        self.close_btn.clicked.connect(self.close)
        self.list.currentRowChanged.connect(lambda _r: self._update_buttons())
        self.reload()

    def rules(self):
        return normalize_correction_rules(self.cfg.get("corrections"))

    def reload(self):
        """照設定重寫清單。"""
        rules = self.rules()
        self.list.clear()
        for rule in rules:
            self.list.addItem(cr.rule_label(rule))
        self.count.setText(f"共 {len(rules)} 條。" if rules else EMPTY)
        self._update_buttons()

    def delete_selected(self):
        """刪掉清單上選的那一條。回傳是否刪了。"""
        row = self.list.currentRow()
        rules, error = cr.delete_rule(self.cfg.get("corrections"), row if row >= 0 else None)
        if error:
            self._warn(error)
            return False
        self.cfg["corrections"] = rules
        self.reload()
        self.changed.emit("已刪除選取的規則。")
        return True

    def _update_buttons(self):
        self.delete_btn.setEnabled(self.list.currentRow() >= 0)

    def _warn(self, text):
        """提示；測試換掉這一個。"""
        QMessageBox.information(self, "提示", text)
