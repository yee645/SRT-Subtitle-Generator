# -*- coding: utf-8 -*-
"""
3.0 第 3 項第一階段：`subtitle/waveform.py`（時間軸的波形峰值）。

這裡守：

1. 純計算：樣本 → (最小, 最大) 峰值表；尾端不滿一格也算；解析度只收允許值。
2. **真的解碼**（ffmpeg 有才跑）：一段「1 秒靜音 → 1 秒 0.5 振幅正弦 → 1 秒
   靜音」的音訊，峰值落在對的格子、振幅對、正負對稱；串流讀取切在任意位置
   都跟一次解完的結果逐格相同；沒有音軌、檔案不存在時拋 WaveformError。
3. `resample`：拉遠時尖峰不被平均掉、拉近時取所在格、範圍外是 (0, 0)。
4. 快取：第二次不再呼叫 ffmpeg；檔案一改就重算；快取檔損毀就重算；解碼失
   敗不寫進快取；超過上限刪最舊的；序列化來回一致、截斷的回傳 None。
5. 取消與進度。
"""
import array
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import waveform  # noqa: E402
from subtitle.waveform import (Peaks, WaveformCancelled, WaveformError,  # noqa: E402
                               deserialize, load_peaks, peaks_from_samples,
                               resample, serialize)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type:
        return True
    except Exception:  # noqa: BLE001 —— 拋錯類型不對也算失敗
        return False
    return False


# ===== 1. 純計算 ========================================================

per = waveform.SAMPLES_PER_BIN
samples = array.array("h", [0] * per + [100, -50] + [0] * (per - 2) + [7, -9, 3])
p = peaks_from_samples(samples, 100)
check("兩格整＋尾端 3 個樣本 → 3 格", len(p) == 3, str(len(p)))
check("第 1 格全靜音是 (0, 0)", (p.mins[0], p.maxs[0]) == (0, 0))
check("第 2 格是 (-50, 100)", (p.mins[1], p.maxs[1]) == (-50, 100))
check("尾端不滿一格也算：(-9, 7)", (p.mins[2], p.maxs[2]) == (-9, 7))
check("duration = 格數 ÷ 每秒格數", abs(p.duration - 0.03) < 1e-9, str(p.duration))
check("空樣本 → 空峰值表", len(peaks_from_samples(array.array("h"), 100)) == 0)
check("解析度只收允許值", raises(ValueError, peaks_from_samples, samples, 60))
check("mins／maxs 長度不同就拒絕",
      raises(ValueError, Peaks, 100, array.array("h", [1]), array.array("h")))

# ===== 3. resample（先用純資料測，不依賴 ffmpeg） =========================

# 10 秒、每秒 100 格；第 5.25 秒那一格有一根尖峰（在拉遠後那一欄的中間，
# 不是第一格——只取每欄第一格的錯誤實作才抓得到），其餘安靜。
quiet = Peaks(100, array.array("h", [-10] * 1000), array.array("h", [10] * 1000))
quiet.maxs[525] = 30000
quiet.mins[525] = -29000
cols = resample(quiet, 0, 10, 20)
check("拉遠（每欄 50 格）：共 20 欄", len(cols) == 20, str(len(cols)))
check("拉遠時尖峰不會被平均掉：第 10 欄是 (-29000, 30000)",
      cols[10] == (-29000, 30000), str(cols[10]))
check("其他欄仍是 (-10, 10)",
      all(c == (-10, 10) for i, c in enumerate(cols) if i != 10), str(cols))
zoom = resample(quiet, 5.25, 5.26, 8)
check("拉近（一欄不到一格）：8 欄都取第 525 格",
      zoom == [(-29000, 30000)] * 8, str(zoom))
outside = resample(quiet, -2, 12, 14)
check("片頭之前、片尾之後的欄位是 (0, 0)",
      outside[0] == (0, 0) and outside[1] == (0, 0)
      and outside[-1] == (0, 0) and outside[-2] == (0, 0)
      and outside[2] == (-10, 10) and outside[11] == (-10, 10), str(outside))
check("欄數 0 或範圍反了 → 空清單",
      resample(quiet, 0, 10, 0) == [] and resample(quiet, 5, 5, 10) == [])

# ===== 4a. 序列化 =======================================================

blob = serialize(quiet)
check("序列化來回一致", deserialize(blob) == quiet)
check("截斷的資料回傳 None", deserialize(blob[:-3]) is None)
check("開頭不對（別的檔案）回傳 None", deserialize(b"NOTWAVE!" + blob[8:]) is None)
check("太短回傳 None", deserialize(b"SRT") is None)

# ===== 2. 真的解碼 ======================================================

if not shutil.which("ffmpeg"):
    print("SKIP 沒有 ffmpeg：略過真的解碼、快取、取消與進度")
