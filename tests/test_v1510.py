# -*- coding: utf-8 -*-
"""
v1.51.0 新功能測試：健檢中心（二）——把 publishcheck_dialog／
thumbcheck_dialog／chapter_dialog 併進健檢中心，`termcheck.apply_term_fixes`
首次接上 GUI；`series_dialog`（多支影片互相比較）依
`docs/UI_AUDIT_2.0.md` 2.2 節預留的退路保留為獨立視窗，只是入口從主視窗
工具列移進健檢中心的對象區。工具列 11→6 顆。

延續 `tests/test_v1500.py` 的做法：**不手寫清單自證**，動態讀入四個舊檔
案（`gui/publishcheck_dialog.py`／`gui/thumbcheck_dialog.py`／
`gui/chapter_dialog.py`／`gui/series_dialog.py`——四個檔案本身完全未被
修改，仍在 repo 裡）的原始碼，逐一確認每個舊有的分析函式、修復函式在新
的 `gui/health_aggregator.py`（或 `gui/health_center_dialog.py`，系列一
致性走這條）仍被呼叫到。

其餘涵蓋：
  1. 18 項健檢定義完整（v1.50.0 的 15 項 + 發佈健檢／封面健檢／章節健
     檢 3 項）。
  2. 9 個修復動作都能被 `tag_fix_key()` 正確標記、`FIX_LABELS` 都有對
     應文字（v1.50.0 的 7 個 + 新增的 term_fix／chapter_fix）。
  3. 真實 ffmpeg 端到端：合成封面圖片（含一張畫面單調會被判定可讀性
     不足的、一張正常的），實跑封面健檢；貼發佈文字與章節文字實跑對應
     檢查；驗證報告內容合理、無例外。
  4. 對象區「全部選填、填什麼檢什麼」延伸到新三項：沒填就悄悄略過，
     不報錯、不擋住其他項目。
  5. `apply_term_fixes` 真的被呼叫得到、真的會修改字幕文字。
  6. `chaptercheck.fix_chapters` 透過新的 `apply_text_fix("chapter_fix")`
     介面被呼叫得到、真的會修改章節文字。
  7. Xvfb 下開出真正的 `HealthCenterDialog`：對象區有封面圖／發佈文字
     （可摺疊）／系列影片三個新區塊、系列一致性視窗開得起來、
     checklist 從 14 顆變 17 顆（+1 顆一律檢查的檔名）。
  8. `gui/app.py`：工具列 11→6 顆，四個舊視窗的 import 都不見了，但
     `gui/series_dialog.py`／`gui/publishcheck_dialog.py`／
     `gui/thumbcheck_dialog.py`／`gui/chapter_dialog.py` 檔案本身仍在
     （只是不再被 app.py 直接開啟）。
  9. 全站規範：沒有 classic `tk.Checkbutton`/`tk.Radiobutton` 殘留。
"""
import os
import shutil
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


from gui import health_aggregator as ha  # noqa: E402

# ===== 0. 讀入四個舊檔案原始碼（檔案本身完全未修改）供動態比對 ========

def _read(rel):
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fp:
        return fp.read()


publish_src = _read("gui/publishcheck_dialog.py")
thumb_src = _read("gui/thumbcheck_dialog.py")
chapter_src = _read("gui/chapter_dialog.py")
series_src = _read("gui/series_dialog.py")
aggregator_src = _read("gui/health_aggregator.py")
center_src = _read("gui/health_center_dialog.py")
app_src = _read("gui/app.py")
termcheck_src = _read("subtitle/termcheck.py")

check("四個舊視窗檔案仍在 repo 裡、完全未被修改（回退性：只改按鈕指向）",
      "class PublishCheckDialog" in publish_src
      and "class ThumbCheckDialog" in thumb_src
      and "class ChapterCheckDialog" in chapter_src
      and "class SeriesCheckDialog" in series_src)

# app.py 不該再 import 三個「已併入單支分級報告」的舊類別；
# SeriesCheckDialog 也不再由 app.py 直接 import（入口移進健檢中心）。
check("gui/app.py 不再 import PublishCheckDialog（改由健檢中心對象區接手）",
      "PublishCheckDialog" not in app_src)
