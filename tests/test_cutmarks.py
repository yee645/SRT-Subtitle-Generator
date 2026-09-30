# -*- coding: utf-8 -*-
"""
3.0 第 5 項第一階段：`subtitle/cutmarks.py`——三種自動剪輯「會剪掉哪幾段」。

零 GUI 依賴，任何環境都跑（有 ffmpeg 時多跑真的剪片對照）：

1. **跟真的剪片對照**：攔下 `apply_jumpcut`／`apply_retake_removal` 交給裁切引擎
   的「保留片段」，隨機 300 份字幕逐份比——剪點必須剛好是保留片段以外的部分。
   審片比對 `cut_rough_video` 用的 `kept_ranges`。
2. **真的用 ffmpeg 剪一次**：三種來源各剪一支測試片，剪完的長度＝片長－剪點總長。
3. 不變式：剪點排好序、不重疊、在片長內；跳剪不剪到任何一句；重複片段的那句整句
   在剪點裡；審片建議保留的段落不被剪到。
4. 原因、摘要、沒有剪點時的說明、逐字時間軸的來源。
5. `retakes.retake_keep_segments` 抽出來之後，結果跟抽出來之前那段程式一模一樣。
6. 第二階段：`apply_overrides`（停用、拖過的起訖套回重算後的剪點）、`drag_mark_edge`
   （不過鄰段、不出片頭片尾、最短 0.05 秒）、`recount`／`summary` 只算啟用的、
   `kept_segments`（全部啟用時＝跳剪真正保留的片段）。
"""
import os
import random
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import cutmarks, jumpcut, retakes, review  # noqa: E402
from subtitle.media import probe_duration  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def spans(result):
    return [(m["start"], m["end"]) for m in result["marks"]]


def close(a, b, tol=0.0015):
    return len(a) == len(b) and all(abs(x[0] - y[0]) <= tol and abs(x[1] - y[1]) <= tol
                                    for x, y in zip(a, b))


SENTENCES = ["大家好歡迎收看今天的節目", "今天要介紹一個很好用的工具", "我們先來看第一個功能",
             "這個按鈕按下去就會開始", "Let me show you how it works", "嗯", "呃這個", "好",
             "接下來是第二個功能", "謝謝大家的收看我們下次見"]


def random_cues(rng):
    cues, t = [], rng.uniform(0, 3)
    for _ in range(rng.randint(2, 18)):
        text = rng.choice(SENTENCES)
        if rng.random() < 0.3 and cues:
            text = cues[-1]["text"] + rng.choice(["", "喔", "啦"])  # 重講
        length = rng.choice([0.4, 1.0, 2.0, 3.5])
        cues.append({"start": round(t, 3), "end": round(t + length, 3), "text": text})
        t += length + rng.choice([0.05, 0.3, 0.8, 1.3, 2.5, 6.0])
    return cues, round(t + rng.choice([0.0, 1.0, 4.0]), 3)


# ----- 1. 跟真的剪片對照（攔下交給裁切引擎的保留片段） -----
captured = {}


def fake_cut(media_path, keep_segments, output_path, progress_cb=None, label=""):
    captured["keep"] = list(keep_segments)
    return sum(e - s for s, e in keep_segments)


saved = (jumpcut.cut_media_segments, jumpcut.probe_duration, jumpcut.ffmpeg_available,
         retakes.cut_media_segments, retakes.probe_duration, retakes.ffmpeg_available)
duration_box = {}
jumpcut.cut_media_segments = retakes.cut_media_segments = fake_cut
jumpcut.probe_duration = retakes.probe_duration = lambda _p: duration_box["d"]
jumpcut.ffmpeg_available = retakes.ffmpeg_available = lambda: True
real_exists = os.path.exists
os.path.exists = lambda p: True if p == "影片.mp4" else real_exists(p)

