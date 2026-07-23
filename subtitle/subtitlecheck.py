# -*- coding: utf-8 -*-
"""
字幕健檢：檢查閱讀速度（CPS）、顯示時間、行數與行長，抓出「觀眾來不及看完」的字幕。

調研引用 Netflix（成人內容 CPS 上限 20、兒童內容 17）、BBC（建議 15 以下）
等業界字幕 QC 規範——CPS（每秒字元數）超標是字幕檔案審核最常被打回的原因。
本工具原本只在「生成字幕」當下靠斷句設定限制單行字數，但下列情境產生的
字幕從未被檢查過：

- 翻譯字幕（雙語模式內容變兩倍長，顯示時間卻沿用原文的時間軸）
- 匯入既有字幕檔（v1.19.0）：檔案品質不明，完全沒做過把關
- 手動新增或編輯字幕：使用者自行輸入，沒有斷句規則保護

本模組掃描「目前的字幕清單」（不論來源），標出過快、過短、行數過多、
單行過長的字幕；並提供「一鍵延長」：利用與下一句之間的空檔延長顯示
秒數（不改動文字內容、不與下一句重疊），空檔不足時保留原樣不強行硬改。

零 GUI 依賴，供字幕健檢對話框與 CLI 共用。
"""

from __future__ import annotations

from typing import Optional

LEVEL_GOOD = "good"
LEVEL_WARN = "warn"
LEVEL_BAD = "bad"

# 使用者可調的健檢門檻（GUI 可調並記憶於 config.json 的 "subtitlecheck"）。
DEFAULT_SUBCHECK = {
    "cps_limit": 17.0,          # 每秒字元數超過此值標記「閱讀過快」
    "min_duration": 0.8,        # 顯示秒數低於此值標記「顯示過短」
    "max_lines": 2,             # 超過此行數標記「行數過多」
    "max_chars_per_line": 21,   # 單行字元數超過此值標記「單行過長」
}
_CPS_RANGE = (10.0, 25.0)
_MIN_DURATION_RANGE = (0.3, 2.0)
_MAX_LINES_RANGE = (1, 4)
_MAX_CHARS_RANGE = (10, 60)

# 一鍵延長時，與下一句之間至少保留的間隔秒數（避免延長到緊貼下一句）。
_EXTEND_GAP = 0.08

_LEVEL_ICONS = {LEVEL_GOOD: "✔", LEVEL_WARN: "⚠", LEVEL_BAD: "✘"}


def _clamp(value, low, high, fallback, cast=float):
    try:
        value = cast(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_subcheck_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出字幕健檢門檻，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_SUBCHECK)
    if config:
        raw.update({k: v for k, v in config.get("subtitlecheck", {}).items()
                    if v is not None})
    return {
        "cps_limit": _clamp(raw.get("cps_limit"), *_CPS_RANGE,
                            DEFAULT_SUBCHECK["cps_limit"]),
        "min_duration": _clamp(raw.get("min_duration"), *_MIN_DURATION_RANGE,
                               DEFAULT_SUBCHECK["min_duration"]),
        "max_lines": int(_clamp(raw.get("max_lines"), *_MAX_LINES_RANGE,
                                DEFAULT_SUBCHECK["max_lines"], cast=int)),
        "max_chars_per_line": int(_clamp(
            raw.get("max_chars_per_line"), *_MAX_CHARS_RANGE,
            DEFAULT_SUBCHECK["max_chars_per_line"], cast=int)),
    }


def _display_char_count(text: str) -> int:
    """計算畫面上會顯示的字元數（不含換行符本身；空白字元計入，符合業界 CPS 慣例）。"""
    return sum(len(line) for line in text.split("\n"))


def compute_cps(text: str, duration: float) -> float:
    """計算字幕的每秒字元數（CPS）；顯示秒數非正值時回傳 0。"""
    if duration <= 0:
        return 0.0
    return _display_char_count(text) / duration