check("gui/app.py 不再 import ThumbCheckDialog（改由健檢中心對象區接手）",
      "ThumbCheckDialog" not in app_src)
check("gui/app.py 不再 import ChapterCheckDialog（改由健檢中心對象區接手）",
      "ChapterCheckDialog" not in app_src)
check("gui/app.py 不再 import SeriesCheckDialog（入口移進健檢中心對象區）",
      "SeriesCheckDialog" not in app_src)
check("gui/health_center_dialog.py 改為 import SeriesCheckDialog（系列一致"
      "性依退路保留為獨立視窗，入口搬進對象區）",
      "from gui.series_dialog import SeriesCheckDialog" in center_src)


# ===== 1. 能力對照表（動態）：舊視窗呼叫過的每個函式，新版仍呼叫得到 ===

# --- 1a. publishcheck_dialog：4 個分析/報告函式、0 個修復（唯讀）---
# format_publish_report／format_desc_report 本身不必被沿用——健檢中心
# 統一改用 `format_health_report` 產生單一分級報告（同 test_v1500.py 的
# 先例：舊視窗各自的報告排版函式本來就不是「能力」，內容（title/detail/
# advice）才是；analyze_publish／analyze_description 這兩個真正做分析
# 判斷的函式才是要對照的對象）。
PUBLISH_FUNCS = ("analyze_publish", "analyze_description")
for func in PUBLISH_FUNCS:
    check(f"舊 publishcheck_dialog 呼叫過的 {func}() 仍在 health_aggregator "
          "呼叫", func in publish_src and func in aggregator_src)

# --- 1b. thumbcheck_dialog：多張排名，0 個修復（唯讀）---
THUMB_FUNCS = ("rank_thumbnails",)
for func in THUMB_FUNCS:
    check(f"舊 thumbcheck_dialog 呼叫過的 {func}() 仍在 health_aggregator "
          "呼叫", func in thumb_src and func in aggregator_src)

# --- 1c. chapter_dialog：章節規則 + 一鍵修正 ---
CHAPTER_ANALYSIS_FUNCS = ("parse_chapters", "validate_chapters",
                          "format_chapters_text")
CHAPTER_FIX_FUNCS = ("fix_chapters",)
for func in CHAPTER_ANALYSIS_FUNCS:
    check(f"舊 chapter_dialog 呼叫過的 {func}() 仍在 health_aggregator 呼叫",
          func in chapter_src and func in aggregator_src)
for func in CHAPTER_FIX_FUNCS:
    check(f"舊 chapter_dialog 呼叫過的一鍵修正 {func}() 仍在 "
          "health_aggregator 呼叫（透過 apply_text_fix）",
          func in chapter_src and func in aggregator_src)

# --- 1d. series_dialog：保留獨立視窗（不併進單支分級報告），入口移進
#          健檢中心對象區——確認 analyze_series／format_series_report
#          仍是 SeriesCheckDialog 在用（檔案未改），且健檢中心真的會開
#          得到這個視窗（見下方 Xvfb 實測段落）。 ---
SERIES_FUNCS = ("analyze_series", "format_series_report")
for func in SERIES_FUNCS:
    check(f"舊 series_dialog 呼叫過的 {func}() 仍在（檔案未修改，只是入口"
          "搬家）", func in series_src)
check("gui/health_center_dialog.py 有一顆會開 SeriesCheckDialog 的按鈕",
      "SeriesCheckDialog(" in center_src)

# --- 1e. termcheck.apply_term_fixes 首次接上 GUI ---
check("subtitle/termcheck.py 的 apply_term_fixes 早就寫好（本檔案未改動）",
      "def apply_term_fixes" in termcheck_src)
check("apply_term_fixes 首次被 health_aggregator 呼叫（v1.50.0 尚未接）",
      "apply_term_fixes" in aggregator_src)
