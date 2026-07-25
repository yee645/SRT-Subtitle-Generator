# -*- coding: utf-8 -*-
"""
重複片段（NG 重錄）偵測與一鍵剪除。

創作者社群公認「同一句話講了好幾次、要手動找出前面講壞掉的那幾次
並剪掉」是初剪另一個吃時間的步驟——現有的坊間工具多半靠語意模型
比對逐字稿，找出重講的句子並自動剪去較早的失敗版本，只留下最後
（通常是講得最順）的那一次。

本工具已有的逐字稿與字幕 cue 時間軸就是現成的比對材料：同一時間窗
內若有兩句字幕文字高度相似，視為「同一句話的前一次嘗試」，標記為
候選重複片段。**這是內容層級的判斷、假陽性風險比純靜音的跳剪高**
（例如刻意重複的口號、報數測試麥克風），因此設計為「偵測 → 列出
候選給使用者勾選確認 → 才真正剪」，而非像跳剪停頓那樣全自動套用。

實際裁切沿用 jumpcut.py 已有的裁切引擎（trim+concat＋時間軸重新
對映），零 GUI 依賴，供 GUI 對話框與 CLI 共用。
"""

from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from typing import Callable, Optional

from .burner import ffmpeg_available
from .jumpcut import _format_seconds, cut_media_segments, remap_cues
from .media import probe_duration

# 使用者可調參數（config["retakes"]）。
DEFAULT_RETAKES = {
    "similarity_threshold": 0.72,  # 兩句文字相似度達此值才視為同一句重講
    "max_gap_seconds": 25.0,       # 只比對此秒數內的句子（間隔太遠不算重錄）
    "pad": 0.2,                    # 剪掉的片段前後各多剪一點（含吸氣停頓）
}
_SIMILARITY_RANGE = (0.5, 0.98)
_MAX_GAP_RANGE = (5.0, 120.0)
_PAD_RANGE = (0.0, 1.0)

_WS_RE = re.compile(r"\s+")


def _clamp(value, low, high, fallback):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_retake_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出去重複參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_RETAKES)
    if config:
        raw.update({k: v for k, v in config.get("retakes", {}).items()
                    if v is not None})
    return {
        "similarity_threshold": _clamp(
            raw.get("similarity_threshold"), *_SIMILARITY_RANGE,
            DEFAULT_RETAKES["similarity_threshold"]),
        "max_gap_seconds": _clamp(
            raw.get("max_gap_seconds"), *_MAX_GAP_RANGE,
            DEFAULT_RETAKES["max_gap_seconds"]),
        "pad": _clamp(raw.get("pad"), *_PAD_RANGE, DEFAULT_RETAKES["pad"]),
    }


def _normalize(text: str) -> str:
    """比對前的正規化：去除換行與多餘空白，不改動原文內容。"""
    return _WS_RE.sub("", (text or "").strip())


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def find_retakes(cues: list, settings: Optional[dict] = None) -> list:
    """
    掃描字幕 cue，找出候選重複片段（同一時間窗內文字高度相似的句子）。

    每組相似的句子只保留「最後一次」，較早的都標記為候選重複片段。
    回傳：[{"index": 原始 cue 索引, "start", "end", "text",
           "matched_index": 對應到的較晚 cue 索引, "matched_text",
           "similarity": 相似度}, ...]，依時間排序。
    """
    if not cues or len(cues) < 2:
        return []
    settings = settings or resolve_retake_settings()
    threshold = settings["similarity_threshold"]
    max_gap = settings["max_gap_seconds"]

    ordered = sorted(range(len(cues)), key=lambda i: cues[i]["start"])
    normalized = [_normalize(cues[i]["text"]) for i in ordered]

    retakes = []
    superseded = set()
    for a in range(len(ordered)):
        if a in superseded:
            continue
        idx_a = ordered[a]
        if not normalized[a]:
            continue
        for b in range(a + 1, len(ordered)):
            idx_b = ordered[b]
            if cues[idx_b]["start"] - cues[idx_a]["end"] > max_gap:
                break
            if not normalized[b]:
                continue
            ratio = _similarity(normalized[a], normalized[b])
            if ratio >= threshold:
                retakes.append({
                    "index": idx_a,
                    "start": cues[idx_a]["start"],
                    "end": cues[idx_a]["end"],
                    "text": cues[idx_a]["text"],
                    "matched_index": idx_b,
                    "matched_text": cues[idx_b]["text"],
                    "similarity": round(ratio, 3),
                })
                superseded.add(a)
                break
    retakes.sort(key=lambda r: r["start"])
    return retakes


