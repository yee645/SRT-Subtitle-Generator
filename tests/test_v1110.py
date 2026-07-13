# -*- coding: utf-8 -*-
"""v1.11.0 新功能測試：封面候選擷取、音訊健檢。"""
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import audiocheck, thumbnails
from subtitle.review import TAG_HIGHLIGHT

# =====================================================================
# 封面候選擷取
# =====================================================================

# ===== 1. 設定夾限與預設 =====
s = thumbnails.resolve_thumbnail_settings(None)
check("縮圖預設值", s == thumbnails.DEFAULT_THUMBNAILS, str(s))
s2 = thumbnails.resolve_thumbnail_settings({"thumbnails": {
    "count": 99, "min_spacing": 0.1, "width": "bad",
    "prefer_highlights": False}})
check("張數夾限上界", s2["count"] == 12)
check("間隔夾限下界", s2["min_spacing"] == 1.0)
check("寬度非數值回預設", s2["width"] == 1280)
check("優先精彩可關閉", s2["prefer_highlights"] is False)

# ===== 2. sample_windows：精彩優先、間隔、均勻補齊 =====
def seg(start, end, score=0.0, tags=(), keep=True, kind="speech"):
    return {"kind": kind, "start": start, "end": end, "score": score,
            "tags": list(tags), "keep": keep, "text": ""}

items = [
    seg(0, 10, score=1.0),
    seg(20, 30, score=5.0, tags=[TAG_HIGHLIGHT]),
    seg(40, 50, score=3.0, tags=[TAG_HIGHLIGHT]),
    seg(60, 70, score=9.0, keep=False),           # 捨棄段不取樣
    seg(80, 90, kind="silence", keep=False),      # 冷場不取樣
]
cfg = {"count": 3, "min_spacing": 5.0, "prefer_highlights": True,
       "width": 1280}
windows = thumbnails.sample_windows(items, 100.0, cfg)
check("窗口數符合張數", len(windows) == 3, str(windows))
check("精彩分數最高者優先", abs(windows[0][0] - 20) < 6
      and windows[0][1] <= 30, str(windows))
check("第二優先為次高精彩", 40 <= windows[1][0] < 50, str(windows))
check("其餘保留段殿後", windows[2][0] < 10, str(windows))

# 段落不足時整片均勻補齊。
windows_even = thumbnails.sample_windows([], 120.0, cfg)
check("無段落時均勻取樣", len(windows_even) == 3, str(windows_even))
centers = [(a + b) / 2 for a, b in windows_even]
check("均勻取樣分佈遞增", centers == sorted(centers)
      and centers[0] > 0 and centers[-1] < 120, str(centers))

# 間隔限制：中心點過近的段落略過。
near = [seg(0, 10, score=5.0, tags=[TAG_HIGHLIGHT]),
        seg(10, 20, score=4.0, tags=[TAG_HIGHLIGHT])]
w_near = thumbnails.sample_windows(
    near, 0.0, {"count": 2, "min_spacing": 30.0,
                "prefer_highlights": True, "width": 1280})
check("中心點過近只留一個窗口", len(w_near) == 1, str(w_near))

# ===== 3. parse_frame_scores =====
meta_text = (
    "[Parsed_metadata_5 @ 0x1] frame:0    pts:0      pts_time:0\n"
    "[Parsed_metadata_5 @ 0x1] lavfi.signalstats.YAVG=10.5\n"
    "[Parsed_metadata_5 @ 0x1] frame:1    pts:512    pts_time:0.5\n"
    "[Parsed_metadata_5 @ 0x1] lavfi.signalstats.YAVG=25.25\n"
    "亂入的行不影響解析\n"
    "[Parsed_metadata_5 @ 0x1] frame:2    pts:1024   pts_time:1.0\n"
    "[Parsed_metadata_5 @ 0x1] lavfi.signalstats.YAVG=bad\n")
scores = thumbnails.parse_frame_scores(meta_text)
check("解析出兩筆有效分數", scores == [(0.0, 10.5), (0.5, 25.25)],
      str(scores))
check("空字串安全", thumbnails.parse_frame_scores("") == [])

# ===== 4. pick_frames：每窗口取最高分、跨候選間隔 =====
picks = thumbnails.pick_frames(
    [[(10.0, 5.0), (12.0, 9.0)],       # 最高分 12.0
     [(13.0, 8.0), (30.0, 6.0)],       # 13.0 與 12.0 過近 → 取 30.0
     [(50.0, 1.0)]],
    count=3, min_spacing=5.0)
