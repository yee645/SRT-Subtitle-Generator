# -*- coding: utf-8 -*-
"""
發佈資訊健檢：標題、說明欄、hashtag 與標籤的上限與靜默失效。

調研（中英文皆搜）確認的規則，全部都是可機器檢查的硬性數字：

- **標題上限 100 字元**
- **說明欄上限 5,000 位元組（bytes），不是 5,000 個字**
- **hashtag 最多 15 個——超過 15 個，YouTube 會「忽略全部」而且不給任何
  提示**；建議只用 3~5 個，前 3 個會顯示在標題上方
- **標籤（tags）欄位總共 500 字元的預算**；建議 8~12 個

其中兩點特別容易踩：

1. **hashtag 超量是靜默失效**——不是超出的那幾個失效，而是**整批都不
   生效**，而且 YouTube 不會告訴你。創作者堆了 16 個想要更多曝光，結果
   得到零。這與 v1.32.0 的章節不顯示是同一種失敗模式。
2. **說明欄算的是位元組**——中文一個字佔 3 個位元組，所以中文創作者
   大約寫到 1,600 多個字就會撞上限。實測 1,690 個中文字 ＝ 5,070 位元組，
   用 `len()` 檢查會判定「沒超過」，實際上早就被擋下。**本模組因此一律
   以 UTF-8 位元組計算**，這對中文使用者是關鍵差異。

本工具自 v1.10.0 起就會產生發佈包（標題候選＋描述草稿＋標籤清單），
但**從未檢查過任何一項上限**——實測產出的發佈包裡沒有出現任何上限提醒。
而且最常見的情境是「我自己寫的說明欄，為什麼 hashtag 沒有作用」，
那份文字根本不是本工具產生的。

因此本模組吃的是**使用者直接貼上的文字**，不限於本工具的產出。

只報告不自動改：標題怎麼寫、要留哪幾個 hashtag 是創作決定——與
v1.26.0 以來的保守設計一致。

零 GUI 依賴，供發佈健檢對話框與 CLI 共用。
"""

from __future__ import annotations

import re
from typing import Optional

# 使用者可調參數（config["publishcheck"]）。預設值即 YouTube 的實際規則。
DEFAULT_PUBLISHCHECK = {
    "title_limit": 100,             # 標題字元上限
    "title_mobile_visible": 40,     # 行動裝置大致可見的標題長度
    "description_byte_limit": 5000,  # 說明欄上限（位元組，非字數）
    "max_hashtags": 15,             # 超過此數 YouTube 忽略全部 hashtag
    "recommended_hashtags": 5,      # 建議的 hashtag 數量上限
    "tag_char_limit": 500,          # 標籤欄位的總字元預算
}

_TITLE_RANGE = (20, 200)
_MOBILE_RANGE = (10, 100)
_DESC_RANGE = (500, 10000)
_MAX_TAG_RANGE = (1, 30)
_REC_TAG_RANGE = (1, 15)
_TAG_CHAR_RANGE = (100, 1000)

LEVEL_GOOD = "good"
LEVEL_WARN = "warn"
LEVEL_BAD = "bad"
_LEVEL_ICONS = {LEVEL_GOOD: "✔", LEVEL_WARN: "⚠", LEVEL_BAD: "✘"}

# hashtag：# 後接非空白且非 # 的字元。YouTube 的 hashtag 不能含空白，
# 中文、數字、底線皆可。
_HASHTAG_RE = re.compile(r"#([^\s#、，。！？；：]+)")
# 標籤輸入以逗號分隔（YouTube 後台就是這樣填）。
_TAG_SPLIT_RE = re.compile(r"[,，\n]+")


def _clamp(value, low, high, fallback, cast=float):
    try:
        value = cast(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_publishcheck_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出發佈健檢參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_PUBLISHCHECK)
    if config:
        raw.update({k: v for k, v in config.get("publishcheck", {}).items()
                    if v is not None})
    return {
        "title_limit": _clamp(raw.get("title_limit"), *_TITLE_RANGE,
                              DEFAULT_PUBLISHCHECK["title_limit"], cast=int),
        "title_mobile_visible": _clamp(
            raw.get("title_mobile_visible"), *_MOBILE_RANGE,
            DEFAULT_PUBLISHCHECK["title_mobile_visible"], cast=int),
        "description_byte_limit": _clamp(
            raw.get("description_byte_limit"), *_DESC_RANGE,
            DEFAULT_PUBLISHCHECK["description_byte_limit"], cast=int),
        "max_hashtags": _clamp(raw.get("max_hashtags"), *_MAX_TAG_RANGE,
                               DEFAULT_PUBLISHCHECK["max_hashtags"], cast=int),
        "recommended_hashtags": _clamp(
            raw.get("recommended_hashtags"), *_REC_TAG_RANGE,
            DEFAULT_PUBLISHCHECK["recommended_hashtags"], cast=int),
        "tag_char_limit": _clamp(
            raw.get("tag_char_limit"), *_TAG_CHAR_RANGE,
            DEFAULT_PUBLISHCHECK["tag_char_limit"], cast=int),
    }


