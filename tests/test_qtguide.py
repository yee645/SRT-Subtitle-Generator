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
# 12-6：12-3 起打包好的 Windows 版會自己更新，「還不能自動更新」那條改成講怎麼更新（行為刻意改變，換新斷言）
check("照實講：怎麼更新、設定什麼時候存、一般版", g.UPDATE_NOTE in g.DIFFERENT and "〔下載並安裝〕" in g.UPDATE_NOTE
      and "還不能自動更新" not in joined and "關掉 Qt 版時才存" in joined and "一般版" in joined)
check("講到的〔下載並安裝〕在 Qt 版真的有", '"下載並安裝"' in qt_src)
check("內容改了，預覽版導覽的版本往上加（看過舊的人會再看一次）", g.GUIDE_VERSION == "3.0-preview-2"
      and g.should_show("3.0-preview-1"))

# ----- 6b：正式版（3.0.0 起）-----
check("哪一版算正式版：3.0.0 起；沒給、看不懂、3.0 之前都當預覽版", [g.is_formal(v) for v in (
    None, "2.3.6", "v2.9.9", "abc", "3.0.0", "v3.0.0", "3.1", "10.0.0")] == [False] * 4 + [True] * 4)
check("預覽版：預設值不變（不傳版本＝傳 3.0 之前的版本）", g.body_text() == g.body_text("2.3.6")
      and g.remember(False) == g.remember(False, "2.9.9") == g.GUIDE_VERSION)
F = "3.0.0"
check("正式版的導覽版本不同：看過預覽版導覽的人升到 3.0 會再看一次", g.guide_version(F) == g.FORMAL_GUIDE_VERSION
      != g.GUIDE_VERSION and g.should_show(g.GUIDE_VERSION, F) and not g.should_show(g.FORMAL_GUIDE_VERSION, F)
      and not g.should_show(g.NEVER_SHOW, F) and g.remember(False, F) == g.FORMAL_GUIDE_VERSION
      and g.remember(True, F) == g.NEVER_SHOW)
ftext = g.body_text(F)
fsections = ["【這一版多了什麼】", "【一般版的東西在哪裡】", g.FORMAL_DIFFERENT_TITLE]
check("正式版全文：開頭換掉、三段照順序、沒有「預覽版」", ftext.startswith(g.FORMAL_INTRO)
      and all(x in ftext for x in fsections) and ftext.index(fsections[0]) < ftext.index(fsections[1])
      < ftext.index(fsections[2]) and "預覽版" not in ftext and "--qt" not in ftext, ftext[:200])
check("正式版全文：每一條都在", all(t in ftext and d in ftext for t, d in g.NEW_IN_QT)
      and all(o in ftext and n in ftext for o, n in g.WHERE) and all(i in ftext for i in g.FORMAL_DIFFERENT))
fjoined = "".join(g.FORMAL_DIFFERENT)
check("正式版照實講：怎麼更新、設定什麼時候存、一般版怎麼回去、兩邊設定各自一份", g.UPDATE_NOTE in g.FORMAL_DIFFERENT
      and "關掉程式時才存" in fjoined and "SRT-Subtitle-Generator.exe" in fjoined and "--tk" in fjoined
      and "各自一份" in fjoined)
main_src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
if g.is_formal(APP_VERSION):
    check("正式版講的 --tk 在 main.py 真的有", '"--tk"' in main_src)
else:
    print("SKIP 正式版講的 --tk：12-7 切預設時才加進 main.py（到時 APP_VERSION 3.0.0 這一條就會驗）")
app_src = open(os.path.join(ROOT, "gui_qt", "app.py"), encoding="utf-8").read()
dlg_src = open(os.path.join(ROOT, "gui_qt", "guide_dialog.py"), encoding="utf-8").read()
check("Qt 版把 APP_VERSION 傳進來挑版本（跳不跳、記什麼、顯示哪一套）",
      "qtguide.remember(never, APP_VERSION)" in app_src
      and "qtguide.should_show(self.config_data.get(qtguide.CONFIG_KEY), APP_VERSION)" in app_src
      and "qtguide.body_text(APP_VERSION)" in dlg_src and "FORMAL = qtguide.is_formal(APP_VERSION)" in app_src)

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
