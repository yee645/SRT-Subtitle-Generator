# -*- coding: utf-8 -*-
"""v1.29.0 新功能測試：廣告友善度自查（黃標風險預檢）。"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import adfriendly as af


def cue(start, end, text):
    return {"start": start, "end": end, "text": text}


# ===== 1. 設定解析與夾限 =====
s = af.resolve_adfriendly_settings(None)
check("預設值", s == af.DEFAULT_ADFRIENDLY, str(s))
s2 = af.resolve_adfriendly_settings({"adfriendly": {
    "window_seconds": 9999, "cluster_threshold": 0.1,
    "opening_seconds": 999}})
check("window_seconds 夾上限 120", s2["window_seconds"] == 120.0, str(s2))
check("cluster_threshold 夾下限 1.0", s2["cluster_threshold"] == 1.0, str(s2))
check("opening_seconds 夾上限 30", s2["opening_seconds"] == 30.0, str(s2))
s3 = af.resolve_adfriendly_settings({"adfriendly": {"window_seconds": "bad"}})
check("非數值回預設", s3["window_seconds"] == 30.0, str(s3))

# ===== 2. parse_terms：多種分隔符 =====
check("逗號分隔", af.parse_terms("甲,乙,丙") == ["甲", "乙", "丙"])
check("全形逗號與頓號", af.parse_terms("甲，乙、丙") == ["甲", "乙", "丙"])
check("空白分隔", af.parse_terms("aaa  bbb") == ["aaa", "bbb"])
check("混合分隔並去空白", af.parse_terms(" 甲, 乙 ；丙 ") == ["甲", "乙", "丙"])
check("空字串回空清單", af.parse_terms("") == [])
check("None 回空清單", af.parse_terms(None) == [])

# ===== 3. _count_occurrences：中文子字串 vs 英文單字邊界 =====
check("中文子字串比對", af._count_occurrences("他說了毒品的事", "毒品") == 1)
check("中文重複計次", af._count_occurrences("毒品毒品", "毒品") == 2)
check("英文單字邊界命中",
      af._count_occurrences("that is shit right there", "shit") == 1)
check("英文不分大小寫", af._count_occurrences("SHIT happens", "shit") == 1)
# 關鍵假陽性防護：英文詞不可命中更長單字的一部分。
check("英文不誤中較長單字（class/grass 不含 ass）",
      af._count_occurrences("this class on grass", "ass") == 0)
check("英文不誤中 damn→damned 以外的黏接",
      af._count_occurrences("damnation", "damn") == 0)
check("空字串安全", af._count_occurrences("", "毒品") == 0
      and af._count_occurrences("abc", "") == 0)

# ===== 4. 叢集分析：這是本功能的核心（調研：看叢集而非單一詞） =====
# 4a. 零星單一命中不該被標為高風險（歷史頻道講一次「步槍」）。
sparse = [cue(0.0, 3.0, "今天聊二戰的歷史背景"),
          cue(120.0, 124.0, "當時的步槍設計有很大改變"),
          cue(300.0, 304.0, "戰後各國重新調整政策")]
r_sparse = af.scan_cues(sparse)
check("零星單一命中：有命中但不標高風險段落",
      len(r_sparse["hits"]) == 1 and r_sparse["clusters"] == [],
      str(r_sparse["clusters"]))

# 4b. 短時間內密集才標記。
dense = [cue(60.0, 63.0, "他拿著手槍跟步槍衝進去"),
         cue(64.0, 67.0, "現場非常血腥，根本是屠殺"),
         cue(70.0, 73.0, "彈藥打完之後還在砍死人")]
r_dense = af.scan_cues(dense)
check("短時間密集：標出高風險段落", len(r_dense["clusters"]) == 1,
      str(r_dense["clusters"]))
cluster = r_dense["clusters"][0]
check("高風險段落涵蓋正確時間範圍",
      cluster["start"] == 60.0 and cluster["end"] == 73.0, str(cluster))
check("高風險段落分數達門檻", cluster["score"] >= 3.0, str(cluster))

# 4c. 相同命中數但散在遠處 → 不成叢集（驗證是「時間密度」而非「總數」）。
spread = [cue(0.0, 3.0, "他拿著手槍"),
          cue(600.0, 603.0, "現場很血腥"),
          cue(1200.0, 1203.0, "彈藥用完了")]
r_spread = af.scan_cues(spread)
check("同樣命中數但時間分散：不成高風險段落",
      len(r_spread["hits"]) == 3 and r_spread["clusters"] == [],
      str(r_spread["clusters"]))

# 4d. 門檻可調：調高門檻後原本的叢集應消失。
r_high = af.scan_cues(dense, af.resolve_adfriendly_settings(
    {"adfriendly": {"cluster_threshold": 10.0}}))
check("調高門檻後不再標記", r_high["clusters"] == [], str(r_high["clusters"]))

# ===== 4e. 重疊詞條解析：同一段文字只算一次（長詞優先） =====
# 「他媽的」會同時命中詞表裡的「他媽」與「媽的」，若不解重疊會把同一句
# 重複計兩次，虛增叢集風險分數、報告也出現重複行。
overlap = af.scan_cues([cue(0.0, 3.0, "他媽的今天要來講一件事")])
check("重疊詞條只計一次", len(overlap["hits"]) == 1, str(overlap["hits"]))
check("重疊時風險分數不被虛增", overlap["total_score"] == 1.0,
      str(overlap["total_score"]))
check("_resolve_overlaps 保留較長詞條",
      [m[2] for m in af._resolve_overlaps(
          [(0, 2, "他媽", "粗俗用語", 1.0),
           (1, 3, "媽的", "粗俗用語", 1.0),
           (0, 3, "他媽的", "粗俗用語", 1.0)])] == ["他媽的"])
check("_resolve_overlaps 不相鄰者全部保留",
      len(af._resolve_overlaps(
          [(0, 2, "甲甲", "x", 1.0), (5, 7, "乙乙", "x", 1.0)])) == 2)

# ===== 5. 開頭區間獨立提醒（依 2025/7 粗俗用語政策更新） =====
opening = [cue(1.0, 3.0, "他媽的今天要來講一件事"),
           cue(200.0, 203.0, "後面這段就正常多了")]
r_open = af.scan_cues(opening)
check("開頭區間命中被獨立列出", len(r_open["opening_hits"]) == 1,
      str(r_open["opening_hits"]))
r_open2 = af.scan_cues([cue(100.0, 103.0, "他媽的這段在很後面")])
check("非開頭區間不列入開頭提醒", r_open2["opening_hits"] == [])

# ===== 6. 自訂補充詞與排除誤判詞 =====
custom = af.resolve_adfriendly_settings(
    {"adfriendly": {"extra_terms": "業配, 抽獎"}})
r_custom = af.scan_cues([cue(0.0, 3.0, "這支影片是業配")], custom)
check("自訂補充詞會被掃到",
      len(r_custom["hits"]) == 1
      and r_custom["hits"][0]["category"] == "自訂", str(r_custom["hits"]))

ignored = af.resolve_adfriendly_settings(
    {"adfriendly": {"ignore_terms": "步槍, 手槍"}})
r_ignored = af.scan_cues(dense, ignored)
terms_left = {h["term"] for h in r_ignored["hits"]}
check("排除誤判詞不再命中",
      "步槍" not in terms_left and "手槍" not in terms_left, str(terms_left))
check("排除誤判詞不影響其他詞", "屠殺" in terms_left, str(terms_left))

# 報告有兩種「通過」情境，訊息必須分得清楚：完全沒命中 vs 有命中但不成叢集。
all_ignored = af.scan_cues(dense, af.resolve_adfriendly_settings(
    {"adfriendly": {"ignore_terms": "手槍,步槍,屠殺,血腥,彈藥,砍死"}}))
check("全部排除：走「沒有掃到」分支",
      all_ignored["hits"] == []
      and "沒有掃到" in af.format_adfriendly_report(all_ignored))
part_ignored = af.scan_cues(dense, af.resolve_adfriendly_settings(
    {"adfriendly": {"ignore_terms": "手槍,步槍,屠殺,血腥"}}))
check("部分排除：有命中但不成叢集，走「無高風險段落」分支",
      len(part_ignored["hits"]) > 0 and part_ignored["clusters"] == []
      and "沒有偵測到風險用詞密集"
      in af.format_adfriendly_report(part_ignored),
      str(part_ignored["hits"]))

# 排除詞應同時能排掉自訂補充詞（避免兩邊設定打架）。
both = af.resolve_adfriendly_settings(
    {"adfriendly": {"extra_terms": "業配", "ignore_terms": "業配"}})
check("排除詞優先於補充詞",
      af.scan_cues([cue(0.0, 3.0, "這支影片是業配")], both)["hits"] == [])

# ===== 7. 分類統計與報告文字 =====
r_cat = af.scan_cues(dense)
check("分類統計有內容", len(r_cat["category_counts"]) > 0,
      str(r_cat["category_counts"]))
check("總分為各命中加權和",
      abs(r_cat["total_score"]
          - sum(h["weight"] * h["count"] for h in r_cat["hits"])) < 1e-9)

clean_report = af.format_adfriendly_report(af.scan_cues(
    [cue(0.0, 3.0, "今天天氣很好我們來聊聊攝影")]))
check("無命中時報告顯示通過", "沒有掃到" in clean_report, clean_report)
check("無命中時仍附上免責說明",
      "從未公布官方禁用詞清單" in clean_report, clean_report)

dense_report = af.format_adfriendly_report(r_dense)
check("有叢集時報告標出高風險段落",
      "高風險段落" in dense_report and "1:00" in dense_report, dense_report)
check("報告含分類統計", "分類統計" in dense_report, dense_report)
check("報告含逐項命中", "逐項命中" in dense_report, dense_report)
check("報告含免責說明（未命中也不保證不被標記）",
      "也不保證不會被標記" in dense_report, dense_report)

open_report = af.format_adfriendly_report(r_open)
check("開頭命中時報告有獨立提醒",
      "開頭" in open_report and "2025" in open_report, open_report)

# 逐項命中數量上限：避免超長報告洗版。
many = [cue(float(i), float(i) + 0.5, "他媽的") for i in range(0, 60, 2)]
many_report = af.format_adfriendly_report(af.scan_cues(many), max_hits=5)
check("逐項命中受 max_hits 限制", "以下列出前 5 項" in many_report,
      many_report[:400])

# 空清單與畸形輸入不應炸掉。
check("空 cue 清單安全", af.scan_cues([])["hits"] == [])
check("cue 缺 text 欄位安全",
      af.scan_cues([{"start": 0.0, "end": 1.0}])["hits"] == [])

# ===== 8. config／CLI／GUI 靜態掃描 =====
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from config import DEFAULT_CONFIG
check("config 預設含 adfriendly 區",
      DEFAULT_CONFIG.get("adfriendly") == af.DEFAULT_ADFRIENDLY,
      str(DEFAULT_CONFIG.get("adfriendly")))

with open(os.path.join(root, "cli.py"), encoding="utf-8") as fp:
    cli_src = fp.read()
check("cli.py 有 --adcheck 旗標", "--adcheck" in cli_src)
check("cli.py 有廣告友善度輸出函式", "_export_adcheck" in cli_src)

with open(os.path.join(root, "gui", "subtitle_check_dialog.py"),
          encoding="utf-8") as fp:
    dialog_src = fp.read()
check("對話框整合廣告友善度自查",
      "廣告友善度" in dialog_src and "scan_cues" in dialog_src
      and "format_adfriendly_report" in dialog_src)
check("對話框有自訂補充詞與排除誤判詞欄位",
      "ad_extra_var" in dialog_src and "ad_ignore_var" in dialog_src)
check("對話框無 classic tk.Checkbutton/Radiobutton 殘留",
      "tk.Checkbutton(" not in dialog_src.replace("ttk.Checkbutton(", "")
      and "tk.Radiobutton(" not in dialog_src.replace(
          "ttk.Radiobutton(", ""))

# ===== 9. 真實 CLI 端到端（用既有字幕檔走 --subs，免轉錄） =====
with tempfile.TemporaryDirectory() as tmp:
    srt_path = os.path.join(tmp, "測試.srt")
    with open(srt_path, "w", encoding="utf-8") as fp:
        fp.write(
            "1\n00:00:01,000 --> 00:00:04,000\n他拿著手槍跟步槍衝進去\n\n"
            "2\n00:00:05,000 --> 00:00:08,000\n現場非常血腥，根本是屠殺\n\n"
            "3\n00:00:09,000 --> 00:00:12,000\n彈藥打完之後還在砍死人\n\n"
            "4\n00:00:30,000 --> 00:00:33,000\n後面這段講的是攝影技巧\n\n")
    media = os.path.join(tmp, "測試.mp4")
    import shutil
    if shutil.which("ffmpeg"):
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=black:s=320x240:d=35",
             "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=35",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-shortest", media],
            capture_output=True, timeout=60)
        env_main = os.path.join(root, "main.py")
        proc = subprocess.run(
            [sys.executable, env_main, "--subs", srt_path, "--adcheck",
             "--formats", "srt", media],
            cwd=tmp, capture_output=True, text=True, timeout=120)
        check("實測：CLI --subs --adcheck 執行成功", proc.returncode == 0,
              proc.stdout[-1500:] + proc.stderr[-1500:])
        report_path = os.path.join(tmp, "測試_廣告友善度.txt")
        check("實測：CLI 廣告友善度報告已產生", os.path.exists(report_path))
        if os.path.exists(report_path):
            report_text = open(report_path, encoding="utf-8").read()
            check("實測：報告標出高風險段落",
                  "高風險段落" in report_text, report_text[:600])
            check("實測：報告含免責說明",
                  "從未公布官方禁用詞清單" in report_text, report_text[:600])
    else:
        print("SKIP CLI 實測（無 ffmpeg）")

print()
if failures:
    print(f"共 {len(failures)} 項失敗：{failures}")
    sys.exit(1)
print("test_v1290 全部通過")