rng = random.Random(20260930)
compared = {"jumpcut": 0, "retakes": 0, "review": 0}
bad = {"jumpcut": None, "retakes": None, "review": None}
refused = 0
invariant_bad = []
try:
    for _ in range(300):
        cues, duration = random_cues(rng)
        duration_box["d"] = duration
        # 跳剪
        mine = cutmarks.plan("jumpcut", cues, duration)
        try:
            jumpcut.apply_jumpcut("影片.mp4", cues, "out.mp4")
            expected = cutmarks.cut_spans(captured["keep"], duration)
        except ValueError:
            refused += 1
            expected = None  # 一般版拒絕剪（沒有停頓、比例過高）：剪點照算，另有說明
        if expected is not None:
            compared["jumpcut"] += 1
            if not close(spans(mine), expected):
                bad["jumpcut"] = bad["jumpcut"] or (cues, duration, spans(mine), expected)
        elif mine["marks"] and not mine["note"]:
            invariant_bad.append(("跳剪被拒卻沒有說明", cues))
        # 重複片段（一般版對話框預設全勾）
        mine = cutmarks.plan("retakes", cues, duration)
        found = retakes.find_retakes(cues)
        if found:
            retakes.apply_retake_removal("影片.mp4", cues, found, "out.mp4")
            compared["retakes"] += 1
            if not close(spans(mine), cutmarks.cut_spans(captured["keep"], duration)):
                bad["retakes"] = bad["retakes"] or (cues, duration, spans(mine))
            for r in found:  # 重講的那句整句都在剪點裡
                if not any(s <= r["start"] + 1e-9 and r["end"] <= e + 1e-9 for s, e in spans(mine)):
                    invariant_bad.append(("重複的那句沒被整句剪掉", r))
        elif mine["marks"]:
            invariant_bad.append(("沒有重複卻有剪點", cues))
        # 審片（cut_rough_video 用的就是 kept_ranges）
        mine = cutmarks.plan("review", cues, duration)
        items = review.analyze(cutmarks.words_from_cues(cues), media_duration=duration,
                               settings=review.resolve_settings())
        expected = cutmarks.cut_spans(review.kept_ranges(items), duration)
        compared["review"] += 1
        if not close(spans(mine), expected):
            bad["review"] = bad["review"] or (cues, duration, spans(mine), expected)
        for item in items:  # 建議保留的段落不被剪到
            if item["keep"] and any(s < item["end"] - 1e-6 and e > item["start"] + 1e-6
                                    for s, e in spans(mine)):
                invariant_bad.append(("保留的段落被剪到", item))
        # 共同的不變式
        for source in cutmarks.SOURCES:
            got = spans(cutmarks.plan(source, cues, duration))
            ok = all(0 <= s < e <= duration + 1e-9 for s, e in got) \
                and all(a[1] < b[0] for a, b in zip(got, got[1:]))
            if not ok:
                invariant_bad.append((source, "剪點沒排好或超出片長", got))
            if source == "jumpcut":
                for cue in cues:
                    if any(s < cue["end"] - 1e-6 and e > cue["start"] + 1e-6 for s, e in got):
                        invariant_bad.append(("跳剪剪到講話", cue, got))
finally:
    (jumpcut.cut_media_segments, jumpcut.probe_duration, jumpcut.ffmpeg_available,
     retakes.cut_media_segments, retakes.probe_duration, retakes.ffmpeg_available) = saved
    os.path.exists = real_exists

check(f"跳剪：跟 apply_jumpcut 真正交給裁切引擎的片段一致（{compared['jumpcut']} 份，另 {refused} 份一般版拒剪）",
      bad["jumpcut"] is None and compared["jumpcut"] > 150, str(bad["jumpcut"]))
check(f"重複片段：跟 apply_retake_removal（全勾）一致（{compared['retakes']} 份）",
      bad["retakes"] is None and compared["retakes"] > 50, str(bad["retakes"]))
check(f"審片建議：跟 cut_rough_video 用的 kept_ranges 一致（{compared['review']} 份）",
      bad["review"] is None, str(bad["review"]))
