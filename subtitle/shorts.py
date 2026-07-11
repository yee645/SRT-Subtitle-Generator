# -*- coding: utf-8 -*-
"""
Shorts 直式短片輸出模組（9:16）。

把橫式素材的精彩段落重新構圖成直式短片，是 YouTuber 發 Shorts／
Reels／TikTok 前最繁瑣的重剪工作。本模組以 ffmpeg 一鍵完成：

- **裁切版式（crop）**：以可調的水平焦點（0=最左、0.5=置中、1=最右）
  裁出 9:16 畫面，適合人物固定在畫面某側的素材。
- **模糊背景版式（blur）**：完整畫面置中、上下以放大模糊的原畫面填滿，
  不損失任何內容，適合畫面資訊多的素材。

可選擇把該段字幕一併燒錄（沿用字幕視覺樣式，時間軸自動平移），
以及輸出時做響度正規化。輸出解析度預設 1080x1920。
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from typing import Callable, Optional

from .audio import build_loudnorm_filter
from .burner import _escape_subtitle_path, _stream_progress, ffmpeg_available
from .exporter import cues_to_ass
from .media import probe_dimensions

logger = logging.getLogger(__name__)

# 預設輸出解析度（YouTube Shorts / Reels / TikTok 通用直式規格）。
DEFAULT_RESOLUTION = (1080, 1920)

# Shorts 輸出設定的預設值（與 config 的 shorts 區段對應）。
DEFAULT_SETTINGS = {
    "mode": "crop",           # crop＝裁切；blur＝模糊背景填滿
    "focus_x": 0.5,           # 裁切版式的水平焦點：0 最左、0.5 置中、1 最右
    "burn_subtitles": True,   # 是否把該段字幕燒錄進短片
    "loudnorm": False,        # 是否同時做響度正規化
}


def resolve_shorts_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出 Shorts 輸出設定，缺漏以預設補齊並夾限。"""
    raw = dict(DEFAULT_SETTINGS)
    if config:
        raw.update({k: v for k, v in config.get("shorts", {}).items()
                    if v is not None})
    mode = str(raw.get("mode") or "crop").lower()
    try:
        focus = float(raw.get("focus_x", 0.5))
    except (TypeError, ValueError):
        focus = 0.5
    return {
        "mode": mode if mode in ("crop", "blur") else "crop",
        "focus_x": max(0.0, min(focus, 1.0)),
        "burn_subtitles": bool(raw.get("burn_subtitles", True)),
        "loudnorm": bool(raw.get("loudnorm", False)),
    }


def shift_cues(cues, clip_start: float, clip_end: float) -> list:
    """
    取出落在片段時間範圍內的字幕，並把時間軸平移為從 0 開始。

    與片段部分重疊的字幕會被裁齊到片段邊界。
    """
    shifted = []
    duration = clip_end - clip_start
    for cue in cues or []:
        if cue["end"] <= clip_start or cue["start"] >= clip_end:
            continue
        start = max(cue["start"] - clip_start, 0.0)
        end = min(cue["end"] - clip_start, duration)
        if end - start < 0.05:
            continue
        shifted.append({"start": start, "end": end, "text": cue["text"]})
    return shifted


def _crop_params(src_w: int, src_h: int, out_w: int, out_h: int,
                 focus_x: float) -> tuple:
    """計算裁切版式的 crop 參數 (寬, 高, x, y)。"""
    target_aspect = out_w / out_h
    crop_w = min(src_w, round(src_h * target_aspect))
    if crop_w < src_w:
        # 來源較寬（一般橫式素材）：垂直吃滿、水平依焦點取景。
        crop_h = src_h
        x = round((src_w - crop_w) * focus_x)
        y = 0
    else:
        # 來源比目標更窄長：水平吃滿、垂直置中。
        crop_w = src_w
        crop_h = min(src_h, round(src_w / target_aspect))
        x = 0
        y = round((src_h - crop_h) / 2)
    return crop_w, crop_h, x, y


