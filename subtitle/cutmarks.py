# -*- coding: utf-8 -*-
"""
剪點可視化（3.0 第 5 項第一階段）：把三種自動剪輯「會剪掉哪幾段」算成時間區間，
讓時間軸畫出來——剪之前先看得到，不再盲剪。零 GUI 依賴。

三個來源都照**真正剪片時用的同一份程式**算，畫出來的就是按下去會剪的：

* `jumpcut`（停頓跳剪）：`jumpcut.find_cut_gaps` → `compute_keep_segments`。
* `retakes`（重複片段）：`retakes.find_retakes` 的全部候選 →
  `retakes.retake_keep_segments`（一般版對話框預設全勾）。
* `review`（審片建議）：`review.analyze` → `review.kept_ranges`（建議捨棄的冷
  場、重複拍攝；設定裡開了「一併剪掉口頭禪」就連口頭禪一起）。

每個來源先得到「要保留的片段」，剪點＝保留片段以外的部分（`cut_spans`）；每一段
剪點附上原因（哪一段停頓、跟哪一句重複…），滑鼠停上去看得到。

審片原本要 Whisper 的逐字時間軸；時間軸上已經有字幕，就用字幕的逐字資料（每句
都有才用），沒有時把每一句當成一個「字」——冷場與重複拍攝只看段落的起訖與文字，
結果不受影響；口頭禪只有在字幕帶逐字資料時才分得出是哪個字。

第一階段只負責「看得到」。第二階段加上**使用者的微調**，規則一樣放在這裡：

* 每段剪點有 `key`（來源＋算出來時的起訖）與 `enabled`。使用者停用某一段、或拖了它
  的邊，記成 `overrides[key]`；字幕改了、剪點重算時，`apply_overrides` 把還對得上
  key 的微調套回去——停頓本身沒變的剪點，微調不會因為改了別句字幕就不見。剪點本身
  變了（key 對不上）的微調就放掉：原本那段已經不存在了。
* `drag_mark_edge`：拖剪點的左右邊。不能拖過相鄰的剪點、不出片頭片尾、至少
  `MIN_CUT` 秒；以毫秒為單位（同 `cueedit`）。
* `recount`／`summary`：只算啟用中的剪點；停用幾處、調過幾處另外寫出來。
* `kept_segments`：啟用中的剪點以外＝要保留的片段（下一階段照時間軸輸出用）。
"""

from . import jumpcut, retakes, review

JUMPCUT = "jumpcut"
RETAKES = "retakes"
REVIEW = "review"
SOURCES = (JUMPCUT, RETAKES, REVIEW)
SOURCE_LABELS = {
    JUMPCUT: "停頓跳剪",
    RETAKES: "重複片段",
    REVIEW: "審片建議",
}

_EPS = 0.001  # 小於 1 毫秒的剪點不算（浮點誤差）
MIN_CUT = 0.05  # 拖剪點的邊時，一段剪點至少多長（秒）


def cut_spans(keep, duration):
    """
    保留片段以外的部分：[(開始, 結束), …]，依時間排序、已合併。
    keep 是剪片函式用的 (開始, 結束) 清單；duration 是片長（0＝以最後一段保留片段為準）。
    """
    spans = []
    cursor = 0.0
    for start, end in sorted((float(s), float(e)) for s, e in keep):
        if start - cursor > _EPS:
            spans.append((cursor, start))
        cursor = max(cursor, end)
    if duration and float(duration) - cursor > _EPS:
        spans.append((cursor, float(duration)))
    return spans


# 剪點沒有蓋到任何具名原因時的說明（審片：段落前後、保留片段緩衝以外的留白）
_FALLBACK_REASON = "段落之間沒講話的空檔"


def _marks(source, spans, reasons):
    """把剪點區間配上原因：reasons 是 [(開始, 結束, 說明)]，跟剪點有重疊的都列進去。"""
    marks = []
    for start, end in spans:
        why = [text for r_start, r_end, text in reasons
               if r_start < end - _EPS and r_end > start + _EPS] or [_FALLBACK_REASON]
        start, end = round(start, 3), round(end, 3)
        marks.append({"source": source, "start": start, "end": end,
                      "reasons": list(dict.fromkeys(why)),
                      "key": f"{source}:{start:.3f}-{end:.3f}", "enabled": True})
    return marks


def _result(source, marks, note=""):
    return {
        "source": source,
        "marks": marks,
        "removed_seconds": round(sum(m["end"] - m["start"] for m in marks), 3),
        "note": note,
    }


def _playable(cues):
    return [c for c in cues or () if float(c.get("end", 0)) > float(c.get("start", 0))]


