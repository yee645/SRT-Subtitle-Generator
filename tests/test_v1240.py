# -*- coding: utf-8 -*-
"""v1.24.0 新功能測試：分段音量一致性分析與一鍵拉平。"""
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

from subtitle import volumeconsistency as vc

# ===== 1. 設定解析與夾限 =====
s = vc.resolve_volume_consistency_settings(None)
check("預設值", s == vc.DEFAULT_VOLUME_CONSISTENCY, str(s))
s2 = vc.resolve_volume_consistency_settings({"volumeconsistency": {
    "segment_seconds": 1.0, "deviation_lu": 99.0}})
check("segment_seconds 夾下限", s2["segment_seconds"] == 10.0)
check("deviation_lu 夾上限", s2["deviation_lu"] == 8.0)
s3 = vc.resolve_volume_consistency_settings(
    {"volumeconsistency": {"segment_seconds": "bad"}})
check("非數值回預設", s3["segment_seconds"]
      == vc.DEFAULT_VOLUME_CONSISTENCY["segment_seconds"])

# ===== 2. build_segments：固定長度分段＋合併過短尾段 =====
check("整除時分段數正確",
      vc.build_segments(60.0, 20.0) == [(0.0, 20.0), (20.0, 40.0),
                                        (40.0, 60.0)])
check("尾段過短併入前一段",
      vc.build_segments(45.0, 20.0) == [(0.0, 20.0), (20.0, 45.0)])
check("尾段不太短時獨立成段",
      vc.build_segments(50.0, 20.0) == [(0.0, 20.0), (20.0, 40.0),
                                        (40.0, 50.0)])
check("時長為 0 回空清單", vc.build_segments(0.0, 20.0) == [])
check("短於一段時仍回傳單一段",
      vc.build_segments(8.0, 20.0) == [(0.0, 8.0)])

# ===== 3. format_volume_consistency_report =====
no_seg_report = vc.format_volume_consistency_report(
    {"segments": [], "median_lufs": None, "issues": []})
check("無分段時提示過短", "過短" in no_seg_report, no_seg_report)

no_median_report = vc.format_volume_consistency_report(
    {"segments": [{"start": 0, "end": 20, "lufs": None}],
     "median_lufs": None, "issues": []})
check("無中位數時提示靜音", "靜音" in no_median_report, no_median_report)

clean_report = vc.format_volume_consistency_report({
    "segments": [{"start": 0, "end": 20, "lufs": -20.0},
                {"start": 20, "end": 40, "lufs": -20.5}],
    "median_lufs": -20.2, "issues": []})
check("無落差時顯示一致", "音量一致" in clean_report, clean_report)

issue_report = vc.format_volume_consistency_report({
    "segments": [{"start": 0, "end": 20, "lufs": -20.0},
                {"start": 20, "end": 40, "lufs": -35.0}],
    "median_lufs": -20.0,
    "issues": [{"start": 20, "end": 40, "lufs": -35.0, "diff": -15.0}]})
check("有落差時標出偏小聲", "偏小聲" in issue_report, issue_report)
issue_report2 = vc.format_volume_consistency_report({
    "segments": [{"start": 0, "end": 20, "lufs": -5.0},
                {"start": 20, "end": 40, "lufs": -20.0}],
    "median_lufs": -20.0,
    "issues": [{"start": 0, "end": 20, "lufs": -5.0, "diff": 15.0}]})
check("正向落差標出偏大聲", "偏大聲" in issue_report2, issue_report2)

# ===== 4. suggest_output_path =====
check("輸出檔名加後綴",
      vc.suggest_output_path("影片.mp4") == "影片_音量平衡.mp4")
check("無副檔名補 .mp4",
      vc.suggest_output_path("影片") == "影片_音量平衡.mp4")

# ===== 5. 安全防呆（不需真的跑 ffmpeg 的錯誤路徑） =====
try:
    vc.analyze_volume_consistency("不存在.mp4")
    check("找不到檔案時報錯", False)
except FileNotFoundError:
    check("找不到檔案時報錯", True)

try:
    vc.fix_volume_consistency("不存在.mp4", {"issues": [{}], "segments": [{}],
                              "median_lufs": -20.0}, "out.mp4")
    check("修復時找不到檔案報錯", False)
except FileNotFoundError:
    check("修復時找不到檔案報錯", True)

with tempfile.TemporaryDirectory() as tmp:
    fake_src = os.path.join(tmp, "fake.mp4")
    open(fake_src, "wb").write(b"x")
    try:
        vc.fix_volume_consistency(
            fake_src, {"issues": [], "segments": [], "median_lufs": -20.0},
            os.path.join(tmp, "o.mp4"))
        check("無落差時修復報錯", False)
    except ValueError as exc:
        check("無落差時修復報錯", "沒有偵測到" in str(exc), str(exc))

    try:
        vc.fix_volume_consistency(
            fake_src, {"issues": [{"start": 0, "end": 1, "lufs": -30}],
                      "segments": [], "median_lufs": None},
            os.path.join(tmp, "o2.mp4"))
        check("無中位數基準時修復報錯", False)
    except ValueError as exc:
        check("無中位數基準時修復報錯", "響度基準" in str(exc), str(exc))

