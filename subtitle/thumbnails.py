# -*- coding: utf-8 -*-
"""
縮圖候選擷取模組：從素材自動挑出適合當影片封面的畫面。

創作者選封面時得在剪輯軟體或播放器裡來回拖時間軸，肉眼找一格
「清晰、明亮、有表情」的畫面，再截圖存檔——既繁瑣又常抓到動態模糊的格。
本模組利用審片分析既有的精彩分數鎖定取樣範圍，再以 ffmpeg 對每個範圍
取樣多格，用 sobel 邊緣能量（值越高畫面越清晰、細節越多；動態模糊與
黑畫面都會得低分）挑出最好的一格，輸出 YouTube 封面尺寸的 PNG 候選圖。

純 ffmpeg 濾鏡實作（sobel + signalstats），不需任何機器學習模型；
未做審片分析時退化為整片均勻取樣，一樣可用。
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Callable, Optional

from .burner import ffmpeg_available
from .review import TAG_HIGHLIGHT

# 使用者可調的擷取參數（GUI 可調並記憶於 config.json 的 "thumbnails"）。
DEFAULT_THUMBNAILS = {
    "count": 6,                 # 候選張數
    "min_spacing": 8.0,         # 候選之間的最小時間間隔（秒），避免抓到同一幕
    "prefer_highlights": True,  # 優先從精彩段落取樣（需先跑審片分析）
    "width": 1280,              # 輸出圖片寬度（YouTube 封面標準 1280）
}
_COUNT_RANGE = (2, 12)
_SPACING_RANGE = (1.0, 120.0)
_WIDTH_RANGE = (640, 1920)

# 取樣細節：每個窗口最長取 12 秒、窗口內每秒取樣 2 格。
# 一支 10 分鐘素材以預設 6 張候選計，僅需解碼約 72 秒畫面，資源負擔小。
_WINDOW_SECONDS = 12.0
_SAMPLE_FPS = 2.0
# 評分時把畫面縮到 320 寬再算邊緣能量：結果排序不變，速度快數倍。
_SCORE_WIDTH = 320

# ffmpeg metadata=mode=print 的輸出行（stderr）。
_PTS_RE = re.compile(r"pts_time:\s*([0-9]+(?:\.[0-9]+)?)")
_YAVG_RE = re.compile(r"lavfi\.signalstats\.YAVG=([0-9.eE+\-]+)")


def _clamp(value, low, high, fallback):
    try:
        value = type(fallback)(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_thumbnail_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出縮圖擷取參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_THUMBNAILS)
    if config:
        raw.update({k: v for k, v in config.get("thumbnails", {}).items()
                    if v is not None})
    return {
        "count": _clamp(raw.get("count"), *_COUNT_RANGE,
                        DEFAULT_THUMBNAILS["count"]),
        "min_spacing": _clamp(raw.get("min_spacing"), *_SPACING_RANGE,
                              DEFAULT_THUMBNAILS["min_spacing"]),
        "prefer_highlights": bool(raw.get("prefer_highlights", True)),
        "width": _clamp(raw.get("width"), *_WIDTH_RANGE,
                        DEFAULT_THUMBNAILS["width"]),
    }


# 間隔比較的浮點容差：均勻取樣的間距與 effective_spacing 可能只差
# 10^-15 級的浮點誤差，不加容差會被誤判為「太近」而剔除。
_SPACING_TOLERANCE = 1e-6


def effective_spacing(duration: float, count: int, spacing: float) -> float:
    """
    短素材時自動縮小候選間隔，確保要求的張數湊得滿。

    固定間隔（預設 8 秒）在短素材上會讓候選數湊不滿（例如 20 秒素材
    要 6 張，均勻取樣的間距只有約 2.9 秒，全被固定間隔剔除）；
    取「設定值」與「素材長度均分」的較小者，並保留 0.5 秒下限
    避免全擠在同一格。長素材不受影響（均分值大於設定值）。
    """
    if duration <= 0 or count <= 0:
        return spacing
    return max(min(spacing, duration / (count + 1)), 0.5)


def sample_windows(items, duration: float, settings: dict) -> list:
    """
    決定要取樣的時間窗口，回傳 [(start, end), ...]（依優先序排列）。

    有審片結果時：精彩段落（分數高者優先）→ 其餘保留段落；
    窗口不足（段落太少或未分析）時以整片均勻取樣補齊。
    窗口中心點彼此至少相隔 effective_spacing() 秒（短素材自動縮小），
    避免候選集中在同一幕。
    """
    count = settings["count"]
    spacing = effective_spacing(duration, count, settings["min_spacing"])
    speech = [i for i in (items or [])
              if i.get("kind") == "speech" and i.get("keep", True)]
    if settings["prefer_highlights"]:
        highlights = [i for i in speech if TAG_HIGHLIGHT in i.get("tags", ())]
        others = [i for i in speech if TAG_HIGHLIGHT not in i.get("tags", ())]
        pool = (sorted(highlights, key=lambda i: -i.get("score", 0.0))
                + sorted(others, key=lambda i: -i.get("score", 0.0)))
    else:
        pool = sorted(speech, key=lambda i: -i.get("score", 0.0))

    windows = []
    centers = []
    for item in pool:
        if len(windows) >= count:
            break
        mid = (item["start"] + item["end"]) / 2.0
        if any(abs(mid - c) < spacing - _SPACING_TOLERANCE
               for c in centers):
            continue
        half = min(_WINDOW_SECONDS, item["end"] - item["start"]) / 2.0
        start = max(item["start"], mid - half)
        end = min(item["end"], mid + half)
        if end - start < 0.2:
            continue
        windows.append((start, end))
        centers.append(mid)

    if len(windows) < count and duration > 0:
        need = count - len(windows)
        step = duration / (need + 1)
        for k in range(1, need + 1):
            mid = step * k
            if any(abs(mid - c) < spacing - _SPACING_TOLERANCE
                   for c in centers):
                continue
            start = max(0.0, mid - _WINDOW_SECONDS / 2.0)
            end = min(duration, mid + _WINDOW_SECONDS / 2.0)
            if end - start < 0.2:
                continue
            windows.append((start, end))
            centers.append(mid)
    return windows


def parse_frame_scores(text: str) -> list:
    """
    解析 ffmpeg metadata=mode=print 的輸出，回傳 [(pts_time, 清晰度分數), ...]。

    輸出格式為兩行一組：frame 行帶 pts_time、下一行帶
    lavfi.signalstats.YAVG（sobel 後的平均亮度＝平均邊緣強度）。
    """
    scores = []
    pts = None
    for line in (text or "").splitlines():
        match = _PTS_RE.search(line)
        if match:
            pts = float(match.group(1))
            continue
        match = _YAVG_RE.search(line)
        if match and pts is not None:
            try:
                scores.append((pts, float(match.group(1))))
            except ValueError:
                pass
            pts = None
    return scores


def _score_command(media_path: str, start: float, duration: float) -> list:
    """組出單一窗口的取樣評分命令：sobel 邊緣能量以 metadata 印出。"""
    return [
        "ffmpeg", "-hide_banner", "-nostats",
        "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
        "-i", media_path,
        "-an",
        "-vf",
        (f"fps={_SAMPLE_FPS},scale={_SCORE_WIDTH}:-2,format=gray,"
         "sobel,signalstats,metadata=mode=print"),
        "-f", "null", "-",
    ]


def score_window(media_path: str, start: float, end: float,
                 timeout: int = 180) -> list:
    """
    對一個時間窗口取樣評分，回傳 [(絕對秒數, 清晰度分數), ...]。

    ffmpeg 不可用或執行失敗時回傳空清單，由呼叫端退回窗口中點。
    """
    duration = max(end - start, 0.1)
    try:
        completed = subprocess.run(
            _score_command(media_path, start, duration),
            capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return []
    stderr = (completed.stderr or b"").decode("utf-8", errors="ignore")
    return [(start + pts, score)
            for pts, score in parse_frame_scores(stderr)]


def pick_frames(window_scores: list, count: int, min_spacing: float) -> list:
    """
    從各窗口的取樣分數挑出最終候選，回傳 [(秒數, 分數), ...]（分數高在前）。

    window_scores 依窗口優先序排列（[[(t, s), ...], ...]）；每個窗口取
    分數最高、且與已選候選相隔至少 min_spacing 秒的一格。
    """
    picks = []
    for scores in window_scores:
        if len(picks) >= count:
            break
        for time, score in sorted(scores, key=lambda p: -p[1]):
            if all(abs(time - t) >= min_spacing - _SPACING_TOLERANCE
                   for t, _ in picks):
                picks.append((time, score))
                break
    if len(picks) < count:
        # 短素材上窗口高度重疊，某些窗口的所有取樣格都可能與已選候選
        # 太近而整窗空手；改用全體取樣格（分數高→低）候補回填，
        # 仍維持間隔限制，確保張數盡量湊滿。
        pooled = sorted((p for scores in window_scores for p in scores),
                        key=lambda p: -p[1])
        for time, score in pooled:
            if len(picks) >= count:
                break
            if all(abs(time - t) >= min_spacing - _SPACING_TOLERANCE
                   for t, _ in picks):
                picks.append((time, score))
    picks.sort(key=lambda p: -p[1])
    return picks[:count]


def extract_frame(media_path: str, timestamp: float, output_path: str,
                  width: int = 1280, timeout: int = 120) -> str:
    """把指定秒數的畫面存成 PNG（等比縮放到指定寬度，不放大小圖）。"""
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{timestamp:.3f}",
        "-i", media_path,
        "-frames:v", "1",
        "-vf", f"scale=min({int(width)}\\,iw):-2",
        output_path,
    ]
    try:
        completed = subprocess.run(command, capture_output=True,
                                   timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"畫面擷取失敗：{exc}") from exc
    if completed.returncode != 0 or not os.path.exists(output_path):
        stderr = (completed.stderr or b"").decode("utf-8", errors="ignore")
        raise RuntimeError(f"畫面擷取失敗：{stderr[-300:]}")
    return output_path


def generate_thumbnails(
    media_path: str,
    items,
    duration: float,
    output_paths: Callable[[int], str],
    settings: Optional[dict] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> list:
    """
    產生封面候選圖，回傳 [{"path", "time", "score"}, ...]（分數高在前）。

    參數：
        media_path: 來源影片。
        items: 審片分析結果（analyze() 的段落清單）；可為 None 或空
               （此時整片均勻取樣）。
        duration: 素材總長（秒）。
        output_paths: 依候選序號（1 起算）回傳輸出路徑的函式，
                      由呼叫端決定命名與避免覆蓋。
        settings: resolve_thumbnail_settings() 的結果；省略則用預設值。
        progress_cb: (ratio, message) 進度回呼。
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    settings = settings or resolve_thumbnail_settings()
    windows = sample_windows(items, duration, settings)
    if not windows:
        raise RuntimeError("素材長度不足，無法取樣封面候選。")

    window_scores = []
    for index, (start, end) in enumerate(windows, start=1):
        if progress_cb:
            progress_cb((index - 1) / (len(windows) + 1),
                        f"正在評分候選畫面（{index}/{len(windows)}）...")
        scores = score_window(media_path, start, end)
        if not scores:
            # 評分失敗（極短窗口、解碼問題）時退回窗口中點，仍給出候選。
            scores = [((start + end) / 2.0, 0.0)]
        window_scores.append(scores)

    picks = pick_frames(window_scores, settings["count"],
                        effective_spacing(duration, settings["count"],
                                          settings["min_spacing"]))
    results = []
    for rank, (time, score) in enumerate(picks, start=1):
        if progress_cb:
            progress_cb((len(windows) + rank / max(len(picks), 1))
                        / (len(windows) + 1),
                        f"正在輸出候選圖（{rank}/{len(picks)}）...")
        path = output_paths(rank)
        extract_frame(media_path, time, path, settings["width"])
        results.append({"path": path, "time": time, "score": score})
    if progress_cb:
        progress_cb(1.0, f"封面候選輸出完成，共 {len(results)} 張。")
    return results
