# -*- coding: utf-8 -*-
"""v1.32.0 新功能測試：YouTube 章節健檢與一鍵修正。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import chaptercheck as cc
from subtitle import review


def levels(result, level):
    return [f for f in result["findings"] if f["level"] == level]


def bad_titles(result):
    return [f["title"] for f in levels(result, cc.LEVEL_BAD)]


# ===== 1. 設定解析與夾限 =====
s = cc.resolve_chaptercheck_settings(None)
check("預設值即 YouTube 規則", s == cc.DEFAULT_CHAPTERCHECK, str(s))
s2 = cc.resolve_chaptercheck_settings({"chaptercheck": {
    "min_chapter_seconds": 999, "min_chapter_count": 99}})
check("min_chapter_seconds 夾上限", s2["min_chapter_seconds"] == 120.0, str(s2))
check("min_chapter_count 夾上限", s2["min_chapter_count"] == 10, str(s2))
s3 = cc.resolve_chaptercheck_settings({"chaptercheck": {
    "min_chapter_seconds": 0.1, "min_chapter_count": 0}})
check("min_chapter_seconds 夾下限", s3["min_chapter_seconds"] == 1.0, str(s3))
check("min_chapter_count 夾下限", s3["min_chapter_count"] == 2, str(s3))
check("非數值回預設",
      cc.resolve_chaptercheck_settings(
          {"chaptercheck": {"min_chapter_seconds": "bad"}})
      ["min_chapter_seconds"] == 10.0)
check("min_chapter_count 保持整數",
      isinstance(cc.resolve_chaptercheck_settings(None)["min_chapter_count"],
                 int))

# ===== 2. 時間戳解析 =====
check("M:SS", cc.parse_timestamp("0:00") == 0.0)
check("MM:SS", cc.parse_timestamp("12:34") == 754.0)
check("H:MM:SS", cc.parse_timestamp("1:02:03") == 3723.0)
check("秒數 >= 60 視為無效", cc.parse_timestamp("0:60") is None)
check("有時位時分鐘 >= 60 視為無效", cc.parse_timestamp("1:75:00") is None)
check("秒數只有一位視為無效", cc.parse_timestamp("0:5") is None)
check("分號分隔視為無效", cc.parse_timestamp("0;00") is None)
check("空字串視為無效", cc.parse_timestamp("") is None)
check("format 省略時位", cc.format_timestamp(65) == "1:05")
check("format 保留時位", cc.format_timestamp(3661) == "1:01:01")
check("format 補滿兩位秒", cc.format_timestamp(5) == "0:05")

# ===== 3. 解析錯誤要「指出是哪一種錯」，而不是只說格式錯誤 =====
text = ("0;00 開場\n"
        "0:5 第二段\n"
        "0:20第三段\n"
        "1:00\n"
        "2:00 正常\n"
        "亂寫的一行\n")
chapters, errors = cc.parse_chapters(text)
check("合法行仍被解析出來",
      [(c["start"], c["title"]) for c in chapters] == [(120.0, "正常")],
      str(chapters))
check("錯誤行數正確", len(errors) == 5, str(len(errors)))
reasons = {e["lineno"]: e["reason"] for e in errors}
check("分隔符打錯指認為冒號問題", "半形冒號" in reasons[1], reasons[1])
check("秒數少一位指認為補兩位", "補滿兩位" in reasons[2], reasons[2])
check("黏在一起指認為缺空白", "空白" in reasons[3], reasons[3])
check("只有時間戳指認為缺標題", "沒有標題" in reasons[4], reasons[4])
check("完全無法辨識時給總括說明", "無法辨識" in reasons[6], reasons[6])
check("錯誤行帶行號與原文",
      errors[0]["lineno"] == 1 and errors[0]["line"] == "0;00 開場")

# ===== 4. 意圖明確的錯誤要能修回來，不能默默丟掉 =====
repaired = {e["lineno"]: e["repaired"] for e in errors}
check("分隔符打錯可修",
      repaired[1] == {"start": 0.0, "title": "開場"}, str(repaired[1]))
check("秒數少一位可修",
      repaired[2] == {"start": 5.0, "title": "第二段"}, str(repaired[2]))
check("缺空白可修",
      repaired[3] == {"start": 20.0, "title": "第三段"}, str(repaired[3]))
check("只有時間戳沒標題無法修", repaired[4] is None)
check("無法辨識的行無法修", repaired[6] is None)
check("可修的行建議按一鍵修正",
      "一鍵修正" in [e for e in cc.validate_chapters(
          chapters, 300.0, s, errors)["findings"]
          if e["title"] == "格式錯誤"][0]["advice"])
check("不可修的行要說請手動修正",
      "手動" in [f for f in cc.validate_chapters(
          chapters, 300.0, s, errors)["findings"]
          if f["title"] == "格式錯誤" and "1:00" in f["detail"]][0]["advice"])

# ===== 5. YouTube 的三條硬規則 =====
ok3 = [{"start": 0.0, "title": "開場"}, {"start": 60.0, "title": "中段"},
       {"start": 150.0, "title": "結尾"}]
check("完全合規判定為 ok", cc.validate_chapters(ok3, 300.0, s)["ok"])

one = [{"start": 0.0, "title": "全片"}]
r_one = cc.validate_chapters(one, 300.0, s)
check("只有 1 章不合規", not r_one["ok"])
check("只有 1 章指出章節數量", "章節數量" in bad_titles(r_one),
      str(bad_titles(r_one)))

late = [{"start": 12.0, "title": "開場"}, {"start": 90.0, "title": "第二"},
        {"start": 200.0, "title": "結尾"}]
r_late = cc.validate_chapters(late, 300.0, s)
check("首章不是 0:00 不合規", not r_late["ok"])
check("首章不是 0:00 指出首章時間", "首章時間" in bad_titles(r_late),
      str(bad_titles(r_late)))

short = [{"start": 0.0, "title": "開場"}, {"start": 30.0, "title": "重點"},
         {"start": 34.0, "title": "插曲"}, {"start": 120.0, "title": "結尾"}]
r_short = cc.validate_chapters(short, 300.0, s)
check("有過短章節不合規", not r_short["ok"])
check("過短章節指出章節長度", "章節長度" in bad_titles(r_short),
      str(bad_titles(r_short)))
check("過短章節報告點名是哪一章",
      "重點" in [f for f in levels(r_short, cc.LEVEL_BAD)
                if f["title"] == "章節長度"][0]["detail"])

# 最後一章的長度只有拿到影片長度才判斷得出來——這是很容易漏掉的一章。
tail = [{"start": 0.0, "title": "開場"}, {"start": 60.0, "title": "中段"},
        {"start": 150.0, "title": "尾"}, {"start": 297.0, "title": "掰掰"}]
check("有影片長度時抓得到過短的最後一章",
      not cc.validate_chapters(tail, 300.0, s)["ok"])
check("沒有影片長度時最後一章不誤判",
      cc.validate_chapters(tail, None, s)["ok"])
check("沒有影片長度時報告要說明最後一章未檢查",
      "最後一章未檢查" in [f for f in cc.validate_chapters(tail, None, s)
                          ["findings"] if f["title"] == "章節長度"][0]["detail"])

dup = [{"start": 0.0, "title": "開場"}, {"start": 60.0, "title": "第二"},
       {"start": 60.0, "title": "重複"}, {"start": 150.0, "title": "尾"}]
check("時間重複不合規", "時間重複" in bad_titles(
    cc.validate_chapters(dup, 300.0, s)))
check("沒有章節時明確回報",
      "章節內容" in bad_titles(cc.validate_chapters([], 300.0, s)))

# ===== 6. 一鍵修正 =====
fixed, changes = cc.fix_chapters(late, 300.0, s)
check("首章補成 0:00", fixed[0]["start"] == 0.0)
check("首章修正後通過檢查", cc.validate_chapters(fixed, 300.0, s)["ok"])
check("首章修正有寫進說明", any("0:00" in c for c in changes), str(changes))

fixed, changes = cc.fix_chapters(short, 300.0, s)
check("過短章節被併掉",
      [(c["start"], c["title"]) for c in fixed]
      == [(0.0, "開場"), (30.0, "重點"), (120.0, "結尾")], str(fixed))
check("合併保留前一章的標題（前一章才是該段主題）",
      any("插曲" in c and "重點" in c for c in changes), str(changes))
check("合併後通過檢查", cc.validate_chapters(fixed, 300.0, s)["ok"])

fixed, changes = cc.fix_chapters(tail, 300.0, s)
check("過短的最後一章被併回前一章",
      [c["title"] for c in fixed] == ["開場", "中段", "尾"], str(fixed))
check("最後一章合併後通過檢查", cc.validate_chapters(fixed, 300.0, s)["ok"])

fixed, changes = cc.fix_chapters(dup, 300.0, s)
check("重複時間被移除",
      [c["start"] for c in fixed] == [0.0, 60.0, 150.0], str(fixed))
check("重複移除有寫進說明", any("重複" in c for c in changes), str(changes))

messy = [{"start": 120.0, "title": "第三"}, {"start": 0.0, "title": "開場"},
         {"start": 60.0, "title": "第二"}]
fixed, _ = cc.fix_chapters(messy, 300.0, s)
check("亂序會排好", [c["start"] for c in fixed] == [0.0, 60.0, 120.0],
      str(fixed))

# 連鎖過短：每一章都太近，應一路併到剩下合規的分界點。
chain = [{"start": 0.0, "title": "A"}, {"start": 3.0, "title": "B"},
         {"start": 6.0, "title": "C"}, {"start": 9.0, "title": "D"},
         {"start": 60.0, "title": "E"}, {"start": 200.0, "title": "F"}]
fixed, _ = cc.fix_chapters(chain, 300.0, s)
check("連鎖過短一路併到合規",
      [(c["start"], c["title"]) for c in fixed]
      == [(0.0, "A"), (60.0, "E"), (200.0, "F")], str(fixed))
check("連鎖過短修正後通過檢查", cc.validate_chapters(fixed, 300.0, s)["ok"])

# 修正不會憑空捏造章節：段落本來就不夠時要如實回報，不能假裝修好了。
few = [{"start": 0.0, "title": "A"}, {"start": 5.0, "title": "B"},
       {"start": 100.0, "title": "C"}]
fixed, _ = cc.fix_chapters(few, 200.0, s)
check("章節數不足時不捏造章節", len(fixed) == 2, str(fixed))
check("章節數不足時修正後仍如實回報不合規",
      not cc.validate_chapters(fixed, 200.0, s)["ok"])

# 這是最容易誤導人的失敗方式：格式打錯的行被丟掉，報告卻顯示「全部合格」。
chapters, errors = cc.parse_chapters(
    "0;00 開場閒聊\n0:20 今天的主題\n0:24 補充一下\n2:00 實際操作\n4:58結尾\n")
fixed, changes = cc.fix_chapters(chapters, 300.0, s, parse_errors=errors)
titles = [c["title"] for c in fixed]
check("格式打錯的第一行被救回、不會消失", "開場閒聊" in titles, str(titles))
check("救回的章節放在正確的時間", fixed[0]["start"] == 0.0, str(fixed))
check("救回動作有寫進修正說明",
      any("開場閒聊" in c and "修正" in c for c in changes), str(changes))
check("含救回的修正結果通過檢查",
      cc.validate_chapters(fixed, 300.0, s)["ok"])
fixed_no_recover, _ = cc.fix_chapters(chapters, 300.0, s)
check("不給 parse_errors 時維持舊行為（僅處理可解析的章節）",
      "開場閒聊" not in [c["title"] for c in fixed_no_recover])

# ===== 7. 門檻可調要真的生效 =====
loose = cc.resolve_chaptercheck_settings(
    {"chaptercheck": {"min_chapter_seconds": 2.0}})
check("放寬每章最短秒數後 4 秒的章節不再被標記",
      cc.validate_chapters(short, 300.0, loose)["ok"])
strict = cc.resolve_chaptercheck_settings({"chaptercheck":
                                           {"min_chapter_count": 4}})
check("調高最少章節數後 3 章不再合規",
      not cc.validate_chapters(ok3, 300.0, strict)["ok"])

# ===== 8. 報告文字 =====
report = cc.format_chapter_report(
    cc.validate_chapters(short, 300.0, s), chapters=short)
check("報告含標題列", "YouTube 章節健檢" in report)
check("報告寫出「不會顯示」這個關鍵後果", "不會顯示" in report)
check("報告不含 markdown 星號（tk.Text 會原樣顯示）", "**" not in report)
check("報告附上目前章節", "0:30 重點" in report)
ok_report = cc.format_chapter_report(
    cc.validate_chapters(ok3, 300.0, s), chapters=ok3)
check("合規報告給出可直接貼上的結論", "可以直接貼到說明欄" in ok_report)
check("有修正說明時列在報告中",
      "已套用的修正" in cc.format_chapter_report(
          cc.validate_chapters(fixed, 300.0, s), chapters=fixed,
          changes=["測試用修正"]))
check("章節文字可直接貼上",
      cc.format_chapters_text(ok3) == "0:00 開場\n1:00 中段\n2:30 結尾",
      cc.format_chapters_text(ok3))

# ===== 9. 回歸：既有產生器的輸出真的會被擋下來 =====
# build_chapters 只保證首章 0:00，段落間隔不足時會靜靜地只吐出 1 章，
# 使用者貼上後 YouTube 完全不顯示卻收不到任何提示——這就是本版要補的洞。
items = []
start = 0.0
for index in range(6):
    items.append({"kind": "speech", "keep": True, "start": start,
                  "end": start + 10.0, "text": f"第 {index} 段"})
    start += 10.5  # 間隔僅 0.5 秒，達不到 break_gap
generated = review.build_chapters(items, min_chapter_seconds=60.0,
                                  break_gap=2.0)
check("既有產生器在此素材上真的只產生 1 章", len(generated) == 1,
      str(generated))
result = cc.validate_chapters(generated, 63.0, s)
check("章節健檢會擋下這種輸出", not result["ok"])
check("並且說明原因是章節數不足", "章節數量" in bad_titles(result),
      str(bad_titles(result)))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.32.0 測試全數通過。")
