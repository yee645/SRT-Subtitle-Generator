# -*- coding: utf-8 -*-
"""v1.47.0 新功能測試：中文字幕標點規範（行尾標點、句中逗頓、英文不動）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import punctstyle as ps
from subtitle.segmenter import split_into_lines
from config import DEFAULT_CONFIG


def cue(index, text, start=0.0, end=2.0):
    return {"index": index, "start": start, "end": end, "text": text}


# ===== 1. 中／英判定：英文的標點是文法，不能動 =====
CHINESE_LINES = [
    "今天要跟大家分享三個剪輯技巧，",
    "我用的是 Premiere Pro，",
    "先按 Ctrl+Shift+D 開啟這個面板，",
    "我覺得 iPhone 17 Pro Max 的錄影真的很扯，",
    "OK 那我們開始吧",
]
ENGLISH_LINES = [
    "Hello, everyone.",
    "So today, we're going to talk about three editing tips.",
    "The 台北 experience, honestly, was great.",
    "I use Premiere Pro, and it works fine.",
]
for line in CHINESE_LINES:
    check(f"判定為中文行：{line[:12]}", ps.is_chinese_line(line),
          f"{ps.cjk_ratio(line):.2f}")
for line in ENGLISH_LINES:
    check(f"判定為英文行：{line[:20]}", not ps.is_chinese_line(line),
          f"{ps.cjk_ratio(line):.2f}")
check("中英門檻有餘裕",
      min(ps.cjk_ratio(t) for t in CHINESE_LINES)
      > max(ps.cjk_ratio(t) for t in ENGLISH_LINES) + 0.15)

# ===== 2. 行尾標點：拿掉沒有作用的，保留帶語氣的 =====
for text, expect in [("今天要跟大家分享，", "今天要跟大家分享"),
                     ("你一定要學會。", "你一定要學會"),
                     ("我的建議是：", "我的建議是"),
                     ("對啊，。", "對啊"),
                     ("好了。。。", "好了")]:
    check(f"拿掉行尾標點 {text}", ps.style_line(text)[0] == expect,
          ps.style_line(text)[0])
for text in ["你相信嗎？", "真的就是這樣！", "然後呢…", "真的假的？？"]:
    check(f"保留語氣標點 {text}", ps.style_line(text)[0] == text,
          ps.style_line(text)[0])

# 英文行原封不動——這是本模組最重要的安全條件。
for text in ENGLISH_LINES:
    check(f"英文行不動 {text[:20]}", ps.style_line(text)[0] == text,
          ps.style_line(text)[0])

# ===== 3. subtitle 模式：句中逗頓改空格 =====
SUB = ps.resolve_punctstyle_settings({"punctstyle": {"mode": "subtitle"}})
out, _, swapped = ps.style_line("這台相機我用了三個月，老實說，優缺點都很明顯。", SUB)
check("句中逗號改成空格", out == "這台相機我用了三個月　老實說　優缺點都很明顯", out)
check("回報換掉的個數", swapped == 2, str(swapped))
check("頓號也改成空格",
      ps.style_line("紅、藍、綠三種顏色都有", SUB)[0] == "紅　藍　綠三種顏色都有",
      ps.style_line("紅、藍、綠三種顏色都有", SUB)[0])
check("subtitle 模式下英文行仍然不動",
      ps.style_line("Hello, everyone.", SUB)[0] == "Hello, everyone.")
check("trim 模式不碰句中逗頓",
      ps.style_line("這台相機我用了三個月，老實說，優缺點都很明顯。")[0]
      == "這台相機我用了三個月，老實說，優缺點都很明顯",
      ps.style_line("這台相機我用了三個月，老實說，優缺點都很明顯。")[0])
check("off 模式什麼都不做",
      ps.style_line("今天要跟大家分享，",
                    ps.resolve_punctstyle_settings(
                        {"punctstyle": {"mode": "off"}}))[0]
      == "今天要跟大家分享，")

# ===== 4. 整份字幕套用 =====
CUES = [cue(1, "今天要跟大家分享三個剪輯技巧，"),
        cue(2, "你相信嗎？"),
        cue(3, "Hello, everyone."),
        cue(4, "第一行，還沒講完\n第二行講完了。"),
        cue(5, "。，")]
fixed, changed = ps.apply_punct_style(CUES)
check("只改需要改的句子", changed == 2, str(changed))
check("多行字幕逐行處理",
      fixed[3]["text"] == "第一行，還沒講完\n第二行講完了", repr(fixed[3]["text"]))
check("整句只有標點時不會被清空", fixed[4]["text"] == "。，", repr(fixed[4]["text"]))
check("不就地修改原本的 cue", CUES[0]["text"] == "今天要跟大家分享三個剪輯技巧，")
check("時間軸原封不動",
      all(o["start"] == n["start"] and o["end"] == n["end"]
          for o, n in zip(CUES, fixed)))
check("index 原封不動",
      [c["index"] for c in fixed] == [1, 2, 3, 4, 5])

# ===== 5. 分析報告 =====
result = ps.analyze_punctuation(CUES)
check("報告抓到行尾標點", result["stats"]["trailing"] == 2,
      str(result["stats"]))
# 6 行裡扣掉英文那行、以及整行只有標點（沒有任何中日韓字元可判斷）的
# 那行，剩下 4 行才是要套用中文慣例的。
check("英文行與純標點行不計入中文行數", result["stats"]["chinese"] == 4,
      str(result["stats"]))
check("總行數含多行字幕的每一行", result["stats"]["lines"] == 6,
      str(result["stats"]))
check("有問題時 ok 為 False", result["ok"] is False)
check("附上實際例子", len(result["samples"]) >= 1)
check("例子標示拿掉的是哪個標點",
      all(s["mark"] for s in result["samples"]))
report = ps.format_punct_report(result)
check("報告有標題", "中文字幕標點規範" in report)
check("報告有結論", "結論：" in report)
check("報告不用 markdown 粗體", "**" not in report)
clean = ps.analyze_punctuation(ps.apply_punct_style(CUES)[0])
check("規範化之後就通過", clean["ok"] is True, str(clean["stats"]))

english_only = ps.analyze_punctuation([cue(1, "Hello, everyone.")])
check("全英文字幕直接判定不適用", english_only["ok"] is True)
check("全英文字幕不會叫人去改",
      english_only["stats"]["trailing"] == 0)

# ===== 6. 這一版的動機：本工具自己的斷句會製造行尾逗號 =====
# 斷句演算法刻意切在逗號上（segmenter.WEAK_PUNCT），所以幾乎每一句都以
# 逗號結尾——那個逗號在字幕裡完全沒有作用，下一句本來就是另一張畫面。
script = ("今天要跟大家分享三個剪輯技巧，第一個技巧真的超級重要，"
          "你一定要學會。很多人都做錯了這一步，結果影片節奏整個亂掉。")
lines = split_into_lines(script, DEFAULT_CONFIG)
own = [cue(i + 1, line) for i, line in enumerate(lines)]
own_result = ps.analyze_punctuation(own)
ratio = own_result["stats"]["trailing"] / own_result["stats"]["chinese"]
check("本工具自己的斷句確實會製造行尾標點", ratio >= 0.7, f"{ratio:.0%}")
check("規範化能全部清掉",
      ps.analyze_punctuation(ps.apply_punct_style(own)[0])["ok"] is True)

# ===== 7. 設定夾限 =====
check("未知模式退回預設",
      ps.resolve_punctstyle_settings(
          {"punctstyle": {"mode": "BOGUS"}})["mode"] == "trim")
check("空白以外的 space 不被接受",
      ps.resolve_punctstyle_settings(
          {"punctstyle": {"space": "哈"}})["space"] == "　")
check("接受兩個半形空白",
      ps.resolve_punctstyle_settings(
          {"punctstyle": {"space": "  "}})["space"] == "  ")
check("cjk_ratio 夾限",
      ps.resolve_punctstyle_settings(
          {"punctstyle": {"cjk_ratio": 9}})["cjk_ratio"] == 1.0)
check("預設值進得了 config",
      DEFAULT_CONFIG["punctstyle"]["mode"] == "trim")
check("空字幕不會炸", ps.analyze_punctuation([])["ok"] is True)
check("None 不會炸", ps.apply_punct_style(None) == ([], 0))

# ===== 8. 零依賴、零 ffmpeg =====
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "subtitle", "punctstyle.py"),
           encoding="utf-8").read()
check("不呼叫 ffmpeg",
      "import subprocess" not in src and "subprocess.run" not in src)
check("重用 segmenter 的 CJK 區段定義（不另外抄一份）",
      "from subtitle.segmenter import CJK_RANGES" in src)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.47.0 測試全數通過。")
