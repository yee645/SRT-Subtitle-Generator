# -*- coding: utf-8 -*-
"""
字幕可讀性健檢：燒錄後的字幕在畫面上真的看得清楚嗎？

調研（中英文皆搜）指向同一個很具體的問題：**白色字幕遇到偏白的畫面就
會糊在一起看不見**。白色在生活與影像中都太常見，所以這件事幾乎每支
影片都會遇到——只是創作者通常要等到燒錄完、播出去才發現。

中英文資料給的解法也一致，而且是有先後順序的：

1. **先加黑色描邊**（白字＋黑描邊在亮暗背景上都看得清）
2. 干擾更高時**加粗描邊或加陰影**
3. **半透明底框留到最後**——中文資料特別提醒「除非整個影片都是亮色，
   否則底框會顯得突兀」

本工具已經負責燒錄字幕，而且**手上就有判斷這件事所需要的全部資訊**：
字幕的垂直位置（`subtitle_style.position_y`）、每一句的時間點（cues）、
文字顏色與描邊寬度（`text_color`／`stroke_width`）。但既有的檢查沒有
任何一項在看這件事：

- 「字幕健檢」（v1.20.0）只看閱讀速度、行數與時間軸重疊，是純文字分析
- 「畫面曝光與色偏」（v1.28.0）量的是**整張畫面**的平均亮度
- 「Shorts 字幕安全區」（v1.25.0）處理的是**位置**會不會被平台介面遮住

都不是「字幕背後那一條帶子有多亮」。

作法：算出字幕實際會落在畫面上的那一條帶子，在各句的時間點取樣，用
ffmpeg 的 `crop` + `signalstats` 量測該區域的亮度，再與文字顏色的亮度
相比。實測一段下方帶子很亮的素材量到 222、很暗的量到 30，而純白文字
亮度為 255——對比分別是 33（看不見）與 225（清楚），區分度足夠。

另外會看**帶內的明暗落差**：若字幕帶本身忽亮忽暗，換任何單一文字顏色
都救不了，這時描邊才是正解。報告會直接講出該調哪一個設定，因為那些
設定就在本工具裡。

只報告不自動改：字幕要用什麼顏色、描邊多粗是視覺風格決定——與
v1.26.0 以來的保守設計一致。

零 GUI 依賴，供字幕健檢對話框與 CLI 共用。
"""

from __future__ import annotations

import re
import subprocess
from typing import Callable, Optional

from subtitle.burner import ffmpeg_available
from subtitle.media import has_video_stream, probe_duration

# 使用者可調參數（config["legibility"]）。
DEFAULT_LEGIBILITY = {
    # 取樣句數：逐句解碼太貴，均勻取樣即可看出趨勢。
    "sample_count": 12,
    # 文字與背景的亮度差下限（0~255）；低於此值視為看不清楚。
    "min_contrast": 60.0,
    # 字幕帶高度佔畫面高度的比例（涵蓋一般字級的一到兩行）。
    "band_ratio": 0.14,
}

_SAMPLE_RANGE = (3, 40)
_CONTRAST_RANGE = (20.0, 200.0)
_BAND_RANGE = (0.05, 0.40)

# 描邊夠不夠粗的判斷門檻：低於此值時「加粗描邊」是第一順位建議。
_THIN_STROKE = 2

LEVEL_GOOD = "good"
LEVEL_WARN = "warn"
LEVEL_BAD = "bad"
_LEVEL_ICONS = {LEVEL_GOOD: "✔", LEVEL_WARN: "⚠", LEVEL_BAD: "✘"}

_STAT_RE = re.compile(r"lavfi\.signalstats\.(\w+)=([-\d.]+)")


def _clamp(value, low, high, fallback, cast=float):
    try:
        value = cast(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_legibility_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出字幕可讀性參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_LEGIBILITY)
    if config:
        raw.update({k: v for k, v in config.get("legibility", {}).items()
                    if v is not None})
    return {
        "sample_count": _clamp(raw.get("sample_count"), *_SAMPLE_RANGE,
                               DEFAULT_LEGIBILITY["sample_count"], cast=int),
        "min_contrast": _clamp(raw.get("min_contrast"), *_CONTRAST_RANGE,
                               DEFAULT_LEGIBILITY["min_contrast"]),
        "band_ratio": _clamp(raw.get("band_ratio"), *_BAND_RANGE,
                             DEFAULT_LEGIBILITY["band_ratio"]),
    }


