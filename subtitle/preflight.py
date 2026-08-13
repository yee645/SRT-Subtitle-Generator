# -*- coding: utf-8 -*-
"""
上片前總體檢：一次跑完所有健檢，給一份依嚴重度排序的結論。

本工具到 v1.37.0 已經累積 **16 項健檢**，但它們散落在五個入口——上片前
健檢對話框、字幕健檢對話框、三個獨立對話框，外加十幾個 CLI 旗標。要在
上傳前確認一支影片沒問題，使用者得記得開三個視窗、按五個按鈕，還要自己
判斷哪些問題是「一定要修」哪些是「有空再說」。

調研（中英文皆搜）確認這正是實務上的痛點：**漏掉單一一個步驟就可能讓
一支影片少掉數千次觀看**，忘記換縮圖、說明欄留空都會直接影響觸及。
市面上的檢查清單工具因此都有兩個共同設計：**依嚴重度分級**（一定要修／
建議修／可選）與**一個總體準備度評分**。YouTube 官方本身也提供發布前的
檢查項目頁面。

本模組不重新實作任何分析，只做三件既有模組做不到的事：

1. **一次跑完**所有適用的健檢，並依實際素材自動略過不適用的項目
   （純音訊檔跳過所有畫面檢查、沒有字幕就跳過字幕相關檢查）
2. **把三種不同的回傳格式正規化**成同一份清單——既有模組有的回傳
   `findings`、有的回傳 `issues`、廣告友善度則是自己的叢集結構
3. **依嚴重度排序並給出準備度評級**，讓使用者知道先修哪一個

另外補上一項既有健檢沒有的檢查：**檔名**。調研指出檔名是演算法最早拿到
的線索之一，`final_cut_v2.mp4` 這種名字等於白白浪費一個訊號。

只報告不自動改——本模組彙總的每一項底下都是既有的「只報告」設計。

零 GUI 依賴，供總體檢對話框與 CLI 共用。
"""

from __future__ import annotations

import os
import re
from typing import Callable, Optional

LEVEL_GOOD = "good"
LEVEL_WARN = "warn"
LEVEL_BAD = "bad"
_LEVEL_ICONS = {LEVEL_GOOD: "✔", LEVEL_WARN: "⚠", LEVEL_BAD: "✘"}
_LEVEL_ORDER = {LEVEL_BAD: 0, LEVEL_WARN: 1, LEVEL_GOOD: 2}

# 使用者可調參數（config["preflight"]）。每一項都可單獨關閉——畫面類的
# 掃描要完整解碼影片，長片上並不便宜，使用者應該能只跑自己在意的。
DEFAULT_PREFLIGHT = {
    "run_audio": True,        # 音訊健檢（爆音／音量／底噪／聲道）
    "run_video": True,        # 影片畫質健檢（位元率／解析度／頭尾廢秒）
    "run_color": True,        # 畫面曝光與色偏
    "run_volume": True,       # 分段音量一致性
    "run_pacing": True,       # 剪輯節奏（畫面太久沒變化）
    "run_subtitle": True,     # 字幕健檢（CPS／行數／重疊）
    "run_adfriendly": True,   # 廣告友善度（黃標風險）
    "run_hook": True,         # 開場健檢（多久才進正題）
    "run_legibility": True,   # 字幕可讀性（與背景的對比）
    "run_endscreen": True,    # 片尾空間（結束畫面放不放得下）
    "run_sponsor": True,      # 工商揭露（需有字幕）
    # 視為「沒有資訊」的檔名關鍵字（逗號分隔）。
    "generic_name_terms": ("final,final_cut,export,output,video,movie,"
                           "未命名,新增專案,序列,專案,輸出,影片"),
}

_BOOL_KEYS = ("run_audio", "run_video", "run_color", "run_volume",
              "run_pacing", "run_subtitle", "run_adfriendly", "run_hook",
              "run_legibility", "run_endscreen", "run_sponsor")

# 檔名裡「只有數字與符號」的樣式（IMG_1234、DJI_0002、20260101_120000）。
_MEANINGLESS_NAME = re.compile(r"^[\W\d_]*$|^[A-Za-z]{2,4}[\W_]?\d{2,}$")


