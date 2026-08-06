# -*- coding: utf-8 -*-
"""
開場健檢：檢查影片前段到底在講什麼、多久才進正題。

調研（中英日文皆搜，日文資料最完整）一致指出同一件事：**開頭十幾秒
決定觀眾要不要看下去**，而流失的主因幾乎都是同一組東西——冗長的打
招呼、自我介紹、頻道宣傳、開場就先要訂閱、以及跟主題無關的閒聊。
業界建議是「15 秒內要讓觀眾知道這支影片能給他什麼」，並且**把訂閱
提醒移到影片後段**，因為對還沒被說服的新觀眾來說，一開場就要訂閱
只會提前趕走他。

本工具已有 46 項功能，卻**沒有任何一項在看開頭講了什麼**：
- 「一鍵去頭尾」偵測的是**靜音／黑畫面**的廢秒，講滿話的開場廢話抓不到
- 「廣告友善度」只在開頭區間找**粗話**
- 「字幕健檢」只看閱讀速度與行數

實測一段 22 秒全是打招呼＋自我介紹＋訂閱提醒的開場，上述三項健檢
全部沒有任何提示。本模組就是補這個洞。

作法刻意是**逐句判斷有沒有實質內容**，而不是單純比對關鍵詞：
「那我們廢話不多說，今天要教大家怎麼用三個步驟做出專業影片」這一句
含有開場套語，但它同時就是正題本身。因此本模組會把套語從句子中扣掉，
再看剩下的字夠不夠構成實質內容——扣完幾乎沒剩的才算開場廢話。

只報告與「建議的開場起點」，不自動剪：要不要保留自我介紹、開場要怎麼
改寫，是創作判斷——與 v1.26.0／v1.28.0／v1.29.0／v1.31.0／v1.32.0
的保守設計一致。建議起點可直接餵給既有的修剪功能由使用者自行決定。

零 GUI 依賴，供開場健檢對話框與 CLI 共用。
"""

from __future__ import annotations

import re
from typing import Optional

# 使用者可調參數（config["hookcheck"]）。
DEFAULT_HOOKCHECK = {
    "target_seconds": 15.0,        # 幾秒內要進正題（業界建議 15 秒）
    "max_greeting_seconds": 5.0,   # 打招呼與自我介紹容許佔用的長度
    "max_head_silence": 1.5,       # 開頭乾等幾秒就算太久才開口
    "extra_filler_terms": "",      # 使用者自訂補充的開場套語
    "ignore_terms": "",            # 排除詞（頻道特色用語，避免誤判）
}

_TARGET_RANGE = (5.0, 60.0)
_GREETING_RANGE = (1.0, 30.0)
_SILENCE_RANGE = (0.0, 10.0)

# 判定「扣掉套語後還算不算有實質內容」的字數門檻。
_MIN_SUBSTANCE_CHARS = 6

LEVEL_GOOD = "good"
LEVEL_WARN = "warn"
LEVEL_BAD = "bad"
_LEVEL_ICONS = {LEVEL_GOOD: "✔", LEVEL_WARN: "⚠", LEVEL_BAD: "✘"}

# 開場套語分類。advice 寫的是「該怎麼改」而不只是「這裡有問題」，
# 因為使用者看到報告時真正需要的是下一步動作。
CATEGORY_GREETING = "打招呼"
CATEGORY_SELF_INTRO = "自我介紹"
CATEGORY_CHANNEL = "頻道宣傳"
CATEGORY_SUBSCRIBE = "訂閱提醒"
CATEGORY_SMALLTALK = "無關閒聊"
CATEGORY_TRANSITION = "廢話轉場"
CATEGORY_SPONSOR = "贊助商"
CATEGORY_HOUSEKEEPING = "頻道雜務"

