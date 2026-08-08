# -*- coding: utf-8 -*-
"""
封面健檢：這張縮圖在手機上還看得清楚嗎？

調研（中英文皆搜）指向同一組數字：**YouTube 七成以上的觀看來自手機**，
而手機列表裡的縮圖只有大約 **200×110 像素**。業界的自我檢查法就是
「把封面縮到 10% 大小再看一眼，如果看不清就是失敗」——調研資料指出
**近四成的封面失敗原因單純就是「縮小後看不清楚」**，而畫面太雜、對比
太低、灰濛濛不顯眼是最常見的三種死法。

本工具自 v1.11.0 起就會從精彩片段自動擷取封面候選圖，但**從未評估過
產出的封面本身好不好用**——`thumbnails.py` 只在「挑哪一格」時算清晰度，
挑完就結束了。更常見的情境其實是「我用 Canva／Photoshop 做好封面，
這張能不能用」，那根本不是從影片幀來的。

因此本模組吃的是**任意圖片檔**，不限於本工具產生的候選圖。

量測方式（皆為實測驗證過可區分的指標）：

- **細節保留率**：把圖縮到手機尺寸再放大回來，比較前後的邊緣能量。
  大色塊構成的封面幾乎不掉（實測 1.46），細碎雜訊型的封面會崩到 0.07
  ——這正是「縮小後糊成一團」的量化版本。
- **對比**：縮到手機尺寸後的 YHIGH−YLOW。灰濛濛的封面實測只有 11，
  大色塊封面有 141。
- **飽和度**：SATAVG。滑動時不顯眼的封面通常飽和度極低。
- **規格**：解析度、16:9 比例、檔案大小（YouTube 上限 2MB）。

只報告不自動修：封面要怎麼改是設計決定，而且自動加濾鏡只會讓它更糟
——與 v1.26.0／v1.28.0／v1.29.0／v1.31.0／v1.32.0／v1.33.0／v1.34.0
的保守設計一致。

零 GUI 依賴，供封面健檢對話框與 CLI 共用。
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Optional

from subtitle.burner import ffmpeg_available

# 使用者可調參數（config["thumbcheck"]）。
DEFAULT_THUMBCHECK = {
    # 手機列表縮圖寬度（實測 YouTube 手機版約 200 像素寬）。
    "mobile_width": 200,
    # 縮到手機尺寸後保留的邊緣能量比例下限；低於此值代表畫面太雜。
    "min_detail_keep": 0.35,
    # 手機尺寸下的對比（YHIGH−YLOW）下限；太低就是灰濛濛不顯眼。
    "min_contrast": 40.0,
    # 平均飽和度下限；太低在滑動時不會被注意到。
    "min_saturation": 15.0,
    # 檔案大小上限（MB）；YouTube 自訂縮圖上限為 2MB。
    "max_file_mb": 2.0,
}

_WIDTH_RANGE = (80, 640)
_DETAIL_RANGE = (0.05, 1.0)
_CONTRAST_RANGE = (10.0, 200.0)
_SATURATION_RANGE = (0.0, 120.0)
_FILE_RANGE = (0.5, 10.0)

# YouTube 建議的自訂縮圖規格。
RECOMMENDED_WIDTH = 1280
RECOMMENDED_HEIGHT = 720
TARGET_ASPECT = 16.0 / 9.0
_ASPECT_TOLERANCE = 0.05

LEVEL_GOOD = "good"
LEVEL_WARN = "warn"
LEVEL_BAD = "bad"
_LEVEL_ICONS = {LEVEL_GOOD: "✔", LEVEL_WARN: "⚠", LEVEL_BAD: "✘"}

_STAT_RE = re.compile(r"lavfi\.signalstats\.(\w+)=([-\d.]+)")
_SIZE_RE = re.compile(r"^(\d+)x(\d+)$")


def _clamp(value, low, high, fallback, cast=float):
    try:
        value = cast(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_thumbcheck_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出封面健檢參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_THUMBCHECK)
    if config:
        raw.update({k: v for k, v in config.get("thumbcheck", {}).items()
                    if v is not None})
    return {
        "mobile_width": _clamp(raw.get("mobile_width"), *_WIDTH_RANGE,
                               DEFAULT_THUMBCHECK["mobile_width"], cast=int),
        "min_detail_keep": _clamp(raw.get("min_detail_keep"), *_DETAIL_RANGE,
                                  DEFAULT_THUMBCHECK["min_detail_keep"]),
        "min_contrast": _clamp(raw.get("min_contrast"), *_CONTRAST_RANGE,
                               DEFAULT_THUMBCHECK["min_contrast"]),
        "min_saturation": _clamp(raw.get("min_saturation"),
                                 *_SATURATION_RANGE,
                                 DEFAULT_THUMBCHECK["min_saturation"]),
        "max_file_mb": _clamp(raw.get("max_file_mb"), *_FILE_RANGE,
                              DEFAULT_THUMBCHECK["max_file_mb"]),
    }


def parse_signalstats(stderr: str) -> dict:
    """從 ffmpeg 的 metadata=print 輸出解析 signalstats 數值。"""
    values = {}
    for match in _STAT_RE.finditer(stderr or ""):
        try:
            values[match.group(1)] = float(match.group(2))
        except ValueError:
            continue
    return values


def _run_stats(image_path: str, vf: str, timeout: int = 120) -> dict:
    """
    對圖片跑一次 signalstats，回傳數值 dict。

    注意 metadata=print 走的是 info 層級的日誌，**不能加 `-v error`**，
    否則整份數值都會被吞掉（沿用 colorcheck.py 的既有慣例）。
    """
    command = [
        "ffmpeg", "-hide_banner", "-nostats",
        "-i", image_path,
        "-vf", f"{vf},signalstats,metadata=print",
        "-f", "null", "-",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return {}
    return parse_signalstats(
        (completed.stderr or b"").decode("utf-8", errors="ignore"))


def probe_image_size(image_path: str, timeout: int = 60) -> tuple:
    """用 ffprobe 取得圖片的 (寬, 高)；讀不到時回 (0, 0)。"""
    command = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0", image_path,
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return (0, 0)
    text = (completed.stdout or b"").decode("utf-8", errors="ignore").strip()
    match = _SIZE_RE.match(text.splitlines()[0] if text else "")
    if not match:
        return (0, 0)
    return (int(match.group(1)), int(match.group(2)))


def measure_thumbnail(image_path: str,
                      settings: Optional[dict] = None) -> dict:
    """
    量測一張封面，回傳各項指標。

    細節保留率的作法是「縮到手機尺寸後再用最近鄰放大回原尺寸」，讓縮放
    前後的邊緣能量落在同一個尺度上才能相比；比值越低代表畫面越雜、
    在手機上越容易糊成一團。
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"找不到檔案：{image_path}")

    settings = settings or resolve_thumbcheck_settings()
    width, height = probe_image_size(image_path)
    if width <= 0 or height <= 0:
        raise ValueError(f"讀不到圖片內容（可能不是圖片檔）：{image_path}")

    mobile_w = settings["mobile_width"]
    edge_full = _run_stats(image_path, "sobel").get("YAVG", 0.0)
    edge_mobile = _run_stats(
        image_path,
        f"scale={mobile_w}:-2,scale={width}:{height}:flags=neighbor,sobel"
    ).get("YAVG", 0.0)
    mobile_stats = _run_stats(image_path, f"scale={mobile_w}:-2")

    # 比值可能略大於 1（最近鄰放大會造出原本沒有的硬邊），但「保留率」
    # 超過 100% 沒有意義，夾在 1.0 以內才是可以直接顯示給使用者的數字。
    detail_keep = min(edge_mobile / edge_full, 1.0) if edge_full > 0 else 0.0
    return {
        "path": image_path,
        "name": os.path.basename(image_path),
        "width": width,
        "height": height,
        "file_mb": os.path.getsize(image_path) / (1024.0 * 1024.0),
        "edge_full": edge_full,
        "edge_mobile": edge_mobile,
        "detail_keep": detail_keep,
        "contrast": mobile_stats.get("YHIGH", 0.0)
        - mobile_stats.get("YLOW", 0.0),
        "luma": mobile_stats.get("YAVG", 0.0),
        "saturation": mobile_stats.get("SATAVG", 0.0),
    }


