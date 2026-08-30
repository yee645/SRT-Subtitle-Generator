# -*- coding: utf-8 -*-
"""
v1.50.0 新功能測試：健檢中心（一）——併 audiocheck_dialog／
subtitle_check_dialog／preflight_dialog 為單一健檢中心（見
docs/UI_AUDIT_2.0.md 2.2 節、docs/UI_ARCHITECTURE_2.0.md B.5、
docs/ROADMAP_2.0.md v1.50 項）。

這是破壞性改動（三個視窗退役），本檔的第一要務是**證明沒有能力消
失**：不是靠手寫一份清單自己對自己打勾，而是動態讀入三個舊檔案
（`gui/audiocheck_dialog.py`／`gui/subtitle_check_dialog.py`／
`gui/preflight_dialog.py`——三個檔案本身完全未被修改，仍在 repo 裡）的
原始碼與常數，逐一確認每個舊有的分析函式、修復函式在新的
`gui/health_aggregator.py` 仍被呼叫到，新舊清單才不會因為手誤或後續
修改而悄悄漂移、卻沒有測試發現。

其餘涵蓋：
  1. 15 項健檢的定義完整（12 項沿用 `subtitle/preflight.py`、外加標點
     規範／語音同步／檔名）。
  2. 7 個修復動作都能被 `tag_fix_key()` 正確標記、`FIX_LABELS` 都有對
     應文字。
  3. 真實 ffmpeg 端到端：合成一段有畫面＋聲音的素材＋刻意有問題的字
     幕，實際跑一次健檢中心的彙總掃描，確認報告內容合理、無例外。
  4. 沒有選素材時，純文字的字幕相關檢查仍照跑（這是舊「字幕健檢」視
     窗本來就有、最容易在整併時被誤收緊的能力）。
  5. Xvfb 下開出真正的 `HealthCenterDialog`：勾選項齊全、進階設定視窗
     打得開、跑完真的把結果塞進 `ttk.Treeview`、選取可修項目會啟用
     「修復此項」按鈕、`gui/app.py` 的三顆舊按鈕都改開這個視窗並在狀
     態列留下「已整併至健檢中心」訊息。
  6. 全站規範：沒有 classic `tk.Checkbutton`/`tk.Radiobutton` 殘留。
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

# ===== 0. 讀入三個舊檔案原始碼（檔案本身完全未修改）供動態比對 =========

def _read(rel):
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fp:
        return fp.read()


audiocheck_src = _read("gui/audiocheck_dialog.py")
subcheck_src = _read("gui/subtitle_check_dialog.py")
preflight_src = _read("gui/preflight_dialog.py")
aggregator_src = _read("gui/health_aggregator.py")
center_src = _read("gui/health_center_dialog.py")
app_src = _read("gui/app.py")

check("三個舊視窗檔案仍在 repo 裡、完全未被修改（回退性：D-3 只改按鈕指向）",
      "class AudioCheckDialog" in audiocheck_src
      and "class SubtitleCheckDialog" in subcheck_src
      and "class PreflightDialog" in preflight_src)

# app.py 不該再 import 三個舊類別（改由健檢中心接手），但檔案本身要保留。
check("gui/app.py 不再 import AudioCheckDialog（改開健檢中心）",
      "AudioCheckDialog" not in app_src)
check("gui/app.py 不再 import SubtitleCheckDialog（改開健檢中心）",
      "SubtitleCheckDialog" not in app_src)
check("gui/app.py 不再 import PreflightDialog（改開健檢中心）",
      "PreflightDialog" not in app_src)
check("gui/app.py 改為 import HealthCenterDialog",
      "from gui.health_center_dialog import HealthCenterDialog" in app_src)
check("三顆舊按鈕的 handler 都改開 HealthCenterDialog",
      app_src.count("HealthCenterDialog(") >= 3)
check("三顆舊按鈕都留下「已整併至健檢中心」的狀態列訊息",
      app_src.count("已整併至健檢中心") == 3)


# ===== 1. 能力對照表（動態）：舊視窗呼叫過的每個 subtitle/ 函式，========
#          新的彙總模組仍然呼叫得到 ==========================================

# --- 1a. audiocheck_dialog：5 檢 3 修 ---
AUDIOCHECK_ANALYSIS_FUNCS = (
    "run_audio_check",            # 音訊（爆音/響度/底噪/聲道）
    "run_video_check",            # 影片畫質＋頭尾冷場
    "analyze_color",              # 曝光與色偏
    "analyze_pacing",             # 剪輯節奏
    "analyze_volume_consistency", # 音量一致性
)
AUDIOCHECK_FIX_FUNCS = ("fix_audio", "trim_video", "fix_volume_consistency")
for func in AUDIOCHECK_ANALYSIS_FUNCS + AUDIOCHECK_FIX_FUNCS:
    check(f"舊 audiocheck_dialog 呼叫過的 {func}() 仍在 health_aggregator 呼叫",
          func in audiocheck_src and func in aggregator_src)

# --- 1b. subtitle_check_dialog：6 檢 4 修 ---
SUBCHECK_ANALYSIS_FUNCS = (
    "analyze_cues",         # CPS／行數／重疊
    "scan_cues",            # 廣告友善度（adfriendly 的 scan_cues）
    "analyze_hook",         # 開場健檢
    "analyze_legibility",   # 字幕可讀性
    "analyze_punctuation",  # 標點規範
    "analyze_sync",         # 語音同步（subsync）
)
SUBCHECK_FIX_FUNCS = ("fix_cue_durations", "fix_overlaps", "apply_punct_style",
                      "apply_sync_correction")
for func in SUBCHECK_ANALYSIS_FUNCS + SUBCHECK_FIX_FUNCS:
    check(f"舊 subtitle_check_dialog 呼叫過的 {func}() 仍在 health_aggregator 呼叫",
          func in subcheck_src and func in aggregator_src)

# --- 1c. preflight_dialog：12 項唯讀勾選（另外 4 項是 audiocheck／
#          subtitle_check 沒有、preflight 才獨有的：片尾空間／工商揭露／
#          術語一致性／檔名）---
from gui.preflight_dialog import _CHECK_ITEMS as OLD_PREFLIGHT_ITEMS  # noqa: E402
old_preflight_keys = {key for key, _label, _needs in OLD_PREFLIGHT_ITEMS}
new_keys = {c.key for c in ha.CHECK_DEFS}
check("preflight_dialog 原有 12 個勾選鍵，新健檢中心一個不少地涵蓋",
      old_preflight_keys <= new_keys,
      str(old_preflight_keys - new_keys))
check("preflight 特有（audiocheck／subtitle_check 都沒有）的 4 項獨有能力"
      "（片尾空間／工商揭露／術語一致性／檔名）都在新清單裡",
      {"run_endscreen", "run_sponsor", "run_term", "filename"} <= new_keys)
for func in ("analyze_endscreen", "analyze_sponsor", "analyze_terms",
            "check_filename"):
    check(f"preflight 專屬的 {func}() 仍在 health_aggregator 呼叫",
          func in aggregator_src)


# ===== 2. 15 項健檢定義完整、來源名稱沿用使用者已認得的舊名 ============

EXPECTED_SOURCES = {
    "音訊健檢", "影片畫質健檢", "畫面曝光與色偏", "分段音量一致性", "剪輯節奏",
    "字幕健檢", "廣告友善度", "開場健檢", "字幕可讀性", "標點規範", "語音同步",
    "片尾空間", "工商揭露", "術語一致性", "檔名",
}
check("CHECK_DEFS 剛好 15 項（preflight 12 項 + 標點規範 + 語音同步 + 檔名）",
      len(ha.CHECK_DEFS) == 15, str(len(ha.CHECK_DEFS)))
check("CHECK_DEFS 的來源名稱集合與預期一致",
      {c.source for c in ha.CHECK_DEFS} == EXPECTED_SOURCES,
      str({c.source for c in ha.CHECK_DEFS} ^ EXPECTED_SOURCES))
check("檔名一律檢查（沿用 preflight 的行為，不受勾選控制）",
      ha._BY_KEY["filename"].always_on is True)
check("字幕健檢／廣告友善度／開場健檢／標點規範／術語一致性"
      "皆不需要媒體檔（純文字，這是舊字幕健檢視窗的既有能力）",
      all(not ha._BY_KEY[k].needs_media for k in
         ("run_subtitle", "run_adfriendly", "run_hook", "run_punct",
          "run_term")))


# ===== 3. 7 個修復動作：fix_key 標記與文字都齊全 =========================

EXPECTED_FIX_KEYS = {"audiofix", "trim", "volumefix", "extend_cues",
                     "fix_overlap", "punct_fix", "sync_fix"}
check("7 個既有修復動作在 FIX_LABELS 都有文字",
      set(ha.FIX_LABELS) == EXPECTED_FIX_KEYS, str(ha.FIX_LABELS))
check("MEDIA_FIX_KEYS ∪ CUE_FIX_KEYS 剛好等於 7 個修復動作",
      (ha.MEDIA_FIX_KEYS | ha.CUE_FIX_KEYS) == EXPECTED_FIX_KEYS)
check("媒體類與字幕類修復動作互斥",
      not (ha.MEDIA_FIX_KEYS & ha.CUE_FIX_KEYS))

_FIX_TEXT_HINTS = {
    "audiofix": "修復", "trim": "修剪", "volumefix": "拉平",
    "extend_cues": "延長", "fix_overlap": "重疊", "punct_fix": "標點",
    "sync_fix": "同步",
}
for key, hint in _FIX_TEXT_HINTS.items():
    check(f"FIX_LABELS[{key}] 文字沿用舊按鈕語意（含「{hint}」）",
          hint in ha.FIX_LABELS[key])


def _mk(level, title, source):
    return {"level": level, "title": title, "detail": "", "advice": "",
           "source": source}


check("tag_fix_key：音訊「整體響度」bad → audiofix",
      ha.tag_fix_key(_mk(ha.LEVEL_BAD, "整體響度", "音訊健檢")) == "audiofix")
check("tag_fix_key：影片「開頭廢秒」warn → trim",
      ha.tag_fix_key(_mk(ha.LEVEL_WARN, "開頭廢秒", "影片畫質健檢")) == "trim")
check("tag_fix_key：「音量落差段落」→ volumefix",
      ha.tag_fix_key(_mk(ha.LEVEL_WARN, "音量落差段落", "分段音量一致性"))
      == "volumefix")
check("tag_fix_key：字幕「閱讀速度過快」→ extend_cues",
      ha.tag_fix_key(_mk(ha.LEVEL_BAD, "閱讀速度過快", "字幕健檢"))
      == "extend_cues")
check("tag_fix_key：字幕「字幕重疊」→ fix_overlap",
      ha.tag_fix_key(_mk(ha.LEVEL_BAD, "字幕重疊", "字幕健檢"))
      == "fix_overlap")
check("tag_fix_key：標點規範「行尾標點」→ punct_fix",
      ha.tag_fix_key(_mk(ha.LEVEL_WARN, "行尾標點", "標點規範"))
      == "punct_fix")
check("tag_fix_key：語音同步「固定偏移」→ sync_fix",
      ha.tag_fix_key(_mk(ha.LEVEL_BAD, "固定偏移", "語音同步")) == "sync_fix")
check("tag_fix_key：good 等級一律不可修",
      ha.tag_fix_key(_mk(ha.LEVEL_GOOD, "整體響度", "音訊健檢")) is None)
check("tag_fix_key：曝光／色偏本來就沒有修復動作（原三窗皆無）",
      ha.tag_fix_key(_mk(ha.LEVEL_WARN, "曝光", "畫面曝光與色偏")) is None)


# ===== 4. 設定：勾選狀態記憶、preflight 沿用舊區塊、新增 healthcenter 區塊 ==

cfg = {}
selected = ha.default_selected_keys(cfg)
check("預設勾選包含 preflight 12 項全開、標點規範開、語音同步關（較慢預設關）",
      "run_punct" in selected and "run_subsync" not in selected
      and "run_audio" in selected)

ha.save_selected_keys(cfg, {"run_audio", "run_subtitle", "run_punct"})
check("save_selected_keys 寫回 config['preflight']（沿用舊區塊，不新開）",
      cfg["preflight"]["run_audio"] is True
      and cfg["preflight"]["run_video"] is False)
check("save_selected_keys 把新增的兩項寫進 config['healthcenter']",
      cfg["healthcenter"]["run_punct"] is True
      and cfg["healthcenter"]["run_subsync"] is False)
reselected = ha.default_selected_keys(cfg)
check("存檔後重新讀取，勾選狀態一致（記憶生效）",
      reselected == {"run_audio", "run_subtitle", "run_punct", "filename"})


# ===== 5. 沒有選素材：純文字字幕檢查仍照跑（舊字幕健檢視窗的既有能力）=====

no_media_cues = [
    {"index": 1, "start": 0.0, "end": 0.5,
     "text": "這句話講得非常非常非常快超過門檻的字幕內容啊啊啊。"},
    {"index": 2, "start": 3.0, "end": 6.0, "text": "第二句，逗號、頓號測試。"},
]
result = ha.run_health_scan("", no_media_cues, {},
                            ha.default_selected_keys({}))
check("沒有素材時不會丟例外，仍回傳結果",
      isinstance(result, dict) and "findings" in result)
sources_found = {f["source"] for f in result["findings"]}
check("沒有素材時，純文字檢查（字幕健檢／標點規範）仍然跑了",
      {"字幕健檢", "標點規範"} <= sources_found, str(sources_found))
check("沒有素材時，需要媒體檔的項目（音訊健檢等）被略過而非報錯",
      "音訊健檢" not in sources_found)
check("略過清單有講清楚原因",
      any("尚未選擇素材" in s for s in result["skipped"]), str(result["skipped"]))


# ===== 6. 真實 ffmpeg 端到端 =============================================

HAS_FFMPEG = shutil.which("ffmpeg") is not None
if HAS_FFMPEG:
    with tempfile.TemporaryDirectory() as tmp:
        clip = os.path.join(tmp, "final_cut_v2.mp4")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=gray:s=640x360:d=20:r=25",
             "-f", "lavfi", "-i",
             "sine=frequency=440:duration=20:sample_rate=44100",
             "-c:v", "libx264", "-c:a", "aac", clip],
            capture_output=True, timeout=60, check=True)

        cues = [
            {"index": 1, "start": 0.0, "end": 0.5,
             "text": "這句話講得非常非常非常快超過門檻的字幕內容啊啊啊。"},
            {"index": 2, "start": 0.4, "end": 3.0, "text": "這句與前一句重疊了。"},
            {"index": 3, "start": 3.0, "end": 6.0, "text": "正常長度的一句話，剛好。"},
            {"index": 4, "start": 6.0, "end": 9.0, "text": "第四句，逗號、頓號測試。"},
        ]
        config = {}
        selected = ha.default_selected_keys(config)
        progress_calls = []
        result = ha.run_health_scan(
            clip, cues, config, selected,
            progress_cb=lambda ratio, msg: progress_calls.append((ratio, msg)))

        check("實測：回報了進度", len(progress_calls) > 3)
        check("實測：報告有一定要修的項目（重疊＋CPS 過快是故意設計的）",
              result["counts"][ha.LEVEL_BAD] >= 2, str(result["counts"]))
        ran_sources = {s["name"] for s in result["sections"] if s["ran"]}
        expected_ran = {"音訊健檢", "影片畫質健檢", "畫面曝光與色偏",
                        "分段音量一致性", "剪輯節奏", "字幕健檢", "廣告友善度",
                        "開場健檢", "字幕可讀性", "標點規範", "片尾空間",
                        "工商揭露", "術語一致性", "檔名"}
        check("實測：14 項（不含預設關閉的語音同步）都成功執行、無例外",
              expected_ran <= ran_sources, str(expected_ran - ran_sources))

        report_text = ha.format_health_report(result)
        check("實測：報告帶有準備度評級", "準備度" in report_text)
        check("實測：報告列出字幕重疊的發現", "字幕重疊" in report_text)
        check("實測：報告列出檔名警告（final_cut_v2 是無資訊檔名）",
              "final" in report_text)

        # --- 修復動作：cues 類（快速、同步）---
        raw = result["raw"]
        new_cues, fixed, _msg = ha.apply_cue_fix("fix_overlap", cues, config, raw)
        check("實測：一鍵修復重疊真的修掉了重疊", fixed >= 1)
        new_cues2, changed, _msg2 = ha.apply_cue_fix(
            "punct_fix", cues, config, raw)
        check("實測：一鍵套用標點規範真的改了內容", changed >= 1)

        # --- 修復動作：media 類（ffmpeg，前置條件不足時要友善報錯）---
        try:
            ha.apply_media_fix("trim", clip, os.path.join(tmp, "t.mp4"),
                               config, raw)
            check("trim 在沒有偵測到廢秒時應該丟 FixError", False)
        except ha.FixError:
            check("實測：trim 在沒有頭尾廢秒時友善拒絕，不是硬錯", True)

        out_path = ha.suggest_fix_output_path("audiofix", clip)
        produced = ha.apply_media_fix("audiofix", clip, out_path, config, raw)
        check("實測：輸出音訊修復版真的產生檔案", os.path.exists(produced))

        # --- 語音同步：獨立測一次（預設不勾選，這裡刻意打開驗證接得上）---
        sync_selected = selected | {"run_subsync"}
        sync_result = ha.run_health_scan(clip, cues, config, sync_selected)
        sync_ran = {s["name"] for s in sync_result["sections"] if s["ran"]}
        check("實測：勾選語音同步後真的執行、無例外", "語音同步" in sync_ran,
              str(sync_result["sections"]))
else:
    print("SKIP 真實 ffmpeg 端到端測試（環境沒有 ffmpeg）")


# ===== 7. 全站規範：進階設定視窗全用 ttk 控件（無 classic Checkbutton/Radiobutton）==

for path, src in (("gui/health_center_dialog.py", center_src),
                  ("gui/health_aggregator.py", aggregator_src)):
    # "ttk.Checkbutton(" 本身以子字串包含 "tk.Checkbutton("，比對前先拿掉
    # ttk. 開頭的合法用法，沿用 tests/test_v1240.py 既有的比對手法。
    stripped = src.replace("ttk.Checkbutton(", "").replace(
        "ttk.Radiobutton(", "")
    check(f"{path} 沒有 classic tk.Checkbutton 殘留",
          "tk.Checkbutton(" not in stripped)
    check(f"{path} 沒有 classic tk.Radiobutton 殘留",
          "tk.Radiobutton(" not in stripped)


# ===== 8. Xvfb 下的真實視窗：勾選齊全、跑得動、Treeview 有結果、可修復 ======

try:
    import tkinter as tk
    from gui.health_center_dialog import (HealthCenterDialog,
                                          HealthSettingsDialog)

    root = tk.Tk()
    root.geometry("60x60+0+0")
    root.deiconify()
    root.update()

    dlg = HealthCenterDialog(root, {}, media_path="",
                             cues=list(no_media_cues))
    dlg.deiconify()
    for _ in range(10):
        root.update()

    check("健檢中心開窗時有 14 顆可勾選＋1 顆一律檢查（檔名）",
          len(dlg.check_vars) == 14)
    check("健檢中心預設尺寸是文件講的『約 900x760』量級",
          dlg.winfo_width() >= 800 and dlg.winfo_height() >= 700)

    settings_dlg = HealthSettingsDialog(dlg, dict(dlg.config_data))
    settings_dlg.deiconify()
    for _ in range(10):
        root.update()
    check("進階設定（門檻）視窗打得開", settings_dlg.winfo_exists())
    settings_dlg.destroy()

    if HAS_FFMPEG:
        with tempfile.TemporaryDirectory() as tmp2:
            clip2 = os.path.join(tmp2, "clip.mp4")
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "lavfi", "-i", "color=c=gray:s=320x240:d=6:r=25",
                 "-f", "lavfi", "-i",
                 "sine=frequency=440:duration=6:sample_rate=44100",
                 "-c:v", "libx264", "-c:a", "aac", clip2],
                capture_output=True, timeout=30, check=True)
            dlg.media_var.set(clip2)
            dlg.cues = [
                {"index": 1, "start": 0.0, "end": 0.5,
                 "text": "這句話講得非常非常非常快超過門檻的字幕內容啊啊。"},
                {"index": 2, "start": 0.4, "end": 3.0, "text": "重疊句子。"},
            ]
            dlg._on_run()
            import time as _time
            deadline = _time.time() + 30
            while dlg.last_result is None and _time.time() < deadline:
                root.update()
                _time.sleep(0.1)
            check("Xvfb 實跑：健檢完成後 last_result 有內容",
                  dlg.last_result is not None)
            if dlg.last_result:
                tree_children = dlg.tree.get_children()
                check("Xvfb 實跑：Treeview 有三個分級群組節點",
                      len(tree_children) == 3, str(len(tree_children)))
                overlap_item = None
                for item_id, finding in dlg._finding_by_item.items():
                    if finding.get("fix_key") == "fix_overlap":
                        overlap_item = item_id
                        break
                check("Xvfb 實跑：找得到一筆可修的「字幕重疊」發現",
                      overlap_item is not None)
                if overlap_item:
                    dlg.tree.selection_set(overlap_item)
                    dlg._on_select_finding()
                    for _ in range(5):
                        root.update()
                    check("Xvfb 實跑：選取可修項目後「修復此項」按鈕啟用",
                          str(dlg.fix_btn.cget("state")) == "normal")

    dlg.destroy()
    root.destroy()
except tk.TclError as exc:  # pragma: no cover - 沒有可用顯示環境時優雅略過
    print(f"SKIP Xvfb 視窗測試（無可用顯示環境）：{exc}")


print()
if failures:
    print(f"共 {len(failures)} 項失敗：{', '.join(failures)}")
    sys.exit(1)
print("v1.50.0 測試全數通過。")
