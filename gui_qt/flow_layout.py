# -*- coding: utf-8 -*-
"""
放不下就換行的排版（E-9e）：一排按鈕、數字框在窄的面板裡自動折到下一行，不撐出橫捲軸。

`FlowLayout` 是 Qt 範例那種流式排版（照加入的順序由左到右排，超過寬度換行；藏起來的不佔位置）。
`flow_rows(layout)` 把一個版面底下「只放元件的橫排」換成流式排版——剪輯器的左側面板用；四頁籤不用。
"""
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import (QBoxLayout, QGridLayout, QHBoxLayout, QLabel, QLayout, QSizePolicy, QVBoxLayout,
                               QWidget, QWidgetItem)


_KEEP = []  # 建出來的 FlowLayout（見 _make_flow）


class FlowLayout(QLayout):
    def __init__(self, parent=None, h_spacing=8, v_spacing=6):
        super().__init__(parent)
        self._items = []
        self._h, self._v = h_spacing, v_spacing
        self.setContentsMargins(0, 0, 0, 0)

    # ----- QLayout 必備的 -----
    def addItem(self, item):
        self._items.append(item)

    def addWidget(self, widget):
        """
        自己建版面項目（不走 QLayout.addWidget）：Qt 在 C++ 建的項目交到 Python 時，可能拿到同一個位址上
        已經刪掉的舊項目的包裝，之後一碰就當。Python 建的項目由 Python 留著，不會有這個問題。
        """
        self.addChildWidget(widget)
        self._items.append(QWidgetItem(widget))
        self.invalidate()

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        """最窄＝最寬的那一個元件（其他的都可以換行）。"""
        size = QSize()
        for item in self._visible():
            size = size.expandedTo(item.minimumSize().expandedTo(item.sizeHint()))
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    # ----- 排 -----
    def _visible(self):
        return [item for item in self._items if not (item.widget() is not None and item.widget().isHidden())]

    def rows(self, width):
        """寬度 width 時每一行放哪幾個（給測試用）：[[元件, ...], ...]。"""
        lines, current, x = [], [], 0
        for item in self._visible():
            w = item.sizeHint().width()
            if current and x + w > width:
                lines.append(current)
                current, x = [], 0
            current.append(item.widget())
            x += w + self._h
        if current:
            lines.append(current)
        return lines

    def _arrange(self, rect, apply):
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        lines, line, x = [], [], area.x()
        for item in self._visible():
            hint = item.sizeHint()
            if line and x + hint.width() > area.right() + 1:
                lines.append(line)
                line, x = [], area.x()
            line.append((item, x, hint))
            x += hint.width() + self._h
        if line:
            lines.append(line)
        y = area.y()
        for i, line in enumerate(lines):
            line_h = max(hint.height() for _item, _x, hint in line)
            if apply:  # 一行裡高矮不一時垂直置中（標籤跟數字框對齊）
                for item, lx, hint in line:
                    item.setGeometry(QRect(QPoint(lx, y + (line_h - hint.height()) // 2), hint))
            y += line_h + (self._v if i < len(lines) - 1 else 0)
        return y - rect.y() + m.bottom()

def _plain_row(layout):
    """只放元件（加上間距、伸縮）的橫排才換：裡面有子版面、或會折行的長說明（它自己會折）就不動。"""
    if type(layout) is not QHBoxLayout:
        return False
    widgets = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.layout() is not None:
            return False
        w = item.widget()
        if w is None:
            continue
        if isinstance(w, QLabel) and w.wordWrap():
            return False
        widgets.append(w)
    return len(widgets) >= 2


def _pairs(widgets):
    """標籤後面緊接著一個輸入元件（數字框、輸入欄…）就包成一組，換行時不會把「音量」跟它的數字框拆開。"""
    out, i = [], 0
    while i < len(widgets):
        w = widgets[i]
        nxt = widgets[i + 1] if i + 1 < len(widgets) else None
        if (isinstance(w, QLabel) and not w.wordWrap() and nxt is not None and not isinstance(nxt, QLabel)):
            pair = QWidget()
            pair.setObjectName("flowPair")
            row = QHBoxLayout(pair)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            row.addWidget(w)
            row.addWidget(nxt)
            pair.setVisible(not nxt.isHidden())
            out.append(pair)
            i += 2
        else:
            out.append(w)
            i += 1
    return out


def _make_flow(widgets):
    box = QWidget()
    box.setObjectName("flowRow")
    flow = FlowLayout(box)
    # Python 寫的版面要留著 Python 那一半：只靠 Qt 持有的話，垃圾回收後 Qt 再來問大小就當掉
    _KEEP.append(flow)
    box.flow = flow
    for w in _pairs(widgets):
        flow.addWidget(w)
    return box


def _take_widgets(layout):
    """
    把 layout 裡的元件照順序拿出來（巢狀的橫排攤平；間距、伸縮丟掉）。

    只回傳元件、不留版面項目（QLayoutItem）的 Python 包裝：元件搬家時 Qt 會刪掉舊項目，新項目可能剛好配在
    同一個位址，舊包裝還留著的話會被當成新項目，回收時把新項目一起標成已刪除。
    """
    if isinstance(layout, QGridLayout):
        order = sorted((layout.getItemPosition(i)[:2], i) for i in range(layout.count()))
        indices = [i for _pos, i in order]
    else:
        indices = list(range(layout.count()))
    widgets = []
    for i in indices:
        w = layout.itemAt(i).widget()
        if w is not None:
            widgets.append(w)
            continue
        sub = layout.itemAt(i).layout()
        if sub is not None:
            widgets += _take_widgets(sub)
    return widgets


def _empty(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.layout() is not None:
            _empty(item.layout())


def _to_flow(row):
    """把橫排 row 的元件搬進一個流式排版的容器。回傳容器。"""
    return _make_flow(_take_widgets(row))


def flow_grid(owner):
    """
    owner（例如群組框）的格狀版面整個換成：一個流式排版放所有元件（標籤配好對），會折行的長說明放在下面整行。
    """
    grid = owner.layout()
    widgets = _take_widgets(grid)
    _empty(grid)  # 元件從版面（含巢狀的）拿出來；空的格狀版面留著，只放一格裝新的內容
    for c in range(grid.columnCount()):
        grid.setColumnStretch(c, 0)
    notes = [w for w in widgets if isinstance(w, QLabel) and w.wordWrap()]
    rest = [w for w in widgets if w not in notes]
    holder = QWidget()
    holder.setObjectName("flowRow")
    col = QVBoxLayout(holder)
    col.setContentsMargins(0, 0, 0, 0)
    box = _make_flow(rest)
    col.addWidget(box)
    for note in notes:
        col.addWidget(note)
    grid.addWidget(holder, 0, 0)
    return box


def flow_rows(layout):
    """把 layout 底下（遞迴）所有只放元件的橫排換成流式排版；回傳換好的容器。"""
    made = []
    targets = []
    for i in range(layout.count()):
        child = layout.itemAt(i).layout()
        if child is None:
            continue
        if _plain_row(child):
            targets.append((i, child))
        else:
            made += flow_rows(child)
    # 從後面換回來，前面的位置才不會跑掉
    for i, child in reversed(targets):
        if isinstance(layout, QBoxLayout):
            stretch = layout.stretch(i)
            box = _to_flow(child)
            layout.takeAt(i)
            layout.insertWidget(i, box, stretch)
        elif isinstance(layout, QGridLayout):
            r, c, rs, cs = layout.getItemPosition(i)
            box = _to_flow(child)
            layout.takeAt(i)
            layout.addWidget(box, r, c, rs, cs)
        else:
            continue
        made.append(box)
    return made


def flow_tree(root):
    """root 自己與底下每個元件的版面都跑一次 flow_rows。回傳換好的容器。"""
    made = []
    for w in [root] + root.findChildren(QWidget):
        if w.objectName() in ("flowRow", "flowPair"):
            continue
        lay = w.layout()
        if lay is not None and not isinstance(lay, FlowLayout):
            made += flow_rows(lay)
    return made
