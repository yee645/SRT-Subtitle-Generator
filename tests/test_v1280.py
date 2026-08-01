# -*- coding: utf-8 -*-
"""v1.28.0 新功能測試：畫面曝光與色偏健檢。"""
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

from subtitle import colorcheck as cc
from subtitle.audiocheck import LEVEL_GOOD, LEVEL_WARN

# ===== 1. 設定解析與夾限 =====
s = cc.resolve_colorcheck_settings(None)
check("預設值", s == cc.DEFAULT_COLORCHECK, str(s))
s2 = cc.resolve_colorcheck_settings({"colorcheck": {
    "sample_count": 99, "dark_luma": 1, "bright_luma": 999,
    "cast_threshold": 999}})
check("sample_count 夾上限 12", s2["sample_count"] == 12, str(s2))
check("dark_luma 夾下限 20", s2["dark_luma"] == 20.0, str(s2))
check("bright_luma 夾上限 240", s2["bright_luma"] == 240.0, str(s2))
check("cast_threshold 夾上限 25", s2["cast_threshold"] == 25.0, str(s2))
s3 = cc.resolve_colorcheck_settings({"colorcheck": {"sample_count": "bad"}})
check("非數值回預設", s3["sample_count"] == 6, str(s3))

# ===== 2. _sample_times：均勻取樣邏輯 =====
times = cc._sample_times(60.0, 6)
check("取樣數量正確", len(times) == 6, str(times))
check("取樣避開頭尾", times[0] > 0 and times[-1] < 60.0, str(times))
check("取樣時間遞增", times == sorted(times), str(times))
check("零時長回空清單", cc._sample_times(0.0, 6) == [])
single = cc._sample_times(10.0, 1)
check("取樣數 1 時回單一時間點", len(single) == 1, str(single))

# ===== 3. _cast_description：色偏方向判讀 =====
check("U 偏高判為偏藍", cc._cast_description(150, 128, 10) == "偏藍")
check("U 偏低判為偏黃", cc._cast_description(100, 128, 10) == "偏黃")
check("V 偏高判為偏紅洋紅", cc._cast_description(128, 150, 10) == "偏紅／洋紅")
check("V 偏低判為偏綠", cc._cast_description(128, 100, 10) == "偏綠")
check("同時偏移合併描述",
      cc._cast_description(100, 150, 10) == "偏黃、偏紅／洋紅",
      cc._cast_description(100, 150, 10))
check("在門檻內視為中性", cc._cast_description(130, 126, 10) is None)

# ===== 4. format_color_report：各分支文字 =====
empty_report = cc.format_color_report({"issues": []})
check("無 issues 時提示略過", "略過" in empty_report, empty_report)
good_report = cc.format_color_report({"issues": [
    {"level": LEVEL_GOOD, "title": "曝光", "detail": "平均亮度 126/255，正常"},
    {"level": LEVEL_GOOD, "title": "色偏", "detail": "色調接近中性，正常"}]})
check("正常時無警告符號", "⚠" not in good_report, good_report)
warn_report = cc.format_color_report({"issues": [
    {"level": LEVEL_WARN, "title": "曝光", "detail": "平均亮度 16/255，偏暗",
     "advice": "提高亮度"}]})
check("異常時含警告符號與建議", "⚠" in warn_report and "建議：提高亮度" in warn_report,
      warn_report)

# ===== 5. 安全防呆（不需真的跑 ffmpeg 的錯誤路徑） =====
try:
    cc.analyze_color("不存在.mp4")
    check("找不到檔案時報錯", False)
except FileNotFoundError:
    check("找不到檔案時報錯", True)

# ===== 6. config／CLI／GUI 靜態掃描 =====
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from config import DEFAULT_CONFIG
check("config 預設含 colorcheck 區",
      DEFAULT_CONFIG.get("colorcheck") == cc.DEFAULT_COLORCHECK,
      str(DEFAULT_CONFIG.get("colorcheck")))

with open(os.path.join(root, "cli.py"), encoding="utf-8") as fp:
    cli_src = fp.read()
check("cli.py 有 --colorcheck 旗標", "--colorcheck" in cli_src)

