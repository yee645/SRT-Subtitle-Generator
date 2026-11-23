# -*- coding: utf-8 -*-
"""
3.0 第 11 項第三十一階段：習慣設定與斷句設定的規則（subtitle/profiles.py）。

1. 預設值與範圍跟設定檔（config._DEFAULT_SEGMENTATION）、一般版斷句設定區一樣。
2. clean_segmentation：每個欄位的上下限；最短不超過最長；壞掉的值退回原本的（沒給就預設）；其他鍵留著；不改傳入的。
3. 夾限規則跟一般版 `_read_segmentation_from_ui` 那幾行一模一樣（比對原始碼）。
4. check_new_name：去頭尾空白；空白不行；同名要問覆蓋。
5. after_delete：至少留一組；刪掉後改用名字排第一的；沒有這組原樣；不改傳入的。
6. 零 GUI 依賴、不 import config。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from subtitle import profiles as pf  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


# ----- 1 -----
check("預設值跟設定檔一樣", pf.SEGMENTATION_DEFAULTS == config._DEFAULT_SEGMENTATION)
check("欄位與範圍跟一般版一樣", [(k, lo, hi) for k, _l, lo, hi, _s, _u in pf.SEGMENTATION_FIELDS] == [
    ("max_chars_cjk", 4, 40), ("max_chars_latin", 10, 90), ("min_duration", 0.3, 5.0),
    ("max_duration", 2.0, 15.0), ("pause_gap", 0.2, 2.0), ("time_offset", -10.0, 10.0)])
check("整數欄位一格 1、秒數欄位有小數", [s for _k, _l, _lo, _hi, s, _u in pf.SEGMENTATION_FIELDS]
      == [1, 1, 0.1, 0.5, 0.1, 0.1])

# ----- 2 -----
check("合理的值原樣", pf.clean_segmentation(config._DEFAULT_SEGMENTATION) == config._DEFAULT_SEGMENTATION)
low = pf.clean_segmentation({"max_chars_cjk": 1, "max_chars_latin": 2, "min_duration": 0.0, "max_duration": 0.1,
                             "pause_gap": 0.0, "time_offset": -99})
check("太小：夾到下限（最長不小於最短）", low == {"max_chars_cjk": 4, "max_chars_latin": 10, "min_duration": 0.3,
                                      "max_duration": 0.3, "pause_gap": 0.2, "time_offset": -10.0}, str(low))
high = pf.clean_segmentation({"max_chars_cjk": 99, "max_chars_latin": 999, "min_duration": 9.0, "max_duration": 99,
                              "pause_gap": 9, "time_offset": 99})
check("太大：夾到上限（最短不超過最長）", high == {"max_chars_cjk": 40, "max_chars_latin": 90, "min_duration": 9.0,
                                       "max_duration": 15.0, "pause_gap": 2.0, "time_offset": 10.0}, str(high))
swap = pf.clean_segmentation(dict(config._DEFAULT_SEGMENTATION, min_duration=6.0, max_duration=3.0))
check("最短比最長大：最短改成最長", swap["min_duration"] == 3.0 and swap["max_duration"] == 3.0, str(swap))
base = dict(config._DEFAULT_SEGMENTATION, max_chars_cjk=12, pause_gap=0.8)
bad = pf.clean_segmentation({"max_chars_cjk": "abc", "pause_gap": None, "max_chars_latin": "50"}, base)
check("壞掉的值退回原本的、字串數字照讀", bad["max_chars_cjk"] == 12 and bad["pause_gap"] == 0.8
      and bad["max_chars_latin"] == 50, str(bad))
check("缺的欄位：沒給 base 就用預設", pf.clean_segmentation({}) == config._DEFAULT_SEGMENTATION)
check("整數欄位是 int", isinstance(pf.clean_segmentation({"max_chars_cjk": 12.7})["max_chars_cjk"], int)
      and pf.clean_segmentation({"max_chars_cjk": 12.7})["max_chars_cjk"] == 12)
given = {"max_chars_cjk": 99, "自訂": 1}
out = pf.clean_segmentation(given)
check("其他鍵留著、不改傳入的", out["自訂"] == 1 and given == {"max_chars_cjk": 99, "自訂": 1})

# ----- 3 -----
gui_src = open(os.path.join(os.path.dirname(config.__file__), "gui", "app.py"), encoding="utf-8").read()
for line in ('seg["max_chars_cjk"] = max(4, min(cjk, 40))', 'seg["max_chars_latin"] = max(10, min(latin, 90))',
             'seg["min_duration"] = max(0.3, min(min_dur, max_dur))',
             'seg["max_duration"] = max(seg["min_duration"], min(max_dur, 15.0))',
             'seg["pause_gap"] = max(0.2, min(pause, 2.0))', 'seg["time_offset"] = max(-10.0, min(offset, 10.0))'):
    mine = line.replace('seg["', 'out["').replace("(cjk", "(int(cjk)").replace("(latin", "(int(latin)")
    mine = mine.replace("min(int(cjk), 40)", "min(int(cjk), 40)")
    check(f"跟一般版同一條夾限：{line.split('=')[0].strip()}", line in gui_src
          and mine in open(pf.__file__, encoding="utf-8").read(), mine)

# ----- 4 -----
presets = {"預設": {}, "直式": {}}
check("去頭尾空白、新名字不覆蓋", pf.check_new_name("  旅遊 ", presets) == ("旅遊", "", False))
check("空白不行", pf.check_new_name("   ", presets) == ("", pf.EMPTY_NAME, False)
      and pf.check_new_name(None, presets)[1] == pf.EMPTY_NAME)
check("同名：要問覆蓋", pf.check_new_name("直式", presets) == ("直式", "", True))
check("清單照名字排", pf.preset_names({"b": 1, "a": 2, "預設": 3}) == ["a", "b", "預設"] and pf.preset_names(None) == [])

# ----- 5 -----
remaining, chosen, error = pf.after_delete(presets, "預設")
check("刪掉後改用名字排第一的", remaining == {"直式": {}} and chosen == "直式" and error == "")
check("不改傳入的", presets == {"預設": {}, "直式": {}})
check("只剩一組：不能刪", pf.after_delete({"預設": {}}, "預設") == ({"預設": {}}, None, pf.KEEP_ONE))
check("沒有這組：原樣", pf.after_delete(presets, "沒有") == (presets, None, ""))

# ----- 6 -----
src = open(pf.__file__, encoding="utf-8").read()
code = [line for line in src.splitlines() if line.startswith(("import ", "from "))]
check("零 GUI 依賴、不 import config", not any(w in " ".join(code) for w in (
    "config", "tkinter", "PySide6", "gui")), str(code))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("習慣設定與斷句設定規則測試全數通過。")
