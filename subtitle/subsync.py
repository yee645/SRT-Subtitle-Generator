# -*- coding: utf-8 -*-
"""
字幕與語音同步檢查與校正：抓出「字幕跟聲音對不上」並自動算出校正參數。

調研顯示這是匯入既有字幕檔時最常見的翻車點，而且分兩種成因、解法完全
不同：

- **固定偏移（offset）**：整條字幕軌一致地早或晚，通常來自匯出設定不同、
  片頭被剪掉、或平台處理延遲。整軌平移即可修好。
- **逐漸漂移（drift）**：開頭對得上、越後面差越多，成因幾乎都是**幀率不符**
  ——為 23.976 fps 來源製作的字幕套到 25 fps 版本上會漂移約 4.3%，
  90 分鐘的影片到片尾可以差到將近 4 秒。這種單靠平移救不回來，必須
  依比例重新縮放時間軸。

坊間工具的作法是要使用者自己找出「第一句」與「最後一句」的正確時間點
當錨點再換算。本工具已經握有媒體檔本身，因此**直接從音訊推導錨點**：
以 ffmpeg 掃出全片的實際語音區間，再搜尋最能讓字幕落在語音上的
「縮放倍率 × 偏移秒數」線性校正，一次同時解決固定偏移與幀率漂移。

縮放倍率的候選值刻意取自常見幀率比（23.976／24／25／29.97／30 互換），
因為漂移的實際成因就是幀率不符；這比盲目搜尋任意倍率更穩、也更不容易
把本來就對齊的字幕「校正」壞掉。

安全設計：
- 只有在校正後的貼合度**明顯優於**原本時才會建議校正，避免對本來就
  對齊的字幕做無謂改動。
- 素材幾乎全程有聲時（例如整片配樂或連續講話沒有停頓），語音區間無法
  提供足夠的對齊資訊，此時明確回報「無法可靠判定」而不是硬給一個
  看似精確的錯誤數字。
- 校正只調整時間軸，不改動或刪除任何文字內容（與 v1.20.0 一鍵延長、
  v1.23.0 修復重疊的既有慣例一致）。

零 GUI 依賴，供字幕健檢對話框與 CLI 共用。
"""

from __future__ import annotations

import bisect
import os
import re
import subprocess
from typing import Optional

from .burner import ffmpeg_available
from .media import has_audio_stream, probe_duration

DEFAULT_SUBSYNC = {
    "silence_db": -35.0,     # 低於此音量視為無聲（dB）
    "min_silence": 0.3,      # 無聲持續超過此秒數才算一段停頓
    "max_offset": 10.0,      # 偏移搜尋範圍（±秒）
    "min_hit_rate": 0.70,    # 貼合度低於此值視為可能不同步
    "min_gain": 0.10,        # 校正後貼合度至少要提升這麼多才建議套用
    "drift_gap": 0.15,       # 頭尾貼合度落差超過此值即懷疑逐漸漂移
}

_SILENCE_DB_RANGE = (-60.0, -20.0)
_MIN_SILENCE_RANGE = (0.1, 2.0)
_MAX_OFFSET_RANGE = (1.0, 60.0)
_HIT_RATE_RANGE = (0.3, 0.95)
_MIN_GAIN_RANGE = (0.02, 0.5)
_DRIFT_GAP_RANGE = (0.05, 0.5)

# 語音覆蓋率高於此值時，語音區間幾乎連成一片，無法提供對齊資訊。
_DENSE_SPEECH_COVERAGE = 0.92
# 搜尋解析度：先粗掃再於最佳點附近細掃，避免整段用細解析度硬跑。
_COARSE_STEP = 0.25
_FINE_STEP = 0.02

# 縮放倍率候選：常見幀率互換比值（漂移的實際成因就是幀率不符）。
_FPS_SCALES = (
    (1.0, "無縮放"),
    (25.0 / 24.0, "24→25 fps"),
    (24.0 / 25.0, "25→24 fps"),
    (25.0 / 23.976, "23.976→25 fps"),
    (23.976 / 25.0, "25→23.976 fps"),
    (30.0 / 29.97, "29.97→30 fps"),
    (29.97 / 30.0, "30→29.97 fps"),
)

_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(\d+(?:\.\d+)?)")

KIND_OK = "ok"
KIND_OFFSET = "offset"
KIND_DRIFT = "drift"
KIND_UNRELIABLE = "unreliable"


