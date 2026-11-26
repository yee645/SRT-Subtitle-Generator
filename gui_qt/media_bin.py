# -*- coding: utf-8 -*-
"""
素材庫（剪輯器版面 E-4）：一次匯入一批影片、圖片、聲音，看縮圖與長度，再拖到時間軸（或按〔加到播放頭〕）。

規則（收哪些檔、去重、拖到哪一列放哪一軌）在 `subtitle/mediabin.py`；縮圖與長度在背景抽（ffmpeg／ffprobe，
晚到的結果照路徑對回去，素材已經拿掉的丟掉）。放上時間軸照舊走 `PlayerPanel.add_track`（讀不出來就講、不放）。
素材庫只是這次開啟的清單，不存進專案。
"""
import os
import subprocess
import tempfile
import threading

from PySide6.QtCore import QMimeData, QObject, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
    QWidget,
)

from subtitle import assemble as assemble_mod
from subtitle import mediabin

THUMB_SIZE = QSize(112, 63)  # 16:9
EMPTY_TEXT = "匯入影片、圖片、聲音之後排在這裡：拖到下面的時間軸上，或選好按〔加到播放頭〕。"
KIND_ICONS = {"video": "film", "image": "image", "audio": "music"}


class _Probe(QObject):
    """背景抽縮圖與量長度；結果用訊號送回主執行緒。"""

    done = Signal(str, str, object)  # 路徑、縮圖檔（空字串＝沒有）、長度（秒；None＝量不到或圖片）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.folder = tempfile.mkdtemp(prefix="srt-bin-")

    def start(self, entry):
        threading.Thread(target=self._run, args=(dict(entry),), daemon=True).start()

    def _run(self, entry):
        path, kind = entry["path"], entry["kind"]
        thumb, seconds = "", None
        try:
            if kind == "image":
                thumb = path
            else:
                seconds = assemble_mod.probe_seconds(path)
                if kind == "video":
                    thumb = self._frame(path, seconds)
        except Exception:  # noqa: BLE001 — 抽不到就用圖示，不影響素材本身
            pass
        self.done.emit(path, thumb, seconds)

    def _frame(self, path, seconds):
        out = os.path.join(self.folder, f"{abs(hash(path))}.png")
        at = min(1.0, (seconds or 0) / 2)
        result = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.3f}", "-i", path, "-frames:v", "1",
                                 "-vf", f"scale={THUMB_SIZE.width() * 2}:-2", out],
                                capture_output=True, timeout=60)
        return out if result.returncode == 0 and os.path.isfile(out) else ""


class _BinList(QListWidget):
    """拖出去的是檔案路徑（file:// 網址）：時間軸、別的程式都認得。"""

    def mimeData(self, items):  # noqa: N802
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(item.data(Qt.UserRole)) for item in items])
        return data

    def mimeTypes(self):  # noqa: N802
        return ["text/uri-list"]


