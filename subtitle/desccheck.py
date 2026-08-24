# -*- coding: utf-8 -*-
"""
說明欄結構健檢：說明欄寫了，但寫在對的地方嗎？

調研（中英文皆搜）指出說明欄的規則已經從「塞關鍵字」變成「結構與前
幾行」，而且有明確、可機器檢查的門檻：

- **前兩三行就是全部**。「搜尋結果頁可能只顯示說明欄的第一行」，前
  200 字元是「above the fold」；主要關鍵字要落在**前 25 個字內**、
  **前 40 個字元內**才不會在行動裝置被截斷。
- **關鍵字堆砌會被當成垃圾內容**：「堆關鍵字的時代已經結束，那個做法
  會觸發垃圾內容分類並傷害頻道權重」。
- **要有結構，不要一整塊**：「把可用的篇幅用清楚的結構寫完，而不是寫
  成一大段密密麻麻的文字」。
- 中文官方說明另外點名**章節來自說明欄的時間戳記**；行動版還要點一下
  標題才看得到說明欄，所以前幾行更關鍵。

本工具既有的「發佈資訊健檢」（v1.36.0）只檢查**硬性上限**——標題 100
字元、說明欄 5000 位元組、hashtag 15 個、標籤 500 字元。那些是「會不會
被系統拒絕」；本模組看的是**寫得對不對**，兩者不重疊：

| 既有的發佈資訊健檢（v1.36） | 本模組 |
|------------------------------|--------|
| 說明欄有沒有超過 5000 位元組 | 前 200 字元有沒有實質內容 |
| hashtag 有沒有超過 15 個 | 同一個詞是不是重複到像堆砌 |
| 標籤字元數 | 有沒有時間戳記章節、有沒有分段 |

時間戳記解析重用既有的 `chaptercheck.parse_chapters`，hashtag 擷取重用
`publishcheck.find_hashtags`，本模組不重新實作任何一邊。

只報告不自動改：說明欄要怎麼寫是創作決定。

零 GUI 依賴，供發佈資訊健檢視窗與 CLI 共用。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Optional

from subtitle.chaptercheck import parse_chapters
from subtitle.publishcheck import find_hashtags

DEFAULT_DESCCHECK = {
    # 「above the fold」的字元數：搜尋結果與收合狀態大約只看得到這麼多。
    "fold_chars": 200,
    # 說明欄短於這個字元數視為幾乎沒寫。
    "min_chars": 100,
    # 同一個詞出現次數佔全部詞數的比例超過此值，視為堆砌。
    "max_term_ratio": 0.05,
    # 開頭被連結／帳號／交際語佔掉超過此比例，視為「沒在講影片內容」。
    "max_plumbing_ratio": 0.55,
    # 一個詞至少要重複這麼多次才可能被判為堆砌（短說明欄不誤判）。
    "min_repeat": 4,
    # 影片長於這個秒數卻沒有章節時提醒（短片本來就不需要章節）。
    "chapter_hint_seconds": 300.0,
}

_FOLD_RANGE = (80, 500)
_MIN_CHARS_RANGE = (0, 1000)
_RATIO_RANGE = (0.01, 0.5)
_REPEAT_RANGE = (2, 50)
_SECONDS_RANGE = (0.0, 7200.0)

LEVEL_GOOD = "good"
LEVEL_WARN = "warn"
LEVEL_BAD = "bad"
_LEVEL_ICONS = {LEVEL_GOOD: "✔", LEVEL_WARN: "⚠", LEVEL_BAD: "✘"}

# 常見的樣板句：這些字出現在最前面代表「開頭被交際語佔掉了」，
# 而不是在講這支影片是什麼。
_BOILERPLATE = [
    "訂閱", "追蹤", "按讚", "小鈴鐺", "開啟通知", "留言告訴我",
    "歡迎來到", "大家好", "哈囉", "合作邀約", "商業合作",
    "subscribe", "follow me", "like and subscribe", "hit the bell",
    "welcome back", "what's up guys",
]

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
# 社群帳號與聯絡方式：開頭被這些佔滿時，等於沒講這支影片是什麼。
_HANDLE_RE = re.compile(
    r"(?:instagram|facebook|discord|twitter|threads|tiktok|line|email|ig|fb)"
    r"\s*[:：]?\s*\S*", re.IGNORECASE)
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'’-]{2,}")
_CJK_RUN = re.compile(r"[一-鿿]{2,}")


def _clamp(value, low, high, fallback, cast=float):
    try:
        value = cast(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_desccheck_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出說明欄健檢參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_DESCCHECK)
    if config:
        raw.update({k: v for k, v in config.get("desccheck", {}).items()
                    if v is not None})
    return {
        "fold_chars": _clamp(raw.get("fold_chars"), *_FOLD_RANGE,
                             DEFAULT_DESCCHECK["fold_chars"], int),
        "min_chars": _clamp(raw.get("min_chars"), *_MIN_CHARS_RANGE,
                            DEFAULT_DESCCHECK["min_chars"], int),
        "max_term_ratio": _clamp(raw.get("max_term_ratio"), *_RATIO_RANGE,
                                 DEFAULT_DESCCHECK["max_term_ratio"]),
        "max_plumbing_ratio": _clamp(
            raw.get("max_plumbing_ratio"), 0.1, 1.0,
            DEFAULT_DESCCHECK["max_plumbing_ratio"]),
        "min_repeat": _clamp(raw.get("min_repeat"), *_REPEAT_RANGE,
                             DEFAULT_DESCCHECK["min_repeat"], int),
        "chapter_hint_seconds": _clamp(
            raw.get("chapter_hint_seconds"), *_SECONDS_RANGE,
            DEFAULT_DESCCHECK["chapter_hint_seconds"]),
    }


def fold_text(description: str, fold_chars: int = 200) -> str:
    """取出「收合前看得到」的那一段文字。"""
    return (description or "")[:max(int(fold_chars), 1)]


def plumbing_spans(text: str) -> list:
    """
    找出「社群管線」佔掉的字元範圍：連結、hashtag、帳號、樣板交際語。

    為什麼不用「剩幾個字」判斷：樣板詞表永遠不可能列全，實測一段全是
    「歡迎來到我的頻道／訂閱按讚小鈴鐺／IG／FB／Discord／合作邀約」的
    開頭，扣掉詞表後仍殘留 50 個字（「我的頻道記得開啟…我的ig我的
    facebook加入我的discord請來信」），字數看起來很多、資訊量卻是零。
    改成量**管線佔了開頭的多少比例**就穩健得多——連結與帳號本身就是
    最大宗，不需要把每句客套話都列出來。
    """
    spans = []
    for pattern in (_URL_RE, re.compile(r"#\S+"), _HANDLE_RE):
        for match in pattern.finditer(text or ""):
            spans.append((match.start(), match.end()))
    lowered = (text or "").lower()
    for phrase in _BOILERPLATE:
        start = lowered.find(phrase.lower())
        while start != -1:
            spans.append((start, start + len(phrase)))
            start = lowered.find(phrase.lower(), start + 1)
    return spans


def plumbing_ratio(text: str) -> float:
    """社群管線佔這段文字的字元比例（0~1）。"""
    text = text or ""
    if not text.strip():
        return 0.0
    covered = set()
    for start, end in plumbing_spans(text):
        covered.update(range(max(start, 0), min(end, len(text))))
    # 只算非空白字元，避免換行與空格灌水分母。
    meaningful = {i for i, ch in enumerate(text) if not ch.isspace()}
    if not meaningful:
        return 0.0
    return len(covered & meaningful) / len(meaningful)


def substance_of(text: str) -> str:
    """
    去掉連結、hashtag 與樣板交際語之後，剩下的實質文字。

    這是判斷「開頭到底有沒有在講這支影片是什麼」的關鍵——一段全是
    「訂閱按讚小鈴鐺＋IG 連結」的開頭，字數再多也沒有傳達任何資訊。
    """
    body = _URL_RE.sub(" ", text or "")
    body = re.sub(r"#\S+", " ", body)
    lowered = body.lower()
    for phrase in _BOILERPLATE:
        lowered = lowered.replace(phrase.lower(), " ")
    # 只留下中文與拉丁文字，去掉標點與空白後計算實質長度。
    return re.sub(r"[^一-鿿A-Za-z0-9]", "", lowered)


def extract_terms(text: str) -> list:
    """
    擷取用來判斷堆砌的詞：拉丁單字＋中文連續字串。

    中文沒有詞間空白，這裡用「連續中文字串」當作詞的近似——堆砌的
    特徵是**同一串字反覆整段出現**，這個近似抓得到。
    """
    body = _URL_RE.sub(" ", text or "")
    body = re.sub(r"#\S+", " ", body)
    terms = [m.group(0).lower() for m in _LATIN_WORD.finditer(body)]
    terms += [m.group(0) for m in _CJK_RUN.finditer(body)]
    return terms


def find_stuffed_terms(text: str, settings: Optional[dict] = None) -> list:
    """
    找出重複到像關鍵字堆砌的詞，回傳 [(詞, 次數, 佔比), ...]。

    同時要求「重複夠多次」與「佔比夠高」：只看佔比會在很短的說明欄
    誤判（總共三個詞，其中一個出現兩次就佔 66%）。
    """
    settings = settings or resolve_desccheck_settings()
    terms = extract_terms(text)
    if not terms:
        return []
    counts = Counter(terms)
    total = len(terms)
    rows = []
    for term, count in counts.items():
        ratio = count / total
        if (count >= settings["min_repeat"]
                and ratio > settings["max_term_ratio"]):
            rows.append((term, count, ratio))
    rows.sort(key=lambda r: -r[1])
    return rows


def paragraph_count(description: str) -> int:
    """說明欄被分成幾段（以空行或換行切分後的非空段落數）。"""
    parts = [p for p in re.split(r"\n\s*", description or "") if p.strip()]
    return len(parts)


def _finding(level, title, detail, advice=""):
    return {"level": level, "title": title, "detail": detail, "advice": advice}


def analyze_description(description: str = "", duration: float = 0.0,
                        config: Optional[dict] = None) -> dict:
    """
    對說明欄做結構健檢，回傳 {"findings","ok","stats"}。

    純文字分析，不碰 ffmpeg；duration 只用來判斷「這支影片長到該有
    章節了嗎」，沒給就跳過那一項。
    """
    settings = resolve_desccheck_settings(config)
    description = description or ""
    text_len = len(description.strip())
    findings = []

    # 1. 根本沒寫或幾乎沒寫。
    if text_len == 0:
        findings.append(_finding(
            LEVEL_BAD, "說明欄內容",
            "說明欄是空的",
            "說明欄是演算法與觀眾理解這支影片的主要文字來源，"
            "留空等於白白丟掉一個訊號。"))
        return {"findings": findings, "ok": False,
                "stats": {"chars": 0, "paragraphs": 0, "chapters": 0}}

    fold = fold_text(description, settings["fold_chars"])
    fold_substance = substance_of(fold)
    chapters, _errors = parse_chapters(description)
    hashtags = find_hashtags(description)
    paragraphs = paragraph_count(description)
    stuffed = find_stuffed_terms(description, settings)

    stats = {
        "chars": text_len,
        "fold_substance": len(fold_substance),
        "paragraphs": paragraphs,
        "chapters": len(chapters),
        "hashtags": len(hashtags),
        "stuffed": stuffed,
        "plumbing": round(plumbing_ratio(fold), 3),
    }

    if text_len < settings["min_chars"]:
        findings.append(_finding(
            LEVEL_WARN, "說明欄內容",
            f"說明欄只有 {text_len} 字元"
            f"（建議至少 {settings['min_chars']} 字元）",
            "篇幅本身不是目的，但太短通常代表沒有交代這支影片在講什麼。"))
    else:
        findings.append(_finding(
            LEVEL_GOOD, "說明欄內容", f"說明欄有 {text_len} 字元"))

    # 2. 開頭（收合前）有沒有實質內容——這是本模組最重要的一項。
    # 用「管線佔比」而不是「剩幾個字」：詞表永遠列不全，但連結與帳號
    # 本身就是最大宗，量比例才抓得到「開頭被社群管線佔滿」。
    plumbing = plumbing_ratio(fold)
    stats_plumbing = round(plumbing, 3)
    if plumbing > settings["max_plumbing_ratio"] or len(fold_substance) < 20:
        findings.append(_finding(
            LEVEL_WARN, "開頭實質內容",
            f"前 {settings['fold_chars']} 字元有 {plumbing * 100:.0f}% 是"
            f"連結、hashtag 或「訂閱按讚」這類交際語"
            f"（建議 {settings['max_plumbing_ratio'] * 100:.0f}% 以下）",
            "搜尋結果頁可能只顯示說明欄的第一行，行動版還要點一下標題"
            "才看得到說明欄——開頭那兩三句就是全部。把「這支影片在講"
            "什麼、為什麼值得看」寫在最前面，訂閱與連結往後放。"))
    else:
        findings.append(_finding(
            LEVEL_GOOD, "開頭實質內容",
            f"開頭只有 {plumbing * 100:.0f}% 是連結與交際語，"
            "有交代影片主題"))

    # 3. 關鍵字堆砌。
    if stuffed:
        listed = "、".join(
            f"「{term}」{count} 次（{ratio * 100:.0f}%）"
            for term, count, ratio in stuffed[:3])
        findings.append(_finding(
            LEVEL_WARN, "關鍵字堆砌",
            f"有 {len(stuffed)} 個詞重複到不太自然：{listed}",
            "堆關鍵字的時代已經結束——那個做法會觸發垃圾內容分類並"
            "傷害頻道權重。關鍵字要自然地寫在讀得通的句子裡。"))
    else:
        findings.append(_finding(
            LEVEL_GOOD, "關鍵字堆砌", "沒有偵測到不自然的重複用詞"))

    # 4. 章節（時間戳記）——長片才提醒。
    if duration and duration >= settings["chapter_hint_seconds"]:
        if chapters:
            findings.append(_finding(
                LEVEL_GOOD, "章節時間戳記",
                f"說明欄有 {len(chapters)} 個時間戳記章節"))
        else:
            findings.append(_finding(
                LEVEL_WARN, "章節時間戳記",
                f"影片長 {duration / 60:.0f} 分鐘，但說明欄沒有時間戳記",
                "章節就是從說明欄的時間戳記產生的。長片加上章節，"
                "觀眾能直接跳到要看的段落，停留時間反而更長。"
                "本工具的「YouTube 章節」功能可以直接產生這段文字。"))

    # 5. 有沒有分段。
    if paragraphs <= 1 and text_len >= settings["min_chars"]:
        findings.append(_finding(
            LEVEL_WARN, "分段結構",
            "整份說明欄是一整塊沒有換行的文字",
            "把篇幅用清楚的結構寫完，而不是寫成一大段密密麻麻的文字——"
            "分成幾段（簡介／重點／連結／章節）才讀得下去。"))
    else:
        findings.append(_finding(
            LEVEL_GOOD, "分段結構", f"說明欄分成 {paragraphs} 段"))

    ok = not any(f["level"] == LEVEL_BAD for f in findings)
    return {"findings": findings, "ok": ok, "stats": stats}


def format_desc_report(result: dict,
                       settings: Optional[dict] = None) -> str:
    """把說明欄結構健檢結果排成純文字報告。"""
    settings = settings or resolve_desccheck_settings()
    lines = ["===== 說明欄結構健檢（寫了，但寫在對的地方嗎）====="]
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
            f"  全長 {stats.get('chars', 0)} 字元、分成 "
            f"{stats.get('paragraphs', 0)} 段、"
            f"{stats.get('chapters', 0)} 個章節、"
            f"{stats.get('hashtags', 0)} 個 hashtag")
        lines.append(
            f"  收合前有 {stats.get('plumbing', 0) * 100:.0f}% 是連結與"
            f"交際語，實質內容 {stats.get('fold_substance', 0)} 字")

    lines.append("")
    if not result.get("ok"):
        lines.append("結論：說明欄有一定要處理的問題。")
    elif any(f["level"] == LEVEL_WARN for f in findings):
        lines.append("結論：說明欄可以再調整——重點是把「這支影片在講什麼」"
                     "放到最前面，那幾句才是大多數人唯一會看到的部分。")
    else:
        lines.append("結論：說明欄的結構沒有問題。")
    return "\n".join(lines)