_CATEGORIES = {
    CATEGORY_GREETING: {
        "advice": "打招呼放在正題之後也不遲；至少壓縮成一句。",
        "terms": [
            "哈囉大家好", "嗨大家好", "大家好", "哈囉", "嗨嗨", "安安",
            "各位觀眾", "各位朋友", "早安", "午安", "晚安",
            "hello everyone", "hey everyone", "hey guys", "hi guys",
            "what's up guys", "whats up guys", "hello", "hey there",
        ],
    },
    CATEGORY_SELF_INTRO: {
        "advice": "回訪觀眾早就知道你是誰，新觀眾在意的是這支影片能給他"
                  "什麼；自我介紹建議移到正題之後或直接省略。",
        "terms": [
            "我是", "這裡是", "我叫", "我的名字",
            "my name is", "i'm", "i am", "this is",
        ],
    },
    CATEGORY_CHANNEL: {
        "advice": "「歡迎來到我的頻道」對留存沒有幫助，觀眾看的是內容"
                  "不是頻道簡介；建議直接刪掉。",
        "terms": [
            "歡迎來到我的頻道", "歡迎來到這個頻道", "歡迎回到我的頻道",
            "歡迎收看", "歡迎回來", "這個頻道",
            "welcome back to my channel", "welcome to my channel",
            "welcome back to the channel", "welcome to the channel",
            "welcome back",
        ],
    },
    CATEGORY_SUBSCRIBE: {
        "advice": "開場就要訂閱會提前趕走還沒被說服的新觀眾——他還不知道"
                  "你的內容值不值得訂。建議整段移到影片後段，等你已經"
                  "給出價值之後再說。",
        "terms": [
            "按個訂閱", "記得訂閱", "訂閱我的頻道", "訂閱這個頻道",
            "訂閱", "小鈴鐺", "開啟通知", "打開通知", "按讚分享",
            "按個讚", "點個讚", "分享出去", "加入會員",
            "幫我按", "幫我點", "幫個忙按",
            "subscribe", "hit the bell", "ring the bell",
            "smash that like", "like and subscribe", "turn on notifications",
        ],
    },
    CATEGORY_SMALLTALK: {
        "advice": "與主題無關的閒聊是開頭流失的主因之一；建議整段刪除。",
        "terms": [
            "今天天氣", "天氣真的很", "最近好嗎", "大家最近",
            "不知道大家", "希望大家都好", "最近過得",
            "how are you", "hope you're doing well", "hope you are doing",
            "hope everyone is",
        ],
    },
    CATEGORY_TRANSITION: {
        "advice": "「廢話不多說」本身就是廢話——與其宣告要進正題，"
                  "不如直接進正題。",
        "terms": [
            "廢話不多說", "話不多說", "閒話不多說", "我們就開始吧",
            "那我們開始", "那就開始吧", "進入正題", "言歸正傳",
            "在開始之前", "開始之前", "在進入正題之前", "首先呢",
            "without further ado", "let's get started", "lets get started",
            "let's dive in", "lets dive in", "let's jump in",
            "before we start", "before we begin", "before we get started",
        ],
    },
    CATEGORY_SPONSOR: {
        "advice": "贊助商放在開頭會讓還沒進入內容的觀眾直接離開；"
                  "建議移到影片中段、觀眾已經投入之後。",
        "terms": [
            "本集由", "本影片由", "感謝贊助", "贊助商", "業配",
            "特別感謝", "廣告時間",
            "sponsored by", "today's sponsor", "thanks to our sponsor",
            "this video is brought to you by",
        ],
    },
    CATEGORY_HOUSEKEEPING: {
        "advice": "頻道近況、更新進度這類交代對新觀眾沒有意義；"
                  "建議移到影片後段或放到社群貼文。",
        "terms": [
            "上一支影片", "上支影片", "上一部影片", "很久沒更新",
            "最近比較忙", "不好意思這麼久", "抱歉最近",
            "如同上次", "先跟大家說一下",
            "last video", "in my last video", "sorry for not uploading",
            "sorry it's been a while", "sorry its been a while",
        ],
    },
}

# 扣掉套語後常見的殘留虛字，這些字不構成「實質內容」。
_STOPWORDS = (
    "的了嗎吧呢喔啊耶欸唷囉啦嘛哦呀哈那這就是我你他們我們大家個先也都還"
    "很真好啦然後所以但是不過其實對阿呃嗯今天一下一個要跟和與及"
)
_PUNCT = re.compile(r"[\s,.!?;:~、，。！？；：…「」『』（）()\-—_\"／/]+")
_NON_SUBSTANCE = re.compile(f"[{_STOPWORDS}]")

