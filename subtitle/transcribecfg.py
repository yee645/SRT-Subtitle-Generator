# -*- coding: utf-8 -*-
"""
轉寫設定的規則（3.0 第 11 項第三十二階段：切預設前補的缺口）。

一般版左欄「轉寫設定」框（`gui/app.py` 的 `_build_transcription_section`／`_collect_transcription_config`）搬到 Qt
版時要一樣的整理規則：模型只能是那五個、語言空白就是自動偵測、文字欄去頭尾空白、兩個勾選是布林。這裡抽出來，
Qt 版用；一般版不改。

**金鑰**：OpenAI 的 API 金鑰跟一般版一樣存在這台電腦的 config.json（明文），Qt 版的轉寫、翻譯字幕、即時查譯
共用這一把。畫面上只顯示遮住的樣子（`mask_key`），要看全文得自己按〔顯示〕。

`sends_text` 講「這組設定下，生成字幕會送什麼出去」——本地 Whisper 什麼都不送；OpenAI 模式送聲音（有提示詞
時提示詞也送）、照用量收費。生成視窗開始前也會再講一次（`pipeline.generation_plan`）。

零 GUI 依賴、不 import config。
"""
from __future__ import annotations

MODELS = ("tiny", "base", "small", "medium", "large")
LANGUAGES = ("auto", "zh", "zh-TW", "en", "ja", "ko")  # 一般版下拉的選項（也可以自己打代碼）
DEFAULTS = {
    "model": "base",
    "language": "auto",
    "use_api": False,
    "api_key": "",
    "python_path": "",
    "prompt": "",
    "use_cache": True,
}
KEY_USES = "這把金鑰也用在翻譯字幕與即時查譯。"
KEY_STORED = "金鑰跟一般版一樣存在這台電腦的 config.json（沒有加密），不會送到 OpenAI 以外的地方。"


def clean_transcription(raw, base=None) -> dict:
    """
    整理成一份完整的轉寫設定（規則同一般版 `_collect_transcription_config`）。

    不認得的模型退回 `base` 裡的（沒有就 "base"）；語言空白＝"auto"；文字欄去頭尾空白；其他鍵原樣留著。
    """
    fallback = dict(DEFAULTS)
    fallback.update({k: v for k, v in (base or {}).items() if k in DEFAULTS})
    raw = dict(raw or {})
    out = dict(raw)
    model = str(raw.get("model", fallback["model"]) or "").strip()
    if model not in MODELS:
        model = fallback["model"] if fallback["model"] in MODELS else "base"
    out["model"] = model
    out["language"] = str(raw.get("language", fallback["language"]) or "").strip() or "auto"
    out["use_api"] = bool(raw.get("use_api", fallback["use_api"]))
    out["use_cache"] = bool(raw.get("use_cache", fallback["use_cache"]))
    for key in ("api_key", "python_path", "prompt"):
        out[key] = str(raw.get(key, fallback[key]) or "").strip()
    return out


def mask_key(key) -> str:
    """畫面上顯示金鑰的樣子：只露頭 3 個字與尾 4 個字；太短就只說幾個字。"""
    key = str(key or "").strip()
    if not key:
        return "（還沒填）"
    if len(key) <= 10:
        return f"已填（{len(key)} 個字）"
    return f"{key[:3]}…{key[-4:]}"


def sends_text(cfg) -> str:
    """這組設定下，生成字幕會送什麼出去（給設定視窗最下面那一行）。"""
    cfg = clean_transcription(cfg)
    if not cfg["use_api"]:
        return "用這台電腦上的 Whisper 辨識：聲音、字幕、提示詞都不會送出去。"
    what = "影片的聲音"
    if cfg["prompt"]:
        what += "與提示詞"
    text = f"用 OpenAI 轉寫：生成字幕時會把{what}送到 OpenAI，照用量收費；檔名、字幕與其他檔案不送。"
    if not cfg["api_key"]:
        text += "還沒有金鑰，填好才能用。"
    return text
