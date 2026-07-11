# -*- coding: utf-8 -*-
"""
審片助手核心模組：用逐字稿快速審素材、找可用片段。

拍完影片後最花時間的是「來回拉時間軸找片段」。本模組改用文字審片：

1. 以 Whisper 逐字時間軸把素材切成「講話段落」，讀文字遠比看影片快。
2. 自動標記三類常見的可剪內容，並給出保留 / 捨棄建議：
   - 冷場：長時間無人聲（預設 ≥ 2 秒），建議捨棄（自動跳剪）。
   - 重複拍攝：同一句話重講多次（YouTuber 吃螺絲重來），
     內容相近的相鄰段落只保留最後一次，前面的建議捨棄。
   - 口頭禪密集：「呃、嗯、欸」等填充詞過多的段落，標記供人工複查。
3. 決定保留哪些段落後，可直接輸出：
   - 粗剪影片：ffmpeg 把保留段落串成一支影片（自動跳剪版）。
   - EDL（CMX3600）：匯入 Premiere / DaVinci Resolve 繼續精剪。
   - CSV 片段清單：Excel 檢視或存檔備查。
   - YouTube 章節草稿：直接貼到影片說明欄。

本模組不依賴任何 GUI 元件，供 gui/review_window.py 與 cli.py 共同使用。
"""

from __future__ import annotations

import difflib
import html
import math
import re
import statistics
import subprocess
from typing import Callable, Optional

from .burner import ffmpeg_available, _stream_progress
from .segmenter import _is_cjk_char

ProgressCallback = Callable[[str, Optional[float]], None]

# 講話段落之間的靜音超過此秒數即切成兩段（比字幕斷句的停頓更寬鬆）。
DEFAULT_SEGMENT_GAP = 1.0
# 視為「冷場」的最短靜音秒數（建議捨棄的無人聲區間）。
DEFAULT_SILENCE_GAP = 2.0
# 兩段文字相似度達此比例即視為重複拍攝。
DEFAULT_TAKE_SIMILARITY = 0.72
# 重複拍攝比對時，往後看幾個段落（重來通常緊接在原句之後）。
_TAKE_LOOKAHEAD = 3
# 參與重複比對的最短字數（太短的句子容易誤判，如「好」「OK」）。
_TAKE_MIN_CHARS = 6
# 每 10 個字出現多少個填充詞即標記「口頭禪多」。
_FILLER_DENSITY = 0.08

# 中文填充詞（單字，直接數出現次數）。
_FILLER_CJK = "呃嗯欸蛤齁"
# 英文填充詞（整字比對）。
_FILLER_LATIN = re.compile(r"\b(um+|uh+|er+|hmm+)\b", re.IGNORECASE)

# 粗剪時每段前後保留的緩衝秒數，避免切字頭字尾。
_CUT_PADDING = 0.15

# 標記字串（GUI 與匯出共用）。
TAG_SILENCE = "冷場"
TAG_REPEATED = "重複拍攝"
TAG_FILLER = "口頭禪多"
TAG_HIGHLIGHT = "精彩"

# 精彩片段偵測：情緒高張的口語詞（中英）。
_EXCITE_WORDS = (
    "哇", "太扯", "太強", "太神", "太猛", "超猛", "超強", "超扯", "超好笑",
    "笑死", "天啊", "傻眼", "不會吧", "絕了", "誇張", "驚人", "太厲害",
    "amazing", "wow", "insane", "crazy", "incredible", "awesome", "unbelievable",
)
_EXCLAIM_CHARS = "！!？?"

# 精彩分數門檻：達標即標記為精彩片段（會除以使用者敏感度倍率）。
_HIGHLIGHT_THRESHOLD = 1.8

# 審片偵測參數的預設值（與 config._DEFAULT_REVIEW 對應；設定缺漏時的保底）。
DEFAULT_SETTINGS = {
    "highlight_sensitivity": 1.0,
    "extra_excite_words": "",
    "filler_words": _FILLER_CJK,
    "silence_gap": DEFAULT_SILENCE_GAP,
    "segment_gap": DEFAULT_SEGMENT_GAP,
    "take_similarity": DEFAULT_TAKE_SIMILARITY,
    "filler_density": _FILLER_DENSITY,
    "chapter_min_seconds": 60.0,
}


