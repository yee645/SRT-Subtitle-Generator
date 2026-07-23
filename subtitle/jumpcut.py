# -*- coding: utf-8 -*-
"""
全片停頓自動跳剪（Jump Cut）：一次剪掉整支影片的停頓，字幕同步對齊。

調研顯示「剪掉停頓、把初剪跳剪掉」是創作者公認最花時間、最想自動化
的步驟（中英文社群一致：「剪輯師花一半時間在剪停頓」「AI 該處理你
討厭的重複工作：剪掉停頓、轉錄、輸出短影音」）。本工具已有的
「一鍵去頭尾」（v1.17.0）只處理開頭結尾廢秒，口頭禪剪除只去掉特定
字詞，中段每一句換氣、思考停頓仍要手剪。

本模組直接利用「已經生成好的字幕 cue 時間軸」找出句與句之間過長的
停頓，一次跳剪整支影片（video＋audio 一起裁掉，兩側各保留緩衝秒數
避免斷得突兀），並同步把字幕時間軸重新對齊到剪完後的新時間——這是
坊間跳剪工具很少做到的地方（多半剪完影片、字幕就對不上了）。

零 GUI 依賴，供 GUI 對話框與 CLI 共用；免額外一次 ffmpeg 掃描，
直接複用轉錄／匯入既有字幕已經算好的時間軸。
"""

from __future__ import annotations

import os
import subprocess
from typing import Callable, Optional

from .burner import _stream_progress, ffmpeg_available
from .media import has_audio_stream, has_video_stream, probe_duration

# 使用者可調參數（config["jumpcut"]）。
DEFAULT_JUMPCUT = {
    "min_gap": 1.2,        # 句間停頓達此秒數才視為可跳剪的「冷場」
    "pad": 0.15,           # 剪點兩側各保留的緩衝秒數（避免斷得突兀）
    "max_cut_ratio": 0.6,  # 跳剪總長度超過影片長度此比例時中止（防誤判）
}
_MIN_GAP_RANGE = (0.5, 5.0)
_PAD_RANGE = (0.0, 1.0)
_MAX_CUT_RATIO_RANGE = (0.1, 0.9)

# ffmpeg filter_complex 分段數上限：段數過多代表門檻設太低（幾乎每句都被
# 判定為可剪），命令會過於龐大且多半是誤判，改請使用者調高門檻。
MAX_SEGMENTS = 200


def _clamp(value, low, high, fallback):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_jumpcut_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出跳剪參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_JUMPCUT)
    if config:
        raw.update({k: v for k, v in config.get("jumpcut", {}).items()
                    if v is not None})
    return {
        "min_gap": _clamp(raw.get("min_gap"), *_MIN_GAP_RANGE,
                          DEFAULT_JUMPCUT["min_gap"]),
        "pad": _clamp(raw.get("pad"), *_PAD_RANGE, DEFAULT_JUMPCUT["pad"]),
        "max_cut_ratio": _clamp(
            raw.get("max_cut_ratio"), *_MAX_CUT_RATIO_RANGE,
            DEFAULT_JUMPCUT["max_cut_ratio"]),
    }


def find_cut_gaps(cues: list, min_gap: float) -> list:
    """依字幕 cue 時間軸找出句間過長停頓，回傳 [(停頓開始, 停頓結束), ...]。"""
    if not cues or len(cues) < 2:
        return []
    ordered = sorted(cues, key=lambda cue: cue["start"])
    gaps = []
    for prev, nxt in zip(ordered, ordered[1:]):
        gap_start, gap_end = prev["end"], nxt["start"]
        if gap_end - gap_start >= min_gap:
            gaps.append((gap_start, gap_end))
    return gaps


