# -*- coding: utf-8 -*-
"""
中文字幕標點規範化：把逐字稿的標點改成字幕該有的樣子。

調研（中英文皆搜）指出中文字幕有一套與書面文字不同、而且相當一致的
標點慣例：**句末不加句號與逗號**（斷行本身就已經表達了停頓）、**句中
的逗號與頓號改用空格**，但**問號與驚嘆號要保留**——那兩個帶的是語氣，
拿掉會讓句子讀起來變平。Netflix 的字幕風格指南講得最直接：句末標點
只允許問號與驚嘆號。專業字幕翻譯的說法則是「以空格代替逗號」。

Whisper 產出的是**書面標點齊全**的逐字稿，本工具的斷句演算法又刻意
**切在逗號上**（`segmenter.WEAK_PUNCT`），兩件事加起來的結果是：**幾乎
每一句字幕都以一個逗號結尾**，而那個逗號在字幕裡完全沒有作用——下一句
本來就是另一張畫面。實測四種常見影片類型的講稿共 27 句，**85% 的句子
以標點結尾**，其中絕大多數是這種沒有作用的逗號。

本模組只做標點，不動字。特別注意兩件事：

1. **英文字幕不能套用**。英文的逗號與句號是文法的一部分，"Hello,
   everyone." 拿掉標點會變成錯的句子。所以只處理**中日韓字元佔多數**
   的行，同一份字幕裡的英文行原封不動。
2. **問號、驚嘆號、刪節號一律保留**，那是語氣不是格式。

不自動套用：字幕要不要留標點，各頻道的風格不同（很多中文頻道就是留著
標點在跑），所以預設只報告、由使用者按下一鍵套用。

零 GUI 依賴，供字幕健檢視窗與 CLI 共用。
"""

from __future__ import annotations

from typing import Optional

from subtitle.segmenter import CJK_RANGES

# 使用者可調參數（config["punctstyle"]）。
DEFAULT_PUNCTSTYLE = {
    # 規範化強度：
    #   "trim"     只拿掉行尾沒有作用的標點（實測佔問題的絕大多數）
    #   "subtitle" 再把句中的逗號、頓號改成空格（完整的字幕慣例）
    #   "off"      不做任何規範化（只想看報告時）
    "mode": "trim",
    # 句中逗頓改成什麼。全形空格在中文字之間的間距才對得起來；
    # 想要窄一點可改成兩個半形空格。
    "space": "　",
    # 一行要有多少比例是中日韓字元才視為中文行（英文行不套用）。
    # 門檻是實測出來的：中英夾雜的中文行（「我用的是 Premiere Pro，」
    # 0.27、「先按 Ctrl+Shift+D 開啟這個面板，」0.40）與真正的英文行
    # （最高 0.06，含夾了一個中文地名的 "The 台北 experience,"）之間
    # 有很大的空隙，0.15 落在中間、兩邊都有餘裕。取 0.5 會把三成的
    # 中英夾雜中文行誤判成英文而漏改。
    "cjk_ratio": 0.15,
}

_MODES = ("off", "trim", "subtitle")
_RATIO_RANGE = (0.1, 1.0)

# 行尾拿掉的標點：句號、逗號、頓號、分號、冒號（全形與半形）。
TRIM_MARKS = "。，、；：,;:."
# 一律保留的標點：問號、驚嘆號、刪節號帶的是語氣，不是格式。
KEEP_MARKS = "？！?!…"
# 句中改成空格的標點（mode="subtitle"）。
INLINE_MARKS = "，、,"


def _clamp(value, low, high, fallback, cast=float):
    try:
        value = cast(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_punctstyle_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出標點規範參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_PUNCTSTYLE)
    if config:
        raw.update({k: v for k, v in (config.get("punctstyle") or {}).items()
                    if v is not None})
    mode = str(raw.get("mode") or "").strip().lower()
    if mode not in _MODES:
        mode = DEFAULT_PUNCTSTYLE["mode"]
    # 只接受空白字元：這個值會被塞進字幕文字裡，讓它變成任意字串等於
    # 開了一個把使用者設定檔內容寫進成品的洞。
    space = raw.get("space")
    if not isinstance(space, str) or not space or space.strip():
        space = DEFAULT_PUNCTSTYLE["space"]
    return {
        "mode": mode,
        "space": space,
        "cjk_ratio": _clamp(raw.get("cjk_ratio"), *_RATIO_RANGE,
                            DEFAULT_PUNCTSTYLE["cjk_ratio"]),
    }