check("每窗口取最高分且守住間隔",
      picks == [(12.0, 9.0), (30.0, 6.0), (50.0, 1.0)], str(picks))
check("候選依分數排序", [s for _, s in picks] == [9.0, 6.0, 1.0],
      str(picks))
picks_cap = thumbnails.pick_frames(
    [[(1.0, 1.0)], [(20.0, 2.0)], [(40.0, 3.0)]], count=2, min_spacing=5.0)
check("張數上限生效", len(picks_cap) == 2)

# ===== 5. 評分與擷取命令組裝 =====
cmd = thumbnails._score_command("v.mp4", 20.0, 12.0)
check("評分命令快轉到窗口", cmd[cmd.index("-ss") + 1] == "20.000")
check("評分命令限制時長", cmd[cmd.index("-t") + 1] == "12.000")
vf = cmd[cmd.index("-vf") + 1]
check("評分鏈含 sobel 邊緣能量", "sobel" in vf and "signalstats" in vf
      and "metadata=mode=print" in vf, vf)
check("評分先縮圖省資源", f"scale={thumbnails._SCORE_WIDTH}:-2" in vf, vf)
check("評分不輸出檔案", cmd[-2:] == ["null", "-"], str(cmd))

# ===== 6. score_window / extract_frame / generate_thumbnails（替身）=====
orig_run = thumbnails.subprocess.run
orig_avail = thumbnails.ffmpeg_available

def fake_run_factory(tmp):
    def fake_run(cmd, **kwargs):
        if "null" in cmd:  # 評分：回報兩格，0.5 秒處分數較高。
            return types.SimpleNamespace(
                returncode=0, stdout=b"", stderr=meta_text.encode("utf-8"))
        out = cmd[-1]      # 擷取：實際建立輸出檔。
        with open(out, "wb") as fp:
            fp.write(b"PNG")
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
    return fake_run

with tempfile.TemporaryDirectory() as tmp:
    thumbnails.ffmpeg_available = lambda: True
    thumbnails.subprocess.run = fake_run_factory(tmp)

    ws = thumbnails.score_window("v.mp4", 20.0, 32.0)
    check("score_window 轉為絕對秒數", ws == [(20.0, 10.5), (20.5, 25.25)],
          str(ws))

    out_png = os.path.join(tmp, "f.png")
    path = thumbnails.extract_frame("v.mp4", 3.5, out_png, width=1280)
    check("extract_frame 建立輸出檔", path == out_png
          and os.path.exists(out_png))

    events = []
    results = thumbnails.generate_thumbnails(
        "v.mp4",
        [seg(20, 30, score=5.0, tags=[TAG_HIGHLIGHT]),
         seg(100, 110, score=3.0, tags=[TAG_HIGHLIGHT])],
        200.0,
        output_paths=lambda rank: os.path.join(tmp, f"封面{rank:02d}.png"),
        settings={"count": 2, "min_spacing": 5.0,
                  "prefer_highlights": True, "width": 1280},
        progress_cb=lambda ratio, msg: events.append((ratio, msg)))
    check("候選張數正確", len(results) == 2, str(results))
    check("候選檔案存在", all(os.path.exists(r["path"]) for r in results))
    check("依清晰度分數排序", results[0]["score"] >= results[1]["score"],
          str(results))
    check("進度回報到完成", events and events[-1][0] == 1.0, str(events))

    # 評分全失敗時退回窗口中點，仍有候選。
    def fail_score_run(cmd, **kwargs):
        if "null" in cmd:
            raise OSError("boom")
        out = cmd[-1]
        with open(out, "wb") as fp:
            fp.write(b"PNG")
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
    thumbnails.subprocess.run = fail_score_run
    fallback = thumbnails.generate_thumbnails(
        "v.mp4", [seg(20, 30, score=5.0, tags=[TAG_HIGHLIGHT])], 0.0,
        output_paths=lambda rank: os.path.join(tmp, f"fb{rank:02d}.png"),
        settings={"count": 1, "min_spacing": 5.0,
                  "prefer_highlights": True, "width": 1280})
    check("評分失敗退回窗口中點", len(fallback) == 1
          and abs(fallback[0]["time"] - 25.0) < 0.01, str(fallback))

thumbnails.subprocess.run = orig_run
thumbnails.ffmpeg_available = orig_avail