def compute_keep_segments(duration: float, cut_gaps: list,
                          pad: float) -> tuple:
    """
    把「要跳剪的停頓區間」轉成「要保留的影片片段」清單。

    每段停頓兩側各留 pad 秒緩衝（剪掉的是停頓「中段」，避免斷得突兀）；
    緩衝後已無可剪空間的停頓視為不夠格，維持原樣不剪。

    回傳 (keep_segments, cut_count)：cut_count 為實際套用的跳剪次數。
    """
    keep = []
    cursor = 0.0
    cut_count = 0
    for gap_start, gap_end in cut_gaps:
        cut_start = gap_start + pad
        cut_end = gap_end - pad
        if cut_end <= cut_start or cut_start <= cursor:
            continue
        keep.append((cursor, cut_start))
        cursor = cut_end
        cut_count += 1
    if cursor < duration:
        keep.append((cursor, duration))
    return keep, cut_count


def _build_breakpoints(keep_segments: list) -> list:
    """(原始開始, 原始結束, 剪後新開始) 三元組，供時間軸重新對映。"""
    breakpoints = []
    new_cursor = 0.0
    for start, end in keep_segments:
        breakpoints.append((start, end, new_cursor))
        new_cursor += end - start
    return breakpoints


def _remap_time(t: float, breakpoints: list) -> float:
    if not breakpoints:
        return t
    for orig_start, orig_end, new_start in breakpoints:
        if orig_start - 1e-6 <= t <= orig_end + 1e-6:
            return new_start + max(0.0, min(t, orig_end) - orig_start)
    # 理論上字幕時間點不會落在被剪掉的停頓區間內（停頓本就無字幕）；
    # 萬一發生（例如來源字幕檔本身時間軸有誤），對齊到最近的保留片段。
    if t < breakpoints[0][0]:
        return breakpoints[0][2]
    last_start, last_end, last_new_start = breakpoints[-1]
    return last_new_start + (last_end - last_start)


def remap_cues(cues: list, keep_segments: list) -> list:
    """把字幕 cue 的時間軸重新對映到跳剪後的新時間軸（文字內容不變）。"""
    breakpoints = _build_breakpoints(keep_segments)
    new_cues = []
    for cue in cues:
        new_cue = dict(cue)
        new_cue["start"] = round(_remap_time(cue["start"], breakpoints), 3)
        new_cue["end"] = round(_remap_time(cue["end"], breakpoints), 3)
        if new_cue["end"] > new_cue["start"]:
            new_cues.append(new_cue)
    return new_cues


def _build_filter_complex(keep_segments: list, has_video: bool,
                          has_audio: bool) -> tuple:
    """組出 trim+concat 的 filter_complex，回傳 (filter_complex, map 參數清單)。"""
    parts = []
    concat_inputs = []
    for index, (start, end) in enumerate(keep_segments):
        if has_video:
            parts.append(
                f"[0:v]trim=start={start:.3f}:end={end:.3f},"
                f"setpts=PTS-STARTPTS[v{index}];")
            concat_inputs.append(f"[v{index}]")
        if has_audio:
            parts.append(
                f"[0:a]atrim=start={start:.3f}:end={end:.3f},"
                f"asetpts=PTS-STARTPTS[a{index}];")
            concat_inputs.append(f"[a{index}]")
    n_streams = int(has_video) + int(has_audio)
    parts.append(
        f"{''.join(concat_inputs)}concat=n={len(keep_segments)}:"
        f"v={int(has_video)}:a={int(has_audio)}"
        f"{'[vout][aout]' if n_streams == 2 else ('[vout]' if has_video else '[aout]')}")
    maps = []
    if has_video:
        maps += ["-map", "[vout]"]
    if has_audio:
        maps += ["-map", "[aout]"]
    return "".join(parts), maps


def suggest_output_path(input_path: str) -> str:
    """建議輸出路徑：來源檔名加「_跳剪」後綴。"""
    base, ext = os.path.splitext(input_path)
    return f"{base}_跳剪{ext or '.mp4'}"