def analyze_cues(cues: list, settings: Optional[dict] = None) -> dict:
    """
    掃描字幕清單，回傳 {"issues": [...], "counts": {...}, "total": N}。

    issues 每筆含 index（清單索引，0 起算）、start、end、level、title、
    detail、advice；同一句可能同時觸發多個檢查項目，各自成一筆。
    空文字的字幕（如純空白佔位）不列入檢查。
    """
    settings = settings or resolve_subcheck_settings()
    issues = []
    counts = {"cps": 0, "duration": 0, "lines": 0, "line_length": 0}
    for index, cue in enumerate(cues):
        text = (cue.get("text") or "").strip()
        if not text:
            continue
        start, end = cue.get("start", 0.0), cue.get("end", 0.0)
        duration = end - start
        lines = text.split("\n")

        cps = compute_cps(text, duration)
        if cps > settings["cps_limit"]:
            counts["cps"] += 1
            issues.append({
                "index": index, "start": start, "end": end,
                "level": (LEVEL_BAD if cps > settings["cps_limit"] * 1.3
                         else LEVEL_WARN),
                "title": "閱讀速度過快",
                "detail": f"第 {index + 1} 句：{cps:.1f} 字/秒"
                          f"（門檻 {settings['cps_limit']:.0f}）",
                "advice": "延長顯示時間（可用「一鍵延長」自動處理有空檔的句子），"
                         "或精簡文字內容。",
            })
        if 0 < duration < settings["min_duration"]:
            counts["duration"] += 1
            issues.append({
                "index": index, "start": start, "end": end,
                "level": LEVEL_WARN,
                "title": "顯示時間過短",
                "detail": f"第 {index + 1} 句：僅顯示 {duration:.2f} 秒"
                          f"（門檻 {settings['min_duration']:.1f} 秒）",
                "advice": "延長顯示時間，太短的字幕觀眾幾乎來不及注意到。",
            })
        if len(lines) > settings["max_lines"]:
            counts["lines"] += 1
            issues.append({
                "index": index, "start": start, "end": end,
                "level": LEVEL_WARN,
                "title": "行數過多",
                "detail": f"第 {index + 1} 句：{len(lines)} 行"
                          f"（門檻 {settings['max_lines']} 行）",
                "advice": "精簡內容或拆成兩句；行數過多會遮住畫面。",
            })
        longest = max((len(line) for line in lines), default=0)
        if longest > settings["max_chars_per_line"]:
            counts["line_length"] += 1
            issues.append({
                "index": index, "start": start, "end": end,
                "level": LEVEL_WARN,
                "title": "單行過長",
                "detail": f"第 {index + 1} 句：最長一行 {longest} 字"
                          f"（門檻 {settings['max_chars_per_line']} 字）",
                "advice": "手動斷成兩行或精簡文字，避免超出畫面寬度。",
            })
    return {"issues": issues, "counts": counts, "total": len(cues)}


def format_subtitle_report(result: dict) -> str:
    """把健檢結果排成純文字報告（GUI 顯示與 CLI 輸出共用）。"""
    lines = ["===== 字幕健檢報告 ====="]
    issues = result.get("issues", [])
    total = result.get("total", 0)
    if not issues:
        lines.append(f"共 {total} 句，全部通過，閱讀速度與行數皆在建議範圍內。")
        return "\n".join(lines)
    for issue in issues:
        icon = _LEVEL_ICONS.get(issue["level"], "・")
        lines.append(f"{icon} {issue['title']}：{issue['detail']}")
        if issue.get("advice"):
            lines.append(f"    建議：{issue['advice']}")
    bad = sum(1 for i in issues if i["level"] == LEVEL_BAD)
    warn = sum(1 for i in issues if i["level"] == LEVEL_WARN)
    lines.append("")
    lines.append(f"結論：共 {total} 句，{bad} 項急需處理、{warn} 項建議留意。")
    return "\n".join(lines)


def fix_cue_durations(cues: list, settings: Optional[dict] = None) -> tuple:
    """
    一鍵延長：把 CPS 超標或顯示過短的字幕，在「不與下一句重疊」的前提下
    盡量延長到符合門檻；下一句銜接太近、沒有空檔可用時維持原樣，不強行
    硬改（避免製造新的重疊）。只調整時間軸，不改動文字內容。

    回傳 (新 cues 複本, 實際延長句數)；輸入的 cues 不會被修改。
    """
    settings = settings or resolve_subcheck_settings()
    new_cues = [dict(cue) for cue in cues]
    fixed = 0
    for index, cue in enumerate(new_cues):
        text = (cue.get("text") or "").strip()
        if not text:
            continue
        start, end = cue["start"], cue["end"]
        duration = end - start
        if duration <= 0:
            continue
        needed = max(_display_char_count(text) / settings["cps_limit"],
                    settings["min_duration"])
        if duration >= needed - 1e-6:
            continue
        if index + 1 < len(new_cues):
            limit = new_cues[index + 1]["start"] - _EXTEND_GAP
        else:
            limit = start + needed
        target_end = min(start + needed, limit)
        if target_end > end + 1e-6:
            cue["end"] = target_end
            fixed += 1
    return new_cues, fixed
