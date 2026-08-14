# -*- coding: utf-8 -*-
"""v1.41.0 新功能測試：術語一致性檢查（同一個詞有沒有被寫成好幾種）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import termcheck as tc


def cue(start, end, text):
    return {"start": start, "end": end, "text": text}


def by_title(result, title):
    for row in result["findings"]:
        if row["title"] == title:
            return row
    return None


def groups_of(cues, kind=None, settings=None):
    rows = tc.find_term_groups(cues, settings)
    return [g for g in rows if kind is None or g["kind"] == kind]


S = tc.resolve_termcheck_settings(None)

# ===== 1. 設定解析與夾限 =====
check("預設拉丁詞最短長度 5", S["min_latin_length"] == 5, str(S))
check("預設相似度 0.8", S["latin_similarity"] == 0.80)
over = tc.resolve_termcheck_settings(
    {"termcheck": {"min_latin_length": 999, "latin_similarity": 9}})
check("長度夾限上界", over["min_latin_length"] == tc._LATIN_LEN_RANGE[1])
check("相似度夾限到 1.0", over["latin_similarity"] == 1.0)
under = tc.resolve_termcheck_settings(
    {"termcheck": {"min_latin_length": 0, "latin_similarity": 0}})
check("長度夾限下界", under["min_latin_length"] == tc._LATIN_LEN_RANGE[0])
check("相似度夾限下界", under["latin_similarity"] == tc._SIMILARITY_RANGE[0])
check("長度會轉成整數", isinstance(over["min_latin_length"], int))
check("無法轉數字時退回預設",
      tc.resolve_termcheck_settings(
          {"termcheck": {"min_latin_length": "五"}})["min_latin_length"] == 5)
check("None 不覆蓋預設值",
      tc.resolve_termcheck_settings(
          {"termcheck": {"latin_similarity": None}})["latin_similarity"] == 0.8)
check("空設定等同預設", tc.resolve_termcheck_settings({}) == S)

# ===== 2. 拉丁詞擷取 =====
counts = tc.collect_latin([cue(0, 5, "今天聊 YouTube 跟 Youtube"),
                           cue(6, 10, "還有 youtube 的演算法")])
check("保留原本大小寫", counts["YouTube"] == 1 and counts["youtube"] == 1,
      str(counts))
check("不會把中文算進去", all(t.isascii() for t in counts))
check("空清單不會炸", tc.collect_latin(None) == {})

# ===== 3. 大小寫不一致（不可能誤判的那一類）=====
case_cues = [cue(0, 5, "今天聊 YouTube"), cue(6, 10, "在 Youtube 上"),
             cue(11, 15, "youtube 官方說明")]
cg = groups_of(case_cues, tc.KIND_CASE)
check("找得到大小寫不一致", len(cg) == 1, str(cg))
check("三種寫法都列出來", len(cg[0]["variants"]) == 3, str(cg[0]["variants"]))
check("次數相同時標為無法判斷", cg[0]["decisive"] is False)
# 有主流寫法時就該給建議。
major = groups_of([cue(0, 5, "YouTube 很好"), cue(6, 10, "YouTube 真棒"),
                   cue(11, 15, "youtube 也不錯")], tc.KIND_CASE)
check("有主流寫法時標為可判斷", major[0]["decisive"] is True)
check("建議採用最常見的寫法", major[0]["suggested"] == "YouTube",
      major[0]["suggested"])
check("寫法一致時不報", groups_of([cue(0, 5, "YouTube"), cue(6, 9, "YouTube")],
                              tc.KIND_CASE) == [])

# ===== 4. 拉丁拼法相近 =====
typo = [cue(0, 5, "這家公司叫 Anthropic"), cue(6, 10, "Anthropic 發表新模型"),
        cue(11, 15, "Anthropik 的文件很清楚")]
lg = groups_of(typo, tc.KIND_LATIN)
check("找得到拼法相近的錯字", len(lg) == 1, str(lg))
check("建議採用出現較多的寫法", lg[0]["suggested"] == "Anthropic")
check("建議保留原本的大小寫（不是小寫化）",
      "Anthropic" in lg[0]["variants"] and "anthropic" not in lg[0]["variants"],
      str(lg[0]["variants"]))

# 4a. 這是本版最容易寫錯的地方：詞形變化不是錯字。
#     只用相似度時 youtube 與 youtuber 相似度高達 0.93，
#     「一鍵統一」會把「這個 youtuber 很有趣」改成「這個 YouTube 很有趣」。
morph = [cue(0, 5, "YouTube 的演算法"), cue(6, 10, "YouTube 很大"),
         cue(11, 15, "這個 youtuber 很有趣")]
check("詞形變化（youtube/youtuber）不算錯字",
      groups_of(morph, tc.KIND_LATIN) == [], str(groups_of(morph, tc.KIND_LATIN)))
plural = [cue(0, 5, "我們用 models 訓練"), cue(6, 10, "這個 model 很小"),
          cue(11, 15, "model 的大小")]
check("單複數（model/models）不算錯字",
      groups_of(plural, tc.KIND_LATIN) == [])
check("互為前綴一律排除",
      tc._is_misspelling("youtube", "youtuber", 0.8) is False)
check("長度差超過 1 一律排除",
      tc._is_misspelling("anthropic", "anthropicxx", 0.5) is False)
check("同長度的替換型錯字算數",
      tc._is_misspelling("anthropic", "anthropik", 0.8) is True)
check("差一個字母的漏字型錯字算數",
      tc._is_misspelling("anthropic", "antropic", 0.8) is True)
check("完全不像的兩個詞不算",
      tc._is_misspelling("youtube", "twitter", 0.8) is False)

# 4b. 短詞不比：form/from、their/there 本來就長得像。
short = [cue(0, 5, "fill the form now"), cue(6, 10, "come from there"),
         cue(11, 15, "the form is from us")]
check("短詞不做相近比對（預設長度 5）",
      groups_of(short, tc.KIND_LATIN) == [],
      str(groups_of(short, tc.KIND_LATIN)))

# 4c. 門檻可調：放寬長度後短詞才會被比。
loose = tc.resolve_termcheck_settings(
    {"termcheck": {"min_latin_length": 4, "latin_similarity": 0.7}})
check("放寬設定後會抓到更多",
      len(groups_of(short, tc.KIND_LATIN, loose)) >= 1)

# ===== 5. 排除詞 =====
ignored = tc.resolve_termcheck_settings(
    {"termcheck": {"ignore_terms": "anthropik"}})
check("排除詞不會被標記",
      groups_of(typo, tc.KIND_LATIN, ignored) == [])
check("排除詞不分大小寫",
      groups_of(typo, tc.KIND_LATIN, tc.resolve_termcheck_settings(
          {"termcheck": {"ignore_terms": "ANTHROPIK"}})) == [])
check("空排除詞不影響", tc._split_terms("") == set())
check("排除詞可用逗號或空白分隔",
      tc._split_terms("a, b  c") == {"a", "b", "c"})

# ===== 6. 出現位置（用單字邊界，不是子字串）=====
occ = tc._occurrences([cue(0, 5, "YouTube 好"), cue(6, 10, "youtuber 很多")],
                      "YouTube")
check("只算完整的詞，不會在 youtuber 裡也算一次",
      len(occ) == 1 and occ[0][1] == 0.0, str(occ))
check("空詞條回空清單", tc._occurrences([cue(0, 5, "x")], "") == [])

# ===== 7. 判定 =====
clean = tc.evaluate_terms([], S)
check("沒有不一致時整體通過", clean["ok"] is True)
check("沒有不一致時只有一項且是通過的",
      len(clean["findings"]) == 1
      and clean["findings"][0]["level"] == tc.LEVEL_GOOD)

result = tc.analyze_terms(case_cues + typo)
check("有不一致時仍不是 bad（不擋上傳）", result["ok"] is True)
check("大小寫不一致獨立成一項",
      by_title(result, "大小寫不一致") is not None)
check("拼法相近獨立成一項",
      by_title(result, "疑似同一個詞的不同寫法") is not None)
check("無法判斷的組會另外提醒",
      by_title(result, "無法判斷哪個才對") is not None)
check("統計含各類數量",
      result["stats"]["case_count"] == 1
      and result["stats"]["latin_count"] == 1, str(result["stats"]))

# ===== 8. 一鍵統一 =====
choices = tc.build_fix_choices(result["groups"])
check("只統一有主流寫法的組", choices == {"Anthropik": "Anthropic"},
      str(choices))
check("次數相同的組不會被自動改",
      not any(k.lower() == "youtube" for k in choices), str(choices))
check("可要求連無法判斷的也一起處理",
      len(tc.build_fix_choices(result["groups"], decisive_only=False))
      > len(choices))

fixed, count = tc.apply_term_fixes(case_cues + typo, choices)
check("實際取代了一處", count == 1, str(count))
check("錯字被換成正確寫法",
      any("Anthropic 的文件很清楚" in c["text"] for c in fixed),
      str([c["text"] for c in fixed]))
check("原始清單不被修改",
      any("Anthropik" in c["text"] for c in (case_cues + typo)))
check("空對照表不做事", tc.apply_term_fixes(case_cues, {})[1] == 0)
check("自己換自己不做事",
      tc.apply_term_fixes(case_cues, {"YouTube": "YouTube"})[1] == 0)
check("None 對照表不會炸", tc.apply_term_fixes(case_cues, None)[1] == 0)

# 回歸：詞形變化不該被一鍵統一改壞。
morph_fixed, morph_count = tc.apply_term_fixes(
    morph, tc.build_fix_choices(tc.find_term_groups(morph)))
check("一鍵統一不會動到 youtuber", morph_count == 0
      and any("youtuber" in c["text"] for c in morph_fixed))

# ===== 9. 時間顯示 =====
check("秒數排成 M:SS", tc.format_timestamp(125) == "2:05")
check("超過一小時排成 H:MM:SS", tc.format_timestamp(3725) == "1:02:05")
check("負數不會變成怪字串", tc.format_timestamp(-5) == "0:00")

# ===== 10. 報告排版 =====
text = tc.format_term_report(result, S)
check("報告有標題", "術語一致性檢查" in text)
check("報告列出逐組明細", "逐組明細" in text)
check("報告標示建議統一成哪個", "建議統一成這個" in text)
check("報告標示無法判斷的組", "次數相同，無法判斷" in text)
check("報告給出可貼進自動修正詞庫的規則",
      "自動修正詞庫" in text and "Anthropik → Anthropic" in text)
check("報告附上出現時間", "出現在" in text)
clean_text = tc.format_term_report(clean, S)
check("沒有不一致時結論是正面的", "術語寫法一致" in clean_text)
check("沒有不一致時不列明細", "逐組明細" not in clean_text)
check("報告不使用 Markdown（tk.Text 會原樣顯示星號）",
      "**" not in text and "**" not in clean_text)
check("空結果不會炸", "沒有可分析的內容" in tc.format_term_report({}, S))
check("None 結果不會炸", "沒有可分析的內容" in tc.format_term_report(None, S))
check("不給 settings 也能排版", isinstance(tc.format_term_report(result), str))

# ===== 11. 效能與健壯性 =====
big = [cue(i, i + 1, f"這是第 {i} 句 YouTube Anthropic 測試")
       for i in range(500)]
big_result = tc.analyze_terms(big)
check("大量字幕不會炸也不會誤報", big_result["ok"] is True
      and big_result["stats"]["group_count"] == 0,
      str(big_result["stats"]))
check("空字幕不會炸", tc.analyze_terms([])["ok"] is True)
check("None 字幕不會炸", tc.analyze_terms(None)["ok"] is True)
check("沒有文字的 cue 不會炸",
      tc.analyze_terms([{"start": 0, "end": 1}])["ok"] is True)

# ===== 12. 與總體檢的整合 =====
from subtitle import preflight as pf

ps = pf.resolve_preflight_settings(None)
check("總體檢預設納入術語一致性", ps["run_term"] is True)
names = [n for n, _ in pf._build_steps(ps, True, True)]
check("有字幕時會跑術語一致性", "術語一致性" in names, str(names))
no_cue = [n for n, _ in pf._build_steps(ps, True, False)]
check("沒有字幕時略過（需要逐字稿）", "術語一致性" not in no_cue)
off = [n for n, _ in pf._build_steps(
    pf.resolve_preflight_settings({"preflight": {"run_term": False}}),
    True, True)]
check("可單獨關閉術語一致性", "術語一致性" not in off)

import inspect
src = inspect.getsource(pf._run_term)
check("轉接器沒有自己的判斷邏輯",
      " if " not in src and "LEVEL_" not in src, src)
rows = pf.normalize_findings(result, "術語一致性")
check("findings 可被總體檢正規化", len(rows) == len(result["findings"]))
check("正規化後帶上來源", all(r["source"] == "術語一致性" for r in rows))

# ===== 13. 設定檔預設值 =====
from config import DEFAULT_CONFIG

check("config 有 termcheck 區段", "termcheck" in DEFAULT_CONFIG)
check("config 預設值與模組一致",
      DEFAULT_CONFIG["termcheck"] == tc.DEFAULT_TERMCHECK,
      str(DEFAULT_CONFIG["termcheck"]))
check("config 的 preflight 有 run_term",
      DEFAULT_CONFIG["preflight"]["run_term"] is True)

# ===== 14. 重用既有取代邏輯，不重新實作 =====
src = inspect.getsource(tc.apply_term_fixes)
check("取代重用 textedit.replace_in_cues", "replace_in_cues" in src)

# ===== 15. 刻意不做中文模糊比對（實測會改壞逐字稿）=====
# 中文沒有詞間空白，不靠斷詞詞典只能用定長 n-gram，而 n-gram 會跨越
# 詞的邊界：「我們就／我們都」兩個都是正常的詞，「柏克萊的時候」與
# 「柏克萊念書」會被切出「克萊的／克萊念」。照著統一會直接改壞內容。
cjk = [cue(0, 5, "我們就這樣一路做下來"), cue(6, 10, "我們都覺得很值得"),
       cue(11, 15, "我第一次去柏克萊的時候"), cue(16, 20, "在伯克萊念書的朋友"),
       cue(21, 25, "那個時候我還不知道"), cue(26, 30, "那個時後我剛開始")]
cjk_groups = tc.find_term_groups(cjk)
check("中文不做模糊比對，不會產生誤判組", cjk_groups == [], str(cjk_groups))
check("中文內容不會被一鍵統一改動",
      tc.apply_term_fixes(cjk, tc.build_fix_choices(cjk_groups))[1] == 0)
check("模組沒有殘留中文 n-gram 實作",
      not hasattr(tc, "collect_cjk_ngrams")
      and not hasattr(tc, "find_cjk_groups"))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.41.0 測試全數通過。")
