# -*- coding: utf-8 -*-
"""
3.0 第 9 項第二～四階段：畫面調整的小視窗（亮度、對比、飽和度、裁切、旋轉、翻轉）。

裁切用「四邊各裁掉幾 %」（原畫面的比例，轉之前的方向）：比框座標好懂，也不必知道畫面多大。

調的對象（`target`）是主片或選取的那段疊加素材，標題寫是哪一個；`set_target` 換對象時
連同送給誰（`apply`）一起換。不擋住播放器（非強制回應）：拉滑桿時播放器的畫面跟著變，可以
邊播邊調。每動一下就交給 `apply`（播放器的 `set_main_adjust`／`set_overlay_adjust`），它不收
（輸出中）就把控件放回它現在的值。數字照
`subtitle/picture.py` 的範圍：滑桿是百分之一的整數。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QSpinBox,
    QVBoxLayout,
)

from subtitle import picture

# (鍵, 標籤, 滑桿最小, 最大)：滑桿是 ×100 的整數
SLIDERS = (("brightness", "亮度", -100, 100), ("contrast", "對比", 0, 200), ("saturation", "飽和度", 0, 300))
ROTATE_LABELS = (("不轉", 0), ("順時針 90°", 90), ("180°", 180), ("逆時針 90°", 270))
CROP_SIDES = (("left", "左"), ("top", "上"), ("right", "右"), ("bottom", "下"))  # 四邊各裁幾 %


def crop_from_sides(left, top, right, bottom):
    """四邊各裁幾 %（0～100）→ picture 的 [x, y, w, h]。"""
    return [left / 100.0, top / 100.0, 1.0 - (left + right) / 100.0, 1.0 - (top + bottom) / 100.0]


def sides_from_crop(crop):
    """[x, y, w, h] → 四邊各裁幾 %（四捨五入到整數）。"""
    x, y, w, h = crop
    return {"left": int(round(x * 100)), "top": int(round(y * 100)),
            "right": int(round((1.0 - x - w) * 100)), "bottom": int(round((1.0 - y - h) * 100))}


def slider_text(key, value):
    """滑桿旁邊寫的數字：亮度寫正負，對比、飽和度寫百分比。"""
    if key == "brightness":
        return f"{value:+d}" if value else "0"
    return f"{value}%"


class PictureDialog(QDialog):
    def __init__(self, apply, parent=None):
        super().__init__(parent)
        self.setModal(False)
        self._apply = apply
        self.target = "main"  # "main" 或 ("overlays", 第幾段)
        self.setWindowTitle("畫面調整（主片）")
        self._filling = False
        self.sliders, self.value_labels = {}, {}
        grid = QGridLayout()
        for row, (key, label, low, high) in enumerate(SLIDERS):
            slider = QSlider(Qt.Horizontal)
            slider.setRange(low, high)
            slider.setMinimumWidth(220)
            slider.setToolTip(f"{label}（{picture.RANGES[key][0]:g}～{picture.RANGES[key][1]:g}，"
                              f"預設 {picture.DEFAULTS[key]:g}）")
            value_label = QLabel("")
            value_label.setMinimumWidth(44)
            slider.valueChanged.connect(lambda _v, k=key: self._on_slider(k))
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(slider, row, 1)
            grid.addWidget(value_label, row, 2)
            self.sliders[key] = slider
            self.value_labels[key] = value_label
        self.rotate_combo = QComboBox()
        for label, degrees in ROTATE_LABELS:
            self.rotate_combo.addItem(label, degrees)
        self.rotate_combo.setToolTip("直拍的影片轉正；轉 90° 時輸出的畫面跟著變成直的或橫的")
        self.crop_spins = {}
        crop_row = QHBoxLayout()
        crop_row.addWidget(QLabel("裁切"))
        for key, label in CROP_SIDES:
            spin = QSpinBox()
            spin.setRange(0, 95)
            spin.setSuffix("%")
            spin.setPrefix(f"{label} ")
            spin.setToolTip(f"{label}邊裁掉原畫面的幾 %（轉之前的方向；裁完至少要留 "
                            f"{picture.MIN_CROP:.0%}）")
            spin.valueChanged.connect(lambda _v: self._send())
            crop_row.addWidget(spin)
            self.crop_spins[key] = spin
        crop_row.addStretch(1)
        self.flip_h_box = QCheckBox("左右翻")
        self.flip_v_box = QCheckBox("上下翻")
        for w in (self.flip_h_box, self.flip_v_box):
            w.setToolTip("轉完之後再翻")
        turn = QHBoxLayout()
        turn.addWidget(QLabel("旋轉"))
        turn.addWidget(self.rotate_combo)
        turn.addSpacing(8)
        turn.addWidget(self.flip_h_box)
        turn.addWidget(self.flip_v_box)
        turn.addStretch(1)
        self.note_label = QLabel("播放器上的顏色是近似（輸出照 ffmpeg 算），差一點點是正常的")
        self.note_label.setWordWrap(True)
        self.reset_btn = QPushButton("全部還原")
        self.close_btn = QPushButton("關閉")
        buttons = QHBoxLayout()
        buttons.addWidget(self.reset_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.close_btn)
        layout = QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addLayout(crop_row)
        layout.addLayout(turn)
        layout.addWidget(self.note_label)
        layout.addLayout(buttons)

        self.rotate_combo.currentIndexChanged.connect(lambda _i: self._send())
        self.flip_h_box.toggled.connect(lambda _on: self._send())
        self.flip_v_box.toggled.connect(lambda _on: self._send())
        self.reset_btn.clicked.connect(lambda: self._send(reset=True))
        self.close_btn.clicked.connect(self.close)
        self.fill({})

    def set_target(self, target, title, apply, adjust):
        """換調的對象：標題寫是誰，之後的變動送給 apply，控件照它現在的調整填。"""
        self.target = target
        self._apply = apply
        self.setWindowTitle(f"畫面調整（{title}）")
        self.fill(adjust)

    def current(self) -> dict:
        """控件現在的值（只留改過的項目）。"""
        return picture.changes(self._raw())

    def _raw(self) -> dict:
        """控件現在的值，沒檢查（裁太小時交給 apply 去擋、說原因）。"""
        adjust = {key: self.sliders[key].value() / 100.0 for key, *_ in SLIDERS}
        adjust["crop"] = crop_from_sides(*(self.crop_spins[k].value() for k, _l in CROP_SIDES))
        adjust["rotate"] = self.rotate_combo.currentData()
        adjust["flip_h"] = self.flip_h_box.isChecked()
        adjust["flip_v"] = self.flip_v_box.isChecked()
        return adjust

    def fill(self, adjust):
        """照一份調整填控件（填的時候不送出）。"""
        full = picture.normalize(adjust)
        self._filling = True
        try:
            for key, *_ in SLIDERS:
                self.sliders[key].setValue(int(round(full[key] * 100)))
                self.value_labels[key].setText(slider_text(key, self.sliders[key].value()))
            for key, value in sides_from_crop(full["crop"]).items():
                self.crop_spins[key].setValue(value)
            self.rotate_combo.setCurrentIndex(max(self.rotate_combo.findData(full["rotate"]), 0))
            self.flip_h_box.setChecked(full["flip_h"])
            self.flip_v_box.setChecked(full["flip_v"])
            self.reset_btn.setEnabled(bool(picture.changes(full)))
        finally:
            self._filling = False

    def _on_slider(self, key):
        self.value_labels[key].setText(slider_text(key, self.sliders[key].value()))
        self._send()

    def _send(self, reset=False):
        if self._filling:
            return
        wanted = {} if reset else self._raw()
        accepted = self._apply(wanted)
        self.fill(accepted)  # 不收就放回原本的值；收了也照存下來的寫一次（還原鈕亮不亮）
