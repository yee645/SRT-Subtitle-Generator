# -*- coding: utf-8 -*-
"""
`subtitle/ocrlayout.py` 測試：把 OCR 的帶座標字塊併回可讀段落。

這一份是 ROADMAP 第 9 項（螢幕畫面翻譯）調研階段的產物之一，對應調研清單
A-3「OCR 結果的排版還原」。**測資不是編的**——`tests/data/ocr_boxes.json`
是用 ffmpeg `drawtext` 合成四張難例圖之後，真的餵給 tesseract 5.3.4 跑出
來的 TSV（連座標與信心值都是原樣），所以這裡驗的是真實輸出的形狀，不是
我想像中 OCR 會長什麼樣。測試本身不需要裝 tesseract。

守住四件事，每一件都是實測踩出來的：

  1. **CJK 之間不可以有空白。** 日文與繁中那兩張圖辨識其實一字不差，但
     tesseract 逐字切開，直接串接會得到「扉 は 三 つ の 封印」。
  2. **句子中間的硬換行要接回去。** 對話框折成四行，接不回去就是四個殘
     句，翻譯只能逐行猜。
  3. **兩欄版面要分得開，而且只有真的兩欄才分。** 一列裡出現一個大洞多
     半是那幾個字沒被辨識出來，不是分欄——彩色場景那張圖就是這樣，只看
     單列會把一段話切成假的兩欄。
  4. **讀不到的時候要說讀不到**，不要把亂碼送去翻譯。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle.ocrlayout import (DEFAULT_OCRLAYOUT, describe_verdict,
                                find_column_edges, group_lines, join_boxes,
                                layout_text, resolve_ocrlayout_settings)

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


_here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_here, "data", "ocr_boxes.json"), encoding="utf-8") as fp:
    FIXTURES = json.load(fp)


def box(text, left, top, width=None, height=24, conf=95.0):
    return {"text": text, "left": left, "top": top,
            "width": width if width is not None else len(text) * 14,
            "height": height, "conf": conf}


# ===== 1. 設定：預設值、夾範圍 ==========================================

base = resolve_ocrlayout_settings(None)
check("沒有設定檔時取得預設值",
      base["min_conf"] == DEFAULT_OCRLAYOUT["min_conf"]
      and base["usable_conf"] == DEFAULT_OCRLAYOUT["usable_conf"])
check("設定檔的值會被讀進來",
      resolve_ocrlayout_settings({"ocrlayout": {"min_conf": 70}})["min_conf"] == 70.0)
check("離譜的值會被夾回合理範圍（不是照單全收）",
      resolve_ocrlayout_settings({"ocrlayout": {"column_gap_ratio": 999}})
      ["column_gap_ratio"] == 12.0
      and resolve_ocrlayout_settings({"ocrlayout": {"para_gap_ratio": 0.01}})
      ["para_gap_ratio"] == 1.05)
check("不認得的鍵不會混進來",
      "nonsense" not in resolve_ocrlayout_settings({"ocrlayout": {"nonsense": 1}}))


# ===== 2. 串接規則 =======================================================

check("英文字之間補一個空白",
      join_boxes([box("Press", 0, 0), box("F", 80, 0)]) == "Press F")
check("CJK 之間不補空白（tesseract 會逐字切開）",
      join_boxes([box("扉", 0, 0), box("は", 30, 0), box("三", 60, 0)]) == "扉は三")
check("CJK 與拉丁字混排時也不補空白（「按F撿起」不是「按 F 撿起」）",
      join_boxes([box("按", 0, 0), box("F", 30, 0), box("撿起", 60, 0)]) == "按F撿起")
check("收尾標點前面不補空白",
      join_boxes([box("north", 0, 0), box(".", 70, 0)]) == "north.")
check("起始括號後面不補空白",
      join_boxes([box("(", 0, 0), box("note", 20, 0)]) == "(note")
check("空字塊被略過，不會多出空白",
      join_boxes([box("A", 0, 0), {"text": "  ", "left": 20, "top": 0,
                                   "width": 5, "height": 24, "conf": 90},
                  box("B", 40, 0)]) == "A B")


# ===== 3. 分列：靠垂直重疊，不是靠 top 相等 =============================

mixed = [box("扉", 32, 46, 57, 29), box("は", 101, 49, 30, 24),
         box("三", 135, 51, 26, 22), box("つ", 149, 41, 40, 30)]
check("同一列的 top 差 10px 仍算同一列（實測日文那張圖就是 41~51）",
      len(group_lines(mixed)) == 1, str(len(group_lines(mixed))))
two = [box("first", 0, 10, 60, 24), box("second", 0, 80, 70, 24)]
check("差得夠遠就是兩列", len(group_lines(two)) == 2)


# ===== 4. 欄界：跨列一致才算，且要取最左邊那一塊的起點 ==================

real_two_col = group_lines(FIXTURES["20_two_column"])
edges = find_column_edges(real_two_col, 3.0, 15.0)
check("真的兩欄版面抓得到一條欄界", len(edges) == 1, str(edges))
check("欄界取的是最左邊那一塊的起點（取平均會把 x=700 的字塊留在左欄，"
      "兩欄內容整個交錯——實測踩過）",
      edges and edges[0] == 700, str(edges))

one_col_with_holes = [
    [box("The", 30, 50, 54), box("gate", 100, 50, 60), box("seals", 700, 50, 70)],
    [box("Press", 30, 105, 80), box("follow", 900, 105, 90)],
]
check("各列的大洞落在不同 x 時不算分欄（那是漏字，不是版面）",
      find_column_edges(one_col_with_holes, 3.0, 15.0) == [],
      str(find_column_edges(one_col_with_holes, 3.0, 15.0)))
check("只有一列時不可能判斷欄界",
      find_column_edges([one_col_with_holes[0]], 3.0, 15.0) == [])


# ===== 5. 真實資料：四個案例的完整結果 ==================================

jp = layout_text(FIXTURES["11_japanese"])
check("日文：併回去之後一個空白都沒有",
      " " not in jp["text"] and "　" not in jp["text"], repr(jp["text"][:40]))
check("日文：內容正確（逐字併回原句）",
      jp["text"].replace("\n", "") == "扉は三つの封印を見つけるまで開かない。Fキーでランタンを拾い、北へ進め。",
      repr(jp["text"]))

zh = layout_text(FIXTURES["12_chinese"])
check("繁中：中文字之間沒有空白",
      "中 文" not in zh["text"] and "這 扇" not in zh["text"], repr(zh["text"][:40]))
check("繁中：「按F撿起提燈」沒有被拆開",
      "按F撿起提燈" in zh["text"], repr(zh["text"]))

para = layout_text(FIXTURES["21_wrapped_para"])
check("對話框：四行硬換行併成一段（不是四個殘句）",
      len(para["paragraphs"]) == 1, str(len(para["paragraphs"])))
check("對話框：句子真的接起來了（跨行的片語不再斷開）",
      "the bridge collapsed years ago" in para["text"], repr(para["text"][:90]))
check("對話框：只有一欄", para["columns"] == 1)

cols = layout_text(FIXTURES["20_two_column"])
check("兩欄版面：分成兩段", len(cols["paragraphs"]) == 2,
      str(len(cols["paragraphs"])))
check("兩欄版面：左欄只有左欄的項目",
      "Graphics Settings" in cols["paragraphs"][0]
      and "Audio" not in cols["paragraphs"][0], repr(cols["paragraphs"][0]))
check("兩欄版面：右欄只有右欄的項目",
      "Audio Settings" in cols["paragraphs"][1]
      and "Graphics" not in cols["paragraphs"][1], repr(cols["paragraphs"][1]))


# ===== 6. 斷字與分段 =====================================================

hyphen = layout_text([box("under-", 30, 10, 90), box("stand", 30, 50, 80)])
check("行尾連字號黏回去並吃掉連字號",
      hyphen["text"] == "understand", repr(hyphen["text"]))

far = layout_text([box("First", 30, 10, 60), box("block", 100, 10, 60),
                   box("Second", 30, 200, 80), box("block", 120, 200, 60)])
check("垂直間距拉很開時分成兩段", len(far["paragraphs"]) == 2,
      str(far["paragraphs"]))


# ===== 7. 信心值：讀不到就要說讀不到 =====================================

junk = [box("Ae", 10, 10, 30, 24, conf=20.0), box("~x", 60, 10, 30, 24, conf=18.0)]
res = layout_text(junk)
check("整塊都是低信心碎片時判定為讀不到",
      res["verdict"] == "unreadable", f"{res['verdict']} conf={res['mean_conf']}")
check("讀不到時不會回傳一串亂碼當正文", res["text"] == "", repr(res["text"]))
check("讀不到時給的訊息講得出下一步（沉默＝使用者以為壞了）",
      "重框" in describe_verdict(res) or "框" in describe_verdict(res),
      describe_verdict(res))

weak = layout_text([box("maybe", 10, 10, 70, 24, conf=52.0),
                    box("words", 90, 10, 70, 24, conf=50.0)])
check("信心中等時判定為勉強可用，並且照樣給出文字",
      weak["verdict"] == "weak" and weak["text"] == "maybe words",
      f"{weak['verdict']} {weak['text']!r}")
check("勉強可用時的訊息有提醒可能有錯字",
      "錯字" in describe_verdict(weak) or "可能" in describe_verdict(weak))

# 這一組是本模組最重要的一條，而且第一版寫錯過：原本只看「留下來那些字
# 塊的平均信心」，結果那張**畫面上根本沒有字**的雜訊圖照樣回報 ok——
# tesseract 在它上面吐出 125 個字塊、整體平均只有 21.9，但把低於 45 的丟
# 掉之後，剩下 18 塊的平均是 68.2。判讀要看過濾**前**的平均與留存比例。
noise = layout_text(FIXTURES["05_noise_no_text"])
check("整張圖沒有字時判定為讀不到（實測資料：125 個字塊、整體信心 21.9、"
      "但濾掉低分後剩下那 18 塊的平均是 68.2——只看後者會誤判成 ok）",
      noise["verdict"] == "unreadable",
      f"{noise['verdict']} raw={noise['raw_mean_conf']:.1f} "
      f"kept={noise['mean_conf']:.1f} ratio={noise['kept_ratio']:.2f}")
check("判定讀不到時不會把亂碼當正文送出去", noise["text"] == "",
      repr(noise["text"][:60]))

damaged = layout_text(FIXTURES["08_scene_gradient"])
check("辨識有掉字但仍讀得出東西時判定為勉強可用（不是 ok，也不是全丟）",
      damaged["verdict"] == "weak" and damaged["text"],
      f"{damaged['verdict']} kept_ratio={damaged['kept_ratio']:.2f}")

good = layout_text(FIXTURES["21_wrapped_para"])
check("乾淨畫面判定為可用", good["verdict"] == "ok",
      f"{good['verdict']} {good['mean_conf']:.1f}")

check("低於門檻的字塊會被丟掉並計數",
      layout_text([box("good", 10, 10, 60, 24, conf=95.0),
                   box("Nn", 90, 10, 20, 24, conf=10.0)])["dropped"] == 1)
check("完全沒有字塊時不會爆掉",
      layout_text([])["verdict"] == "unreadable")
check("字塊沒有 conf 欄位時當成 0，不會拋例外",
      layout_text([{"text": "x", "left": 0, "top": 0,
                    "width": 10, "height": 10}])["verdict"] == "unreadable")


print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("subtitle/ocrlayout.py 測試全數通過。")
