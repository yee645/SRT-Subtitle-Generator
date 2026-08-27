# -*- coding: utf-8 -*-
"""
快速翻譯：在本程式內選取一段文字，立刻看到中文翻譯。

調研背景：創作者在看外文素材（逐字稿、外語留言、參考影片的原文字幕）
時，遇到看不懂的字詞就得切出去查字典或翻譯網站，思路一斷，剪輯節奏就
跟著斷掉。技術調研的結論是第一階段只做「本程式內選取」——監聽
Tkinter 的 `<<Selection>>` 事件、以 `selection_get()` 取出選取範圍的
文字，零依賴、已原型驗證可行。

本模組是那個功能底下的純邏輯層：正規化選取到的文字、判斷值不值得送出
翻譯、呼叫 API、快取結果。刻意把這層與 Tkinter 事件綁定分開，GUI 端
只需要「選取變了 → 呼叫 translate_snippet → 顯示 dict」。

沿用「轉寫設定」既有的 OpenAI API 金鑰與呼叫慣例（同一組金鑰、同一套
錯誤訊息前綴，讓 errors.py 免費歸類），比照 subtitle/translator.py 的
作法：`from openai import OpenAI`、聊天模型 `_CHAT_MODEL`、金鑰空白或
函式庫未安裝時丟固定前綴的 RuntimeError。

「學習性」的落地方式：同一次 API 呼叫請模型除了譯文也一併回幾個值得
學的關鍵詞與解釋，不為了這個額外功能多打一次 API、多花一次錢。

max_chars 的理由：這個功能觸發的動作是「選取文字」，使用者很容易一失
手 Ctrl+A 把整份逐字稿（可能上萬字）選起來，若照樣送出去就是一次不小
的 API 費用，而且回應也不會是「選字翻譯」該有的樣子。600 字元大約是
中文影片腳本 2～3 分鐘的講稿量，遠超過「選一個詞或一兩句話查意思」的
正常使用範圍，超過此長度直接視為不適用、不觸發翻譯。

零 GUI 依賴，供選取翻譯浮動視窗與 CLI 共用。
"""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from typing import Optional

from subtitle.punctstyle import cjk_ratio

# 使用者可調參數（config["quicktranslate"]）。
DEFAULT_QUICKTRANSLATE = {
    "target_language": "zh-TW",  # 目標語言代碼；英翻中是主要情境
    "debounce_ms": 350,          # 選取變動後等待這麼久才送出，避免拖曳中途連續觸發
    "cache_size": 200,           # LRU 快取筆數，同一段文字翻過不再打 API
    "max_chars": 600,            # 單次翻譯的字數上限（理由見檔頭 docstring）
    "min_chars": 2,              # 選取字數低於此值不觸發（避免選到一兩個字母就送出）
    "explain": True,             # 是否一併請模型解說關鍵詞（學習性功能）
}

_DEBOUNCE_RANGE = (0, 3000)
_CACHE_SIZE_RANGE = (1, 2000)
_MAX_CHARS_RANGE = (20, 4000)
_MIN_CHARS_RANGE = (1, 50)

# 翻譯用的聊天模型，與 translator.py 共用同一顆（文字翻譯不需要語音模型）。
_CHAT_MODEL = "gpt-4o-mini"

# 沿用 translator.py 的語言代碼 → 中文名稱對照表，快速翻譯只是另一個
# 使用場景，沒有理由另起一份。
try:
    from subtitle.translator import LANGUAGE_LABELS
except ImportError:  # pragma: no cover - translator.py 屬本專案既有模組
    LANGUAGE_LABELS = {"zh-TW": "繁體中文", "en": "英文"}

_WS_RE = re.compile(r"\s+")
_DIGIT_PUNCT_RE = re.compile(
    r"^[\d\s\W_]+$", re.UNICODE)  # 純數字／純標點／純符號（不含任何文字字元）


def _clamp_int(value, low, high, fallback):
    try:
        value = int(float(value))
    except (TypeError, ValueError):
        return fallback
    return max(low, min(value, high))


