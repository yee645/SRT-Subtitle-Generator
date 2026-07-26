# -*- coding: utf-8 -*-
"""
分段音量一致性分析與一鍵修復：抓出「忽大忽小」的段落並拉平。

調研（中英文皆搜）：素材來自不同時段、不同麥克風距離、不同錄製環境時，
「各段落音量忽大忽小」是剪輯時的常見痛點——Premiere 的 Essential Sound
自動音量匹配、剪映的「響度統一」都是針對這個問題的專門功能。本工具
已有的響度正規化（v1.5.0）與音訊健檢（v1.11.0）都只看「整支影片」的
單一整體響度，從未檢查過同一支影片「內部各段落彼此是否一致」。

本模組把影片切成固定長度的分段，逐段量測響度（LUFS），標出與整體
中位數響度差異過大的段落；一鍵修復時只對這些段落套用音量增益拉近到
中位數，其餘段落原樣不動——不是整支影片重新正規化一次，而是「抓出
落差、只調整落差」，保留原始素材本身的動態表現。

實測發現：ffmpeg 的 loudnorm 濾鏡與 -ss/-t 輸入時間範圍限制搭配使用時
量測結果不準確（不論輸入或輸出端 seek 皆同），因此改為每段先擷取成
暫存 wav 檔（純音訊、單聲道，擷取快速，不需重新編碼影像），再對擷取
出的獨立檔案呼叫既有的 measure_loudness()，量測結果才正確可靠。

零 GUI 依賴，供 GUI 對話框與 CLI 共用。
"""

from __future__ import annotations

import os
import statistics
import subprocess
import tempfile
from typing import Callable, Optional

from .audio import measure_loudness
from .burner import _stream_progress, ffmpeg_available
from .media import has_audio_stream, has_video_stream, probe_duration

# 使用者可調參數（config["volumeconsistency"]）。
DEFAULT_VOLUME_CONSISTENCY = {
    "segment_seconds": 20.0,  # 分段長度（秒），每段獨立量測響度
    "deviation_lu": 3.0,      # 與整體中位數響度相差超過此值（LU）標記為不一致
}
_SEGMENT_RANGE = (10.0, 60.0)
_DEVIATION_RANGE = (1.5, 8.0)

# 分段長度低於此秒數時併入前一段，避免量測樣本太短不準確。
_MIN_SEGMENT_SECONDS = 6.0
# 響度低於此值（LUFS）視為近乎靜音，不列入中位數計算與差異比對
# （避免真正的冷場段落被誤判為「音量落差」，修復時反而放大底噪）。
_SILENCE_GATE_LUFS = -70.0
# 分段數上限：避免長片段搭配過小的分段秒數導致量測次數過多。
MAX_SEGMENTS = 60


def _clamp(value, low, high, fallback):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_volume_consistency_settings(
        config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出音量一致性參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_VOLUME_CONSISTENCY)
    if config:
        raw.update({k: v for k, v in config.get(
            "volumeconsistency", {}).items() if v is not None})
    return {
        "segment_seconds": _clamp(
            raw.get("segment_seconds"), *_SEGMENT_RANGE,
            DEFAULT_VOLUME_CONSISTENCY["segment_seconds"]),
        "deviation_lu": _clamp(
            raw.get("deviation_lu"), *_DEVIATION_RANGE,
            DEFAULT_VOLUME_CONSISTENCY["deviation_lu"]),
    }


def build_segments(duration: float, segment_seconds: float) -> list:
    """把 [0, duration] 切成固定長度的分段；最後一段太短時併入前一段。"""
    if duration <= 0:
        return []
    segments = []
    start = 0.0
    while start < duration - 1e-6:
        end = min(start + segment_seconds, duration)
        segments.append((start, end))
        start = end
    if (len(segments) >= 2
            and segments[-1][1] - segments[-1][0] < _MIN_SEGMENT_SECONDS):
        last = segments.pop()
        prev = segments.pop()
        segments.append((prev[0], last[1]))
    return segments


