# -*- coding: utf-8 -*-
"""
工商揭露健檢：業配段落有沒有揭露、揭露得夠不夠早。

調研（中英文皆搜）確認這一段有明確、可機器檢查的規則，而且踩到的代價
不是「數據難看」而是法規風險：

- YouTube 官方：「如果創作者表明影片有付費宣傳內容，YouTube 就會在影片
  開頭顯示揭露訊息」；創作者「有責任瞭解並完全遵守所在管轄區的法律
  義務，當中可能包含提供揭露訊息的**時機**、方式和對象」——時機是被
  官方明文點名的。
- 揭露義務**與頻道大小、金額無關**，收到免費商品且有報導預期也算。
- 關鍵的時機規則：**揭露必須出現在業配段落開始之前**。FTC 已明確指出
  「影片稍早就出現業配、卻把揭露放在片尾」不符合「清楚顯著」的標準。
- 口頭揭露的份量高於單純的畫面文字。
- 中文資料另外提醒，違反揭露義務在台灣可能面臨《公平交易法》裁罰。

還有一個反直覺但一致的發現：**坦白反而留得住觀眾**。中文討論的標題就是
「想工商卻怕觀眾跑光？坦白才是最好的業配之道」——把工商段落做成一個
可以跳過的章節，比藏起來讓觀眾自己撞上更不傷留存。

本工具既有的檢查沒有涵蓋這一段：

- 「開場健檢」（v1.33）確實認得贊助商用語，但**只看開頭那幾秒**，而且
  問的是「會不會害觀眾離開」這個留存問題，不是揭露合不合規。
- 「廣告友善度」（v1.29）看的是**黃標**——YouTube 會不會不給你放廣告，
  與「你有沒有向觀眾揭露這是業配」是完全相反的兩件事。

所以本模組看的是**順序**，不是有沒有工商：有工商段落很正常，沒揭露、
或揭露得比業配還晚才是問題。

只報告不自動改：要怎麼揭露、章節要怎麼命名是創作決定——與 v1.26.0
以來的保守設計一致。

零 GUI 依賴，供上片前總體檢與 CLI 共用。
"""

from __future__ import annotations

import re
from typing import Optional

# 使用者可調參數（config["sponsorcheck"]）。
DEFAULT_SPONSORCHECK = {
    # 相鄰命中間隔小於此秒數視為同一段工商（一段業配口白中間本來就會
    # 有幾句沒有關鍵字的話）。
    "gap_seconds": 30.0,
    # 工商段落佔全片比例超過此值就提醒（觀眾對「整支都在賣」很敏感）。
    "max_ratio": 0.25,
    # 使用者自訂補充詞與誤判排除詞（逗號或空白分隔）。
    "extra_disclosure_terms": "",
    "extra_promo_terms": "",
    "ignore_terms": "",
}

_GAP_RANGE = (5.0, 180.0)
_RATIO_RANGE = (0.05, 1.0)

LEVEL_GOOD = "good"
LEVEL_WARN = "warn"
LEVEL_BAD = "bad"
_LEVEL_ICONS = {LEVEL_GOOD: "✔", LEVEL_WARN: "⚠", LEVEL_BAD: "✘"}

# 揭露語：講出「這是業配」的話。這一類是**合規的關鍵**。
DISCLOSURE_TERMS = [
    "本集由", "本影片由", "這支影片由", "這集由", "感謝贊助", "贊助播出",
    "贊助商", "業配", "工商", "付費推廣", "付費宣傳", "合作影片",
    "廠商合作", "商業合作", "體驗合作", "廠商提供",
    "sponsored by", "this video is sponsored", "paid promotion",
    "brought to you by", "in partnership with", "paid partnership",
    "#ad", "#sponsored", "thanks to our sponsor",
]

# 推銷語：業配段落實際在「賣」的時候會講的話。單獨出現不足以認定是
# 業配（「連結在資訊欄」太常見於一般影片），要兩種以上或搭配揭露語。
PROMO_TERMS = [
    "折扣碼", "優惠碼", "專屬連結", "專屬優惠", "限時優惠", "輸入代碼",
    "輸入折扣", "點下方連結", "下方連結", "資訊欄連結", "描述欄連結",
    "免費試用", "首購", "早鳥價", "團購連結", "點擊連結",
    "discount code", "promo code", "use code", "coupon code",
    "link in the description", "link below", "free trial",
    "sign up using", "check them out",
]

_CJK_RE = re.compile(r"[㐀-鿿豈-﫿぀-ヿ]")


