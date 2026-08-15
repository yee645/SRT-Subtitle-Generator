# -*- coding: utf-8 -*-
"""v1.42.0 新功能測試：短片選段規劃（長片自動挑成多支直式短片）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import clipplan as cp
from subtitle.review import TAG_HIGHLIGHT


def seg(start, end, text="說話", score=0.0, highlight=False, kind="speech"):
    return {"kind": kind, "start": start, "end": end, "text": text,
            "score": score, "tags": [TAG_HIGHLIGHT] if highlight else []}


S = cp.resolve_clipplan_settings(None)

# ===== 1. 設定解析與夾限 =====
check("預設輸出 3 支", S["count"] == 3, str(S))
check("預設最短 15 秒", S["min_seconds"] == 15.0)
check("預設最長 60 秒（Shorts 平台安全值）", S["max_seconds"] == 60.0)
over = cp.resolve_clipplan_settings(
    {"clipplan": {"count": 999, "min_seconds": 999, "max_seconds": 999,
                  "pad_seconds": 99, "min_gap_seconds": 999}})
check("支數夾限上界", over["count"] == cp._COUNT_RANGE[1], str(over))
check("最長夾限上界", over["max_seconds"] == cp._MAX_RANGE[1])
check("留白夾限上界", over["pad_seconds"] == cp._PAD_RANGE[1])
under = cp.resolve_clipplan_settings(
    {"clipplan": {"count": 0, "min_seconds": 0, "pad_seconds": -5,
                  "min_gap_seconds": -5}})
check("支數夾限下界", under["count"] == cp._COUNT_RANGE[0])
check("最短夾限下界", under["min_seconds"] == cp._MIN_RANGE[0])
check("留白夾限下界", under["pad_seconds"] == 0.0)
check("間隔夾限下界", under["min_gap_seconds"] == 0.0)
check("支數會轉成整數", isinstance(over["count"], int))
check("無法轉數字時退回預設",
      cp.resolve_clipplan_settings(
          {"clipplan": {"count": "三"}})["count"] == 3)
check("None 不覆蓋預設值",
      cp.resolve_clipplan_settings(
          {"clipplan": {"min_seconds": None}})["min_seconds"] == 15.0)
check("空設定等同預設", cp.resolve_clipplan_settings({}) == S)

# 最短被設得比最長還大時，照著跑會一支都規劃不出來——要壓回去而不是
# 靜靜地回傳空清單。
weird = cp.resolve_clipplan_settings(
    {"clipplan": {"min_seconds": 60, "max_seconds": 30}})
check("最短大於最長時壓回最長",
      weird["min_seconds"] == 30.0 and weird["max_seconds"] == 30.0,
      str(weird))

# ===== 2. 講話段落擷取 =====
mixed = [seg(10, 20), {"kind": "silence", "start": 0, "end": 5},
         seg(0, 8), {"kind": "silence", "start": 25, "end": 30}]
speech = cp.speech_segments(mixed)
check("只取講話段落", len(speech) == 2, str(len(speech)))
check("依時間排序", speech[0]["start"] == 0 and speech[1]["start"] == 10)
check("空清單不會炸", cp.speech_segments([]) == [])
check("None 不會炸", cp.speech_segments(None) == [])

# ===== 3. 基本規劃 =====
items = [seg(0, 8, "開場白"),
         seg(10, 14, "很精彩但只有 4 秒", 9.0, True),
         seg(15, 22, "接下來這段"),
         seg(30, 100, "這段超長又精彩", 8.0, True),
         seg(105, 125, "剛好夠長的精彩段", 7.0, True),
         seg(130, 140, "結尾")]
clips = cp.plan_clips(items, S, media_duration=200)
check("規劃出三支", len(clips) == 3, str(len(clips)))
check("依精彩分數排序",
      [c["score"] for c in clips] == sorted(
          [c["score"] for c in clips], reverse=True))
check("每一支都達到最短長度",
      all(c["duration"] >= S["min_seconds"] for c in clips),
      str([round(c["duration"], 1) for c in clips]))
check("每一支都不超過最長長度",
      all(c["duration"] <= S["max_seconds"] + 1e-9 for c in clips),
      str([round(c["duration"], 1) for c in clips]))
sorted_clips = sorted(clips, key=lambda c: c["start"])
check("依時間排序後確實不重疊",
      all(sorted_clips[i]["end"] <= sorted_clips[i + 1]["start"]
          for i in range(len(sorted_clips) - 1)),
      str([(round(c["start"], 1), round(c["end"], 1)) for c in sorted_clips]))

# ===== 4. 太短的片段要沿講話邊界往外擴 =====
# 只有 4 秒的精彩片段，必須擴到 >= 15 秒才輸出，而且起訖要落在
# 講話段落的邊界上（加減留白），不能從句子中間切。
short_clip = next(c for c in clips if "4 秒" in c["text"])
check("太短的精彩片段被擴長",
      short_clip["duration"] >= S["min_seconds"], str(short_clip))
check("擴張沿講話段落邊界（起點對齊 0 減留白後夾到 0）",
      short_clip["start"] == 0.0, str(short_clip["start"]))
check("擴張後的終點對齊某個講話段落的結尾＋留白",
      abs(short_clip["end"] - (22 + S["pad_seconds"])) < 1e-9,
      str(short_clip["end"]))

# 孤立的短片段：前後都沒有東西可擴，硬湊不如放棄。
check("擴不到最短長度就放棄，不硬湊",
      cp.plan_clips([seg(0, 4, "孤立的短片段", 9.0, True)], S) == [])

# ===== 5. 太長的片段要裁到上限 =====
long_clip = next(c for c in clips if "超長" in c["text"])
check("超長片段被裁到上限",
      abs(long_clip["duration"] - S["max_seconds"]) < 1e-9,
      str(long_clip["duration"]))
check("被裁的片段有標記", long_clip["trimmed"] is True)
check("沒被裁的片段不標記",
      any(c["trimmed"] is False for c in clips))

# ===== 6. 重疊與間隔 =====
close = [seg(0, 20, "精彩一", 9.0, True), seg(21, 41, "精彩二", 8.0, True)]
check("靠太近的第二個精彩片段被擋掉",
      len(cp.plan_clips(close, S)) == 1,
      str(cp.plan_clips(close, S)))
far = [seg(0, 20, "精彩一", 9.0, True), seg(100, 120, "精彩二", 8.0, True)]
check("拉開距離後兩支都要", len(cp.plan_clips(far, S)) == 2)
no_gap = cp.resolve_clipplan_settings({"clipplan": {"min_gap_seconds": 0}})
check("間隔設為 0 後靠近的也收",
      len(cp.plan_clips(close, no_gap)) == 2,
      str(cp.plan_clips(close, no_gap)))

# ===== 7. 支數上限 =====
many = [seg(i * 200, i * 200 + 20, f"精彩{i}", 9.0 - i, True)
        for i in range(6)]
check("預設最多 3 支", len(cp.plan_clips(many, S)) == 3)
check("支數可調",
      len(cp.plan_clips(many, cp.resolve_clipplan_settings(
          {"clipplan": {"count": 5}}))) == 5)
check("取的是分數最高的那幾支",
      [c["score"] for c in cp.plan_clips(many, S)] == [9.0, 8.0, 7.0])

# ===== 8. 邊界與健壯性 =====
check("沒有精彩片段就不規劃",
      cp.plan_clips([seg(0, 30), seg(31, 60)], S) == [])
check("空清單不會炸", cp.plan_clips([], S) == [])
check("None 不會炸", cp.plan_clips(None, S) == [])
check("非講話段落即使標了精彩也不算",
      cp.plan_clips([{"kind": "silence", "start": 0, "end": 60,
                      "tags": [TAG_HIGHLIGHT], "score": 9.0}], S) == [])
check("起點不會變成負數（留白往前超出開頭）",
      cp.plan_clips([seg(0, 20, "精彩", 9.0, True)], S)[0]["start"] == 0.0)
check("終點不會超過影片長度",
      cp.plan_clips([seg(0, 20, "精彩", 9.0, True)], S,
                    media_duration=20.1)[0]["end"] == 20.1)
check("沒給片長時不夾限終點",
      cp.plan_clips([seg(0, 20, "精彩", 9.0, True)], S)[0]["end"]
      == 20 + S["pad_seconds"])
check("缺少 score 欄位也不會炸",
      len(cp.plan_clips([{"kind": "speech", "start": 0, "end": 20,
                          "text": "x", "tags": [TAG_HIGHLIGHT]}], S)) == 1)
check("缺少 tags 欄位也不會炸",
      cp.plan_clips([{"kind": "speech", "start": 0, "end": 20,
                      "text": "x", "score": 9.0}], S) == [])
check("不給 settings 也能規劃",
      isinstance(cp.plan_clips(items, media_duration=200), list))

# ===== 9. 時間顯示 =====
check("秒數排成 M:SS", cp.format_timestamp(125) == "2:05")
check("超過一小時排成 H:MM:SS", cp.format_timestamp(3725) == "1:02:05")
check("負數不會變成怪字串", cp.format_timestamp(-5) == "0:00")

# ===== 10. 報告排版 =====
text = cp.format_clip_plan_report(clips, S)
check("報告有標題", "短片選段規劃" in text)
check("報告逐支列出時間", "短片 1：" in text and "～" in text)
check("報告標示被裁到上限的段落", "已裁到長度上限" in text)
check("報告列出內容摘要", "內容：" in text)
check("報告總結長度範圍", "15～60 秒" in text)
empty_text = cp.format_clip_plan_report([], S)
check("沒有結果時說明原因", "沒有規劃出可用的短片段落" in empty_text)
check("沒有結果時給出可調的設定",
      "min_seconds" in empty_text and "敏感度" in empty_text)
check("報告不使用 Markdown（tk.Text 會原樣顯示星號）",
      "**" not in text and "**" not in empty_text)
check("不給 settings 也能排版",
      isinstance(cp.format_clip_plan_report(clips), str))

# ===== 11. 設定檔預設值 =====
from config import DEFAULT_CONFIG

check("config 有 clipplan 區段", "clipplan" in DEFAULT_CONFIG)
check("config 預設值與模組一致",
      DEFAULT_CONFIG["clipplan"] == cp.DEFAULT_CLIPPLAN,
      str(DEFAULT_CONFIG["clipplan"]))

# ===== 12. CLI 介面 =====
import cli

parser = cli.build_parser()
args = parser.parse_args(["--shorts", "x.mp4"])
check("CLI 有 --shorts", args.shorts is True)
check("--shorts-count 預設為 None", args.shorts_count is None)
check("--shorts-count 可指定",
      parser.parse_args(["--shorts", "--shorts-count", "5",
                         "x.mp4"]).shorts_count == 5)
check("cli 匯入了 DEFAULT_TARGET_LUFS（否則燒錄響度時會 NameError）",
      hasattr(cli, "DEFAULT_TARGET_LUFS"))

import inspect
src = inspect.getsource(cli._export_shorts)
check("輸出重用既有的 cut_vertical_clip", "cut_vertical_clip" in src)
check("選段完全交給 clipplan", "plan_clips" in src)
check("字幕重用既有的 build_cues_from_words",
      "build_cues_from_words" in src)
check("沒有規劃結果時不會硬跑裁切",
      "if not clips" in src)

# ===== 13. 回歸：本模組只規劃，不重新實作裁切 =====
plan_src = inspect.getsource(cp)
check("clipplan 不碰 ffmpeg",
      "ffmpeg" not in plan_src and "subprocess" not in plan_src)
check("clipplan 零 GUI 依賴",
      "tkinter" not in plan_src and "gui" not in plan_src)

# ===== 14. 回歸：GUI 不得使用 classic tk 的勾選／選取控件 =====
# classic tk 元件在 sv_ttk 主題下不會跟著換色，深色主題會整顆糊掉——
# 這是實際出貨過的 bug。本版修掉審片視窗殘留的最後一個 tk.Radiobutton。
import glob
import re as _re

offenders = []
for path in glob.glob(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "gui", "*.py")):
    text = open(path, encoding="utf-8").read()
    for kind in ("Checkbutton", "Radiobutton"):
        if _re.search(r"(?<!t)tk\." + kind, text):
            offenders.append(f"{os.path.basename(path)}:{kind}")
check("gui/ 全面沒有 classic tk 勾選／選取控件",
      offenders == [], str(offenders))

review_src = open(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "gui", "review_window.py"), encoding="utf-8").read()
check("審片視窗的顯示篩選改用 ttk.Radiobutton",
      "ttk.Radiobutton" in review_src)
check("審片視窗有自動選段輸出的入口",
      "_on_auto_shorts" in review_src)
check("自動選段重用 clipplan 規劃", "plan_clips" in review_src)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.42.0 測試全數通過。")
