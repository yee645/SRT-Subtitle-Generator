# -*- coding: utf-8 -*-
"""
3.0 第 11 項第四階段：字幕樣式的整理（subtitle/exporter.py 的 clean_style／vertical_zone）。

1. 預設值跟 config.py 的 _DEFAULT_STYLE 一模一樣（subtitle/ 不讀 config，兩份要釘住）。
2. 缺的補預設；字級 10～96、邊框寬 0～6、位置 0～1 夾回來；小數字級取整數。
3. 看不懂的換回預設：顏色不是 #RRGGBB、動態模式不認得、字型空白、數字不是數字（含 NaN）。
4. 顏色統一大寫；重點字詞去頭尾空白；不認得的欄位原樣留著；不改傳進來的 dict。
5. vertical_zone 跟燒錄的對齊（burn_layout 的 anchor）一致，三段的界線 0.33／0.66。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from subtitle import exporter  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


clean = exporter.clean_style

# ----- 1. 預設值 -----
check("預設值跟 config.py 一樣", exporter.STYLE_DEFAULTS == config._DEFAULT_STYLE,
      f"{exporter.STYLE_DEFAULTS} != {config._DEFAULT_STYLE}")
check("什麼都沒給：就是預設", clean(None) == config._DEFAULT_STYLE and clean({}) == config._DEFAULT_STYLE)

# ----- 2. 範圍 -----
check("字級夾在 10～96", clean({"font_size": 4})["font_size"] == 10 and clean({"font_size": 200})["font_size"] == 96
      and clean({"font_size": 40})["font_size"] == 40)
check("小數字級取整數", clean({"font_size": "30.7"})["font_size"] == 30)
check("邊框寬夾在 0～6", clean({"stroke_width": -2})["stroke_width"] == 0
      and clean({"stroke_width": 9})["stroke_width"] == 6)
check("位置夾在 0～1", clean({"position_y": 1.5})["position_y"] == 1.0 and clean({"position_y": -1})["position_y"] == 0.0
      and clean({"position_x": 2})["position_x"] == 1.0 and clean({"position_y": 0.25})["position_y"] == 0.25)

# ----- 3. 看不懂的換回預設 -----
check("顏色不是 #RRGGBB：換回預設", clean({"text_color": "red"})["text_color"] == "#FFFFFF"
      and clean({"stroke_color": "#12345"})["stroke_color"] == "#000000"
      and clean({"emphasis_color": 123})["emphasis_color"] == "#FFD700")
check("動態模式不認得：無", clean({"dynamic_mode": "blink"})["dynamic_mode"] == "off"
      and clean({"dynamic_mode": "word"})["dynamic_mode"] == "word")
check("字型空白：換回預設；有字就去頭尾空白", clean({"font_family": "  "})["font_family"] == "Microsoft JhengHei"
      and clean({"font_family": " Noto Sans CJK TC "})["font_family"] == "Noto Sans CJK TC")
check("數字不是數字（含 NaN、None）：換回預設", clean({"font_size": "大"})["font_size"] == 26
      and clean({"position_y": float("nan")})["position_y"] == 0.88 and clean({"stroke_width": None})["stroke_width"] == 2)

# ----- 4. 其他 -----
check("顏色統一大寫", clean({"text_color": " #ffcc00 "})["text_color"] == "#FFCC00")
check("重點字詞去頭尾空白、開關照給的", clean({"emphasis_words": " 重點, 字 ", "emphasis_enabled": 1})
      == dict(config._DEFAULT_STYLE, emphasis_words="重點, 字", emphasis_enabled=True))
given = {"font_size": 30, "future_option": "keep"}
out = clean(given)
check("不認得的欄位原樣留著、不改傳進來的", out["future_option"] == "keep" and given == {"font_size": 30, "future_option": "keep"}
      and out is not given)

# ----- 5. vertical_zone -----
anchors = {"top": "top", "middle": "middle", "bottom": "bottom"}
same = all(exporter.vertical_zone(y) == anchors[exporter.burn_layout({"position_y": y}, 1920, 1080)["anchor"]]
           for y in [i / 100 for i in range(101)])
check("三段跟燒錄的對齊方式一致（0～1 每 0.01 比過）", same)
check("界線：0.33 是上段、0.34 中段、0.65 中段、0.66 下段",
      [exporter.vertical_zone(y) for y in (0.33, 0.34, 0.65, 0.66)] == ["top", "middle", "middle", "bottom"])

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 字幕樣式整理的核心測試全數通過。")
