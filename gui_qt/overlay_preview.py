# -*- coding: utf-8 -*-
"""
3.0 第 7 項第四階段：在播放器上預覽疊加軌（B-roll／圖片）。

擺法跟輸出一模一樣：框的位置與大小用 `assemble.overlay_box`（輸出組 ffmpeg 指令也是
用它），素材在框裡等比縮小、置中、四周補黑（`assemble.fit_inside`，同 ffmpeg 的
`force_original_aspect_ratio=decrease`＋`pad`）。哪幾段在這一刻出現、後加的疊在上面，
照 `assemble.overlays_at`。

* **圖片**：照實畫（讀一次、記住）。
* **影片**：不另外開一個播放器同步播（第二路解碼太重，還要跟主片對時）。改成在背景用
  ffmpeg 抽「這一刻的那一格」，**每 `POSTER_STEP` 秒換一格**；抽好之前先畫同一支上一
  次抽到的那格，再沒有就畫黑框寫檔名。所以播放中影片素材看起來是一秒一跳的幻燈片，
  位置與內容是對的、動作不是。

疊在影片上、字幕底下（輸出時字幕另存 .srt，不燒進去；預覽照舊把字幕畫在最上面，才看得
到字幕有沒有被擋到）。
"""
from __future__ import annotations

import os
import queue
import subprocess
import threading

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsSimpleTextItem

from subtitle import assemble as assemble_mod

POSTER_STEP = 1.0     # 影片素材的預覽格多久換一次（秒）
POSTER_WIDTH = 480    # 抽出來的預覽格縮到多寬（夠看清楚就好，抽得快）
MAX_POSTERS = 120     # 記住幾張預覽格（大約兩分鐘的 B-roll）
Z_VALUE = 0.5         # 影片是 0、字幕是 1