def text_luma(hex_color: str) -> float:
    """
    把 #RRGGBB 文字顏色換算成亮度（0~255）。

    用 BT.601 的係數，與 ffmpeg signalstats 量到的 Y 值在同一個尺度上，
    兩者才能直接相減比對比。
    """
    text = (hex_color or "#FFFFFF").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        # 解析不出來時當作白字（最常見也最保守的假設）。這裡刻意用
        # 純白的實際亮度，與空值走 "#FFFFFF" 的路徑得到同一個值。
        return 255.0
    try:
        red = int(text[0:2], 16)
        green = int(text[2:4], 16)
        blue = int(text[4:6], 16)
    except ValueError:
        return 255.0
    return 0.299 * red + 0.587 * green + 0.114 * blue


def subtitle_band(width: int, height: int, style: Optional[dict] = None,
                  band_ratio: float = 0.14) -> tuple:
    """
    算出字幕實際會落在畫面上的那一條帶子，回傳 (w, h, x, y)。

    垂直位置沿用 exporter.py 的 `position_y`（0＝最上、1＝最下），
    以該位置為中心往上下各取半條帶子，並夾在畫面範圍內。
    """
    style = style or {}
    position_y = float(style.get("position_y", 0.88) or 0.88)
    position_y = max(0.0, min(position_y, 1.0))
    band_h = max(int(height * band_ratio), 8)
    center = int(height * position_y)
    top = center - band_h // 2
    top = max(0, min(top, max(height - band_h, 0)))
    return (int(width), int(band_h), 0, int(top))


def sample_times(cues: list, count: int) -> list:
    """
    從字幕清單均勻取樣時間點（各句的中點），回傳 [(時間, 文字), ...]。

    逐句解碼在長片上太貴；均勻取樣足以看出「哪幾段背景會蓋掉字幕」。
    """
    usable = [c for c in (cues or [])
              if (c.get("text") or "").strip()
              and (c.get("end") or 0) > (c.get("start") or 0)]
    if not usable:
        return []
    count = max(int(count), 1)
    if len(usable) <= count:
        picked = usable
    else:
        step = len(usable) / float(count)
        picked = [usable[min(int(i * step), len(usable) - 1)]
                  for i in range(count)]
    return [((float(c["start"]) + float(c["end"])) / 2.0,
             (c.get("text") or "").strip()) for c in picked]