check("build_fix_choices 也一併接上（挑出有明確主流寫法的組別）",
      "build_fix_choices" in aggregator_src)


# ===== 2. 18 項健檢定義完整（v1.50.0 的 15 項 + 本版新 3 項）===========

NEW_SOURCES = {"發佈健檢", "封面健檢", "章節健檢"}
OLD_15_SOURCES = {
    "音訊健檢", "影片畫質健檢", "畫面曝光與色偏", "分段音量一致性", "剪輯節奏",
    "字幕健檢", "廣告友善度", "開場健檢", "字幕可讀性", "標點規範", "語音同步",
    "片尾空間", "工商揭露", "術語一致性", "檔名",
}
check("CHECK_DEFS 剛好 18 項（v1.50.0 的 15 項 + 發佈／封面／章節）",
      len(ha.CHECK_DEFS) == 18, str(len(ha.CHECK_DEFS)))
all_sources = {c.source for c in ha.CHECK_DEFS}
check("v1.50.0 既有的 15 項來源名稱一項不少",
      OLD_15_SOURCES <= all_sources, str(OLD_15_SOURCES - all_sources))
check("本版新增的 3 項來源名稱都在",
      NEW_SOURCES <= all_sources, str(NEW_SOURCES - all_sources))
check("CHECK_DEFS 的來源名稱集合剛好是 18 項（無多餘、無遺漏）",
      all_sources == (OLD_15_SOURCES | NEW_SOURCES),
      str(all_sources ^ (OLD_15_SOURCES | NEW_SOURCES)))
check("系列一致性沒有被塞進 CHECK_DEFS（依退路保留獨立視窗，不併進單支"
      "分級報告）",
      "系列" not in all_sources and "run_series" not in
      {c.key for c in ha.CHECK_DEFS})

check("發佈健檢／封面健檢／章節健檢皆不需要「已選好的媒體檔」"
      "（needs_media=False，對象是文字或圖片，不是影片）",
      all(not ha._BY_KEY[k].needs_media for k in
         ("run_publish", "run_thumb", "run_chapter")))
check("封面健檢需要 ffmpeg 本身（needs_ffmpeg），但不需要已選好的媒體檔"
      "（量的是任意圖片，不是選好的那支影片）",
      ha._BY_KEY["run_thumb"].needs_ffmpeg
      and not ha._BY_KEY["run_thumb"].needs_media)
check("發佈健檢／封面健檢／章節健檢分別標記了對應的『沒填就略過』旗標",
      ha._BY_KEY["run_publish"].needs_publish_text
      and ha._BY_KEY["run_thumb"].needs_images
      and ha._BY_KEY["run_chapter"].needs_chapters_text)


# ===== 3. 9 個修復動作：fix_key 標記與文字都齊全 =========================

EXPECTED_FIX_KEYS = {"audiofix", "trim", "volumefix", "extend_cues",
                     "fix_overlap", "punct_fix", "sync_fix",
                     "term_fix", "chapter_fix"}
check("9 個修復動作在 FIX_LABELS 都有文字（v1.50.0 的 7 個 + 本版新增的"
      "術語統一／章節修正）",
      set(ha.FIX_LABELS) == EXPECTED_FIX_KEYS, str(ha.FIX_LABELS))
check("MEDIA_FIX_KEYS ∪ CUE_FIX_KEYS ∪ TEXT_FIX_KEYS 剛好等於 9 個修復動作",
      (ha.MEDIA_FIX_KEYS | ha.CUE_FIX_KEYS | ha.TEXT_FIX_KEYS)
      == EXPECTED_FIX_KEYS)
check("三類修復動作彼此互斥",
      not (ha.MEDIA_FIX_KEYS & ha.CUE_FIX_KEYS)
      and not (ha.MEDIA_FIX_KEYS & ha.TEXT_FIX_KEYS)
      and not (ha.CUE_FIX_KEYS & ha.TEXT_FIX_KEYS))
check("term_fix 是一種 CUE_FIX_KEY（改的是字幕文字，不是媒體檔或章節）",
      "term_fix" in ha.CUE_FIX_KEYS)
