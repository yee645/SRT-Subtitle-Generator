# -*- coding: utf-8 -*-
"""v1.8.0 新功能測試：自動修正詞庫、人聲頻帶音量分析與 RMS 加速。"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

# ===== 1. 自動修正詞庫 =====
from subtitle.textedit import (MAX_CORRECTION_RULES, apply_corrections,
                               normalize_correction_rules)

rules = normalize_correction_rules([
    {"find": "克勞德", "replace": "Claude"},
    {"find": "", "replace": "x"},                       # 空 find 剔除
    {"find": "克勞德", "replace": "Claude AI"},          # 同 find 保留最新
    "garbage",                                           # 非 dict 剔除
    {"find": "GPT", "replace": "Claude", "case": True},
])
check("規則去空去重保留最新", len(rules) == 2
      and rules[0]["replace"] == "Claude AI")
check("非清單輸入回空", normalize_correction_rules(None) == []
      and normalize_correction_rules("x") == [])
check("規則數量上限", len(normalize_correction_rules(
    [{"find": f"w{i}"} for i in range(500)])) == MAX_CORRECTION_RULES)

cues = [{"start": 0, "end": 1, "text": "克勞德和 gpt 與 GPT"}]
fixed, n = apply_corrections(cues, [
    {"find": "克勞德", "replace": "Claude"},
    {"find": "GPT", "replace": "Claude", "case": True},
])
check("套用規則取代次數", n == 2)
check("區分大小寫僅中大寫", fixed[0]["text"] == "Claude和 gpt 與 Claude",
      fixed[0]["text"])
check("原 cue 不被修改", cues[0]["text"].startswith("克勞德"))
check("空規則不動作", apply_corrections(cues, [])[1] == 0)

# 逐字資料互動：可同步就同步、不可同步退回整句（沿用 v1.7 行為）
dyn = [{"start": 0, "end": 1, "text": "GPT rocks",
        "words": [{"word": "GPT", "start": 0, "end": 0.5},
                  {"word": "rocks", "start": 0.5, "end": 1}]}]
out, _ = apply_corrections(dyn, [{"find": "GPT", "replace": "Claude"}])
check("規則同步逐字資料",
      any(w["word"] == "Claude" for w in out[0].get("words", [])))

# ===== 2. 生成管線自動套用（隔離 whisper／ffmpeg 替身） =====
import types

fake_transcriber = types.ModuleType("subtitle.transcriber")
def _fake_transcribe(path, config, report=None):
    words = []
    t = 0.0
    for ch in "今天介紹克勞德模型":
        words.append({"word": ch, "start": t, "end": t + 0.3})
        t += 0.3
    return words
fake_transcriber.transcribe = _fake_transcribe
sys.modules["subtitle.transcriber"] = fake_transcriber

from subtitle import pipeline
import tempfile

with tempfile.TemporaryDirectory() as tmp:
    media = os.path.join(tmp, "素材.mp4")
    open(media, "wb").write(b"\x00")
    config = {
        "automation": {"export_srt": True, "burn_video": False,
                       "output_dir": tmp},
        "segmentation": {"max_chars_cjk": 18, "max_chars_latin": 45,
                         "min_duration": 1.0, "max_duration": 7.0,
                         "pause_gap": 0.5},
        "subtitle_style": {},
        "transcription": {"use_cache": False},
        "corrections": [{"find": "克勞德", "replace": "Claude"}],
    }
    result = pipeline.run_pipeline(media, config)
    srt_text = open(result["exports"][0], encoding="utf-8").read()
    check("管線自動套用修正詞庫", "Claude" in srt_text and "克勞德" not in srt_text,
          srt_text)

# ===== 3. 人聲頻帶音量分析 =====
from subtitle import review

cmd_on = review._loudness_command("a.mp4", 16000, True)
cmd_off = review._loudness_command("a.mp4", 16000, False)
check("人聲頻帶加帶通濾波",
      "highpass=f=150,lowpass=f=4000" in " ".join(cmd_on))
check("關閉時無濾波", "-af" not in cmd_off)
check("輸出管線參數不變", cmd_on[-1] == "pipe:1" and "-ar" in cmd_on)

s = review.resolve_settings({})
check("voice_band 預設開", s["voice_band"] is True)
check("voice_band 可關",
      review.resolve_settings({"review": {"voice_band": False}})["voice_band"]
      is False)

# ===== 4. RMS 計算（audioop 加速與純 Python 後備一致性） =====
import array

full = array.array("h", [32767, -32768] * 1000).tobytes()
check("滿刻度 RMS≈1", abs(review._chunk_rms(full) - 1.0) < 0.01)
check("靜音 RMS=0", review._chunk_rms(
    array.array("h", [0] * 2000).tobytes()) == 0.0)
check("空區塊安全", review._chunk_rms(b"") == 0.0)
check("奇數位元組安全", review._chunk_rms(b"\x01") == 0.0)
sine = array.array("h", [int(16384 * math.sin(i / 10)) for i in range(4000)])
rms_sine = review._chunk_rms(sine.tobytes())
check("正弦波 RMS 合理", 0.3 < rms_sine < 0.4, str(rms_sine))

# ===== 5. 設定預設值 =====
from config import DEFAULT_CONFIG
check("config 含 corrections", DEFAULT_CONFIG["corrections"] == [])
check("config 含 voice_band", DEFAULT_CONFIG["review"]["voice_band"] is True)

print("\n" + ("ALL PASS" if not failures else f"FAILURES: {failures}"))
sys.exit(1 if failures else 0)
