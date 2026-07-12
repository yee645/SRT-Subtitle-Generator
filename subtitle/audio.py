# -*- coding: utf-8 -*-
"""
音訊處理模組：響度正規化與背景音樂自動閃避（ducking）。

## 響度正規化（YouTube -14 LUFS 標準）

YouTube 對超過約 -14 LUFS 的音訊會自動調小，但**太小聲的不會調大**——
音量偏低的影片在平台上會一直小聲，觀眾體驗差。以 ffmpeg 的 loudnorm
濾鏡做兩階段正規化：先量測實際響度數據，再以線性模式精準校正到目標值。
目標響度可調（預設 -14 LUFS）；供燒錄字幕與 Shorts 直式輸出流程掛用。

## 背景音樂自動閃避

幫影片配上背景音樂時，音樂蓋過講話聲是常見問題；手動逐段拉關鍵字曲線
調音量非常花時間，各家剪輯軟體（Premiere、Filmora、DaVinci Resolve）
2026 年都已內建自動閃避功能。本模組以 ffmpeg 的 sidechaincompress
濾鏡達成同等效果：偵測到人聲時自動壓低音樂音量，安靜時音樂恢復正常，
全程不需手動關鍵影格。
"""

from __future__ import annotations

import json
import logging
import os
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


# ---------------------------------------------------------------------------
# 背景音樂自動閃避（audio ducking）
# ---------------------------------------------------------------------------

# 三個使用者可調的強度旋鈕，皆有合理範圍與預設值。
DEFAULT_DUCKING = {
    "music_volume": 0.35,      # 背景音樂基礎音量（混音前，不受閃避影響時的音量）
    "duck_strength": 8.0,      # 閃避強度：講話時音樂被壓低的程度，越高壓得越低
    "duck_sensitivity": 0.06,  # 閃避靈敏度：越低，越輕的講話音量就會觸發閃避
}
_MUSIC_VOLUME_RANGE = (0.05, 1.0)
_DUCK_STRENGTH_RANGE = (1.0, 20.0)
_DUCK_SENSITIVITY_RANGE = (0.01, 0.5)
# 閃避的反應與回復速度（毫秒），固定為業界常用值，不開放調整以控制複雜度。
_DUCK_ATTACK_MS = 5
_DUCK_RELEASE_MS = 300


def _clamp_float(value, low: float, high: float, fallback: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_ducking_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出背景音樂閃避參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_DUCKING)
    if config:
        raw.update({k: v for k, v in config.get("ducking", {}).items()
                   if v is not None})
    low, high = _MUSIC_VOLUME_RANGE
    music_volume = _clamp_float(raw.get("music_volume"), low, high,
                                DEFAULT_DUCKING["music_volume"])
    low, high = _DUCK_STRENGTH_RANGE
    duck_strength = _clamp_float(raw.get("duck_strength"), low, high,
                                 DEFAULT_DUCKING["duck_strength"])
    low, high = _DUCK_SENSITIVITY_RANGE
    duck_sensitivity = _clamp_float(raw.get("duck_sensitivity"), low, high,
                                    DEFAULT_DUCKING["duck_sensitivity"])
    return {
        "music_volume": music_volume,
        "duck_strength": duck_strength,
        "duck_sensitivity": duck_sensitivity,
    }


def build_ducking_filter_complex(settings: dict) -> str:
    """
    組出背景音樂閃避的 ffmpeg filter_complex 字串。

    輸入慣例：[0:a] 為原始影片音軌（人聲），[1:a] 為背景音樂。
    流程：音樂先套基礎音量，再以人聲為側鏈訊號做 sidechaincompress
    （講話時自動壓低音樂），最後與原始人聲混音成單一輸出 [aout]。
    """
    return (
        f"[1:a]volume={settings['music_volume']:.3f}[bgvol];"
        f"[bgvol][0:a]sidechaincompress=threshold="
        f"{settings['duck_sensitivity']:.3f}:ratio="
        f"{settings['duck_strength']:.2f}:attack={_DUCK_ATTACK_MS}:"
        f"release={_DUCK_RELEASE_MS}:makeup=1[bgduck];"
        f"[0:a][bgduck]amix=inputs=2:duration=first:"
        f"dropout_transition=0:weights=1 1[aout]"
    )


def _ducking_command(video_path: str, music_path: str, filter_complex: str,
                     duration: float, output_path: str) -> list:
    """
    組出背景音樂混音的 ffmpeg 命令。

    音樂輸入加 -stream_loop -1 無限循環，避免素材較短的音樂中途消失；
    輸出以 -t 明確裁到影片長度（amix 的 duration=first 依賴串流結尾
    偵測，循環輸入下不可靠，故以顯式時長為準，兩者雙重保險）。
    """
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", video_path,
        "-stream_loop", "-1", "-i", music_path,
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{duration:.3f}",
        "-progress", "pipe:1",
        output_path,
    ]


def mix_background_music(
    video_path: str,
    music_path: str,
    output_path: str,
    settings: Optional[dict] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    把背景音樂混進影片，講話時自動閃避（壓低音樂音量）。

    參數：
        video_path: 來源影片（保留原有人聲音軌與畫面）。
        music_path: 背景音樂檔（比影片短時自動循環播放）。
        output_path: 輸出影片路徑。
        settings: resolve_ducking_settings() 的結果；省略則用預設值。
        progress_cb: (ratio, message) 進度回呼。
    回傳：輸出檔路徑。
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"找不到來源影片：{video_path}")
    if not os.path.exists(music_path):
        raise FileNotFoundError(f"找不到背景音樂檔：{music_path}")

    settings = settings or resolve_ducking_settings()
    duration = probe_duration(video_path)
    filter_complex = build_ducking_filter_complex(settings)
    command = _ducking_command(
        video_path, music_path, filter_complex, duration, output_path)

    if progress_cb:
        progress_cb(0.0, "正在混音背景音樂（自動閃避人聲段落）...")
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
        raise RuntimeError(f"背景音樂混音失敗：{stderr[-400:]}")
    if progress_cb:
        progress_cb(1.0, "背景音樂混音完成")
    return output_path