check("不變式：排好序不重疊、在片長內；跳剪不剪講話；重講的整句在剪點裡；審片保留的不被剪；被拒時有說明",
      not invariant_bad, str(invariant_bad[:2]))
check("隨機資料裡確實有一般版拒剪的情況（說明那一條有被測到）", refused > 0, str(refused))

# ----- 2. 真的用 ffmpeg 剪一次 -----
CUES = [
    {"start": 0.5, "end": 2.5, "text": "大家好歡迎收看今天的節目"},
    {"start": 6.0, "end": 8.0, "text": "大家好歡迎收看今天的節目喔"},
    {"start": 9.0, "end": 10.0, "text": "今天要介紹一個很好用的工具"},
    {"start": 13.5, "end": 15.5, "text": "我們先來看第一個功能"},
    {"start": 15.8, "end": 17.0, "text": "謝謝大家"},
]
if shutil.which("ffmpeg") and shutil.which("ffprobe"):
    work = tempfile.mkdtemp(prefix="cutmarks-")
    try:
        src = os.path.join(work, "src.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=25",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "20",
                        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", src],
                       check=True)
        duration = probe_duration(src)
        results = []
        for source in cutmarks.SOURCES:
            plan = cutmarks.plan(source, CUES, duration)
            out = os.path.join(work, f"{source}.mp4")
            if source == "jumpcut":
                jumpcut.apply_jumpcut(src, CUES, out)
            elif source == "retakes":
                retakes.apply_retake_removal(src, CUES, retakes.find_retakes(CUES), out)
            else:
                items = review.analyze(cutmarks.words_from_cues(CUES), media_duration=duration,
                                       settings=review.resolve_settings())
                review.cut_rough_video(src, items, out)
            got = probe_duration(out)
            want = duration - plan["removed_seconds"]
            results.append((source, round(got, 3), round(want, 3), len(plan["marks"])))
        check("真的剪：三種來源剪完的長度＝片長－剪點總長（誤差 0.15 秒內），每種都有剪點",
              all(abs(g - w) <= 0.15 and n > 0 for _s, g, w, n in results), str(results))
    finally:
        shutil.rmtree(work, ignore_errors=True)
else:
    print("SKIP 沒有 ffmpeg：略過真的剪片對照")

# ----- 3. 原因與摘要 -----
jc = cutmarks.plan("jumpcut", CUES, 20.0)
check("跳剪：兩處停頓（2.5→6.0、10.0→13.5），兩側各留 0.15 秒",
      spans(jc) == [(2.65, 5.85), (10.15, 13.35)], str(spans(jc)))
check("跳剪：原因寫出停頓多長", jc["marks"][0]["reasons"] == ["句間停頓 3.5 秒"], str(jc["marks"][0]))
check("每個剪點都標上來源", all(m["source"] == "jumpcut" for m in jc["marks"]))
check("摘要：幾處、剪掉幾秒", cutmarks.summary(jc) == "停頓跳剪：2 處，共剪掉 6.4 秒", cutmarks.summary(jc))
rt = cutmarks.plan("retakes", CUES, 20.0)
check("重複片段：第一句（被後面重講）連同前後 0.2 秒", spans(rt) == [(0.3, 2.7)], str(spans(rt)))
check("重複片段：原因寫出跟哪一句像、像多少",
      rt["marks"][0]["reasons"][0].startswith("跟後面「大家好歡迎收看今天的節目喔」相似 9"),
      str(rt["marks"][0]["reasons"]))
rv = cutmarks.plan("review", CUES, 20.0)
check("審片：開頭到第一段冷場結束（0→5.85）一段剪掉，原因同時列出重複拍攝與冷場",
      spans(rv)[0] == (0.0, 5.85) and len(rv["marks"][0]["reasons"]) == 2
      and rv["marks"][0]["reasons"][0].startswith("重複拍攝：「大家好")
      and rv["marks"][0]["reasons"][1].startswith("冷場："), str(rv["marks"][0]))
