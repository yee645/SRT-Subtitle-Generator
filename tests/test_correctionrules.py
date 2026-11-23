# -*- coding: utf-8 -*-
"""
3.0 第 11 項第三十三階段：自動修正詞庫的增刪規則（subtitle/correctionrules.py）。

1. rule_label：跟一般版清單同一種寫法（換成空白寫「（刪除）」、區分大小寫要註明）。
2. save_rule：「尋找」去頭尾空白、不能空；「換成」原樣（可以空）；同一個「尋找」換掉舊的、移到最後；不改傳入的；
   壞掉的舊清單先整理；滿了不加（換掉舊的那條不算加）。
3. delete_rule：刪第幾條；沒選、超出範圍都說要先選；不改傳入的。
4. 存下來的規則真的會在生成字幕時套用（textedit.apply_corrections，pipeline 也是呼叫它）。
5. 零 GUI 依賴、不 import config。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import correctionrules as cr  # noqa: E402
from subtitle.textedit import MAX_CORRECTION_RULES, apply_corrections  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


# ----- 1 -----
check("一般的規則", cr.rule_label({"find": "達聞西", "replace": "達文西", "case": False}) == "達聞西 → 達文西")
check("換成空白：寫（刪除）", cr.rule_label({"find": "嗯嗯", "replace": "", "case": False}) == "嗯嗯 → （刪除）")
check("區分大小寫要註明", cr.rule_label({"find": "youtube", "replace": "YouTube", "case": True})
      == "youtube → YouTube（區分大小寫）")
gui_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui", "replace_dialog.py"),
               encoding="utf-8").read()
check("跟一般版同一種寫法", 'case = "（區分大小寫）" if rule["case"] else ""' in gui_src
      and 'target = rule["replace"] if rule["replace"] else "（刪除）"' in gui_src
      and """f"{rule['find']} → {target}{case}\"""" in gui_src)

# ----- 2 -----
rules = [{"find": "a", "replace": "A", "case": False}, {"find": "b", "replace": "B", "case": False}]
new, err = cr.save_rule(rules, "  達聞西 ", " 達文西", True)
check("新規則放最後、尋找去空白、換成原樣", err == "" and new[-1] == {"find": "達聞西", "replace": " 達文西", "case": True}
      and len(new) == 3, str(new))
check("不改傳入的", len(rules) == 2)
new, err = cr.save_rule(rules, "a", "AA", False)
check("同一個尋找：換掉舊的、移到最後", err == "" and [r["find"] for r in new] == ["b", "a"] and new[-1]["replace"] == "AA")
new, err = cr.save_rule(rules, "嗯", "", False)
check("換成可以空（＝刪掉）", err == "" and new[-1] == {"find": "嗯", "replace": "", "case": False})
new, err = cr.save_rule(rules, "   ", "x", False)
check("尋找空白：不存、說要先填", err == cr.NEED_FIND and new == rules)
new, err = cr.save_rule([{"find": "", "replace": "x"}, "壞掉", {"find": "c", "replace": None}], "d", "D", False)
check("壞掉的舊清單先整理", err == "" and new == [{"find": "c", "replace": "", "case": False},
                                                {"find": "d", "replace": "D", "case": False}], str(new))
full = [{"find": f"w{i}", "replace": "x", "case": False} for i in range(MAX_CORRECTION_RULES)]
new, err = cr.save_rule(full, "新的", "y", False)
check("滿了：不加、說上限", err == cr.FULL and len(new) == MAX_CORRECTION_RULES and str(MAX_CORRECTION_RULES) in cr.FULL)
new, err = cr.save_rule(full, "w5", "改", False)
check("滿了但是換掉舊的：可以", err == "" and len(new) == MAX_CORRECTION_RULES and new[-1] == {
    "find": "w5", "replace": "改", "case": False})

# ----- 3 -----
three = [{"find": k, "replace": k.upper(), "case": False} for k in "abc"]
new, err = cr.delete_rule(three, 1)
check("刪第幾條", err == "" and [r["find"] for r in new] == ["a", "c"])
check("不改傳入的", len(three) == 3)
check("沒選、超出範圍：說要先選", cr.delete_rule(three, None) == (three, cr.NEED_SELECTION)
      and cr.delete_rule(three, 3)[1] == cr.NEED_SELECTION and cr.delete_rule(three, -1)[1] == cr.NEED_SELECTION)

# ----- 4 -----
saved, _ = cr.save_rule([], "達聞西", "達文西", False)
cues, count = apply_corrections([{"start": 0, "end": 1, "text": "達聞西說達聞西"}], saved)
check("存下來的規則生成字幕時會套用", cues[0]["text"] == "達文西說達文西" and count == 2)
pipeline_src = open(os.path.join(os.path.dirname(cr.__file__), "pipeline.py"), encoding="utf-8").read()
check("生成字幕（pipeline）呼叫的是同一個 apply_corrections", 'apply_corrections(cues, config.get("corrections"))'
      in pipeline_src)

# ----- 5 -----
src = open(cr.__file__, encoding="utf-8").read()
code = [line for line in src.splitlines() if line.startswith(("import ", "from "))]
check("零 GUI 依賴、不 import config", not any(w in " ".join(code) for w in (
    "config", "tkinter", "PySide6", "gui")), str(code))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("自動修正詞庫規則測試全數通過。")
