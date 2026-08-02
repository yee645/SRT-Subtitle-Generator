# -*- coding: utf-8 -*-
"""
廣告友善度自查（黃標風險預檢）：上傳前先掃一遍逐字稿，而不是等黃標出現才申訴。

調研（中英文皆搜）顯示「黃標」（影片被標為不適合多數廣告主）是創作者社群
反覆抱怨的痛點：影片剪完上傳後才被系統標記，申訴要等、重新審查也要等，
而問題往往只是某幾句話用詞踩到 YouTube 的「廣告客戶青睞內容規範」。目前
社群流傳的自保作法是「先以不公開模式上傳、靜置 12~24 小時等系統掃描」——
等於每支影片都要多花一天。

本模組直接掃描本工具已經有的逐字稿 cue（不論來源：轉錄、對齊、匯入字幕
檔、手動編輯），標出可能觸發廣告友善度審查的用詞與其時間點，讓創作者在
上傳前幾分鐘內自查、決定要不要改口或重剪。

**設計上刻意避開「詞表比對」的天真作法**，因為調研有兩個關鍵發現：

1. **YouTube 從未公布官方「禁用詞列表」**——所有判定都源自「廣告客戶
   青睞內容規範」的主題分類，由 AI 掃描＋人工審查＋廣告主偏好共同決定。
   因此本模組的內建詞表明確定位為「依規範主題整理的自查起點」，不是
   官方清單，使用者可自行增補（自訂詞）與排除（誤判詞）。
2. **判定看的是「關鍵字叢集」而非單一詞**——業界分析指出，歷史頻道
   影片裡出現一次「槍」通常不會被標記，但短時間內密集出現一整串相關
   詞就會。因此本模組除了列出個別命中，更以**時間窗加權叢集分析**
   找出「短時間內風險詞密集」的高風險段落，這才是真正該處理的地方。

另外依 YouTube 2025 年 7 月粗俗用語政策更新，**開頭數秒**的用詞影響
特別大，本模組對開頭區間的命中另外獨立提醒。

本模組只做分析與提醒，**不自動消音或改動內容**：用詞是否要改屬於創作
判斷（同一個詞在教育、新聞、遊戲實況情境下的風險完全不同），自動處理
反而可能破壞內容原意——與凍結畫面偵測（v1.26.0）、畫面色偏健檢
（v1.28.0）的保守設計一致。

零 GUI 依賴，供字幕健檢對話框與 CLI 共用。
"""

from __future__ import annotations

import re
from typing import Optional

# 使用者可調參數（config["adfriendly"]）。
DEFAULT_ADFRIENDLY = {
    "window_seconds": 30.0,    # 叢集分析的時間窗長度（秒）
    "cluster_threshold": 3.0,  # 時間窗內加權分數達此值即標為高風險段落
    "opening_seconds": 7.0,    # 開頭區間長度（秒），此區間命中另外提醒
    "extra_terms": "",         # 使用者自訂補充詞（逗號或空白分隔）
    "ignore_terms": "",        # 使用者自訂排除詞（頻道情境下的誤判詞）
}

_WINDOW_RANGE = (10.0, 120.0)
_THRESHOLD_RANGE = (1.0, 10.0)
_OPENING_RANGE = (0.0, 30.0)

LEVEL_GOOD = "good"
LEVEL_WARN = "warn"
LEVEL_BAD = "bad"
_LEVEL_ICONS = {LEVEL_GOOD: "✔", LEVEL_WARN: "⚠", LEVEL_BAD: "✘"}