def _clamp(value, low, high, fallback, cast=float):
    try:
        value = cast(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def _split_terms(text: str) -> list:
    """把使用者輸入的詞表（逗號或空白分隔）拆成乾淨的詞條清單。"""
    if not text:
        return []
    parts = re.split(r"[,，\s]+", str(text))
    return [p.strip().lower() for p in parts if p.strip()]


def resolve_sponsorcheck_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出工商揭露健檢參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_SPONSORCHECK)
    if config:
        raw.update({k: v for k, v in config.get("sponsorcheck", {}).items()
                    if v is not None})
    return {
        "gap_seconds": _clamp(raw.get("gap_seconds"), *_GAP_RANGE,
                              DEFAULT_SPONSORCHECK["gap_seconds"]),
        "max_ratio": _clamp(raw.get("max_ratio"), *_RATIO_RANGE,
                            DEFAULT_SPONSORCHECK["max_ratio"]),
        "extra_disclosure_terms": str(
            raw.get("extra_disclosure_terms", "") or ""),
        "extra_promo_terms": str(raw.get("extra_promo_terms", "") or ""),
        "ignore_terms": str(raw.get("ignore_terms", "") or ""),
    }


def build_term_lists(settings: Optional[dict] = None) -> tuple:
    """
    組出實際使用的（揭露詞, 推銷詞）清單，套用自訂補充與排除。

    排除詞同時作用於兩張表——使用者標記為誤判的詞，在哪一類都該排除。
    """
    settings = settings or resolve_sponsorcheck_settings()
    ignore = set(_split_terms(settings.get("ignore_terms")))
    disclosure = [t for t in DISCLOSURE_TERMS
                  + _split_terms(settings.get("extra_disclosure_terms"))
                  if t.lower() not in ignore]
    promo = [t for t in PROMO_TERMS
             + _split_terms(settings.get("extra_promo_terms"))
             if t.lower() not in ignore]
    return (disclosure, promo)


def _term_hits(text: str, term: str) -> bool:
    """
    詞條有沒有出現在這句話裡。

    含中日韓字元的詞條用子字串比對（中文沒有詞間空白）；純拉丁字母的
    詞條用單字邊界比對，避免 "ad" 誤中 "advice"、"radar"（沿用
    adfriendly.py 的既有慣例）。
    """
    if not text or not term:
        return False
    text = text.lower()
    term = term.lower()
    if _CJK_RE.search(term):
        return term in text
    if term.startswith("#"):
        return term in text
    return re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text) is not None


def scan_cues(cues: list, settings: Optional[dict] = None) -> list:
    """
    掃描字幕清單，回傳每一次命中：
    [{"start","end","text","kind","terms"}, ...]，kind 為 disclosure/promo。

    同一句同時命中兩類時，**揭露語優先**——「本集由 X 贊助，用我的折扣碼」
    這種句子的合規意義是揭露，不是推銷。
    """
    settings = settings or resolve_sponsorcheck_settings()
    disclosure, promo = build_term_lists(settings)
    hits = []
    for cue in cues or []:
        text = (cue.get("text") or "").strip()
        if not text:
            continue
        found_d = [t for t in disclosure if _term_hits(text, t)]
        found_p = [t for t in promo if _term_hits(text, t)]
        if not found_d and not found_p:
            continue
        hits.append({
            "start": float(cue.get("start") or 0.0),
            "end": float(cue.get("end") or 0.0),
            "text": text,
            "kind": "disclosure" if found_d else "promo",
            "terms": found_d or found_p,
        })
    return hits