def utf8_bytes(text: str) -> int:
    """
    算 UTF-8 位元組長度——說明欄的上限是位元組不是字數。

    這不是吹毛求疵：中文一個字佔 3 個位元組，用字數檢查會讓中文創作者
    在超過上限三倍時仍以為自己還有空間。
    """
    return len((text or "").encode("utf-8"))


def find_hashtags(text: str) -> list:
    """
    找出文字中的所有 hashtag（含重複），保留原始出現順序。

    回傳 ["#標籤", ...]。中文的標點（、，。等）視為分隔，不會被吃進標籤裡。
    """
    return [f"#{m.group(1)}" for m in _HASHTAG_RE.finditer(text or "")]


def split_tags(text: str) -> list:
    """把標籤欄位的輸入（逗號分隔）切成清單，去除空白與空項。"""
    return [part.strip() for part in _TAG_SPLIT_RE.split(text or "")
            if part.strip()]


def tags_char_count(tags: list) -> int:
    """
    算標籤欄位佔用的字元預算。

    YouTube 的標籤欄位是「一整串逗號分隔的文字」，因此分隔用的逗號也要
    算進去，否則會低估而放行實際上超量的輸入。
    """
    if not tags:
        return 0
    return sum(len(tag) for tag in tags) + (len(tags) - 1)


def _finding(level, title, detail, advice=""):
    return {"level": level, "title": title, "detail": detail, "advice": advice}


