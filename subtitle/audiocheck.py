# -*- coding: utf-8 -*-
"""
音訊健檢模組：上片前一鍵檢查音訊常見翻車點。

「畫面差觀眾會忍，聲音差觀眾直接關掉」——爆音（clipping）、整體音量
過小、底噪過高、麥克風只錄到單邊聲道，都是創作者傳上 YouTube 之後
才發現的常見悲劇，而且事後幾乎救不回來。本模組以 ffmpeg 的 astats
與 loudnorm 濾鏡各掃一次音軌（無需重新編碼），把量測值對照可調門檻
產出「✔ 通過／⚠ 注意／✘ 建議修正」的健檢報告與具體修法建議。

純 ffmpeg 量測、純文字規則判讀，核心邏輯零 GUI 依賴，供 CLI 重用。
"""

from __future__ import annotations

import re
import subprocess
from typing import Callable, Optional

from .audio import measure_loudness
from .burner import ffmpeg_available

# 使用者可調的判定門檻（GUI 可調並記憶於 config.json 的 "audiocheck"）。
DEFAULT_AUDIOCHECK = {
    "quiet_lufs": -19.0,      # 整體響度低於此值（LUFS）判定「太小聲」
    "noise_floor_db": -50.0,  # 底噪高於此值（dB）判定「底噪偏高」
    "clip_peak_db": -0.5,     # 峰值高於此值（dB）視為爆音風險
    "balance_db": 6.0,        # 左右聲道 RMS 相差超過此值（dB）判定不平衡
}
_QUIET_RANGE = (-30.0, -10.0)
_NOISE_RANGE = (-90.0, -20.0)
_CLIP_RANGE = (-6.0, 0.0)
_BALANCE_RANGE = (2.0, 20.0)

# 判定等級（報告以圖示呈現）。
LEVEL_GOOD = "good"
LEVEL_WARN = "warn"
LEVEL_BAD = "bad"
_LEVEL_ICONS = {LEVEL_GOOD: "✔", LEVEL_WARN: "⚠", LEVEL_BAD: "✘"}

# astats 輸出行（stderr）：「[Parsed_astats_0 @ ...] Peak level dB: -1.03」。
_ASTATS_KEYS = {
    "Peak level dB": "peak_db",
    "RMS level dB": "rms_db",
    "Noise floor dB": "noise_floor_db",
    "Flat factor": "flat_factor",
    "Peak count": "peak_count",
}
_ASTATS_LINE_RE = re.compile(
    r"\]\s*(Channel:\s*\d+|Overall|[A-Za-z ]+dB|Flat factor|Peak count)"
    r"(?::\s*(\S+))?\s*$")


def _clamp_float(value, low, high, fallback):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_audiocheck_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出健檢門檻，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_AUDIOCHECK)
    if config:
        raw.update({k: v for k, v in config.get("audiocheck", {}).items()
                    if v is not None})
    return {
        "quiet_lufs": _clamp_float(raw.get("quiet_lufs"), *_QUIET_RANGE,
                                   DEFAULT_AUDIOCHECK["quiet_lufs"]),
        "noise_floor_db": _clamp_float(
            raw.get("noise_floor_db"), *_NOISE_RANGE,
            DEFAULT_AUDIOCHECK["noise_floor_db"]),
        "clip_peak_db": _clamp_float(raw.get("clip_peak_db"), *_CLIP_RANGE,
                                     DEFAULT_AUDIOCHECK["clip_peak_db"]),
        "balance_db": _clamp_float(raw.get("balance_db"), *_BALANCE_RANGE,
                                   DEFAULT_AUDIOCHECK["balance_db"]),
    }


def parse_astats(text: str) -> Optional[dict]:
    """
    解析 ffmpeg astats 濾鏡的 stderr 輸出。

    回傳 {"overall": {...}, "channels": [{...}, ...]}，各 dict 可能含
    peak_db / rms_db / noise_floor_db / flat_factor / peak_count；
    完全解析不到時回傳 None。
    """
    overall = {}
    channels = []
    current = None
    for line in (text or "").splitlines():
        if "Parsed_astats" not in line:
            continue
        match = _ASTATS_LINE_RE.search(line)
        if not match:
            continue
        head, value = match.group(1), match.group(2)
        if head.startswith("Channel"):
            current = {}
            channels.append(current)
            continue
        if head == "Overall":
            current = overall
            continue
        key = _ASTATS_KEYS.get(head.strip())
        if key is None or current is None or value is None:
            continue
        try:
            current[key] = float(value)
        except ValueError:
            pass  # "nan"/"unknown" 之類的值直接略過。
    if not overall and not channels:
        return None
    return {"overall": overall, "channels": channels}


