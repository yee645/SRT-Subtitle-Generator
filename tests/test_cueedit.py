# -*- coding: utf-8 -*-
"""
3.0 第 4 項第二、三階段：`subtitle/cueedit.py`——拖曳字幕塊的邊改時間的規則、
復原／重做、存回字幕檔。

零 GUI 依賴，任何環境都跑。時間軸（Qt）的拖曳測試在 test_qt_timeline.py。
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


CUES = [
    {"start": 1.0, "end": 3.0, "text": "一"},
    {"start": 4.0, "end": 6.0, "text": "二"},
    {"start": 7.5, "end": 9.0, "text": "三"},
]

# ----- 鄰居 -----
check("鄰居：第二句 → 上一句結束 3、下一句開始 7.5", cueedit.neighbours(CUES, 1) == (3.0, 7.5),
      str(cueedit.neighbours(CUES, 1)))
check("鄰居：第一句沒有上一句", cueedit.neighbours(CUES, 0) == (None, 4.0))
check("鄰居：最後一句沒有下一句", cueedit.neighbours(CUES, 2) == (6.0, None))
unsorted = [CUES[2], CUES[0], CUES[1]]
check("鄰居：清單沒排序也照開始時間找（第三句在清單第 0 個）",
      cueedit.neighbours(unsorted, 0) == (6.0, None) and cueedit.neighbours(unsorted, 2) == (3.0, 7.5),
      f"{cueedit.neighbours(unsorted, 0)} {cueedit.neighbours(unsorted, 2)}")
with_zero = CUES + [{"start": 3.5, "end": 3.5, "text": "零長度"}]
check("鄰居：零長度的句子不算（時間軸也不畫）", cueedit.neighbours(with_zero, 1) == (3.0, 7.5),
      str(cueedit.neighbours(with_zero, 1)))
same_start = [{"start": 2.0, "end": 3.0}, {"start": 2.0, "end": 4.0}]
check("鄰居：同一個開始時間，清單前面的算上一句",
      cueedit.neighbours(same_start, 1) == (3.0, None) and cueedit.neighbours(same_start, 0) == (None, 2.0),
      f"{cueedit.neighbours(same_start, 1)} {cueedit.neighbours(same_start, 0)}")

# ----- 拖左邊 -----
check("拖左邊：一般情況照拖（4 → 3.5）", cueedit.drag_edge(CUES, 1, "start", 3.5) == (3.5, 6.0))
check("拖左邊：不能拖進上一句（拖到 2 → 停在 3）", cueedit.drag_edge(CUES, 1, "start", 2.0) == (3.0, 6.0))
check("拖左邊：不能拖過右邊（拖到 10 → 停在結束前 0.1 秒）",
      cueedit.drag_edge(CUES, 1, "start", 10.0) == (5.9, 6.0),
      str(cueedit.drag_edge(CUES, 1, "start", 10.0)))
check("拖左邊：第一句不能拖到 0 秒以前", cueedit.drag_edge(CUES, 0, "start", -2) == (0.0, 3.0))
check("拖左邊：最短長度可以改（min_duration=0.5）",
      cueedit.drag_edge(CUES, 1, "start", 10.0, min_duration=0.5) == (5.5, 6.0))

# ----- 拖右邊 -----
check("拖右邊：一般情況照拖（6 → 6.8）", cueedit.drag_edge(CUES, 1, "end", 6.8) == (4.0, 6.8))
check("拖右邊：不能拖進下一句（拖到 9 → 停在 7.5）", cueedit.drag_edge(CUES, 1, "end", 9.0) == (4.0, 7.5))
check("拖右邊：不能拖過左邊（拖到 0 → 停在開始後 0.1 秒）",
      cueedit.drag_edge(CUES, 1, "end", 0.0) == (4.0, 4.1),
      str(cueedit.drag_edge(CUES, 1, "end", 0.0)))
check("拖右邊：最後一句不能拖過片尾", cueedit.drag_edge(CUES, 2, "end", 30, duration=10) == (7.5, 10.0))
check("拖右邊：不知道片長就不限", cueedit.drag_edge(CUES, 2, "end", 30) == (7.5, 30.0))
check("拖右邊：片尾與下一句取比較近的那個（片長 7 < 下一句 7.5）",
      cueedit.drag_edge(CUES, 1, "end", 9, duration=7) == (4.0, 7.0))

# ----- 原本就重疊／超出的，不硬拉開，也不能更糟 -----
overlap = [{"start": 1.0, "end": 5.0}, {"start": 4.0, "end": 8.0}]
check("原本重疊：左邊不能再往前拖（停在原本的 4）", cueedit.drag_edge(overlap, 1, "start", 2.0) == (4.0, 8.0))
check("原本重疊：往後拖照樣可以（4 → 5.5）", cueedit.drag_edge(overlap, 1, "start", 5.5) == (5.5, 8.0))
check("原本重疊：右邊不能再往後拖（停在原本的 5）", cueedit.drag_edge(overlap, 0, "end", 7.0) == (1.0, 5.0))
check("原本就超過片尾：保留，但不能再往外", cueedit.drag_edge(CUES, 2, "end", 12, duration=8.5) == (7.5, 9.0))

# ----- 吸附 -----
check("吸附：離播放頭 0.05 秒（容許 0.1）→ 貼上播放頭",
      cueedit.drag_edge(CUES, 1, "start", 4.55, snap_to=[4.6], snap_tolerance=0.1) == (4.6, 6.0))
check("吸附：超出容許就不吸",
      cueedit.drag_edge(CUES, 1, "start", 4.4, snap_to=[4.6], snap_tolerance=0.1) == (4.4, 6.0))
check("吸附：鄰句的邊一律是吸附點（右邊拖到 7.45 → 7.5）",
      cueedit.drag_edge(CUES, 1, "end", 7.45, snap_tolerance=0.1) == (4.0, 7.5))
check("吸附：取最近的那個（7.44 離 7.5 比離 7.3 近）",
      cueedit.drag_edge(CUES, 1, "end", 7.44, snap_to=[7.3], snap_tolerance=0.2) == (4.0, 7.5))
check("吸附後一樣要過界線（播放頭在上一句裡面 → 還是停在 3）",
      cueedit.drag_edge(CUES, 1, "start", 2.6, snap_to=[2.5], snap_tolerance=0.2) == (3.0, 6.0))
check("snap：沒有吸附點就是原值", cueedit.snap(1.23, [], 5) == 1.23)
check("snap：None 的吸附點略過", cueedit.snap(1.0, [None, 1.05], 0.1) == 1.05)

# ----- 毫秒 -----
got = cueedit.drag_edge(CUES, 1, "start", 3.123456)
check("結果取整毫秒（3.123456 → 3.123）", got == (3.123, 6.0), str(got))
float_cues = [{"start": 0.1 + 0.2, "end": 1.0}]
check("浮點誤差不讓合法的值被夾（0.30000000000000004 拖右邊到 0.4 → 0.4）",
      cueedit.drag_edge(float_cues, 0, "end", 0.4) == (0.3, 0.4),
      str(cueedit.drag_edge(float_cues, 0, "end", 0.4)))

try:
    cueedit.drag_edge(CUES, 0, "middle", 1)
    check("edge 打錯要報錯", False)
except ValueError:
    check("edge 打錯要報錯", True)

# ----- 抓到哪裡 -----
check("edge_at：左邊容許範圍內 → start", cueedit.edge_at(4, 6, 3.95, 0.1) == "start")
check("edge_at：右邊容許範圍內 → end", cueedit.edge_at(4, 6, 6.08, 0.1) == "end")
check("edge_at：中間 → body", cueedit.edge_at(4, 6, 5, 0.1) == "body")
check("edge_at：外面 → None", cueedit.edge_at(4, 6, 6.2, 0.1) is None)
check("edge_at：很窄的方塊兩邊各佔一半（0.1 秒寬、容許 0.2）",
      cueedit.edge_at(4, 4.1, 4.04, 0.2) == "start" and cueedit.edge_at(4, 4.1, 4.06, 0.2) == "end",
      f"{cueedit.edge_at(4, 4.1, 4.04, 0.2)} {cueedit.edge_at(4, 4.1, 4.06, 0.2)}")

# ----- 回寫 -----
new = cueedit.with_times(CUES, 1, 3.5, 6.5)
check("with_times：只改那一句的時間，其餘欄位保留",
      new[1] == {"start": 3.5, "end": 6.5, "text": "二"} and new[0] == CUES[0] and new[2] == CUES[2],
      str(new))
check("with_times：不改到傳進來的清單", CUES[1]["start"] == 4.0 and new[1] is not CUES[1])

# ===== 第四階段：整句移動 =====
check("整句移動：一般情況（4～6 → 4.5 開始 → 4.5～6.5，長度不變）",
      cueedit.move_cue(CUES, 1, 4.5) == (4.5, 6.5))
check("整句移動：不能移進上一句（移到 2 → 停在 3～5）", cueedit.move_cue(CUES, 1, 2) == (3.0, 5.0))
check("整句移動：不能移進下一句（移到 7 → 停在 5.5～7.5）", cueedit.move_cue(CUES, 1, 7) == (5.5, 7.5))
check("整句移動：第一句不能移到 0 秒以前", cueedit.move_cue(CUES, 0, -5) == (0.0, 2.0))
check("整句移動：最後一句不能移過片尾（片長 10 → 8.5～10）",
      cueedit.move_cue(CUES, 2, 20, duration=10) == (8.5, 10.0))
check("整句移動：不知道片長就不限", cueedit.move_cue(CUES, 2, 20) == (20.0, 21.5))
check("整句移動：兩句中間剛好塞得下（上一句結束 3、下一句開始 7.5，長 2 → 可以停在 3～5 或 5.5～7.5）",
      cueedit.move_cue(CUES, 1, 3) == (3.0, 5.0) and cueedit.move_cue(CUES, 1, 5.5) == (5.5, 7.5))
check("整句移動：開始靠近上一句的結尾 → 吸上去（3.05 → 3）",
      cueedit.move_cue(CUES, 1, 3.05, snap_tolerance=0.1) == (3.0, 5.0))
check("整句移動：結束靠近下一句的開始 → 吸上去（開始 5.45、結束 7.45 → 7.5）",
      cueedit.move_cue(CUES, 1, 5.45, snap_tolerance=0.1) == (5.5, 7.5))
check("整句移動：結束靠近播放頭 → 結束貼上播放頭（播放頭 6.8，結束 6.75）",
      cueedit.move_cue(CUES, 1, 4.75, snap_to=[6.8], snap_tolerance=0.1) == (4.8, 6.8))
check("整句移動：開始與結束都有吸附點時取最近的（開始離 4.6 差 0.02、結束離 6.7 差 0.05）",
      cueedit.move_cue(CUES, 1, 4.62, snap_to=[6.67, 4.6], snap_tolerance=0.1) == (4.6, 6.6))
check("整句移動：超出容許不吸", cueedit.move_cue(CUES, 1, 4.4, snap_to=[4.6], snap_tolerance=0.1) == (4.4, 6.4))
check("整句移動：吸附後一樣要過界線（播放頭在上一句裡）",
      cueedit.move_cue(CUES, 1, 2.6, snap_to=[2.5], snap_tolerance=0.2) == (3.0, 5.0))
overlap2 = [{"start": 1.0, "end": 5.0}, {"start": 4.0, "end": 8.0}, {"start": 7.0, "end": 9.0}]
check("整句移動：原本兩邊都重疊 → 哪邊都不能更重疊，原地不動",
      cueedit.move_cue(overlap2, 1, 3.0) == (4.0, 8.0) and cueedit.move_cue(overlap2, 1, 5.0) == (4.0, 8.0),
      f"{cueedit.move_cue(overlap2, 1, 3.0)} {cueedit.move_cue(overlap2, 1, 5.0)}")
got = cueedit.move_cue(CUES, 1, 4.1234567)
check("整句移動：取整毫秒、長度精確不變", got == (4.123, 6.123), str(got))
check("整句移動：原本就超過片尾的句子 → 可以往前、不能再往後（片長 8.5，第三句 7.5～9）",
      cueedit.move_cue(CUES, 2, 8, duration=8.5) == (7.5, 9.0)
      and cueedit.move_cue(CUES, 2, 7, duration=8.5) == (7.0, 8.5),
      f"{cueedit.move_cue(CUES, 2, 8, duration=8.5)} {cueedit.move_cue(CUES, 2, 7, duration=8.5)}")
long_cue = [{"start": 0.0, "end": 12.0}]
check("整句移動：比片長還長的句子（原本就超過）→ 不動也不壞", cueedit.move_cue(long_cue, 0, 3, duration=10) == (0.0, 12.0),
      str(cueedit.move_cue(long_cue, 0, 3, duration=10)))

# ===== 第三階段：復原／重做、改過幾處、存檔 =====
import shutil  # noqa: E402
import tempfile  # noqa: E402

from subtitle.importer import load_subtitle_file  # noqa: E402

h = cueedit.EditHistory()
check("新的紀錄：不能復原也不能重做", not h.can_undo() and not h.can_redo() and h.undo(CUES) is None
      and h.redo(CUES) is None)
cur = cueedit.with_times(CUES, 1, 4.0, 6.8)
h.record(1, (4.0, 6.0), (4.0, 6.8))
cur2 = cueedit.with_times(cur, 0, 0.5, 3.0)
h.record(0, (1.0, 3.0), (0.5, 3.0))
back, idx = h.undo(cur2)
check("復原：最後一筆先退（第 0 句回到 1～3）", idx == 0 and back[0]["start"] == 1.0 and back[1]["end"] == 6.8,
      f"{idx} {back[:2]}")
back2, idx2 = h.undo(back)
check("再復原：第 1 句回到 4～6，整份回到原樣", idx2 == 1 and cueedit.changed_count(back2, CUES) == 0,
      str(back2))
check("復原到底：不能再復原、可以重做", not h.can_undo() and h.can_redo())
fwd, idx3 = h.redo(back2)
check("重做：照原順序重來（先第 1 句）", idx3 == 1 and fwd[1]["end"] == 6.8 and fwd[0]["start"] == 1.0, str(fwd[:2]))
check("復原／重做不改到傳進去的清單", back2[1]["end"] == 6.0 and CUES[1]["end"] == 6.0)
h.record(2, (7.5, 9.0), (7.5, 8.0))
check("做了新的修改 → 重做那一疊清掉", not h.can_redo() and h.redo(fwd) is None)
before_len = len(h._done)
h.record(2, (7.5, 8.0), (7.5, 8.0))
check("沒變的修改不記（按住邊沒動）", len(h._done) == before_len, f"{before_len} → {len(h._done)}")
small = cueedit.EditHistory(limit=3)
for k in range(5):
    small.record(0, (k, 10), (k + 1, 10))
steps = 0
while small.undo(CUES) is not None:
    steps += 1
check("紀錄有上限（limit=3 → 最多復原 3 步）", steps == 3, str(steps))

check("changed_count：一樣 → 0", cueedit.changed_count(CUES, [dict(c) for c in CUES]) == 0)
check("changed_count：改了兩句 → 2", cueedit.changed_count(cur2, CUES) == 2)
check("changed_count：浮點誤差不算改過（0.1+0.2 vs 0.3）",
      cueedit.changed_count([{"start": 0.1 + 0.2, "end": 1}], [{"start": 0.3, "end": 1}]) == 0)
check("changed_count：句數不同，多出來的算改過", cueedit.changed_count(CUES[:2], CUES) == 1)

tmp = tempfile.mkdtemp()
try:
    # 真的會遇到的原檔：Big5（cp950）編碼、帶斜體標記——載入時標記被拿掉、存回
    # 時改成 UTF-8，所以第一次覆蓋前一定要留原檔。
    original = ("1\r\n00:00:01,000 --> 00:00:03,000\r\n<i>第一句</i>\r\n\r\n"
                "2\r\n00:00:04,000 --> 00:00:06,000\r\n第二句\r\n").encode("cp950")
    srt = os.path.join(tmp, "片子.srt")
    with open(srt, "wb") as fp:
        fp.write(original)
    loaded = load_subtitle_file(srt)
    check("測資：原檔是 cp950、載入時拿掉斜體", loaded["encoding"] == "cp950"
          and loaded["cues"][0]["text"] == "第一句", str(loaded))
    edited = cueedit.with_times(loaded["cues"], 1, 4.25, 6.5)
    result = cueedit.save_cues(edited, srt)
    check("存檔：回傳存到哪、這次做了備份", result == {"path": srt, "backup": srt + ".bak"}, str(result))
    with open(srt + ".bak", "rb") as fp:
        check("備份檔跟原檔一個位元組都不差（cp950、斜體都在）", fp.read() == original)
    again = load_subtitle_file(srt)
    check("存完再讀回來：時間是改過的、文字一樣、句數一樣",
          [(c["start"], c["end"], c["text"]) for c in again["cues"]]
          == [(1.0, 3.0, "第一句"), (4.25, 6.5, "第二句")], str(again["cues"]))
    check("存成 UTF-8", again["encoding"] in ("utf-8", "utf-8-sig"), again["encoding"])
    result2 = cueedit.save_cues(cueedit.with_times(edited, 0, 1.5, 3.0), srt)
    with open(srt + ".bak", "rb") as fp:
        kept = fp.read()
    check("第二次存：不再做備份，.bak 保住的還是最早的原檔", result2["backup"] is None and kept == original)
    check("資料夾裡沒有留下暫存檔", sorted(os.listdir(tmp)) == ["片子.srt", "片子.srt.bak"], str(os.listdir(tmp)))

    vtt = os.path.join(tmp, "b.vtt")
    cueedit.save_cues(CUES, vtt)
    check("存成 .vtt：照副檔名、讀得回來、新檔不做備份",
          [(c["start"], c["end"]) for c in load_subtitle_file(vtt)["cues"]] == [(1.0, 3.0), (4.0, 6.0), (7.5, 9.0)]
          and not os.path.exists(vtt + ".bak"))
    for bad, why in ((os.path.join(tmp, "c.ass"), "副檔名不是 .srt／.vtt"), (os.path.join(tmp, "d"), "沒有副檔名")):
        try:
            cueedit.save_cues(CUES, bad)
            check(f"存檔：{why} → 報錯", False)
        except ValueError:
            check(f"存檔：{why} → 報錯、沒寫出檔案", not os.path.exists(bad))
    try:
        cueedit.save_cues([], os.path.join(tmp, "e.srt"))
        check("存檔：沒有字幕 → 報錯", False)
    except ValueError:
        check("存檔：沒有字幕 → 報錯", not os.path.exists(os.path.join(tmp, "e.srt")))

    # 寫到一半失敗（換名那一步出錯）：原檔原封不動、暫存檔清掉
    with open(srt, "rb") as fp:
        before_fail = fp.read()
    real_replace = cueedit.os.replace

    def broken_replace(_src, _dst):
        raise OSError("磁碟滿了（測試）")
    cueedit.os.replace = broken_replace
    try:
        cueedit.save_cues(CUES, srt)
        check("換名失敗 → 報錯", False)
    except OSError:
        with open(srt, "rb") as fp:
            check("換名失敗 → 原檔原封不動、暫存檔清掉",
                  fp.read() == before_fail and sorted(os.listdir(tmp)) == ["b.vtt", "片子.srt", "片子.srt.bak"],
                  str(os.listdir(tmp)))
    finally:
        cueedit.os.replace = real_replace
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"{len(failures)} 項失敗")
    sys.exit(1)
print("cueedit（拖曳改時間的規則、復原重做、存檔）測試全數通過。")
