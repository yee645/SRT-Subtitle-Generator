# -*- coding: utf-8 -*-
"""
YouTube 章節健檢與一鍵修正：抓出「章節貼上去卻不顯示」的原因。

章節（影片說明欄的時間戳清單）出問題時 YouTube **不會給任何錯誤訊息**，
就只是整批章節都不顯示——創作者只能一條一條試錯。這是社群反覆抱怨的
情境，而規則其實是明確且可機器檢查的：

- **首章必須從 0:00 開始**（沒有 0:00 就完全不會啟用章節）
- **至少要 3 章**（少於 3 章一律不顯示）
- **每章至少 10 秒**（任何一章太短，整批都不顯示）
- 時間必須遞增，且每章都要有標題
- 時間戳要用半形冒號、秒數補到兩位、時間戳與標題之間要有空白

本工具自 v1.3.0 起就會產生 YouTube 章節草稿，但**從未檢查產出是否符合
上述規則**——實測既有產生器在「段落間隔不足」的素材上只會產生 1 章，
使用者複製貼上後章節完全不會出現，卻不會收到任何提示。

本模組同時支援兩種來源：
- 本工具產生的章節
- **使用者自己手寫或從別的工具拿到的章節文字**（直接貼上檢查）

後者才是實務上最常見的求助情境，因此解析器刻意對常見的手寫錯誤
（用分號或句點當分隔、秒數只寫一位、時間戳與標題之間沒有空白）
給出具體指認，而不是只說「格式錯誤」。

修正只在安全的範圍內進行：把過短的章節併入前一章、首章補成 0:00、
排序並移除重複時間；**章節數不足 3 章時不會憑空捏造章節**，而是明確
告知這支影片的段落不足以使用章節功能。

零 GUI 依賴，供章節健檢對話框與 CLI 共用。
"""

from __future__ import annotations

import re
from typing import Optional

# 使用者可調參數（config["chaptercheck"]）。預設值即 YouTube 的實際規則，
# 之所以做成可調，是為了讓其他平台或未來規則調整時不必改程式。
DEFAULT_CHAPTERCHECK = {
    "min_chapter_seconds": 10.0,  # 每章最短長度（YouTube 規定 10 秒）
    "min_chapter_count": 3,       # 最少章節數（YouTube 規定 3 章）
}

_MIN_SECONDS_RANGE = (1.0, 120.0)
_MIN_COUNT_RANGE = (2, 10)

LEVEL_GOOD = "good"
LEVEL_WARN = "warn"
LEVEL_BAD = "bad"
_LEVEL_ICONS = {LEVEL_GOOD: "✔", LEVEL_WARN: "⚠", LEVEL_BAD: "✘"}

# 合法時間戳：M:SS／MM:SS／H:MM:SS／HH:MM:SS，秒與分皆補滿兩位。
_VALID_TS = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})$")
# 一行章節：時間戳 + 至少一個空白 + 標題。
_LINE_RE = re.compile(r"^\s*(\S+)\s+(.*\S)\s*$")
# 常見手寫錯誤的偵測樣式。
_WRONG_SEP = re.compile(r"^\d{1,2}[;.．；]\d{1,2}")
_SHORT_SECONDS = re.compile(r"^(?:\d{1,2}:)?\d{1,2}:\d$")
_NO_SPACE = re.compile(r"^((?:\d{1,2}:)?\d{1,2}:\d{2})(\S.*)$")
# 時間戳與標題黏在一起時，用來把兩者拆開（分隔符尚未正規化，故放寬）。
_GLUED = re.compile(r"^([\d;.．；:：]+)(\S.*)$")
# 各種被打錯的分隔符，一律正規化成半形冒號。
_SEP_CHARS = re.compile(r"[;.．；：]")


def _clamp(value, low, high, fallback, cast=float):
    try:
        value = cast(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_chaptercheck_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出章節健檢參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_CHAPTERCHECK)
    if config:
        raw.update({k: v for k, v in config.get("chaptercheck", {}).items()
                    if v is not None})
    return {
        "min_chapter_seconds": _clamp(
            raw.get("min_chapter_seconds"), *_MIN_SECONDS_RANGE,
            DEFAULT_CHAPTERCHECK["min_chapter_seconds"]),
        "min_chapter_count": _clamp(
            raw.get("min_chapter_count"), *_MIN_COUNT_RANGE,
            DEFAULT_CHAPTERCHECK["min_chapter_count"], cast=int),
    }


