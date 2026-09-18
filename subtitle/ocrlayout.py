# -*- coding: utf-8 -*-
"""
把 OCR 回來的「一堆帶座標的字塊」併回人看得懂的段落。

**為什麼需要這一層**：OCR 引擎（tesseract 的 TSV、各家 vision API 的
`boundingBox`）吐出來的不是文章，是一堆字塊加上它們在圖上的位置。直接照
順序串起來會得到三種壞結果，而且每一種都會讓後面的翻譯跟著爛掉：

1. **硬換行留在句子中間。** 對話框把一句話折成三行，串起來就是三個殘
   句，翻譯只能逐行猜，出來的中文接不起來。
2. **中日文之間被插入空白。** 調研實測（`docs/RESEARCH_SCREEN_OCR.md`）
   裡，日文與繁中兩個案例的辨識其實是**一字不差**的，但 tesseract 會在
   每個字之間放一個空白，逐字元比對的錯誤率因此從 0% 變成 73~82%。送出
   去的若是「扉 は 三 つ の 封印」，翻譯品質當然會掉。
3. **左右兩欄被讀成同一行。** 遊戲設定頁那種兩欄版面，OCR 依 y 座標排
   序，會把左欄的「Resolution」和右欄的「Master Volume」串成一行。

本模組是純邏輯、零 GUI 依賴、也不綁任何一家 OCR 引擎——只吃
``{"text", "left", "top", "width", "height", "conf"}`` 這個共同形狀，所
以三條 OCR 路線（tesseract／vision API／Windows 內建）換來換去都不必改
這裡。

**信心值門檻**同樣在這裡：調研實測顯示「用 tesseract 自報的平均信心值挑
辨識模式」在 12 個案例裡有 11 個挑中最佳或相差 2% 以內，而唯一挑錯的那
個是「整張圖是雜訊、根本沒有字」的極端情形——它的平均信心值只有 22。所
以低信心不是拿來挑模式的，是拿來**告訴使用者「這塊沒讀到字，請重框」**，
而不是把一串亂碼送去翻譯。
"""

import re

# 可調參數（存進 config.json 的 "ocrlayout" 區塊）。
DEFAULT_OCRLAYOUT = {
    # 單一字塊的信心值低於此就丟掉（雜訊碎片）。
    "min_conf": 45.0,
    # 整塊的平均信心值低於此就判定「讀不到」，不送翻譯。
    # 實測參考值：乾淨畫面 96、彩色場景上的描邊字 77、亮底描邊字 83、
    # 逐像素雜訊（沒有字）22。60 落在「勉強可用」與「根本沒字」之間。
    "usable_conf": 60.0,
    # 同一列裡的水平間距大於「中位字寬 × 此倍數」就視為分欄。
    "column_gap_ratio": 3.0,
    # 列與列的垂直間距大於「中位列高 × 此倍數」就分段。
    "para_gap_ratio": 1.6,
}

# 判定為 CJK 的字元範圍（中日韓統一表意文字、日文假名、全形標點）。
_CJK_RE = re.compile(
    r"[　-〿぀-ゟ゠-ヿ㐀-䶿"
    r"一-鿿豈-﫿＀-｠￠-￦]")
# 前面不該有空白的半形標點。
_CLOSE_PUNCT = ".,!?;:)]}%’”"
# 後面不該有空白的半形標點。
_OPEN_PUNCT = "([{‘“$"


def _clamp(value, low, high):
    return max(low, min(high, value))


def resolve_ocrlayout_settings(config=None):
    """取出本模組的設定，缺漏補預設值並夾到合理範圍。"""
    raw = dict(DEFAULT_OCRLAYOUT)
    if config:
        raw.update({k: v for k, v in (config.get("ocrlayout") or {}).items()
                    if k in DEFAULT_OCRLAYOUT})
    return {
        "min_conf": _clamp(float(raw["min_conf"]), 0.0, 100.0),
        "usable_conf": _clamp(float(raw["usable_conf"]), 0.0, 100.0),
        "column_gap_ratio": _clamp(float(raw["column_gap_ratio"]), 1.2, 12.0),
        "para_gap_ratio": _clamp(float(raw["para_gap_ratio"]), 1.05, 6.0),
    }


def is_cjk(text):
    """字串的第一個／最後一個字元是不是 CJK（用來決定要不要補空白）。"""
    return bool(text) and bool(_CJK_RE.search(text))


def _median(values):
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _char_width(box):
    """單字元寬度估計；CJK 一個字就佔一格，拉丁文要除以字數。"""
    text = box.get("text") or ""
    if not text:
        return float(box.get("width", 0))
    return float(box.get("width", 0)) / max(1, len(text))


