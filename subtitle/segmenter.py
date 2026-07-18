# -*- coding: utf-8 -*-
"""
智慧字幕斷句與分段演算法（本專案核心重點）。

設計目標：
1. 防止單一字幕過長：限制單行最大字數（中文與英文採不同上限）。
2. 合理斷句：優先以「強標點（句末）」切句，其次以「弱標點（句中停頓）」切子句，
   最後才在無標點可切時做硬切，避免突然一大段文字霸佔畫面。
3. 同時支援兩種模式：
   - 模式一以 Whisper 逐字時間軸組成字幕（build_cues_from_words）。
   - 模式二以純文字稿切行（split_into_lines），再由 aligner 配上時間。

字幕資料結構（cue）統一為 dict：
    {"index": int, "start": float, "end": float, "text": str}
"""

# 句末標點：遇到即視為一句結束。
STRONG_PUNCT = "。！？!?…．"
# 句中停頓標點：用來把長句切成較短的子句（含半形空白，方便英文以單字為單位打包）。
WEAK_PUNCT = "，、,；;：:—–- "
# 成對引號 / 括弧：演算法在引號內不切句，避免把對話一刀切成兩半。
QUOTE_PAIRS = {
    "「": "」", "『": "』", "“": "”", "‘": "’",
    "(": ")", "（": "）", "[": "]", "【": "】", "《": "》",
    "\"": "\"", "'": "'",
}
_OPEN_QUOTES = set(QUOTE_PAIRS.keys())
_CLOSE_TO_OPEN = {close: open_ for open_, close in QUOTE_PAIRS.items()}

# 常見 CJK（中日韓）與全形字元的 Unicode 區段，用來判斷文字屬性。
CJK_RANGES = (
    (0x3040, 0x30FF),   # 日文平假名、片假名
    (0x3400, 0x4DBF),   # CJK 擴充 A
    (0x4E00, 0x9FFF),   # CJK 基本區
    (0xAC00, 0xD7AF),   # 韓文
    (0xF900, 0xFAFF),   # CJK 相容表意文字
    (0xFF00, 0xFFEF),   # 全形符號
)


def _is_cjk_char(char):
    """判斷單一字元是否屬於 CJK / 全形範圍。"""
    code = ord(char)
    return any(low <= code <= high for low, high in CJK_RANGES)


# 標點前不補空白：這些字元若剛好落在新 token 的開頭（Whisper 偶爾把標點
# 切成獨立 token），不應在其前方多出一個孤立空白（如「today .」）。
# 除了本模組既有的句末／子句停頓標點，另外補上 STRONG_PUNCT／WEAK_PUNCT
# 未涵蓋的常見半形收尾標點（如英文句點「.」），確保英文標點也不會被誤加
# 空白；引號因半形寫法開闔同形（開頭/結尾都用同一個字元），無法單靠字元
# 本身判斷方向，故不列入（保守起見，寧可漏掉極少數情境也不誤刪必要空白）。
_NO_LEADING_SPACE = (frozenset(STRONG_PUNCT + WEAK_PUNCT)
                     | frozenset(".,!?;:)]}%")) - {" "}


def join_words(words) -> str:
    """
    把逐字時間軸的文字串回句子：拉丁字之間補空白、中日韓文字直接相連。

    Whisper 的逐字 token 在傳入前已被呼叫端 strip() 過（見
    transcriber.py），原始的前導空白資訊已經遺失，因此這裡改以「相鄰兩字
    是否都不是 CJK」判斷是否要補回空白，而非依賴 token 本身有無空白。
    中英混排時只在拉丁字與拉丁字的邊界補空白，CJK 字元前後不加空白；
    標點（句尾或停頓標點）開頭的 token 也不補空白，避免標點前出現孤立空白。
    """
    parts = []
    for item in words:
        text = item["word"] if isinstance(item, dict) else item
        if not text:
            continue
        if parts and text[0] not in _NO_LEADING_SPACE \
                and not _is_cjk_char(text[0]) \
                and not _is_cjk_char(parts[-1][-1]):
            parts.append(" ")
        parts.append(text)
    return "".join(parts).strip()


def is_cjk_dominant(text):
    """判斷一段文字是否以中文等全形文字為主（含少量英數仍視為中文）。"""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return False
    cjk_count = sum(1 for c in chars if _is_cjk_char(c))
    return cjk_count / len(chars) >= 0.3


def _line_limit(text, seg_cfg):
    """依文字屬性回傳該行允許的最大字數。"""
    if is_cjk_dominant(text):
        return max(int(seg_cfg.get("max_chars_cjk", 18)), 4)
    return max(int(seg_cfg.get("max_chars_latin", 45)), 8)


def _length(text):
    """計算文字長度（去除前後空白後的字元數）。"""
    return len(text.strip())


