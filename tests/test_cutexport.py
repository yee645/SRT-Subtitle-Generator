# -*- coding: utf-8 -*-
"""
3.0 第 5 項第三階段：照時間軸上的剪點輸出（`subtitle/cutmarks.py` 的 export_plan／
remap_time／remap_cues／render）。零 GUI 依賴，任何環境都跑（有 ffmpeg 時多跑真的剪）：

1. `remap_time` 對照定義：剪後的時間＝保留片段在 t 之前的總長（落在剪點裡＝接縫）。
   隨機 3000 組比對。
2. 跟一般版對照：全部啟用、字幕沒有落在剪點裡時，對齊結果跟 `apply_jumpcut`／
   `apply_retake_removal` 算出來的字幕一樣（隨機 300 份）。
3. 使用者拖過剪點邊以後：只被剪到一部分的字幕縮短、整句在剪點裡的拿掉、逐字時間
   跟著對齊；jumpcut.remap_cues 在這種情況會把字幕拉到片尾（這裡不會）。
4. 錯誤：還不知道片長、沒有啟用的剪點、剪完不剩、片段太多、輸出蓋到原檔。
5. ffmpeg 真的剪：剪完長度＝保留片段總長；停用的剪點真的沒剪。
"""
import os
import random
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import cutmarks, jumpcut, retakes  # noqa: E402
from subtitle.media import probe_duration  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


# ----- 1. remap_time 對照定義 -----
rng = random.Random(20260930)
bad = None
for _ in range(3000):
    keep, t0 = [], 0.0
    for _k in range(rng.randint(1, 6)):
        s = round(t0 + rng.choice([0.0, 0.3, 1.0, 2.5]), 3)
        e = round(s + rng.choice([0.2, 1.0, 3.0]), 3)
        keep.append((s, e))
        t0 = e
    t = round(rng.uniform(-0.5, t0 + 2), 3)
    want = round(sum(max(0.0, min(e, t) - s) for s, e in keep), 3)
    got = cutmarks.remap_time(t, keep)
    if abs(got - want) > 0.0015:
        bad = bad or (keep, t, got, want)
check("remap_time：3000 組隨機資料都等於「t 之前保留下來的總長」", bad is None, str(bad))
check("remap_time：剪點裡的時間對到接縫", cutmarks.remap_time(3.0, [(0, 2), (5, 10)]) == 2.0
      and cutmarks.remap_time(5.0, [(0, 2), (5, 10)]) == 2.0 and cutmarks.remap_time(6.5, [(0, 2), (5, 10)]) == 3.5)
check("jumpcut.remap_cues 在這種情況會把時間拉到片尾（所以另外寫）",
      jumpcut._remap_time(3.0, jumpcut._build_breakpoints([(0, 2), (5, 10)])) == 7.0)

# ----- 2. 跟一般版對照 -----
captured = {}


def fake_cut(media_path, keep_segments, output_path, progress_cb=None, label=""):
    captured["keep"] = list(keep_segments)
    return sum(e - s for s, e in keep_segments)


saved = (jumpcut.cut_media_segments, jumpcut.probe_duration, jumpcut.ffmpeg_available,
         retakes.cut_media_segments, retakes.probe_duration, retakes.ffmpeg_available)
box = {}
jumpcut.cut_media_segments = retakes.cut_media_segments = fake_cut
jumpcut.probe_duration = retakes.probe_duration = lambda _p: box["d"]
jumpcut.ffmpeg_available = retakes.ffmpeg_available = lambda: True
real_exists = os.path.exists
os.path.exists = lambda p: True if p == "影片.mp4" else real_exists(p)
SENT = ["大家好歡迎收看今天的節目", "今天要介紹一個很好用的工具", "我們先來看第一個功能", "嗯", "好",
        "接下來是第二個功能", "謝謝大家的收看我們下次見"]
