# -*- coding: utf-8 -*-
"""
波形峰值：給 3.0 時間軸畫波形用的資料來源（ROADMAP_3.0 第 3 項）。

2.x 的波形只出現在「音訊轉影片」的**輸出物**裡（`audiovis.py` 讓 ffmpeg
直接畫進影片），編輯時看不到。時間軸要的是另一種東西：**任何縮放倍率、
任何可見範圍都能立刻畫出來的峰值表**。

作法：

1. ffmpeg 把音軌解成單聲道 16-bit PCM（取樣率 = 每秒格數 × 每格樣本數，
   預設 100 格／秒 × 80 = 8 kHz；畫圖用綽綽有餘，解碼量是 44.1 kHz 的五分之一）。
   串流讀取，一小時的片子也不會一次吃進記憶體。
2. 每格記一對 (最小值, 最大值)——經典的波形畫法，正負兩邊都看得到。
   用內建 `min()`／`max()` 對切片取值，不寫逐樣本的 Python 迴圈。
3. 畫面要多少欄就用 `resample()` 從峰值表合併出來：拉遠時多格併一欄
   （取最小的最小值、最大的最大值，尖峰不會被平均掉），拉近到一欄不到
   一格時取該欄所在的那一格。
4. 結果以二進位存到 `waveform_cache/`（與 config.json 同層，比照
   `transcache.py`）；鍵是路徑＋大小＋修改時間＋每秒格數，檔案一動就重算。
   快取檔損毀或版本不符時靜默重算，寫不進去也不影響結果。

零 GUI 依賴，回傳純資料；Qt 時間軸（第 4 項）與日後任何介面共用。
"""

from __future__ import annotations

import array
import hashlib
import json
import math
import os
import struct
import subprocess
import sys
from typing import Callable, Optional

# 每一格的樣本數：解碼取樣率 = 每秒格數 × 這個數。
SAMPLES_PER_BIN = 80
DEFAULT_BINS_PER_SECOND = 100
# 允許的解析度：太粗時間軸拉近就糊、太細快取檔變大，這幾檔就夠用。
ALLOWED_BINS_PER_SECOND = (25, 50, 100, 200)

CACHE_DIR = "waveform_cache"
MAX_CACHE_FILES = 40
_MAGIC = b"SRTWAVE1"
_HEADER = struct.Struct("<8sII")  # magic、每秒格數、格數

# 一次從 ffmpeg 讀多少格（的樣本）：約 20 秒的音訊，讀取次數與記憶體都小。
_READ_BINS = 2000


class WaveformError(RuntimeError):
    """解不出音訊（沒有音軌、檔案壞掉、沒有 ffmpeg）。"""


class WaveformCancelled(RuntimeError):
    """呼叫端中途取消。"""


class Peaks:
    """
    峰值表：第 i 格涵蓋 [i / bins_per_second, (i + 1) / bins_per_second) 秒，
    `mins[i]`／`maxs[i]` 是該格的最小與最大樣本值（-32768～32767）。
    """

    __slots__ = ("bins_per_second", "mins", "maxs")

    def __init__(self, bins_per_second: int, mins=None, maxs=None):
        self.bins_per_second = int(bins_per_second)
        self.mins = mins if mins is not None else array.array("h")
        self.maxs = maxs if maxs is not None else array.array("h")
        if len(self.mins) != len(self.maxs):
            raise ValueError("mins 與 maxs 長度不同")

    def __len__(self):
        return len(self.mins)

    @property
    def duration(self) -> float:
        """峰值表涵蓋的秒數。"""
        return len(self.mins) / self.bins_per_second

    def __eq__(self, other):
        return (isinstance(other, Peaks)
                and self.bins_per_second == other.bins_per_second
                and self.mins == other.mins and self.maxs == other.maxs)


def _check_rate(bins_per_second: int) -> int:
    rate = int(bins_per_second)
    if rate not in ALLOWED_BINS_PER_SECOND:
        raise ValueError(f"每秒格數只能是 {ALLOWED_BINS_PER_SECOND} 之一：{bins_per_second}")
    return rate


