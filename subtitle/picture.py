# -*- coding: utf-8 -*-
"""
3.0 第 9 項：畫面調整——亮度、對比、飽和度、裁切、旋轉、翻轉。

一份調整是單純的 dict（可以直接存進時間軸／專案檔）：

* `brightness`：亮度 −1～1，0＝不變（ffmpeg `eq` 的 brightness，加在每個像素上）。
* `contrast`：對比 0～2，1＝不變。
* `saturation`：飽和度 0～3，1＝不變，0＝黑白。
* `crop`：裁切 `[x, y, w, h]`，原畫面的 0～1 比例，省略＝不裁。寬高至少 `MIN_CROP`。
* `rotate`：順時針轉 0／90／180／270 度。
* `flip_h`／`flip_v`：左右／上下翻轉（轉完之後的方向）。

順序固定：先裁（在原畫面上框）、再轉、再翻、最後調色。`filters` 回傳 ffmpeg 濾鏡鏈；裁切
用 `iw`／`ih` 的算式寫（不必先量畫面大小），寬高取偶數。`crop_box`／`output_size` 用同一
套算法給介面算（預覽的框、輸出的畫面比例）。

零 GUI 依賴。
"""
from __future__ import annotations

DEFAULTS = {"brightness": 0.0, "contrast": 1.0, "saturation": 1.0, "crop": [0.0, 0.0, 1.0, 1.0],
            "rotate": 0, "flip_h": False, "flip_v": False}
RANGES = {"brightness": (-1.0, 1.0, "亮度"), "contrast": (0.0, 2.0, "對比"), "saturation": (0.0, 3.0, "飽和度")}
ROTATIONS = (0, 90, 180, 270)
MIN_CROP = 0.05   # 裁切後至少留原畫面的 5%（再小就只剩幾個像素）
_EPS = 1e-6


class PictureError(ValueError):
    """畫面調整的參數不合理。"""


def _number(value, label, where):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise PictureError(f"{where}的{label}不是數字：{value!r}") from None
    if value != value or value in (float("inf"), float("-inf")):
        raise PictureError(f"{where}的{label}不是有限的數字")
    return value


def normalize(adjust, where="畫面調整") -> dict:
    """檢查並補齊預設值，回傳新的 dict（不改原本的）。不合理就拋 PictureError，說哪一項怎麼不對。"""
    if adjust is None:
        return dict(DEFAULTS, crop=list(DEFAULTS["crop"]))
    if not isinstance(adjust, dict):
        raise PictureError(f"{where}要是 dict")
    unknown = sorted(set(adjust) - set(DEFAULTS))
    if unknown:
        raise PictureError(f"{where}有不認得的項目：{'、'.join(unknown)}")
    out = dict(DEFAULTS, crop=list(DEFAULTS["crop"]))
    for key, (low, high, label) in RANGES.items():
        if key in adjust:
            value = round(_number(adjust[key], label, where), 3)
            if not low <= value <= high:
                raise PictureError(f"{where}的{label}要在 {low:g}～{high:g} 之間（現在是 {value:g}）")
            out[key] = value
    if adjust.get("crop") is not None:
        try:
            crop = [float(v) for v in adjust["crop"]]
        except (TypeError, ValueError):
            raise PictureError(f"{where}的裁切要是四個數字 [x, y, w, h]") from None
        if len(crop) != 4 or any(v != v for v in crop):
            raise PictureError(f"{where}的裁切要是四個數字 [x, y, w, h]")
        x, y, w, h = crop
        if w < MIN_CROP - _EPS or h < MIN_CROP - _EPS:
            raise PictureError(f"{where}的裁切太小：寬高至少要留原畫面的 {MIN_CROP:.0%}")
        if x < -_EPS or y < -_EPS or x + w > 1 + 1e-4 or y + h > 1 + 1e-4:
            raise PictureError(f"{where}的裁切要在畫面裡（0～1 的比例，[x, y, w, h]）")
        out["crop"] = [round(min(max(v, 0.0), 1.0), 4) for v in crop]
    if "rotate" in adjust:
        rotate = adjust["rotate"]
        try:
            rotate = int(rotate) % 360 if float(rotate) == int(rotate) else None
        except (TypeError, ValueError):
            rotate = None
        if rotate not in ROTATIONS:
            raise PictureError(f"{where}的旋轉只能是 0／90／180／270 度（現在是 {adjust['rotate']!r}）")
        out["rotate"] = rotate
    for key in ("flip_h", "flip_v"):
        if key in adjust:
            out[key] = bool(adjust[key])
    return out


def is_identity(adjust) -> bool:
    """這份調整等於什麼都不做（不必加濾鏡）。"""
    return normalize(adjust) == normalize(None)


def changes(adjust) -> dict:
    """只留跟預設不一樣的項目（存檔用：沒改的不寫）。"""
    full = normalize(adjust)
    return {k: v for k, v in full.items() if v != DEFAULTS[k]}


def _even(expr):
    return f"trunc({expr}/2)*2"


def filters(adjust) -> list:
    """ffmpeg 濾鏡鏈（照「裁 → 轉 → 翻 → 調色」的順序）；什麼都不做時回傳空清單。"""
    adj = normalize(adjust)
    out = []
    x, y, w, h = adj["crop"]
    if adj["crop"] != DEFAULTS["crop"]:
        out.append(f"crop=w={_even(f'iw*{w:g}')}:h={_even(f'ih*{h:g}')}:"
                   f"x=trunc(iw*{x:g}):y=trunc(ih*{y:g})")
    out.extend({90: ["transpose=clock"], 180: ["hflip", "vflip"], 270: ["transpose=cclock"]}.get(adj["rotate"], []))
    if adj["flip_h"]:
        out.append("hflip")
    if adj["flip_v"]:
        out.append("vflip")
    if (adj["brightness"], adj["contrast"], adj["saturation"]) != (0.0, 1.0, 1.0):
        out.append(f"eq=brightness={adj['brightness']:g}:contrast={adj['contrast']:g}:"
                   f"saturation={adj['saturation']:g}")
    return out


def crop_box(adjust, width: int, height: int) -> tuple:
    """在 width×height 的原畫面上裁哪一塊：(x, y, 寬, 高) 像素，跟 `filters` 的算式一樣取整。"""
    x, y, w, h = normalize(adjust)["crop"]
    cw, ch = int(width * w / 2) * 2, int(height * h / 2) * 2
    return int(width * x), int(height * y), max(cw, 2), max(ch, 2)


def output_size(adjust, width: int, height: int) -> tuple:
    """調整完的畫面多大：裁切之後，轉 90／270 度時寬高對調。"""
    _x, _y, cw, ch = crop_box(adjust, width, height)
    return (ch, cw) if normalize(adjust)["rotate"] in (90, 270) else (cw, ch)