else:
    tmp = tempfile.mkdtemp()
    tone = os.path.join(tmp, "tone.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='if(between(t,1,2),0.5*sin(2*PI*440*t),0)':d=3:s=44100",
                    tone], check=True)
    pk = waveform.compute_peaks(tone)
    check("3 秒 → 約 300 格（±2）", abs(len(pk) - 300) <= 2, str(len(pk)))
    silent = [max(abs(pk.mins[i]), abs(pk.maxs[i])) for i in list(range(0, 95)) + list(range(205, 295))]
    check("靜音段的峰值近乎 0（< 1% 滿格）", max(silent) < 330, str(max(silent)))
    loud = [pk.maxs[i] for i in range(105, 195)]
    check("正弦段的峰值 ≈ 0.5 滿格（16384 ±5%）",
          all(abs(v - 16384) < 820 for v in loud), f"{min(loud)}～{max(loud)}")
    check("正弦段正負對稱（最小值 ≈ -最大值）",
          all(abs(pk.mins[i] + pk.maxs[i]) < 820 for i in range(105, 195)))

    # 串流：管線的 read() 不保證一次給滿，讓它每次只給奇數個位元組（切在
    # 樣本中間、格子中間），而且音訊長度不是整數格（尾端有零頭）。結果要與
    # 一次解完完全相同。
    odd = os.path.join(tmp, "odd.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='0.3*sin(2*PI*220*t)*(1+t)':d=1.2371:s=44100", odd], check=True)
    raw = subprocess.run(waveform._decode_command(odd, 100),
                         capture_output=True, check=True).stdout
    whole = peaks_from_samples(waveform._to_samples(raw), 100)
    check("測資長度不是整數格（有零頭，才測得到尾端）",
          (len(raw) // 2) % waveform.SAMPLES_PER_BIN != 0, str(len(raw) // 2))

    class _Stingy:
        """包住真的 stdout，每次最多給 333 個位元組。"""

        def __init__(self, inner):
            self.inner = inner

        def read(self, n=-1):
            return self.inner.read(min(n, 333) if n and n > 0 else 333)

        def close(self):
            self.inner.close()

    real_popen_for_stream = subprocess.Popen

    def stingy_popen(*args, **kwargs):
        proc = real_popen_for_stream(*args, **kwargs)
        proc.stdout = _Stingy(proc.stdout)
        return proc

    waveform.subprocess.Popen = stingy_popen
    try:
        chunked = waveform.compute_peaks(odd)
    finally:
        waveform.subprocess.Popen = real_popen_for_stream
    check("串流每次只拿到 333 位元組，結果仍與一次解完逐格相同", chunked == whole,
          f"{len(chunked)} {len(whole)}")

    pk50 = waveform.compute_peaks(tone, 50)
    check("每秒 50 格：約 150 格、每格涵蓋 20ms", abs(len(pk50) - 150) <= 1
          and pk50.bins_per_second == 50, str(len(pk50)))

    clip = os.path.join(ROOT, "research", "qt_probe", "probe_clip.mp4")
    pclip = waveform.compute_peaks(clip)
    check("真的影片（probe_clip.mp4，2 秒 H.264＋AAC）→ 約 2 秒的峰值",
          abs(pclip.duration - 2.0) < 0.05, str(pclip.duration))

    noaudio = os.path.join(tmp, "noaudio.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=black:s=64x64:d=1", "-an", noaudio], check=True)
    check("沒有音軌 → WaveformError", raises(WaveformError, waveform.compute_peaks, noaudio))
    check("檔案不存在 → WaveformError",
          raises(WaveformError, waveform.compute_peaks, os.path.join(tmp, "nope.mp4")))

    # ----- 5. 取消與進度 -----
    long_audio = os.path.join(tmp, "long.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=300:duration=120:sample_rate=16000", long_audio], check=True)
    calls = []
    t0 = time.time()
    ok = raises(WaveformCancelled, waveform.compute_peaks, long_audio,
                cancel=lambda: calls.append(1) or len(calls) > 2)
    check("cancel() 回 True → WaveformCancelled，而且很快停下（< 3 秒）",
          ok and time.time() - t0 < 3, f"{ok} {time.time() - t0:.2f}s")
    progress = []
    waveform.compute_peaks(long_audio, progress_cb=progress.append, duration=120)
    check("進度遞增、落在 0～1、最後是 1.0",
          progress and progress == sorted(progress) and progress[-1] == 1.0
          and all(0 <= v <= 1 for v in progress) and len(progress) >= 3,
          str(progress[:3]) + str(progress[-2:]))

    # ----- 4b. 快取 -----
    cache = os.path.join(tmp, "cache")
    first = load_peaks(tone, cache_dir=cache)
    files = [n for n in os.listdir(cache) if n.endswith(".peaks")]
    check("第一次：算出來並寫進快取（一個 .peaks 檔、沒有殘留 .tmp）",
          first == pk and len(files) == 1 and not [n for n in os.listdir(cache) if n.endswith(".tmp")],
          str(os.listdir(cache)))

    real_popen = subprocess.Popen
    popen_calls = []

    def spy_popen(*args, **kwargs):
        popen_calls.append(args)
        return real_popen(*args, **kwargs)

    def no_popen(*args, **kwargs):
        raise AssertionError("不該再呼叫 ffmpeg")

    waveform.subprocess.Popen = no_popen
    try:
        again = load_peaks(tone, cache_dir=cache)
    except AssertionError:
        again = None
    finally:
        waveform.subprocess.Popen = real_popen
    check("第二次：直接讀快取，不再呼叫 ffmpeg", again == pk)

    # 檔案一改就重算：換成別的內容（大小、修改時間都變）。
    edited = os.path.join(tmp, "edited.wav")
    shutil.copy(tone, edited)
    load_peaks(edited, cache_dir=cache)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=200:duration=1:sample_rate=44100", edited], check=True)
    waveform.subprocess.Popen = spy_popen
    try:
        popen_calls.clear()
        changed = load_peaks(edited, cache_dir=cache)
    finally:
        waveform.subprocess.Popen = real_popen
    check("檔案改過 → 重算（呼叫了 ffmpeg、長度變成約 100 格）",
          len(popen_calls) == 1 and abs(len(changed) - 100) <= 2,
          f"{len(popen_calls)} {len(changed)}")

    # 大小不變、內容變了（同長度同格式、換個頻率）：只有修改時間能分辨。
    same = os.path.join(tmp, "same.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=200:duration=1:sample_rate=44100", same], check=True)
    old_peaks = load_peaks(same, cache_dir=cache)
    size = os.path.getsize(same)
    st = os.stat(same)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='0.9*sin(2*PI*200*t)':d=1:s=44100", same], check=True)
    os.utime(same, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    new_peaks = load_peaks(same, cache_dir=cache)
    check("大小相同、內容改了 → 靠修改時間認出來、重算",
          os.path.getsize(same) == size and new_peaks != old_peaks
          and max(new_peaks.maxs) > 25000,
          f"{os.path.getsize(same)} vs {size}, {max(new_peaks.maxs)}")

    # 快取檔損毀 → 重算並覆寫。
    key_path = os.path.join(cache, waveform.cache_key(tone) + ".peaks")
    with open(key_path, "wb") as fh:
        fh.write(b"garbage")
    waveform.subprocess.Popen = spy_popen
    try:
        popen_calls.clear()
        healed = load_peaks(tone, cache_dir=cache)
    finally:
        waveform.subprocess.Popen = real_popen
    with open(key_path, "rb") as fh:
        rewritten = deserialize(fh.read())
    check("快取檔損毀 → 重算、結果正確、並寫回好的快取",
          len(popen_calls) == 1 and healed == pk and rewritten == pk)

    before = set(os.listdir(cache))
    check("解碼失敗照樣拋 WaveformError", raises(WaveformError, load_peaks, noaudio, cache_dir=cache))
    check("解碼失敗不寫進快取", set(os.listdir(cache)) == before,
          str(set(os.listdir(cache)) - before))

    # 超過上限刪最舊的。
    prune_dir = os.path.join(tmp, "prune")
    os.makedirs(prune_dir)
    for i in range(waveform.MAX_CACHE_FILES + 5):
        path = os.path.join(prune_dir, f"{i:03d}.peaks")
        with open(path, "wb") as fh:
            fh.write(serialize(quiet))
        os.utime(path, (1000 + i, 1000 + i))
    waveform._prune_cache(prune_dir)
    left = sorted(os.listdir(prune_dir))
    check(f"超過 {waveform.MAX_CACHE_FILES} 個就刪最舊的",
          len(left) == waveform.MAX_CACHE_FILES and left[0] == "005.peaks", str(left[:3]))
    check("clear_cache 清空並回報刪了幾個",
          waveform.clear_cache(prune_dir) == waveform.MAX_CACHE_FILES
          and not os.listdir(prune_dir))

    shutil.rmtree(tmp, ignore_errors=True)

# ===== 6. 零 GUI 依賴 ===================================================

with open(os.path.join(ROOT, "subtitle", "waveform.py"), encoding="utf-8") as fh:
    source = fh.read()
check("subtitle/waveform.py 不匯入任何 GUI 套件",
      not any(name in source for name in ("tkinter", "PySide6", "gui_qt", "from gui", "import gui")))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 波形峰值測試全數通過。")