def _is_cjk_char(ch: str) -> bool:
    code = ord(ch)
    return any(low <= code <= high for low, high in CJK_RANGES)


def cjk_ratio(text: str) -> float:
    """算出一段文字裡中日韓字元的比例（標點與空白不計入分母）。"""
    chars = [ch for ch in text or "" if not ch.isspace()
             and ch not in TRIM_MARKS + KEEP_MARKS]
    if not chars:
        return 0.0
    return sum(1 for ch in chars if _is_cjk_char(ch)) / len(chars)


def is_chinese_line(text: str, settings: Optional[dict] = None) -> bool:
    """判斷這一行要不要套用中文字幕標點慣例（英文行不套用）。"""
    settings = settings or resolve_punctstyle_settings()
    return cjk_ratio(text) >= settings["cjk_ratio"]


def _trim_line(line: str) -> tuple:
    """
    拿掉一行結尾沒有作用的標點，回傳 (新文字, 拿掉的標點)。

    連續標點（「好了。。」「對啊，。」）一路拿到底；問號驚嘆號一碰到就
    停手，那是語氣不是格式。
    """
    trimmed = line.rstrip()
    removed = ""
    while trimmed and trimmed[-1] in TRIM_MARKS:
        removed = trimmed[-1] + removed
        trimmed = trimmed[:-1].rstrip()
    return trimmed, removed


def _inline_to_space(line: str, space: str) -> tuple:
    """把句中的逗號、頓號換成空格，回傳 (新文字, 換掉的個數)。"""
    count = 0
    out = []
    for ch in line:
        if ch in INLINE_MARKS:
            count += 1
            out.append(space)
        else:
            out.append(ch)
    text = "".join(out)
    # 「好了， 然後」這種標點後本來就有空白的情況會變成兩個空白。
    while space + space in text:
        text = text.replace(space + space, space)
    return text.strip(), count


def style_line(line: str, settings: Optional[dict] = None) -> tuple:
    """
    規範化單獨一行，回傳 (新文字, 拿掉的行尾標點, 換成空格的個數)。

    非中文行原封不動——英文的逗號與句號是文法的一部分。
    """
    settings = settings or resolve_punctstyle_settings()
    if settings["mode"] == "off" or not is_chinese_line(line, settings):
        return line, "", 0
    text, removed = _trim_line(line)
    swapped = 0
    if settings["mode"] == "subtitle":
        text, swapped = _inline_to_space(text, settings["space"])
    return text, removed, swapped


def apply_punct_style(cues: list, settings: Optional[dict] = None) -> tuple:
    """
    對整份字幕套用標點規範，回傳 (新字幕清單, 更動的句數)。

    不就地修改傳入的 cue，與 subtitlecheck 的一鍵修復行為一致。
    """
    settings = settings or resolve_punctstyle_settings()
    new_cues = []
    changed = 0
    for cue in cues or []:
        text = cue.get("text") or ""
        lines = [style_line(line, settings)[0] for line in text.split("\n")]
        new_text = "\n".join(lines)
        # 整行只有標點時會被清成空字串，那樣等於吃掉一句字幕；保留原文。
        if not new_text.strip():
            new_text = text
        if new_text != text:
            changed += 1
        updated = dict(cue)
        updated["text"] = new_text
        new_cues.append(updated)
    return new_cues, changed


