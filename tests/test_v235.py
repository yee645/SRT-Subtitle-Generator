# -*- coding: utf-8 -*-
"""
v2.3.5 回歸測試：〔匯入字幕〕在文件說的地方、〔字幕健檢〕轉址鈕移除。

架構文件 C-7 定案把清單編輯列的「字幕健檢」「匯入字幕」兩顆拿掉：前者
移到③、後者移到來源區。2.0 起程式內的「功能去哪了？」、README、
WHATS_NEW_2.0、遷移指南都已經告訴使用者〔匯入字幕〕在①，按鈕卻一直留在
②——照說明去找的人找不到。

這裡守：

1. 真的視窗裡：〔匯入字幕〕在①、整個程式只有這一顆；按下去真的載入一份
   字幕檔（`filedialog` 換成回傳現做的 .srt），②的清單跟著更新，①的
   〔剪停頓〕〔剪重複片段〕跟著啟用；狀態列講明下一步在②。
2. ①的卡片順序（既有字幕在自動修剪上面）與可視範圍（量座標）。
3. 清單編輯列剛好 8 顆，不再有〔匯入字幕〕〔字幕健檢〕。
4. 文件說的位置 = 畫面上的位置：速覽對照表、README、WHATS_NEW_2.0、遷移
   指南都說①，按鈕的祖先就要是①那個頁籤。
5. 版號與 CHANGELOG。
"""
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DISPLAY", ":99")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


# ===== 1. 文件說的位置（純文字，不需要視窗） ============================

import gui.whatsnew_dialog as wn  # noqa: E402

moved = dict(wn.MOVED)
import_dest = next((new for old, new in moved.items() if "〔匯入字幕〕" in old), "")
check("速覽對照表說〔匯入字幕〕在①", import_dest.startswith("① "), import_dest)
check_row = next((old for old in moved if "〔字幕健檢〕" in old), "")
check("速覽對照表把舊〔字幕健檢〕寫成清單編輯列（不是工具列）",
      "清單編輯列〔字幕健檢〕" in check_row
      and not re.search(r"工具列〔字幕健檢〕", check_row), check_row)

for rel in ("README.md", "docs/WHATS_NEW_2.0.md", "docs/MIGRATION_1x_TO_2.0.md"):
    row = next((ln for ln in _read(rel).splitlines()
                if ln.startswith("| **① 素材與剪輯**")), "")
    check(f"{rel} 的階段表把「匯入既有字幕」列在①", "匯入既有字幕" in row, row)

readme = _read("README.md")
check("README 不再說〔匯入字幕〕在字幕清單下方（除了講明「之前在」）",
      "字幕清單下方多了「**匯入字幕**」" not in readme
      and "v2.3.5 起在〔① 素材與剪輯〕的「既有字幕」卡片" in readme)
check("README 不再叫人按字幕清單下方的「字幕健檢」",
      "字幕清單下方按「**字幕健檢**」" not in readme
      and "編輯列「字幕健檢」按鈕這一版還在" not in readme)

# ===== 2. 真的視窗 ======================================================
#
# 只有建不起視窗可以略過；之後任何例外都算失敗（v2.3.2 踩過：過寬的
# except tk.TclError 會把真的錯誤當成沒有 DISPLAY）。

import tkinter as tk  # noqa: E402

import config  # noqa: E402

