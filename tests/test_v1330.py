# -*- coding: utf-8 -*-
"""v1.33.0 新功能測試：開場健檢（多久才進正題）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import hookcheck as hc


def cues(*rows):
    return [{"start": s, "end": e, "text": t} for s, e, t in rows]


def titles(result, level=None):
    return [f["title"] for f in result["findings"]
            if level is None or f["level"] == level]


S = hc.resolve_hookcheck_settings(None)
TABLE = hc.build_term_table(S)

# ===== 1. 設定解析與夾限 =====
check("預設值", S == hc.DEFAULT_HOOKCHECK, str(S))
s2 = hc.resolve_hookcheck_settings({"hookcheck": {
    "target_seconds": 999, "max_greeting_seconds": 999,
    "max_head_silence": 999}})
check("target_seconds 夾上限", s2["target_seconds"] == 60.0, str(s2))
check("max_greeting_seconds 夾上限", s2["max_greeting_seconds"] == 30.0)
check("max_head_silence 夾上限", s2["max_head_silence"] == 10.0)
s3 = hc.resolve_hookcheck_settings({"hookcheck": {
    "target_seconds": 0.1, "max_greeting_seconds": 0.1}})
check("target_seconds 夾下限", s3["target_seconds"] == 5.0, str(s3))
check("max_greeting_seconds 夾下限", s3["max_greeting_seconds"] == 1.0)
check("非數值回預設",
      hc.resolve_hookcheck_settings(
          {"hookcheck": {"target_seconds": "bad"}})["target_seconds"] == 15.0)
check("詞表欄位為字串",
      isinstance(hc.resolve_hookcheck_settings(None)["ignore_terms"], str))

# ===== 2. 詞表：長詞優先，補充與排除生效 =====
check("詞表依長度由長到短",
      all(len(TABLE[i][0]) >= len(TABLE[i + 1][0])
          for i in range(len(TABLE) - 1)))
custom = hc.build_term_table(hc.resolve_hookcheck_settings(
    {"hookcheck": {"extra_filler_terms": "老規矩, 開場白"}}))
check("自訂套語有加進詞表",
      "老規矩" in [t for t, _ in custom] and "開場白" in [t for t, _ in custom])
ignored = hc.build_term_table(hc.resolve_hookcheck_settings(
    {"hookcheck": {"ignore_terms": "訂閱"}}))
check("排除詞會從詞表移除", "訂閱" not in [t for t, _ in ignored])
check("排除詞不影響其他同類詞", "小鈴鐺" in [t for t, _ in ignored])

# ===== 3. 逐句判定：關鍵是「扣掉套語後還剩多少實質內容」 =====
def verdict(text, table=TABLE):
    return hc.classify_cue(text, table)["filler"]

check("純打招呼是套語", verdict("哈囉大家好，我是阿明"))
check("頻道宣傳是套語", verdict("歡迎來到我的頻道"))
check("無關閒聊是套語", verdict("今天天氣真的很不錯對不對"))
check("開場要訂閱是套語", verdict("在開始之前先幫我按個訂閱跟小鈴鐺"))
check("純轉場語是套語", verdict("那我們廢話不多說"))
check("正題不是套語", not verdict("今天要教大家怎麼用三個步驟做出專業影片"))
# 這是本模組最關鍵的判斷：句子含套語，但它同時就是正題本身。
# 若只做關鍵詞比對，這一句會被誤判成廢話而把進正題時間往後推。
check("含套語但同時是正題者不算套語",
      not verdict("廢話不多說，今天要教大家怎麼用三個步驟做出專業影片"))
check("短但有結論的句子不算套語", not verdict("先講結論：這支筆電不值得買"))

# 英文若直接數字母，任何一句都會遠超門檻而永遠算成有內容。
check("英文純套語是套語", verdict("hey guys welcome back to my channel"))
check("英文開場要訂閱是套語",
      verdict("so before we get started, don't forget to subscribe"))
check("英文正題不是套語",
      not verdict("so today I'm going to show you how to render 4K video "
                  "without dropping frames"))

# 排除單一詞不該連帶讓包含它的長詞失效：排除「訂閱」後，
# 「記得訂閱」這個更長的套語仍應命中。
check("排除短詞後較長的同義套語仍然命中",
      hc.classify_cue("記得訂閱喔", ignored)["filler"],
      str(hc.classify_cue("記得訂閱喔", ignored)))
# 反過來，把整句唯一命中的套語排除掉，該句就不該再被當成套語。
only_channel = hc.build_term_table(hc.resolve_hookcheck_settings(
    {"hookcheck": {"ignore_terms": "歡迎來到我的頻道"}}))
check("排除掉唯一命中的套語後該句不再算套語",
      not hc.classify_cue("歡迎來到我的頻道", only_channel)["filler"],
      str(hc.classify_cue("歡迎來到我的頻道", only_channel)))

# ===== 4. 完整分析：實證缺口的那一組素材 =====
BAD = cues(
    (0.0, 3.5, "哈囉大家好，我是阿明"),
    (3.5, 7.0, "歡迎來到我的頻道"),
    (7.0, 11.0, "今天天氣真的很不錯對不對"),
    (11.0, 15.0, "在開始之前先幫我按個訂閱跟小鈴鐺"),
    (15.0, 18.5, "也記得開啟通知喔"),
    (18.5, 22.0, "那我們廢話不多說"),
    (22.0, 27.0, "今天要教大家怎麼用三個步驟做出專業影片"),
)
bad = hc.analyze_hook(BAD, S)
check("廢話開場判定為不合格", not bad["ok"])
check("正確算出 22 秒才進正題", bad["time_to_point"] == 22.0,
      str(bad["time_to_point"]))
check("建議起點等於進正題時間", bad["suggested_start"] == 22.0)
check("指出進正題時間問題", "進正題時間" in titles(bad, hc.LEVEL_BAD))
check("指出開場要訂閱", "開場要訂閱" in titles(bad, hc.LEVEL_BAD))
check("指出寒暄過長", "開場寒暄過長" in titles(bad, hc.LEVEL_WARN))
check("指出無關閒聊", "開場無關閒聊" in titles(bad, hc.LEVEL_WARN))
check("六句套語全部被列出",
      len([r for r in bad["opening"] if r["filler"]]) == 6,
      str(len([r for r in bad["opening"] if r["filler"]])))
check("正題那句不算套語", bad["opening"][-1]["filler"] is False)
check("分析在找到正題後就停止（不掃全片）", len(bad["opening"]) == 7,
      str(len(bad["opening"])))

# ===== 5. 好的開場 =====
GOOD = cues(
    (0.0, 4.0, "這支筆電我用了三個月，結論是不值得買"),
    (4.0, 8.0, "我會從散熱、續航跟鍵盤三個地方講"),
    (8.0, 12.0, "哈囉大家好我是阿明，記得訂閱喔"),
)
good = hc.analyze_hook(GOOD, S)
check("直接進正題判定為合格", good["ok"])
check("進正題時間為 0", good["time_to_point"] == 0.0)
# 訂閱提醒出現在正題之後就不該被罵——研究建議的正是「移到後段」。
check("正題之後才要訂閱不列為問題",
      "開場要訂閱" not in titles(good), str(titles(good)))

# ===== 6. 各項獨立判準 =====
sub_only = cues((0.0, 4.0, "記得訂閱按讚開啟通知"),
                (4.0, 9.0, "這台相機在低光源下的表現讓我很意外"))
r = hc.analyze_hook(sub_only, S)
check("開場要訂閱單獨成立", "開場要訂閱" in titles(r, hc.LEVEL_BAD))
check("4 秒進正題仍算及格（未超過 15 秒）",
      "進正題時間" in titles(r, hc.LEVEL_GOOD), str(titles(r)))

sponsor = cues((0.0, 5.0, "本集由某某贊助商提供"),
               (5.0, 10.0, "這台相機在低光源下的表現讓我很意外"))
check("贊助商卡在正題前會提醒",
      "開場放贊助商" in titles(hc.analyze_hook(sponsor, S), hc.LEVEL_WARN))

silent = cues((4.0, 9.0, "這台相機在低光源下的表現讓我很意外"))
r = hc.analyze_hook(silent, S)
check("開頭乾等太久會提醒", "開頭沒聲音" in titles(r, hc.LEVEL_WARN))
check("開頭乾等秒數正確", r["head_silence"] == 4.0)
check("開頭乾等不影響合格判定（僅 WARN）", r["ok"])

house = cues((0.0, 5.0, "不好意思這麼久沒更新，最近比較忙"),
             (5.0, 10.0, "這台相機在低光源下的表現讓我很意外"))
check("頻道雜務會提醒",
      "開場頻道雜務" in titles(hc.analyze_hook(house, S), hc.LEVEL_WARN))

# ===== 7. 邊界情況 =====
empty = hc.analyze_hook([], S)
check("沒有字幕時明確回報", not empty["ok"])
check("沒有字幕時 time_to_point 為 None", empty["time_to_point"] is None)
check("沒有字幕時建議起點為 0", empty["suggested_start"] == 0.0)

all_filler = cues((0.0, 3.0, "哈囉大家好"), (3.0, 6.0, "歡迎來到我的頻道"))
r = hc.analyze_hook(all_filler, S)
check("全片都是套語時判定不合格", not r["ok"])
check("全片都是套語時 time_to_point 為 None", r["time_to_point"] is None)
check("全片都是套語時報告說明可能是誤判",
      "排除詞" in [f["advice"] for f in r["findings"]
                  if f["title"] == "進正題時間"][0])

check("空白句被略過不影響判定",
      hc.analyze_hook(cues((0.0, 1.0, "   "),
                           (1.0, 6.0, "這台相機在低光源下的表現讓我很意外")),
                      S)["time_to_point"] == 1.0)
check("亂序輸入會先排序",
      hc.analyze_hook(cues((9.0, 14.0, "這台相機在低光源下表現讓我意外"),
                           (0.0, 4.0, "哈囉大家好")), S)["opening"][0]["start"]
      == 0.0)

# ===== 8. 門檻可調要真的生效 =====
loose = hc.resolve_hookcheck_settings({"hookcheck": {"target_seconds": 30.0}})
check("放寬目標秒數後 22 秒不再被判不合格",
      "進正題時間" in titles(hc.analyze_hook(BAD, loose), hc.LEVEL_GOOD),
      str(titles(hc.analyze_hook(BAD, loose))))
strict = hc.resolve_hookcheck_settings(
    {"hookcheck": {"max_greeting_seconds": 30.0}})
check("放寬寒暄上限後不再提醒寒暄過長",
      "開場寒暄過長" not in titles(hc.analyze_hook(BAD, strict)))
quiet = hc.resolve_hookcheck_settings({"hookcheck": {"max_head_silence": 10.0}})
check("放寬乾等上限後不再提醒開頭沒聲音",
      "開頭沒聲音" not in titles(hc.analyze_hook(silent, quiet)))
# 排除是「逐詞」生效的（與 adfriendly 的 ignore_terms 慣例一致）：
# 要讓一句話完全不再算套語，該句命中的每個詞都要列出來。
custom_ignore = hc.resolve_hookcheck_settings(
    {"hookcheck": {"ignore_terms": "歡迎來到我的頻道, 哈囉大家好, 哈囉, 大家好"}})
check("排除誤判詞會讓該句不再算套語",
      hc.analyze_hook(all_filler, custom_ignore)["time_to_point"] == 0.0,
      str(hc.analyze_hook(all_filler, custom_ignore)["time_to_point"]))
partial_ignore = hc.resolve_hookcheck_settings(
    {"hookcheck": {"ignore_terms": "哈囉, 大家好"}})
check("只排除組成詞時合併套語仍然命中",
      hc.analyze_hook(all_filler, partial_ignore)["time_to_point"] is None)

# ===== 9. 報告文字 =====
report = hc.format_hook_report(bad, S)
check("報告含標題列", "開場健檢" in report)
check("報告不含 markdown 星號（tk.Text 會原樣顯示）", "**" not in report)
check("報告列出被判定為套語的句子", "被判定為開場套語的句子" in report)
check("報告給出建議起點", "0:22" in report, report[-200:])
check("報告標出分類", "訂閱提醒" in report)
good_report = hc.format_hook_report(good, S)
check("合格報告給出正面結論", "沒有明顯拖累留存的問題" in good_report)
check("空報告不會爆炸",
      "沒有可分析" in hc.format_hook_report({"findings": []}, S))
check("時間格式化省略時位", hc.format_timestamp(65) == "1:05")
check("時間格式化保留時位", hc.format_timestamp(3661) == "1:01:01")

# ===== 10. 回歸：既有健檢確實抓不到這個問題（本版存在的理由）=====
from subtitle.subtitlecheck import analyze_cues, resolve_subcheck_settings
from subtitle.adfriendly import scan_cues, resolve_adfriendly_settings
sub_result = analyze_cues(BAD, resolve_subcheck_settings(None))
ad_result = scan_cues(BAD, resolve_adfriendly_settings(None))
check("字幕健檢對這段廢話開場沒有任何意見",
      len(sub_result.get("issues") or []) == 0)
check("廣告友善度對這段廢話開場沒有任何意見",
      len(ad_result.get("clusters") or []) == 0)
check("開場健檢才抓得到", not bad["ok"])

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.33.0 測試全數通過。")
