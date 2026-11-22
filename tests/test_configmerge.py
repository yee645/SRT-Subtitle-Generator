# -*- coding: utf-8 -*-
"""
3.0 第 11 項第二十八階段：Qt 版存設定時只寫自己改過的區塊（subtitle/configmerge.py）。

1. changed_sections：改過、新增、拿掉的最上層區塊都算；區塊裡面深處改一個值也算；沒改的不算；排序。
2. merge_for_save：以磁碟上現在的為底；Qt 沒動的區塊留磁碟上的（一般版剛存的）；Qt 動過的用 Qt 的；
   Qt 拿掉的從磁碟拿掉；磁碟上才有的（一般版新加的區塊）留著；兩邊都改同一區塊時 Qt 的勝出。
3. 不動三個輸入、回傳深拷貝（之後改回傳值不會改到 Qt 記憶體裡那份）；空的／None 也能用。
4. 零 GUI 依賴、不 import config。
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle.configmerge import changed_sections, merge_for_save  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


base = {"theme": "light", "subtitle_style": {"font_size": 40, "color": "#ffffff"},
        "seriescheck": {"luma_tolerance": 25.0}, "transcription": {"language": "zh", "api_key": ""},
        "old": 1}
current = copy.deepcopy(base)
current["subtitle_style"]["font_size"] = 60          # 改深處一個值
current["automation"] = {"export_srt": True}        # 新增
del current["old"]                                   # 拿掉

# ----- 1 -----
check("改過、新增、拿掉的都算，照名稱排序", changed_sections(base, current) == ["automation", "old", "subtitle_style"],
      str(changed_sections(base, current)))
check("沒改：空的", changed_sections(base, copy.deepcopy(base)) == [])
many = {f"區塊{i:02d}": i for i in range(30)}
check("很多區塊也照名稱排序（不是剛好照 set 的順序）",
      changed_sections({}, many) == sorted(many) and changed_sections(many, {}) == sorted(many))
check("值是 None 跟沒有這一項不一樣", changed_sections({"a": None}, {}) == ["a"]
      and changed_sections({}, {"a": None}) == ["a"])
check("None 也能用", changed_sections(None, None) == [] and changed_sections(None, {"a": 1}) == ["a"])

# ----- 2 -----
disk = copy.deepcopy(base)
disk["transcription"]["language"] = "en"             # 一般版在這段期間改了 Qt 沒動的區塊
disk["presets"] = {"直播": {}}                        # 一般版新加的區塊
disk["seriescheck"] = {"luma_tolerance": 40.0}
current["seriescheck"] = {"luma_tolerance": 30.0}    # 兩邊都改：Qt 勝出
snapshot = (copy.deepcopy(disk), copy.deepcopy(base), copy.deepcopy(current))
merged = merge_for_save(disk, base, current)
check("Qt 動過的區塊用 Qt 的", merged["subtitle_style"] == {"font_size": 60, "color": "#ffffff"}
      and merged["automation"] == {"export_srt": True})
check("Qt 沒動的區塊留磁碟上的（一般版剛存的不被蓋掉）", merged["transcription"]["language"] == "en"
      and merged["theme"] == "light")
check("磁碟上才有的區塊留著", merged["presets"] == {"直播": {}})
check("Qt 拿掉的區塊從磁碟拿掉", "old" not in merged)
check("兩邊都改同一區塊：Qt 的勝出（後存的算數）", merged["seriescheck"] == {"luma_tolerance": 30.0})
check("剛好整份就是這些區塊", sorted(merged) == ["automation", "presets", "seriescheck", "subtitle_style",
                                                "theme", "transcription"], str(sorted(merged)))

# ----- 3 -----
check("不動三個輸入", (disk, base, current) == snapshot)
merged["subtitle_style"]["font_size"] = 99
merged["transcription"]["language"] = "ja"
check("回傳深拷貝：改回傳值不會改到 Qt 的或磁碟那份", current["subtitle_style"]["font_size"] == 60
      and disk["transcription"]["language"] == "en")
check("磁碟上沒有設定檔（空的）：寫出 Qt 改過的區塊", merge_for_save({}, base, current)["subtitle_style"]["font_size"] == 60
      and merge_for_save(None, {}, {"a": 1}) == {"a": 1})
check("沒改任何東西：照磁碟上的原樣", merge_for_save(disk, base, copy.deepcopy(base)) == disk)

# ----- 4 -----
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "subtitle", "configmerge.py"),
           encoding="utf-8").read()
check("零 GUI 依賴、不 import config", not any(w in src for w in ("import config", "from config", "tkinter",
                                                                  "PySide6", "gui_qt", "from gui")))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("Qt 版存設定的合併規則測試全數通過。")
