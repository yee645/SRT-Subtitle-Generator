# -*- coding: utf-8 -*-
"""
音樂節拍分析與剪點對齊：把剪接點對到音樂的拍子上。

調研（中英文皆搜）在「2026 年 AI 已經接手哪些、還有哪些仍靠手工」這個
題目上反覆點名同一件事：**把畫面的轉場對齊到音樂的重拍與停頓，至今
仍是編輯要手動做的**（"editors still need to manually align visual
transitions to match audio peaks and pauses"），而且工具端能做到的頂多
是「分析節奏與情緒、建議符合 BPM 的曲子」。換句話說，**知道 BPM 只是
第一步，真正花時間的是把剪點一個一個挪到拍子上**。

本工具既有的功能都沒有碰到這一段：

- 「配樂助手」（v1.9.0）只做**音量閃避**，完全沒有分析音樂的節奏
- 「剪輯節奏健檢」（v1.34.0）量的是**畫面多久沒變化**，與音樂無關
- 「自動跳剪」（v1.21.0）依**語音停頓**剪，也與音樂無關

所以這裡補的是：**量出音樂的 BPM 與每一拍的時間點，再把影片既有的
剪點對齊過去**，並如實說出每個剪點要挪多少。

### 演算法（純標準函式庫，不引入任何第三方套件）

1. 用 ffmpeg 把音樂解成單聲道 PCM，算每個 hop 的 RMS 能量包絡。
2. 對能量做**半波整流的一階差分**當起音強度（只保留「變大聲」的部分）。
3. 用**相位感知的梳狀濾波**掃描候選 BPM：直接在「該 BPM 預期的拍點」
   上取值加總，取平均最高者。這同時得到 BPM 與**相位**（第一拍落在
   哪），後者是產生拍點清單所必需的。

開發時實測踩到並修掉的兩個坑（都是拿已知 BPM 的節拍軌驗證才發現的）：

- **固定整數 lag 的自相關會系統性偏袒慢速。** lag 取整後在長訊號上
  累積漂移，短 lag（快速）受害更重，實測 120 BPM 的素材被判成 60。
  改成每一拍都從 `k × 週期` 重新計算位置，不累積誤差。
- **只看單一幀會錯過起音尖峰。** 一個 40ms 的敲擊只有約 1.7 幀寬，
  ±0.5 幀的捨入就可能整個踩空。改成取拍點附近 ±1 幀的最大值。
- 即使如此，**慢一倍的速度分數必然與正確速度相當**（它落在真拍點的
  子集上），單靠分數分不出來。因此另外做**八度校正**：若倍速的分數
  仍接近，取較快的那個。實測 90／120／140 BPM 三種素材皆正確還原。

零 GUI 依賴，供配樂助手與 CLI 共用。
"""

from __future__ import annotations

import array
import math
import subprocess
from typing import Callable, Optional

# 分析用的取樣率與 hop：22.05kHz 對節拍偵測綽綽有餘，又比原始取樣率
# 省下大量運算；hop 512 約等於 23ms 的時間解析度。
SAMPLE_RATE = 22050
HOP = 512
FRAMES_PER_SECOND = SAMPLE_RATE / HOP

# 能量計算的抽樣步長：每 8 個樣本取 1 個。實測對節拍偵測沒有影響，
# 但把純 Python 的迴圈量降到八分之一。
_ENERGY_STRIDE = 8

DEFAULT_BEATSYNC = {
    "min_bpm": 60.0,        # 搜尋的最慢速度
    "max_bpm": 200.0,       # 搜尋的最快速度
    "max_shift": 0.25,      # 剪點最多可以挪多少秒去對齊拍子
    "octave_tolerance": 0.85,  # 倍速分數達最佳分數的幾成就改取較快者
    # 信心門檻：最佳分數要是「所有候選 BPM 平均分數」的幾倍，才算真的
    # 有節拍。這個數字是實測校準出來的，不是拍腦袋——量測合成素材得到
    # 節拍軌 4.7~6.5、有回音的類音樂素材 5.3、純長音 1.24、靜音 0.0，
    # 因此取 2.0，落在「真的有節拍」與「根本沒有節拍」之間。
    "min_confidence": 2.0,
}