with open(os.path.join(root, "gui", "audiocheck_dialog.py"),
          encoding="utf-8") as fp:
    dialog_src = fp.read()
check("對話框有色彩健檢設定與整合呼叫",
      "過暗門檻" in dialog_src and "analyze_color" in dialog_src
      and "format_color_report" in dialog_src)
check("對話框無 classic tk.Checkbutton/Radiobutton 殘留",
      "tk.Checkbutton(" not in dialog_src.replace("ttk.Checkbutton(", "")
      and "tk.Radiobutton(" not in dialog_src.replace(
          "ttk.Radiobutton(", ""))

# ===== 7. 真實 ffmpeg 端到端 =====
if cc.ffmpeg_available():
    with tempfile.TemporaryDirectory() as tmp:
        # 7a. 明顯暖色偏（模擬白平衡沒調好）。
        warm_clip = os.path.join(tmp, "warm.mp4")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=0xC8B496:s=320x240:d=4",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", warm_clip],
            capture_output=True, timeout=30)
        result = cc.analyze_color(warm_clip, cc.resolve_colorcheck_settings())
        check("實測：偵測到取樣畫面", len(result["samples"]) > 0,
              str(result["samples"]))
        titles = {i["title"]: i for i in result["issues"]}
        check("實測：暖色偏被正確偵測",
              titles.get("色偏", {}).get("level") == LEVEL_WARN
              and "黃" in titles["色偏"]["detail"], str(titles))

        # 7b. 明顯偏暗（曝光不足）。
        dark_clip = os.path.join(tmp, "dark.mp4")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=black:s=320x240:d=4",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", dark_clip],
            capture_output=True, timeout=30)
        dark_result = cc.analyze_color(
            dark_clip, cc.resolve_colorcheck_settings())
        dark_titles = {i["title"]: i for i in dark_result["issues"]}
        check("實測：曝光不足被正確偵測",
              dark_titles.get("曝光", {}).get("level") == LEVEL_WARN
              and "偏暗" in dark_titles["曝光"]["detail"], str(dark_titles))

        # 7c. 中性灰：不應誤判（防止假陽性）。
        normal_clip = os.path.join(tmp, "normal.mp4")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=gray:s=320x240:d=4",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", normal_clip],
            capture_output=True, timeout=30)
        normal_result = cc.analyze_color(
            normal_clip, cc.resolve_colorcheck_settings())
        normal_titles = {i["title"]: i for i in normal_result["issues"]}
        check("實測：正常素材無誤判（曝光/色偏皆判定正常）",
              normal_titles.get("曝光", {}).get("level") == LEVEL_GOOD
              and normal_titles.get("色偏", {}).get("level") == LEVEL_GOOD,
              str(normal_titles))

        # 7d. 純音訊檔（無影像串流）：優雅報錯，不當機。
        audio_only = os.path.join(tmp, "audio.mp3")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
             "-c:a", "mp3", audio_only],
            capture_output=True, timeout=30)
        try:
            cc.analyze_color(audio_only)
            check("實測：純音訊檔報錯", False)
        except ValueError as exc:
            check("實測：純音訊檔報錯", "影像串流" in str(exc), str(exc))

        # 7e. CLI 端到端。
        env_main = os.path.join(root, "main.py")
        proc = subprocess.run(
            [sys.executable, env_main, "--colorcheck", warm_clip],
            cwd=tmp, capture_output=True, text=True, timeout=120)
        check("實測：CLI --colorcheck 執行成功", proc.returncode == 0,
              proc.stdout + proc.stderr)
        report_path = os.path.join(tmp, "warm_色彩健檢.txt")
        check("實測：CLI 色彩健檢報告已產生", os.path.exists(report_path))
        if os.path.exists(report_path):
            report_text = open(report_path, encoding="utf-8").read()
            check("實測：CLI 報告含色偏段落", "色偏" in report_text, report_text)
else:
    print("SKIP 實測（無 ffmpeg）")

print()
if failures:
    print(f"共 {len(failures)} 項失敗：{failures}")
    sys.exit(1)
print("test_v1280 全部通過")
