# -*- coding: utf-8 -*-
"""
音訊一鍵修復：降噪、去低頻隆隆、響度正規化，畫面原樣複製。

音訊健檢（v1.11）能診斷「底噪偏高」「太小聲」，但修法只能指向
剪輯軟體或線上工具——調研顯示創作者為了去背噪，得把整支影片上傳到
第三方網站處理。本模組把修復收進程式內，以 ffmpeg 一次完成：

- 降噪：afftdn（FFT 頻譜降噪），對冷氣聲、電流聲、嘶聲等穩態底噪
  有效，強度可調（過強會讓人聲發悶，預設取保守值）
- 去低頻隆隆：highpass 高通濾波，切掉桌面震動、風切、空調的低頻
  （人聲基頻在 85Hz 以上，預設 80Hz 不傷人聲）
- 響度正規化：重用既有 loudnorm 兩階段流程，同步校正到 YouTube 標準

影像串流原樣複製、僅音軌重新編碼，畫質不受影響；純音訊檔也可修。
零 GUI 依賴，供健檢視窗與 CLI 共用。
"""

from __future__ import annotations

import os
import subprocess
from typing import Callable, Optional

from .audio import (DEFAULT_TARGET_LUFS, build_loudnorm_filter,
                    measure_loudness)
from .burner import _stream_progress, ffmpeg_available
from .media import ffprobe_available, has_audio_stream, probe_duration

# 使用者可調參數（config["audiofix"]）。
DEFAULT_AUDIOFIX = {
    "denoise": True,            # FFT 頻譜降噪
    "denoise_strength": 12.0,   # 降噪量（dB）：越高越乾淨、過高人聲發悶
    "highpass": True,           # 高通濾波去低頻隆隆
    "highpass_hz": 80.0,        # 高通截止頻率（Hz）
    "loudnorm": False,          # 同步做響度正規化（目標沿用自動化輸出設定）
}
_STRENGTH_RANGE = (6.0, 40.0)
_HIGHPASS_RANGE = (40.0, 200.0)


def _clamp(value, low, high, fallback):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_audiofix_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出音訊修復參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_AUDIOFIX)
    if config:
        raw.update({k: v for k, v in config.get("audiofix", {}).items()
                    if v is not None})
    return {
        "denoise": bool(raw.get("denoise", True)),
        "denoise_strength": _clamp(
            raw.get("denoise_strength"), *_STRENGTH_RANGE,
            DEFAULT_AUDIOFIX["denoise_strength"]),
        "highpass": bool(raw.get("highpass", True)),
        "highpass_hz": _clamp(raw.get("highpass_hz"), *_HIGHPASS_RANGE,
                              DEFAULT_AUDIOFIX["highpass_hz"]),
        "loudnorm": bool(raw.get("loudnorm", False)),
    }


def build_audiofix_filter(settings: dict, measured: Optional[dict] = None,
                          target_lufs: float = DEFAULT_TARGET_LUFS) -> str:
    """
    組出修復用的音訊濾鏡鏈；全部關閉時回傳空字串（由呼叫端擋下）。

    順序：先高通（把低頻隆隆切掉，降噪就不用處理它們）→ 降噪 →
    最後響度正規化（以「修好之後」的音訊量響度才準）。
    """
    parts = []
    if settings.get("highpass"):
        parts.append(f"highpass=f={settings['highpass_hz']:.0f}")
    if settings.get("denoise"):
        parts.append(f"afftdn=nr={settings['denoise_strength']:.0f}")
    if settings.get("loudnorm"):
        parts.append(build_loudnorm_filter(measured, target_lufs))
    return ",".join(parts)


def has_video_stream(media_path: str) -> bool:
    """檢查媒體檔是否含影像串流（純音訊檔輸出改走 .m4a）。"""
    if not ffprobe_available():
        # 無 ffprobe 時保守假設有影像（-map 0:v? 容忍實際沒有）。
        return True
    try:
        completed = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0",
                media_path,
            ],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return bool((completed.stdout or b"").decode(
        "utf-8", errors="ignore").strip())


def suggest_output_path(input_path: str) -> str:
    """建議輸出路徑：影片保留原副檔名、純音訊改 .m4a（AAC 容器）。"""
    base, ext = os.path.splitext(input_path)
    if has_video_stream(input_path):
        return f"{base}_修復{ext or '.mp4'}"
    return f"{base}_修復.m4a"


def _fix_command(input_path: str, output_path: str, audio_filter: str,
                 has_video: bool) -> list:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-i", input_path]
    if has_video:
        # -map 0:v? 容忍「以為有、實際沒有」影像的邊界情況。
        command += ["-map", "0:v?", "-map", "0:a", "-c:v", "copy"]
    else:
        command += ["-vn"]
    command += [
        "-af", audio_filter,
        "-c:a", "aac", "-b:a", "192k",
        "-progress", "pipe:1",
        output_path,
    ]
    return command


def fix_audio(
    input_path: str,
    output_path: str,
    settings: Optional[dict] = None,
    target_lufs: float = DEFAULT_TARGET_LUFS,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    輸出音訊修復版：依設定套用降噪／高通／響度正規化。

    參數：
        input_path: 來源影音檔。
        output_path: 輸出路徑（可用 suggest_output_path() 取建議值）。
        settings: resolve_audiofix_settings() 的結果；省略用預設值。
        target_lufs: 響度正規化目標（僅 loudnorm 開啟時使用）。
        progress_cb: (ratio, message) 進度回呼。
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"找不到檔案：{input_path}")
    settings = settings or resolve_audiofix_settings()

    measured = None
    if settings["loudnorm"]:
        if progress_cb:
            progress_cb(0.0, "正在量測音訊響度（修復前置作業）...")
        measured = measure_loudness(input_path)

    audio_filter = build_audiofix_filter(settings, measured, target_lufs)
    if not audio_filter:
        raise ValueError("請至少勾選一個修復項目（降噪、去低頻或響度正規化）。")
    if not has_audio_stream(input_path):
        raise ValueError("此檔案沒有音訊軌，無法進行音訊修復。")

    has_video = has_video_stream(input_path)
    duration = probe_duration(input_path)
    command = _fix_command(input_path, output_path, audio_filter, has_video)

    if progress_cb:
        progress_cb(0.05, "正在輸出修復版（畫面原樣複製、僅處理音軌）...")
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="ignore",
        )
    except OSError as exc:
        raise RuntimeError(f"無法啟動 ffmpeg：{exc}") from exc

    _stream_progress(process, duration, progress_cb, label="修復")
    ret = process.wait()
    if ret != 0:
        stderr = (process.stderr.read() if process.stderr else "") or ""
        raise RuntimeError(f"音訊修復失敗：{stderr[-400:]}")
    if progress_cb:
        progress_cb(1.0, "音訊修復完成")
    return output_path