def poster_time(source_seconds):
    """影片素材的第幾秒要用哪一格預覽：往下取到 POSTER_STEP 的倍數。"""
    step = POSTER_STEP
    return round(max(0.0, float(source_seconds)) // step * step, 3)


def grab_frame(path, seconds, width=POSTER_WIDTH):
    """用 ffmpeg 抽 path 第 seconds 秒的那一格，縮到 width 寬，回傳 PNG bytes（失敗回傳 b""）。"""
    try:
        done = subprocess.run(
            ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{float(seconds):.3f}", "-i", path,
             "-frames:v", "1", "-vf", f"scale={int(width)}:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return b""
    return done.stdout if done.returncode == 0 else b""


class OverlayPreview(QObject):
    """
    管疊在播放器畫面上的那一層。`show(...)` 每次位置一變就叫；跟上一次畫的一樣就不重畫。
    影片素材的預覽格在背景執行緒抽，抽好送 `updated`，播放器再叫一次 show。
    """

    _grabbed = Signal()   # 背景執行緒 → 主執行緒：有新抽好的格
    updated = Signal()    # 有新的預覽格可以畫了（播放器接這個重畫）

    def __init__(self, scene, parent=None, grabber=grab_frame):
        super().__init__(parent)
        self.scene = scene
        self.items = []          # 目前畫著的框（給測試用）
        self.shown = []          # 目前畫著的是哪幾段：[(第幾段, 用哪張圖：路徑或 (路徑, 秒) 或 None)]
        self._signature = None
        self._images = {}        # 圖片：路徑 → QImage
        self._posters = {}       # 影片：(路徑, 秒) → QImage
        self._latest = {}        # 影片：路徑 → 最近一張抽到的 (路徑, 秒)
        self._pending = set()
        self._failed = set()     # 抽不到的格：不重試（不然每一刻都重跑一次 ffmpeg）
        self._results = queue.Queue()
        self._grabber = grabber
        self._queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._work, daemon=True)
        self._thread.start()
        self._grabbed.connect(self._on_grabbed)

    # ---- 對外 ----------------------------------------------------------

    def show(self, overlays, seconds, total, video_rect, native_size=None, enabled=True):
        """
        畫出第 seconds 秒該出現的疊加。video_rect：影片在場景裡實際佔的矩形；
        native_size：影片原本的 (寬, 高)，算框用（跟輸出的畫布同一個尺寸）。
        """
        active = assemble_mod.overlays_at(overlays, seconds, total) if enabled and total > 0 else []
        plan = []
        for index, source in active:
            item = overlays[index]
            path = str(item.get("path", ""))
            rect = tuple(float(v) for v in (item.get("rect") or (0.0, 0.0, 1.0, 1.0)))
            if source is None:
                art = path if self._image(path) is not None else None
            else:
                key = (path, poster_time(source))
                if key not in self._posters:
                    if key not in self._failed:
                        self._request(key)
                    key = self._latest.get(path)  # 先用上一次抽到的那格
                art = key
            plan.append((index, path, rect, art))
        native = tuple(native_size) if native_size else None
        signature = (tuple(plan), (video_rect.x(), video_rect.y(), video_rect.width(), video_rect.height()),
                     native)
        if signature == self._signature:
            return False
        self._signature = signature
        self._clear()
        canvas_w, canvas_h = native if native and native[0] > 0 and native[1] > 0 else \
            (video_rect.width(), video_rect.height())
        scale_x = video_rect.width() / float(canvas_w) if canvas_w else 1.0
        scale_y = video_rect.height() / float(canvas_h) if canvas_h else 1.0
        for index, path, rect, art in plan:
            ox, oy, ow, oh = assemble_mod.overlay_box(rect, int(round(canvas_w)), int(round(canvas_h)))
            box = QRectF(video_rect.x() + ox * scale_x, video_rect.y() + oy * scale_y,
                         ow * scale_x, oh * scale_y)
            frame = QGraphicsRectItem(box)
            frame.setBrush(QBrush(QColor(0, 0, 0)))
            frame.setPen(QPen(Qt.NoPen))
            frame.setZValue(Z_VALUE + index * 0.001)  # 後加的疊在上面（跟輸出一樣）
            image = self._image(art) if isinstance(art, str) else self._posters.get(art) if art else None
            if image is not None and not image.isNull():
                x, y, w, h = assemble_mod.fit_inside(image.width(), image.height(), box.width(), box.height())
                pixmap = QPixmap.fromImage(image).scaled(max(1, round(w)), max(1, round(h)),
                                                         Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                picture = QGraphicsPixmapItem(pixmap, frame)
                picture.setPos(box.x() + x, box.y() + y)
            else:
                label = QGraphicsSimpleTextItem(f"{os.path.basename(path)}（正在載入預覽…）", frame)
                font = QFont()
                font.setPixelSize(max(10, min(16, int(box.height() / 8))))
                label.setFont(font)
                label.setBrush(QBrush(QColor(230, 230, 230)))
                label.setPos(box.x() + 6, box.y() + 6)
            frame.setFlag(QGraphicsRectItem.ItemClipsChildrenToShape, True)
            self.scene.addItem(frame)
            self.items.append(frame)
            self.shown.append((index, art))
        return True

    def stop(self, timeout=2.0):
        """關視窗前：停掉背景抽格的執行緒。"""
        self._stop.set()
        self._queue.put(None)
        self._thread.join(timeout)

    # ---- 內部 ----------------------------------------------------------

    def _clear(self):
        for item in self.items:
            self.scene.removeItem(item)
        self.items, self.shown = [], []

    def _image(self, path):
        if path not in self._images:
            image = QImage(path)
            self._images[path] = None if image.isNull() else image
        return self._images[path]

    def _request(self, key):
        if key not in self._pending:
            self._pending.add(key)
            self._queue.put(key)

    def _work(self):
        while not self._stop.is_set():
            key = self._queue.get()
            if key is None or self._stop.is_set():
                return
            data = self._grabber(key[0], key[1])
            if self._stop.is_set():
                return
            self._results.put((key, data))
            try:
                self._grabbed.emit()
            except RuntimeError:  # 視窗已經關了（物件被刪掉），結果不要了
                return

    def _on_grabbed(self):
        # 在主執行緒把 bytes 轉成 QImage（QImage 可以跨執行緒，但統一在這裡做比較單純）
        while True:
            try:
                key, data = self._results.get_nowait()
            except queue.Empty:
                break
            self._pending.discard(key)
            image = QImage.fromData(data, "PNG") if data else QImage()
            if image.isNull():
                self._failed.add(key)  # 之後照舊畫黑框寫檔名
                continue
            self._posters[key] = image
            self._latest[key[0]] = key
            # 太多就丟最舊的（每支影片最近抽到的那格留著，換格時才不會閃黑框）
            keep = set(self._latest.values())
            for old in [k for k in self._posters if k not in keep][:max(0, len(self._posters) - MAX_POSTERS)]:
                del self._posters[old]
        self._signature = None  # 下一次 show 一定重畫
        self.updated.emit()