# ffmpeg 不可用時報錯。
thumbnails.ffmpeg_available = lambda: False
try:
    thumbnails.generate_thumbnails("v.mp4", [], 10.0,
                                   output_paths=lambda r: "x.png")
    check("縮圖 ffmpeg 不可用時報錯", False)
except RuntimeError as exc:
    check("縮圖 ffmpeg 不可用時報錯", "ffmpeg" in str(exc))
thumbnails.ffmpeg_available = orig_avail

# =====================================================================
# 音訊健檢
# =====================================================================

# ===== 7. 設定夾限與預設 =====
a = audiocheck.resolve_audiocheck_settings(None)
check("健檢預設值", a == audiocheck.DEFAULT_AUDIOCHECK, str(a))
a2 = audiocheck.resolve_audiocheck_settings({"audiocheck": {
    "quiet_lufs": -99, "noise_floor_db": 10, "clip_peak_db": "bad",
    "balance_db": 100}})
check("太小聲門檻夾限", a2["quiet_lufs"] == -30.0)
check("底噪門檻夾限", a2["noise_floor_db"] == -20.0)
check("爆音門檻非數值回預設", a2["clip_peak_db"] == -0.5)
check("聲道差異夾限", a2["balance_db"] == 20.0)

# ===== 8. parse_astats =====
astats_text = (
    "[Parsed_astats_0 @ 0x557] Channel: 1\n"
    "[Parsed_astats_0 @ 0x557] DC offset: 0.000001\n"
    "[Parsed_astats_0 @ 0x557] Peak level dB: -1.033658\n"
    "[Parsed_astats_0 @ 0x557] RMS level dB: -18.500000\n"
    "[Parsed_astats_0 @ 0x557] RMS peak dB: -12.000000\n"
    "[Parsed_astats_0 @ 0x557] Flat factor: 0.000000\n"
    "[Parsed_astats_0 @ 0x557] Peak count: 2\n"
    "[Parsed_astats_0 @ 0x557] Noise floor dB: -58.123456\n"
    "[Parsed_astats_0 @ 0x557] Channel: 2\n"
    "[Parsed_astats_0 @ 0x557] Peak level dB: -1.100000\n"
    "[Parsed_astats_0 @ 0x557] RMS level dB: -19.000000\n"
    "[Parsed_astats_0 @ 0x557] Overall\n"
    "[Parsed_astats_0 @ 0x557] Peak level dB: -1.033658\n"
    "[Parsed_astats_0 @ 0x557] RMS level dB: -18.700000\n"
    "[Parsed_astats_0 @ 0x557] Flat factor: 0.000000\n"
    "[Parsed_astats_0 @ 0x557] Peak count: 2\n"
    "[Parsed_astats_0 @ 0x557] Noise floor dB: -57.000000\n"
    "size=N/A time=00:01:00.00 bitrate=N/A speed= 120x\n")
parsed = audiocheck.parse_astats(astats_text)
check("解析出兩個聲道", len(parsed["channels"]) == 2, str(parsed))
check("聲道一峰值", parsed["channels"][0]["peak_db"] == -1.033658)
check("聲道二 RMS", parsed["channels"][1]["rms_db"] == -19.0)
check("整體底噪", parsed["overall"]["noise_floor_db"] == -57.0)
check("未知欄位不誤收", "rms_peak_db" not in parsed["overall"]
      and "dc_offset" not in parsed["channels"][0], str(parsed))
check("解析不到時回 None", audiocheck.parse_astats("hello") is None)
check("-inf 峰值可解析", audiocheck.parse_astats(
    "[Parsed_astats_0 @ 0x1] Overall\n"
    "[Parsed_astats_0 @ 0x1] Peak level dB: -inf\n"
)["overall"]["peak_db"] == float("-inf"))

# ===== 9. evaluate：各檢查情境 =====
def levels(findings):
    return {f["title"]: f["level"] for f in findings}

good_astats = {
    "overall": {"peak_db": -6.0, "noise_floor_db": -60.0,
                "flat_factor": 0.0, "peak_count": 1},
    "channels": [{"rms_db": -18.0}, {"rms_db": -19.0}],
}
ok = levels(audiocheck.evaluate({"input_i": "-14.2"}, good_astats))
check("全部通過情境", set(ok.values()) == {"good"}, str(ok))

