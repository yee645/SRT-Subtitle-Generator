# -*- coding: utf-8 -*-
"""v1.7.0 新功能測試：尋找取代、精彩訊號權重、多檔彙總、逐字動態字幕。"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

# ===== 1. 字幕尋找與取代 =====
from subtitle.textedit import count_occurrences, find_in_cues, replace_in_cues

cues = [
    {"start": 0, "end": 1, "text": "今天介紹的是克勞德"},
    {"start": 1, "end": 2, "text": "克勞德真的很好用，克勞德萬歲"},
    {"start": 2, "end": 3, "text": "沒有關鍵字的一句"},
    {"start": 3, "end": 4, "text": "Use Claude or CLAUDE today"},
]
check("尋找回傳命中索引", find_in_cues(cues, "克勞德") == [0, 1])
check("計數含句內多次", count_occurrences(cues, "克勞德") == 3)
check("空字串不命中", find_in_cues(cues, "") == [])

new, n = replace_in_cues(cues, "克勞德", "Claude")
check("全部取代次數", n == 3)
check("句內多處都取代", new[1]["text"] == "Claude真的很好用，Claude萬歲")
check("原清單不被修改", cues[1]["text"].startswith("克勞德"))
check("未命中句沿用原物件", new[2] is cues[2])

check("預設不分大小寫", count_occurrences(cues, "claude") == 2)
check("區分大小寫比對", count_occurrences(cues, "claude",
                                          case_sensitive=True) == 0)
only, n_only = replace_in_cues(cues, "克勞德", "X", only_indices=[1])
check("僅限指定索引", n_only == 2 and only[0]["text"] == "今天介紹的是克勞德")

c2 = [{"start": 0, "end": 1, "text": "價格是 $100 (含稅)"}]
n4 = replace_in_cues(c2, "$100 (含稅)", r"NT\$3000")[1]
check("特殊字元字面比對", n4 == 1)

# ===== 2. 精彩訊號權重 =====
from subtitle import review

s = review.resolve_settings({})
check("權重預設 1.0", s["weight_energy"] == 1.0 and s["weight_excite"] == 1.0)
check("彙總 TopN 預設 10", s["batch_top_n"] == 10)
s2 = review.resolve_settings({"review": {
    "weight_excite": 9, "weight_pace": -1, "weight_exclaim": "bad",
    "batch_top_n": 100}})
check("權重夾限上界", s2["weight_excite"] == 3.0)
check("權重夾限下界", s2["weight_pace"] == 0.0)
check("權重非數值回預設", s2["weight_exclaim"] == 1.0)
check("TopN 夾限上界", s2["batch_top_n"] == 50)

def make_words():
    words = []
    t = 0.0
    for text in ("今天天氣不錯而已", "哇太扯了吧太扯太神了！", "平淡的結尾句子囉"):
        for ch in text:
            words.append({"word": ch, "start": t, "end": t + 0.4})
            t += 0.4
        t += 3.0
    return words

base_items = review.analyze(make_words(), settings=review.resolve_settings({}))
check("預設權重有精彩段",
      any(review.TAG_HIGHLIGHT in i["tags"] for i in base_items))

off = review.resolve_settings({"review": {"weight_excite": 0.0,
                                          "weight_exclaim": 0.0}})
off_items = review.analyze(make_words(), settings=off)
check("權重 0 停用文字訊號",
      not any(review.TAG_HIGHLIGHT in i["tags"] for i in off_items))

hi = review.resolve_settings({"review": {"weight_excite": 3.0}})
hi_items = review.analyze(make_words(), settings=hi)
check("權重調高分數變大",
      max(i["score"] for i in hi_items) > max(i["score"] for i in base_items))

# ===== 3. 多檔審片彙總 =====
def seg(start, end, text, score=0.0, hl=False):
    tags = [review.TAG_HIGHLIGHT] if hl else []
    return {"kind": "speech", "start": start, "end": end, "text": text,
            "tags": tags, "fillers": 0, "score": score, "keep": True}

sources = [
    ("a.mp4", [seg(0, 10, "A 普通"), seg(12, 20, "A 超精彩", 3.5, True),
               seg(22, 30, "A 次精彩", 2.0, True)]),
    ("b.mp4", [seg(0, 8, "B 最強片段", 4.2, True), seg(10, 15, "B 普通")]),
]
top = review.collect_highlights(sources, top_n=2)
check("跨檔取前 N 段", len(top) == 2)
check("跨檔依分數排序", top[0]["source"] == "b.mp4" and top[0]["score"] == 4.2)
check("次名正確", top[1]["text"] == "A 超精彩")
check("TopN 大於總數時全取",
      len(review.collect_highlights(sources, top_n=50)) == 3)

with tempfile.TemporaryDirectory() as tmp:
    csv_path = os.path.join(tmp, "top.csv")
    review.export_batch_csv(top, csv_path)
    body = open(csv_path, encoding="utf-8-sig").read()
    check("彙總 CSV 內容", "B 最強片段" in body
          and body.splitlines()[1].startswith("1,b.mp4"))

    html_path = os.path.join(tmp, "sum.html")
    review.export_batch_html(sources, html_path, top_n=2)
    doc = open(html_path, encoding="utf-8").read()
    check("彙總 HTML 含統計與 Top N",
          "審片彙總" in doc and "a.mp4" in doc and "B 最強片段" in doc)
    review.export_batch_html([("c.mp4", [seg(0, 5, "普通")])], html_path, 5)
    check("無精彩段時顯示空狀態提示",
          "沒有達標的精彩片段" in open(html_path, encoding="utf-8").read())

# ===== 4. 逐字動態字幕 =====
from subtitle.segmenter import build_cues_from_words
from subtitle.exporter import DYNAMIC_MODES, cues_to_ass, cues_to_srt
from subtitle.shorts import shift_cues

check("動態模式常數", DYNAMIC_MODES == ("off", "karaoke", "word"))

seg_cfg = {"max_chars_cjk": 18, "max_chars_latin": 45,
           "min_duration": 1.0, "max_duration": 7.0, "pause_gap": 0.5}
words = []
t = 0.0
for ch in "今天要開箱的東西超級厲害":
    words.append({"word": ch, "start": t, "end": t + 0.25}); t += 0.25
t += 1.2
for w in ["it", "is", "amazing"]:
    words.append({"word": w, "start": t, "end": t + 0.3}); t += 0.35

dyn_cues = build_cues_from_words(words, seg_cfg)
check("逐字時間軸掛回 cue",
      sum(len(c.get("words", [])) for c in dyn_cues) == len(words))

style_k = {"dynamic_mode": "karaoke", "emphasis_color": "#FF0000"}
ass_k = cues_to_ass(dyn_cues, style_k)
check("卡拉OK每字一事件", ass_k.count("Dialogue:") == len(words))
check("卡拉OK當前字換色", "{\\1c&H0000FF&}今{\\r}" in ass_k
      and "{\\1c&H0000FF&}amazing{\\r}" in ass_k)

ass_w = cues_to_ass(dyn_cues, {"dynamic_mode": "word"})
check("單字彈出每字一事件", ass_w.count("Dialogue:") == len(words))
check("單字彈出帶縮放動畫", ass_w.count("\\fscx80") == len(words))

check("off 模式維持整句",
      cues_to_ass(dyn_cues, {"dynamic_mode": "off"}).count("Dialogue:")
      == len(dyn_cues))
check("未知模式視為 off",
      cues_to_ass(dyn_cues, {"dynamic_mode": "bogus"}).count("Dialogue:")
      == len(dyn_cues))
check("SRT 不受動態資料影響", "\\fscx" not in cues_to_srt(dyn_cues))

# 事件時間單調遞增且不為零長度
stamps = re.findall(r"Dialogue: 0,(\d+:\d+:\d+\.\d+),(\d+:\d+:\d+\.\d+)", ass_w)
def _sec(ts):
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)
check("動態事件時間正向", all(_sec(e) > _sec(s) for s, e in stamps))

manual = [{"start": 0, "end": 2, "text": "手動字幕"}]
check("無逐字資料退回整句",
      cues_to_ass(manual, style_k).count("Dialogue:") == 1)

# 取代與逐字資料的互動
r1, _ = replace_in_cues(dyn_cues, "amazing", "awesome")
target = [c for c in r1 if "awesome" in c["text"]][0]
check("單字層取代同步 words",
      any(w["word"] == "awesome" for w in target.get("words", [])))
r2, _ = replace_in_cues(dyn_cues, "厲害", "超猛")
k2 = cues_to_ass(r2, style_k)
check("跨字詞取代不殘留舊字", "超猛" in k2 and "厲害" not in k2)

clip = shift_cues(dyn_cues, 0.5, 2.5)
check("短片平移逐字時間軸", clip and clip[0].get("words")
      and all(w["start"] >= 0 and w["end"] <= 2.0 + 1e-6
              for w in clip[0]["words"]))

# ===== 5. 設定預設值 =====
from config import DEFAULT_CONFIG
check("樣式含 dynamic_mode 預設 off",
      DEFAULT_CONFIG["subtitle_style"]["dynamic_mode"] == "off")
check("review 含權重與 TopN 預設",
      DEFAULT_CONFIG["review"]["weight_energy"] == 1.0
      and DEFAULT_CONFIG["review"]["batch_top_n"] == 10)

print("\n" + ("ALL PASS" if not failures else f"FAILURES: {failures}"))
sys.exit(1 if failures else 0)
