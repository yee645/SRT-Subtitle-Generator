# -*- coding: utf-8 -*-
"""
3.0 第 6 項：代理檔——大片子編輯時換成小一號、好跳轉的版本，輸出時仍用原檔。

為什麼要：第 0 項實測 1080p 在時間軸上跳轉最慢近 0.2 秒（x264 預設關鍵影格約
8 秒一張，跳到兩張之間要從前一張一路解過來）。代理檔做兩件事：

* **縮小**：短邊 1080 以上（含直式 1080x1920）才做，短邊縮到 540，解一格的量少
  四分之三。
* **關鍵影格密**：每 12 格一張，跳到任何位置最多往前解 11 格；再加
  `-tune fastdecode`（關掉 CABAC 與去區塊，解碼更省）。

時間必須跟原檔一格不差（剪點、字幕都照播放器的時間算），所以不改影格率、不丟
格、聲音一起轉，做完量一次長度，跟原檔差太多就當失敗、不用它。

快取照縮圖條的規則：鍵＝路徑＋大小＋修改時間＋參數；先寫 `.tmp` 再換名，中途
失敗或取消不留下殘缺的檔；超過上限（檔數或總大小）刪最舊的。

零 GUI 依賴；Qt 那一層只負責「什麼時候換成代理檔播」。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from typing import Callable, Optional

CACHE_DIR = "proxy_cache"
THRESHOLD = 1080       # 短邊到這麼大才做代理檔
PROXY_SHORT_SIDE = 540  # 代理檔的短邊
GOP = 12               # 關鍵影格間距（格）
CRF = 26
MAX_CACHE_FILES = 8
MAX_CACHE_BYTES = 6 * 1024 ** 3
DURATION_TOLERANCE = 0.25  # 代理檔與原檔長度最多差幾秒（聲音編碼的前置延遲約幾十毫秒）
STALE_TMP_SECONDS = 24 * 3600
_FORMAT_VERSION = 1


class ProxyError(RuntimeError):
    """做不出代理檔（沒有影像、ffmpeg 失敗、長度對不上）。"""


class ProxyCancelled(RuntimeError):
    """中途取消。"""


# ===== 判斷 =============================================================

def probe_video(media_path: str) -> Optional[dict]:
    """
    讀第一條影像軌的寬高與片長：{"width", "height", "duration"}。

    讀不到（沒有 ffprobe、沒有影像軌、檔案壞掉）回傳 None——**不猜**：
    `media.probe_dimensions` 失敗時回 1920x1080，拿來判斷要不要做代理檔會誤判。
    寬高是**顯示時**的方向（手機直拍的旋轉資訊會換過來），短邊不受影響。
    """
    if not shutil.which("ffprobe"):
        return None
    try:
        completed = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height:stream_side_data=rotation:format=duration",
             "-of", "json", media_path],
            capture_output=True, timeout=30)
        if completed.returncode != 0:
            return None
        data = json.loads(completed.stdout.decode("utf-8", errors="ignore") or "{}")
        streams = data.get("streams") or []
        if not streams:
            return None
        width, height = int(streams[0]["width"]), int(streams[0]["height"])
        rotation = 0
        for side in streams[0].get("side_data_list") or []:
            if "rotation" in side:
                rotation = int(side["rotation"])
        if rotation % 180:
            width, height = height, width
        duration = float((data.get("format") or {}).get("duration") or 0.0)
        if width <= 0 or height <= 0:
            return None
        return {"width": width, "height": height, "duration": duration}
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None


def needs_proxy(width: int, height: int, threshold: int = THRESHOLD) -> bool:
    """短邊到 threshold 才需要（1920x1080、1080x1920、4K 要；1280x720 不要）。"""
    return min(int(width), int(height)) >= threshold


def proxy_size(width: int, height: int, short_side: int = PROXY_SHORT_SIDE) -> tuple:
    """代理檔的寬高：短邊縮到 short_side、比例不變、兩邊都是偶數（x264 的要求）。"""
    width, height = int(width), int(height)
    if width <= 0 or height <= 0:
        raise ValueError("寬高要大於 0")
    scale = short_side / float(min(width, height))
    if scale >= 1:
        return (width - width % 2, height - height % 2)

    def even(value):
        return max(2, int(round(value * scale / 2.0)) * 2)
    return (even(width), even(height))


# ===== 產生 =============================================================

def build_command(media_path: str, output_path: str, width: int, height: int) -> list:
    """ffmpeg 指令：縮小、關鍵影格密、聲音轉 AAC；時間戳照原檔（不改影格率、不丟格）。"""
    out_w, out_h = proxy_size(width, height)
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", media_path,
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", f"scale={out_w}:{out_h}",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "fastdecode", "-crf", str(CRF),
        "-g", str(GOP), "-keyint_min", str(GOP), "-sc_threshold", "0",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-f", "mp4",
        "-progress", "pipe:1", output_path,
    ]


def make_proxy(media_path: str, output_path: str,
               info: Optional[dict] = None,
               progress_cb: Optional[Callable[[float], None]] = None,
               cancel: Optional[Callable[[], bool]] = None) -> str:
    """
    產生代理檔到 output_path（先寫 `.tmp` 再換名）。info 省略時自己量。

    取消拋 ProxyCancelled；沒有影像軌、ffmpeg 失敗、做出來的長度跟原檔差超過
    DURATION_TOLERANCE 拋 ProxyError。任何失敗都不留下檔案。
    """
    if info is None:
        info = probe_video(media_path)
    if not info:
        raise ProxyError("讀不到影像軌（沒有 ffprobe，或這個檔案沒有畫面）")
    duration = float(info.get("duration") or 0.0)
    temp = output_path + ".tmp"
    command = build_command(media_path, temp, info["width"], info["height"])
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="ignore")
    except OSError as exc:
        raise ProxyError(f"無法執行 ffmpeg：{exc}") from exc
    try:
        for line in process.stdout:
            if cancel is not None and cancel():
                raise ProxyCancelled("已取消")
            key, _, value = line.strip().partition("=")
            if key in ("out_time_us", "out_time_ms") and progress_cb is not None and duration > 0:
                try:
                    progress_cb(min(max(int(value) / 1e6 / duration, 0.0), 0.99))
                except ValueError:
                    pass
        if cancel is not None and cancel():
            raise ProxyCancelled("已取消")
        stderr = process.stderr.read() or ""
        ret = process.wait()
    except BaseException:
        process.kill()
        process.wait()
        _remove(temp)
        raise
    finally:
        process.stdout.close()
        process.stderr.close()
    if ret != 0:
        _remove(temp)
        detail = stderr.strip().splitlines()
        raise ProxyError("ffmpeg 轉檔失敗" + (f"：{detail[-1]}" if detail else ""))
    made = probe_video(temp)
    if not made or (duration > 0 and abs(made["duration"] - duration) > DURATION_TOLERANCE):
        _remove(temp)
        got = f"{made['duration']:.2f}" if made else "讀不到"
        raise ProxyError(f"代理檔長度跟原檔對不上（原檔 {duration:.2f} 秒、代理檔 {got} 秒），不用它")
    try:
        os.replace(temp, output_path)
    except OSError:
        _remove(temp)
        raise
    if progress_cb is not None:
        progress_cb(1.0)
    return output_path


def _remove(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


# ===== 快取 =============================================================

def cache_key(media_path: str) -> str:
    """快取鍵（sha1）：路徑＋大小＋修改時間＋代理檔參數。檔案不存在時拋 OSError。"""
    stat = os.stat(media_path)
    payload = json.dumps({
        "path": os.path.abspath(media_path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "short_side": PROXY_SHORT_SIDE,
        "gop": GOP,
        "crf": CRF,
        "version": _FORMAT_VERSION,
    }, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def cache_path(media_path: str, cache_dir: str = CACHE_DIR) -> str:
    return os.path.join(cache_dir, cache_key(media_path) + ".mp4")


def cached_proxy(media_path: str, cache_dir: str = CACHE_DIR) -> Optional[str]:
    """快取裡已經有這支的代理檔就回傳路徑（順便更新修改時間，清快取時排後面）。"""
    try:
        path = cache_path(media_path, cache_dir)
        if os.path.getsize(path) > 0:
            os.utime(path)
            return path
    except OSError:
        pass
    return None


def prune_cache(cache_dir: str = CACHE_DIR, keep: str = "") -> None:
    """超過檔數或總大小上限就刪最舊的（keep 不刪）；殘留的 .tmp 一併清掉。"""
    try:
        names = os.listdir(cache_dir)
    except OSError:
        return
    entries = []
    for name in names:
        path = os.path.join(cache_dir, name)
        if name.endswith(".mp4.tmp"):
            # 可能是另一個視窗正在做的，不動；放了一天以上的是當掉留下的，清掉
            try:
                if time.time() - os.path.getmtime(path) > STALE_TMP_SECONDS:
                    os.unlink(path)
            except OSError:
                pass
            continue
        if len(name) == 44 and name.endswith(".mp4"):
            try:
                entries.append((os.path.getmtime(path), os.path.getsize(path), path))
            except OSError:
                pass
    entries.sort()
    total = sum(size for _t, size, _p in entries)
    count = len(entries)
    for _t, size, path in entries:
        if count <= MAX_CACHE_FILES and total <= MAX_CACHE_BYTES:
            break
        if keep and os.path.abspath(path) == os.path.abspath(keep):
            continue
        try:
            os.unlink(path)
            count -= 1
            total -= size
        except OSError:
            pass


def load_proxy(media_path: str, cache_dir: str = CACHE_DIR,
               progress_cb: Optional[Callable[[float], None]] = None,
               cancel: Optional[Callable[[], bool]] = None,
               info: Optional[dict] = None) -> Optional[str]:
    """
    取這支影片的代理檔：不需要（短邊不到 1080）回傳 None；快取有就直接用；沒有就
    做一份放進快取。失敗拋 ProxyError、取消拋 ProxyCancelled。
    """
    if info is None:
        info = probe_video(media_path)
    if not info:
        raise ProxyError("讀不到影像軌（沒有 ffprobe，或這個檔案沒有畫面）")
    if not needs_proxy(info["width"], info["height"]):
        return None
    try:
        found = cached_proxy(media_path, cache_dir)
        if found:
            if progress_cb is not None:
                progress_cb(1.0)
            return found
        os.makedirs(cache_dir, exist_ok=True)
        path = cache_path(media_path, cache_dir)
    except OSError as exc:
        raise ProxyError(f"快取資料夾不能用：{exc}") from exc
    make_proxy(media_path, path, info, progress_cb, cancel)
    prune_cache(cache_dir, keep=path)
    return path


def clear_cache(cache_dir: str = CACHE_DIR) -> int:
    """清空代理檔快取，回傳刪掉幾個檔。"""
    removed = 0
    try:
        for name in os.listdir(cache_dir):
            if name.endswith(".mp4") or name.endswith(".mp4.tmp"):
                os.unlink(os.path.join(cache_dir, name))
                removed += 1
    except OSError:
        pass
    return removed