def resolve_settings(config: Optional[dict] = None) -> dict:
    """
    從完整設定 dict 取出審片偵測參數，缺漏欄位以預設值補齊並做範圍夾限。

    回傳的 dict 另含解析好的 ``excite_words``（內建＋使用者自訂）與
    ``filler_chars``（口頭禪單字表），供 analyze 直接使用。
    """
    raw = dict(DEFAULT_SETTINGS)
    if config:
        raw.update({k: v for k, v in config.get("review", {}).items()
                    if v is not None})

    def clamp(value, low, high, fallback):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return fallback
        return max(low, min(value, high))

    extra = [w.strip().lower()
             for w in re.split(r"[,，、\s]+", str(raw.get("extra_excite_words") or ""))
             if w.strip()]
    filler = str(raw.get("filler_words") or "").strip() or _FILLER_CJK

    return {
        "highlight_sensitivity": clamp(
            raw.get("highlight_sensitivity"), 0.2, 3.0, 1.0),
        "extra_excite_words": str(raw.get("extra_excite_words") or ""),
        "filler_words": filler,
        "silence_gap": clamp(raw.get("silence_gap"), 0.5, 10.0,
                             DEFAULT_SILENCE_GAP),
        "segment_gap": clamp(raw.get("segment_gap"), 0.4, 5.0,
                             DEFAULT_SEGMENT_GAP),
        "take_similarity": clamp(raw.get("take_similarity"), 0.5, 0.95,
                                 DEFAULT_TAKE_SIMILARITY),
        "filler_density": clamp(raw.get("filler_density"), 0.02, 0.5,
                                _FILLER_DENSITY),
        "chapter_min_seconds": clamp(raw.get("chapter_min_seconds"),
                                     10.0, 600.0, 60.0),
        "excite_words": tuple(_EXCITE_WORDS) + tuple(extra),
        "filler_chars": filler,
    }

# 分類顏色（GUI 時間軸、清單列與 HTML 報告共用，確保視覺一致）。
CATEGORY_COLORS = {
    "highlight": "#2e9e44",   # 精彩：綠
    "review": "#e6a817",      # 待審視（重複拍攝 / 口頭禪多）：琥珀
    "silence": "#9a9a9a",     # 冷場：灰
    "normal": "#4a90d9",      # 一般內容：藍
}
CATEGORY_LABELS = {
    "highlight": "精彩片段",
    "review": "待審視",
    "silence": "冷場",
    "normal": "一般內容",
}


def categorize(item: dict) -> str:
    """把段落歸入四種視覺分類：silence / review / highlight / normal。"""
    if item["kind"] == "silence":
        return "silence"
    tags = set(item.get("tags", ()))
    if TAG_REPEATED in tags:
        return "review"
    if TAG_HIGHLIGHT in tags:
        return "highlight"
    if TAG_FILLER in tags:
        return "review"
    return "normal"


def _join_words(words) -> str:
    """把逐字結果串回句子：拉丁字之間補空白、中日韓文字直接相連。"""
    parts = []
    for item in words:
        text = item["word"]
        if parts and text and not _is_cjk_char(text[0]) \
                and not _is_cjk_char(parts[-1][-1]):
            parts.append(" ")
        parts.append(text)
    return "".join(parts).strip()


def count_fillers(text: str, filler_chars: str = _FILLER_CJK) -> int:
    """計算文字中的填充詞數量（中文單字表可自訂 + 英文整字）。"""
    count = sum(text.count(ch) for ch in filler_chars)
    count += len(_FILLER_LATIN.findall(text))
    return count


def _normalize_for_compare(text: str) -> str:
    """重複拍攝比對前的正規化：去標點、空白、統一小寫。"""
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE).lower()


def compute_loudness(media_path: str, hop: float = 0.5) -> list:
    """
    以 ffmpeg 解出單聲道 PCM 並計算每個時間窗的 RMS 音量（0.0~1.0）。

    回傳 [(時間秒, rms), ...]；ffmpeg 不可用或解碼失敗時回傳空清單，
    呼叫端應能在沒有音量資料的情況下正常運作（精彩偵測退化為純文字訊號）。
    """
    if not ffmpeg_available():
        return []
    sample_rate = 16000
    chunk_samples = max(int(sample_rate * hop), 1)
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", media_path, "-vn",
        "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "pipe:1",
    ]
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return []

    import array
    result = []
    time_cursor = 0.0
    try:
        while True:
            chunk = process.stdout.read(chunk_samples * 2)
            if not chunk:
                break
            samples = array.array("h", chunk[: len(chunk) - (len(chunk) % 2)])
            if not samples:
                break
            # 大檔用間隔取樣減少計算量；RMS 對此不敏感。
            step = 4 if len(samples) > 2000 else 1
            picked = samples[::step]
            mean_square = sum(int(v) * int(v) for v in picked) / len(picked)
            result.append((time_cursor, math.sqrt(mean_square) / 32768.0))
            time_cursor += hop
    finally:
        try:
            process.stdout.close()
            process.wait(timeout=10)
        except Exception:
            process.kill()
    return result


