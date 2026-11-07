# -*- coding: utf-8 -*-
"""
字幕樣式（3.0 第 11 項第四階段）：逐句校對的「字幕樣式…」打開這個小視窗，不擋住播放器，邊播邊調。

跟一般版的「字幕視覺調整」是同一份設定（config 的 subtitle_style）、同一套範圍；值先過
`subtitle/exporter.clean_style` 整理。改了立刻在播放器畫面上看得到（播放器照燒錄的規則畫）。

跟一般版不一樣的地方（都照燒錄實際的樣子）：

* **沒有水平位置滑桿**：燒錄時字幕一律水平置中，一般版的 X 滑桿拉了也不會變。值照樣留著不動。
* **垂直位置寫出會放在哪一段**：燒錄只分三段——上段字的頂邊對齊那條線、下段字的底邊對齊那條線、
  中段（34～65）一律放在正中間，拉了也不會動。滑桿旁邊寫出現在是哪一段，免得以為壞了。
* **只記在這次開啟的設定裡**：Qt 預覽版不寫回 config.json（跟一般版同時開會互相蓋掉）。
  「還原」回到打開預覽版時的樣式。

字型可以從清單選或自己打（按 Enter 或離開就套用）；電腦上沒有的字型，畫面用替代字型畫，
燒錄時也一樣是替代字型。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSlider, QSpinBox, QVBoxLayout,
)

from subtitle import exporter

FONT_CHOICES = (
    "Microsoft JhengHei", "Microsoft JhengHei UI", "微軟正黑體", "Microsoft YaHei", "PMingLiU", "新細明體",
    "MingLiU", "細明體", "DFKai-SB", "標楷體", "KaiTi", "SimSun", "SimHei", "FangSong",
    "Noto Sans CJK TC", "Noto Serif CJK TC", "Arial", "Segoe UI", "Times New Roman", "Tahoma", "Verdana",
)
VERTICAL_PRESETS = (("頂部", 0.12), ("中部", 0.50), ("底部", 0.88))
DYNAMIC_LABELS = (("off", "無（整句）"), ("karaoke", "逐字上色（卡拉OK）"), ("word", "單字彈出"))
ZONE_NOTES = {
    "top": "上段：字的頂邊對齊這條線",
    "middle": "中段（34～65）：一律放在正中間",
    "bottom": "下段：字的底邊對齊這條線",
}
COLOR_KEYS = (("text_color", "文字顏色"), ("stroke_color", "邊框顏色"), ("emphasis_color", "重點字顏色"))


class StyleDialog(QDialog):
    """字幕樣式的小視窗。player＝PlayerPanel（`set_style` 與這次開啟的設定 `_config` 都在那邊）。"""

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.setModal(False)
        self.setWindowTitle("字幕樣式")
        self.player = player
        self._filling = False
        self.opened_with = exporter.clean_style(player._config.get("subtitle_style"))

        self.y_slider = QSlider(Qt.Horizontal)
        self.y_slider.setRange(0, 100)
        self.y_slider.setMinimumWidth(220)
        self.y_value = QLabel()
        self.y_value.setMinimumWidth(32)
        self.zone_note = QLabel()
        self.preset_buttons = {}
        presets = QHBoxLayout()
        presets.addWidget(QLabel("快捷位置："))
        for label, value in VERTICAL_PRESETS:
            button = QPushButton(label)
            button.clicked.connect(lambda _c=False, v=value: self.y_slider.setValue(int(round(v * 100))))
            presets.addWidget(button)
            self.preset_buttons[label] = button
        presets.addStretch(1)

        self.font_box = QComboBox()
        self.font_box.setEditable(True)
        self.font_box.addItems(list(FONT_CHOICES))
        self.font_note = QLabel()
        self.font_note.setWordWrap(True)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(*exporter.FONT_SIZE_RANGE)
        self.stroke_spin = QSpinBox()
        self.stroke_spin.setRange(*exporter.STROKE_WIDTH_RANGE)
        self.color_buttons = {}
        colors = QHBoxLayout()
        for key, label in COLOR_KEYS[:2]:
            button = QPushButton(label)
            button.clicked.connect(lambda _c=False, k=key: self.choose_color(k))
            colors.addWidget(button)
            self.color_buttons[key] = button
        colors.addStretch(1)
        self.emphasis_box = QCheckBox("重點字上色")
        emphasis_color = QPushButton(COLOR_KEYS[2][1])
        emphasis_color.clicked.connect(lambda _c=False: self.choose_color("emphasis_color"))
        self.color_buttons["emphasis_color"] = emphasis_color
        self.emphasis_edit = QLineEdit()
        self.emphasis_edit.setPlaceholderText("重點字詞：逗號或空白分隔")
        self.dynamic_combo = QComboBox()
        for value, label in DYNAMIC_LABELS:
            self.dynamic_combo.addItem(label, value)
        self.note = QLabel("改了馬上在播放器畫面上看得到。只記在這次開啟的設定裡（預覽版不寫回 config.json）；"
                           "要一直用這組樣式，請在一般版調。燒錄時字幕一律水平置中，所以這裡沒有水平位置。")
        self.note.setWordWrap(True)
        self.reset_btn = QPushButton("還原成打開時的樣式")
        self.close_btn = QPushButton("關閉")

        grid = QGridLayout()
        grid.addWidget(QLabel("垂直位置"), 0, 0)
        grid.addWidget(self.y_slider, 0, 1)
        grid.addWidget(self.y_value, 0, 2)
        grid.addWidget(self.zone_note, 1, 1, 1, 2)
        grid.addLayout(presets, 2, 0, 1, 3)
        grid.addWidget(QLabel("字型"), 3, 0)
        grid.addWidget(self.font_box, 3, 1, 1, 2)
        grid.addWidget(self.font_note, 4, 1, 1, 2)
        sizes = QHBoxLayout()
        sizes.addWidget(QLabel("字級"))
        sizes.addWidget(self.size_spin)
        sizes.addSpacing(16)
        sizes.addWidget(QLabel("邊框寬"))
        sizes.addWidget(self.stroke_spin)
        sizes.addStretch(1)
        grid.addLayout(sizes, 5, 0, 1, 3)
        grid.addLayout(colors, 6, 0, 1, 3)
        emphasis = QHBoxLayout()
        emphasis.addWidget(self.emphasis_box)
        emphasis.addWidget(emphasis_color)
        emphasis.addStretch(1)
        grid.addLayout(emphasis, 7, 0, 1, 3)
        grid.addWidget(self.emphasis_edit, 8, 0, 1, 3)
        grid.addWidget(QLabel("動態字幕"), 9, 0)
        grid.addWidget(self.dynamic_combo, 9, 1, 1, 2)
        buttons = QHBoxLayout()
        buttons.addWidget(self.reset_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.close_btn)
        layout = QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addWidget(self.note)
        layout.addLayout(buttons)
        self.setMinimumWidth(440)

        self.y_slider.valueChanged.connect(self._send)
        self.size_spin.valueChanged.connect(self._send)
        self.stroke_spin.valueChanged.connect(self._send)
        self.font_box.activated.connect(self._send)
        self.font_box.lineEdit().editingFinished.connect(self._send)
        self.emphasis_box.toggled.connect(self._send)
        self.emphasis_edit.editingFinished.connect(self._send)
        self.dynamic_combo.currentIndexChanged.connect(self._send)
        self.reset_btn.clicked.connect(self.reset)
        self.close_btn.clicked.connect(self.close)
        self.fill(self.current())

    # ---- 對外 ----------------------------------------------------------

    def current(self):
        """播放器現在用的樣式（整理過）。"""
        return exporter.clean_style(self.player._config.get("subtitle_style"))

    def fill(self, style):
        """照 style 擺好每個控件（不送出）。"""
        style = exporter.clean_style(style)
        self._filling = True
        try:
            self._colors = {key: style[key] for key, _label in COLOR_KEYS}
            self.y_slider.setValue(int(round(style["position_y"] * 100)))
            self.font_box.setEditText(style["font_family"])
            self.size_spin.setValue(style["font_size"])
            self.stroke_spin.setValue(style["stroke_width"])
            self.emphasis_box.setChecked(style["emphasis_enabled"])
            self.emphasis_edit.setText(style["emphasis_words"])
            self.dynamic_combo.setCurrentIndex(self.dynamic_combo.findData(style["dynamic_mode"]))
        finally:
            self._filling = False
        self._refresh_labels(style)

    def style(self):
        """控件上現在的樣式（其他欄位照播放器現在的，例如水平位置）。"""
        out = dict(self.current())
        out.update({
            "position_y": self.y_slider.value() / 100.0,
            "font_family": self.font_box.currentText(),
            "font_size": self.size_spin.value(),
            "stroke_width": self.stroke_spin.value(),
            "emphasis_enabled": self.emphasis_box.isChecked(),
            "emphasis_words": self.emphasis_edit.text(),
            "dynamic_mode": self.dynamic_combo.currentData(),
        })
        out.update(self._colors)
        return exporter.clean_style(out)

    def choose_color(self, key):
        """選色（文字／邊框／重點字）；取消就不變。回傳選到的顏色或 None。"""
        color = self._ask_color(self._colors[key], dict(COLOR_KEYS)[key])
        if not color:
            return None
        self._colors[key] = color.upper()
        self._send()
        return self._colors[key]

    def reset(self):
        """還原成打開預覽版時的樣式。"""
        self.fill(self.opened_with)
        self._send()

    # ---- 內部 ----------------------------------------------------------

    def _ask_color(self, current, title):
        """跳出選色視窗；回傳 "#RRGGBB" 或 None（取消）。測試換掉這一個。"""
        color = QColorDialog.getColor(QColor(current), self, f"選{title}")
        return color.name() if color.isValid() else None

    def _send(self, *_args):
        if self._filling:
            return
        style = self.style()
        # 只記在這次開啟的設定裡：Qt 預覽版不寫回 config.json
        self.player._config["subtitle_style"] = style
        self.player.set_style(style)
        self._refresh_labels(style)

    def _refresh_labels(self, style):
        self.y_value.setText(str(int(round(style["position_y"] * 100))))
        self.zone_note.setText(ZONE_NOTES[exporter.vertical_zone(style["position_y"])])
        for key, label in COLOR_KEYS:
            color = QColor(self._colors[key])
            text = "#000000" if color.lightness() > 140 else "#FFFFFF"
            self.color_buttons[key].setText(f"{label} {self._colors[key]}")
            self.color_buttons[key].setStyleSheet(f"background-color: {self._colors[key]}; color: {text};")
        family = style["font_family"]
        if family in QFontDatabase.families():
            self.font_note.setText("")
        else:
            self.font_note.setText(f"這台電腦沒有「{family}」：畫面先用替代字型畫，燒錄時也會是替代字型。")
        self.emphasis_edit.setEnabled(style["emphasis_enabled"])
        self.color_buttons["emphasis_color"].setEnabled(style["emphasis_enabled"])
