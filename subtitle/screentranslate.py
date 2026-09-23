# -*- coding: utf-8 -*-
"""
螢幕畫面翻譯的流程層：框好的範圍 → 擷取 → 辨識 → **決定能不能送出翻譯**。

ROADMAP 第 9 項第一階段第 5 項（介面）底下的邏輯。前四項各自做好了一個
零件（`ocrengine`、`tesseract_setup`、`screencap`、`hotkey`），這個模組把
它們串成一條流程，並且把「辨識完之後要做什麼」這個決定集中在一個地方。

**為什麼要獨立成一個模組**：這些決定是整個功能最要緊的地方——隱私規則全
部落在這裡——不該散在 Tk 的事件處理裡。放在 `subtitle/` 還有第二個理由：
3.0 會把介面換成 Qt（`docs/ROADMAP_3.0.md`），到時候這一層原封沿用，要重
寫的只有畫面。

**「寧可漏翻、不可誤送」在這裡的樣子**（調研文件第 4 節）：

1. **辨識結果一律先顯示，預設不自動送出。** 使用者要先看得到自己框到了
   什麼。讀得很清楚的結果可以讓使用者自己打開「自動送出」，但預設關。
2. **讀不到字（`unreadable`）絕不送出**——那多半是一串亂碼，送出去只會
   浪費一次 API 呼叫、換回一段莫名其妙的「翻譯」。
3. **像密碼或金鑰的內容絕不送出**，沿用 `subtitle/clipwatch.py` 的篩子。
   被擋下來的內容**仍然可以在本機朗讀與複製**——那兩件事不離開這台電腦。
4. **截圖用完就刪。** 畫面上可能有私訊、帳戶資料；辨識完不需要那張圖，
   就不該留在暫存資料夾裡。不論辨識成功或失敗都刪。

零 GUI 依賴，擷取與辨識兩個函式都可以注入，測試不必真的截圖。
"""

from __future__ import annotations

import os
import re
import tempfile
import time
from typing import Callable, Optional

from subtitle import clipwatch, ocrengine, ocrlayout, screencap

# 使用者可調參數（config["screentranslate"]）。
DEFAULT_SCREENTRANSLATE = {
    # 辨識得清楚（verdict 為 ok）時自動送出翻譯。預設關：先顯示再送。
    "auto_send_ok": False,
}

# 決定的三種結果。
ACTION_SEND = "send"     # 直接送翻譯（只有使用者自己打開自動送出才會出現）
ACTION_HOLD = "hold"     # 顯示出來，等使用者確認後按「翻譯」
ACTION_BLOCK = "block"   # 不送出（讀不到字、像密碼）；朗讀與複製仍可用


def resolve_screentranslate_settings(config: Optional[dict] = None) -> dict:
    raw = dict(DEFAULT_SCREENTRANSLATE)
    if config:
        raw.update({k: v for k, v in (config.get("screentranslate") or {}).items()
                    if k in DEFAULT_SCREENTRANSLATE})
    return {"auto_send_ok": bool(raw["auto_send_ok"])}


# ----------------------------------------------------------------------
# 辨識完之後：送、等、還是擋
# ----------------------------------------------------------------------
BLOCK_UNREADABLE = "unreadable"
BLOCK_SECRET = "secret"
BLOCK_EMPTY = "empty"

_SECRET_MESSAGE = ("框到的內容看起來像密碼或金鑰，不會送去翻譯。"
                   "需要的話仍可在本機朗讀或複製。")
_EMPTY_MESSAGE = "這一塊沒有讀到任何文字。試著框大一點、框準一點再試一次。"
_HOLD_WEAK = ("辨識信心偏低（%.0f），可能有錯字。原文可以直接修改，"
              "確認後按「翻譯辨識結果」。")
_HOLD_OK = "辨識完成（信心 %.0f）。確認原文沒問題就按「翻譯辨識結果」。"


