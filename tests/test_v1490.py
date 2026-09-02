# -*- coding: utf-8 -*-
"""
v1.49.0 曾新增的功能：生成完成後把字幕清單捲進視野
（`gui/scrollable.py` 的 `ScrollableFrame.scroll_into_view`）。

**v1.52.0 更新說明（重要，讀這份文件前請先讀這段）**：本檔原本測的是
v1.49.0 的權宜之計——主視窗預設 1400x800 放不下自己的內容
（`docs/UI_AUDIT_2.0.md` 1.3-①），生成完成後若使用者停在頁頂會看不到
變化，於是在 `_on_generation_done`／`_on_auto_done` 呼叫
`scroll_frame.scroll_into_view(self.cue_tree)` 把清單捲進視野。

v1.52.0 主視窗三欄化（`docs/UI_ARCHITECTURE_2.0.md` B.2/B.3）**結構性
修好了折疊線問題本身**：字幕清單搬進中欄，中欄不隨左欄（設定區）捲
動，1400x800 下主動作按鈕與字幕清單本來就同屏永遠可見，不需要再捲。
`gui/app.py` 的 `_on_generation_done`／`_on_auto_done` 已移除那兩行呼
叫——這是預期中的retirement，不是缺陷，見 `docs/ROADMAP_2.0.md` v1.52
項與 `docs/UI_AUDIT_2.0.md` 修正紀錄。

本檔改測兩件事：
  1. `ScrollableFrame.scroll_into_view` 這個工具方法本身還在、行為不
     變（獨立於 `SrtApp` 測試，因為左欄仍然用它——只捲設定，元件多的
     時候一樣需要把特定欄位捲進視野；中欄在 minsize 980x560 這種極端
     窄高情形也改用同一個元件當退化保底，見 `tests/test_v1520.py`）。
  2. 字幕清單在 v1.52.0 的新版面下，1400x800 預設尺寸「不捲動也看得
     見」——這是取代舊權宜之計的真正修法，用實際量測驗證。
"""
import os
import sys
import tempfile

os.environ.setdefault("DISPLAY", ":99")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


# ===== 1. 靜態檢查：scroll_into_view 方法還在；app.py 的舊呼叫已退役 =====

SCROLLABLE_PATH = os.path.join(REPO_ROOT, "gui", "scrollable.py")
APP_PATH = os.path.join(REPO_ROOT, "gui", "app.py")
scrollable_src = open(SCROLLABLE_PATH, encoding="utf-8").read()
app_src = open(APP_PATH, encoding="utf-8").read()

check("gui/scrollable.py 的 ScrollableFrame 仍有 scroll_into_view 方法"
      "（左欄、中欄 minsize 退化保底都還在用這個元件）",
      "def scroll_into_view(self, widget" in scrollable_src)

check("gui/app.py 的 _on_generation_done／_on_auto_done 已移除舊版"
      "「捲進視野」權宜之計（v1.52.0 三欄化讓字幕清單結構性永遠可見，"
      "不再需要靠捲動補救——這是預期中的retirement，見本檔開頭說明）",
      "scroll_frame.scroll_into_view(self.cue_tree)" not in app_src)


# ===== 2. 起一個離屏 Tk root，驗證兩件事 =====

try:
    import tkinter as tk
    tk_root_probe = tk.Tk()
    tk_root_probe.destroy()
    TK_OK = True
except Exception as exc:  # pragma: no cover - 沒有可用 X 伺服器時整段跳過
    TK_OK = False
    print(f"（沒有可用的 Tk/X 顯示環境，跳過真實視窗量測：{exc}）")
    failures.append("需要可用的 X 顯示環境（DISPLAY），本檔的核心硬性驗收條件無法在此環境驗證")

