# -*- coding: utf-8 -*-
"""v1.5.0 新功能測試：響度正規化、Shorts 直式輸出（ffmpeg 以替身驗證指令組裝）。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

# ===== 1. audio 響度正規化 =====
from subtitle import audio

# 1a. clamp_target
check("目標響度夾限上界", audio.clamp_target(-3) == -8.0)
check("目標響度夾限下界", audio.clamp_target(-99) == -30.0)
check("目標響度無效值回預設", audio.clamp_target("abc") == -14.0)

# 1b. 濾鏡字串：無量測（動態模式）
f1 = audio.build_loudnorm_filter(None, -14.0)
check("動態模式濾鏡", f1.startswith("loudnorm=I=-14.0:TP=-1.5:LRA=11.0")
      and "linear" not in f1, f1)

# 1c. 濾鏡字串：兩階段線性模式
measured = {"input_i": "-23.5", "input_tp": "-4.2", "input_lra": "6.1",
            "input_thresh": "-33.9", "target_offset": "0.3"}
f2 = audio.build_loudnorm_filter(measured, -14.0)
check("線性模式帶量測值", "measured_I=-23.5" in f2 and "linear=true" in f2
      and "offset=0.3" in f2, f2)

# 1d. measure_loudness 解析 stderr JSON（以替身 subprocess.run）
class FakeCompleted:
    returncode = 0
    stdout = b""
    stderr = ("frame= 100\n[Parsed_loudnorm_0 @ 0x1] \n{\n"
              '\t"input_i" : "-23.47",\n\t"input_tp" : "-4.15",\n'
              '\t"input_lra" : "6.10",\n\t"input_thresh" : "-33.86",\n'
              '\t"output_i" : "-13.95",\n\t"target_offset" : "0.32"\n}\n'
              ).encode("utf-8")
orig_run = audio.subprocess.run
orig_avail = audio.ffmpeg_available
audio.subprocess.run = lambda *a, **k: FakeCompleted()
audio.ffmpeg_available = lambda: True
m = audio.measure_loudness("x.mp4")
check("量測 JSON 解析", m and m["input_i"] == "-23.47", str(m))
audio.subprocess.run = orig_run
audio.ffmpeg_available = orig_avail

# 1e. normalize_video 指令組裝（替身 Popen + 量測）
captured = {}
class FakeProc:
    stdout = None; stderr = None
    def wait(self): return 0
audio.ffmpeg_available = lambda: True
audio.measure_loudness = lambda p, timeout=600: measured
audio.subprocess.Popen = lambda cmd, **k: captured.update(cmd=cmd) or FakeProc()
audio.normalize_video("in.mp4", "out.mp4", -13.0)
cmd = captured["cmd"]
check("正規化影像串流複製", "-c:v" in cmd and cmd[cmd.index("-c:v")+1] == "copy")
check("正規化音訊濾鏡帶量測", any("measured_I" in str(a) for a in cmd))
check("正規化目標 -13", any("I=-13.0" in str(a) for a in cmd))

# ===== 2. burner 響度整合 =====
import importlib
from subtitle import burner
importlib.reload(audio)  # 還原 audio 替身

with tempfile.TemporaryDirectory() as tmp:
    video = os.path.join(tmp, "v.mp4")
    open(video, "wb").write(b"x")
    cues = [{"start": 0.0, "end": 2.0, "text": "哈囉"}]

    burn_captured = {}
    class BurnProc:
        stdout = None; stderr = None
        def wait(self): return 0
    orig_popen = burner.subprocess.Popen
    orig_bavail = burner.ffmpeg_available
    burner.subprocess.Popen = lambda cmd, **k: burn_captured.update(cmd=cmd) or BurnProc()
    burner.ffmpeg_available = lambda: True
    # audio.measure_loudness 會被延遲匯入呼叫——替身化避免真的跑 ffmpeg
    audio.ffmpeg_available = lambda: True
    audio.measure_loudness = lambda p, timeout=600: None

    # 2a. 未開啟響度 → 音訊 copy
    burner.burn_subtitles(video, cues, os.path.join(tmp, "o1.mp4"))
    c1 = burn_captured["cmd"]
    check("預設音訊 copy", c1[c1.index("-c:a")+1] == "copy")

    # 2b. 開啟響度 → loudnorm + aac
    burner.burn_subtitles(video, cues, os.path.join(tmp, "o2.mp4"),
                          loudnorm_target=-14.0)
    c2 = burn_captured["cmd"]
    check("響度開啟時帶 loudnorm", "-af" in c2
          and "loudnorm" in c2[c2.index("-af")+1])
    check("響度開啟時音訊 aac", c2[c2.index("-c:a")+1] == "aac")
    burner.subprocess.Popen = orig_popen
    burner.ffmpeg_available = orig_bavail

# ===== 3. shorts 直式輸出 =====
from subtitle import shorts

# 3a. 設定解析與夾限
s = shorts.resolve_shorts_settings({})
check("shorts 預設值", s["mode"] == "crop" and s["focus_x"] == 0.5
      and s["burn_subtitles"] is True)
s2 = shorts.resolve_shorts_settings(
    {"shorts": {"mode": "BLUR", "focus_x": 9}})
check("shorts 夾限", s2["mode"] == "blur" and s2["focus_x"] == 1.0)

# 3b. 字幕平移裁齊
cues_abs = [
    {"start": 8.0, "end": 12.0, "text": "跨進片段"},
    {"start": 12.5, "end": 15.0, "text": "完整在內"},
    {"start": 19.9, "end": 25.0, "text": "跨出片段"},
    {"start": 30.0, "end": 32.0, "text": "在片段外"},
]
shifted = shorts.shift_cues(cues_abs, 10.0, 20.0)
check("平移數量正確", len(shifted) == 3, str(shifted))
check("跨界裁齊", shifted[0]["start"] == 0.0 and shifted[0]["end"] == 2.0)
check("完整字幕平移", shifted[1]["start"] == 2.5 and shifted[1]["end"] == 5.0)
check("尾端裁齊", abs(shifted[2]["end"] - 10.0) < 1e-6)

# 3c. 裁切參數計算
check("橫式素材垂直吃滿",
      shorts._crop_params(1920, 1080, 1080, 1920, 0.5) == (608, 1080, 656, 0))
check("焦點靠左", shorts._crop_params(1920, 1080, 1080, 1920, 0.0)[2] == 0)
check("焦點靠右", shorts._crop_params(1920, 1080, 1080, 1920, 1.0)[2] == 1312)
w, h, x, y = shorts._crop_params(1080, 2400, 1080, 1920, 0.5)
check("過窄素材水平吃滿垂直置中", w == 1080 and h == 1920 and x == 0 and y == 240)

# 3d. cut_vertical_clip 指令組裝（crop / blur / 字幕 / 響度）
with tempfile.TemporaryDirectory() as tmp:
    video = os.path.join(tmp, "素材.mp4")
    open(video, "wb").write(b"x")
    cap = {}
    class ClipProc:
        stdout = None; stderr = None
        def wait(self): return 0
    orig_p = shorts.subprocess.Popen
    orig_a = shorts.ffmpeg_available
    orig_d = shorts.probe_dimensions
    shorts.subprocess.Popen = lambda cmd, **k: cap.update(cmd=cmd) or ClipProc()
    shorts.ffmpeg_available = lambda: True
    shorts.probe_dimensions = lambda p: (1920, 1080)

    out = os.path.join(tmp, "短片.mp4")
    shorts.cut_vertical_clip(video, 10.0, 25.0, out, mode="crop",
                             focus_x=0.25,
                             cues=[{"start": 11.0, "end": 13.0, "text": "嗨"}],
                             style={"font_size": 30})
    cmd = cap["cmd"]
    vf = cmd[cmd.index("-vf")+1]
    check("crop 濾鏡與縮放", "crop=608:1080:328:0" in vf and "scale=1080:1920" in vf, vf)
    check("crop 含字幕燒錄", ",ass='" in vf)
    check("片段秒數正確", cmd[cmd.index("-ss")+1] == "10.000"
          and cmd[cmd.index("-t")+1] == "15.000")
    check("無響度時音訊 aac 無濾鏡", "-af" not in cmd)

    shorts.cut_vertical_clip(video, 0.0, 10.0, out, mode="blur",
                             loudnorm_target=-14.0)
    cmd2 = cap["cmd"]
    fc = cmd2[cmd2.index("-filter_complex")+1]
    check("blur 版式雙層合成", "boxblur" in fc and "overlay" in fc
          and "force_original_aspect_ratio=increase" in fc)
    check("blur 無字幕時不掛 ass", "ass=" not in fc)
    check("短片響度正規化", "-af" in cmd2
          and "loudnorm" in cmd2[cmd2.index("-af")+1])

    # 過短片段報錯
    try:
        shorts.cut_vertical_clip(video, 5.0, 5.05, out)
        check("過短片段報錯", False)
    except ValueError:
        check("過短片段報錯", True)

    shorts.subprocess.Popen = orig_p
    shorts.ffmpeg_available = orig_a
    shorts.probe_dimensions = orig_d

# ===== 4. media.probe_dimensions 容錯 =====
from subtitle import media
check("無 ffprobe 回保底尺寸",
      media.probe_dimensions("x.mp4") == (1920, 1080)
      if not media.ffprobe_available() else True)

# ===== 5. pipeline 響度整合 =====
from subtitle import pipeline
with tempfile.TemporaryDirectory() as tmp:
    m1 = os.path.join(tmp, "a.mp4")
    open(m1, "wb").write(b"x")
    from config import load_config
    cfg = load_config()
    cfg["transcription"]["use_cache"] = False
    cfg["automation"] = {"export_srt": False, "export_vtt": False,
                         "export_ass": False, "export_txt": False,
                         "burn_video": True, "loudnorm": True,
                         "loudnorm_target": -12.0, "output_dir": ""}
    got = {}
    pipeline.transcribe = lambda p, c, cb=None: [
        {"word": "測", "start": 0.0, "end": 0.5},
        {"word": "試", "start": 0.5, "end": 1.0}]
    def fake_burn(video_path, cues, output_path, style=None,
                  progress_cb=None, use_ass=True, loudnorm_target=None):
        got["target"] = loudnorm_target
        open(output_path, "wb").write(b"v")
        return output_path
    pipeline.burn_subtitles = fake_burn
    pipeline.run_pipeline(m1, cfg)
    check("pipeline 傳遞響度目標", got.get("target") == -12.0, str(got))

print("\n" + ("ALL PASS" if not failures else f"FAILURES: {failures}"))
sys.exit(1 if failures else 0)
