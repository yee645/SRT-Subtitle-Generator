# -*- coding: utf-8 -*-
"""v1.45.0 新功能測試：說明欄結構健檢（寫了，但寫在對的地方嗎）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import desccheck as dc


def by_title(result, title):
    for row in result["findings"]:
        if row["title"] == title:
            return row
    return None


S = dc.resolve_desccheck_settings(None)

GOOD = """這支影片會教你三個剪輯技巧，讓你的影片節奏更好看。我會示範怎麼抓剪點、怎麼配樂、以及怎麼處理字幕，全部都有實際操作。

00:00 開場
01:30 技巧一：節奏
05:00 技巧二：配樂

訂閱：https://example.com
#剪輯 #教學"""

PLUMBING = """歡迎來到我的頻道！記得訂閱、按讚、開啟小鈴鐺，這樣才不會錯過每一支新影片喔！

追蹤我的 IG：https://example.com/instagram
追蹤我的 Facebook：https://example.com/facebook
加入我的 Discord：https://example.com/discord
合作邀約請來信：https://example.com/mail

#剪輯 #教學 #YouTube #創作者

這支影片會教你三個剪輯技巧。"""

# ===== 1. 設定解析與夾限 =====
check("預設收合字元 200", S["fold_chars"] == 200, str(S))
check("預設管線比例上限 0.55", S["max_plumbing_ratio"] == 0.55)
over = dc.resolve_desccheck_settings(
    {"desccheck": {"fold_chars": 9999, "min_repeat": 999,
                   "max_term_ratio": 9, "max_plumbing_ratio": 9}})
check("收合字元夾限上界", over["fold_chars"] == dc._FOLD_RANGE[1])
check("重複次數夾限上界", over["min_repeat"] == dc._REPEAT_RANGE[1])
check("堆砌比例夾限到上界", over["max_term_ratio"] == dc._RATIO_RANGE[1])
check("管線比例夾限到 1.0", over["max_plumbing_ratio"] == 1.0)
check("收合字元會轉成整數", isinstance(over["fold_chars"], int))
check("無法轉數字時退回預設",
      dc.resolve_desccheck_settings(
          {"desccheck": {"fold_chars": "兩百"}})["fold_chars"] == 200)
check("None 不覆蓋預設值",
      dc.resolve_desccheck_settings(
          {"desccheck": {"min_chars": None}})["min_chars"] == 100)
check("空設定等同預設", dc.resolve_desccheck_settings({}) == S)

# ===== 2. 收合前文字 =====
check("取前 N 字元", dc.fold_text("abcdef", 3) == "abc")
check("短於 N 時全取", dc.fold_text("ab", 10) == "ab")
check("空字串不會炸", dc.fold_text("", 10) == "")
check("None 不會炸", dc.fold_text(None, 10) == "")

# ===== 3. 管線佔比（本版最關鍵的判準）=====
# 為什麼不用「扣掉樣板後剩幾個字」：詞表永遠列不全。實測那段全是
# 交際語與帳號的開頭，扣完仍殘留 50 個字，看起來很多、資訊量是零。
plumb = dc.plumbing_ratio(dc.fold_text(PLUMBING, 200))
clean = dc.plumbing_ratio(dc.fold_text(GOOD, 200))
check("管線開頭的佔比很高", plumb > 0.7, f"{plumb:.2f}")
check("內容開頭的佔比很低", clean < 0.4, f"{clean:.2f}")
check("兩者分得開且門檻落在中間",
      clean < S["max_plumbing_ratio"] < plumb,
      f"{clean:.2f} < {S['max_plumbing_ratio']} < {plumb:.2f}")
check("純連結是 1.0",
      dc.plumbing_ratio("https://example.com") == 1.0)
