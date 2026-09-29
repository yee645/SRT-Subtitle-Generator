# -*- coding: utf-8 -*-
"""
3.0 第 2 項第三階段：逐字動態字幕（karaoke／word）預覽的核心層。

`subtitle.exporter.dynamic_frame(cue, mode, 秒)` 回答「這一刻燒錄出來畫面上是什
麼」。零 GUI 依賴，任何環境都跑：

1. **跟燒錄逐刻對照**：隨機產生 400 句帶逐字時間的字幕（中英混雜、標點、空字、
   時間倒退、極短的字），每句取好幾個時間點——dynamic_frame 組回 ASS 文字，要
   等於 `_dynamic_dialogues`（燒錄用的那份）在那一刻生效的那一行；燒錄那一刻沒
   有字時，預覽也要沒有字。
2. 邊界：模式 off、沒有逐字資料、全是空字 → None（照一般整句顯示）。
3. word 模式的彈出縮放照 `_POP_TAG`：剛出現 0.8、60 ms 時 0.9、120 ms 以後 1。
4. `cueedit.with_times`：整句移動時逐字時間跟著平移，只拖一邊時不動。
"""
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import cueedit, exporter  # noqa: E402
from subtitle.exporter import dynamic_frame  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


TAG = "{\\1c&H0000FF&}"


def as_ass(frame, mode):
    """把 dynamic_frame 的結果組回燒錄會寫的 ASS 文字。"""
    if mode == "word":
        return exporter._POP_TAG + "".join(p for p, _lit in frame["segments"])
    return "".join(f"{TAG}{p}{{\\r}}" if lit else p for p, lit in frame["segments"])


def burned_at(cue, mode, t):
    """燒錄在 t 這一刻顯示的那一行（沒有就是 None）。"""
    for start, end, text in exporter._dynamic_dialogues(cue, mode, TAG):
        if start <= t < end:
            return text
    return None


# ----- 1. 跟燒錄逐刻對照 -----
random.seed(20260929)
vocab = ["Hello", "world", ",", "今天", "天氣", "很好", "!", "don't", "OK", "。", "テスト", "a",
         "", " ", "100%", "(yes)", "é", "Premiere"]
compared = mismatches = empty_both = 0
first_bad = None
for i in range(400):
    t0 = round(random.uniform(0, 100), 3)
    ws, words = t0, []
    for _k in range(random.randint(1, 8)):
        d = random.choice([0.0, 0.01, 0.03, 0.05, 0.2, 0.4])
        words.append({"word": random.choice(vocab), "start": round(ws, 3), "end": round(ws + d, 3)})
        ws += d
        if random.random() < 0.1:
            ws -= 0.05  # 時間倒退也要照燒錄的夾法
    cue = {"start": t0, "end": round(t0 + random.choice([0.02, 0.5, 1.2, 3.0]), 3), "text": "x",
           "words": words}
    samples = [cue["start"], cue["end"] - 1e-6] + [w["start"] for w in words] \
        + [w["start"] + 0.001 for w in words] + [random.uniform(cue["start"], cue["end"]) for _ in range(5)]
    for mode in ("karaoke", "word"):
        for t in samples:
            if not cue["start"] <= t < cue["end"]:
                continue
            frame = dynamic_frame(cue, mode, t)
            burned = burned_at(cue, mode, t)
            if frame is None:
                ok = burned is None and not exporter._dynamic_dialogues(cue, mode, TAG)
            elif not frame["segments"]:
                ok = burned is None
                empty_both += ok
            else:
                ok = burned == as_ass(frame, mode)
            compared += 1
            if not ok:
                mismatches += 1
                first_bad = first_bad or (mode, t, cue, frame, burned)
check(f"跟燒錄逐刻對照：400 句 × 多個時間點 × 兩種模式（{compared} 次）全部一樣",
      mismatches == 0 and compared > 5000, f"{mismatches} 次不一樣，第一個：{first_bad}")
check("對照裡確實有「燒錄那一刻沒有字」的情況（極短的字被略過），預覽也沒有字",
      empty_both > 0, str(empty_both))

# ----- 2. 邊界 -----
words = [{"word": "今天", "start": 1.0, "end": 1.4}, {"word": "天氣", "start": 1.4, "end": 1.9},
         {"word": "Hello", "start": 1.9, "end": 2.3}, {"word": "world", "start": 2.3, "end": 3.0}]
