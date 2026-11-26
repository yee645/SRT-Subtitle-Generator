# -*- coding: utf-8 -*-
"""
剪輯器版面的介紹（剪輯器版面 E-7b，`docs/ROADMAP_EDITOR.md`）。

3.1 起新介面預設是剪輯器版面（單一工作區，照剪映專業版、Premiere 的排版）。用慣四頁籤的人第一次打開會看到這份介紹：

1. 版面長什麼樣（四個區塊各放什麼）。
2. 這一版多了什麼（四頁籤沒有的）。
3. 四頁籤的東西在剪輯器的哪裡。
4. 快捷鍵。
5. 想用回四頁籤：怎麼切（記在設定裡，下次開啟生效）。

規則跟 3.0 的導覽一樣（`subtitle/qtguide.py`）：看過這一版的介紹、或勾過「不再顯示」就不跳；記在設定的
`editor_guide_seen`（**不跟 `qt_guide_seen` 共用**：看過四頁籤的導覽不代表看過剪輯器的介紹）。內容大改時把
`GUIDE_VERSION` 往上加。

另外管「新介面開哪一種版面」：命令列 `--editor`／`--tabs` 優先，其次是設定的 `qt_layout`，都沒有就是剪輯器。

零 GUI 依賴、不 import config。
"""
from __future__ import annotations

GUIDE_VERSION = "3.1-editor"
NEVER_SHOW = "never"
CONFIG_KEY = "editor_guide_seen"

# 版面：設定的鍵與兩種值；命令列旗標
LAYOUT_KEY = "qt_layout"
EDITOR = "editor"
TABS = "tabs"
LAYOUTS = (EDITOR, TABS)
LAYOUT_NAMES = {EDITOR: "剪輯器版面", TABS: "四頁籤版面"}
DEFAULT_LAYOUT = EDITOR
EDITOR_FLAG = "--editor"
TABS_FLAG = "--tabs"

INTRO = ("歡迎使用剪輯器版面。素材、預覽、屬性、時間軸放在同一個畫面，不用在頁籤之間來回切：\n"
         "左邊選媒體、字幕、智慧剪輯、健檢；中間是預覽；右邊的屬性面板跟著你選的東西變；下面是時間軸；"
         "做好按右上角〔匯出〕。\n"
         "四頁籤的功能一個不少，只是換了位置——下面先講多了什麼，再講東西在哪。")

AREAS = [
    ("左邊", "圖示列切換四區：媒體（素材庫、開影片、載入字幕）、字幕（生成字幕、逐句校對）、"
             "智慧剪輯（審片助手）、健檢（18 項檢查、發佈文字、封面圖）。"),
    ("中間", "預覽：字幕疊在真的影片畫面上；下面是時間碼、上一格／播放／下一格、預覽放大、專注預覽。"),
    ("右邊", "屬性面板：什麼都沒選＝專案（主片段、剪點）；選一句字幕＝文字與開始／結束時間；"
             "選一段素材＝那段的屬性。"),
    ("下面", "時間軸：畫面、聲音、字幕、剪點、疊加、音樂六條軌；上面一列工具：復原、重做、存字幕、分割、"
             "刪除、吸附、縮放。"),
]

NEW_IN_EDITOR = [
    ("素材庫", "〔匯入素材…〕一次選好幾個影片、圖片、音樂，看縮圖與長度，再拖到時間軸上想放的那一條、那個時間。"),
    ("屬性面板跟著選取變", "選字幕直接改文字與時間（數字欄），選素材直接改它的屬性，不用另開小視窗。"),
    ("在播放頭分割", "〔分割〕或 Ctrl+B：選字幕切字幕，選素材切素材；都能復原。"),
    ("一個〔匯出〕搞定", "右上角〔匯出〕（Ctrl+E）一個對話框：完成輸出、照剪點輸出、輸出多軌、單獨匯出字幕檔、"
                       "多語字幕包、品牌套版。"),
    ("快捷鍵", "Space 播放、J／K／L 倒退／暫停／快轉、←／→ 逐格，跟主流剪輯軟體一樣。"),
    ("選單列與專注預覽", "上方選單列每一項都是畫面上的按鈕；〔專注預覽〕把左右面板收起來，預覽可以放大 2 倍、4 倍看細節。"),
]

