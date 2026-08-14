# -*- coding: utf-8 -*-
"""
術語一致性檢查：同一個名字在同一支影片裡被辨識成好幾種寫法。

調研（中英文皆搜）指向同一個很具體的問題：**語音辨識最會錯的就是專有
名詞**，而且錯得很有自信。

- 英文資料說得最直接：「Proper nouns are where ASR drafts look confident
  but fail」，而且「**同一支影片裡同一個專有名詞被拼成不同樣子**是有
  完整記載的問題」；模型會「拿發音相近、自己認得的詞去替換不認得的
  專有名詞」。
- 中文資料同樣點名：「AI 辨識再準確還是會有錯字，特別是**專有名詞、
  人名、英文縮寫**」，以及**同音異字**。

關鍵是**既有的解法都不夠**：本工具已經有「轉寫提示詞」可以填人名，
但 OpenAI 自己的文件就說這個做法對專有名詞「不特別可靠」。實務上被
推薦的做法是**事後在整份逐字稿裡把拼法統一**，並維護一份自己的詞庫。

本工具的既有功能剛好各差一步：

- 「自動修正詞庫」（v1.8.0）能把錯字每集自動修掉，但**要你先知道哪裡
  錯了**——它負責修，不負責找。
- 「系列一致性檢查」（v1.31.0）比的是整批影片的響度／解析度／色調，
  完全沒有碰文字。
- 「尋找取代」要你自己想得到該找什麼。

所以缺的正是中間那一段：**把「同一個詞出現了兩種以上寫法」找出來**。
這件事不需要任何模型，因為證據就在逐字稿本身——同一支影片裡出現
「Anthropic」和「Anthropik」，其中一個必定是錯的。

判定分兩個信心層級，報告會分開標示：

1. **大小寫不一致**（如 YouTube／Youtube／youtube）——字母完全相同、
   只有大小寫不同，**不可能誤判**，必定是同一個詞。
2. **英數拼法相近**（如 Anthropic／Anthropik）——長度足夠的拉丁詞才比，
   短詞不比（form／from 這種都是正常字）。

**刻意不做中文的模糊比對。** 開發時實作過「中文同長度一字之差」的版本，
實測立刻證明這條路走不通：中文沒有詞間空白，不靠斷詞詞典就只能用定長
n-gram，而 n-gram 會跨越詞的邊界。實測同一份逐字稿掃出「我們就／我們都」
（兩個都是正常的詞）與「克萊的／克萊念」（「柏克萊的時候」與「柏克萊念書」
被切出來的碎片）——照著它「統一」會把「柏克萊念書」改成「柏克萊的書」，
**直接改壞逐字稿**；而真正的錯字「的時候／的時後」反而沒被抓到。訊號比
雜訊還少，又會破壞內容，因此整層拿掉。中文的同音錯字仍請走既有的
「自動修正詞庫」：修一次、之後每一集自動修。

找到之後可以**一鍵統一**（重用既有的 replace_in_cues，不重新實作取代），
並把建議的修正規則直接印出來，貼進「自動修正詞庫」就能讓之後每一集
都自動修好——這正是調研建議的「維護自己的詞庫」。

零 GUI 依賴，供上片前總體檢、字幕健檢視窗與 CLI 共用。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Optional

# 使用者可調參數（config["termcheck"]）。
DEFAULT_TERMCHECK = {
    # 拉丁詞要多長才拿去做「拼法相近」比對。太短的英文單字（form/from、
    # their/there）本來就長得像，比了只會製造誤判。
    "min_latin_length": 5,
    # 拉丁詞的相似度下限（0~1）。
    "latin_similarity": 0.80,
    # 誤判排除詞（逗號或空白分隔）：列在這裡的寫法不會被標記。
    "ignore_terms": "",
}

_LATIN_LEN_RANGE = (3, 20)
_SIMILARITY_RANGE = (0.5, 1.0)

LEVEL_GOOD = "good"
LEVEL_WARN = "warn"
LEVEL_BAD = "bad"
_LEVEL_ICONS = {LEVEL_GOOD: "✔", LEVEL_WARN: "⚠", LEVEL_BAD: "✘"}

# 信心層級（報告分開列，使用者才知道哪些可以放心一鍵統一）。
KIND_CASE = "case"        # 大小寫不一致：不可能誤判
KIND_LATIN = "latin"      # 拉丁拼法相近

_KIND_LABELS = {
    KIND_CASE: "大小寫不一致",
    KIND_LATIN: "英數拼法相近",
}

_LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'’\-]*")


def _clamp(value, low, high, fallback, cast=float):
    try:
        value = cast(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def _split_terms(text: str) -> set:
    """把使用者輸入的排除詞（逗號或空白分隔）拆成小寫詞條集合。"""
    if not text:
        return set()
    return {p.strip().lower()
            for p in re.split(r"[,，\s]+", str(text)) if p.strip()}


def resolve_termcheck_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出術語一致性參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_TERMCHECK)
    if config:
        raw.update({k: v for k, v in config.get("termcheck", {}).items()
                    if v is not None})
    return {
        "min_latin_length": _clamp(raw.get("min_latin_length"),
                                   *_LATIN_LEN_RANGE,
                                   DEFAULT_TERMCHECK["min_latin_length"], int),
        "latin_similarity": _clamp(raw.get("latin_similarity"),
                                   *_SIMILARITY_RANGE,
                                   DEFAULT_TERMCHECK["latin_similarity"]),
        "ignore_terms": str(raw.get("ignore_terms", "") or ""),
    }


def collect_latin(cues: list) -> Counter:
    """數出逐字稿裡每一個拉丁詞（保留原本大小寫）的出現次數。"""
    counts = Counter()
    for cue in cues or []:
        for match in _LATIN_RE.finditer((cue.get("text") or "")):
            counts[match.group(0)] += 1
    return counts


def _occurrences(cues: list, term: str) -> list:
    """
    找出詞條出現在哪幾句，回傳 [(cue 索引, 開始秒數), ...]。

    用單字邊界比對而不是子字串：否則 "youtube" 會在 "youtuber" 裡也算
    一次，時間點就會指到根本沒有這個詞的句子。
    """
    if not term:
        return []
    pattern = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)")
    rows = []
    for index, cue in enumerate(cues or []):
        if pattern.search(cue.get("text") or ""):
            rows.append((index, float(cue.get("start") or 0.0)))
    return rows


def find_case_groups(counts: Counter, ignore: set) -> list:
    """
    找出「字母相同、只有大小寫不同」的寫法群組。

    這一類**不可能誤判**：YouTube 與 Youtube 必定是同一個詞。
    """
    buckets = defaultdict(dict)
    for term, count in counts.items():
        if term.lower() in ignore:
            continue
        buckets[term.lower()][term] = count
    groups = []
    for variants in buckets.values():
        if len(variants) > 1:
            groups.append({"kind": KIND_CASE, "variants": dict(variants)})
    return groups


def _is_misspelling(first: str, second: str, threshold: float) -> bool:
    """
    兩個拉丁詞是不是「同一個詞的兩種拼法」，而不是兩個不同的字。

    語音辨識的錯法是**拿發音相近的詞去替換**，所以錯字與正字的長度幾乎
    一樣；真正會差在字尾的多半是詞形變化（youtube／youtuber、model／
    models、run／running），那是兩個不同的字，統一過去會直接改壞句子。
    因此這裡要求：長度最多差 1，且**兩者不能互為前綴**。

    實測就是這樣抓出來的——只用相似度時，youtube 與 youtuber 的相似度
    高達 0.93，「一鍵統一」會把「這個 youtuber 很有趣」改成
    「這個 YouTube 很有趣」。
    """
    if abs(len(first) - len(second)) > 1:
        return False
    if first.startswith(second) or second.startswith(first):
        return False
    return SequenceMatcher(None, first, second).ratio() >= threshold


def find_latin_groups(counts: Counter, settings: dict, ignore: set) -> list:
    """
    找出拼法相近（但字母不同）的拉丁詞。

    只比長度足夠的詞：短詞本來就長得像，比了只會製造誤判。
    """
    min_len = settings["min_latin_length"]
    threshold = settings["latin_similarity"]
    # 同一個詞的大小寫差異已由 find_case_groups 處理，這裡以小寫為單位
    # 做比對；但回報時要換回**實際出現在字幕裡的寫法**，否則建議會變成
    # 「Anthropik → anthropic」這種把大小寫也一起改掉的錯誤取代。
    surfaces = defaultdict(Counter)
    for term, count in counts.items():
        if term.lower() in ignore:
            continue
        if len(term) >= min_len:
            surfaces[term.lower()][term] += count

    def surface_of(fold):
        """該小寫形式在字幕裡最常見的實際寫法。"""
        return surfaces[fold].most_common(1)[0][0]

    def total_of(fold):
        return sum(surfaces[fold].values())

    words = sorted(surfaces)
    used = set()
    groups = []
    for i, first in enumerate(words):
        if first in used:
            continue
        matched = [first]
        for second in words[i + 1:]:
            if second in used:
                continue
            if not _is_misspelling(first, second, threshold):
                continue
            matched.append(second)
        if len(matched) > 1:
            used.update(matched)
            groups.append({
                "kind": KIND_LATIN,
                "variants": {surface_of(f): total_of(f) for f in matched},
            })
    return groups


def _drop_nested(groups: list) -> list:
    """
    去掉被另一組完全包住的群組。

    「柏克萊大」與「柏克萊」會各自成組，只留較短的那一組就夠，
    否則同一個錯字會被報好幾次。
    """
    kept = []
    for group in groups:
        terms = set(group["variants"])
        nested = False
        for other in groups:
            if other is group:
                continue
            other_terms = set(other["variants"])
            if len(other_terms) != len(terms):
                continue
            # 每一個寫法都被對方的某個較短寫法包住 ⇒ 這組是多餘的。
            if all(any(o != t and o in t for o in other_terms) for t in terms):
                nested = True
                break
        if not nested:
            kept.append(group)
    return kept


def _finalize(groups: list, cues: list) -> list:
    """替每一組補上出現位置、建議的統一寫法與是否有明確主流寫法。"""
    rows = []
    for group in groups:
        variants = group["variants"]
        ranked = sorted(variants.items(), key=lambda kv: (-kv[1], kv[0]))
        top_count = ranked[0][1]
        # 兩種寫法一樣多時無從判斷哪個才對，據實標示而不是亂猜。
        decisive = len(ranked) > 1 and ranked[1][1] < top_count
        detail = {}
        for term in variants:
            hits = _occurrences(cues, term)
            detail[term] = {"count": variants[term],
                            "times": [t for _, t in hits[:3]]}
        rows.append({
            "kind": group["kind"],
            "variants": dict(ranked),
            "suggested": ranked[0][0],
            "decisive": decisive,
            "total": sum(variants.values()),
            "detail": detail,
        })
    rows.sort(key=lambda r: (-r["total"], r["suggested"]))
    return rows


def find_term_groups(cues: list, settings: Optional[dict] = None) -> list:
    """
    掃描字幕，回傳所有「同一個詞有多種寫法」的群組。

    每一組為 {"kind","variants","suggested","decisive","total","detail"}。
    """
    settings = settings or resolve_termcheck_settings()
    ignore = _split_terms(settings.get("ignore_terms"))
    latin = collect_latin(cues)
    groups = (find_case_groups(latin, ignore)
              + find_latin_groups(latin, settings, ignore))
    return _finalize(_drop_nested(groups), cues)


def format_timestamp(seconds: float) -> str:
    """把秒數排成 M:SS／H:MM:SS，與其他健檢的顯示格式一致。"""
    seconds = max(int(seconds or 0), 0)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _finding(level, title, detail, advice=""):
    return {"level": level, "title": title, "detail": detail, "advice": advice}


def evaluate_terms(groups: list,
                   settings: Optional[dict] = None) -> dict:
    """依偵測到的寫法群組產出健檢項目，回傳 {"findings","ok","stats"}。"""
    settings = settings or resolve_termcheck_settings()
    groups = groups or []
    stats = {
        "group_count": len(groups),
        "case_count": sum(1 for g in groups if g["kind"] == KIND_CASE),
        "latin_count": sum(1 for g in groups if g["kind"] == KIND_LATIN),
    }
    findings = []

    if not groups:
        findings.append(_finding(
            LEVEL_GOOD, "術語一致性",
            "沒有掃到同一個詞出現多種寫法"))
        return {"findings": findings, "ok": True, "stats": stats,
                "groups": []}

    def describe(group):
        return "／".join(f"{term}（{count} 次）"
                         for term, count in group["variants"].items())

    case_groups = [g for g in groups if g["kind"] == KIND_CASE]
    if case_groups:
        findings.append(_finding(
            LEVEL_WARN, "大小寫不一致",
            f"{len(case_groups)} 個詞在同一支影片裡用了不同的大小寫："
            + "；".join(describe(g) for g in case_groups[:4])
            + (f"，另有 {len(case_groups) - 4} 個"
               if len(case_groups) > 4 else ""),
            "字母完全相同、只有大小寫不同，必定是同一個詞。"
            "品牌名的大小寫寫錯在觀眾眼裡就是不專業，可以放心一鍵統一。"))

    fuzzy = [g for g in groups if g["kind"] == KIND_LATIN]
    if fuzzy:
        findings.append(_finding(
            LEVEL_WARN, "疑似同一個詞的不同寫法",
            f"{len(fuzzy)} 組寫法很接近，其中一種可能是辨識錯字："
            + "；".join(describe(g) for g in fuzzy[:4])
            + (f"，另有 {len(fuzzy) - 4} 組" if len(fuzzy) > 4 else ""),
            "語音辨識最會錯的就是專有名詞，而且會拿發音相近的詞去替換。"
            "確認哪一個才對之後一鍵統一，並把它加進「自動修正詞庫」，"
            "之後每一集都會自動修好。"))

    unsure = [g for g in groups if not g["decisive"]]
    if unsure:
        findings.append(_finding(
            LEVEL_WARN, "無法判斷哪個才對",
            f"{len(unsure)} 組的各種寫法出現次數一樣多，沒有主流寫法可以參考："
            + "；".join(describe(g) for g in unsure[:4]),
            "這幾組請自己確認正確寫法再統一——次數一樣時，"
            "本工具不會替你猜。"))

    # 找到寫法不一致並不代表影片不能上傳，所以不用 bad。
    return {"findings": findings, "ok": True, "stats": stats,
            "groups": groups}


def analyze_terms(cues: Optional[list] = None,
                  config: Optional[dict] = None) -> dict:
    """對字幕清單跑術語一致性檢查，回傳 evaluate_terms 的結果。"""
    settings = resolve_termcheck_settings(config)
    groups = find_term_groups(cues or [], settings)
    return evaluate_terms(groups, settings)


def apply_term_fixes(cues: list, choices: dict) -> tuple:
    """
    把選定的寫法套用到字幕，回傳 (新的 cue 清單, 取代次數)。

    choices 為 {要被換掉的寫法: 要換成的寫法}。取代本身重用既有的
    replace_in_cues，本模組不重新實作字串取代。
    """
    from subtitle.textedit import replace_in_cues

    total = 0
    for wrong, right in (choices or {}).items():
        if not wrong or not right or wrong == right:
            continue
        cues, count = replace_in_cues(cues, wrong, right, case_sensitive=True)
        total += count
    return cues, total


def build_fix_choices(groups: list, decisive_only: bool = True) -> dict:
    """
    從偵測結果組出「一鍵統一」要用的取代對照表。

    預設只處理有明確主流寫法的群組——次數一樣多時無從判斷哪個才對，
    自動挑一個等於是幫使用者亂猜。
    """
    choices = {}
    for group in groups or []:
        if decisive_only and not group.get("decisive"):
            continue
        right = group["suggested"]
        for term in group["variants"]:
            if term != right:
                choices[term] = right
    return choices


def format_term_report(result: dict,
                       settings: Optional[dict] = None) -> str:
    """把術語一致性檢查結果排成純文字報告（GUI 顯示與 CLI 輸出共用）。"""
    settings = settings or resolve_termcheck_settings()
    lines = ["===== 術語一致性檢查（同一個詞有沒有被寫成好幾種）====="]
    findings = (result or {}).get("findings") or []
    if not findings:
        lines.append("・沒有可分析的內容。")
        return "\n".join(lines)

    for finding in findings:
        icon = _LEVEL_ICONS.get(finding["level"], "・")
        lines.append(f"{icon} {finding['title']}：{finding['detail']}")
        if finding.get("advice"):
            lines.append(f"    建議：{finding['advice']}")

    groups = result.get("groups") or []
    if groups:
        lines.append("")
        lines.append("逐組明細：")
        for group in groups:
            label = _KIND_LABELS.get(group["kind"], group["kind"])
            mark = "" if group["decisive"] else "（次數相同，無法判斷）"
            lines.append(f"  [{label}]{mark}")
            for term, count in group["variants"].items():
                times = group["detail"].get(term, {}).get("times") or []
                stamps = ("，出現在 "
                          + "、".join(format_timestamp(t) for t in times)
                          if times else "")
                flag = " ← 建議統一成這個" if term == group["suggested"] else ""
                lines.append(f"    {term}：{count} 次{stamps}{flag}")

        choices = build_fix_choices(groups)
        if choices:
            lines.append("")
            lines.append("建議加進「自動修正詞庫」的規則"
                         "（加了之後每一集都會自動修）：")
            for wrong, right in choices.items():
                lines.append(f"  {wrong} → {right}")

    lines.append("")
    if not groups:
        lines.append("結論：全片的術語寫法一致。")
    else:
        lines.append("結論：有寫法不一致的詞。這不會擋住上傳，但同一個名字"
                     "在影片裡寫成兩種樣子，觀眾看得出來，字幕搜尋也會漏。")
    return "\n".join(lines)
