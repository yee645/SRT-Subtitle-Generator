# -*- coding: utf-8 -*-
"""
Qt 版的首次啟動導覽（3.0 第 11 項第三十五階段，第 19 列（五））。

一般版的「新版介面速覽」（`gui/whatsnew_dialog.py`）是給 1.x 老用戶看「按鈕搬到哪」的對照表。Qt 版要回答的是同一
個問題，換一個起點：**用慣一般版的人，第一次打開 Qt 版**——

1. 這一版多了什麼（一般版做不到、換了 Qt 才有的）。
2. 一般版的東西在 Qt 版的哪裡（照使用者最可能先找的順序排）。
3. 還跟一般版不一樣的地方（照實講）。

預覽版（3.0 之前）與正式版（3.0.0 起）各一套開頭與第 3 段，呼叫端傳 APP_VERSION 挑（3.0 第 12 項 12-6）。

規則跟一般版一樣：看過這一版的導覽、或勾過「不再顯示」就不跳；記在設定的 `qt_guide_seen`（**不跟一般版的
`whatsnew_seen` 共用**：兩個版本的導覽講的是不同的東西，看過一個不代表看過另一個）。導覽內容大改時把
`GUIDE_VERSION` 往上加，看過舊版導覽的人會再看到一次；勾過「不再顯示」的永遠不跳。

零 GUI 依賴、不 import config。
"""
from __future__ import annotations

# 預覽版（APP_VERSION 3.0 之前）與正式版（3.0.0 起）各一套說法；呼叫端傳 APP_VERSION 進來挑（`is_formal`）。
# 不 import updater：這裡零依賴，版本由 gui_qt 傳。3.0.0 發版時 APP_VERSION 一改，標題、狀態列、導覽一起換成正式版。
GUIDE_VERSION = "3.0-preview-2"   # 預覽版的導覽（-2：12-3 起會自動更新，「還不能自動更新」那條改掉了）
FORMAL_GUIDE_VERSION = "3.0"      # 正式版的導覽：看過預覽版導覽的人，升到 3.0 會再看到一次
FORMAL_FROM = (3, 0, 0)
NEVER_SHOW = "never"
CONFIG_KEY = "qt_guide_seen"

INTRO = ("這是 3.0 預覽版（Qt 介面）。四個頁籤的順序跟一般版一樣：\n"
         "① 素材與剪輯 → ② 字幕 → ③ 健檢中心 → ④ 輸出與發佈。\n"
         "兩個版本讀同一份設定檔；一般版的功能都已經搬過來，下面先講多了什麼，再講東西在哪。")
FORMAL_INTRO = ("歡迎使用 3.0 的新介面。四個頁籤的順序跟一般版一樣：\n"
                "① 素材與剪輯 → ② 字幕 → ③ 健檢中心 → ④ 輸出與發佈。\n"
                "一般版的功能都搬過來了，下面先講多了什麼，再講東西在哪。")

# (標題, 說明)：換了 Qt 才做得到的
NEW_IN_QT = [
    ("字幕疊在真的影片畫面上",
     "②的播放器邊播邊看字幕，字型、大小、位置跟燒錄出來的一樣；改樣式立刻看得到。"),
    ("時間軸",
     "縮圖、波形、字幕塊排成一條：拖字幕塊的左右邊改時間、整句拖、←／→ 微調，都能復原。"),
    ("剪點看得見",
     "剪停頓、剪重複、審片建議會剪掉哪幾段直接畫在時間軸上：可以單獨停用、拖邊調範圍、播放時預覽剪後。"),
    ("多段素材與多軌",
     "時間軸上加畫面（B-roll、圖片）與音樂，拖位置、修頭尾；接縫可以溶接或黑場；跟剪點一起輸出。"),
    ("畫面調整即時預覽",
     "亮度、對比、飽和度、裁切，調了播放器上馬上看得到。"),
    ("專案檔",
     "整條時間軸（剪點、素材、樣式）存成 .srtproj，下次打開接著做。"),
]

