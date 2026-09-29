# -*- coding: utf-8 -*-
"""
3.0 第 4 項第二階段：`subtitle/cueedit.py`——拖曳字幕塊的邊改時間的規則。

零 GUI 依賴，任何環境都跑。時間軸（Qt）的拖曳測試在 test_qt_timeline.py。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import cueedit  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


CUES = [
    {"start": 1.0, "end": 3.0, "text": "一"},
    {"start": 4.0, "end": 6.0, "text": "二"},
    {"start": 7.5, "end": 9.0, "text": "三"},
]

# ----- 鄰居 -----
check("鄰居：第二句 → 上一句結束 3、下一句開始 7.5", cueedit.neighbours(CUES, 1) == (3.0, 7.5),
      str(cueedit.neighbours(CUES, 1)))
check("鄰居：第一句沒有上一句", cueedit.neighbours(CUES, 0) == (None, 4.0))
check("鄰居：最後一句沒有下一句", cueedit.neighbours(CUES, 2) == (6.0, None))
unsorted = [CUES[2], CUES[0], CUES[1]]
check("鄰居：清單沒排序也照開始時間找（第三句在清單第 0 個）",
      cueedit.neighbours(unsorted, 0) == (6.0, None) and cueedit.neighbours(unsorted, 2) == (3.0, 7.5),
      f"{cueedit.neighbours(unsorted, 0)} {cueedit.neighbours(unsorted, 2)}")
with_zero = CUES + [{"start": 3.5, "end": 3.5, "text": "零長度"}]
check("鄰居：零長度的句子不算（時間軸也不畫）", cueedit.neighbours(with_zero, 1) == (3.0, 7.5),
      str(cueedit.neighbours(with_zero, 1)))
same_start = [{"start": 2.0, "end": 3.0}, {"start": 2.0, "end": 4.0}]
check("鄰居：同一個開始時間，清單前面的算上一句",
      cueedit.neighbours(same_start, 1) == (3.0, None) and cueedit.neighbours(same_start, 0) == (None, 2.0),
      f"{cueedit.neighbours(same_start, 1)} {cueedit.neighbours(same_start, 0)}")

# ----- 拖左邊 -----
check("拖左邊：一般情況照拖（4 → 3.5）", cueedit.drag_edge(CUES, 1, "start", 3.5) == (3.5, 6.0))
check("拖左邊：不能拖進上一句（拖到 2 → 停在 3）", cueedit.drag_edge(CUES, 1, "start", 2.0) == (3.0, 6.0))
check("拖左邊：不能拖過右邊（拖到 10 → 停在結束前 0.1 秒）",
      cueedit.drag_edge(CUES, 1, "start", 10.0) == (5.9, 6.0),
      str(cueedit.drag_edge(CUES, 1, "start", 10.0)))
check("拖左邊：第一句不能拖到 0 秒以前", cueedit.drag_edge(CUES, 0, "start", -2) == (0.0, 3.0))
check("拖左邊：最短長度可以改（min_duration=0.5）",
      cueedit.drag_edge(CUES, 1, "start", 10.0, min_duration=0.5) == (5.5, 6.0))

# ----- 拖右邊 -----
check("拖右邊：一般情況照拖（6 → 6.8）", cueedit.drag_edge(CUES, 1, "end", 6.8) == (4.0, 6.8))
check("拖右邊：不能拖進下一句（拖到 9 → 停在 7.5）", cueedit.drag_edge(CUES, 1, "end", 9.0) == (4.0, 7.5))
check("拖右邊：不能拖過左邊（拖到 0 → 停在開始後 0.1 秒）",
      cueedit.drag_edge(CUES, 1, "end", 0.0) == (4.0, 4.1),
      str(cueedit.drag_edge(CUES, 1, "end", 0.0)))
check("拖右邊：最後一句不能拖過片尾", cueedit.drag_edge(CUES, 2, "end", 30, duration=10) == (7.5, 10.0))
check("拖右邊：不知道片長就不限", cueedit.drag_edge(CUES, 2, "end", 30) == (7.5, 30.0))
check("拖右邊：片尾與下一句取比較近的那個（片長 7 < 下一句 7.5）",
      cueedit.drag_edge(CUES, 1, "end", 9, duration=7) == (4.0, 7.0))

# ----- 原本就重疊／超出的，不硬拉開，也不能更糟 -----
overlap = [{"start": 1.0, "end": 5.0}, {"start": 4.0, "end": 8.0}]
check("原本重疊：左邊不能再往前拖（停在原本的 4）", cueedit.drag_edge(overlap, 1, "start", 2.0) == (4.0, 8.0))
check("原本重疊：往後拖照樣可以（4 → 5.5）", cueedit.drag_edge(overlap, 1, "start", 5.5) == (5.5, 8.0))
check("原本重疊：右邊不能再往後拖（停在原本的 5）", cueedit.drag_edge(overlap, 0, "end", 7.0) == (1.0, 5.0))
check("原本就超過片尾：保留，但不能再往外", cueedit.drag_edge(CUES, 2, "end", 12, duration=8.5) == (7.5, 9.0))

# ----- 吸附 -----
check("吸附：離播放頭 0.05 秒（容許 0.1）→ 貼上播放頭",
      cueedit.drag_edge(CUES, 1, "start", 4.55, snap_to=[4.6], snap_tolerance=0.1) == (4.6, 6.0))
check("吸附：超出容許就不吸",
      cueedit.drag_edge(CUES, 1, "start", 4.4, snap_to=[4.6], snap_tolerance=0.1) == (4.4, 6.0))
check("吸附：鄰句的邊一律是吸附點（右邊拖到 7.45 → 7.5）",
      cueedit.drag_edge(CUES, 1, "end", 7.45, snap_tolerance=0.1) == (4.0, 7.5))
check("吸附：取最近的那個（7.44 離 7.5 比離 7.3 近）",
      cueedit.drag_edge(CUES, 1, "end", 7.44, snap_to=[7.3], snap_tolerance=0.2) == (4.0, 7.5))
check("吸附後一樣要過界線（播放頭在上一句裡面 → 還是停在 3）",
      cueedit.drag_edge(CUES, 1, "start", 2.6, snap_to=[2.5], snap_tolerance=0.2) == (3.0, 6.0))
check("snap：沒有吸附點就是原值", cueedit.snap(1.23, [], 5) == 1.23)
check("snap：None 的吸附點略過", cueedit.snap(1.0, [None, 1.05], 0.1) == 1.05)

# ----- 毫秒 -----
got = cueedit.drag_edge(CUES, 1, "start", 3.123456)
check("結果取整毫秒（3.123456 → 3.123）", got == (3.123, 6.0), str(got))
float_cues = [{"start": 0.1 + 0.2, "end": 1.0}]
check("浮點誤差不讓合法的值被夾（0.30000000000000004 拖右邊到 0.4 → 0.4）",
      cueedit.drag_edge(float_cues, 0, "end", 0.4) == (0.3, 0.4),
      str(cueedit.drag_edge(float_cues, 0, "end", 0.4)))

try:
    cueedit.drag_edge(CUES, 0, "middle", 1)
    check("edge 打錯要報錯", False)
except ValueError:
    check("edge 打錯要報錯", True)

# ----- 抓到哪裡 -----
check("edge_at：左邊容許範圍內 → start", cueedit.edge_at(4, 6, 3.95, 0.1) == "start")
check("edge_at：右邊容許範圍內 → end", cueedit.edge_at(4, 6, 6.08, 0.1) == "end")
check("edge_at：中間 → body", cueedit.edge_at(4, 6, 5, 0.1) == "body")
check("edge_at：外面 → None", cueedit.edge_at(4, 6, 6.2, 0.1) is None)
check("edge_at：很窄的方塊兩邊各佔一半（0.1 秒寬、容許 0.2）",
      cueedit.edge_at(4, 4.1, 4.04, 0.2) == "start" and cueedit.edge_at(4, 4.1, 4.06, 0.2) == "end",
      f"{cueedit.edge_at(4, 4.1, 4.04, 0.2)} {cueedit.edge_at(4, 4.1, 4.06, 0.2)}")

# ----- 回寫 -----
new = cueedit.with_times(CUES, 1, 3.5, 6.5)
check("with_times：只改那一句的時間，其餘欄位保留",
      new[1] == {"start": 3.5, "end": 6.5, "text": "二"} and new[0] == CUES[0] and new[2] == CUES[2],
      str(new))
check("with_times：不改到傳進來的清單", CUES[1]["start"] == 4.0 and new[1] is not CUES[1])

print()
if failures:
    print(f"{len(failures)} 項失敗")
    sys.exit(1)
print("cueedit（拖曳改時間的規則）測試全數通過。")