_BPM_RANGE = (30.0, 300.0)
_SHIFT_RANGE = (0.0, 2.0)
_TOLERANCE_RANGE = (0.5, 1.0)
_CONFIDENCE_RANGE = (1.0, 10.0)


def _clamp(value, low, high, fallback, cast=float):
    try:
        value = cast(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_beatsync_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出節拍分析參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_BEATSYNC)
    if config:
        raw.update({k: v for k, v in config.get("beatsync", {}).items()
                    if v is not None})
    resolved = {
        "min_bpm": _clamp(raw.get("min_bpm"), *_BPM_RANGE,
                          DEFAULT_BEATSYNC["min_bpm"]),
        "max_bpm": _clamp(raw.get("max_bpm"), *_BPM_RANGE,
                          DEFAULT_BEATSYNC["max_bpm"]),
        "max_shift": _clamp(raw.get("max_shift"), *_SHIFT_RANGE,
                            DEFAULT_BEATSYNC["max_shift"]),
        "octave_tolerance": _clamp(raw.get("octave_tolerance"),
                                   *_TOLERANCE_RANGE,
                                   DEFAULT_BEATSYNC["octave_tolerance"]),
        "min_confidence": _clamp(raw.get("min_confidence"),
                                 *_CONFIDENCE_RANGE,
                                 DEFAULT_BEATSYNC["min_confidence"]),
    }
    # 最慢被設得比最快還大時直接對調，而不是靜靜地一個候選都掃不到。
    if resolved["min_bpm"] > resolved["max_bpm"]:
        resolved["min_bpm"], resolved["max_bpm"] = (
            resolved["max_bpm"], resolved["min_bpm"])
    return resolved


