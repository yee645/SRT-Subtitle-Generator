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
import re
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


def count_fillers(text: str) -> int:
    """計算文字中的填充詞數量（中文單字 + 英文整字）。"""
    count = sum(text.count(ch) for ch in _FILLER_CJK)
    count += len(_FILLER_LATIN.findall(text))
    return count


def _normalize_for_compare(text: str) -> str:
    """重複拍攝比對前的正規化：去標點、空白、統一小寫。"""
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE).lower()


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
    segment_gap: float = DEFAULT_SEGMENT_GAP,
    silence_gap: float = DEFAULT_SILENCE_GAP,
    take_similarity: float = DEFAULT_TAKE_SIMILARITY,
) -> list:
    """
    分析逐字時間軸，回傳審片段落清單（依時間排序）。

    每個段落為 dict：
        kind: "speech" 或 "silence"
        start / end: 秒
        text: 段落文字（冷場則為說明文字）
        tags: 標記清單（冷場 / 重複拍攝 / 口頭禪多）
        fillers: 填充詞數量
        keep: 建議是否保留（冷場與重複拍攝預設捨棄）
    """
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
        fillers = count_fillers(seg["text"])
        length = max(len(_normalize_for_compare(seg["text"])), 1)
        if fillers and fillers / length >= _FILLER_DENSITY:
            tags.append(TAG_FILLER)
        items.append({
            "kind": "speech",
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"],
            "tags": tags,
            "fillers": fillers,
            "keep": keep,
        })
        previous_end = seg["end"]

    # 結尾冷場（需要知道媒體總長度才能偵測）。
    if media_duration and media_duration - previous_end >= silence_gap:
        items.append(_silence_item(previous_end, media_duration))
    return items


def _silence_item(start: float, end: float) -> dict:
    return {
        "kind": "silence",
        "start": start,
        "end": end,
        "text": f"（冷場 {end - start:.1f} 秒，無人聲）",
        "tags": [TAG_SILENCE],
        "fillers": 0,
        "keep": False,
    }


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


def export_youtube_chapters(items, max_title_chars: int = 20) -> str:
    """
    由保留的講話段落產生 YouTube 章節草稿文字（貼到影片說明欄用）。

    YouTube 規定第一個章節必須是 0:00；標題取段落開頭文字。
    """
    lines = []
    for item in items:
        if item["kind"] != "speech" or not item["keep"]:
            continue
        title = item["text"][:max_title_chars]
        minutes, secs = divmod(int(item["start"]), 60)
        hours, minutes = divmod(minutes, 60)
        stamp = (f"{hours}:{minutes:02d}:{secs:02d}" if hours
                 else f"{minutes}:{secs:02d}")
        lines.append(f"{stamp} {title}")
    if lines and not lines[0].startswith(("0:00 ", "0:00\t")):
        first_title = lines[0].split(" ", 1)[1] if " " in lines[0] else "開場"
        lines[0] = f"0:00 {first_title}"
    return "\n".join(lines)
