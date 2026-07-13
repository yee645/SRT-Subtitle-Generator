# -*- coding: utf-8 -*-
"""v1.10.0 新功能測試：口頭禪單字自動剪除、一鍵發佈包。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import publisher, review

# ===== 1. 口頭禪單字偵測與時間段 =====
words = [
    {"word": "今", "start": 0.0, "end": 0.3},
    {"word": "呃", "start": 0.3, "end": 0.6},
    {"word": "嗯", "start": 0.65, "end": 0.9},    # 相鄰口頭禪 → 合併
    {"word": "天", "start": 1.0, "end": 1.3},
    {"word": "um", "start": 2.0, "end": 2.4},
    {"word": "umbrella", "start": 3.0, "end": 3.5},  # 整字比對，不誤中
]
spans = review.find_filler_spans(words)
check("相鄰口頭禪合併", spans[0] == (0.3, 0.9), str(spans))
check("英文填充詞整字比對", (2.0, 2.4) in spans)
check("一般英文字不誤中", not any(3.0 <= s < 3.5 for s, _e in spans))
check("自訂口頭禪字表",
      review.find_filler_spans(
          [{"word": "啦", "start": 0, "end": 0.3}], "啦") == [(0, 0.3)])

def mk(triples):
    return [{"word": w, "start": s, "end": e} for w, s, e in triples]

ws = mk([("大", 0, .3), ("家", .3, .6), ("好", .6, .9), ("呃", 1.0, 1.4),
         ("這", 1.5, 1.8), ("集", 1.8, 2.1), ("超", 2.1, 2.4), ("讚", 2.4, 2.7)])
items = review.analyze(ws)
speech = [i for i in items if i["kind"] == "speech"]
check("analyze 記錄 filler_spans",
      speech[0]["filler_spans"] == [(1.0, 1.4)], str(speech[0]["filler_spans"]))

# ===== 2. kept_ranges 剪除口頭禪 =====
ranges_off = review.kept_ranges(items)
ranges_on = review.kept_ranges(items, drop_filler_words=True)
check("預設不剪口頭禪", len(ranges_off) == 1)
check("開啟後區間一分為二", len(ranges_on) == 2, str(ranges_on))
check("剪除後總長變短",
      sum(e - s for s, e in ranges_on) < sum(e - s for s, e in ranges_off))
check("剪點落在口頭禪範圍",
      0.95 < ranges_on[0][1] < 1.1 and 1.3 < ranges_on[1][0] < 1.45,
      str(ranges_on))

# 太短的口頭禪不剪（跳剪抖動保護）
ws2 = mk([("好", 0, .3), ("呃", .35, .40), ("讚", .5, .8)])
check("過短口頭禪不剪",
      len(review.kept_ranges(review.analyze(ws2),
                             drop_filler_words=True)) == 1)

# _subtract_spans 邊界
check("整段被挖光回空", review._subtract_spans([(0, 1)], [(0, 1)]) == [])
check("殘片過短捨棄",
      review._subtract_spans([(0.0, 1.0)], [(0.05, 0.95)]) == [])
check("不相交不受影響",
      review._subtract_spans([(0, 1)], [(2, 3)]) == [(0, 1)])

# 設定
check("cut_filler_words 預設關",
      review.resolve_settings({})["cut_filler_words"] is False)
check("cut_filler_words 可開", review.resolve_settings(
    {"review": {"cut_filler_words": True}})["cut_filler_words"] is True)

# ===== 3. 發佈包：標題候選 =====
def seg(start, end, text, score=0.0, hl=False, keep=True):
    tags = [review.TAG_HIGHLIGHT] if hl else []
    return {"kind": "speech", "start": start, "end": end, "text": text,
            "tags": tags, "fillers": 0, "score": score, "keep": keep}

pub_items = [
    seg(0, 8, "大家好今天要開箱這台螢幕保護神器真的有夠猛"),
    seg(10, 20, "這台螢幕保護神器居然只要三百塊太扯了吧", 3.2, True),
    seg(22, 30, "測試結果螢幕保護神器直接擋下十次摔落", 2.1, True),
    seg(32, 40, "被捨棄的段落不該入選標題", 9.9, True, keep=False),
    seg(42, 50, "we test the gadget and the gadget survives a gadget drop"),
]
titles = publisher.suggest_titles(pub_items, count=3, max_chars=40)
check("精彩段依分數排最前", titles[0].startswith("這台螢幕保護神器"), str(titles))
check("捨棄段不入選", all("捨棄" not in t for t in titles))
check("標題不超過長度上限", all(len(t) <= 40 for t in titles))
long_title = publisher.suggest_titles(
    [seg(0, 5, "很長的一句" * 20, 5.0, True)], count=1, max_chars=20)
check("超長文字截斷", long_title and len(long_title[0]) <= 20)

# ===== 4. 發佈包：標籤 =====
tags = publisher.suggest_tags(pub_items, tag_count=10,
                              extra_words="神器, 沒講過的詞")
check("自訂詞命中最優先", tags[0] == "神器", str(tags))
check("未命中的自訂詞不列", "沒講過的詞" not in tags)
check("中文高頻 n-gram 入選", any("螢幕保護" in t for t in tags), str(tags))
check("英文高頻詞入選", "gadget" in tags)
check("英文停用詞剔除", "the" not in tags and "and" not in tags)

# ===== 5. 發佈包：設定夾限與整包輸出 =====
s = publisher.resolve_publish_settings({})
check("發佈包預設值", s == publisher.DEFAULT_PUBLISH)
s2 = publisher.resolve_publish_settings({"publish": {
    "title_candidates": 99, "title_max_chars": 5, "tag_count": "bad"}})
check("發佈包夾限", s2["title_candidates"] == 6
      and s2["title_max_chars"] == 20 and s2["tag_count"] == 15)

chapters = review.build_chapters(pub_items, min_chapter_seconds=10,
                                 break_gap=2)
pack = publisher.build_publish_pack(
    pub_items, chapters=chapters, source_name="開箱.mp4",
    extra_words="神器")
check("發佈包含四大區塊", all(key in pack for key in
      ("建議標題", "描述草稿", "章節：", "建議標籤")), pack[:200])
check("描述帶開場鉤子", "大家好今天要開箱" in pack)
check("hashtag 行", "#神器" in pack)
check("空清單安全", "沒有可用的段落文字"
      in publisher.build_publish_pack([]))

# ===== 6. config 預設值 =====
from config import DEFAULT_CONFIG
check("config 含 publish 區塊",
      DEFAULT_CONFIG["publish"] == publisher.DEFAULT_PUBLISH)
check("config 含 cut_filler_words",
      DEFAULT_CONFIG["review"]["cut_filler_words"] is False)

print("\n" + ("ALL PASS" if not failures else f"FAILURES: {failures}"))
sys.exit(1 if failures else 0)
