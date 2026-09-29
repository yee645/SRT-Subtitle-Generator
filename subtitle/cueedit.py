# -*- coding: utf-8 -*-
"""
拖曳字幕塊的邊改時間（3.0 第 4 項第二階段）：規則全部在這裡，零 GUI 依賴。

時間軸只負責把滑鼠位置換成秒數、把結果畫出來；「可以拖到哪裡」由這裡決定，
日後任何介面（或鍵盤微調）共用同一套規則：

* 以毫秒為單位計算（SRT 的精度），回傳的秒數都是整毫秒。
* 一句至少 `MIN_DURATION` 秒——左邊不能拖過右邊，反之亦然。
* 不能拖進相鄰那句：左邊最多拖到上一句的結束、右邊最多拖到下一句的開始。
  原本就重疊的字幕不會被硬拉開，但也不能再拖得更重疊（界線取「原本的位置」
  與「鄰句邊界」較寬的那個）。
* 不能拖到 0 秒以前；知道片長時，右邊不能拖過片尾（原本就超過的同理保留）。
* 吸附：離吸附點（播放頭、鄰句的邊）夠近就貼上去——吸附後的值一樣要過上面
  的界線。
"""

MIN_DURATION = 0.1

START = "start"
END = "end"
BODY = "body"


def _ms(seconds):
    return int(round(float(seconds) * 1000))


def neighbours(cues, index):
    """
    第 index 句的鄰居邊界：(上一句的結束, 下一句的開始)，沒有就是 None。
    「上一句／下一句」依開始時間排序決定（清單本身不一定排好序）；零長度或
    時間倒過來的句子不算（時間軸也不畫它們）。
    """
    me = cues[index]
    my_start = _ms(me["start"])
    prev_end = next_start = None
    for i, cue in enumerate(cues):
        if i == index:
            continue
        start, end = _ms(cue["start"]), _ms(cue["end"])
        if end <= start:
            continue
        # 同一個開始時間的，清單裡排前面的算「上一句」（與 CueIndex 的穩定排序一致）
        before = start < my_start or (start == my_start and i < index)
        if before:
            prev_end = end if prev_end is None else max(prev_end, end)
        else:
            next_start = start if next_start is None else min(next_start, start)
    return (None if prev_end is None else prev_end / 1000.0,
            None if next_start is None else next_start / 1000.0)


def snap(seconds, targets, tolerance):
    """離 seconds 最近、而且在 tolerance 秒以內的吸附點；沒有就原值。"""
    best = None
    for target in targets or ():
        if target is None:
            continue
        gap = abs(float(target) - float(seconds))
        if gap <= tolerance and (best is None or gap < best[0]):
            best = (gap, float(target))
    return seconds if best is None else best[1]


def drag_edge(cues, index, edge, seconds, duration=None, snap_to=(), snap_tolerance=0.0,
              min_duration=MIN_DURATION):
    """
    把第 index 句的 edge（"start"／"end"）拖到 seconds，回傳合法的 (開始, 結束) 秒數。
    snap_to：額外的吸附點（例如播放頭）；鄰句的邊一律是吸附點。
    """
    if edge not in (START, END):
        raise ValueError(f"edge 只能是 {START!r} 或 {END!r}：{edge!r}")
    cue = cues[index]
    start, end = _ms(cue["start"]), _ms(cue["end"])
    min_ms = _ms(min_duration)
    prev_end, next_start = neighbours(cues, index)
    targets = list(snap_to or ()) + [prev_end, next_start]
    t = _ms(snap(seconds, targets, snap_tolerance))
    if edge == START:
        low = 0
        if prev_end is not None:
            low = max(low, min(_ms(prev_end), start))
        high = max(end - min_ms, low)
        start = min(max(t, low), high)
    else:
        high = None
        if next_start is not None:
            high = max(_ms(next_start), end)
        if duration:
            limit = max(_ms(duration), end)
            high = limit if high is None else min(high, limit)
        low = start + min_ms
        end = max(t, low) if high is None else min(max(t, low), max(high, low))
    return start / 1000.0, end / 1000.0


def edge_at(start, end, seconds, tolerance):
    """
    seconds 落在這一句的哪裡："start"／"end"（邊的 tolerance 秒以內）、"body"、
    或 None（不在這句上）。方塊太窄時兩個邊的範圍各佔一半，不會永遠只抓得到一邊。
    """
    start, end, seconds = float(start), float(end), float(seconds)
    if not start - tolerance <= seconds <= end + tolerance:
        return None
    reach = min(tolerance, (end - start) / 2)
    if seconds <= start + reach:
        return START
    if seconds >= end - reach:
        return END
    return BODY



def with_times(cues, index, start, end):
    """回傳改過第 index 句時間的新清單（其餘句子與欄位原封不動，不改到傳進來的清單）。"""
    out = [dict(c) for c in cues]
    out[index]["start"] = float(start)
    out[index]["end"] = float(end)
    return out
