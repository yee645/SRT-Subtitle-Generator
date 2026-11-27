# -*- coding: utf-8 -*-
"""
剪輯器版面 E-8b：連續調整併成一筆復原（subtitle/cueedit.py 的 EditHistory，`merge` 與 `end_merge`）。

1. 同一個鍵的連續修改（字幕時間、素材軌）只記一筆：復原一次回到最早的樣子，重做一次到最後的樣子。
2. 不併的情況：沒給鍵、鍵不一樣、`end_merge()` 之後、中間記了別的、復原或重做之後、清空或 forget 之後、
   同一個鍵但最上面那筆是另一種（字幕時間 vs 素材軌）或另一句。
3. 調回原樣：那一串整筆拿掉（沒得復原）；之後同一個鍵再改是新的一筆，不會併進底下不相干的那一筆。
4. 併的時候重做清空；併不會讓紀錄變多（上限照算）。
5. 沒給鍵的呼叫跟以前一模一樣（既有的呼叫點不受影響）。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from subtitle.cueedit import EditHistory  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


CUES = [{"start": 1.0, "end": 2.0, "text": "一"}, {"start": 3.0, "end": 4.0, "text": "二"}]


def starts(cues):
    return [c["start"] for c in cues]


def tracks(volume):
    return {"overlays": [], "music": [{"path": "m.wav", "at": 0.0, "out": 5.0, "volume": volume}]}


def size(h):
    return len(h._done)


# ----- 1 -----
h = EditHistory()
h.record(0, (1.0, 2.0), (1.1, 2.0), merge=("start", 0))
h.record(0, (1.1, 2.0), (1.2, 2.0), merge=("start", 0))
h.record(0, (1.2, 2.0), (1.3, 2.0), merge=("start", 0))
check("字幕時間連續改三次：只記一筆", size(h) == 1 and h._done[-1][2:] == ((1.0, 2.0), (1.3, 2.0)), str(h._done))
now = [dict(CUES[0], start=1.3), CUES[1]]
undone, focus = h.undo(now)
check("復原一次：回到最早的樣子", starts(undone) == [1.0, 3.0] and focus == 0 and not h.can_undo())
redone, _f = h.redo(undone)
check("重做一次：到最後的樣子", starts(redone) == [1.3, 3.0] and not h.can_redo())

t = EditHistory()
for before, after in ((1.0, 0.9), (0.9, 0.8), (0.8, 0.7)):
    t.record_tracks(tracks(before), tracks(after), merge=("volume", "music", 0))
check("素材軌連續改三次：只記一筆", size(t) == 1 and t.next_kind() == "tracks")
check("復原一次：回到最早的音量", t.step_tracks()["music"][0]["volume"] == 1.0 and not t.can_undo())
check("重做一次：到最後的音量", t.step_tracks(redo=True)["music"][0]["volume"] == 0.7)

# ----- 2 -----
h = EditHistory()
h.record(0, (1.0, 2.0), (1.1, 2.0))
h.record(0, (1.1, 2.0), (1.2, 2.0))
check("沒給鍵：照舊一次一筆", size(h) == 2)
h = EditHistory()
h.record(0, (1.0, 2.0), (1.1, 2.0), merge=("start", 0))
h.record(0, (1.1, 2.0), (1.1, 2.5), merge=("end", 0))
check("鍵不一樣（開始 vs 結束）：兩筆", size(h) == 2)
h = EditHistory()
h.record(0, (1.0, 2.0), (1.1, 2.0), merge=("start", 0))
h.end_merge()
h.record(0, (1.1, 2.0), (1.2, 2.0), merge=("start", 0))
check("end_merge 之後：另記一筆", size(h) == 2)
h = EditHistory()
h.record(0, (1.0, 2.0), (1.1, 2.0), merge=("start", 0))
h.record_text(1, "二", "二！")
h.record(0, (1.1, 2.0), (1.2, 2.0), merge=("start", 0))
check("中間記了別的：另記一筆", size(h) == 3)
h = EditHistory()
h.record(0, (1.0, 2.0), (1.1, 2.0), merge=("start", 0))
h.undo([dict(CUES[0], start=1.1), CUES[1]])
h.record(0, (1.0, 2.0), (1.2, 2.0), merge=("start", 0))
h.record(0, (1.2, 2.0), (1.3, 2.0), merge=("start", 0))
check("復原之後同一個鍵：新的一串（不併進已經退掉的那筆）", size(h) == 1 and h._done[-1][2:] == ((1.0, 2.0), (1.3, 2.0))
      and not h.can_redo(), str(h._done))
h = EditHistory()
h.record(0, (1.0, 2.0), (1.1, 2.0), merge=("start", 0))
h.record(0, (1.1, 2.0), (1.2, 2.0), merge=("start", 0))
h.undo([dict(CUES[0], start=1.2), CUES[1]])
h.redo([dict(CUES[0], start=1.0), CUES[1]])
h.record(0, (1.2, 2.0), (1.3, 2.0), merge=("start", 0))
check("重做之後同一個鍵：另記一筆", size(h) == 2)
h = EditHistory()
h.record(0, (1.0, 2.0), (1.5, 2.0))  # 底下一筆同一句、同一種，但不是那一串的
h.record(0, (1.5, 2.0), (1.6, 2.0), merge=("start", 0))
h.undo([dict(CUES[0], start=1.6), CUES[1]])
h.record(0, (1.5, 2.0), (1.7, 2.0), merge=("start", 0))
check("復原之後同一個鍵：不併進底下那筆", size(h) == 2 and h._done[0][2:] == ((1.0, 2.0), (1.5, 2.0)), str(h._done))
for name, reset in (("clear", lambda x: x.clear()), ("forget", lambda x: x.forget("text"))):
    h = EditHistory()
    h.record(0, (1.0, 2.0), (1.1, 2.0), merge=("start", 0))
    reset(h)
    h.record(0, (1.1, 2.0), (1.2, 2.0), merge=("start", 0))
    check(f"{name} 之後同一個鍵：另記一筆", size(h) == (1 if name == "clear" else 2))
t = EditHistory()
t.record_tracks(tracks(1.0), tracks(0.9), merge=("volume", "music", 0))
t.step_tracks()
t.step_tracks(redo=True)
t.record_tracks(tracks(0.9), tracks(0.8), merge=("volume", "music", 0))
check("素材軌復原再重做之後：另記一筆", size(t) == 2)
m = EditHistory()
m.record(0, (1.0, 2.0), (1.1, 2.0), merge="同一個鍵")
m.record_tracks(tracks(1.0), tracks(0.9), merge="同一個鍵")
check("同一個鍵但另一種（字幕時間 vs 素材軌）：兩筆", size(m) == 2)
m = EditHistory()
m.record(0, (1.0, 2.0), (1.1, 2.0), merge="同一個鍵")
m.record(1, (3.0, 4.0), (3.1, 4.0), merge="同一個鍵")
check("同一個鍵但另一句：兩筆", size(m) == 2)

# ----- 3 -----
h = EditHistory()
h.record(0, (1.0, 2.0), (1.5, 2.0))  # 底下一筆不相干的（同一句、同一種）
h.record(0, (1.5, 2.0), (1.6, 2.0), merge=("start", 0))
h.record(0, (1.6, 2.0), (1.5, 2.0), merge=("start", 0))
check("調回原樣：那一串整筆拿掉", size(h) == 1 and h._done[-1][2:] == ((1.0, 2.0), (1.5, 2.0)), str(h._done))
h.record(0, (1.5, 2.0), (1.7, 2.0), merge=("start", 0))
check("之後同一個鍵再改：新的一筆，不併進底下那筆", size(h) == 2 and h._done[-1][2:] == ((1.5, 2.0), (1.7, 2.0))
      and h._done[0][2:] == ((1.0, 2.0), (1.5, 2.0)), str(h._done))
t = EditHistory()
t.record_tracks(tracks(1.0), tracks(0.9), merge=("volume", "music", 0))
t.record_tracks(tracks(0.9), tracks(1.0), merge=("volume", "music", 0))
check("素材軌調回原樣：沒得復原", not t.can_undo())

# ----- 4 -----
h = EditHistory()
h.record(1, (3.0, 4.0), (3.5, 4.0))
h.record(0, (1.0, 2.0), (1.1, 2.0), merge=("start", 0))
h.undo([dict(CUES[0], start=1.1), dict(CUES[1], start=3.5)])
check("（準備）有得重做", h.can_redo())
h.record(0, (1.0, 2.0), (1.2, 2.0), merge=("start", 0))
check("新的修改照舊清掉重做", not h.can_redo())
small = EditHistory(limit=3)
for i in range(3):
    small.record(1, (3.0 + i, 4.0 + i), (3.0 + i + 1, 4.0 + i + 1))
for step in range(10):
    small.record(0, (1.0 + step / 100, 2.0), (1.0 + (step + 1) / 100, 2.0), merge=("start", 0))
check("併的時候不會變多（上限照算、最舊的才被擠掉一筆）", size(small) == 3 and small._done[-1][2:] == ((1.0, 2.0), (1.1, 2.0))
      and small._done[0][2] == (4.0, 5.0), str(small._done))

# ----- 5 -----
h = EditHistory()
h.record(0, (1.0, 2.0), (1.0, 2.0), merge=("start", 0))
check("沒有變：不記（照舊）", size(h) == 0)
plain = EditHistory()
plain.record(0, (1.0, 2.0), (1.1, 2.0))
plain.record(0, (1.1, 2.0), (1.0, 2.0))
check("沒給鍵、改回原樣：照舊兩筆（不會被拿掉）", size(plain) == 2)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("連續調整併成一筆復原（E-8b）測試全數通過。")
