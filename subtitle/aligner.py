# -*- coding: utf-8 -*-
"""
文字稿對齊模組（模式二：文字稿對齊）。

使用者提供現成文字稿時，本模組以「文字比對對齊（forced alignment）」處理：

1. 用語音辨識（Whisper / OpenAI API）辨識音訊，取得「Whisper 聽到的字」
   以及每個字的精確時間戳。語音辨識只辨識人聲，會自動忽略背景音樂。
   辨識時並把使用者文字稿尾段當作提示，讓辨識用詞與字體更貼近文字稿。
2. 把使用者文字稿與 Whisper 辨識內容做字元序列比對，找出相符片段作為「錨點」。
3. 每個錨點都帶有 Whisper 的真實時間戳；其餘未對上的字元在錨點之間線性內插。
4. 依此把每一行字幕的起訖時間，對齊到 Whisper 偵測到的真實語音位置。

如此字幕時間會直接貼著真實語音，而非機械式地按字數平均攤開。

注意：本模式需要可用的語音辨識引擎，設定方式與模式一的「轉寫設定」相同。
"""

import difflib

from .segmenter import split_into_lines, _post_process
from .transcriber import transcribe

# 取作 Whisper 提示文字的文字稿尾段長度（Whisper 提示僅採用最後約 200 餘字）。
_PROMPT_CHARS = 200


def align_transcript(audio_path, transcript, config, status_cb=None):
    """
    將文字稿對齊到音訊時間軸，回傳 cue 清單。

    參數：
        audio_path: 影片或音訊檔路徑。
        transcript: 使用者貼上的純文字稿。
        config: 完整設定 dict。
        status_cb: 可選的狀態回呼函式。
    """
    transcript = (transcript or "").strip()
    if not transcript:
        raise ValueError("文字稿內容為空，請先貼上逐字稿。")

    seg_cfg = config.get("segmentation", {})

    # 用文字稿尾段當作辨識提示，提升辨識與後續比對的一致性。
    # 若使用者另外填了「轉寫提示」（專有名詞、人名等），優先放在前面以強化導正。
    if callable(status_cb):
        status_cb("正在以語音辨識分析音訊...")
    user_prompt = (config.get("transcription", {}).get("prompt") or "").strip()
    tail = transcript[-_PROMPT_CHARS:]
    prompt = f"{user_prompt} {tail}".strip() if user_prompt else tail
    words = transcribe(audio_path, config, status_cb, initial_prompt=prompt)
    if not words:
        raise RuntimeError("未能從音訊辨識到任何人聲。")

    # 建立 Whisper 的字元時間軸。
    whisper_chars, whisper_times = _build_whisper_char_timeline(words)
    if len(whisper_chars) < 2 or whisper_times[-1] <= whisper_times[0]:
        raise RuntimeError(
            "語音辨識未提供有效的時間資訊，請改用模式一，或確認音訊含清晰人聲。")

    if callable(status_cb):
        status_cb("正在比對文字稿與語音、對齊時間軸...")
    lines = split_into_lines(transcript, seg_cfg)
    if not lines:
        raise ValueError("文字稿無法切出有效字幕內容。")

    # 建立使用者文字稿的字元串流（記錄每個字元屬於哪一行）。
    user_chars, user_line = _build_user_char_stream(lines)
    if not user_chars:
        raise ValueError("文字稿無有效文字內容。")

    # 序列比對求錨點。
    anchors = _build_anchors(user_chars, whisper_chars, whisper_times)

    if anchors:
        # 補上頭尾錨點：讓開頭/結尾未對上的字元也能內插，
        # 而非被夾平成零長度（例如 Whisper 把句尾的字聽錯時）。
        if anchors[0][0] > 0:
            anchors.insert(0, (0, whisper_times[0]))
        end_index = len(user_chars)
        if anchors[-1][0] < end_index:
            anchors.append((end_index, whisper_times[-1]))

    if len(anchors) >= 2:
        cues = _aligned_cues(lines, user_line, anchors)
    else:
        # 幾乎比對不到相符內容時，退回依字數比例分配於語音時間範圍。
        cues = _proportional_cues(lines, whisper_times[0], whisper_times[-1])

    return _post_process(cues, seg_cfg)


