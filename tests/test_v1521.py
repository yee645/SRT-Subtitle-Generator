# -*- coding: utf-8 -*-
"""
v1.52.1 第二輪測試：拆「一鍵完成」、併三個輸出面、首次啟動速覽。

版面／控件那一面由 `tests/test_v1520.py` 守（它握有與 v1.51.0 的動態對
照）；這一份專測本輪新增的**邏輯**：

1. `subtitle.pipeline.describe_output_plan` —— 階段④那句「這次會輸出什
   麼」。它必須與同檔的 `export_and_burn` 說同一件事，所以這裡不只驗字
   串長相，還實際跑一次 `export_and_burn`，比對它產出的檔案是否正好就
   是那句話講的。這是本檔案的重點：說明與行為對不上，比說明難看嚴重。
2. `gui.whatsnew_dialog.should_show` —— 速覽該不該跳的規則。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


# ===== 1. describe_output_plan：文字長相 =============================
from subtitle.pipeline import describe_output_plan, export_and_burn

plan = describe_output_plan({"automation": {}})
check("什麼都沒勾時明講「尚未勾選」，不是印一句空的輸出計畫",
      "尚未勾選" in plan, plan)

plan = describe_output_plan({"automation": {"export_srt": True}})
check("只勾 SRT：說明提到 SRT 且提到輸出位置",
      "SRT" in plan and "→" in plan, plan)

plan = describe_output_plan(
    {"automation": {"export_srt": True, "export_ass": True}})
check("勾兩種格式時兩種都列出來", "SRT" in plan and "ASS" in plan, plan)

plan = describe_output_plan({"automation": {"burn_video": True}})
check("只勾燒錄時說明講燒錄、不會憑空多出匯出",
      "燒錄" in plan and "匯出" not in plan, plan)

plan = describe_output_plan(
    {"automation": {"burn_video": True, "loudnorm": True,
                    "loudnorm_target": -14.0}})
check("勾了響度正規化時說明帶出目標 LUFS（使用者按之前就知道會被改音量）",
      "響度正規化" in plan and "-14.0" in plan and "LUFS" in plan, plan)

plan = describe_output_plan(
    {"automation": {"export_srt": True, "output_dir": "D:/成品"}})
check("有指定輸出資料夾時說明直接寫出那個資料夾", "D:/成品" in plan, plan)

plan = describe_output_plan({"automation": {"export_srt": True}})
check("沒指定資料夾、也沒給來源檔時說「來源檔所在資料夾」",
      "來源檔所在資料夾" in plan, plan)

with tempfile.TemporaryDirectory() as tmp:
    media = os.path.join(tmp, "影片.mp4")
    open(media, "wb").write(b"x")
    plan = describe_output_plan({"automation": {"export_srt": True}}, media)
    check("給了來源檔時輸出位置解析成實際路徑（與 resolve_output_dir 同規則）",
          os.path.normpath(tmp) in os.path.normpath(plan), plan)


# ===== 2. 說明與實際行為必須一致（本檔案的重點）=======================
# 只驗不需要 ffmpeg 的匯出路徑；燒錄那一半由 tests/test_v150.py 以替身驗。
CUES = [{"start": 0.0, "end": 1.5, "text": "第一句"},
        {"start": 1.6, "end": 3.0, "text": "第二句"}]

for label, autom, expect_exts in [
    ("只勾 SRT", {"export_srt": True}, {".srt"}),
    ("勾 SRT+VTT", {"export_srt": True, "export_vtt": True}, {".srt", ".vtt"}),
    ("勾 TXT", {"export_txt": True}, {".txt"}),
]:
    with tempfile.TemporaryDirectory() as tmp:
        media = os.path.join(tmp, "素材.mp4")
        open(media, "wb").write(b"x")
        cfg = {"automation": dict(autom), "subtitle_style": {}}
        said = describe_output_plan(cfg, media)
        exports, burned = export_and_burn(CUES, media, cfg)
        got_exts = {os.path.splitext(p)[1] for p in exports}
        check(f"{label}：export_and_burn 實際產出的格式 == 說明講的格式",
              got_exts == expect_exts, f"說明={said!r} 實際={sorted(got_exts)}")
        for path in exports:
            check(f"{label}：{os.path.basename(path)} 真的被寫出來了",
                  os.path.exists(path) and os.path.getsize(path) > 0)
        check(f"{label}：沒勾燒錄就不該有燒錄產物", burned is None, str(burned))
        check(f"{label}：輸出落在說明講的那個資料夾",
              all(os.path.dirname(p) == tmp for p in exports), str(exports))

# 說明說「尚未勾選」時，export_and_burn 也確實什麼都不做——這一對必須同時成立，
# 否則介面會出現「說沒東西可輸出、卻默默寫了檔」或反過來的矛盾。
with tempfile.TemporaryDirectory() as tmp:
    media = os.path.join(tmp, "素材.mp4")
    open(media, "wb").write(b"x")
    cfg = {"automation": {}, "subtitle_style": {}}
    exports, burned = export_and_burn(CUES, media, cfg)
    check("說明說「尚未勾選」時，實際也真的一個檔都沒產生",
          not exports and burned is None
          and "尚未勾選" in describe_output_plan(cfg, media),
          str(exports))


# ===== 3. 速覽該不該跳 ===============================================
try:
    from gui.whatsnew_dialog import (MOVED, NEVER_SHOW, RENAMED, SPLIT_TEXT,
                                     should_show)
except ImportError as exc:  # 沒有 tkinter 的環境
    print(f"SKIP 速覽規則測試（無 tkinter：{exc}）")
else:
    check("全新使用者（設定檔沒這個欄位）會看到速覽", should_show({}, "1.52.1"))
    check("看過這一版就不再跳", not should_show({"whatsnew_seen": "1.52.1"}, "1.52.1"))
    check("看過舊版、但這一版又大改介面時會再跳一次",
          should_show({"whatsnew_seen": "1.52.0"}, "1.52.1"))
    check("勾過「不再顯示」之後，任何版本都不跳",
          not should_show({"whatsnew_seen": NEVER_SHOW}, "1.99.0"))
    check("欄位被寫成空字串（或只有空白）等同沒看過",
          should_show({"whatsnew_seen": "   "}, "1.52.1"))

    # 對照表內容：這張表是給老用戶「我的功能呢」用的，缺項就失去意義。
    moved_targets = " ".join(new for _old, new in MOVED)
    for stage in ("① 素材與剪輯", "③ 健檢中心", "④ 輸出與發佈"):
        check(f"對照表有指向「{stage}」的條目", stage in moved_targets, moved_targets)
    check("D-1 改名的兩顆按鈕都列進對照表",
          {old for old, _new, _why in RENAMED}
          == {"自動跳剪停頓", "重複片段偵測"}, str(RENAMED))
    check("拆按鈕那段有把三個新入口都講出來",
          all(t in SPLIT_TEXT for t in
              ("開始生成字幕", "完成輸出（依輸出設定）", "批次一鍵完成")),
          SPLIT_TEXT)
    check("拆按鈕那段有講清楚「為什麼要拆」（校對機會），不是只說改了什麼",
          "校對" in SPLIT_TEXT, SPLIT_TEXT)


print()
if failures:
    print(f"失敗 {len(failures)} 項：" + ", ".join(failures))
    sys.exit(1)
print("v1.52.1 第二輪（拆一鍵完成／併輸出面／首次速覽）測試全數通過。")
