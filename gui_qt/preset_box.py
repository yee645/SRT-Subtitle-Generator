# -*- coding: utf-8 -*-
"""
習慣設定（樣式組合）與斷句設定（3.0 第 11 項第三十一階段，第 19 列（四））：放在「字幕樣式」小視窗裡。

一般版的「習慣設定（樣式組合）」框與左欄的「斷句設定」框搬過來。一組習慣設定存的是**字幕外觀＋斷句設定**
兩樣（`config.make_profile`）；Qt 版以前沒有斷句設定的介面（生成字幕照設定檔裡的值斷句，看不到也改不了），
這階段一起補上，放在同一個視窗裡，兩樣東西的關係一眼看得到。

* 選一組：字幕外觀與斷句設定都換成那一組，播放器上立刻看得到。
* 〔另存新樣式〕：問名字；空白不行；同名先問要不要覆蓋。
* 〔更新目前樣式〕：把現在的值存進選取的那一組。
* 〔刪除〕：先問；至少留一組；刪掉後改用名字排第一的那一組。
* 下面一行寫「目前的值跟選取的那一組一不一樣」（`config.describe_preset_state`，跟一般版同一句）。
* 斷句設定的範圍與夾限跟一般版一樣（`subtitle/profiles.clean_segmentation`），改了寫進這次開啟的設定；
  下次「生成字幕…」就照這組斷句。

都寫進同一份 `player._config`（＝主視窗的 `config_data`），關掉 Qt 版時只把改過的區塊存回 config.json。
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout,
)

import config as app_config
from subtitle import exporter, profiles

PRESET_NOTE = ("一組樣式存的是下方左邊的「字幕外觀」，加上右邊的「斷句設定」；"
               "改了之後要按〔更新目前樣式〕才會存進去。")
SEGMENTATION_NOTE = "下次「生成字幕…」照這組斷句；已經有的字幕不會重新斷句。"


def ensure_presets(cfg):
    """設定裡沒有（或壞掉的）習慣設定時，照 config.load_config 的相容規則補一組「預設」。回傳 presets。"""
    presets = cfg.get("presets")
    if not isinstance(presets, dict) or not presets:
        cfg["presets"] = {"預設": app_config.make_profile(
            exporter.clean_style(cfg.get("subtitle_style")),
            profiles.clean_segmentation(cfg.get("segmentation")))}
        cfg["active_preset"] = "預設"
    if cfg.get("active_preset") not in cfg["presets"]:
        cfg["active_preset"] = profiles.preset_names(cfg["presets"])[0]
    return cfg["presets"]


class SegmentationBox(QGroupBox):
    """斷句設定（一般版左欄的那一框）。改了就寫進 cfg["segmentation"]，送出 changed。"""

    changed = Signal()

    def __init__(self, cfg, parent=None):
        super().__init__("斷句設定", parent)
        self.cfg = cfg
        self._filling = False
        self.spins = {}
        form = QFormLayout()
        for key, label, low, high, step, unit in profiles.SEGMENTATION_FIELDS:
            if isinstance(step, int):
                spin = QSpinBox()
            else:
                spin = QDoubleSpinBox()
                spin.setDecimals(1)
                spin.setSingleStep(step)
            spin.setRange(low, high)
            spin.setSuffix(f" {unit.split('（')[0]}")
            spin.valueChanged.connect(self._send)
            self.spins[key] = spin
            form.addRow(label, spin)
        self.offset_note = QLabel("正值整體延後、負值整體提前。")
        self.note = QLabel(SEGMENTATION_NOTE)
        self.note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.offset_note)
        layout.addWidget(self.note)
        self.fill()

    def current(self):
        return profiles.clean_segmentation(self.cfg.get("segmentation"))

    def fill(self, seg=None):
        seg = profiles.clean_segmentation(seg if seg is not None else self.cfg.get("segmentation"))
        self._filling = True
        try:
            for key, spin in self.spins.items():
                spin.setValue(seg[key])
        finally:
            self._filling = False

    def values(self):
        """控件上的值（夾限過；最短不超過最長）。"""
        raw = {key: spin.value() for key, spin in self.spins.items()}
        return profiles.clean_segmentation(raw, self.cfg.get("segmentation"))

    def _send(self, *_args):
        if self._filling:
            return
        seg = dict(self.cfg.get("segmentation") or {})
        seg.update(self.values())
        self.cfg["segmentation"] = seg
        self.changed.emit()


class PresetBox(QGroupBox):
    """
    習慣設定（樣式組合）。`get_profile()` 回傳畫面上現在的 {subtitle_style, segmentation}；
    `apply_profile(profile)` 把一組套到畫面與播放器上（StyleDialog 給）。
    """

    applied = Signal(str)   # 套用了哪一組
    message = Signal(str)   # 狀態文字（已儲存、已刪除…）

    def __init__(self, cfg, get_profile, apply_profile, parent=None):
        super().__init__("習慣設定（樣式組合）", parent)
        self.cfg = cfg
        self.get_profile = get_profile
        self.apply_profile = apply_profile
        ensure_presets(cfg)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(160)
        self.save_new_btn = QPushButton("另存新樣式")
        self.update_btn = QPushButton("更新目前樣式")
        self.delete_btn = QPushButton("刪除")
        self.note = QLabel(PRESET_NOTE)
        self.note.setWordWrap(True)
        self.state = QLabel()
        self.state.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(QLabel("目前樣式："))
        row.addWidget(self.combo, 1)
        buttons = QHBoxLayout()
        for button in (self.save_new_btn, self.update_btn, self.delete_btn):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addLayout(buttons)
        layout.addWidget(self.note)
        layout.addWidget(self.state)
        self._refill(cfg["active_preset"])
        self.combo.activated.connect(lambda _i: self.choose(self.combo.currentText()))
        self.save_new_btn.clicked.connect(lambda _c=False: self.save_new())
        self.update_btn.clicked.connect(lambda _c=False: self.update_current())
        self.delete_btn.clicked.connect(lambda _c=False: self.delete_current())
        # 狀態行等外面的控件擺好再算：StyleDialog 建好之後呼叫 refresh_state()

    # ---- 對外 ----------------------------------------------------------

    def selected(self):
        return self.combo.currentText()

    def choose(self, name):
        """套用一組：字幕外觀與斷句設定都換成它。回傳是否套用了。"""
        preset = ensure_presets(self.cfg).get(name)
        if not preset:
            return False
        self.cfg["active_preset"] = name
        self._refill(name)
        self.apply_profile(app_config.make_profile(preset["subtitle_style"], preset["segmentation"]))
        self.refresh_state()
        self.applied.emit(name)
        self.message.emit(f"已套用習慣設定：{name}（字幕外觀與斷句設定都換成這一組）")
        return True

    def save_new(self):
        """另存新樣式。回傳存下的名字或 None（取消、空白、不覆蓋）。"""
        presets = ensure_presets(self.cfg)
        raw = self._ask_name()
        if raw is None:
            return None
        name, error, overwrite = profiles.check_new_name(raw, presets)
        if error:
            self._warn(error)
            return None
        if overwrite and not self._ask_yes("確認覆蓋", f"樣式「{name}」已存在，要覆蓋嗎？"):
            return None
        presets[name] = self._current_profile()
        self.cfg["active_preset"] = name
        self._refill(name)
        self.refresh_state()
        self.message.emit(f"已儲存習慣設定：{name}")
        return name

    def update_current(self):
        """把現在的值存進選取的那一組。"""
        name = self.selected()
        presets = ensure_presets(self.cfg)
        if name not in presets:
            return False
        presets[name] = self._current_profile()
        self.refresh_state()
        self.message.emit(f"已更新習慣設定：{name}")
        return True

    def delete_current(self):
        """刪除選取的那一組（先問；至少留一組）。回傳改選的名字或 None。"""
        name = self.selected()
        presets = ensure_presets(self.cfg)
        if name not in presets:
            return None
        if len(presets) <= 1:
            self._warn(profiles.KEEP_ONE)
            return None
        if not self._ask_yes("確認刪除", f"確定要刪除習慣設定「{name}」？"):
            return None
        remaining, fallback, _error = profiles.after_delete(presets, name)
        self.cfg["presets"] = remaining
        self.choose(fallback)
        self.message.emit(f"已刪除習慣設定：{name}")
        return fallback

    def reload(self):
        """照設定重擺下拉選單（選取中的＝active_preset），重算狀態行。"""
        ensure_presets(self.cfg)
        self._refill(self.cfg["active_preset"])
        self.refresh_state()

    def refresh_state(self):
        """「目前的值跟選取的那一組一不一樣」那一行。"""
        self.state.setText(app_config.describe_preset_state(
            self._current_profile(), ensure_presets(self.cfg), self.selected()))
        self.delete_btn.setEnabled(len(self.cfg["presets"]) > 1)

    # ---- 內部 ----------------------------------------------------------

    def _current_profile(self):
        profile = self.get_profile()
        return app_config.make_profile(profile["subtitle_style"], profile["segmentation"])

    def _refill(self, selected):
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(profiles.preset_names(self.cfg["presets"]))
        self.combo.setCurrentIndex(max(0, self.combo.findText(selected)))
        self.combo.blockSignals(False)

    def _ask_name(self):
        """問新樣式的名字；取消回 None。測試換掉這一個。"""
        text, ok = QInputDialog.getText(self, "另存新樣式", "請輸入樣式名稱：")
        return text if ok else None

    def _ask_yes(self, title, text):
        """是／否；測試換掉這一個。"""
        return QMessageBox.question(self, title, text) == QMessageBox.Yes

    def _warn(self, text):
        """提示；測試換掉這一個。"""
        QMessageBox.information(self, "提示", text)