# 英文得分開算：中文一個字是一個單位，英文一個字母不是。只數「實詞」，
# 並讓一個實詞約當兩個中文字，兩種語言才落在同一個門檻上。
_LATIN_WORD = re.compile(r"[a-z][a-z']*")
_EN_STOPWORDS = {
    "a", "an", "the", "i", "im", "you", "we", "they", "it", "he", "she",
    "my", "your", "our", "their", "this", "that", "these", "those",
    "is", "am", "are", "was", "were", "be", "been", "do", "does", "did",
    "to", "of", "in", "on", "for", "with", "at", "by", "from", "as",
    "and", "but", "so", "or", "if", "then", "than", "just", "really",
    "actually", "well", "now", "ok", "okay", "alright", "right", "yeah",
    "yep", "hey", "hi", "guys", "everyone", "everybody", "folks",
    "before", "after", "get", "got", "gonna", "going", "want", "wanna",
    "let", "lets", "all", "first", "here", "there", "up", "out", "back",
    "dont", "don", "forget", "gotta", "some", "thing", "things", "much",
    "very", "quick", "quickly", "little", "bit", "one", "two", "again",
    "also", "too", "not", "no", "yes", "will", "can", "would", "could",
    "have", "has", "had", "s", "t", "re", "ve", "ll", "m", "d",
}
_CJK_ONLY = re.compile(r"[a-z0-9'\s]+")


def _clamp(value, low, high, fallback, cast=float):
    try:
        value = cast(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def _split_terms(raw) -> list:
    """把使用者輸入的補充／排除詞切成清單（空白、逗號、頓號皆可分隔）。"""
    if not raw:
        return []
    parts = re.split(r"[\s,，、;；]+", str(raw))
    return [p.strip().lower() for p in parts if p.strip()]


def resolve_hookcheck_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出開場健檢參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_HOOKCHECK)
    if config:
        raw.update({k: v for k, v in config.get("hookcheck", {}).items()
                    if v is not None})
    return {
        "target_seconds": _clamp(
            raw.get("target_seconds"), *_TARGET_RANGE,
            DEFAULT_HOOKCHECK["target_seconds"]),
        "max_greeting_seconds": _clamp(
            raw.get("max_greeting_seconds"), *_GREETING_RANGE,
            DEFAULT_HOOKCHECK["max_greeting_seconds"]),
        "max_head_silence": _clamp(
            raw.get("max_head_silence"), *_SILENCE_RANGE,
            DEFAULT_HOOKCHECK["max_head_silence"]),
        "extra_filler_terms": str(raw.get("extra_filler_terms", "") or ""),
        "ignore_terms": str(raw.get("ignore_terms", "") or ""),
    }


def build_term_table(settings: Optional[dict] = None) -> list:
    """
    組出 [(套語, 分類), ...]，**依長度由長到短排序**。

    長詞優先才不會讓「訂閱」先吃掉「訂閱我的頻道」，與 publisher.py
    的 n-gram 慣例、adfriendly.py 的重疊處理一致。
    """
    settings = settings or resolve_hookcheck_settings()
    ignore = set(_split_terms(settings.get("ignore_terms")))
    table = []
    for category, spec in _CATEGORIES.items():
        for term in spec["terms"]:
            if term.lower() not in ignore:
                table.append((term.lower(), category))
    for term in _split_terms(settings.get("extra_filler_terms")):
        if term not in ignore:
            table.append((term, CATEGORY_SMALLTALK))
    table.sort(key=lambda pair: len(pair[0]), reverse=True)
    return table


def _substance_length(text: str) -> int:
    """
    扣掉標點與虛字後還剩多少「實質內容」——判斷這句話是不是純套語。

    中英文分開計算：中文按字數，英文按實詞數（一個實詞約當兩個中文字）。
    若對英文也直接數字母，任何一句英文都會遠超門檻而永遠被判定成有內容。
    """
    cleaned = _PUNCT.sub(" ", (text or "").lower())
    cjk = len(_NON_SUBSTANCE.sub("", _CJK_ONLY.sub("", cleaned)))
    words = [w for w in _LATIN_WORD.findall(cleaned)
             if w.replace("'", "") not in _EN_STOPWORDS]
    return cjk + 2 * len(words)


