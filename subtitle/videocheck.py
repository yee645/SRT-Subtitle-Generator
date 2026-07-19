# -*- coding: utf-8 -*-
"""
影片畫質健檢與一鍵去頭尾：上片前抓出「上傳後才發現」的畫質翻車點。

調研顯示創作者最常見的畫質悲劇是：以過低的位元率輸出，上傳後被
YouTube 重新壓縮成一片糊（YouTube 對每支影片都會再壓一次，來源
位元率不足時丟失的細節救不回來）；其次是開頭／結尾留著開機、
清喉嚨的無聲廢秒——開頭廢秒是留存率殺手，逐支手剪又很繁瑣。

本模組兩件事都免轉錄、純 ffmpeg／ffprobe：

- 影片健檢：解析度、畫面更新率、位元率（對照 YouTube 官方建議值，
  可調寬嚴倍率）、編碼格式，以及開頭／結尾的靜音與黑畫面廢秒偵測
- 一鍵去頭尾：依偵測結果（可手動微調）重新輸出修剪版

核心邏輯零 GUI 依賴，供健檢視窗與 CLI 共用。
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Callable, Optional

from .audiocheck import LEVEL_BAD, LEVEL_GOOD, LEVEL_WARN
from .burner import _stream_progress, ffmpeg_available
from .media import ffprobe_available, probe_duration

# 使用者可調參數（config["videocheck"]）。
DEFAULT_VIDEOCHECK = {
    "bitrate_margin": 1.0,     # 位元率門檻＝YouTube 建議值 × 此倍率
    "dead_air_db": -45.0,      # 視為「無聲」的音量門檻（dB）
    "head_max_seconds": 1.0,   # 開頭廢秒超過此長度即提醒修剪
    "tail_max_seconds": 1.5,   # 結尾廢秒超過此長度即提醒修剪
    "trim_pad": 0.25,          # 修剪時保留的緩衝秒數（避免切得太貼）
}
_MARGIN_RANGE = (0.5, 2.0)
_DEAD_AIR_DB_RANGE = (-70.0, -25.0)
_HEAD_MAX_RANGE = (0.3, 10.0)
_TAIL_MAX_RANGE = (0.3, 10.0)
_PAD_RANGE = (0.0, 2.0)

# YouTube 官方建議上傳位元率（SDR，Mbps）：(最小高度, 30fps 建議, 60fps 建議)。
# 高度取「至少達到」判定（1440 以上算 2K、2160 以上算 4K）。
_BITRATE_TABLE = (
    (2160, 35.0, 53.0),
    (1440, 16.0, 24.0),
    (1080, 8.0, 12.0),
    (720, 5.0, 7.5),
    (0, 2.5, 4.0),
)

# 常見標準畫面更新率；偏離任何一者過多時提醒（可能是可變更新率來源）。
_STANDARD_FPS = (23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0)

# 建議直接可上傳的視訊編碼；其餘（如 mpeg4、wmv）提醒重新輸出。
_GOOD_CODECS = {"h264", "hevc", "av1", "vp9", "prores"}

_BLACK_RE = re.compile(
    r"black_start:(\d+(?:\.\d+)?)\s+black_end:(\d+(?:\.\d+)?)")
_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(\d+(?:\.\d+)?)")


def _clamp_float(value, low, high, fallback):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_videocheck_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出影片健檢參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_VIDEOCHECK)
    if config:
        raw.update({k: v for k, v in config.get("videocheck", {}).items()
                    if v is not None})
    return {
        "bitrate_margin": _clamp_float(
            raw.get("bitrate_margin"), *_MARGIN_RANGE,
            DEFAULT_VIDEOCHECK["bitrate_margin"]),
        "dead_air_db": _clamp_float(
            raw.get("dead_air_db"), *_DEAD_AIR_DB_RANGE,
            DEFAULT_VIDEOCHECK["dead_air_db"]),
        "head_max_seconds": _clamp_float(
            raw.get("head_max_seconds"), *_HEAD_MAX_RANGE,
            DEFAULT_VIDEOCHECK["head_max_seconds"]),
        "tail_max_seconds": _clamp_float(
            raw.get("tail_max_seconds"), *_TAIL_MAX_RANGE,
            DEFAULT_VIDEOCHECK["tail_max_seconds"]),
        "trim_pad": _clamp_float(raw.get("trim_pad"), *_PAD_RANGE,
                                 DEFAULT_VIDEOCHECK["trim_pad"]),
    }


def recommended_bitrate_mbps(height: int, fps: float) -> float:
    """依解析度與更新率回傳 YouTube 官方建議上傳位元率（Mbps）。"""
    high_fps = fps >= 48.0
    for min_height, std, high in _BITRATE_TABLE:
        if height >= min_height:
            return high if high_fps else std
    return _BITRATE_TABLE[-1][1]


def probe_video_info(media_path: str) -> Optional[dict]:
    """讀出影片基本資訊；無 ffprobe 或無影像串流時回傳 None。"""
    if not ffprobe_available():
        return None
    try:
        completed = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries",
                "stream=width,height,avg_frame_rate,codec_name,pix_fmt",
                "-show_entries", "format=bit_rate,duration",
                "-of", "default=noprint_wrappers=1",
                media_path,
            ],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (completed.stdout or b"").decode("utf-8", errors="ignore")
    info = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            info[key.strip()] = value.strip()
    if "width" not in info or "height" not in info:
        return None
    try:
        width = int(info["width"])
        height = int(info["height"])
    except ValueError:
        return None
    fps = 0.0
    rate = info.get("avg_frame_rate", "0/1")
    if "/" in rate:
        num, _, den = rate.partition("/")
        try:
            fps = float(num) / float(den) if float(den) else 0.0
        except ValueError:
            fps = 0.0
    try:
        bitrate_mbps = float(info.get("bit_rate", 0)) / 1_000_000.0
    except ValueError:
        bitrate_mbps = 0.0
    return {
        "width": width,
        "height": height,
        "fps": fps,
        "codec": info.get("codec_name", ""),
        "pix_fmt": info.get("pix_fmt", ""),
        "bitrate_mbps": bitrate_mbps,
        "duration": float(info.get("duration", 0) or 0),
    }


# 兩段靜音／黑畫面間可忽略的最長空隙（秒）：小於此值視為同一段廢秒。
_BRIDGE_GAP = 0.35


def _bridge_spans(spans):
    """合併間隔小於 _BRIDGE_GAP 的相鄰區段（輸入需已依起點排序）。"""
    merged = []
    for span in spans:
        if merged and span[0] - merged[-1][1] <= _BRIDGE_GAP:
            merged[-1] = (merged[-1][0], max(merged[-1][1], span[1]))
        else:
            merged.append(tuple(span))
    return merged


def parse_dead_air(stderr: str, duration: float) -> dict:
    """
    解析 blackdetect＋silencedetect 的輸出，回傳頭尾廢秒資訊。

    head_silence／head_black：從 0 秒起算的連續無聲／黑畫面長度；
    tail_silence／tail_black：貼著結尾的連續無聲／黑畫面長度。
    """
    silences = []
    start = None
    for line in (stderr or "").splitlines():
        match = _SILENCE_START_RE.search(line)
        if match:
            start = float(match.group(1))
            continue
        match = _SILENCE_END_RE.search(line)
        if match and start is not None:
            silences.append((max(start, 0.0), float(match.group(1))))
            start = None
    if start is not None:  # 靜音一路延伸到檔案結尾（沒有 silence_end 行）。
        silences.append((max(start, 0.0), duration))
    blacks = [(float(m.group(1)), float(m.group(2)))
              for m in _BLACK_RE.finditer(stderr or "")]
    # 橋接短暫聲響：真實素材的廢秒中常夾著一瞬間的雜音（相機提示音、
    # 椅子聲，實測 Big Buck Bunny 素材曾出現 0.1 秒的斷點），兩段靜音
    # 之間的空隙夠短時視為同一段廢秒，避免嚴重低估開頭廢秒長度。
    silences = _bridge_spans(sorted(silences))
    blacks = _bridge_spans(sorted(blacks))

    def head_run(spans):
        return max((end for s, end in spans if s <= 0.1), default=0.0)

    def tail_run(spans):
        best = 0.0
        for s, end in spans:
            if duration and end >= duration - 0.1:
                best = max(best, duration - s)
        return best

    return {
        "head_silence": head_run(silences),
        "head_black": head_run(blacks),
        "tail_silence": tail_run(silences),
        "tail_black": tail_run(blacks),
    }


def detect_dead_air(media_path: str, settings: Optional[dict] = None,
                    timeout: int = 600) -> dict:
    """實際掃描頭尾廢秒（單次 ffmpeg 同時跑 blackdetect＋silencedetect）。"""
    settings = settings or resolve_videocheck_settings()
    duration = probe_duration(media_path)
    command = [
        "ffmpeg", "-hide_banner", "-nostats",
        "-i", media_path,
        "-vf", "blackdetect=d=0.3:pic_th=0.97",
        "-af", f"silencedetect=n={settings['dead_air_db']:.0f}dB:d=0.4",
        "-f", "null", "-",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return {"head_silence": 0.0, "head_black": 0.0,
                "tail_silence": 0.0, "tail_black": 0.0,
                "duration": duration}
    stderr = (completed.stderr or b"").decode("utf-8", errors="ignore")
    result = parse_dead_air(stderr, duration)
    result["duration"] = duration
    return result


def _finding(level, title, detail, advice=""):
    return {"level": level, "title": title, "detail": detail,
            "advice": advice}


def run_video_check(
    media_path: str,
    config: Optional[dict] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> dict:
    """
    對影片跑畫質健檢，回傳 {"findings": [...], "dead_air": {...},
    "info": {...}}；純音訊檔（無影像串流）回傳 findings 為空。
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    if not os.path.exists(media_path):
        raise FileNotFoundError(f"找不到檔案：{media_path}")
    settings = resolve_videocheck_settings(config)

    if progress_cb:
        progress_cb(0.05, "正在讀取影片規格...")
    info = probe_video_info(media_path)
    if info is None:
        return {"findings": [], "dead_air": None, "info": None}
    findings = []

    # 1. 解析度。
    width, height = info["width"], info["height"]
    portrait = height > width
    smaller = min(width, height)
    if smaller < 720:
        findings.append(_finding(
            LEVEL_WARN, "解析度",
            f"{width}x{height}（未達 720p）",
            "YouTube 會提供的最高畫質受來源解析度限制；建議以 1080p "
            "以上重新輸出（若來源素材本身就低，放大無益，可忽略）。"))
    else:
        note = "（直式，適合 Shorts）" if portrait else ""
        findings.append(_finding(
            LEVEL_GOOD, "解析度", f"{width}x{height}{note}"))

    # 2. 畫面更新率。
    fps = info["fps"]
    if fps <= 0:
        findings.append(_finding(
            LEVEL_WARN, "畫面更新率", "無法判讀",
            "來源可能是可變更新率（VFR，常見於手機／螢幕錄影），"
            "上傳前建議轉成固定更新率，避免影音不同步。"))
    elif min(abs(fps - std) for std in _STANDARD_FPS) > 0.5:
        findings.append(_finding(
            LEVEL_WARN, "畫面更新率",
            f"{fps:.2f} fps（非標準值）",
            "非標準更新率通常代表可變更新率（VFR）來源，YouTube 處理後"
            "可能造成影音不同步或卡頓；建議重新輸出為 30 或 60 fps。"))
    else:
        findings.append(_finding(LEVEL_GOOD, "畫面更新率", f"{fps:.2f} fps"))

    # 3. 位元率對照 YouTube 建議。
    recommended = recommended_bitrate_mbps(smaller if portrait else height,
                                           fps if fps > 0 else 30.0)
    threshold = recommended * settings["bitrate_margin"]
    bitrate = info["bitrate_mbps"]
    if bitrate <= 0:
        findings.append(_finding(
            LEVEL_WARN, "位元率", "無法判讀（容器未記錄）", ""))
    elif bitrate < threshold:
        findings.append(_finding(
            LEVEL_BAD, "位元率",
            f"{bitrate:.1f} Mbps，低於 YouTube 建議的 "
            f"{recommended:g} Mbps（此解析度／更新率）",
            "上傳後 YouTube 會再壓縮一次，來源位元率不足時畫面會明顯"
            "變糊（實務上常建議以建議值的 1.5 倍輸出留餘裕）；"
            "請提高輸出位元率後重新匯出。"))
    else:
        findings.append(_finding(
            LEVEL_GOOD, "位元率",
            f"{bitrate:.1f} Mbps（建議值 {recommended:g} Mbps）"))

    # 4. 編碼格式。
    codec = (info["codec"] or "").lower()
    if codec and codec not in _GOOD_CODECS:
        findings.append(_finding(
            LEVEL_WARN, "視訊編碼", codec,
            "建議使用 H.264（MP4 容器）上傳，相容性與處理速度最佳。"))
    else:
        findings.append(_finding(
            LEVEL_GOOD, "視訊編碼", codec or "未知"))

    # 5. 頭尾廢秒。
    if progress_cb:
        progress_cb(0.35, "正在掃描頭尾廢秒（靜音／黑畫面）...")
    dead_air = detect_dead_air(media_path, settings)
    head = max(dead_air["head_silence"], dead_air["head_black"])
    tail = max(dead_air["tail_silence"], dead_air["tail_black"])
    if head > settings["head_max_seconds"]:
        findings.append(_finding(
            LEVEL_WARN, "開頭廢秒",
            f"開頭約 {head:.1f} 秒無聲"
            + ("／黑畫面" if dead_air["head_black"] > 0.2 else ""),
            "開頭空白是留存率殺手（觀眾前幾秒就決定要不要走）；"
            "可用健檢視窗的「輸出修剪版」一鍵去掉。"))
    else:
        findings.append(_finding(LEVEL_GOOD, "開頭廢秒",
                                 f"{head:.1f} 秒，正常"))
    if tail > settings["tail_max_seconds"]:
        findings.append(_finding(
            LEVEL_WARN, "結尾廢秒",
            f"結尾約 {tail:.1f} 秒無聲"
            + ("／黑畫面" if dead_air["tail_black"] > 0.2 else ""),
            "結尾長時間空白會拉低平均觀看時長；可用下方「輸出修剪版」"
            "一鍵去掉。"))
    else:
        findings.append(_finding(LEVEL_GOOD, "結尾廢秒",
                                 f"{tail:.1f} 秒，正常"))

    if progress_cb:
        progress_cb(0.6, "影片畫質健檢完成。")
    return {"findings": findings, "dead_air": dead_air, "info": info}