def _extract_segment_wav(media_path: str, start: float, end: float,
                         tmp_dir: str) -> Optional[str]:
    """
    擷取單一分段為暫存 wav 檔（純音訊、單聲道）供響度量測使用。

    loudnorm 濾鏡搭配 -ss/-t 時間範圍限制量測不準確（已實測確認），
    改為先擷取成獨立檔案再量測整個檔案，量測結果才正確。
    失敗時回傳 None。
    """
    out_path = os.path.join(tmp_dir, f"seg_{start:.3f}_{end:.3f}.wav")
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
        "-i", media_path,
        "-vn", "-ar", "44100", "-ac", "1",
        out_path,
    ]
    try:
        completed = subprocess.run(command, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0 or not os.path.exists(out_path):
        return None
    return out_path


def analyze_volume_consistency(
    media_path: str,
    settings: Optional[dict] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> dict:
    """
    把影片切成固定長度分段，逐段量測響度，找出與整體中位數落差過大的段落。

    回傳：{"segments": [{"start","end","lufs"}, ...]（lufs 可能為 None
          代表量測失敗），"median_lufs": 整體中位數響度或 None（樣本不足時）,
          "issues": [{"start","end","lufs","diff"}, ...]}
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    if not os.path.exists(media_path):
        raise FileNotFoundError(f"找不到檔案：{media_path}")
    if not has_audio_stream(media_path):
        raise ValueError("此檔案沒有音訊軌，無法分析音量一致性。")
    settings = settings or resolve_volume_consistency_settings()
    duration = probe_duration(media_path)
    segments = build_segments(duration, settings["segment_seconds"])
    if len(segments) > MAX_SEGMENTS:
        raise ValueError(
            f"分段數過多（{len(segments)} 段，可能是影片過長或分段秒數"
            "設太短），請調大「分段秒數」後再試。")
    if len(segments) < 2:
        return {"segments": [], "median_lufs": None, "issues": []}

    measured = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        for index, (start, end) in enumerate(segments):
            if progress_cb:
                progress_cb(
                    index / len(segments),
                    f"正在量測第 {index + 1}/{len(segments)} 段響度...")
            wav_path = _extract_segment_wav(media_path, start, end, tmp_dir)
            lufs = None
            if wav_path:
                data = measure_loudness(wav_path)
                if data:
                    try:
                        lufs = float(data["input_i"])
                    except (KeyError, ValueError, TypeError):
                        lufs = None
            measured.append({"start": start, "end": end, "lufs": lufs})

    valid_lufs = [m["lufs"] for m in measured
                 if m["lufs"] is not None and m["lufs"] > _SILENCE_GATE_LUFS]
    if len(valid_lufs) < 2:
        if progress_cb:
            progress_cb(1.0, "音量一致性分析完成")
        return {"segments": measured, "median_lufs": None, "issues": []}

    median_lufs = statistics.median(valid_lufs)
    issues = []
    for m in measured:
        if m["lufs"] is None or m["lufs"] <= _SILENCE_GATE_LUFS:
            continue
        diff = m["lufs"] - median_lufs
        if abs(diff) > settings["deviation_lu"]:
            issues.append({
                "start": m["start"], "end": m["end"], "lufs": m["lufs"],
                "diff": round(diff, 2),
            })
    if progress_cb:
        progress_cb(1.0, "音量一致性分析完成")
    return {
        "segments": measured,
        "median_lufs": round(median_lufs, 2),
        "issues": issues,
    }


def format_volume_consistency_report(result: dict) -> str:
    """把分析結果排成人類可讀的文字報告（GUI 顯示與 CLI 輸出共用）。"""
    segments = result.get("segments") or []
    issues = result.get("issues") or []
    median_lufs = result.get("median_lufs")
    if not segments:
        return "素材過短，不足以切成兩段以上比較音量一致性。"
    if median_lufs is None:
        return "素材音量近乎全靜音，無法分析音量一致性。"
    if not issues:
        return (f"共 {len(segments)} 段，音量一致（整體中位數 "
                f"{median_lufs:.1f} LUFS），未發現明顯落差。")
    lines = [f"共 {len(segments)} 段，整體中位數響度 {median_lufs:.1f} LUFS，"
             f"發現 {len(issues)} 段音量落差過大："]
    for issue in issues:
        direction = "偏小聲" if issue["diff"] < 0 else "偏大聲"
        lines.append(
            f"  {issue['start']:.1f}s ~ {issue['end']:.1f}s："
            f"{issue['lufs']:.1f} LUFS（{direction} "
            f"{abs(issue['diff']):.1f} LU）")
    return "\n".join(lines)


def suggest_output_path(input_path: str) -> str:
    """建議輸出路徑：來源檔名加「_音量平衡」後綴。"""
    base, ext = os.path.splitext(input_path)
    return f"{base}_音量平衡{ext or '.mp4'}"


def fix_volume_consistency(
    media_path: str,
    result: dict,
    output_path: str,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    對落差過大的分段套用音量增益拉近到整體中位數響度，其餘分段原樣不動；
    影像串流原樣複製（若有），僅音軌重新編碼。

    參數：
        result: analyze_volume_consistency() 的回傳值。
    回傳：輸出檔案路徑。
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    if not os.path.exists(media_path):
        raise FileNotFoundError(f"找不到檔案：{media_path}")
    issues = result.get("issues") or []
    segments = result.get("segments") or []
    median_lufs = result.get("median_lufs")
    if not issues:
        raise ValueError("沒有偵測到音量落差過大的分段，無需修復。")
    if median_lufs is None or not segments:
        raise ValueError("沒有可用的整體響度基準，無法修復。")

    duration = probe_duration(media_path)
    has_video = has_video_stream(media_path)
    gain_by_span = {(i["start"], i["end"]): median_lufs - i["lufs"]
                   for i in issues}

    parts = []
    audio_labels = []
    for index, seg in enumerate(segments):
        gain = gain_by_span.get((seg["start"], seg["end"]))
        filt = f"volume={gain:.2f}dB" if gain else "anull"
        parts.append(
            f"[0:a]atrim=start={seg['start']:.3f}:end={seg['end']:.3f},"
            f"asetpts=PTS-STARTPTS,{filt}[a{index}];")
        audio_labels.append(f"[a{index}]")
    parts.append(
        f"{''.join(audio_labels)}concat=n={len(segments)}:v=0:a=1[aout]")
    filter_complex = "".join(parts)

    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", media_path,
        "-filter_complex", filter_complex,
        "-map", "[aout]",
    ]
    if has_video:
        command += ["-map", "0:v", "-c:v", "copy"]
    command += [
        "-c:a", "aac", "-b:a", "192k",
        "-progress", "pipe:1", output_path,
    ]

    if progress_cb:
        progress_cb(0.02, f"正在調整 {len(issues)} 段音量...")
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="ignore",
        )
    except OSError as exc:
        raise RuntimeError(f"無法啟動 ffmpeg：{exc}") from exc
    _stream_progress(process, duration, progress_cb, label="音量調整")
    ret = process.wait()
    if ret != 0:
        stderr = (process.stderr.read() if process.stderr else "") or ""
        raise RuntimeError(f"影片音量調整失敗：{stderr[-400:]}")
    if progress_cb:
        progress_cb(1.0, "音量調整完成")
    return output_path
