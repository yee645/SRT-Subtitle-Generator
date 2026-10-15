# -*- coding: utf-8 -*-
"""
3.0 第 11 項第一階段：逐句改文字的核心（subtitle/cueedit.py 的 clean_text／with_text／
text_changed_count，EditHistory.record_text）。

1. 整理：換行統一、每行去頭尾空白、拿掉空行，中間的換行（雙行字幕）保留。
2. with_text：回傳新清單、原本的不動；只換那一句的文字，時間與其他欄位照舊；空的不收；超出範圍拋
   IndexError。
3. text_changed_count：只數文字不一樣的句子（時間不一樣的由 changed_count 數）。
4. 復原／重做：改時間與改文字在同一疊，照做的順序一步一步退；做了新的修改重做的那一疊清掉；
   沒變的修改不記；復原回原本的文字原封不動（不再整理一次）。
5. 改了文字存檔再讀回來：文字是新的。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import cueedit  # noqa: E402
from subtitle.importer import load_subtitle_file  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def error_of(fn, *args):
    try:
        fn(*args)
    except (ValueError, IndexError) as exc:
        return type(exc).__name__ + ":" + str(exc)
    return None


# ----- 1. 整理 -----
check("換行統一、每行去頭尾空白、拿掉空行，中間的換行保留",
      cueedit.clean_text("  第一行 \r\n\r\n 第二行\r第三行  \n  ") == "第一行\n第二行\n第三行",
      repr(cueedit.clean_text("  第一行 \r\n\r\n 第二行\r第三行  \n  ")))
check("只有空白與換行：整理完是空的", cueedit.clean_text(" \n \t\n") == "")
check("行內的空白不動（英文字中間的空格）", cueedit.clean_text(" Hello  world ") == "Hello  world")

# ----- 2. with_text -----
cues = [{"start": 0.5, "end": 2.0, "text": "第一句"},
        {"start": 3.0, "end": 5.5, "text": "第二句", "emphasis": ["第二"]}]
out = cueedit.with_text(cues, 1, " 改過的\n第二句 ")
check("只換那一句的文字；時間與其他欄位照舊", out[1] == {"start": 3.0, "end": 5.5, "text": "改過的\n第二句",
                                                     "emphasis": ["第二"]} and out[0] == cues[0], str(out))
check("原本的清單不動", cues[1]["text"] == "第二句" and out is not cues and out[1] is not cues[1])
check("改成空的：不收", "ValueError" in (error_of(cueedit.with_text, cues, 0, " \n ") or ""))
check("超出範圍：IndexError", "IndexError" in (error_of(cueedit.with_text, cues, 2, "x") or "")
      and "IndexError" in (error_of(cueedit.with_text, cues, -1, "x") or ""))

# ----- 3. text_changed_count -----
saved = [dict(c) for c in cues]
check("沒改：0", cueedit.text_changed_count(cues, saved) == 0)
check("改了一句的文字：1；時間的數字不受影響", cueedit.text_changed_count(out, saved) == 1
      and cueedit.changed_count(out, saved) == 0)
moved = cueedit.with_times(out, 0, 0.6, 2.0)
check("另一句改時間：文字仍是 1、時間 1", cueedit.text_changed_count(moved, saved) == 1
      and cueedit.changed_count(moved, saved) == 1)
check("多出一句：文字不算（由 changed_count 算）", cueedit.text_changed_count(saved + [{"start": 6, "end": 7,
                                                                                    "text": "新"}], saved) == 0)

# ----- 4. 復原／重做 -----
h = cueedit.EditHistory()
now = [dict(c) for c in cues]
h.record_text(0, now[0]["text"], "第一句改")
now = cueedit.with_text(now, 0, "第一句改")
h.record(1, (3.0, 5.5), (3.2, 5.5))
now = cueedit.with_times(now, 1, 3.2, 5.5)
h.record_text(1, now[1]["text"], "第二句改")
now = cueedit.with_text(now, 1, "第二句改")
step1, i1 = h.undo(now)
step2, i2 = h.undo(step1)
step3, i3 = h.undo(step2)
check("改文字、改時間、改文字：照做的順序一步一步退", (i1, i2, i3) == (1, 1, 0)
      and step1[1]["text"] == "第二句" and step1[1]["start"] == 3.2
      and step2[1]["start"] == 3.0 and step2[1]["text"] == "第二句"
      and step3[0]["text"] == "第一句" and step3 == cues, f"{step1}\n{step2}\n{step3}")
check("全部退完：不能再退", not h.can_undo() and h.undo(step3) is None)
again, j = h.redo(step3)
check("重做：文字回來", j == 0 and again[0]["text"] == "第一句改" and h.can_redo())
h.record_text(0, "第一句改", "又改")
check("做了新的修改：重做的那一疊清掉", not h.can_redo())
before = len(h._done)
h.record_text(0, "一樣", "一樣")
check("沒變的修改不記", len(h._done) == before)
odd = [{"start": 0, "end": 1, "text": "原本\n\n有空行"}]
h2 = cueedit.EditHistory()
h2.record_text(0, odd[0]["text"], "新的")
back, _k = h2.undo(cueedit.with_text(odd, 0, "新的"))
check("復原回原本的文字原封不動（不再整理一次）", back[0]["text"] == "原本\n\n有空行", repr(back[0]["text"]))

# ----- 5. 存檔再讀回來 -----
tmp = tempfile.mkdtemp()
path = os.path.join(tmp, "改過.srt")
cueedit.save_cues(cueedit.with_text(cues, 1, "改過的\n第二句"), path)
loaded = load_subtitle_file(path)["cues"]
check("存檔再讀回來：雙行文字照新的", [c["text"] for c in loaded] == ["第一句", "改過的\n第二句"],
      str([c["text"] for c in loaded]))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 逐句改文字的核心測試全數通過。")
