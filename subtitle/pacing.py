# -*- coding: utf-8 -*-
"""
剪輯節奏健檢：抓出「畫面太久沒有變化」的段落。

調研（中英文皆搜）指向同一個問題：**長時間維持單一畫面是留存殺手**。
英文資料稱之為「cognitive underload」——畫面沒有新東西可看可處理，
觀眾就走了；並給出可量化的基準：talking head 的常態節奏約**每 15~25 秒
一次畫面變化**，每隔 2~3 分鐘再安排一小段密集快切。中文資料的說法是
「都是維持靜態的片段會讓整個影片的可看性降低很多」「節奏忽快忽慢」。

本工具既有的畫面檢查沒有任何一項在看這件事：
- **凍結畫面偵測（v1.26.0）看的是「畫面完全靜止」**，而 talking head
  長鏡頭裡人是會動的——正好是它抓不到的情況，兩者關注的性質相反
- 畫質健檢看的是位元率／解析度／更新率／編碼，與節奏無關

實測一段「前 30 秒完全沒有剪接」的素材，既有健檢對那 30 秒沒有任何提示。

作法是用 ffmpeg 的 scene 分數找出畫面變化點（等同剪接點），把整支影片
切成一個個「鏡頭」，再看有沒有哪一個鏡頭長到會讓觀眾失去注意力。

**只報告不自動改**：要插 B-roll、推近鏡頭還是加圖卡，是創作決定，
而且本工具手上也沒有 B-roll 素材——與 v1.26.0／v1.28.0／v1.29.0／
v1.31.0／v1.32.0／v1.33.0 的保守設計一致。

零 GUI 依賴，供上片前健檢對話框與 CLI 共用。
"""

from __future__ import annotations

import re
import subprocess
from typing import Callable, Optional

from subtitle.burner import ffmpeg_available
from subtitle.media import probe_duration

# 使用者可調參數（config["pacing"]）。
DEFAULT_PACING = {
    # 畫面變化幅度達此值視為一次剪接（0~1，越小越敏感）。
    "scene_threshold": 0.30,
    # 單一畫面超過此秒數就提醒（業界建議 talking head 約 15~25 秒一刀）。
    "max_static_seconds": 25.0,
}

_THRESHOLD_RANGE = (0.05, 0.90)
_STATIC_RANGE = (5.0, 300.0)

LEVEL_GOOD = "good"
LEVEL_WARN = "warn"
LEVEL_BAD = "bad"
_LEVEL_ICONS = {LEVEL_GOOD: "✔", LEVEL_WARN: "⚠", LEVEL_BAD: "✘"}

# metadata=print 的輸出樣式：frame:0 pts:... pts_time:12.345
_PTS_TIME_RE = re.compile(r"pts_time:\s*([0-9]+(?:\.[0-9]+)?)")


def _clamp(value, low, high, fallback, cast=float):
    try:
        value = cast(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_pacing_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出剪輯節奏參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_PACING)
    if config:
        raw.update({k: v for k, v in config.get("pacing", {}).items()
                    if v is not None})
    return {
        "scene_threshold": _clamp(
            raw.get("scene_threshold"), *_THRESHOLD_RANGE,
            DEFAULT_PACING["scene_threshold"]),
        "max_static_seconds": _clamp(
            raw.get("max_static_seconds"), *_STATIC_RANGE,
            DEFAULT_PACING["max_static_seconds"]),
    }


def parse_scene_times(stderr: str) -> list:
    """從 ffmpeg 的 metadata=print 輸出解析出畫面變化的時間點（秒）。"""
    times = []
    for match in _PTS_TIME_RE.finditer(stderr or ""):
        try:
            value = float(match.group(1))
        except ValueError:
            continue
        if value >= 0:
            times.append(value)
    times.sort()
    return times


