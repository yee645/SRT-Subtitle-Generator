# -*- coding: utf-8 -*-
"""v1.20.0 新功能測試：字幕健檢（閱讀速度 CPS／行數／顯示時間）＋一鍵延長。"""
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


def cue(start, end, text):
    return {"start": start, "end": end, "text": text}


# ===== 1. CPS 計算 =====
check("CPS 基本計算", sc.compute_cps("一二三四五", 1.0) == 5.0)
check("多行合併計算（不含換行本身）",
      sc.compute_cps("一二三\n四五", 1.0) == 5.0)
check("非正時長回 0", sc.compute_cps("測試", 0.0) == 0.0)
check("負時長回 0", sc.compute_cps("測試", -1.0) == 0.0)

# ===== 2. 設定解析與夾限 =====
s = sc.resolve_subcheck_settings(None)
check("預設值", s == sc.DEFAULT_SUBCHECK, str(s))
s2 = sc.resolve_subcheck_settings({"subtitlecheck": {
    "cps_limit": 999, "min_duration": -1, "max_lines": "bad",
    "max_chars_per_line": 1}})
check("cps 夾上限", s2["cps_limit"] == 25.0)
check("min_duration 夾下限", s2["min_duration"] == 0.3)
check("max_lines 非數值回預設", s2["max_lines"] == sc.DEFAULT_SUBCHECK["max_lines"])
check("max_chars_per_line 夾下限", s2["max_chars_per_line"] == 10)

# ===== 3. analyze_cues：各項檢查觸發 =====
settings = sc.resolve_subcheck_settings(None)  # cps 17 / min_dur 0.8 / lines 2 / chars 21

# 正常句子：不觸發任何項目
normal = [cue(0.0, 2.0, "今天天氣真的很不錯")]
r = sc.analyze_cues(normal, settings)
check("正常句子零問題", r["issues"] == [], str(r))

# CPS 過快（BAD：超過門檻 1.3 倍）
fast_bad = [cue(0.0, 1.0, "一二三四五六七八九十一二三四五六七八九十一二三四五")]  # 25 字/1秒
r = sc.analyze_cues(fast_bad, settings)
check("CPS 嚴重過快標記 BAD",
      any(i["title"] == "閱讀速度過快" and i["level"] == sc.LEVEL_BAD
          for i in r["issues"]), str(r["issues"]))

# CPS 輕微過快（WARN：超過門檻但未達 1.3 倍）
fast_warn = [cue(0.0, 1.0, "一二三四五六七八九十一二三四五六七八")]  # 18 字/1秒，門檻17
r = sc.analyze_cues(fast_warn, settings)
check("CPS 輕微過快標記 WARN",
      any(i["title"] == "閱讀速度過快" and i["level"] == sc.LEVEL_WARN
          for i in r["issues"]), str(r["issues"]))

# 顯示過短
short_dur = [cue(0.0, 0.3, "嗯")]
r = sc.analyze_cues(short_dur, settings)
check("顯示過短標記", any(i["title"] == "顯示時間過短" for i in r["issues"]))

# 行數過多
many_lines = [cue(0.0, 3.0, "第一行\n第二行\n第三行")]
r = sc.analyze_cues(many_lines, settings)
check("行數過多標記", any(i["title"] == "行數過多" for i in r["issues"]))

# 單行過長
long_line = [cue(0.0, 5.0, "這是一句非常非常非常非常非常非常非常長的字幕內容超過門檻")]
r = sc.analyze_cues(long_line, settings)
check("單行過長標記", any(i["title"] == "單行過長" for i in r["issues"]))

# 空文字不檢查
blank = [cue(0.0, 0.1, "   ")]
r = sc.analyze_cues(blank, settings)
check("空白字幕不列入檢查", r["issues"] == [] and r["total"] == 1)

# 索引正確且從 0 起算
multi = [cue(0.0, 2.0, "正常句子在此處"), cue(2.0, 2.3, "嗯")]
r = sc.analyze_cues(multi, settings)
check("問題句子索引正確",
      any(i["index"] == 1 for i in r["issues"]), str(r["issues"]))

# ===== 4. format_subtitle_report =====
clean_report = sc.format_subtitle_report(sc.analyze_cues(normal, settings))
check("無問題報告含通過字樣", "全部通過" in clean_report)
issue_report = sc.format_subtitle_report(sc.analyze_cues(fast_bad, settings))
check("有問題報告含結論行", "結論：" in issue_report)

# ===== 5. fix_cue_durations：一鍵延長 =====
# 有空檔可延長
gapped = [cue(0.0, 1.0, "一二三四五六七八九十一二三四五六七八九十一二三四五"),  # 需要約 1.47s
         cue(3.0, 4.0, "下一句字幕內容")]
