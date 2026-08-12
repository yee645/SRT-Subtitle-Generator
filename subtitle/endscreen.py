# -*- coding: utf-8 -*-
"""
片尾空間健檢：最後 20 秒留得下 YouTube 結束畫面嗎？

YouTube 的結束畫面（片尾）可以加在**影片結束前的 5 到 20 秒**，16:9 影片
最多四項元素。官方最佳做法直接寫著：**編輯時請務必考慮影片最後 20 秒，
為結束畫面預留足夠的空間**。

調研（中英文皆搜）指出這一段有兩個方向相反、卻同樣常見的失敗：

1. **內容被蓋掉**——中文資料的描述最精準：「有些影片並沒有提供片尾的
   過場畫面，主要內容播放完畢就結束，片尾的推薦影片跑出來時，反而就
   擋住了最後這幾秒的畫面」。英文資料則說最常見的錯誤就是元素疊在
   重要內容、人臉或文字上。
2. **反過來留了一段死寂**——「留 20 秒給元素，卻在這 20 秒什麼都不講，
   觀眾認出這是片尾就直接離開」。

所以正解不是「把最後 20 秒空出來」，而是**讓結束畫面疊在仍有意義的內容
上，但不要疊到會被擋住的東西上**。這兩件事必須一起看，只檢查其中一個
都會給出錯誤的建議。

本工具既有的檢查沒有涵蓋這一段：
- 「品牌套版」（v1.14.0）的片尾是**接上一段片尾影片檔**，不是檢查最後
  20 秒的內容
- 「一鍵去頭尾」（v1.17.0）的尾端檢查只看**結尾靜音的廢秒**

本模組看四件事：影片長度放不放得下片尾、最後這段的字幕會不會落進元素
會擺的位置、有沒有變成死寂的片尾、以及畫面是不是太雜（元素疊上去一片
混亂）。

要注意「會被蓋住」不等於「最後 20 秒不能有字幕」——字幕本來就是避免
死寂片尾的東西。真正會被蓋掉的是**擺在元素位置上**的字幕；YouTube 的
元素一般落在畫面中央區塊，畫面最下緣那一條反而是相對安全的（播放器
控制列本來就會佔住那裡，元素不會擺過去）。所以這裡看的是字幕的垂直
位置，不是字幕的有無。

只報告不自動改：片尾要怎麼設計是創作決定——與 v1.26.0 以來的保守設計
一致。

零 GUI 依賴，供上片前總體檢與 CLI 共用。
"""

from __future__ import annotations

import re
import subprocess
from typing import Callable, Optional

from subtitle.burner import ffmpeg_available
from subtitle.media import has_video_stream, probe_duration

# 使用者可調參數（config["endscreen"]）。預設值取自 YouTube 官方說明。
DEFAULT_ENDSCREEN = {
    # 結束畫面的時間窗長度（秒）。官方可設 5~20 秒，取最長的 20 秒檢查
    # 才涵蓋得到所有可能的設定。
    "window_seconds": 20.0,
    # 這段時間內講話覆蓋率低於此值，視為「死寂的片尾」。
    "min_speech_ratio": 0.30,
    # 片尾畫面的邊緣能量高於此值，視為太雜、元素疊上去會很亂。
    # 這個數字是實測校準出來的，不是拍腦袋：以 sobel 邊緣能量的平均值
    # （0~255）量測合成素材，得到純色 0、SMPTE 彩條 4.3、testsrc2 測試
    # 圖 11.3、mandelbrot 碎形 14.5、life 細胞格 103、純雜訊 146。取 12
    # 落在「有文字與圖形的測試圖」與「整片碎形細節」之間。
    "max_busy_edge": 12.0,
}

_WINDOW_RANGE = (5.0, 60.0)
_RATIO_RANGE = (0.0, 1.0)
_BUSY_RANGE = (5.0, 80.0)

# 影片短於這個長度就完全放不下結束畫面（官方最短 5 秒）。
MIN_ENDSCREEN_SECONDS = 5.0

# 結束畫面元素一般會落在的垂直範圍（0＝最上、1＝最下）。這是本工具的
# 保守估計，不是官方數字：YouTube 讓元素在畫面內自由擺放，但範本都落在
# 中央區塊，而畫面最下緣那條被播放器控制列佔住，元素不會擺過去。
ELEMENT_ZONE = (0.05, 0.80)

# 字幕實際佔用的高度比例，沿用 legibility.py 的 subtitle_band 預設值。
_BAND_RATIO = 0.14

LEVEL_GOOD = "good"
LEVEL_WARN = "warn"
LEVEL_BAD = "bad"
_LEVEL_ICONS = {LEVEL_GOOD: "✔", LEVEL_WARN: "⚠", LEVEL_BAD: "✘"}