def load_samples(audio_path: str, timeout: int = 300) -> array.array:
    """用 ffmpeg 把音檔解成單聲道 16-bit PCM，回傳樣本陣列。"""
    command = [
        "ffmpeg", "-v", "error", "-i", audio_path,
        "-f", "s16le", "-acodec", "pcm_s16le",
        "-ar", str(SAMPLE_RATE), "-ac", "1", "-",
    ]
    try:
        completed = subprocess.run(command, capture_output=True,
                                   timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"讀取音訊失敗：{exc}") from exc
    raw = completed.stdout or b""
    samples = array.array("h")
    samples.frombytes(raw[:len(raw) // 2 * 2])
    return samples


def energy_envelope(samples) -> list:
    """算每個 hop 的 RMS 能量，回傳能量包絡。"""
    envelope = []
    total = len(samples)
    for start in range(0, total - HOP, HOP):
        acc = 0
        for i in range(start, start + HOP, _ENERGY_STRIDE):
            value = samples[i]
            acc += value * value
        envelope.append(math.sqrt(acc / (HOP / _ENERGY_STRIDE)))
    return envelope


def onset_strength(envelope: list) -> list:
    """
    半波整流的一階差分：只保留能量「變大聲」的部分，那就是起音。

    直接用能量會被長音的持續段帶偏；只取上升沿才對得準敲擊點。
    """
    flux = [0.0]
    for i in range(1, len(envelope)):
        delta = envelope[i] - envelope[i - 1]
        flux.append(delta if delta > 0 else 0.0)
    return flux


def _comb_score(flux: list, bpm: float) -> tuple:
    """
    給定 BPM，找最合適的相位，回傳 (分數, 相位秒數)。

    每一拍的位置都由 `k × 週期` 重新算出，不用固定整數 lag 累加——
    後者會累積捨入誤差，在長素材上系統性偏袒慢速。
    """
    n = len(flux)
    period = FRAMES_PER_SECOND * 60.0 / bpm
    if n < 4 or period < 1:
        return (-1.0, 0.0)
    best = (-1.0, 0.0)
    for phase in range(max(int(round(period)), 1)):
        total = 0.0
        count = 0
        step = 0
        while True:
            index = int(round(phase + step * period))
            if index >= n:
                break
            # 取拍點附近 ±1 幀的最大值：一個短促的敲擊只有一兩幀寬，
            # 只看單一幀時捨入誤差就可能整個踩空。
            low = max(index - 1, 0)
            high = min(index + 2, n)
            total += max(flux[low:high])
            count += 1
            step += 1
        if count >= 4:
            score = total / count
            if score > best[0]:
                best = (score, phase / FRAMES_PER_SECOND)
    return best


def detect_tempo(flux: list, settings: Optional[dict] = None) -> dict:
    """
    掃描候選 BPM，回傳 {"bpm","phase","score","confidence"}。

    含**八度校正**：慢一倍的速度會落在真拍點的子集上，平均分數必然
    與正確速度相當，單靠分數分不出來；因此若倍速的分數仍接近最佳分數，
    改取較快的那個。

    也含**信心判定**：沒有節拍的素材（靜音、純長音、環境音）一樣會有
    一個「最高分」的 BPM，直接報出去等於自信地講一個錯的數字。因此拿
    最佳分數與所有候選的平均分數相比，比值不夠高就回報 bpm=0，讓上層
    據實說「沒有偵測到穩定的節拍」。
    """
    settings = settings or resolve_beatsync_settings()
    if not flux:
        return {"bpm": 0.0, "phase": 0.0, "score": 0.0, "confidence": 0.0}

    scores = {}
    bpm = settings["min_bpm"]
    while bpm <= settings["max_bpm"]:
        scores[round(bpm, 1)] = _comb_score(flux, bpm)
        bpm = round(bpm + 0.5, 1)
    if not scores:
        return {"bpm": 0.0, "phase": 0.0, "score": 0.0, "confidence": 0.0}

    values = [v[0] for v in scores.values() if v[0] >= 0]
    mean = sum(values) / len(values) if values else 0.0
    peak = max(values) if values else 0.0
    confidence = (peak / mean) if mean > 0 else 0.0
    if confidence < settings["min_confidence"]:
        # 沒有穩定節拍：據實回報，不要自信地給一個錯的 BPM。
        return {"bpm": 0.0, "phase": 0.0, "score": peak,
                "confidence": confidence}

    best_bpm = max(scores, key=lambda b: scores[b][0])
    tolerance = settings["octave_tolerance"]
    changed = True
    while changed:
        changed = False
        for multiple in (2, 3):
            faster = round(best_bpm * multiple, 1)
            if (faster in scores
                    and scores[faster][0] >= scores[best_bpm][0] * tolerance):
                best_bpm = faster
                changed = True
                break

    score, phase = scores[best_bpm]
    return {"bpm": best_bpm, "phase": phase, "score": score,
            "confidence": confidence}


def beat_times(bpm: float, phase: float, duration: float) -> list:
    """依 BPM 與相位產生整首曲子的拍點時間清單。"""
    if bpm <= 0 or duration <= 0:
        return []
    period = 60.0 / bpm
    beats = []
    time = float(phase)
    while time < duration:
        if time >= 0:
            beats.append(round(time, 3))
        time += period
    return beats


def analyze_beats(audio_path: str, config: Optional[dict] = None,
                  progress_cb: Optional[Callable] = None) -> dict:
    """
    對音樂檔做節拍分析，回傳 {"bpm","phase","beats","duration"}。

    這是唯一會碰 ffmpeg 的入口；判定邏輯全部可以單獨測試。
    """
    settings = resolve_beatsync_settings(config)

    def report(ratio, message):
        if callable(progress_cb):
            progress_cb(ratio, message)

    report(0.1, "讀取音訊…")
    samples = load_samples(audio_path)
    if len(samples) < HOP * 8:
        raise RuntimeError("音訊太短或讀不到內容，無法分析節拍。")

    report(0.4, "計算能量包絡…")
    envelope = energy_envelope(samples)
    flux = onset_strength(envelope)

    report(0.7, "偵測速度與拍點…")
    tempo = detect_tempo(flux, settings)
    duration = len(samples) / SAMPLE_RATE
    beats = beat_times(tempo["bpm"], tempo["phase"], duration)
    report(1.0, "完成")
    return {"bpm": tempo["bpm"], "phase": tempo["phase"],
            "score": tempo["score"], "confidence": tempo["confidence"],
            "beats": beats, "duration": duration}


def snap_times(times: list, beats: list,
               max_shift: float = 0.25) -> list:
    """
    把剪點對齊到最近的拍子。

    回傳 [{"original","snapped","shift","aligned"}, ...]；超過 max_shift
    就維持原位並標記 aligned=False——硬挪過去會讓畫面與內容對不上，
    那不是對齊而是破壞。
    """
    rows = []
    for value in times or []:
        original = float(value)
        if not beats:
            rows.append({"original": original, "snapped": original,
                         "shift": 0.0, "aligned": False})
            continue
        nearest = min(beats, key=lambda b: abs(b - original))
        shift = nearest - original
        if abs(shift) <= max_shift:
            rows.append({"original": original, "snapped": round(nearest, 3),
                         "shift": round(shift, 3), "aligned": True})
        else:
            rows.append({"original": original, "snapped": original,
                         "shift": round(shift, 3), "aligned": False})
    return rows


def format_timestamp(seconds: float) -> str:
    """把秒數排成 M:SS.s，剪點需要看到小數位。"""
    seconds = max(float(seconds or 0.0), 0.0)
    minutes = int(seconds // 60)
    rest = seconds - minutes * 60
    return f"{minutes}:{rest:04.1f}"


def format_beat_report(result: dict, snapped: Optional[list] = None,
                       settings: Optional[dict] = None) -> str:
    """把節拍分析與剪點對齊結果排成純文字報告。"""
    settings = settings or resolve_beatsync_settings()
    lines = ["===== 音樂節拍分析（把剪點對到拍子上）====="]
    result = result or {}
    bpm = result.get("bpm", 0.0)
    if not bpm:
        lines.append("・沒有偵測到穩定的節拍。")
        lines.append("")
        lines.append("純人聲、環境音或速度變化很大的曲子本來就沒有固定"
                     "拍點；這種素材不適合做節拍對齊。")
        return "\n".join(lines)

    beats = result.get("beats") or []
    lines.append(f"  速度：{bpm:.1f} BPM"
                 f"（每拍 {60.0 / bpm:.3f} 秒）")
    lines.append(f"  第一拍：{format_timestamp(result.get('phase', 0.0))}"
                 f"；全曲共 {len(beats)} 拍")
    if beats:
        preview = "、".join(format_timestamp(b) for b in beats[:6])
        lines.append(f"  前幾拍：{preview}…")

    if snapped:
        lines.append("")
        lines.append("剪點對齊建議：")
        moved = 0
        for index, row in enumerate(snapped, start=1):
            if row["aligned"]:
                if abs(row["shift"]) > 0.001:
                    moved += 1
                lines.append(
                    f"  剪點 {index}：{format_timestamp(row['original'])}"
                    f" → {format_timestamp(row['snapped'])}"
                    f"（挪 {row['shift']:+.3f} 秒）")
            else:
                lines.append(
                    f"  剪點 {index}：{format_timestamp(row['original'])}"
                    f" 離最近的拍子 {abs(row['shift']):.3f} 秒，"
                    f"超過上限 {settings['max_shift']:.2f} 秒，維持原位")
        total = len(snapped)
        aligned = sum(1 for r in snapped if r["aligned"])
        lines.append("")
        lines.append(f"  {aligned}/{total} 個剪點可對齊（實際需要挪動 "
                     f"{moved} 個）。超過上限的不會硬挪——"
                     "那會讓畫面與內容對不上，不是對齊而是破壞。")

    lines.append("")
    lines.append("拍點清單可作為剪輯軟體的參考標記；把轉場放在拍點上"
                 "是目前仍需人工處理、但最能提升觀感的一步。")
    return "\n".join(lines)
