# -*- coding: utf-8 -*-
"""v1.26.0 新功能測試：影片畫質健檢新增凍結畫面偵測。"""
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

from subtitle import videocheck
from subtitle.audiocheck import LEVEL_GOOD, LEVEL_WARN

# ===== 1. 設定解析與夾限 =====
s = videocheck.resolve_videocheck_settings(None)
check("預設凍結判定秒數 1.0", s["freeze_min_seconds"] == 1.0, str(s))
s2 = videocheck.resolve_videocheck_settings(
    {"videocheck": {"freeze_min_seconds": 99.0}})
check("凍結判定秒數夾上限 5.0", s2["freeze_min_seconds"] == 5.0, str(s2))
s3 = videocheck.resolve_videocheck_settings(
    {"videocheck": {"freeze_min_seconds": 0.01}})
check("凍結判定秒數夾下限 0.5", s3["freeze_min_seconds"] == 0.5, str(s3))
s4 = videocheck.resolve_videocheck_settings(
    {"videocheck": {"freeze_min_seconds": "bad"}})
check("非數值回預設", s4["freeze_min_seconds"] == 1.0, str(s4))

# ===== 2. parse_dead_air：freezedetect 輸出解析 =====
freeze_sample = """
[freezedetect @ 0x1] lavfi.freezedetect.freeze_start: 2
[freezedetect @ 0x1] lavfi.freezedetect.freeze_duration: 2
[freezedetect @ 0x1] lavfi.freezedetect.freeze_end: 4
"""
parsed = videocheck.parse_dead_air(freeze_sample, 10.0)
check("解析出一段凍結畫面", len(parsed["freezes"]) == 1, str(parsed))
check("凍結起訖秒數正確",
      parsed["freezes"][0]["start"] == 2.0
      and parsed["freezes"][0]["end"] == 4.0
      and parsed["freezes"][0]["duration"] == 2.0, str(parsed))

# 凍結一路延伸到檔尾（沒有 freeze_end 行）。
freeze_to_end = """
[freezedetect @ 0x1] lavfi.freezedetect.freeze_start: 7
"""
parsed_end = videocheck.parse_dead_air(freeze_to_end, 10.0)
check("凍結延伸到檔尾時正確補上結尾時間",
      len(parsed_end["freezes"]) == 1
      and parsed_end["freezes"][0]["end"] == 10.0, str(parsed_end))

# 無凍結時回空清單，不影響既有的頭尾廢秒解析。
clean = videocheck.parse_dead_air("", 10.0)
check("乾淨素材凍結清單為空", clean["freezes"] == [], str(clean))
check("乾淨素材其餘欄位仍全零",
      all(v == 0.0 for k, v in clean.items() if k != "freezes"), str(clean))

# ===== 3. config／GUI 靜態掃描 =====
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from config import DEFAULT_CONFIG
check("config 預設含 freeze_min_seconds",
      DEFAULT_CONFIG["videocheck"].get("freeze_min_seconds") == 1.0,
      str(DEFAULT_CONFIG.get("videocheck")))

with open(os.path.join(root, "gui", "audiocheck_dialog.py"),
          encoding="utf-8") as fp:
    dialog_src = fp.read()
check("對話框有凍結判定秒數設定",
      "凍結判定秒數" in dialog_src and "freeze_min_var" in dialog_src)
check("對話框無 classic tk.Checkbutton 殘留",
      "tk.Checkbutton(" not in dialog_src.replace("ttk.Checkbutton(", ""))

# ===== 4. 真實 ffmpeg 端到端：合成含真實凍結片段的素材 =====
if videocheck.ffmpeg_available():
    with tempfile.TemporaryDirectory() as tmp:
        # 0~2s 正常動態畫面、2~4s 畫面凍結（複製單一格）、4~6s 恢復正常，
        # 全程有連續音訊（模擬「畫面卡住但聲音仍在播放」的錄製瑕疵）。
        frozen_clip = os.path.join(tmp, "frozen.mp4")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc=size=640x480:rate=25:duration=6",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
             "-filter_complex",
             "[0:v]trim=0:2,setpts=PTS-STARTPTS[a];"
             "[0:v]trim=2:2.04,setpts=PTS-STARTPTS,"
             "tpad=stop_mode=clone:stop_duration=1.96[b];"
             "[0:v]trim=4:6,setpts=PTS-STARTPTS[c];"
             "[a][b][c]concat=n=3:v=1:a=0[vout]",
             "-map", "[vout]", "-map", "1:a",
             "-c:v", "libx264", "-c:a", "aac", "-shortest", frozen_clip],
            capture_output=True, timeout=60)

        result = videocheck.run_video_check(frozen_clip, None)
        titles = [f for f in result["findings"] if f["title"] == "凍結畫面"]
        check("實測：偵測到凍結畫面段落",
              len(titles) >= 1 and titles[0]["level"] == LEVEL_WARN,
              str(titles))
        check("實測：凍結時間點約落在 2~4 秒",
              titles and "2." in titles[0]["detail"], str(titles))

        # CLI 端到端：--videocheck 報告自動涵蓋凍結畫面（無需新增旗標）。
        env_main = os.path.join(root, "main.py")
        proc = subprocess.run(
            [sys.executable, env_main, "--videocheck", frozen_clip],
            cwd=tmp, capture_output=True, text=True, timeout=120)
        check("實測：CLI --videocheck 執行成功", proc.returncode == 0,
              proc.stdout + proc.stderr)
        report_path = os.path.join(tmp, "frozen_影片健檢.txt")
        check("實測：CLI 影片健檢報告已產生", os.path.exists(report_path))
        if os.path.exists(report_path):
            report_text = open(report_path, encoding="utf-8").read()
            check("實測：CLI 報告含凍結畫面段落", "凍結畫面" in report_text,
                  report_text)

        # 乾淨素材（無凍結）：應顯示為正常，不誤判。
        clean_clip = os.path.join(tmp, "clean.mp4")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi",
             "-i", "color=c=gray:s=1920x1080:d=3,"
                   "noise=alls=60:allf=t+u,format=yuv420p",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
             "-c:v", "libx264", "-b:v", "10M", "-c:a", "aac",
             clean_clip], capture_output=True, timeout=60)
        result_clean = videocheck.run_video_check(clean_clip, None)
        titles_clean = {f["title"]: f["level"]
                        for f in result_clean["findings"]}
        check("實測：乾淨素材凍結畫面判定為正常（無誤判）",
              titles_clean.get("凍結畫面") == LEVEL_GOOD, str(titles_clean))
else:
    print("SKIP 實測（無 ffmpeg）")

print()
if failures:
    print(f"共 {len(failures)} 項失敗：{failures}")
    sys.exit(1)
print("test_v1260 全部通過")