def measure_band(media_path: str, time_s: float, crop: tuple,
                 timeout: int = 60) -> dict:
    """
    量測某個時間點、某個區域的亮度統計。

    注意 metadata=print 走 info 層級的日誌，**不能加 `-v error`**，
    否則整份數值都會被吞掉（沿用 colorcheck.py 的既有慣例）。
    """
    width, height, x, y = crop
    command = [
        "ffmpeg", "-hide_banner", "-nostats",
        "-ss", f"{max(float(time_s), 0.0):.3f}", "-i", media_path,
        "-vframes", "1",
        "-vf", f"crop={width}:{height}:{x}:{y},signalstats,metadata=print",
        "-f", "null", "-",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return {}
    stderr = (completed.stderr or b"").decode("utf-8", errors="ignore")
    values = {}
    for match in _STAT_RE.finditer(stderr):
        try:
            values[match.group(1)] = float(match.group(2))
        except ValueError:
            continue
    return values


def _finding(level, title, detail, advice=""):
    return {"level": level, "title": title, "detail": detail, "advice": advice}


def format_timestamp(seconds: float) -> str:
    """把秒數排成 M:SS／H:MM:SS，與其他健檢的顯示格式一致。"""
    seconds = max(int(seconds or 0), 0)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def evaluate_legibility(samples: list, style: Optional[dict] = None,
                        settings: Optional[dict] = None) -> dict:
    """
    依取樣結果產出健檢項目，回傳 {"findings","ok","stats","weak"}。

    與量測分開，讓判定邏輯可以完全不碰 ffmpeg 單獨測試。
    samples 為 [{"time","text","luma","spread"}, ...]。
    """
    style = style or {}
    settings = settings or resolve_legibility_settings()
    limit = settings["min_contrast"]
    findings = []

    if not samples:
        findings.append(_finding(
            LEVEL_BAD, "字幕可讀性", "沒有可分析的字幕或畫面。",
            "請先產生字幕（或用「匯入既有字幕檔」載入），"
            "並確認素材含有影像軌。"))
        return {"findings": findings, "ok": False, "stats": {}, "weak": []}

    fg = text_luma(style.get("text_color", "#FFFFFF"))
    stroke = int(style.get("stroke_width", 2) or 0)
    contrasts = [abs(fg - s["luma"]) for s in samples]
    spreads = [s.get("spread", 0.0) for s in samples]
    weak = [s for s in samples if abs(fg - s["luma"]) < limit]

    stats = {
        "text_luma": fg,
        "stroke_width": stroke,
        "sample_count": len(samples),
        "weak_count": len(weak),
        "min_contrast": min(contrasts),
        "average_contrast": sum(contrasts) / len(contrasts),
        "average_spread": sum(spreads) / len(spreads) if spreads else 0.0,
    }

    # 1. 對比不足的句子——本健檢的主判準。
    if weak:
        listed = "、".join(
            f"{format_timestamp(s['time'])}"
            f"（背景亮度 {s['luma']:.0f}、對比 {abs(fg - s['luma']):.0f}）"
            for s in weak[:5])
        more = (f"，另有 {len(weak) - 5} 處未列出" if len(weak) > 5 else "")
        level = LEVEL_BAD if len(weak) * 2 >= len(samples) else LEVEL_WARN
        findings.append(_finding(
            level, "字幕與背景對比",
            f"{len(weak)}／{len(samples)} 個取樣點的對比低於 {limit:.0f}："
            f"{listed}{more}",
            _contrast_advice(stroke, fg)))
    else:
        findings.append(_finding(
            LEVEL_GOOD, "字幕與背景對比",
            f"{len(samples)} 個取樣點的對比都在 {limit:.0f} 以上"
            f"（最低 {stats['min_contrast']:.0f}）"))

    # 2. 描邊寬度：這是最有效也最不破壞畫面的保護。
    if stroke < _THIN_STROKE:
        findings.append(_finding(
            LEVEL_WARN, "描邊寬度",
            f"目前描邊寬度為 {stroke}",
            "白字不加描邊，遇到偏白的畫面就會糊在一起。"
            "描邊是最有效也最不破壞畫面的保護，建議至少設為 2。"))
    else:
        findings.append(_finding(
            LEVEL_GOOD, "描邊寬度", f"描邊寬度 {stroke}，有基本保護"))

    # 3. 背景忽亮忽暗：換單一文字顏色救不了，只有描邊有用。
    if stats["average_spread"] >= 100.0:
        findings.append(_finding(
            LEVEL_WARN, "背景明暗變化大",
            f"字幕帶內的平均明暗落差 {stats['average_spread']:.0f}",
            "字幕背後的畫面忽亮忽暗，換成任何單一文字顏色都會在某些段落"
            "失效——這種情況只有描邊（或半透明底框）救得了。"))

    ok = not any(f["level"] == LEVEL_BAD for f in findings)
    return {"findings": findings, "ok": ok, "stats": stats, "weak": weak}


def _contrast_advice(stroke: int, fg: float) -> str:
    """
    依目前設定給出「該調哪一個」的建議。

    順序刻意照調研的共識排：先描邊、再加粗、最後才是底框——底框除非
    整支影片都是亮色，否則會顯得突兀。
    """
    steps = []
    if stroke < _THIN_STROKE:
        steps.append("先把「邊框寬度」調到 2（白字＋黑描邊在亮暗背景上都看得清）")
    else:
        steps.append(f"把「邊框寬度」從 {stroke} 再加粗一級")
    if fg >= 200:
        steps.append("或把文字顏色從純白改成淺灰／淡黃，與亮背景拉開一點距離")
    steps.append("畫面干擾真的很高時，才考慮加半透明底框——"
                 "除非整支影片都是亮色，否則底框會顯得突兀")
    return "；".join(steps) + "。"


def analyze_legibility(media_path: str, cues: list,
                       style: Optional[dict] = None,
                       config: Optional[dict] = None,
                       progress_cb: Optional[Callable[[float, str], None]]
                       = None) -> dict:
    """
    對素材與字幕跑可讀性健檢，回傳 evaluate_legibility 的結果並附上取樣。
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    if not has_video_stream(media_path):
        raise ValueError("這個檔案沒有影像軌，無法檢查字幕與畫面的對比。")

    settings = resolve_legibility_settings(config)
    style = style or {}

    def report(ratio, message):
        if callable(progress_cb):
            progress_cb(ratio, message)

    report(0.05, "讀取影片資訊…")
    width, height = _probe_size(media_path)
    if width <= 0 or height <= 0:
        raise ValueError("讀不到影片尺寸，無法計算字幕位置。")
    duration = probe_duration(media_path)
    crop = subtitle_band(width, height, style, settings["band_ratio"])

    picked = sample_times(cues, settings["sample_count"])
    samples = []
    total = max(len(picked), 1)
    for index, (time_s, text) in enumerate(picked):
        report(0.1 + 0.85 * (index / total),
               f"量測字幕背景（{index + 1}/{len(picked)}）…")
        if duration and time_s >= duration:
            continue
        values = measure_band(media_path, time_s, crop)
        if "YAVG" not in values:
            continue
        samples.append({
            "time": time_s,
            "text": text,
            "luma": values["YAVG"],
            "spread": values.get("YHIGH", 0.0) - values.get("YLOW", 0.0),
        })

    result = evaluate_legibility(samples, style, settings)
    result["samples"] = samples
    result["band"] = crop
    result["size"] = (width, height)
    report(1.0, "完成")
    return result


def _probe_size(media_path: str, timeout: int = 60) -> tuple:
    """用 ffprobe 取得影片的 (寬, 高)；讀不到時回 (0, 0)。"""
    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0", media_path,
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return (0, 0)
    text = (completed.stdout or b"").decode("utf-8", errors="ignore").strip()
    first = text.splitlines()[0] if text else ""
    match = re.match(r"^(\d+)x(\d+)$", first)
    if not match:
        return (0, 0)
    return (int(match.group(1)), int(match.group(2)))


def format_legibility_report(result: dict,
                             settings: Optional[dict] = None) -> str:
    """把字幕可讀性健檢結果排成純文字報告（GUI 顯示與 CLI 輸出共用）。"""
    settings = settings or resolve_legibility_settings()
    lines = ["===== 字幕可讀性健檢（燒錄後在畫面上看得清楚嗎）====="]
    findings = (result or {}).get("findings") or []
    if not findings:
        lines.append("・沒有可分析的內容。")
        return "\n".join(lines)

    for finding in findings:
        icon = _LEVEL_ICONS.get(finding["level"], "・")
        lines.append(f"{icon} {finding['title']}：{finding['detail']}")
        if finding.get("advice"):
            lines.append(f"    建議：{finding['advice']}")

    stats = result.get("stats") or {}
    if stats:
        lines.append("")
        lines.append("量測數值：")
        lines.append(f"  文字亮度 {stats.get('text_luma', 0):.0f}"
                     f"、描邊寬度 {stats.get('stroke_width', 0)}")
        lines.append(f"  取樣 {stats.get('sample_count', 0)} 點，"
                     f"平均對比 {stats.get('average_contrast', 0):.0f}、"
                     f"最低 {stats.get('min_contrast', 0):.0f}")

    weak = result.get("weak") or []
    if weak:
        lines.append("")
        lines.append("對比不足的句子：")
        for sample in weak[:10]:
            text = sample.get("text", "")
            shown = text if len(text) <= 24 else text[:24] + "…"
            lines.append(f"  {format_timestamp(sample['time'])} 「{shown}」")
        if len(weak) > 10:
            lines.append(f"  （另有 {len(weak) - 10} 句未列出）")

    lines.append("")
    if result.get("ok"):
        lines.append("結論：字幕在畫面上看得清楚，可以直接燒錄。")
    else:
        lines.append("結論：有段落的字幕會糊在背景裡——這種問題通常要等到"
                     "燒錄完、播出去才發現。調整上述設定後再燒錄一次即可。")
    return "\n".join(lines)
