# -*- coding: utf-8 -*-
"""review 審片模組功能測試（ffmpeg 以替身驗證指令組裝）。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import review

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

def mk_words(spec):
    """spec: list of (text, start, end) → whisper words（逐字切開，均分時間）。"""
    words = []
    for text, start, end in spec:
        chars = list(text)
        step = (end - start) / max(len(chars), 1)
        for i, ch in enumerate(chars):
            words.append({"word": ch, "start": start + i * step,
                          "end": start + (i + 1) * step})
    return words

# 素材模擬：開場 → 吃螺絺重來兩次（前兩次該被標記）→ 冷場 3 秒 → 口頭禪段 → 正常段
words = mk_words([
    ("大家好歡迎回到我的頻道", 0.0, 3.0),
    ("今天要開箱這台新相機的實拍表現", 4.0, 7.0),    # take 1（重複）
    ("今天要開箱這台新相機的實拍表現喔", 8.0, 11.0),  # take 2（重複）
    ("今天要開箱這台新相機的實拍表現", 12.0, 15.0),   # take 3（保留）
    ("呃就是嗯這個呃畫質呃真的嗯很棒欸", 20.0, 24.0),  # 冷場後、口頭禪多
    ("最後別忘了訂閱按讚開啟小鈴鐺", 25.0, 28.0),
])

items = review.analyze(words, media_duration=35.0)

speech = [i for i in items if i["kind"] == "speech"]
silences = [i for i in items if i["kind"] == "silence"]
check("講話段落數=6", len(speech) == 6, f"got {len(speech)}")
check("偵測到冷場(15→20)", any(abs(s["start"] - 15.0) < 0.2 and abs(s["end"] - 20.0) < 0.2 for s in silences))
check("偵測到結尾冷場(28→35)", any(abs(s["end"] - 35.0) < 0.2 for s in silences))
check("冷場預設捨棄", all(not s["keep"] for s in silences))

takes = [s for s in speech if review.TAG_REPEATED in s["tags"]]
check("前兩次重複拍攝被標記", len(takes) == 2 and all(not t["keep"] for t in takes))
check("最後一次take保留", speech[3]["keep"] and review.TAG_REPEATED not in speech[3]["tags"])
check("口頭禪段被標記且仍保留", review.TAG_FILLER in speech[4]["tags"] and speech[4]["keep"])
check("開場與結尾正常保留", speech[0]["keep"] and speech[5]["keep"])

# 搜尋
hits = review.search_segments(items, "訂閱")
check("關鍵字搜尋命中", len(hits) == 1 and "訂閱" in items[hits[0]]["text"])

# kept_ranges：緩衝與合併
ranges = review.kept_ranges(items)
check("保留區間數合理", 3 <= len(ranges) <= 4, f"got {ranges}")
check("區間有前後緩衝", ranges[0][0] == 0.0 and ranges[0][1] > 3.0)

with tempfile.TemporaryDirectory() as tmp:
    # CSV
    csv_path = os.path.join(tmp, "審片.csv")
    review.export_csv(items, csv_path)
    content = open(csv_path, encoding="utf-8-sig").read()
    check("CSV 有表頭與標記", "保留" in content and "重複拍攝" in content and "冷場" in content)

    # EDL
    edl_path = os.path.join(tmp, "cut.edl")
    review.export_edl(items, edl_path, clip_name="素材.mp4")
    edl = open(edl_path, encoding="utf-8").read()
    check("EDL 標頭正確", edl.startswith("TITLE:") and "FCM: NON-DROP FRAME" in edl)
    check("EDL 含剪輯事件", "001  AX       V     C" in edl and "FROM CLIP NAME: 素材.mp4" in edl)

    # YouTube 章節（v1.6 起依最短章節長度合併；此處縮小門檻驗證多章）
    chapters = review.export_youtube_chapters(
        items, min_chapter_seconds=10, break_gap=2)
    check("章節第一行為 0:00", chapters.startswith("0:00 "))
    check("章節含後段時間戳", "0:12" in chapters, chapters)

    # 粗剪：以替身攔截 ffmpeg 命令
    captured = {}
    class FakeProc:
        stdout = None; stderr = None
        def wait(self): return 0
    def fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        return FakeProc()
    review.ffmpeg_available = lambda: True
    import subprocess as sp
    orig = sp.Popen
    review.subprocess.Popen = fake_popen
    out = review.cut_rough_video(os.path.join(tmp, "in.mp4"), items,
                                 os.path.join(tmp, "out.mp4"))
    review.subprocess.Popen = orig
    cmd = captured["cmd"]
    fc = cmd[cmd.index("-filter_complex") + 1]
    check("粗剪 filter 含 trim/concat", "trim=start=" in fc and "concat=n=" in fc)
    check("粗剪段數與 kept_ranges 一致", f"concat=n={len(ranges)}" in fc)
    check("粗剪輸出映射正確", "[outv]" in fc and "-map" in cmd)

    # 全捨棄 → 明確報錯
    for item in items:
        item["keep"] = False
    try:
        review.cut_rough_video("x.mp4", items, "y.mp4")
        check("全捨棄應報錯", False)
    except ValueError:
        check("全捨棄應報錯", True)

# ===== 精彩片段偵測 =====
# 高能段：情緒詞 + 驚嘆句 + 快語速；其他為平穩段。
hl_words = mk_words([
    ("今天我們來看這台車的加速表現如何", 0.0, 5.0),
    ("接下來進行直線加速測試看看數據", 6.0, 11.0),
    ("哇太扯了吧這也太強了吧不會吧！！", 12.0, 14.0),   # 精彩
    ("好我們把車開回來慢慢分析剛才的數據", 16.0, 22.0),
    ("整體來說表現算是中規中矩的水準", 23.0, 29.0),
])
hl_items = review.analyze(hl_words, media_duration=30.0)
hl_speech = [i for i in hl_items if i["kind"] == "speech"]
check("精彩段被標記", review.TAG_HIGHLIGHT in hl_speech[2]["tags"],
      f"tags={[s['tags'] for s in hl_speech]}")
check("平穩段不標精彩", all(review.TAG_HIGHLIGHT not in hl_speech[i]["tags"]
                            for i in (0, 1, 3, 4)))
check("精彩段有分數", hl_speech[2]["score"] > hl_speech[0]["score"])

# 音量能量參與評分：給精彩段高 RMS
loud = [(t * 0.5, 0.9 if 12.0 <= t * 0.5 < 14.0 else 0.2) for t in range(60)]
hl_items2 = review.analyze(hl_words, media_duration=30.0, loudness=loud)
hl2 = [i for i in hl_items2 if i["kind"] == "speech"]
check("加入音量後精彩分數更高", hl2[2]["score"] > hl_speech[2]["score"])

# categorize 分類
check("分類：精彩", review.categorize(hl_speech[2]) == "highlight")
check("分類：一般", review.categorize(hl_speech[0]) == "normal")
check("分類：冷場", review.categorize(review._silence_item(0, 3)) == "silence")
check("分類：重複=待審", review.categorize(
    {"kind": "speech", "tags": [review.TAG_REPEATED, review.TAG_HIGHLIGHT]}) == "review")

# summarize 統計
stats = review.summarize(hl_items2, 30.0)
check("統計欄位齊全", all(k in stats for k in (
    "kept_seconds", "silence_seconds", "highlight_count", "filler_total")))
check("精彩統計正確", stats["highlight_count"] == 1)

# 審片標記字幕
cues = review.build_review_cues(hl_items2)
check("審片字幕含精彩前綴", any("【精彩】" in c["text"] for c in cues))
check("審片字幕含建議剪掉", any("【建議剪掉】" in c["text"] for c in cues))

# HTML 報告
with tempfile.TemporaryDirectory() as tmp2:
    html_path = os.path.join(tmp2, "報告.html")
    review.export_html_report(hl_items2, html_path, source_name="測試素材.mp4",
                              media_duration=30.0)
    doc = open(html_path, encoding="utf-8").read()
    check("HTML 有時間軸色塊", 'class="blk"' in doc and "#2e9e44" in doc)
    check("HTML 有統計與表格", "精彩片段" in doc and "<table>" in doc)
    check("HTML 段落錨點", 'id="seg0"' in doc and 'href="#seg' in doc)
    check("HTML 無外部資源", "http://" not in doc and "https://" not in doc)

# compute_loudness 在無 ffmpeg 環境優雅退化
check("無 ffmpeg 時音量分析回空", review.compute_loudness("x.mp4") == []
      if not review.ffmpeg_available() else True)

print("\n" + ("ALL PASS" if not failures else f"FAILURES: {failures}"))
sys.exit(1 if failures else 0)