def group_segments(hits: list, settings: Optional[dict] = None) -> list:
    """
    把命中聚成工商段落，並替每一段找出對應的揭露時間。

    相鄰命中間隔小於 gap_seconds 就併為同一段。一段要被認定為工商段落，
    必須**真的在推銷**：含有兩個以上不同的推銷詞，或含有推銷詞且同一段
    裡就有揭露語。單一句「連結在資訊欄」在一般影片裡太常見，不該被當成
    業配；反過來，只講了一句「這集是業配」而沒有任何推銷，那是**揭露**
    本身，不是業配段落，不該被算成一段、也不該產生章節。

    揭露時間是**跨全片**找的，不是只看段落內部。這很重要：「這支影片由
    X 贊助」講在影片開頭、業配口白在第 5 分鐘，是完全合規而且很常見的
    做法；只看段落內部會把這種正確的影片誤判成沒有揭露。
    """
    settings = settings or resolve_sponsorcheck_settings()
    gap = settings["gap_seconds"]
    hits = sorted(hits or [], key=lambda h: h["start"])
    disclosure_times = sorted(h["start"] for h in hits
                              if h["kind"] == "disclosure")

    groups = []
    for hit in hits:
        if groups and hit["start"] - groups[-1]["end"] <= gap:
            groups[-1]["end"] = max(groups[-1]["end"], hit["end"])
            groups[-1]["hits"].append(hit)
        else:
            groups.append({"start": hit["start"], "end": hit["end"],
                           "hits": [hit]})

    segments = []
    for group in groups:
        has_disclosure = any(h["kind"] == "disclosure" for h in group["hits"])
        promo_terms = {t for h in group["hits"] if h["kind"] == "promo"
                       for t in h["terms"]}
        if not promo_terms:
            continue
        if len(promo_terms) < 2 and not has_disclosure:
            continue
        start = group["start"]
        prior = [t for t in disclosure_times if t <= start]
        later = [t for t in disclosure_times if t > start]
        segments.append({
            "start": start,
            "end": group["end"],
            "hits": group["hits"],
            # 段落開始前最近的一次揭露；沒有就是 None。
            "disclosure_time": max(prior) if prior else None,
            # 沒有事前揭露時，記下事後才講的那一次，用來區分
            #「太晚講」與「完全沒講」——兩者的建議不一樣。
            "late_disclosure_time": (min(later)
                                     if later and not prior else None),
            "promo_terms": sorted(promo_terms),
        })
    return segments


def format_timestamp(seconds: float) -> str:
    """把秒數排成 M:SS／H:MM:SS，與其他健檢的顯示格式一致。"""
    seconds = max(int(seconds or 0), 0)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def chapter_line(segment: dict, title: str = "贊助商說明") -> str:
    """
    把工商段落排成一行可直接貼進 YouTube 說明欄的章節。

    調研的共識是「做成可以跳過的章節反而留得住觀眾」，所以這裡直接
    把可以貼的那一行給出來，而不是只叫使用者自己去加。
    """
    return f"{format_timestamp(segment.get('start', 0))} {title}"


def _finding(level, title, detail, advice=""):
    return {"level": level, "title": title, "detail": detail, "advice": advice}


def evaluate_sponsor(segments: list, duration: float = 0.0,
                     settings: Optional[dict] = None) -> dict:
    """
    依偵測到的工商段落產出健檢項目，回傳 {"findings","ok","stats"}。

    與掃描分開，讓判定邏輯可以完全不碰字幕來源單獨測試。
    """
    settings = settings or resolve_sponsorcheck_settings()
    findings = []
    segments = segments or []
    duration = max(float(duration or 0.0), 0.0)

    covered = sum(max(s["end"] - s["start"], 0.0) for s in segments)
    ratio = (covered / duration) if duration > 0 else 0.0
    stats = {
        "segment_count": len(segments),
        "covered_seconds": covered,
        "duration": duration,
        "ratio": ratio,
    }

    # 沒有工商段落是最常見的情況，而且完全正常——這一項必須通得過。
    if not segments:
        findings.append(_finding(
            LEVEL_GOOD, "工商揭露",
            "沒有掃到業配或贊助段落，沒有需要揭露的內容"))
        return {"findings": findings, "ok": True, "stats": stats,
                "segments": [], "chapter_lines": []}

    # 1. 每一段工商各自看揭露的有無與時機。
    # 事前有揭露＝合規；事後才講＝FTC 明講不合格；完全沒講＝最嚴重。
    ontime = [s for s in segments if s["disclosure_time"] is not None]
    late = [s for s in segments
            if s["disclosure_time"] is None
            and s["late_disclosure_time"] is not None]
    missing = [s for s in segments
               if s["disclosure_time"] is None
               and s["late_disclosure_time"] is None]

    if missing:
        listed = "、".join(
            f"{format_timestamp(s['start'])}～{format_timestamp(s['end'])}"
            for s in missing[:4])
        more = f"，另有 {len(missing) - 4} 段" if len(missing) > 4 else ""
        findings.append(_finding(
            LEVEL_BAD, "沒有揭露的工商段落",
            f"掃到 {len(missing)} 段在推銷、但全片都沒有講出這是業配："
            f"{listed}{more}",
            "揭露義務與頻道大小、金額無關，收到免費商品且有報導預期也算。"
            "請至少在上傳時勾選「內容含付費宣傳」，並在段落開始前口頭"
            "講一句——口頭揭露的份量高於單純的畫面文字。"))

    if late:
        rows = []
        for seg in late[:3]:
            rows.append(
                f"業配從 {format_timestamp(seg['start'])} 開始，"
                f"揭露卻遲至 "
                f"{format_timestamp(seg['late_disclosure_time'])} 才講")
        findings.append(_finding(
            LEVEL_BAD, "揭露得太晚",
            "；".join(rows),
            "揭露必須出現在業配段落開始之前。FTC 已明確指出「影片稍早"
            "就出現業配、卻把揭露放在後面」不符合「清楚顯著」的標準——"
            "把那句揭露挪到這一段的開頭就好。"))

    if ontime and not missing and not late:
        listed = "、".join(
            f"{format_timestamp(s['disclosure_time'])} 先揭露、"
            f"{format_timestamp(s['start'])} 開始"
            for s in ontime[:3])
        findings.append(_finding(
            LEVEL_GOOD, "工商揭露",
            f"{len(ontime)} 段工商都在開始前就揭露了（{listed}）"))

    stats["ontime_count"] = len(ontime)
    stats["late_count"] = len(late)
    stats["missing_count"] = len(missing)

    # 2. 工商佔比。
    if duration > 0:
        if ratio > settings["max_ratio"]:
            findings.append(_finding(
                LEVEL_WARN, "工商佔比",
                f"工商段落合計 {covered:.0f} 秒，佔全片 {ratio * 100:.0f}%"
                f"（建議 {settings['max_ratio'] * 100:.0f}% 以下）",
                "整支影片有太大比例在推銷，觀眾對這件事非常敏感。"
                "把口白收斂到重點，或把部分內容移到說明欄。"))
        else:
            findings.append(_finding(
                LEVEL_GOOD, "工商佔比",
                f"工商段落合計 {covered:.0f} 秒，佔全片 {ratio * 100:.0f}%，"
                "比例合理"))

    ok = not any(f["level"] == LEVEL_BAD for f in findings)
    return {
        "findings": findings,
        "ok": ok,
        "stats": stats,
        "segments": segments,
        "chapter_lines": [chapter_line(s) for s in segments],
    }