class MediaBin(QWidget):
    """素材庫：〔匯入素材…〕＋縮圖格＋〔加到播放頭〕〔開成主片〕〔移除〕。"""

    changed = Signal()

    def __init__(self, player, icon_for=None, parent=None):
        super().__init__(parent)
        self.player = player
        self.entries = []
        self.info = {}  # 路徑 → {"thumb", "seconds"}
        self._icon_for = icon_for or (lambda name: QIcon())
        self.import_btn = QPushButton("匯入素材…")
        self.import_btn.setToolTip("一次選多個影片、圖片、聲音放進素材庫（不會改動原始檔案）")
        self.list = _BinList()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(THUMB_SIZE)
        self.list.setGridSize(QSize(THUMB_SIZE.width() + 16, THUMB_SIZE.height() + 40))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setWordWrap(True)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setDragEnabled(True)
        self.list.setDragDropMode(QAbstractItemView.DragOnly)
        self.list.setMinimumHeight(2 * self.list.gridSize().height() + 8)  # 兩排放得下
        self.empty_label = QLabel(EMPTY_TEXT)
        self.empty_label.setWordWrap(True)
        self.empty_label.setProperty("secondary", True)
        self.add_btn = QPushButton("加到播放頭")
        self.add_btn.setToolTip("選取的素材放到播放頭的位置：影片與圖片疊在畫面上、聲音放音樂軌（一個接一個）")
        self.main_btn = QPushButton("開成主片")
        self.main_btn.setToolTip("把選取的影片當主片開啟（換主片會清掉素材軌與畫面調整，沒存的會先問）")
        self.remove_btn = QPushButton("移除")
        self.remove_btn.setToolTip("從素材庫拿掉（不刪檔案，已經放上時間軸的不受影響）")

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        for btn in (self.add_btn, self.main_btn, self.remove_btn):
            buttons.addWidget(btn)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.import_btn)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.list, 1)
        layout.addLayout(buttons)

        self._probe = _Probe(self)
        self._probe.done.connect(self._on_probed)
        self.import_btn.clicked.connect(lambda _c=False: self.choose_files())
        self.add_btn.clicked.connect(lambda _c=False: self.add_selected())
        self.main_btn.clicked.connect(lambda _c=False: self.open_selected_as_main())
        self.remove_btn.clicked.connect(lambda _c=False: self.remove_selected())
        self.list.itemSelectionChanged.connect(self._update_buttons)
        self.list.itemDoubleClicked.connect(lambda _item: self.add_selected())
        self._refresh()

    # ----- 匯入 -----
    def choose_files(self):
        start = os.path.dirname(self.player.media_path or "")
        paths, _ = QFileDialog.getOpenFileNames(self, "匯入素材", start, mediabin.file_filter())
        return self.add_files(paths) if paths else ([], [])

    def add_files(self, paths):
        """加一批檔案；回傳 (加了哪些, 略過哪些)。略過的在下面那一行講。"""
        self.entries, added, skipped = mediabin.add_paths(self.entries, paths)
        for entry in added:
            self.info[entry["path"]] = {"thumb": "", "seconds": None}
            self._probe.start(entry)
        self._refresh()
        if skipped:
            names = "、".join(f"{os.path.basename(p)}（{why}）" for p, why in skipped[:3])
            more = f"等 {len(skipped)} 個" if len(skipped) > 3 else ""
            self.empty_label.setText(f"加了 {len(added)} 個；略過 {names}{more}。")
            self.empty_label.show()
        if added or skipped:
            self.changed.emit()
        return added, skipped

    def _on_probed(self, path, thumb, seconds):
        if path not in self.info:
            return  # 已經從素材庫拿掉
        self.info[path] = {"thumb": thumb, "seconds": seconds}
        self._refresh()

    # ----- 動作 -----
    def selected_paths(self):
        return [item.data(Qt.UserRole) for item in self.list.selectedItems()]

    def add_selected(self):
        """選取的素材放到播放頭（一個接一個）；回傳放了幾個。"""
        paths = self.selected_paths()
        if not paths:
            return 0
        return self.player.drop_files(paths, "", self.player.player.position() / 1000.0)

    def open_selected_as_main(self):
        paths = self.selected_paths()
        if len(paths) != 1 or mediabin.kind_of(paths[0]) != "video":
            return False
        if not self.player._maybe_drop_project():  # 換影片會清掉素材軌與畫面調整：同〔開啟影片〕
            return False
        self.player.open_video(paths[0])
        return True

    def remove_selected(self):
        paths = self.selected_paths()
        self.entries = mediabin.remove_paths(self.entries, paths)
        for path in paths:
            self.info.pop(path, None)
        self._refresh()
        if paths:
            self.changed.emit()
        return len(paths)

    # ----- 畫面 -----
    def _refresh(self):
        keep = set(self.selected_paths())
        self.list.blockSignals(True)
        try:
            self.list.clear()
            for entry in self.entries:
                path, kind = entry["path"], entry["kind"]
                info = self.info.get(path, {})
                label = os.path.basename(path)
                length = mediabin.duration_label(info.get("seconds"))
                item = QListWidgetItem(f"{label}\n{length}" if length else label)
                item.setData(Qt.UserRole, path)
                item.setToolTip(f"{mediabin.KIND_NAMES[kind]}：{path}")
                thumb = info.get("thumb")
                pix = QPixmap(thumb) if thumb else QPixmap()
                if not pix.isNull():
                    item.setIcon(QIcon(pix.scaled(THUMB_SIZE * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
                else:
                    item.setIcon(self._icon_for(KIND_ICONS[kind]))
                item.setSizeHint(self.list.gridSize())
                self.list.addItem(item)
                item.setSelected(path in keep)
        finally:
            self.list.blockSignals(False)
        if not self.entries:
            self.empty_label.setText(EMPTY_TEXT)
        self.empty_label.setVisible(not self.entries or self.empty_label.text() != EMPTY_TEXT)
        self.list.setVisible(bool(self.entries))
        self._update_buttons()

    def _update_buttons(self):
        paths = self.selected_paths()
        ready = bool(self.player.media_path)
        self.add_btn.setEnabled(bool(paths) and ready)
        self.main_btn.setEnabled(len(paths) == 1 and mediabin.kind_of(paths[0]) == "video")
        self.remove_btn.setEnabled(bool(paths))
