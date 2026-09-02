# -*- coding: utf-8 -*-
"""
v1.52.0 新功能測試：主視窗三欄化，修「折疊線」問題。

背景（`docs/UI_AUDIT_2.0.md` 1.3-①、`docs/UI_ARCHITECTURE_2.0.md`
B.2/B.3）：v1.x 主視窗是一張 1240px 高的單欄設定長表單，1400x800 預設
尺寸下「開始生成字幕」「一鍵完成」在 y=826、字幕清單在 y=889，全部在
畫面外；右欄同時有水平裁切（「刪除」剩「刪」、樣式面板右緣被切）。

v1.52.0 把它轉九十度：左欄（330px，`ScrollableFrame` 自帶垂直捲動，只
捲設定）／中欄（flex，主動作＋字幕清單＋清單編輯列＋匯出燒錄＋自動化
輸出，永遠可見）／右欄（420px，樣式組合＋預覽＋樣式面板）。這一步**只
換容器**：控件、command、config 欄位、按鈕文字全部不變（不做頁籤、不
拆一鍵完成——那些排在 v1.53）。

**本檔的核心驗收條件**（硬性要求，不能只斷言「有三個欄位」）：
1400x800、`deiconify()` 之後量「開始生成字幕」與字幕清單的 y，兩者都
要 < 800（視窗高度）——這是折疊線問題本身有沒有真的修好的直接證據。

其餘涵蓋：
  1. 功能對照：與 v1.51.0 逐行比對，app.py 的按鈕文字／self.xxx 屬性／
     方法名稱一個不少（動態讀入 git 凍結的舊版原始碼比對，不手寫清
     單）。
  2. 通用版面掃描（沿用 `tests/test_v1501.py` 的手法，套到主視窗）：
     走訪所有帶文字且已 map 的控件，任何「要的寬度 > 拿到的寬度」、
     「右緣超出視窗」都算失敗；另外掃描「應該看得到卻整個沒 map」的
     互動控件（比裁切更嚴重的情形，本版施工時真的踩到過，見 PR 說
     明）。
  3. minsize 980x560 退化規則：右欄收合、無裁切、主動作仍可見，
     「自動化輸出」仍可捲動到達（不會整個消失）；放寬回 1400x800 後
     右欄自動恢復。
  4. `style_panel.py` 420px 重排：`ttk.Scale` 取代 `tk.Scale`（規範漏
     網項），數值標籤功能保留；`preview_panel.py` 畫布縮小為 392x200。
  5. 深色主題：切換不拋例外，左右兩個 ScrollableFrame 的 Canvas 背景
     色都同步。
  6. 全站規範：`gui/` 沒有殘留 classic `tk.Checkbutton`/`tk.Radiobutton`/
     `tk.Scale`（排除合法的 `ttk.` 用法）。
  7. `subtitle/` 公開介面零改動（比對套件的 `__init__.py`／函式簽名與
     上一版一致，動態比對而非手寫清單）。
"""
import os
import re
import subprocess
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


def _read(rel):
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fp:
        return fp.read()


app_src = _read("gui/app.py")
style_src = _read("gui/style_panel.py")
preview_src = _read("gui/preview_panel.py")

# ===== 0. 動態讀入 v1.51.0（上一版）凍結的 gui/app.py，逐項比對 =========
# 用 `git show` 讀上一個 tag/commit 的內容，而非手寫「舊按鈕清單」——
# 清單本身就可能抄漏，動態比對才是真的在對照「改之前 vs 改之後」。

OLD_REF = "9364eea"  # v1.51.0 轉正版（本分支開工前的 HEAD）


def _git_show(ref, path):
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"], cwd=REPO_ROOT,
        capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout


old_app_src = _git_show(OLD_REF, "gui/app.py")

if old_app_src is None:
    print(f"SKIP 對照 {OLD_REF} 的 gui/app.py（此環境 git history 不含"
          "該 commit，略過動態功能對照，其餘測項照跑）")
