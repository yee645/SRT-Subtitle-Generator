# -*- coding: utf-8 -*-
"""
3.0 第 3 項第二階段：`subtitle/filmstrip.py`（時間軸的縮圖條）。

測資用 ffmpeg 現做：畫面亮度 = 時間 × k（`geq=lum=T*k`），所以**每張縮圖的
平均亮度就說出它真正是第幾秒的畫面**——不只驗「抽到幾張」，還驗「標的時間
跟畫面內容對得上」。

這裡守：

1. 純計算：補空檔的時間點、nearest／slots、參數檢查、索引不准跳出資料夾。
2. 真的抽（ffmpeg 有才跑）：
   - 一般素材（每 2 秒一個關鍵影格）：時間正確、畫面內容與時間相符。
   - 每一幀都是關鍵影格：不會一秒吐 30 張，相鄰至少隔 min_interval。
   - 關鍵影格很疏（20 秒一個）：空檔補抽，補的那幾張畫面也是對的時間。
   - 沒有影像軌、檔案不存在：FilmstripError。
3. 取消、進度。
4. 快取：命中不再呼叫 ffmpeg；影片改了、圖少一張、索引壞掉都重抽；取消
   或失敗不留暫存資料夾；超過上限刪最舊的。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import filmstrip  # noqa: E402
from subtitle.filmstrip import (Filmstrip, FilmstripCancelled, FilmstripError,  # noqa: E402
                                gap_fill_times, load_filmstrip, read_index)

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

check("空檔補點：0 與 20 之間隔 10 補一個（10）",
      gap_fill_times([0, 20], 0, 10) == [10], str(gap_fill_times([0, 20], 0, 10)))
check("空檔補點：最後一張到片尾也補（40→60 補 50）",
      gap_fill_times([0, 20, 40], 60, 10) == [10, 30, 50],
      str(gap_fill_times([0, 20, 40], 60, 10)))
check("空檔補點：間距沒超過就不補",
      gap_fill_times([0, 2, 4, 6], 8, 10) == [])
check("空檔補點：離下一張太近（< 1/4 間距）的點不補",
      gap_fill_times([0, 11], 0, 10) == [], str(gap_fill_times([0, 11], 0, 10)))
check("空檔補點：有上限",
      len(gap_fill_times([0], 100000, 10, limit=7)) == 7)

strip = Filmstrip(90, 10.0, [(4.0, "d"), (0.0, "a"), (2.0, "b"), (3.0, "c")])
check("frames 依時間排序", [t for t, _ in strip.frames] == [0, 2, 3, 4])
check("nearest：取最近的一張（2.4 → 2、2.6 → 3、99 → 最後一張、-5 → 第一張）",
      [strip.nearest(x)[1] for x in (2.4, 2.6, 99, -5)] == ["b", "c", "d", "a"])
check("nearest：剛好在中間取前一張", strip.nearest(2.5)[1] == "b")
check("沒有縮圖時 nearest 回 None", Filmstrip(90, 0, []).nearest(1) is None)
slots = strip.slots(-2, 12, 7)  # 每格 2 秒，中心在 -1、1、3、5、7、9、11
check("slots：片頭前、片尾後是 None，中間取最近",
      slots == [None, strip.frames[0], strip.frames[2], strip.frames[3],
                strip.frames[3], strip.frames[3], None], str(slots))
check("slots：格數 0 或範圍反了 → 空清單",
      strip.slots(0, 10, 0) == [] and strip.slots(5, 5, 3) == [])
check("縮圖高度要合理", raises(ValueError, filmstrip._check_args, 4, 1, 10)
      and raises(ValueError, filmstrip._check_args, 2000, 1, 10))
check("max_gap 比 min_interval 小不合理", raises(ValueError, filmstrip._check_args, 90, 5, 2))

evil = tempfile.mkdtemp()
with open(os.path.join(evil, "index.json"), "w", encoding="utf-8") as fh:
    json.dump({"version": 1, "height": 90, "duration": 1,
               "frames": [[0, "../../etc/passwd"]]}, fh)
check("索引裡的檔名不准跳出快取資料夾", read_index(evil) is None)
shutil.rmtree(evil, ignore_errors=True)

# ===== 2. 真的抽 ========================================================

if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
    print("SKIP 沒有 ffmpeg／ffprobe：略過真的抽、快取、取消與進度")
else:
    tmp = tempfile.mkdtemp()

    def make(name, seconds, gop, k, extra=()):
        """亮度 = 時間 × k 的測試影片（160x90、30fps）。"""
        path = os.path.join(tmp, name)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"color=black:s=160x90:r=30:d={seconds},format=gray,"
                        f"geq=lum='min(255,T*{k})',format=yuv420p",
                        *extra, "-c:v", "libx264", "-preset", "ultrafast",
                        "-g", str(gop), path], check=True)
        return path

    def luma(path):
        """一張圖的平均亮度（ffmpeg 縮成 1x1 灰階）。"""
        out = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf",
                              "scale=1:1:flags=area,format=gray", "-f", "rawvideo", "-"],
                             capture_output=True, check=True).stdout
        return out[0]

    normal = make("normal.mp4", 30, 60, 8)          # 每 2 秒一個關鍵影格
    allkey = make("allkey.mp4", 10, 1, 24)          # 每一幀都是關鍵影格
    sparse = make("sparse.mp4", 60, 600, 4)         # 每 20 秒一個關鍵影格

    out = os.path.join(tmp, "n")
    os.makedirs(out)
    s = filmstrip.extract(normal, out)
    times = [t for t, _ in s.frames]
    check("一般素材：30 秒、每 2 秒一個關鍵影格 → 15 張，時間 0、2、4…",
          len(s) == 15 and all(abs(t - 2 * i) < 0.05 for i, t in enumerate(times)),
          str(times))
    check("一般素材：片長量到 30 秒", abs(s.duration - 30) < 0.1, str(s.duration))
    off = [(round(t, 1), round(luma(p) / 8, 1)) for t, p in s.frames
           if abs(luma(p) / 8 - t) > 0.6]
    check("一般素材：每張的畫面內容就是標的那一秒（亮度換回時間，差 0.6 秒內）",
          not off, str(off))
    check("縮圖高度是 90px（寬度照比例）",
          subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", s.frames[0][1]], capture_output=True,
                         text=True).stdout.strip() == "160,90")

    out = os.path.join(tmp, "k")
    os.makedirs(out)
    s = filmstrip.extract(allkey, out)
    times = [t for t, _ in s.frames]
    gaps = [b - a for a, b in zip(times, times[1:])]
    check("每一幀都是關鍵影格：10 秒只留約 10 張（不是 300 張）",
          9 <= len(s) <= 11, str(len(s)))
    check("每一幀都是關鍵影格：相鄰至少隔 min_interval（1 秒）",
          gaps and min(gaps) >= 0.99, str(gaps))

    out = os.path.join(tmp, "s")
    os.makedirs(out)
    s = filmstrip.extract(sparse, out)
    times = [round(t, 1) for t, _ in s.frames]
    check("關鍵影格很疏（20 秒一個）：補抽後 0、10、20、30、40、50",
          times == [0, 10, 20, 30, 40, 50], str(times))
    fills = [(t, p) for t, p in s.frames if os.path.basename(p).startswith("fill_")]
    check("補抽的是 10、30、50 那三張", [round(t) for t, _ in fills] == [10, 30, 50],
          str(fills))
    off = [(round(t, 1), round(luma(p) / 4, 1)) for t, p in s.frames
           if abs(luma(p) / 4 - t) > 1.0]
    check("補抽的畫面也是標的那一秒（不是前一個關鍵影格的畫面）", not off, str(off))

    audio_only = os.path.join(tmp, "audio.m4a")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=d=2",
                    audio_only], check=True)
    out = os.path.join(tmp, "a")
    os.makedirs(out)
    check("沒有影像軌 → FilmstripError", raises(FilmstripError, filmstrip.extract, audio_only, out))
    check("檔案不存在 → FilmstripError",
          raises(FilmstripError, filmstrip.extract, os.path.join(tmp, "nope.mp4"), out))

    clip = os.path.join(ROOT, "research", "qt_probe", "probe_clip.mp4")
    out = os.path.join(tmp, "c")
    os.makedirs(out)
    s = filmstrip.extract(clip, out)
    check("真的影片（probe_clip.mp4）抽得出縮圖、片長約 2 秒",
          len(s) >= 1 and abs(s.duration - 2) < 0.1, f"{len(s)} {s.duration}")

    # ----- 3. 取消與進度 -----
    progress = []
    out = os.path.join(tmp, "p")
    os.makedirs(out)
    filmstrip.extract(sparse, out, progress_cb=progress.append)
    check("進度遞增、落在 0～1、最後是 1.0，補抽階段也有回報",
          progress == sorted(progress) and progress[-1] == 1.0
          and all(0 <= v <= 1 for v in progress)
          and any(0.9 < v < 1.0 for v in progress), str(progress))

    cache = os.path.join(tmp, "cache")
    calls = []
    t0 = time.time()
    ok = raises(FilmstripCancelled, load_filmstrip, sparse, cache_dir=cache,
                cancel=lambda: calls.append(1) or len(calls) > 1)
    check("cancel() 回 True → FilmstripCancelled，而且很快停下", ok and time.time() - t0 < 5)
    # 一般素材沒有空檔要補：取消只能在抽關鍵影格那一段生效。
    calls.clear()
    out = os.path.join(tmp, "x")
    os.makedirs(out)
    check("抽關鍵影格的途中也能取消（沒有補抽階段的素材）",
          raises(FilmstripCancelled, filmstrip.extract, normal, out,
                 cancel=lambda: calls.append(1) or len(calls) > 1))
    check("取消後不留暫存資料夾、也沒有寫出快取",
          not os.path.isdir(cache) or not os.listdir(cache),
          str(os.listdir(cache) if os.path.isdir(cache) else ""))

    # ----- 4. 快取 -----
    first = load_filmstrip(normal, cache_dir=cache)
    entries = os.listdir(cache)
    check("第一次：抽完寫進一個快取資料夾（名字是 40 字元的鍵，沒有 .tmp 殘留）",
          len(entries) == 1 and len(entries[0]) == 40, str(entries))
    check("快取裡每張圖都在資料夾裡", all(os.path.dirname(p) == os.path.join(cache, entries[0])
                                          for _, p in first.frames))

    real_popen, real_run = subprocess.Popen, subprocess.run
    spawned = []

    def spy_popen(*args, **kwargs):
        spawned.append(args)
        return real_popen(*args, **kwargs)

    def spy_run(*args, **kwargs):
        spawned.append(args)
        return real_run(*args, **kwargs)

    def use_spy(on):
        filmstrip.subprocess.Popen = spy_popen if on else real_popen
        filmstrip.subprocess.run = spy_run if on else real_run

    use_spy(True)
    try:
        spawned.clear()
        again = load_filmstrip(normal, cache_dir=cache)
        hit_calls = len(spawned)
    finally:
        use_spy(False)
    check("第二次：直接用快取，不再呼叫 ffmpeg／ffprobe",
          hit_calls == 0 and [t for t, _ in again.frames] == [t for t, _ in first.frames],
          str(hit_calls))

    folder = os.path.join(cache, entries[0])
    os.unlink(first.frames[3][1])
    use_spy(True)
    try:
        spawned.clear()
        healed = load_filmstrip(normal, cache_dir=cache)
        heal_calls = len(spawned)
    finally:
        use_spy(False)
    check("快取裡少了一張圖 → 重抽、而且補齊", heal_calls > 0 and len(healed) == 15
          and all(os.path.isfile(p) for _, p in healed.frames), str(heal_calls))

    with open(os.path.join(folder, "index.json"), "w", encoding="utf-8") as fh:
        fh.write("{壞掉")
    use_spy(True)
    try:
        spawned.clear()
        fixed = load_filmstrip(normal, cache_dir=cache)
        fix_calls = len(spawned)
    finally:
        use_spy(False)
    check("索引壞掉 → 重抽", fix_calls > 0 and len(fixed) == 15)

    edited = os.path.join(tmp, "edited.mp4")
    shutil.copy(normal, edited)
    before = load_filmstrip(edited, cache_dir=cache)
    shutil.copy(allkey, edited)
    after = load_filmstrip(edited, cache_dir=cache)
    check("影片改了（換內容）→ 重抽，張數跟著變", len(before) == 15 and 9 <= len(after) <= 11,
          f"{len(before)} {len(after)}")

    # 內容與大小都沒變、只有修改時間變了（重新存檔、從備份還原）也要重抽。
    st = os.stat(edited)
    os.utime(edited, ns=(st.st_atime_ns, st.st_mtime_ns + 7_000_000_000))
    use_spy(True)
    try:
        spawned.clear()
        load_filmstrip(edited, cache_dir=cache)
        touch_calls = len(spawned)
    finally:
        use_spy(False)
    check("只有修改時間變了 → 也重抽", touch_calls > 0, str(touch_calls))

    snapshot = sorted(os.listdir(cache))
    check("抽不出來 → 照樣拋 FilmstripError",
          raises(FilmstripError, load_filmstrip, audio_only, cache_dir=cache))
    check("失敗不留暫存資料夾、不寫快取", sorted(os.listdir(cache)) == snapshot,
          str(set(os.listdir(cache)) ^ set(snapshot)))

    prune = os.path.join(tmp, "prune")
    for i in range(filmstrip.MAX_CACHE_ENTRIES + 3):
        path = os.path.join(prune, f"{i:040d}")
        os.makedirs(path)
        os.utime(path, (1000 + i, 1000 + i))
    newest = os.path.join(prune, f"{filmstrip.MAX_CACHE_ENTRIES + 2:040d}")
    filmstrip._prune_cache(prune, newest)
    left = sorted(os.listdir(prune))
    check(f"超過 {filmstrip.MAX_CACHE_ENTRIES} 支就刪最舊的",
          len(left) == filmstrip.MAX_CACHE_ENTRIES and left[0] == f"{3:040d}", str(left[:2]))
    check("clear_cache 清空並回報刪了幾支",
          filmstrip.clear_cache(prune) == filmstrip.MAX_CACHE_ENTRIES and not os.listdir(prune))

    shutil.rmtree(tmp, ignore_errors=True)

# ===== 5. 零 GUI 依賴 ===================================================

with open(os.path.join(ROOT, "subtitle", "filmstrip.py"), encoding="utf-8") as fh:
    source = fh.read()
check("subtitle/filmstrip.py 不匯入任何 GUI 套件",
      not any(name in source for name in ("tkinter", "PySide6", "gui_qt", "from gui", "import gui")))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 縮圖條測試全數通過。")