def resolve_quicktranslate_settings(config: Optional[dict] = None) -> dict:
    """從完整設定 dict 取出快速翻譯參數，缺漏補齊預設值並夾限範圍。"""
    raw = dict(DEFAULT_QUICKTRANSLATE)
    if config:
        raw.update({k: v for k, v in (config.get("quicktranslate") or {}).items()
                    if v is not None})
    language = raw.get("target_language")
    if not isinstance(language, str) or not language.strip():
        language = DEFAULT_QUICKTRANSLATE["target_language"]
    explain = raw.get("explain")
    if not isinstance(explain, bool):
        explain = DEFAULT_QUICKTRANSLATE["explain"]
    return {
        "target_language": language,
        "debounce_ms": _clamp_int(raw.get("debounce_ms"), *_DEBOUNCE_RANGE,
                                  DEFAULT_QUICKTRANSLATE["debounce_ms"]),
        "cache_size": _clamp_int(raw.get("cache_size"), *_CACHE_SIZE_RANGE,
                                 DEFAULT_QUICKTRANSLATE["cache_size"]),
        "max_chars": _clamp_int(raw.get("max_chars"), *_MAX_CHARS_RANGE,
                                DEFAULT_QUICKTRANSLATE["max_chars"]),
        "min_chars": _clamp_int(raw.get("min_chars"), *_MIN_CHARS_RANGE,
                                DEFAULT_QUICKTRANSLATE["min_chars"]),
        "explain": explain,
    }


def normalize_snippet(text: str) -> str:
    """
    正規化選取到的文字：收合換行與多餘空白、去除頭尾空白。

    目的是讓「同一句話但選取邊界差一個空白／換行」能命中同一份快取，
    也讓短句判斷（純數字、純標點等）不被雜散的空白干擾。
    """
    if not text:
        return ""
    return _WS_RE.sub(" ", text).strip()


def looks_translatable(text: str, settings: Optional[dict] = None) -> bool:
    """
    判斷這段選取值不值得送出翻譯。

    以下情況一律回傳 False：
      - 正規化後長度低於 min_chars 或超過 max_chars
      - 純數字／純標點／純符號（沒有任何文字內容可翻）
      - 目標語言是中文時，選取內容本身已經是中文為主
        （沿用 punctstyle.cjk_ratio 同樣的「中英夾雜也算中文」邏輯：
        門檻抓 0.15，「我用的是 Premiere Pro」這種夾雜英文專有名詞的
        中文句子不會被誤判成英文而再翻一次）
    """
    settings = settings or resolve_quicktranslate_settings()
    snippet = normalize_snippet(text)
    length = len(snippet)
    if length < settings["min_chars"] or length > settings["max_chars"]:
        return False
    if _DIGIT_PUNCT_RE.match(snippet):
        return False
    target = settings.get("target_language", "")
    if target.startswith("zh") and cjk_ratio(snippet) >= 0.15:
        return False
    return True


class TranslationCache:
    """
    容量固定的 LRU 快取：key 是（正規化文字, 目標語言），value 是翻譯結果。

    翻譯浮動視窗一次工作階段可能選取上百次同樣的詞（例如反覆查同一個
    專有名詞），沒有快取就是每次都重打 API；容量固定避免長時間使用下
    無限吃記憶體。
    """

    def __init__(self, capacity: int = 200):
        self._capacity = max(int(capacity or 1), 1)
        self._store: "OrderedDict[tuple, dict]" = OrderedDict()

    def __len__(self):
        return len(self._store)

    def make_key(self, text: str, target_language: str,
                 explain: bool = True) -> tuple:
        # explain 要進 key：同一段文字在「要關鍵詞解說」與「不要」兩種
        # 設定下的結果格式不同，只用文字當 key 會在使用者中途切換開關時
        # 命中格式不符的舊結果。
        return (normalize_snippet(text), target_language, bool(explain))

    def get(self, text: str, target_language: str, explain: bool = True):
        key = self.make_key(text, target_language, explain)
        if key not in self._store:
            return None
        self._store.move_to_end(key)
        return self._store[key]

    def put(self, text: str, target_language: str, value: dict,
            explain: bool = True) -> None:
        key = self.make_key(text, target_language, explain)
        self._store[key] = value
        self._store.move_to_end(key)
        while len(self._store) > self._capacity:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()


def _strip_code_fence(text: str) -> str:
    """去除 API 回應可能夾帶的 ```json ... ``` 圍欄，方便後續 json.loads。"""
    text = (text or "").strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines:
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_terms(raw) -> list:
    """把 API 回應裡的 terms 欄位整理成 [{"word","meaning"}, ...]；格式不符時回傳空清單。"""
    if not isinstance(raw, list):
        return []
    terms = []
    for item in raw:
        if isinstance(item, dict):
            word = str(item.get("word") or item.get("term") or "").strip()
            meaning = str(item.get("meaning") or item.get("explanation") or "").strip()
            if word and meaning:
                terms.append({"word": word, "meaning": meaning})
    return terms


