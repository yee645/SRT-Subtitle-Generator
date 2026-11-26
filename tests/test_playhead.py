# -*- coding: utf-8 -*-
"""
剪輯器版面改版 E-6a：播放頭的規則（subtitle/playhead.py，零 GUI 依賴）。

1. 時間碼：時:分:秒.百分之一秒；百分之一秒捨去不進位；負的當 0；超過一小時照寫。
2. 影格率：不合理的（None、0、負的、超過 240、NaN、字串）一律當 30。
3. 逐格：對齊到格的開頭；往前、往後、一次多格；不出片頭、不過片尾最後一格；29.97 這種非整數也不會卡在同一格。
4. J／K／L：L 沒在播＝1 倍、在播快一級到 4 倍為止；J 倒退 1 秒不出片頭。
5. 模組不 import 任何 GUI 或 config。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from subtitle import playhead as ph  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


# ----- 1 -----
check("時間碼：0", ph.format_timecode(0) == "00:00:00.00")
check("時間碼：12.405 秒捨去成 .40", ph.format_timecode(12405) == "00:00:12.40", ph.format_timecode(12405))
check("時間碼：59.999 秒不進位成下一分", ph.format_timecode(59999) == "00:00:59.99")
check("時間碼：超過一小時", ph.format_timecode(3723450) == "01:02:03.45")
check("時間碼：負的當 0", ph.format_timecode(-5) == "00:00:00.00")

# ----- 2 -----
check("影格率：正常的照用", ph.clean_fps(25) == 25.0 and ph.clean_fps("29.97") == 29.97)
check("影格率：不合理的當 30", all(ph.clean_fps(v) == 30.0 for v in (None, 0, -24, 500, float("nan"), "abc")))

# ----- 3 -----
check("第幾格", ph.frame_index(0, 25) == 0 and ph.frame_index(39, 25) == 0 and ph.frame_index(40, 25) == 1)
check("格的開頭", ph.frame_start_ms(1, 25) == 40 and ph.frame_start_ms(3, 30) == 100)
check("下一格：從格中間走也對齊到下一格開頭", ph.step_frames(50, 1, 25) == 80)
check("上一格", ph.step_frames(85, -1, 25) == 40)
check("一次多格", ph.step_frames(0, 10, 25) == 400 and ph.step_frames(400, -3, 25) == 280)
check("不出片頭", ph.step_frames(20, -5, 25) == 0)
check("不過片尾最後一格", ph.step_frames(1900, 10, 25, duration_ms=2000) == 1960, str(ph.step_frames(1900, 10, 25, 2000)))
pos, seen = 0, []
for _ in range(60):
    pos = ph.step_frames(pos, 1, 29.97)
    seen.append(pos)
check("29.97：連走 60 格每次都往前、沒有卡住", all(b > a for a, b in zip([0] + seen, seen))
      and ph.frame_index(seen[-1], 29.97) == 60, str(seen[-3:]))
back = seen[-1]
for _ in range(60):
    back = ph.step_frames(back, -1, 29.97)
check("29.97：再退 60 格回到 0", back == 0, str(back))
check("走到的位置正好落在那一格裡面", all(ph.frame_index(ph.frame_start_ms(i, 23.976), 23.976) == i for i in range(500)))

# ----- 4 -----
check("L：沒在播＝1 倍", ph.next_rate(4.0, playing=False) == 1.0)
check("L：在播快一級", ph.next_rate(1.0, True) == 2.0 and ph.next_rate(2.0, True) == 4.0)
check("L：到頂不變", ph.next_rate(4.0, True) == 4.0 and ph.next_rate(8.0, True) == 4.0)
check("J：倒退 1 秒", ph.rewind(5000) == 4000 and ph.rewind(300) == 0)

# ----- 5 -----
src = open(os.path.join(ROOT, "subtitle", "playhead.py"), encoding="utf-8").read()
check("零 GUI 依賴、不 import config", not re.search(r"^\s*(import|from)\s+(PySide6|tkinter|config|gui)", src, re.M))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("播放頭規則（E-6a）測試全數通過。")