quiet = levels(audiocheck.evaluate({"input_i": "-25.0"}, good_astats))
check("太小聲判 bad", quiet["整體響度"] == "bad", str(quiet))
loud = levels(audiocheck.evaluate({"input_i": "-9.0"}, good_astats))
check("過大聲判 warn", loud["整體響度"] == "warn", str(loud))
no_loud = levels(audiocheck.evaluate(None, good_astats))
check("無響度資料判 warn", no_loud["整體響度"] == "warn", str(no_loud))

clip_astats = {
    "overall": {"peak_db": 0.0, "noise_floor_db": -60.0,
                "flat_factor": 1.5, "peak_count": 500},
    "channels": [{"rms_db": -18.0}, {"rms_db": -18.5}],
}
clip = levels(audiocheck.evaluate({"input_i": "-14.0"}, clip_astats))
check("削波判 bad", clip["爆音檢查"] == "bad", str(clip))
hot_astats = {
    "overall": {"peak_db": -0.2, "noise_floor_db": -60.0,
                "flat_factor": 0.0},
    "channels": [{"rms_db": -18.0}, {"rms_db": -18.5}],
}
hot = levels(audiocheck.evaluate({"input_i": "-14.0"}, hot_astats))
check("貼頂未削波判 warn", hot["爆音檢查"] == "warn", str(hot))

noisy_astats = {
    "overall": {"peak_db": -6.0, "noise_floor_db": -35.0,
                "flat_factor": 0.0},
    "channels": [{"rms_db": -18.0}, {"rms_db": -18.5}],
}
noisy = levels(audiocheck.evaluate({"input_i": "-14.0"}, noisy_astats))
check("底噪偏高判 warn", noisy["底噪檢查"] == "warn", str(noisy))

dead_astats = {
    "overall": {"peak_db": -6.0, "noise_floor_db": -60.0,
                "flat_factor": 0.0},
    "channels": [{"rms_db": -18.0}, {"rms_db": float("-inf")}],
}
dead = levels(audiocheck.evaluate({"input_i": "-14.0"}, dead_astats))
check("單邊無聲判 bad", dead["聲道平衡"] == "bad", str(dead))
tilt_astats = {
    "overall": {"peak_db": -6.0, "noise_floor_db": -60.0,
                "flat_factor": 0.0},
    "channels": [{"rms_db": -12.0}, {"rms_db": -25.0}],
}
tilt = levels(audiocheck.evaluate({"input_i": "-14.0"}, tilt_astats))
check("聲道不平衡判 warn", tilt["聲道平衡"] == "warn", str(tilt))
mono_astats = {
    "overall": {"peak_db": -6.0, "noise_floor_db": -60.0,
                "flat_factor": 0.0},
    "channels": [{"rms_db": -18.0}],
}
mono = levels(audiocheck.evaluate({"input_i": "-14.0"}, mono_astats))
check("單聲道判 good", mono["聲道平衡"] == "good", str(mono))
none_astats = levels(audiocheck.evaluate({"input_i": "-14.0"}, None))
check("無 astats 時峰值底噪判 warn",
      none_astats["爆音檢查"] == "warn"
      and none_astats["底噪檢查"] == "warn", str(none_astats))

# 自訂門檻生效：把太小聲門檻收緊到 -15，-16 LUFS 應判 bad。
strict = levels(audiocheck.evaluate(
    {"input_i": "-16.0"}, good_astats,
    audiocheck.resolve_audiocheck_settings(
        {"audiocheck": {"quiet_lufs": -15.0}})))
check("自訂門檻生效", strict["整體響度"] == "bad", str(strict))

# ===== 10. format_report =====
report_ok = audiocheck.format_report(
    {"findings": audiocheck.evaluate({"input_i": "-14.0"}, good_astats)},
    source_name="demo.mp4")
check("報告含素材名", "demo.mp4" in report_ok)
check("全過結論", "可放心上傳" in report_ok, report_ok)
check("通過項帶勾號", "✔ 整體響度" in report_ok, report_ok)
report_bad = audiocheck.format_report(
    {"findings": audiocheck.evaluate({"input_i": "-25.0"}, clip_astats)})
check("問題結論建議修正", "建議修正" in report_bad
      and "✘" in report_bad, report_bad)
check("附具體建議", "建議：" in report_bad, report_bad)

