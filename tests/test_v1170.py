# -*- coding: utf-8 -*-
"""v1.17.0 新功能測試：上片前影片畫質健檢、一鍵去頭尾。"""
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
from subtitle.audiocheck import LEVEL_BAD, LEVEL_GOOD, LEVEL_WARN

# ===== 1. YouTube 建議位元率表 =====
check("1080p30 → 8", videocheck.recommended_bitrate_mbps(1080, 30.0) == 8.0)
check("1080p60 → 12", videocheck.recommended_bitrate_mbps(1080, 60.0) == 12.0)
check("4K30 → 35", videocheck.recommended_bitrate_mbps(2160, 30.0) == 35.0)
check("720p30 → 5", videocheck.recommended_bitrate_mbps(720, 29.97) == 5.0)
check("480p → 2.5", videocheck.recommended_bitrate_mbps(480, 30.0) == 2.5)
check("2K60 → 24", videocheck.recommended_bitrate_mbps(1440, 59.94) == 24.0)

# ===== 2. 設定解析與夾限 =====
s = videocheck.resolve_videocheck_settings(None)
check("預設值", s == videocheck.DEFAULT_VIDEOCHECK, str(s))
s2 = videocheck.resolve_videocheck_settings({"videocheck": {
    "bitrate_margin": 9.0, "dead_air_db": 0, "head_max_seconds": "bad"}})
check("夾限與容錯", s2["bitrate_margin"] == 2.0
      and s2["dead_air_db"] == -25.0
      and s2["head_max_seconds"] == 1.0, str(s2))

# ===== 3. blackdetect / silencedetect 解析 =====
stderr_sample = """
[silencedetect @ 0x1] silence_start: 0
[silencedetect @ 0x1] silence_end: 2.1 | silence_duration: 2.1
[blackdetect @ 0x2] black_start:0 black_end:1.8 black_duration:1.8
[silencedetect @ 0x1] silence_start: 8.5
"""
parsed = videocheck.parse_dead_air(stderr_sample, 10.0)
check("開頭靜音 2.1", parsed["head_silence"] == 2.1, str(parsed))
check("開頭黑畫面 1.8", parsed["head_black"] == 1.8, str(parsed))
check("結尾靜音延伸到檔尾", abs(parsed["tail_silence"] - 1.5) < 1e-9,
      str(parsed))
check("結尾無黑畫面", parsed["tail_black"] == 0.0)
# 無廢秒素材
clean = videocheck.parse_dead_air("", 10.0)
check("乾淨素材全零", all(v == 0.0 for v in clean.values()))

# 廢秒中的短暫聲響（相機提示音等）要橋接，不可低估廢秒長度
# （實測 Big Buck Bunny 素材曾因 0.1 秒斷點把 2.2 秒廢秒低估成 1.07 秒）。
blip_sample = """
[silencedetect @ 0x1] silence_start: 0
[silencedetect @ 0x1] silence_end: 1.07 | silence_duration: 1.07
[silencedetect @ 0x1] silence_start: 1.17
[silencedetect @ 0x1] silence_end: 2.22 | silence_duration: 1.05
"""
bridged = videocheck.parse_dead_air(blip_sample, 8.0)
check("短暫聲響橋接後廢秒完整", bridged["head_silence"] == 2.22,
      str(bridged))
# 空隙夠長（> 0.35 秒）就不是同一段廢秒，不可誤併
long_gap = """
[silencedetect @ 0x1] silence_start: 0
[silencedetect @ 0x1] silence_end: 1.0 | silence_duration: 1.0
[silencedetect @ 0x1] silence_start: 2.0
[silencedetect @ 0x1] silence_end: 3.0 | silence_duration: 1.0
"""
apart = videocheck.parse_dead_air(long_gap, 8.0)
check("長空隙不誤併", apart["head_silence"] == 1.0, str(apart))

# ===== 4. 修剪建議 =====
sug = videocheck.suggest_trim(
    {"head_silence": 2.1, "head_black": 1.8,
     "tail_silence": 0.4, "tail_black": 0.0},
    videocheck.resolve_videocheck_settings(None))
check("頭超門檻建議修剪（留緩衝）", abs(sug[0] - 1.85) < 1e-9, str(sug))
check("尾未超門檻不修剪", sug[1] == 0.0, str(sug))
check("空偵測回零", videocheck.suggest_trim(None) == (0.0, 0.0))

# ===== 5. 輸出命名與錯誤分類 =====
check("修剪版命名", videocheck.suggest_output_path("a/b.mp4")
      == "a/b_修剪.mp4")
from subtitle.errors import describe_exception
err = describe_exception(RuntimeError("影片修剪失敗：some stderr"))
check("修剪失敗歸入 ffmpeg 類", "影音處理（ffmpeg）執行失敗" in str(err))

