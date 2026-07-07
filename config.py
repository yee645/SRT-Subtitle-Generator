# -*- coding: utf-8 -*-
"""
設定檔管理模組。

負責將使用者調整的字幕樣式、轉寫參數與斷句參數儲存至本地 config.json，
並於程式啟動時自動載入，達成「記憶功能」。

config.json 同時保存多組「習慣設定（preset）」，每組包含字幕樣式與斷句參數，
使用者可於介面上隨時切換、新增、更新或刪除。
"""

import json
import os

# 設定檔路徑採用相對路徑，存放於專案根目錄。
CONFIG_PATH = "config.json"

# 預設字幕樣式。
_DEFAULT_STYLE = {
    "position_x": 0.5,        # 水平位置，0.0 最左、1.0 最右
    "position_y": 0.88,       # 垂直位置，0.0 最上、1.0 最下
    "font_family": "Microsoft JhengHei",
    "font_size": 26,          # 字型大小（點）
    "text_color": "#FFFFFF",  # 文字顏色
    "stroke_color": "#000000",# 邊框（描邊）顏色
    "stroke_width": 2,        # 邊框寬度（像素）
}

# 預設斷句參數。
_DEFAULT_SEGMENTATION = {
    "max_chars_cjk": 18,      # 中文等全形文字單行最大字數
    "max_chars_latin": 45,    # 英文等半形文字單行最大字數
    "min_duration": 1.0,      # 單句字幕最短秒數
    "max_duration": 7.0,      # 單句字幕最長秒數
    "pause_gap": 0.5,         # 視為「停頓」的最短靜音秒數
    "time_offset": 0.0,       # 時間軸整體偏移秒數（正值延後、負值提前）
}

# 預設設定。實際載入時會與使用者設定做深層合併，避免新版本新增欄位後讀不到值。
DEFAULT_CONFIG = {
    # 介面外觀主題：'light' 或 'dark'，預設為 light。
    "theme": "light",
    # 目前作用中的字幕樣式與斷句設定（記憶功能保存的即時狀態）。
    "subtitle_style": dict(_DEFAULT_STYLE),
    "segmentation": dict(_DEFAULT_SEGMENTATION),
    # 語音轉寫相關設定。
    "transcription": {
        "model": "base",          # 本地 Whisper 模型：tiny/base/small/medium/large
        "language": "auto",       # 語言代碼，auto 表示自動偵測
        "use_api": False,         # 是否改用 OpenAI API 進行轉寫
        "api_key": "",            # OpenAI API 金鑰（使用 API 模式時填入）
        "python_path": "",        # 外部 Python 直譯器路徑（供 exe 使用自備的 whisper）
        "prompt": "",             # 轉寫提示詞：可填入專有名詞、人名、常見錯字導正
    },
    # 已儲存的習慣設定，每組包含一份字幕樣式與斷句參數。
    "presets": {
        "預設": {
            "subtitle_style": dict(_DEFAULT_STYLE),
            "segmentation": dict(_DEFAULT_SEGMENTATION),
        },
    },
    # 目前選用的習慣設定名稱。
    "active_preset": "預設",
    # 一鍵自動化輸出設定（「一鍵完成」與 CLI 批次模式共用）。
    "automation": {
        "export_srt": True,       # 自動匯出 SRT
        "export_vtt": False,      # 自動匯出 VTT
        "export_ass": False,      # 自動匯出 ASS
        "export_txt": False,      # 自動匯出 TXT
        "burn_video": False,      # 自動燒錄硬字幕影片
        "output_dir": "",         # 輸出資料夾；留空表示與來源檔相同資料夾
    },
    # 其他狀態。
    "last_dir": "",               # 上次開啟檔案的目錄
}


def _deep_merge(base, override):
    """將 override 的內容深層合併進 base 的複本並回傳（不修改原物件，符合不可變原則）。"""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def make_profile(subtitle_style, segmentation):
    """把一份字幕樣式與斷句參數打包成一組習慣設定（preset）。"""
    return {
        "subtitle_style": dict(subtitle_style),
        "segmentation": dict(segmentation),
    }


def load_config():
    """載入設定檔；若檔案不存在或損毀，回傳預設設定的複本。"""
    if not os.path.exists(CONFIG_PATH):
        return _deep_merge(DEFAULT_CONFIG, {})
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fp:
            user_config = json.load(fp)
        if not isinstance(user_config, dict):
            raise ValueError("設定檔格式錯誤")
    except (json.JSONDecodeError, ValueError, OSError):
        # 設定檔毀損時不中斷程式，改用預設值。
        return _deep_merge(DEFAULT_CONFIG, {})

    # 以預設設定為基底，套上使用者設定，確保缺漏欄位有預設值。
    merged = _deep_merge(DEFAULT_CONFIG, user_config)

    # 相容處理：舊版設定檔沒有 presets 時，以目前樣式建立「預設」習慣設定。
    if "presets" not in user_config or not isinstance(user_config.get("presets"), dict):
        merged["presets"] = {
            "預設": make_profile(merged["subtitle_style"], merged["segmentation"]),
        }
        merged["active_preset"] = "預設"

    # 確保至少有一組習慣設定，且 active_preset 指向存在的名稱。
    if not merged["presets"]:
        merged["presets"] = {
            "預設": make_profile(merged["subtitle_style"], merged["segmentation"]),
        }
    if merged.get("active_preset") not in merged["presets"]:
        merged["active_preset"] = sorted(merged["presets"].keys())[0]

    return merged


def save_config(config):
    """將設定寫回 config.json。發生 I/O 錯誤時拋出例外由呼叫端處理。"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as fp:
        json.dump(config, fp, ensure_ascii=False, indent=2)
