# -*- coding: utf-8 -*-
"""
畫面曝光與色偏健檢：上片前抓出「調色沒調好」的翻車點。

調研顯示曝光不足／過曝、白平衡沒調好造成的色偏（畫面偏黃偏藍），
是創作者社群反覆提到的剪輯常見錯誤——不少創作者匯出後直接上傳，
沒有從頭到尾看過一次，這類問題往往等觀眾留言才發現。本工具既有的
影片畫質健檢（v1.17.0）只看位元率／解析度／更新率／編碼等技術規格，
完全沒有涵蓋畫面本身「好不好看」這件事。

本模組用 ffmpeg 的 signalstats 濾鏡在全片均勻取樣幾張畫面（免逐幀
解碼，速度快），量測平均亮度（是否過暗／過曝）與 U/V 色度平均值
（是否偏離中性灰，代表明顯色偏）。

色彩校正的「正確答案」因人因場景而異，錯誤的自動校正反而可能讓
畫面更難看（例如刻意的暖色調氛圍被誤「修正」成灰白）；因此比照
凍結畫面偵測（v1.26.0）的設計，本模組只負責報告與建議，不提供
自動一鍵校色，交由使用者自行判斷是否需要回到剪輯軟體調色。

零 GUI 依賴，供健檢對話框與 CLI 共用。
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Callable, Optional

from .audiocheck import LEVEL_BAD, LEVEL_GOOD, LEVEL_WARN, _LEVEL_ICONS
from .burner import ffmpeg_available
from .media import has_video_stream, probe_duration

DEFAULT_COLORCHECK = {
    "sample_count": 6,       # 全片均勻取樣張數
    "dark_luma": 60.0,       # 平均亮度低於此值視為曝光不足（0~255）
    "bright_luma": 200.0,    # 平均亮度高於此值視為過曝（0~255）
    "cast_threshold": 10.0,  # U/V 偏離中性 128 超過此值視為明顯色偏
}

_SAMPLE_RANGE = (3, 12)
_DARK_RANGE = (20.0, 100.0)
_BRIGHT_RANGE = (160.0, 240.0)
_CAST_RANGE = (5.0, 25.0)

_STAT_RE = re.compile(
    r"lavfi\.signalstats\.(YAVG|UAVG|VAVG)=([\-\d.]+)")

# 取樣時避開開頭與結尾（常是黑畫面／轉場，量測會失真）。
_SAMPLE_MARGIN = 0.05


def _clamp_float(value, low, high, fallback):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_colorcheck_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出色彩健檢參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_COLORCHECK)
    if config:
        raw.update({k: v for k, v in config.get("colorcheck", {}).items()
                    if v is not None})
    try:
        sample_count = int(raw.get("sample_count",
                                    DEFAULT_COLORCHECK["sample_count"]))
    except (TypeError, ValueError):
        sample_count = DEFAULT_COLORCHECK["sample_count"]
    return {
        "sample_count": max(_SAMPLE_RANGE[0],
                            min(sample_count, _SAMPLE_RANGE[1])),
        "dark_luma": _clamp_float(raw.get("dark_luma"), *_DARK_RANGE,
                                  DEFAULT_COLORCHECK["dark_luma"]),
        "bright_luma": _clamp_float(raw.get("bright_luma"), *_BRIGHT_RANGE,
                                    DEFAULT_COLORCHECK["bright_luma"]),
        "cast_threshold": _clamp_float(
            raw.get("cast_threshold"), *_CAST_RANGE,
            DEFAULT_COLORCHECK["cast_threshold"]),
    }


def _sample_times(duration: float, count: int) -> list:
    """在 [margin, 1-margin] 區間內均勻取樣 count 個時間點。"""
    if duration <= 0:
        return []
    lo = duration * _SAMPLE_MARGIN
    hi = duration * (1.0 - _SAMPLE_MARGIN)
    if hi <= lo:
        return [duration / 2.0]
    if count <= 1:
        return [(lo + hi) / 2.0]
    step = (hi - lo) / (count - 1)
    return [lo + step * i for i in range(count)]


def _measure_frame(media_path: str, time_s: float,
                   timeout: int = 30) -> Optional[dict]:
    """擷取指定時間點的單張畫面並回傳 signalstats 量測結果。"""
    command = [
        "ffmpeg", "-hide_banner", "-nostats",
        "-ss", f"{max(time_s, 0.0):.3f}", "-i", media_path,
        "-vframes", "1", "-vf", "signalstats,metadata=print",
        "-f", "null", "-",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    stderr = (completed.stderr or b"").decode("utf-8", errors="ignore")
    values = {}
    for match in _STAT_RE.finditer(stderr):
        key, value = match.group(1), match.group(2)
        try:
            values[key] = float(value)
        except ValueError:
            continue
    if "YAVG" not in values:
        return None
    return {
        "time": time_s,
        "luma": values["YAVG"],
        "u": values.get("UAVG", 128.0),
        "v": values.get("VAVG", 128.0),
    }


def _cast_description(u: float, v: float, threshold: float) -> Optional[str]:
    """依 U/V 偏離中性 128 的方向給出簡單易懂的色偏描述。"""
    parts = []
    if u - 128.0 > threshold:
        parts.append("偏藍")
    elif 128.0 - u > threshold:
        parts.append("偏黃")
    if v - 128.0 > threshold:
        parts.append("偏紅／洋紅")
    elif 128.0 - v > threshold:
        parts.append("偏綠")
    return "、".join(parts) if parts else None


def analyze_color(
    media_path: str,
    settings: Optional[dict] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> dict:
    """
    全片均勻取樣，回傳 {"samples": [...], "avg_luma", "avg_u", "avg_v",
    "issues": [...]}；issues 為 _finding 風格的字典清單。
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    if not os.path.exists(media_path):
        raise FileNotFoundError(f"找不到檔案：{media_path}")
    if not has_video_stream(media_path):
        raise ValueError("此檔案沒有影像串流，無法分析畫面曝光與色調。")

    settings = settings or resolve_colorcheck_settings()
    duration = probe_duration(media_path)
    times = _sample_times(duration, settings["sample_count"])

    samples = []
    for index, t in enumerate(times):
        if progress_cb:
            progress_cb(index / max(len(times), 1),
                        f"正在取樣畫面（{index + 1}/{len(times)}）...")
        sample = _measure_frame(media_path, t)
        if sample:
            samples.append(sample)

    if not samples:
        return {"samples": [], "avg_luma": None, "avg_u": None,
                "avg_v": None, "issues": []}

    avg_luma = sum(s["luma"] for s in samples) / len(samples)
    avg_u = sum(s["u"] for s in samples) / len(samples)
    avg_v = sum(s["v"] for s in samples) / len(samples)

    issues = []
    if avg_luma < settings["dark_luma"]:
        issues.append({
            "level": LEVEL_WARN, "title": "曝光",
            "detail": f"平均亮度 {avg_luma:.0f}/255，偏暗（曝光不足）",
            "advice": "畫面偏暗細節容易糊成一片；可回剪輯軟體提高亮度／"
                      "對比，或重新拍攝時增加補光。",
        })
    elif avg_luma > settings["bright_luma"]:
        issues.append({
            "level": LEVEL_WARN, "title": "曝光",
            "detail": f"平均亮度 {avg_luma:.0f}/255，偏亮（可能過曝）",
            "advice": "過曝的亮部細節通常救不回來；可回剪輯軟體降低曝光／"
                      "對比，或重新拍攝時減少進光量。",
        })
    else:
        issues.append({
            "level": LEVEL_GOOD, "title": "曝光",
            "detail": f"平均亮度 {avg_luma:.0f}/255，正常"})

    cast = _cast_description(avg_u, avg_v, settings["cast_threshold"])
    if cast:
        issues.append({
            "level": LEVEL_WARN, "title": "色偏",
            "detail": f"畫面整體{cast}，可能是白平衡沒調好",
            "advice": "可回剪輯軟體調整白平衡／色溫校正；若是刻意營造的"
                      "色調氛圍可忽略此提醒。",
        })
    else:
        issues.append({
            "level": LEVEL_GOOD, "title": "色偏", "detail": "色調接近中性，正常"})

    if progress_cb:
        progress_cb(1.0, "畫面曝光與色調分析完成。")
    return {"samples": samples, "avg_luma": avg_luma, "avg_u": avg_u,
            "avg_v": avg_v, "issues": issues}


def format_color_report(result: dict) -> str:
    """把色彩健檢結果排成純文字段落（附加在其他健檢報告之後）。"""
    issues = (result or {}).get("issues") or []
    if not issues:
        return "===== 畫面曝光與色調 =====\n素材過短或無法取樣，略過此項分析。"
    lines = ["===== 畫面曝光與色調 ====="]
    for issue in issues:
        icon = _LEVEL_ICONS.get(issue["level"], "・")
        lines.append(f"{icon} {issue['title']}：{issue['detail']}")
        if issue.get("advice"):
            lines.append(f"    建議：{issue['advice']}")
    return "\n".join(lines)
