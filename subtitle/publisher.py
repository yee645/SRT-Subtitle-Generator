# -*- coding: utf-8 -*-
"""
發佈包產生器：從審片結果組出「上傳 YouTube 用的文字素材」。

調研顯示多數創作者花大量時間剪片，標題、描述與標籤卻隨便帶過，
導致點擊率與搜尋排名低迷。本模組把已有的分析結果組裝成發佈包：

- 建議標題候選：按有效標題的常見型態各出一手（精華句／疑問句／
  數字句／關鍵字冠頭），剝句首贅詞、以完整子句湊到長度上限，
  不再是把逐字稿攔腰截斷（行動裝置標題只顯示前約 40 字）
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


# 標題候選的句首贅詞（口語開場、連接詞）：出現在句首就剝掉，
# 讓標題直接從賣點開始（「然後這台真的很猛」→「這台真的很猛」）。
_LEAD_FILLER_RE = re.compile(
    r"^(?:然後|接下來|接著|再來|所以|所以說|那|那個|就是|就是說|其實|"
    r"欸|呃|嗯|好|好啦|好了|OK|okay)+[，,、\s]*", re.I)
# 疑問句判定：結尾語氣詞或句首疑問詞（好奇缺口式標題點閱率較高）。
_QUESTION_ENDS = ("？", "?", "嗎", "呢", "吧")
_QUESTION_LEADS = ("為什麼", "怎麼", "如何", "是不是", "到底", "你知道",
                   "你有沒有", "什麼是")
# 數字句判定：阿拉伯數字或常見中文數量詞組（數字標題具體、易獲點擊）。
_NUMBER_RE = re.compile(r"[0-9０-９]+|[一二兩三四五六七八九十百千萬]{2,}")
# 子句切分（保留完整子句，不從句中硬截斷）。
_CLAUSE_SPLIT_RE = re.compile(r"[。！!？?；;，,、]+")


def _hard_cut(text: str, max_chars: int) -> str:
    """最後手段的硬截斷：不切在英文單字中間。"""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    # 截點若落在拉丁字詞中間，退到前一個完整字詞結尾。
    if re.match(r"[A-Za-z0-9]", text[max_chars:1 + max_chars] or ""):
        trimmed = re.sub(r"[A-Za-z0-9']+$", "", cut)
        if len(trimmed) >= 6:
            cut = trimmed
    return cut


def _clean_title(text: str, max_chars: int) -> str:
    """
    整理標題候選：去空白與句首贅詞後，以「完整子句」湊到長度上限。

    舊版直接 text[:max]，常把句子攔腰切斷（甚至切在英文單字中間）；
    改為逐子句累積、放不下就停在前一個子句結尾，讀起來才像標題。
    """
    text = re.sub(r"\s+", " ", (text or "").strip())
    text = _LEAD_FILLER_RE.sub("", text)
    if len(text) <= max_chars:
        return text.rstrip(_TRAILING_PUNCT)
    clauses = [c for c in _CLAUSE_SPLIT_RE.split(text) if c.strip()]
    built = ""
    for clause in clauses:
        candidate = (built + "，" + clause.strip()) if built else clause.strip()
        if len(candidate) > max_chars:
            break
        built = candidate
    if len(built) < 6:  # 第一個子句就超長（口語長句無標點）→ 硬截斷保底。
        built = _hard_cut(text, max_chars)
    return built.rstrip(_TRAILING_PUNCT)


def _is_question(text: str) -> bool:
    stripped = (text or "").rstrip(_TRAILING_PUNCT + "！!")
    return (stripped.endswith(_QUESTION_ENDS)
            or stripped.startswith(_QUESTION_LEADS))


def _top_keyword(items, extra_words: str = "") -> str:
    """挑一個冠頭關鍵字：自訂情緒詞（實際講到的）優先，其次高頻詞。"""
    text = " ".join(item["text"] for item in items
                    if item["kind"] == "speech")
    lowered = text.lower()
    for word in re.split(r"[,，、\s]+", extra_words or ""):
        word = word.strip()
        if word and word.lower() in lowered:
            return word
    for gram, count in _cjk_ngram_counts(text).most_common():
        if count >= _NGRAM_MIN_COUNT:
            return gram
    return ""


def suggest_titles(items, count: int = 3, max_chars: int = 40,
                   extra_words: str = "") -> list:
    """
    從段落清單組出多種型態的標題候選（依精彩分數排序、去重）。

    舊版只是把精彩段落文字截前 40 字，常常是半句話、實用價值低。
    現在按「有效標題」的常見型態各出一手，供創作者挑選或組合：

    1. 精華句：精彩分數最高段落，剝句首贅詞、以完整子句湊長度
    2. 疑問句：素材中實際講出的疑問（好奇缺口，觀眾想知道答案）
    3. 數字句：含具體數字的句子（「只要三百塊」比「很便宜」有力）
    4. 關鍵字冠頭：【關鍵字】＋精華子句（搜尋／辨識度導向）

    仍為純文字啟發式；不足 count 時以其餘保留段落補齊。
    """
    speech = [item for item in items
              if item["kind"] == "speech" and item["keep"] and
              item["text"].strip()]
    ranked = sorted(speech, key=lambda i: i.get("score", 0.0), reverse=True)
    highlights = [i for i in ranked if TAG_HIGHLIGHT in i.get("tags", ())]
    backfill = sorted(
        (i for i in speech if i not in highlights),
        key=lambda i: len(i["text"]), reverse=True)
    ordered = highlights + backfill

    def cleaned(item):
        return _clean_title(item["text"], max_chars)

    candidates = []

    # 1. 精華句（永遠當第一候選：最貼近影片賣點）。
    for item in ordered:
        title = cleaned(item)
        if len(title) >= 6:
            candidates.append(title)
            break

    # 2. 疑問句：從分數高到低找素材中真實講出的疑問。
    for item in ranked:
        if _is_question(item["text"]):
            title = _clean_title(item["text"], max_chars)
            if len(title) >= 6:
                # 疑問語氣是賣點，補回問號讓好奇缺口明確。
                if not title.endswith(("？", "?")):
                    title += "？"
                candidates.append(title)
                break

    # 3. 數字句：含具體數字的高分句。
    for item in ranked:
        if _NUMBER_RE.search(item["text"]):
            title = cleaned(item)
            if len(title) >= 6:
                candidates.append(title)
                break

    # 4. 關鍵字冠頭：【關鍵字】＋（與第一候選不同的）精華子句。
    keyword = _top_keyword(items, extra_words)
    if keyword:
        for item in ordered:
            body = _clean_title(item["text"], max(max_chars - len(keyword) - 2,
                                                  10))
            if len(body) >= 6:
                title = f"【{keyword}】{body}"[:max_chars]
                candidates.append(title)
                break

    # 去重（忽略結尾問號差異）後不足 count 再拿其餘段落補齊。
    def norm(text):
        return text.rstrip("？?")

    titles = []
    seen = set()
    def add(title):
        if len(title) >= 6 and norm(title) not in seen:
            titles.append(title)
            seen.add(norm(title))

    for title in candidates:
        add(title)
    for item in ordered:
        if len(titles) >= count:
            break
        add(cleaned(item))
    return titles[:count]


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


DEFAULT_DESC_SUMMARY_POINTS = 3
_DESC_LEAD_CHARS = 90
_DESC_POINT_CHARS = 40


def build_description(items, chapters=None, tags=None,
                      summary_points: int = DEFAULT_DESC_SUMMARY_POINTS,
                      extra_words: str = "") -> str:
    """
    組出**有結構的**描述草稿。

    舊版是 `kept[0]["text"][:60] + "……"`——把第一段講話硬截 60 字。實測
    產出的開頭是「那個 就是說 今天我們要來聊一個東西……」：句首贅詞沒剝
    （本工具別處明明就會剪掉口頭禪）、攔腰截斷、而且取的是**第一段**而
    不是**最精彩那段**。同一個模組替標題挑到了「怎麼樣讓你的影片節奏
    變得更好看」，描述卻用了最沒資訊量的一句，前後不一致。

    調研（中英文皆搜）給的結構很明確：**前 200 字元權重最高**、要用
    「清楚說明這支影片是什麼」的一句開頭，接著簡短摘要、章節、最後才是
    hashtag，而且**頻道樣板要放最下面不是最上面**。本函式就照這個順序組。

    句子的挑選與清理完全重用 suggest_titles 那套（依精彩分數排序、剝
    句首贅詞、以完整子句湊長度），不重新實作。
    """
    speech = [item for item in items or []
              if item.get("kind") == "speech" and item.get("keep")
              and (item.get("text") or "").strip()]
    if not speech:
        return ""

    ranked = sorted(speech, key=lambda i: i.get("score", 0.0), reverse=True)
    highlights = [i for i in ranked if TAG_HIGHLIGHT in i.get("tags", ())]
    # 沒有標記精彩時退回分數排序，仍然比「取第一段」有意義。
    pool = highlights or ranked

    # 開頭句優先挑**講到主題關鍵字**的那一句：前 200 字元權重最高，
    # 主題詞落在這裡才有意義，落在最後一段等於白放。挑不到就照分數。
    keyword = _top_keyword(items, extra_words)
    lead_item = pool[0]
    if keyword:
        for item in pool:
            if keyword.lower() in (item.get("text") or "").lower():
                lead_item = item
                break

    lead = _clean_title(lead_item["text"], _DESC_LEAD_CHARS)
    lines = []
    if lead:
        lines.append(lead + "。")

    # 摘要：再取幾個不同的重點句，讓說明欄有內容而不是只有一行。
    limit = max(int(summary_points or 0), 0)
    points = []
    seen = {lead}
    for item in pool:
        if len(points) >= limit:
            break
        if item is lead_item:
            continue
        point = _clean_title(item["text"], _DESC_POINT_CHARS)
        if point and point not in seen and len(point) >= 6:
            seen.add(point)
            points.append(point)
    if points:
        lines.append("")
        lines.append("這支影片會講到：")
        lines.extend(f"・{point}" for point in points)

    chapters_text = _format_chapters(chapters)
    if chapters_text:
        lines.append("")
        lines.append("章節：")
        lines.append(chapters_text)

    if tags:
        lines.append("")
        lines.append(" ".join(f"#{tag}" for tag in list(tags)[:5]))

    # 頻道樣板放最後——調研明講「boilerplate 放最下面，不要放最上面」，
    # 放最上面會把權重最高的前 200 字元佔掉。
    lines.append("")
    lines.append("（訂閱、社群連結與合作邀約請放在這一段，不要放最上面）")
    return "\n".join(lines)


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
                            settings["title_max_chars"], extra_words)
    tags = suggest_tags(items, settings["tag_count"], extra_words)

    lines = [f"===== 發佈包：{source_name or '素材'} =====", ""]

    lines.append(f"【建議標題（{len(titles)} 個候選，含精華句／疑問句／"
                 "數字句／關鍵字型態，挑一個或自行組合）】")
    if titles:
        lines.extend(f"{index}. {title}"
                     for index, title in enumerate(titles, start=1))
    else:
        lines.append("（沒有可用的段落文字，請先完成分析）")
    lines.append("")

    lines.append("【描述草稿（複製後自行潤飾）】")
    description = build_description(items, chapters, tags,
                                    extra_words=extra_words)
    lines.append(description or "（沒有可用的段落文字，請先完成分析）")
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