fixed_cues, n = sc.fix_cue_durations(gapped, settings)
check("有空檔時延長成功", n == 1, str(fixed_cues))
check("延長後不超過下一句開始前的間隔",
      fixed_cues[0]["end"] <= gapped[1]["start"] - sc._EXTEND_GAP + 1e-6)
check("延長後確實變長", fixed_cues[0]["end"] > gapped[0]["end"])
check("原始 cues 不被修改（不可變）", gapped[0]["end"] == 1.0)

# 無空檔（下一句緊接）時不強行延長
tight = [cue(0.0, 1.0, "一二三四五六七八九十一二三四五六七八九十一二三四五"),
        cue(1.01, 2.0, "緊接著的下一句")]
fixed_tight, n2 = sc.fix_cue_durations(tight, settings)
check("無空檔不強行延長", n2 == 0 and fixed_tight[0]["end"] == 1.0, str(fixed_tight))

# 已符合門檻的句子不動
already_ok = [cue(0.0, 3.0, "這句話顯示時間很充足")]
fixed_ok, n3 = sc.fix_cue_durations(already_ok, settings)
check("已合格句子不變動", n3 == 0 and fixed_ok[0]["end"] == 3.0)

# 最後一句無下一句限制，可自由延長到所需時長
last_cue = [cue(0.0, 2.0, "正常句子"),
           cue(2.0, 3.0, "一二三四五六七八九十一二三四五六七八九十一二三四五")]
fixed_last, n4 = sc.fix_cue_durations(last_cue, settings)
check("最後一句可延長到所需時長", n4 == 1
      and fixed_last[1]["end"] > 3.0, str(fixed_last))

# 空清單不炸
check("空清單不炸", sc.analyze_cues([], settings)["issues"] == [])
check("空清單延長不炸", sc.fix_cue_durations([], settings) == ([], 0))

# ===== 6. GUI／config 靜態掃描 =====
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(root, "gui", "subtitle_check_dialog.py"),
          encoding="utf-8") as fp:
    dialog_src = fp.read()
check("對話框無 classic tk.Checkbutton/Radiobutton 殘留",
      "tk.Checkbutton(" not in dialog_src.replace("ttk.Checkbutton(", "")
      and "tk.Radiobutton(" not in dialog_src.replace("ttk.Radiobutton(", ""))

with open(os.path.join(root, "gui", "app.py"), encoding="utf-8") as fp:
    app_src = fp.read()
check("app.py 有字幕健檢按鈕與 handler",
      "字幕健檢" in app_src and "_open_subtitle_check_dialog" in app_src)

from config import DEFAULT_CONFIG
check("config 預設含 subtitlecheck 區",
      DEFAULT_CONFIG["subtitlecheck"]["cps_limit"] == 17.0)

with open(os.path.join(root, "cli.py"), encoding="utf-8") as fp:
    cli_src = fp.read()
check("cli.py 有 --subcheck 旗標", "--subcheck" in cli_src)

# ===== 7. 真實 CLI 端到端（ffmpeg 免必要，但用於合成測試媒體＋燒錄） =====
import shutil
if shutil.which("ffmpeg"):
    with tempfile.TemporaryDirectory() as tmp:
        clip = os.path.join(tmp, "clip.mp4")
        srt = os.path.join(tmp, "clip.srt")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=6",
             "-c:v", "libx264", clip], capture_output=True, timeout=60)
        # 刻意寫一份「過快」的字幕檔（第一句嚴重超 CPS）。
        with open(srt, "w", encoding="utf-8") as fp:
            fp.write(
                "1\n00:00:00,000 --> 00:00:01,000\n"
                "一二三四五六七八九十一二三四五六七八九十一二三四五\n\n"
                "2\n00:00:02,000 --> 00:00:05,000\n"
                "這句字幕顯示時間充足不會有問題\n\n"
            )
        env_main = os.path.join(root, "main.py")
        proc = subprocess.run(
            [sys.executable, env_main, "--subs", srt, "--subcheck",
             "--formats", "srt", clip],
            cwd=tmp, capture_output=True, text=True, timeout=120)
        check("實測：CLI --subs --subcheck 執行成功",
              proc.returncode == 0, proc.stdout + proc.stderr)
        report_path = os.path.join(tmp, "clip_字幕健檢.txt")
        check("實測：字幕健檢報告檔案已產生", os.path.exists(report_path))
        if os.path.exists(report_path):
            report_text = open(report_path, encoding="utf-8").read()
            check("實測：報告內容標出過快句子", "閱讀速度過快" in report_text,
                  report_text)
else:
    print("SKIP 實測（無 ffmpeg）")

print()
if failures:
    print(f"共 {len(failures)} 項失敗：{failures}")
    sys.exit(1)
print("test_v1200 全部通過")