def measure_astats(media_path: str, timeout: int = 600) -> Optional[dict]:
    """跑 astats 濾鏡量測音軌統計；ffmpeg 不可用或失敗時回傳 None。"""
    if not ffmpeg_available():
        return None
    command = [
        "ffmpeg", "-hide_banner", "-nostats",
        "-i", media_path,
        "-vn", "-af", "astats",
        "-f", "null", "-",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    stderr = (completed.stderr or b"").decode("utf-8", errors="ignore")
    return parse_astats(stderr)


def _finding(level: str, title: str, detail: str, advice: str = "") -> dict:
    return {"level": level, "title": title, "detail": detail,
            "advice": advice}


def evaluate(loudness: Optional[dict], astats: Optional[dict],
             settings: Optional[dict] = None) -> list:
    """
    把量測值對照門檻，回傳健檢結果清單（含通過項，報告呈現為檢查表）。

    loudness 為 measure_loudness() 的結果（input_i / input_tp ...）、
    astats 為 parse_astats() 的結果；兩者皆可為 None（該項顯示無法量測）。
    """
    settings = settings or resolve_audiocheck_settings()
    findings = []

    # 1) 整體響度：太小聲的影片 YouTube 不會幫忙調大。
    lufs = None
    if loudness:
        try:
            lufs = float(loudness.get("input_i"))
        except (TypeError, ValueError):
            lufs = None
    if lufs is None:
        findings.append(_finding(
            LEVEL_WARN, "整體響度", "無法量測（音軌缺失或 ffmpeg 失敗）。"))
    elif lufs < settings["quiet_lufs"]:
        findings.append(_finding(
            LEVEL_BAD, "整體響度",
            f"量測 {lufs:.1f} LUFS，低於門檻 {settings['quiet_lufs']:.1f}。"
            "YouTube 只會把太大聲的調小、不會把太小聲的調大，"
            "觀眾得自己開大音量。",
            "燒錄或輸出時勾選「響度正規化」（目標 -14 LUFS）即可自動修正。"))
    elif lufs > -13.0:
        findings.append(_finding(
            LEVEL_WARN, "整體響度",
            f"量測 {lufs:.1f} LUFS，高於 YouTube 的 -14 LUFS 標準，"
            "平台會自動調小（無損），但通常伴隨壓縮過度的觀感。",
            "可勾選「響度正規化」統一到 -14 LUFS。"))
    else:
        findings.append(_finding(
            LEVEL_GOOD, "整體響度",
            f"量測 {lufs:.1f} LUFS，符合 YouTube 播放音量範圍。"))

    overall = (astats or {}).get("overall") or {}
    channels = (astats or {}).get("channels") or []

    # 2) 爆音（clipping）：峰值貼頂＋波形削平是最難救的錄音事故。
    peak = overall.get("peak_db")
    if peak is None:
        findings.append(_finding(
            LEVEL_WARN, "爆音檢查", "無法量測峰值電平。"))
    elif peak >= settings["clip_peak_db"] and (
            overall.get("flat_factor", 0.0) > 0.0):
        findings.append(_finding(
            LEVEL_BAD, "爆音檢查",
            f"峰值 {peak:.1f} dB 已貼頂且偵測到削波"
            f"（flat factor {overall['flat_factor']:.2f}），"
            "部分段落應已爆音失真。",
            "爆音幾乎無法事後修復；重錄時請把錄音增益調低、峰值留 -6 dB "
            "餘裕。輕微爆音可嘗試剪掉該段或壓低該段音量減少刺耳感。"))
    elif peak >= settings["clip_peak_db"]:
        findings.append(_finding(
            LEVEL_WARN, "爆音檢查",
            f"峰值 {peak:.1f} dB 貼近 0 dB 上限，雖未偵測到明顯削波，"
            "但已無安全餘裕。",
            "建議錄音時峰值保持在 -6 dB 以下；輸出時開啟響度正規化"
            "（內含 -1.5 dB true peak 上限）可避免轉檔再突波。"))
    else:
        findings.append(_finding(
            LEVEL_GOOD, "爆音檢查",
            f"峰值 {peak:.1f} dB，餘裕足夠、未見削波。"))

    # 3) 底噪：冷氣聲、電流聲在安靜段落會特別明顯。
    noise = overall.get("noise_floor_db")
    if noise is None:
        findings.append(_finding(
            LEVEL_WARN, "底噪檢查", "無法量測底噪。"))
    elif noise > settings["noise_floor_db"]:
        findings.append(_finding(
            LEVEL_WARN, "底噪檢查",
            f"底噪約 {noise:.1f} dB，高於門檻 "
            f"{settings['noise_floor_db']:.1f} dB，"
            "安靜段落可能聽得到嘶聲或環境噪音。",
            "可在剪輯軟體以降噪濾鏡處理，或錄音時關閉風扇冷氣、"
            "麥克風靠近嘴巴以提高訊噪比。"))
    else:
        findings.append(_finding(
            LEVEL_GOOD, "底噪檢查",
            f"底噪約 {noise:.1f} dB，乾淨。"))

    # 4) 聲道平衡：領夾麥或介面只接一聲道時，觀眾只有一邊耳機有聲音。
    if len(channels) >= 2:
        rms = [ch.get("rms_db") for ch in channels[:2]]
        if None in rms:
            findings.append(_finding(
                LEVEL_WARN, "聲道平衡", "無法量測左右聲道電平。"))
        elif any(value == float("-inf") or value < -70.0 for value in rms):
            findings.append(_finding(
                LEVEL_BAD, "聲道平衡",
                f"左右聲道電平 {rms[0]:.1f} / {rms[1]:.1f} dB，"
                "其中一邊幾乎無聲——觀眾戴耳機時只有單邊有聲音。",
                "常見原因是單聲道麥克風接進立體聲軌；"
                "在剪輯軟體把音軌改成單聲道（或複製有聲的聲道）即可修正。"))
        elif abs(rms[0] - rms[1]) > settings["balance_db"]:
            findings.append(_finding(
                LEVEL_WARN, "聲道平衡",
                f"左右聲道電平 {rms[0]:.1f} / {rms[1]:.1f} dB，"
                f"相差超過 {settings['balance_db']:.0f} dB，聲音會偏一邊。",
                "檢查麥克風與錄音介面的聲道設定，"
                "或在剪輯軟體把音軌置中／改單聲道。"))
        else:
            findings.append(_finding(
                LEVEL_GOOD, "聲道平衡",
                f"左右聲道電平 {rms[0]:.1f} / {rms[1]:.1f} dB，平衡良好。"))
    elif len(channels) == 1:
        findings.append(_finding(
            LEVEL_GOOD, "聲道平衡", "單聲道音軌，無左右不平衡問題。"))

    return findings


def run_audio_check(
    media_path: str,
    config: Optional[dict] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> dict:
    """
    對媒體檔執行完整音訊健檢。

    回傳 {"loudness": ..., "astats": ..., "findings": [...]}；
    findings 依 evaluate() 的檢查表順序排列。
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    settings = resolve_audiocheck_settings(config)
    if progress_cb:
        progress_cb(0.05, "正在量測整體響度（1/2）...")
    loudness = measure_loudness(media_path)
    if progress_cb:
        progress_cb(0.55, "正在量測峰值、底噪與聲道電平（2/2）...")
    astats = measure_astats(media_path)
    findings = evaluate(loudness, astats, settings)
    if progress_cb:
        progress_cb(1.0, "音訊健檢完成。")
    return {"loudness": loudness, "astats": astats, "findings": findings}


def format_report(result: dict, source_name: str = "") -> str:
    """把健檢結果排成純文字報告（GUI 顯示與 CLI 輸出共用）。"""
    lines = ["===== 音訊健檢報告 ====="]
    if source_name:
        lines.append(f"素材：{source_name}")
    lines.append("")
    for finding in result.get("findings", []):
        icon = _LEVEL_ICONS.get(finding["level"], "・")
        lines.append(f"{icon} {finding['title']}：{finding['detail']}")
        if finding.get("advice"):
            lines.append(f"    建議：{finding['advice']}")
    bad = sum(1 for f in result.get("findings", [])
              if f["level"] == LEVEL_BAD)
    warn = sum(1 for f in result.get("findings", [])
               if f["level"] == LEVEL_WARN)
    lines.append("")
    if bad:
        lines.append(f"結論：{bad} 項建議修正、{warn} 項注意，"
                     "建議處理後再上傳。")
    elif warn:
        lines.append(f"結論：{warn} 項注意，可視情況處理。")
    else:
        lines.append("結論：全部通過，可放心上傳。")
    return "\n".join(lines)
