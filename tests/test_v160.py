# -*- coding: utf-8 -*-
"""v1.6.0 新功能測試：YouTube 章節智慧合併、重點字上色。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

# ===== 1. 章節智慧合併 =====
from subtitle import review

def seg(start, end, text, keep=True):
    return {"kind": "speech", "start": start, "end": end, "text": text,
            "tags": [], "fillers": 0, "score": 0.0, "keep": keep}

# 模擬 10 分鐘影片：段落密集，僅在大停頓＋達最短長度時切章
items = [
    seg(0, 25, "開場介紹今天的主題"),
    seg(26, 55, "先講第一個重點的細節"),      # 小間隔：不切
    seg(60, 110, "接著進入第二部分的實測"),    # 5 秒間隔且已 60 秒：切
    seg(112, 150, "實測數據的補充說明"),
    seg(155, 170, "被捨棄的重複段", keep=False),
    seg(175, 260, "第三部分：價格與競品比較"),  # 大間隔且已達長度：切
    seg(262, 300, "總結與訂閱呼籲"),
]
chapters = review.build_chapters(items, min_chapter_seconds=60, break_gap=3)
check("章節數合理合併", len(chapters) == 3, f"got {len(chapters)}: {chapters}")
check("首章強制 0:00", chapters[0]["start"] == 0.0)
check("次章起點正確", chapters[1]["start"] == 60)
check("三章起點正確", chapters[2]["start"] == 175)
check("捨棄段不影響章節標題",
      all("重複段" not in c["title"] for c in chapters))

# 最短長度調大 → 章節更少
fewer = review.build_chapters(items, min_chapter_seconds=200, break_gap=3)
check("最短長度調大章節變少", len(fewer) < len(chapters), f"{len(fewer)}")

# 全部捨棄 → 空清單
check("無保留段落回空", review.build_chapters(
    [seg(0, 5, "x", keep=False)]) == [])

# 文字輸出格式
text = review.export_youtube_chapters(items, min_chapter_seconds=60,
                                      break_gap=3)
lines = text.splitlines()
check("章節文字三行", len(lines) == 3, text)
check("格式 分:秒＋標題", lines[1].startswith("1:00 ") and
      lines[2].startswith("2:55 "), text)

# settings 夾限
s = review.resolve_settings({"review": {"chapter_min_seconds": 5}})
check("章節最短夾限下界", s["chapter_min_seconds"] == 10.0)

# ===== 2. 重點字上色 =====
from subtitle import exporter

# 2a. 詞清單解析（長詞優先、去重）
words = exporter.parse_emphasis_words("免費, 超值 免費、破盤價")
check("詞清單解析去重", set(words) == {"免費", "超值", "破盤價"}, str(words))
check("長詞排前", words[0] == "破盤價")

# 2b. 行內標籤
out = exporter.apply_emphasis("今天全部免費送給大家", ["免費"], "#FF0000")
check("重點字包上色標籤", "{\\1c&H0000FF&}免費{\\r}" in out, out)
check("其餘文字不變", out.startswith("今天全部") and out.endswith("送給大家"))

# 2c. 拉丁字不分大小寫、多詞單次比對
out2 = exporter.apply_emphasis("Buy now or BUY later", ["buy"], "#FFD700")
check("拉丁字不分大小寫", out2.count("{\\r}") == 2, out2)

# 2d. cues_to_ass 整合：啟用才生效
cues = [{"start": 0.0, "end": 2.0, "text": "這價格太扯了"}]
style_on = {"emphasis_enabled": True, "emphasis_words": "太扯",
            "emphasis_color": "#FFD700"}
style_off = {"emphasis_enabled": False, "emphasis_words": "太扯"}
ass_on = exporter.cues_to_ass(cues, style_on)
ass_off = exporter.cues_to_ass(cues, style_off)
check("啟用時 ASS 含色彩標籤", "\\1c&H00D7FF&" in ass_on, ass_on[-200:])
check("停用時 ASS 無標籤", "\\1c&H00D7FF&" not in ass_off)

# 2e. SRT 輸出不受影響（不含 ASS 標籤）
srt = exporter.cues_to_srt(cues)
check("SRT 不含標籤", "\\1c" not in srt)

# 2f. 空詞清單安全
check("空詞清單原样返回",
      exporter.apply_emphasis("文字", [], "#FFD700") == "文字")


# ===== 3. v1.6.1 精修：切段函式與報告章節 =====

# 3a. split_emphasis_segments 切段正確
segs = exporter.split_emphasis_segments("今天全部免費送給大家", ["免費"])
check("切段結構正確", segs == [("今天全部", False), ("免費", True),
                               ("送給大家", False)], str(segs))
check("切段重組還原原文", "".join(s for s, _e in segs) == "今天全部免費送給大家")
segs2 = exporter.split_emphasis_segments("免費就是免費", ["免費"])
check("首尾命中切段", segs2[0] == ("免費", True) and segs2[-1] == ("免費", True))
check("無詞清單單段返回",
      exporter.split_emphasis_segments("文字", []) == [("文字", False)])
check("空文字回空清單", exporter.split_emphasis_segments("", ["x"]) == [])

# 3b. apply_emphasis 與切段一致（同一來源）
joined = exporter.apply_emphasis("今天全部免費送給大家", ["免費"], "#FF0000")
plain = joined.replace("{\\1c&H0000FF&}", "").replace("{\\r}", "")
check("標籤移除後還原原文", plain == "今天全部免費送給大家", plain)

# 3c. HTML 報告含建議章節
import tempfile as _tf
with _tf.TemporaryDirectory() as _tmp:
    _p = os.path.join(_tmp, "r.html")
    review.export_html_report(
        items, _p, source_name="s.mp4", media_duration=310.0,
        chapters=review.build_chapters(items, min_chapter_seconds=60,
                                       break_gap=3))
    _doc = open(_p, encoding="utf-8").read()
    check("報告含建議章節區塊", "建議章節" in _doc and "0:00 " in _doc)
    check("報告章節含次章", "1:00 " in _doc, _doc[-500:])
    review.export_html_report(items, _p, source_name="s.mp4",
                              media_duration=310.0)
    _doc2 = open(_p, encoding="utf-8").read()
    check("未傳章節時報告無該區塊", "建議章節" not in _doc2)

print("\n" + ("ALL PASS" if not failures else f"FAILURES: {failures}"))
sys.exit(1 if failures else 0)