def analyze_punctuation(cues: list, config: Optional[dict] = None) -> dict:
    """
    檢查整份字幕的標點是否符合中文字幕慣例。

    回傳 {"ok", "findings", "stats", "samples"}；findings 沿用本專案
    既有的 {"level","title","detail","advice"} 格式。
    """
    settings = resolve_punctstyle_settings(config)
    total = 0
    chinese = 0
    trailing = 0
    inline = 0
    samples = []
    for cue in cues or []:
        text = (cue.get("text") or "")
        for line in text.split("\n"):
            if not line.strip():
                continue
            total += 1
            if not is_chinese_line(line, settings):
                continue
            chinese += 1
            _, removed = _trim_line(line)
            if removed:
                trailing += 1
                if len(samples) < 5:
                    samples.append({"index": cue.get("index"),
                                    "text": line.strip(),
                                    "mark": removed})
            inline += sum(1 for ch in _trim_line(line)[0]
                          if ch in INLINE_MARKS)

    findings = []
    if not total:
        return {"ok": True, "findings": [], "samples": [],
                "stats": {"lines": 0, "chinese": 0,
                          "trailing": 0, "inline": 0}}

    if not chinese:
        findings.append({
            "level": "good",
            "title": "語言判定",
            "detail": f"{total} 行字幕都不是中文，本項不適用",
            "advice": "英文的逗號與句號是文法的一部分，不會被更動。",
        })
        return {"ok": True, "findings": findings, "samples": [],
                "stats": {"lines": total, "chinese": 0,
                          "trailing": 0, "inline": 0}}

    ratio = trailing / chinese
    if trailing:
        findings.append({
            "level": "warn",
            "title": "行尾標點",
            "detail": (f"{chinese} 行中文字幕裡有 {trailing} 行"
                       f"（{ratio:.0%}）以標點結尾"),
            "advice": ("中文字幕的慣例是句末不加句號與逗號——斷行本身"
                       "就已經表達了停頓，下一句本來就是另一張畫面。"
                       "問號與驚嘆號會保留。"),
        })
    else:
        findings.append({
            "level": "good",
            "title": "行尾標點",
            "detail": f"{chinese} 行中文字幕都沒有多餘的行尾標點",
            "advice": "",
        })

    # 句中逗頓只在 subtitle 模式下才是「待辦事項」。trim 模式刻意不碰它們，
    # 這時候若還列成一條檢查項，就會出現「✔ 句中還有 4 個逗號」這種
    # 打了勾卻在講問題的矛盾行；改為只留在量測數值與報告末尾的提示。
    if inline and settings["mode"] == "subtitle":
        findings.append({
            "level": "warn",
            "title": "句中逗頓",
            "detail": f"句中還有 {inline} 個逗號或頓號",
            "advice": "完整的字幕慣例是把句中逗頓改成空格，一鍵套用會一併處理。",
        })

    ok = trailing == 0 and not (settings["mode"] == "subtitle" and inline)
    return {
        "ok": ok,
        "findings": findings,
        "samples": samples,
        "stats": {"lines": total, "chinese": chinese,
                  "trailing": trailing, "inline": inline},
    }


_LEVEL_ICONS = {"good": "✔", "warn": "⚠", "bad": "✘"}


def format_punct_report(result: dict,
                        settings: Optional[dict] = None) -> str:
    """把標點規範健檢結果排成純文字報告（CLI 與 GUI 共用）。"""
    settings = settings or resolve_punctstyle_settings()
    lines = ["===== 中文字幕標點規範 ====="]
    findings = (result or {}).get("findings") or []
    if not findings:
        lines.append("・沒有可分析的字幕。")
        return "\n".join(lines)

    for finding in findings:
        icon = _LEVEL_ICONS.get(finding["level"], "・")
        lines.append(f"{icon} {finding['title']}：{finding['detail']}")
        if finding.get("advice"):
            lines.append(f"    建議：{finding['advice']}")

    samples = (result or {}).get("samples") or []
    if samples:
        lines.append("")
        lines.append("實際例子：")
        for sample in samples:
            index = sample.get("index")
            mark = sample.get("mark") or ""
            lines.append(f"  第 {index} 句：「{sample['text']}」"
                         f"（行尾的「{mark}」可以拿掉）")

    stats = (result or {}).get("stats") or {}
    if stats:
        lines.append("")
        lines.append("量測數值：")
        lines.append(
            f"  共 {stats.get('lines', 0)} 行，其中 "
            f"{stats.get('chinese', 0)} 行判定為中文；"
            f"行尾有標點 {stats.get('trailing', 0)} 行、"
            f"句中逗頓 {stats.get('inline', 0)} 個")

    lines.append("")
    mode_note = {"off": "目前設定為不套用（off）",
                 "trim": "目前設定為只拿掉行尾標點（trim）",
                 "subtitle": "目前設定為完整字幕慣例（subtitle）"}
    lines.append(f"結論：{'標點已符合字幕慣例。' if result.get('ok') else '標點還是逐字稿的樣子，建議規範化。'}"
                 f"{mode_note.get(settings['mode'], '')}。")
    inline = stats.get("inline", 0)
    if inline and settings["mode"] != "subtitle":
        lines.append(
            f"　（句中另有 {inline} 個逗號或頓號，目前的強度刻意不動它們；"
            "想連句中一起改成空格，把強度切到「完整字幕慣例」。）")
    return "\n".join(lines)