# 內建自查詞表：依 YouTube「廣告客戶青睞內容規範」的主題分類整理。
#
# 重要：這**不是**官方禁用詞清單（YouTube 從未公布此類清單），而是依
# 規範主題整理的自查起點；各頻道題材差異極大（新聞、遊戲、醫療、歷史
# 頻道本來就會大量提及部分詞彙），請務必用「自訂排除詞」剪裁成適合自己
# 頻道的清單。weight 反映該主題在規範中被限制營利的相對嚴格程度。
_CATEGORIES = {
    "粗俗用語": {
        "weight": 1.0,
        "advice": "開頭與標題避免粗話影響最大；中後段偶爾出現風險較低，"
                  "密集出現則建議改口或消音。",
        "terms": [
            "幹你", "他媽", "媽的", "靠北", "白痴", "智障", "垃圾話",
            "fuck", "shit", "bitch", "asshole", "bastard", "damn",
        ],
    },
    "暴力與血腥": {
        "weight": 1.2,
        "advice": "描述性提及通常可接受，但細節描寫或密集出現容易被限制"
                  "營利；新聞／歷史題材建議在描述欄註明教育用途。",
        "terms": [
            "殺人", "屠殺", "血腥", "斬首", "虐殺", "自殘", "砍死",
            "murder", "killing", "massacre", "gore", "bloodshed",
            "torture", "stabbing",
        ],
    },
    "槍械與武器": {
        "weight": 1.0,
        "advice": "教學、改造、販售相關內容風險最高；單純提及或歷史討論"
                  "通常無妨，但短時間內密集出現仍可能被歸類。",
        "terms": [
            "槍枝", "手槍", "步槍", "彈藥", "改造槍",
            "firearm", "handgun", "rifle", "ammunition", "silencer",
        ],
    },
    "毒品與管制藥物": {
        "weight": 1.3,
        "advice": "提及施用方式、取得管道風險最高；醫療或戒癮題材建議"
                  "明確標示教育／衛教立場。",
        "terms": [
            "毒品", "大麻", "海洛因", "安非他命", "吸毒", "嗑藥",
            "cocaine", "heroin", "meth", "marijuana", "overdose",
        ],
    },
    "菸酒": {
        "weight": 0.8,
        "advice": "此類提及通常只造成部分營利；若非內容主軸，減少重複"
                  "提及即可降低風險。",
        "terms": [
            "香菸", "電子菸", "抽菸", "酗酒", "醉酒",
            "cigarette", "vaping", "alcohol abuse", "drunk",
        ],
    },
    "成人與性暗示": {
        "weight": 1.5,
        "advice": "此類是限制營利最常見的原因之一；即使是玩笑或引用，"
                  "密集出現仍容易被歸類，建議改以中性用詞帶過。",
        "terms": [
            "色情", "情色", "裸體", "性愛", "援交",
            "porn", "nudity", "sexual", "nsfw",
        ],
    },
    "仇恨與貶抑": {
        "weight": 1.5,
        "advice": "針對族群、性別、宗教、國籍的貶抑用語風險最高且可能"
                  "同時違反社群規範，建議直接改寫。",
        "terms": [
            "歧視", "仇恨言論", "racist", "hate speech", "slur",
            "homophobic",
        ],
    },
    "危險行為": {
        "weight": 1.0,
        "advice": "挑戰、惡作劇類內容若可能被模仿，建議加上明確警語，"
                  "並避免描述具體作法。",
        "terms": [
            "自殺", "輕生", "危險挑戰", "跳樓",
            "suicide", "self-harm", "dangerous challenge",
        ],
    },
    "爭議與敏感事件": {
        "weight": 1.0,
        "advice": "重大災難、衝突、政治敏感事件的討論本身允許，但商業"
                  "廣告主偏好保守；建議在描述欄說明立場為新聞或評論。",
        "terms": [
            "恐怖攻擊", "戰爭罪", "種族清洗", "疫情陰謀",
            "terrorist attack", "war crime", "genocide",
        ],
    },
}

# 中日韓字元範圍（判斷詞條要用子字串比對還是英文單字邊界比對）。
_CJK_RE = re.compile(r"[㐀-鿿豈-﫿]")
# 使用者自訂詞表的分隔符：逗號（半形／全形）、頓號、分號、空白。
_SPLIT_RE = re.compile(r"[,，、;；\s]+")


def _clamp(value, low, high, fallback):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def parse_terms(text: str) -> list:
    """把使用者輸入的自訂詞字串拆成詞條清單（逗號／頓號／空白分隔）。"""
    if not text:
        return []
    return [part.strip() for part in _SPLIT_RE.split(str(text))
            if part.strip()]


def resolve_adfriendly_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出廣告友善度參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_ADFRIENDLY)
    if config:
        raw.update({k: v for k, v in config.get("adfriendly", {}).items()
                    if v is not None})
    return {
        "window_seconds": _clamp(raw.get("window_seconds"), *_WINDOW_RANGE,
                                 DEFAULT_ADFRIENDLY["window_seconds"]),
        "cluster_threshold": _clamp(
            raw.get("cluster_threshold"), *_THRESHOLD_RANGE,
            DEFAULT_ADFRIENDLY["cluster_threshold"]),
        "opening_seconds": _clamp(raw.get("opening_seconds"), *_OPENING_RANGE,
                                  DEFAULT_ADFRIENDLY["opening_seconds"]),
        "extra_terms": str(raw.get("extra_terms", "") or ""),
        "ignore_terms": str(raw.get("ignore_terms", "") or ""),
    }


def _find_matches(text: str, term: str) -> list:
    """
    找出詞條在文字中的所有命中位置，回傳 [(起, 迄)...]。

    含中日韓字元的詞條用子字串比對（中文沒有詞間空白）；純拉丁字母的
    詞條用單字邊界比對，避免 "ass" 誤中 "class"、"grass" 這類假陽性。
    """
    if not text or not term:
        return []
    if _CJK_RE.search(term):
        spans = []
        start = text.find(term)
        while start != -1:
            spans.append((start, start + len(term)))
            start = text.find(term, start + len(term))
        return spans
    pattern = r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])"
    return [m.span() for m in re.finditer(pattern, text, flags=re.IGNORECASE)]


