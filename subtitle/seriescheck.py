# -*- coding: utf-8 -*-
"""
系列一致性檢查：比對同一批（同系列）影片彼此之間是否一致。

調研顯示批次製作已是維持穩定更新頻率的主流作法——創作者一次集中拍
5~10 支，再一次批次剪輯、以相同設定匯出、一次排程上傳。這種作法的
盲點是：每一支單獨看都沒問題，**彼此之間卻不一致**。觀眾連看同一個
系列時，就會遇到第三集突然要調大音量、第五集畫面明顯偏暗或偏黃、
某一集解析度掉到 720p 這類體驗落差。

本工具既有的八類健檢全都是「這一支影片本身合不合格」——拿固定門檻
（YouTube 建議位元率、-14 LUFS、CPS 上限…）去衡量單一檔案。**沒有任何
一項在比較「這批影片彼此之間」**。同理，v1.24.0 的分段音量一致性比的是
同一支影片內部各段落，也不是跨檔案。

本模組因此改用**相對基準**：把整批的中位數當基準，找出偏離整批的那幾支，
而不是拿絕對門檻去衡量。這樣才抓得到「整批都偏暗但彼此一致」（沒問題，
是風格）與「其中一支特別暗」（有問題，該修）的差別。

比對項目：
- **整體響度**（LUFS）：連看時最有感的落差，觀眾得動手調音量
- **解析度／畫面更新率／視訊編碼**：規格不一致代表匯出設定跑掉
- **畫面亮度與色調**：不同天拍攝、白平衡沒統一時最常見

量測本身完全重用既有模組（audio.measure_loudness、videocheck.
probe_video_info、colorcheck.analyze_color），本模組只負責跨檔比較，
不重複實作任何 ffmpeg 呼叫。

只報告不自動修：統一整批需要重新編碼整支影片，且「要往哪個基準統一」
是創作判斷；報告會直接指向本工具既有的對應功能（響度正規化、音訊修復）
讓使用者自己決定。與 v1.26.0／v1.28.0／v1.29.0 的保守設計一致。

零 GUI 依賴，供系列一致性對話框與 CLI 共用。
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from .audio import measure_loudness
from .audiocheck import LEVEL_BAD, LEVEL_GOOD, LEVEL_WARN, _LEVEL_ICONS
from .burner import ffmpeg_available
from .colorcheck import analyze_color, resolve_colorcheck_settings
from .media import has_audio_stream, has_video_stream
from .videocheck import probe_video_info

DEFAULT_SERIESCHECK = {
    "loudness_tolerance": 2.0,  # 與整批中位數響度差超過此值（LU）即標記
    "luma_tolerance": 25.0,     # 平均亮度差超過此值（0~255）即標記
    "cast_tolerance": 8.0,      # 色調偏離整批中位數超過此值即標記
}

_LOUDNESS_RANGE = (0.5, 8.0)
_LUMA_RANGE = (10.0, 80.0)
_CAST_RANGE = (3.0, 30.0)

# 少於這個數量就沒有「整批基準」可言。
MIN_FILES = 2


def _clamp(value, low, high, fallback):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_seriescheck_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出系列一致性參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_SERIESCHECK)
    if config:
        raw.update({k: v for k, v in config.get("seriescheck", {}).items()
                    if v is not None})
    return {
        "loudness_tolerance": _clamp(
            raw.get("loudness_tolerance"), *_LOUDNESS_RANGE,
            DEFAULT_SERIESCHECK["loudness_tolerance"]),
        "luma_tolerance": _clamp(raw.get("luma_tolerance"), *_LUMA_RANGE,
                                 DEFAULT_SERIESCHECK["luma_tolerance"]),
        "cast_tolerance": _clamp(raw.get("cast_tolerance"), *_CAST_RANGE,
                                 DEFAULT_SERIESCHECK["cast_tolerance"]),
    }


def median(values: list) -> Optional[float]:
    """回傳中位數；空清單回 None。用中位數而非平均，單一極端值不會拉走基準。"""
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return None
    mid = len(clean) // 2
    if len(clean) % 2:
        return clean[mid]
    return (clean[mid - 1] + clean[mid]) / 2.0


def _as_float(value):
    """
    安全轉成 float，失敗回 None。

    ffmpeg 的 loudnorm 量測是以 JSON 輸出，數值欄位實際上是字串
    （例如 "-23.5"）；跨檔比較前必須轉型，否則會在相減時炸掉。
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _majority(values: list):
    """回傳出現次數最多的值（整批的「標準規格」）；空清單回 None。"""
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    counts = {}
    for value in clean:
        counts[value] = counts.get(value, 0) + 1
    return max(counts.items(), key=lambda kv: (kv[1], -clean.index(kv[0])))[0]