def _parse_translation_response(content: str, fallback_source: str) -> dict:
    """
    解析 API 回應，回傳 {"translation", "terms"}。

    解析失敗或格式不符時採用漸進式 fallback，絕不因此丟出例外：
      1. 不是合法 JSON → 把整段回應內容當成譯文（模型有時仍會用純文字
         正確回答，只是沒照要求包成 JSON，直接丟掉這段翻譯太浪費）。
      2. 是 JSON 但沒有 translation 欄位 → 同樣退回整段原始內容當譯文。
      3. terms 缺漏或格式不符 → 直接視為沒有關鍵詞解說，不影響譯文。
    """
    text = _strip_code_fence(content)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"translation": text or fallback_source, "terms": []}
    if not isinstance(parsed, dict):
        return {"translation": text or fallback_source, "terms": []}
    translation = parsed.get("translation")
    if not isinstance(translation, str) or not translation.strip():
        translation = text or fallback_source
    return {"translation": translation.strip(), "terms": _parse_terms(parsed.get("terms"))}


def translate_snippet(
    text: str,
    api_key: str,
    settings: Optional[dict] = None,
    cache: Optional[TranslationCache] = None,
) -> dict:
    """
    把一段選取文字翻成目標語言，附帶關鍵詞解說（學習性功能）。

    參數：
        text: 選取到的原始文字（未正規化亦可，內部會正規化）。
        api_key: 轉寫設定共用的 OpenAI API 金鑰。
        settings: resolve_quicktranslate_settings() 的結果；省略則用預設值。
        cache: TranslationCache 實例；命中時直接回傳、不打 API。省略則
            不使用快取（每次都呼叫 API）。

    回傳 dict：
        source: 正規化後的原文
        translation: 譯文
        terms: 關鍵詞清單 [{"word","meaning"}, ...]；settings["explain"]
            為 False，或模型沒有回傳可用的詞條時為空清單
        cached: 這次是否命中快取

    例外：
        金鑰空白、openai 函式庫未安裝、API 呼叫失敗時，丟出與
        translator.py 相同前綴的 RuntimeError（errors.py 靠前綴歸類，
        不要更動這些字串）。API 回應本身格式不符 JSON 屬於「內容問題」
        而非「呼叫失敗」，一律走 fallback、不會拋出例外。
    """
    settings = settings or resolve_quicktranslate_settings()
    source = normalize_snippet(text)

    if cache is not None:
        hit = cache.get(source, settings["target_language"],
                        settings["explain"])
        if hit is not None:
            result = dict(hit)
            result["cached"] = True
            return result

    api_key = (api_key or "").strip()
    if not api_key:
        raise RuntimeError("已啟用 API 模式，但尚未填入 OpenAI API 金鑰。")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "未安裝 openai 函式庫。請執行：pip install openai"
        ) from exc

    client = OpenAI(api_key=api_key)
    language_label = LANGUAGE_LABELS.get(
        settings["target_language"], settings["target_language"])

    if settings["explain"]:
        instruction = (
            f"Translate the user's text into {language_label}. Also pick "
            "up to 3 words or phrases from the original text that a "
            "learner would benefit from understanding (skip this if the "
            "text is too short or simple for it), each with a brief "
            f"meaning/explanation written in {language_label}. Return ONLY "
            "a JSON object of the exact shape "
            '{"translation": string, "terms": [{"word": string, '
            '"meaning": string}]} with no extra text, explanation, or '
            "markdown."
        )
    else:
        instruction = (
            f"Translate the user's text into {language_label}. Return "
            'ONLY a JSON object of the exact shape {"translation": string, '
            '"terms": []} with no extra text, explanation, or markdown.'
        )

    try:
        response = client.chat.completions.create(
            model=_CHAT_MODEL,
            messages=[
                {"role": "system", "content": instruction},
                {"role": "user", "content": source},
            ],
        )
        content = response.choices[0].message.content
    except Exception as exc:
        raise RuntimeError(f"呼叫 OpenAI API 失敗：{exc}") from exc

    parsed = _parse_translation_response(content, source)
    result = {
        "source": source,
        "translation": parsed["translation"],
        "terms": parsed["terms"] if settings["explain"] else [],
        "cached": False,
    }

    if cache is not None:
        cache.put(source, settings["target_language"], result,
                  settings["explain"])
    return result


def format_snippet_report(result: dict) -> str:
    """
    把 translate_snippet() 的結果排成純文字，CLI 與 GUI 共用。

    本專案慣例：不用 markdown 的 ** 粗體（tk.Text 會原樣顯示星號），
    要強調用「」。
    """
    lines = [
        f"原文：{result.get('source', '')}",
        f"「翻譯」：{result.get('translation', '')}",
    ]
    terms = result.get("terms") or []
    if terms:
        lines.append("")
        lines.append("關鍵詞：")
        for term in terms:
            word = term.get("word", "")
            meaning = term.get("meaning", "")
            lines.append(f"・「{word}」：{meaning}")
    if result.get("cached"):
        lines.append("")
        lines.append("（快取結果）")
    return "\n".join(lines)
