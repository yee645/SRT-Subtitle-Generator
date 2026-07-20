# -*- coding: utf-8 -*-
"""
字幕匯入模組：讀入既有 SRT／VTT 字幕檔，接上既有的編修／翻譯／燒錄管線。

調研痛點：本工具目前只能「匯出」字幕，創作者手上已經有的字幕檔——下載的
YouTube 自動字幕、其他工具產出的檔案、舊專案留下的字幕——完全進不了本工具，
想修正錯字、換樣式、燒錄硬字幕或加上雙語翻譯，只能開記事本手動改，或另外
找網路工具處理一次。TikTok／Reels 等平台又不支援外掛字幕檔，燒錄硬字幕是
唯一選項，「匯入既有字幕 → 燒錄」因此是實務上會重複發生的需求。

本模組把 SRT／VTT 檔案容錯解析成與 exporter.py／segmenter.py 相同形狀的
cue 清單（{"start", "end", "text"}，無 "words" 鍵——下游逐字動態字幕遇到
沒有 words 的 cue 本就會自動退回整句顯示，無需額外相容處理）。

Windows 世界的現實是下載或舊工具產出的字幕檔往往不是 UTF-8：依序嘗試
utf-8-sig／utf-8／cp950（繁體 Big5 系列）／gb18030（簡體），全部失敗才
以 utf-8 + errors="replace" 兜底，避免直接看到亂碼或程式崩潰。

解析採「儘量救回可用內容」原則：單一區塊格式有誤不中斷整個檔案，
計入 skipped 略過數量即可；只有整份檔案救不回任何一句時才報錯，
讓 errors.py 統一翻譯成友善訊息。

零 GUI 依賴，供 GUI 匯入按鈕與 CLI --subs 旗標共用。
"""

from __future__ import annotations

import os
import re
from typing import Tuple

# 依序嘗試的編碼：BOM UTF-8 → 一般 UTF-8（嚴格）→ 繁體 Big5 系列 → 簡體。
_ENCODINGS = ("utf-8-sig", "utf-8", "cp950", "gb18030")

# SRT 時間軸：HH:MM:SS,mmm --> HH:MM:SS,mmm（毫秒可用逗號或點，容忍缺前導零與多餘空白）。
_SRT_TIME_RE = re.compile(
    r"(\d{1,2}):(\d{1,2}):(\d{1,2})[.,](\d{1,3})\s*-->\s*"
    r"(\d{1,2}):(\d{1,2}):(\d{1,2})[.,](\d{1,3})")

# VTT 時間軸：時數可省略（MM:SS.mmm），毫秒固定用點。
_VTT_TIME_RE = re.compile(
    r"(?:(\d{1,2}):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})\s*-->\s*"
    r"(?:(\d{1,2}):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})")

# 常見行內標記：<i> <b> <u> <font ...>（含收尾與帶屬性）。
_HTML_TAG_RE = re.compile(r"</?(?:i|b|u|font)(?:\s[^>]*)?>", re.IGNORECASE)
# ASS 覆寫碼（如 {\an8}）。
_ASS_OVERRIDE_RE = re.compile(r"\{\\[^}]*\}")
# YouTube VTT 逐字時間標記：<00:00:01.500>。
_VTT_INLINE_TIME_RE = re.compile(r"<\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}>")
# YouTube VTT 語音／顏色標籤：<c> </c> <c.colorXXXXXX> <v Speaker> </v>。
_VTT_VOICE_TAG_RE = re.compile(r"</?[cv](?:\.[^>]*|\s[^>]*)?>", re.IGNORECASE)


def _strip_markup(text: str) -> str:
    """去除常見行內標記，保留內文（SRT／VTT 共用）。"""
    text = _VTT_INLINE_TIME_RE.sub("", text)
    text = _VTT_VOICE_TAG_RE.sub("", text)
    text = _HTML_TAG_RE.sub("", text)
    text = _ASS_OVERRIDE_RE.sub("", text)
    return text


def _decode(raw: bytes) -> Tuple[str, str]:
    """依序嘗試編碼，回傳 (解出的文字, 成功的編碼名稱)。"""
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8（含無法辨識字元）"


def _to_seconds(h: str, m: str, s: str, ms: str) -> float:
    millis = ms.ljust(3, "0")[:3] if ms else "000"
    return (int(h or 0) * 3600 + int(m) * 60 + int(s)
            + int(millis) / 1000.0)