def _clamp(value, low, high, fallback):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_subsync_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出同步檢查參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_SUBSYNC)
    if config:
        raw.update({k: v for k, v in config.get("subsync", {}).items()
                    if v is not None})
    return {
        "silence_db": _clamp(raw.get("silence_db"), *_SILENCE_DB_RANGE,
                             DEFAULT_SUBSYNC["silence_db"]),
        "min_silence": _clamp(raw.get("min_silence"), *_MIN_SILENCE_RANGE,
                              DEFAULT_SUBSYNC["min_silence"]),
        "max_offset": _clamp(raw.get("max_offset"), *_MAX_OFFSET_RANGE,
                             DEFAULT_SUBSYNC["max_offset"]),
        "min_hit_rate": _clamp(raw.get("min_hit_rate"), *_HIT_RATE_RANGE,
                               DEFAULT_SUBSYNC["min_hit_rate"]),
        "min_gain": _clamp(raw.get("min_gain"), *_MIN_GAIN_RANGE,
                           DEFAULT_SUBSYNC["min_gain"]),
        "drift_gap": _clamp(raw.get("drift_gap"), *_DRIFT_GAP_RANGE,
                            DEFAULT_SUBSYNC["drift_gap"]),
    }


def parse_speech_spans(stderr: str, duration: float) -> list:
    """
    把 silencedetect 的輸出轉成「語音區間」清單（無聲區間的補集）。

    silencedetect 報的是無聲區段，實際有聲的部分就是其補集；最後一段
    無聲若延伸到檔尾則沒有對應的 silence_end 行，需補上檔案總長。
    """
    silences = []
    start = None
    for line in (stderr or "").splitlines():
        match = _SILENCE_START_RE.search(line)
        if match:
            start = max(float(match.group(1)), 0.0)
            continue
        match = _SILENCE_END_RE.search(line)
        if match and start is not None:
            silences.append((start, float(match.group(1))))
            start = None
    if start is not None:
        silences.append((start, duration))

    spans = []
    cursor = 0.0
    for sil_start, sil_end in sorted(silences):
        if sil_start > cursor:
            spans.append((cursor, min(sil_start, duration)))
        cursor = max(cursor, sil_end)
    if cursor < duration:
        spans.append((cursor, duration))
    return [(s, e) for s, e in spans if e > s]