def _finding(level, title, detail, advice=""):
    return {"level": level, "title": title, "detail": detail, "advice": advice}


def evaluate_thumbnail(metrics: dict,
                       settings: Optional[dict] = None) -> dict:
    """
    依量測結果產出健檢項目，回傳 {"findings","ok","score","metrics"}。

    與 measure_thumbnail 分開，讓判定邏輯可以完全不碰 ffmpeg 單獨測試。
    """
    settings = settings or resolve_thumbcheck_settings()
    findings = []
    if not metrics:
        findings.append(_finding(
            LEVEL_BAD, "封面內容", "沒有可分析的圖片。",
            "請選擇一張封面圖片（PNG／JPG）再執行健檢。"))
        return {"findings": findings, "ok": False, "score": 0.0,
                "metrics": {}}

    width, height = metrics.get("width", 0), metrics.get("height", 0)

    # 1. 手機尺寸下的可讀性——本健檢的主判準。
    keep = metrics.get("detail_keep", 0.0)
    limit = settings["min_detail_keep"]
    if keep < limit:
        findings.append(_finding(
            LEVEL_BAD, "手機尺寸可讀性",
            f"縮到手機尺寸（約 {settings['mobile_width']} 像素寬）後只剩下 "
            f"{keep * 100:.0f}% 的畫面細節（建議 {limit * 100:.0f}% 以上）",
            "畫面元素太多、太細碎，縮小後會糊成一團。七成以上的觀看來自"
            "手機，請大幅簡化：留 1 個主體、文字控制在 3~5 個字、"
            "用粗體大字並加深色描邊。"))
    else:
        findings.append(_finding(
            LEVEL_GOOD, "手機尺寸可讀性",
            f"縮到手機尺寸後仍保留 {keep * 100:.0f}% 的畫面細節"))

    # 2. 對比：滑動時會不會被看見。
    contrast = metrics.get("contrast", 0.0)
    if contrast < settings["min_contrast"]:
        findings.append(_finding(
            LEVEL_BAD, "對比",
            f"手機尺寸下的明暗落差只有 {contrast:.0f}"
            f"（建議 {settings['min_contrast']:.0f} 以上）",
            "整張圖灰濛濛的，在滿是縮圖的清單裡不會被注意到。"
            "把主體和背景的明暗拉開，或改用「深底＋亮字」這類高對比配色。"))
    else:
        findings.append(_finding(
            LEVEL_GOOD, "對比", f"明暗落差 {contrast:.0f}，足以在清單中辨識"))

    # 3. 飽和度：夠不夠顯眼。
    saturation = metrics.get("saturation", 0.0)
    if saturation < settings["min_saturation"]:
        findings.append(_finding(
            LEVEL_WARN, "色彩鮮明度",
            f"平均飽和度 {saturation:.0f}"
            f"（建議 {settings['min_saturation']:.0f} 以上）",
            "顏色太淡會被旁邊的縮圖蓋過去；可提高主體的彩度，"
            "或加一塊高彩度的色塊當背景。"))

    # 4. 規格：解析度、比例、檔案大小。
    if width and height:
        if width < RECOMMENDED_WIDTH or height < RECOMMENDED_HEIGHT:
            findings.append(_finding(
                LEVEL_WARN, "解析度",
                f"{width}x{height}"
                f"（建議 {RECOMMENDED_WIDTH}x{RECOMMENDED_HEIGHT} 以上）",
                "解析度不足在大螢幕與電視上會糊掉；請以 1280x720 以上輸出。"))
        aspect = width / float(height)
        if abs(aspect - TARGET_ASPECT) > _ASPECT_TOLERANCE:
            findings.append(_finding(
                LEVEL_WARN, "長寬比",
                f"目前約 {aspect:.2f}:1（YouTube 建議 16:9，約 1.78:1）",
                "非 16:9 的圖會被 YouTube 裁切或補黑邊，主體可能被切掉。"))

    file_mb = metrics.get("file_mb", 0.0)
    if file_mb > settings["max_file_mb"]:
        findings.append(_finding(
            LEVEL_BAD, "檔案大小",
            f"{file_mb:.2f} MB，超過上限 {settings['max_file_mb']:.0f} MB",
            "超過上限的縮圖 YouTube 會直接拒絕上傳。"
            "改存成 JPG 或降低品質即可，封面用不到無損畫質。"))

    ok = not any(f["level"] == LEVEL_BAD for f in findings)
    return {"findings": findings, "ok": ok,
            "score": thumbnail_score(metrics, settings), "metrics": metrics}


