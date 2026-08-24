# -*- coding: utf-8 -*-
"""v1.46.0 新功能測試：發佈包描述草稿重寫（有結構、且通過自己的健檢）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import publisher as pub
from subtitle.review import TAG_HIGHLIGHT
from subtitle import desccheck as dc


def seg(start, end, text, score=0.0, highlight=False, keep=True):
    return {"kind": "speech", "start": start, "end": end, "text": text,
            "score": score, "tags": [TAG_HIGHLIGHT] if highlight else [],
            "keep": keep, "fillers": 0}


ITEMS = [
    seg(0, 6, "那個 就是說 今天我們要來聊一個東西"),
    seg(7, 14, "就是怎麼樣讓你的影片節奏變得更好看，這件事其實有三個關鍵",
        8.0, True),
    seg(15, 22, "第一個技巧是抓剪點，要對到說話的停頓", 7.5, True),
    seg(23, 30, "第二個技巧是配樂的處理", 7.0, True),
    seg(31, 40, "最後一個是字幕的細節，很多人都忽略", 6.5, True),
]
CHAPTERS = [{"start": 0, "title": "開場"}, {"start": 15, "title": "技巧一"}]
TAGS = ["剪輯", "教學", "節奏"]

desc = pub.build_description(ITEMS, CHAPTERS, TAGS)

# ===== 1. 開頭取的是「最精彩那句」而不是「第一段」 =====
# 舊版是 kept[0]["text"][:60]，產出「那個 就是說 今天我們要來聊一個東西……」
# ——句首贅詞沒剝、攔腰截斷、而且取的是最沒資訊量的第一段。
first_line = desc.splitlines()[0]
check("開頭用精彩分數最高的句子", "節奏變得更好看" in first_line, first_line)
check("開頭不是第一段的內容", "今天我們要來聊一個東西" not in first_line)
check("開頭剝掉句首贅詞",
      not first_line.startswith(("那個", "就是", "然後")), first_line)
check("開頭不以刪節號收尾（不是攔腰截斷）",
      "……" not in first_line, first_line)
check("開頭是完整句子", first_line.endswith("。"), first_line)

# ===== 2. 結構 =====
check("有摘要區塊", "這支影片會講到：" in desc)
check("摘要逐點列出", desc.count("・") >= 2, str(desc.count("・")))
check("摘要不重複開頭那句",
      desc.count("節奏變得更好看") == 1)
check("有章節區塊", "章節：" in desc and "0:00 開場" in desc)
check("有 hashtag", "#剪輯" in desc)
# 調研明講 boilerplate 要放最下面，放最上面會佔掉權重最高的前 200 字元。
check("頻道樣板放在最後",
      desc.rstrip().splitlines()[-1].startswith("（訂閱"))
check("樣板排在章節與 hashtag 之後",
      desc.index("訂閱") > desc.index("#剪輯") > desc.index("章節："))
check("開頭那一行不是樣板", not desc.splitlines()[0].startswith("（訂閱"))

# ===== 3. 這一版的驗收標準：產出的草稿要通過自己的說明欄結構健檢 =====
result = dc.analyze_description(desc, 600)
check("草稿通過自己的結構健檢（無 bad）", result["ok"] is True)
check("草稿的每一項都是通過",
      all(f["level"] == dc.LEVEL_GOOD for f in result["findings"]),
      str([(f["level"], f["title"]) for f in result["findings"]]))

# 對照組：舊版的做法（第一段硬截 60 字）會被自己的健檢抓到。
old_style = ITEMS[0]["text"][:60] + "……"
old_result = dc.analyze_description(old_style, 600)
check("舊做法會被健檢標記",
      any(f["level"] != dc.LEVEL_GOOD for f in old_result["findings"]),
      str([(f["level"], f["title"]) for f in old_result["findings"]]))

# ===== 4. 主題關鍵字要落在權重最高的開頭 =====
# 調研：前 200 字元權重最高，主題詞放最後一段等於白放。使用者自訂的
# 情緒詞（與審片設定共用）若真的有講到，開頭句就優先挑講到它的那句。
kw_items = [
    seg(0, 6, "先講一下今天的緣起", 9.0, True),
    seg(7, 14, "字幕這件事其實比大家想的重要很多", 5.0, True),
]
kw_desc = pub.build_description(kw_items, None, None, extra_words="字幕")
check("開頭優先挑講到自訂關鍵字的那句",
      "字幕" in kw_desc.splitlines()[0], kw_desc.splitlines()[0])
check("關鍵字挑不到時照精彩分數",
      "緣起" in pub.build_description(
          kw_items, None, None, extra_words="沒講過的詞").splitlines()[0])
check("被挑去當開頭的句子不會又出現在摘要",
      kw_desc.count("字幕這件事") == 1, kw_desc)

# ===== 5. 參數與邊界 =====
check("可調摘要點數",
      pub.build_description(ITEMS, None, None,
                            summary_points=1).count("・") == 1)
check("摘要點數 0 時不出摘要區塊",
      "這支影片會講到" not in pub.build_description(
          ITEMS, None, None, summary_points=0))
check("沒有章節時不出章節區塊",
      "章節：" not in pub.build_description(ITEMS, None, TAGS))
check("沒有標籤時不出 hashtag",
      "#" not in pub.build_description(ITEMS, CHAPTERS, None))
check("空清單回空字串", pub.build_description([], CHAPTERS, TAGS) == "")
check("None 回空字串", pub.build_description(None) == "")
check("全部都被捨棄時回空字串",
      pub.build_description([seg(0, 5, "不要", keep=False)]) == "")
check("沒有精彩標記時退回分數排序（仍不是取第一段）",
      "節奏變得更好看" in pub.build_description(
          [seg(0, 6, "那個 就是說 開頭廢話"),
           seg(7, 14, "怎麼樣讓你的影片節奏變得更好看", 8.0)],
          None, None).splitlines()[0])
check("只有一句時也能組出草稿",
      pub.build_description([seg(0, 6, "這支影片講剪輯技巧", 5.0, True)]) != "")
check("hashtag 最多取五個",
      pub.build_description(ITEMS, None, list("abcdefgh")).count("#") == 5)

# ===== 6. 發佈包整體 =====
pack = pub.build_publish_pack(ITEMS, pub.resolve_publish_settings(),
                              CHAPTERS, "示範.mp4")
check("發佈包含描述草稿區塊", "【描述草稿" in pack)
check("發佈包的描述用新的建構器", "這支影片會講到：" in pack)
check("發佈包不再出現舊的截斷刪節號",
      "今天我們要來聊一個東西……" not in pack)
check("描述區塊與標籤區塊之間有空行",
      "\n\n【建議標籤" in pack, repr(pack[pack.index("（訂閱"):][:60]))
check("發佈包仍有標題候選", "【建議標題" in pack)
check("沒有段落時發佈包不會炸",
      isinstance(pub.build_publish_pack([], pub.resolve_publish_settings()),
                 str))

# ===== 7. 重用既有邏輯，不重新實作 =====
import inspect
src = inspect.getsource(pub.build_description)
check("句子清理重用 _clean_title", "_clean_title" in src)
check("章節排版重用 _format_chapters", "_format_chapters" in src)
check("依精彩標記挑句", "TAG_HIGHLIGHT" in src)
check("沒有殘留的舊 hook 死碼",
      "hook" not in inspect.getsource(pub.build_publish_pack))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.46.0 測試全數通過。")