app = None
try:
    tmp = tempfile.mkdtemp(prefix="v235_test_")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")
    with open(config.CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump({"whatsnew_seen": "never"}, fh)
    import gui.app as app_module
    app = app_module.SrtApp()
except tk.TclError as exc:
    print(f"SKIP Xvfb 實測（{exc}）")

if app is not None:
    try:
        def pump(times=30):
            for _ in range(times):
                app.update()
                app.update_idletasks()

        def walk(widget):
            for child in widget.winfo_children():
                yield child
                yield from walk(child)

        def text_of(widget):
            try:
                return str(widget.cget("text"))
            except tk.TclError:
                return ""

        def is_inside(widget, ancestor):
            while widget is not None:
                if widget == ancestor:
                    return True
                widget = widget.master
            return False

        app.geometry("1400x800+0+0")
        app.deiconify()
        pump()

        # --- 整個程式只有一顆〔匯入字幕〕，而且在①頁籤裡 ---
        imports = [w for w in walk(app) if text_of(w) == "匯入字幕"]
        check("整個主視窗只有一顆〔匯入字幕〕", len(imports) == 1, str(len(imports)))
        btn = imports[0] if imports else None
        check("〔匯入字幕〕在①「素材與剪輯」頁籤裡（跟文件說的一樣）",
              btn is not None and is_inside(btn, app.stage_source_tab))
        check("〔匯入字幕〕不在②字幕頁",
              btn is not None and not is_inside(btn, app.stage_subtitle_tab))
        check("整個主視窗已經沒有〔字幕健檢〕按鈕",
              not [w for w in walk(app)
                   if isinstance(w, (tk.Button, tk.ttk.Button))
                   and text_of(w) == "字幕健檢"])

        # --- 清單編輯列剛好 8 顆 ---
        edit = [text_of(b) for row in app.cue_edit_frame.winfo_children()
                for b in row.winfo_children()]
        check("清單編輯列剛好 8 顆（C-7：10 → 8）", len(edit) == 8, str(edit))
        check("清單編輯列沒有〔匯入字幕〕〔字幕健檢〕",
              "匯入字幕" not in edit and "字幕健檢" not in edit, str(edit))
        check("清單編輯列原本的其他 8 顆都還在",
              set(edit) == {"新增字幕", "編輯選取", "刪除選取", "上移", "下移",
                            "清空清單", "尋找取代", "翻譯字幕"}, str(edit))

        # --- ①的卡片：順序與可視範圍（量座標） ---
        app.notebook.select(app.stage_source_tab)
        pump()
        cards = {text_of(w): w for w in walk(app.stage_source_tab)
                 if isinstance(w, tk.ttk.LabelFrame)}
        check("①有「既有字幕」卡片", "既有字幕" in cards, str(list(cards)))
        if "既有字幕" in cards and "自動修剪" in cards:
            a, b = cards["既有字幕"], cards["自動修剪"]
            check("「既有字幕」排在「自動修剪」上面（匯入後不必換頁就能剪）",
                  a.winfo_rooty() + a.winfo_height() <= b.winfo_rooty(),
                  f"{a.winfo_rooty()}+{a.winfo_height()} > {b.winfo_rooty()}")
        win_bottom = app.winfo_rooty() + app.winfo_height()
        for name, card in cards.items():
            check(f"①「{name}」卡片整塊在預設視窗 1400x800 內",
                  card.winfo_rooty() + card.winfo_height() <= win_bottom,
                  f"{card.winfo_rooty() + card.winfo_height()} > {win_bottom}")
        if btn is not None:
            check("〔匯入字幕〕沒有被裁切（要求寬度 ≤ 實際寬度）",
                  btn.winfo_reqwidth() <= btn.winfo_width(),
                  f"{btn.winfo_reqwidth()} > {btn.winfo_width()}")

        # --- 真的按下去：載入一份字幕檔 ---
        srt = os.path.join(tmp, "既有.srt")
        with open(srt, "w", encoding="utf-8") as fh:
            fh.write("1\n00:00:01,000 --> 00:00:02,500\n第一句\n\n"
                     "2\n00:00:03,000 --> 00:00:04,000\n第二句\n")
        check("匯入前：剪停頓／剪重複片段是停用的（沒有字幕）",
              str(app.jumpcut_btn.cget("state")) == "disabled"
              and str(app.retakes_btn.cget("state")) == "disabled")
        real_ask = app_module.filedialog.askopenfilename
        app_module.filedialog.askopenfilename = lambda **kw: srt
        try:
            btn.invoke()
        finally:
            app_module.filedialog.askopenfilename = real_ask
        pump()
        check("按①的〔匯入字幕〕真的載入字幕（2 句）",
              [c["text"] for c in app.cues] == ["第一句", "第二句"],
              str(app.cues))
        check("②的字幕清單跟著更新",
              len(app.cue_tree.get_children()) == 2,
              str(len(app.cue_tree.get_children())))
        check("匯入後同一頁的〔剪停頓〕〔剪重複片段〕跟著啟用",
              str(app.jumpcut_btn.cget("state")) == "normal"
              and str(app.retakes_btn.cget("state")) == "normal")
        status = app.status_var.get()
        check("狀態列講明匯入幾句、下一步到②字幕頁校對",
              "已匯入 2 句字幕" in status and "到②字幕頁校對" in status, status)
        check("匯入後停在①（使用者可能要接著剪停頓，不自作主張換頁）",
              app.notebook.select() == str(app.stage_source_tab))

        app.destroy()
    except Exception as exc:  # noqa: BLE001 —— 視窗建起來之後，任何例外都是失敗
        check("視窗實測過程沒有丟出例外", False, repr(exc))

# ===== 3. 版號與 CHANGELOG ==============================================

m = re.search(r'APP_VERSION = "(\d+)\.(\d+)\.(\d+)"', _read("updater.py"))
version = tuple(int(g) for g in m.groups()) if m else (0, 0, 0)
check("APP_VERSION 已進到 2.3.5 以上", version >= (2, 3, 5), str(version))
heads = re.findall(r"^## (v2\.3\.5\D.*)$", _read("CHANGELOG.md"), re.M)
check("CHANGELOG 有 v2.3.5 這一條（只有一條）", len(heads) == 1, str(heads))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v2.3.5 匯入字幕位置與字幕健檢轉址鈕移除測試全數通過。")
