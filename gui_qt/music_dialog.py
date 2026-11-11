# -*- coding: utf-8 -*-
"""
音樂軌的「配樂設定」小視窗（3.0 第 11 項第十五階段）：一般版「配樂助手」裡音樂軌還沒有的兩件事。

一般版的配樂助手是另開的工具：選影片、選音樂、輸出一支混好的影片。Qt 版早就有音樂軌（放在哪、
音量、循環、講話時壓低，跟畫面素材、剪點一起輸出），缺的只有：

1. **閃避設定**：講話時把音樂壓多低（強度）、多小聲的講話就算（靈敏度）、要不要先量人聲自動算。
   跟一般版同一份設定（config 的 ducking）、同一個範圍；整支影片共用——每一段勾了「講話時壓低」的
   音樂都照這一份。只記在這次開啟的設定裡（Qt 預覽版不寫 config.json）。
2. **分析節拍**：算選取那段音樂的速度與拍點，再掃影片的畫面剪接點，列出每個剪點離最近的拍子多遠、
   挪多少能對上。一般版假設音樂從影片 0 秒整首放；這裡照音樂軌上實際擺的位置、取的那一段、循環算
   （`beatsync.beats_on_timeline`）。只出報告，不動剪點也不動素材。

不擋住播放器（非強制回應）；選別段音樂，視窗跟著換對象。節拍分析在背景跑，全在本機，什麼都不送出去。
"""
import os
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDoubleSpinBox, QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar,
    QPushButton, QVBoxLayout,
)

from subtitle import audio, beatsync
from subtitle.burner import ffmpeg_available
from subtitle.errors import describe_exception
from subtitle.media import has_video_stream
from subtitle.pacing import detect_scene_changes, resolve_pacing_settings

DUCK_NOTE = ("強度：講話時音樂被壓低的程度，越高壓得越低。自動適應開著時，靈敏度照量到的人聲自動算"
             "（人聲偏小聲也壓得下去）；取消勾選才用手動靈敏度（數值越低，越輕的講話聲就會觸發）。"
             "整支影片共用：每一段勾了「講話時壓低」的音樂都照這裡。")
NO_TARGET = "先在時間軸上選一段音樂，再按「分析節拍」。"
NO_FILE = "找不到這段音樂的檔案，沒辦法分析。"
NO_FFMPEG = "找不到 ffmpeg，節拍分析需要它：請先在一般版按「自動安裝 ffmpeg」（兩版共用）。"
NO_CUTS = "影片裡沒有偵測到畫面剪接點，沒有剪點可以對。"
REPORT_HINT = "報告會列在這裡：速度、拍點，以及影片的畫面剪接點各離最近的拍子多遠。只出報告，不改任何東西。"


def placement_line(item, placed):
    """報告開頭那一行：這段音樂擺在影片的哪裡、落在影片上幾拍。"""
    stamp = beatsync.format_timestamp
    start = float(item.get("in") or 0.0)
    end = item.get("out")
    piece = f"取素材的 {stamp(start)}～{stamp(end)}" if end is not None else f"從素材的 {stamp(start)} 起"
    loop = "，循環到片尾" if item.get("loop") else ""
    return (f"「{os.path.basename(item['path'])}」從影片 {stamp(item.get('at', 0.0))} 開始放（{piece}{loop}），"
            f"落在影片上的拍子共 {len(placed)} 拍。下面剪點的時間是影片上的時間。")


def beat_report(payload):
    """背景算完的結果 → 給人看的報告（一般版同一份 format_beat_report，前面加一行擺放位置）。"""
    text = beatsync.format_beat_report(payload["result"], payload["snapped"], payload["settings"])
    if not payload["result"].get("bpm"):
        return text
    lines = [placement_line(payload["item"], payload["placed"]), "", text]
    if payload["scanned"] and not payload["snapped"]:
        lines += ["", NO_CUTS]
    return "\n".join(lines)


class BeatWorker(QObject):
    """背景執行緒：算節拍、照音樂軌上的位置換成影片時間、掃影片剪接點、對齊。busy 由畫面那邊放下。"""

    progress = Signal(float, str)
    finished = Signal(object)
    failed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False

    def start(self, item, video_path, total, config):
        self.busy = True
        threading.Thread(target=self._run, args=(dict(item), video_path, float(total), dict(config)),
                         daemon=True).start()

    def _run(self, item, video_path, total, config):
        try:
            settings = beatsync.resolve_beatsync_settings(config)
            result = beatsync.analyze_beats(item["path"], config,
                                            progress_cb=lambda r, m: self.progress.emit(float(r) * 0.8, str(m)))
            placed = beatsync.beats_on_timeline(result["beats"], item.get("at", 0.0), item.get("in") or 0.0,
                                                item.get("out"), total, bool(item.get("loop")))
            snapped, scanned = None, False
            if result["bpm"] and video_path and os.path.exists(video_path) and has_video_stream(video_path):
                self.progress.emit(0.8, "掃描畫面剪接點…")
                scanned = True
                cuts = detect_scene_changes(video_path, resolve_pacing_settings(config))
                if cuts:
                    snapped = beatsync.snap_times(cuts, placed, settings["max_shift"])
        except Exception as exc:  # noqa: BLE001 —— 背景執行緒的例外一律送回畫面上講
            self.failed.emit(exc)
            return
        self.finished.emit({"result": result, "placed": placed, "snapped": snapped, "scanned": scanned,
                            "settings": settings, "item": item})


