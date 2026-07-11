# -*- coding: utf-8 -*-
"""
響度正規化模組（YouTube -14 LUFS 標準）。

YouTube 對超過約 -14 LUFS 的音訊會自動調小，但**太小聲的不會調大**——
音量偏低的影片在平台上會一直小聲，觀眾體驗差。本模組以 ffmpeg 的
loudnorm 濾鏡做兩階段正規化：

1. 量測：先掃一遍音訊取得實際響度數據（integrated LUFS、true peak、LRA）。
2. 套用：把量測值帶回 loudnorm 以線性模式精準校正到目標響度。

目標響度可調（預設 -14 LUFS，即 YouTube 的正規化基準）；
供燒錄字幕與 Shorts 直式輸出流程掛用，也可對影片單獨執行。
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from typing import Callable, Optional

from .burner import _stream_progress, ffmpeg_available
from .media import probe_duration

logger = logging.getLogger(__name__)

# 目標響度的合理範圍（LUFS）；YouTube 標準為 -14。
DEFAULT_TARGET_LUFS = -14.0
MIN_TARGET_LUFS = -30.0
MAX_TARGET_LUFS = -8.0

# loudnorm 的其餘目標參數（true peak 上限與響度範圍），採業界常用值。
_TARGET_TRUE_PEAK = -1.5
_TARGET_LRA = 11.0

# ffmpeg loudnorm print_format=json 會把 JSON 區塊印在 stderr。
_JSON_BLOCK_RE = re.compile(r"\{[^{}]*\}", re.S)


def clamp_target(value, fallback: float = DEFAULT_TARGET_LUFS) -> float:
    """夾限目標響度到合理範圍；無法解析時回傳預設值。"""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(MIN_TARGET_LUFS, min(value, MAX_TARGET_LUFS))


def measure_loudness(media_path: str, timeout: int = 600) -> Optional[dict]:
    """
    第一階段：量測音訊實際響度。

    回傳 loudnorm 輸出的量測 dict（input_i / input_tp / input_lra /
    input_thresh / target_offset）；ffmpeg 不可用或量測失敗時回傳 None，
    呼叫端應退回單階段動態模式或跳過正規化。
    """
    if not ffmpeg_available():
        return None
    command = [
        "ffmpeg", "-hide_banner", "-nostats",
        "-i", media_path,
        "-vn",
        "-af",
        (f"loudnorm=I={DEFAULT_TARGET_LUFS}:TP={_TARGET_TRUE_PEAK}:"
         f"LRA={_TARGET_LRA}:print_format=json"),
        "-f", "null", "-",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    stderr = (completed.stderr or b"").decode("utf-8", errors="ignore")
    # 取 stderr 中最後一個 JSON 區塊（loudnorm 的量測報告）。
    matches = _JSON_BLOCK_RE.findall(stderr)
    for block in reversed(matches):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if "input_i" in data:
            return data
    return None


def build_loudnorm_filter(measured: Optional[dict] = None,
                          target_lufs: float = DEFAULT_TARGET_LUFS) -> str:
    """
    組出 loudnorm 濾鏡字串。

    有量測資料時採兩階段線性模式（音質最佳、響度最準）；
    無量測資料時退回單階段動態模式（仍可正規化，精準度稍差）。
    """
    target = clamp_target(target_lufs)
    base = (f"loudnorm=I={target}:TP={_TARGET_TRUE_PEAK}:LRA={_TARGET_LRA}")
    if not measured:
        return base
    return (
        f"{base}"
        f":measured_I={measured.get('input_i')}"
        f":measured_TP={measured.get('input_tp')}"
        f":measured_LRA={measured.get('input_lra')}"
        f":measured_thresh={measured.get('input_thresh')}"
        f":offset={measured.get('target_offset', 0.0)}"
        f":linear=true"
    )


def normalize_video(
    input_path: str,
    output_path: str,
    target_lufs: float = DEFAULT_TARGET_LUFS,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    對影片做響度正規化：影像串流原樣複製、音訊重編碼校正到目標響度。

    參數：
        input_path: 來源影片。
        output_path: 輸出影片路徑。
        target_lufs: 目標響度（預設 -14，YouTube 標準）。
        progress_cb: (ratio, message) 進度回呼。
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")

    if progress_cb:
        progress_cb(0.0, "正在量測音訊響度（第 1/2 階段）...")
    measured = measure_loudness(input_path)
    audio_filter = build_loudnorm_filter(measured, target_lufs)

    duration = probe_duration(input_path)
    if progress_cb:
        progress_cb(0.05, "正在套用響度正規化（第 2/2 階段）...")
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", input_path,
        "-c:v", "copy",
        "-af", audio_filter,
        "-c:a", "aac", "-b:a", "192k",
        "-progress", "pipe:1",
        output_path,
    ]
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="ignore",
        )
    except OSError as exc:
        raise RuntimeError(f"無法啟動 ffmpeg：{exc}") from exc

    _stream_progress(process, duration, progress_cb)
    ret = process.wait()
    if ret != 0:
        stderr = (process.stderr.read() if process.stderr else "") or ""
        raise RuntimeError(f"響度正規化失敗：{stderr[-400:]}")
    if progress_cb:
        progress_cb(1.0, "響度正規化完成")
    return output_path