def decide(result: dict, settings: Optional[dict] = None) -> dict:
    """
    辨識完之後該怎麼辦。

    回傳 ``{"action", "reason", "message", "text"}``：
      * ``action``：``send`` / ``hold`` / ``block``
      * ``reason``：``block`` 時說明是哪一種（``unreadable``／``secret``／
        ``empty``），其他情況是空字串
      * ``message``：給狀態列的一句話，**每一種結果都要有話講**
      * ``text``：辨識出來的文字（被擋下來時也照樣給，方便朗讀與複製）

    判斷順序是刻意的：先看是不是讀不到字，再看像不像密碼，最後才看要不
    要自動送。任何一條擋下來就不再往下。
    """
    settings = settings or resolve_screentranslate_settings()
    text = (result.get("text") or "").strip()
    conf = float(result.get("mean_conf") or 0.0)
    verdict = result.get("verdict")

    if verdict == "unreadable":
        return {"action": ACTION_BLOCK, "reason": BLOCK_UNREADABLE,
                "message": ocrlayout.describe_verdict(result), "text": text}
    if not text:
        return {"action": ACTION_BLOCK, "reason": BLOCK_EMPTY,
                "message": _EMPTY_MESSAGE, "text": ""}
    if is_secret(text):
        return {"action": ACTION_BLOCK, "reason": BLOCK_SECRET,
                "message": _SECRET_MESSAGE, "text": text}
    if verdict == "ok" and settings["auto_send_ok"]:
        return {"action": ACTION_SEND, "reason": "",
                "message": "辨識完成（信心 %.0f），送出翻譯。" % conf,
                "text": text}
    template = _HOLD_OK if verdict == "ok" else _HOLD_WEAK
    return {"action": ACTION_HOLD, "reason": "", "message": template % conf,
            "text": text}


# 「標籤：值」的標籤。框一塊畫面最常見的外洩方式不是金鑰本身，而是
# 「密碼：hunter2」這種連同欄位名稱一起框進來的樣子——值本身可能很短、
# 很像普通單字，單看值是認不出來的。
_LABEL_RE = re.compile(
    r"(?<![A-Za-z])(password|passwd|passcode|pin|api[\s_-]?key|access[\s_-]?key|secret|"
    r"token|otp|密碼|口令|金鑰|密鑰|驗證碼|認證碼|安全碼)\s*[:：=]\s*\S",
    re.IGNORECASE)
# 句子裡的單一詞要多長、英數混雜到什麼程度才算像金鑰。實測
# `clipwatch.looks_like_secret` 直接套到每個詞會把 iPhone15Pro、COVID-19、
# 1080p60fps、Windows11 這種普通詞全部判成金鑰（它是為「複製一整段」設計
# 的，有空白就放行）；框一段畫面的句子裡有這種詞很正常，不能整段擋掉。
_LONG_TOKEN = 24


def is_secret(text: str) -> bool:
    """
    框到的內容像不像含有密碼／金鑰。分三層：

    1. **整段、或某一行只有一個詞**：沿用 `clipwatch.looks_like_secret`。
       一行只有一個英數混雜的詞，最像從密碼欄位框下來的值。
    2. **句子裡的詞**：只認已知的金鑰前綴（``sk-``、``ghp_``…），或長度
       24 以上、英數混雜的亂碼。普通詞（iPhone15Pro）不算。
    3. **「密碼：xxx」「API Key: xxx」這類標籤後面接著值**：一律算。

    寧可漏翻：被判成密碼的內容仍然可以在本機朗讀與複製，使用者損失的只
    是一次翻譯，而誤送的代價是金鑰外流。
    """
    snippet = (text or "").strip()
    if not snippet:
        return False
    if clipwatch.looks_like_secret(snippet):
        return True
    if _LABEL_RE.search(snippet):
        return True
    for line in snippet.splitlines():
        tokens = line.split()
        if len(tokens) == 1 and clipwatch.looks_like_secret(tokens[0]):
            return True
        for token in tokens:
            if token.startswith(clipwatch._SECRET_PREFIXES) and len(token) >= 12:
                return True
            if (len(token) >= _LONG_TOKEN
                    and any(c.isalpha() for c in token)
                    and any(c.isdigit() for c in token)):
                return True
    return False


