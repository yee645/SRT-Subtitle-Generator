# -*- coding: utf-8 -*-
"""
逐句校對（3.0 第 11 項）：②字幕頁播放器旁邊的字幕清單，邊看邊改。

第一階段：

* 清單三欄：第幾句、時間、文字（雙行字幕用「 / 」接起來顯示）。點一句＝播放器跳到那句開頭、
  時間軸選到那句；時間軸上點一句，清單也跟著選。
* 下面的編輯框改選到的那一句：按 Ctrl+Enter、點別句、或離開編輯框就套用；Esc 放回原本的。
  套用走播放器的 `set_cue_text`：畫面上、時間軸上立刻換，跟改時間同一疊復原（Ctrl+Z）。
* 改完是空的不收：編輯框放回原本的文字，下面寫原因（要整句拿掉用「刪除這句」）。

第二階段（追平一般版的字幕清單）：

* 「新增一句」：放在播放頭那裡（落在某句裡面就接在那句後面，最長 2 秒，不蓋到下一句）。
  編輯框清空讓你打字，Ctrl+Enter 或離開編輯框就加進去；沒打字就不加；Esc 取消。
* 「刪除這句」（或在清單上按 Delete）：直接拿掉，Ctrl+Z 救得回來，所以不另外問。
* 「尋找取代」（Ctrl+F）：清單上方展開一列——找下一個、取代這句、全部取代；可選區分大小寫。
  全部取代整批是一步復原。取代後會變成空的那幾句不改，下面列出來（要拿掉請用刪除）。
  一般版的「自動修正詞庫」要寫設定檔，預覽版不碰設定檔，所以這裡先不做。

第三階段：「翻譯字幕…」打開翻譯的小視窗（gui_qt/translate_dialog.py）：送出前說會送什麼、可以中途停止、
翻完整份是一步復原。

第四階段：「字幕樣式…」打開樣式的小視窗（gui_qt/style_panel.py），改了播放器上立刻看得到。

清單只是看與選；字幕本身只有播放器那一份（`PlayerPanel.cues`），改過就照 `cuesChanged` 重畫。
"""
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from subtitle import cueedit
from subtitle.textedit import count_occurrences, find_in_cues

HINT = "選一句來改文字：改完按 Ctrl+Enter、點別句或離開編輯框就套用，Esc 放回原本的。"
EMPTY_HINT = "還沒有字幕：在播放器那邊按「載入字幕」或「開專案…」，或按「新增一句」自己打。"
ADD_HINT = "新的一句（{start} → {end}）：打好字按 Ctrl+Enter 或離開編輯框就加進去，Esc 取消。"


def format_seconds(seconds):
    """0:02.5 這種寫法（分:秒.十分之一秒），跟播放器的時間一樣。"""
    tenths = int(round(float(seconds) * 10))
    minutes, tenths = divmod(tenths, 600)
    return f"{minutes}:{tenths // 10:02d}.{tenths % 10}"


def display_text(text):
    """清單裡一行放得下：雙行字幕用「 / 」接起來。"""
    return " / ".join(line for line in str(text).split("\n"))


def numbers(indices):
    """[0, 3] → 「第 1、4 句」。"""
    return "第 " + "、".join(str(i + 1) for i in indices) + " 句"