def _normalize_lines(text: str) -> list:
    """CRLF／CR 一律轉為 LF 後切行。"""
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def parse_srt(text: str) -> Tuple[list, int]:
    """
    容錯解析 SRT 純文字，回傳 (cues, skipped)。

    區塊以空行分隔；索引行可省略；文字保留多行（以 \\n 相接）；
    任何一個區塊格式有誤（找不到有效時間軸、文字為空、結束<=開始）
    只略過該區塊並計入 skipped，不中斷整份檔案的解析。
    """
    lines = _normalize_lines(text)
    cues = []
    skipped = 0
    block: list = []

    def flush(block_lines):
        nonlocal skipped
        if not block_lines:
            return
        # 找出區塊中第一行有效時間軸；其前一行（若存在且非索引數字）當作時間軸行，
        # 其後的所有行都是文字。索引行（純數字）本身略過、不算進文字。
        time_line_idx = None
        match = None
        for idx, line in enumerate(block_lines):
            m = _SRT_TIME_RE.search(line)
            if m:
                time_line_idx = idx
                match = m
                break
        if match is None:
            skipped += 1
            return
        text_lines = block_lines[time_line_idx + 1:]
        raw_text = "\n".join(text_lines).strip("\n")
        raw_text = _strip_markup(raw_text).strip()
        if not raw_text:
            skipped += 1
            return
        start = _to_seconds(*match.group(1, 2, 3, 4))
        end = _to_seconds(*match.group(5, 6, 7, 8))
        if end <= start:
            skipped += 1
            return
        cues.append({"start": start, "end": end, "text": raw_text})

    for line in lines:
        if line.strip() == "":
            flush(block)
            block = []
        else:
            block.append(line)
    flush(block)  # 檔案結尾若無空行收尾，補處理最後一個區塊。

    cues.sort(key=lambda cue: cue["start"])
    return cues, skipped


# VTT 區塊中應忽略的非字幕內容起始關鍵字。
_VTT_SKIP_PREFIXES = ("NOTE", "STYLE", "REGION")


def parse_vtt(text: str) -> Tuple[list, int]:
    """
    容錯解析 WebVTT 純文字，回傳 (cues, skipped)。

    WEBVTT 標頭若缺漏不視為致命錯誤（當作類 SRT 內容嘗試解析）；
    NOTE／STYLE／REGION 區塊整段略過；cue identifier 可有可無；
    時間軸小時數可省略（MM:SS.mmm）；時間軸行尾端的 cue settings
    （position/align/line 等）會被切掉；YouTube 下載常見的逐字時間
    標記 <00:00:01.500> 與語音／顏色標籤 <c> <v Speaker> 一律清除。
    """
    lines = _normalize_lines(text)
    # 跳過開頭的 WEBVTT 標頭行（含後方可能的說明文字）。
    start_idx = 0
    if lines and lines[0].strip().upper().startswith("WEBVTT"):
        start_idx = 1

    cues = []
    skipped = 0
    block: list = []
    in_skip_block = False

    def is_skip_start(line: str) -> bool:
        stripped = line.strip()
        return any(stripped == kw or stripped.startswith(kw + " ")
                  for kw in _VTT_SKIP_PREFIXES)

    def flush(block_lines):
        nonlocal skipped
        if not block_lines:
            return
        time_line_idx = None
        match = None
        for idx, line in enumerate(block_lines):
            m = _VTT_TIME_RE.search(line)
            if m:
                time_line_idx = idx
                match = m
                break
        if match is None:
            skipped += 1
            return
        text_lines = block_lines[time_line_idx + 1:]
        raw_text = "\n".join(text_lines).strip("\n")
        raw_text = _strip_markup(raw_text).strip()
        if not raw_text:
            skipped += 1
            return
        start = _to_seconds(match.group(1) or "0", match.group(2),
                            match.group(3), match.group(4))
        end = _to_seconds(match.group(5) or "0", match.group(6),
                          match.group(7), match.group(8))
        if end <= start:
            skipped += 1
            return
        cues.append({"start": start, "end": end, "text": raw_text})

    for raw_line in lines[start_idx:]:
        line = raw_line
        if line.strip() == "":
            if not in_skip_block:
                flush(block)
            block = []
            in_skip_block = False
            continue
        if not block and is_skip_start(line):
            in_skip_block = True
            continue
        if in_skip_block:
            continue
        block.append(line)
    if not in_skip_block:
        flush(block)

    cues.sort(key=lambda cue: cue["start"])
    return cues, skipped


def load_subtitle_file(path: str) -> dict:
    """
    讀入字幕檔並依副檔名解析，回傳
    {"cues": cue 清單, "skipped": 略過的區塊數, "encoding": 偵測到的編碼}。

    找不到檔案時拋出 FileNotFoundError（訊息格式沿用全站慣例，
    errors.py 既有規則會自動接手翻譯）；副檔名非 .srt/.vtt 時拋出
    ValueError；整份檔案解析不出任何一句字幕時拋出 RuntimeError，
    由 errors.py 的新規則翻譯成友善訊息。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到檔案：{path}")
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".srt", ".vtt"):
        raise ValueError(f"不支援的字幕檔格式：{ext}（目前支援 .srt 與 .vtt）")

    with open(path, "rb") as fp:
        raw = fp.read()
    text, encoding = _decode(raw)

    if ext == ".srt":
        cues, skipped = parse_srt(text)
    else:
        cues, skipped = parse_vtt(text)

    if not cues:
        raise RuntimeError("無法解析字幕檔：檔案中找不到有效的字幕內容")

    return {"cues": cues, "skipped": skipped, "encoding": encoding}
