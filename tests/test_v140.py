# -*- coding: utf-8 -*-
"""v1.4.0 新功能測試：重複字幕修復、審片參數可調、轉錄快取。"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

# ===== 1. transcriber._dedupe_words（Issue #4）=====
from subtitle.transcriber import _dedupe_words

# 1a. 同字同時間戳重複（issue 截圖情境）
words = [
    {"word": "你好", "start": 1.0, "end": 1.5},
    {"word": "你好", "start": 1.0, "end": 1.5},
    {"word": "你好", "start": 1.02, "end": 1.5},
    {"word": "世界", "start": 1.6, "end": 2.0},
]
out = _dedupe_words(words)
check("同時間戳重複字只留一個", [w["word"] for w in out] == ["你好", "世界"],
      f"got {[w['word'] for w in out]}")

# 1b. 片語迴圈（靜音幻覺：同句連續多次、時間前進）
loop = []
t = 10.0
for _ in range(6):
    for ch, dur in (("謝", 0.2), ("謝", 0.2), ("觀", 0.2), ("看", 0.2)):
        loop.append({"word": ch, "start": t, "end": t + dur})
        t += dur
words2 = ([{"word": "正", "start": 9.0, "end": 9.3}] + loop
          + [{"word": "常", "start": 30.0, "end": 30.3}])
out2 = _dedupe_words(words2)
text2 = "".join(w["word"] for w in out2)
check("片語迴圈收斂為一組", text2 == "正謝謝觀看常", f"got {text2}")

# 1c. 正常少量重複不誤刪
words3 = [{"word": w, "start": i, "end": i + 0.5}
          for i, w in enumerate(["好", "好", "好", "沒", "問", "題"])]
out3 = _dedupe_words(words3)
check("三連字保留不誤刪", "".join(w["word"] for w in out3) == "好好好沒問題")

# 1d. 單字迴圈（4+ 次）收斂
words4 = [{"word": "對", "start": i * 0.3, "end": i * 0.3 + 0.2}
          for i in range(8)] + [{"word": "啊", "start": 3.0, "end": 3.2}]
out4 = _dedupe_words(words4)
check("單字 8 連發收斂", "".join(w["word"] for w in out4) == "對啊",
      f"got {''.join(w['word'] for w in out4)}")

# ===== 2. segmenter 重複 cue 合併 =====
from subtitle.segmenter import _merge_duplicate_cues

cues = [
    {"start": 1.0, "end": 3.0, "text": "同一句話"},
    {"start": 3.0, "end": 5.0, "text": "同一句話"},
    {"start": 5.1, "end": 7.0, "text": "同一句話"},
    {"start": 9.0, "end": 10.0, "text": "同一句話"},   # 相隔 2 秒，不合併
    {"start": 11.0, "end": 12.0, "text": "另一句"},
]
merged = _merge_duplicate_cues([dict(c) for c in cues], max_duration=7.0)
check("相鄰同文字 cue 合併", len(merged) == 3, f"got {len(merged)}")
check("合併不超過最長秒數", merged[0]["end"] - merged[0]["start"] <= 7.0)
check("遠距同文字不合併", merged[1]["start"] == 9.0)

# ===== 3. 轉錄快取 =====
from subtitle import transcache

with tempfile.TemporaryDirectory() as tmp:
    os.chdir(tmp)  # CACHE_DIR 為相對路徑
    media = os.path.join(tmp, "a.mp4")
    open(media, "wb").write(b"data")
    cfg = {"model": "base", "language": "zh-TW", "use_api": False, "prompt": ""}

    key1 = transcache.make_key(media, cfg)
    check("快取未命中回 None", transcache.load_cached_words(key1) is None)
    sample = [{"word": "測", "start": 0.0, "end": 0.5}]
    transcache.save_cached_words(key1, sample)
    check("快取寫入後可讀回", transcache.load_cached_words(key1) == sample)

    # 設定不同 → 不同 key
    key2 = transcache.make_key(media, dict(cfg, model="small"))
    check("模型不同 key 不同", key1 != key2)
    key3 = transcache.make_key(media, cfg, initial_prompt="提示")
    check("提示不同 key 不同", key1 != key3)

    # 檔案內容變動（mtime/size 改變）→ key 失效
    time.sleep(1.1)
    open(media, "wb").write(b"data-changed!")
    key4 = transcache.make_key(media, cfg)
    check("檔案變動 key 失效", key4 != key1)

    # 損毀快取回 None
    with open(transcache._cache_path(key1), "w") as fp:
        fp.write("{broken")
    check("損毀快取回 None", transcache.load_cached_words(key1) is None)

    check("清除快取", transcache.clear_cache() >= 1)

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ===== 4. transcribe() 快取整合（以替身引擎驗證） =====
from subtitle import transcriber

with tempfile.TemporaryDirectory() as tmp:
    os.chdir(tmp)
    media = os.path.join(tmp, "b.mp4")
    open(media, "wb").write(b"audio")
    calls = {"n": 0}
    def fake_local(audio_path, cfg, cb, prompt):
        calls["n"] += 1
        return [{"word": "嗨", "start": 0.0, "end": 0.5}]
    orig = transcriber._transcribe_with_local
    transcriber._transcribe_with_local = fake_local
    config = {"transcription": {"model": "base", "language": "auto",
                                "use_api": False, "api_key": "",
                                "python_path": "", "prompt": "",
                                "use_cache": True}}
    r1 = transcriber.transcribe(media, config)
    r2 = transcriber.transcribe(media, config)
    check("第二次轉錄走快取（引擎只呼叫一次）", calls["n"] == 1 and r1 == r2,
          f"calls={calls['n']}")
    config["transcription"]["use_cache"] = False
    transcriber.transcribe(media, config)
    check("關閉快取時重新辨識", calls["n"] == 2)
    transcriber._transcribe_with_local = orig

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ===== 5. 審片參數可調 =====
from subtitle import review

def mk_words(spec):
    words = []
    for text, start, end in spec:
        chars = list(text)
        step = (end - start) / max(len(chars), 1)
        for i, ch in enumerate(chars):
            words.append({"word": ch, "start": start + i * step,
                          "end": start + (i + 1) * step})
    return words

hl_words = mk_words([
    ("今天我們來看這台車的加速表現如何", 0.0, 5.0),
    ("接下來進行直線加速測試看看數據", 6.0, 11.0),
    ("這段普普通通沒有什麼特別亮點", 12.0, 17.0),
    ("好我們把車開回來慢慢分析剛才的數據", 18.0, 24.0),
    ("整體來說表現算是中規中矩的水準", 25.0, 31.0),
])

# 5a. resolve_settings 預設與夾限
s = review.resolve_settings({})
check("resolve_settings 給預設值", s["highlight_sensitivity"] == 1.0
      and s["silence_gap"] == 2.0)
s2 = review.resolve_settings({"review": {"highlight_sensitivity": 99,
                                          "take_similarity": 0.1}})
check("參數夾限生效", s2["highlight_sensitivity"] == 3.0
      and s2["take_similarity"] == 0.5)

# 5b. 自訂情緒詞：預設不標，加入自訂詞後被標為精彩
base = review.analyze(hl_words, media_duration=32.0)
base_hl = sum(1 for i in base if review.TAG_HIGHLIGHT in i["tags"])
custom = review.resolve_settings(
    {"review": {"extra_excite_words": "亮點, 加速"}})
tuned = review.analyze(hl_words, media_duration=32.0, settings=custom)
tuned_hl = sum(1 for i in tuned if review.TAG_HIGHLIGHT in i["tags"])
check("自訂情緒詞增加精彩標記", tuned_hl > base_hl,
      f"base={base_hl} tuned={tuned_hl}")

# 5c. 敏感度：調低後標記變少（或不變），調高後不少於原本
strict = review.analyze(hl_words, media_duration=32.0,
    settings=review.resolve_settings(
        {"review": {"extra_excite_words": "亮點, 加速",
                    "highlight_sensitivity": 0.3}}))
strict_hl = sum(1 for i in strict if review.TAG_HIGHLIGHT in i["tags"])
loose = review.analyze(hl_words, media_duration=32.0,
    settings=review.resolve_settings(
        {"review": {"extra_excite_words": "亮點, 加速",
                    "highlight_sensitivity": 3.0}}))
loose_hl = sum(1 for i in loose if review.TAG_HIGHLIGHT in i["tags"])
check("敏感度低→標記較少", strict_hl <= tuned_hl,
      f"strict={strict_hl} tuned={tuned_hl}")
check("敏感度高→標記不少於原本", loose_hl >= tuned_hl,
      f"loose={loose_hl} tuned={tuned_hl}")

# 5d. 自訂口頭禪字表
filler_words = mk_words([("這個那個這個那個這個講話內容", 0.0, 6.0)])
s_filler = review.resolve_settings({"review": {"filler_words": "這那",
                                               "filler_density": 0.1}})
items_f = review.analyze(filler_words, media_duration=7.0, settings=s_filler)
speech_f = [i for i in items_f if i["kind"] == "speech"]
check("自訂口頭禪字表生效", any(review.TAG_FILLER in i["tags"] for i in speech_f))

# 5e. 冷場門檻可調
gap_words = mk_words([("第一段", 0.0, 1.0), ("第二段", 4.5, 5.5)])
s_low = review.resolve_settings({"review": {"silence_gap": 3.0}})
s_high = review.resolve_settings({"review": {"silence_gap": 5.0}})
low_items = review.analyze(gap_words, media_duration=6.0, settings=s_low)
high_items = review.analyze(gap_words, media_duration=6.0, settings=s_high)
check("冷場門檻低→偵測到冷場",
      any(i["kind"] == "silence" for i in low_items))
check("冷場門檻高→不偵測",
      not any(i["kind"] == "silence" for i in high_items))

print("\n" + ("ALL PASS" if not failures else f"FAILURES: {failures}"))
sys.exit(1 if failures else 0)
