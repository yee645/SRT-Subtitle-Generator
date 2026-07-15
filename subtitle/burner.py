# -*- coding: utf-8 -*-
"""
影片字幕燒錄模組（hardsub via ffmpeg）。

呼叫系統 ffmpeg 將 SRT/ASS 字幕直接「燒進」影片畫面，輸出新的 MP4 檔。
過程中以解析 ffmpeg 的 progress 輸出推送 0.0~1.0 的進度比例給呼叫端。

需求：系統已安裝 ffmpeg 並可於 PATH 取得（與本程式既有要求一致）。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from typing import Callable, Optional

from .exporter import cues_to_ass, cues_to_srt

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]

# ffmpeg `-progress pipe:1` 會輸出 key=value 行，out_time_ms 為已處理的微秒。
_PROGRESS_RE = re.compile(r"^([a-zA-Z_]+)=(.+)$")
# ffprobe 偵測時長失敗時使用的保底值（避免除以零；最終仍以 ffmpeg 實際進度為準）。
_FALLBACK_DURATION = 60.0


def ffmpeg_available() -> bool:
    """檢查系統是否有可用的 ffmpeg。"""
    return shutil.which("ffmpeg") is not None


def ffprobe_available() -> bool:
    """檢查系統是否有可用的 ffprobe。"""
    return shutil.which("ffprobe") is not None


def probe_duration(video_path: str) -> float:
    """以 ffprobe 取得影片時長（秒），失敗時回傳保底值。"""
    if not ffprobe_available():
        return _FALLBACK_DURATION
    try:
        completed = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path,
            ],
            capture_output=True, timeout=30,
        )
        if completed.returncode != 0:
            return _FALLBACK_DURATION
        text = (completed.stdout or b"").decode("utf-8", errors="ignore").strip()
        return float(text) if text else _FALLBACK_DURATION
    except (OSError, ValueError, subprocess.SubprocessError):
        return _FALLBACK_DURATION


def _escape_subtitle_path(path: str) -> str:
    """
    為 ffmpeg subtitles 濾鏡轉義路徑。

    Windows 上需把反斜線換成正斜線、冒號逸出，否則濾鏡會把路徑當成參數分隔。
    """
    text = path.replace("\\", "/")
    # 冒號（碟符號）需以反斜線逸出，等號與單引號亦如是。
    text = text.replace(":", "\\:")
    return text


def burn_subtitles(
    video_path: str,
    cues: list,
    output_path: str,
    style: Optional[dict] = None,
    progress_cb: Optional[ProgressCallback] = None,
    use_ass: bool = True,
    loudnorm_target: Optional[float] = None,
) -> str:
    """
    將字幕燒錄進影片。

    參數：
        video_path: 來源影片檔。
        cues: 字幕 cue 清單。
        output_path: 輸出影片路徑（建議 .mp4）。
        style: 字幕視覺樣式（含字型/顏色/位置）；use_ass 為真時生效。
        progress_cb: (ratio, message) 進度回呼，ratio 為 0.0~1.0。
        use_ass: True 用 ASS 帶樣式燒錄；False 用 SRT 由 ffmpeg 預設樣式繪製。
        loudnorm_target: 設定時同步做響度正規化到該 LUFS 值
            （先量測再線性校正；量測失敗自動退回動態模式）。
    回傳：輸出檔路徑。
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"找不到來源影片：{video_path}")
    if not cues:
        raise ValueError("沒有可燒錄的字幕內容。")

    suffix = ".ass" if use_ass else ".srt"
    content = cues_to_ass(cues, style) if use_ass else cues_to_srt(cues)

    duration = probe_duration(video_path)
    temp_subtitle: Optional[str] = None
    try:
        # 字幕暫存檔放在輸出檔同目錄，避免 ffmpeg 路徑解析失敗。
        out_dir = os.path.dirname(os.path.abspath(output_path)) or os.getcwd()
        fd, temp_subtitle = tempfile.mkstemp(suffix=suffix, dir=out_dir)
        os.close(fd)
        with open(temp_subtitle, "w", encoding="utf-8") as fp:
            fp.write(content)

        subtitle_arg = _escape_subtitle_path(temp_subtitle)
        if use_ass:
            video_filter = f"ass='{subtitle_arg}'"
        else:
            video_filter = f"subtitles='{subtitle_arg}'"

        # 音訊：預設原樣複製；要求響度正規化時改為量測後校正並重編碼。
        audio_args = ["-c:a", "copy"]
        if loudnorm_target is not None:
            # 延遲匯入避免與 audio 模組互相依賴。
            from .audio import build_loudnorm_filter, measure_loudness
            if progress_cb:
                progress_cb(0.0, "正在量測音訊響度...")
            measured = measure_loudness(video_path)
            audio_args = ["-af", build_loudnorm_filter(measured, loudnorm_target),
                          "-c:a", "aac", "-b:a", "192k"]

        if progress_cb:
            progress_cb(0.0, "啟動 ffmpeg 燒錄程序...")

        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", video_path,
            "-vf", video_filter,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            *audio_args,
            "-progress", "pipe:1",
            output_path,
        ]
        logger.debug("ffmpeg 命令：%s", command)

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
            raise RuntimeError(f"ffmpeg 燒錄失敗：{stderr[-400:]}")

        if progress_cb:
            progress_cb(1.0, "字幕燒錄完成")
    finally:
        if temp_subtitle and os.path.exists(temp_subtitle):
            try:
                os.unlink(temp_subtitle)
            except OSError:
                pass
    return output_path


def _stream_progress(process: subprocess.Popen, duration: float,
                     progress_cb: Optional[ProgressCallback],
                     label: str = "燒錄") -> None:
    """從 ffmpeg 的 stdout 解析 progress 並轉成 0~1 比例回報。"""
    if not progress_cb or not process.stdout:
        return
    duration = max(duration, 0.1)
    last_ratio = 0.0
    for raw in process.stdout:
        line = raw.strip()
        match = _PROGRESS_RE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        if key == "out_time_ms":
            try:
                processed_us = int(value)
            except ValueError:
                continue
            processed_seconds = processed_us / 1_000_000.0
            ratio = min(processed_seconds / duration, 0.999)
            if ratio > last_ratio + 0.005:
                last_ratio = ratio
                progress_cb(ratio,
                            f"{label}中 {int(ratio * 100)}%（已處理 "
                            f"{processed_seconds:.1f}s / {duration:.1f}s）")
        elif key == "progress" and value == "end":
            progress_cb(1.0, f"{label}完成")
            return
