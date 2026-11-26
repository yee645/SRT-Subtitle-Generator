# -*- coding: utf-8 -*-
"""
剪輯器版面改版 E-1：設計基準（subtitle/designtokens.py）。

1. 深淺兩套色票的名稱一模一樣（程式只用名稱，換主題不會缺色），每個都是 #rrggbb。
2. 對比度的算法對：白對黑 21、同色 1、順序不影響。
3. 每一組「字 × 底」（TEXT_PAIRS）兩個主題都 ≥ 4.5:1（WCAG AA）。
4. 規格文件（docs/ROADMAP_EDITOR.md）色表裡寫的顏色跟程式一致（文件與程式不會各說各話）。
5. 不認得的主題當淺色；不認得的名稱丟 KeyError（拼錯名稱要馬上看得到，不能悄悄變成別的顏色）。
6. 零 GUI 依賴、不 import config。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from subtitle import designtokens as dt  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


check("深淺兩套色票的名稱一模一樣", set(dt.TOKENS["dark"]) == set(dt.TOKENS["light"]),
      str(set(dt.TOKENS["dark"]) ^ set(dt.TOKENS["light"])))
bad = [(t, k, v) for t in dt.THEMES for k, v in dt.TOKENS[t].items() if not re.fullmatch(r"#[0-9a-f]{6}", v)]
check("每個顏色都是 #rrggbb（小寫）", not bad, str(bad))

check("對比度：白對黑 21", abs(dt.contrast("#ffffff", "#000000") - 21) < 1e-9)
check("對比度：同色 1", abs(dt.contrast("#20b6c4", "#20b6c4") - 1) < 1e-9)
check("對比度：前景背景順序不影響", dt.contrast("#123456", "#abcdef") == dt.contrast("#abcdef", "#123456"))
check("對比度：已知值（#767676 對白約 4.54）", abs(dt.contrast("#767676", "#ffffff") - 4.54) < 0.01,
      str(dt.contrast("#767676", "#ffffff")))
try:
    dt.luminance("#fff")
    check("縮寫色碼丟 ValueError", False)
except ValueError:
    check("縮寫色碼丟 ValueError", True)

for theme in dt.THEMES:
    low = [r for r in dt.contrast_report(theme) if r[2] < dt.MIN_CONTRAST]
    check(f"{theme}：每一組字×底都 ≥ 4.5:1", not low, str(low))
    check(f"{theme}：組合齊全（{len(dt.TEXT_PAIRS)} 組）", len(dt.contrast_report(theme)) == len(dt.TEXT_PAIRS))

doc = open(os.path.join(ROOT, "docs", "ROADMAP_EDITOR.md"), encoding="utf-8").read()
rows = re.findall(r"^\| `([a-z.]+)` \| `(#[0-9a-f]{6})` \| `(#[0-9a-f]{6})` \|", doc, re.M)
check("規格文件的色表有列出顏色", len(rows) >= 15, str(len(rows)))
mismatch = [(n, d, l) for n, d, l in rows
            if dt.TOKENS["dark"].get(n) != d or dt.TOKENS["light"].get(n) != l]
check("規格文件色表的顏色跟程式一致", not mismatch, str(mismatch))

check("不認得的主題當淺色", dt.token("sepia", "bg.panel") == dt.TOKENS["light"]["bg.panel"])
try:
    dt.token("dark", "bg.panle")
    check("拼錯的名稱丟 KeyError", False)
except KeyError:
    check("拼錯的名稱丟 KeyError", True)

src = open(os.path.join(ROOT, "subtitle", "designtokens.py"), encoding="utf-8").read()
check("零 GUI 依賴、不 import config",
      not re.search(r"^\s*(from|import)\s+(PySide6|tkinter|config|gui|gui_qt)\b", src, re.M))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("設計基準測試全數通過。")