check("審片：段落之間 1 秒的空檔（粗剪兩側各留 0.15 秒）也剪，沒有具名原因就寫「空檔」",
      rv["marks"][1] == {"source": "review", "start": 8.15, "end": 8.85,
                         "reasons": ["段落之間沒講話的空檔"],
                         "key": "review:8.150-8.850", "enabled": True}, str(rv["marks"][1]))
check("每個來源的每一段剪點都至少有一個原因（滑鼠停上去不會是空的）",
      all(m["reasons"] for src in cutmarks.SOURCES for m in cutmarks.plan(src, CUES, 20.0)["marks"]))
check("審片：片尾 17→20 的冷場也剪（需要片長）", spans(rv)[-1] == (17.15, 20.0), str(spans(rv)))

# ----- 4. 沒有剪點的說明 -----
check("沒有字幕 → 說明剪點從字幕算", cutmarks.plan("review", [], 10)["note"].startswith("還沒有字幕"))
check("只有零長度的字幕也算沒有", cutmarks.plan("jumpcut", [{"start": 1, "end": 1, "text": "x"}], 10)["marks"] == [])
tight = [{"start": 0, "end": 1, "text": "一"}, {"start": 1.2, "end": 2, "text": "二"}]
check("沒有夠長的停頓 → 說明門檻", cutmarks.summary(cutmarks.plan("jumpcut", tight, 2)) ==
      "停頓跳剪：沒有超過 1.2 秒的停頓", cutmarks.summary(cutmarks.plan("jumpcut", tight, 2)))
pad_only = cutmarks.plan("jumpcut", tight, 2, {"jumpcut": {"min_gap": 0.5, "pad": 0.1}})
check("設定照 config[\"jumpcut\"]（門檻調低就找得到 0.2 秒以外的…這裡 0.2 秒仍不夠 0.5）",
      pad_only["marks"] == [] and "0.5" in pad_only["note"], str(pad_only))
gap_pad = cutmarks.plan("jumpcut", [{"start": 0, "end": 1, "text": "一"}, {"start": 2.3, "end": 3, "text": "二"}], 3,
                        {"jumpcut": {"min_gap": 1.2, "pad": 0.7}})
check("停頓夠長但扣掉緩衝不夠剪 → 另有說明", gap_pad["marks"] == [] and "緩衝" in gap_pad["note"], str(gap_pad))
greedy = [{"start": 0, "end": 0.5, "text": "一"}, {"start": 9.5, "end": 10, "text": "二"}]
g = cutmarks.plan("jumpcut", greedy, 10)
check("剪太多（超過 max_cut_ratio）→ 剪點照畫、說明一般版會拒絕",
      len(g["marks"]) == 1 and "誤判" in g["note"] and "誤判" in cutmarks.summary(g), cutmarks.summary(g))
check("沒有重講 → 說明", cutmarks.plan("retakes", tight, 2)["note"] == "沒有找到疑似重講的句子")
try:
    cutmarks.plan("magic", CUES, 20)
    check("不認得的來源 → ValueError", False)
except ValueError:
    check("不認得的來源 → ValueError", True)
check("片長 0（還沒開影片）→ 以字幕最後為準，不剪片尾",
      spans(cutmarks.plan("review", CUES, 0))[-1][1] <= 17.0, str(spans(cutmarks.plan("review", CUES, 0))))

# ----- 5. 逐字時間軸 -----
words_cues = [{"start": 0, "end": 2, "text": "嗯 今天", "words": [
    {"word": "嗯", "start": 0.0, "end": 0.5}, {"word": "今天", "start": 0.6, "end": 2.0}]},
    {"start": 3, "end": 4, "text": "好", "words": [{"word": " 好", "start": 3.0, "end": 4.0}]}]
check("每句都有逐字資料 → 攤平用它（去掉前後空白）",
      [w["word"] for w in cutmarks.words_from_cues(words_cues)] == ["嗯", "今天", "好"])