_STAT_RE = re.compile(r"lavfi\.signalstats\.(\w+)=([-\d.]+)")


def _clamp(value, low, high, fallback, cast=float):
    try:
        value = cast(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_endscreen_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出片尾健檢參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_ENDSCREEN)
    if config:
        raw.update({k: v for k, v in config.get("endscreen", {}).items()
                    if v is not None})
    return {
        "window_seconds": _clamp(raw.get("window_seconds"), *_WINDOW_RANGE,
                                 DEFAULT_ENDSCREEN["window_seconds"]),
        "min_speech_ratio": _clamp(raw.get("min_speech_ratio"), *_RATIO_RANGE,
                                   DEFAULT_ENDSCREEN["min_speech_ratio"]),
        "max_busy_edge": _clamp(raw.get("max_busy_edge"), *_BUSY_RANGE,
                                DEFAULT_ENDSCREEN["max_busy_edge"]),
    }


def window_bounds(duration: float, window_seconds: float) -> tuple:
    """回傳結束畫面時間窗的 (起, 迄)；影片比視窗短時就從 0 開始。"""
    duration = max(float(duration or 0.0), 0.0)
    start = max(duration - float(window_seconds or 0.0), 0.0)
    return (start, duration)


def cues_in_window(cues: list, start: float, end: float) -> list:
    """找出與結束畫面時間窗有重疊的字幕句。"""
    rows = []
    for cue in cues or []:
        cue_start = float(cue.get("start") or 0.0)
        cue_end = float(cue.get("end") or 0.0)
        if cue_end > start and cue_start < end and (cue.get("text") or "").strip():
            rows.append(cue)
    return rows


def speech_ratio(cues: list, start: float, end: float) -> float:
    """
    算結束畫面時間窗內「有人在講話」的時間比例。

    用字幕的時間軸當講話的代理指標——本工具的字幕本來就來自語音辨識，
    不必再解一次音訊。重疊的句子會先合併，避免比例算超過 1。
    """
    span = max(float(end) - float(start), 0.0)
    if span <= 0:
        return 0.0
    spans = []
    for cue in cues_in_window(cues, start, end):
        spans.append((max(float(cue["start"]), start),
                      min(float(cue["end"]), end)))
    if not spans:
        return 0.0
    spans.sort()
    merged = [list(spans[0])]
    for begin, finish in spans[1:]:
        if begin <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], finish)
        else:
            merged.append([begin, finish])
    covered = sum(finish - begin for begin, finish in merged)
    return min(covered / span, 1.0)


def subtitle_band_range(style: Optional[dict] = None,
                        band_ratio: float = _BAND_RATIO) -> tuple:
    """
    字幕在畫面上佔的垂直範圍，回傳 (上緣, 下緣) 的 0~1 比例。

    以 exporter.py 的 `position_y` 為中心往上下各取半條帶子，與
    legibility.py 的 subtitle_band 同一套算法，只是不需要畫面尺寸。
    """
    style = style or {}
    try:
        position_y = float(style.get("position_y", 0.88))
    except (TypeError, ValueError):
        position_y = 0.88
    position_y = max(0.0, min(position_y, 1.0))
    half = max(float(band_ratio), 0.0) / 2.0
    return (max(position_y - half, 0.0), min(position_y + half, 1.0))


def safe_position_y(band_ratio: float = _BAND_RATIO) -> float:
    """字幕要擺多低才完全避開元素區，回傳建議的 position_y 下限。"""
    return round(ELEMENT_ZONE[1] + max(float(band_ratio), 0.0) / 2.0, 2)


def band_hits_element_zone(style: Optional[dict] = None,
                           band_ratio: float = _BAND_RATIO) -> bool:
    """字幕帶是否與結束畫面元素會擺的範圍重疊。"""
    top, bottom = subtitle_band_range(style, band_ratio)
    zone_top, zone_bottom = ELEMENT_ZONE
    return top < zone_bottom and bottom > zone_top