def detect_scene_changes(media_path: str, settings: Optional[dict] = None,
                         timeout: int = 900) -> list:
    """
    單次 ffmpeg 掃出畫面變化（剪接）的時間點清單。

    加 `-an` 完全不解碼音訊：本分析只看畫面，解音訊純屬浪費。
    720p30／60 秒的素材實測省下約三成 CPU（4.6 → 3.2 秒）。

    **刻意不先縮圖**：直覺上「縮小再比較」應該更省，但實測結果相反——
    scale 濾鏡自己每一格都要重採樣，成本高過它替 scene 偵測省下的量，
    同一支素材加了 scale 反而從 1.26 秒變成 3.43 秒（偵測結果完全相同）。
    """
    settings = settings or resolve_pacing_settings()
    command = [
        "ffmpeg", "-hide_banner", "-nostats",
        "-i", media_path,
        "-an",
        "-vf", (f"select='gt(scene,{settings['scene_threshold']:.2f})',"
                "metadata=print"),
        "-f", "null", "-",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return []
    stderr = (completed.stderr or b"").decode("utf-8", errors="ignore")
    return parse_scene_times(stderr)


def build_shots(cuts: list, duration: float) -> list:
    """
    把剪接點切成一個個「鏡頭」，回傳 [{"start","end","duration"}, ...]。

    第一個鏡頭從 0 秒開始；最後一個鏡頭到影片結束為止。
    """
    duration = float(duration or 0.0)
    if duration <= 0:
        return []
    points = [0.0]
    for cut in sorted(cuts or []):
        cut = float(cut)
        if 0.0 < cut < duration and cut > points[-1]:
            points.append(cut)
    shots = []
    for index, start in enumerate(points):
        end = points[index + 1] if index + 1 < len(points) else duration
        if end > start:
            shots.append({"start": start, "end": end,
                          "duration": end - start})
    return shots


def _median(values: list) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def format_timestamp(seconds: float) -> str:
    """把秒數排成 M:SS／H:MM:SS，與章節、開場健檢的顯示格式一致。"""
    seconds = max(int(seconds or 0), 0)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _finding(level, title, detail, advice=""):
    return {"level": level, "title": title, "detail": detail, "advice": advice}


def suggest_broll_points(static_shots: list, limit: float) -> list:
    """
    對每一段過長的畫面給出建議的 B-roll 插入時間點。

    在該段之內每隔 limit 秒放一個插入點（不貼在段落頭尾，避免剛切完
    又切一次），回傳秒數清單。
    """
    points = []
    limit = max(float(limit or 0.0), 1.0)
    for shot in static_shots or []:
        position = shot["start"] + limit
        while position < shot["end"] - 1.0:
            points.append(position)
            position += limit
    return points


def evaluate_pacing(shots: list, duration: float,
                    settings: Optional[dict] = None) -> dict:
    """
    依鏡頭清單產出健檢結果，回傳 {"findings","ok","stats","static_shots"}。

    與 detect_scene_changes 分開，讓判定邏輯可以完全不碰 ffmpeg 單獨測試。
    """
    settings = settings or resolve_pacing_settings()
    limit = settings["max_static_seconds"]
    findings = []

    if not shots:
        findings.append(_finding(
            LEVEL_BAD, "節奏分析", "讀不到影片畫面，無法分析剪輯節奏。",
            "請確認檔案含有影像軌（純音訊檔沒有畫面可分析）。"))
        return {"findings": findings, "ok": False, "stats": {},
                "static_shots": [], "suggestions": []}

    lengths = [s["duration"] for s in shots]
    stats = {
        "cut_count": len(shots) - 1,
        "shot_count": len(shots),
        "duration": float(duration or 0.0),
        "average": sum(lengths) / len(lengths),
        "median": _median(lengths),
        "longest": max(lengths),
    }
    static_shots = [s for s in shots if s["duration"] > limit]

    # 1. 完全沒有任何畫面變化。
    if stats["cut_count"] == 0:
        findings.append(_finding(
            LEVEL_BAD, "畫面變化",
            f"整支影片（{format_timestamp(stats['duration'])}）"
            "從頭到尾沒有任何畫面變化",
            "單一畫面撐完全片是留存最大的殺手之一。至少安排幾次"
            "推近／拉遠鏡頭、插入 B-roll 或圖卡，讓畫面有新東西可看。"))
    else:
        findings.append(_finding(
            LEVEL_GOOD, "畫面變化",
            f"共偵測到 {stats['cut_count']} 次畫面變化，"
            f"平均每 {stats['average']:.0f} 秒一次"))

    # 2. 過長的單一畫面——本健檢的主判準。
    # 一鏡到底時上面那條已經把話說完了，這裡再報一次只是重複；但 static_shots
    # 仍要保留，B-roll 建議插入點還是算得出來。
    if static_shots and stats["cut_count"] > 0:
        listed = "、".join(
            f"{format_timestamp(s['start'])}～{format_timestamp(s['end'])}"
            f"（{s['duration']:.0f} 秒）" for s in static_shots[:6])
        more = (f"，另有 {len(static_shots) - 6} 段未列出"
                if len(static_shots) > 6 else "")
        findings.append(_finding(
            LEVEL_WARN, "畫面太久沒變化",
            f"{len(static_shots)} 段畫面超過 {limit:.0f} 秒沒有變化："
            f"{listed}{more}",
            "這些位置最適合插入 B-roll、推近鏡頭或圖卡。"
            "建議的插入點見報告末段。"))
    elif stats["cut_count"] > 0:
        findings.append(_finding(
            LEVEL_GOOD, "畫面太久沒變化",
            f"沒有超過 {limit:.0f} 秒不變的畫面"))

    # 3. 節奏是否忽快忽慢：最長鏡頭遠超中位數時提醒。
    if stats["cut_count"] > 0 and stats["median"] > 0:
        ratio = stats["longest"] / stats["median"]
        if ratio >= 4.0:
            findings.append(_finding(
                LEVEL_WARN, "節奏不平均",
                f"最長的一個鏡頭 {stats['longest']:.0f} 秒，"
                f"是中位數（{stats['median']:.0f} 秒）的 {ratio:.1f} 倍",
                "整支影片的節奏忽快忽慢，觀眾會在最慢的那一段流失；"
                "建議把特別長的鏡頭拆開處理。"))

    ok = not any(f["level"] == LEVEL_BAD for f in findings)
    return {"findings": findings, "ok": ok, "stats": stats,
            "static_shots": static_shots,
            "suggestions": suggest_broll_points(static_shots, limit)}


def analyze_pacing(media_path: str, config: Optional[dict] = None,
                   progress_cb: Optional[Callable[[float, str], None]] = None
                   ) -> dict:
    """
    對影片跑剪輯節奏健檢，回傳 evaluate_pacing 的結果並附上 shots 與建議點。
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    settings = resolve_pacing_settings(config)

    def report(ratio, message):
        if callable(progress_cb):
            progress_cb(ratio, message)

    report(0.05, "讀取影片長度…")
    duration = probe_duration(media_path)
    report(0.15, "掃描畫面變化（這一步會完整讀過影片）…")
    cuts = detect_scene_changes(media_path, settings)
    report(0.85, "統計鏡頭長度…")
    shots = build_shots(cuts, duration)
    result = evaluate_pacing(shots, duration, settings)
    result["shots"] = shots
    result["cuts"] = cuts
    report(1.0, "完成")
    return result


def format_pacing_report(result: dict,
                         settings: Optional[dict] = None) -> str:
    """把剪輯節奏健檢結果排成純文字報告（GUI 顯示與 CLI 輸出共用）。"""
    settings = settings or resolve_pacing_settings()
    lines = ["===== 剪輯節奏健檢（畫面太久沒變化會流失觀眾）====="]
    findings = (result or {}).get("findings") or []
    if not findings:
        lines.append("・沒有可分析的畫面內容。")
        return "\n".join(lines)

    for finding in findings:
        icon = _LEVEL_ICONS.get(finding["level"], "・")
        lines.append(f"{icon} {finding['title']}：{finding['detail']}")
        if finding.get("advice"):
            lines.append(f"    建議：{finding['advice']}")

    stats = result.get("stats") or {}
    if stats:
        lines.append("")
        lines.append("鏡頭長度統計：")
        lines.append(f"  鏡頭數 {stats.get('shot_count', 0)}、"
                     f"畫面變化 {stats.get('cut_count', 0)} 次")
        lines.append(f"  平均 {stats.get('average', 0.0):.1f} 秒、"
                     f"中位數 {stats.get('median', 0.0):.1f} 秒、"
                     f"最長 {stats.get('longest', 0.0):.1f} 秒")

    suggestions = result.get("suggestions") or []
    if suggestions:
        lines.append("")
        lines.append("建議插入 B-roll／推鏡／圖卡的時間點：")
        shown = suggestions[:12]
        lines.append("  " + "、".join(format_timestamp(p) for p in shown)
                     + (f"，另有 {len(suggestions) - 12} 處"
                        if len(suggestions) > 12 else ""))

    lines.append("")
    if result.get("ok") and not result.get("static_shots"):
        lines.append("結論：剪輯節奏沒有明顯拖累留存的問題。")
    else:
        lines.append("結論：有畫面停留過久的段落——這是觀眾中途離開最常見的"
                     "原因之一。本檢查只提醒不自動改，要插什麼素材由你決定。")
    return "\n".join(lines)