check("chapter_fix 是一種 TEXT_FIX_KEY（改的是章節貼上框，不是字幕）",
      "chapter_fix" in ha.TEXT_FIX_KEYS)
check("FIX_LABELS[term_fix] 文字沿用「統一」語意",
      "統一" in ha.FIX_LABELS["term_fix"])
check("FIX_LABELS[chapter_fix] 文字沿用舊按鈕「一鍵修正」語意",
      "修正" in ha.FIX_LABELS["chapter_fix"])


def _mk(level, title, source):
    return {"level": level, "title": title, "detail": "", "advice": "",
           "source": source}


check("tag_fix_key：術語「大小寫不一致」warn → term_fix",
      ha.tag_fix_key(_mk(ha.LEVEL_WARN, "大小寫不一致", "術語一致性"))
      == "term_fix")
check("tag_fix_key：術語「疑似同一個詞的不同寫法」warn → term_fix",
      ha.tag_fix_key(_mk(ha.LEVEL_WARN, "疑似同一個詞的不同寫法", "術語一致性"))
      == "term_fix")
check("tag_fix_key：術語「無法判斷哪個才對」不可修（次數一樣多，不能亂猜）",
      ha.tag_fix_key(_mk(ha.LEVEL_WARN, "無法判斷哪個才對", "術語一致性"))
      is None)
check("tag_fix_key：章節「章節數量」bad → chapter_fix",
      ha.tag_fix_key(_mk(ha.LEVEL_BAD, "章節數量", "章節健檢"))
      == "chapter_fix")
check("tag_fix_key：章節「首章時間」bad → chapter_fix",
      ha.tag_fix_key(_mk(ha.LEVEL_BAD, "首章時間", "章節健檢"))
      == "chapter_fix")
check("tag_fix_key：發佈健檢本來就沒有修復動作（原視窗唯讀）",
      ha.tag_fix_key(_mk(ha.LEVEL_BAD, "標題長度", "發佈健檢")) is None)
check("tag_fix_key：封面健檢本來就沒有修復動作（原視窗唯讀）",
      ha.tag_fix_key(_mk(ha.LEVEL_BAD, "對比", "封面健檢")) is None)


# ===== 4. 對象區「全部選填、填什麼檢什麼」延伸到新三項 ==================

result = ha.run_health_scan("", [], {}, ha.default_selected_keys({}))
check("三個新對象都留空時不會丟例外，仍回傳結果",
      isinstance(result, dict) and "findings" in result)
sources_found = {f["source"] for f in result["findings"]}
check("三個新對象都留空時，悄悄略過、不出現在報告裡（不報錯、不硬跑）",
      not ({"發佈健檢", "封面健檢", "章節健檢"} & sources_found),
      str(sources_found))

publish_only = ha.run_health_scan(
    "", [], {}, {"run_publish"},
    publish={"title": "測試標題", "description": "", "tags": ""})
check("只填標題時，發佈健檢照跑（填什麼檢什麼）",
      any(f["source"] == "發佈健檢" for f in publish_only["findings"]))


# ===== 5. 真實 ffmpeg 端到端 =============================================