def _mean_energy(start: float, end: float, loudness: list) -> Optional[float]:
    """取段落時間範圍內的平均 RMS；無資料時回傳 None。"""
    values = [value for stamp, value in loudness if start <= stamp < end]
    if not values:
        return None
    return statistics.fmean(values)


def _excitement_hits(text: str, excite_words=_EXCITE_WORDS) -> int:
    """計算情緒高張詞出現次數（中文子字串 + 英文不分大小寫，詞庫可擴充）。"""
    lowered = text.lower()
    return sum(lowered.count(word) for word in excite_words)


def _zscores(values: list) -> list:
    """把數列轉成 z 分數；樣本不足或無變異時回傳全 0。"""
    cleaned = [v for v in values if v is not None]
    if len(cleaned) < 3:
        return [0.0] * len(values)
    mean = statistics.fmean(cleaned)
    stdev = statistics.pstdev(cleaned)
    if stdev < 1e-9:
        return [0.0] * len(values)
    return [((v - mean) / stdev) if v is not None else 0.0 for v in values]


def _score_highlights(items: list, loudness: list,
                      settings: Optional[dict] = None) -> None:
    """
    為講話段落計算「精彩分數」並就地標記 TAG_HIGHLIGHT。

    綜合四種訊號：音量能量（講得大聲、有笑聲的段落通常較精彩）、
    語速（興奮時語速快）、情緒詞（內建＋使用者自訂）、驚嘆/疑問句。
    分數達門檻即標記為精彩；門檻除以使用者的敏感度倍率——
    敏感度 >1 更容易標記、<1 更嚴格。無音量資料時退化為其餘三種訊號。
    """
    settings = settings or resolve_settings()
    excite_words = settings.get("excite_words", _EXCITE_WORDS)
    sensitivity = max(float(settings.get("highlight_sensitivity", 1.0)), 0.2)
    threshold = _HIGHLIGHT_THRESHOLD / sensitivity

    speech = [item for item in items if item["kind"] == "speech"]
    if not speech:
        return
    energies = [_mean_energy(item["start"], item["end"], loudness)
                for item in speech] if loudness else [None] * len(speech)
    rates = []
    for item in speech:
        duration = max(item["end"] - item["start"], 0.2)
        rates.append(len(_normalize_for_compare(item["text"])) / duration)

    energy_z = _zscores(energies)
    rate_z = _zscores(rates)
    for index, item in enumerate(speech):
        excites = _excitement_hits(item["text"], excite_words)
        exclaims = sum(item["text"].count(ch) for ch in _EXCLAIM_CHARS)
        score = (1.2 * energy_z[index]
                 + 0.8 * rate_z[index]
                 + 1.0 * min(excites, 3)
                 + 0.5 * min(exclaims, 2))
        item["score"] = round(score, 2)
        if score >= threshold and TAG_REPEATED not in item["tags"]:
            item["tags"].insert(0, TAG_HIGHLIGHT)


def build_speech_segments(words, segment_gap: float = DEFAULT_SEGMENT_GAP):
    """依字與字之間的停頓把逐字時間軸切成講話段落。"""
    segments = []
    bucket = []
    for index, word in enumerate(words):
        bucket.append(word)
        next_word = words[index + 1] if index + 1 < len(words) else None
        if next_word is None or next_word["start"] - word["end"] >= segment_gap:
            segments.append({
                "kind": "speech",
                "start": bucket[0]["start"],
                "end": bucket[-1]["end"],
                "text": _join_words(bucket),
            })
            bucket = []
    return segments