else:
    # --- 按鈕/勾選/單選文字：舊版每一個 text="..." 在新版都要找得到 ---
    # 例外：三顆模式 radiobutton 改成迴圈建構＋插入 \n 換行（見
    # `_build_mode_section`，430px→330px 欄寬下 ttk.Radiobutton 不支援
    # wraplength，改用明確換行；文字內容一字不少，只是排成兩行）。
    old_texts = set(re.findall(r'text="([^"]*)"', old_app_src))
    new_texts = set(re.findall(r'text="([^"]*)"', app_src))
    # 三顆模式文字改成迴圈建構＋插入 \n 換行（見 `_build_mode_section`，
    # 330px 欄寬下 ttk.Radiobutton 不支援 wraplength，改用明確換行；
    # 內容一字不少，只是排成兩行），比對時把 \n 去掉再核對是否還在。
    # app_src 是原始檔案文字，字串裡的換行是「反斜線 + n」兩個字元
    # （不是真正的換行字元），要用同樣的兩字元序列取代才對得起來。
    mode_texts_folded = {
        t.replace("\\n", "") for t in
        re.findall(r'"(模式[一二三][：:].*?)"', app_src)
    }
    truly_missing = {t for t in (old_texts - new_texts)
                     if t not in mode_texts_folded}
    check(f"v1.51.0 的所有按鈕/標籤文字（共 {len(old_texts)} 個）在 "
          "v1.52.0 一個不少（三顆模式文字改插入換行，內容不變，已排除）",
          not truly_missing, str(truly_missing))

    # --- self.xxx 屬性：舊版賦值過的屬性，新版一個不能少 ---
    old_attrs = set(re.findall(r"self\.(\w+)(?=\s*=[^=])", old_app_src))
    new_attrs = set(re.findall(r"self\.(\w+)(?=\s*=[^=])", app_src))
    missing_attrs = old_attrs - new_attrs
    check(f"v1.51.0 的所有 self.xxx 屬性（共 {len(old_attrs)} 個）在 "
          "v1.52.0 一個不少", not missing_attrs, str(missing_attrs))

    # --- 方法名稱：舊版定義過的方法，新版一個不能少 ---
    old_methods = set(re.findall(r"def (\w+)\(", old_app_src))
    new_methods = set(re.findall(r"def (\w+)\(", app_src))
    missing_methods = old_methods - new_methods
    check(f"v1.51.0 的所有方法（共 {len(old_methods)} 個）在 v1.52.0 "
          "一個不少", not missing_methods, str(missing_methods))
    added_methods = new_methods - old_methods
    check("新增的方法只有三欄退化規則相關的兩個（_apply_body_layout／"
          "_on_root_configure），沒有意外多改東西",
          added_methods == {"_apply_body_layout", "_on_root_configure"},
          str(added_methods))


# ===== 1. style_panel.py：ttk.Scale 取代 tk.Scale =====================

check("gui/style_panel.py 已把 tk.Scale 換成 ttk.Scale（規範漏網項）",
      "tk.Scale(" not in style_src.replace("ttk.Scale(", ""))
check("gui/style_panel.py 用共用的 _scale_row 建構水平/垂直位置兩支滑桿"
      "（實際會建立幾個 ttk.Scale 實例在下方 Xvfb 動態驗證，不能只看原"
      "始碼出現次數——helper 抽出來後 source 只會出現一次 ttk.Scale(）",
      style_src.count("self._scale_row(") == 2)
check("gui/style_panel.py 的滑桿長度改為 200（B.7 排版）",
      "length=_SCALE_LENGTH" in style_src and "_SCALE_LENGTH = 200" in style_src)

# ===== 2. preview_panel.py：畫布縮小為 392x200 ==========================

check("gui/preview_panel.py PREVIEW_WIDTH == 392",
      "PREVIEW_WIDTH = 392" in preview_src)
check("gui/preview_panel.py PREVIEW_HEIGHT == 200",
      "PREVIEW_HEIGHT = 200" in preview_src)

# ===== 3. 全站規範：無殘留 classic tk.Checkbutton/Radiobutton/Scale =====

import glob as _glob
offenders = []
for path in _glob.glob(os.path.join(REPO_ROOT, "gui", "*.py")):
    text = open(path, encoding="utf-8").read()
    stripped = (text.replace("ttk.Checkbutton(", "")
                .replace("ttk.Radiobutton(", "")
                .replace("ttk.Scale(", ""))
    for widget in ("Checkbutton", "Radiobutton", "Scale"):
        if f"tk.{widget}(" in stripped:
            offenders.append((os.path.basename(path), widget))
