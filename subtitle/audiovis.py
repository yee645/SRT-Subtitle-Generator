# -*- coding: utf-8 -*-
"""
音訊轉視覺化影片模組：讓純音訊創作者也能用上整條字幕管線。

Podcast、廣播剪輯、純錄音訪談這類創作者手上常常只有音訊檔，但
YouTube 等平台的慣例是上傳「影片」——沒有畫面的音軌難以被演算法
推薦，也不符合大多數觀眾的觀看習慣。創作者因此得另外找線上工具或
剪輯軟體，把音訊隨便套一張封面圖生成影片才能上傳，多一道手續；本
工具原本也完全無法處理純音訊來源的「輸出影片」需求（燒錄字幕等
功能都假設來源已經是影片）。

本模組直接用 ffmpeg 內建的 showwaves／showspectrum 濾鏡，把音訊即時
轉成波形或頻譜視覺化影片：可選擇疊在自訂背景圖片（例如節目封面）
下緣的一條色帶上，或不指定背景圖時輸出純黑底的全畫面視覺化。轉出
的影片是一支正常的 mp4，可以直接接上本工具既有的轉錄、字幕燒錄、
翻譯等整條既有管線，等於讓純音訊創作者也能用上完整功能。

零 GUI 依賴，供對話框與 CLI 共用。
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Callable, Optional

from .burner import _stream_progress, ffmpeg_available
from .media import has_audio_stream, probe_duration

DEFAULT_AUDIOVIS = {
    "mode": "waveform",         # waveform（波形）或 spectrum（頻譜）
    "color": "#3fa9f5",         # 波形顏色（僅 waveform 模式生效）
    "width": 1920,
    "height": 1080,
    "background_image": "",     # 留空時輸出純黑底全畫面視覺化
}

_WIDTH_RANGE = (640, 3840)
_HEIGHT_RANGE = (360, 2160)
_MODES = ("waveform", "spectrum")
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# 有背景圖時，視覺化色帶佔整體畫面高度的比例（疊在下緣）。
_WAVE_BAND_RATIO = 0.28
_MIN_BAND_HEIGHT = 40


def _clamp_int(value, low, high, fallback):
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return fallback
    return max(low, min(parsed, high))


def resolve_audiovis_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出音訊視覺化設定，缺漏以預設補齊並夾限。"""
    raw = dict(DEFAULT_AUDIOVIS)
    if config:
        raw.update({k: v for k, v in config.get("audiovis", {}).items()
                    if v is not None})
    mode = str(raw.get("mode") or "waveform").lower()
    color = str(raw.get("color") or DEFAULT_AUDIOVIS["color"])
    if not _HEX_RE.match(color):
        color = DEFAULT_AUDIOVIS["color"]
    return {
        "mode": mode if mode in _MODES else "waveform",
        "color": color,
        "width": _clamp_int(raw.get("width"), *_WIDTH_RANGE,
                            DEFAULT_AUDIOVIS["width"]),
        "height": _clamp_int(raw.get("height"), *_HEIGHT_RANGE,
                             DEFAULT_AUDIOVIS["height"]),
        "background_image": str(
            raw.get("background_image", "") or "").strip(),
    }


def suggest_output_path(input_path: str) -> str:
    """建議輸出路徑：來源檔名加上「_視覺化影片」後綴，固定輸出 .mp4。"""
    base, _ext = os.path.splitext(input_path)
    return f"{base}_視覺化影片.mp4"


def _vis_filter(mode: str, size: str, color: str) -> str:
    if mode == "spectrum":
        return f"showspectrum=s={size}:mode=combined:slide=scroll"
    return f"showwaves=s={size}:mode=cline:colors={color}"


def render_audio_video(
    audio_path: str,
    output_path: str,
    settings: Optional[dict] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
    timeout: int = 1800,
) -> str:
    """
    把音訊檔轉成附波形／頻譜視覺化的影片，可選擇疊在背景圖片上。

    無背景圖時輸出純黑底全畫面視覺化；有背景圖時視覺化縮成下緣一條
    色帶疊加，背景圖裁切置中填滿整個畫面（比例不符時裁切而非變形）。
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"找不到音訊檔：{audio_path}")
    if not has_audio_stream(audio_path):
        raise ValueError("此檔案沒有音訊軌，無法轉換成視覺化影片。")

    settings = settings or resolve_audiovis_settings()
    width, height = settings["width"], settings["height"]
    bg_image = settings.get("background_image", "")
    if bg_image and not os.path.exists(bg_image):
        raise FileNotFoundError(f"找不到背景圖片：{bg_image}")

    duration = probe_duration(audio_path)
    inputs = ["-i", audio_path]
    if bg_image:
        band_h = max(int(height * _WAVE_BAND_RATIO), _MIN_BAND_HEIGHT)
        vis = _vis_filter(settings["mode"], f"{width}x{band_h}",
                          settings["color"])
        inputs += ["-loop", "1", "-i", bg_image]
        filter_complex = (
            f"[1:v]scale={width}:{height}:force_original_aspect_ratio="
            f"increase,crop={width}:{height},format=yuv420p[bgv];"
            f"[0:a]{vis},format=yuv420p[wave];"
            f"[bgv][wave]overlay=0:{height - band_h}:shortest=1[vout]")
    else:
        vis = _vis_filter(settings["mode"], f"{width}x{height}",
                          settings["color"])
        filter_complex = f"[0:a]{vis},format=yuv420p[vout]"

    command = (
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        + inputs
        + ["-filter_complex", filter_complex,
           "-map", "[vout]", "-map", "0:a",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-c:a", "aac", "-b:a", "192k",
           "-shortest",
           "-progress", "pipe:1", output_path]
    )
    if progress_cb:
        progress_cb(0.0, "正在產生視覺化影片...")
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="ignore",
        )
    except OSError as exc:
        raise RuntimeError(f"無法啟動 ffmpeg：{exc}") from exc
    _stream_progress(process, duration, progress_cb, label="轉換")
    try:
        ret = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        raise RuntimeError("音訊轉影片逾時，請確認檔案是否過長或已損毀。")
    if ret != 0:
        stderr = (process.stderr.read() if process.stderr else "") or ""
        raise RuntimeError(f"音訊轉影片失敗：{stderr[-400:]}")
    if progress_cb:
        progress_cb(1.0, "視覺化影片產生完成")
    return output_path
