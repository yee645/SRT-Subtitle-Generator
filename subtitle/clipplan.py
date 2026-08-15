# -*- coding: utf-8 -*-
"""
短片選段規劃：把一支長片自動挑成好幾支可以直接發的直式短片。

調研（中英文皆搜）指出「一支長片再利用成多支短影音」已經是 2026 年的
主流工作流程，但同一批資料也點名了它真正的失敗模式：**做出一套慢到
撐不下去的流程**（「the risky part is building a workflow that is too
slow to sustain」）。另一個共識是**選段比數量重要**——「最強的再利用
系統都是從『本來就有張力、有結論、有意外』的片段開始」，而不是把整支
影片機械式切塊。

本工具的缺口剛好就在這裡。v1.5.0 已經有直式短片輸出（`shorts.py` 的
`cut_vertical_clip`），品質也夠用，但是：

- **只有 GUI 入口**：得在審片視窗裡自己一段一段勾選再按輸出
- **沒有任何地方在決定「要剪哪幾段」**：選段完全靠人工
- 因此**沒辦法批次**——十支影片就是十次手動操作，正是調研說的那種
  「慢到撐不下去」的流程

所以缺的不是把既有函式包一層 CLI，而是中間那段**從來不存在的邏輯**：
拿審片模組已經算好的精彩片段，規劃成一組**真的能發**的短片。這件事有
幾個非做不可的判斷：

1. **長度要落在平台可用範圍**。精彩片段本身長度是任意的——可能 3 秒，
   也可能 90 秒。太短沒頭沒尾、太長超過 Shorts 上限。
2. **太短的要往外擴**，而且要**沿著講話段落的邊界擴**，不能從句子中間
   切下去；擴的時候前後都要考慮，才不會每支都從半句話開始。
3. **彼此不能重疊**，否則會輸出好幾支內容幾乎一樣的短片。
4. **擴不到最短長度的就該放棄**，不是硬湊一支沒人看得完的東西。

只規劃不猜內容：真正要發哪幾支仍由使用者決定，本模組給的是排序過的
候選與明確的理由。

零 GUI 依賴，供 CLI 批次與審片視窗共用。
"""

from __future__ import annotations

from typing import Optional

from subtitle.review import TAG_HIGHLIGHT

# 使用者可調參數（config["clipplan"]）。
DEFAULT_CLIPPLAN = {
    # 一支長片要規劃出幾支短片。
    "count": 3,
    # 短片最短長度（秒）。太短的片段沒頭沒尾，觀眾看不懂在講什麼。
    "min_seconds": 15.0,
    # 短片最長長度（秒）。YouTube Shorts／Reels／TikTok 的共同安全值。
    "max_seconds": 60.0,
    # 前後各留一點呼吸，避免第一個字被切掉。
    "pad_seconds": 0.4,
    # 兩支短片之間至少要隔開多久，避免內容重疊。
    "min_gap_seconds": 5.0,
}

_COUNT_RANGE = (1, 20)
_MIN_RANGE = (3.0, 60.0)
_MAX_RANGE = (10.0, 180.0)
_PAD_RANGE = (0.0, 3.0)
_GAP_RANGE = (0.0, 120.0)


def _clamp(value, low, high, fallback, cast=float):
    try:
        value = cast(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_clipplan_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出短片選段參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_CLIPPLAN)
    if config:
        raw.update({k: v for k, v in config.get("clipplan", {}).items()
                    if v is not None})
    resolved = {
        "count": _clamp(raw.get("count"), *_COUNT_RANGE,
                        DEFAULT_CLIPPLAN["count"], int),
        "min_seconds": _clamp(raw.get("min_seconds"), *_MIN_RANGE,
                              DEFAULT_CLIPPLAN["min_seconds"]),
        "max_seconds": _clamp(raw.get("max_seconds"), *_MAX_RANGE,
                              DEFAULT_CLIPPLAN["max_seconds"]),
        "pad_seconds": _clamp(raw.get("pad_seconds"), *_PAD_RANGE,
                              DEFAULT_CLIPPLAN["pad_seconds"]),
        "min_gap_seconds": _clamp(raw.get("min_gap_seconds"), *_GAP_RANGE,
                                  DEFAULT_CLIPPLAN["min_gap_seconds"]),
    }
    # 使用者可能把最短設得比最長還大；照著跑會一支都規劃不出來，
    # 這裡直接以最長為準把最短壓回去，而不是靜靜地產出空清單。
    if resolved["min_seconds"] > resolved["max_seconds"]:
        resolved["min_seconds"] = resolved["max_seconds"]
    return resolved


def speech_segments(items: list) -> list:
    """從審片結果取出講話段落（依時間排序），供選段擴張使用。"""
    rows = [i for i in items or [] if i.get("kind") == "speech"]
    rows.sort(key=lambda i: float(i.get("start") or 0.0))
    return rows