def measure_file(path: str, config: Optional[dict] = None) -> dict:
    """
    量測單一檔案的各項指標（完全重用既有模組，不重複實作 ffmpeg 呼叫）。

    無法量測的項目回 None，由跨檔比較階段自行略過，不會中斷整批。
    """
    entry = {"path": path, "name": os.path.basename(path), "lufs": None,
             "width": None, "height": None, "fps": None, "codec": None,
             "luma": None, "u": None, "v": None, "error": None}
    if not os.path.exists(path):
        entry["error"] = "找不到檔案"
        return entry

    if has_audio_stream(path):
        measured = measure_loudness(path)
        if measured:
            entry["lufs"] = _as_float(measured.get("input_i"))

    if has_video_stream(path):
        info = probe_video_info(path)
        if info:
            entry.update({"width": info["width"], "height": info["height"],
                          "fps": info["fps"], "codec": info["codec"]})
        try:
            color = analyze_color(path, resolve_colorcheck_settings(config))
            entry.update({"luma": color["avg_luma"], "u": color["avg_u"],
                          "v": color["avg_v"]})
        except (RuntimeError, ValueError, FileNotFoundError):
            pass  # 色彩取樣失敗不影響其他比對項目。
    return entry


def _finding(level, title, detail, advice=""):
    return {"level": level, "title": title, "detail": detail, "advice": advice}


def _compare_numeric(entries: list, key: str, tolerance: float, title: str,
                     unit: str, advice: str, decimals: int = 1) -> list:
    """
    以整批中位數為基準，找出某個數值指標偏離過多的檔案。

    用中位數而非平均：整批裡有一支特別離譜時，平均會被它拉走，反而讓
    其他正常檔案看起來也偏離。
    """
    values = [e[key] for e in entries if e.get(key) is not None]
    if len(values) < MIN_FILES:
        return []
    base = median(values)
    outliers = [(e, e[key] - base) for e in entries
                if e.get(key) is not None and abs(e[key] - base) > tolerance]
    if not outliers:
        return [_finding(LEVEL_GOOD, title,
                         f"整批一致（基準 {base:.{decimals}f}{unit}）")]
    detail = "、".join(
        f"{e['name']}（{e[key]:.{decimals}f}{unit}，"
        f"{'高' if diff > 0 else '低'} {abs(diff):.{decimals}f}{unit}）"
        for e, diff in outliers)
    return [_finding(
        LEVEL_WARN, title,
        f"基準 {base:.{decimals}f}{unit}，以下偏離：{detail}", advice)]


def _compare_spec(entries: list) -> list:
    """比對解析度／更新率／編碼是否整批一致（規格不一代表匯出設定跑掉）。"""
    findings = []
    specs = [(e, (e["width"], e["height"])) for e in entries
             if e.get("width") and e.get("height")]
    if len(specs) >= MIN_FILES:
        base = _majority([s for _e, s in specs])
        odd = [e for e, s in specs if s != base]
        if odd:
            findings.append(_finding(
                LEVEL_BAD, "解析度",
                f"整批多數為 {base[0]}x{base[1]}，"
                + "、".join(f"{e['name']}（{e['width']}x{e['height']}）"
                            for e in odd),
                "同系列解析度不一致，觀眾連看時畫質會忽好忽壞；"
                "請以相同輸出設定重新匯出不一致的那幾支。"))
        else:
            findings.append(_finding(
                LEVEL_GOOD, "解析度", f"整批一致（{base[0]}x{base[1]}）"))

    fps_list = [(e, round(e["fps"], 2)) for e in entries
                if e.get("fps")]
    if len(fps_list) >= MIN_FILES:
        base = _majority([f for _e, f in fps_list])
        odd = [e for e, f in fps_list if abs(f - base) > 0.5]
        if odd:
            findings.append(_finding(
                LEVEL_WARN, "畫面更新率",
                f"整批多數為 {base:.2f} fps，"
                + "、".join(f"{e['name']}（{e['fps']:.2f} fps）" for e in odd),
                "更新率不一致可能來自不同的拍攝或匯出設定；"
                "統一成同一個更新率再匯出比較保險。"))
        else:
            findings.append(_finding(
                LEVEL_GOOD, "畫面更新率", f"整批一致（{base:.2f} fps）"))

    codecs = [(e, e["codec"]) for e in entries if e.get("codec")]
    if len(codecs) >= MIN_FILES:
        base = _majority([c for _e, c in codecs])
        odd = [e for e, c in codecs if c != base]
        if odd:
            findings.append(_finding(
                LEVEL_WARN, "視訊編碼",
                f"整批多數為 {base}，"
                + "、".join(f"{e['name']}（{e['codec']}）" for e in odd),
                "編碼不一致通常代表匯出設定跑掉；建議統一。"))
        else:
            findings.append(_finding(
                LEVEL_GOOD, "視訊編碼", f"整批一致（{base}）"))
    return findings