# ===== 6. config／CLI／GUI 靜態掃描 =====
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from config import DEFAULT_CONFIG
check("config 預設含 volumeconsistency 區",
      DEFAULT_CONFIG["volumeconsistency"] == vc.DEFAULT_VOLUME_CONSISTENCY,
      str(DEFAULT_CONFIG.get("volumeconsistency")))

with open(os.path.join(root, "cli.py"), encoding="utf-8") as fp:
    cli_src = fp.read()
check("cli.py 有 --volumecheck 旗標", "--volumecheck" in cli_src)
check("cli.py 有 --volumefix 旗標", "--volumefix" in cli_src)

with open(os.path.join(root, "gui", "audiocheck_dialog.py"),
          encoding="utf-8") as fp:
    dialog_src = fp.read()
check("對話框有拉平音量落差按鈕與 handler",
      "拉平音量落差" in dialog_src and "_on_volume_fix" in dialog_src
      and "fix_volume_consistency" in dialog_src)
check("對話框無 classic tk.Radiobutton 殘留",
      "tk.Radiobutton(" not in dialog_src.replace("ttk.Radiobutton(", ""))

with open(os.path.join(root, "subtitle", "errors.py"),
          encoding="utf-8") as fp:
    errors_src = fp.read()
check("errors.py 已註冊「影片音量調整失敗」的友善錯誤分類",
      "影片音量調整失敗" in errors_src)

# ===== 7. 真實 ffmpeg 端到端：合成音量忽大忽小的素材，分析＋修復＋驗證改善 =====
import shutil
if shutil.which("ffmpeg"):
    with tempfile.TemporaryDirectory() as tmp:
        clip = os.path.join(tmp, "uneven.mp4")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=60:r=25",
             "-f", "lavfi", "-i",
             "sine=frequency=440:duration=60:sample_rate=44100",
             "-filter_complex",
             "[1:a]volume='if(between(t,20,40),0.05,1)':eval=frame[aout]",
             "-map", "0:v", "-map", "[aout]",
             "-c:v", "libx264", "-c:a", "aac", clip],
            capture_output=True, timeout=60)

        settings = vc.resolve_volume_consistency_settings(None)
        result = vc.analyze_volume_consistency(clip, settings)
        check("實測：偵測到 3 個分段", len(result["segments"]) == 3,
              str(result["segments"]))
        check("實測：找出音量落差過大的中段", len(result["issues"]) == 1
              and result["issues"][0]["start"] == 20.0, str(result["issues"]))
        check("實測：落差為明顯偏小聲",
              result["issues"][0]["diff"] < -10.0, str(result["issues"]))

        report_text = vc.format_volume_consistency_report(result)
        check("實測：報告標出落差", "偏小聲" in report_text, report_text)

        fixed_out = os.path.join(tmp, "fixed.mp4")
        vc.fix_volume_consistency(clip, result, fixed_out)
        check("實測：修復輸出檔案已產生", os.path.exists(fixed_out))

        dur_proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", fixed_out],
            capture_output=True, text=True, timeout=30)
        try:
            out_dur = float(dur_proc.stdout.strip())
        except ValueError:
            out_dur = 0.0
        check("實測：輸出長度與原始相同（未裁切任何內容）",
              abs(out_dur - 60.0) < 0.5, f"out_dur={out_dur}")

        # 重新分析修復後的檔案，確認落差已消除。
        result2 = vc.analyze_volume_consistency(fixed_out, settings)
        check("實測：修復後不再有音量落差問題", result2["issues"] == [],
              str(result2["issues"]))

        # CLI 端到端。
        env_main = os.path.join(root, "main.py")
        proc = subprocess.run(
            [sys.executable, env_main, "--volumecheck", "--volumefix", clip],
            cwd=tmp, capture_output=True, text=True, timeout=120)
        check("實測：CLI --volumecheck --volumefix 執行成功",
              proc.returncode == 0, proc.stdout + proc.stderr)
        report_path = os.path.join(tmp, "uneven_音量一致性.txt")
        check("實測：CLI 音量一致性報告已產生", os.path.exists(report_path))
        volume_out = os.path.join(tmp, "uneven_音量平衡.mp4")
        check("實測：CLI 音量平衡影片已產生", os.path.exists(volume_out))
else:
    print("SKIP 實測（無 ffmpeg）")

print()
if failures:
    print(f"共 {len(failures)} 項失敗：{failures}")
    sys.exit(1)
print("test_v1240 全部通過")