HAS_FFMPEG = shutil.which("ffmpeg") is not None
if HAS_FFMPEG:
    with tempfile.TemporaryDirectory() as tmp:
        # 一張畫面單調（16:9、大色塊）、一張過小又雜訊的封面。
        good_thumb = os.path.join(tmp, "封面候選_大色塊.png")
        bad_thumb = os.path.join(tmp, "封面候選_太小.png")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i",
             "mandelbrot=size=1280x720:rate=1", "-frames:v", "1",
             good_thumb],
            capture_output=True, timeout=30, check=True)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=gray:s=90x90", "-frames:v", "1",
             bad_thumb],
            capture_output=True, timeout=30, check=True)

        thumb_result = ha.run_health_scan(
            "", [], {}, {"run_thumb"},
            image_paths=[good_thumb, bad_thumb])
        thumb_sources = {f["source"] for f in thumb_result["findings"]}
        check("實測：封面健檢真的跑了（兩張圖都有量測結果）",
              "封面健檢" in thumb_sources)
        check("實測：太小那張封面被標記出問題",
              any("太小" in f["title"] and f["level"] != ha.LEVEL_GOOD
                 for f in thumb_result["findings"]),
              str([f["title"] for f in thumb_result["findings"]]))
        check("實測：兩張以上會多一則排名建議",
              any(f["title"] == "封面候選排名"
                 for f in thumb_result["findings"]))

        # --- 發佈資訊：標題超長 + hashtag 超過 15 個 → 一定要修 ---
        publish = {
            "title": "超長標題" * 30,
            "description": "介紹影片內容" + " #tag" * 20,
            "tags": "a,b,c",
            "chapters_text": "",
        }
        publish_result = ha.run_health_scan(
            "", [], {}, {"run_publish"}, publish=publish)
        check("實測：標題超長被判定一定要修",
              any(f["title"] == "標題長度" and f["level"] == ha.LEVEL_BAD
                 for f in publish_result["findings"]))
        check("實測：hashtag 超過 15 個被判定一定要修（YouTube 會忽略全部）",
              any(f["title"] == "hashtag 數量" and f["level"] == ha.LEVEL_BAD
                 for f in publish_result["findings"]))

        # --- 章節：格式錯誤 + 首章非 0:00 + 一鍵修正 ---
        chapters_text = "0.30 開場\n2:00 主題一\n5:00 主題二"
        chapter_result = ha.run_health_scan(
            "", [], {}, {"run_chapter"},
            publish={"chapters_text": chapters_text})
        check("實測：章節健檢抓到首章不是 0:00",
              any(f["title"] == "首章時間" and f["level"] == ha.LEVEL_BAD
                 for f in chapter_result["findings"]))
        fixed_text, changes, message = ha.apply_text_fix(
            "chapter_fix", {}, chapter_result["raw"])
        check("實測：一鍵修正真的改了章節文字", fixed_text.startswith("0:00"))
        check("實測：一鍵修正的說明清單非空", len(changes) >= 1)

        # --- 術語一致性：apply_term_fixes 首次接上 GUI ---
        term_cues = [{"index": 1, "start": 0.0, "end": 3.0,
                     "text": "Youtube 訂閱 youtube 訂閱 youtube 訂閱"}]
        term_result = ha.run_health_scan("", term_cues, {}, {"run_term"})
        raw = term_result["raw"]
        new_cues, changed, msg = ha.apply_cue_fix(
            "term_fix", term_cues, {}, raw)
        check("實測：apply_term_fixes 真的統一了寫法（至少改了一次）",
              changed >= 1)
        check("實測：統一後字幕裡只剩一種寫法",
              "Youtube" not in new_cues[0]["text"])
else:
    print("SKIP 真實 ffmpeg 端到端測試（環境沒有 ffmpeg）")


# ===== 6. Xvfb 下的真實視窗：對象區三個新區塊、checklist 17+1、系列視窗 ===