def parse_timestamp(text: str) -> Optional[float]:
    """把 M:SS／MM:SS／H:MM:SS 形式的時間戳轉成秒數；格式不合回 None。"""
    match = _VALID_TS.match((text or "").strip())
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    if int(seconds) >= 60:
        return None
    if hours is not None and int(minutes) >= 60:
        return None
    total = int(minutes) * 60 + int(seconds)
    if hours is not None:
        total += int(hours) * 3600
    return float(total)


def format_timestamp(seconds: float) -> str:
    """把秒數排成 YouTube 章節用的時間戳（不足一小時省略時位）。"""
    seconds = max(int(seconds), 0)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _normalize_stamp(stamp: str) -> str:
    """把打錯的分隔符換成半形冒號，並把最後一段秒數補滿兩位。"""
    fixed = _SEP_CHARS.sub(":", (stamp or "").strip()).rstrip(":")
    parts = fixed.split(":")
    if len(parts) >= 2 and parts[-1].isdigit():
        parts[-1] = parts[-1].zfill(2)
    return ":".join(parts)


def repair_chapter_line(line: str) -> Optional[dict]:
    """
    嘗試把一行常見的手寫錯誤修回可用的章節；無法明確修正時回 None。

    只處理「意圖明確」的三種錯誤：分隔符打錯、秒數少一位、時間戳與標題
    黏在一起。修好的行會在報告中逐條列出修改前後，使用者看得到我們動了
    什麼，而不是靜靜地把整行丟掉。
    """
    line = (line or "").strip()
    if not line:
        return None
    match = _LINE_RE.match(line)
    if match:
        stamp, title = match.group(1), match.group(2)
    else:
        # 整行本身就是一個時間戳＝沒有標題可用。這一步不能省：拆黏在一起
        # 的樣式時會把「1:00」硬拆成時間戳 1:0 加標題「0」，憑空生出一章。
        if parse_timestamp(_normalize_stamp(line)) is not None:
            return None
        match = _GLUED.match(line)
        if not match:
            return None
        stamp, title = match.group(1), match.group(2)
    title = title.strip()
    if not title:
        return None
    seconds = parse_timestamp(_normalize_stamp(stamp))
    if seconds is None:
        return None
    return {"start": seconds, "title": title}


def parse_chapters(text: str) -> tuple:
    """
    解析使用者貼上的章節文字，回傳 (章節清單, 無法解析的行清單)。

    對常見的手寫錯誤給出具體指認，而不是只說「格式錯誤」——這正是
    使用者卡住時最需要的資訊。無法解析但意圖明確的行會附上 "repaired"
    欄位，供 fix_chapters 救回來，避免一鍵修正把使用者的章節弄不見。
    """
    chapters = []
    errors = []
    for lineno, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        match = _LINE_RE.match(line)
        if match:
            stamp, title = match.group(1), match.group(2)
            seconds = parse_timestamp(stamp)
            if seconds is not None:
                chapters.append({"start": seconds, "title": title,
                                 "lineno": lineno})
                continue
            reason = _explain_bad_stamp(stamp)
        else:
            reason = _explain_bad_line(line)
        errors.append({"lineno": lineno, "line": line, "reason": reason,
                       "repaired": repair_chapter_line(line)})
    return chapters, errors


def _explain_bad_stamp(stamp: str) -> str:
    if _WRONG_SEP.match(stamp):
        return "時間戳要用半形冒號「:」分隔，不能用分號或句點"
    if _SHORT_SECONDS.match(stamp):
        return "秒數要補滿兩位（例如 0:05 而不是 0:5）"
    return f"「{stamp}」不是有效的時間戳（格式應為 0:00 或 1:02:03）"


def _explain_bad_line(line: str) -> str:
    match = _NO_SPACE.match(line)
    if match:
        return "時間戳與標題之間要有一個空白"
    if parse_timestamp(line) is not None:
        return "這一行只有時間戳、沒有標題文字"
    if _WRONG_SEP.match(line):
        return "時間戳要用半形冒號「:」分隔，不能用分號或句點"
    return "無法辨識為「時間戳 空白 標題」的格式"


def _finding(level, title, detail, advice=""):
    return {"level": level, "title": title, "detail": detail, "advice": advice}