def thumbnail_score(metrics: dict, settings: Optional[dict] = None) -> float:
    """
    給封面一個 0~100 的綜合分數，用來排序多張候選圖。

    三項指標各自對門檻正規化後加權平均；門檻本身即得 60 分，
    達到門檻兩倍即接近滿分。這個分數只用於「同一批候選圖誰比較好」，
    不代表絕對品質。
    """
    settings = settings or resolve_thumbcheck_settings()
    if not metrics:
        return 0.0

    def graded(value, target):
        if target <= 0:
            return 100.0
        ratio = max(float(value), 0.0) / float(target)
        return max(0.0, min(100.0, 60.0 * min(ratio, 1.0)
                            + 40.0 * min(max(ratio - 1.0, 0.0), 1.0)))

    parts = [
        (graded(metrics.get("detail_keep", 0.0),
                settings["min_detail_keep"]), 0.5),
        (graded(metrics.get("contrast", 0.0), settings["min_contrast"]), 0.3),
        (graded(metrics.get("saturation", 0.0),
                settings["min_saturation"]), 0.2),
    ]
    return round(sum(value * weight for value, weight in parts), 1)


def check_thumbnail(image_path: str, config: Optional[dict] = None) -> dict:
    """量測並評估單張封面，回傳 evaluate_thumbnail 的結果。"""
    settings = resolve_thumbcheck_settings(config)
    return evaluate_thumbnail(measure_thumbnail(image_path, settings),
                              settings)


