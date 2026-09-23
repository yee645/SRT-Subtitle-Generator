# -*- coding: utf-8 -*-
"""
螢幕擷取：把使用者框起來的那一塊畫面存成圖，交給 OCR。

**隱私是這個模組的第一條規則**，不是附註：只擷取**使用者當下框起來的那
一塊**，不自動、不背景、不連續截圖。沿用 v2.1.0 剪貼簿監聽的同一個原則
——「寧可漏翻、不可誤送」。這裡沒有任何定時器，每一次擷取都必須由一次明
確的使用者動作觸發。

**三個平台各用各的辦法，但介面一樣**：

| 平台 | 作法 | 開發時能不能驗 |
|---|---|---|
| Windows | `ctypes` + GDI（`BitBlt` / `GetDIBits`），零第三方依賴 | **不行**（沒有 Windows） |
| Linux | ImageMagick 的 `import`，退到 ffmpeg 的 `x11grab` | **可以**，Xvfb 下實測 |
| macOS | 內建的 `screencapture -R` | 不行（沒有 macOS） |

Linux 那條在這裡是真的跑得起來的，所以「框選範圍換算、擷取、驗證結果、
錯誤處理」這一整條路**在開發環境就驗得到**——只有 Windows 那一段的
`ctypes` 呼叫沒辦法。這比整個模組都靠猜好得多。

**一律輸出 24 位元未壓縮 BMP**：三個平台都寫得出來（Windows 那邊我們自己
組檔頭，另外兩個由外部工具寫），tesseract 也讀得進去，而且格式簡單到可以
用純 Python 讀回像素——`looks_flat()` 就是靠這點做「整塊同一個顏色」的判
斷，那是**全螢幕獨佔模式的遊戲抓不到畫面**時最典型的樣子（抓回來全黑）。
沒有這個判斷的話，使用者會拿到一句「沒有讀到文字」，卻不知道真正的原因是
遊戲模式。
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys

DEFAULT_SCREENCAP = {
    # 小於這個邊長的框選視為誤觸（滑鼠點一下也會產生一個 1x1 的框）。
    "min_region_px": 8,
    # 框選面積上限；超過就擋下來並說明，不要讓使用者等到以為當掉。
    "max_region_pixels": 16_000_000,
    # 判定「整塊同一個顏色」的容許值（0~255）。JPEG 之類的雜訊會讓全黑
    # 畫面不是精確的 0，留一點餘裕。
    "flat_tolerance": 3,
}

# 擷取逾時；正常情形都在一秒內。
_TIMEOUT = 30


class CaptureError(RuntimeError):
    """擷取失敗；訊息一律寫成看得懂、而且講得出下一步的話。"""


def _clamp(value, low, high):
    return max(low, min(high, value))


def resolve_screencap_settings(config=None):
    """取出本模組的設定，缺漏補預設值並夾到合理範圍。"""
    raw = dict(DEFAULT_SCREENCAP)
    if config:
        raw.update({k: v for k, v in (config.get("screencap") or {}).items()
                    if k in DEFAULT_SCREENCAP})
    return {
        "min_region_px": int(_clamp(int(raw["min_region_px"]), 1, 200)),
        "max_region_pixels": int(_clamp(int(raw["max_region_pixels"]),
                                        10_000, 200_000_000)),
        "flat_tolerance": int(_clamp(int(raw["flat_tolerance"]), 0, 64)),
    }


# ----------------------------------------------------------------------
# 框選範圍（純算式，可離線測）
# ----------------------------------------------------------------------
def normalize_region(x0, y0, x1, y1):
    """
    把「按下去的點」與「放開的點」換成 (left, top, width, height)。

    使用者往哪個方向拖都要成立——由右下往左上拖是很自然的動作，沒有處理
    的話會得到負的寬高，後面每一步都會錯。
    """
    left, right = sorted((int(x0), int(x1)))
    top, bottom = sorted((int(y0), int(y1)))
    return left, top, right - left, bottom - top


def clamp_region(region, bounds):
    """把框選範圍夾進螢幕範圍內（拖出畫面邊緣是常事）。"""
    left, top, width, height = region
    bleft, btop, bwidth, bheight = bounds
    new_left = _clamp(left, bleft, bleft + bwidth)
    new_top = _clamp(top, btop, btop + bheight)
    new_right = _clamp(left + width, bleft, bleft + bwidth)
    new_bottom = _clamp(top + height, btop, btop + bheight)
    return new_left, new_top, new_right - new_left, new_bottom - new_top


def validate_region(region, config=None):
    """框選範圍能不能用；不能用就拋出講得出原因的 CaptureError。"""
    settings = resolve_screencap_settings(config)
    _, _, width, height = region
    if width < settings["min_region_px"] or height < settings["min_region_px"]:
        raise CaptureError(
            "框選的範圍太小了（可能只是點了一下）。按住滑鼠左鍵拖出一塊"
            "包含文字的區域再放開。")
    if width * height > settings["max_region_pixels"]:
        raise CaptureError(
            "框選的範圍太大，辨識會很慢。只框要讀的那幾行會又快又準。")
    return True


def scale_region(region, factor):
    """
    高 DPI 換算：把邏輯座標換成實際像素座標。

    Windows 在 125%／150% 縮放下，Tk 回報的座標與實際像素差一個倍率，
    不換算就會抓錯位置。**這一項在開發環境驗不到**（沒有 Windows），所以
    換算本身寫成純算式、單獨測，真正的倍率由呼叫端提供。
    """
    if not factor or factor == 1:
        return tuple(int(v) for v in region)
    return tuple(int(round(v * factor)) for v in region)


# GetDeviceCaps 的索引：HORZRES 是「本程式看到的」寬度，DESKTOPHORZRES
# 是螢幕實際的像素寬度。
_HORZRES = 8
_DESKTOPHORZRES = 118
# 超出這個範圍的倍率視為讀值有問題（Windows 的縮放最高 500%，但讀到比
# 1 小或大得離譜的值，比較可能是驅動回報怪數字），寧可不換算。
_DPI_FACTOR_RANGE = (1.0, 5.0)


def dpi_factor(physical_width, logical_width):
    """
    從「實際像素寬度／本程式看到的寬度」算出高 DPI 倍率。

    本程式沒有宣告自己支援高 DPI，所以在 125%／150% 縮放下 Windows 會給
    它一套縮小過的座標：Tk 回報的框選位置是邏輯座標，但對整個螢幕做
    `BitBlt` 用的是實際像素——不換算就會抓到左上方偏移的一塊（Pillow 的
    螢幕截圖在同樣情況下只抓到畫面的一部分，是同一件事）。

    讀不到、或讀到不合理的值時回傳 1（不換算）：換算錯比不換算更糟。
    **這一項在開發環境驗不到**（沒有 Windows），算式本身單獨測。
    """
    try:
        physical, logical = float(physical_width), float(logical_width)
    except (TypeError, ValueError):
        return 1.0
    if physical <= 0 or logical <= 0:
        return 1.0
    factor = physical / logical
    low, high = _DPI_FACTOR_RANGE
    if factor < low or factor > high:
        return 1.0
    return round(factor, 4)


# ----------------------------------------------------------------------
# BMP：寫得出、也讀得回（零第三方依賴）
# ----------------------------------------------------------------------
def write_bmp(path, width, height, bgr_rows):
    """
    寫一個 24 位元未壓縮 BMP。``bgr_rows`` 由上而下、每列是 BGR 位元組。

    Windows 的 GDI 給的就是 BGR、由下而上，所以這裡的列順序寫成由上而下
    之後要反過來存（BMP 的預設就是由下而上）。
    """
    row_padding = (4 - (width * 3) % 4) % 4
    row_bytes = width * 3 + row_padding
    pixel_bytes = row_bytes * height
    header = struct.pack("<2sIHHI", b"BM", 14 + 40 + pixel_bytes, 0, 0, 54)
    info = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0,
                       pixel_bytes, 2835, 2835, 0, 0)
    with open(path, "wb") as handle:
        handle.write(header)
        handle.write(info)
        pad = b"\0" * row_padding
        for row in reversed(bgr_rows):      # BMP 由下而上
            handle.write(row)
            if row_padding:
                handle.write(pad)


def read_bmp_samples(path, step=7):
    """
    從 BMP 取樣一些像素（每 step 個取一個），回傳 (b, g, r) 清單。

    只為了判斷「整塊是不是同一個顏色」，不需要完整解碼，所以用取樣而不是
    全讀——一塊 1920x1080 全讀是六百萬個像素，取樣夠用又快得多。
    """
    try:
        with open(path, "rb") as handle:
            head = handle.read(54)
            if len(head) < 54 or head[:2] != b"BM":
                return []
            offset = struct.unpack("<I", head[10:14])[0]
            width, height = struct.unpack("<ii", head[18:26])
            bits = struct.unpack("<H", head[28:30])[0]
            if bits != 24:
                return []
            handle.seek(offset)
            data = handle.read()
    except OSError:
        return []
    height = abs(height)
    row_bytes = width * 3 + (4 - (width * 3) % 4) % 4
    samples = []
    for y in range(0, height, max(1, step)):
        base = y * row_bytes
        for x in range(0, width, max(1, step)):
            start = base + x * 3
            if start + 3 <= len(data):
                samples.append(tuple(data[start:start + 3]))
    return samples


def looks_flat(path, config=None):
    """
    整塊畫面是不是同一個顏色（抓回來全黑／全白）。

    這是**全螢幕獨佔模式的遊戲抓不到畫面**時最典型的樣子。沒有這個判斷的
    話，使用者只會拿到一句「沒有讀到文字」，完全不知道真正的原因是遊戲的
    顯示模式——而那件事他自己改得掉。
    """
    settings = resolve_screencap_settings(config)
    samples = read_bmp_samples(path)
    if not samples:
        return False
    for channel in range(3):
        values = [s[channel] for s in samples]
        if max(values) - min(values) > settings["flat_tolerance"]:
            return False
    return True


# ----------------------------------------------------------------------
# 各平台的擷取
# ----------------------------------------------------------------------
def capture_backend():
    """回傳 (代號, 這台機器上可不可用)。"""
    if sys.platform == "win32":
        return "windows-gdi", True
    if sys.platform == "darwin":
        return "macos-screencapture", bool(shutil.which("screencapture"))
    available = bool(shutil.which("import")) or bool(shutil.which("ffmpeg"))
    return "linux-x11", available


def describe_backend():
    """一句話說明擷取走哪一條路（給記錄與錯誤訊息用）。"""
    name, ok = capture_backend()
    labels = {"windows-gdi": "Windows 內建繪圖介面",
              "macos-screencapture": "macOS 內建擷取",
              "linux-x11": "X11 擷取"}
    return f"{labels.get(name, name)}（{'可用' if ok else '不可用'}）"


def _capture_windows(region, out_path):
    """
    Windows：`ctypes` 直接叫 GDI，零第三方依賴。

    **開發環境無法實測**（沒有 Windows）。每一個可能失敗的呼叫都檢查回
    傳值並換成看得懂的訊息，而不是讓 ctypes 丟出一個沒頭沒尾的錯誤。
    """
    import ctypes
    from ctypes import wintypes

    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    screen_dc = user32.GetDC(None)
    if not screen_dc:
        raise CaptureError("取不到螢幕畫面（系統拒絕存取）。請改用視窗化"
                           "或無邊框模式再試一次。")
    # 框選座標是 Tk 給的邏輯座標，BitBlt 要的是實際像素（見 dpi_factor）。
    factor = dpi_factor(gdi32.GetDeviceCaps(screen_dc, _DESKTOPHORZRES),
                        gdi32.GetDeviceCaps(screen_dc, _HORZRES))
    left, top, width, height = scale_region(region, factor)
    mem_dc = bitmap = None
    try:
        mem_dc = gdi32.CreateCompatibleDC(screen_dc)
        bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
        if not mem_dc or not bitmap:
            raise CaptureError("建立擷取用的畫布失敗（系統資源不足）。")
        gdi32.SelectObject(mem_dc, bitmap)
        srccopy = 0x00CC0020
        if not gdi32.BitBlt(mem_dc, 0, 0, width, height,
                            screen_dc, left, top, srccopy):
            raise CaptureError(
                "抓不到這個畫面。全螢幕獨佔模式的遊戲不允許被擷取——"
                "把遊戲改成「視窗化」或「無邊框視窗」再試一次。")

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD),
                        ("biWidth", ctypes.c_long),
                        ("biHeight", ctypes.c_long),
                        ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD),
                        ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", ctypes.c_long),
                        ("biYPelsPerMeter", ctypes.c_long),
                        ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", BITMAPINFOHEADER),
                        ("bmiColors", wintypes.DWORD * 3)]

        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        # 負的高度＝由上而下，省得自己翻轉。
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 24
        info.bmiHeader.biCompression = 0

        row_bytes = width * 3 + (4 - (width * 3) % 4) % 4
        buffer = ctypes.create_string_buffer(row_bytes * height)
        if not gdi32.GetDIBits(mem_dc, bitmap, 0, height, buffer,
                               ctypes.byref(info), 0):
            raise CaptureError("讀取擷取結果失敗，請再試一次。")
        rows = [bytes(buffer[y * row_bytes:y * row_bytes + width * 3])
                for y in range(height)]
        write_bmp(out_path, width, height, rows)
    finally:
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if mem_dc:
            gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)
    return out_path


def _capture_linux(region, out_path):
    """Linux：先用 ImageMagick 的 `import`，不在就退到 ffmpeg 的 x11grab。"""
    left, top, width, height = region
    display = os.environ.get("DISPLAY", ":0")
    if shutil.which("import"):
        cmd = ["import", "-window", "root", "-crop",
               f"{width}x{height}+{left}+{top}", "+repage",
               f"BMP3:{out_path}"]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as exc:
            raise CaptureError(f"擷取畫面失敗（{exc}）。") from exc
        if proc.returncode == 0 and os.path.isfile(out_path):
            return out_path
    if shutil.which("ffmpeg"):
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "x11grab", "-video_size", f"{width}x{height}",
               "-i", f"{display}+{left},{top}", "-frames:v", "1",
               "-pix_fmt", "bgr24", out_path]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as exc:
            raise CaptureError(f"擷取畫面失敗（{exc}）。") from exc
        if proc.returncode == 0 and os.path.isfile(out_path):
            return out_path
    raise CaptureError(
        "這個系統上找不到可用的螢幕擷取工具（需要 ImageMagick 或 ffmpeg）。")


def _capture_macos(region, out_path):
    """macOS：內建的 screencapture。**開發環境無法實測**。"""
    left, top, width, height = region
    cmd = ["screencapture", "-x", "-t", "bmp",
           "-R", f"{left},{top},{width},{height}", out_path]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CaptureError(f"擷取畫面失敗（{exc}）。") from exc
    if proc.returncode != 0 or not os.path.isfile(out_path):
        raise CaptureError(
            "擷取畫面失敗。macOS 需要在「系統設定 → 隱私權與安全性 → "
            "螢幕錄製」允許本程式。")
    return out_path


def capture_region(region, out_path, config=None, bounds=None):
    """
    擷取一塊畫面到 ``out_path``（BMP），回傳該路徑。

    只做這一件事，而且只在被呼叫時做一次——本模組沒有任何定時器。
    """
    if bounds:
        region = clamp_region(region, bounds)
    validate_region(region, config)
    name, available = capture_backend()
    if not available:
        raise CaptureError(
            f"這個系統上沒有可用的螢幕擷取方式（{describe_backend()}）。")
    folder = os.path.dirname(os.path.abspath(out_path))
    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    if name == "windows-gdi":
        _capture_windows(region, out_path)
    elif name == "macos-screencapture":
        _capture_macos(region, out_path)
    else:
        _capture_linux(region, out_path)
    if not os.path.isfile(out_path) or os.path.getsize(out_path) < 64:
        raise CaptureError("擷取結果是空的，請再試一次。")
    if looks_flat(out_path, config):
        raise CaptureError(
            "抓到的畫面整塊都是同一個顏色，通常表示那個視窗不允許被擷取"
            "——全螢幕獨佔模式的遊戲就是這樣。把它改成「視窗化」或"
            "「無邊框視窗」再試一次。")
    return out_path
