# -*- coding: utf-8 -*-
"""
v2.3.2 回歸測試：〔文字稿對齊〕也顯示「轉寫設定」。

文字稿對齊要靠語音辨識找出人聲的時間（`align_transcript` 內部呼叫
`transcribe`），引擎、模型、語言、金鑰、轉寫提示全都會用到；但 v2.3.1
以前這一塊只在〔語音轉寫〕下顯示，使用者得先切過去設好再切回來。

這裡在真的 Tk 視窗裡量：

1. 三個模式各自顯示哪些區塊。
2. 文字稿對齊下，**文字稿框在轉寫設定上面**、而且在預設視窗 1400x800
   下整塊落在左欄可視範圍內（121～773）。只把轉寫設定打開、文字稿框照
   舊排最後的話，實測會被推到 y=1006～1179，這個模式最主要的輸入就看不
   到了。改動前（v2.3.1）的文字稿框在 617～790，底部已經被切掉一截。
3. 來回切換幾次之後順序不變（pack 的 before= 用錯時，第二次切換才會亂）。
4. README、版號與發佈政策。

捲動區裡的控件一律回報 `winfo_ismapped()==1`，所以「看不看得到」一律量
座標，不看 ismapped。
"""
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


# ===== 1. 真的視窗 ======================================================
#
# 只有「建不起視窗」（沒有 DISPLAY）可以略過。之後的任何例外都算失敗：
# 本檔第一版用一個大的 `except tk.TclError` 包住整段，結果「文字稿對齊下
# 不打開轉寫設定」的破壞探針讓 `_update_mode_state` 丟出 TclError（pack
# 的 before= 指向沒被 pack 的區塊），被當成沒有 DISPLAY 印了 SKIP，照樣
# 回報通過。

import json
import tkinter as tk

app = None
try:
    import config as config_module
    _tmp = tempfile.mkdtemp(prefix="v232_test_")
    config_module.CONFIG_PATH = os.path.join(_tmp, "config.json")
    with open(config_module.CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump({"whatsnew_seen": "never"}, fh)

    from gui.app import MODE_ALIGN, MODE_MANUAL, MODE_TRANSCRIBE, SrtApp

    def pump(widget, times=30):
        for _ in range(times):
            widget.update()
            widget.update_idletasks()

    app = SrtApp()
except tk.TclError as exc:  # 沒有 DISPLAY 時整段略過，不算失敗。
    print(f"SKIP Xvfb 實測（{exc}）")

if app is not None:
    try:
        app.geometry("1400x800+0+0")
        app.deiconify()
        pump(app)
        check("視窗是預設大小 1400x800（量到的不是 1px 假值）",
              (app.winfo_width(), app.winfo_height()) == (1400, 800),
              f"{app.winfo_width()}x{app.winfo_height()}")

        def shown(frame):
            return bool(frame.winfo_manager())

        def top(frame):
            return frame.winfo_rooty()

        def bottom(frame):
            return frame.winfo_rooty() + frame.winfo_height()

        view = app.scroll_frame
        view_top = view.winfo_rooty()
        view_bottom = view_top + view.winfo_height()

        def set_mode(mode):
            app.mode_var.set(mode)
            app._update_mode_state()
            pump(app)

        set_mode(MODE_TRANSCRIBE)
        check("語音轉寫：顯示轉寫設定", shown(app.transcription_frame))
        check("語音轉寫：不顯示文字稿框", not shown(app.transcript_frame))

        set_mode(MODE_MANUAL)
        check("手動輸入：兩塊都不顯示",
              not shown(app.transcription_frame) and not shown(app.transcript_frame))

        for round_no in (1, 2, 3):
            set_mode(MODE_ALIGN)
            tag = f"文字稿對齊（第 {round_no} 次切進來）"
            check(f"{tag}：顯示轉寫設定", shown(app.transcription_frame))
            check(f"{tag}：顯示文字稿框", shown(app.transcript_frame))
            check(f"{tag}：文字稿框在轉寫設定上面",
                  bottom(app.transcript_frame) <= top(app.transcription_frame),
                  f"{bottom(app.transcript_frame)} > {top(app.transcription_frame)}")
            check(f"{tag}：轉寫設定在斷句設定上面",
                  bottom(app.transcription_frame) <= top(app.segmentation_frame),
                  f"{bottom(app.transcription_frame)} > {top(app.segmentation_frame)}")
            check(f"{tag}：文字稿框整塊在左欄可視範圍內（{view_top}～{view_bottom}）",
                  view_top <= top(app.transcript_frame)
                  and bottom(app.transcript_frame) <= view_bottom,
                  f"{top(app.transcript_frame)}～{bottom(app.transcript_frame)}")
            # 切去別的模式再切回來，確認 before= 不會在第二次把順序弄亂。
            set_mode(MODE_TRANSCRIBE if round_no % 2 else MODE_MANUAL)

        # 轉寫設定裡真的有文字稿對齊會用到的東西（不是空殼）。
        set_mode(MODE_ALIGN)
        texts = []

        def walk(widget):
            for child in widget.winfo_children():
                try:
                    texts.append(str(child.cget("text")))
                except tk.TclError:
                    pass
                walk(child)
        walk(app.transcription_frame)
        for label in ("改用 OpenAI API", "API 金鑰:", "轉寫提示:"):
            check(f"文字稿對齊下看得到「{label}」", label in texts, str(texts[:12]))

        app.destroy()
    except Exception as exc:  # noqa: BLE001 —— 視窗建起來之後，任何例外都是失敗
        check("視窗實測過程沒有丟出例外", False, repr(exc))

# ===== 2. 文件與發佈政策 ================================================

readme = _read("README.md")
check("README 寫明轉寫設定在語音轉寫與文字稿對齊下都會顯示",
      "〔語音轉寫〕或〔文字稿對齊〕（「轉寫設定」在這兩個模式下都會顯示）" in readme)
check("README 不再說轉寫設定只在語音轉寫下顯示",
      "只在這個模式下顯示" not in readme)

promote = _read(".github/promote_releases.txt")
promoted = set(re.findall(r"^(v\d+\.\d+\.\d+)\s*$", promote, re.M))
m = re.search(r'APP_VERSION = "(\d+)\.(\d+)\.(\d+)"', _read("updater.py"))
version = tuple(int(g) for g in m.groups()) if m else (0, 0, 0)
check("APP_VERSION 已進到 2.3.2 以上", version >= (2, 3, 2), str(version))
if "v2.3.0" not in promoted:
    check("v2.3.0 還沒轉正，v2.3.2 也不能轉正", "v2.3.2" not in promoted)
changelog = _read("CHANGELOG.md")
heads = re.findall(r"^## (v2\.3\.2.*)$", changelog, re.M)
check("CHANGELOG 有 v2.3.2 且標明測試版",
      len(heads) == 1 and "測試版" in heads[0], str(heads))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v2.3.2 文字稿對齊顯示轉寫設定測試全數通過。")