def _count_occurrences(text: str, term: str) -> int:
    """計算詞條在文字中出現次數（不考慮與其他詞條的重疊）。"""
    return len(_find_matches(text, term))


def _resolve_overlaps(matches: list) -> list:
    """
    同一段文字被多個詞條命中時，只保留最具體的那個（長詞優先）。

    例如「他媽的」會同時命中詞表裡的「他媽」與「媽的」，若不處理會把
    一句話重複計兩次，虛增叢集風險分數、報告也出現重複行。作法是依
    「詞長遞減、權重遞減、位置遞增」排序後貪婪取用，與 publisher 既有的
    中文 n-gram 長詞優先慣例一致。

    參數 matches：[(起, 迄, 詞條, 分類, 權重)...]
    """
    ordered = sorted(matches, key=lambda m: (-(m[1] - m[0]), -m[4], m[0]))
    kept = []
    for match in ordered:
        start, end = match[0], match[1]
        if any(start < k[1] and k[0] < end for k in kept):
            continue  # 與已保留的命中重疊，捨棄較短／較弱者。
        kept.append(match)
    return sorted(kept, key=lambda m: m[0])


def _build_term_table(settings: dict) -> list:
    """
    組出實際要掃描的 (詞條, 分類, 權重) 清單。

    內建詞表＋使用者自訂補充詞（歸入「自訂」分類）；使用者排除詞
    （不分大小寫）在此階段就整批剔除，之後不再參與比對。
    """
    ignore = {t.lower() for t in parse_terms(settings.get("ignore_terms", ""))}
    table = []
    for category, spec in _CATEGORIES.items():
        for term in spec["terms"]:
            if term.lower() not in ignore:
                table.append((term, category, spec["weight"]))
    for term in parse_terms(settings.get("extra_terms", "")):
        if term.lower() not in ignore:
            table.append((term, "自訂", 1.0))
    return table


def _find_clusters(hits: list, window: float, threshold: float) -> list:
    """
    時間窗加權叢集分析：找出「短時間內風險詞密集」的高風險段落。

    調研指出 YouTube 分類器判斷的是關鍵字叢集而非單一詞（單獨出現一次
    通常不觸發，短時間內密集出現才會），因此逐一以每個命中為窗起點，
    累計窗內加權分數，達門檻者記為候選段落，最後合併重疊的候選。
    """
    if not hits or window <= 0:
        return []
    ordered = sorted(hits, key=lambda h: h["start"])
    candidates = []
    for index, hit in enumerate(ordered):
        window_end = hit["start"] + window
        inside = [h for h in ordered[index:] if h["start"] < window_end]
        score = sum(h["weight"] * h["count"] for h in inside)
        if score >= threshold:
            candidates.append({
                "start": hit["start"],
                "end": max(h["end"] for h in inside),
                "score": score,
                "terms": inside,
            })
    if not candidates:
        return []
    merged = [candidates[0]]
    for candidate in candidates[1:]:
        last = merged[-1]
        if candidate["start"] <= last["end"]:
            # 重疊：併成同一段，分數取較高者（代表該段最密集處的風險）。
            last["end"] = max(last["end"], candidate["end"])
            if candidate["score"] > last["score"]:
                last["score"] = candidate["score"]
            known = {(t["start"], t["term"]) for t in last["terms"]}
            last["terms"].extend(
                t for t in candidate["terms"]
                if (t["start"], t["term"]) not in known)
        else:
            merged.append(candidate)
    for cluster in merged:
        cluster["terms"].sort(key=lambda t: t["start"])
    return merged


def scan_cues(cues: list, settings: Optional[dict] = None) -> dict:
    """
    掃描字幕 cue 清單，回傳廣告友善度自查結果。

    回傳：
        hits: [{"start","end","term","category","weight","count","text"}...]
        category_counts: {分類: 命中次數}
        clusters: 高風險段落（時間窗加權叢集）
        opening_hits: 落在開頭區間內的命中
        total_score: 全片加權總分
    """
    settings = settings or resolve_adfriendly_settings()
    table = _build_term_table(settings)
    hits = []
    category_counts = {}
    for cue in cues or []:
        text = (cue.get("text") or "")
        if not text:
            continue
        # 先蒐集所有命中位置，再解重疊（長詞優先），避免「他媽的」這類
        # 一段文字同時命中多個詞條而被重複計數。
        raw_matches = []
        for term, category, weight in table:
            for start, end in _find_matches(text, term):
                raw_matches.append((start, end, term, category, weight))
        counted = {}
        for _s, _e, term, category, weight in _resolve_overlaps(raw_matches):
            key = (term, category, weight)
            counted[key] = counted.get(key, 0) + 1
        for (term, category, weight), count in counted.items():
            hits.append({
                "start": float(cue.get("start", 0.0)),
                "end": float(cue.get("end", 0.0)),
                "term": term,
                "category": category,
                "weight": weight,
                "count": count,
                "text": text,
            })
            category_counts[category] = category_counts.get(
                category, 0) + count
    hits.sort(key=lambda h: (h["start"], h["term"]))
    opening = settings["opening_seconds"]
    return {
        "hits": hits,
        "category_counts": category_counts,
        "clusters": _find_clusters(hits, settings["window_seconds"],
                                   settings["cluster_threshold"]),
        "opening_hits": [h for h in hits if h["start"] < opening],
        "total_score": sum(h["weight"] * h["count"] for h in hits),
        "opening_seconds": opening,
    }


