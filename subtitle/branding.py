# -*- coding: utf-8 -*-
"""
品牌套版：片頭／片尾一鍵接續、浮水印（Logo）自動疊加。

調研顯示創作者最常抱怨「每支影片都要重複手動加一次片頭片尾、調一次
浮水印位置」——本模組把這兩件事收進設定檔一次設好，之後每支影片
一鍵套用即可，不必再進剪輯軟體重複同一套操作：

- 片頭／片尾接續：自動把設定好的片頭、片尾影片接到來源影片前後；
  尺寸／畫面更新率／音訊格式不一致時自動正規化（避免黑畫面、比例跑掉、
  或音訊格式不符無法接續），沒有音軌的片頭／片尾自動補靜音音軌。
- 浮水印（Logo）疊加：圖片以可調的位置、大小（相對主畫面寬度比例）、
  透明度疊加在畫面上，全片皆有效。

兩者可各自單獨使用，也可同時套用（合併成同一次 ffmpeg 執行，避免
重複編碼消耗資源）。有片頭／片尾時無法只複製串流（不同片段需重新
編碼才能接續），純浮水印疊加則維持音訊直接複製、只重新編碼畫面。

零 GUI 依賴，供品牌套版對話框與 CLI 共用。
"""

from __future__ import annotations

import os
import subprocess
from typing import Callable, Optional

from .burner import _stream_progress, ffmpeg_available
from .media import (has_audio_stream, probe_dimensions, probe_duration,
                    probe_fps)

DEFAULT_BRANDING = {
    "intro_path": "",
    "outro_path": "",
    "watermark_path": "",
    "watermark_position": "bottom_right",
    "watermark_opacity": 0.85,
    "watermark_scale": 0.15,
    "watermark_margin": 24,
}

_OPACITY_RANGE = (0.1, 1.0)
_SCALE_RANGE = (0.05, 0.5)
_MARGIN_RANGE = (0, 200)
_POSITIONS = ("top_left", "top_right", "bottom_left", "bottom_right", "center")
POSITION_LABELS = {
    "top_left": "左上", "top_right": "右上",
    "bottom_left": "左下", "bottom_right": "右下",
    "center": "置中",
}


def _clamp(value, low, high, fallback):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_branding_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出品牌套版參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_BRANDING)
    if config:
        raw.update({k: v for k, v in config.get("branding", {}).items()
                    if v is not None})
    position = raw.get("watermark_position", "bottom_right")
    if position not in _POSITIONS:
        position = "bottom_right"
    return {
        "intro_path": str(raw.get("intro_path", "") or "").strip(),
        "outro_path": str(raw.get("outro_path", "") or "").strip(),
        "watermark_path": str(raw.get("watermark_path", "") or "").strip(),
        "watermark_position": position,
        "watermark_opacity": _clamp(
            raw.get("watermark_opacity"), *_OPACITY_RANGE,
            DEFAULT_BRANDING["watermark_opacity"]),
        "watermark_scale": _clamp(
            raw.get("watermark_scale"), *_SCALE_RANGE,
            DEFAULT_BRANDING["watermark_scale"]),
        "watermark_margin": _clamp(
            raw.get("watermark_margin"), *_MARGIN_RANGE,
            DEFAULT_BRANDING["watermark_margin"]),
    }


def has_intro_or_outro(settings: dict) -> bool:
    return bool(settings.get("intro_path") or settings.get("outro_path"))


def has_watermark(settings: dict) -> bool:
    return bool(settings.get("watermark_path"))


def suggest_output_path(input_path: str) -> str:
    """建議輸出路徑：來源檔名加上「_套版」後綴，副檔名沿用來源。"""
    base, ext = os.path.splitext(input_path)
    return f"{base}_套版{ext or '.mp4'}"


def _overlay_position_expr(position: str, margin) -> tuple:
    """依位置代碼組出 ffmpeg overlay 濾鏡的 x/y 座標運算式。"""
    m = int(margin)
    x_map = {
        "top_left": f"{m}",
        "bottom_left": f"{m}",
        "top_right": f"main_w-overlay_w-{m}",
        "bottom_right": f"main_w-overlay_w-{m}",
        "center": "(main_w-overlay_w)/2",
    }
    y_map = {
        "top_left": f"{m}",
        "top_right": f"{m}",
        "bottom_left": f"main_h-overlay_h-{m}",
        "bottom_right": f"main_h-overlay_h-{m}",
        "center": "(main_h-overlay_h)/2",
    }
    return x_map[position], y_map[position]


def _check_assets(settings: dict) -> None:
    for label, key in (("片頭", "intro_path"), ("片尾", "outro_path"),
                       ("浮水印", "watermark_path")):
        path = settings.get(key)
        if path and not os.path.exists(path):
            raise FileNotFoundError(f"找不到{label}檔案：{path}")


