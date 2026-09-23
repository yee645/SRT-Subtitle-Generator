# -*- coding: utf-8 -*-
"""
v2.2.0 回歸測試：健檢中心內嵌成階段③頁籤內容（架構文件 B.5）。

在這一版之前，階段③只是一張「健檢中心」入口卡片，按下去仍會開一個
1120x900 的 Toplevel——四階段頁籤裡唯一一個還要另外開窗的階段，也是
2.0 實測 31 擊／7 窗沒達到預估 20 擊／3–5 窗的兩個原因之一。

本檔守住四件事：

  1. **健檢中心真的在頁籤裡**，而且從入口到開跑都不再開任何新視窗。
  2. **18 項勾選與〔進階設定〕沒有被埋進捲動區看不見的地方**。頁籤高度
     只有獨立視窗的七成，上下疊會把每次都要用的那一整組推到捲不到的位
     置；並排之後要能一眼全看到。這條是用「控件的可視範圍是否落在捲動
     畫布的可視區內」量的，不是看有沒有 pack 成功——widget 在捲動區裡
     一律 mapped，只看 mapped 會通過，等於沒測。
  3. **〔修復此項〕在預設尺寸與 minsize 都按得到**，連詳情三行文字都長
     到會換行時也一樣（pack 是先到先分配，這顆先宣告才卡得住位子）。
  4. **字幕是每次健檢前現拿的**，不再是開窗當下的快照。

量測一律在 `deiconify()` 之後（未顯示的視窗其子元件一律回報
`winfo_ismapped()=0`、寬高 1px），GUI 段一定要用有 sv_ttk 的直譯器。
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


# ===== 1. 原始碼層：不再是 Toplevel =====================================

check("gui/health_center_panel.py 存在（Toplevel 版已改寫為頁籤內容）",
      os.path.exists(os.path.join(ROOT, "gui", "health_center_panel.py")))
check("gui/health_center_dialog.py 已不存在（不留兩份會分岔的實作）",
      not os.path.exists(os.path.join(ROOT, "gui", "health_center_dialog.py")))

panel_src = _read("gui/health_center_panel.py")
app_src = _read("gui/app.py")

check("HealthCenterPanel 是 ttk.Frame 子類別（不是 tk.Toplevel）",
      "class HealthCenterPanel(ttk.Frame):" in panel_src)
check("面板裡沒有殘留視窗專屬呼叫（title/geometry/transient/protocol）",
      not re.search(r"\n        self\.(title|geometry|transient|protocol)\(",
                    panel_src.split("class HealthSettingsDialog")[0]))
check("gui/app.py 不再有任何地方 new 一個健檢中心視窗",
      "HealthCenterDialog" not in app_src)
check("階段③頁籤建的就是 HealthCenterPanel",
      "self.health_panel = HealthCenterPanel(" in app_src)
check("〔送健檢中心〕改成切頁籤而不是開窗",
      "self._go_to_health_stage(publish=dict(self.publish_data))" in app_src)

# 進階設定等子視窗的 master 必須是主視窗：Tk 的 wm transient 要的是
# toplevel，傳一個 Frame 進去會拋 TclError。
for cls in ("HealthSettingsDialog", "FfmpegInstallDialog", "SeriesCheckDialog"):
    check(f"{cls} 以主視窗（self._window）為 master，不是拿 Frame 當 master",
          f"{cls}(self._window" in panel_src or f"{cls}(\n            self._window"
          in panel_src)


# ===== 2. 純算式：捲動區高度預算 ========================================

from gui.health_center_panel import (_BOTTOM_RESERVE, _TOP_HEIGHT_MAX,
                                     _TOP_HEIGHT_MIN, _SIDE_BY_SIDE_WIDTH,
                                     _clamp_top_height)

check("很矮的頁籤仍留得住下半部（捲動區收到下限，不是等比縮水）",
      _clamp_top_height(300) == _TOP_HEIGHT_MIN, str(_clamp_top_height(300)))
check("很高的頁籤不會讓捲動區無限長（收在上限）",
      _clamp_top_height(5000) == _TOP_HEIGHT_MAX, str(_clamp_top_height(5000)))
check("預設尺寸（頁籤高 652px）時捲動區拿到 652-保留額",
      _clamp_top_height(652) == 652 - _BOTTOM_RESERVE,
      str(_clamp_top_height(652)))
check("保留額真的留得下主動作與報告區（至少 300px）",
      _BOTTOM_RESERVE >= 300, str(_BOTTOM_RESERVE))


# ===== 3. 次版的四個產出物（發佈政策硬性條件） ==========================
# 「任何次版以上的轉正，都要先有一份涵蓋『上一個轉正版 → 這一版』全部改
# 動的新功能介紹」，比照 2.0 的四個產出物：主文件、CHANGELOG 條目、
# README、程式內速覽。這裡寫成**跟著 APP_VERSION 走**的不變式，不是寫死
# 2.2——下一個次版照樣受這條約束，不必再改測試。

updater_src = _read("updater.py")
_m = re.search(r'APP_VERSION = "(\d+)\.(\d+)\.(\d+)"', updater_src)
check("讀得到 APP_VERSION", _m is not None)
if _m:
    major, minor, patch = (int(g) for g in _m.groups())
    check(f"APP_VERSION（{major}.{minor}.{patch}）已進到 2.2.0 以上",
          (major, minor, patch) >= (2, 2, 0))
    doc_name = f"WHATS_NEW_{major}.{minor}.md"
    doc_path = os.path.join(ROOT, "docs", doc_name)
    check(f"產出物①：docs/{doc_name} 存在（次版的新功能介紹）",
          os.path.exists(doc_path))
    changelog = _read("CHANGELOG.md")
    check(f"產出物②：CHANGELOG 有 v{major}.{minor}.{patch} 條目",
          f"## v{major}.{minor}.{patch}" in changelog)
    readme = _read("README.md")
    check(f"產出物③：README 指向 docs/{doc_name}", doc_name in readme)
    dialog_src = _read("gui/whatsnew_dialog.py")
    check(f"產出物④：程式內速覽提到本版（v{major}.{minor}）",
          f"v{major}.{minor}" in dialog_src)
    check("程式內速覽仍保有 v2.2 的主題（健檢中心內嵌）",
          "v2.2" in dialog_src)

    # 下面是 **v2.2 這一份**介紹的內容檢查（點擊數三處一致、誠實交代未
    # 達預估）。v2.3.0 起 APP_VERSION 往前走了，但這些數字只屬於 2.2 那份
    # 文件與那一條 CHANGELOG——若跟著 APP_VERSION 走，就會要求 2.3 的文件
    # 也放一張跟它無關的點擊數表。所以釘在 2.2，強度不變；新版本自己的內
    # 容檢查寫在自己的測試檔（見 tests/test_v230.py）。
    doc_name = "WHATS_NEW_2.2.md"
    doc_path = os.path.join(ROOT, "docs", doc_name)
    check("docs/WHATS_NEW_2.2.md 仍在（後面版本的介紹會連回它）",
          os.path.exists(doc_path))
    if os.path.exists(doc_path):
        doc = _read(f"docs/{doc_name}")
        section = changelog.split("\n## v2.2.0", 1)[1]
        nxt = re.search(r"\n## v", section)
        section = section[:nxt.start()] if nxt else section

        def pull(text, pattern, label):
            m = re.search(pattern, text)
            if m is None:
                check(f"{label}：找得到對照表那一列", False, pattern)
                return None
            return m.group(1)

        # 只比「有沒有出現這個字串」擋不住不一致（同一個數字在文中本來就
        # 會出現好幾次），所以從各自的對照表列裡把數字抓出來再互比——這是
        # tests/test_v200.py 用破壞探針證實過必要的作法。
        pairs = (
            (r"\|\s*點擊\s*\|[^|]*\|\s*\*\*(\d+)\s*次\*\*",
             r"點擊[^\n]*?→\s*(\d+)\s*次", "點擊數"),
            (r"\|\s*開啟視窗\s*\|[^|]*\|\s*\*\*(\d+)\s*個\*\*",
             r"開啟視窗[^\n]*?→\s*(\d+)\s*個", "視窗數"),
        )
        for table_re, dlg_re, label in pairs:
            a = pull(doc, table_re, f"{doc_name} {label}")
            b = pull(section, table_re, f"CHANGELOG {label}")
            c = pull(dialog_src, dlg_re, f"速覽 {label}")
            check(f"三處的「{label}」是同一個（{doc_name}／CHANGELOG／速覽）",
                  a is not None and a == b == c,
                  f"{doc_name}={a} CHANGELOG={b} 速覽={c}")

        check("介紹文件誠實交代仍未達預估值，而不是拿預估充數",
              "20 次" in doc and "校對" in doc)
        check("介紹文件是寫給使用者看的：不出現函式名或內部識別字",
              not any(t in doc for t in
                      ("_build_", "def ", "ttk.", "self.", "winfo_")))


# ===== 4. Xvfb 實測 ======================================================

if not os.environ.get("DISPLAY"):
    print("SKIP 無 DISPLAY，略過 GUI 段（CI 無虛擬螢幕時的正常情況）")
else:
    import tempfile
    import tkinter as tk

    import config as app_config

    _tmpcfg = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    _tmpcfg.write(b'{"whatsnew_seen": "99.9.9"}')
    _tmpcfg.close()
    app_config.CONFIG_PATH = _tmpcfg.name

    try:
        import sv_ttk  # noqa: F401
    except ImportError:
        print("SKIP GUI 段：這個直譯器沒有 sv_ttk，量到的不是使用者看到的樣子")
        sv_ttk = None

    from gui.app import SrtApp

    def pump(app, seconds=1.0):
        end = time.time() + seconds
        while time.time() < end:
            app.update()

    def toplevels(app):
        return [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]

    def visible_in_scroll(panel, widget):
        """控件是否落在捲動畫布「現在看得到」的那一段裡。

        捲動區裡的控件一律 winfo_ismapped()==1（它們在 canvas 的
        window 裡），所以只看 mapped 抓不到「被埋在最底下」。改量座標。
        """
        canvas = panel.top_scroll.canvas
        top = widget.winfo_rooty() - canvas.winfo_rooty()
        bottom = top + widget.winfo_height()
        left = widget.winfo_rootx() - canvas.winfo_rootx()
        right = left + widget.winfo_width()
        return (top >= -1 and bottom <= canvas.winfo_height() + 1
                and left >= -1 and right <= canvas.winfo_width() + 1)

    app = SrtApp()
    app.geometry("1400x800")
    app.deiconify()
    pump(app, 0.8)
    # 首次啟動速覽會蓋住主視窗，關掉再量（截圖／量測都踩過）。
    for w in toplevels(app):
        w.destroy()
    pump(app, 0.3)

    check("健檢中心是階段③頁籤的內容（不是按鈕）",
          hasattr(app, "health_panel")
          and str(app.health_panel.winfo_parent()) == str(app.stage_health_tab))

    before = len(toplevels(app))
    app.notebook.select(app.stage_health_tab)
    pump(app, 1.2)
    panel = app.health_panel
    check("切到階段③沒有開出任何新視窗",
          len(toplevels(app)) == before, str(toplevels(app)))
    check("頁籤裡就有開始健檢鈕與 17 項勾選",
          str(panel.run_btn.cget("text")) == "開始健檢"
          and len(panel.check_vars) == 17, str(len(panel.check_vars)))

    # ---- 18 項勾選＋進階設定不可被埋在捲動區看不見的地方 ----
    buried = []
    for child in panel._checklist_frame.winfo_children():
        for widget in ([child] + list(child.winfo_children())):
            try:
                text = widget.cget("text")
            except Exception:
                continue
            if isinstance(text, str) and text and not visible_in_scroll(
                    panel, widget):
                buried.append(text)
    check("1400x800：整組檢查勾選與〔進階設定〕一眼全看得到（沒有被埋在"
          "捲動區看不見的地方）",
          not buried, f"看不到的有 {len(buried)} 項：{buried[:4]}")

    check("1400x800：上半部是左右並排（寬度夠時不浪費橫向空間）",
          panel._top_wide is True)
    check("並排時兩欄的總寬度沒有溢出捲動畫布（否則要橫向捲）",
          panel._top_columns.winfo_reqwidth()
          <= panel.top_scroll.canvas.winfo_width() + 1,
          f"{panel._top_columns.winfo_reqwidth()} vs "
          f"{panel.top_scroll.canvas.winfo_width()}")

    # ---- 〔修復此項〕壓不得：灌進最長的內容也要按得到 ----
    long_text = "這是一段很長的發現說明，" * 12
    for size in ("1400x800", "980x560"):
        app.geometry(size)
        pump(app, 1.0)
        panel.detail_title_var.set("✘ " + long_text)
        panel.detail_body_var.set(long_text)
        panel.detail_advice_var.set(long_text)
        pump(app, 0.8)
        check(f"{size}：詳情三行都長到換行時，〔修復此項〕仍然看得到、"
              f"且拿得到完整尺寸",
              panel.fix_btn.winfo_ismapped() == 1
              and panel.fix_btn.winfo_width() >= panel.fix_btn.winfo_reqwidth()
              and panel.fix_btn.winfo_height() >= 20,
              f"{panel.fix_btn.winfo_width()}x{panel.fix_btn.winfo_height()} "
              f"mapped={panel.fix_btn.winfo_ismapped()}")
        check(f"{size}：〔開始健檢〕看得到",
              panel.run_btn.winfo_ismapped() == 1)
    panel.detail_title_var.set("")
    panel.detail_body_var.set("")
    panel.detail_advice_var.set("")

    check("980x560：窄到放不下兩欄時退回上下疊（由捲動區處理）",
          panel._top_wide is False, str(panel._top_wide))
    app.geometry("1400x800")
    pump(app, 1.0)
    check("拉回寬視窗時自動換回並排", panel._top_wide is True)

    # ---- 字幕現拿，不是開窗當下的快照 ----
    app.cues = [{"index": 1, "start": 0.0, "end": 1.0, "text": "第一句"},
                {"index": 2, "start": 1.0, "end": 2.0, "text": "第二句"}]
    panel.sync_cues()
    check("主視窗字幕改了之後，健檢中心拿到的是新的那一份（不是快照）",
          len(panel.cues) == 2 and panel.subs_var.get() == "（沿用目前的 2 句字幕）",
          f"{len(panel.cues)} / {panel.subs_var.get()}")
    app.cues = [{"index": 1, "start": 0.0, "end": 1.0, "text": "只剩一句"}]
    panel.sync_cues()
    check("再改一次也跟得上（每次健檢前現拿）", len(panel.cues) == 1)

    # 使用者自己挑過字幕檔之後，主視窗的變動不再蓋掉那份明示的選擇。
    panel.cues_overridden = True
    panel.cues = [{"index": 1, "start": 0.0, "end": 1.0, "text": "自己挑的"}]
    app.cues = [{"index": i, "start": 0.0, "end": 1.0, "text": "x"}
                for i in range(5)]
    panel.sync_cues()
    check("使用者自己用〔瀏覽...〕挑過字幕檔之後，自動同步不會蓋掉它",
          len(panel.cues) == 1 and panel.cues[0]["text"] == "自己挑的",
          str(len(panel.cues)))
    panel.cues_overridden = False

    # ---- 影片檔欄位的自動同步不覆蓋手動輸入 ----
    panel.set_media_path("/tmp/auto-1.mp4", auto=True)
    check("自動同步會把目前影片填進對象區",
          panel.media_var.get() == "/tmp/auto-1.mp4")
    panel.media_var.set("/tmp/使用者自己打的.mp4")
    panel.set_media_path("/tmp/auto-2.mp4", auto=True)
    check("使用者手動改過影片檔之後，自動同步不覆蓋",
          panel.media_var.get() == "/tmp/使用者自己打的.mp4",
          panel.media_var.get())
    panel.media_var.set("")
    panel.set_media_path("/tmp/auto-3.mp4", auto=True)
    check("欄位空著時自動同步照填", panel.media_var.get() == "/tmp/auto-3.mp4")

    # ---- 佇列輪詢只在背景工作進行中才排程 ----
    check("閒著的時候沒有每 120ms 空轉的輪詢（頁籤與程式同壽，空轉是"
          "整個生命週期的成本）",
          panel._poll_job is None, str(panel._poll_job))
    panel._ensure_polling()
    check("背景工作開跑時才排輪詢", panel._poll_job is not None)
    panel.after_cancel(panel._poll_job)
    panel._poll_job = None

    # ---- 舊「字幕健檢」鈕：切頁籤而不是開窗 ----
    app.notebook.select(app.stage_subtitle_tab)
    pump(app, 0.4)
    before = len(toplevels(app))
    app.cues = [{"index": 1, "start": 0.0, "end": 1.0, "text": "一句"}]
    app._open_subtitle_check_dialog()
    pump(app, 0.5)
    check("舊「字幕健檢」入口改成切到階段③，不再開視窗",
          app.notebook.select() == str(app.stage_health_tab)
          and len(toplevels(app)) == before,
          f"{app.notebook.select()} / {toplevels(app)}")

    # ---- 封面圖／系列影片預設收合，加檔案時自動展開 ----
    check("封面圖預設收合（頁籤上半部只有約 260px，攤開會把勾選擠掉）",
          not panel._thumb_expanded
          and panel.thumb_body.winfo_ismapped() == 0)
    check("系列影片預設收合",
          not panel._series_expanded
          and panel.series_body.winfo_ismapped() == 0)
    panel._toggle_thumb()
    pump(app, 0.3)
    check("點一下封面圖就展開", panel._thumb_expanded
          and panel.thumb_body.winfo_ismapped() == 1)
    panel._toggle_thumb()
    pump(app, 0.3)
    check("再點一下收合", not panel._thumb_expanded
          and panel.thumb_body.winfo_ismapped() == 0)
    panel.prefill_publish({"thumbs": ["/tmp/a.png"]})
    pump(app, 0.3)
    check("帶入封面候選圖時自動展開（填了卻收著等於沒填）",
          panel._thumb_expanded and panel.thumb_body.winfo_ismapped() == 1)

    app.destroy()
    os.unlink(_tmpcfg.name)


print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v2.2.0 健檢中心內嵌測試全數通過。")
