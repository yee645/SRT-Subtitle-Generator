# -*- coding: utf-8 -*-
"""
縮圖條：給 3.0 時間軸畫影片縮圖用的資料來源（ROADMAP_3.0 第 3 項第二階段）。

時間軸的縮圖不必每一格都精準到那一幀——剪輯軟體的縮圖條本來就是「這一段
大概長這樣」。所以採**只解關鍵影格**（`-skip_frame nokey`）：解碼器跳過所有
非關鍵影格，一支 5 分鐘 720p、每 2 秒一個關鍵影格的影片，150 張縮圖 1.1 秒
（全解碼再每 2 秒取一張要 6.2 秒）。

兩種極端另外處理：

- **關鍵影格太密**（每一幀都是關鍵影格的素材）：`select` 濾鏡只留跟上一張
  至少隔 `min_interval` 秒的，不會一支 20 秒的片子吐出 600 張。
- **關鍵影格太疏**（螢幕錄影常見 10 秒以上一個）：相鄰兩張隔超過 `max_gap`
  的地方，逐點 seek 補抽（每 `max_gap` 秒一張，最多 `MAX_FILL` 張），時間軸
  拉近時不會一大段都是同一張。

時間：縮圖條最後一個濾鏡接 `showinfo`，從 stderr 讀每一張的 `pts_time`；第 n
張對應輸出檔 `%06d.jpg` 的 n+1 號。

縮圖存成 JPEG 檔（高 90px，約 2～4 KB 一張），放在 `filmstrip_cache/<鍵>/`，
旁邊一份 `index.json` 記每張的時間。鍵是路徑＋大小＋修改時間＋高度＋間距設定，
影片一改就重抽。先抽到暫存資料夾、完成才換名，抽一半中斷不會留下殘缺的快取。
上限 20 支影片，超過刪最舊的。

零 GUI 依賴：回傳 (秒, 檔案路徑) 清單，介面自己決定怎麼載入圖檔。
"""

from __future__ import annotations

import bisect
import hashlib
import json
import os
import re
import shutil
import subprocess
from typing import Callable, List, Optional, Tuple

DEFAULT_HEIGHT = 90
DEFAULT_MIN_INTERVAL = 1.0
DEFAULT_MAX_GAP = 10.0
MAX_FILL = 120
JPEG_QUALITY = 5  # ffmpeg -q:v，2（最好）～31（最差）

CACHE_DIR = "filmstrip_cache"
MAX_CACHE_ENTRIES = 20
_INDEX = "index.json"
_FORMAT_VERSION = 1

_SHOWINFO = re.compile(rb"\bn:\s*(\d+)\b.*?\bpts_time:\s*(-?[\d.]+)")

Frame = Tuple[float, str]


class FilmstripError(RuntimeError):
    """抽不出畫面（沒有影像軌、檔案壞掉、沒有 ffmpeg）。"""


class FilmstripCancelled(RuntimeError):
    """呼叫端中途取消。"""


class Filmstrip:
    """一支影片的縮圖條：frames 依時間排序，每張是 (秒, JPEG 檔路徑)。"""

    __slots__ = ("height", "duration", "frames", "_times")

    def __init__(self, height: int, duration: float, frames: List[Frame]):
        self.height = int(height)
        self.duration = float(duration)
        self.frames = sorted(frames)
        self._times = [t for t, _ in self.frames]

    def __len__(self):
        return len(self.frames)

    def nearest(self, seconds: float) -> Optional[Frame]:
        """離 seconds 最近的一張；沒有縮圖時回傳 None。"""
        if not self.frames:
            return None
        i = bisect.bisect_left(self._times, seconds)
        if i == 0:
            return self.frames[0]
        if i == len(self.frames):
            return self.frames[-1]
        before, after = self.frames[i - 1], self.frames[i]
        return before if seconds - before[0] <= after[0] - seconds else after

    def slots(self, start: float, end: float, count: int) -> List[Optional[Frame]]:
        """
        把 [start, end) 秒切成 count 格，每格給離格子中心最近的縮圖。

        格子中心在片頭之前或片尾之後（duration 已知時）給 None，時間軸那一格
        就留空，不會把第一張／最後一張一直重複畫到畫面外。
        """
        count = int(count)
        if count <= 0 or end <= start:
            return []
        width = (end - start) / count
        out = []
        for i in range(count):
            center = start + (i + 0.5) * width
            if center < 0 or (self.duration > 0 and center > self.duration):
                out.append(None)
            else:
                out.append(self.nearest(center))
        return out