def validate_chapters(chapters: list, duration: Optional[float] = None,
                      settings: Optional[dict] = None,
                      parse_errors: Optional[list] = None) -> dict:
    """
    依 YouTube 的章節規則檢查，回傳 {"findings", "ok"}。

    duration 提供時，最後一章的長度才算得出來（否則只能檢查到倒數第二章）。
    """
    settings = settings or resolve_chaptercheck_settings()
    min_seconds = settings["min_chapter_seconds"]
    min_count = settings["min_chapter_count"]
    findings = []

    for error in parse_errors or []:
        advice = ("YouTube 解析不到的行會讓整批章節失效，"
                  "這一行的意圖很明確，可按「一鍵修正」直接改好。"
                  if error.get("repaired") else
                  "YouTube 解析不到的行會讓整批章節失效，"
                  "且無法自動判斷你原本想寫的時間，請手動修正後再貼上。")
        findings.append(_finding(
            LEVEL_BAD, "格式錯誤",
            f"第 {error['lineno']} 行「{error['line']}」：{error['reason']}",
            advice))

    ordered = sorted(chapters or [], key=lambda c: c["start"])

    # 1. 首章必須 0:00。
    if not ordered:
        findings.append(_finding(
            LEVEL_BAD, "章節內容", "沒有讀到任何章節。",
            "章節格式為每行一個「時間戳 空白 標題」，例如「0:00 開場」。"))
        return {"findings": findings, "ok": False}
    if ordered[0]["start"] != 0:
        findings.append(_finding(
            LEVEL_BAD, "首章時間",
            f"第一章從 {format_timestamp(ordered[0]['start'])} 開始，"
            "不是 0:00",
            "沒有 0:00 這一章，YouTube 完全不會啟用章節功能；"
            "請把第一章改成 0:00。"))
    else:
        findings.append(_finding(LEVEL_GOOD, "首章時間", "第一章從 0:00 開始"))

    # 2. 章節數量。
    if len(ordered) < min_count:
        findings.append(_finding(
            LEVEL_BAD, "章節數量",
            f"只有 {len(ordered)} 章，未達 {min_count} 章",
            f"少於 {min_count} 章時 YouTube 一律不顯示章節。"
            "請把影片再切出幾個段落，或乾脆不要使用章節功能。"))
    else:
        findings.append(_finding(
            LEVEL_GOOD, "章節數量", f"共 {len(ordered)} 章，符合最低要求"))

    # 3. 時間重複或遞增問題。
    duplicates = [c for i, c in enumerate(ordered[1:], start=1)
                  if c["start"] == ordered[i - 1]["start"]]
    if duplicates:
        findings.append(_finding(
            LEVEL_BAD, "時間重複",
            "、".join(f"{format_timestamp(c['start'])} {c['title']}"
                      for c in duplicates),
            "同一個時間點不能有兩章，請調整其中一章的時間。"))

    # 4. 每章長度。
    short = []
    for index, chapter in enumerate(ordered):
        if index + 1 < len(ordered):
            length = ordered[index + 1]["start"] - chapter["start"]
        elif duration:
            length = duration - chapter["start"]
        else:
            continue  # 沒有影片長度時，最後一章無法判斷。
        if length < min_seconds:
            short.append((chapter, length))
    if short:
        findings.append(_finding(
            LEVEL_BAD, "章節長度",
            "、".join(
                f"{format_timestamp(c['start'])} {c['title']}（{length:.0f} 秒）"
                for c, length in short),
            f"每章至少要 {min_seconds:.0f} 秒，只要有一章太短，"
            "整批章節都不會顯示；可按「一鍵修正」把過短的章節併入前一章。"))
    else:
        findings.append(_finding(
            LEVEL_GOOD, "章節長度",
            f"每章都達到 {min_seconds:.0f} 秒"
            + ("" if duration else "（未提供影片長度，最後一章未檢查）")))

    # 5. 標題。
    untitled = [c for c in ordered if not (c.get("title") or "").strip()]
    if untitled:
        findings.append(_finding(
            LEVEL_BAD, "章節標題",
            "、".join(format_timestamp(c["start"]) for c in untitled),
            "每一章都必須有標題文字，否則該行不會被視為章節。"))

    ok = not any(f["level"] == LEVEL_BAD for f in findings)
    return {"findings": findings, "ok": ok}