def rank_thumbnails(image_paths: list, config: Optional[dict] = None,
                    progress_cb=None) -> list:
    """
    一次檢查多張候選圖並依分數由高到低排序。

    v1.11.0 的封面候選一次會產出好幾張，「該用哪一張」正是接下來的問題；
    單張讀不到內容時不中斷整批，改在該筆記錄 error。
    """
    settings = resolve_thumbcheck_settings(config)
    results = []
    total = len(image_paths or [])
    for index, path in enumerate(image_paths or []):
        if callable(progress_cb):
            progress_cb((index + 1) / max(total, 1),
                        f"檢查 {os.path.basename(path)}…")
        try:
            result = evaluate_thumbnail(
                measure_thumbnail(path, settings), settings)
            result["error"] = None
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            result = {"findings": [], "ok": False, "score": 0.0,
                      "metrics": {"path": path,
                                  "name": os.path.basename(path)},
                      "error": str(exc)}
        results.append(result)
    results.sort(key=lambda r: -r["score"])
    return results


def format_thumb_report(result: dict,
                        settings: Optional[dict] = None) -> str:
    """把單張封面的健檢結果排成純文字報告。"""
    settings = settings or resolve_thumbcheck_settings()
    metrics = (result or {}).get("metrics") or {}
    name = metrics.get("name") or "封面"
    lines = [f"===== 封面健檢：{name} ====="]

    findings = (result or {}).get("findings") or []
    if not findings:
        if (result or {}).get("error"):
            lines.append(f"・無法分析：{result['error']}")
        else:
            lines.append("・沒有可分析的圖片。")
        return "\n".join(lines)

    for finding in findings:
        icon = _LEVEL_ICONS.get(finding["level"], "・")
        lines.append(f"{icon} {finding['title']}：{finding['detail']}")
        if finding.get("advice"):
            lines.append(f"    建議：{finding['advice']}")

    lines.append("")
    lines.append("量測數值：")
    lines.append(f"  尺寸 {metrics.get('width', 0)}x{metrics.get('height', 0)}"
                 f"、檔案 {metrics.get('file_mb', 0.0):.2f} MB")
    lines.append(f"  手機尺寸細節保留 {metrics.get('detail_keep', 0.0) * 100:.0f}%"
                 f"、對比 {metrics.get('contrast', 0.0):.0f}"
                 f"、飽和度 {metrics.get('saturation', 0.0):.0f}")
    lines.append(f"  綜合分數 {result.get('score', 0.0):.0f}／100")

    lines.append("")
    if result.get("ok"):
        lines.append("結論：這張封面在手機上看得清楚，可以使用。")
    else:
        lines.append("結論：這張封面在手機上會吃虧——七成以上的觀看來自手機，"
                     "而手機清單裡的縮圖只有約 200 像素寬。請依上述項目調整。")
    return "\n".join(lines)


def format_ranking_report(results: list,
                          settings: Optional[dict] = None) -> str:
    """把多張候選圖的比較結果排成純文字報告（分數由高到低）。"""
    settings = settings or resolve_thumbcheck_settings()
    lines = ["===== 封面候選比較（分數由高到低）====="]
    if not results:
        lines.append("・沒有可比較的圖片。")
        return "\n".join(lines)

    for index, result in enumerate(results, start=1):
        metrics = result.get("metrics") or {}
        name = metrics.get("name") or f"第 {index} 張"
        if result.get("error"):
            lines.append(f"{index}. {name}：無法分析（{result['error']}）")
            continue
        mark = "✔" if result.get("ok") else "✘"
        lines.append(
            f"{index}. {mark} {name}　{result.get('score', 0.0):.0f} 分"
            f"（細節保留 {metrics.get('detail_keep', 0.0) * 100:.0f}%、"
            f"對比 {metrics.get('contrast', 0.0):.0f}、"
            f"飽和 {metrics.get('saturation', 0.0):.0f}）")

    usable = [r for r in results if r.get("ok") and not r.get("error")]
    lines.append("")
    if usable:
        best = (usable[0].get("metrics") or {}).get("name") or "第 1 張"
        lines.append(f"建議使用：{best}")
    else:
        lines.append("這批候選圖沒有一張通過健檢——建議重做封面，"
                     "或從影片中另外挑一格畫面單純、對比明顯的畫面。")
    lines.append("")
    lines.append("（分數只用於同一批候選圖之間的相對比較，"
                 "不代表絕對品質；最終仍請以肉眼縮小檢視為準。）")
    return "\n".join(lines)