compared = {"jumpcut": 0, "retakes": 0}
mismatch = {"jumpcut": None, "retakes": None}
try:
    for _ in range(300):
        cues, t = [], rng.uniform(0, 2)
        for _k in range(rng.randint(2, 14)):
            text = rng.choice(SENT)
            if cues and rng.random() < 0.3:
                text = cues[-1]["text"] + "喔"
            length = rng.choice([0.5, 1.5, 3.0])
            cues.append({"start": round(t, 3), "end": round(t + length, 3), "text": text})
            t += length + rng.choice([0.1, 0.6, 1.5, 3.0, 5.0])
        duration = round(t + 1, 3)
        box["d"] = duration
        plan = cutmarks.plan("jumpcut", cues, duration)
        if plan["marks"]:
            try:
                result = jumpcut.apply_jumpcut("影片.mp4", cues, "out.mp4")
            except ValueError:
                result = None  # 一般版拒剪（剪太多）：照時間軸輸出不受這條限制
            if result is not None:
                mine = cutmarks.export_plan(plan["marks"], duration, cues)
                compared["jumpcut"] += 1
                same_keep = len(mine["keep"]) == len(captured["keep"]) and all(
                    abs(a - b) < 0.0015 for x, y in zip(mine["keep"], captured["keep"]) for a, b in zip(x, y))
                if not same_keep or mine["cues"] != result["cues"] or mine["dropped"] != 0:
                    diff = [(a, b) for a, b in zip(mine["cues"], result["cues"]) if a != b]
                    mismatch["jumpcut"] = mismatch["jumpcut"] or (
                        same_keep, mine["keep"][:3], captured["keep"][:3], len(mine["cues"]),
                        len(result["cues"]), mine["dropped"], diff[:2])
        found = retakes.find_retakes(cues)
        plan = cutmarks.plan("retakes", cues, duration)
        if found:
            removed = {r["index"] for r in found}
            spans = [(m["start"], m["end"]) for m in plan["marks"]]
            others_clear = all(not (s < c["end"] and e > c["start"])
                               for i, c in enumerate(cues) if i not in removed for s, e in spans)
            if others_clear:
                result = retakes.apply_retake_removal("影片.mp4", cues, found, "out.mp4")
                mine = cutmarks.export_plan(plan["marks"], duration, cues)
                compared["retakes"] += 1
                if mine["cues"] != result["cues"] or mine["dropped"] != len(removed):
                    mismatch["retakes"] = mismatch["retakes"] or (cues, mine["cues"], result["cues"])
finally:
    (jumpcut.cut_media_segments, jumpcut.probe_duration, jumpcut.ffmpeg_available,
     retakes.cut_media_segments, retakes.probe_duration, retakes.ffmpeg_available) = saved
    os.path.exists = real_exists
check(f"全部啟用的停頓跳剪：保留片段（毫秒內）與對齊後的字幕跟 apply_jumpcut 一樣（{compared['jumpcut']} 份）",
      mismatch["jumpcut"] is None and compared["jumpcut"] > 150, str(mismatch["jumpcut"])[:400])
check(f"全部啟用的重複片段：對齊後的字幕跟 apply_retake_removal 一樣、重講的句子拿掉（{compared['retakes']} 份）",
      mismatch["retakes"] is None and compared["retakes"] > 50, str(mismatch["retakes"])[:400])

# ----- 3. 拖過剪點邊以後 -----
CUES = [{"start": 1.0, "end": 3.0, "text": "一"},
        {"start": 4.0, "end": 6.0, "text": "二", "words": [{"word": "二", "start": 4.0, "end": 5.0},
                                                           {"word": "！", "start": 5.0, "end": 6.0}]},
        {"start": 7.0, "end": 8.0, "text": "三"},
        {"start": 9.0, "end": 10.0, "text": "四"}]
marks = [{"start": 2.5, "end": 4.5, "enabled": True},    # 剪到「一」的尾巴和「二」的頭
         {"start": 6.8, "end": 8.2, "enabled": True},    # 「三」整句在裡面
         {"start": 8.5, "end": 8.9, "enabled": False}]   # 停用：不剪
out = cutmarks.export_plan(marks, 12.0, CUES)
check("保留片段：停用那段不剪", out["keep"] == [(0.0, 2.5), (4.5, 6.8), (8.2, 12.0)], str(out["keep"]))
check("只被剪到一部分的縮短（一：1.0～2.5；二：接縫 2.5～4.0）、整句在剪點裡的拿掉（三）",
      [(c["text"], c["start"], c["end"]) for c in out["cues"]]
      == [("一", 1.0, 2.5), ("二", 2.5, 4.0), ("四", 5.6, 6.6)] and out["dropped"] == 1,
      str(out["cues"]))
check("逐字時間跟著對齊（二的第一個字頭被剪掉 → 從接縫開始）",
      out["cues"][1]["words"] == [{"word": "二", "start": 2.5, "end": 3.0}, {"word": "！", "start": 3.0, "end": 4.0}],
      str(out["cues"][1].get("words")))
