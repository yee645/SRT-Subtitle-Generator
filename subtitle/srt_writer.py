# -*- coding: utf-8 -*-
"""SRT 字幕檔輸出模組。"""


def format_timestamp(seconds):
    """將秒數轉為 SRT 時間格式 HH:MM:SS,mmm。"""
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours, total_ms = divmod(total_ms, 3600_000)
    minutes, total_ms = divmod(total_ms, 60_000)
    secs, millis = divmod(total_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def cues_to_srt(cues):
    """將 cue 清單組成 SRT 純文字內容。"""
    blocks = []
    for number, cue in enumerate(cues, start=1):
        blocks.append(
            f"{number}\n"
            f"{format_timestamp(cue['start'])} --> {format_timestamp(cue['end'])}\n"
            f"{cue['text']}\n"
        )
    return "\n".join(blocks)


def write_srt(cues, path):
    """將 cue 清單寫入指定路徑的 SRT 檔（UTF-8 編碼）。"""
    if not cues:
        raise ValueError("沒有可輸出的字幕內容")
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(cues_to_srt(cues))