check("純內容是 0.0", dc.plumbing_ratio("這支影片在講剪輯技巧") == 0.0)
check("空字串回 0", dc.plumbing_ratio("") == 0.0)
check("只有空白回 0", dc.plumbing_ratio("   \n  ") == 0.0)
check("None 不會炸", dc.plumbing_ratio(None) == 0.0)
check("換行不灌水分母",
      dc.plumbing_ratio("https://a.com\n\n\n") == 1.0)

# ===== 4. 關鍵字堆砌 =====
stuffed = dc.find_stuffed_terms("剪輯教學 " * 10 + "其他內容都不一樣的字", S)
check("重複多次的詞被抓到", len(stuffed) >= 1, str(stuffed))
check("回傳詞、次數、佔比",
      len(stuffed[0]) == 3 and stuffed[0][1] >= S["min_repeat"])
check("依次數由多到少排序",
      all(stuffed[i][1] >= stuffed[i + 1][1]
          for i in range(len(stuffed) - 1)))
# 只看佔比會在很短的說明欄誤判（總共三個詞、一個出現兩次就 66%）。
check("重複次數不足時不判為堆砌",
      dc.find_stuffed_terms("剪輯 剪輯 教學", S) == [],
      str(dc.find_stuffed_terms("剪輯 剪輯 教學", S)))
check("正常說明欄不誤判", dc.find_stuffed_terms(GOOD, S) == [])
check("空字串不會炸", dc.find_stuffed_terms("", S) == [])
check("連結與 hashtag 不算進詞頻",
      dc.find_stuffed_terms("#剪輯 " * 10, S) == [])

# ===== 5. 詞擷取 =====
terms = dc.extract_terms("這支影片講 editing 技巧 editing 很重要")
check("擷取到拉丁詞", "editing" in terms)
check("拉丁詞轉小寫", "Editing".lower() in [t for t in terms])
check("擷取到中文連續字串", any("影片" in t for t in terms))
check("空字串回空清單", dc.extract_terms("") == [])

# ===== 6. 分段 =====
check("多段會被數出來", dc.paragraph_count("一\n\n二\n三") == 3)
check("單段就是 1", dc.paragraph_count("只有一段") == 1)
check("空字串是 0", dc.paragraph_count("") == 0)
check("只有空白是 0", dc.paragraph_count("  \n  ") == 0)

# ===== 7. 判定 =====
empty = dc.analyze_description("", 600)
check("空說明欄是 bad", empty["ok"] is False)
check("空說明欄只回一項", len(empty["findings"]) == 1)
check("空說明欄講出代價", "白白丟掉" in empty["findings"][0]["advice"])

good = dc.analyze_description(GOOD, 600)
check("良好的說明欄整體通過", good["ok"] is True)
check("良好的說明欄開頭項通過",
      by_title(good, "開頭實質內容")["level"] == dc.LEVEL_GOOD)
check("良好的說明欄有章節",
      by_title(good, "章節時間戳記")["level"] == dc.LEVEL_GOOD)
check("良好的說明欄有分段",
      by_title(good, "分段結構")["level"] == dc.LEVEL_GOOD)
check("良好的說明欄不報堆砌",
      by_title(good, "關鍵字堆砌")["level"] == dc.LEVEL_GOOD)

bad_open = dc.analyze_description(PLUMBING, 600)
row = by_title(bad_open, "開頭實質內容")
check("開頭被管線佔滿會警告", row["level"] == dc.LEVEL_WARN, str(row))
check("警告給出實際百分比與門檻",
      "%" in row["detail"] and "55%" in row["detail"], row["detail"])
check("建議點出搜尋結果只顯示第一行", "第一行" in row["advice"])

short = dc.analyze_description("太短了", 600)
check("太短的說明欄會警告",
      by_title(short, "說明欄內容")["level"] == dc.LEVEL_WARN)

one_block = dc.analyze_description("這支影片會講剪輯技巧" * 12, 600)
check("一整塊沒分段會警告",
      by_title(one_block, "分段結構")["level"] == dc.LEVEL_WARN)