def may_send(text: str) -> tuple:
    """
    使用者修改過原文、按下「翻譯辨識結果」時的最後一道檢查。

    回傳 ``(可以送, 不可以時的原因)``。**不能只在辨識完當下檢查一次**：
    原文框是可以改的，使用者可能把金鑰貼進去再按翻譯。
    """
    snippet = (text or "").strip()
    if not snippet:
        return False, _EMPTY_MESSAGE
    if is_secret(snippet):
        return False, _SECRET_MESSAGE
    return True, ""


# ----------------------------------------------------------------------
# 朗讀用：猜語言
# ----------------------------------------------------------------------
_KANA_RE = re.compile(r"[぀-ヿ]")
_HANGUL_RE = re.compile(r"[가-힯ᄀ-ᇿ]")
_HAN_RE = re.compile(r"[一-鿿㐀-䶿]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def guess_speech_lang(text: str) -> Optional[str]:
    """
    猜一段文字該用哪種語言的聲音念。

    用字元範圍判斷就夠了：朗讀要的只是「挑對口音」，挑錯的代價是念得怪，
    不是念錯內容。**假名優先於漢字**——日文句子裡漢字很多，只看漢字會把
    日文判成中文。猜不出來回 `None`，讓引擎用預設聲音。
    """
    sample = text or ""
    if _KANA_RE.search(sample):
        return "ja"
    if _HANGUL_RE.search(sample):
        return "ko"
    han = len(_HAN_RE.findall(sample))
    latin = len(_LATIN_RE.findall(sample))
    if han and han >= latin / 4:
        return "zh-TW"
    if latin:
        return "en"
    return None


# ----------------------------------------------------------------------
# 擷取 ＋ 辨識
# ----------------------------------------------------------------------
def capture_and_recognize(region, config: Optional[dict] = None,
                          bounds=None, workdir: Optional[str] = None,
                          capture: Optional[Callable] = None,
                          recognize: Optional[Callable] = None) -> dict:
    """
    擷取 `region` 並辨識，回傳 `ocrengine.recognize_text` 的結果，另加上
    ``region``（實際擷取的範圍）與 ``capture_seconds``。

    **截圖用完一定刪掉**（包在 finally 裡）——辨識失敗、使用者中途關掉，
    都不能讓一張畫面截圖留在暫存資料夾。擷取或辨識失敗會把
    `screencap.CaptureError`／`ocrengine.OcrError` 原樣往上拋，那兩種例外
    的訊息本來就寫成使用者看得懂、講得出下一步的話。
    """
    capture = capture or screencap.capture_region
    recognize = recognize or ocrengine.recognize_text
    folder = workdir or tempfile.gettempdir()
    handle, path = tempfile.mkstemp(prefix="srtgen_screen_", suffix=".bmp",
                                    dir=folder)
    os.close(handle)
    try:
        started = time.monotonic()
        capture(region, path, config=config, bounds=bounds)
        captured = time.monotonic()
        result = recognize(path, config=config)
        result = dict(result)
        result["region"] = tuple(region)
        result["capture_seconds"] = round(captured - started, 3)
        return result
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def format_status(result: dict, decision: dict) -> str:
    """狀態列的一行：決定的那句話，再加上花了多久（使用者會想知道慢在哪）。"""
    seconds = float(result.get("seconds") or 0.0) + float(
        result.get("capture_seconds") or 0.0)
    return "%s（%.1f 秒）" % (decision["message"].rstrip("。"), seconds) + "。"
