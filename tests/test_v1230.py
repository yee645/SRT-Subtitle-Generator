# -*- coding: utf-8 -*-
"""v1.23.0 新功能測試：字幕健檢新增時間軸重疊檢查與一鍵修復。"""
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

from subtitle import subtitlecheck as sc


def cue(start, end, text="正常字幕內容測試"):
    return {"start": start, "end": end, "text": text}


# ===== 1. find_overlaps：偵測時間軸重疊 =====
no_overlap = [cue(0.0, 2.0), cue(3.0, 5.0)]
check("無重疊時回空清單", sc.find_overlaps(no_overlap) == [])

simple_overlap = [cue(0.0, 3.0), cue(2.0, 5.0)]
issues = sc.find_overlaps(simple_overlap)
check("找出簡單重疊", len(issues) == 1 and issues[0]["index"] == 0, str(issues))
check("重疊詳情含秒數", "1.00 秒" in issues[0]["detail"], issues[0]["detail"])
check("重疊標記為 BAD 等級", issues[0]["level"] == sc.LEVEL_BAD)

# 極小誤差（浮點數）不算重疊。
tiny = [cue(0.0, 2.000001), cue(2.0, 4.0)]
check("極小誤差不算重疊", sc.find_overlaps(tiny) == [])

# 未排序輸入也要能正確偵測（依開始時間排序後比對）。
unsorted_cues = [cue(5.0, 8.0), cue(0.0, 6.0)]
issues_unsorted = sc.find_overlaps(unsorted_cues)
check("未排序輸入正確偵測重疊",
      len(issues_unsorted) == 1 and issues_unsorted[0]["index"] == 1,
      str(issues_unsorted))

# 少於 2 句不炸。
check("空清單不炸", sc.find_overlaps([]) == [])
check("單句不炸", sc.find_overlaps([cue(0, 1)]) == [])

# 相同起始時間（極端情況）。
same_start = [cue(0.0, 3.0), cue(0.0, 4.0)]
issues_same = sc.find_overlaps(same_start)
check("相同起始時間也算重疊", len(issues_same) == 1, str(issues_same))

# ===== 2. analyze_cues：整合重疊檢查（即使句子文字為空也要檢查） =====
settings = sc.resolve_subcheck_settings(None)
blank_but_overlap = [
    {"start": 0.0, "end": 3.0, "text": "  "},
    {"start": 2.0, "end": 5.0, "text": "  "},
]
result = sc.analyze_cues(blank_but_overlap, settings)
check("空白字幕仍檢查時間軸重疊（結構性問題與文字無關）",
      any(i["title"] == "字幕重疊" for i in result["issues"]),
      str(result["issues"]))
check("counts 含 overlap 欄位", "overlap" in result["counts"])

normal_overlap_result = sc.analyze_cues(simple_overlap, settings)
check("counts 正確統計重疊數",
      normal_overlap_result["counts"]["overlap"] == 1,
      str(normal_overlap_result["counts"]))

# ===== 3. fix_overlaps：一鍵修復 =====
fixed_simple, n1 = sc.fix_overlaps(simple_overlap)
check("簡單重疊修復：截短較早一句",
      fixed_simple[0]["end"] == 2.0 and fixed_simple[1]["start"] == 2.0,
      str(fixed_simple))
check("簡單重疊修復次數正確", n1 == 1)
check("原始 cues 不被修改（不可變）", simple_overlap[0]["end"] == 3.0)

fixed_same, n2 = sc.fix_overlaps(same_start)
check("相同起始時間：較早一句保留極短長度",
      abs(fixed_same[0]["end"] - fixed_same[0]["start"] - 0.05) < 1e-6,
      str(fixed_same))
check("相同起始時間：較晚一句整段順延且時長不變",
      abs((fixed_same[1]["end"] - fixed_same[1]["start"]) - 4.0) < 1e-6,
      str(fixed_same))
check("相同起始時間修復次數正確", n2 == 1)

fixed_none, n3 = sc.fix_overlaps(no_overlap)
check("無重疊時不修改", n3 == 0 and fixed_none == no_overlap)