# ===== 6. GUI 靜態掃描 =====
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(root, "gui", "audiocheck_dialog.py"),
           encoding="utf-8").read()
check("健檢視窗含修剪列與畫質門檻",
      "輸出修剪版" in src and "bitrate_margin" in src)
check("無 classic tk.Checkbutton 殘留",
      "tk.Checkbutton(" not in src.replace("ttk.Checkbutton(", ""))
from config import DEFAULT_CONFIG
check("config 含 videocheck 區", "videocheck" in DEFAULT_CONFIG
      and DEFAULT_CONFIG["videocheck"]["bitrate_margin"] == 1.0)

# ===== 7. 真實 ffmpeg 端到端 =====
if videocheck.ffmpeg_available():
    with tempfile.TemporaryDirectory() as tmp:
        # 有問題的素材：低位元率 720p、開頭 2 秒黑畫面＋靜音、結尾 2 秒靜音。
        bad_clip = os.path.join(tmp, "bad.mp4")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi",
             "-i", "color=c=black:s=1280x720:d=2,format=yuv420p",
             "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=6",
             "-f", "lavfi", "-i",
             "sine=frequency=440:duration=4,adelay=2000|2000,apad",
             "-filter_complex",
             "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p[v]",
             "-map", "[v]", "-map", "2:a",
             "-c:v", "libx264", "-b:v", "300k", "-c:a", "aac",
             "-t", "8", bad_clip], capture_output=True, timeout=180)
        result = videocheck.run_video_check(bad_clip, None)
        titles = {f["title"]: f["level"] for f in result["findings"]}
        check("實測：低位元率被抓（bad）",
              titles.get("位元率") == LEVEL_BAD, str(titles))
        check("實測：開頭廢秒被抓（warn）",
              titles.get("開頭廢秒") == LEVEL_WARN, str(titles))
        check("實測：結尾廢秒被抓（warn）",
              titles.get("結尾廢秒") == LEVEL_WARN, str(titles))
        check("實測：解析度/更新率/編碼通過",
              titles.get("解析度") == LEVEL_GOOD
              and titles.get("畫面更新率") == LEVEL_GOOD
              and titles.get("視訊編碼") == LEVEL_GOOD, str(titles))
        head_cut, tail_cut = videocheck.suggest_trim(result["dead_air"])
        check("實測：建議去頭接近 2 秒", 1.2 <= head_cut <= 2.2,
              str((head_cut, tail_cut)))

        # 修剪實跑：輸出時長 = 原長 - 頭 - 尾（±0.3s）。
        trimmed = os.path.join(tmp, "trimmed.mp4")
        videocheck.trim_video(bad_clip, trimmed, head_seconds=2.0,
                              tail_seconds=1.0)
        from subtitle.media import probe_duration
        out_dur = probe_duration(trimmed)
        check("實測：修剪後時長正確", abs(out_dur - 5.0) < 0.35,
              str(out_dur))

        # 修剪過頭要擋下。
        try:
            videocheck.trim_video(bad_clip, os.path.join(tmp, "x.mp4"),
                                  head_seconds=5.0, tail_seconds=4.0)
            check("實測：修剪過頭擋下", False, "未拋出例外")
        except ValueError:
            check("實測：修剪過頭擋下", True)

        # 健康素材：高位元率、無廢秒 → 全綠。
        good_clip = os.path.join(tmp, "good.mp4")
        # 雜訊畫面難以壓縮，確保實際輸出位元率能達到 -b:v 目標值
        # （靜態測試圖樣會被 x264 壓到遠低於目標，反而誤觸低位元率判定）。
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi",
             "-i", "color=c=gray:s=1920x1080:d=5,"
                   "noise=alls=60:allf=t+u,format=yuv420p",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
             "-c:v", "libx264", "-b:v", "10M",
             "-c:a", "aac", "-t", "5", good_clip],
            capture_output=True, timeout=180)
        good = videocheck.run_video_check(good_clip, None)
        levels = {f["title"]: f["level"] for f in good["findings"]}
        check("實測：健康素材全數通過",
              all(v == LEVEL_GOOD for v in levels.values()), str(levels))

        # 純音訊檔：略過畫質段落、不炸。
        audio_only = os.path.join(tmp, "a.m4a")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
             "-c:a", "aac", audio_only], capture_output=True, timeout=60)
        aud = videocheck.run_video_check(audio_only, None)
        check("實測：純音訊檔回空 findings", aud["findings"] == []
              and videocheck.format_video_report(aud) == "")
else:
    print("SKIP 實測（無 ffmpeg）")

print()
if failures:
    print(f"共 {len(failures)} 項失敗：{failures}")
    sys.exit(1)
print("test_v1170 全部通過")
