# -*- coding: utf-8 -*-
"""
v1.50.1 回歸測試：健檢中心在預設尺寸下不可有控件被切掉。

v1.50.0 出貨時「進階設定（門檻）⚙」被 `pack(side="right")` 與勾選格線
搶同一條水平空間，實測需要 168px 卻只分到 69px，文字被切成「進階設」。
水平裁切是 `docs/UI_AUDIT_2.0.md` 點名的系統性問題（v1.x 主視窗右欄的
「刪除」鈕剩「刪」），所以這裡寫成**通用掃描**而不是只檢查那一顆：
走訪視窗裡所有帶文字且已 map 的控件，任何一個「要的寬度 > 拿到的寬度」
或「右緣超出視窗」都算失敗。

注意：一定要在 `deiconify()` 之後才量。未顯示的視窗其子元件一律回報
`winfo_ismapped()=0`、寬高 1px，在那之前量會誤判（這個坑 v1.48.0 踩過）。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


if not os.environ.get("DISPLAY"):
    print("SKIP 無 DISPLAY，略過 GUI 版面測試（CI 無虛擬螢幕時的正常情況）")
    sys.exit(0)

import tkinter as tk
from gui.health_center_dialog import HealthCenterDialog
from config import DEFAULT_CONFIG

# root 不 withdraw、且每輪 root 與 dlg 都要 update：只更新 root 時
# Toplevel 的版面不會被算出來，量到的會是 1x1 的假值（本測試第一條斷言
# 就是為了擋下這種誤判而存在）。
root = tk.Tk()
root.geometry("400x300")
root.update()
dlg = HealthCenterDialog(root, dict(DEFAULT_CONFIG), media_path="", cues=[])
dlg.deiconify()
for _ in range(30):
    root.update()
    dlg.update()
    time.sleep(0.05)

win_w = dlg.winfo_width()
win_h = dlg.winfo_height()
check("視窗有真的顯示出來（否則量到的都是 1px 假值）",
      win_w > 100 and win_h > 100, f"{win_w}x{win_h}")

clipped = []
overflow = []


def walk(widget):
    for child in widget.winfo_children():
        try:
            text = child.cget("text")
        except Exception:
            text = None
        if text and isinstance(text, str) and child.winfo_ismapped():
            need = child.winfo_reqwidth()
            got = child.winfo_width()
            right = child.winfo_rootx() - dlg.winfo_rootx() + got
            if need > got + 1:
                clipped.append((text, need, got))
            if right > win_w:
                overflow.append((text, right))
        walk(child)


walk(dlg)

check("沒有控件的文字被切掉（要的寬度 > 拿到的寬度）",
      not clipped,
      "; ".join(f"「{t}」需要{n}px 只有{g}px" for t, n, g in clipped))
check("沒有控件右緣超出視窗寬度",
      not overflow,
      "; ".join(f"「{t}」右緣{r} > 視窗{win_w}" for t, r in overflow))

# 那顆闖禍的按鈕本身也單獨驗一次，讓失敗訊息直指原因。
found = []


def find_button(widget):
    for child in widget.winfo_children():
        try:
            if "進階設定" in (child.cget("text") or ""):
                found.append(child)
        except Exception:
            pass
        find_button(child)


find_button(dlg)
check("找得到「進階設定」按鈕（門檻沒有被拿掉）", bool(found))
if found:
    btn = found[0]
    check("「進階設定」按鈕拿到它需要的完整寬度",
          btn.winfo_width() >= btn.winfo_reqwidth(),
          f"需要{btn.winfo_reqwidth()}px 只有{btn.winfo_width()}px")

dlg.destroy()
root.destroy()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.50.1 版面回歸測試全數通過。")