if TK_OK:
    import tkinter.ttk as ttk

    from gui.scrollable import ScrollableFrame

    def pump(widget, times=15, step=0.03):
        import time
        for _ in range(times):
            widget.update()
            time.sleep(step)

    # ---- 2a. ScrollableFrame.scroll_into_view 本身：獨立驗證（不依賴 SrtApp）----
    probe_root = tk.Tk()
    probe_root.geometry("300x150+0+0")
    probe_root.deiconify()
    pump(probe_root)

    frame = ScrollableFrame(probe_root, theme="light")
    frame.pack(fill="both", expand=True)
    # 塞進遠比可視高度多的內容，讓最後一個 widget 落在視窗外。
    labels = []
    for i in range(60):
        lbl = ttk.Label(frame.interior, text=f"第 {i} 列")
        lbl.pack(anchor="w")
        labels.append(lbl)
    pump(probe_root, times=10)

    target = labels[-1]
    diff_before = target.winfo_rooty() - probe_root.winfo_rooty()
    check("刻意塞爆內容後，最後一列確實落在可視範圍之外（量到的前提）",
          diff_before > probe_root.winfo_height(), diff_before)

    frame.scroll_into_view(target)
    pump(probe_root, times=8)
    diff_after = target.winfo_rooty() - probe_root.winfo_rooty()
    check("呼叫 scroll_into_view 後該列進入可視範圍內",
          diff_after < probe_root.winfo_height(), diff_after)

    # 已經看得見就不捲：把捲軸移回頂端後，對第一列呼叫應該不動 yview。
    frame.canvas.yview_moveto(0.0)
    pump(probe_root, times=5)
    yview_before = frame.canvas.yview()
    frame.scroll_into_view(labels[0])
    pump(probe_root, times=5)
    yview_after = frame.canvas.yview()
    check("已可見時呼叫 scroll_into_view 不會捲動（yview 前後不變）",
          yview_before == yview_after, (yview_before, yview_after))

    # 未 map 的 widget 安全略過。
    unmapped = ttk.Label(frame.interior, text="尚未 pack")
    try:
        frame.scroll_into_view(unmapped)
        no_exception = True
    except Exception as exc:  # pragma: no cover
        no_exception = False
        print("scroll_into_view 對未 map widget 丟出例外：", exc)
    check("scroll_into_view 對尚未 map 的 widget 安全略過、不丟例外", no_exception)

    probe_root.destroy()

    # ---- 2b. SrtApp 新版面：字幕清單在 1400x800 不捲動也看得見 ----
    import config as config_module
    _isolated_dir = tempfile.mkdtemp(prefix="v1490_test_")
    config_module.CONFIG_PATH = os.path.join(_isolated_dir, "config.json")

    from gui.app import SrtApp

    FAKE_CUES = [
        {"start": i * 2.0, "end": i * 2.0 + 1.5, "text": f"字幕測試句 {i}"}
        for i in range(6)
    ]

    app = SrtApp()
    app.geometry("1400x800")
    app.deiconify()
    pump(app)

    win_height = app.winfo_height()
    check("主視窗確實依 geometry 顯示為高 800px（deiconify 之後量）",
          win_height == 800, win_height)

    app._populate_cue_list(FAKE_CUES)
    pump(app, times=8)

    diff = app.cue_tree.winfo_rooty() - app.winfo_rooty()
    check("字幕清單已 map（deiconify 之後）",
          app.cue_tree.winfo_ismapped() == 1)
    check(f"v1.52.0 三欄化後：字幕清單不必捲動就在視窗高度之內"
          f"（量到 y 差={diff}, 視窗高={win_height}，取代 v1.49.0 的"
          "「捲進視野」權宜之計）",
          diff < win_height, diff)

    # 真實路徑 _on_generation_done／_on_auto_done 呼叫後清單仍然可見
    # （不再需要捲動，但功能——填入清單、更新預覽——要維持正常）。
    app._on_generation_done(FAKE_CUES)
    pump(app, times=8)
    diff_gen = app.cue_tree.winfo_rooty() - app.winfo_rooty()
    check(f"呼叫 _on_generation_done 後字幕清單仍在視野內（y 差={diff_gen}）",
          diff_gen < win_height, diff_gen)
    check("_on_generation_done 正確填入字幕清單",
          len(app.cue_tree.get_children()) == len(FAKE_CUES))

    import gui.app as app_module
    info_calls = []
    warn_calls = []
    real_showinfo = app_module.messagebox.showinfo
    real_showwarning = app_module.messagebox.showwarning
    app_module.messagebox.showinfo = lambda *a, **k: info_calls.append(a)
    app_module.messagebox.showwarning = lambda *a, **k: warn_calls.append(a)
    try:
        auto_results = [{
            "ok": True,
            "path": "/tmp/v1490_fake_video.mp4",
            "result": {
                "cues": FAKE_CUES,
                "exports": ["/tmp/v1490_fake_video.srt"],
                "burned": None,
            },
        }]
        app._on_auto_done(auto_results)
        pump(app, times=8)
    finally:
        app_module.messagebox.showinfo = real_showinfo
        app_module.messagebox.showwarning = real_showwarning

    diff_auto = app.cue_tree.winfo_rooty() - app.winfo_rooty()
    check(f"呼叫 _on_auto_done（一鍵完成批次路徑）後字幕清單仍在視野內"
          f"（y 差={diff_auto}）",
          diff_auto < win_height, diff_auto)
    check("一鍵完成結束確實跳出摘要訊息框（成功路徑）",
          len(info_calls) == 1 and len(warn_calls) == 0)

    app.destroy()


print()
if failures:
    print(f"失敗項目（共 {len(failures)}）：")
    for name in failures:
        print(" -", name)
    sys.exit(1)
print("全部通過。")