# (四頁籤在哪, 剪輯器在哪)：照用慣四頁籤的人最可能先找的順序
WHERE = [
    ("②〔開啟影片〕〔載入字幕〕", "左邊「媒體」最上面（〔匯入素材…〕下面）；也在選單「檔案」"),
    ("②〔生成字幕…〕", "左邊「字幕」最上面"),
    ("②右邊的逐句校對（改文字、新增刪除、尋找取代、翻譯）", "左邊「字幕」；選一句之後，右邊屬性面板也能直接改"),
    ("②〔字幕樣式…〕", "左邊「字幕」，或選一句字幕後右邊屬性面板的〔字幕樣式…〕"),
    ("②播放器與時間軸", "中間預覽與下面時間軸（拖邊、整句拖、←／→ 微調照舊）"),
    ("②〔加入畫面…〕〔加入音樂…〕", "左邊「媒體」（照舊在；也可以用素材庫匯入後拖到時間軸，或選好按〔加到播放頭〕）"),
    ("②剪點選單、預覽剪後、接縫", "右邊屬性面板（什麼都沒選的時候）"),
    ("②〔畫面調整…〕〔編輯用代理檔〕", "右邊屬性面板（什麼都沒選的時候）"),
    ("②〔開專案〕〔存專案〕", "頂列專案名稱旁邊；也在選單「檔案」（存專案 Ctrl+Shift+S）"),
    ("①審片助手", "左邊「智慧剪輯」"),
    ("①〔音訊轉影片〕〔批次一鍵完成〕", "左邊「媒體」"),
    ("③健檢中心", "左邊「健檢」"),
    ("④輸出與發佈（完成輸出、單獨匯出、多語字幕包、品牌套版）", "右上角〔匯出〕"),
    ("②〔照剪點輸出…〕〔輸出多軌…〕", "右上角〔匯出〕的「影片」"),
    ("〔轉寫與金鑰…〕〔即時查譯…〕〔深淺色〕〔新介面導覽…〕", "頂列右邊的圖示按鈕；也在選單「說明」「檢視」"),
]

KEYS = [
    ("Space", "播放／暫停"),
    ("J／K／L", "倒退 1 秒／暫停／播放（再按 L 兩倍、四倍速）"),
    ("←／→", "上一格／下一格（選了字幕時照舊微調那句）"),
    ("Ctrl+B", "在播放頭分割"),
    ("Delete", "刪除選取"),
    ("Ctrl+Z／Ctrl+Shift+Z", "復原／重做"),
    ("Ctrl+=／Ctrl+-／Shift+Z", "時間軸拉近／拉遠／整支"),
    ("Ctrl+S／Ctrl+Shift+S", "存字幕／存專案"),
    ("Ctrl+E", "匯出"),
]

SWITCH_BACK = ("想用回四頁籤：狀態列右邊的〔改用四頁籤版面…〕（選單「檢視」也有），下次開啟就是四頁籤；四頁籤的狀態列有"
               "〔改用剪輯器版面…〕可以換回來。兩種版面是同一套功能、同一份設定與專案檔，隨時可以換。")


def should_show(seen) -> bool:
    """啟動時要不要跳介紹：看過這一版的介紹、或勾過「不再顯示」就不跳。"""
    return str(seen or "").strip() not in (NEVER_SHOW, GUIDE_VERSION)


def remember(never) -> str:
    """關掉介紹時寫進設定的值：勾了「不再顯示」是永久，沒勾是「看過這一版」。"""
    return NEVER_SHOW if never else GUIDE_VERSION


def choose_layout(argv, stored=None) -> str:
    """新介面開哪一種版面：命令列 --tabs／--editor 優先（兩個都給取後面那個），其次設定的 qt_layout，最後剪輯器。"""
    flags = [a for a in (argv or ()) if a in (EDITOR_FLAG, TABS_FLAG)]
    if flags:
        return TABS if flags[-1] == TABS_FLAG else EDITOR
    stored = str(stored or "").strip().lower()
    return stored if stored in LAYOUTS else DEFAULT_LAYOUT


def body_text() -> str:
    """介紹全文（純文字，測試直接驗）。"""
    lines = [INTRO, "", "【版面】", ""]
    for where, what in AREAS:
        lines.append(f"　◆ {where}：{what}")
    lines += ["", "【這一版多了什麼】", ""]
    for title, detail in NEW_IN_EDITOR:
        lines.append(f"　◆ {title}")
        lines.append(f"　　{detail}")
        lines.append("")
    lines += ["【四頁籤的東西在哪裡】", ""]
    for old, new in WHERE:
        lines.append(f"　{old}")
        lines.append(f"　　→ {new}")
    lines += ["", "【快捷鍵】", ""]
    width = max(len(k) for k, _d in KEYS)
    for key, what in KEYS:
        lines.append(f"　{key.ljust(width)}　{what}")
    lines += ["", "【想用回四頁籤】", "", f"　{SWITCH_BACK}"]
    return "\n".join(lines)