def suggest_trim(dead_air: dict, settings: Optional[dict] = None) -> tuple:
    """
    依廢秒偵測結果建議 (去頭秒數, 去尾秒數)。

    以「無聲」為主要依據（開著鏡頭安靜等待的廢秒畫面通常不是黑的），
    各保留 trim_pad 秒緩衝避免切得太貼；未超過提醒門檻的不建議修剪。
    """
    settings = settings or resolve_videocheck_settings()
    if not dead_air:
        return (0.0, 0.0)
    pad = settings["trim_pad"]
    head = max(dead_air.get("head_silence", 0.0),
               dead_air.get("head_black", 0.0))
    tail = max(dead_air.get("tail_silence", 0.0),
               dead_air.get("tail_black", 0.0))
    head_cut = max(head - pad, 0.0) if head > settings["head_max_seconds"] \
        else 0.0
    tail_cut = max(tail - pad, 0.0) if tail > settings["tail_max_seconds"] \
        else 0.0
    return (round(head_cut, 2), round(tail_cut, 2))


def suggest_output_path(input_path: str) -> str:
    """建議修剪版輸出路徑：來源檔名加「_修剪」後綴。"""
    base, ext = os.path.splitext(input_path)
    return f"{base}_修剪{ext or '.mp4'}"


def trim_video(
    input_path: str,
    output_path: str,
    head_seconds: float = 0.0,
    tail_seconds: float = 0.0,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    輸出去頭尾修剪版：重新編碼確保剪點精準（串流複製只能切在關鍵格）。

    參數：
        head_seconds: 從開頭去掉的秒數。
        tail_seconds: 從結尾去掉的秒數。
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"找不到檔案：{input_path}")
    duration = probe_duration(input_path)
    head = max(float(head_seconds or 0.0), 0.0)
    tail = max(float(tail_seconds or 0.0), 0.0)
    kept = duration - head - tail
    if kept < 1.0:
        raise ValueError("修剪後長度不足 1 秒，請縮小去頭／去尾秒數。")

    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{head:.3f}",
        "-i", input_path,
        "-t", f"{kept:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-progress", "pipe:1",
        output_path,
    ]
    if progress_cb:
        progress_cb(0.02, "正在輸出修剪版...")
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="ignore",
        )
    except OSError as exc:
        raise RuntimeError(f"無法啟動 ffmpeg：{exc}") from exc
    _stream_progress(process, kept, progress_cb, label="修剪")
    ret = process.wait()
    if ret != 0:
        stderr = (process.stderr.read() if process.stderr else "") or ""
        raise RuntimeError(f"影片修剪失敗：{stderr[-400:]}")
    if progress_cb:
        progress_cb(1.0, "影片修剪完成")
    return output_path


def format_video_report(result: dict) -> str:
    """把影片健檢結果排成純文字段落（附加在音訊健檢報告之後）。"""
    findings = (result or {}).get("findings") or []
    if not findings:
        return ""
    from .audiocheck import _LEVEL_ICONS
    lines = ["===== 影片畫質健檢 ====="]
    for finding in findings:
        icon = _LEVEL_ICONS.get(finding["level"], "・")
        lines.append(f"{icon} {finding['title']}：{finding['detail']}")
        if finding.get("advice"):
            lines.append(f"    建議：{finding['advice']}")
    return "\n".join(lines)