# ---------------------------------------------------------------------------
# 純文字斷行：split_into_lines 及其輔助函式
# ---------------------------------------------------------------------------

def split_into_lines(text, seg_cfg):
    """
    將一段（可能很長的）文字切成多行字幕文字。

    流程：換行/強標點切句 -> 過長者再以弱標點切子句並重新打包 -> 仍過長者硬切。
    回傳：list[str]，每個元素為一行不超過字數上限的字幕文字。
    """
    text = (text or "").strip()
    if not text:
        return []

    lines = []
    for sentence in _split_sentences(text):
        lines.extend(_split_long_clause(sentence, seg_cfg))
    return [line.strip() for line in lines if line.strip()]


def _split_sentences(text):
    """
    依換行與句末標點把文字切成數個句子，標點保留在句尾。

    為避免把對話、引文一刀切成兩半，引號或括弧內的句末標點不視為斷點。
    連續句末標點（如「。。。」「！！」「!?」）視為同一個結尾，僅切一次。
    """
    sentences = []
    buffer = ""
    quote_stack: list[str] = []
    previous = ""
    for char in text:
        if char in "\r\n":
            if buffer.strip():
                sentences.append(buffer.strip())
            buffer = ""
            previous = ""
            quote_stack.clear()
            continue
        # 維護引號 / 括弧堆疊：配對的關閉符號優先處理，再判斷是否為開啟符號。
        if (char in _CLOSE_TO_OPEN and quote_stack
                and quote_stack[-1] == _CLOSE_TO_OPEN[char]):
            quote_stack.pop()
        elif char in _OPEN_QUOTES:
            quote_stack.append(char)
        buffer += char
        # 在引號 / 括弧內不切句，避免把對話切散。
        if quote_stack:
            previous = char
            continue
        if char in STRONG_PUNCT:
            if previous in STRONG_PUNCT and sentences:
                # 連續強標點：併入上一個剛切出的句尾，避免「。。。」變成多句。
                sentences[-1] = (sentences[-1].rstrip() + char).strip()
                buffer = ""
            else:
                sentences.append(buffer.strip())
                buffer = ""
        previous = char
    if buffer.strip():
        sentences.append(buffer.strip())
    return sentences


def _split_at_weak(text):
    """依弱標點把句子切成子句，標點保留在子句尾端。"""
    clauses = []
    buffer = ""
    for char in text:
        buffer += char
        if char in WEAK_PUNCT and buffer.strip():
            clauses.append(buffer)
            buffer = ""
    if buffer:
        clauses.append(buffer)
    return clauses


def _split_long_clause(sentence, seg_cfg):
    """把單一句子切成不超過字數上限的多行。"""
    limit = _line_limit(sentence, seg_cfg)
    if _length(sentence) <= limit:
        return [sentence]

    # 以弱標點切成子句後，採貪婪法把子句打包進不超過上限的行。
    lines = []
    current = ""
    for clause in _split_at_weak(sentence):
        if not current:
            current = clause
        elif _length(current) + _length(clause) <= limit:
            current += clause
        else:
            lines.append(current)
            current = clause
    if current:
        lines.append(current)

    # 若仍有子句本身就超過上限（例如一長串沒有標點的文字），進行硬切。
    result = []
    for line in lines:
        if _length(line) <= limit:
            result.append(line)
        else:
            result.extend(_hard_split(line, limit))
    return result


def _hard_split(text, limit):
    """無標點可切時的最後手段：中文依字數切、英文依單字切。"""
    text = text.strip()
    if is_cjk_dominant(text):
        return [text[i:i + limit] for i in range(0, len(text), limit)]

    # 英文：以空白切成單字後逐字打包。
    lines = []
    current = ""
    for word in text.split():
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= limit:
            current += " " + word
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)

    # 處理單一單字就超長的極端情況。
    final = []
    for line in lines:
        if len(line) <= limit:
            final.append(line)
        else:
            final.extend(line[i:i + limit] for i in range(0, len(line), limit))
    return final


# ---------------------------------------------------------------------------
# 由逐字時間軸組字幕：build_cues_from_words（模式一使用）
# ---------------------------------------------------------------------------