def measure_tail_busyness(media_path: str, start: float, end: float,
                          timeout: int = 300) -> float:
    """
    量測結束畫面時間窗的畫面「雜亂程度」（邊緣能量平均值）。

    用 sobel 邊緣能量當指標，與 v1.34.0 剪輯節奏健檢同一套作法。加 `-an`
    完全不解碼音訊——這段只看畫面，解音訊純屬浪費。

    注意 metadata=print 走 info 層級的日誌，**不能加 `-v error`**，
    否則整份數值都會被吞掉（沿用 colorcheck.py 的既有慣例）。
    """
    span = max(float(end) - float(start), 0.0)
    if span <= 0:
        return 0.0
    command = [
        "ffmpeg", "-hide_banner", "-nostats",
        "-ss", f"{max(float(start), 0.0):.3f}",
        "-t", f"{span:.3f}",
        "-i", media_path,
        "-an",
        "-vf", "sobel,signalstats,metadata=print",
        "-f", "null", "-",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return 0.0
    stderr = (completed.stderr or b"").decode("utf-8", errors="ignore")
    values = [float(m.group(2)) for m in _STAT_RE.finditer(stderr)
              if m.group(1) == "YAVG"]
    return sum(values) / len(values) if values else 0.0


def _finding(level, title, detail, advice=""):
    return {"level": level, "title": title, "detail": detail, "advice": advice}


def format_timestamp(seconds: float) -> str:
    """把秒數排成 M:SS／H:MM:SS，與其他健檢的顯示格式一致。"""
    seconds = max(int(seconds or 0), 0)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def evaluate_endscreen(duration: float, tail_cues: list, ratio: float,
                       busyness: Optional[float] = None,
                       settings: Optional[dict] = None,
                       style: Optional[dict] = None) -> dict:
    """
    依量測結果產出健檢項目，回傳 {"findings","ok","stats"}。

    與量測分開，讓判定邏輯可以完全不碰 ffmpeg 單獨測試。
    """
    settings = settings or resolve_endscreen_settings()
    window = settings["window_seconds"]
    findings = []
    duration = float(duration or 0.0)

    # 1. 影片長度放不放得下結束畫面。
    if duration <= 0:
        findings.append(_finding(
            LEVEL_BAD, "片尾空間", "讀不到影片長度，無法檢查片尾。",
            "請確認檔案可以正常開啟。"))
        return {"findings": findings, "ok": False, "stats": {}}
    if duration < MIN_ENDSCREEN_SECONDS:
        findings.append(_finding(
            LEVEL_BAD, "片尾空間",
            f"影片只有 {duration:.0f} 秒，短於結束畫面的最短長度 "
            f"{MIN_ENDSCREEN_SECONDS:.0f} 秒",
            "YouTube 的結束畫面要加在影片結束前的 5~20 秒處，"
            "這麼短的影片放不下任何結束畫面元素。"))

    start, end = window_bounds(duration, window)
    band_top, band_bottom = subtitle_band_range(style)
    stats = {
        "duration": duration,
        "window_start": start,
        "window_seconds": min(window, duration),
        "tail_cue_count": len(tail_cues or []),
        "speech_ratio": ratio,
        "busyness": busyness,
        "band_top": band_top,
        "band_bottom": band_bottom,
    }

    # 2. 這段的字幕會不會落進元素會擺的位置。
    # 注意判斷的是「位置」不是「有無」——最後 20 秒本來就該有字幕，
    # 沒有反而是第 3 項的死寂片尾。
    if not tail_cues:
        findings.append(_finding(
            LEVEL_GOOD, "字幕位置",
            f"{format_timestamp(start)} 之後沒有字幕，沒有會被元素蓋掉的字"))
    elif band_hits_element_zone(style):
        listed = "、".join(
            f"{format_timestamp(float(c['start']))}"
            f"「{(c.get('text') or '')[:14]}」" for c in tail_cues[:4])
        more = (f"，另有 {len(tail_cues) - 4} 句"
                if len(tail_cues) > 4 else "")
        findings.append(_finding(
            LEVEL_WARN, "字幕位置",
            f"{format_timestamp(start)} 之後有 {len(tail_cues)} 句字幕，"
            f"而字幕擺在畫面 {band_top * 100:.0f}%~{band_bottom * 100:.0f}% "
            f"的高度，正好落進結束畫面元素會擺的範圍："
            f"{listed}{more}",
            f"把字幕的垂直位置調到 {safe_position_y():.2f} 以下"
            "（也就是更貼近畫面底部，預設值 0.88 就是安全的）；"
            "畫面最下緣是播放器控制列的地盤，元素不會擺過去。"))
    else:
        findings.append(_finding(
            LEVEL_GOOD, "字幕位置",
            f"{format_timestamp(start)} 之後有 {len(tail_cues)} 句字幕，"
            f"但字幕壓在畫面 {band_top * 100:.0f}% 以下，"
            "在結束畫面元素會擺的範圍之外"))

    # 3. 反過來的失敗：留了一段死寂。
    # 只有在影片長到放得下結束畫面時才判斷——太短的影片前面已經報過了。
    if duration >= MIN_ENDSCREEN_SECONDS:
        if ratio < settings["min_speech_ratio"]:
            findings.append(_finding(
                LEVEL_WARN, "片尾內容",
                f"最後 {stats['window_seconds']:.0f} 秒只有 "
                f"{ratio * 100:.0f}% 的時間有人在講話",
                "留了一段什麼都沒講的片尾，觀眾一認出是片尾就會直接離開。"
                "結束畫面的目的是疊在「仍然有意義的內容」上，"
                "不是用一段空白把它換掉——講點下一支影片的預告也好。"))
        else:
            findings.append(_finding(
                LEVEL_GOOD, "片尾內容",
                f"最後 {stats['window_seconds']:.0f} 秒有 "
                f"{ratio * 100:.0f}% 的時間在講話，不是空白片尾"))

    # 4. 畫面太雜，元素疊上去會一片混亂。
    if busyness is not None:
        if busyness > settings["max_busy_edge"]:
            findings.append(_finding(
                LEVEL_WARN, "片尾畫面",
                f"最後這段的畫面細節量 {busyness:.0f}"
                f"（建議 {settings['max_busy_edge']:.0f} 以下）",
                "元素疊在細碎的畫面上會變成一團視覺噪音，觀眾不是忽略"
                "就是反感。片尾建議換成乾淨、單純的背景畫面。"))
        else:
            findings.append(_finding(
                LEVEL_GOOD, "片尾畫面",
                f"最後這段的畫面夠單純（細節量 {busyness:.0f}），"
                "元素疊上去看得清楚"))

    ok = not any(f["level"] == LEVEL_BAD for f in findings)
    return {"findings": findings, "ok": ok, "stats": stats}


def analyze_endscreen(media_path: str, cues: Optional[list] = None,
                      config: Optional[dict] = None,
                      progress_cb: Optional[Callable[[float, str], None]]
                      = None) -> dict:
    """對素材跑片尾空間健檢，回傳 evaluate_endscreen 的結果並附上時間窗。"""
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")

    settings = resolve_endscreen_settings(config)
    cues = cues or []

    def report(ratio, message):
        if callable(progress_cb):
            progress_cb(ratio, message)

    report(0.1, "讀取影片長度…")
    duration = probe_duration(media_path)
    start, end = window_bounds(duration, settings["window_seconds"])

    tail_cues = cues_in_window(cues, start, end)
    ratio = speech_ratio(cues, start, end)

    busyness = None
    if has_video_stream(media_path) and duration > 0:
        report(0.4, "量測片尾畫面的細節量…")
        busyness = measure_tail_busyness(media_path, start, end)

    style = (config or {}).get("subtitle_style") or {}
    result = evaluate_endscreen(duration, tail_cues, ratio, busyness,
                                settings, style)
    result["window"] = (start, end)
    result["tail_cues"] = tail_cues
    report(1.0, "完成")
    return result


def format_endscreen_report(result: dict,
                            settings: Optional[dict] = None) -> str:
    """把片尾空間健檢結果排成純文字報告（GUI 顯示與 CLI 輸出共用）。"""
    settings = settings or resolve_endscreen_settings()
    lines = ["===== 片尾空間健檢（最後 20 秒留得下結束畫面嗎）====="]
    findings = (result or {}).get("findings") or []
    if not findings:
        lines.append("・沒有可分析的內容。")
        return "\n".join(lines)

    for finding in findings:
        icon = _LEVEL_ICONS.get(finding["level"], "・")
        lines.append(f"{icon} {finding['title']}：{finding['detail']}")
        if finding.get("advice"):
            lines.append(f"    建議：{finding['advice']}")

    stats = result.get("stats") or {}
    if stats:
        lines.append("")
        lines.append("量測數值：")
        lines.append(
            f"  影片長度 {format_timestamp(stats.get('duration', 0))}"
            f"、結束畫面時間窗 "
            f"{format_timestamp(stats.get('window_start', 0))} 之後")
        busy = stats.get("busyness")
        lines.append(
            f"  這段有 {stats.get('tail_cue_count', 0)} 句字幕、"
            f"講話覆蓋率 {stats.get('speech_ratio', 0) * 100:.0f}%"
            + (f"、畫面細節量 {busy:.0f}" if busy is not None else ""))
        lines.append(
            f"  字幕高度 {stats.get('band_top', 0) * 100:.0f}%~"
            f"{stats.get('band_bottom', 0) * 100:.0f}%"
            f"、元素區 {ELEMENT_ZONE[0] * 100:.0f}%~"
            f"{ELEMENT_ZONE[1] * 100:.0f}%")

    warn_count = sum(1 for f in findings if f["level"] == LEVEL_WARN)
    lines.append("")
    if not result.get("ok"):
        lines.append("結論：片尾的空間有問題——結束畫面是白拿的訂閱與觀看"
                     "來源，值得在剪輯時就把最後這段規劃好。")
    elif warn_count:
        lines.append(f"結論：片尾放得下結束畫面，但有 {warn_count} 項值得調整"
                     "（見上方建議）。理想狀態是元素疊在仍有意義的內容上，"
                     "而不是疊掉字幕、也不是換成一段空白。")
    else:
        lines.append("結論：片尾留得下結束畫面。理想狀態是元素疊在仍有意義的"
                     "內容上，而不是疊掉字幕、也不是換成一段空白。")
    return "\n".join(lines)
