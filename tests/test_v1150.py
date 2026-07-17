# -*- coding: utf-8 -*-
"""v1.15.0 新功能測試：標題候選真標題化、配樂閃避自動適應人聲音量。"""
import math
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

from subtitle import audio, publisher, review


def seg(start, end, text, score=0.0, hl=False, keep=True):
    tags = [review.TAG_HIGHLIGHT] if hl else []
    return {"kind": "speech", "start": start, "end": end, "text": text,
            "tags": tags, "fillers": 0, "score": score, "keep": keep}


# ===== 1. 標題候選：多型態產生 =====
items = [
    seg(0, 8, "然後這台螢幕保護神器真的有夠猛我從三樓丟下去都沒事", 3.5, True),
    seg(10, 20, "你知道為什麼大家都在搶這台嗎", 2.8, True),
    seg(22, 30, "實測下來只要三百塊就能擋十次摔落", 2.0, True),
    seg(32, 40, "這段是普通的講話內容沒有什麼特別亮點", 0.1),
]
titles = publisher.suggest_titles(items, count=4, max_chars=40,
                                  extra_words="神器")
check("句首贅詞剝除（然後→剝掉）",
      titles[0].startswith("這台螢幕保護神器"), str(titles))
check("疑問句候選存在且帶問號",
      any(t.endswith("？") for t in titles), str(titles))
check("數字句候選存在", any("三百塊" in t for t in titles), str(titles))
check("關鍵字冠頭候選存在",
      any(t.startswith("【神器】") for t in titles), str(titles))
check("全部不超過長度上限", all(len(t) <= 40 for t in titles), str(titles))
check("候選彼此不重複", len(set(titles)) == len(titles), str(titles))

# 子句截斷：停在完整子句結尾，不攔腰切
long_item = [seg(0, 9, "這支影片我們要來測試三種完全不同的收音方式，"
                       "包含領夾麥、槍型麥跟手機內建麥克風，"
                       "最後告訴你哪一種最值得買", 4.0, True)]
t_clause = publisher.suggest_titles(long_item, count=1, max_chars=30)
check("以完整子句湊長度",
      t_clause == ["這支影片我們要來測試三種完全不同的收音方式，包含領夾麥"],
      str(t_clause))

# 英文硬截斷不切在單字中間
latin_item = [seg(0, 9, "we compare the sony camera with the canon camera "
                        "in real world tests today", 4.0, True)]
t_latin = publisher.suggest_titles(latin_item, count=1, max_chars=20)
check("英文不切在單字中間",
      t_latin and t_latin[0].split()[-1] in
      ("we", "compare", "the", "sony"), str(t_latin))

# 疑問句判定
check("句尾嗎判定疑問", publisher._is_question("大家都在搶這台嗎"))
check("句首為什麼判定疑問", publisher._is_question("為什麼會這樣呢"))
check("一般句非疑問", not publisher._is_question("今天天氣很好"))

# 無精彩段落時仍以保留段落補齊
plain = [seg(0, 8, "這是一段夠長的普通講話內容可以當標題", 0.5)]
check("無精彩段落也有候選",
      publisher.suggest_titles(plain, count=2, max_chars=40) != [], "")

# ===== 2. 自動閃避靈敏度：換算與夾限 =====
val = audio.compute_auto_sensitivity(-20.0)
check("換算公式（-20 LUFS → 0.0251）",
      val is not None and math.isclose(val, 10 ** (-32.0 / 20.0),
                                       rel_tol=1e-6), str(val))
check("極小聲夾到下限 0.002",
      audio.compute_auto_sensitivity(-58.0) == 0.002)
check("靜音 -inf 回 None",
      audio.compute_auto_sensitivity(float("-inf")) is None)
check("非數值回 None", audio.compute_auto_sensitivity("bad") is None)
check("正值（量測異常）回 None",
      audio.compute_auto_sensitivity(5.0) is None)

s = audio.resolve_ducking_settings(None)
check("auto_sensitivity 預設開", s["auto_sensitivity"] is True)
s_off = audio.resolve_ducking_settings(
    {"ducking": {"auto_sensitivity": False}})
check("auto_sensitivity 可關", s_off["auto_sensitivity"] is False)