def _check_args(height, min_interval, max_gap):
    height = int(height)
    if not 16 <= height <= 720:
        raise ValueError(f"縮圖高度要在 16～720 之間：{height}")
    min_interval = float(min_interval)
    max_gap = float(max_gap)
    if min_interval <= 0 or max_gap < min_interval:
        raise ValueError(f"間距設定不合理：min_interval={min_interval} max_gap={max_gap}")
    return height, min_interval, max_gap


def probe_duration(media_path: str) -> float:
    """
    用 ffprobe 量片長；量不到回傳 0.0（未知）。

    不用 `media.probe_duration`：它量不到時回傳保底值 60 秒，跟一支真的
    60 秒的片子分不出來，補空檔會算錯。
    """
    try:
        completed = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", media_path],
            capture_output=True, timeout=30)
        value = float((completed.stdout or b"").decode("utf-8", "ignore").strip())
        return value if value > 0 else 0.0
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def keyframe_command(media_path: str, out_dir: str, height: int,
                     min_interval: float) -> list:
    """只解關鍵影格、限制最小間距、縮成 height 高的 JPEG，並用 showinfo 報時間。"""
    select = f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{min_interval:g})'"
    return ["ffmpeg", "-hide_banner", "-nostats", "-nostdin", "-v", "info",
            "-skip_frame", "nokey", "-i", media_path, "-an", "-sn", "-dn",
            "-vf", f"{select},scale=-2:{height},showinfo",
            "-fps_mode", "passthrough", "-q:v", str(JPEG_QUALITY),
            os.path.join(out_dir, "%06d.jpg")]


def seek_command(media_path: str, seconds: float, out_path: str, height: int) -> list:
    """精準 seek 到 seconds 抽一張（補關鍵影格之間太大的空檔用）。"""
    return ["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{seconds:.3f}",
            "-i", media_path, "-an", "-sn", "-dn", "-frames:v", "1",
            "-vf", f"scale=-2:{height}", "-q:v", str(JPEG_QUALITY), out_path]


def gap_fill_times(times: List[float], duration: float, max_gap: float,
                   limit: int = MAX_FILL) -> List[float]:
    """
    關鍵影格之間（含最後一張到片尾）隔超過 max_gap 的地方，每 max_gap 秒補一
    個時間點；最多 limit 個。純計算，不碰檔案。
    """
    points = sorted(times)
    if duration > 0:
        points = points + [duration]
    fills = []
    for a, b in zip(points, points[1:]):
        t = a + max_gap
        while b - t > max_gap * 0.25 and len(fills) < limit:
            fills.append(round(t, 3))
            t += max_gap
    return fills


