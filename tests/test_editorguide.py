# -*- coding: utf-8 -*-
"""
剪輯器版面 E-7b：剪輯器的介紹與版面選擇（subtitle/editorguide.py）。

1. 版面選擇：命令列 --tabs／--editor 優先（兩個都給取後面那個），其次設定的 qt_layout（大小寫、空白不計較，
   看不懂的值不算），都沒有就是剪輯器。
2. 跳不跳介紹：沒看過跳；看過這一版不跳；勾過「不再顯示」永遠不跳；看過舊版的介紹再跳一次。
   跟 3.0 導覽的 qt_guide_seen 分開記。
3. 介紹全文：五段標題都在；四頁籤的東西每一筆都講了「在哪」；指的位置都是剪輯器真的有的（左邊四區、
   右上角〔匯出〕、屬性面板、頂列、選單）；快捷鍵跟剪輯器真的註冊的一致；有講怎麼切回四頁籤。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from subtitle import editorguide as eg  # noqa: E402
from subtitle import qtguide  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


# ----- 1 -----
check("什麼都沒給：剪輯器", eg.choose_layout([], None) == eg.EDITOR)
check("設定寫 tabs：四頁籤", eg.choose_layout(["main.py", "--qt"], "tabs") == eg.TABS)
check("設定大小寫、空白不計較", eg.choose_layout([], "  TABS ") == eg.TABS)
check("設定看不懂：剪輯器", eg.choose_layout([], "grid") == eg.EDITOR and eg.choose_layout([], 3) == eg.EDITOR)
check("--tabs 蓋過設定", eg.choose_layout(["--qt", "--tabs"], "editor") == eg.TABS)
check("--editor 蓋過設定", eg.choose_layout(["--qt", "--editor"], "tabs") == eg.EDITOR)
check("兩個都給：取後面那個", eg.choose_layout(["--tabs", "--editor"], None) == eg.EDITOR
      and eg.choose_layout(["--editor", "--tabs"], None) == eg.TABS)
check("旗標要完全相同才算", eg.choose_layout(["--tabsx", "tabs"], None) == eg.EDITOR)
check("argv 是 None 也行", eg.choose_layout(None, "tabs") == eg.TABS)

# ----- 2 -----
check("沒看過：跳", eg.should_show(None) and eg.should_show(""))
check("看過這一版：不跳", not eg.should_show(eg.GUIDE_VERSION))
check("勾過不再顯示：不跳", not eg.should_show(eg.NEVER_SHOW) and not eg.should_show(eg.remember(True)))
check("看過舊版的介紹：再跳", eg.should_show("3.0-editor"))
check("沒勾：記成看過這一版", eg.remember(False) == eg.GUIDE_VERSION)
check("跟 3.0 導覽分開記", eg.CONFIG_KEY != qtguide.CONFIG_KEY and eg.CONFIG_KEY == "editor_guide_seen")
check("看過 3.0 導覽不等於看過剪輯器介紹", eg.should_show(qtguide.FORMAL_GUIDE_VERSION))

# ----- 3 -----
body = eg.body_text()
for title in ("【版面】", "【這一版多了什麼】", "【四頁籤的東西在哪裡】", "【快捷鍵】", "【想用回四頁籤】"):
    check(f"介紹有 {title}", title in body)
check("開頭是介紹語", body.startswith(eg.INTRO))
check("四頁籤的東西每一筆都寫了在哪", all(old and new and f"→ {new}" in body for old, new in eg.WHERE))
PLACES = ("左邊「媒體」", "左邊「字幕」", "左邊「智慧剪輯」", "左邊「健檢」", "〔匯出〕", "屬性面板", "頂列", "中間", "下面")
check("每一筆的新位置都是剪輯器真的有的地方", all(any(p in new for p in PLACES) for _o, new in eg.WHERE),
      str([new for _o, new in eg.WHERE if not any(p in new for p in PLACES)]))
check("四頁籤的四頁都講到", all(any(old.startswith(c) for old, _n in eg.WHERE) for c in "①②③④"))
check("新位置不再用頁籤編號", not any(c in new for _o, new in eg.WHERE for c in "①②③④"))
check("有講怎麼切回四頁籤（選單項目名稱）", "改用四頁籤版面" in body and "改用剪輯器版面" in body)
keys_in_guide = " ".join(k for k, _w in eg.KEYS)
for key in ("Space", "J", "K", "L", "Ctrl+B", "Delete", "Ctrl+Z", "Ctrl+Shift+Z", "Ctrl+E", "Ctrl+Shift+S", "Shift+Z"):
    check(f"快捷鍵寫到 {key}", key in keys_in_guide)
check("介紹裡沒有寫死的色碼或連結", "#" not in body and "http" not in body)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("剪輯器介紹與版面選擇（E-7b）測試全數通過。")