def analyze_publish(title: str = "", description: str = "", tags: str = "",
                    settings: Optional[dict] = None) -> dict:
    """
    檢查標題／說明欄／標籤，回傳 {"findings","ok","stats"}。

    三個欄位皆為選填——只貼說明欄進來檢查 hashtag 也是合理用法。
    """
    settings = settings or resolve_publishcheck_settings()
    findings = []
    title = (title or "").strip()
    description = description or ""
    hashtags = find_hashtags(description) + find_hashtags(title)
    tag_list = split_tags(tags)

    stats = {
        "title_chars": len(title),
        "description_bytes": utf8_bytes(description),
        "description_chars": len(description),
        "hashtag_count": len(hashtags),
        "hashtags": hashtags,
        "tag_count": len(tag_list),
        "tag_chars": tags_char_count(tag_list),
    }

    # ---- 標題 ----
    if title:
        if stats["title_chars"] > settings["title_limit"]:
            findings.append(_finding(
                LEVEL_BAD, "標題長度",
                f"{stats['title_chars']} 字元，超過上限 "
                f"{settings['title_limit']} 字元",
                "超過上限的標題無法儲存，YouTube 會直接擋下。請先精簡。"))
        elif stats["title_chars"] > settings["title_mobile_visible"]:
            findings.append(_finding(
                LEVEL_WARN, "標題長度",
                f"{stats['title_chars']} 字元，超過行動裝置大致可見的 "
                f"{settings['title_mobile_visible']} 字元",
                "手機上後面會被截斷成「…」。把最關鍵的字放在前面，"
                "讓人只看前半段就知道這支影片在講什麼。"))
        else:
            findings.append(_finding(
                LEVEL_GOOD, "標題長度",
                f"{stats['title_chars']} 字元，手機上可完整顯示"))

    # ---- 說明欄（位元組，不是字數）----
    if description.strip():
        limit = settings["description_byte_limit"]
        if stats["description_bytes"] > limit:
            findings.append(_finding(
                LEVEL_BAD, "說明欄長度",
                f"{stats['description_bytes']} 位元組"
                f"（{stats['description_chars']} 個字），超過上限 "
                f"{limit} 位元組",
                "YouTube 的說明欄上限算的是「位元組」而不是字數——"
                "中文一個字佔 3 個位元組，所以中文說明大約寫到 1,600 多字"
                "就會撞到上限。請刪減內容。"))
        else:
            findings.append(_finding(
                LEVEL_GOOD, "說明欄長度",
                f"{stats['description_bytes']} 位元組"
                f"（{stats['description_chars']} 個字），"
                f"未超過 {limit} 位元組上限"))

    # ---- hashtag：本健檢最重要的一項，因為它是靜默失效 ----
    if hashtags:
        unique = []
        duplicates = []
        seen = set()
        for tag in hashtags:
            key = tag.lower()
            if key in seen:
                if tag not in duplicates:
                    duplicates.append(tag)
            else:
                seen.add(key)
                unique.append(tag)

        if stats["hashtag_count"] > settings["max_hashtags"]:
            findings.append(_finding(
                LEVEL_BAD, "hashtag 數量",
                f"共 {stats['hashtag_count']} 個，超過上限 "
                f"{settings['max_hashtags']} 個",
                f"超過 {settings['max_hashtags']} 個時 YouTube 會「忽略全部」"
                "hashtag，而且不會給任何提示——你會得到零個生效的 hashtag。"
                f"請刪到 {settings['recommended_hashtags']} 個以內。"))
        elif stats["hashtag_count"] > settings["recommended_hashtags"]:
            findings.append(_finding(
                LEVEL_WARN, "hashtag 數量",
                f"共 {stats['hashtag_count']} 個，未超過上限但偏多"
                f"（建議 {settings['recommended_hashtags']} 個以內）",
                "一長串 hashtag 容易被判定為濫用而降低觸及；"
                "只留最相關的幾個效果更好。"))
        else:
            findings.append(_finding(
                LEVEL_GOOD, "hashtag 數量",
                f"共 {stats['hashtag_count']} 個，在建議範圍內"))

        if duplicates:
            findings.append(_finding(
                LEVEL_WARN, "hashtag 重複",
                "、".join(duplicates),
                "重複的 hashtag 只會算一次，卻仍佔用 15 個的額度。"))

        findings.append(_finding(
            LEVEL_GOOD, "顯示在標題上方的 hashtag",
            "、".join(unique[:3]) if unique else "（無）",
            "說明欄的前 3 個 hashtag 會以連結形式顯示在影片標題上方，"
            "請確認這 3 個正是你最想被看到的。"))

    # ---- 標籤（tags）----
    if tag_list:
        if stats["tag_chars"] > settings["tag_char_limit"]:
            findings.append(_finding(
                LEVEL_BAD, "標籤長度",
                f"{stats['tag_count']} 個標籤共 {stats['tag_chars']} 字元，"
                f"超過 {settings['tag_char_limit']} 字元的總預算",
                "超出預算的標籤會被截斷。標籤欄位是整串逗號分隔的文字，"
                "分隔的逗號也算在預算內；請刪掉重複或過於冷門的標籤。"))
        else:
            findings.append(_finding(
                LEVEL_GOOD, "標籤長度",
                f"{stats['tag_count']} 個標籤共 {stats['tag_chars']} 字元，"
                f"未超過 {settings['tag_char_limit']} 字元的總預算"))

    if not findings:
        findings.append(_finding(
            LEVEL_BAD, "發佈資訊", "標題、說明欄與標籤都是空的，沒有可檢查的內容。",
            "請至少貼上其中一項再執行健檢。"))

    ok = not any(f["level"] == LEVEL_BAD for f in findings)
    return {"findings": findings, "ok": ok, "stats": stats}


def format_publish_report(result: dict,
                          settings: Optional[dict] = None) -> str:
    """把發佈資訊健檢結果排成純文字報告（GUI 顯示與 CLI 輸出共用）。"""
    settings = settings or resolve_publishcheck_settings()
    lines = ["===== 發佈資訊健檢（標題／說明欄／hashtag／標籤）====="]
    findings = (result or {}).get("findings") or []
    if not findings:
        lines.append("・沒有可檢查的內容。")
        return "\n".join(lines)

    for finding in findings:
        icon = _LEVEL_ICONS.get(finding["level"], "・")
        lines.append(f"{icon} {finding['title']}：{finding['detail']}")
        if finding.get("advice"):
            lines.append(f"    建議：{finding['advice']}")

    stats = result.get("stats") or {}
    if stats:
        lines.append("")
        lines.append("統計：")
        lines.append(f"  標題 {stats.get('title_chars', 0)} 字元"
                     f"、說明欄 {stats.get('description_bytes', 0)} 位元組"
                     f"（{stats.get('description_chars', 0)} 個字）")
        lines.append(f"  hashtag {stats.get('hashtag_count', 0)} 個"
                     f"、標籤 {stats.get('tag_count', 0)} 個"
                     f"（{stats.get('tag_chars', 0)} 字元）")

    lines.append("")
    if result.get("ok"):
        lines.append("結論：發佈資訊符合 YouTube 的各項上限，可以直接使用。")
    else:
        lines.append("結論：有超過上限的項目——特別注意 hashtag 超量時 "
                     "YouTube 會「忽略全部」而且不給任何提示。請依上述項目調整。")
    return "\n".join(lines)
