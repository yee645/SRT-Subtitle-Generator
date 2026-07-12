# -*- coding: utf-8 -*-
"""v1.9.0 新功能測試：背景音樂自動閃避（audio ducking）。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import audio

# ===== 1. 設定夾限與預設 =====
s = audio.resolve_ducking_settings(None)
check("預設值", s == audio.DEFAULT_DUCKING, str(s))
s_empty = audio.resolve_ducking_settings({})
check("空設定回預設", s_empty == audio.DEFAULT_DUCKING)

s2 = audio.resolve_ducking_settings({"ducking": {
    "music_volume": 5.0, "duck_strength": -1, "duck_sensitivity": "bad"}})
check("音量夾限上界", s2["music_volume"] == 1.0)
check("強度夾限下界", s2["duck_strength"] == 1.0)
check("靈敏度非數值回預設", s2["duck_sensitivity"]
      == audio.DEFAULT_DUCKING["duck_sensitivity"])

s3 = audio.resolve_ducking_settings({"ducking": {"music_volume": 0.02}})
check("音量夾限下界", s3["music_volume"] == 0.05)

# ===== 2. filter_complex 組裝 =====
fc = audio.build_ducking_filter_complex(audio.DEFAULT_DUCKING)
check("音樂基礎音量濾鏡", "[1:a]volume=0.350[bgvol]" in fc, fc)
check("側鏈壓縮參數", "sidechaincompress=threshold=0.060:ratio=8.00" in fc, fc)
check("固定攻擊回復時間", "attack=5:release=300" in fc, fc)
check("最終混音節點", "[0:a][bgduck]amix=inputs=2" in fc, fc)
check("輸出標籤正確", fc.endswith("[aout]"), fc)

custom = audio.build_ducking_filter_complex({
    "music_volume": 0.5, "duck_strength": 12.0, "duck_sensitivity": 0.1})
check("自訂參數反映在濾鏡", "volume=0.500" in custom
      and "ratio=12.00" in custom and "threshold=0.100" in custom, custom)

# ===== 3. 指令組裝 =====
cmd = audio._ducking_command("v.mp4", "m.mp3", fc, 12.345, "out.mp4")
check("影片輸入正確", cmd[cmd.index("-i") + 1] == "v.mp4")
check("音樂輸入前有 stream_loop -1",
      cmd[cmd.index("-stream_loop") + 1] == "-1"
      and cmd[cmd.index("-stream_loop") + 2] == "-i"
      and cmd[cmd.index("-stream_loop") + 3] == "m.mp3")
check("輸出裁到影片長度", cmd[cmd.index("-t") + 1] == "12.345")
check("影像串流原樣複製", cmd[cmd.index("-c:v") + 1] == "copy")
check("音訊輸出 aac", cmd[cmd.index("-c:a") + 1] == "aac")
check("輸出路徑在結尾", cmd[-1] == "out.mp4")
check("filter_complex 帶入指令", fc in cmd)

# ===== 4. mix_background_music：邊界與例外路徑 =====
orig_avail = audio.ffmpeg_available
audio.ffmpeg_available = lambda: False
try:
    audio.mix_background_music("v.mp4", "m.mp3", "o.mp4")
    check("ffmpeg 不可用時報錯", False)
except RuntimeError as exc:
    check("ffmpeg 不可用時報錯", "ffmpeg" in str(exc))
audio.ffmpeg_available = lambda: True

try:
    audio.mix_background_music("no_such_video.mp4", "no_such_music.mp3", "o.mp4")
    check("找不到影片時報錯", False)
except FileNotFoundError as exc:
    check("找不到影片時報錯", "找不到來源影片" in str(exc))

with tempfile.TemporaryDirectory() as tmp:
    video = os.path.join(tmp, "v.mp4")
    open(video, "wb").write(b"x")
    try:
        audio.mix_background_music(video, "no_such_music.mp3",
                                   os.path.join(tmp, "o.mp4"))
        check("找不到音樂時報錯", False)
    except FileNotFoundError as exc:
        check("找不到音樂時報錯", "找不到背景音樂檔" in str(exc))
audio.ffmpeg_available = orig_avail

# ===== 5. mix_background_music：成功路徑（替身 Popen，驗證命令與進度回報）=====
with tempfile.TemporaryDirectory() as tmp:
    video = os.path.join(tmp, "v.mp4")
    music = os.path.join(tmp, "m.mp3")
    output = os.path.join(tmp, "out.mp4")
    open(video, "wb").write(b"x")
    open(music, "wb").write(b"x")

    captured = {}
    class FakeProc:
        stdout = None
        stderr = None
        def wait(self):
            return 0
    orig_popen = audio.subprocess.Popen
    orig_probe = audio.probe_duration
    audio.ffmpeg_available = lambda: True
    audio.probe_duration = lambda p: 30.0
    audio.subprocess.Popen = (
        lambda cmd, **k: captured.update(cmd=cmd) or FakeProc())

    events = []
    result = audio.mix_background_music(
        video, music, output,
        settings={"music_volume": 0.4, "duck_strength": 6.0,
                 "duck_sensitivity": 0.08},
        progress_cb=lambda ratio, message: events.append((ratio, message)))

    check("回傳輸出路徑", result == output)
    check("使用自訂設定組出的命令", "volume=0.400" in captured["cmd"][
        captured["cmd"].index("-filter_complex") + 1])
    check("進度回報含開始與完成", events and events[0][0] == 0.0
          and events[-1][0] == 1.0, str(events))

    audio.subprocess.Popen = orig_popen
    audio.probe_duration = orig_probe

# ===== 6. config 預設值 =====
from config import DEFAULT_CONFIG
check("config 含 ducking 區塊",
      DEFAULT_CONFIG["ducking"] == audio.DEFAULT_DUCKING, DEFAULT_CONFIG["ducking"])

print("\n" + ("ALL PASS" if not failures else f"FAILURES: {failures}"))
sys.exit(1 if failures else 0)