def analyze_sponsor(cues: Optional[list] = None, duration: float = 0.0,
                    config: Optional[dict] = None) -> dict:
    """對字幕清單跑工商揭露健檢，回傳 evaluate_sponsor 的結果。"""
    settings = resolve_sponsorcheck_settings(config)
    hits = scan_cues(cues or [], settings)
    segments = group_segments(hits, settings)
    if not duration and cues:
        duration = max((float(c.get("end") or 0.0) for c in cues), default=0.0)
    return evaluate_sponsor(segments, duration, settings)


def format_sponsor_report(result: dict,
                          settings: Optional[dict] = None) -> str:
    """把工商揭露健檢結果排成純文字報告（GUI 顯示與 CLI 輸出共用）。"""
    settings = settings or resolve_sponsorcheck_settings()
    lines = ["===== 工商揭露健檢（業配有沒有揭露、揭露得夠不夠早）====="]
    findings = (result or {}).get("findings") or []
    if not findings:
        lines.append("・沒有可分析的內容。")
        return "\n".join(lines)

    for finding in findings:
        icon = _LEVEL_ICONS.get(finding["level"], "・")
        lines.append(f"{icon} {finding['title']}：{finding['detail']}")
        if finding.get("advice"):
            lines.append(f"    建議：{finding['advice']}")

    segments = result.get("segments") or []
    if segments:
        lines.append("")
        lines.append("偵測到的工商段落：")
        for seg in segments:
            if seg["disclosure_time"] is not None:
                mark = format_timestamp(seg["disclosure_time"])
            elif seg.get("late_disclosure_time") is not None:
                mark = (f"{format_timestamp(seg['late_disclosure_time'])}"
                        "（太晚，在段落之後）")
            else:
                mark = "無"
            lines.append(
                f"  {format_timestamp(seg['start'])}～"
                f"{format_timestamp(seg['end'])}（揭露時間：{mark}）")
            sample = next((h["text"] for h in seg["hits"]), "")
            if sample:
                lines.append(f"    例：「{sample[:30]}」")

        lines.append("")
        lines.append("建議加上的章節（讓觀眾可以跳過，坦白反而留得住人）：")
        for line in result.get("chapter_lines") or []:
            lines.append(f"  {line}")
        lines.append("  ※ 請併進你原本的章節清單再貼上；YouTube 需要第一個"
                     "章節從 0:00 開始、每段至少 10 秒。")

    lines.append("")
    if not result.get("ok"):
        lines.append("結論：揭露有問題——這一項的代價不是數據難看，而是"
                     "法規風險，上傳前請先處理。")
    elif any(f["level"] == LEVEL_WARN for f in findings):
        lines.append("結論：揭露沒問題，但有可以再調整的地方（見上方建議）。")
    else:
        lines.append("結論：工商揭露沒有問題。")
    return "\n".join(lines)
