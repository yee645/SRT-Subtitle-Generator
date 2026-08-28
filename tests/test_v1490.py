# -*- coding: utf-8 -*-
"""
v1.49.0 新功能測試：生成完成後把字幕清單捲進視野
（`gui/scrollable.py` 的 `ScrollableFrame.scroll_into_view`）。

背景（見 `docs/UI_AUDIT_2.0.md` 1.3-①）：主視窗預設 1400x800 放不下自
己的內容，實測「開始生成字幕」在 y=826、字幕清單在 y=889、匯出與燒錄
在 y=1180，全部在 800px 之外——生成完成後若使用者停在頁頂，視野內沒有
任何變化。本檔驗證的硬性條件：

  1. 要有測試證明「原本看不到、修完看得到」——量測
     `cue_tree.winfo_rooty() - app.winfo_rooty()`，捲動前 > 視窗高、呼
     叫 `scroll_into_view` 後 < 視窗高，而不只是斷言函式有被呼叫。
  2. 「已經看得見就不捲」也要有測試：視窗開得夠高讓清單本來就可見時，
     `canvas.yview()[0]` 呼叫前後不變。
  3. 版面類斷言一律在 `deiconify()` 之後、且反覆 `app.update()` 讓版面
     配置真的跑完之後才量（未顯示的視窗子元件一律 `winfo_ismapped()=0`
     、寬高 1px，量了也是假數字）。

另外驗證：
  - `_on_generation_done`、`_on_auto_done`（一鍵完成批次路徑）兩條真實
    呼叫路徑都會觸發捲動（不只是測試底層方法本身）。
  - widget 尚未 map 時安全略過，不丟例外。

面板本身是真實的 Tkinter 視窗，這裡用 DISPLAY 指向可用的 X 伺服器
（本機 Xvfb :99）實際開出主視窗量測，而非只靜態掃原始碼。
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


# ===== 1. 靜態檢查：方法存在、兩條呼叫路徑都真的接上了 =====

SCROLLABLE_PATH = os.path.join(REPO_ROOT, "gui", "scrollable.py")
APP_PATH = os.path.join(REPO_ROOT, "gui", "app.py")
scrollable_src = open(SCROLLABLE_PATH, encoding="utf-8").read()
app_src = open(APP_PATH, encoding="utf-8").read()

check("gui/scrollable.py 的 ScrollableFrame 有 scroll_into_view 方法",
      "def scroll_into_view(self, widget" in scrollable_src)

import re
gen_done_block = re.search(
    r"def _on_generation_done\(self, cues\):.*?(?=\n    def )",
    app_src, re.S)
check("_on_generation_done 找得到（供下方檢查呼叫是否接上）",
      gen_done_block is not None)
if gen_done_block:
    check("_on_generation_done 內有呼叫 scroll_into_view",
          "scroll_frame.scroll_into_view(self.cue_tree)" in gen_done_block.group(0))

auto_done_block = re.search(
    r"def _on_auto_done\(self, results\):.*?(?=\n    def )",
    app_src, re.S)
check("_on_auto_done 找得到（一鍵完成批次路徑）",
      auto_done_block is not None)
if auto_done_block:
    check("_on_auto_done 內有呼叫 scroll_into_view",
          "scroll_frame.scroll_into_view(self.cue_tree)" in auto_done_block.group(0))


# ===== 2. 起一個離屏 Tk root，用真實主視窗驗證行為 =====

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
    import config as config_module

    # SrtApp 會讀寫真正的 config.json（記憶主題、上次選取路徑等），測試
    # 不該動到使用者的真實檔案，指到一個獨立暫存目錄。
    _isolated_dir = tempfile.mkdtemp(prefix="v1490_test_")
    config_module.CONFIG_PATH = os.path.join(_isolated_dir, "config.json")

    from gui.app import SrtApp
    import gui.app as app_module

    FAKE_CUES = [
        {"start": i * 2.0, "end": i * 2.0 + 1.5, "text": f"字幕測試句 {i}"}
        for i in range(6)
    ]

    def pump(app, times=15, step=0.03):
        import time
        for _ in range(times):
            app.update()
            time.sleep(step)

    # ---- 2a. 「原本看不到、修完看得到」：底層方法直接量測 ----
    app = SrtApp()
    app.geometry("1400x800")
    app.deiconify()
    pump(app)

    win_height = app.winfo_height()
    check("主視窗確實依 geometry 顯示為高 800px（deiconify 之後量）",
          win_height == 800, win_height)

    app._populate_cue_list(FAKE_CUES)
    pump(app, times=8)

    diff_before = app.cue_tree.winfo_rooty() - app.winfo_rooty()
    check("字幕清單已 map（deiconify 之後）",
          app.cue_tree.winfo_ismapped() == 1)
    check(f"捲動前字幕清單在視窗高度之外（量到 y 差={diff_before}, 視窗高={win_height}）",
          diff_before > win_height, diff_before)

    app.scroll_frame.scroll_into_view(app.cue_tree)
    pump(app, times=8)

    diff_after = app.cue_tree.winfo_rooty() - app.winfo_rooty()
    check(f"呼叫 scroll_into_view 後字幕清單進入視窗高度之內（量到 y 差={diff_after}, 視窗高={win_height}）",
          diff_after < win_height, diff_after)

    # ---- 2b. 真實路徑 _on_generation_done 會觸發捲動 ----
    app.scroll_frame.canvas.yview_moveto(0.0)  # 重置回頁頂，模擬使用者停在頁頂
    pump(app, times=5)
    diff_reset = app.cue_tree.winfo_rooty() - app.winfo_rooty()
    check(f"重置回頁頂後字幕清單再次落在視窗高度之外（y 差={diff_reset}）",
          diff_reset > win_height, diff_reset)

    app._on_generation_done(FAKE_CUES)
    pump(app, times=8)
    diff_gen_done = app.cue_tree.winfo_rooty() - app.winfo_rooty()
    check(f"真實呼叫 _on_generation_done 後字幕清單進入視野（y 差={diff_gen_done}）",
          diff_gen_done < win_height, diff_gen_done)

    # ---- 2c. 真實路徑 _on_auto_done（一鍵完成批次）也會觸發捲動 ----
    app.scroll_frame.canvas.yview_moveto(0.0)
    pump(app, times=5)
    diff_reset2 = app.cue_tree.winfo_rooty() - app.winfo_rooty()

    # _on_auto_done 結束時會跳出摘要訊息框（messagebox.showinfo/showwarning），
    # Xvfb 下沒有人可以按確定，攔掉避免整個測試卡住。
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

    diff_auto_done = app.cue_tree.winfo_rooty() - app.winfo_rooty()
    check(f"重置回頁頂後（一鍵完成前）字幕清單落在視窗高度之外（y 差={diff_reset2}）",
          diff_reset2 > win_height, diff_reset2)
    check(f"真實呼叫 _on_auto_done（一鍵完成批次路徑）後字幕清單進入視野（y 差={diff_auto_done}）",
          diff_auto_done < win_height, diff_auto_done)
    check("一鍵完成結束確實跳出摘要訊息框（成功路徑）",
          len(info_calls) == 1 and len(warn_calls) == 0)

    # ---- 2d. 已經看得見就不要捲：夠高的視窗，canvas.yview() 不變 ----
    app_tall = SrtApp()
    app_tall.geometry("1400x2200")
    app_tall.deiconify()
    pump(app_tall)
    app_tall._populate_cue_list(FAKE_CUES)
    pump(app_tall, times=8)

    check("夠高的視窗下字幕清單本來就已 map 可見",
          app_tall.cue_tree.winfo_ismapped() == 1)

    yview_before = app_tall.scroll_frame.canvas.yview()
    app_tall.scroll_frame.scroll_into_view(app_tall.cue_tree)
    pump(app_tall, times=5)
    yview_after = app_tall.scroll_frame.canvas.yview()
    check(f"已可見時 canvas.yview() 呼叫前後不變（before={yview_before}, after={yview_after}）",
          yview_before == yview_after, (yview_before, yview_after))

    # ---- 2e. widget 尚未 map 時安全略過，不丟例外 ----
    import tkinter.ttk as ttk
    unmapped_widget = ttk.Label(app_tall.scroll_frame.interior, text="尚未 pack")
    # 刻意不呼叫 pack()／grid()，widget 停留在未 map 狀態。
    check("刻意建立的未 map widget 確實 winfo_ismapped()==0（前提成立才有意義測略過）",
          unmapped_widget.winfo_ismapped() == 0)
    try:
        app_tall.scroll_frame.scroll_into_view(unmapped_widget)
        no_exception = True
    except Exception as exc:  # pragma: no cover
        no_exception = False
        print("scroll_into_view 對未 map widget 丟出例外：", exc)
    check("scroll_into_view 對尚未 map 的 widget 安全略過、不丟例外", no_exception)


print()
if failures:
    print(f"失敗項目（共 {len(failures)}）：")
    for name in failures:
        print(" -", name)
    sys.exit(1)
print("全部通過。")
