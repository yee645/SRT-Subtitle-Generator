# -*- coding: utf-8 -*-
"""
健檢中心的彙總邏輯（GUI 層黏合，`subtitle/` 零改動）。

v1.50.0 把三個健檢視窗（上片前健檢／字幕健檢／上片前總體檢）併成一個
「健檢中心」。三個舊視窗背後總共呼叫 15 種既有的 `subtitle/` 健檢邏輯
（12 項 `subtitle/preflight.py` 已彙總過，外加標點規範／語音同步兩項只
有字幕健檢有、外加檔名檢查），本模組把這 15 種通通接進同一份分級報告，
並記錄每一筆發現能不能一鍵修復、修復時該呼叫哪一個既有函式。

不重新實作任何分析邏輯——只做三件事：
1. 依使用者勾選跑對應的既有 `subtitle/` 函式，把不同的回傳格式正規化成
   統一的 `{level, title, detail, advice, source, fix_key}`。
2. 標記每一筆發現的 `fix_key`（能不能修、修的話要呼叫哪個既有修復函式）。
3. 提供給 GUI 呼叫的修復入口（`apply_cue_fix` / 背景執行緒用的
   `run_media_fix`），統一包一層例外處理。

零 GUI 依賴（本檔案本身可在沒有 Tkinter 顯示的環境被 import 與單元測
試），但檔名以 `gui/` 開頭是因為它服務的對象是 GUI；純 CLI 用不到本模組
——CLI 直接沿用 `subtitle/preflight.py` 或個別模組。
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from subtitle.preflight import (LEVEL_BAD, LEVEL_GOOD, LEVEL_WARN,
                                check_filename, normalize_adfriendly,
                                normalize_findings, readiness_grade,
                                resolve_preflight_settings, sort_findings,
                                summarize)

# ---------------------------------------------------------------------
# 設定：健檢中心新增的兩個勾選項（preflight 既有 12 項沿用
# config["preflight"]，這裡只補標點規範與語音同步的開關）。
# ---------------------------------------------------------------------

DEFAULT_HEALTHCENTER = {
    "run_punct": True,     # 標點規範（純文字分析，快）
    "run_subsync": False,  # 語音同步（需完整解碼音訊，預設關閉，同舊版
                           # 字幕健檢視窗裡需手動點擊才會跑的行為一致）
}


def resolve_healthcenter_settings(config: Optional[dict] = None) -> dict:
    """取出健檢中心專屬的兩個勾選項設定，缺漏補齊預設值。"""
    raw = dict(DEFAULT_HEALTHCENTER)
    if config:
        raw.update({k: v for k, v in config.get("healthcenter", {}).items()
                    if v is not None})
    return {key: bool(raw.get(key, DEFAULT_HEALTHCENTER[key]))
           for key in DEFAULT_HEALTHCENTER}


# ---------------------------------------------------------------------
# 檢查項目定義：15 項（preflight 12 項 + 標點規範 + 語音同步 + 檔名）。
# ---------------------------------------------------------------------
#   key            設定鍵（preflight 的沿用舊鍵，新兩項用 healthcenter 鍵）
#   label          勾選項顯示文字
#   source         報告分組名稱（沿用使用者已認得的舊名）
#   needs_video    是否需要影像串流才適用
#   needs_cues     是否需要字幕才適用
#   toggle_group   "preflight" 或 "healthcenter"（決定存哪個 config 區塊）
#   always_on      True 時不受勾選控制、每次都跑（目前只有檔名）


class CheckDef:
    """
    一項健檢的描述。

    `needs_media` 區分「要不要選好素材＋ffmpeg 才能跑」——這條界線刻意
    保留原本三個視窗的差異：字幕健檢（CPS／廣告友善度／開場／標點／
    術語）原本完全不需要媒體檔就能跑（純文字分析），若健檢中心把它們
    也綁上「一定要先選素材」的門檻，就是把舊字幕健檢視窗能做的事做少
    了——這是本次整併最容易不小心弄丟的一項能力，所以特別留這個旗標。
    """
    __slots__ = ("key", "label", "source", "needs_media", "needs_video",
                "needs_cues", "toggle_group", "always_on")

    def __init__(self, key, label, source, needs_media=True,
                needs_video=False, needs_cues=False,
                toggle_group="preflight", always_on=False):
        self.key = key
        self.label = label
        self.source = source
        self.needs_media = needs_media
        self.needs_video = needs_video
        self.needs_cues = needs_cues
        self.toggle_group = toggle_group
        self.always_on = always_on


CHECK_DEFS = (
    CheckDef("run_audio", "音訊健檢（爆音／音量／底噪／聲道）", "音訊健檢"),
    CheckDef("run_video", "影片畫質＋頭尾廢秒", "影片畫質健檢",
            needs_video=True),
    CheckDef("run_color", "畫面曝光與色偏", "畫面曝光與色偏",
            needs_video=True),
    CheckDef("run_volume", "分段音量一致性", "分段音量一致性"),
    CheckDef("run_pacing", "剪輯節奏", "剪輯節奏", needs_video=True),
    CheckDef("run_subtitle", "字幕健檢（CPS／行數／重疊）", "字幕健檢",
            needs_media=False, needs_cues=True),
    CheckDef("run_adfriendly", "廣告友善度", "廣告友善度",
            needs_media=False, needs_cues=True),
    CheckDef("run_hook", "開場健檢", "開場健檢",
            needs_media=False, needs_cues=True),
    CheckDef("run_legibility", "字幕可讀性", "字幕可讀性",
            needs_cues=True, needs_video=True),
    CheckDef("run_punct", "標點規範", "標點規範",
            needs_media=False, needs_cues=True,
            toggle_group="healthcenter"),
    CheckDef("run_subsync", "語音同步（需完整解碼音訊，較慢）", "語音同步",
            needs_cues=True, toggle_group="healthcenter"),
    CheckDef("run_endscreen", "片尾空間", "片尾空間"),
    CheckDef("run_sponsor", "工商揭露", "工商揭露",
            needs_media=False, needs_cues=True),
    CheckDef("run_term", "術語一致性", "術語一致性",
            needs_media=False, needs_cues=True),
    CheckDef("filename", "檔名（有選素材才會一併檢查）", "檔名",
            needs_media=True, always_on=True),
)

_BY_KEY = {c.key: c for c in CHECK_DEFS}


def _toggle_value(key, settings_preflight, settings_healthcenter):
    check = _BY_KEY[key]
    if check.always_on:
        return True
    if check.toggle_group == "healthcenter":
        return bool(settings_healthcenter.get(key, True))
    return bool(settings_preflight.get(key, True))


def default_selected_keys(config: Optional[dict] = None) -> set:
    """依 config 目前記憶的勾選狀態，回傳這次預設會跑的 key 集合。"""
    pf = resolve_preflight_settings(config)
    hc = resolve_healthcenter_settings(config)
    return {c.key for c in CHECK_DEFS
           if c.always_on or _toggle_value(c.key, pf, hc)}


def save_selected_keys(config: dict, selected_keys) -> None:
    """把使用者這次的勾選寫回 config（preflight 沿用舊區塊、新兩項寫入
    healthcenter 區塊），呼叫端負責 save_config()。"""
    selected = set(selected_keys)
    pf = dict(config.get("preflight") or {})
    hc = dict(config.get("healthcenter") or {})
    for check in CHECK_DEFS:
        if check.always_on:
            continue
        value = check.key in selected
        if check.toggle_group == "healthcenter":
            hc[check.key] = value
        else:
            pf[check.key] = value
    config["preflight"] = pf
    config["healthcenter"] = hc


# ---------------------------------------------------------------------
# 每一項檢查的轉接器：呼叫既有 subtitle/ 函式、正規化成統一格式。
# 回傳 (findings, raw)：raw 是原始回傳值，修復動作需要用到（例如
# suggest_trim 需要 dead_air、拉平音量落差需要完整的 volume 分析結果）。
# ---------------------------------------------------------------------

def _fmt_ts(seconds):
    seconds = max(float(seconds or 0.0), 0.0)
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def _run_filename(media_path, cues, config, progress_cb=None):
    settings = resolve_preflight_settings(config)
    return list(check_filename(media_path, settings)), None


def _run_audio(media_path, cues, config, progress_cb=None):
    from subtitle.audiocheck import run_audio_check
    result = run_audio_check(media_path, config, progress_cb=progress_cb)
    return normalize_findings(result, "音訊健檢"), result


def _run_video(media_path, cues, config, progress_cb=None):
    from subtitle.videocheck import run_video_check
    result = run_video_check(media_path, config, progress_cb=progress_cb)
    return normalize_findings(result, "影片畫質健檢"), result


def _run_color(media_path, cues, config, progress_cb=None):
    from subtitle.colorcheck import analyze_color, resolve_colorcheck_settings
    result = analyze_color(media_path, resolve_colorcheck_settings(config),
                           progress_cb=progress_cb)
    return normalize_findings(result, "畫面曝光與色偏"), result


def _run_volume(media_path, cues, config, progress_cb=None):
    from subtitle.volumeconsistency import (analyze_volume_consistency,
                                            resolve_volume_consistency_settings)
    result = analyze_volume_consistency(
        media_path, resolve_volume_consistency_settings(config),
        progress_cb=progress_cb)
    issues = result.get("issues") or []
    median = result.get("median_lufs")
    if median is None:
        findings = [{
            "level": LEVEL_WARN, "title": "分段音量一致性",
            "detail": "素材過短或有效樣本不足，無法分析分段音量一致性。",
            "advice": "", "source": "分段音量一致性",
        }]
    elif not issues:
        findings = [{
            "level": LEVEL_GOOD, "title": "分段音量一致性",
            "detail": f"整體中位數響度 {median:.1f} LUFS，各段落落差都在"
                      "容許範圍內。",
            "advice": "", "source": "分段音量一致性",
        }]
    else:
        findings = []
        for issue in issues:
            diff = issue.get("diff", 0.0)
            level = LEVEL_BAD if abs(diff) > 6.0 else LEVEL_WARN
            direction = "偏大" if diff > 0 else "偏小"
            findings.append({
                "level": level, "title": "音量落差段落",
                "detail": (f"{_fmt_ts(issue['start'])}"
                          f"~{_fmt_ts(issue['end'])} 約 "
                          f"{issue['lufs']:.1f} LUFS，比整體中位數"
                          f"{direction} {abs(diff):.1f} LU"),
                "advice": "可用「拉平音量落差」只調整落差過大的段落，"
                         "其餘段落原樣不動。",
                "source": "分段音量一致性",
            })
    return findings, result


def _run_pacing(media_path, cues, config, progress_cb=None):
    from subtitle.pacing import analyze_pacing
    result = analyze_pacing(media_path, config, progress_cb=progress_cb)
    return normalize_findings(result, "剪輯節奏"), result


def _run_subtitle(media_path, cues, config, progress_cb=None):
    from subtitle.subtitlecheck import analyze_cues, resolve_subcheck_settings
    result = analyze_cues(cues, resolve_subcheck_settings(config))
    issues = result.get("issues") or []
    if not issues:
        total = result.get("total", len(cues or []))
        findings = [{
            "level": LEVEL_GOOD, "title": "字幕健檢",
            "detail": f"共 {total} 句，閱讀速度、顯示時間、行數與重疊皆"
                      "正常。",
            "advice": "", "source": "字幕健檢",
        }]
    else:
        findings = [dict(row, source="字幕健檢") for row in issues]
    return findings, result


def _run_adfriendly(media_path, cues, config, progress_cb=None):
    from subtitle.adfriendly import resolve_adfriendly_settings, scan_cues
    result = scan_cues(cues, resolve_adfriendly_settings(config))
    return normalize_adfriendly(result, "廣告友善度"), result


def _run_hook(media_path, cues, config, progress_cb=None):
    from subtitle.hookcheck import analyze_hook, resolve_hookcheck_settings
    result = analyze_hook(cues, resolve_hookcheck_settings(config))
    return normalize_findings(result, "開場健檢"), result


def _run_legibility(media_path, cues, config, progress_cb=None):
    from subtitle.legibility import analyze_legibility
    style = (config or {}).get("subtitle_style", {})
    result = analyze_legibility(media_path, cues, style, config,
                                progress_cb=progress_cb)
    return normalize_findings(result, "字幕可讀性"), result


def _run_punct(media_path, cues, config, progress_cb=None):
    from subtitle.punctstyle import analyze_punctuation
    result = analyze_punctuation(cues, config)
    findings = normalize_findings(result, "標點規範")
    if not findings:
        findings = [{
            "level": LEVEL_GOOD, "title": "標點規範",
            "detail": "沒有可分析的字幕內容。", "advice": "", "source": "標點規範",
        }]
    return findings, result


_SYNC_TITLES = {
    "offset": "固定偏移",
    "drift": "逐漸漂移",
    "unreliable": "貼合度偏低",
    "ok": "同步正常",
}


def _run_subsync(media_path, cues, config, progress_cb=None):
    from subtitle.subsync import analyze_sync, resolve_subsync_settings
    result = analyze_sync(media_path, cues, resolve_subsync_settings(config))
    kind = result.get("kind", "ok")
    hit = (result.get("hit_rate") or 0.0) * 100.0
    title = _SYNC_TITLES.get(kind, "同步")
    if kind == "ok":
        finding = {"level": LEVEL_GOOD, "title": title,
                   "detail": f"字幕與語音貼合度 {hit:.0f}%，同步正常。",
                   "advice": "", "source": "語音同步"}
    elif kind == "unreliable":
        finding = {"level": LEVEL_WARN, "title": title,
                   "detail": f"貼合度 {hit:.0f}%，找不到明顯更好的校正參數。",
                   "advice": "可能是字幕來源不是這支素材，或素材中段被剪過"
                            "而不是單純的整體偏移；請確認字幕來源是否正確。",
                   "source": "語音同步"}
    else:
        corrected = (result.get("corrected_hit_rate") or 0.0) * 100.0
        offset = result.get("offset", 0.0)
        direction = "延後" if offset > 0 else "提前"
        if kind == "drift":
            detail = (f"貼合度僅 {hit:.0f}%（校正後可達 {corrected:.0f}%）："
                      f"時間軸需縮放 {result.get('scale', 1.0):.4f} 倍"
                      f"（{result.get('scale_label', '')}），通常是字幕製作"
                      "時的幀率與這支影片不同。")
        else:
            detail = (f"貼合度僅 {hit:.0f}%（校正後可達 {corrected:.0f}%）："
                      f"整軌{direction} {abs(offset):.2f} 秒即可對上。")
        finding = {"level": LEVEL_BAD, "title": title, "detail": detail,
                   "advice": "可按「修復此項」一鍵校正（只調整時間軸、不改"
                            "動文字內容）。",
                   "source": "語音同步"}
    return [finding], result


def _run_endscreen(media_path, cues, config, progress_cb=None):
    from subtitle.endscreen import analyze_endscreen
    result = analyze_endscreen(media_path, cues, config)
    return normalize_findings(result, "片尾空間"), result


def _run_sponsor(media_path, cues, config, progress_cb=None):
    from subtitle.sponsorcheck import analyze_sponsor
    duration = 0.0
    if media_path and os.path.exists(media_path):
        # 有素材時用實際片長；沒有時 analyze_sponsor 會自己從字幕最後一句
        # 的結束時間推算（見 subtitle/sponsorcheck.py），不需要媒體檔。
        from subtitle.media import probe_duration
        duration = probe_duration(media_path)
    result = analyze_sponsor(cues, duration, config)
    return normalize_findings(result, "工商揭露"), result


def _run_term(media_path, cues, config, progress_cb=None):
    from subtitle.termcheck import analyze_terms
    result = analyze_terms(cues, config)
    return normalize_findings(result, "術語一致性"), result


_RUNNERS = {
    "filename": _run_filename,
    "run_audio": _run_audio,
    "run_video": _run_video,
    "run_color": _run_color,
    "run_volume": _run_volume,
    "run_pacing": _run_pacing,
    "run_subtitle": _run_subtitle,
    "run_adfriendly": _run_adfriendly,
    "run_hook": _run_hook,
    "run_legibility": _run_legibility,
    "run_punct": _run_punct,
    "run_subsync": _run_subsync,
    "run_endscreen": _run_endscreen,
    "run_sponsor": _run_sponsor,
    "run_term": _run_term,
}


# ---------------------------------------------------------------------
# fix_key 標記：判斷一筆發現能不能修、要呼叫哪個既有修復函式。
# ---------------------------------------------------------------------

_FIXABLE = {
    ("音訊健檢", "整體響度"): "audiofix",
    ("音訊健檢", "爆音檢查"): "audiofix",
    ("音訊健檢", "底噪檢查"): "audiofix",
    ("影片畫質健檢", "開頭廢秒"): "trim",
    ("影片畫質健檢", "結尾廢秒"): "trim",
    ("分段音量一致性", "音量落差段落"): "volumefix",
    ("字幕健檢", "閱讀速度過快"): "extend_cues",
    ("字幕健檢", "顯示時間過短"): "extend_cues",
    ("字幕健檢", "字幕重疊"): "fix_overlap",
    ("標點規範", "行尾標點"): "punct_fix",
    ("標點規範", "句中逗頓"): "punct_fix",
    ("語音同步", "固定偏移"): "sync_fix",
    ("語音同步", "逐漸漂移"): "sync_fix",
}

FIX_LABELS = {
    "audiofix": "輸出音訊修復版",
    "trim": "輸出修剪版（去頭尾）",
    "volumefix": "拉平音量落差",
    "extend_cues": "一鍵延長過快字幕",
    "fix_overlap": "一鍵修復重疊",
    "punct_fix": "一鍵套用標點規範",
    "sync_fix": "一鍵校正同步",
}


def tag_fix_key(finding: dict) -> Optional[str]:
    if finding.get("level") == LEVEL_GOOD:
        return None
    return _FIXABLE.get((finding.get("source"), finding.get("title")))


# ---------------------------------------------------------------------
# 主要進入點：一次跑完使用者勾選的檢查項，回傳彙總結果。
# ---------------------------------------------------------------------

def run_health_scan(media_path: str, cues: Optional[list],
                    config: Optional[dict], selected_keys,
                    progress_cb: Optional[Callable[[float, str], None]] = None
                    ) -> dict:
    """
    一次跑完 selected_keys 指定的檢查項，回傳
    {"findings", "raw", "counts", "grade", "ok", "skipped", "media"}。

    raw：{source: 該檢查的原始回傳值}，修復動作需要用到（例如拉平音量
    落差需要完整的分析結果，不能只靠正規化後的 finding 文字）。

    依素材自動略過不適用的項目（無影像串流略過畫面類；無字幕略過字幕
    類；**沒有選素材、或缺 ffmpeg 時，純文字的字幕相關檢查仍會照跑**——
    這是舊字幕健檢視窗本來就有的能力：CPS／廣告友善度／開場／標點／
    術語一致性完全不需要媒體檔，健檢中心不能因為併了另外兩個一定要選
    素材的視窗，就連帶讓這幾項也變成「一定要先選素材」。）
    """
    cues = list(cues or [])
    selected = set(selected_keys or [])
    media_path = (media_path or "").strip()

    def report(ratio, message):
        if callable(progress_cb):
            progress_cb(ratio, message)

    report(0.02, "檢查素材類型…")
    has_media = bool(media_path and os.path.exists(media_path))
    has_ffmpeg = False
    has_video = False
    if has_media:
        from subtitle.burner import ffmpeg_available
        has_ffmpeg = ffmpeg_available()
        if has_ffmpeg:
            from subtitle.media import has_video_stream
            has_video = has_video_stream(media_path)

    steps = []
    skipped = []
    if media_path and not has_media:
        skipped.append(f"找不到檔案：{media_path}，已略過所有需要媒體檔的檢查")
    elif has_media and not has_ffmpeg:
        skipped.append("找不到 ffmpeg，已略過所有需要媒體檔的檢查（純文字"
                       "的字幕相關檢查不受影響）")
    for check in CHECK_DEFS:
        if not (check.always_on or check.key in selected):
            continue
        if check.needs_media and not (has_media and has_ffmpeg):
            if check.key == "filename" and not media_path:
                continue  # 完全沒選素材時，檔名檢查悄悄略過即可，不必報告。
            if media_path:
                continue  # 上面已統一記一則略過說明，不要每項都重複列出。
            skipped.append(f"{check.source}：尚未選擇素材，已略過")
            continue
        if check.needs_video and not has_video:
            skipped.append(f"{check.source}：此素材沒有影像軌，已略過")
            continue
        if check.needs_cues and not cues:
            skipped.append(f"{check.source}：沒有字幕，已略過")
            continue
        steps.append(check)

    findings = []
    raw = {}
    sections = []
    total = max(len(steps), 1)
    for index, check in enumerate(steps):
        report(0.05 + 0.9 * (index / total), f"{check.source}…")
        runner = _RUNNERS[check.key]

        def sub_progress(ratio, message, _base=0.05 + 0.9 * (index / total),
                         _span=0.9 / total):
            report(_base + _span * max(0.0, min(ratio, 1.0)), message)

        try:
            rows, raw_result = runner(media_path, cues, config,
                                      progress_cb=sub_progress)
            for row in rows:
                row = dict(row)
                row.setdefault("source", check.source)
                row["fix_key"] = tag_fix_key(row)
                findings.append(row)
            raw[check.source] = raw_result
            sections.append({"name": check.source, "ran": True})
        except Exception as exc:  # 單項失敗不該讓整份健檢中斷。
            sections.append({"name": check.source, "ran": False,
                            "error": str(exc)})
            skipped.append(f"{check.source}：{exc}")

    findings = sort_findings(findings)
    counts = summarize(findings)
    report(1.0, "完成")
    return {
        "findings": findings,
        "raw": raw,
        "sections": sections,
        "counts": counts,
        "grade": readiness_grade(counts),
        "ok": counts[LEVEL_BAD] == 0,
        "skipped": skipped,
        "media": os.path.basename(media_path),
        "cues": cues,
    }


def format_health_report(result: dict) -> str:
    """把健檢中心結果排成純文字報告（複製／另存共用）。"""
    media = (result or {}).get("media") or "素材"
    lines = [f"===== 健檢中心：{media} ====="]
    findings = (result or {}).get("findings") or []
    if not findings:
        lines.append("・沒有可檢查的項目。")
        return "\n".join(lines)

    counts = result.get("counts") or {}
    grade = result.get("grade", "?")
    icons = {LEVEL_BAD: "✘", LEVEL_WARN: "⚠", LEVEL_GOOD: "✔"}
    lines.append(f"準備度：{grade}"
                 f"（一定要修 {counts.get(LEVEL_BAD, 0)}、"
                 f"建議修 {counts.get(LEVEL_WARN, 0)}、"
                 f"通過 {counts.get(LEVEL_GOOD, 0)}）")
    lines.append("")
    for label, level in (("一定要修", LEVEL_BAD), ("建議修", LEVEL_WARN),
                         ("通過", LEVEL_GOOD)):
        rows = [f for f in findings if f["level"] == level]
        if not rows:
            continue
        lines.append(f"--- {label}（{len(rows)}）---")
        for row in rows:
            icon = icons.get(row["level"], "・")
            source = row.get("source") or "健檢中心"
            lines.append(f"{icon} [{source}] {row['title']}："
                         f"{row.get('detail', '')}")
            if row.get("advice") and level != LEVEL_GOOD:
                lines.append(f"    建議：{row['advice']}")
        lines.append("")

    skipped = result.get("skipped") or []
    if skipped:
        lines.append("略過的項目：")
        for note in skipped:
            lines.append(f"  ・{note}")
        lines.append("")

    if result.get("ok"):
        lines.append("結論：沒有「一定要修」的項目，可以上傳。")
    else:
        lines.append("結論：還有「一定要修」的項目——這些會實際影響上傳"
                     "或觀看體驗，建議處理完再上傳。")
    return "\n".join(lines)


# ---------------------------------------------------------------------
# 修復動作：包一層既有 subtitle/ 函式，統一介面供 GUI 呼叫。
# ---------------------------------------------------------------------

class FixError(Exception):
    """修復動作的前置條件不足（例如尚未跑過健檢）時丟出，訊息可直接顯示。"""


def apply_cue_fix(fix_key: str, cues: list, config: Optional[dict],
                  raw: dict) -> tuple:
    """
    處理不需要重新編碼媒體檔的修復（都是快速的純運算）。

    回傳 (new_cues, changed_count, message)；changed_count 為 0 時代表
    沒有東西可修（呼叫端應以提示告知，不視為錯誤）。
    """
    if fix_key == "extend_cues":
        from subtitle.subtitlecheck import (fix_cue_durations,
                                            resolve_subcheck_settings)
        new_cues, fixed = fix_cue_durations(
            cues, resolve_subcheck_settings(config))
        return new_cues, fixed, f"已延長 {fixed} 句字幕的顯示時間。"
    if fix_key == "fix_overlap":
        from subtitle.subtitlecheck import fix_overlaps
        new_cues, fixed = fix_overlaps(cues)
        return new_cues, fixed, f"已修復 {fixed} 處時間軸重疊。"
    if fix_key == "punct_fix":
        from subtitle.punctstyle import (apply_punct_style,
                                         resolve_punctstyle_settings)
        new_cues, changed = apply_punct_style(
            cues, resolve_punctstyle_settings(config))
        return new_cues, changed, f"已規範化 {changed} 句字幕的標點。"
    if fix_key == "sync_fix":
        sync_result = raw.get("語音同步")
        if not sync_result or sync_result.get("kind") not in ("offset",
                                                               "drift"):
            raise FixError("請先跑過健檢並確認偵測到同步偏移。")
        from subtitle.subsync import apply_sync_correction
        new_cues = apply_sync_correction(
            cues, sync_result["scale"], sync_result["offset"])
        return new_cues, 1, "已套用同步校正。"
    raise FixError(f"不支援的修復項目：{fix_key}")


def apply_media_fix(fix_key: str, media_path: str, output_path: str,
                    config: Optional[dict], raw: dict,
                    progress_cb: Optional[Callable[[float, str], None]]
                    = None) -> str:
    """
    處理需要跑 ffmpeg 重新編碼媒體檔的修復；呼叫端須在背景執行緒執行。

    回傳輸出檔案路徑。
    """
    if fix_key == "audiofix":
        from subtitle.audiofix import fix_audio, resolve_audiofix_settings
        settings = resolve_audiofix_settings(config)
        if not (settings["denoise"] or settings["highpass"]
                or settings["loudnorm"]):
            raise FixError("目前沒有勾選任何修復項目（降噪／去低頻／響度"
                           "正規化），請到「進階設定」勾選後再修復。")
        return fix_audio(media_path, output_path, settings=settings,
                         progress_cb=progress_cb)
    if fix_key == "trim":
        from subtitle.videocheck import (resolve_videocheck_settings,
                                         suggest_trim, trim_video)
        video_result = raw.get("影片畫質健檢")
        dead_air = (video_result or {}).get("dead_air")
        if not dead_air:
            raise FixError("請先跑過健檢並確認偵測到頭尾廢秒。")
        head, tail = suggest_trim(dead_air, resolve_videocheck_settings(
            config))
        if head <= 0 and tail <= 0:
            raise FixError("沒有偵測到需要修剪的頭尾廢秒。")
        return trim_video(media_path, output_path, head_seconds=head,
                          tail_seconds=tail, progress_cb=progress_cb)
    if fix_key == "volumefix":
        from subtitle.volumeconsistency import fix_volume_consistency
        volume_result = raw.get("分段音量一致性")
        if not volume_result or not volume_result.get("issues"):
            raise FixError("請先跑過健檢並確認偵測到音量落差過大的段落。")
        return fix_volume_consistency(media_path, volume_result,
                                      output_path, progress_cb=progress_cb)
    raise FixError(f"不支援的修復項目：{fix_key}")


def suggest_fix_output_path(fix_key: str, media_path: str) -> str:
    """依修復種類取建議輸出路徑（沿用各既有模組自己的命名慣例）。"""
    from subtitle.pipeline import unique_path
    if fix_key == "audiofix":
        from subtitle.audiofix import suggest_output_path
    elif fix_key == "trim":
        from subtitle.videocheck import suggest_output_path
    elif fix_key == "volumefix":
        from subtitle.volumeconsistency import suggest_output_path
    else:
        raise FixError(f"不支援的修復項目：{fix_key}")
    return unique_path(suggest_output_path(media_path))


MEDIA_FIX_KEYS = frozenset({"audiofix", "trim", "volumefix"})
CUE_FIX_KEYS = frozenset({"extend_cues", "fix_overlap", "punct_fix",
                          "sync_fix"})
