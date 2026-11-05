# -*- coding: utf-8 -*-
"""
3.0 第 11 項第二階段：逐句校對的新增、刪除、尋找取代的核心（subtitle/cueedit.py 的 place_new_cue／
with_cue_inserted／without_cue／replace_text／diff_counts，EditHistory 的 record_insert／record_delete／
record_cues）。

1. place_new_cue：放在播放頭；落在某句裡面就接到那句後面（連續重疊的一路接下去）；最長 2 秒、不蓋到
   下一句、不超過片長；剩不到 0.1 秒就不放；插在第幾個照開始時間；空清單從播放頭開始。
2. 插入／刪除：回傳新清單、原本的不動；插入時文字整理過、空的不收；超出範圍 IndexError。
3. 取代：字面比對（. 不是萬用字元）、可選區分大小寫、可只改某幾句；取代完再整理；會變空的不改並回報；
   次數只算真的改到的句子；逐字時間軸跟著（textedit 的規則）。
4. 復原／重做：新增、刪除、全部取代各是一步，跟改文字、改時間同一疊；復原新增後要選的那句夾在範圍內。
5. diff_counts：先對齊沒變的句子——插一句只算「新增 1」，刪一句只算「刪除 1」，其他改動照數。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import cueedit  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def error_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except (ValueError, IndexError) as exc:
        return type(exc).__name__ + ":" + str(exc)
    return None


cues = [{"start": 1.0, "end": 2.0, "text": "第一句"},
        {"start": 3.0, "end": 4.0, "text": "第二句"},
        {"start": 4.0, "end": 6.5, "text": "第三句"},
        {"start": 9.0, "end": 10.0, "text": "Hello hello"}]
original = [dict(c) for c in cues]

# ----- 1. place_new_cue -----
check("空檔裡：從播放頭開始、長 2 秒、插在前面那句後面",
      cueedit.place_new_cue(cues, 6.8) == (3, 6.8, 8.8), str(cueedit.place_new_cue(cues, 6.8)))
check("不蓋到下一句：8.0 秒開始的只到 9.0", cueedit.place_new_cue(cues, 8.0) == (3, 8.0, 9.0))
check("落在某句裡面：接到那句結束；連著的（4.0 那句接著 3.0 那句）一路接下去",
      cueedit.place_new_cue(cues, 3.5) == (3, 6.5, 8.5), str(cueedit.place_new_cue(cues, 3.5)))
check("最前面：插在第 0 個", cueedit.place_new_cue(cues, 0.0) == (0, 0.0, 1.0))
check("剛好在某句開始的那一刻：算在那句裡面，接到後面", cueedit.place_new_cue(cues, 1.0) == (1, 2.0, 3.0))
check("不超過片長", cueedit.place_new_cue(cues, 10.5, duration=11.0) == (4, 10.5, 11.0))
check("空位不到 0.1 秒：不放",
      "ValueError" in (error_of(cueedit.place_new_cue, cues, 8.95) or "")
      and "ValueError" in (error_of(cueedit.place_new_cue, cues, 10.95, duration=11.0) or "")
      and "ValueError" in (error_of(cueedit.place_new_cue, cues, 12.0, duration=11.0) or ""))
check("剛好 0.1 秒：放得下", cueedit.place_new_cue(cues, 8.9) == (3, 8.9, 9.0))
check("負的播放頭當 0、空清單從播放頭開始", cueedit.place_new_cue([], -1) == (0, 0.0, 2.0)
      and cueedit.place_new_cue([], 5.25) == (0, 5.25, 7.25))
messy = [{"start": 4.0, "end": 6.5, "text": "後"}, {"start": 3.0, "end": 4.0, "text": "前"}]
check("清單沒照時間排（舊專案檔）：連著的照樣一路接下去", cueedit.place_new_cue(messy, 3.5) == (2, 6.5, 8.5),
      str(cueedit.place_new_cue(messy, 3.5)))
check("指定長度", cueedit.place_new_cue(cues, 6.8, length=0.5) == (3, 6.8, 7.3))

# ----- 2. 插入／刪除 -----
added = cueedit.with_cue_inserted(cues, 3, {"start": 6.8, "end": 8.8, "text": "  新的 \n\n 一句 "})
check("插入：在指定位置、文字整理過、時間是 float", len(added) == 5
      and added[3] == {"start": 6.8, "end": 8.8, "text": "新的\n一句"} and added[4] == cues[3], str(added[3]))
check("插入：原本的清單不動", cues == original)
check("插入在最後面（index == 長度）可以", cueedit.with_cue_inserted(cues, 4, {"start": 11, "end": 12,
                                                                    "text": "尾"})[-1]["text"] == "尾")
check("插入空的：不收", "ValueError" in (error_of(cueedit.with_cue_inserted, cues, 0,
                                                    {"start": 0, "end": 1, "text": " \n"}) or ""))
check("插入超出範圍：IndexError", "IndexError" in (error_of(cueedit.with_cue_inserted, cues, 5,
                                                            {"start": 0, "end": 1, "text": "x"}) or "")
      and "IndexError" in (error_of(cueedit.with_cue_inserted, cues, -1, {"start": 0, "end": 1, "text": "x"}) or ""))
removed = cueedit.without_cue(cues, 1)
check("刪除：拿掉那一句、其他照舊、原本的不動", [c["text"] for c in removed] == ["第一句", "第三句", "Hello hello"]
      and cues == original)
check("刪除超出範圍：IndexError", "IndexError" in (error_of(cueedit.without_cue, cues, 4) or "")
      and "IndexError" in (error_of(cueedit.without_cue, cues, -1) or ""))
check("刪掉最後一句：空清單", cueedit.without_cue([cues[0]], 0) == [])

# ----- 3. 取代 -----
out, count, changed, emptied = cueedit.replace_text(cues, "hello", "Hi")
check("不分大小寫：Hello 與 hello 都換；算 2 處、1 句", out[3]["text"] == "Hi Hi" and count == 2
      and changed == [3] and emptied == [], f"{out[3]} {count} {changed}")
check("取代：原本的清單不動", cues == original)
out, count, changed, _e = cueedit.replace_text(cues, "hello", "Hi", case_sensitive=True)
check("區分大小寫：只換小寫的", out[3]["text"] == "Hello Hi" and count == 1, out[3]["text"])
out, count, changed, _e = cueedit.replace_text(cues, "句", "段", only=[0, 2])
check("只改指定的幾句", [c["text"] for c in out] == ["第一段", "第二句", "第三段", "Hello hello"]
      and count == 2 and changed == [0, 2], str(changed))
out, count, changed, _e = cueedit.replace_text(cues, ".", "!")
check("字面比對：「.」不是萬用字元", count == 0 and changed == [] and out == cues)
out, count, changed, emptied = cueedit.replace_text(cues, "第一句", "")
check("會變成空的：不改、回報出來", out[0]["text"] == "第一句" and changed == [] and emptied == [0] and count == 0)
out, count, changed, emptied = cueedit.replace_text(cues, "Hello", "")
check("拿掉一個字（不分大小寫兩個都拿掉）會變空：不改", emptied == [3] and out[3]["text"] == "Hello hello")
out, count, changed, emptied = cueedit.replace_text(cues, "Hello", "", case_sensitive=True)
check("拿掉開頭那個字：剩下的去掉頭尾空白", out[3]["text"] == "hello" and changed == [3] and count == 1,
      repr(out[3]["text"]))
out, count, changed, _e = cueedit.replace_text(cues, "第一句", "第一句")
check("換成一樣的：不算改", changed == [] and count == 0)
out, count, changed, _e = cueedit.replace_text(cues, "第一句", "第一句 ")
check("取代後整理回一模一樣（多打的空白）：不算改、不算次數", changed == [] and count == 0 and out == cues,
      f"{changed} {count}")
check("空的搜尋字：什麼都不做", cueedit.replace_text(cues, "", "x")[1:] == (0, [], []))
worded = [{"start": 0, "end": 1, "text": "厲害", "words": [{"start": 0, "end": 0.5, "word": "厲"},
                                                          {"start": 0.5, "end": 1, "word": "害"}]}]
out, _c, _ch, _e = cueedit.replace_text(worded, "厲害", "很強")
check("逐字時間軸對不上就拿掉（照 textedit 的規則，動態字幕不會出現舊字）",
      out[0]["text"] == "很強" and "words" not in out[0], str(out[0]))
multi = [{"start": 0, "end": 1, "text": "嗯 你好\n嗯"}]
out, count, changed, emptied = cueedit.replace_text(multi, "嗯", "")
check("雙行：拿掉後空的那行也拿掉", out[0]["text"] == "你好" and count == 2 and emptied == [], repr(out[0]["text"]))

# ----- 4. 復原／重做 -----
h = cueedit.EditHistory()
now = [dict(c) for c in cues]
position, start, end = cueedit.place_new_cue(now, 6.8)
now = cueedit.with_cue_inserted(now, position, {"start": start, "end": end, "text": "新的"})
h.record_insert(position, now[position])
h.record_delete(1, now[1])
now = cueedit.without_cue(now, 1)
now2, count, changed, _e = cueedit.replace_text(now, "句", "段")
h.record_cues(changed, [now[i] for i in changed], [now2[i] for i in changed])
now = now2
h.record_text(0, now[0]["text"], "改字")
now = cueedit.with_text(now, 0, "改字")
check("做完四步：新增、刪除、全部取代、改字", [c["text"] for c in now] == ["改字", "第三段", "新的", "Hello hello"],
      str([c["text"] for c in now]))
s1, i1 = h.undo(now)
s2, i2 = h.undo(s1)
s3, i3 = h.undo(s2)
s4, i4 = h.undo(s3)
check("復原改字", [c["text"] for c in s1] == ["第一段", "第三段", "新的", "Hello hello"] and i1 == 0)
check("全部取代一步就退完，選第一句", [c["text"] for c in s2] == ["第一句", "第三句", "新的", "Hello hello"]
      and i2 == 0, str([c["text"] for c in s2]))
check("復原刪除：那句回到原位、時間照舊", s3[1] == cues[1] and len(s3) == 5 and i3 == 1)
check("復原新增：回到一開始的樣子", s4 == cues and i4 == 3, str(s4))
check("全部退完：不能再退", not h.can_undo())
r1, j1 = h.redo(s4)
r2, j2 = h.redo(r1)
r3, j3 = h.redo(r2)
check("重做新增、刪除、取代：跟做的時候一樣", r1[3]["text"] == "新的" and j1 == 3
      and [c["text"] for c in r2] == ["第一句", "第三句", "新的", "Hello hello"] and j2 == 1
      and [c["text"] for c in r3] == ["第一段", "第三段", "新的", "Hello hello"] and j3 == 0)
h.record_cues([], [], [])
check("取代沒改到任何句子：不記", h.can_redo())
check("記下來的是複本：之後改清單不影響紀錄", h._undone[-1][2] is not r3[0])

# ----- 5. diff_counts -----
zero = {"times": 0, "texts": 0, "added": 0, "removed": 0}
check("沒改：全是 0", cueedit.diff_counts(cues, original) == zero)
ins = cueedit.with_cue_inserted(cues, 1, {"start": 2.2, "end": 2.8, "text": "插的"})
check("中間插一句：只算新增 1（後面的不算改過）", cueedit.diff_counts(ins, original) == dict(zero, added=1),
      str(cueedit.diff_counts(ins, original)))
check("刪一句：只算刪除 1", cueedit.diff_counts(removed, original) == dict(zero, removed=1))
mixed = cueedit.with_text(cueedit.with_times(ins, 3, 4.1, 6.5), 0, "改字")
check("插一句、改另一句時間、改一句文字：各算各的", cueedit.diff_counts(mixed, original)
      == {"times": 1, "texts": 1, "added": 1, "removed": 0}, str(cueedit.diff_counts(mixed, original)))
both = cueedit.with_text(cueedit.with_times(cues, 1, 3.1, 4.0), 1, "又改時間又改字")
check("同一句改時間又改字：時間 1、文字 1", cueedit.diff_counts(both, original) == dict(zero, times=1, texts=1))
check("全部刪光：刪除 4", cueedit.diff_counts([], original) == dict(zero, removed=4))
check("存檔前是空的、新增了兩句：新增 2", cueedit.diff_counts(cues[:2], []) == dict(zero, added=2))
check("時間只差不到 1 毫秒：不算改", cueedit.diff_counts([dict(cues[0], start=1.0001)] + cues[1:], original) == zero)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 逐句校對新增、刪除、尋找取代的核心測試全數通過。")
