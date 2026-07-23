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
    "emphasis_enabled": False,      # 重點字上色（燒錄與 ASS 匯出時生效）
    "emphasis_color": "#FFD700",    # 重點字顏色（預設金黃）
    "emphasis_words": "",           # 重點字詞清單（逗號或空白分隔）
    # 逐字動態字幕（燒錄與 ASS 匯出時生效；需要逐字時間軸）：
    # off＝一般整句、karaoke＝整句顯示+講到的字換色、word＝只彈出當前字詞
    "dynamic_mode": "off",
}

# 預設審片偵測參數（審片助手用，皆可於介面調整並記憶）。
_DEFAULT_REVIEW = {
    "highlight_sensitivity": 1.0,  # 精彩判定敏感度倍率：<1 更嚴格、>1 更容易標記
    "extra_excite_words": "",      # 自訂情緒詞（逗號或空白分隔），附加於內建詞庫
    "filler_words": "呃嗯欸蛤齁",   # 口頭禪單字表（連寫，逐字比對）
    "silence_gap": 2.0,            # 視為「冷場」的最短無人聲秒數
    "segment_gap": 1.0,            # 講話段落切分的停頓秒數
    "take_similarity": 0.72,       # 重複拍攝判定的文字相似度（0~1）
    "filler_density": 0.08,        # 每字的填充詞密度達此值標記「口頭禪多」
    "chapter_min_seconds": 60.0,   # YouTube 章節的最短長度（秒），避免章節過細
    # 精彩訊號個別權重（0~3；0＝停用該訊號、1＝預設強度）。
    "weight_energy": 1.0,          # 音量能量
    "weight_pace": 1.0,            # 語速
    "weight_excite": 1.0,          # 情緒詞
    "weight_exclaim": 1.0,         # 驚嘆／疑問句
    "batch_top_n": 10,             # 多檔審片彙總取跨檔精彩片段前 N 段
    "voice_band": True,            # 音量分析聚焦人聲頻帶，降低背景音樂干擾
    "cut_filler_words": False,     # 粗剪/EDL 同時剪掉口頭禪字詞（呃、嗯…）
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
        "use_cache": True,        # 重用轉錄快取：同檔同設定免重跑語音辨識
    },
    # 審片助手的偵測參數（敏感度、詞表、門檻，介面可調）。
    "review": dict(_DEFAULT_REVIEW),
    # 自動修正詞庫：轉錄完成後自動套用的取代規則
    # （[{"find": 錯字, "replace": 正確字, "case": 是否區分大小寫}, ...]）。
    # 於「尋找取代」對話框按「存為自動修正」新增，修一次、每集自動修。
    "corrections": [],
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
        "loudnorm": False,        # 燒錄時同步做響度正規化
        "loudnorm_target": -14.0, # 目標響度（LUFS）；-14 為 YouTube 標準
        "output_dir": "",         # 輸出資料夾；留空表示與來源檔相同資料夾
    },
    # 發佈包設定：從審片結果組出建議標題／描述草稿／標籤。
    "publish": {
        "title_candidates": 3,    # 建議標題數量（2~6）
        "title_max_chars": 40,    # 標題長度上限（行動裝置可見長度，20~60）
        "tag_count": 15,          # 建議標籤數量（5~30）
    },
    # 背景音樂自動閃避設定（配樂助手用）：講話時自動壓低音樂音量。
    "ducking": {
        "music_volume": 0.35,       # 背景音樂基礎音量（混音前）
        "duck_strength": 8.0,       # 閃避強度：講話時音樂被壓低的程度
        "duck_sensitivity": 0.06,   # 閃避靈敏度：越低越容易被輕聲觸發
        "auto_sensitivity": True,   # 自動適應人聲音量（量測後自動算靈敏度）
    },
    # 封面候選擷取設定（審片助手用）：自動挑清晰畫面輸出 PNG 候選圖。
    "thumbnails": {
        "count": 6,               # 候選張數（2~12）
        "min_spacing": 8.0,       # 候選之間最小時間間隔（秒）
        "prefer_highlights": True,# 優先從精彩段落取樣
        "width": 1280,            # 輸出圖片寬度（YouTube 封面標準 1280）
    },
    # 音訊健檢門檻（上片前檢查爆音、音量、底噪與聲道平衡）。
    "audiocheck": {
        "quiet_lufs": -19.0,      # 響度低於此值（LUFS）判定太小聲
        "noise_floor_db": -50.0,  # 底噪高於此值（dB）判定偏高
        "clip_peak_db": -0.5,     # 峰值高於此值（dB）視為爆音風險
        "balance_db": 6.0,        # 左右聲道相差超過此值（dB）判定不平衡
    },
    # 影片畫質健檢與去頭尾（健檢視窗的畫質段落）。
    "videocheck": {
        "bitrate_margin": 1.0,     # 位元率門檻＝YouTube 建議值 × 此倍率
        "dead_air_db": -45.0,      # 視為「無聲」的音量門檻（dB）
        "head_max_seconds": 1.0,   # 開頭廢秒超過此長度即提醒修剪
        "tail_max_seconds": 1.5,   # 結尾廢秒超過此長度即提醒修剪
        "trim_pad": 0.25,          # 修剪保留的緩衝秒數
    },
    # 音訊修復設定（健檢視窗的一鍵修復）。
    "audiofix": {
        "denoise": True,            # FFT 頻譜降噪（afftdn）
        "denoise_strength": 12.0,   # 降噪量（dB，6~40）：過高人聲會發悶
        "highpass": True,           # 高通濾波去低頻隆隆（風切、震動）
        "highpass_hz": 80.0,        # 高通截止頻率（Hz，40~200）
        "loudnorm": False,          # 修復時同步做響度正規化
    },
    # mid-roll 廣告插入點建議（審片助手與發佈包用）。
    "adbreaks": {
        "min_spacing_minutes": 4.0, # 兩個廣告點的最小間隔（分鐘）
        "max_breaks": 6,            # 建議數量上限
        "min_pause": 1.2,           # 視為自然停頓的最短無人聲秒數
        "skip_head_minutes": 2.0,   # 影片開頭不放廣告的長度（分鐘）
        "skip_tail_minutes": 1.0,   # 影片結尾不放廣告的長度（分鐘）
    },
    # Shorts 直式短片輸出設定（審片助手用）。
    "shorts": {
        "mode": "crop",           # crop＝裁切；blur＝模糊背景填滿
        "focus_x": 0.5,           # 裁切版式水平焦點：0 最左、0.5 置中、1 最右
        "burn_subtitles": True,   # 短片是否燒錄字幕
        "loudnorm": False,        # 短片輸出時做響度正規化
    },
    # 品牌套版設定（片頭／片尾接續、浮水印疊加）。
    "branding": {
        "intro_path": "",
        "outro_path": "",
        "watermark_path": "",
        "watermark_position": "bottom_right",
        "watermark_opacity": 0.85,
        "watermark_scale": 0.15,
        "watermark_margin": 24,
    },
    # 字幕翻譯（雙語字幕）設定：金鑰沿用「轉寫設定」的 OpenAI API 金鑰。
    "translate": {
        "target_language": "en",  # 目標語言代碼（en/ja/ko/...）
        "mode": "bilingual",      # bilingual＝原文+譯文上下行；replace＝僅譯文
        "batch_size": 30,         # 每次 API 請求的句數
    },
    # 字幕健檢門檻（閱讀速度 CPS、顯示時間、行數與行長）。
    "subtitlecheck": {
        "cps_limit": 17.0,          # 每秒字元數超過此值標記「閱讀過快」
        "min_duration": 0.8,        # 顯示秒數低於此值標記「顯示過短」
        "max_lines": 2,             # 超過此行數標記「行數過多」
        "max_chars_per_line": 21,   # 單行字元數超過此值標記「單行過長」
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
