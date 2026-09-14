# -*- coding: utf-8 -*-
"""
v1.52.3 收尾測試：自動修剪合併、classic 控件清理、字幕清單欄寬。

三件事：

1. **`gui/autotrim_dialog.py` 併掉 jumpcut + retakes 兩個視窗**。合併最容
   易出的錯是把兩個偵測器的**個性差異抹平**——剪停頓動的是沒人講話的空
   檔（誤判成本低，預覽後直接輸出），剪重複片段動的是實際講話內容（刻意
   重複的口號、報數測試麥克風都會中，所以必須逐項勾選確認才剪）。這裡逐
   項驗證兩邊的能力與那個保護都還在。
2. **classic 控件清理**：84 個 `tk.Spinbox` 換成 `ttk.Spinbox`。深色主題
   下 classic 版本會是一個刺眼的白框（實測截圖確認，不是憑感覺）。
3. **字幕清單「時間」欄寬**：`00:00:00,000 → 00:00:02,000` 實測要 210px，
   原本設 180，每一列的結束時間都被截掉。
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fp:
        return fp.read()


# ===== 1. 兩個舊視窗確實退役、能力一項不少 ===========================
check("gui/jumpcut_dialog.py 已退役",
      not os.path.exists(os.path.join(ROOT, "gui", "jumpcut_dialog.py")))
check("gui/retakes_dialog.py 已退役",
      not os.path.exists(os.path.join(ROOT, "gui", "retakes_dialog.py")))

trim_src = read("gui", "autotrim_dialog.py")

# 兩個核心模組的公開函式一個都不能少——併窗不該併掉能力。
for name in ("apply_jumpcut", "find_cut_gaps", "compute_keep_segments",
             "format_jumpcut_report", "resolve_jumpcut_settings"):
    check(f"剪停頓能力 {name} 仍在", name in trim_src)
for name in ("apply_retake_removal", "find_retakes",
             "format_retake_removal_report", "resolve_retake_settings"):
    check(f"剪重複片段能力 {name} 仍在", name in trim_src)

check("兩邊各自的設定 config 區段都還在寫（jumpcut／retakes 不可互相覆蓋）",
      '"jumpcut"' in trim_src and '"retakes"' in trim_src)
check("「逐項勾選確認才剪」的保護沒有被抹平成跳剪那套流程",
      "_selected_retakes" in trim_src and "_check_vars" in trim_src)
check("剪後字幕仍會同步輸出（時間軸已對齊，不必手動調）",
      "_export_cues" in trim_src and "export(" in trim_src)

app_src = read("gui", "app.py")
# 注意：方法名 `_open_jumpcut_dialog` 本身就含 "jumpcut_dialog" 這個子字
# 串，直接用 `not in` 會誤判。要驗的是 **import 那一行**不見了。
check("app.py 不再 import 退役的兩個模組",
      "from gui.jumpcut_dialog" not in app_src
      and "from gui.retakes_dialog" not in app_src)
check("app.py 改 import 合併後的自動修剪對話框",
      "from gui.autotrim_dialog import" in app_src)
check("兩顆入口都保留（使用者按下按鈕時想做的事是明確的）",
      "_open_jumpcut_dialog" in app_src and "_open_retakes_dialog" in app_src)


# ===== 2. classic 控件清理 ===========================================
import glob

offenders = []
for path in sorted(glob.glob(os.path.join(ROOT, "gui", "*.py"))):
    src = read("gui", os.path.basename(path))
    for widget in ("Checkbutton", "Radiobutton", "Scale", "Spinbox"):
        stripped = src.replace(f"ttk.{widget}(", "")
        if f"tk.{widget}(" in stripped:
            offenders.append((os.path.basename(path), widget))
check("gui/*.py 沒有殘留 classic tk.Checkbutton/Radiobutton/Scale/Spinbox"
      "（深色主題下 classic 版本會是刺眼的白框，實測截圖確認）",
      not offenders, str(offenders))

spin_count = sum(read("gui", os.path.basename(p)).count("ttk.Spinbox(")
                 for p in glob.glob(os.path.join(ROOT, "gui", "*.py")))
check(f"ttk.Spinbox 數量合理（實際 {spin_count}，換掉的 84 個都在）",
      spin_count >= 84, str(spin_count))


# ===== 3. 字幕清單「時間」欄寬 =======================================
check("時間欄寬已從 180 調大（180 放不下 00:00:00,000 → 00:00:02,000）",
      'self.cue_tree.column("time", width=226' in app_src)
check("時間欄設了 minwidth，拖窄也讀得到完整時間碼",
      'minwidth=210' in app_src)


# ===== 4. Xvfb 下的真實驗證 =========================================
try:
    import tkinter as tk
    from tkinter import font as tkfont
except ImportError as exc:
    print(f"SKIP Xvfb 段（無 tkinter：{exc}）")
else:
    import config as app_config
    _cfg = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    _cfg.write(b'{"whatsnew_seen": "never"}')
    _cfg.close()
    app_config.CONFIG_PATH = _cfg.name
    app = None
    try:
        from gui.app import SrtApp
        from gui.autotrim_dialog import AutoTrimDialog, TAB_GAPS, TAB_RETAKES
        app = SrtApp()
    except tk.TclError as exc:
        message = str(exc).lower()
        if "display" in message or "connect" in message:
            print(f"SKIP Xvfb 段（無顯示器：{exc}）")
        else:
            check(f"主視窗開得起來（TclError：{exc}）", False)

    if app is not None:
        app.geometry("1400x800+0+0")
        app.deiconify()
        for _ in range(60):
            app.update()

        def pump():
            for _ in range(20):
                app.update()

        # --- 時間欄真的放得下完整時間碼 ---
        app.cues = [{"start": 0.0, "end": 2.0, "text": "第一句"},
                    {"start": 3725.678, "end": 3739.999, "text": "長時間碼"}]
        app._populate_cue_list(app.cues)
        pump()
        need = tkfont.nametofont("TkDefaultFont").measure(
            "00:00:00,000 → 00:00:02,000")
        got = app.cue_tree.column("time", "width")
        check(f"時間欄實際寬 {got} >= 完整時間碼所需 {need}", got >= need,
              f"{got} < {need}")

        # --- 自動修剪對話框：兩個分頁都開得起來、控件都在 ---
        cues = [
            {"start": 0.0, "end": 2.0, "text": "今天要講三件事"},
            {"start": 8.0, "end": 10.0, "text": "第一件事是這樣"},
            {"start": 10.5, "end": 12.5, "text": "第一件事是這樣"},
            {"start": 20.0, "end": 22.0, "text": "第二件事不一樣"},
        ]
        dialog = AutoTrimDialog(app, app.config_data, cues, media_path="",
                                tab=TAB_GAPS)
        dialog.geometry("680x640+0+0")
        dialog.deiconify()
        pump()
        check("自動修剪視窗有真的顯示出來（否則量到的都是 1px 假值）",
              dialog.winfo_width() > 100 and dialog.winfo_height() > 100,
              f"{dialog.winfo_width()}x{dialog.winfo_height()}")
        check("有兩個分頁", dialog.notebook.index("end") == 2,
              str(dialog.notebook.index("end")))
        tabs = [dialog.notebook.tab(i, "text")
                for i in range(dialog.notebook.index("end"))]
        check("分頁名稱沿用 D-1 改名後的按鈕名（使用者認得）",
              tabs == ["剪停頓（依字幕）", "剪重複片段"], str(tabs))
        check("tab=TAB_GAPS 時開在第一頁",
              dialog.notebook.index(dialog.notebook.select()) == 0)

        # 兩個偵測器開窗就各跑過一次。
        check("開窗時剪停頓已跑過（測資有 6 秒空檔，應該偵測得到）",
              len(dialog._preview_gaps) > 0, str(dialog._preview_gaps))
        check("開窗時重複片段已跑過（測資有兩句一模一樣）",
              len(dialog._retakes) > 0, str(dialog._retakes))
        # **開窗當下**（還沒手動切過任何分頁）狀態列就該講開著的那一頁。
        # 兩個偵測器都會在 __init__ 跑一次，後跑完的重複片段若直接寫進共用
        # 狀態列，使用者停在「剪停頓」分頁卻看到「重複片段偵測完成」——
        # 截圖抓到的就是這個。這一項要放在任何 notebook.select() 之前，否則
        # 切分頁的事件會把狀態修正掉，就測不到開窗當下的狀態了。
        check("開窗當下（tab=TAB_GAPS）狀態列講的就是跳剪，不是重複片段",
              "跳剪" in dialog.status_var.get(), dialog.status_var.get())
        check("有候選時「輸出跳剪版」啟用",
              str(dialog.run_btn["state"]) == "normal")
        check("有候選時「剪掉勾選的重複片段」啟用",
              str(dialog.cut_btn["state"]) == "normal")
        check("重複片段候選預設全部勾選",
              len(dialog._selected_retakes()) == len(dialog._retakes))

        # 狀態列要跟著看得見的那一頁走。兩個偵測器開窗都各跑一次，若共用
        # 一個狀態列而不分頁保存，後跑完的會蓋掉前一個——實際看到的就是
        # 「停在剪停頓分頁、狀態列卻寫著重複片段偵測完成」（截圖抓到的）。
        dialog.notebook.select(0)
        pump()
        check("停在「剪停頓」分頁時，狀態列講的是跳剪",
              "跳剪" in dialog.status_var.get(), dialog.status_var.get())
        dialog.notebook.select(1)
        pump()
        check("切到「剪重複片段」分頁時，狀態列換成重複片段的訊息",
              "重複片段" in dialog.status_var.get(), dialog.status_var.get())
        dialog.notebook.select(0)
        pump()
        check("切回去時狀態列也換回來（不是只更新一次）",
              "跳剪" in dialog.status_var.get(), dialog.status_var.get())

        # 處理中要鎖住四顆鈕——背景只跑得動一件事。
        dialog._set_processing(True)
        pump()
        check("處理中四顆動作鈕全部鎖住（否則會同時送出兩個 ffmpeg 工作）",
              all(str(b["state"]) == "disabled" for b in
                  (dialog.preview_btn, dialog.run_btn,
                   dialog.detect_btn, dialog.cut_btn)))
        dialog._set_processing(False)
        pump()
        check("解鎖後四顆鈕恢復",
              all(str(b["state"]) == "normal" for b in
                  (dialog.preview_btn, dialog.run_btn,
                   dialog.detect_btn, dialog.cut_btn)))

        # 沒有偵測結果時，解鎖不可以把輸出鈕一起打開。
        dialog._preview_gaps = []
        dialog._retakes = []
        dialog._set_processing(False)
        pump()
        check("沒有偵測結果時，解鎖不會誤開兩顆輸出鈕",
              str(dialog.run_btn["state"]) == "disabled"
              and str(dialog.cut_btn["state"]) == "disabled")

        # 版面掃描：不可有裁切或整個沒 map 的互動控件。
        from tkinter import ttk as _ttk
        dialog._preview_gaps = [(2.0, 8.0)]
        dialog._on_detect_retakes()
        clipped, unmapped = [], []

        def describe(widget):
            """
            控件的可讀名稱。

            注意 `ttk.Spinbox.cget("text")` **不會拋例外**——Tk 的 cget 會
            做選項前綴比對，`-text` 命中 `-textvariable`，回傳的是變數名
            （PY_VAR46 之類），看起來像個控件名其實不是。所以要先問
            `keys()` 有沒有 text，不能靠 try/except。
            """
            try:
                if "text" in widget.keys():
                    label = widget.cget("text")
                    if label:
                        return str(label)[:20]
            except Exception:
                pass
            return widget.winfo_class()

        def scan(widget, active_tab):
            for child in widget.winfo_children():
                if isinstance(child, (_ttk.Button, _ttk.Checkbutton,
                                      _ttk.Entry, _ttk.Spinbox, _ttk.Label)):
                    if child.winfo_ismapped():
                        req, act = child.winfo_reqwidth(), child.winfo_width()
                        if act > 1 and req > act:
                            clipped.append((describe(child), req, act))
                    elif isinstance(child, (_ttk.Button, _ttk.Spinbox)):
                        # 存**控件物件**不是名稱：六個 ttk.Spinbox 的
                        # describe() 全都回 "TSpinbox"，用名稱取交集會把六
                        # 個不同的控件當成同一個，憑空造出一個「每頁都消
                        # 失」的假陽性。v1.52.1 已經在四顆「瀏覽...」按鈕
                        # 上踩過一次同樣的坑。
                        unmapped.append(child)
                scan(child, active_tab)

        # 未選中分頁的控件本來就 unmapped（Notebook 的正常行為），所以
        # 「整個消失」要逐分頁掃完再取**交集**——在每一頁都不見的才是真
        # 的不見了。比照 tests/test_v1520.py 的作法。裁切則是每頁各看各的。
        still_unmapped = None
        for index in range(dialog.notebook.index("end")):
            dialog.notebook.select(index)
            pump()
            clipped, unmapped = [], []
            scan(dialog, index)
            check(f"分頁「{tabs[index]}」沒有控件被裁切", not clipped, str(clipped))
            here = set(unmapped)
            still_unmapped = here if still_unmapped is None else (
                still_unmapped & here)
        check("沒有任何按鈕或數字框在每一個分頁下都消失",
              not still_unmapped,
              str(sorted(describe(w) for w in (still_unmapped or ()))))

        # **minsize 才是真正的考驗**：預設 840x720 空間寬裕，就算把分頁內
        # 的動作鈕改回排在 expand 容器之後也不會出事（實測探針證實這個尺
        # 寸抓不到）。視窗縮到 minsize 時剩餘空間才會不夠，expand 容器把
        # 按鈕擠掉的問題就是在那裡現形的。
        dialog.geometry("780x620")
        pump()
        pump()
        min_unmapped = None
        for index in range(dialog.notebook.index("end")):
            dialog.notebook.select(index)
            pump()
            clipped, unmapped = [], []
            scan(dialog, index)
            here = set(unmapped)
            min_unmapped = here if min_unmapped is None else (
                min_unmapped & here)
        check("minsize 780x620 下也沒有按鈕或數字框在每一個分頁都消失",
              not min_unmapped,
              str(sorted(describe(w) for w in (min_unmapped or ()))))
        for name, button in (("預覽跳剪點", dialog.preview_btn),
                             ("輸出跳剪版", dialog.run_btn)):
            dialog.notebook.select(0)
            pump()
            check(f"minsize 下分頁一的〔{name}〕仍看得見",
                  button.winfo_ismapped() == 1)
        for name, button in (("偵測重複片段", dialog.detect_btn),
                             ("剪掉勾選的重複片段", dialog.cut_btn)):
            dialog.notebook.select(1)
            pump()
            check(f"minsize 下分頁二的〔{name}〕仍看得見",
                  button.winfo_ismapped() == 1)
        dialog.geometry("840x720")
        pump()

        dialog.destroy()

        # tab=TAB_RETAKES 會開在第二頁。
        d2 = AutoTrimDialog(app, app.config_data, cues, media_path="",
                            tab=TAB_RETAKES)
        d2.deiconify()
        pump()
        check("tab=TAB_RETAKES 時開在第二頁（兩顆入口各自 deep-link）",
              d2.notebook.index(d2.notebook.select()) == 1)
        d2.destroy()

        app.destroy()
    if os.path.exists(_cfg.name):
        os.unlink(_cfg.name)


print()
if failures:
    print(f"失敗 {len(failures)} 項：" + ", ".join(failures))
    sys.exit(1)
print("v1.52.3 收尾（自動修剪合併／classic 控件清理／欄寬）測試全數通過。")
