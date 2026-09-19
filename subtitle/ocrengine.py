# -*- coding: utf-8 -*-
"""
本地 OCR 引擎（tesseract）的包裝層。

**為什麼是本地而不是 vision 模型 API**：`docs/RESEARCH_SCREEN_OCR.md` 的
實測結論——12 個難例裡 8 個一字不差、10 個字元錯誤率 ≤ 5%、單次中位數
218 ms、不用錢，而且**畫面不必離開這台電腦**（只有辨識出來的文字才會送
去翻譯）。費用、延遲、隱私三件事一起解掉。

本模組做三件事，每一件都是調研量出來的：

1. **三種模式全跑，照 tesseract 自報的平均信心值挑。** 沒有一種模式全
   贏——`psm6` 把「亮底白字黑描邊」那個案例從 51.8% 救到 4.4%，
   `psm6`＋放大把細描邊從 3.6% 救到 1.1%，而 `psm3` 最快、在乾淨畫面上
   並列第一。實作時沒有標準答案可比，只能照信心值挑；實測 13 個案例裡
   12 個挑中最佳或與最佳相差 2% 以內。
2. **放大依面積設上限。** 使用者框到大半個螢幕時，放大後的面積會爆
   增，所以超過上限就跳過那個模式，並記下原因。
3. **貴的模式只在「可能救得起來」時才跑。** 放大那一次要花掉其餘兩次
   加起來的時間，所以先跑兩個便宜的，再看它們的信心值決定要不要跑：
   已經夠好（≥ 90）就不必救，根本沒讀到東西（< 40）也救不起來。實測
   這條規則在乾淨畫面上省下約 0.4 秒，在那張雜訊圖上省下 **6.8 秒**，
   而唯二真的靠放大變好的兩個案例（細描邊 80→93、彩色場景 68→77）都
   落在中間區間，照樣會跑。
4. **引擎不在時給得出下一步。** 「找不到 tesseract」要講清楚可以怎麼
   辦，不是丟一個 FileNotFoundError。

零 GUI 依賴，CLI 也用得到。辨識結果是一堆帶座標的字塊，要併回可讀段落
交給 `subtitle/ocrlayout.py`（那一層不綁任何一家 OCR 引擎）。
"""

from __future__ import annotations

import csv
import io
import os
import shutil
import struct
import subprocess
import sys
import time

from subtitle import ocrlayout

# 依序嘗試的辨識模式：(名稱, tesseract 的 --psm, 放大倍率)。
# 三個全跑約 0.8 秒，換來的是「難例不會整個垮掉」。
MODES = (("psm3", 3, 1), ("psm6", 6, 1), ("psm6_x3", 6, 3))

DEFAULT_OCRENGINE = {
    # 放大後的像素面積上限；超過就跳過放大那個模式（見模組說明第 2 點）。
    "max_upscale_pixels": 4_000_000,
    # 便宜的模式已經跑到這個信心值以上，就不必再花時間放大重跑。
    "good_enough_conf": 90.0,
    # 反過來，低到這個程度表示畫面上根本沒有可讀的字，放大也救不起來。
    # 實測那張雜訊圖的兩個便宜模式是 0 與 22，放大跑掉 6.8 秒還是亂碼。
    "hopeless_conf": 40.0,
    # 單一模式的逾時秒數。
    "timeout_seconds": 30,
    # 預設辨識語言（tesseract 的語言代碼，可用 "+" 串多個）。
    "lang": "eng",
}

# 打包成 exe 之後 tesseract 會被裝在這裡（比照 subtitle/ffmpeg_setup.py
# 的作法；一鍵安裝本身是下一階段的工作，這裡先把尋找的路認好，安裝功能
# 接上來時不必改這個模組）。
_TOOL_SUBDIR = os.path.join("tools", "tesseract")
_BINARY_NAME = "tesseract.exe" if sys.platform == "win32" else "tesseract"


class OcrError(RuntimeError):
    """OCR 失敗；訊息一律寫成使用者看得懂、而且講得出下一步的話。"""