def classify_cue(text: str, table: list) -> dict:
    """
    判斷單句是不是「開場廢話」，回傳 {"categories", "residual", "filler"}。

    先把命中的套語從句子裡扣掉（長詞優先），再看剩下的字夠不夠構成實質
    內容。這樣「廢話不多說，今天要教大家做影片」會被正確判定為**有**實質
    內容——它含套語，但它同時就是正題。
    """
    lowered = (text or "").lower()
    categories = []
    for term, category in table:
        if term and term in lowered:
            lowered = lowered.replace(term, " ")
            if category not in categories:
                categories.append(category)
    residual = _substance_length(lowered)
    return {"categories": categories, "residual": residual,
            "filler": bool(categories) and residual < _MIN_SUBSTANCE_CHARS}


def _finding(level, title, detail, advice=""):
    return {"level": level, "title": title, "detail": detail, "advice": advice}


def analyze_hook(cues: list, settings: Optional[dict] = None) -> dict:
    """
    分析開場，回傳分析結果 dict。

    參數：
        cues: [{"start","end","text"}, ...]（字幕 cue，需依時間排序）。
        settings: resolve_hookcheck_settings() 的結果。

    回傳：
        {"findings": [...], "ok": bool, "time_to_point": 秒或 None,
         "suggested_start": 秒, "opening": [逐句判定], "head_silence": 秒}
    """
    settings = settings or resolve_hookcheck_settings()
    target = settings["target_seconds"]
    table = build_term_table(settings)
    ordered = sorted(
        [c for c in (cues or []) if (c.get("text") or "").strip()],
        key=lambda c: c.get("start") or 0.0)

    findings = []
    if not ordered:
        findings.append(_finding(
            LEVEL_BAD, "開場內容", "沒有讀到任何字幕，無法分析開場。",
            "請先產生字幕（或用「匯入既有字幕檔」載入），再執行開場健檢。"))
        return {"findings": findings, "ok": False, "time_to_point": None,
                "suggested_start": 0.0, "opening": [], "head_silence": 0.0}

    # 逐句判定，直到找到第一句有實質內容的話為止。
    opening = []
    time_to_point = None
    for cue in ordered:
        verdict = classify_cue(cue.get("text", ""), table)
        record = {"start": float(cue.get("start") or 0.0),
                  "end": float(cue.get("end") or 0.0),
                  "text": cue.get("text", ""),
                  "categories": verdict["categories"],
                  "filler": verdict["filler"]}
        opening.append(record)
        if not verdict["filler"]:
            time_to_point = record["start"]
            break

    head_silence = float(ordered[0].get("start") or 0.0)
    suggested_start = time_to_point if time_to_point is not None else 0.0

    # 1. 多久才進正題——這是本健檢的主判準。
    if time_to_point is None:
        findings.append(_finding(
            LEVEL_BAD, "進正題時間",
            "整支影片的字幕從頭到尾都被判定為開場套語，找不到正題。",
            "這通常代表字幕內容過短或辨識結果有問題；若是誤判，"
            "可把頻道慣用語加進「排除詞」。"))
    elif time_to_point > target:
        findings.append(_finding(
            LEVEL_BAD, "進正題時間",
            # 用「過了」而非「講了」：開頭也可能是乾等沒聲音，
            # 那時候並沒有在講話，說「講了 N 秒」會是錯的。
            f"開場過了 {time_to_point:.0f} 秒才進正題"
            f"（建議 {target:.0f} 秒內）",
            f"觀眾多半在前十幾秒就決定要不要看下去。建議把開場壓到 "
            f"{target:.0f} 秒內，或直接從 {format_timestamp(suggested_start)} "
            "開始剪。"))
    else:
        findings.append(_finding(
            LEVEL_GOOD, "進正題時間",
            f"{time_to_point:.0f} 秒就進正題（建議 {target:.0f} 秒內）"))

    # 2. 開場就要訂閱：研究一致認為這會提前趕走還沒被說服的新觀眾。
    subscribe = [r for r in opening if r["filler"]
                 and CATEGORY_SUBSCRIBE in r["categories"]]
    if subscribe:
        findings.append(_finding(
            LEVEL_BAD, "開場要訂閱",
            "、".join(f"{format_timestamp(r['start'])}「{r['text']}」"
                      for r in subscribe),
            _CATEGORIES[CATEGORY_SUBSCRIBE]["advice"]))

    # 3. 贊助商卡在正題之前。
    sponsor = [r for r in opening if r["filler"]
               and CATEGORY_SPONSOR in r["categories"]]
    if sponsor:
        findings.append(_finding(
            LEVEL_WARN, "開場放贊助商",
            "、".join(f"{format_timestamp(r['start'])}「{r['text']}」"
                      for r in sponsor),
            _CATEGORIES[CATEGORY_SPONSOR]["advice"]))

    # 4. 打招呼與自我介紹佔用過久。
    greet = [r for r in opening if r["filler"]
             and ({CATEGORY_GREETING, CATEGORY_SELF_INTRO, CATEGORY_CHANNEL}
                  & set(r["categories"]))]
    greet_seconds = sum(r["end"] - r["start"] for r in greet)
    if greet_seconds > settings["max_greeting_seconds"]:
        findings.append(_finding(
            LEVEL_WARN, "開場寒暄過長",
            f"打招呼、自我介紹與頻道宣傳共佔 {greet_seconds:.0f} 秒"
            f"（建議 {settings['max_greeting_seconds']:.0f} 秒內）",
            _CATEGORIES[CATEGORY_CHANNEL]["advice"]))

    # 5. 其餘開場廢話分類彙整（前面已單獨提醒的不重複列）。
    reported = {CATEGORY_SUBSCRIBE, CATEGORY_SPONSOR, CATEGORY_GREETING,
                CATEGORY_SELF_INTRO, CATEGORY_CHANNEL}
    others = {}
    for record in opening:
        if not record["filler"]:
            continue
        for category in record["categories"]:
            if category not in reported:
                others.setdefault(category, []).append(record)
    for category, records in others.items():
        findings.append(_finding(
            LEVEL_WARN, f"開場{category}",
            "、".join(f"{format_timestamp(r['start'])}「{r['text']}」"
                      for r in records),
            _CATEGORIES[category]["advice"]))

    # 6. 開頭乾等太久才開口。
    if head_silence > settings["max_head_silence"]:
        findings.append(_finding(
            LEVEL_WARN, "開頭沒聲音",
            f"影片開始後 {head_silence:.1f} 秒才有第一句話",
            "開頭的空白會讓觀眾以為影片有問題；可用「上片前健檢」的"
            "一鍵去頭尾把這段剪掉。"))

    ok = not any(f["level"] == LEVEL_BAD for f in findings)
    return {"findings": findings, "ok": ok, "time_to_point": time_to_point,
            "suggested_start": suggested_start, "opening": opening,
            "head_silence": head_silence}