def analyze_series(
    paths: list,
    config: Optional[dict] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> dict:
    """
    比對整批影片彼此之間是否一致，回傳 {"entries", "findings"}。

    每個檔案只量測一次，之後全部比較都用同一份量測結果。
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    paths = [p for p in (paths or []) if p]
    if len(paths) < MIN_FILES:
        raise ValueError(
            f"系列一致性檢查需要至少 {MIN_FILES} 個檔案才有比較基準，"
            "請一次選取同系列的多支影片。")

    settings = resolve_seriescheck_settings(config)
    entries = []
    for index, path in enumerate(paths):
        if progress_cb:
            progress_cb(index / len(paths),
                        f"正在量測（{index + 1}/{len(paths)}）"
                        f"{os.path.basename(path)}...")
        entries.append(measure_file(path, config))

    if progress_cb:
        progress_cb(0.95, "正在比對整批一致性...")

    usable = [e for e in entries if not e["error"]]
    findings = []
    findings.extend(_compare_numeric(
        usable, "lufs", settings["loudness_tolerance"], "整體響度", " LUFS",
        "同系列音量落差最有感——觀眾連看時得一直調音量。"
        "可對偏離的那幾支用「音訊修復」勾選響度正規化，"
        "或輸出時勾「響度正規化」統一到 -14 LUFS。"))
    findings.extend(_compare_spec(usable))
    findings.extend(_compare_numeric(
        usable, "luma", settings["luma_tolerance"], "畫面亮度", "",
        "同系列亮度落差通常是不同天拍攝或曝光設定不同；"
        "可回剪輯軟體對偏離的那幾支調整亮度。", decimals=0))
    findings.extend(_compare_numeric(
        usable, "u", settings["cast_tolerance"], "色調（藍黃）", "",
        "色調不一致通常是白平衡沒統一；可回剪輯軟體校正色溫。",
        decimals=0))
    findings.extend(_compare_numeric(
        usable, "v", settings["cast_tolerance"], "色調（紅綠）", "",
        "色調不一致通常是白平衡沒統一；可回剪輯軟體校正色溫。",
        decimals=0))

    if progress_cb:
        progress_cb(1.0, "系列一致性檢查完成。")
    return {"entries": entries, "findings": findings}


def format_series_report(result: dict) -> str:
    """把系列一致性結果排成純文字報告（GUI 顯示與 CLI 輸出共用）。"""
    lines = ["===== 系列一致性檢查 ====="]
    entries = (result or {}).get("entries") or []
    findings = (result or {}).get("findings") or []
    if not entries:
        lines.append("・沒有可比對的檔案。")
        return "\n".join(lines)

    lines.append(f"比對 {len(entries)} 支影片：")
    for entry in entries:
        if entry["error"]:
            lines.append(f"  ・{entry['name']}：{entry['error']}")
            continue
        parts = []
        if entry["lufs"] is not None:
            parts.append(f"{entry['lufs']:.1f} LUFS")
        if entry["width"] and entry["height"]:
            parts.append(f"{entry['width']}x{entry['height']}")
        if entry["fps"]:
            parts.append(f"{entry['fps']:.2f} fps")
        if entry["luma"] is not None:
            parts.append(f"亮度 {entry['luma']:.0f}")
        summary = "、".join(parts) if parts else "無可量測項目"
        lines.append(f"  ・{entry['name']}：{summary}")

    lines.append("")
    warn = 0
    for finding in findings:
        icon = _LEVEL_ICONS.get(finding["level"], "・")
        lines.append(f"{icon} {finding['title']}：{finding['detail']}")
        if finding.get("advice"):
            lines.append(f"    建議：{finding['advice']}")
        if finding["level"] != LEVEL_GOOD:
            warn += 1

    lines.append("")
    if warn:
        lines.append(f"結論：{warn} 項在整批之間不一致，建議處理後再上傳，"
                     "避免觀眾連看時遇到體驗落差。")
    else:
        lines.append("結論：整批各項指標彼此一致。")
    lines.append("注意：本檢查比的是「這批影片彼此之間」是否一致，"
                 "與單支影片是否合格（上片前健檢）是不同的問題——"
                 "整批一致但整批都偏暗，這裡不會標記。")
    return "\n".join(lines)