def _clamp(value, low, high):
    return max(low, min(high, value))


def resolve_ocrengine_settings(config=None):
    """取出本模組的設定，缺漏補預設值並夾到合理範圍。"""
    raw = dict(DEFAULT_OCRENGINE)
    if config:
        raw.update({k: v for k, v in (config.get("ocrengine") or {}).items()
                    if k in DEFAULT_OCRENGINE})
    return {
        "max_upscale_pixels": int(_clamp(int(raw["max_upscale_pixels"]),
                                         100_000, 80_000_000)),
        "timeout_seconds": int(_clamp(int(raw["timeout_seconds"]), 3, 300)),
        "good_enough_conf": _clamp(float(raw["good_enough_conf"]), 0.0, 100.0),
        "hopeless_conf": _clamp(float(raw["hopeless_conf"]), 0.0, 100.0),
        "lang": str(raw["lang"]).strip() or "eng",
    }


# ----------------------------------------------------------------------
# 找引擎
# ----------------------------------------------------------------------
def install_candidates():
    """依優先序回傳可能裝著 tesseract 的資料夾（比照 ffmpeg_setup）。"""
    from subtitle.ffmpeg_setup import app_root, _user_data_dir
    return [os.path.join(app_root(), _TOOL_SUBDIR),
            os.path.join(_user_data_dir(), "tesseract")]


def tesseract_path():
    """找得到就回傳執行檔路徑，否則 None。先看 PATH，再看自己裝的位置。"""
    found = shutil.which("tesseract")
    if found:
        return found
    for folder in install_candidates():
        candidate = os.path.join(folder, _BINARY_NAME)
        if os.path.isfile(candidate):
            return candidate
    return None


def tesseract_available():
    return tesseract_path() is not None


def _require_tesseract():
    path = tesseract_path()
    if not path:
        raise OcrError(
            "找不到文字辨識引擎（tesseract）。可以用程式裡的一鍵安裝裝好"
            "它，或自行安裝後加入系統 PATH。")
    return path


def available_languages():
    """回傳已安裝的語言代碼集合；引擎不在或問不到時回傳空集合。"""
    path = tesseract_path()
    if not path:
        return set()
    try:
        proc = subprocess.run([path, "--list-langs"], capture_output=True,
                              timeout=30)
    except (OSError, subprocess.SubprocessError):
        return set()
    langs = set()
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        line = line.strip()
        # 第一行是「List of available languages ...」之類的說明。
        if line and " " not in line and ":" not in line:
            langs.add(line)
    return langs


def missing_languages(lang, installed=None):
    """``lang``（可用 "+" 串多個）裡有哪幾個沒裝。"""
    installed = available_languages() if installed is None else set(installed)
    wanted = [part for part in str(lang).split("+") if part.strip()]
    return [part for part in wanted if part not in installed]


# ----------------------------------------------------------------------
# 圖片尺寸（零第三方依賴）
# ----------------------------------------------------------------------
def image_size(path):
    """
    回傳 (寬, 高)；認不出來時回傳 None。

    只讀檔頭，不解碼整張圖——PNG 與 BMP 是螢幕擷取會產出的兩種格式，直
    接讀規格裡固定位置的欄位就夠了。都認不出來時退到 ffprobe（本專案本
    來就要 ffmpeg）。
    """
    try:
        with open(path, "rb") as handle:
            head = handle.read(32)
    except OSError:
        return None
    if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
        width, height = struct.unpack(">II", head[16:24])
        return int(width), int(height)
    if head[:2] == b"BM" and len(head) >= 26:
        width, height = struct.unpack("<ii", head[18:26])
        return abs(int(width)), abs(int(height))
    return _ffprobe_size(path)


def _ffprobe_size(path):
    if not shutil.which("ffprobe"):
        return None
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x",
             path], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    text = proc.stdout.decode("utf-8", "replace").strip()
    parts = text.split("x")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return int(parts[0]), int(parts[1])
    return None