# (一般版在哪, Qt 版在哪)：照用慣一般版的人最可能先找的順序
WHERE = [
    ("左欄「轉寫設定」（模型、OpenAI 金鑰、提示詞）", "頁籤列右上角〔轉寫與金鑰…〕；生成字幕視窗裡也有〔轉寫設定…〕"),
    ("左欄「斷句設定」＋右邊「習慣設定（樣式組合）」＋「字幕視覺調整」", "②〔字幕樣式…〕：三塊放在同一個視窗"),
    ("〔開始生成字幕〕", "②播放器上方〔生成字幕…〕"),
    ("字幕清單、逐句修字、尋找取代、翻譯", "②右邊的逐句校對"),
    ("尋找取代視窗下面的「自動修正詞庫」", "②〔尋找取代〕展開後的〔存為自動修正〕〔自動修正詞庫…〕"),
    ("〔匯入字幕〕", "②播放器上方〔載入字幕〕"),
    ("剪停頓、剪重複片段", "②時間軸上方的「剪點」選單選「停頓跳剪」或「重複片段」（看得到剪哪裡，再〔照剪點輸出…〕）"),
    ("審片助手、音訊轉影片、批次一鍵完成", "①素材與剪輯（審片助手就是這一頁本身）"),
    ("健檢中心、系列一致性", "③健檢中心（系列一致性在封面圖下面）"),
    ("匯出、燒錄、〔完成輸出〕、品牌套版", "④輸出與發佈"),
    ("配樂助手", "②時間軸加入音樂後，選取音樂軌按〔配樂設定…〕"),
    ("即時查譯、框選螢幕翻譯", "頁籤列右上角〔即時查譯…〕"),
    ("ffmpeg／文字辨識的一鍵安裝", "缺 ffmpeg 時主視窗上方的提示列；文字辨識在框選翻譯時會問"),
    ("〔切換為深色／淺色〕", "狀態列右邊"),
    ("「新版介面速覽」", "狀態列右邊〔新介面導覽…〕（就是這一頁，隨時可以再打開）"),
]

UPDATE_NOTE = ("更新：有新版時頁籤上方會出現提示。打包好的 Windows 版按〔下載並安裝〕，準備好之後關掉程式時自動換上"
               "新版並重新開啟，設定、生字本與一鍵安裝的工具會一起帶過去；從原始碼跑的照提示到下載頁。")

# 還跟一般版不一樣的地方（照實講）
DIFFERENT = [
    UPDATE_NOTE,
    "設定在關掉 Qt 版時才存回 config.json（只存這次改過的部分，一般版同時開著也不會互相蓋掉）。",
    "這是預覽版：遇到問題可以隨時改用一般版（直接執行、不加 --qt），兩邊讀同一份設定與專案。",
]
FORMAL_DIFFERENT = [
    UPDATE_NOTE,
    "設定在關掉程式時才存回 config.json（只存這次改過的部分，一般版同時開著也不會互相蓋掉）。",
    "一般版照樣能用、隨時可以回去：打包版是 SRT-Subtitle-Generator.exe（從原始碼跑是 python main.py --tk）。"
    "從一般版裝新介面時，設定是複製一份過來的，之後兩邊各自一份。",
]
DIFFERENT_TITLE = "【還跟一般版不一樣的地方】"
FORMAL_DIFFERENT_TITLE = "【跟一般版不一樣的地方】"


def _version_tuple(text) -> tuple:
    text = str(text or "").strip().lstrip("vV")
    parts = []
    for piece in text.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)


def is_formal(app_version=None) -> bool:
    """這一版是不是 3.0 正式版（3.0.0 起）；沒給或看不懂當預覽版（保守，跟打包的 zip 名稱同一條規則）。"""
    return app_version is not None and _version_tuple(app_version) >= FORMAL_FROM


def guide_version(app_version=None) -> str:
    return FORMAL_GUIDE_VERSION if is_formal(app_version) else GUIDE_VERSION


def should_show(seen, app_version=None) -> bool:
    """啟動時要不要跳導覽：看過這一版的導覽、或勾過「不再顯示」就不跳。"""
    seen = str(seen or "").strip()
    return seen not in (NEVER_SHOW, guide_version(app_version))


def remember(never, app_version=None) -> str:
    """關掉導覽時寫進設定的值：勾了「不再顯示」是永久，沒勾是「看過這一版」。"""
    return NEVER_SHOW if never else guide_version(app_version)


def body_text(app_version=None) -> str:
    """導覽全文（純文字，測試直接驗）。"""
    formal = is_formal(app_version)
    lines = [FORMAL_INTRO if formal else INTRO, "", "【這一版多了什麼】", ""]
    for title, detail in NEW_IN_QT:
        lines.append(f"　◆ {title}")
        lines.append(f"　　{detail}")
        lines.append("")
    lines += ["【一般版的東西在哪裡】", ""]
    for old, new in WHERE:
        lines.append(f"　{old}")
        lines.append(f"　　→ {new}")
    lines += ["", FORMAL_DIFFERENT_TITLE if formal else DIFFERENT_TITLE, ""]
    for item in (FORMAL_DIFFERENT if formal else DIFFERENT):
        lines.append(f"　・{item}")
    return "\n".join(lines)
