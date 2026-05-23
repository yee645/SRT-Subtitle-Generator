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