mixed = words_cues + [{"start": 5, "end": 6, "text": "沒有逐字"}]
check("有一句沒有逐字資料 → 每句當一個字",
      [w["word"] for w in cutmarks.words_from_cues(mixed)] == ["嗯 今天", "好", "沒有逐字"])
check("空白字幕與零長度的不算", cutmarks.words_from_cues(
    [{"start": 0, "end": 1, "text": "  "}, {"start": 2, "end": 2, "text": "x"}]) == [])
fill = cutmarks.plan("review", words_cues, 4, {"review": {"cut_filler_words": True, "filler_density": 0.02}})
check("設定開了「一併剪掉口頭禪」＋有逐字資料 → 口頭禪那個字也畫成剪點",
      any(m["start"] <= 0.02 and m["end"] >= 0.48 and "口頭禪" in m["reasons"] for m in fill["marks"]),
      str(fill["marks"]))
nofill = cutmarks.plan("review", words_cues, 4, {"review": {"cut_filler_words": False, "filler_density": 0.02}})
check("沒開 → 口頭禪不剪", not any("口頭禪" in m["reasons"] for m in nofill["marks"]), str(nofill["marks"]))

# ----- 6. retake_keep_segments 抽出來前後一樣 -----


def old_keep(duration, selected, pad):
    cut = sorted((max(r["start"] - pad, 0.0), min(r["end"] + pad, duration)) for r in selected)
    keep, cursor = [], 0.0
    for s, e in cut:
        if s <= cursor:
            cursor = max(cursor, e)
            continue
        keep.append((cursor, s))
        cursor = e
    if cursor < duration:
        keep.append((cursor, duration))
    return keep


rng = random.Random(7)
same = 0
for _ in range(500):
    d = rng.uniform(5, 60)
    sel = []
    for _k in range(rng.randint(1, 6)):
        s = rng.uniform(-1, d)
        sel.append({"start": s, "end": s + rng.uniform(0.1, 8)})
    pad = rng.choice([0.0, 0.2, 1.0])
    same += retakes.retake_keep_segments(d, sel, pad) == old_keep(d, sel, pad)
check("retake_keep_segments：500 組隨機資料跟抽出來前的程式結果完全相同", same == 500, str(same))

# ----- 7. 第二階段：使用者的微調（停用、拖邊）-----
jc = cutmarks.plan("jumpcut", CUES, 20.0)
keys = [m["key"] for m in jc["marks"]]
check("每段剪點有 key（來源＋算出來的起訖）、預設啟用",
      keys == ["jumpcut:2.650-5.850", "jumpcut:10.150-13.350"]
      and all(m["enabled"] is True for m in jc["marks"]), str(keys))
over = {keys[0]: {"enabled": False}, keys[1]: {"start": 10.5, "end": 13.0}}
applied = cutmarks.apply_overrides(jc["marks"], over)
check("apply_overrides：第一段停用、第二段換成拖過的起訖並標 edited",
      [(m["enabled"], m["start"], m["end"], m["edited"]) for m in applied]
      == [(False, 2.65, 5.85, False), (True, 10.5, 13.0, True)], str(applied))
check("apply_overrides 不改傳進來的清單", jc["marks"][0]["enabled"] is True and jc["marks"][1]["start"] == 10.15)
check("apply_overrides：key 仍是算出來時的（再套一次同樣的微調結果一樣）",
      cutmarks.apply_overrides(applied, over) == applied)
check("對不上 key 的微調不理", cutmarks.apply_overrides(jc["marks"], {"jumpcut:1.000-2.000": {"enabled": False}})
      == [dict(m, edited=False) for m in jc["marks"]])
res = cutmarks.recount(dict(jc, marks=applied))
check("recount：只算啟用中的剪點（13.0−10.5＝2.5 秒）", res["removed_seconds"] == 2.5, str(res["removed_seconds"]))
check("摘要：只算啟用中的、另寫停用與調過幾處",
      cutmarks.summary(res) == "停頓跳剪：1 處，共剪掉 2.5 秒（停用 1 處；調過 1 處）", cutmarks.summary(res))