def _normalize(text):
    """正規化文字以利比對：轉小寫並只保留字母、數字與中日韓文字（去標點與空白）。"""
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def _build_whisper_char_timeline(words):
    """
    把 Whisper 逐字時間軸展開成「字元層級」的時間軸。

    每個辨識字的每個字元，依其在該字內的位置在 [start, end] 之間內插時間。
    回傳：(chars, times) 兩個等長 list。
    """
    chars = []
    times = []
    for word in words:
        text = _normalize(word.get("word", ""))
        if not text:
            continue
        start = float(word.get("start", 0.0))
        end = float(word.get("end", start))
        if end < start:
            end = start
        length = len(text)
        for index, char in enumerate(text):
            chars.append(char)
            times.append(start + (end - start) * ((index + 0.5) / length))
    return chars, times


def _build_user_char_stream(lines):
    """把使用者文字稿展開成字元串流，並記錄每個字元所屬的行索引。"""
    chars = []
    line_of = []
    for line_index, line in enumerate(lines):
        for char in _normalize(line):
            chars.append(char)
            line_of.append(line_index)
    return chars, line_of


def _build_anchors(user_chars, whisper_chars, whisper_times):
    """
    對使用者文字稿與 Whisper 辨識內容做字元序列比對，求出對齊錨點。

    回傳：[(user_index, time), ...]，依 user_index 遞增，
    每個錨點代表「文字稿第 user_index 個字」對應到的真實秒數。
    """
    matcher = difflib.SequenceMatcher(
        None, "".join(user_chars), "".join(whisper_chars), autojunk=False)
    anchors = []
    for user_i, whisper_j, size in matcher.get_matching_blocks():
        if size <= 0:
            continue
        # 以相符區塊的首、尾字元各設一個錨點。
        anchors.append((user_i, whisper_times[whisper_j]))
        anchors.append(
            (user_i + size - 1, whisper_times[whisper_j + size - 1]))
    return anchors


def _interpolate_time(user_index, anchors):
    """依錨點求出文字稿某字元位置對應的時間（錨點外則夾住端點）。"""
    if user_index <= anchors[0][0]:
        return anchors[0][1]
    if user_index >= anchors[-1][0]:
        return anchors[-1][1]
    low = anchors[0]
    for anchor in anchors:
        if anchor[0] >= user_index:
            high = anchor
            break
        low = anchor
    if high[0] == low[0]:
        return low[1]
    fraction = (user_index - low[0]) / (high[0] - low[0])
    return low[1] + (high[1] - low[1]) * fraction


def _aligned_cues(lines, user_line, anchors):
    """依錨點把每一行字幕對齊到真實時間。"""
    line_count = len(lines)
    # 找出每一行在字元串流中的首、尾索引。
    line_first = [None] * line_count
    line_last = [None] * line_count
    for index, line_index in enumerate(user_line):
        if line_first[line_index] is None:
            line_first[line_index] = index
        line_last[line_index] = index

    cues = []
    previous_end = 0.0
    for line_index in range(line_count):
        if line_first[line_index] is None:
            # 該行正規化後為空（例如純標點），給予零長度，交由後處理修正。
            start = end = previous_end
        else:
            start = _interpolate_time(line_first[line_index], anchors)
            # 行尾取「最後字元的下一個位置」，使相鄰行時間首尾相接。
            end = _interpolate_time(line_last[line_index] + 1, anchors)
            if end < start:
                end = start
        cues.append({"start": start, "end": end, "text": lines[line_index]})
        previous_end = end
    return cues


def _proportional_cues(lines, span_start, span_end):
    """退回方案：在語音時間範圍內依字數比例分配字幕。"""
    weights = [max(len(_normalize(line)), 1) for line in lines]
    weight_total = sum(weights)
    duration = max(span_end - span_start, 0.1)
    cues = []
    cursor = span_start
    for line, weight in zip(lines, weights):
        span = duration * weight / weight_total
        cues.append({"start": cursor, "end": cursor + span, "text": line})
        cursor += span
    return cues
