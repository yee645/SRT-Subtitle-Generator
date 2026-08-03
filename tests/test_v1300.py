# -*- coding: utf-8 -*-
"""v1.30.0 新功能測試：字幕與語音同步檢查與一鍵校正。"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import subsync as ss


def cue(start, end, text="對白"):
    return {"start": start, "end": end, "text": text}


# 基準語音配置：5-10, 15-20, 25-30, 35-40, 45-50 秒有聲，其餘靜音。
SPEECH = [(5.0, 10.0), (15.0, 20.0), (25.0, 30.0), (35.0, 40.0), (45.0, 50.0)]
ALIGNED = [cue(s, e, f"第{i+1}句") for i, (s, e) in enumerate(SPEECH)]

# ===== 1. 設定解析與夾限 =====
s = ss.resolve_subsync_settings(None)
check("預設值", s == ss.DEFAULT_SUBSYNC, str(s))
s2 = ss.resolve_subsync_settings({"subsync": {
    "silence_db": -999, "min_silence": 99, "max_offset": 0.1,
    "min_hit_rate": 9.9, "min_gain": 9.9, "drift_gap": 9.9}})
check("silence_db 夾下限", s2["silence_db"] == -60.0, str(s2))
check("min_silence 夾上限", s2["min_silence"] == 2.0, str(s2))
check("max_offset 夾下限", s2["max_offset"] == 1.0, str(s2))
check("min_hit_rate 夾上限", s2["min_hit_rate"] == 0.95, str(s2))
check("min_gain 夾上限", s2["min_gain"] == 0.5, str(s2))
check("drift_gap 夾上限", s2["drift_gap"] == 0.5, str(s2))
check("非數值回預設",
      ss.resolve_subsync_settings({"subsync": {"max_offset": "bad"}})
      ["max_offset"] == 10.0)

# ===== 2. parse_speech_spans：無聲區間的補集 =====
sample = """
[silencedetect @ 0x1] silence_start: 0
[silencedetect @ 0x1] silence_end: 5.0 | silence_duration: 5.0
[silencedetect @ 0x1] silence_start: 10.0
[silencedetect @ 0x1] silence_end: 15.0 | silence_duration: 5.0
"""
spans = ss.parse_speech_spans(sample, 20.0)
check("語音區間為無聲的補集",
      spans == [(5.0, 10.0), (15.0, 20.0)], str(spans))
# 無聲延伸到檔尾（沒有 silence_end 行）。
tail = ss.parse_speech_spans(
    "[silencedetect @ 0x1] silence_start: 0\n"
    "[silencedetect @ 0x1] silence_end: 3.0\n"
    "[silencedetect @ 0x1] silence_start: 8.0\n", 10.0)
check("尾端無聲正確收尾", tail == [(3.0, 8.0)], str(tail))
check("全程有聲時回單一區間",
      ss.parse_speech_spans("", 10.0) == [(0.0, 10.0)])
check("全程無聲時回空清單",
      ss.parse_speech_spans(
          "[silencedetect @ 0x1] silence_start: 0\n"
          "[silencedetect @ 0x1] silence_end: 10.0\n", 10.0) == [])

# ===== 3. overlap_ratio：貼合度計算 =====
check("完全貼合為 1.0",
      abs(ss.overlap_ratio(ALIGNED, SPEECH) - 1.0) < 1e-9)
check("完全落在靜音為 0.0",
      ss.overlap_ratio([cue(11.0, 14.0)], SPEECH) == 0.0)
check("一半重疊約 0.5",
      abs(ss.overlap_ratio([cue(8.0, 12.0)], SPEECH) - 0.5) < 1e-9)
check("套用偏移後可還原貼合",
      abs(ss.overlap_ratio(
          [cue(c["start"] + 2, c["end"] + 2) for c in ALIGNED],
          SPEECH, offset=-2.0) - 1.0) < 1e-9)
check("空字幕回 0.0", ss.overlap_ratio([], SPEECH) == 0.0)
check("空語音區間回 0.0", ss.overlap_ratio(ALIGNED, []) == 0.0)
check("零長度字幕不列入計算",
      ss.overlap_ratio([cue(5.0, 5.0)], SPEECH) == 0.0)

# ===== 4. head_tail_gap：漂移的關鍵判準 =====
# 漂移會被對得準的開頭稀釋掉全片平均，必須另外比較頭尾。
drift_cues = [cue(c["start"] * 1.0427, c["end"] * 1.0427) for c in ALIGNED]
gap = ss.head_tail_gap(drift_cues, SPEECH)
check("漂移字幕頭尾落差為正且明顯", gap > 0.15, f"gap={gap:.3f}")
check("對齊字幕頭尾無落差",
      abs(ss.head_tail_gap(ALIGNED, SPEECH)) < 1e-9)
check("字幕數不足時回 0", ss.head_tail_gap([cue(1, 2)], SPEECH) == 0.0)

# ===== 5. estimate_correction：線性校正搜尋 =====
offset_cues = [cue(c["start"] + 2.0, c["end"] + 2.0) for c in ALIGNED]
est = ss.estimate_correction(offset_cues, SPEECH)
check("固定偏移：估出 scale=1.0", est["scale"] == 1.0, str(est))
check("固定偏移：估出 offset≈-2.0", abs(est["offset"] + 2.0) < 0.1, str(est))
check("固定偏移：校正後貼合度接近 1.0", est["score"] > 0.95, str(est))

est_d = ss.estimate_correction(drift_cues, SPEECH)
check("幀率漂移：估出非 1.0 的縮放", est_d["scale"] != 1.0, str(est_d))
check("幀率漂移：校正後貼合度大幅提升", est_d["gain"] > 0.15, str(est_d))
check("幀率漂移：標示出幀率換算來源",
      "fps" in est_d["scale_label"], str(est_d))

# ===== 6. apply_sync_correction：只動時間軸 =====
fixed = ss.apply_sync_correction(offset_cues, 1.0, -2.0)
check("校正後起訖時間正確",
      abs(fixed[0]["start"] - 5.0) < 1e-9
      and abs(fixed[0]["end"] - 10.0) < 1e-9, str(fixed[0]))
check("校正不改動文字內容",
      [c["text"] for c in fixed] == [c["text"] for c in offset_cues])
check("校正不改動原始清單（回傳新物件）",
      abs(offset_cues[0]["start"] - 7.0) < 1e-9, str(offset_cues[0]))
check("負時間夾到 0",
      ss.apply_sync_correction([cue(1.0, 3.0)], 1.0, -5.0)[0]["start"] == 0.0)
# 逐字時間軸（動態字幕用）也要一起校正。
worded = [{"start": 10.0, "end": 12.0, "text": "嗨",
           "words": [{"word": "嗨", "start": 10.0, "end": 10.5}]}]
wfixed = ss.apply_sync_correction(worded, 1.0, -2.0)
check("逐字時間軸一併校正",
      wfixed[0]["words"][0]["start"] == 8.0
      and wfixed[0]["words"][0]["end"] == 8.5, str(wfixed[0]["words"]))
check("空清單安全", ss.apply_sync_correction([]) == [])

# ===== 7. format_sync_report 各分支 =====
ok_text = ss.format_sync_report({"kind": ss.KIND_OK, "hit_rate": 0.98})
check("同步正常時報告顯示通過", "同步正常" in ok_text, ok_text)

off_text = ss.format_sync_report({
    "kind": ss.KIND_OFFSET, "hit_rate": 0.6, "corrected_hit_rate": 0.99,
    "scale": 1.0, "offset": -2.0, "scale_label": "無縮放"})
check("固定偏移報告標明整軌平移",
      "固定偏移" in off_text and "提前" in off_text, off_text)

drift_text = ss.format_sync_report({
    "kind": ss.KIND_DRIFT, "hit_rate": 0.7, "corrected_hit_rate": 0.99,
    "scale": 0.959, "offset": 0.0, "scale_label": "25→23.976 fps"})
check("漂移報告標明幀率與縮放",
      "逐漸漂移" in drift_text and "25→23.976 fps" in drift_text, drift_text)
check("偏移可忽略時不贅印 0.00 秒",
      "0.00 秒" not in drift_text, drift_text)

dense_text = ss.format_sync_report({
    "kind": ss.KIND_UNRELIABLE, "hit_rate": 0.5, "speech_coverage": 0.99})
check("全程有聲時報告說明無法判定",
      "幾乎全程有聲" in dense_text, dense_text)
nofit_text = ss.format_sync_report({
    "kind": ss.KIND_UNRELIABLE, "hit_rate": 0.4, "speech_coverage": 0.5})
check("找不到更好校正時提醒字幕可能不對",
      "字幕來源" in nofit_text, nofit_text)

# ===== 8. config／CLI／GUI 靜態掃描 =====
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from config import DEFAULT_CONFIG
check("config 預設含 subsync 區",
      DEFAULT_CONFIG.get("subsync") == ss.DEFAULT_SUBSYNC,
      str(DEFAULT_CONFIG.get("subsync")))

with open(os.path.join(root, "cli.py"), encoding="utf-8") as fp:
    cli_src = fp.read()
check("cli.py 有 --synccheck 旗標", "--synccheck" in cli_src)
check("cli.py 有 --syncfix 旗標", "--syncfix" in cli_src)
check("cli.py 有同步檢查輸出函式", "_export_synccheck" in cli_src)

with open(os.path.join(root, "gui", "subtitle_check_dialog.py"),
          encoding="utf-8") as fp:
    dialog_src = fp.read()
check("對話框有同步檢查與校正按鈕",
      "檢查與語音同步" in dialog_src and "一鍵校正同步" in dialog_src
      and "apply_sync_correction" in dialog_src)
check("對話框於背景執行緒跑同步檢查（不凍住 UI）",
      "threading.Thread" in dialog_src and "_sync_worker" in dialog_src)
check("對話框無 classic tk.Checkbutton/Radiobutton 殘留",
      "tk.Checkbutton(" not in dialog_src.replace("ttk.Checkbutton(", "")
      and "tk.Radiobutton(" not in dialog_src.replace(
          "ttk.Radiobutton(", ""))

with open(os.path.join(root, "gui", "app.py"), encoding="utf-8") as fp:
    app_src = fp.read()
check("主視窗把媒體路徑傳給字幕健檢對話框",
      "media_path=media_path" in app_src)

# ===== 9. 真實媒體端到端：對齊／固定偏移／幀率漂移三情境 =====
if ss.ffmpeg_available():
    with tempfile.TemporaryDirectory() as tmp:
        media = os.path.join(tmp, "素材.mp4")
        gate = "+".join(f"between(t,{a},{b})" for a, b in SPEECH)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=navy:s=320x240:d=60",
             "-f", "lavfi", "-i", "sine=frequency=300:duration=60",
             "-af", f"volume='if({gate},1,0)':eval=frame",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-shortest", media],
            capture_output=True, timeout=120)

        detected = ss.detect_speech_spans(media)
        check("實測：偵測到 5 段語音", len(detected) == 5, str(detected))
        check("實測：語音區間與合成值相符（±0.1 秒）",
              all(abs(d[0] - s[0]) < 0.1 and abs(d[1] - s[1]) < 0.1
                  for d, s in zip(detected, SPEECH)), str(detected))

        # 9a. 對齊的字幕不該被建議校正（防止誤動已正確的字幕）。
        r_ok = ss.analyze_sync(media, ALIGNED)
        check("實測：對齊字幕判定為同步正常",
              r_ok["kind"] == ss.KIND_OK, str(r_ok["kind"]))

        # 9b. 固定偏移。
        r_off = ss.analyze_sync(media, offset_cues)
        check("實測：固定偏移被判定為 offset",
              r_off["kind"] == ss.KIND_OFFSET, str(r_off["kind"]))
        check("實測：偏移量估算正確（≈-2.0 秒）",
              abs(r_off["offset"] + 2.0) < 0.15, str(r_off["offset"]))
        recovered = ss.apply_sync_correction(
            offset_cues, r_off["scale"], r_off["offset"])
        check("實測：套用校正後貼合度回到 0.95 以上",
              ss.overlap_ratio(recovered, detected) > 0.95,
              str(ss.overlap_ratio(recovered, detected)))

        # 9c. 幀率漂移——全片平均貼合度仍高於門檻，靠頭尾落差才抓得到。
        fps_drift = [cue(c["start"] * (25.0 / 23.976),
                         c["end"] * (25.0 / 23.976)) for c in ALIGNED]
        r_drift = ss.analyze_sync(media, fps_drift)
        check("實測：幀率漂移被判定為 drift",
              r_drift["kind"] == ss.KIND_DRIFT, str(r_drift["kind"]))
        check("實測：漂移案例全片平均仍高於門檻（證實需要頭尾判準）",
              r_drift["hit_rate"] > 0.70, str(r_drift["hit_rate"]))
        check("實測：辨識出正確的幀率換算",
              "23.976" in r_drift["scale_label"], r_drift["scale_label"])
        recovered_d = ss.apply_sync_correction(
            fps_drift, r_drift["scale"], r_drift["offset"])
        check("實測：漂移校正後貼合度回到 0.95 以上",
              ss.overlap_ratio(recovered_d, detected) > 0.95,
              str(ss.overlap_ratio(recovered_d, detected)))

        # 9d. 全程有聲：明確回報無法判定，而不是硬給數字。
        dense = os.path.join(tmp, "全程有聲.m4a")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "sine=frequency=300:duration=30",
             "-c:a", "aac", dense],
            capture_output=True, timeout=60)
        r_dense = ss.analyze_sync(dense, [cue(1, 3), cue(5, 7), cue(9, 11)])
        check("實測：全程有聲時回報無法可靠判定",
              r_dense["kind"] == ss.KIND_UNRELIABLE, str(r_dense["kind"]))

        # 9e. 防呆：無音訊軌 / 空字幕。
        silent_video = os.path.join(tmp, "無音軌.mp4")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=black:s=320x240:d=5",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", silent_video],
            capture_output=True, timeout=60)
        try:
            ss.analyze_sync(silent_video, ALIGNED)
            check("實測：無音訊軌時報錯", False)
        except ValueError as exc:
            check("實測：無音訊軌時報錯", "音訊軌" in str(exc), str(exc))
        try:
            ss.analyze_sync(media, [])
            check("實測：空字幕時報錯", False)
        except ValueError as exc:
            check("實測：空字幕時報錯", "沒有字幕" in str(exc), str(exc))
        try:
            ss.analyze_sync("不存在.mp4", ALIGNED)
            check("找不到檔案時報錯", False)
        except FileNotFoundError:
            check("找不到檔案時報錯", True)

        # 9f. CLI 端到端：--subs 匯入偏移字幕 → --synccheck --syncfix。
        def ts(t):
            h = int(t // 3600); m = int(t % 3600 // 60); sec = t % 60
            return f"{h:02d}:{m:02d}:{sec:06.3f}".replace(".", ",")
        srt_path = os.path.join(tmp, "素材.srt")
        with open(srt_path, "w", encoding="utf-8") as fp:
            for i, (a, b) in enumerate(SPEECH, 1):
                fp.write(f"{i}\n{ts(a + 2)} --> {ts(b + 2)}\n第{i}句\n\n")
        proc = subprocess.run(
            [sys.executable, os.path.join(root, "main.py"),
             "--subs", srt_path, "--synccheck", "--syncfix",
             "--formats", "srt", media],
            cwd=tmp, capture_output=True, text=True, timeout=300)
        check("實測：CLI --synccheck --syncfix 執行成功",
              proc.returncode == 0, proc.stdout[-1200:] + proc.stderr[-800:])
        report_path = os.path.join(tmp, "素材_同步檢查.txt")
        check("實測：CLI 同步檢查報告已產生", os.path.exists(report_path))
        if os.path.exists(report_path):
            report_text = open(report_path, encoding="utf-8").read()
            check("實測：CLI 報告判定為固定偏移",
                  "固定偏移" in report_text, report_text)
        fixed_srt = os.path.join(tmp, "素材_同步校正.srt")
        check("實測：CLI 校正後字幕已產生", os.path.exists(fixed_srt))
        if os.path.exists(fixed_srt):
            content = open(fixed_srt, encoding="utf-8").read()
            check("實測：校正後時間軸還原為原始正確值",
                  "00:00:05,000 --> 00:00:10,000" in content,
                  content[:200])
else:
    print("SKIP 實測（無 ffmpeg）")

print()
if failures:
    print(f"共 {len(failures)} 項失敗：{failures}")
    sys.exit(1)
print("test_v1300 全部通過")