# resolve_auto_sensitivity：量測成功覆寫、失敗保留手動值、不改原 dict
orig_measure = audio.measure_loudness
try:
    audio.measure_loudness = lambda path, timeout=600: {"input_i": "-30.5"}
    base = {"music_volume": 0.35, "duck_strength": 8.0,
            "duck_sensitivity": 0.06, "auto_sensitivity": True}
    out = audio.resolve_auto_sensitivity("v.mp4", base)
    check("量測成功覆寫靈敏度",
          math.isclose(out["duck_sensitivity"], 10 ** (-42.5 / 20.0),
                       rel_tol=1e-6), str(out))
    check("原設定 dict 不被修改", base["duck_sensitivity"] == 0.06)

    audio.measure_loudness = lambda path, timeout=600: None
    out2 = audio.resolve_auto_sensitivity("v.mp4", base)
    check("量測失敗沿用手動值", out2["duck_sensitivity"] == 0.06)

    base_off = dict(base, auto_sensitivity=False)
    audio.measure_loudness = lambda path, timeout=600: (_ for _ in ()).throw(
        AssertionError("關閉時不應量測"))
    out3 = audio.resolve_auto_sensitivity("v.mp4", base_off)
    check("關閉時不量測、原樣回傳", out3 is base_off)
finally:
    audio.measure_loudness = orig_measure

# ===== 3. GUI／config 靜態掃描 =====
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(root, "gui", "music_dialog.py"),
          encoding="utf-8") as fp:
    dialog_src = fp.read()
check("配樂助手有自動適應勾選（ttk）",
      "ttk.Checkbutton" in dialog_src and "auto_sensitivity" in dialog_src)
check("無 classic tk.Checkbutton 殘留",
      "tk.Checkbutton(" not in dialog_src.replace("ttk.Checkbutton(", ""))

from config import DEFAULT_CONFIG
check("config 預設含 auto_sensitivity",
      DEFAULT_CONFIG["ducking"].get("auto_sensitivity") is True)

# ===== 4. 真實 ffmpeg 端到端：小聲人聲也能觸發閃避 =====
def _mean_volume(path, start, end):
    """以 volumedetect 量測片段平均音量（dB）。"""
    completed = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", path,
         "-af", f"atrim={start}:{end},volumedetect", "-f", "null", "-"],
        capture_output=True, timeout=60)
    stderr = (completed.stderr or b"").decode("utf-8", errors="ignore")
    for line in stderr.splitlines():
        if "mean_volume:" in line:
            return float(line.split("mean_volume:")[1].split("dB")[0])
    return None


if audio.ffmpeg_available():
    with tempfile.TemporaryDirectory() as tmp:
        voice = os.path.join(tmp, "voice.mp4")
        music = os.path.join(tmp, "music.wav")
        mixed = os.path.join(tmp, "mixed.mp4")
        ducked = os.path.join(tmp, "ducked.wav")
        # 人聲刻意偏小聲（振幅 0.05 ≈ -26 dBFS，低於手動預設門檻 0.06），
        # 只在 2~4 秒講話——這正是先前實測「固定靈敏度不觸發」的情境。
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=black:s=160x120:d=6",
             "-f", "lavfi", "-i", "sine=frequency=300:duration=6",
             "-filter_complex",
             "[1:a]volume='if(between(t,2,4),0.05,0.0001)':eval=frame[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "libx264",
             "-t", "6", voice], capture_output=True, timeout=120)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "sine=frequency=800:duration=6",
             "-af", "volume=0.5", music], capture_output=True, timeout=120)

        settings = audio.resolve_ducking_settings(None)
        resolved = audio.resolve_auto_sensitivity(voice, settings)
        check("實測：自動靈敏度低於人聲位準",
              resolved["duck_sensitivity"] < 0.05,
              str(resolved["duck_sensitivity"]))

        # 只輸出閃避後的音樂訊號（[bgduck]），直接量測壓低量。
        fc = audio.build_ducking_filter_complex(resolved)
        fc_isolated = fc.split(";")[0] + ";" + fc.split(";")[1]
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-i", voice, "-stream_loop", "-1", "-i", music,
             "-filter_complex", fc_isolated, "-map", "[bgduck]",
             "-t", "6", ducked], capture_output=True, timeout=120)
        speech_db = _mean_volume(ducked, 2.3, 3.7)
        silence_db = _mean_volume(ducked, 0.3, 1.7)
        check("實測：講話段音樂被壓低 ≥6dB",
              speech_db is not None and silence_db is not None
              and silence_db - speech_db >= 6.0,
              f"speech={speech_db} silence={silence_db}")

        # 完整流程可正常輸出。
        audio.mix_background_music(voice, music, mixed, settings=settings)
        check("實測：完整混音輸出存在", os.path.getsize(mixed) > 0)
else:
    print("SKIP 實測（無 ffmpeg）")

print()
if failures:
    print(f"共 {len(failures)} 項失敗：{failures}")
    sys.exit(1)
print("test_v1150 全部通過")