def format_retakes_report(retakes: list) -> str:
    """把偵測結果排成人類可讀的候選清單（供對話框／CLI 顯示）。"""
    if not retakes:
        return "未偵測到疑似重複片段。"
    lines = [f"共偵測到 {len(retakes)} 處疑似重複片段（建議剪掉較早的版本）："]
    for i, r in enumerate(retakes, start=1):
        lines.append(
            f"  {i}. {r['start']:.1f}s ~ {r['end']:.1f}s"
            f"（相似度 {r['similarity'] * 100:.0f}%）")
        lines.append(f"     這句：{r['text']}")
        lines.append(f"     後面較晚的版本：{r['matched_text']}")
    return "\n".join(lines)


def suggest_output_path(input_path: str) -> str:
    """建議輸出路徑：來源檔名加「_去重複」後綴。"""
    base, ext = os.path.splitext(input_path)
    return f"{base}_去重複{ext or '.mp4'}"


def apply_retake_removal(
    media_path: str,
    cues: list,
    selected_retakes: list,
    output_path: str,
    settings: Optional[dict] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> dict:
    """
    剪掉使用者勾選的重複片段，回傳新影片路徑與同步更新（移除已剪句子＋
    重新對齊時間軸）的字幕清單。

    參數：
        cues: 完整字幕清單。
        selected_retakes: find_retakes() 回傳清單中，使用者確認要剪掉的
            項目（子集合即可，未勾選的候選會保留不動）。
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    if not os.path.exists(media_path):
        raise FileNotFoundError(f"找不到檔案：{media_path}")
    if not selected_retakes:
        raise ValueError("沒有勾選任何要剪掉的重複片段。")
    settings = settings or resolve_retake_settings()
    pad = settings["pad"]
    duration = probe_duration(media_path)

    cut_spans = sorted(
        (max(r["start"] - pad, 0.0), min(r["end"] + pad, duration))
        for r in selected_retakes)
    removed_indexes = {r["index"] for r in selected_retakes}

    keep = []
    cursor = 0.0
    for cut_start, cut_end in cut_spans:
        if cut_start <= cursor:
            cursor = max(cursor, cut_end)
            continue
        keep.append((cursor, cut_start))
        cursor = cut_end
    if cursor < duration:
        keep.append((cursor, duration))
    if not keep:
        raise ValueError("剪掉勾選的片段後沒有可保留的內容，請減少勾選項目。")

    kept_seconds = cut_media_segments(
        media_path, keep, output_path, progress_cb,
        label=f"剪掉 {len(selected_retakes)} 處重複片段")

    remaining_cues = [cue for i, cue in enumerate(cues)
                      if i not in removed_indexes]
    new_cues = remap_cues(remaining_cues, keep)
    return {
        "output": output_path,
        "cues": new_cues,
        "cut_count": len(selected_retakes),
        "removed_seconds": round(duration - kept_seconds, 2),
        "kept_seconds": round(kept_seconds, 2),
        "original_seconds": round(duration, 2),
    }


def format_retake_removal_report(result: dict) -> str:
    """把剪除重複片段的結果排成一行人類可讀摘要。"""
    return (
        f"共剪掉 {result['cut_count']} 處重複片段，省下 "
        f"{_format_seconds(result['removed_seconds'])}"
        f"（原長度 {_format_seconds(result['original_seconds'])} → "
        f"剪後 {_format_seconds(result['kept_seconds'])}）。")