def jumpcut_marks(cues, duration, config=None):
    settings = jumpcut.resolve_jumpcut_settings(config)
    cues = _playable(cues)
    gaps = jumpcut.find_cut_gaps(cues, settings["min_gap"])
    if not duration:
        duration = max((float(c["end"]) for c in cues), default=0.0)
    keep, _count = jumpcut.compute_keep_segments(duration, gaps, settings["pad"])
    spans = cut_spans(keep, duration) if gaps else []
    reasons = [(s, e, f"句間停頓 {e - s:.1f} 秒") for s, e in gaps]
    result = _result(JUMPCUT, _marks(JUMPCUT, spans, reasons))
    if not gaps:
        result["note"] = f"沒有超過 {settings['min_gap']:g} 秒的停頓"
    elif not spans:
        result["note"] = "停頓扣掉兩側緩衝後都不夠剪"
    elif duration and result["removed_seconds"] / duration > settings["max_cut_ratio"]:
        # 照剪片時的規則：剪太多多半是誤判，一般版會拒絕剪
        result["note"] = (f"停頓總長超過片長的 {settings['max_cut_ratio'] * 100:.0f}%，"
                          "一般版會當成誤判而不剪——請調高「最短停頓秒數」")
    return result


def retake_marks(cues, duration, config=None):
    settings = retakes.resolve_retake_settings(config)
    found = retakes.find_retakes(list(cues or ()), settings)
    if not found:
        return _result(RETAKES, [], "沒有找到疑似重講的句子")
    if not duration:
        duration = max(float(c["end"]) for c in cues)
    keep = retakes.retake_keep_segments(duration, found, settings["pad"])
    reasons = [(r["start"], r["end"],
                f"跟後面「{_short(r['matched_text'])}」相似 {r['similarity'] * 100:.0f}%，"
                "剪掉較早這次") for r in found]
    return _result(RETAKES, _marks(RETAKES, cut_spans(keep, duration), reasons))


def words_from_cues(cues):
    """
    審片要的逐字時間軸：每一句都有逐字資料就攤平用它，否則每句當一個「字」。
    """
    cues = sorted(_playable(cues), key=lambda c: float(c["start"]))
    texted = [c for c in cues if str(c.get("text", "")).strip()]
    if texted and all(c.get("words") for c in texted):
        words = [{"word": str(w.get("word", "")).strip(), "start": float(w["start"]),
                  "end": float(w["end"])}
                 for c in texted for w in c["words"] if "start" in w and "end" in w]
        words = [w for w in words if w["word"]]
        return sorted(words, key=lambda w: w["start"])
    return [{"word": " ".join(str(c["text"]).split()), "start": float(c["start"]),
             "end": float(c["end"])} for c in texted]


def review_marks(cues, duration, config=None):
    settings = review.resolve_settings(config)
    words = words_from_cues(cues)
    if not words:
        return _result(REVIEW, [], "沒有字幕可以審")
    items = review.analyze(words, media_duration=duration or 0.0, settings=settings)
    if not duration:
        duration = max(i["end"] for i in items)
    drop_fillers = settings["cut_filler_words"]
    keep = review.kept_ranges(items, drop_filler_words=drop_fillers)
    reasons = []
    for item in items:
        if not item["keep"]:
            tags = "、".join(item["tags"]) or "建議捨棄"
            text = item["text"] if item["kind"] == "silence" else f"「{_short(item['text'])}」"
            reasons.append((item["start"], item["end"], f"{tags}：{text}"))
        elif drop_fillers:
            for s, e in item.get("filler_spans") or ():
                reasons.append((s, e, "口頭禪"))
    note = "" if keep else "沒有建議保留的段落（整支都會剪掉）"
    result = _result(REVIEW, _marks(REVIEW, cut_spans(keep, duration), reasons), note)
    if not result["marks"] and not note:
        result["note"] = "沒有建議剪掉的段落"
    return result


_BUILDERS = {JUMPCUT: jumpcut_marks, RETAKES: retake_marks, REVIEW: review_marks}


def plan(source, cues, duration, config=None):
    """
    算某一種來源的剪點。回傳 {"source", "marks": [{"source", "start", "end",
    "reasons": [說明…]}], "removed_seconds": 剪掉的總秒數, "note": 一行說明（沒有
    剪點的原因、一般版會拒絕剪的警告），沒有就是空字串}。
    """
    if source not in _BUILDERS:
        raise ValueError(f"不認得的剪點來源：{source!r}")
    if not _playable(cues):
        return _result(source, [], "還沒有字幕——剪點是從字幕的時間算出來的")
    return _BUILDERS[source](cues, float(duration or 0.0), config)