def _expand(segments: list, index: int, settings: dict) -> tuple:
    """
    從第 index 段往外擴到夠長，回傳 (起段, 迄段) 的索引。

    沿著**講話段落的邊界**擴，不會從句子中間切下去；前後輪流擴一段，
    才不會每支短片都從半句話開始、或都在同一個方向長出去。
    """
    low = high = index
    target = settings["min_seconds"]
    limit = settings["max_seconds"]

    def span(a, b):
        return float(segments[b]["end"]) - float(segments[a]["start"])

    forward = True
    while span(low, high) < target:
        grew = False
        # 前後輪流試；某一邊擴不動（到頭或會超過上限）就換另一邊。
        for _ in range(2):
            if forward and high + 1 < len(segments):
                if span(low, high + 1) <= limit:
                    high += 1
                    grew = True
            elif not forward and low - 1 >= 0:
                if span(low - 1, high) <= limit:
                    low -= 1
                    grew = True
            forward = not forward
            if grew:
                break
        if not grew:
            break
    return (low, high)


def plan_clips(items: list, settings: Optional[dict] = None,
               media_duration: float = 0.0) -> list:
    """
    規劃出一組可直接輸出的短片候選。

    回傳 [{"start","end","duration","score","text","trimmed"}, ...]，
    依精彩分數由高到低排序，彼此不重疊。
    """
    settings = settings or resolve_clipplan_settings()
    segments = speech_segments(items)
    if not segments:
        return []

    ranked = sorted(
        (i for i, seg in enumerate(segments)
         if TAG_HIGHLIGHT in (seg.get("tags") or [])),
        key=lambda i: -float(segments[i].get("score") or 0.0))

    pad = settings["pad_seconds"]
    limit = settings["max_seconds"]
    gap = settings["min_gap_seconds"]
    picked = []

    for index in ranked:
        if len(picked) >= settings["count"]:
            break
        low, high = _expand(segments, index, settings)
        start = float(segments[low]["start"]) - pad
        end = float(segments[high]["end"]) + pad
        start = max(start, 0.0)
        if media_duration and media_duration > 0:
            end = min(end, float(media_duration))

        trimmed = False
        if end - start > limit:
            # 單一段落就超過上限時，取開頭那一段——精彩片段的鉤子
            # 通常在開頭，硬要塞完整段反而會超過平台限制。
            end = start + limit
            trimmed = True

        duration = end - start
        if duration < settings["min_seconds"]:
            # 擴到底仍然太短，硬湊出來也沒人看得完，直接放棄這一段。
            continue
        if any(start < p["end"] + gap and end + gap > p["start"]
               for p in picked):
            continue

        picked.append({
            "start": start,
            "end": end,
            "duration": duration,
            "score": float(segments[index].get("score") or 0.0),
            "text": (segments[index].get("text") or "").strip(),
            "trimmed": trimmed,
        })

    picked.sort(key=lambda c: -c["score"])
    return picked


def format_timestamp(seconds: float) -> str:
    """把秒數排成 M:SS／H:MM:SS，與其他模組的顯示格式一致。"""
    seconds = max(int(seconds or 0), 0)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_clip_plan_report(clips: list,
                            settings: Optional[dict] = None) -> str:
    """把選段結果排成純文字報告（CLI 輸出與 GUI 顯示共用）。"""
    settings = settings or resolve_clipplan_settings()
    lines = ["===== 短片選段規劃（長片自動挑成多支直式短片）====="]
    if not clips:
        lines.append("・沒有規劃出可用的短片段落。")
        lines.append("")
        lines.append(
            f"可能的原因：這支影片沒有偵測到精彩片段，或精彩片段擴到"
            f"講話段落邊界後仍不足 {settings['min_seconds']:.0f} 秒。"
            "可於 config.json 的 clipplan 調低 min_seconds，"
            "或於審片設定調整精彩判定敏感度。")
        return "\n".join(lines)

    for index, clip in enumerate(clips, start=1):
        mark = "（已裁到長度上限）" if clip["trimmed"] else ""
        lines.append(
            f"  短片 {index}：{format_timestamp(clip['start'])}～"
            f"{format_timestamp(clip['end'])}"
            f"（{clip['duration']:.0f} 秒，精彩分數 {clip['score']:.1f}）"
            f"{mark}")
        if clip["text"]:
            lines.append(f"    內容：「{clip['text'][:40]}」")

    lines.append("")
    lines.append(
        f"共規劃 {len(clips)} 支，長度介於 "
        f"{settings['min_seconds']:.0f}～{settings['max_seconds']:.0f} 秒；"
        "各段沿講話段落邊界切齊，不會從句子中間開始。")
    return "\n".join(lines)