def join_boxes(boxes):
    """
    把同一列（或同一欄段）的字塊串成一行文字。

    規則只有三條，但每一條都是實測踩出來的：
      - 兩邊只要有一邊是 CJK 就**不加空白**（tesseract 會逐字切開）
      - 半形收尾標點前面不加空白、起始標點後面不加空白
      - 其餘照英文習慣補一個空白
    """
    parts = []
    for box in boxes:
        text = (box.get("text") or "").strip()
        if not text:
            continue
        if not parts:
            parts.append(text)
            continue
        prev = parts[-1]
        if _CJK_RE.search(prev[-1]) or _CJK_RE.search(text[0]):
            sep = ""
        elif text[0] in _CLOSE_PUNCT or prev[-1] in _OPEN_PUNCT:
            sep = ""
        else:
            sep = " "
        parts.append(sep + text)
    return "".join(parts)


def group_lines(boxes):
    """
    依垂直重疊把字塊分成一列一列。

    用「重疊過半」而不是「top 相同」：同一列裡大小寫字母、CJK 與拉丁字
    混排時，`top` 本來就會差好幾像素（實測日文那張圖同一列的 top 從 41
    到 51 都有）。
    """
    remaining = sorted((b for b in boxes if (b.get("text") or "").strip()),
                       key=lambda b: (b.get("top", 0), b.get("left", 0)))
    lines = []
    for box in remaining:
        top = box.get("top", 0)
        bottom = top + box.get("height", 0)
        placed = False
        for line in lines:
            ltop = min(b.get("top", 0) for b in line)
            lbottom = max(b.get("top", 0) + b.get("height", 0) for b in line)
            overlap = min(bottom, lbottom) - max(top, ltop)
            shorter = max(1, min(bottom - top, lbottom - ltop))
            if overlap > shorter * 0.5:
                line.append(box)
                placed = True
                break
        if not placed:
            lines.append([box])
    for line in lines:
        line.sort(key=lambda b: b.get("left", 0))
    lines.sort(key=lambda line: min(b.get("top", 0) for b in line))
    return lines


def line_gaps(line, gap_ratio, char_width):
    """回傳這一列裡「間距大到可能是欄界」的位置（後一塊的左緣）。"""
    if len(line) < 2 or char_width <= 0:
        return []
    threshold = char_width * gap_ratio
    edges = []
    for prev, box in zip(line, line[1:]):
        gap = box.get("left", 0) - (prev.get("left", 0) + prev.get("width", 0))
        if gap > threshold:
            edges.append(box.get("left", 0))
    return edges


def find_column_edges(lines, gap_ratio, char_width):
    """
    從所有列的大間距裡，挑出**真的是欄界**的那幾個 x。

    關鍵是「跨列一致」：單獨一列出現一個大洞，多半是那幾個字沒被辨識出
    來，不是版面分欄。實測踩到過——彩色場景那張圖有兩列各缺了幾個字，
    只看單列就把一段話切成假的兩欄（「The gate will not ／ Press F
    to」），整段話因此對不起來。要求同一個 x 至少被兩列、且至少四成的
    列支持，那張圖就不再誤判，而真的兩欄版面（四列都在同一個 x 斷開）
    照樣抓得到。
    """
    if len(lines) < 2 or char_width <= 0:
        return []
    clusters = []            # [[x 們], 支持它的列數]
    for line in lines:
        for edge in line_gaps(line, gap_ratio, char_width):
            for cluster in clusters:
                if abs(edge - cluster[0][0]) <= char_width * 2:
                    cluster[0].append(edge)
                    cluster[1] += 1
                    break
            else:
                clusters.append([[edge], 1])
    need = max(2, int(len(lines) * 0.4 + 0.5))
    # 用**最小值**而不是平均值當欄界：平均會落在那些本來就該被分到右欄
    # 的字塊身上。實測踩過——四列的右欄分別從 x=700、703、703、700 開
    # 始，平均是 701.5，於是 x=700 的那兩塊（Audio、Voice）被留在左欄，
    # 兩欄的內容整個交錯。最左邊那一塊的起點才是真正的界線。
    return sorted(min(xs) for xs, n in clusters if n >= need)


def split_columns(line, edges):
    """照既定的欄界把一列切成多段。"""
    if not edges:
        return [list(line)]
    segments = [[]]
    cursor = 0
    for box in line:
        while cursor < len(edges) and box.get("left", 0) >= edges[cursor]:
            cursor += 1
            segments.append([])
        segments[-1].append(box)
    return [seg for seg in segments if seg]


def _column_index(left, boundaries):
    """把一個段落起點對到它屬於第幾欄。"""
    index = 0
    for i, edge in enumerate(boundaries):
        if left >= edge:
            index = i
    return index


