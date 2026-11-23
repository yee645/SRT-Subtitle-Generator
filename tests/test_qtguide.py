# -*- coding: utf-8 -*-
"""
3.0 第 11 項第三十五階段：Qt 版首次啟動導覽的內容與規則（subtitle/qtguide.py）。

1. should_show：沒看過跳；看過這一版的導覽不跳；勾過「不再顯示」永遠不跳；看過舊版導覽的會再跳一次；
   前後空白、None 都照常判斷。
2. remember：勾了是永久（never），沒勾是「看過這一版」。
3. 跟一般版的 whatsnew_seen 分開記（不同的鍵、不同的值）。
4. 全文：開頭講四個頁籤；三段（多了什麼、在哪裡、還不一樣的地方）照順序；每一條都在全文裡。
5. **導覽講的按鈕真的存在**：WHERE 裡〔…〕括起來的按鈕名稱，每一個都在 gui_qt/ 的原始碼裡找得到
   （改了按鈕名字忘了改導覽，這裡會抓到）。
6. 照實講限制：不能自動更新、設定關掉時才存、隨時可以改用一般版。
7. 零 GUI 依賴、不 import config。
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import qtguide as g  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ----- 1 -----
check("沒看過：跳", g.should_show("") and g.should_show(None))
check("看過這一版的導覽：不跳", not g.should_show(g.GUIDE_VERSION) and not g.should_show(f"  {g.GUIDE_VERSION} "))
check("勾過不再顯示：不跳", not g.should_show(g.NEVER_SHOW) and not g.should_show(" never "))
check("看過舊版導覽：再跳一次", g.should_show("3.0-preview-0"))

# ----- 2 -----
check("勾了：永久", g.remember(True) == g.NEVER_SHOW == "never")
check("沒勾：看過這一版", g.remember(False) == g.GUIDE_VERSION)

# ----- 3 -----
import config  # noqa: E402
from gui.whatsnew_dialog import NEVER_SHOW as TK_NEVER  # noqa: E402

check("跟一般版分開記（不同的鍵）", g.CONFIG_KEY == "qt_guide_seen" and g.CONFIG_KEY not in config.DEFAULT_CONFIG
      and "whatsnew_seen" in config.DEFAULT_CONFIG)
from updater import APP_VERSION  # noqa: E402

# 一般版看過速覽會在 whatsnew_seen 寫 APP_VERSION 或 never；那些值就算被誤放進 qt_guide_seen，也不等於 Qt 導覽的版本
check("一般版的「看過這一版」不等於看過 Qt 導覽", g.should_show(APP_VERSION) and g.GUIDE_VERSION != APP_VERSION)
check("兩邊的「不再顯示」用同一個字（never），但記在不同的鍵", TK_NEVER == g.NEVER_SHOW)

# ----- 4 -----
text = g.body_text()
check("開頭講四個頁籤", text.startswith(g.INTRO) and all(t in text for t in (
    "① 素材與剪輯", "② 字幕", "③ 健檢中心", "④ 輸出與發佈")))
sections = ["【這一版多了什麼】", "【一般版的東西在哪裡】", "【還跟一般版不一樣的地方】"]
check("三段照順序", all(s in text for s in sections)
      and text.index(sections[0]) < text.index(sections[1]) < text.index(sections[2]))
check("每一條都在全文裡", all(t in text and d in text for t, d in g.NEW_IN_QT)
      and all(o in text and n in text for o, n in g.WHERE) and all(i in text for i in g.DIFFERENT))
check("條目數合理（不是空的）", len(g.NEW_IN_QT) >= 5 and len(g.WHERE) >= 10 and len(g.DIFFERENT) >= 3)

# ----- 5 -----
qt_src = "".join(open(p, encoding="utf-8").read() for p in glob.glob(os.path.join(ROOT, "gui_qt", "*.py")))
named = sorted({m for _old, new in g.WHERE for m in re.findall(r"〔([^〕]+)〕", new)})
missing = [name for name in named if f'"{name}"' not in qt_src and f"'{name}'" not in qt_src
           and f'QPushButton("{name}' not in qt_src]
check("導覽講的每一顆按鈕在 Qt 版真的有", named and not missing, f"找不到：{missing}；全部：{named}")
check("頁籤名稱跟主視窗一樣", all(f'"{t}"' in qt_src for t in ("① 素材與剪輯", "② 字幕", "③ 健檢中心", "④ 輸出與發佈")))

# ----- 6 -----
joined = "".join(g.DIFFERENT)
check("照實講限制", "還不能自動更新" in joined and "關掉 Qt 版時才存" in joined and "一般版" in joined)

# ----- 7 -----
src = open(g.__file__, encoding="utf-8").read()
code = [line for line in src.splitlines() if line.startswith(("import ", "from "))]
check("零 GUI 依賴、不 import config", not any(w in " ".join(code) for w in (
    "config", "tkinter", "PySide6", "gui")), str(code))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("Qt 版首次啟動導覽內容與規則測試全數通過。")
