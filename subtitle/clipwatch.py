# -*- coding: utf-8 -*-
"""
剪貼簿監聽：「複製即翻譯」的判斷邏輯（選取即翻譯第二階段）。

第一階段（`subtitle/quicktranslate.py` ＋ 本程式內的選取）只在自家視窗裡
有效。使用者要的是「不管在拍片與否都可以使用」——也就是看 YouTube 教
學、讀英文文件、翻 Reddit 討論時也能即時查譯。

**技術現實**：Windows 沒有讓外部程式讀取「使用者此刻在別的軟體裡選了什
麼」的通用 API，零第三方依賴下更沒有。退而求其次是監聽剪貼簿——變成
「複製即翻譯」。體驗退一步（要多按一次 Ctrl+C），但技術可靠。

**這個模組要解的是那個退讓帶來的新問題：複製 ≠ 想翻譯。**

使用者一天到晚在複製東西——密碼、API 金鑰、檔案路徑、網址、程式碼片
段、要貼到別處的中文。這些全部送去翻譯的話，輕則吵、重則**把密碼送進別
人的 API**。所以監聽開著的時候，每一次剪貼簿變動都要先過這裡的篩子。

篩子刻意**寧可漏翻、不可誤送**：判斷不準時一律不送。漏翻的代價是使用者
自己按一下〔翻譯剪貼簿內容〕，誤送的代價是隱私外洩，兩者不對等。

本模組零 GUI 依賴，判斷邏輯可以完全不開視窗就測。
"""

from __future__ import annotations

import re
from typing import Optional

from .quicktranslate import (looks_translatable, normalize_snippet,
                             resolve_quicktranslate_settings)

DEFAULT_CLIPWATCH = {
    # 預設**關閉**。監聽剪貼簿等於讀取使用者複製的每一樣東西，這種功能
    # 必須是使用者主動打開的，不能預設幫他開。
    "enabled": False,
    # 輪詢間隔。Tk 沒有「剪貼簿變了」的事件，只能定時去看。500ms 是可
    # 感覺即時、又不會把 CPU 吃在空轉上的折衷。
    "poll_ms": 500,
    # 下面三個篩子都預設開啟，理由見各自的偵測函式。
    "skip_secrets": True,
    "skip_code": True,
    "skip_paths": True,
}

_POLL_RANGE = (200, 5000)

# --- 密碼／金鑰特徵 -------------------------------------------------
# 一串沒有空白、混雜大小寫與數字的字元，多半是密碼、token 或雜湊。這種
# 東西沒有翻譯的意義，卻是最不該送出去的。
_SECRET_MIN = 8
_SECRET_MAX = 200
# 常見金鑰前綴，命中就直接擋（不必等特徵分析）。
_SECRET_PREFIXES = ("sk-", "pk-", "ghp_", "gho_", "github_pat_", "xox",
                    "AKIA", "AIza", "ya29.", "eyJ", "-----BEGIN")

# --- 程式碼特徵 -----------------------------------------------------
# 程式碼片段複製得非常頻繁，而且翻譯它沒有意義（變數名不該被翻成中文）。
_CODE_MARKERS = (
    "def ", "class ", "function ", "const ", "let ", "var ",
    "import ", "from ", "#include", "public static", "return ",
    "=>", "!=", "===", "::", "&&", "||", "</", "/>", "});", ");",
)
_CODE_LINE_END_RE = re.compile(r"[;{}]\s*$", re.MULTILINE)
_INDENT_RE = re.compile(r"^[ \t]{2,}\S", re.MULTILINE)
# **行首**的 import/from/#include 等匯入語句。錨定行首是刻意的：用子字串
# 比對的話「Let me import some clips」會被誤判成程式碼，但正常英文句子幾
# 乎不會**以** import 開頭。
_IMPORT_LINE_RE = re.compile(
    r"^\s*(import|from|#include|using|require|package)\s+\S", re.MULTILINE)
# HTML／JSX 標籤：<div />、</span>、<a href="...">text</a>
_TAG_RE = re.compile(r"</\w+>|<\w[\w.-]*(\s[^<>]*)?/>", re.DOTALL)

# --- 路徑／網址特徵 -------------------------------------------------
_URL_RE = re.compile(r"^(https?|ftp|file)://\S+$", re.IGNORECASE)
_WIN_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
_UNIX_PATH_RE = re.compile(r"^(/|~/|\./|\.\./)\S*$")
_UNC_PATH_RE = re.compile(r"^\\\\\w")