def _ms(seconds):
    return int(round(float(seconds) * 1000))


def apply_overrides(marks, overrides):
    """
    把使用者的微調套回剪點：overrides 是 {key: {"enabled": bool, "start": 秒, "end": 秒}}
    （欄位都可省略）。回傳新清單（不改傳進來的）；對不上 key 的微調不理。
    套上去的剪點多一個 "edited": True（起訖跟算出來的不一樣時）。
    """
    out = []
    for mark in marks:
        mark = dict(mark)
        change = (overrides or {}).get(mark.get("key"))
        if change:
            if "enabled" in change:
                mark["enabled"] = bool(change["enabled"])
            if "start" in change and "end" in change:
                mark["start"], mark["end"] = round(float(change["start"]), 3), round(float(change["end"]), 3)
        key_start, key_end = _key_times(mark)
        mark["edited"] = key_start is not None and (
            _ms(mark["start"]), _ms(mark["end"])) != (_ms(key_start), _ms(key_end))
        out.append(mark)
    return out


def _key_times(mark):
    try:
        span = str(mark["key"]).rsplit(":", 1)[1]
        start, end = span.split("-")
        return float(start), float(end)
    except (KeyError, IndexError, ValueError):
        return None, None


def drag_mark_edge(marks, index, edge, seconds, duration=None, min_len=MIN_CUT):
    """
    把第 index 段剪點的 edge（"start"／"end"）拖到 seconds，回傳合法的 (開始, 結束)。
    不能拖過相鄰的剪點（依開始時間排序找鄰居）、不出 0～片長、至少 min_len 秒。
    原本就超出界線的不會被硬拉回來，但也不能再往外拖。
    """
    if edge not in ("start", "end"):
        raise ValueError(f"edge 只能是 'start' 或 'end'：{edge!r}")
    me = marks[index]
    start, end = _ms(me["start"]), _ms(me["end"])
    min_ms = _ms(min_len)
    prev_end = next_start = None
    for i, other in enumerate(marks):
        if i == index:
            continue
        o_start, o_end = _ms(other["start"]), _ms(other["end"])
        if o_start < start or (o_start == start and i < index):
            prev_end = o_end if prev_end is None else max(prev_end, o_end)
        else:
            next_start = o_start if next_start is None else min(next_start, o_start)
    t = _ms(seconds)
    if edge == "start":
        low = 0 if prev_end is None else min(prev_end, start)
        low = min(max(low, 0), start)
        high = max(end - min_ms, low)
        start = min(max(t, low), high)
    else:
        highs = [h for h in (next_start, _ms(duration) if duration else None) if h is not None]
        high = max(min(highs), end) if highs else None
        low = start + min_ms
        end = max(t, low) if high is None else min(max(t, low), max(high, low))
    return start / 1000.0, end / 1000.0


def recount(result):
    """照啟用中的剪點重算 removed_seconds（改 result 本身並回傳）。"""
    result["removed_seconds"] = round(sum(m["end"] - m["start"] for m in result["marks"]
                                          if m.get("enabled", True)), 3)
    return result


def kept_segments(marks, duration):
    """啟用中的剪點以外＝要保留的 (開始, 結束) 片段（依時間排序）。"""
    cuts = sorted((float(m["start"]), float(m["end"])) for m in marks if m.get("enabled", True))
    keep, cursor = [], 0.0
    for start, end in cuts:
        if start - cursor > _EPS:
            keep.append((round(cursor, 3), round(start, 3)))
        cursor = max(cursor, end)
    if duration and float(duration) - cursor > _EPS:
        keep.append((round(cursor, 3), round(float(duration), 3)))
    return keep


def summary(result):
    """一行摘要（狀態列用）：只算啟用中的剪點；停用、調過的另外寫出來。"""
    label = SOURCE_LABELS[result["source"]]
    marks = result["marks"]
    if not marks:
        return f"{label}：{result['note'] or '沒有剪點'}"
    on = [m for m in marks if m.get("enabled", True)]
    removed = sum(m["end"] - m["start"] for m in on)
    text = f"{label}：{len(on)} 處，共剪掉 {removed:.1f} 秒"
    extra = []
    if len(on) < len(marks):
        extra.append(f"停用 {len(marks) - len(on)} 處")
    edited = sum(1 for m in marks if m.get("edited"))
    if edited:
        extra.append(f"調過 {edited} 處")
    if result["note"]:
        extra.append(result["note"])
    if extra:
        text += "（" + "；".join(extra) + "）"
    return text


def _short(text, limit=16):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "…"