def _format_time(seconds: float) -> str:
    seconds = max(float(seconds), 0.0)
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:d}:{secs:02d}"


def format_adfriendly_report(result: dict, max_hits: int = 20) -> str:
    """把自查結果排成純文字報告（GUI 顯示與 CLI 輸出共用）。"""
    lines = ["===== 廣告友善度自查（黃標風險） ====="]
    hits = (result or {}).get("hits") or []
    if not hits:
        lines.append("✔ 沒有掃到內建詞表與自訂詞中的風險用詞。")
        lines.append("")
        lines.append("注意：本檢查為依 YouTube「廣告客戶青睞內容規範」主題"
                     "整理的自查工具，YouTube 從未公布官方禁用詞清單，"
                     "實際判定另包含畫面、標題、縮圖與整體脈絡，"
                     "通過本檢查不等於保證不會被標記。")
        return "\n".join(lines)

    clusters = result.get("clusters") or []
    opening_hits = result.get("opening_hits") or []

    if clusters:
        lines.append(f"✘ 高風險段落 {len(clusters)} 處（短時間內風險用詞密集，"
                     "這是最該優先處理的地方）：")
        for cluster in clusters:
            terms = "、".join(
                dict.fromkeys(t["term"] for t in cluster["terms"]))
            lines.append(
                f"    {_format_time(cluster['start'])}~"
                f"{_format_time(cluster['end'])}"
                f"（風險分數 {cluster['score']:.1f}）：{terms}")
        lines.append("    建議：平台判定看的是短時間內的關鍵字叢集而非單一詞；"
                     "把這些段落改口、剪掉或分散開來，"
                     "降風險的效果遠大於改動零星出現的單一用詞。")
    else:
        lines.append("✔ 沒有偵測到風險用詞密集的高風險段落。")

    if opening_hits:
        opening = result.get("opening_seconds", 7.0)
        terms = "、".join(dict.fromkeys(h["term"] for h in opening_hits))
        lines.append(f"⚠ 開頭 {opening:.0f} 秒內出現風險用詞：{terms}")
        lines.append("    建議：依 YouTube 2025 年 7 月粗俗用語政策更新，"
                     "開頭數秒的用詞對營利判定影響特別大，"
                     "建議優先處理這幾句。")

    counts = result.get("category_counts") or {}
    if counts:
        lines.append("")
        lines.append("分類統計：")
        for category, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            advice = _CATEGORIES.get(category, {}).get("advice", "")
            lines.append(f"  ・{category}：{count} 次")
            if advice:
                lines.append(f"      {advice}")

    lines.append("")
    lines.append(f"逐項命中（共 {len(hits)} 項"
                 + (f"，以下列出前 {max_hits} 項" if len(hits) > max_hits
                    else "") + "）：")
    for hit in hits[:max_hits]:
        snippet = hit["text"].replace("\n", " ")
        if len(snippet) > 40:
            snippet = snippet[:40] + "..."
        suffix = f" x{hit['count']}" if hit["count"] > 1 else ""
        lines.append(f"  [{_format_time(hit['start'])}] "
                     f"{hit['term']}{suffix}（{hit['category']}）：{snippet}")

    lines.append("")
    lines.append(f"結論：全片風險分數 {result.get('total_score', 0.0):.1f}，"
                 f"高風險段落 {len(clusters)} 處。")
    lines.append("注意：本檢查為依 YouTube「廣告客戶青睞內容規範」主題整理"
                 "的自查工具，YouTube 從未公布官方禁用詞清單，實際判定另"
                 "包含畫面、標題、縮圖與整體脈絡；命中不代表一定被標記，"
                 "未命中也不保證不會被標記。頻道題材本來就會提及的詞"
                 "（如新聞、歷史、醫療頻道）請加入「排除詞」避免重複誤判。")
    return "\n".join(lines)