cue = {"start": 1.0, "end": 3.0, "text": "今天天氣 Hello world", "words": words}
check("模式 off → None（照一般整句）", dynamic_frame(cue, "off", 1.5) is None)
check("不認得的模式 → None", dynamic_frame(cue, "bounce", 1.5) is None)
check("沒有逐字資料 → None", dynamic_frame({"start": 0, "end": 1, "text": "x"}, "karaoke", 0.5) is None)
check("逐字資料全是空字 → None（燒錄也退回整句）",
      dynamic_frame({"start": 0, "end": 1, "text": "x", "words": [{"word": " ", "start": 0, "end": 1}]},
                    "karaoke", 0.5) is None)
k = dynamic_frame(cue, "karaoke", 2.0)
check("karaoke：整句都在、講到的字亮起（2.0 秒 → Hello）；中文與中英交界不空格、英文之間空一格"
      "（跟燒錄既有的規則一樣）",
      k["segments"] == [("今天", False), ("天氣", False), ("Hello", True), (" ", False),
                        ("world", False)] and k["scale"] == 1.0, str(k))
w = dynamic_frame(cue, "word", 1.45)
check("word：只有當前的字（1.45 秒 → 天氣）", w["segments"] == [("天氣", False)], str(w))
check("句子範圍外 → 沒有字", dynamic_frame(cue, "karaoke", 3.0)["segments"] == []
      and dynamic_frame(cue, "karaoke", 0.5)["segments"] == [])

# ----- 3. 彈出縮放 -----
m = re.search(r"fscx(\d+).*\\t\(0,(\d+),", exporter._POP_TAG)
check("彈出動畫的參數與燒錄的 _POP_TAG 一致（80%、120 ms）",
      m and int(m.group(1)) / 100 == exporter.POP_FROM_SCALE and int(m.group(2)) / 1000 == exporter.POP_SECONDS,
      exporter._POP_TAG)
scales = [round(dynamic_frame(cue, "word", 1.4 + dt)["scale"], 3) for dt in (0, 0.06, 0.12, 0.3)]
check("word：剛出現 0.8、60 ms 時 0.9、120 ms 以後 1", scales == [0.8, 0.9, 1.0, 1.0], str(scales))
check("karaoke 不縮放", dynamic_frame(cue, "karaoke", 1.4)["scale"] == 1.0)

# ----- 4. 整句移動時逐字時間跟著平移 -----
cues = [cue, {"start": 5.0, "end": 6.0, "text": "別句", "words": [{"word": "別句", "start": 5.0, "end": 6.0}]}]
moved = cueedit.with_times(cues, 0, 1.5, 3.5)
check("整句往後 0.5 秒 → 每個字的開始與結束都 +0.5",
      [(x["start"], x["end"]) for x in moved[0]["words"]]
      == [(1.5, 1.9), (1.9, 2.4), (2.4, 2.8), (2.8, 3.5)], str(moved[0]["words"]))
check("平移後同一個相對時間顯示同一個字（原本 2.0 秒是 Hello → 現在 2.5 秒）",
      dynamic_frame(moved[0], "karaoke", 2.5)["segments"] == k["segments"])
check("平移不改到傳進來的清單、也不動別句", cue["words"][0]["start"] == 1.0
      and moved[1]["words"] == cues[1]["words"] and moved[0]["words"][0] is not cue["words"][0])
check("字的其他欄位保留", moved[0]["words"][2]["word"] == "Hello")
trim = cueedit.with_times(cues, 0, 1.2, 3.0)
check("只拖左邊（長度變了）→ 逐字時間不動", trim[0]["words"] == cue["words"])
trim2 = cueedit.with_times(cues, 0, 1.0, 2.5)
check("只拖右邊 → 逐字時間不動", trim2[0]["words"] == cue["words"])
back = cueedit.with_times(moved, 0, 1.0, 3.0)
check("移回去（復原）→ 逐字時間回到原樣", [(x["start"], x["end"]) for x in back[0]["words"]]
      == [(x["start"], x["end"]) for x in cue["words"]], str(back[0]["words"]))
plain = cueedit.with_times([{"start": 1, "end": 2, "text": "x"}], 0, 2, 3)
check("沒有逐字資料的句子照常移動", plain[0]["start"] == 2 and "words" not in plain[0])
tiny = cueedit.with_times(cues, 0, 1.0004, 3.0004)
check("不到 1 毫秒的移動不算移動（逐字時間不動）", tiny[0]["words"] == cue["words"])

print()
if failures:
    print(f"{len(failures)} 項失敗")
    sys.exit(1)
print("逐字動態字幕預覽（核心層）測試全數通過。")