def analyze(
    words,
    media_duration: float = 0.0,
    segment_gap: Optional[float] = None,
    silence_gap: Optional[float] = None,
    take_similarity: Optional[float] = None,
    loudness: Optional[list] = None,
    settings: Optional[dict] = None,
) -> list:
    """
    分析逐字時間軸，回傳審片段落清單（依時間排序）。

    每個段落為 dict：
        kind: "speech" 或 "silence"
        start / end: 秒
        text: 段落文字（冷場則為說明文字）
        tags: 標記清單（冷場 / 重複拍攝 / 口頭禪多 / 精彩）
        fillers: 填充詞數量
        score: 精彩分數（講話段落才有）
        keep: 建議是否保留（冷場與重複拍攝預設捨棄）

    settings 為 resolve_settings() 的審片偵測參數（敏感度、詞表、門檻）；
    segment_gap／silence_gap／take_similarity 明確傳入時優先於 settings。
    loudness 為 compute_loudness() 的音量資料，供精彩片段偵測使用；
    省略時偵測退化為語速與文字訊號。
    """
    settings = settings or resolve_settings()
    segment_gap = settings["segment_gap"] if segment_gap is None else segment_gap
    silence_gap = settings["silence_gap"] if silence_gap is None else silence_gap
    if take_similarity is None:
        take_similarity = settings["take_similarity"]
    filler_chars = settings.get("filler_chars", _FILLER_CJK)
    filler_density = float(settings.get("filler_density", _FILLER_DENSITY))
    speech = build_speech_segments(words, segment_gap)

    # 重複拍攝：與後面鄰近段落內容高度相似者，保留最後一次、前面的建議捨棄。
    normalized = [_normalize_for_compare(seg["text"]) for seg in speech]
    repeated = set()
    for i in range(len(speech)):
        if len(normalized[i]) < _TAKE_MIN_CHARS:
            continue
        for j in range(i + 1, min(i + 1 + _TAKE_LOOKAHEAD, len(speech))):
            if len(normalized[j]) < _TAKE_MIN_CHARS:
                continue
            ratio = difflib.SequenceMatcher(
                None, normalized[i], normalized[j]).ratio()
            if ratio >= take_similarity:
                repeated.add(i)
                break

    items = []
    previous_end = 0.0
    for index, seg in enumerate(speech):
        # 前一段（或影片開頭）到本段之間的靜音是否構成冷場。
        gap = seg["start"] - previous_end
        if gap >= silence_gap:
            items.append(_silence_item(previous_end, seg["start"]))

        tags = []
        keep = True
        if index in repeated:
            tags.append(TAG_REPEATED)
            keep = False
        fillers = count_fillers(seg["text"], filler_chars)
        length = max(len(_normalize_for_compare(seg["text"])), 1)
        if fillers and fillers / length >= filler_density:
            tags.append(TAG_FILLER)
        items.append({
            "kind": "speech",
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"],
            "tags": tags,
            "fillers": fillers,
            "score": 0.0,
            "keep": keep,
        })
        previous_end = seg["end"]

    # 結尾冷場（需要知道媒體總長度才能偵測）。
    if media_duration and media_duration - previous_end >= silence_gap:
        items.append(_silence_item(previous_end, media_duration))

    # 精彩片段偵測（音量能量 + 語速 + 情緒詞 + 驚嘆句）。
    _score_highlights(items, loudness or [], settings)
    return items


def _silence_item(start: float, end: float) -> dict:
    return {
        "kind": "silence",
        "start": start,
        "end": end,
        "text": f"（冷場 {end - start:.1f} 秒，無人聲）",
        "tags": [TAG_SILENCE],
        "fillers": 0,
        "score": 0.0,
        "keep": False,
    }


def summarize(items, media_duration: float = 0.0) -> dict:
    """彙整審片統計：有效內容、冷場、重複拍攝、精彩片段與口頭禪總量。"""
    def total(predicate):
        return sum(i["end"] - i["start"] for i in items if predicate(i))

    speech_seconds = total(lambda i: i["kind"] == "speech")
    stats = {
        "media_duration": media_duration or (items[-1]["end"] if items else 0.0),
        "speech_seconds": speech_seconds,
        "kept_seconds": total(lambda i: i["keep"]),
        "silence_seconds": total(lambda i: i["kind"] == "silence"),
        "repeated_seconds": total(lambda i: TAG_REPEATED in i["tags"]),
        "highlight_count": sum(1 for i in items if TAG_HIGHLIGHT in i["tags"]),
        "highlight_seconds": total(lambda i: TAG_HIGHLIGHT in i["tags"]),
        "filler_total": sum(i["fillers"] for i in items),
        "segment_count": sum(1 for i in items if i["kind"] == "speech"),
    }
    return stats