check("kept_segments：啟用中的剪點以外（停用那段不剪）",
      cutmarks.kept_segments(applied, 20.0) == [(0.0, 10.5), (13.0, 20.0)],
      str(cutmarks.kept_segments(applied, 20.0)))
check("kept_segments：全部啟用＝跳剪真正保留的片段",
      cutmarks.kept_segments(jc["marks"], 20.0)
      == jumpcut.compute_keep_segments(20.0, jumpcut.find_cut_gaps(CUES, 1.2), 0.15)[0],
      str(cutmarks.kept_segments(jc["marks"], 20.0)))
# 字幕改了、剪點重算：沒變的那段微調留著，變了的那段放掉
moved = [dict(c) for c in CUES]
moved[3] = dict(moved[3], start=14.0, end=15.9)  # 第二段停頓變長
again = cutmarks.apply_overrides(cutmarks.plan("jumpcut", moved, 20.0)["marks"], over)
check("重算後：停頓沒變的第一段仍停用；停頓變了的第二段 key 對不上 → 微調放掉（照新算的）",
      [(m["enabled"], m["start"], m["end"]) for m in again] == [(False, 2.65, 5.85), (True, 10.15, 13.85)],
      str(again))

M = [{"start": 2.0, "end": 4.0}, {"start": 6.0, "end": 8.0}, {"start": 10.0, "end": 11.0}]
check("拖左邊：往左不能過上一段的結束（4.0）", cutmarks.drag_mark_edge(M, 1, "start", 3.0) == (4.0, 8.0))
check("拖左邊：往右最多到結束前 0.05 秒", cutmarks.drag_mark_edge(M, 1, "start", 9.0) == (7.95, 8.0))
check("拖右邊：不能過下一段的開始（10.0）", cutmarks.drag_mark_edge(M, 1, "end", 12.0) == (6.0, 10.0))
check("拖右邊：往左最少留 0.05 秒", cutmarks.drag_mark_edge(M, 1, "end", 5.0) == (6.0, 6.05))
check("第一段往左到 0 為止", cutmarks.drag_mark_edge(M, 0, "start", -3.0) == (0.0, 4.0))
check("最後一段往右到片長為止", cutmarks.drag_mark_edge(M, 2, "end", 99.0, duration=12.5) == (10.0, 12.5))
check("最後一段、不知道片長 → 不設上限", cutmarks.drag_mark_edge(M, 2, "end", 99.0) == (10.0, 99.0))
check("中間照拖（毫秒為單位）", cutmarks.drag_mark_edge(M, 1, "start", 5.12345) == (5.123, 8.0))
check("清單沒排序也照開始時間找鄰居",
      cutmarks.drag_mark_edge([M[2], M[0], M[1]], 2, "end", 12.0) == (6.0, 10.0))
over_l = [{"start": 2.0, "end": 6.5}, {"start": 6.0, "end": 8.0}]
check("原本就重疊的不會被拉開，但也不能再往外拖",
      cutmarks.drag_mark_edge(over_l, 1, "start", 5.0) == (6.0, 8.0)
      and cutmarks.drag_mark_edge(over_l, 1, "start", 6.2) == (6.2, 8.0))
check("停用的剪點也是鄰居（不能拖進停用的那段，免得重新啟用時重疊）",
      cutmarks.drag_mark_edge([dict(M[0], enabled=False), M[1]], 1, "start", 1.0) == (4.0, 8.0))
try:
    cutmarks.drag_mark_edge(M, 0, "body", 1.0)
    check("edge 只能是 start／end", False)
except ValueError:
    check("edge 只能是 start／end", True)

print()
if failures:
    print(f"{len(failures)} 項失敗")
    sys.exit(1)
print("剪點可視化（核心層）測試全數通過。")
