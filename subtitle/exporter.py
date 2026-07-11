# -*- coding: utf-8 -*-
"""
字幕匯出模組：統一處理多種字幕格式輸出。

支援格式：
    - SRT  ：標準 SubRip 字幕（HH:MM:SS,mmm）
    - VTT  ：WebVTT 字幕（HH:MM:SS.mmm，含 WEBVTT 標頭）
    - ASS  ：Advanced SubStation Alpha（含樣式資訊，與字幕視覺設定整合）
    - TXT  ：純文字稿（去除時間軸，僅留文字內容）

ASS 輸出會把目前的字幕樣式（字型、字級、顏色、邊框、位置）一併寫入
Script Info 與 Styles 區段，匯入 Aegisub、PotPlayer 等播放器可直接套用。
"""

from __future__ import annotations

import os
import re
from typing import Iterable, Mapping


# ---------------------------------------------------------------------------
# 通用時間格式輔助函式
# ---------------------------------------------------------------------------

def _clamp(value: float, low: float = 0.0) -> float:
    """夾住數值下限，避免負數時間造成格式錯誤。"""
    return value if value > low else low


def format_srt_timestamp(seconds: float) -> str:
    """SRT 時間格式：HH:MM:SS,mmm（毫秒以逗號分隔）。"""
    total_ms = int(round(_clamp(seconds) * 1000))
    hours, total_ms = divmod(total_ms, 3_600_000)
    minutes, total_ms = divmod(total_ms, 60_000)
    secs, millis = divmod(total_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_vtt_timestamp(seconds: float) -> str:
    """WebVTT 時間格式：HH:MM:SS.mmm（毫秒以點分隔）。"""
    total_ms = int(round(_clamp(seconds) * 1000))
    hours, total_ms = divmod(total_ms, 3_600_000)
    minutes, total_ms = divmod(total_ms, 60_000)
    secs, millis = divmod(total_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def format_ass_timestamp(seconds: float) -> str:
    """ASS 時間格式：H:MM:SS.cs（百分秒）。"""
    total_cs = int(round(_clamp(seconds) * 100))
    hours, total_cs = divmod(total_cs, 360_000)
    minutes, total_cs = divmod(total_cs, 6_000)
    secs, centi = divmod(total_cs, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centi:02d}"


# ---------------------------------------------------------------------------
# 各格式的內容組裝
# ---------------------------------------------------------------------------

def cues_to_srt(cues: Iterable[Mapping]) -> str:
    """把 cue 清單組成 SRT 純文字。"""
    blocks = []
    for number, cue in enumerate(cues, start=1):
        blocks.append(
            f"{number}\n"
            f"{format_srt_timestamp(cue['start'])} --> "
            f"{format_srt_timestamp(cue['end'])}\n"
            f"{cue['text']}\n"
        )
    return "\n".join(blocks)


def cues_to_vtt(cues: Iterable[Mapping]) -> str:
    """把 cue 清單組成 WebVTT 純文字。"""
    blocks = ["WEBVTT", ""]
    for number, cue in enumerate(cues, start=1):
        blocks.append(str(number))
        blocks.append(
            f"{format_vtt_timestamp(cue['start'])} --> "
            f"{format_vtt_timestamp(cue['end'])}"
        )
        blocks.append(cue["text"])
        blocks.append("")
    return "\n".join(blocks)


def cues_to_txt(cues: Iterable[Mapping]) -> str:
    """把 cue 清單組成純文字稿（一句一行，去除時間軸）。"""
    return "\n".join(cue["text"].strip() for cue in cues if cue.get("text"))


def _hex_to_ass_color(color: str) -> str:
    """把 #RRGGBB 轉成 ASS 的 &HAABBGGRR& 格式（Alpha 預設 00 不透明）。"""
    text = (color or "#FFFFFF").lstrip("#")
    if len(text) != 6:
        text = "FFFFFF"
    red, green, blue = text[0:2], text[2:4], text[4:6]
    return f"&H00{blue}{green}{red}".upper() + "&"


def _hex_to_ass_inline(color: str) -> str:
    """把 #RRGGBB 轉成 ASS 行內色彩覆寫標籤用的 &HBBGGRR& 格式。"""
    text = (color or "#FFD700").lstrip("#")
    if len(text) != 6:
        text = "FFD700"
    red, green, blue = text[0:2], text[2:4], text[4:6]
    return f"&H{blue}{green}{red}&".upper()


def parse_emphasis_words(raw: str) -> list:
    """解析重點字詞清單（逗號、頓號或空白分隔），長詞優先以避免部分遮蔽。"""
    words = [w.strip() for w in re.split(r"[,，、\s]+", raw or "") if w.strip()]
    return sorted(set(words), key=len, reverse=True)


def split_emphasis_segments(text: str, words: list) -> list:
    """
    把文字依重點字詞切成 [(片段文字, 是否重點), ...] 清單。

    ASS 標籤包裹與 GUI 預覽分色渲染共用此切段結果，
    確保輸出與預覽看到的重點範圍一致。拉丁字詞不分大小寫。
    """
    if not text:
        return []
    if not words:
        return [(text, False)]
    # 單次合併比對（長詞在前），避免短詞遮蔽長詞。
    pattern = re.compile("|".join(re.escape(w) for w in words), re.IGNORECASE)
    segments = []
    cursor = 0
    for match in pattern.finditer(text):
        if match.start() > cursor:
            segments.append((text[cursor:match.start()], False))
        segments.append((match.group(0), True))
        cursor = match.end()
    if cursor < len(text):
        segments.append((text[cursor:], False))
    return segments


def apply_emphasis(text: str, words: list, color: str) -> str:
    """
    把文字中的重點字詞包上 ASS 行內色彩標籤（CapCut 風格的重點字上色）。

    以 {\\1c&H..&} 切換顏色、{\\r} 還原為樣式預設；拉丁字詞不分大小寫。
    """
    if not words or not text:
        return text
    tag = f"{{\\1c{_hex_to_ass_inline(color)}}}"
    return "".join(
        f"{tag}{segment}{{\\r}}" if emphasized else segment
        for segment, emphasized in split_emphasis_segments(text, words))


def _ass_alignment(position_y: float) -> int:
    """依垂直位置選擇 ASS 對齊代號（2=底部、5=中部、8=頂部，皆置中）。"""
    if position_y <= 0.33:
        return 8
    if position_y >= 0.66:
        return 2
    return 5


def cues_to_ass(cues: Iterable[Mapping], style: Mapping | None = None,
                resolution: tuple[int, int] = (1920, 1080)) -> str:
    """把 cue 清單組成 ASS 文字（內含 Style 與 Events）。"""
    style = style or {}
    font_family = style.get("font_family", "Microsoft JhengHei")
    font_size = max(int(style.get("font_size", 26)), 1)
    primary = _hex_to_ass_color(style.get("text_color", "#FFFFFF"))
    outline = _hex_to_ass_color(style.get("stroke_color", "#000000"))
    stroke_width = max(int(style.get("stroke_width", 2)), 0)
    align = _ass_alignment(float(style.get("position_y", 0.88)))
    play_x, play_y = resolution
    margin_v = max(int(play_y * (1.0 - float(style.get("position_y", 0.88)))), 10)

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "Collisions: Normal\n"
        "PlayResX: {px}\n"
        "PlayResY: {py}\n"
        "Timer: 100.0000\n"
        "WrapStyle: 2\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,{font},{size},{primary},&H000000FF,{outline},"
        "&H00000000,0,0,0,0,100,100,0,0,1,{stroke},0,{align},20,20,{mv},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
    ).format(
        px=play_x, py=play_y, font=font_family, size=font_size,
        primary=primary, outline=outline, stroke=stroke_width,
        align=align, mv=margin_v,
    )

    # 重點字上色：樣式啟用且有詞清單時，於 ASS 文字內嵌色彩標籤。
    emphasis_words = []
    if style.get("emphasis_enabled"):
        emphasis_words = parse_emphasis_words(
            str(style.get("emphasis_words") or ""))
    emphasis_color = style.get("emphasis_color", "#FFD700")

    lines = [header]
    for cue in cues:
        text = (cue.get("text") or "").replace("\n", "\\N").replace("\r", "")
        if emphasis_words:
            text = apply_emphasis(text, emphasis_words, emphasis_color)
        lines.append(
            "Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n".format(
                start=format_ass_timestamp(cue["start"]),
                end=format_ass_timestamp(cue["end"]),
                text=text,
            )
        )
    return "".join(lines)


# ---------------------------------------------------------------------------
# 統一寫檔介面
# ---------------------------------------------------------------------------

# 副檔名與輸出函式的對應表。
_BUILDERS = {
    ".srt": cues_to_srt,
    ".vtt": cues_to_vtt,
    ".txt": cues_to_txt,
}


def export(cues: list, path: str, style: Mapping | None = None) -> str:
    """
    依目的路徑的副檔名自動選擇輸出格式並寫檔。

    參數：
        cues: cue 清單。
        path: 目的檔案路徑，副檔名決定格式。
        style: 字幕視覺樣式（ASS 格式會使用；其他格式忽略）。
    回傳：實際寫入的檔案路徑。
    """
    if not cues:
        raise ValueError("沒有可輸出的字幕內容")
    ext = os.path.splitext(path)[1].lower()
    if ext == ".ass":
        content = cues_to_ass(cues, style)
    elif ext in _BUILDERS:
        content = _BUILDERS[ext](cues)
    else:
        raise ValueError(f"不支援的輸出格式：{ext}")
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(content)
    return path


# 對外公開的格式描述（filedialog 用）。
FORMAT_FILETYPES = [
    ("SRT 字幕檔", "*.srt"),
    ("WebVTT 字幕檔", "*.vtt"),
    ("ASS 進階字幕檔", "*.ass"),
    ("純文字稿", "*.txt"),
    ("所有檔案", "*.*"),
]