def layout_text(boxes, config=None):
    """
    主入口：一堆字塊 → 可讀的段落。

    回傳 ``{"text", "paragraphs", "columns", "mean_conf", "verdict",
    "kept", "dropped"}``。``verdict`` 是 ``"ok"`` / ``"weak"`` /
    ``"unreadable"``，介面層照它決定要直接翻、要提醒使用者結果可能不準、
    還是根本不要送出去翻（見模組說明裡的信心值那一段）。
    """
    settings = resolve_ocrlayout_settings(config)
    all_text = [b for b in boxes if (b.get("text") or "").strip()]
    usable = [b for b in all_text
              if float(b.get("conf", 0)) >= settings["min_conf"]]
    dropped = len(all_text) - len(usable)
    # 過濾**之前**的平均與留存比例：這兩個才看得出「整張圖根本沒有字」。
    raw_mean = (sum(float(b.get("conf", 0)) for b in all_text) / len(all_text)
                if all_text else 0.0)
    kept_ratio = len(usable) / len(all_text) if all_text else 0.0
    if not usable:
        return {"text": "", "paragraphs": [], "columns": 0, "mean_conf": 0.0,
                "raw_mean_conf": raw_mean, "kept_ratio": 0.0,
                "verdict": "unreadable", "kept": 0, "dropped": dropped}

    mean_conf = sum(float(b.get("conf", 0)) for b in usable) / len(usable)
    char_width = _median([_char_width(b) for b in usable])

    lines = group_lines(usable)
    line_height = _median([max(b.get("height", 0) for b in line)
                           for line in lines]) or 1.0

    # 先找出跨列一致的欄界，再照它切——不是每一列各切各的。
    edges = find_column_edges(lines, settings["column_gap_ratio"], char_width)
    segmented = [split_columns(line, edges) for line in lines]
    boundaries = [0.0] + list(edges)

    # 欄 → 該欄由上而下的列（帶著 y 座標，等一下要算段落間距）。
    columns = {}
    for line, segs in zip(lines, segmented):
        for seg in segs:
            left = min(b.get("left", 0) for b in seg)
            idx = _column_index(left, boundaries)
            top = min(b.get("top", 0) for b in seg)
            bottom = max(b.get("top", 0) + b.get("height", 0) for b in seg)
            columns.setdefault(idx, []).append((top, bottom, seg))

    paragraphs = []
    for idx in sorted(columns):
        rows = sorted(columns[idx], key=lambda r: r[0])
        current = []
        prev_bottom = None
        for top, bottom, seg in rows:
            gap = 0 if prev_bottom is None else top - prev_bottom
            if current and gap > line_height * settings["para_gap_ratio"]:
                paragraphs.append(_stitch(current))
                current = []
            current.append(join_boxes(seg))
            prev_bottom = bottom
        if current:
            paragraphs.append(_stitch(current))

    paragraphs = [p for p in paragraphs if p]
    # 只看「留下來那些的平均信心」會被自己騙過去：實測那張逐像素雜訊圖
    # （畫面上根本沒有字）吐出 125 個字塊、整體平均只有 21.9，但把低於
    # 45 的丟掉之後，剩下 18 塊的平均是 68.2——照那個數字判就會回報
    # 「ok」，然後把一串亂碼送去翻譯。所以判讀要看**過濾前**的平均與留
    # 存比例。
    if (mean_conf < settings["usable_conf"] * 0.6
            or (kept_ratio < 0.5 and raw_mean < settings["usable_conf"])):
        verdict = "unreadable"
        paragraphs = []
    elif mean_conf < settings["usable_conf"] or kept_ratio < 0.75:
        verdict = "weak"
    else:
        verdict = "ok"
    return {"text": "\n\n".join(paragraphs), "paragraphs": paragraphs,
            "columns": len(columns), "mean_conf": mean_conf,
            "raw_mean_conf": raw_mean, "kept_ratio": kept_ratio,
            "verdict": verdict, "kept": len(usable), "dropped": dropped}


def _stitch(lines):
    """
    把同一段裡被硬換行切開的幾列接回一句。

    - 行尾是連字號：直接黏起來並吃掉那個連字號（英文斷字）
    - 兩邊有一邊是 CJK：不補空白
    - 其餘補一個空白
    """
    out = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if not out:
            out = line
            continue
        if out.endswith("-"):
            out = out[:-1] + line
        elif _CJK_RE.search(out[-1]) or _CJK_RE.search(line[0]):
            out += line
        else:
            out += " " + line
    return out


def describe_verdict(result):
    """給介面用的一句話（沉默地什麼都不做＝使用者以為壞掉）。"""
    verdict = result.get("verdict")
    conf = result.get("mean_conf", 0.0)
    if verdict == "unreadable":
        return ("這一塊沒有讀到文字（辨識信心 %.0f）。試著框大一點、"
                "框準一點，或把畫面放大再框。" % conf)
    if verdict == "weak":
        return ("辨識信心偏低（%.0f），下面的結果可能有錯字，"
                "翻譯也會跟著受影響。" % conf)
    return "辨識完成（信心 %.0f）。" % conf