class MusicDialog(QDialog):
    def __init__(self, player, parent=None):
        super().__init__(parent if parent is not None else player)
        self.setModal(False)
        self.setWindowTitle("配樂設定")
        self.player = player
        self.config = player._config
        self.target = None  # 音樂軌第幾段；None＝沒選取音樂
        self.last_payload = None
        settings = audio.resolve_ducking_settings(self.config)

        layout = QVBoxLayout(self)
        duck = QGroupBox("講話時壓低（閃避）")
        box = QVBoxLayout(duck)
        row = QHBoxLayout()
        self.strength_spin = QDoubleSpinBox()
        self.strength_spin.setRange(*audio._DUCK_STRENGTH_RANGE)
        self.strength_spin.setSingleStep(0.5)
        self.strength_spin.setDecimals(1)
        self.strength_spin.setValue(settings["duck_strength"])
        self.sensitivity_spin = QDoubleSpinBox()
        self.sensitivity_spin.setRange(*audio._DUCK_SENSITIVITY_RANGE)
        self.sensitivity_spin.setSingleStep(0.01)
        self.sensitivity_spin.setDecimals(2)
        self.sensitivity_spin.setValue(settings["duck_sensitivity"])
        row.addWidget(QLabel("閃避強度"))
        row.addWidget(self.strength_spin)
        row.addSpacing(12)
        row.addWidget(QLabel("閃避靈敏度"))
        row.addWidget(self.sensitivity_spin)
        row.addStretch(1)
        box.addLayout(row)
        self.auto_box = QCheckBox("自動適應人聲音量（建議：先量測人聲，再自動計算靈敏度）")
        self.auto_box.setChecked(settings["auto_sensitivity"])
        box.addWidget(self.auto_box)
        note = QLabel(DUCK_NOTE)
        note.setWordWrap(True)
        box.addWidget(note)
        layout.addWidget(duck)

        beat = QGroupBox("節拍（把剪點對到拍子上）")
        box = QVBoxLayout(beat)
        self.target_label = QLabel(NO_TARGET)
        self.target_label.setWordWrap(True)
        box.addWidget(self.target_label)
        row = QHBoxLayout()
        self.beat_btn = QPushButton("分析節拍")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        row.addWidget(self.beat_btn)
        row.addWidget(self.progress_bar)
        row.addWidget(self.status_label, 1)
        box.addLayout(row)
        self.report_box = QPlainTextEdit()
        self.report_box.setReadOnly(True)
        self.report_box.setPlaceholderText(REPORT_HINT)
        self.report_box.setMinimumHeight(220)
        box.addWidget(self.report_box, 1)
        layout.addWidget(beat, 1)
        self.resize(620, 560)

        self.worker = BeatWorker(self)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.strength_spin.valueChanged.connect(self.collect_settings)
        self.sensitivity_spin.valueChanged.connect(self.collect_settings)
        self.auto_box.toggled.connect(self.collect_settings)
        self.beat_btn.clicked.connect(self.start_beats)
        self._sync()

    # ----- 閃避設定 -----
    def collect_settings(self, *_args):
        """畫面上的值寫進這次開啟的設定（ducking，跟一般版同一個區塊；預設音量那一項照舊留著）。"""
        kept = self.config.get("ducking") if isinstance(self.config.get("ducking"), dict) else {}
        self.config["ducking"] = {
            **kept,
            "duck_strength": round(self.strength_spin.value(), 1),
            "duck_sensitivity": round(self.sensitivity_spin.value(), 2),
            "auto_sensitivity": self.auto_box.isChecked(),
        }
        self._sync()
        return audio.resolve_ducking_settings(self.config)

    # ----- 對象 -----
    def item(self):
        tracks = self.player.tracks["music"]
        return tracks[self.target] if self.target is not None and 0 <= self.target < len(tracks) else None

    def set_target(self, index):
        """換成音樂軌第 index 段（None＝沒選取音樂）。報告留著，上面寫著是哪一段的。"""
        self.target = index
        self._sync()

    def _sync(self):
        self.sensitivity_spin.setEnabled(not self.auto_box.isChecked())  # 自動開著：手動那格不能改，免得混淆
        item = self.item()
        if item is None:
            self.target_label.setText(NO_TARGET)
        else:
            self.target_label.setText(f"音樂第 {self.target + 1} 段：{os.path.basename(item['path'])}")
        self.beat_btn.setEnabled(item is not None and not self.worker.busy)
        self.beat_btn.setText("分析中…" if self.worker.busy else "分析節拍")
        self.progress_bar.setVisible(self.worker.busy)

    # ----- 節拍 -----
    def busy(self):
        return self.worker.busy

    def start_beats(self):
        if self.worker.busy:
            return False
        item = self.item()
        if item is None:
            return self._refuse(NO_TARGET)
        if not os.path.exists(item["path"]):
            return self._refuse(NO_FILE)
        if not ffmpeg_available():
            return self._refuse(NO_FFMPEG)
        self.worker.start(item, self.player.media_path or "", self.player.media_duration(), self.config)
        self.progress_bar.setValue(0)
        self.status_label.setText(f"分析中：{os.path.basename(item['path'])}")
        self._sync()
        return True

    def _refuse(self, text):
        self.status_label.setText(text)
        return False

    def _on_progress(self, ratio, message):
        self.progress_bar.setValue(int(max(0.0, min(ratio, 1.0)) * 1000))
        if message:
            self.status_label.setText(f"分析中：{message}")

    def _on_finished(self, payload):
        self.worker.busy = False
        self.last_payload = payload
        self.report_box.setPlainText(beat_report(payload))
        self.status_label.setText("節拍分析完成。")
        self._sync()

    def _on_failed(self, exc):
        self.worker.busy = False
        err = describe_exception(exc)
        detail = f"（{err.details}）" if err.details and err.details != str(err) else ""
        self.status_label.setText(f"節拍分析失敗：{err}{detail}")
        self._sync()