def fix_chapters(chapters: list, duration: Optional[float] = None,
                 settings: Optional[dict] = None,
                 parse_errors: Optional[list] = None) -> tuple:
    """
    在安全範圍內修正章節，回傳 (修正後章節, 修正說明清單)。

    做的事：修好格式打錯的行（分隔符、秒數位數、缺空白）、排序、移除
    重複時間、首章補成 0:00、把過短的章節併入前一章（保留前一章的標題，
    因為前一章才是該段落的主題）。

    **不做的事**：章節數不足時不會憑空捏造章節——那需要知道影片實際
    在講什麼，不是格式修正能解決的。
    """
    settings = settings or resolve_chaptercheck_settings()
    min_seconds = settings["min_chapter_seconds"]
    changes = []
    collected = [dict(c) for c in (chapters or [])
                 if (c.get("title") or "").strip()]

    # 先救回格式打錯但意圖明確的行——直接丟掉會讓使用者的章節莫名消失，
    # 而且修正後的報告還會顯示「全部合格」，是最容易誤導人的失敗方式。
    for error in parse_errors or []:
        repaired = error.get("repaired")
        if not repaired:
            changes.append(
                f"無法自動修正第 {error['lineno']} 行"
                f"「{error['line']}」，已略過（{error['reason']}）")
            continue
        changes.append(
            f"修正第 {error['lineno']} 行格式："
            f"「{error['line']}」→「{format_timestamp(repaired['start'])} "
            f"{repaired['title']}」")
        collected.append(dict(repaired))

    ordered = sorted(collected, key=lambda c: c["start"])
    if not ordered:
        return [], changes

    deduped = [ordered[0]]
    for chapter in ordered[1:]:
        if chapter["start"] == deduped[-1]["start"]:
            changes.append(
                f"移除與 {format_timestamp(chapter['start'])} 時間重複的"
                f"「{chapter['title']}」")
            continue
        deduped.append(chapter)

    if deduped[0]["start"] != 0:
        changes.append(
            f"把第一章從 {format_timestamp(deduped[0]['start'])} 改為 0:00")
        deduped[0]["start"] = 0.0

    # 逐章往後看：某一章距離「上一個保留下來的章節」不足 min_seconds，
    # 代表上一章太短。移除這個較晚的分界點，等於把該段併入上一章
    # （保留上一章的起點與標題，因為上一章才是該段落的主題）。
    merged = [deduped[0]]
    for chapter in deduped[1:]:
        gap = chapter["start"] - merged[-1]["start"]
        if gap < min_seconds:
            changes.append(
                f"「{chapter['title']}」距前一章只有 {gap:.0f} 秒，"
                f"已移除此分段並併入「{merged[-1]['title']}」")
            continue
        merged.append(chapter)

    # 最後一章太短時併回前一章（需要影片長度才判斷得出來）。
    if duration and len(merged) > 1:
        tail = duration - merged[-1]["start"]
        if tail < min_seconds:
            changes.append(
                f"把過短的最後一章「{merged[-1]['title']}」"
                f"（{tail:.0f} 秒）併入前一章")
            merged.pop()

    return merged, changes


def format_chapters_text(chapters: list) -> str:
    """把章節排成可直接貼進 YouTube 說明欄的文字。"""
    return "\n".join(
        f"{format_timestamp(c['start'])} {c['title']}"
        for c in chapters or [])


def format_chapter_report(result: dict, chapters: Optional[list] = None,
                          changes: Optional[list] = None) -> str:
    """把章節健檢結果排成純文字報告（GUI 顯示與 CLI 輸出共用）。"""
    lines = ["===== YouTube 章節健檢 ====="]
    findings = (result or {}).get("findings") or []
    if not findings:
        lines.append("・沒有可檢查的章節。")
        return "\n".join(lines)

    for finding in findings:
        icon = _LEVEL_ICONS.get(finding["level"], "・")
        lines.append(f"{icon} {finding['title']}：{finding['detail']}")
        if finding.get("advice"):
            lines.append(f"    建議：{finding['advice']}")

    if changes:
        lines.append("")
        lines.append("已套用的修正：")
        for change in changes:
            lines.append(f"  ・{change}")

    if chapters is not None:
        lines.append("")
        lines.append("目前章節：")
        lines.append(format_chapters_text(chapters) or "  （無）")

    lines.append("")
    if result.get("ok"):
        lines.append("結論：符合 YouTube 章節規則，可以直接貼到說明欄。")
    else:
        lines.append("結論：不符合 YouTube 章節規則——貼上去之後章節"
                     "「不會顯示」，而且 YouTube 不會給任何錯誤訊息。"
                     "請依上述項目修正。")
    return "\n".join(lines)