def extract(media_path: str, out_dir: str,
            height: int = DEFAULT_HEIGHT,
            min_interval: float = DEFAULT_MIN_INTERVAL,
            max_gap: float = DEFAULT_MAX_GAP,
            progress_cb: Optional[Callable[[float], None]] = None,
            cancel: Optional[Callable[[], bool]] = None,
            duration: Optional[float] = None) -> Filmstrip:
    """
    抽縮圖到 out_dir（不經快取；資料夾要先存在）。

    沒有影像軌或解碼失敗拋 FilmstripError；cancel() 回 True 就停下並拋
    FilmstripCancelled。duration 沒給時用 ffprobe 量（補空檔與進度都要用）。
    """
    height, min_interval, max_gap = _check_args(height, min_interval, max_gap)
    if not os.path.isfile(media_path):
        raise FilmstripError(f"找不到檔案：{media_path}")
    if not duration:
        duration = probe_duration(media_path)

    try:
        proc = subprocess.Popen(keyframe_command(media_path, out_dir, height, min_interval),
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except OSError as exc:
        raise FilmstripError(f"無法執行 ffmpeg：{exc}") from exc

    times = {}
    last_lines = []
    try:
        for line in proc.stderr:
            if cancel is not None and cancel():
                raise FilmstripCancelled("已取消")
            match = _SHOWINFO.search(line)
            if match:
                t = float(match.group(2))
                times[int(match.group(1))] = t
                if progress_cb is not None and duration > 0:
                    progress_cb(min(t / duration, 1.0) * 0.9)
            else:
                last_lines = (last_lines + [line])[-5:]
        proc.wait()
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    finally:
        proc.stderr.close()

    frames = []
    for n, t in sorted(times.items()):
        path = os.path.join(out_dir, f"{n + 1:06d}.jpg")
        if os.path.isfile(path):
            frames.append((max(t, 0.0), path))
    if not frames:
        detail = [x.decode("utf-8", "ignore").strip() for x in last_lines if x.strip()]
        raise FilmstripError("抽不出畫面（沒有影像軌或檔案無法讀取）"
                             + (f"：{detail[-1]}" if detail else ""))

    fills = gap_fill_times([t for t, _ in frames], duration, max_gap)
    for i, t in enumerate(fills):
        if cancel is not None and cancel():
            raise FilmstripCancelled("已取消")
        path = os.path.join(out_dir, f"fill_{i:04d}.jpg")
        subprocess.run(seek_command(media_path, t, path, height),
                       capture_output=True, timeout=60)
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            frames.append((t, path))
        if progress_cb is not None:
            progress_cb(0.9 + 0.1 * (i + 1) / len(fills))
    if progress_cb is not None:
        progress_cb(1.0)
    return Filmstrip(height, duration, frames)


# ===== 快取 =============================================================

def cache_key(media_path: str, height: int = DEFAULT_HEIGHT,
              min_interval: float = DEFAULT_MIN_INTERVAL,
              max_gap: float = DEFAULT_MAX_GAP) -> str:
    """快取鍵（sha1）：路徑＋大小＋修改時間＋高度＋間距。檔案不存在時拋 OSError。"""
    stat = os.stat(media_path)
    payload = json.dumps({
        "path": os.path.abspath(media_path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "height": int(height),
        "min_interval": float(min_interval),
        "max_gap": float(max_gap),
        "version": _FORMAT_VERSION,
    }, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _write_index(folder: str, strip: Filmstrip) -> None:
    data = {
        "version": _FORMAT_VERSION,
        "height": strip.height,
        "duration": strip.duration,
        "frames": [[t, os.path.basename(p)] for t, p in strip.frames],
    }
    with open(os.path.join(folder, _INDEX), "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def read_index(folder: str) -> Optional[Filmstrip]:
    """讀快取資料夾；索引壞掉、版本不符、圖檔少了任何一張都回傳 None。"""
    try:
        with open(os.path.join(folder, _INDEX), encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("version") != _FORMAT_VERSION:
            return None
        frames = []
        for t, name in data["frames"]:
            if os.path.basename(name) != name:  # 索引只該有檔名，不跳出資料夾
                return None
            path = os.path.join(folder, name)
            if not os.path.isfile(path):
                return None
            frames.append((float(t), path))
        if not frames:
            return None
        return Filmstrip(int(data["height"]), float(data["duration"]), frames)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _prune_cache(cache_dir: str, keep: str) -> None:
    """超過上限時刪最舊的快取資料夾（剛寫好的 keep 不刪）。"""
    try:
        entries = [os.path.join(cache_dir, name) for name in os.listdir(cache_dir)
                   if len(name) == 40 and os.path.isdir(os.path.join(cache_dir, name))]
        if len(entries) <= MAX_CACHE_ENTRIES:
            return
        entries.sort(key=os.path.getmtime)
        for path in entries[:len(entries) - MAX_CACHE_ENTRIES]:
            if os.path.abspath(path) != os.path.abspath(keep):
                shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def load_filmstrip(media_path: str,
                   height: int = DEFAULT_HEIGHT,
                   min_interval: float = DEFAULT_MIN_INTERVAL,
                   max_gap: float = DEFAULT_MAX_GAP,
                   cache_dir: str = CACHE_DIR,
                   progress_cb: Optional[Callable[[float], None]] = None,
                   cancel: Optional[Callable[[], bool]] = None) -> Filmstrip:
    """
    取縮圖條：快取有就直接用，沒有就抽並寫進快取。

    抽的過程在 `<鍵>.tmp-<pid>` 暫存資料夾，完成才換名成 `<鍵>`；中途失敗或
    取消會把暫存資料夾刪掉，不留下殘缺的快取。
    """
    height, min_interval, max_gap = _check_args(height, min_interval, max_gap)
    try:
        key = cache_key(media_path, height, min_interval, max_gap)
    except OSError as exc:
        raise FilmstripError(f"找不到檔案：{media_path}") from exc
    final = os.path.join(cache_dir, key)
    cached = read_index(final)
    if cached is not None:
        if progress_cb is not None:
            progress_cb(1.0)
        return cached

    temp = f"{final}.tmp-{os.getpid()}"
    shutil.rmtree(temp, ignore_errors=True)
    os.makedirs(temp)
    try:
        strip = extract(media_path, temp, height, min_interval, max_gap,
                        progress_cb=progress_cb, cancel=cancel)
        _write_index(temp, strip)
        shutil.rmtree(final, ignore_errors=True)  # 壞掉的舊快取
        os.replace(temp, final)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    _prune_cache(cache_dir, final)
    loaded = read_index(final)
    return loaded if loaded is not None else strip


def clear_cache(cache_dir: str = CACHE_DIR) -> int:
    """清空縮圖快取，回傳刪除的影片數。"""
    removed = 0
    try:
        for name in os.listdir(cache_dir):
            path = os.path.join(cache_dir, name)
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
    except OSError:
        pass
    return removed