# ===== 11. run_audio_check（替身量測）=====
orig_measure_loud = audiocheck.measure_loudness
orig_measure_astats = audiocheck.measure_astats
orig_check_avail = audiocheck.ffmpeg_available
audiocheck.ffmpeg_available = lambda: True
audiocheck.measure_loudness = lambda p, **k: {"input_i": "-14.0"}
audiocheck.measure_astats = lambda p, **k: good_astats
events = []
result = audiocheck.run_audio_check(
    "demo.mp4", None, progress_cb=lambda r, m: events.append((r, m)))
check("健檢回傳結構完整", set(result) == {"loudness", "astats", "findings"}
      and len(result["findings"]) == 4, str(result))
check("健檢進度回報到完成", events and events[-1][0] == 1.0, str(events))
audiocheck.ffmpeg_available = lambda: False
try:
    audiocheck.run_audio_check("demo.mp4")
    check("健檢 ffmpeg 不可用時報錯", False)
except RuntimeError as exc:
    check("健檢 ffmpeg 不可用時報錯", "ffmpeg" in str(exc))
audiocheck.measure_loudness = orig_measure_loud
audiocheck.measure_astats = orig_measure_astats
audiocheck.ffmpeg_available = orig_check_avail

# ===== 12. astats 命令組裝 =====
captured = {}
audiocheck.ffmpeg_available = lambda: True
audiocheck.subprocess.run = (
    lambda cmd, **k: captured.update(cmd=cmd) or types.SimpleNamespace(
        returncode=0, stdout=b"", stderr=astats_text.encode("utf-8")))
parsed_via_run = audiocheck.measure_astats("demo.mp4")
check("astats 命令純量測", "-vn" in captured["cmd"]
      and "astats" in captured["cmd"]
      and captured["cmd"][-2:] == ["null", "-"], str(captured["cmd"]))
check("measure_astats 解析結果", parsed_via_run["overall"]["peak_db"]
      == -1.033658)
audiocheck.subprocess.run = orig_run
audiocheck.ffmpeg_available = orig_check_avail

# ===== 13. config 預設值 =====
from config import DEFAULT_CONFIG
check("config 含 thumbnails 區塊",
      DEFAULT_CONFIG["thumbnails"] == thumbnails.DEFAULT_THUMBNAILS,
      str(DEFAULT_CONFIG.get("thumbnails")))
check("config 含 audiocheck 區塊",
      DEFAULT_CONFIG["audiocheck"] == audiocheck.DEFAULT_AUDIOCHECK,
      str(DEFAULT_CONFIG.get("audiocheck")))

# ===== 14. CLI 工具批次（替身核心函式）=====
import cli

orig_cli_check = cli.run_audio_check
orig_cli_thumbs = cli.generate_thumbnails
orig_cli_probe = cli.probe_duration
cli.run_audio_check = lambda p, c, **k: {
    "findings": audiocheck.evaluate({"input_i": "-14.0"}, good_astats)}
cli.probe_duration = lambda p: 60.0

with tempfile.TemporaryDirectory() as tmp:
    media = os.path.join(tmp, "素材.mp4")
    open(media, "wb").write(b"x")

    def fake_thumbs(path, items, duration, output_paths, settings=None):
        outs = []
        for rank in (1, 2):
            out = output_paths(rank)
            open(out, "wb").write(b"PNG")
            outs.append({"path": out, "time": rank * 10.0, "score": 1.0})
        return outs
    cli.generate_thumbnails = fake_thumbs

    logs = []
    config = {"automation": {"output_dir": ""}}
    results = cli._run_tools_batch(
        [media, os.path.join(tmp, "缺席.mp4")], config,
        lambda msg, ratio=None: logs.append(msg),
        do_audiocheck=True, do_thumbnails=True)
    check("工具批次成功一敗一", results[0]["ok"] and not results[1]["ok"],
          str(results))
    exports = results[0]["result"]["exports"]
    check("健檢報告輸出", any("音訊健檢" in p for p in exports), str(exports))
    check("封面候選輸出兩張",
          sum(1 for p in exports if "封面" in p) == 2, str(exports))
    check("報告檔存在", all(os.path.exists(p) for p in exports))

cli.run_audio_check = orig_cli_check
cli.generate_thumbnails = orig_cli_thumbs
cli.probe_duration = orig_cli_probe

# ===== 15. CLI 旗標解析 =====
parser = cli.build_parser()
args = parser.parse_args(["--audiocheck", "--thumbnails", "a.mp4"])
check("CLI 新旗標解析", args.audiocheck and args.thumbnails)

print("\n" + ("ALL PASS" if not failures else f"FAILURES: {failures}"))
sys.exit(1 if failures else 0)