def resolve_preflight_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出總體檢參數，缺漏補齊預設值。"""
    raw = dict(DEFAULT_PREFLIGHT)
    if config:
        raw.update({k: v for k, v in config.get("preflight", {}).items()
                    if v is not None})
    resolved = {key: bool(raw.get(key, DEFAULT_PREFLIGHT[key]))
                for key in _BOOL_KEYS}
    resolved["generic_name_terms"] = str(
        raw.get("generic_name_terms",
                DEFAULT_PREFLIGHT["generic_name_terms"]) or "")
    return resolved


def _finding(level, title, detail, advice="", source="總體檢"):
    """本模組的項目一律帶 source，報告才知道每一條是哪一項檢查給的。"""
    return {"level": level, "title": title, "detail": detail,
            "advice": advice, "source": source}


def check_filename(media_path: str,
                   settings: Optional[dict] = None) -> list:
    """
    檢查檔名有沒有帶到資訊。

    調研指出檔名是演算法最早拿到的線索之一；`final_cut_v2.mp4` 這種名字
    等於白白浪費一個訊號。這是既有 16 項健檢都沒有涵蓋的一項。
    """
    settings = settings or resolve_preflight_settings()
    name = os.path.splitext(os.path.basename(media_path or ""))[0]
    if not name:
        return [_finding(LEVEL_WARN, "檔名", "讀不到檔名。", "", "檔名")]

    lowered = name.lower()
    terms = [t.strip().lower() for t in
             (settings.get("generic_name_terms") or "").split(",") if t.strip()]
    hit = [t for t in terms if t and t in lowered]

    if _MEANINGLESS_NAME.match(name):
        return [_finding(
            LEVEL_WARN, "檔名",
            f"「{name}」看起來是相機或裝置的預設檔名",
            "檔名是演算法最早拿到的線索之一。改成帶關鍵字的名稱"
            "（例如「相機隱藏設定實測.mp4」）不花時間，卻是白拿的訊號。",
            "檔名")]
    if hit:
        return [_finding(
            LEVEL_WARN, "檔名",
            f"「{name}」含有沒有資訊的字眼：{'、'.join(hit)}",
            "檔名是演算法最早拿到的線索之一。上傳前改成帶主題關鍵字的"
            "名稱，不花時間卻是白拿的訊號。", "檔名")]
    return [_finding(LEVEL_GOOD, "檔名", f"「{name}」有帶到內容資訊",
                     "", "檔名")]


def normalize_findings(result: Optional[dict], source: str) -> list:
    """
    把既有模組的回傳正規化成同一份清單。

    既有模組的格式並不一致：多數回傳 `findings`，色彩／音量／字幕健檢
    回傳 `issues`（欄位相同、只有鍵名不同），廣告友善度則是自己的叢集
    結構。這裡統一成 [{level,title,detail,advice,source}, ...]。
    """
    if not result:
        return []
    rows = result.get("findings")
    if rows is None:
        rows = result.get("issues") or []
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized.append({
            "level": row.get("level", LEVEL_WARN),
            "title": row.get("title", ""),
            "detail": row.get("detail", ""),
            "advice": row.get("advice", ""),
            "source": source,
        })
    return normalized


def normalize_adfriendly(result: Optional[dict], source: str) -> list:
    """
    廣告友善度的回傳是叢集結構，沒有 findings／issues，需單獨轉換。

    只把「高風險叢集」與「開頭命中」轉成項目——個別用詞命中太細碎，
    放進總體檢只會淹沒真正要處理的事。
    """
    if not result:
        return []
    rows = []
    clusters = result.get("clusters") or []
    if clusters:
        listed = "、".join(
            f"{int(c['start'] // 60)}:{int(c['start'] % 60):02d}"
            for c in clusters[:5])
        more = f"，另有 {len(clusters) - 5} 處" if len(clusters) > 5 else ""
        rows.append({
            "level": LEVEL_WARN, "title": "廣告友善度",
            "detail": f"{len(clusters)} 處高風險段落：{listed}{more}",
            "advice": "這些段落短時間內密集出現可能觸發審查的用詞，"
                      "建議改口或消音；詳細命中詞請看字幕健檢的完整報告。",
            "source": source,
        })
    opening = result.get("opening_hits") or []
    if opening:
        rows.append({
            "level": LEVEL_WARN, "title": "開頭用詞",
            "detail": f"開頭 {result.get('opening_seconds', 0):.0f} 秒內"
                      f"出現 {len(opening)} 個風險用詞",
            "advice": "開頭數秒的用詞對營利判定影響特別大。",
            "source": source,
        })
    if not rows:
        rows.append({
            "level": LEVEL_GOOD, "title": "廣告友善度",
            "detail": "沒有掃到高風險段落", "advice": "", "source": source,
        })
    return rows


def readiness_grade(counts: dict) -> str:
    """
    依問題數量給一個準備度評級。

    分級刻意讓「一定要修」（bad）主導：只要還有 bad，最好也只到 C，
    因為那些是會實際影響上傳或觀看體驗的問題。
    """
    bad = counts.get(LEVEL_BAD, 0)
    warn = counts.get(LEVEL_WARN, 0)
    if bad == 0 and warn == 0:
        return "A+"
    if bad == 0 and warn <= 2:
        return "A"
    if bad == 0:
        return "B"
    if bad == 1:
        return "C"
    if bad <= 3:
        return "D"
    return "F"


def summarize(findings: list) -> dict:
    """統計各嚴重度的數量。"""
    counts = {LEVEL_BAD: 0, LEVEL_WARN: 0, LEVEL_GOOD: 0}
    for row in findings or []:
        level = row.get("level", LEVEL_WARN)
        if level in counts:
            counts[level] += 1
    return counts


def sort_findings(findings: list) -> list:
    """依嚴重度排序（一定要修的排最前面），同級維持原本的檢查順序。"""
    return sorted(
        list(findings or []),
        key=lambda row: _LEVEL_ORDER.get(row.get("level"), 1))


def run_preflight(media_path: str, cues: Optional[list] = None,
                  config: Optional[dict] = None,
                  progress_cb: Optional[Callable[[float, str], None]] = None
                  ) -> dict:
    """
    一次跑完所有適用的健檢，回傳彙總結果。

    回傳 {"findings", "sections", "counts", "grade", "ok", "skipped"}。

    **依素材自動略過**：純音訊檔跳過全部畫面檢查、沒有字幕就跳過字幕相關
    檢查。這不只是為了不出錯——每一項畫面檢查都要完整解碼一次影片，
    對純音訊檔跑四項畫面檢查是白白浪費四次解碼。
    """
    from subtitle.burner import ffmpeg_available
    from subtitle.media import has_video_stream

    if not os.path.exists(media_path):
        raise FileNotFoundError(f"找不到檔案：{media_path}")
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")

    settings = resolve_preflight_settings(config)
    cues = cues or []

    def report(ratio, message):
        if callable(progress_cb):
            progress_cb(ratio, message)

    # 先問一次「有沒有影像軌」，後面所有畫面檢查共用這個答案。
    report(0.02, "檢查素材類型…")
    has_video = has_video_stream(media_path)

    findings = list(check_filename(media_path, settings))
    sections = [{"name": "檔名", "ran": True}]
    skipped = []
    if not has_video:
        skipped.append("此素材沒有影像軌，已略過所有畫面相關檢查")

    steps = _build_steps(settings, has_video, bool(cues))
    total = max(len(steps), 1)
    for index, (name, runner) in enumerate(steps):
        report(0.05 + 0.9 * (index / total), f"{name}…")
        try:
            rows = runner(media_path, cues, config)
            findings.extend(rows)
            sections.append({"name": name, "ran": True})
        except Exception as exc:  # 單項失敗不該讓整份體檢中斷。
            sections.append({"name": name, "ran": False, "error": str(exc)})
            skipped.append(f"{name}：{exc}")

    if not cues:
        skipped.append("沒有字幕，已略過字幕相關檢查"
                       "（字幕健檢、廣告友善度、開場健檢、字幕可讀性）")

    findings = sort_findings(findings)
    counts = summarize(findings)
    report(1.0, "完成")
    return {
        "findings": findings,
        "sections": sections,
        "counts": counts,
        "grade": readiness_grade(counts),
        "ok": counts[LEVEL_BAD] == 0,
        "skipped": skipped,
        "media": os.path.basename(media_path),
    }


def _build_steps(settings: dict, has_video: bool, has_cues: bool) -> list:
    """
    組出這次要跑的檢查清單。

    分開成一個函式，讓「哪些會被略過」可以完全不碰 ffmpeg 單獨測試。
    """
    steps = []
    if settings["run_audio"]:
        steps.append(("音訊健檢", _run_audio))
    if settings["run_video"] and has_video:
        steps.append(("影片畫質健檢", _run_video))
    if settings["run_color"] and has_video:
        steps.append(("畫面曝光與色偏", _run_color))
    if settings["run_volume"]:
        steps.append(("分段音量一致性", _run_volume))
    if settings["run_pacing"] and has_video:
        steps.append(("剪輯節奏", _run_pacing))
    if settings["run_subtitle"] and has_cues:
        steps.append(("字幕健檢", _run_subtitle))
    if settings["run_adfriendly"] and has_cues:
        steps.append(("廣告友善度", _run_adfriendly))
    if settings["run_hook"] and has_cues:
        steps.append(("開場健檢", _run_hook))
    if settings["run_legibility"] and has_cues and has_video:
        steps.append(("字幕可讀性", _run_legibility))
    if settings["run_endscreen"]:
        steps.append(("片尾空間", _run_endscreen))
    if settings["run_sponsor"] and has_cues:
        steps.append(("工商揭露", _run_sponsor))
    return steps


# --- 各項檢查的轉接器：只負責呼叫既有模組並正規化，不含任何分析邏輯 ---

def _run_audio(media_path, cues, config):
    from subtitle.audiocheck import run_audio_check
    return normalize_findings(run_audio_check(media_path, config), "音訊健檢")


def _run_video(media_path, cues, config):
    from subtitle.videocheck import run_video_check
    return normalize_findings(run_video_check(media_path, config),
                              "影片畫質健檢")


def _run_color(media_path, cues, config):
    from subtitle.colorcheck import analyze_color, resolve_colorcheck_settings
    return normalize_findings(
        analyze_color(media_path, resolve_colorcheck_settings(config)),
        "畫面曝光與色偏")


def _run_volume(media_path, cues, config):
    from subtitle.volumeconsistency import (analyze_volume_consistency,
                                            resolve_volume_consistency_settings)
    return normalize_findings(
        analyze_volume_consistency(
            media_path, resolve_volume_consistency_settings(config)),
        "分段音量一致性")


def _run_pacing(media_path, cues, config):
    from subtitle.pacing import analyze_pacing
    return normalize_findings(analyze_pacing(media_path, config), "剪輯節奏")


def _run_subtitle(media_path, cues, config):
    from subtitle.subtitlecheck import analyze_cues, resolve_subcheck_settings
    return normalize_findings(
        analyze_cues(cues, resolve_subcheck_settings(config)), "字幕健檢")


def _run_adfriendly(media_path, cues, config):
    from subtitle.adfriendly import resolve_adfriendly_settings, scan_cues
    return normalize_adfriendly(
        scan_cues(cues, resolve_adfriendly_settings(config)), "廣告友善度")


def _run_hook(media_path, cues, config):
    from subtitle.hookcheck import analyze_hook, resolve_hookcheck_settings
    return normalize_findings(
        analyze_hook(cues, resolve_hookcheck_settings(config)), "開場健檢")


def _run_legibility(media_path, cues, config):
    from subtitle.legibility import analyze_legibility
    style = (config or {}).get("subtitle_style", {})
    return normalize_findings(
        analyze_legibility(media_path, cues, style, config), "字幕可讀性")


def _run_endscreen(media_path, cues, config):
    from subtitle.endscreen import analyze_endscreen
    return normalize_findings(
        analyze_endscreen(media_path, cues, config), "片尾空間")


def _run_sponsor(media_path, cues, config):
    from subtitle.media import probe_duration
    from subtitle.sponsorcheck import analyze_sponsor
    return normalize_findings(
        analyze_sponsor(cues, probe_duration(media_path), config), "工商揭露")


def format_preflight_report(result: dict) -> str:
    """把總體檢結果排成純文字報告（GUI 顯示與 CLI 輸出共用）。"""
    media = (result or {}).get("media") or "素材"
    lines = [f"===== 上片前總體檢：{media} ====="]
    findings = (result or {}).get("findings") or []
    if not findings:
        lines.append("・沒有可檢查的項目。")
        return "\n".join(lines)

    counts = result.get("counts") or {}
    grade = result.get("grade", "?")
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
            icon = _LEVEL_ICONS.get(row["level"], "・")
            source = row.get("source") or "總體檢"
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