def _to_samples(raw: bytes) -> array.array:
    """s16le 位元組 → 樣本陣列（大端序機器上翻轉位元組）。"""
    samples = array.array("h")
    samples.frombytes(raw[:len(raw) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


def _append_bins(samples, mins, maxs, per_bin: int) -> None:
    """把整數格的樣本併成 (最小, 最大) 追加進去；呼叫端保證長度是 per_bin 的倍數。"""
    for start in range(0, len(samples), per_bin):
        chunk = samples[start:start + per_bin]
        mins.append(min(chunk))
        maxs.append(max(chunk))


def peaks_from_samples(samples, bins_per_second: int = DEFAULT_BINS_PER_SECOND) -> Peaks:
    """
    從已解碼的樣本（取樣率 = bins_per_second × SAMPLES_PER_BIN）算峰值表。

    尾端不滿一格的樣本也算一格，免得最後一小段聲音畫不出來。
    """
    rate = _check_rate(bins_per_second)
    per_bin = SAMPLES_PER_BIN
    mins, maxs = array.array("h"), array.array("h")
    whole = len(samples) // per_bin * per_bin
    _append_bins(samples[:whole], mins, maxs, per_bin)
    tail = samples[whole:]
    if len(tail):
        mins.append(min(tail))
        maxs.append(max(tail))
    return Peaks(rate, mins, maxs)


def _decode_command(media_path: str, rate: int) -> list:
    return ["ffmpeg", "-v", "error", "-nostdin", "-i", media_path, "-vn",
            "-ac", "1", "-ar", str(rate * SAMPLES_PER_BIN),
            "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1"]


def compute_peaks(media_path: str,
                  bins_per_second: int = DEFAULT_BINS_PER_SECOND,
                  progress_cb: Optional[Callable[[float], None]] = None,
                  cancel: Optional[Callable[[], bool]] = None,
                  duration: Optional[float] = None) -> Peaks:
    """
    用 ffmpeg 解碼並算出峰值表（不經快取）。

    progress_cb(0.0～1.0) 需要知道總長：給了 duration 就用它，沒給且有
    progress_cb 時用 ffprobe 量一次。cancel() 回傳 True 就停下並拋
    WaveformCancelled。沒有音軌或解碼失敗時拋 WaveformError。
    """
    rate = _check_rate(bins_per_second)
    if not os.path.isfile(media_path):
        raise WaveformError(f"找不到檔案：{media_path}")
    if progress_cb is not None and not duration:
        from .media import probe_duration  # 延遲匯入：沒要進度就不必量
        duration = probe_duration(media_path)
    try:
        proc = subprocess.Popen(_decode_command(media_path, rate),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise WaveformError(f"無法執行 ffmpeg：{exc}") from exc

    per_bin = SAMPLES_PER_BIN
    mins, maxs = array.array("h"), array.array("h")
    pending = b""
    block = _READ_BINS * per_bin * 2
    try:
        while True:
            if cancel is not None and cancel():
                raise WaveformCancelled("已取消")
            data = proc.stdout.read(block)
            if not data:
                break
            pending += data
            usable = len(pending) // (per_bin * 2) * (per_bin * 2)
            if usable:
                _append_bins(_to_samples(pending[:usable]), mins, maxs, per_bin)
                pending = pending[usable:]
            if progress_cb is not None and duration and duration > 0:
                progress_cb(min(len(mins) / rate / duration, 0.99))
        stderr = proc.stderr.read()
        proc.wait()
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    finally:
        proc.stdout.close()
        proc.stderr.close()

    tail = _to_samples(pending)
    if len(tail):
        mins.append(min(tail))
        maxs.append(max(tail))
    if not len(mins):
        detail = stderr.decode("utf-8", errors="ignore").strip().splitlines()
        raise WaveformError("解不出音訊（沒有音軌或檔案無法讀取）"
                            + (f"：{detail[-1]}" if detail else ""))
    if progress_cb is not None:
        progress_cb(1.0)
    return Peaks(rate, mins, maxs)


def resample(peaks: Peaks, start: float, end: float, columns: int) -> list:
    """
    把 [start, end) 秒的峰值併成 columns 欄，回傳 [(最小, 最大), ...]。

    拉遠（一欄多格）：取該欄範圍內最小的最小值與最大的最大值，尖峰不會被
    平均掉。拉近（一欄不到一格）：取該欄起點所在的那一格。超出音訊範圍
    （片頭之前、片尾之後）的欄位是 (0, 0)。
    """
    columns = int(columns)
    if columns <= 0 or end <= start:
        return []
    total = len(peaks)
    rate = peaks.bins_per_second
    span = (end - start) / columns
    out = []
    for col in range(columns):
        t0 = start + col * span
        first = math.floor(t0 * rate)
        last = math.floor((t0 + span) * rate)
        if last <= first:
            last = first + 1
        first = max(first, 0)
        last = min(last, total)
        if first >= last:  # 整欄都在片頭之前或片尾之後
            out.append((0, 0))
            continue
        out.append((min(peaks.mins[first:last]), max(peaks.maxs[first:last])))
    return out


# ===== 快取 =============================================================

def cache_key(media_path: str, bins_per_second: int = DEFAULT_BINS_PER_SECOND) -> str:
    """快取鍵（sha1）：路徑＋大小＋修改時間＋每秒格數。檔案不存在時拋 OSError。"""
    stat = os.stat(media_path)
    payload = json.dumps({
        "path": os.path.abspath(media_path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "bins_per_second": int(bins_per_second),
        "samples_per_bin": SAMPLES_PER_BIN,
    }, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def serialize(peaks: Peaks) -> bytes:
    """峰值表 → 位元組（小端序：標頭、全部最小值、全部最大值）。"""
    mins, maxs = array.array("h", peaks.mins), array.array("h", peaks.maxs)
    if sys.byteorder == "big":
        mins.byteswap()
        maxs.byteswap()
    return (_HEADER.pack(_MAGIC, peaks.bins_per_second, len(mins))
            + mins.tobytes() + maxs.tobytes())


def deserialize(data: bytes) -> Optional[Peaks]:
    """位元組 → 峰值表；格式不對（損毀、舊版、截斷）回傳 None。"""
    if len(data) < _HEADER.size:
        return None
    magic, rate, count = _HEADER.unpack_from(data)
    if magic != _MAGIC or rate not in ALLOWED_BINS_PER_SECOND:
        return None
    body = data[_HEADER.size:]
    if len(body) != count * 4:
        return None
    mins, maxs = array.array("h"), array.array("h")
    mins.frombytes(body[:count * 2])
    maxs.frombytes(body[count * 2:])
    if sys.byteorder == "big":
        mins.byteswap()
        maxs.byteswap()
    return Peaks(rate, mins, maxs)


def _cache_path(key: str, cache_dir: str) -> str:
    return os.path.join(cache_dir, f"{key}.peaks")


def _prune_cache(cache_dir: str) -> None:
    """超過上限時刪除最舊的快取檔。"""
    try:
        entries = [os.path.join(cache_dir, name) for name in os.listdir(cache_dir)
                   if name.endswith(".peaks")]
        if len(entries) <= MAX_CACHE_FILES:
            return
        entries.sort(key=os.path.getmtime)
        for path in entries[:len(entries) - MAX_CACHE_FILES]:
            os.unlink(path)
    except OSError:
        pass


def load_peaks(media_path: str,
               bins_per_second: int = DEFAULT_BINS_PER_SECOND,
               cache_dir: str = CACHE_DIR,
               progress_cb: Optional[Callable[[float], None]] = None,
               cancel: Optional[Callable[[], bool]] = None) -> Peaks:
    """
    取峰值表：快取有就直接讀，沒有就解碼並寫回快取。

    快取讀寫失敗一律靜默（重算／不存），不影響結果；解碼失敗照樣拋
    WaveformError，而且**不把失敗寫進快取**。
    """
    rate = _check_rate(bins_per_second)
    try:
        path = _cache_path(cache_key(media_path, rate), cache_dir)
    except OSError as exc:
        raise WaveformError(f"找不到檔案：{media_path}") from exc
    try:
        with open(path, "rb") as fh:
            cached = deserialize(fh.read())
        if cached is not None and cached.bins_per_second == rate:
            if progress_cb is not None:
                progress_cb(1.0)
            return cached
    except OSError:
        pass
    peaks = compute_peaks(media_path, rate, progress_cb=progress_cb, cancel=cancel)
    try:
        os.makedirs(cache_dir, exist_ok=True)
        temp = path + ".tmp"
        with open(temp, "wb") as fh:
            fh.write(serialize(peaks))
        os.replace(temp, path)
        _prune_cache(cache_dir)
    except OSError:
        pass
    return peaks


def clear_cache(cache_dir: str = CACHE_DIR) -> int:
    """清空波形快取，回傳刪除的檔案數。"""
    removed = 0
    try:
        for name in os.listdir(cache_dir):
            if name.endswith(".peaks"):
                os.unlink(os.path.join(cache_dir, name))
                removed += 1
    except OSError:
        pass
    return removed