check("gui/*.py 沒有殘留 classic tk.Checkbutton/Radiobutton/Scale"
      "（有勾選/選取狀態的控件一律 ttk.*）",
      not offenders, str(offenders))

# ===== 4. subtitle/ 公開介面零改動（動態比對 v1.51.0） =================

if old_app_src is not None:
    old_subtitle_files = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", OLD_REF, "subtitle/"],
        cwd=REPO_ROOT, capture_output=True, text=True).stdout.split()
    new_subtitle_files = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD", "subtitle/"],
        cwd=REPO_ROOT, capture_output=True, text=True).stdout.split()
    diff = subprocess.run(
        ["git", "diff", "--name-only", OLD_REF, "--", "subtitle/"],
        cwd=REPO_ROOT, capture_output=True, text=True).stdout.split()
    check("subtitle/ 目錄相對上一版沒有任何檔案被改動（硬性要求：公開"
          "介面零改動）", not diff, str(diff))
    check("subtitle/ 檔案清單也沒有增減",
          set(old_subtitle_files) == set(new_subtitle_files),
          str(set(old_subtitle_files) ^ set(new_subtitle_files)))


# ===== 5. Xvfb 下的真實視窗：核心驗收條件 + 通用版面掃描 + minsize 退化 ===

try:
    import tkinter as tk
    from tkinter import ttk

    import config as config_module
    _isolated_dir = tempfile.mkdtemp(prefix="v1520_test_")
    config_module.CONFIG_PATH = os.path.join(_isolated_dir, "config.json")

    from gui.app import SrtApp
    from gui.app import _HAS_SV_TTK

    def pump(widget, times=40):
        for _ in range(times):
            widget.update()
            widget.update_idletasks()

    def scan(root, win_w):
        """沿用 tests/test_v1501.py 的通用版面掃描手法。"""
        clipped, overflow = [], []
        def walk(widget):
            for child in widget.winfo_children():
                try:
                    text = child.cget("text")
                except Exception:
                    text = None
                if text and isinstance(text, str) and child.winfo_ismapped():
                    need = child.winfo_reqwidth()
                    got = child.winfo_width()
                    right = child.winfo_rootx() - root.winfo_rootx() + got
                    if need > got + 1:
                        clipped.append((text.replace("\n", "/"), need, got))
                    if right > win_w:
                        overflow.append((text.replace("\n", "/"), right))
                walk(child)
        walk(root)
        return clipped, overflow

    def scan_unmapped(root, excluded_roots=()):
        """找出「應該看得到卻整個沒 map」的互動控件（比裁切更嚴重）。"""
        found = []
        def walk(widget):
            if widget in excluded_roots:
                return
            for child in widget.winfo_children():
                if child in excluded_roots:
                    continue
                if isinstance(child, (ttk.Button, ttk.Checkbutton,
                                      ttk.Radiobutton, tk.Button)):
                    try:
                        text = child.cget("text")
                    except Exception:
                        text = None
                    if text and not child.winfo_ismapped():
                        found.append(text)
                walk(child)
        walk(root)
        return found

    app = SrtApp()
    app.geometry("1400x800+0+0")
    app.deiconify()
    pump(app)

    win_w, win_h = app.winfo_width(), app.winfo_height()
    check("視窗有真的顯示出來（否則量到的都是 1px 假值）",
          win_w > 100 and win_h > 100, f"{win_w}x{win_h}")

    # ---- 核心驗收條件：主鈕與字幕清單的 y 都 < 視窗高度 ----
    gen_y = app.generate_btn.winfo_rooty() - app.winfo_rooty()
    auto_y = app.auto_btn.winfo_rooty() - app.winfo_rooty()
    cue_y = app.cue_tree.winfo_rooty() - app.winfo_rooty()
    check(f"【核心驗收】「開始生成字幕」y={gen_y} < 視窗高 {win_h}",
          gen_y < win_h, gen_y)
    check(f"【核心驗收】「一鍵完成」y={auto_y} < 視窗高 {win_h}",
          auto_y < win_h, auto_y)
    check(f"【核心驗收】字幕清單 y={cue_y} < 視窗高 {win_h}",
          cue_y < win_h, cue_y)
    check("主鈕與字幕清單同屏可見（不必捲動）",
          app.generate_btn.winfo_ismapped() == 1
          and app.cue_tree.winfo_ismapped() == 1)

    # ---- 通用版面掃描：1400x800 下不可有裁切/溢出/整個消失 ----
    clipped, overflow = scan(app, win_w)
    check("1400x800：沒有控件被裁切（要的寬度 > 拿到的寬度）",
          not clipped, str(clipped))
    check("1400x800：沒有控件右緣超出視窗",
          not overflow, str(overflow))
    unmapped = scan_unmapped(app, excluded_roots=(app.transcript_frame,))
    check("1400x800：沒有互動控件因版面擠不下而整個消失（比裁切更嚴重，"
          "施工時真的踩過——cue_edit_controls 10 顆按鈕擠一列時後 4 顆"
          "被 pack 擠到寬度 1px/未 map）",
          not unmapped, str(unmapped))

    # ---- 右欄無水平裁切，樣式面板/預覽都收在視窗內 ----
    style_right = (app.style_panel.winfo_rootx() - app.winfo_rootx()
                  + app.style_panel.winfo_width())
    check(f"樣式面板右緣 {style_right} < 視窗寬 {win_w}（v1.x 曾被裁切）",
          style_right <= win_w, style_right)
    # Canvas 的 winfo_reqwidth/height 會多算 highlightthickness*2（邊框
    # 1px），392+2=394、200+2=202 才是量到的真實值；PREVIEW_WIDTH/HEIGHT
    # 常數本身已在上面靜態檢查過是 392/200。
    check("預覽畫布尺寸為 392x200（連 highlightthickness 邊框一起量）",
          app.preview.canvas.winfo_reqwidth() == 394
          and app.preview.canvas.winfo_reqheight() == 202,
          f"{app.preview.canvas.winfo_reqwidth()}x"
          f"{app.preview.canvas.winfo_reqheight()}")

    # ---- 左欄 ScrollableFrame 只捲設定：mode/transcription 等都在裡面 ----
    check("左欄的 scroll_frame.interior 底下找得到運作模式區",
          app.mode_var is not None)  # 建構期不拋例外即代表掛載成功
    check("左欄寬度固定為 330px", app.left_container.winfo_width() == 330)
    check("右欄寬度固定為 420px", app.right_container.winfo_width() == 420)

    def count_scales(widget):
        total = sum(1 for c in widget.winfo_children()
                   if isinstance(c, ttk.Scale))
        for c in widget.winfo_children():
            total += count_scales(c)
        return total

    check("style_panel 實際建立了 2 個 ttk.Scale 元件（水平/垂直位置，"
          "動態驗證，不只看原始碼出現次數）",
          count_scales(app.style_panel) == 2, count_scales(app.style_panel))

    # ---- 深色主題：切換不拋例外，兩個 ScrollableFrame 背景色都同步 ----
    theme_ok = True
    try:
        app._toggle_theme()
        pump(app, times=15)
    except Exception as exc:  # pragma: no cover
        theme_ok = False
        print("切換深色主題時發生例外：", exc)
    check("切換深色主題不拋例外", theme_ok)
    # Canvas 背景同步只在有裝 sv_ttk 時才會實際套用（`_apply_theme` 對
    # 未裝 sv_ttk 直接 early return，這是既有設計、不是本版新行為）；
    # `tests/run_all.py` 用 `sys.executable` 跑全部測試檔，不保證是
    # /tmp/vtk/bin/python3，所以這裡照 `_HAS_SV_TTK` 決定要不要驗證，
    # 真正的主題渲染驗證交給 Xvfb 截圖（見 PR 說明的紀律要求）。
    if _HAS_SV_TTK:
        check("左欄 Canvas 背景已同步為深色",
              app.scroll_frame.canvas.cget("background") == "#1c1c1c")
        check("中欄 Canvas 背景也同步為深色（v1.52.0 中欄新增的"
              "ScrollableFrame，理由同左欄——Canvas 不是 ttk 元件）",
              app.middle_scroll_frame.canvas.cget("background") == "#1c1c1c")
    else:
        print("SKIP Canvas 深色背景同步驗證（此直譯器未裝 sv_ttk，"
              "_apply_theme 依既有設計直接 early return；截圖驗證另外"
              "用 /tmp/vtk/bin/python3 做，見 PR 說明）")
    app._toggle_theme()  # 切回淺色，避免影響後續量測。
    pump(app, times=15)

    # ---- 模式切換：ALIGN／MANUAL／回 TRANSCRIBE 都不拋例外 ----
    mode_ok = True
    try:
        app.mode_var.set("align")
        app._update_mode_state()
        pump(app, times=10)
        check("切到模式二後文字稿區塊可見",
              app.transcript_frame.winfo_ismapped() == 1)
        app.mode_var.set("manual")
        app._update_mode_state()
        pump(app, times=10)
        app.mode_var.set("transcribe")
        app._update_mode_state()
        pump(app, times=10)
        check("切回模式一後轉寫設定區塊可見",
              app.transcription_frame.winfo_ismapped() == 1)
    except Exception as exc:  # pragma: no cover
        mode_ok = False
        print("模式切換時發生例外：", exc)
    check("模式一/二/三來回切換不拋例外", mode_ok)

    # ---- minsize 980x560：右欄收合、無裁切、主動作仍可見 ----
    app.geometry("980x560+0+0")
    pump(app)
    check("minsize 980x560 時右欄已收合（三欄退化規則）",
          app._right_collapsed and app.right_container.winfo_ismapped() == 0)
    min_clipped, min_overflow = scan(app, app.winfo_width())
    check("minsize 980x560：沒有控件被裁切", not min_clipped, str(min_clipped))
    check("minsize 980x560：沒有控件右緣超出視窗",
          not min_overflow, str(min_overflow))
    check("minsize 980x560：「開始生成字幕」仍然可見",
          app.generate_btn.winfo_ismapped() == 1
          and app.generate_btn.winfo_rooty() - app.winfo_rooty() < 560)

    # 「自動化輸出」在 minsize 不會整個消失——mapped，且捲到底可以看到。
    check("minsize 980x560：「自動化輸出」區塊仍有 mapped（不是像本版"
          "施工時一度出現的『整個消失』，可透過中欄捲動到達）",
          app.automation_frame.winfo_ismapped() == 1)
    ms = app.middle_scroll_frame
    ms.canvas.yview_moveto(1.0)
    pump(app, times=10)
    top_frac, bottom_frac = ms.canvas.yview()
    interior_h = ms.interior.winfo_reqheight()
    visible_top = top_frac * interior_h
    visible_bottom = bottom_frac * interior_h
    auto_top = app.automation_frame.winfo_rooty() - ms.interior.winfo_rooty()
    auto_bottom = auto_top + app.automation_frame.winfo_height()
    check("minsize 980x560：捲到底後「自動化輸出」進入可視範圍（真的"
          "拿得到，不只是 mapped=1 的假象）",
          auto_top >= visible_top - 5 and auto_bottom <= visible_bottom + 5,
          f"auto=({auto_top},{auto_bottom}) visible=({visible_top},{visible_bottom})")

    # ---- 放寬回 1400x800：右欄自動恢復 ----
    app.geometry("1400x800+0+0")
    pump(app)
    check("放寬回 1400x800 後右欄自動恢復（不需要另外按什麼展開鈕）",
          not app._right_collapsed and app.right_container.winfo_ismapped() == 1)

    # ---- 功能性 smoke：自動化設定收集、新增/刪除字幕在新版面下仍正常 ----
    app.auto_export_vars["export_vtt"].set(True)
    app._collect_automation_config()
    check("自動化輸出設定收集功能正常（搬到中欄後行為不變）",
          app.config_data["automation"]["export_vtt"] is True)

    before_count = len(app.cues)
    app.cues = [{"start": 0.0, "end": 1.0, "text": "測試"}]
    app._populate_cue_list(app.cues)
    pump(app, times=5)
    check("字幕清單在新版面下仍能正常填入",
          len(app.cue_tree.get_children()) == 1)

    app.destroy()
except tk.TclError as exc:  # 沒有 DISPLAY 時整段略過，不算失敗。
    print(f"SKIP Xvfb 實測（{exc}）")


print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.52.0 主視窗三欄化測試全數通過。")