def cut_vertical_clip(
    video_path: str,
    start: float,
    end: float,
    output_path: str,
    mode: str = "crop",
    focus_x: float = 0.5,
    style: Optional[dict] = None,
    cues: Optional[list] = None,
    resolution: tuple = DEFAULT_RESOLUTION,
    loudnorm_target: Optional[float] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    把素材的一個時間段輸出成 9:16 直式短片。

    參數：
        video_path: 來源影片。
        start / end: 片段起訖秒數（來源影片的絕對時間）。
        output_path: 輸出檔路徑（建議 .mp4）。
        mode: "crop" 裁切、"blur" 模糊背景填滿。
        focus_x: 裁切版式的水平焦點（0~1）。
        style: 字幕視覺樣式；cues 提供時用於燒錄。
        cues: 該片段的字幕（來源影片絕對時間，內部自動平移裁齊）。
        resolution: 輸出解析度，預設 (1080, 1920)。
        loudnorm_target: 設定時同步做響度正規化（單階段動態模式）。
        progress_cb: (ratio, message) 進度回呼。
    回傳：輸出檔路徑。
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    duration = end - start
    if duration <= 0.1:
        raise ValueError("片段長度過短，無法輸出短片。")

    out_w, out_h = resolution
    clip_cues = shift_cues(cues, start, end) if cues else []

    temp_subtitle = None
    try:
        # 字幕暫存檔（時間已平移），放輸出目錄避免 ffmpeg 路徑解析問題。
        subtitle_filter = ""
        if clip_cues:
            out_dir = os.path.dirname(os.path.abspath(output_path)) or os.getcwd()
            fd, temp_subtitle = tempfile.mkstemp(suffix=".ass", dir=out_dir)
            os.close(fd)
            with open(temp_subtitle, "w", encoding="utf-8") as fp:
                fp.write(cues_to_ass(clip_cues, style,
                                     resolution=(out_w, out_h)))
            subtitle_filter = f",ass='{_escape_subtitle_path(temp_subtitle)}'"

        if mode == "blur":
            # 模糊背景版式：完整畫面置中、放大模糊的原畫面墊底。
            video_filter = (
                f"[0:v]split=2[bgsrc][fgsrc];"
                f"[bgsrc]scale={out_w}:{out_h}:force_original_aspect_ratio="
                f"increase,crop={out_w}:{out_h},boxblur=20:5[bg];"
                f"[fgsrc]scale={out_w}:{out_h}:force_original_aspect_ratio="
                f"decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
                f"{subtitle_filter}[vout]")
            filter_args = ["-filter_complex", video_filter,
                           "-map", "[vout]", "-map", "0:a?"]
        else:
            src_w, src_h = probe_dimensions(video_path)
            crop_w, crop_h, x, y = _crop_params(
                src_w, src_h, out_w, out_h, max(0.0, min(focus_x, 1.0)))
            video_filter = (f"crop={crop_w}:{crop_h}:{x}:{y},"
                            f"scale={out_w}:{out_h}{subtitle_filter}")
            filter_args = ["-vf", video_filter]

        audio_args = ["-c:a", "aac", "-b:a", "192k"]
        if loudnorm_target is not None:
            audio_args = ["-af", build_loudnorm_filter(None, loudnorm_target),
                          "-c:a", "aac", "-b:a", "192k"]

        if progress_cb:
            progress_cb(0.0, f"輸出直式短片（{duration:.1f} 秒）...")
        command = (
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
             "-i", video_path]
            + filter_args
            + ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]
            + audio_args
            + ["-progress", "pipe:1", output_path]
        )
        logger.debug("Shorts ffmpeg 命令：%s", command)
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
            raise RuntimeError(f"短片輸出失敗：{stderr[-400:]}")
    finally:
        if temp_subtitle and os.path.exists(temp_subtitle):
            try:
                os.unlink(temp_subtitle)
            except OSError:
                pass

    if progress_cb:
        progress_cb(1.0, "短片輸出完成")
    return output_path