def resolve_clipwatch_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出剪貼簿監聽參數，缺漏補預設、數值夾限。"""
    raw = dict(DEFAULT_CLIPWATCH)
    if config:
        raw.update({k: v for k, v in (config.get("clipwatch") or {}).items()
                    if v is not None})

    def flag(key):
        value = raw.get(key)
        return DEFAULT_CLIPWATCH[key] if not isinstance(value, bool) else value

    try:
        poll = int(float(raw.get("poll_ms")))
    except (TypeError, ValueError):
        poll = DEFAULT_CLIPWATCH["poll_ms"]
    return {
        "enabled": flag("enabled"),
        "poll_ms": max(_POLL_RANGE[0], min(poll, _POLL_RANGE[1])),
        "skip_secrets": flag("skip_secrets"),
        "skip_code": flag("skip_code"),
        "skip_paths": flag("skip_paths"),
    }


def looks_like_secret(text: str) -> bool:
    """
    像不像密碼、API 金鑰或 token。

    兩條路判定：
      1. **已知金鑰前綴**（`sk-`、`ghp_`、`AKIA`、JWT 的 `eyJ`…）直接命
         中——這些一眼就認得出來，不必等特徵分析。
      2. **特徵分析**：整串沒有空白、長度在 8~200 之間，且同時混有英文字
         母與數字，或含有金鑰常見的符號。正常英文句子一定有空白，所以
         「沒有空白」這一條就擋掉了絕大多數誤判。

    寧可漏翻不可誤送：一個沒有空白的長字串就算真的是要翻的單字，使用者
    再按一次手動翻譯的代價，遠小於把金鑰送進 API。
    """
    snippet = (text or "").strip()
    if not snippet:
        return False
    if any(snippet.startswith(prefix) for prefix in _SECRET_PREFIXES):
        return True
    if " " in snippet or "\n" in snippet:
        return False  # 有空白／換行就不像單一組金鑰
    if not (_SECRET_MIN <= len(snippet) <= _SECRET_MAX):
        return False
    has_alpha = any(c.isalpha() for c in snippet)
    has_digit = any(c.isdigit() for c in snippet)
    has_symbol = any(c in "-_+=/.:@#$%^&*!" for c in snippet)
    # 英數混雜，或英文加上金鑰常見符號 → 當作密碼類。
    return has_alpha and (has_digit or has_symbol)


def looks_like_code(text: str) -> bool:
    """
    像不像程式碼片段。

    程式碼是最常被複製的東西之一，而且翻譯它沒有意義——變數名被翻成中文
    只會更難讀。判定看幾種訊號：行尾的 `;` `{` `}`、**行首**的匯入語句、
    HTML／JSX 標籤、以及語法關鍵字／運算子的數量。

    **匯入語句錨定行首是刻意的**：用子字串比對的話「Let me import some
    clips」會被誤判成程式碼而漏翻；正常英文句子幾乎不會**以** import 開
    頭。同理，單一關鍵字（`return `、`class ` 之類）必須再有「多行＋縮
    排」佐證才算數，否則「The return on investment」「The class starts at
    nine」這些句子全會中招。
    """
    snippet = (text or "").strip()
    if not snippet:
        return False
    if _CODE_LINE_END_RE.search(snippet):
        return True
    if _IMPORT_LINE_RE.search(snippet):
        return True
    if _TAG_RE.search(snippet):
        return True
    marker_hits = sum(1 for m in _CODE_MARKERS if m in snippet)
    if marker_hits >= 2:
        return True
    # 單一關鍵字時要多一個佐證（多行＋縮排），否則正常英文句子會中招。
    if marker_hits == 1 and "\n" in snippet and _INDENT_RE.search(snippet):
        return True
    return False


def looks_like_path_or_url(text: str) -> bool:
    """像不像檔案路徑或網址——翻譯它沒有意義，而且會洩漏本機目錄結構。"""
    snippet = (text or "").strip()
    if not snippet or " " in snippet and "\n" in snippet:
        return False
    first_line = snippet.splitlines()[0].strip() if snippet else ""
    if "\n" in snippet and len(snippet.splitlines()) > 1:
        return False  # 多行不當成單一路徑
    return bool(
        _URL_RE.match(first_line)
        or _WIN_PATH_RE.match(first_line)
        or _UNIX_PATH_RE.match(first_line)
        or _UNC_PATH_RE.match(first_line)
    )


def classify_clipboard(text: str, settings: Optional[dict] = None,
                       translate_settings: Optional[dict] = None) -> dict:
    """
    判斷這次剪貼簿內容該不該自動送去翻譯。

    回傳 ``{"translate": bool, "reason": str, "detail": str}``——``reason``
    是給介面顯示用的代號，讓使用者看得到「為什麼沒翻」而不是以為壞了。
    介面沉默地什麼都不做，跟功能故障在使用者眼裡是同一件事。

    ``detail`` 是給人看的一句話。
    """
    settings = settings or resolve_clipwatch_settings()
    translate_settings = translate_settings or resolve_quicktranslate_settings()
    snippet = normalize_snippet(text)

    if not snippet:
        return {"translate": False, "reason": "empty", "detail": "剪貼簿是空的。"}
    # **路徑／網址要先判，不能排在密碼後面**：網址與 Windows 路徑同樣是
    # 「沒有空白＋英數混雜＋含符號」，會先被密碼那條命中，結果雖然一樣是
    # 跳過，但顯示給使用者的理由會變成「看起來像密碼或金鑰」——那是錯
    # 的。理由要是真的才有意義，否則使用者會以為程式把他的網址當成密碼。
    if settings["skip_paths"] and looks_like_path_or_url(text):
        return {"translate": False, "reason": "path",
                "detail": "看起來像檔案路徑或網址，已跳過。"}
    if settings["skip_secrets"] and looks_like_secret(text):
        return {"translate": False, "reason": "secret",
                "detail": "看起來像密碼或金鑰，已跳過（不會送出）。"}
    if settings["skip_code"] and looks_like_code(text):
        return {"translate": False, "reason": "code",
                "detail": "看起來像程式碼，已跳過。"}
    if not looks_translatable(text, translate_settings):
        target = translate_settings.get("target_language", "")
        if target.startswith("zh"):
            return {"translate": False, "reason": "not_translatable",
                    "detail": "內容已經是中文、太短或太長，不需要翻譯。"}
        return {"translate": False, "reason": "not_translatable",
                "detail": "內容太短、太長或沒有可翻譯的文字。"}
    return {"translate": True, "reason": "ok", "detail": ""}


def format_skip_reason(result: dict) -> str:
    """把 classify_clipboard 的結果寫成一行狀態列文字。"""
    if result.get("translate"):
        return "偵測到新的剪貼簿內容，翻譯中..."
    return result.get("detail") or "這次的剪貼簿內容不需要翻譯。"
