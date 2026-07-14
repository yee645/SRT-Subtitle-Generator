# -*- coding: utf-8 -*-
"""
發佈包產生器：從審片結果組出「上傳 YouTube 用的文字素材」。

調研顯示多數創作者花大量時間剪片，標題、描述與標籤卻隨便帶過，
導致點擊率與搜尋排名低迷。本模組把已有的分析結果組裝成發佈包：

- 建議標題候選：取精彩分數最高的段落文字（行動裝置標題只顯示前
  約 40 字、關鍵字越前面權重越高——候選皆已截到可調的長度上限）
- 描述草稿：開場鉤子（第一個保留段落）＋建議章節＋hashtag 行
- 建議標籤：素材中實際高頻出現的詞（中文 n-gram 頻率統計＋
  英文詞頻＋使用者自訂情緒詞），供上傳時挑選增刪

純文字啟發式、不依賴任何機器學習模型；本模組零 GUI 依賴，
供審片助手與 CLI 共用。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Optional

from .review import TAG_HIGHLIGHT

# 發佈包可調參數的預設值（config["publish"]）。
DEFAULT_PUBLISH = {
    "title_candidates": 3,   # 建議標題數量
    "title_max_chars": 40,   # 標題長度上限（行動裝置可見長度）
    "tag_count": 15,         # 建議標籤數量
}
_TITLE_CANDIDATES_RANGE = (2, 6)
_TITLE_MAX_CHARS_RANGE = (20, 60)
_TAG_COUNT_RANGE = (5, 30)

# 中文標籤 n-gram 統計的參數：至少出現次數與詞長範圍。
_NGRAM_MIN_COUNT = 3
_NGRAM_SIZES = (4, 3, 2)  # 長詞優先，避免「螢幕保護」被「螢幕」蓋掉

# 中文虛詞（n-gram 含任一字即不當標籤）與英文停用詞。
_CJK_STOPCHARS = set("的了是我你他她它這那就都也很有在不個嗎吧呢啊喔欸呃嗯"
                     "和跟與或但因為所以如果然後還要會能可以沒有什麼怎麼")
_LATIN_STOPWORDS = {
    "the", "and", "for", "you", "that", "this", "with", "have", "are",
    "was", "but", "not", "they", "his", "her", "she", "him", "can",
    "will", "just", "your", "what", "when", "how", "all", "out", "get",
    "like", "one", "about", "really", "going", "know", "yeah", "okay",
}

_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9']{2,}")
_CJK_RUN_RE = re.compile(r"[一-鿿]+")
# 標題候選結尾要去掉的標點。
_TRAILING_PUNCT = "，。、；：,.;: "


def _clamp_int(value, low: int, high: int, fallback: int) -> int:
    try:
        value = int(float(value))
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_publish_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出發佈包參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_PUBLISH)
    if config:
        raw.update({k: v for k, v in config.get("publish", {}).items()
                   if v is not None})
    return {
        "title_candidates": _clamp_int(
            raw.get("title_candidates"), *_TITLE_CANDIDATES_RANGE,
            fallback=DEFAULT_PUBLISH["title_candidates"]),
        "title_max_chars": _clamp_int(
            raw.get("title_max_chars"), *_TITLE_MAX_CHARS_RANGE,
            fallback=DEFAULT_PUBLISH["title_max_chars"]),
        "tag_count": _clamp_int(
            raw.get("tag_count"), *_TAG_COUNT_RANGE,
            fallback=DEFAULT_PUBLISH["tag_count"]),
    }


def _clean_title(text: str, max_chars: int) -> str:
    """整理標題候選：去頭尾空白、截長度上限、去結尾殘標點。"""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) > max_chars:
        text = text[:max_chars]
    return text.rstrip(_TRAILING_PUNCT)


def suggest_titles(items, count: int = 3, max_chars: int = 40) -> list:
    """
    從段落清單挑出建議標題候選（依精彩分數排序、去重）。

    精彩段落是「觀眾反應最大的內容」，其文字通常最貼近影片賣點；
    不足時以較長的保留段落補齊。
    """
    speech = [item for item in items
              if item["kind"] == "speech" and item["keep"] and
              item["text"].strip()]
    ranked = sorted(speech, key=lambda i: i.get("score", 0.0), reverse=True)
    highlights = [i for i in ranked if TAG_HIGHLIGHT in i.get("tags", ())]
    backfill = sorted(
        (i for i in speech if i not in highlights),
        key=lambda i: len(i["text"]), reverse=True)

    titles = []
    for item in highlights + backfill:
        title = _clean_title(item["text"], max_chars)
        if len(title) < 6 or title in titles:
            continue
        titles.append(title)
        if len(titles) >= count:
            break
    return titles


def _cjk_ngram_counts(text: str) -> Counter:
    """統計中文 n-gram 頻率（長詞優先、跳過含虛詞的組合）。"""
    counts = Counter()
    runs = _CJK_RUN_RE.findall(text)
    for size in _NGRAM_SIZES:
        for run in runs:
            for i in range(len(run) - size + 1):
                gram = run[i:i + size]
                if any(ch in _CJK_STOPCHARS for ch in gram):
                    continue
                counts[gram] += 1
    return counts


def suggest_tags(items, tag_count: int = 15,
                 extra_words: str = "") -> list:
    """
    從素材文字統計出建議標籤。

    組成（依序、去重）：
    1. 使用者自訂情緒詞中實際出現在素材裡的（頻道口號、產品名最優先）
    2. 中文高頻 n-gram（長詞優先、出現 ≥3 次、含虛詞者剔除，
       且不與已入選的長標籤重疊）
    3. 英文高頻詞（≥3 個字母、去停用詞）

    標籤取自素材中實際講到的詞，上傳前可自行增刪。
    """
    text = " ".join(item["text"] for item in items
                    if item["kind"] == "speech")
    lowered = text.lower()
    tags = []

    for word in re.split(r"[,，、\s]+", extra_words or ""):
        word = word.strip()
        if word and word.lower() in lowered and word not in tags:
            tags.append(word)

    cjk_counts = _cjk_ngram_counts(text)
    for gram, count in cjk_counts.most_common():
        if count < _NGRAM_MIN_COUNT or len(tags) >= tag_count:
            break
        # 已被較長標籤涵蓋的子字串不重複列（「保護」vs「螢幕保護」）。
        if any(gram in existing for existing in tags):
            continue
        tags.append(gram)

    latin_counts = Counter(
        word.lower() for word in _LATIN_WORD_RE.findall(text)
        if word.lower() not in _LATIN_STOPWORDS)
    for word, count in latin_counts.most_common():
        if count < _NGRAM_MIN_COUNT or len(tags) >= tag_count:
            break
        if word not in tags:
            tags.append(word)
    return tags[:tag_count]


def _format_chapters(chapters) -> str:
    lines = []
    for chapter in chapters or []:
        minutes, secs = divmod(int(chapter["start"]), 60)
        hours, minutes = divmod(minutes, 60)
        stamp = (f"{hours}:{minutes:02d}:{secs:02d}" if hours
                 else f"{minutes}:{secs:02d}")
        lines.append(f"{stamp} {chapter['title']}")
    return "\n".join(lines)


def build_publish_pack(items, settings: Optional[dict] = None,
                       chapters=None, source_name: str = "",
                       extra_words: str = "", ad_breaks=None) -> str:
    """
    組出完整發佈包文字（標題候選＋描述草稿＋標籤清單）。

    參數：
        items: analyze() 的段落清單。
        settings: resolve_publish_settings() 的結果；省略用預設。
        chapters: build_chapters() 的結果（可省略）。
        source_name: 素材檔名（僅作抬頭註記）。
        extra_words: 使用者自訂情緒詞（審片設定共用，作優先標籤）。
        ad_breaks: suggest_ad_breaks() 的結果（可省略；影片不足
                   8 分鐘時本來就是空清單，該區塊自動略去）。
    """
    settings = settings or resolve_publish_settings()
    titles = suggest_titles(items, settings["title_candidates"],
                            settings["title_max_chars"])
    tags = suggest_tags(items, settings["tag_count"], extra_words)

    kept = [item for item in items
            if item["kind"] == "speech" and item["keep"]]
    hook = re.sub(r"\s+", " ", kept[0]["text"].strip())[:60] if kept else ""

    lines = [f"===== 發佈包：{source_name or '素材'} =====", ""]

    lines.append(f"【建議標題（{len(titles)} 個候選，挑一個或自行組合；"
                 "關鍵字放前 40 字內）】")
    if titles:
        lines.extend(f"{index}. {title}"
                     for index, title in enumerate(titles, start=1))
    else:
        lines.append("（沒有可用的段落文字，請先完成分析）")
    lines.append("")

    lines.append("【描述草稿（複製後自行潤飾）】")
    if hook:
        lines.append(hook + "……")
        lines.append("")
    chapters_text = _format_chapters(chapters)
    if chapters_text:
        lines.append("章節：")
        lines.append(chapters_text)
        lines.append("")
    if tags:
        lines.append(" ".join(f"#{tag}" for tag in tags[:5]))
        lines.append("")

    lines.append(f"【建議標籤（{len(tags)} 個，取自素材中實際講到的高頻詞，"
                 "上傳時可自行增刪）】")
    lines.append(", ".join(tags) if tags else "（素材中沒有足夠的高頻詞）")

    # mid-roll 廣告插入點：放在自然停頓處才容易被投放（不足 8 分鐘略去）。
    if ad_breaks:
        from .adbreaks import format_ad_breaks
        lines.append("")
        lines.append("【mid-roll 廣告插入點（8 分鐘以上影片適用）】")
        lines.append(format_ad_breaks(ad_breaks))
    return "\n".join(lines)