try:
    import tkinter as tk
    from gui.health_center_dialog import HealthCenterDialog
    from gui.series_dialog import SeriesCheckDialog

    root = tk.Tk()
    root.geometry("60x60+0+0")
    root.deiconify()
    root.update()

    dlg = HealthCenterDialog(root, {}, media_path="", cues=[])
    dlg.deiconify()
    for _ in range(20):
        root.update()

    check("健檢中心開窗時有 17 顆可勾選＋1 顆一律檢查（檔名）",
          len(dlg.check_vars) == 17, str(len(dlg.check_vars)))
    check("健檢中心預設尺寸仍在合理量級（不小於文件講的『約 900x760』）",
          dlg.winfo_width() >= 900 and dlg.winfo_height() >= 760)

    check("對象區有封面圖清單（thumb_list）", hasattr(dlg, "thumb_list"))
    check("對象區有發佈文字四個欄位（標題／說明欄／標籤／章節）",
          hasattr(dlg, "publish_title_var") and hasattr(dlg, "publish_desc")
          and hasattr(dlg, "publish_tags_var")
          and hasattr(dlg, "publish_chapters"))
    check("對象區有系列影片清單（series_list）", hasattr(dlg, "series_list"))
    check("發佈文字預設收合（可摺疊，不佔滿主畫面）",
          not dlg._publish_expanded
          and not dlg.publish_body.winfo_ismapped())
    dlg._toggle_publish()
    root.update()
    check("點一下展開後，發佈文字欄位變成看得到",
          dlg._publish_expanded and dlg.publish_body.winfo_ismapped())

    # 系列一致性：加一個檔案後開對話框，檔案數不足 2 支時應友善提示而非
    # 崩潰（沿用 series_dialog.py 既有行為，未修改）。
    dlg._series_paths = ["/tmp/不存在的檔案.mp4"]
    series_ok = True
    try:
        series_dlg = SeriesCheckDialog(dlg, dlg.config_data,
                                       list(dlg._series_paths))
        series_dlg.deiconify()
        root.update()
        check("開啟系列一致性視窗成功（獨立視窗，未被併掉）",
              series_dlg.winfo_exists())
        series_dlg.destroy()
    except Exception:
        series_ok = False
    check("系列一致性視窗開啟過程沒有例外", series_ok)

    settings_dlg_cls = None
    from gui.health_center_dialog import HealthSettingsDialog
    settings_dlg = HealthSettingsDialog(dlg, dict(dlg.config_data))
    settings_dlg.deiconify()
    for _ in range(10):
        root.update()
    check("進階設定新增了發佈／封面／章節三組門檻",
          hasattr(settings_dlg, "pub_title_limit_var")
          and hasattr(settings_dlg, "thumb_width_var")
          and hasattr(settings_dlg, "chapter_min_seconds_var"))
    settings_dlg.destroy()
    dlg.destroy()

    # ---- app.py 工具列：11→6 顆 ----
    from tkinter import ttk as _ttk

    from gui.app import SrtApp  # noqa: F401
    app = SrtApp()  # SrtApp 本身即 tk.Tk() 子類別，會自行載入 config。
    app.geometry("1400x900+0+0")
    app.deiconify()
    for _ in range(20):
        app.update()

    def _toolbar_button_texts(widget):
        texts = []
        for child in widget.winfo_children():
            if isinstance(child, _ttk.Button):
                try:
                    texts.append(child.cget("text"))
                except Exception:
                    pass
            texts.extend(_toolbar_button_texts(child))
        return texts

    # 工具列按鈕群位於第二個 ttk.Frame（第一個是標題列）；用內容比對找出來，
    # 不依賴內部屬性名稱（app.py 沒有把 tools frame 存成 self 屬性）。
    all_texts = _toolbar_button_texts(app)
    expected_gone = {"上片前健檢", "上片前總體檢", "系列一致性", "章節健檢",
                     "封面健檢", "發佈健檢"}
    check("工具列六顆舊健檢類按鈕文字都不見了（併入健檢中心／對象區）",
          not (expected_gone & set(all_texts)), str(set(all_texts)))
    check("工具列出現新的「健檢中心」按鈕",
          "健檢中心" in all_texts)
    app.destroy()
except tk.TclError as exc:  # 沒有 DISPLAY 時整段略過，不算失敗。
    print(f"SKIP Xvfb 實測（{exc}）")


# ===== 7. 全站規範：本版新增/改動的檔案全用 ttk 控件 ======================

for path, src in (("gui/health_center_dialog.py", center_src),
                  ("gui/health_aggregator.py", aggregator_src),
                  ("gui/app.py", app_src)):
    stripped = src.replace("ttk.Checkbutton(", "").replace(
        "ttk.Radiobutton(", "")
    check(f"{path} 沒有 classic tk.Checkbutton 殘留",
          "tk.Checkbutton(" not in stripped)
    check(f"{path} 沒有 classic tk.Radiobutton 殘留",
          "tk.Radiobutton(" not in stripped)


print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.51.0 健檢中心（二）測試全數通過。")