def upscale_worthwhile(best_conf, settings):
    """
    便宜的模式跑完之後，值不值得再花時間放大重跑（純算式，可離線測）。

    兩頭都不划算：已經夠好的不必救，根本沒讀到字的救不起來。回傳
    ``(要不要跑, 不跑的原因)``。
    """
    if best_conf >= settings["good_enough_conf"]:
        return False, "前面的模式已經夠準"
    if best_conf < settings["hopeless_conf"]:
        return False, "畫面上讀不到字，放大也沒用"
    return True, ""


def upscale_allowed(size, factor, settings):
    """
    放大這張圖划不划算（純算式，可離線測）。

    尺寸量不到時保守地**不放大**——寧可少一個模式，也不要讓使用者框到一
    大塊畫面時等上好幾秒還以為當掉了。
    """
    if factor <= 1:
        return True
    if not size:
        return False
    width, height = size
    return width * height * factor * factor <= settings["max_upscale_pixels"]


# ----------------------------------------------------------------------
# 跑辨識
# ----------------------------------------------------------------------
def parse_tsv(text):
    """把 tesseract 的 TSV 輸出轉成字塊清單（只留真的有字的列）。"""
    rows = csv.DictReader(io.StringIO(text), delimiter="\t",
                          quoting=csv.QUOTE_NONE)
    boxes = []
    for row in rows:
        word = (row.get("text") or "").strip()
        if not word:
            continue
        try:
            conf = float(row.get("conf", "-1"))
        except (TypeError, ValueError):
            conf = -1.0
        if conf < 0:
            continue
        try:
            boxes.append({
                "text": word,
                "left": int(row["left"]), "top": int(row["top"]),
                "width": int(row["width"]), "height": int(row["height"]),
                "conf": round(conf, 1),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return boxes


def mean_conf(boxes):
    if not boxes:
        return 0.0
    return sum(float(b.get("conf", 0)) for b in boxes) / len(boxes)


def rescale_boxes(boxes, factor):
    """把放大後的座標換算回原圖座標。"""
    if factor == 1:
        return boxes
    out = []
    for box in boxes:
        item = dict(box)
        for key in ("left", "top", "width", "height"):
            item[key] = int(round(box.get(key, 0) / float(factor)))
        out.append(item)
    return out


def pick_best(attempts):
    """
    從各模式的結果裡挑一個（純邏輯，可離線測）。

    照**平均信心值**挑：實作時沒有標準答案可比，而調研實測顯示這個挑法
    在 13 個案例裡有 12 個挑中最佳或與最佳相差 2% 以內。完全沒讀到字的
    模式（沒有字塊）一律不列入，否則一個空結果會以 0 分參賽。
    """
    usable = [a for a in attempts if a.get("boxes")]
    if not usable:
        return None
    return max(usable, key=lambda a: a["mean_conf"])


def _upscale_image(path, factor, timeout):
    """用 ffmpeg 放大（本專案本來就要 ffmpeg，不必多一個相依）。"""
    if not shutil.which("ffmpeg"):
        return None
    base, ext = os.path.splitext(path)
    out = f"{base}_x{factor}{ext or '.png'}"
    try:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", path,
             "-vf", f"scale=iw*{factor}:ih*{factor}:flags=lanczos", out],
            capture_output=True, timeout=timeout, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return out if os.path.isfile(out) else None


def _run_mode(binary, image_path, lang, psm, timeout):
    started = time.time()
    try:
        proc = subprocess.run(
            [binary, image_path, "stdout", "-l", lang, "--psm", str(psm),
             "tsv"],
            capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise OcrError(
            f"文字辨識逾時（超過 {timeout} 秒）。框選的範圍可能太大，"
            "試著只框要讀的那幾行。")
    except OSError as exc:
        raise OcrError(f"文字辨識引擎無法執行：{exc}")
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise OcrError("文字辨識失敗："
                       + (detail[-1] if detail else f"錯誤碼 {proc.returncode}"))
    boxes = parse_tsv(proc.stdout.decode("utf-8", "replace"))
    return boxes, time.time() - started


def recognize(image_path, lang=None, config=None, progress_cb=None):
    """
    對一張圖跑辨識，回傳挑選後的結果。

    回傳 ``{"boxes", "mode", "mean_conf", "seconds", "attempts"}``。
    ``attempts`` 逐項記下每個模式的信心值、耗時，以及**被跳過的原因**
    ——放大被面積上限擋下來時要看得出來，不然使用者只會覺得「有時候慢有
    時候快」。
    """
    settings = resolve_ocrengine_settings(config)
    lang = (lang or settings["lang"]).strip() or "eng"
    binary = _require_tesseract()
    if not os.path.isfile(image_path):
        raise OcrError(f"找不到要辨識的圖片：{image_path}")

    size = image_size(image_path)
    attempts = []
    temps = []
    started = time.time()
    try:
        for name, psm, factor in MODES:
            if factor > 1:
                best_so_far = max([a["mean_conf"] for a in attempts] or [0.0])
                worth, why = upscale_worthwhile(best_so_far, settings)
                if not worth:
                    attempts.append({"mode": name, "skipped": why, "boxes": [],
                                     "mean_conf": 0.0, "seconds": 0.0})
                    continue
            if not upscale_allowed(size, factor, settings):
                attempts.append({"mode": name, "skipped": "框選範圍太大，"
                                 "放大後會太慢",
                                 "boxes": [], "mean_conf": 0.0, "seconds": 0.0})
                continue
            target = image_path
            if factor > 1:
                target = _upscale_image(image_path, factor,
                                        settings["timeout_seconds"])
                if not target:
                    attempts.append({"mode": name, "skipped": "放大失敗（ffmpeg）",
                                     "boxes": [], "mean_conf": 0.0,
                                     "seconds": 0.0})
                    continue
                temps.append(target)
            if progress_cb:
                progress_cb(len(attempts) / float(len(MODES)), f"辨識中（{name}）...")
            boxes, seconds = _run_mode(binary, target, lang, psm,
                                       settings["timeout_seconds"])
            attempts.append({"mode": name, "skipped": "",
                             "boxes": rescale_boxes(boxes, factor),
                             "mean_conf": mean_conf(boxes), "seconds": seconds})
    finally:
        for path in temps:
            try:
                os.unlink(path)
            except OSError:
                pass

    best = pick_best(attempts)
    return {
        "boxes": best["boxes"] if best else [],
        "mode": best["mode"] if best else "",
        "mean_conf": best["mean_conf"] if best else 0.0,
        "seconds": time.time() - started,
        "attempts": attempts,
    }


def recognize_text(image_path, lang=None, config=None, progress_cb=None):
    """
    辨識 ＋ 排版還原，一步到位（GUI 端最常用的入口）。

    回傳 `ocrlayout.layout_text` 的結果再加上 ``mode``／``seconds``。
    `verdict` 為 ``"unreadable"`` 時**不要把文字送去翻譯**——那多半是一
    串亂碼，調研文件第 3.3 節有實測數字。
    """
    result = recognize(image_path, lang=lang, config=config,
                       progress_cb=progress_cb)
    laid = ocrlayout.layout_text(result["boxes"], config)
    laid["mode"] = result["mode"]
    laid["seconds"] = result["seconds"]
    laid["attempts"] = result["attempts"]
    return laid


def describe_attempts(attempts):
    """一行字說明各模式跑了什麼（給狀態列／記錄用）。"""
    parts = []
    for attempt in attempts:
        if attempt.get("skipped"):
            parts.append(f"{attempt['mode']}：略過（{attempt['skipped']}）")
        else:
            parts.append(f"{attempt['mode']}：信心 {attempt['mean_conf']:.0f}、"
                         f"{attempt['seconds'] * 1000:.0f}ms")
    return "；".join(parts)