check("統計：剪 2 處、保留 8.6 秒（2.5＋2.3＋3.8）、剪掉 3.4 秒",
      (out["cut_count"], out["kept_seconds"], out["removed_seconds"]) == (2, 8.6, 3.4), str(out))
check("不改傳進來的字幕", CUES[1]["start"] == 4.0 and CUES[1]["words"][0]["start"] == 4.0)
old_way = jumpcut.remap_cues(CUES, out["keep"])
check("對照：jumpcut.remap_cues 會把「一」的結尾拉到片尾（這就是另外寫的原因）",
      old_way[0]["end"] == 8.6, str(old_way[0]))
tiny, n = cutmarks.remap_cues([{"start": 2.46, "end": 4.6, "text": "x"}], out["keep"])
check("剪後短於 0.05 秒的拿掉（2.46～4.6 剪後只剩 0.04＋0.1…＝0.14 秒 → 留著；2.48～4.52 → 拿掉）",
      len(tiny) == 1 and cutmarks.remap_cues([{"start": 2.48, "end": 4.52, "text": "x"}], out["keep"])[1] == 1,
      str(tiny))
check("建議檔名：原檔名加「_剪輯」", cutmarks.suggest_output_path("/a/b/影片.mov") == "/a/b/影片_剪輯.mov"
      and cutmarks.suggest_output_path("/a/b/無副檔名") == "/a/b/無副檔名_剪輯.mp4")

# ----- 4. 錯誤 -----


def raises(fn, text):
    try:
        fn()
    except ValueError as exc:
        return text in str(exc)
    return False


check("還不知道片長 → 說明要先開影片", raises(lambda: cutmarks.export_plan(marks, 0, CUES), "片長"))
check("沒有啟用的剪點 → 說明", raises(lambda: cutmarks.export_plan([dict(marks[2])], 12, CUES), "沒有啟用"))
check("剪完什麼都不剩 → 說明", raises(lambda: cutmarks.export_plan([{"start": 0, "end": 12}], 12, CUES), "不剩"))
many = [{"start": i + 0.5, "end": i + 0.7} for i in range(jumpcut.MAX_SEGMENTS)]
check("片段超過裁切引擎的上限 → 說明（剛好上限不擋）",
      raises(lambda: cutmarks.export_plan(many, jumpcut.MAX_SEGMENTS + 1, []), "太多")
      and len(cutmarks.export_plan(many[:-1], jumpcut.MAX_SEGMENTS, [])["keep"]) == jumpcut.MAX_SEGMENTS)
check("輸出檔跟原始影片同一個 → 說明（不會蓋掉原檔）",
      raises(lambda: cutmarks.render("/tmp/x/a.mp4", out, "/tmp/x/../x/a.mp4"), "同一個"))

# ----- 5. ffmpeg 真的剪 -----
if shutil.which("ffmpeg") and shutil.which("ffprobe"):
    work = tempfile.mkdtemp(prefix="cutexport-")
    try:
        src = os.path.join(work, "src.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=25",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "12",
                        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", src], check=True)
        duration = probe_duration(src)
        plan = cutmarks.export_plan(marks, duration, CUES)
        progress = []
        dst = os.path.join(work, "out.mp4")
        kept = cutmarks.render(src, plan, dst, lambda r, m: progress.append((r, m)))
        got = probe_duration(dst)
        check("真的剪：長度＝保留片段總長（誤差 0.15 秒）、有回報進度",
              abs(got - plan["kept_seconds"]) <= 0.15 and abs(kept - plan["kept_seconds"]) < 0.01
              and progress and progress[-1][0] == 1.0, f"{got} vs {plan['kept_seconds']} {progress[-1:]}")
        all_on = cutmarks.export_plan([dict(m, enabled=True) for m in marks], duration, CUES)
        check("停用的剪點真的沒剪（全部啟用會再短 0.4 秒）",
              abs((plan["kept_seconds"] - all_on["kept_seconds"]) - 0.4) < 0.01)
    finally:
        shutil.rmtree(work, ignore_errors=True)
else:
    print("SKIP 沒有 ffmpeg：略過真的剪")

print()
if failures:
    print(f"{len(failures)} 項失敗")
    sys.exit(1)
print("照時間軸剪點輸出（核心層）測試全數通過。")
