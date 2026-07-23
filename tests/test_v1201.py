# -*- coding: utf-8 -*-
"""v1.20.1 修復驗證：音訊一鍵修復遇到無音軌檔案時的友善錯誤。

以真實影片測試集（scikit-video 的 carphone_pristine.mp4，確認無音軌）
跑過 audiofix.fix_audio() 時發現：命令組裝一律帶 -map 0:a，未檢查來源
是否真的有音軌，導致 ffmpeg 直接噴出英文錯誤訊息中斷。修法：呼叫前先用
media.has_audio_stream() 檢查，沒有音軌時改丟出清楚的中文錯誤。
"""
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

from subtitle import audiofix

# ===== 1. 無音軌時 fix_audio 丟出清楚的中文錯誤，而非讓 ffmpeg 噴英文錯誤 =====
with tempfile.TemporaryDirectory() as tmp:
    src = os.path.join(tmp, "無聲影片.mp4")
    open(src, "wb").write(b"x")
    out = os.path.join(tmp, "無聲影片_修復.mp4")

    orig_avail = audiofix.ffmpeg_available
    orig_has_audio = audiofix.has_audio_stream
    audiofix.ffmpeg_available = lambda: True
    audiofix.has_audio_stream = lambda p: False
    try:
        audiofix.fix_audio(src, out, settings={
            "denoise": True, "denoise_strength": 12.0,
            "highpass": True, "highpass_hz": 80.0, "loudnorm": False})
        check("無音軌時擋下並報錯", False)
    except ValueError as exc:
        check("無音軌時擋下並報錯", "音訊軌" in str(exc), str(exc))
    except RuntimeError:
        check("無音軌時擋下並報錯（不應是 ffmpeg 原始錯誤）", False)
    finally:
        audiofix.ffmpeg_available = orig_avail
        audiofix.has_audio_stream = orig_has_audio

# ===== 2. 有音軌時不受影響，照常組出命令並執行 =====
with tempfile.TemporaryDirectory() as tmp:
    src = os.path.join(tmp, "有聲影片.mp4")
    open(src, "wb").write(b"x")
    out = os.path.join(tmp, "有聲影片_修復.mp4")

    orig_avail = audiofix.ffmpeg_available
    orig_has_audio = audiofix.has_audio_stream
    orig_has_video = audiofix.has_video_stream
    orig_dur = audiofix.probe_duration
    orig_popen = audiofix.subprocess.Popen

    audiofix.ffmpeg_available = lambda: True
    audiofix.has_audio_stream = lambda p: True
    audiofix.has_video_stream = lambda p: True
    audiofix.probe_duration = lambda p: 10.0

    captured = {}
    class FakeProc:
        stdout = None
        stderr = None
        def wait(self):
            return 0
    audiofix.subprocess.Popen = (
        lambda cmd, **k: captured.update(cmd=cmd) or FakeProc())

    try:
        result = audiofix.fix_audio(src, out, settings={
            "denoise": True, "denoise_strength": 12.0,
            "highpass": True, "highpass_hz": 80.0, "loudnorm": False})
        check("有音軌時正常執行", result == out)
        check("命令仍帶 -map 0:a", "0:a" in captured.get("cmd", []),
              str(captured.get("cmd")))
    finally:
        audiofix.ffmpeg_available = orig_avail
        audiofix.has_audio_stream = orig_has_audio
        audiofix.has_video_stream = orig_has_video
        audiofix.probe_duration = orig_dur
        audiofix.subprocess.Popen = orig_popen

# ===== 3. 真實影片端到端：scikit-video 的 carphone_pristine.mp4（真實無音軌檔） =====
import shutil
real_clip = "/tmp/testlib/carphone_pristine.mp4"
if shutil.which("ffmpeg") and os.path.exists(real_clip):
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "carphone_修復.mp4")
        try:
            audiofix.fix_audio(real_clip, out)
            check("實測：真實無音軌影片被擋下", False)
        except ValueError as exc:
            check("實測：真實無音軌影片被擋下", "音訊軌" in str(exc), str(exc))
        check("實測：無音軌時不產生半成品輸出檔",
              not os.path.exists(out))
else:
    print("SKIP 真實影片實測（無 ffmpeg 或測試素材）")

print()
if failures:
    print(f"共 {len(failures)} 項失敗：{failures}")
    sys.exit(1)
print("test_v1201 全部通過")