def apply_jumpcut(
    media_path: str,
    cues: list,
    output_path: str,
    settings: Optional[dict] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> dict:
    """
    對影片跑跳剪：偵測句間停頓 → 裁掉 → 輸出新影片，並回傳重新對齊的字幕。

    回傳：{"output": 輸出路徑, "cues": 對齊後的新 cue 清單,
          "cut_count": 實際剪掉的停頓數, "removed_seconds": 省下的秒數,
          "kept_seconds": 剪後長度, "original_seconds": 原始長度}
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    if not os.path.exists(media_path):
        raise FileNotFoundError(f"找不到檔案：{media_path}")
    settings = settings or resolve_jumpcut_settings()
    duration = probe_duration(media_path)

    cut_gaps = find_cut_gaps(cues, settings["min_gap"])
    if not cut_gaps:
        raise ValueError(
            "未偵測到可跳剪的停頓片段（可調低「最短停頓秒數」門檻再試，"
            "或影片本身節奏已經很緊湊）。")

    keep_segments, cut_count = compute_keep_segments(
        duration, cut_gaps, settings["pad"])
    if not keep_segments:
        raise ValueError("跳剪後沒有可保留的片段，請調整門檻設定。")
    if cut_count == 0:
        raise ValueError(
            "偵測到的停頓緩衝後皆不夠格跳剪（可調低「緩衝秒數」或降低"
            "「最短停頓秒數」門檻再試）。")
    if len(keep_segments) > MAX_SEGMENTS:
        raise ValueError(
            f"偵測到的停頓片段過多（{len(keep_segments)} 段，可能是門檻設"
            "太低導致誤判），請調高「最短停頓秒數」後再試。")

    kept_seconds = sum(end - start for start, end in keep_segments)
    removed_seconds = duration - kept_seconds
    if duration > 0 and removed_seconds / duration > settings["max_cut_ratio"]:
        raise ValueError(
            f"偵測到的停頓總長達 {removed_seconds:.1f} 秒（超過影片長度的 "
            f"{settings['max_cut_ratio'] * 100:.0f}%，可能是誤判），已停止"
            "跳剪；請提高「最短停頓秒數」門檻後再試。")

    has_video = has_video_stream(media_path)
    has_audio = has_audio_stream(media_path)
    if not has_video and not has_audio:
        raise ValueError("此檔案沒有影像也沒有音訊軌，無法跳剪。")

    filter_complex, maps = _build_filter_complex(
        keep_segments, has_video, has_audio)
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", media_path,
        "-filter_complex", filter_complex,
        *maps,
    ]
    if has_video:
        command += ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]
    if has_audio:
        command += ["-c:a", "aac", "-b:a", "192k"]
    command += ["-progress", "pipe:1", output_path]

    if progress_cb:
        progress_cb(0.02, f"正在跳剪 {len(cut_gaps)} 處停頓...")
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="ignore",
        )
    except OSError as exc:
        raise RuntimeError(f"無法啟動 ffmpeg：{exc}") from exc
    _stream_progress(process, kept_seconds, progress_cb, label="跳剪")
    ret = process.wait()
    if ret != 0:
        stderr = (process.stderr.read() if process.stderr else "") or ""
        raise RuntimeError(f"影片跳剪失敗：{stderr[-400:]}")
    if progress_cb:
        progress_cb(1.0, "跳剪完成")

    new_cues = remap_cues(cues, keep_segments)
    return {
        "output": output_path,
        "cues": new_cues,
        "cut_count": cut_count,
        "removed_seconds": round(removed_seconds, 2),
        "kept_seconds": round(kept_seconds, 2),
        "original_seconds": round(duration, 2),
    }


def _format_seconds(value: float) -> str:
    minutes, seconds = divmod(max(value, 0.0), 60)
    return f"{int(minutes)}:{seconds:04.1f}" if minutes else f"{seconds:.1f} 秒"


def format_jumpcut_report(result: dict) -> str:
    """把跳剪結果排成一行人類可讀摘要。"""
    return (
        f"共跳剪 {result['cut_count']} 處停頓，省下 "
        f"{_format_seconds(result['removed_seconds'])}"
        f"（原長度 {_format_seconds(result['original_seconds'])} → "
        f"剪後 {_format_seconds(result['kept_seconds'])}）。")