def _normalize_segment_filter(input_index: int, seg_id: str, width: int,
                              height: int, fps: float) -> str:
    return (f"[{input_index}:v]scale={width}:{height}:"
            f"force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1,fps={fps:.3f}[v{seg_id}]")


def _build_command(input_path: str, output_path: str, settings: dict):
    """組出本次套版所需的 ffmpeg 指令與總時長（供進度換算）。回傳 (command, total_duration)。"""
    intro, outro, watermark = (settings["intro_path"], settings["outro_path"],
                               settings["watermark_path"])
    width, height = probe_dimensions(input_path)
    fps = probe_fps(input_path)

    segment_paths = []
    if intro:
        segment_paths.append(("intro", intro))
    segment_paths.append(("main", input_path))
    if outro:
        segment_paths.append(("outro", outro))

    path_inputs = [p for _, p in segment_paths]
    watermark_idx = None
    if watermark:
        watermark_idx = len(path_inputs)
        path_inputs.append(watermark)

    filters = []
    extra_inputs = []
    seg_labels = []
    total_duration = 0.0
    concat_needed = bool(intro or outro)

    for i, (seg_id, path) in enumerate(segment_paths):
        total_duration += probe_duration(path)
        if concat_needed:
            filters.append(_normalize_segment_filter(i, seg_id, width, height, fps))
            if has_audio_stream(path):
                filters.append(
                    f"[{i}:a]aformat=sample_rates=48000:"
                    f"channel_layouts=stereo[a{seg_id}]")
            else:
                seg_duration = probe_duration(path)
                silent_idx = len(path_inputs) + len(extra_inputs)
                extra_inputs.append(
                    ["-f", "lavfi", "-t", f"{seg_duration:.3f}",
                     "-i", "anullsrc=r=48000:cl=stereo"])
                filters.append(f"[{silent_idx}:a]anull[a{seg_id}]")
            seg_labels.append(seg_id)

    if concat_needed:
        concat_inputs = "".join(f"[v{s}][a{s}]" for s in seg_labels)
        filters.append(
            f"{concat_inputs}concat=n={len(seg_labels)}:v=1:a=1[ccv][cca]")
        video_label, audio_label = "ccv", "cca"
    else:
        video_label, audio_label = None, None

    if watermark:
        wm_width = max(int(width * settings["watermark_scale"]), 2)
        x_expr, y_expr = _overlay_position_expr(
            settings["watermark_position"], settings["watermark_margin"])
        base_video = f"[{video_label}]" if video_label else "[0:v]"
        filters.append(
            f"[{watermark_idx}:v]scale={wm_width}:-1,format=rgba,"
            f"colorchannelmixer=aa={settings['watermark_opacity']:.2f}[wm]")
        filters.append(f"{base_video}[wm]overlay={x_expr}:{y_expr}[outv]")
        video_label = "outv"

    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for path in path_inputs:
        command += ["-i", path]
    for extra in extra_inputs:
        command += extra
    command += ["-filter_complex", ";".join(filters)]
    command += ["-map", f"[{video_label}]" if video_label else "0:v"]
    if concat_needed:
        command += ["-map", f"[{audio_label}]", "-c:a", "aac", "-b:a", "192k"]
    else:
        command += ["-map", "0:a?", "-c:a", "copy"]
    command += ["-c:v", "libx264", "-preset", "medium", "-crf", "18",
               "-progress", "pipe:1", output_path]
    return command, total_duration


def apply_branding(
    input_path: str,
    output_path: str,
    settings: Optional[dict] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    輸出套版影片：依設定接續片頭／片尾、疊加浮水印，兩者可單獨或同時套用。

    參數：
        input_path: 來源影片。
        output_path: 輸出路徑（可用 suggest_output_path() 取建議值）。
        settings: resolve_branding_settings() 的結果；省略用預設值。
        progress_cb: (ratio, message) 進度回呼。
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"找不到檔案：{input_path}")
    settings = settings or resolve_branding_settings()
    if not (settings["intro_path"] or settings["outro_path"]
            or settings["watermark_path"]):
        raise ValueError("請至少設定片頭、片尾或浮水印其中一項。")
    _check_assets(settings)

    command, total_duration = _build_command(input_path, output_path, settings)

    if progress_cb:
        progress_cb(0.02, "正在套版（片頭／片尾／浮水印）...")
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="ignore",
        )
    except OSError as exc:
        raise RuntimeError(f"無法啟動 ffmpeg：{exc}") from exc

    _stream_progress(process, total_duration, progress_cb, label="套版")
    ret = process.wait()
    if ret != 0:
        stderr = (process.stderr.read() if process.stderr else "") or ""
        raise RuntimeError(f"品牌套版失敗：{stderr[-400:]}")
    if progress_cb:
        progress_cb(1.0, "品牌套版完成")
    return output_path