def detect_speech_spans(media_path: str, settings: Optional[dict] = None,
                        timeout: int = 600) -> list:
    """以單次 ffmpeg silencedetect 掃出全片語音區間。"""
    settings = settings or resolve_subsync_settings()
    duration = probe_duration(media_path)
    command = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", media_path, "-vn",
        "-af", (f"silencedetect=n={settings['silence_db']:.0f}dB"
                f":d={settings['min_silence']:.2f}"),
        "-f", "null", "-",
    ]
    try:
        completed = subprocess.run(command, capture_output=True,
                                   timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return []
    stderr = (completed.stderr or b"").decode("utf-8", errors="ignore")
    return parse_speech_spans(stderr, duration)


def _span_index(spans: list) -> tuple:
    """把語音區間拆成兩個平行陣列，供 bisect 快速查詢。"""
    return [s for s, _e in spans], [e for _s, e in spans]


def overlap_ratio(cues: list, spans: list, scale: float = 1.0,
                  offset: float = 0.0, index: Optional[tuple] = None) -> float:
    """
    計算字幕落在語音上的「貼合度」：套用 t'=scale*t+offset 後，字幕總時長
    有多少比例與語音區間重疊（0.0~1.0）。

    以重疊時長比例（而非單看起點）當分數，對「字幕被切在句中」這種正常
    情況比較寬容，對整體偏移／漂移仍然敏感。
    """
    if not cues or not spans:
        return 0.0
    starts, ends = index if index else _span_index(spans)
    total = 0.0
    covered = 0.0
    for cue in cues:
        cue_start = float(cue.get("start", 0.0)) * scale + offset
        cue_end = float(cue.get("end", 0.0)) * scale + offset
        length = cue_end - cue_start
        if length <= 0:
            continue
        total += length
        # 第一個結束時間 > cue_start 的語音區間，之後往右掃到不重疊為止。
        pos = bisect.bisect_right(ends, cue_start)
        while pos < len(starts) and starts[pos] < cue_end:
            covered += (min(cue_end, ends[pos]) - max(cue_start, starts[pos]))
            pos += 1
    return covered / total if total > 0 else 0.0


def head_tail_gap(cues: list, spans: list,
                  index: Optional[tuple] = None) -> float:
    """
    回傳「頭段貼合度 − 尾段貼合度」，用來偵測逐漸漂移。

    漂移的物理特徵是誤差隨時間累積：開頭幾乎沒偏、越後面差越多。單看
    全片平均貼合度會被對得很準的開頭稀釋掉，導致明明片尾已經差了好幾秒
    卻仍高於門檻而漏判——實測 60 秒素材套上 25→23.976 fps 漂移時，全片
    平均仍有 0.76，但尾段已經掉到 0.66。因此另外比較頭尾三分之一。
    """
    ordered = sorted(cues or [], key=lambda c: float(c.get("start", 0.0)))
    if len(ordered) < 3:
        return 0.0
    third = max(len(ordered) // 3, 1)
    head = overlap_ratio(ordered[:third], spans, index=index)
    tail = overlap_ratio(ordered[-third:], spans, index=index)
    return head - tail


def _best_offset(cues: list, spans: list, scale: float, max_offset: float,
                 index: tuple) -> tuple:
    """
    在給定縮放倍率下搜尋最佳偏移，回傳 (偏移秒數, 貼合度)。

    先以較粗的步進掃過整個範圍，再於最佳點附近以細步進微調——比整段
    都用細解析度硬掃省下大量計算，結果實質相同。
    """
    best_offset, best_score = 0.0, -1.0
    steps = int(max_offset / _COARSE_STEP)
    for i in range(-steps, steps + 1):
        offset = i * _COARSE_STEP
        score = overlap_ratio(cues, spans, scale, offset, index)
        if score > best_score:
            best_offset, best_score = offset, score
    fine_steps = int(_COARSE_STEP / _FINE_STEP)
    for i in range(-fine_steps, fine_steps + 1):
        offset = best_offset + i * _FINE_STEP
        if abs(offset) > max_offset:
            continue
        score = overlap_ratio(cues, spans, scale, offset, index)
        if score > best_score:
            best_offset, best_score = offset, score
    return best_offset, best_score


def estimate_correction(cues: list, spans: list,
                        settings: Optional[dict] = None) -> dict:
    """
    搜尋最能讓字幕貼合語音的線性校正（縮放倍率 × 偏移秒數）。

    縮放倍率只試常見幀率比值——漂移的成因就是幀率不符，限定候選比盲目
    搜尋任意倍率更穩，也更不容易把本來就對齊的字幕改壞。
    """
    settings = settings or resolve_subsync_settings()
    index = _span_index(spans)
    baseline = overlap_ratio(cues, spans, 1.0, 0.0, index)
    best = {"scale": 1.0, "offset": 0.0, "score": baseline,
            "scale_label": "無縮放"}
    for scale, label in _FPS_SCALES:
        offset, score = _best_offset(cues, spans, scale,
                                     settings["max_offset"], index)
        if score > best["score"]:
            best = {"scale": scale, "offset": offset, "score": score,
                    "scale_label": label}
    best["baseline"] = baseline
    best["gain"] = best["score"] - baseline
    return best


def analyze_sync(media_path: str, cues: list,
                 settings: Optional[dict] = None) -> dict:
    """
    檢查字幕是否與實際語音同步，需要時算出建議的校正參數。

    回傳 {"kind", "hit_rate", "corrected_hit_rate", "scale", "offset",
          "scale_label", "speech_coverage", "spans"}；
    kind 為 ok／offset／drift／unreliable。
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    if not os.path.exists(media_path):
        raise FileNotFoundError(f"找不到檔案：{media_path}")
    if not has_audio_stream(media_path):
        raise ValueError("此檔案沒有音訊軌，無法檢查字幕與語音是否同步。")
    if not cues:
        raise ValueError("目前沒有字幕可供檢查。")

    settings = settings or resolve_subsync_settings()
    duration = probe_duration(media_path)
    spans = detect_speech_spans(media_path, settings)
    speech_total = sum(end - start for start, end in spans)
    coverage = speech_total / duration if duration > 0 else 0.0

    index = _span_index(spans) if spans else ([], [])
    gap = head_tail_gap(cues, spans, index) if spans else 0.0
    result = {
        "spans": spans,
        "speech_coverage": coverage,
        "hit_rate": overlap_ratio(cues, spans, index=index),
        "head_tail_gap": gap,
        "corrected_hit_rate": None,
        "scale": 1.0,
        "offset": 0.0,
        "scale_label": "無縮放",
        "kind": KIND_OK,
    }

    if not spans or coverage >= _DENSE_SPEECH_COVERAGE:
        # 幾乎全程有聲：語音區間提供不了對齊資訊，硬算只會得到假精確的
        # 數字，明確回報無法判定比較誠實。
        result["kind"] = KIND_UNRELIABLE
        return result

    # 全片平均貼合度過關，還要再確認頭尾沒有明顯落差——漂移會被對得準的
    # 開頭稀釋掉平均值，只看平均會漏判。
    if (result["hit_rate"] >= settings["min_hit_rate"]
            and gap < settings["drift_gap"]):
        return result  # 已經貼合，不需要（也不應該）動它。

    best = estimate_correction(cues, spans, settings)
    result["corrected_hit_rate"] = best["score"]
    if best["gain"] < settings["min_gain"]:
        # 找不到明顯更好的校正：可能是字幕內容本來就跟這支素材不符，
        # 亂套一個校正只會更糟。
        result["kind"] = KIND_UNRELIABLE
        return result

    result["scale"] = best["scale"]
    result["offset"] = best["offset"]
    result["scale_label"] = best["scale_label"]
    result["kind"] = KIND_OFFSET if best["scale"] == 1.0 else KIND_DRIFT
    return result


def apply_sync_correction(cues: list, scale: float = 1.0,
                          offset: float = 0.0) -> list:
    """
    套用線性校正 t'=scale*t+offset，回傳新的字幕清單。

    只調整時間軸、不改動任何文字內容；原始清單不受影響（回傳新物件）。
    校正後為負的時間一律夾到 0，避免產生無效時間軸。
    """
    corrected = []
    for cue in cues or []:
        new_cue = dict(cue)
        new_cue["start"] = max(float(cue.get("start", 0.0)) * scale + offset,
                               0.0)
        new_cue["end"] = max(float(cue.get("end", 0.0)) * scale + offset, 0.0)
        if cue.get("words"):
            new_cue["words"] = [
                {**word,
                 "start": max(float(word.get("start", 0.0)) * scale + offset,
                              0.0),
                 "end": max(float(word.get("end", 0.0)) * scale + offset, 0.0)}
                for word in cue["words"]]
        corrected.append(new_cue)
    return corrected


def format_sync_report(result: dict) -> str:
    """把同步檢查結果排成純文字報告（GUI 顯示與 CLI 輸出共用）。"""
    lines = ["===== 字幕與語音同步檢查 ====="]
    if not result:
        lines.append("・尚未檢查。")
        return "\n".join(lines)

    kind = result.get("kind")
    hit = result.get("hit_rate") or 0.0
    if kind == KIND_UNRELIABLE:
        if result.get("speech_coverage", 0.0) >= _DENSE_SPEECH_COVERAGE:
            lines.append("・素材幾乎全程有聲（連續講話或整片配樂），"
                         "語音區間無法提供足夠的對齊資訊，略過同步判定。")
        else:
            lines.append(f"⚠ 字幕與語音貼合度偏低（{hit * 100:.0f}%），"
                         "但找不到明顯更好的校正參數。")
            lines.append("    建議：可能是這份字幕本來就不是這支素材的，"
                         "或素材中段被剪過而不是單純的整體偏移；"
                         "請確認字幕來源是否正確。")
        return "\n".join(lines)

    if kind == KIND_OK:
        lines.append(f"✔ 字幕與語音貼合度 {hit * 100:.0f}%，同步正常。")
        return "\n".join(lines)

    corrected = result.get("corrected_hit_rate") or 0.0
    offset = result.get("offset", 0.0)
    direction = "延後" if offset > 0 else "提前"
    lines.append(f"✘ 字幕與語音不同步：目前貼合度僅 {hit * 100:.0f}%，"
                 f"套用建議校正後可達 {corrected * 100:.0f}%。")
    if kind == KIND_DRIFT:
        # 偏移可忽略時不要贅印「並提前 0.00 秒」這種沒有資訊的句子。
        shift_note = (f"並{direction} {abs(offset):.2f} 秒"
                      if abs(offset) >= 0.05 else "")
        lines.append(f"    判定為「逐漸漂移」（幀率不符，{result['scale_label']}）："
                     f"時間軸需縮放 {result['scale']:.4f} 倍{shift_note}。")
        lines.append("    說明：開頭對得上、越後面差越多，通常是字幕製作時的"
                     "幀率與這支影片不同；單純整軌平移救不回來，"
                     "必須依比例縮放。")
    else:
        lines.append(f"    判定為「固定偏移」：整軌{direction} "
                     f"{abs(offset):.2f} 秒即可對上。")
    lines.append("    可按「一鍵校正同步」自動套用（只調整時間軸，"
                 "不改動文字內容）。")
    return "\n".join(lines)
