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

這一階段只負責「看得到」；下一階段才是剪點可拖、可單獨停用。
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
        marks.append({"source": source, "start": round(start, 3), "end": round(end, 3),
                      "reasons": list(dict.fromkeys(why))})
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


def summary(result):
    """一行摘要（狀態列用）。"""
    label = SOURCE_LABELS[result["source"]]
    if not result["marks"]:
        return f"{label}：{result['note'] or '沒有剪點'}"
    text = f"{label}：{len(result['marks'])} 處，共剪掉 {result['removed_seconds']:.1f} 秒"
    if result["note"]:
        text += f"（{result['note']}）"
    return text


def _short(text, limit=16):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "…"