def search_segments(items, keyword: str) -> list:
    """回傳文字包含關鍵字的段落索引清單（不分大小寫）。"""
    keyword = (keyword or "").strip().lower()
    if not keyword:
        return []
    return [i for i, item in enumerate(items)
            if keyword in item["text"].lower()]


# ---------------------------------------------------------------------------
# 匯出：粗剪影片 / EDL / CSV / YouTube 章節
# ---------------------------------------------------------------------------

def kept_ranges(items, padding: float = _CUT_PADDING) -> list:
    """
    取出保留段落的 (start, end) 區間：前後加緩衝、相鄰或重疊區間自動合併。
    """
    ranges = []
    for item in items:
        if not item["keep"]:
            continue
        start = max(item["start"] - padding, 0.0)
        end = item["end"] + padding
        if ranges and start <= ranges[-1][1] + 0.04:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))
    return ranges


def cut_rough_video(
    video_path: str,
    items: list,
    output_path: str,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    以 ffmpeg 把保留段落串接成粗剪影片（自動跳剪掉捨棄的段落）。

    參數：
        video_path: 來源影片。
        items: analyze() 的段落清單（依 keep 旗標取捨）。
        output_path: 輸出影片路徑（建議 .mp4）。
        progress_cb: (ratio, message) 進度回呼。
    """
    if not ffmpeg_available():
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    ranges = kept_ranges(items)
    if not ranges:
        raise ValueError("沒有任何保留的段落可輸出。")

    filters = []
    concat_inputs = []
    for index, (start, end) in enumerate(ranges):
        filters.append(
            f"[0:v]trim=start={start:.3f}:end={end:.3f},"
            f"setpts=PTS-STARTPTS[v{index}];"
            f"[0:a]atrim=start={start:.3f}:end={end:.3f},"
            f"asetpts=PTS-STARTPTS[a{index}]")
        concat_inputs.append(f"[v{index}][a{index}]")
    filter_complex = (
        ";".join(filters) + ";" + "".join(concat_inputs)
        + f"concat=n={len(ranges)}:v=1:a=1[outv][outa]")

    total = sum(end - start for start, end in ranges)
    if progress_cb:
        progress_cb(0.0, f"啟動 ffmpeg 粗剪（共 {len(ranges)} 段、"
                         f"約 {total:.0f} 秒）...")
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", video_path,
        "-filter_complex", filter_complex,
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac",
        "-progress", "pipe:1",
        output_path,
    ]
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="ignore",
        )
    except OSError as exc:
        raise RuntimeError(f"無法啟動 ffmpeg：{exc}") from exc

    _stream_progress(process, total, progress_cb)
    ret = process.wait()
    if ret != 0:
        stderr = (process.stderr.read() if process.stderr else "") or ""
        raise RuntimeError(f"ffmpeg 粗剪失敗：{stderr[-400:]}")
    if progress_cb:
        progress_cb(1.0, "粗剪輸出完成")
    return output_path


def _timecode(seconds: float, fps: int) -> str:
    """秒數轉 EDL 時間碼 HH:MM:SS:FF。"""
    total_frames = int(round(max(seconds, 0.0) * fps))
    frames = total_frames % fps
    total_seconds = total_frames // fps
    hours, rem = divmod(total_seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{frames:02d}"


def export_edl(items, path: str, clip_name: str = "SOURCE",
               fps: int = 30, title: str = "ROUGH CUT") -> str:
    """
    匯出 CMX3600 EDL：保留段落依序接成時間軸，可匯入 Premiere / Resolve。
    """
    ranges = kept_ranges(items, padding=0.0)
    if not ranges:
        raise ValueError("沒有任何保留的段落可輸出。")
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]
    record = 0.0
    for number, (start, end) in enumerate(ranges, start=1):
        duration = end - start
        lines.append(
            f"{number:03d}  AX       V     C        "
            f"{_timecode(start, fps)} {_timecode(end, fps)} "
            f"{_timecode(record, fps)} {_timecode(record + duration, fps)}")
        lines.append(f"* FROM CLIP NAME: {clip_name}")
        lines.append("")
        record += duration
    with open(path, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines))
    return path


def _hms(seconds: float) -> str:
    """秒數轉 HH:MM:SS.mmm（CSV 用）。"""
    total_ms = int(round(max(seconds, 0.0) * 1000))
    hours, total_ms = divmod(total_ms, 3_600_000)
    minutes, total_ms = divmod(total_ms, 60_000)
    secs, millis = divmod(total_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def export_csv(items, path: str) -> str:
    """匯出段落清單 CSV（UTF-8 BOM，Excel 可直接開啟）。"""
    import csv
    with open(path, "w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(
            ["保留", "類型", "開始", "結束", "長度(秒)", "標記", "填充詞數", "內容"])
        for item in items:
            writer.writerow([
                "是" if item["keep"] else "否",
                "講話" if item["kind"] == "speech" else "冷場",
                _hms(item["start"]),
                _hms(item["end"]),
                f"{item['end'] - item['start']:.1f}",
                "、".join(item["tags"]),
                item["fillers"],
                item["text"],
            ])
    return path


def build_chapters(items, min_chapter_seconds: float = 60.0,
                   break_gap: float = 2.0, max_title_chars: int = 20) -> list:
    """
    把保留的講話段落合併成合理粒度的 YouTube 章節。

    直接把每個段落當一章會太細碎（創作者常見抱怨）。合併規則：
    - 段落之間有明顯間隔（≥ break_gap 秒，即被剪掉的冷場處）
      且目前章節已達最短長度（min_chapter_seconds）時，才切新章節
    - 章節標題取該章第一個段落的開頭文字
    - 第一章強制從 0:00 開始（YouTube 規定）

    回傳 [{"start": 秒, "title": 文字}, ...]。
    """
    kept = [item for item in items
            if item["kind"] == "speech" and item["keep"]]
    if not kept:
        return []
    chapters = []
    current_start = kept[0]["start"]
    current_title = kept[0]["text"][:max_title_chars]
    last_end = kept[0]["end"]
    for seg in kept[1:]:
        gap = seg["start"] - last_end
        if (gap >= break_gap
                and seg["start"] - current_start >= min_chapter_seconds):
            chapters.append({"start": current_start, "title": current_title})
            current_start = seg["start"]
            current_title = seg["text"][:max_title_chars]
        last_end = seg["end"]
    chapters.append({"start": current_start, "title": current_title})
    chapters[0]["start"] = 0.0
    return chapters


def export_youtube_chapters(items, max_title_chars: int = 20,
                            min_chapter_seconds: float = 60.0,
                            break_gap: float = 2.0) -> str:
    """
    由保留的講話段落產生 YouTube 章節草稿文字（貼到影片說明欄用）。

    章節經 build_chapters 合併，避免過細；第一章固定 0:00。
    """
    lines = []
    for chapter in build_chapters(items, min_chapter_seconds, break_gap,
                                  max_title_chars):
        minutes, secs = divmod(int(chapter["start"]), 60)
        hours, minutes = divmod(minutes, 60)
        stamp = (f"{hours}:{minutes:02d}:{secs:02d}" if hours
                 else f"{minutes}:{secs:02d}")
        lines.append(f"{stamp} {chapter['title']}")
    return "\n".join(lines)


def build_review_cues(items) -> list:
    """
    把審片結果轉成「審片標記字幕」cue 清單（含【精彩】【冷場】等前綴）。

    匯出成 .srt 後與原始素材一起載入剪輯軟體或播放器，
    拉時間軸時即可直接看到每一段的標記與內容。
    """
    cues = []
    for item in items:
        prefix = "".join(f"【{tag}】" for tag in item["tags"])
        if not item["keep"]:
            prefix += "【建議剪掉】"
        cues.append({
            "start": item["start"],
            "end": item["end"],
            "text": f"{prefix}{item['text']}" if prefix else item["text"],
        })
    return cues


def export_html_report(items, path: str, source_name: str = "",
                       media_duration: float = 0.0) -> str:
    """
    匯出單一檔案的 HTML 審片報告：彩色時間軸 + 統計摘要 + 段落表。

    報告不依賴任何外部資源，可直接傳給剪輯師；時間軸色塊點擊即可
    跳到對應段落，一眼看出精彩（綠）、待審視（琥珀）、冷場（灰）分佈。
    """
    stats = summarize(items, media_duration)
    total = max(stats["media_duration"], 0.1)

    def pct(seconds):
        return f"{seconds / total * 100:.0f}%"

    def fmt_min(seconds):
        return f"{seconds / 60.0:.1f} 分"

    # 時間軸色塊（依比例定位；捨棄段半透明）。
    blocks = []
    for index, item in enumerate(items):
        left = item["start"] / total * 100
        width = max((item["end"] - item["start"]) / total * 100, 0.15)
        color = CATEGORY_COLORS[categorize(item)]
        opacity = "1" if item["keep"] else "0.35"
        tip = html.escape(
            f"{_hms(item['start'])} {'、'.join(item['tags']) or '一般'}："
            f"{item['text'][:60]}")
        blocks.append(
            f'<a class="blk" href="#seg{index}" title="{tip}" '
            f'style="left:{left:.2f}%;width:{width:.2f}%;'
            f'background:{color};opacity:{opacity}"></a>')

    legend = "".join(
        f'<span class="lg"><i style="background:{CATEGORY_COLORS[key]}"></i>'
        f'{CATEGORY_LABELS[key]}</span>'
        for key in ("highlight", "normal", "review", "silence"))

    rows = []
    for index, item in enumerate(items):
        color = CATEGORY_COLORS[categorize(item)]
        keep = "保留" if item["keep"] else "剪掉"
        keep_class = "keep" if item["keep"] else "drop"
        tags = "、".join(item["tags"]) or "—"
        rows.append(
            f'<tr id="seg{index}" class="{keep_class}">'
            f'<td><i class="dot" style="background:{color}"></i></td>'
            f'<td class="mono">{_hms(item["start"])}</td>'
            f'<td class="mono">{item["end"] - item["start"]:.1f}s</td>'
            f'<td>{html.escape(tags)}</td>'
            f'<td class="k">{keep}</td>'
            f'<td class="txt">{html.escape(item["text"])}</td></tr>')

    title = html.escape(source_name or "審片報告")
    document = f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>審片報告：{title}</title>
<style>
body{{font-family:"Microsoft JhengHei",system-ui,sans-serif;margin:24px;
     background:#fafafa;color:#222}}
h1{{font-size:20px}} .sub{{color:#777;font-size:13px;margin-bottom:16px}}
.stats{{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0}}
.stat{{background:#fff;border:1px solid #e3e3e3;border-radius:8px;
      padding:8px 14px;font-size:13px}}
.stat b{{display:block;font-size:17px}}
.timeline{{position:relative;height:46px;background:#eee;border-radius:6px;
          overflow:hidden;margin:8px 0 4px}}
.blk{{position:absolute;top:0;bottom:0;display:block}}
.blk:hover{{outline:2px solid #222;z-index:2}}
.lg{{font-size:12px;color:#555;margin-right:14px}}
.lg i,.dot{{display:inline-block;width:10px;height:10px;border-radius:2px;
           margin-right:4px;vertical-align:middle}}
table{{border-collapse:collapse;width:100%;margin-top:16px;background:#fff;
      font-size:13px}}
th,td{{border-bottom:1px solid #ececec;padding:6px 8px;text-align:left;
      vertical-align:top}}
th{{background:#f3f3f3;position:sticky;top:0}}
.mono{{font-family:Consolas,monospace;white-space:nowrap}}
.txt{{word-break:break-all}}
tr.drop td{{color:#aaa}} tr.drop .txt{{text-decoration:line-through}}
tr:target{{background:#fff6d9}}
.k{{white-space:nowrap}}
</style></head><body>
<h1>審片報告：{title}</h1>
<div class="sub">總長 {fmt_min(total)}｜點時間軸色塊可跳到對應段落</div>
<div class="stats">
<div class="stat"><b>{fmt_min(stats['kept_seconds'])}</b>保留內容（{pct(stats['kept_seconds'])}）</div>
<div class="stat"><b>{stats['highlight_count']} 段</b>精彩片段（{fmt_min(stats['highlight_seconds'])}）</div>
<div class="stat"><b>{fmt_min(stats['silence_seconds'])}</b>冷場（{pct(stats['silence_seconds'])}）</div>
<div class="stat"><b>{fmt_min(stats['repeated_seconds'])}</b>重複拍攝</div>
<div class="stat"><b>{stats['filler_total']}</b>口頭禪次數</div>
<div class="stat"><b>{stats['segment_count']}</b>講話段落</div>
</div>
<div class="timeline">{''.join(blocks)}</div>
<div>{legend}</div>
<table><thead><tr><th></th><th>開始</th><th>長度</th><th>標記</th>
<th>取捨</th><th>內容</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</body></html>"""
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(document)
    return path
