# -*- coding: utf-8 -*-
"""媒體工具：影音檔時長偵測等共用函式。"""

from __future__ import annotations

import shutil
import subprocess

# ffprobe 偵測失敗時的保底時長（避免除以零）。
FALLBACK_DURATION = 60.0


def ffprobe_available() -> bool:
    """檢查系統是否有可用的 ffprobe。"""
    return shutil.which("ffprobe") is not None


def probe_duration(media_path: str) -> float:
    """以 ffprobe 取得媒體檔時長（秒）；失敗時回傳保底值。"""
    if not ffprobe_available():
        return FALLBACK_DURATION
    try:
        completed = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                media_path,
            ],
            capture_output=True, timeout=30,
        )
        if completed.returncode != 0:
            return FALLBACK_DURATION
        text = (completed.stdout or b"").decode("utf-8", errors="ignore").strip()
        return float(text) if text else FALLBACK_DURATION
    except (OSError, ValueError, subprocess.SubprocessError):
        return FALLBACK_DURATION


def probe_dimensions(media_path: str) -> tuple:
    """
    以 ffprobe 取得影片畫面尺寸 (寬, 高)；失敗時回傳 (1920, 1080) 保底值。
    """
    fallback = (1920, 1080)
    if not ffprobe_available():
        return fallback
    try:
        completed = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=s=x:p=0",
                media_path,
            ],
            capture_output=True, timeout=30,
        )
        if completed.returncode != 0:
            return fallback
        text = (completed.stdout or b"").decode("utf-8", errors="ignore").strip()
        width, height = text.split("x")[:2]
        width, height = int(width), int(height)
        if width > 0 and height > 0:
            return (width, height)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return fallback