def format_timestamp(seconds: float) -> str:
    """把秒數排成 M:SS／H:MM:SS，與章節健檢的顯示格式一致。"""
    seconds = max(int(seconds or 0), 0)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_hook_report(result: dict, settings: Optional[dict] = None) -> str:
    """把開場健檢結果排成純文字報告（GUI 顯示與 CLI 輸出共用）。"""
    settings = settings or resolve_hookcheck_settings()
    lines = ["===== 開場健檢（前 15 秒決定觀眾走不走）====="]
    findings = (result or {}).get("findings") or []
    if not findings:
        lines.append("・沒有可分析的開場內容。")
        return "\n".join(lines)

    for finding in findings:
        icon = _LEVEL_ICONS.get(finding["level"], "・")
        lines.append(f"{icon} {finding['title']}：{finding['detail']}")
        if finding.get("advice"):
            lines.append(f"    建議：{finding['advice']}")

    opening = result.get("opening") or []
    filler = [r for r in opening if r["filler"]]
    if filler:
        lines.append("")
        lines.append("被判定為開場套語的句子：")
        for record in filler:
            tags = "／".join(record["categories"])
            lines.append(f"  {format_timestamp(record['start'])} "
                         f"「{record['text']}」（{tags}）")

    lines.append("")
    suggested = result.get("suggested_start") or 0.0
    if result.get("ok"):
        lines.append("結論：開場沒有明顯拖累留存的問題。")
    elif result.get("time_to_point") is None:
        lines.append("結論：找不到正題，請確認字幕內容是否完整。")
    else:
        lines.append(
            f"結論：建議的開場起點為 {format_timestamp(suggested)}"
            f"（{suggested:.0f} 秒）——在此之前沒有正題內容。"
            "可用「上片前健檢」的修剪功能或審片助手剪掉，"
            "但要不要保留仍由你決定。")
    return "\n".join(lines)