# 章節只在長片提醒——短片本來就不需要章節。
short_video = dc.analyze_description(GOOD.replace("00:00 開場", ""), 60)
check("短片不提醒章節", by_title(short_video, "章節時間戳記") is None)
no_dur = dc.analyze_description(GOOD, 0)
check("沒給片長時不提醒章節", by_title(no_dur, "章節時間戳記") is None)
long_no_ch = dc.analyze_description("這支影片會講很多剪輯技巧與後製流程。\n\n第二段內容。", 600)
check("長片沒章節會警告",
      by_title(long_no_ch, "章節時間戳記")["level"] == dc.LEVEL_WARN)

# ===== 8. 統計 =====
stats = good["stats"]
check("統計含字元數", stats["chars"] > 0)
check("統計含章節數", stats["chapters"] == 3, str(stats["chapters"]))
check("統計含 hashtag 數", stats["hashtags"] == 2, str(stats["hashtags"]))
check("統計含管線佔比", 0.0 <= stats["plumbing"] <= 1.0)

# ===== 9. 報告排版 =====
text = dc.format_desc_report(bad_open, S)
check("報告有標題", "說明欄結構健檢" in text)
check("報告用驚嘆號標示警告", "⚠" in text)
check("報告含量測數值", "量測數值" in text and "收合前" in text)
check("有警告時結論給方向", "放到最前面" in text)
check("空結果不會炸", "沒有可分析的內容" in dc.format_desc_report({}, S))
check("None 不會炸", "沒有可分析的內容" in dc.format_desc_report(None, S))
check("報告不使用 Markdown（tk.Text 會原樣顯示星號）",
      "**" not in text)
check("不給 settings 也能排版", isinstance(dc.format_desc_report(good), str))
check("全數通過時結論是正面的",
      "沒有問題" in dc.format_desc_report(good, S))

# ===== 10. 設定檔預設值 =====
from config import DEFAULT_CONFIG

check("config 有 desccheck 區段", "desccheck" in DEFAULT_CONFIG)
check("config 預設值與模組一致",
      DEFAULT_CONFIG["desccheck"] == dc.DEFAULT_DESCCHECK,
      str(DEFAULT_CONFIG["desccheck"]))

# ===== 11. 重用既有模組，不重新實作 =====
import inspect
src = inspect.getsource(dc)
check("時間戳記解析重用 chaptercheck", "parse_chapters" in src)
check("hashtag 擷取重用 publishcheck", "find_hashtags" in src)
check("零 GUI 依賴", "tkinter" not in src)
# 只看實際使用（import／呼叫），不要被說明文字裡的「不碰 ffmpeg」騙過。
check("不碰 ffmpeg（無 import 也無呼叫）",
      "import subprocess" not in src and "subprocess.run" not in src
      and '"ffmpeg"' not in src)

# ===== 12. 與既有發佈資訊健檢不重疊 =====
# v1.36 看的是「會不會被系統拒絕」的硬性上限；本模組看的是「寫得對不對」。
from subtitle import publishcheck as pc

pub = pc.analyze_publish("標題", PLUMBING, "", pc.resolve_publishcheck_settings())
check("兩個模組的項目標題不重疊",
      not ({f["title"] for f in pub["findings"]}
           & {f["title"] for f in bad_open["findings"]}),
      str({f["title"] for f in pub["findings"]}))

# ===== 13. CLI 與 GUI 接線 =====
import cli
check("CLI 匯入了說明欄健檢", hasattr(cli, "analyze_description"))
cli_src = inspect.getsource(cli._run_publishcheck)
check("CLI 把說明欄結構接在上限檢查之後", "format_desc_report" in cli_src)
check("CLI 會嘗試取得影片長度供章節判斷", "probe_duration" in cli_src)
gui_src = open(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "gui", "publishcheck_dialog.py"), encoding="utf-8").read()
check("GUI 也接上說明欄結構", "format_desc_report" in gui_src)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.45.0 測試全數通過。")
