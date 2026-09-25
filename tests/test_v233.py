# -*- coding: utf-8 -*-
"""
v2.3.3 回歸測試：習慣設定講清楚「一組樣式存了什麼」與「改了還沒存」。

`docs/UI_AUDIT_2.0.md` 1.3-② 記錄「習慣設定（樣式組合）」與「字幕視覺調
整」兩個面板的關係沒有表達。實際讀程式發現更具體的兩件事：

- 一組「樣式」存的是字幕外觀**加上左欄的斷句設定**（`make_profile`），
  標題與下拉選單卻都只說「樣式」，套用時左欄的數值會被悄悄換掉。
- 改了外觀或斷句之後，看不出「畫面上的值還沒存進那一組」。

這裡守：

1. `config.profile_changed_parts`／`describe_preset_state` 的判斷（純函
   式，零 GUI）。
2. 真的視窗裡：狀態行跟著改動即時變化、存起來或重新套用後回到「一致」；
   說明文字提到的區塊名稱與按鈕名稱都是介面上真的存在的；改斷句數字時
   **不會每按一下就寫一次設定檔**。
3. 發佈政策。
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


import config  # noqa: E402

# ===== 1. 純函式 ========================================================

style = {"font_size": 26, "position_x": 0.5, "text_color": "#FFFFFF",
         "emphasis_enabled": False}
seg = {"max_chars_cjk": 18, "pause_gap": 0.5}
base = config.make_profile(style, seg)

check("完全一致 → 沒有差異", config.profile_changed_parts(base, base) == [])
check("只改外觀 → 只說字幕外觀",
      config.profile_changed_parts(
          config.make_profile({**style, "font_size": 30}, seg), base) == ["字幕外觀"])
check("只改斷句 → 只說斷句設定",
      config.profile_changed_parts(
          config.make_profile(style, {**seg, "max_chars_cjk": 22}), base) == ["斷句設定"])
check("兩個都改 → 兩個都說，順序固定（外觀在前）",
      config.profile_changed_parts(
          config.make_profile({**style, "text_color": "#000000"},
                              {**seg, "pause_gap": 0.8}), base) == ["字幕外觀", "斷句設定"])
check("滑桿換算的微小誤差不算改過",
      config.profile_changed_parts(
          config.make_profile({**style, "position_x": 0.5 + 1e-9}, seg), base) == [])
check("整數與同值的小數不算改過（Spinbox 讀回來可能是 26.0）",
      config.profile_changed_parts(
          config.make_profile({**style, "font_size": 26.0}, seg), base) == [])
check("布林值照實比（勾選重點字上色算改過）",
      config.profile_changed_parts(
          config.make_profile({**style, "emphasis_enabled": True}, seg), base)
      == ["字幕外觀"])
check("舊版存下的組合少了後來才加的欄位，不算改過",
      config.profile_changed_parts(
          config.make_profile({**style, "dynamic_mode": "karaoke"}, seg), base) == [])

presets = {"預設": base}
check("選取的名稱不存在 → 不顯示任何狀態",
      config.describe_preset_state(base, presets, "不存在") == "")
check("一致時講明跟哪一組一致",
      config.describe_preset_state(base, presets, "預設") == "目前的值與「預設」一致。")
dirty = config.describe_preset_state(
    config.make_profile(style, {**seg, "max_chars_cjk": 22}), presets, "預設")
check("改過時講明改了哪一部分、還沒存進哪一組", "已改過斷句設定" in dirty
      and "還沒存進「預設」" in dirty, dirty)

# 狀態行叫使用者按的按鈕，要是介面上真的有的按鈕。
app_src = _read("gui/app.py")
body = app_src.split("def _build_preset_section", 1)[1].split("\n    def ", 1)[0]
buttons = set(re.findall(r'text="([^"]+)", command=', body))
for name in re.findall(r"〔([^〕]+)〕", dirty):
    check(f"狀態行提到的〔{name}〕是習慣設定區真的有的按鈕", name in buttons,
          str(buttons))

# ===== 2. 真的視窗 ======================================================
#
# 只有建不起視窗可以略過；之後任何例外都算失敗（v2.3.2 踩過：過寬的
# except tk.TclError 會把真的錯誤當成沒有 DISPLAY）。

import json  # noqa: E402
import tkinter as tk  # noqa: E402

app = None
try:
    config.CONFIG_PATH = os.path.join(tempfile.mkdtemp(prefix="v233_test_"),
                                      "config.json")
    with open(config.CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump({"whatsnew_seen": "never"}, fh)
    from gui.app import SrtApp
    app = SrtApp()
except tk.TclError as exc:
    print(f"SKIP Xvfb 實測（{exc}）")

if app is not None:
    try:
        def pump(times=20):
            for _ in range(times):
                app.update()
                app.update_idletasks()

        app.geometry("1400x800+0+0")
        app.deiconify()
        pump()
        state = app.preset_state_var

        check("啟動時：目前的值與選取的那一組一致",
              state.get() == f"目前的值與「{app.preset_var.get()}」一致。", state.get())

        saves = []
        real_save = app._save_config_silently
        app._save_config_silently = lambda: saves.append(1)
        app.cjk_limit_var.set(app.cjk_limit_var.get() + 3)
        pump()
        check("改斷句數字 → 狀態行立刻說斷句設定改過",
              "已改過斷句設定" in state.get(), state.get())
        check("改斷句數字時不會寫設定檔（只比對、不存）", saves == [], str(len(saves)))
        app._save_config_silently = real_save

        st = app.style_panel.get_style()
        st["font_size"] = st["font_size"] + 4
        app.style_panel.set_style(st)
        app._on_style_change(app.style_panel.get_style())
        pump()
        check("再改外觀 → 狀態行說兩部分都改過",
              "已改過字幕外觀、斷句設定" in state.get(), state.get())

        app._update_preset()
        pump()
        check("按〔更新目前樣式〕之後回到一致",
              state.get().startswith("目前的值與"), state.get())
        check("更新之後，存起來的那一組真的包含左欄改過的斷句數字",
              app.config_data["presets"][app.preset_var.get()]["segmentation"]
              ["max_chars_cjk"] == app.cjk_limit_var.get())

        app.pause_gap_var.set(round(app.pause_gap_var.get() + 0.3, 2))
        pump()
        check("再改一次 → 又變成改過", "已改過斷句設定" in state.get(), state.get())
        st = app.style_panel.get_style()
        st["stroke_width"] = st["stroke_width"] + 1
        app.style_panel.set_style(st)
        app._on_style_change(app.style_panel.get_style())
        pump()
        # 前置條件：下面「回到一致」要是真的被重算出來的，不是狀態行本來就停
        # 在「一致」（沒有這條時，拿掉斷句的即時更新後那條照樣會過）。
        check("重新套用前，狀態行確實是『外觀與斷句都改過』",
              "已改過字幕外觀、斷句設定" in state.get(), state.get())
        app._apply_preset()
        pump()
        check("重新套用那一組 → 左欄數字被換回來、狀態回到一致",
              state.get().startswith("目前的值與"), state.get())
        check("套用時狀態列講明左欄的斷句設定也一起換了",
              "斷句設定" in app.status_var.get(), app.status_var.get())

        # 說明文字提到的區塊名稱是介面上真的存在的標題。
        titles = set()

        def walk(widget):
            for child in widget.winfo_children():
                try:
                    titles.add(str(child.cget("text")))
                except tk.TclError:
                    pass
                walk(child)
        walk(app)
        hint = next((t for t in titles if t.startswith("一組樣式存的是")), "")
        check("習慣設定區有說明一組樣式存了什麼", bool(hint))
        for name in re.findall(r"「([^」]+)」", hint):
            check(f"說明提到的「{name}」是介面上真的有的區塊", name in titles)
        for name in re.findall(r"〔([^〕]+)〕", hint):
            check(f"說明提到的〔{name}〕是真的有的按鈕", name in titles)

        label = app.preset_state_label
        check("狀態行在預設視窗大小下沒有被裁切（要求寬度 ≤ 實際寬度）",
              label.winfo_reqwidth() <= label.winfo_width(),
              f"{label.winfo_reqwidth()} > {label.winfo_width()}")

        app.destroy()
    except Exception as exc:  # noqa: BLE001 —— 視窗建起來之後，任何例外都是失敗
        check("視窗實測過程沒有丟出例外", False, repr(exc))

# ===== 3. 發佈政策 ======================================================

promote = _read(".github/promote_releases.txt")
promoted = set(re.findall(r"^(v\d+\.\d+\.\d+)\s*$", promote, re.M))
m = re.search(r'APP_VERSION = "(\d+)\.(\d+)\.(\d+)"', _read("updater.py"))
version = tuple(int(g) for g in m.groups()) if m else (0, 0, 0)
check("APP_VERSION 已進到 2.3.3 以上", version >= (2, 3, 3), str(version))
if "v2.3.0" not in promoted:
    check("v2.3.0 還沒轉正，v2.3.3 也不能轉正", "v2.3.3" not in promoted)
heads = re.findall(r"^## (v2\.3\.3\D.*)$", _read("CHANGELOG.md"), re.M)
check("CHANGELOG 有 v2.3.3 且標明測試版",
      len(heads) == 1 and "測試版" in heads[0], str(heads))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v2.3.3 習慣設定狀態測試全數通過。")
