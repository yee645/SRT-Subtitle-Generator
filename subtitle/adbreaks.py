# -*- coding: utf-8 -*-
"""
Mid-roll 廣告插入點建議：從審片分析找出「自然停頓」時間點。

YouTube 允許 8 分鐘以上的影片放置 mid-roll 廣告，且官方明確指出：
放在「自然停頓、話題轉換」的廣告點觀眾留存較高、也較容易被實際投放；
插在句子中間的廣告點則常被系統跳過。手動找這些點得整支影片再拉一次
時間軸——而審片分析早就知道每個停頓在哪裡。

本模組從段落資料計算建議插入點：挑講話段落之間夠長的停頓，
優先選停頓最久的（通常就是話題轉換處），彼此保持最小間隔、
避開影片頭尾。時間以原始素材時間軸為準（未剪輯直接上傳時直接可用；
輸出粗剪後上傳者請以粗剪版重新分析）。

純計算、零 GUI 依賴，供審片助手與發佈包共用。
"""

from __future__ import annotations

from typing import Optional

# YouTube mid-roll 的最短影片長度（8 分鐘）。
MIDROLL_MIN_SECONDS = 8 * 60

# 使用者可調參數（config["adbreaks"]）。
DEFAULT_ADBREAKS = {
    "min_spacing_minutes": 4.0,  # 兩個廣告點的最小間隔（分鐘）
    "max_breaks": 6,             # 建議數量上限
    "min_pause": 1.2,            # 視為「自然停頓」的最短無人聲秒數
    "skip_head_minutes": 2.0,    # 影片開頭不放廣告的長度（分鐘）
    "skip_tail_minutes": 1.0,    # 影片結尾不放廣告的長度（分鐘）
}
_SPACING_RANGE = (2.0, 15.0)
_MAX_BREAKS_RANGE = (1, 20)
_MIN_PAUSE_RANGE = (0.5, 5.0)
_SKIP_HEAD_RANGE = (0.0, 10.0)
_SKIP_TAIL_RANGE = (0.0, 10.0)

# 前後句摘要的長度（讓使用者不開影片也能判斷這個停頓在講什麼之間）。
_CONTEXT_CHARS = 12


def _clamp(value, low, high, fallback):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_adbreak_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出廣告插入點參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_ADBREAKS)
    if config:
        raw.update({k: v for k, v in config.get("adbreaks", {}).items()
                    if v is not None})
    return {
        "min_spacing_minutes": _clamp(
            raw.get("min_spacing_minutes"), *_SPACING_RANGE,
            DEFAULT_ADBREAKS["min_spacing_minutes"]),
        "max_breaks": int(_clamp(
            raw.get("max_breaks"), *_MAX_BREAKS_RANGE,
            DEFAULT_ADBREAKS["max_breaks"])),
        "min_pause": _clamp(raw.get("min_pause"), *_MIN_PAUSE_RANGE,
                            DEFAULT_ADBREAKS["min_pause"]),
        "skip_head_minutes": _clamp(
            raw.get("skip_head_minutes"), *_SKIP_HEAD_RANGE,
            DEFAULT_ADBREAKS["skip_head_minutes"]),
        "skip_tail_minutes": _clamp(
            raw.get("skip_tail_minutes"), *_SKIP_TAIL_RANGE,
            DEFAULT_ADBREAKS["skip_tail_minutes"]),
    }


def find_pause_candidates(items, min_pause: float) -> list:
    """
    找出講話段落之間 ≥ min_pause 秒的停頓。

    回傳 [{"time": 停頓中點秒數, "gap": 停頓長度,
           "before": 前句結尾摘要, "after": 後句開頭摘要}, ...]（依時間排序）。
    """
    speech = sorted(
        (item for item in (items or []) if item.get("kind") == "speech"),
        key=lambda item: item["start"])
    candidates = []
    for prev, nxt in zip(speech, speech[1:]):
        gap = nxt["start"] - prev["end"]
        if gap < min_pause:
            continue
        candidates.append({
            "time": (prev["end"] + nxt["start"]) / 2.0,
            "gap": gap,
            "before": (prev.get("text") or "").strip()[-_CONTEXT_CHARS:],
            "after": (nxt.get("text") or "").strip()[:_CONTEXT_CHARS],
        })
    return candidates


def suggest_ad_breaks(items, duration: float,
                      settings: Optional[dict] = None) -> list:
    """
    建議 mid-roll 廣告插入點（依時間排序）。

    影片不足 8 分鐘（YouTube mid-roll 門檻）時回傳空清單。
    候選以「停頓越久越優先」挑選（長停頓通常就是話題轉換處），
    同時保持彼此最小間隔並避開頭尾。
    """
    settings = settings or resolve_adbreak_settings()
    if not duration or duration < MIDROLL_MIN_SECONDS:
        return []
    head = settings["skip_head_minutes"] * 60.0
    tail_limit = duration - settings["skip_tail_minutes"] * 60.0
    spacing = settings["min_spacing_minutes"] * 60.0

    candidates = [c for c in find_pause_candidates(items,
                                                   settings["min_pause"])
                  if head <= c["time"] <= tail_limit]
    candidates.sort(key=lambda c: -c["gap"])

    picked = []
    for candidate in candidates:
        if len(picked) >= settings["max_breaks"]:
            break
        if all(abs(candidate["time"] - p["time"]) >= spacing
               for p in picked):
            picked.append(candidate)
    picked.sort(key=lambda c: c["time"])
    return picked


def _stamp(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return (f"{hours}:{minutes:02d}:{secs:02d}" if hours
            else f"{minutes:02d}:{secs:02d}")


def format_ad_breaks(breaks) -> str:
    """把建議插入點排成可貼上的文字清單（含前後句摘要供人工確認）。"""
    if not breaks:
        return ""
    lines = ["建議 mid-roll 廣告插入點（自然停頓處，於 YouTube Studio "
             "手動放置時參考）："]
    for index, item in enumerate(breaks, start=1):
        context = ""
        if item.get("before") or item.get("after"):
            context = f"　…{item.get('before', '')}｜{item.get('after', '')}…"
        lines.append(f"{index}. {_stamp(item['time'])}"
                     f"（停頓 {item['gap']:.1f} 秒）{context}")
    return "\n".join(lines)
