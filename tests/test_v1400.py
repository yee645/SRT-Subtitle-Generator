# -*- coding: utf-8 -*-
"""v1.40.0 新功能測試：工商揭露健檢（業配揭露得夠不夠早）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import sponsorcheck as sc


def cue(start, end, text):
    return {"start": start, "end": end, "text": text}


def by_title(result, title):
    for row in result["findings"]:
        if row["title"] == title:
            return row
    return None


S = sc.resolve_sponsorcheck_settings(None)

# ===== 1. 設定解析與夾限 =====
check("預設間隔 30 秒", S["gap_seconds"] == 30.0, str(S))
check("預設佔比上限 0.25", S["max_ratio"] == 0.25)
over = sc.resolve_sponsorcheck_settings(
    {"sponsorcheck": {"gap_seconds": 9999, "max_ratio": 9}})
check("間隔夾限上界", over["gap_seconds"] == sc._GAP_RANGE[1], str(over))
check("佔比夾限到 1.0", over["max_ratio"] == 1.0)
under = sc.resolve_sponsorcheck_settings(
    {"sponsorcheck": {"gap_seconds": 0, "max_ratio": 0}})
check("間隔夾限下界", under["gap_seconds"] == sc._GAP_RANGE[0])
check("佔比夾限下界", under["max_ratio"] == sc._RATIO_RANGE[0])
check("無法轉數字時退回預設",
      sc.resolve_sponsorcheck_settings(
          {"sponsorcheck": {"gap_seconds": "很久"}})["gap_seconds"] == 30.0)
check("None 不覆蓋預設值",
      sc.resolve_sponsorcheck_settings(
          {"sponsorcheck": {"max_ratio": None}})["max_ratio"] == 0.25)
check("空設定等同預設", sc.resolve_sponsorcheck_settings({}) == S)

# ===== 2. 詞表組裝 =====
d, p = sc.build_term_lists(S)
check("內建揭露詞非空", len(d) > 10, str(len(d)))
check("內建推銷詞非空", len(p) > 10, str(len(p)))
custom = sc.resolve_sponsorcheck_settings(
    {"sponsorcheck": {"extra_disclosure_terms": "阿福贊助, 友情提供",
                      "extra_promo_terms": "神秘連結"}})
d2, p2 = sc.build_term_lists(custom)
check("自訂揭露詞會被加入", "阿福贊助" in d2)
check("自訂推銷詞會被加入", "神秘連結" in p2)
ignored = sc.resolve_sponsorcheck_settings(
    {"sponsorcheck": {"ignore_terms": "業配, 折扣碼"}})
d3, p3 = sc.build_term_lists(ignored)
check("排除詞會從揭露表移除", "業配" not in d3)
check("排除詞也會從推銷表移除", "折扣碼" not in p3)
check("排除詞不影響其他詞", "贊助商" in d3)

# ===== 3. 詞條比對 =====
check("中文用子字串比對", sc._term_hits("這集是業配影片", "業配") is True)
# 純拉丁詞若用子字串比對，"ad" 會誤中 "radar"、"advice"。
check("英文用單字邊界比對，不誤中 radar",
      sc._term_hits("look at the radar", "ad") is False)
check("英文完整單字仍比對得到",
      sc._term_hits("use code CLAUDE", "use code") is True)
check("英文比對不分大小寫",
      sc._term_hits("USE CODE CLAUDE", "use code") is True)
check("井字號開頭的標籤比對得到",
      sc._term_hits("這是 #ad 影片", "#ad") is True)
check("空字串不會炸", sc._term_hits("", "業配") is False)

# ===== 4. 掃描 =====
hits = sc.scan_cues([cue(0, 5, "今天要講剪輯"),
                     cue(10, 16, "本集由某某贊助"),
                     cue(16, 22, "用我的折扣碼")], S)
check("只回報有命中的句子", len(hits) == 2, str(hits))
check("揭露語標為 disclosure", hits[0]["kind"] == "disclosure")
check("推銷語標為 promo", hits[1]["kind"] == "promo")
# 一句話同時有兩類時，合規意義是「揭露」。
both = sc.scan_cues([cue(0, 5, "本集由某某贊助，用我的折扣碼")], S)
check("同句同時命中時揭露優先", both[0]["kind"] == "disclosure")
check("空白句子不掃", sc.scan_cues([cue(0, 5, "   ")], S) == [])
check("空清單不會炸", sc.scan_cues(None, S) == [])

# ===== 5. 分段（本版最容易寫錯的地方）=====
# 5a. 只講一句揭露、完全沒有推銷 → 那是「揭露」本身，不是業配段落，
#     不該被算成一段、也不該產生章節。
only_disc = sc.group_segments(
    sc.scan_cues([cue(10, 16, "順帶一提我完全沒有收業配")], S), S)
check("只有揭露沒有推銷不算一段工商", only_disc == [], str(only_disc))
# 5b. 單一句「連結在資訊欄」在一般影片太常見，不該被當成業配。
one_promo = sc.group_segments(
    sc.scan_cues([cue(10, 16, "連結在資訊欄，記得看")], S), S)
check("單一個推銷詞不算一段工商", one_promo == [], str(one_promo))
# 5c. 兩個以上不同推銷詞才算。
two_promo = sc.group_segments(
    sc.scan_cues([cue(10, 16, "用我的折扣碼"), cue(16, 22, "下方連結點進去")],
                 S), S)
check("兩個以上推銷詞算一段工商", len(two_promo) == 1, str(two_promo))
# 5d. 一個推銷詞＋同段揭露也算。
disc_promo = sc.group_segments(
    sc.scan_cues([cue(10, 16, "本集由某某贊助"), cue(16, 22, "用我的折扣碼")],
                 S), S)
check("揭露＋一個推銷詞算一段工商", len(disc_promo) == 1)
# 5e. 間隔超過 gap 的命中要分成兩段。
far = sc.group_segments(
    sc.scan_cues([cue(10, 16, "用我的折扣碼"), cue(16, 22, "下方連結"),
                  cue(600, 606, "用我的優惠碼"), cue(606, 612, "專屬連結")],
                 S), S)
check("間隔太遠會分成兩段", len(far) == 2, str(len(far)))
close = sc.group_segments(
    sc.scan_cues([cue(10, 16, "用我的折扣碼"), cue(30, 36, "下方連結")], S), S)
check("間隔在 gap 之內併為同一段", len(close) == 1)

# 5f. 這是本版的核心：揭露時間要跨全片找，不是只看段落內部。
#     「這支影片由 X 贊助」講在開頭、業配口白在第 5 分鐘，是完全合規
#     而且非常常見的做法；只看段落內部會把正確的影片誤判成沒有揭露。
early = sc.group_segments(
    sc.scan_cues([cue(8, 14, "先說，這支影片由某某贊助"),
                  cue(300, 306, "用我的折扣碼"),
                  cue(306, 312, "專屬連結在資訊欄")], S), S)
check("開頭揭露、稍後才業配算一段", len(early) == 1, str(len(early)))
check("開頭的揭露會被算成事前揭露",
      early[0]["disclosure_time"] == 8.0, str(early[0]["disclosure_time"]))
check("事前有揭露時不記錄遲到時間",
      early[0]["late_disclosure_time"] is None)

# 5g. 揭露在業配之後（FTC 明講不合格）——這條分支若寫錯會永遠走不到。
late_seg = sc.group_segments(
    sc.scan_cues([cue(120, 126, "用我的折扣碼"),
                  cue(126, 132, "專屬連結在資訊欄"),
                  cue(600, 606, "對了這集是業配")], S), S)
check("片尾才揭露仍只算一段業配", len(late_seg) == 1, str(len(late_seg)))
check("片尾才揭露不算事前揭露",
      late_seg[0]["disclosure_time"] is None)
check("片尾才揭露會記錄遲到時間",
      late_seg[0]["late_disclosure_time"] == 600.0,
      str(late_seg[0]["late_disclosure_time"]))

# ===== 6. 判定 =====
no_seg = sc.evaluate_sponsor([], 300.0, S)
check("沒有工商段落整體通過", no_seg["ok"] is True)
check("沒有工商時只有一項且是通過的",
      len(no_seg["findings"]) == 1
      and no_seg["findings"][0]["level"] == sc.LEVEL_GOOD)
check("沒有工商時不產生章節", no_seg["chapter_lines"] == [])

ok_result = sc.evaluate_sponsor(early, 320.0, S)
check("事前揭露整體通過", ok_result["ok"] is True)
check("事前揭露列出兩個時間點",
      "0:08" in by_title(ok_result, "工商揭露")["detail"]
      and "5:00" in by_title(ok_result, "工商揭露")["detail"],
      by_title(ok_result, "工商揭露")["detail"])

late_result = sc.evaluate_sponsor(late_seg, 610.0, S)
check("揭露太晚是 bad", late_result["ok"] is False)
row = by_title(late_result, "揭露得太晚")
check("揭露太晚會被獨立標題標記", row is not None and row["level"] == sc.LEVEL_BAD)
check("揭露太晚同時給出兩個時間",
      "2:00" in row["detail"] and "10:00" in row["detail"], row["detail"])
check("揭露太晚的建議引用 FTC 標準", "FTC" in row["advice"])

missing_seg = sc.group_segments(
    sc.scan_cues([cue(120, 126, "用我的優惠碼"),
                  cue(126, 132, "下方連結點進去")], S), S)
missing_result = sc.evaluate_sponsor(missing_seg, 300.0, S)
check("完全沒揭露是 bad", missing_result["ok"] is False)
row = by_title(missing_result, "沒有揭露的工商段落")
check("完全沒揭露會被標記", row is not None and row["level"] == sc.LEVEL_BAD)
check("完全沒揭露的建議提到勾選付費宣傳", "付費宣傳" in row["advice"])
check("完全沒揭露的建議提到與金額大小無關", "金額" in row["advice"])
check("沒揭露與太晚是不同的兩項",
      by_title(missing_result, "揭露得太晚") is None)

# 佔比。
big = [{"start": 0.0, "end": 200.0, "hits": [], "disclosure_time": 0.0,
        "late_disclosure_time": None, "promo_terms": ["折扣碼", "下方連結"]}]
ratio_result = sc.evaluate_sponsor(big, 300.0, S)
row = by_title(ratio_result, "工商佔比")
check("工商佔比過高會警告", row["level"] == sc.LEVEL_WARN, str(row))
check("佔比警告給出百分比與門檻",
      "67%" in row["detail"] and "25%" in row["detail"], row["detail"])
check("佔比過高但有揭露仍非 bad", ratio_result["ok"] is True)
loose = sc.resolve_sponsorcheck_settings({"sponsorcheck": {"max_ratio": 1.0}})
check("放寬佔比門檻後不再警告",
      by_title(sc.evaluate_sponsor(big, 300.0, loose),
               "工商佔比")["level"] == sc.LEVEL_GOOD)
check("讀不到片長時不報佔比",
      by_title(sc.evaluate_sponsor(big, 0.0, S), "工商佔比") is None)

# ===== 7. 章節建議 =====
check("章節行是可直接貼上的格式",
      sc.chapter_line({"start": 125.0}) == "2:05 贊助商說明",
      sc.chapter_line({"start": 125.0}))
check("章節標題可自訂",
      sc.chapter_line({"start": 0.0}, "工商時間") == "0:00 工商時間")
check("有工商段落就給出章節",
      late_result["chapter_lines"] == ["2:00 贊助商說明"],
      str(late_result["chapter_lines"]))

# ===== 8. 時間顯示 =====
check("秒數排成 M:SS", sc.format_timestamp(125) == "2:05")
check("超過一小時排成 H:MM:SS", sc.format_timestamp(3725) == "1:02:05")
check("零秒顯示 0:00", sc.format_timestamp(0) == "0:00")
check("負數不會變成怪字串", sc.format_timestamp(-5) == "0:00")

# ===== 9. 端到端 =====
full = sc.analyze_sponsor(
    [cue(0, 5, "今天要講剪輯"), cue(120, 126, "本集由某某贊助"),
     cue(126, 132, "用我的折扣碼"), cue(300, 306, "以上就是今天的內容")],
    310.0)
check("端到端：合規影片通過", full["ok"] is True)
check("端到端：產出章節", full["chapter_lines"] == ["2:00 贊助商說明"])
check("沒給片長時用字幕末尾推算",
      sc.analyze_sponsor([cue(0, 5, "今天要講剪輯")])["stats"]["duration"]
      == 5.0)
check("空字幕不會炸", sc.analyze_sponsor([])["ok"] is True)
check("None 字幕不會炸", sc.analyze_sponsor(None)["ok"] is True)

# ===== 10. 報告排版 =====
text = sc.format_sponsor_report(late_result, S)
check("報告有標題", "工商揭露健檢" in text)
check("報告用叉號標示 bad", "✘" in text)
check("報告列出偵測到的段落", "偵測到的工商段落" in text)
check("報告標示揭露太晚", "太晚，在段落之後" in text)
check("報告給出可貼上的章節", "2:00 贊助商說明" in text)
check("報告提醒章節的既有規則", "0:00" in text and "10 秒" in text)
check("bad 時結論點出法規風險", "法規風險" in text)
clean_text = sc.format_sponsor_report(no_seg, S)
check("沒有工商時結論是正面的", "沒有問題" in clean_text)
check("沒有工商時不列出章節區塊", "建議加上的章節" not in clean_text)
warn_only = sc.format_sponsor_report(sc.evaluate_sponsor(big, 300.0, S), S)
check("只有警告時結論不說得像全數通過",
      "可以再調整" in warn_only, warn_only.splitlines()[-1])
check("報告不使用 Markdown（tk.Text 會原樣顯示星號）",
      "**" not in text and "**" not in clean_text)
check("空結果不會炸", "沒有可分析的內容" in sc.format_sponsor_report({}, S))
check("None 結果不會炸", "沒有可分析的內容" in sc.format_sponsor_report(None, S))
check("不給 settings 也能排版",
      isinstance(sc.format_sponsor_report(late_result), str))

# ===== 11. 與總體檢的整合 =====
from subtitle import preflight as pf

ps = pf.resolve_preflight_settings(None)
check("總體檢預設納入工商揭露", ps["run_sponsor"] is True)
names = [n for n, _ in pf._build_steps(ps, True, True)]
check("有字幕時會跑工商揭露", "工商揭露" in names, str(names))
no_cue_names = [n for n, _ in pf._build_steps(ps, True, False)]
check("沒有字幕時略過工商揭露（需要逐字稿）",
      "工商揭露" not in no_cue_names, str(no_cue_names))
off_names = [n for n, _ in pf._build_steps(
    pf.resolve_preflight_settings({"preflight": {"run_sponsor": False}}),
    True, True)]
check("可單獨關閉工商揭露", "工商揭露" not in off_names)

import inspect
src = inspect.getsource(pf._run_sponsor)
check("轉接器沒有自己的判斷邏輯",
      " if " not in src and "LEVEL_" not in src, src)
rows = pf.normalize_findings(late_result, "工商揭露")
check("findings 可被總體檢正規化", len(rows) == len(late_result["findings"]))
check("正規化後帶上來源", all(r["source"] == "工商揭露" for r in rows))

# ===== 12. 設定檔預設值 =====
from config import DEFAULT_CONFIG

check("config 有 sponsorcheck 區段", "sponsorcheck" in DEFAULT_CONFIG)
check("config 預設值與模組一致",
      DEFAULT_CONFIG["sponsorcheck"] == sc.DEFAULT_SPONSORCHECK,
      str(DEFAULT_CONFIG["sponsorcheck"]))
check("config 的 preflight 有 run_sponsor",
      DEFAULT_CONFIG["preflight"]["run_sponsor"] is True)

# ===== 13. 不與既有檢查重複 =====
# 開場健檢（v1.33）也認得贊助商用語，但問的是「會不會害觀眾離開」這個
# 留存問題；本模組問的是揭露合不合規。兩者的判定必須各自獨立。
from subtitle import hookcheck as hc

opening_sponsor = [cue(0, 5, "本集由某某贊助"), cue(5, 11, "用我的折扣碼"),
                   cue(30, 36, "好，今天要講剪輯技巧")]
hook_result = hc.analyze_hook(opening_sponsor, hc.resolve_hookcheck_settings())
sponsor_result = sc.analyze_sponsor(opening_sponsor, 40.0)
check("開場健檢仍會提醒贊助商卡在開頭",
      any(f["title"] == "開場放贊助商" for f in hook_result["findings"]),
      str([f["title"] for f in hook_result["findings"]]))
check("工商揭露對同一份字幕判為合規（有事前揭露）",
      sponsor_result["ok"] is True)
check("兩個模組的項目標題不重疊",
      not ({f["title"] for f in hook_result["findings"]}
           & {f["title"] for f in sponsor_result["findings"]}))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.40.0 測試全數通過。")
