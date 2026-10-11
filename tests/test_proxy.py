# -*- coding: utf-8 -*-
"""
3.0 第 6 項：代理檔核心（subtitle/proxy.py）。

1. 什麼時候要做：短邊 1080 以上（橫、直、4K、4:3），720p 與 1079 不做。
2. 代理檔多大：短邊 540、比例不變、兩邊偶數；短邊本來就不到 540 的不放大。
3. 指令：關鍵影格每 12 格、不看場景切換、fastdecode、聲音可有可無。
4. probe_video：讀不到就回 None（不猜 1920x1080）；手機直拍的旋轉會換過來。
5. 真的做一份（ffmpeg）：尺寸、長度、關鍵影格間距、聲音都在；同一時間的畫面跟原檔
   一樣（跟別的時間差很多）——時間一格不差；直拍的做出來是直的。
6. 取消、失敗、長度對不上 → 拋錯而且不留下檔案。
7. 快取：第二次直接用（不再跑 ffmpeg）；原檔改過就重做；不需要的不做、不建檔；
   超過檔數或大小上限刪最舊的（剛做好的不刪）；當掉留下的舊 .tmp 清掉、新的不動。
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import proxy  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type as exc:
        return str(exc) or True
    except Exception as exc:  # noqa: BLE001 —— 丟錯種類也算不對
        return False if not isinstance(exc, exc_type) else True
    return False


# ----- 1. 什麼時候要做 -----
cases = {(1920, 1080): True, (1080, 1920): True, (3840, 2160): True, (1440, 1080): True,
         (1280, 720): False, (1918, 1079): False, (720, 1280): False, (640, 360): False}
got = {size: proxy.needs_proxy(*size) for size in cases}
check("短邊 1080 以上才做（橫、直、4K、4:3 要；720p、1079 不要）", got == cases, str(got))

# ----- 2. 代理檔多大 -----
sizes = {(1920, 1080): (960, 540), (1080, 1920): (540, 960), (3840, 2160): (960, 540),
         (1440, 1080): (720, 540), (1998, 1080): (1000, 540), (2560, 1080): (1280, 540),
         (1280, 720): (960, 540), (640, 360): (640, 360), (641, 359): (640, 358)}
got = {size: proxy.proxy_size(*size) for size in sizes}
check("短邊縮到 540、比例不變、兩邊偶數；短邊不到 540 的不放大", got == sizes, str(got))
check("寬高是 0 → ValueError", bool(raises(ValueError, proxy.proxy_size, 0, 1080)))

# ----- 3. 指令 -----
cmd = proxy.build_command("in.mov", "out.tmp", 1920, 1080)
joined = " ".join(cmd)
check("指令：縮到 960x540、關鍵影格每 12 格、不看場景切換、fastdecode、聲音可有可無、輸出 mp4",
      "scale=960:540" in cmd and cmd[cmd.index("-g") + 1] == "12"
      and cmd[cmd.index("-keyint_min") + 1] == "12" and cmd[cmd.index("-sc_threshold") + 1] == "0"
      and "fastdecode" in cmd and "0:a:0?" in cmd and cmd[cmd.index("-f") + 1] == "mp4"
      and cmd[-1] == "out.tmp" and "-r" not in cmd and "fps=" not in joined, joined)

if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
    print("SKIP 這個環境沒有 ffmpeg／ffprobe：略過真的轉檔的部分")
else:
    tmp = tempfile.mkdtemp()

    def make(name, size, seconds, extra=(), audio=True):
        path = os.path.join(tmp, name)
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30"]
        if audio:
            cmd += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-shortest"]
        cmd += ["-t", str(seconds), "-c:v", "libx264", "-preset", "ultrafast", *extra, path]
        subprocess.run(cmd, check=True)
        return path

    def frame(path, t, size="96x54"):
        """t 秒那一格縮成小灰階圖的位元組。"""
        out = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1",
                              "-vf", f"scale={size},format=gray", "-f", "rawvideo", "pipe:1"],
                             capture_output=True, check=True).stdout
        return out

    def diff(a, b):
        return sum(abs(x - y) for x, y in zip(a, b)) / max(len(a), 1)

    def keyframe_times(path):
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey",
                              "-show_entries", "frame=pts_time", "-of", "csv=p=0", path],
                             capture_output=True, text=True, check=True).stdout
        return [float(x.strip(",")) for x in out.split() if x.strip(",")]

    def streams(path):
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                              "-of", "csv=p=0", path], capture_output=True, text=True, check=True).stdout
        return out.split()

    src = make("src.mp4", "1920x1080", 4, ["-g", "300"])
    small = make("small.mp4", "1280x720", 2)
    rotated = os.path.join(tmp, "rot.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-display_rotation", "90", "-i", src, "-c", "copy",
                    rotated], check=True)
    silent = make("silent.mp4", "1920x1080", 2, audio=False)
    audio_only = os.path.join(tmp, "a.m4a")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440", "-t", "1",
                    audio_only], check=True)

    # ----- 4. probe_video -----
    info = proxy.probe_video(src)
    check("probe_video：寬高與片長", info is not None and (info["width"], info["height"]) == (1920, 1080)
          and abs(info["duration"] - 4) < 0.1, str(info))
    rinfo = proxy.probe_video(rotated)
    check("probe_video：直拍（旋轉 90 度）的寬高換過來", rinfo is not None
          and (rinfo["width"], rinfo["height"]) == (1080, 1920), str(rinfo))
    check("probe_video：讀不到就回 None（不存在、只有聲音），不猜 1920x1080",
          proxy.probe_video(os.path.join(tmp, "none.mp4")) is None and proxy.probe_video(audio_only) is None)

    # ----- 5. 真的做一份 -----
    out = os.path.join(tmp, "p.mp4")
    ratios = []
    proxy.make_proxy(src, out, progress_cb=ratios.append)
    pinfo = proxy.probe_video(out)
    check("代理檔 960x540、長度跟原檔差不到 0.25 秒", pinfo is not None
          and (pinfo["width"], pinfo["height"]) == (960, 540)
          and abs(pinfo["duration"] - info["duration"]) <= proxy.DURATION_TOLERANCE, str(pinfo))
    check("進度有往上走、最後是 1.0", ratios and ratios[-1] == 1.0 and ratios == sorted(ratios)
          and any(0 < r < 1 for r in ratios), str(ratios[-5:]))
    keys = keyframe_times(out)
    gaps = [round(b - a, 3) for a, b in zip(keys, keys[1:])]
    check("關鍵影格每 12 格（0.4 秒）一張；原檔這裡只有 1 張",
          len(keys) == 10 and all(abs(g - 0.4) < 0.01 for g in gaps) and len(keyframe_times(src)) == 1,
          f"{keys} {len(keyframe_times(src))}")
    check("聲音也在", streams(out) == ["video", "audio"], str(streams(out)))
    same = [diff(frame(src, t), frame(out, t)) for t in (0.5, 1.7, 3.3)]
    other = [diff(frame(src, t), frame(out, t + 1 / 30.0)) for t in (0.5, 1.7, 3.3)]
    check("同一時間的畫面跟原檔一樣（差一格就明顯不同）——時間一格不差",
          max(same) < 1 and min(other) > 3 * max(same),
          f"同時間 {[round(x, 2) for x in same]}，差一格 {[round(x, 2) for x in other]}")
    rout = proxy.make_proxy(rotated, os.path.join(tmp, "r.mp4"))
    rp = proxy.probe_video(rout)
    check("直拍做出來是直的 540x960", rp is not None and (rp["width"], rp["height"]) == (540, 960), str(rp))
    sout = proxy.make_proxy(silent, os.path.join(tmp, "s.mp4"))
    check("沒有聲音的片子也做得出來", streams(sout) == ["video"], str(streams(sout)))

    # ----- 6. 取消、失敗、長度對不上 -----
    def leftovers():
        return sorted(n for n in os.listdir(tmp) if n.endswith(".tmp"))

    dest = os.path.join(tmp, "c.mp4")
    check("一開始就取消 → ProxyCancelled、不留檔",
          bool(raises(proxy.ProxyCancelled, proxy.make_proxy, src, dest, cancel=lambda: True))
          and not os.path.exists(dest) and not leftovers(), str(leftovers()))
    calls = []

    def cancel_later():
        calls.append(1)
        return len(calls) > 2

    check("做到一半取消 → ProxyCancelled、不留檔",
          bool(raises(proxy.ProxyCancelled, proxy.make_proxy, src, dest, cancel=cancel_later))
          and not os.path.exists(dest) and not leftovers(), str(leftovers()))
    msg = raises(proxy.ProxyError, proxy.make_proxy, audio_only, dest)
    check("沒有畫面 → ProxyError（說讀不到影像軌）、不留檔", isinstance(msg, str) and "影像軌" in msg
          and not os.path.exists(dest), str(msg))
    broken = os.path.join(tmp, "broken.mp4")
    with open(broken, "wb") as fh:
        fh.write(b"\x00" * 4096)
    msg = raises(proxy.ProxyError, proxy.make_proxy, broken, dest,
                 info={"width": 1920, "height": 1080, "duration": 4.0})
    check("ffmpeg 轉不了 → ProxyError、不留檔", isinstance(msg, str) and "失敗" in msg
          and not os.path.exists(dest) and not leftovers(), f"{msg} {leftovers()}")
    msg = raises(proxy.ProxyError, proxy.make_proxy, src, dest,
                 info={"width": 1920, "height": 1080, "duration": 4.6})
    check("做出來的長度跟原檔差太多 → ProxyError（對不上）、不留檔", isinstance(msg, str)
          and "對不上" in msg and not os.path.exists(dest) and not leftovers(), f"{msg} {leftovers()}")
    msg = raises(proxy.ProxyError, proxy.make_proxy, src, dest,
                 info={"width": 1920, "height": 1080, "duration": 4.0 + proxy.DURATION_TOLERANCE * 0.8})
    check("差在容許範圍內 → 照用", msg is False and os.path.exists(dest), str(msg))

    # ----- 7. 快取 -----
    cache = os.path.join(tmp, "cache")
    first = proxy.load_proxy(src, cache)
    check("第一次：做一份放進快取（檔名＝快取鍵）", first == proxy.cache_path(src, cache)
          and os.path.getsize(first) > 0 and os.path.dirname(first) == cache, str(first))
    real_make = proxy.make_proxy
    proxy.make_proxy = lambda *a, **k: (_ for _ in ()).throw(AssertionError("不該再跑 ffmpeg"))
    try:
        seen = []
        again = proxy.load_proxy(src, cache, progress_cb=seen.append)
        check("第二次：直接用快取（不跑 ffmpeg）、進度直接 1.0", again == first and seen == [1.0], str(seen))
        check("不到 1080p → None、快取裡不多出檔案",
              proxy.load_proxy(small, cache) is None and os.listdir(cache) == [os.path.basename(first)],
              str(os.listdir(cache)))
    finally:
        proxy.make_proxy = real_make
    old_key = proxy.cache_key(src)
    later = time.time() + 5
    os.utime(src, (later, later))
    check("原檔改過（修改時間變了）→ 快取鍵不同、舊的代理檔不算數",
          proxy.cache_key(src) != old_key and proxy.cached_proxy(src, cache) is None)
    check("讀不到影像軌 → load_proxy 拋 ProxyError", bool(raises(proxy.ProxyError, proxy.load_proxy,
                                                                   audio_only, cache)))

    prune = os.path.join(tmp, "prune")
    os.makedirs(prune)
    now = time.time()
    names = []
    for i in range(11):
        name = f"{i:040d}.mp4"
        path = os.path.join(prune, name)
        with open(path, "wb") as fh:
            fh.write(b"x" * 100)
        os.utime(path, (now - 1000 + i, now - 1000 + i))
        names.append(name)
    stale = os.path.join(prune, "a" * 40 + ".mp4.tmp")
    fresh = os.path.join(prune, "b" * 40 + ".mp4.tmp")
    other = os.path.join(prune, "notes.txt")
    for path in (stale, fresh, other):
        with open(path, "w") as fh:
            fh.write("x")
    os.utime(stale, (now - proxy.STALE_TMP_SECONDS - 60,) * 2)
    keep = os.path.join(prune, names[0])  # 最舊的，但剛做好
    proxy.prune_cache(prune, keep=keep)
    left = sorted(os.listdir(prune))
    expect = sorted([names[0]] + names[4:] + [os.path.basename(fresh), "notes.txt"])
    check("超過 8 個 → 刪最舊的（剛做好的不刪）；一天以上的 .tmp 清掉、新的不動、別的檔不動",
          left == expect, str(left))
    real_cap = proxy.MAX_CACHE_BYTES
    proxy.MAX_CACHE_BYTES = 350
    try:
        proxy.prune_cache(prune)
    finally:
        proxy.MAX_CACHE_BYTES = real_cap
    left = sorted(n for n in os.listdir(prune) if n.endswith(".mp4"))
    check("超過總大小上限 → 刪到放得下為止（從最舊的刪）", left == names[-3:], str(left))
    check("clear_cache 清掉代理檔與 .tmp、別的檔不動",
          proxy.clear_cache(prune) == 4 and os.listdir(prune) == ["notes.txt"], str(os.listdir(prune)))

    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 代理檔核心測試全數通過。")
