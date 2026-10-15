# -*- coding: utf-8 -*-
"""
逐句校對（3.0 第 11 項第一階段）：②字幕頁播放器旁邊的字幕清單，邊看邊改文字。

* 清單三欄：第幾句、時間、文字（雙行字幕用「 / 」接起來顯示）。點一句＝播放器跳到那句開頭、
  時間軸選到那句；時間軸上點一句，清單也跟著選。
* 下面的編輯框改選到的那一句：按 Ctrl+Enter、點別句、或離開編輯框就套用；Esc 放回原本的。
  套用走播放器的 `set_cue_text`：畫面上、時間軸上立刻換，跟改時間同一疊復原（Ctrl+Z）。
* 改完是空的不收：編輯框放回原本的文字，下面寫原因（要整句拿掉是之後的「刪除」）。

清單只是看與選；字幕本身只有播放器那一份（`PlayerPanel.cues`），改過就照 `cuesChanged` 重畫。
"""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QPlainTextEdit, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

HINT = "選一句來改文字：改完按 Ctrl+Enter、點別句或離開編輯框就套用，Esc 放回原本的。"
EMPTY_HINT = "還沒有字幕：在播放器那邊按「載入字幕」或「開專案…」。"


def format_seconds(seconds):
    """0:02.5 這種寫法（分:秒.十分之一秒），跟播放器的時間一樣。"""
    tenths = int(round(float(seconds) * 10))
    minutes, tenths = divmod(tenths, 600)
    return f"{minutes}:{tenths // 10:02d}.{tenths % 10}"


def display_text(text):
    """清單裡一行放得下：雙行字幕用「 / 」接起來。"""
    return " / ".join(line for line in str(text).split("\n"))


class CueListPanel(QWidget):
    """逐句校對：字幕清單＋改文字的編輯框，跟播放器（PlayerPanel）綁在一起。"""

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.player = player
        self._updating = False
        self._editing = -1  # 編輯框現在改的是第幾句（-1＝沒有）
        self._from_timeline = False  # 這次選取是時間軸那邊來的：只跟著選，不跳播放頭

        self.title = QLabel("逐句校對")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["#", "時間", "字幕內容"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.editor = QPlainTextEdit()
        self.editor.setTabChangesFocus(True)
        line = self.editor.fontMetrics().lineSpacing()
        self.editor.setFixedHeight(line * 3 + 16)  # 雙行字幕放得下，多一行喘氣
        self.editor.setEnabled(False)
        self.editor.installEventFilter(self)
        self.note = QLabel(EMPTY_HINT)
        self.note.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 8, 8)
        layout.addWidget(self.title)
        # 播放器的狀態那一行（影片、字幕、改過幾處沒存）放這裡，可以折行，不會撐寬播放器
        self.info = player.take_info_label()
        layout.addWidget(self.info)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.editor)
        layout.addWidget(self.note)

        # 復原／重做／存字幕跟播放器同一套（編輯框裡的 Ctrl+Z 是編輯框自己的：還在打字時退字）
        from gui_qt.player import edit_shortcuts
        for seq, slot in edit_shortcuts(player.undo, player.redo, self.save):
            shortcut = QShortcut(seq, self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
        self.table.itemSelectionChanged.connect(self._on_selection)
        player.cuesChanged.connect(self.refresh)
        player.timeline.cueSelected.connect(self._on_timeline_cue)
        self.refresh()

    # ---- 對外 ----------------------------------------------------------

    def refresh(self):
        """照播放器目前的字幕重畫清單；選取與編輯中的那句留著（還在的話）。"""
        cues = self.player.cues
        keep = self.selected_index()
        self._updating = True
        try:
            self.table.setRowCount(len(cues))
            for row, cue in enumerate(cues):
                values = (str(row + 1), f"{format_seconds(cue['start'])} → {format_seconds(cue['end'])}",
                          display_text(cue.get("text", "")))
                for col, value in enumerate(values):
                    item = self.table.item(row, col)
                    if item is None:
                        item = QTableWidgetItem()
                        if col < 2:
                            item.setTextAlignment(Qt.AlignCenter)
                        self.table.setItem(row, col, item)
                    item.setText(value)
                    item.setToolTip(cue.get("text", "") if col == 2 else "")
            if 0 <= keep < len(cues):
                self.table.selectRow(keep)
            else:
                self.table.clearSelection()
        finally:
            self._updating = False
        self._load_editor(self.selected_index())

    def selected_index(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return rows[0].row() if rows else -1

    def select(self, index):
        """選第 index 句（跟使用者點一樣：播放器跳過去、時間軸選到）。"""
        self.table.selectRow(index)

    def commit(self):
        """把編輯框的文字套用到正在改的那句。回傳是否套用（沒改、或不收時是 False）。"""
        index = self._editing
        if not 0 <= index < len(self.player.cues):
            return False
        text = self.editor.toPlainText()
        if text == self.player.cues[index].get("text", ""):
            return False
        try:
            self.player.set_cue_text(index, text)
        except ValueError as exc:
            self._load_editor(index)
            self.note.setText(f"沒有套用：{exc}，已放回原本的文字。要整句拿掉請等「刪除」功能。")
            return False
        return True

    def save(self):
        """存字幕（Ctrl+S）：編輯框裡改到一半的先套用再存。"""
        self.commit()
        return self.player.save()

    def revert(self):
        """編輯框放回原本的文字（Esc）。"""
        self._load_editor(self._editing)

    # ---- 內部 ----------------------------------------------------------

    def _load_editor(self, index):
        self._editing = index
        cues = self.player.cues
        if 0 <= index < len(cues):
            self.editor.setEnabled(True)
            self.editor.setPlainText(cues[index].get("text", ""))
            self.note.setText(f"第 {index + 1} 句。" + HINT)
        else:
            self.editor.setPlainText("")
            self.editor.setEnabled(False)
            self.note.setText(HINT if cues else EMPTY_HINT)

    def _on_selection(self):
        if self._updating:
            return
        self.commit()  # 點別句前先把改到一半的套用掉
        index = self.selected_index()
        self._load_editor(index)
        if self._from_timeline:
            return  # 時間軸上點或拖的時候播放頭由時間軸決定，這裡跳過去會蓋掉
        if 0 <= index < len(self.player.cues):
            self.player.player.setPosition(int(round(self.player.cues[index]["start"] * 1000)))
            self.player.timeline.select_cue(index, seek=False)

    def _on_timeline_cue(self, index):
        if index != self.selected_index() and 0 <= index < self.table.rowCount():
            self._from_timeline = True
            try:
                self.table.selectRow(index)
            finally:
                self._from_timeline = False

    def eventFilter(self, obj, event):  # noqa: N802 —— Qt 的命名
        if obj is self.editor:
            if event.type() == QEvent.KeyPress:
                if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
                    self.commit()
                    return True
                if event.key() == Qt.Key_Escape:
                    self.revert()
                    return True
            elif event.type() == QEvent.FocusOut:
                self.commit()
        return super().eventFilter(obj, event)