def build_cues_from_words(words, seg_cfg):
    """
    將 Whisper 回傳的逐字時間軸組成字幕 cue 清單。

    參數：
        words: list[dict]，每筆為 {"word": str, "start": float, "end": float}
        seg_cfg: 斷句參數（config["segmentation"]）
    斷句時機（任一成立即切）：
        1. 累積文字達單行字數上限。
        2. 上一個字結尾為句末標點，且：
           - 已累積達上限的一半以上（避免「OK。」「對。」這種零碎字幕），或
           - 再加入下一字就會超過上限（避免下一句的開頭幾個字被擠進當段）。
        3. 上一個字結尾為子句停頓標點，且再加入下一字會超過上限
           （在子句邊界切，下一個子句整段留給下一段）。
        4. 與下一個字之間的靜音間隔超過 pause_gap。
    """
    if not words:
        return []

    pause_gap = float(seg_cfg.get("pause_gap", 0.5))
    cues = []
    bucket = []

    for index, word in enumerate(words):
        bucket.append(word)
        text = join_words(bucket)
        limit = _line_limit(text, seg_cfg)
        next_word = words[index + 1] if index + 1 < len(words) else None
        next_length = _length(next_word["word"]) if next_word else 0

        should_cut = False
        if _length(text) >= limit:
            # 已達字數上限：硬切。
            should_cut = True
        elif text and text[-1] in STRONG_PUNCT:
            # 句末：累積夠長、或下一字會跨上限時才切，
            # 否則允許繼續吸納下一句，整段同時也不會把下句頭幾字硬塞進來。
            soft_threshold = max(limit // 2, 6)
            if (_length(text) >= soft_threshold
                    or _length(text) + next_length > limit):
                should_cut = True
        elif next_word and (next_word["start"] - word["end"]) > pause_gap:
            # 明顯停頓：視為句子邊界。
            should_cut = True
        elif (text and text[-1] in WEAK_PUNCT and next_word
              and _length(text) + next_length > limit):
            # 子句邊界（如逗號、頓號）：若再加一字將跨上限，先在此切，
            # 把下個子句的整段留給下一段字幕，避免它被切散只剩前幾字。
            should_cut = True

        if should_cut or next_word is None:
            cues.append({
                "start": bucket[0]["start"],
                "end": bucket[-1]["end"],
                "text": text,
            })
            bucket = []

    return _post_process(cues, seg_cfg, words)


# ---------------------------------------------------------------------------
# 共用後處理：再切過長文字、套用秒數限制、避免重疊、重新編號
# ---------------------------------------------------------------------------

def _post_process(cues, seg_cfg, words=None):
    """
    對初步產生的 cue 做收尾處理：
    1. 文字若仍過長則再切，並依字數比例分配時間。
    2. 套用單句最短/最長秒數。
    3. 修正相鄰字幕的時間重疊。
    4. 重新編號 index，並把逐字時間軸掛回各 cue（供逐字動態字幕）。
    """
    min_duration = float(seg_cfg.get("min_duration", 1.0))
    max_duration = float(seg_cfg.get("max_duration", 7.0))

    expanded = []
    for cue in cues:
        text = cue["text"].strip()
        if not text:
            continue
        lines = split_into_lines(text, seg_cfg)
        if not lines:
            continue
        duration = max(cue["end"] - cue["start"], 0.1)
        weight_total = sum(max(_length(line), 1) for line in lines)
        cursor = cue["start"]
        for line in lines:
            share = duration * max(_length(line), 1) / weight_total
            expanded.append({"start": cursor, "end": cursor + share, "text": line})
            cursor += share

    # 套用最短與最長秒數限制。
    for cue in expanded:
        length = cue["end"] - cue["start"]
        if length < min_duration:
            cue["end"] = cue["start"] + min_duration
        if cue["end"] - cue["start"] > max_duration:
            cue["end"] = cue["start"] + max_duration

    # 修正重疊：確保輸出嚴格不重疊且時間單調遞增（不重疊優先於最短秒數）。
    expanded = _normalize_no_overlap(expanded)

    # 合併過短的孤字，避免單一字（如英文單字尾巴）被擠到下一段顯示。
    expanded = _merge_orphan_cues(expanded)

    # 合併相鄰且內容相同的字幕（Whisper 幻覺重複的最後一道防線，Issue #4）。
    expanded = _merge_duplicate_cues(expanded, max_duration)

    # 套用整體時間軸偏移，供使用者修正字幕時間偏差。
    time_offset = float(seg_cfg.get("time_offset", 0.0))
    if time_offset:
        for cue in expanded:
            cue["start"] = max(0.0, cue["start"] + time_offset)
            cue["end"] = max(cue["start"] + 0.1, cue["end"] + time_offset)

    for number, cue in enumerate(expanded, start=1):
        cue["index"] = number
    # 把逐字時間軸依時間掛回各 cue，供逐字動態字幕（卡拉OK／單字彈出）
    # 於燒錄與 ASS 匯出時使用；不影響其他輸出格式。
    if words:
        _attach_words(expanded, words, time_offset)
    return expanded


def _attach_words(cues, words, time_offset=0.0):
    """
    把逐字時間軸依時間中點分配到各 cue（cue["words"]）。

    cue 時間經過比例重分配與偏移，與原始字時間只是近似對應；
    以「字的時間中點落在哪個 cue 區間」分派，落在間隙的字歸給
    下一個 cue、結尾剩餘的字歸給最後一個 cue，確保沒有字被丟失。
    存入的是複製品（已套用時間偏移），不改動呼叫端的 words。
    """
    if not cues:
        return
    word_index = 0
    total = len(words)
    for position, cue in enumerate(cues):
        bucket = []
        is_last = position == len(cues) - 1
        while word_index < total:
            word = words[word_index]
            midpoint = (word["start"] + word["end"]) / 2 + time_offset
            if midpoint > cue["end"] and not is_last:
                break  # 屬於後面的 cue。
            text = (word.get("word") or "").strip()
            if text:
                bucket.append({
                    "word": text,
                    "start": word["start"] + time_offset,
                    "end": word["end"] + time_offset,
                })
            word_index += 1
        if bucket:
            cue["words"] = bucket


# 視為「孤字碎片」的最大字數，達此長度以下會被併回前一句。
_MAX_ORPHAN_CHARS = 2

# 孤字合併允許的最大時間差（秒）：孤字與前一句間隔超過此值時視為
# 停頓後的獨立反應詞（「嗯」「喔」很常見），不併回——否則前一句的
# 顯示時間會被拉長、橫跨整段靜音，畫面上字幕停留過久。
_MAX_ORPHAN_GAP = 1.0

# 不重疊正規化用的極小間隔（秒）：兩句時間衝突到無法單靠截短前一句解決時
# （例如起始時間相同或反序），前一句最少也要有這麼長，避免變成零長度或負值。
_MIN_GAP_EPSILON = 0.05


def _normalize_no_overlap(cues):
    """
    最終正規化：確保輸出嚴格不重疊、且時間單調遞增。

    對齊模式（模式二）常見兩句幾乎同時起始（甚至起始時間完全相同）的情況；
    先前只靠「截短前一句」的作法在起始時間相同或反序時無法真正消除重疊
    （見 v1.14.1 修復的 Issue：前一句被延長到最短秒數後，
    截短時又被拉回原本過短的結束時間，導致與下一句重疊）。

    修正原則：不重疊優先於最短秒數——寧可前一句稍短，也不要兩句重疊：
    1. 若前一句結束時間超過下一句開始時間，先嘗試把前一句結束時間
       截到下一句的開始時間（兩句剛好首尾相接，不算重疊）。
    2. 若下一句開始時間早於（或等於）前一句開始時間（起始時間相同或反序），
       單靠截短前一句無法避免重疊：改為讓前一句維持極小長度
       （_MIN_GAP_EPSILON），並把下一句整段順延相同的時間，
       保留下一句原本的長度不變。
    依序處理相鄰兩句，順延效應會在下一輪迭代中一併處理後續的句子，
    確保整體時間軸不會因此在更後面重新產生重疊。
    """
    for i in range(1, len(cues)):
        previous = cues[i - 1]
        current = cues[i]
        if previous["end"] <= current["start"]:
            continue  # 未重疊，維持原樣（不影響一般不衝突的情況）。
        new_previous_end = current["start"]
        if new_previous_end <= previous["start"]:
            # 起始時間相同或反序：改為順延下一句，保留其原本長度。
            new_previous_end = previous["start"] + _MIN_GAP_EPSILON
            shift = new_previous_end - current["start"]
            duration = current["end"] - current["start"]
            current["start"] = new_previous_end
            current["end"] = current["start"] + duration
        previous["end"] = new_previous_end
    return cues


def _merge_duplicate_cues(cues, max_duration):
    """
    合併相鄰且文字完全相同、時間重疊或緊貼的字幕（修復 Issue #4）。

    Whisper 幻覺會在同一時間點重複輸出同一句話；即使字詞層已去重，
    仍以此作為 cue 層的最後防線。合併後長度以 max_duration 為上限。
    """
    if len(cues) < 2:
        return cues
    merged = [cues[0]]
    for cue in cues[1:]:
        previous = merged[-1]
        if (cue["text"] == previous["text"]
                and cue["start"] <= previous["end"] + 0.2):
            previous["end"] = min(
                max(previous["end"], cue["end"]),
                previous["start"] + max_duration)
        else:
            merged.append(cue)
    return merged


def _merge_orphan_cues(cues):
    """把過短的孤字字幕併回前一句，避免單字被擠到下一段顯示。"""
    if len(cues) < 2:
        return cues
    merged = []
    for cue in cues:
        text = cue["text"].strip()
        if (merged and len(text) <= _MAX_ORPHAN_CHARS
                and cue["start"] - merged[-1]["end"] <= _MAX_ORPHAN_GAP):
            # 視為被擠出的碎片，接回前一句末端並延長其結束時間；
            # 以 CJK 感知組字接回（英文孤字如 ok 之前要補空白）。
            previous = merged[-1]
            previous["text"] = join_words([previous["text"].rstrip(), text])
            previous["end"] = cue["end"]
        else:
            merged.append(cue)
    return merged