class CueListPanel(QWidget):
    """逐句校對：字幕清單＋改文字的編輯框，跟播放器（PlayerPanel）綁在一起。"""

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.player = player
        self._updating = False
        self._editing = -1  # 編輯框現在改的是第幾句（-1＝沒有）
        self._adding = None  # 「新增一句」打字中：新的那句從幾秒開始（None＝不是在新增）
        self._from_timeline = False  # 這次選取是時間軸那邊來的：只跟著選，不跳播放頭

        self.title = QLabel("逐句校對")
        self.add_btn = QPushButton("新增一句")
        self.add_btn.setToolTip("在播放頭那裡加一句（落在某句裡面就接在那句後面）")
        self.delete_btn = QPushButton("刪除這句")
        self.delete_btn.setToolTip("拿掉選到的那句（Delete；Ctrl+Z 救得回來）")
        self.find_btn = QPushButton("尋找取代")
        self.find_btn.setCheckable(True)
        self.find_btn.setToolTip("Ctrl+F")
        self.translate_btn = QPushButton("翻譯字幕…")
        self.translate_btn.setToolTip("用 OpenAI 把整份字幕翻成別的語言（送出前會先說送什麼）")
        self.translate_dialog = None
        self.style_btn = QPushButton("字幕樣式…")
        self.style_btn.setToolTip("字型、字級、顏色、上下位置、重點字、動態字幕；播放器上立刻看得到")
        self.style_dialog = None
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        for button in (self.add_btn, self.delete_btn, self.find_btn, self.translate_btn, self.style_btn):
            buttons.addWidget(button)
        buttons.addStretch(1)

        self.find_bar = QWidget()
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("要找的字")
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("換成（可以留空＝刪掉那幾個字）")
        self.case_box = QCheckBox("區分大小寫（英文）")
        self.find_next_btn = QPushButton("找下一個")
        self.replace_one_btn = QPushButton("取代這句")
        self.replace_all_btn = QPushButton("全部取代")
        grid = QGridLayout(self.find_bar)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.addWidget(QLabel("尋找"), 0, 0)
        grid.addWidget(self.find_edit, 0, 1, 1, 3)
        grid.addWidget(QLabel("取代"), 1, 0)
        grid.addWidget(self.replace_edit, 1, 1, 1, 3)
        grid.addWidget(self.case_box, 2, 0, 1, 4)
        grid.addWidget(self.find_next_btn, 3, 1)
        grid.addWidget(self.replace_one_btn, 3, 2)
        grid.addWidget(self.replace_all_btn, 3, 3)
        self.find_bar.setVisible(False)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["#", "時間", "字幕內容"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setWordWrap(False)
        self.table.installEventFilter(self)
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
        layout.addLayout(buttons)
        layout.addWidget(self.find_bar)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.editor)
        layout.addWidget(self.note)

        # 復原／重做／存字幕跟播放器同一套（編輯框裡的 Ctrl+Z 是編輯框自己的：還在打字時退字）
        from gui_qt.player import edit_shortcuts
        bindings = list(edit_shortcuts(player.undo, player.redo, self.save))
        bindings.append((QKeySequence(QKeySequence.Find), self.show_find))
        for seq, slot in bindings:
            shortcut = QShortcut(seq, self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
        self.add_btn.clicked.connect(self.start_add)
        self.delete_btn.clicked.connect(self.delete_selected)
        self.find_btn.toggled.connect(self._on_find_toggled)
        self.translate_btn.clicked.connect(self.open_translate)
        self.style_btn.clicked.connect(self.open_style)
        self.find_next_btn.clicked.connect(self.find_next)
        self.replace_one_btn.clicked.connect(self.replace_current)
        self.replace_all_btn.clicked.connect(self.replace_all)
        self.find_edit.returnPressed.connect(self.find_next)
        self.find_edit.textChanged.connect(self._update_buttons)
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
        if self._adding is None:  # 新增打字中：打到一半的字留著
            self._load_editor(self.selected_index())
        self._update_buttons()

    def selected_index(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return rows[0].row() if rows else -1

    def select(self, index):
        """選第 index 句（跟使用者點一樣：播放器跳過去、時間軸選到）。"""
        self.table.selectRow(index)

    def commit(self):
        """
        把編輯框的文字套用到正在改的那句（新增打字中就是把新的那句加進去）。
        回傳是否有改到字幕（沒改、或不收時是 False）。
        """
        if self._adding is not None:
            return self._commit_add()
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
            self.note.setText(f"沒有套用：{exc}，已放回原本的文字。要整句拿掉請按「刪除這句」。")
            return False
        return True

    def save(self):
        """存字幕（Ctrl+S）：編輯框裡改到一半的先套用再存。"""
        self.commit()
        return self.player.save()

    def revert(self):
        """編輯框放回原本的文字（Esc）；新增打字中就是取消新增。"""
        if self._adding is not None:
            self._adding = None
            self._load_editor(self.selected_index())
            self.note.setText("沒有新增。")
            return
        self._load_editor(self._editing)

    def start_add(self):
        """「新增一句」：找好播放頭那裡的空位，編輯框清空等你打字。回傳是否進入新增。"""
        self.commit()
        try:
            _position, start, end = self.player.new_cue_slot()
        except ValueError as exc:
            self.note.setText(f"沒辦法新增：{exc}。把播放頭移到兩句中間的空檔再按一次。")
            return False
        self._adding = start
        self._updating = True
        try:
            self.table.clearSelection()
        finally:
            self._updating = False
        self.player.timeline.select_cue(-1, seek=False)  # 時間軸也不選：新的那句還不在上面
        self._editing = -1
        self.editor.setEnabled(True)
        self.editor.setPlainText("")
        self.editor.setFocus()
        self.note.setText(ADD_HINT.format(start=format_seconds(start), end=format_seconds(end)))
        self._update_buttons()
        return True

    def delete_selected(self):
        """拿掉選到的那句（Ctrl+Z 救得回來）。回傳是否刪了。"""
        self.commit()
        index = self.selected_index()
        if not 0 <= index < len(self.player.cues):
            self.note.setText("先在清單裡選一句再刪除。")
            return False
        self.player.delete_cue(index)
        self._select_quietly(min(index, len(self.player.cues) - 1))
        self.note.setText(f"已刪除第 {index + 1} 句（按 Ctrl+Z 救得回來）。")
        return True

    def open_translate(self):
        """「翻譯字幕…」：編輯框裡改到一半的先套用，再開翻譯的小視窗（翻的是套用後的字幕）。"""
        self.commit()
        if not self.player.cues:
            self.note.setText("還沒有字幕可以翻。")
            return None
        if self.translate_dialog is None:
            from gui_qt.translate_dialog import TranslateDialog
            self.translate_dialog = TranslateDialog(self.player, self)
            self.translate_dialog.applied.connect(self.note.setText)
        self.translate_dialog.status.setText("")
        self.translate_dialog.progress.setValue(0)
        self.translate_dialog.refresh()
        self.translate_dialog.open()
        return self.translate_dialog

    def open_style(self):
        """「字幕樣式…」：開樣式的小視窗（不擋住播放器，可以邊播邊調）。"""
        if self.style_dialog is None:
            from gui_qt.style_panel import StyleDialog
            self.style_dialog = StyleDialog(self.player, self)
        self.style_dialog.fill(self.style_dialog.current())
        self.style_dialog.show()
        self.style_dialog.raise_()
        return self.style_dialog

    def show_find(self):
        """Ctrl+F：展開尋找取代，游標放到「尋找」。"""
        self.find_btn.setChecked(True)
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def find_next(self):
        """從選到的那句往下找（到底繞回開頭），選到就跳過去。回傳找到第幾句（-1＝沒有）。"""
        self.commit()
        term, case = self.find_edit.text(), self.case_box.isChecked()
        hits = find_in_cues(self.player.cues, term, case)
        if not term:
            self.note.setText("先打要找的字。")
            return -1
        if not hits:
            self.note.setText(f"沒有找到「{term}」。")
            return -1
        current = self.selected_index()
        target = next((i for i in hits if i > current), hits[0])
        self.select(target)
        total = count_occurrences(self.player.cues, term, case)
        self.note.setText(f"「{term}」：第 {hits.index(target) + 1} / {len(hits)} 句（一共 {total} 處）。")
        return target

    def replace_current(self):
        """
        取代這句：選到的那句有要找的字就換掉，然後跳到下一個；沒有的話先找下一個（再按一次才換）。
        回傳取代了幾處。
        """
        self.commit()
        term, case = self.find_edit.text(), self.case_box.isChecked()
        index = self.selected_index()
        if not term:
            self.note.setText("先打要找的字。")
            return 0
        if index not in find_in_cues(self.player.cues, term, case):
            self.find_next()
            return 0
        count, _changed, emptied = self.player.replace_text(term, self.replace_edit.text(), case, only=[index])
        if emptied:
            self.note.setText(f"第 {index + 1} 句取代後會變成空的，沒有改（要整句拿掉請按「刪除這句」）。")
            return 0
        if find_in_cues(self.player.cues, term, case):
            self.find_next()
            self.note.setText(f"已取代第 {index + 1} 句。" + self.note.text())
        else:
            self.note.setText(f"已取代第 {index + 1} 句，沒有別的「{term}」了。")
        return count

    def replace_all(self):
        """全部取代（整批是一步復原）。回傳取代了幾處。"""
        self.commit()
        term, case = self.find_edit.text(), self.case_box.isChecked()
        if not term:
            self.note.setText("先打要找的字。")
            return 0
        count, changed, emptied = self.player.replace_text(term, self.replace_edit.text(), case)
        if not changed and not emptied:
            self.note.setText(f"沒有找到「{term}」。")
            return 0
        parts = [f"已取代 {count} 處（{len(changed)} 句），按 Ctrl+Z 一次全部退回。"] if changed else []
        if emptied:
            parts.append(f"{numbers(emptied)}取代後會變成空的，沒有改（要整句拿掉請用「刪除這句」）。")
        self.note.setText("".join(parts))
        return count

    # ---- 內部 ----------------------------------------------------------

    def _commit_add(self):
        start, self._adding = self._adding, None
        text = self.editor.toPlainText()
        if not cueedit.clean_text(text):
            self._load_editor(self.selected_index())
            self.note.setText("新的一句沒有打字，沒有新增。")
            return False
        try:
            position, start, end = self.player.new_cue_slot(start)  # 打字的時候字幕可能變過：照現在的重找一次
        except ValueError as exc:
            self._load_editor(self.selected_index())
            self.note.setText(f"沒有新增：{exc}。")
            return False
        self.player.insert_cue(position, start, end, text)
        self._select_quietly(position)
        self.note.setText(f"已新增第 {position + 1} 句（{format_seconds(start)} → {format_seconds(end)}）。"
                          "要調時間就在時間軸上拖。")
        return True

    def _select_quietly(self, index):
        """選第 index 句但不跳播放頭（剛新增或刪除完：播放頭留在原地）。"""
        if 0 <= index < self.table.rowCount():
            self._from_timeline = True
            try:
                self.table.selectRow(index)
            finally:
                self._from_timeline = False
            self.player.timeline.select_cue(index, seek=False)

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
        self._update_buttons()

    def _update_buttons(self):
        has_cues = bool(self.player.cues)
        self.delete_btn.setEnabled(has_cues and self.selected_index() >= 0)
        self.translate_btn.setEnabled(has_cues)
        has_term = bool(self.find_edit.text())
        for button in (self.find_next_btn, self.replace_one_btn, self.replace_all_btn):
            button.setEnabled(has_cues and has_term)

    def _on_find_toggled(self, shown):
        self.find_bar.setVisible(shown)
        if shown:
            self.find_edit.setFocus()

    def _on_selection(self):
        if self._updating:
            return
        clicked = self.selected_index()
        before = len(self.player.cues)
        wanted = self.player.cues[clicked] if 0 <= clicked < before else None
        self.commit()  # 點別句前先把改到一半的套用掉（新增打字中就是先加進去）
        if wanted is not None and len(self.player.cues) != before:
            # 剛加了一句，後面的句子往後挪了一格：照原本點的那句找回來
            moved = next((i for i, c in enumerate(self.player.cues) if c == wanted), clicked)
            if moved != self.selected_index():
                self.table.selectRow(moved)
                return
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
                if self._adding is not None:
                    # 新增打字中點了清單：讓清單先換選取（那邊會先加進去、再照原本點的那句選回來），
                    # 不然先加進去的話清單往下挪一格，點到的就變成別句
                    QTimer.singleShot(0, self.commit)
                else:
                    self.commit()
        elif obj is self.table and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Delete:
            self.delete_selected()
            return True
        return super().eventFilter(obj, event)