check("空清單修復不炸", sc.fix_overlaps([]) == ([], 0))

# 未排序輸入：修復後也要正確（依時間序處理，回傳仍保持原始清單順序對應）。
fixed_unsorted, n4 = sc.fix_overlaps(unsorted_cues)
check("未排序輸入修復正確（後段 cue 被截短）",
      fixed_unsorted[1]["end"] == 5.0, str(fixed_unsorted))
check("未排序輸入修復次數正確", n4 == 1)

# 連鎖重疊：三句依序重疊，確認逐一正確消除。
chained = [cue(0.0, 5.0), cue(1.0, 6.0), cue(2.0, 7.0)]
fixed_chained, n5 = sc.fix_overlaps(chained)
check("連鎖重疊全部修復", n5 == 2, str(fixed_chained))
check("連鎖重疊修復後彼此不再重疊",
      fixed_chained[0]["end"] <= fixed_chained[1]["start"] + 1e-6
      and fixed_chained[1]["end"] <= fixed_chained[2]["start"] + 1e-6,
      str(fixed_chained))

# ===== 4. format_subtitle_report 涵蓋重疊訊息 =====
report_text = sc.format_subtitle_report(
    sc.analyze_cues(simple_overlap, settings))
check("報告含重疊項目", "字幕重疊" in report_text, report_text)

# ===== 5. config／CLI／GUI 靜態掃描 =====
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(root, "cli.py"), encoding="utf-8") as fp:
    cli_src = fp.read()
check("cli.py --subcheck 說明提及時間軸重疊", "時間軸重疊" in cli_src)

with open(os.path.join(root, "gui", "subtitle_check_dialog.py"),
          encoding="utf-8") as fp:
    dialog_src = fp.read()
check("對話框有一鍵修復重疊按鈕與 handler",
      "一鍵修復重疊" in dialog_src and "_on_fix_overlap" in dialog_src
      and "fix_overlaps" in dialog_src)
check("對話框無 classic tk.Checkbutton/Radiobutton 殘留",
      "tk.Checkbutton(" not in dialog_src.replace("ttk.Checkbutton(", "")
      and "tk.Radiobutton(" not in dialog_src.replace("ttk.Radiobutton(", ""))

# ===== 6. 真實 CLI 端到端（合成測試媒體＋刻意重疊的匯入字幕檔） =====
import shutil
if shutil.which("ffmpeg"):
    with tempfile.TemporaryDirectory() as tmp:
        clip = os.path.join(tmp, "clip.mp4")
        srt = os.path.join(tmp, "clip.srt")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=8:r=25",
             "-c:v", "libx264", clip], capture_output=True, timeout=60)
        with open(srt, "w", encoding="utf-8") as fp:
            fp.write(
                "1\n00:00:00,000 --> 00:00:03,000\n第一句正常時間\n\n"
                "2\n00:00:02,000 --> 00:00:05,000\n第二句與第一句重疊\n\n"
                "3\n00:00:06,000 --> 00:00:08,000\n第三句正常\n\n"
            )
        env_main = os.path.join(root, "main.py")
        proc = subprocess.run(
            [sys.executable, env_main, "--subs", srt, "--subcheck",
             "--formats", "srt", clip],
            cwd=tmp, capture_output=True, text=True, timeout=120)
        check("實測：CLI --subs --subcheck 執行成功",
              proc.returncode == 0, proc.stdout + proc.stderr)
        report_path = os.path.join(tmp, "clip_字幕健檢.txt")
        check("實測：字幕健檢報告已產生", os.path.exists(report_path))
        if os.path.exists(report_path):
            report_content = open(report_path, encoding="utf-8").read()
            check("實測：報告正確標出重疊",
                  "字幕重疊" in report_content and "1.00 秒" in report_content,
                  report_content)
else:
    print("SKIP 實測（無 ffmpeg）")

print()
if failures:
    print(f"共 {len(failures)} 項失敗：{failures}")
    sys.exit(1)
print("test_v1230 全部通過")
