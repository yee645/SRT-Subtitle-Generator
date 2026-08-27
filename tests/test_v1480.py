# -*- coding: utf-8 -*-
"""v1.48.0 新功能測試：快速翻譯（選取文字立刻看到中文翻譯，附關鍵詞解說）。"""
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import quicktranslate as qt
from config import DEFAULT_CONFIG


# ===== 1. 設定夾限與非法值退回 =====
check("預設值進得了 config",
      DEFAULT_CONFIG["quicktranslate"]["target_language"] == "zh-TW")
check("空白 target_language 退回預設",
      qt.resolve_quicktranslate_settings(
          {"quicktranslate": {"target_language": "  "}}
      )["target_language"] == "zh-TW")
check("debounce_ms 夾限上限",
      qt.resolve_quicktranslate_settings(
          {"quicktranslate": {"debounce_ms": 999999}}
      )["debounce_ms"] == qt._DEBOUNCE_RANGE[1])
check("debounce_ms 夾限下限（負值）",
      qt.resolve_quicktranslate_settings(
          {"quicktranslate": {"debounce_ms": -50}}
      )["debounce_ms"] == qt._DEBOUNCE_RANGE[0])
check("cache_size 非數字退回預設",
      qt.resolve_quicktranslate_settings(
          {"quicktranslate": {"cache_size": "abc"}}
      )["cache_size"] == 200)
check("max_chars 夾限",
      qt.resolve_quicktranslate_settings(
          {"quicktranslate": {"max_chars": 99999}}
      )["max_chars"] == qt._MAX_CHARS_RANGE[1])
check("min_chars 夾限",
      qt.resolve_quicktranslate_settings(
          {"quicktranslate": {"min_chars": 0}}
      )["min_chars"] == qt._MIN_CHARS_RANGE[0])
check("explain 非 bool 退回預設 True",
      qt.resolve_quicktranslate_settings(
          {"quicktranslate": {"explain": "yes"}}
      )["explain"] is True)
check("explain 可關閉",
      qt.resolve_quicktranslate_settings(
          {"quicktranslate": {"explain": False}}
      )["explain"] is False)
check("空設定不會炸，回傳預設",
      qt.resolve_quicktranslate_settings(None) == dict(qt.DEFAULT_QUICKTRANSLATE))

DEFAULT = qt.resolve_quicktranslate_settings()

# ===== 2. looks_translatable：值不值得送出 =====
check("英文句子該翻",
      qt.looks_translatable("So today we're going to talk about editing.", DEFAULT))
check("純中文不該翻（目標語言是中文，選到中文沒有意義）",
      not qt.looks_translatable("今天要跟大家分享三個剪輯技巧", DEFAULT))
check("中英夾雜的中文句不該翻（不能把專有名詞誤判成英文）",
      not qt.looks_translatable("我用的是 Premiere Pro，超好用", DEFAULT))
check("太短不該翻",
      not qt.looks_translatable("ab", qt.resolve_quicktranslate_settings(
          {"quicktranslate": {"min_chars": 3}})))
check("剛好達到 min_chars 該翻",
      qt.looks_translatable("abc", qt.resolve_quicktranslate_settings(
          {"quicktranslate": {"min_chars": 3}})))
check("純數字不該翻", not qt.looks_translatable("123456", DEFAULT))
check("純標點不該翻", not qt.looks_translatable("...!!!？？", DEFAULT))
check("純數字加標點不該翻", not qt.looks_translatable("12:34, 56.7", DEFAULT))
check("超過 max_chars 不該翻",
      not qt.looks_translatable("x" * (DEFAULT["max_chars"] + 1), DEFAULT))
check("剛好等於 max_chars 該翻",
      qt.looks_translatable("x" * DEFAULT["max_chars"], DEFAULT))
check("空字串不該翻", not qt.looks_translatable("", DEFAULT))
check("目標語言不是中文時，選到中文也該翻",
      qt.looks_translatable("這是一段中文", qt.resolve_quicktranslate_settings(
          {"quicktranslate": {"target_language": "en"}})))

# ===== 3. normalize_snippet：不同空白邊界能命中同一份快取 =====
check("收合連續空白與換行",
      qt.normalize_snippet("  hello\n\n  world  ") == "hello world")
check("純換行變單一空白",
      qt.normalize_snippet("hello\nworld") == "hello world")
check("None 不會炸", qt.normalize_snippet(None) == "")
VARIANTS = ["Premiere Pro", "  Premiere Pro  ", "Premiere\nPro", "Premiere   Pro"]
check("不同空白邊界正規化後相同",
      len({qt.normalize_snippet(v) for v in VARIANTS}) == 1)


# ===== 4. TranslationCache：LRU 行為 =====
cache = qt.TranslationCache(capacity=2)
cache.put("a", "zh-TW", {"translation": "1"})
cache.put("b", "zh-TW", {"translation": "2"})
check("容量內的兩筆都在", cache.get("a", "zh-TW") is not None
      and cache.get("b", "zh-TW") is not None)
cache.put("c", "zh-TW", {"translation": "3"})
check("超過容量時擠掉最久未用的一筆", cache.get("a", "zh-TW") is None, "a 應已被擠掉")
check("較新的兩筆還在", cache.get("b", "zh-TW") is not None
      and cache.get("c", "zh-TW") is not None)
check("容量上限沒有超過設定值", len(cache) == 2)
check("不同目標語言不會互相命中",
      qt.TranslationCache(5).get("a", "en") is None)

cache2 = qt.TranslationCache(capacity=3)
cache2.put("x", "zh-TW", {"v": 1})
cache2.put("y", "zh-TW", {"v": 2})
cache2.get("x", "zh-TW")  # 存取 x，讓它變成最近使用
cache2.put("z", "zh-TW", {"v": 3})
cache2.put("w", "zh-TW", {"v": 4})  # 超過容量，應擠掉最久未用的 y（不是 x）
check("get 會更新使用順序（LRU 而非單純先進先出）",
      cache2.get("x", "zh-TW") is not None and cache2.get("y", "zh-TW") is None)


# ===== 5. 假 openai：不打真的 API，用計數器與假模組驗證 =====
def install_fake_openai(reply_content, raise_error=None):
    """裝一個假 openai 模組到 sys.modules，回傳呼叫次數計數器。"""
    calls = {"n": 0}
    fake = types.ModuleType("openai")

    class FakeMsg:
        def __init__(self, content):
            self.content = content

    class FakeChoice:
        def __init__(self, content):
            self.message = FakeMsg(content)

    class FakeResp:
        def __init__(self, content):
            self.choices = [FakeChoice(content)]

    class FakeCompletions:
        def create(self, model, messages):
            calls["n"] += 1
            if raise_error:
                raise raise_error
            content = (reply_content(calls["n"])
                       if callable(reply_content) else reply_content)
            return FakeResp(content)

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeClient:
        def __init__(self, api_key=None):
            self.chat = FakeChat()

    fake.OpenAI = FakeClient
    sys.modules["openai"] = fake
    return calls


good_json = json.dumps(
    {"translation": "你好世界",
     "terms": [{"word": "hello", "meaning": "打招呼用語"}]},
    ensure_ascii=False)
calls = install_fake_openai(good_json)
c = qt.TranslationCache(capacity=10)
r1 = qt.translate_snippet("hello world", "sk-fake-key", cache=c)
check("翻譯結果正確", r1["translation"] == "你好世界", r1)
check("回傳正規化後的原文", r1["source"] == "hello world")
check("terms 有解析出關鍵詞", r1["terms"] == [{"word": "hello", "meaning": "打招呼用語"}])
check("第一次不是快取命中", r1["cached"] is False)

r2 = qt.translate_snippet("  hello   world  ", "sk-fake-key", cache=c)
check("第二次同樣文字（空白邊界不同）命中快取", r2["cached"] is True)
check("命中快取時不會再呼叫 API", calls["n"] == 1, f"實際呼叫次數={calls['n']}")
check("快取命中的內容與原結果一致", r2["translation"] == r1["translation"])

r3 = qt.translate_snippet("hello world", "sk-fake-key")  # 不給 cache
check("不給 cache 時每次都呼叫 API", calls["n"] == 2, f"實際呼叫次數={calls['n']}")

# explain=False 時 terms 應為空，即使模型仍回了 terms。
settings_no_explain = qt.resolve_quicktranslate_settings(
    {"quicktranslate": {"explain": False}})
r4 = qt.translate_snippet("hello again", "sk-fake-key", settings=settings_no_explain)
check("explain=False 時 terms 為空清單", r4["terms"] == [], r4)


# explain 必須進快取 key：同一段文字在「要關鍵詞解說」與「不要」兩種設定
# 下結果格式不同，只用文字當 key 的話，使用者中途切換開關會命中格式不符
# 的舊結果（這是實際發生過的 bug）。
calls_explain = install_fake_openai(good_json)
shared = qt.TranslationCache(capacity=10)
a = qt.translate_snippet("switch me", "sk-fake-key", cache=shared)
b = qt.translate_snippet("switch me", "sk-fake-key",
                         settings=settings_no_explain, cache=shared)
check("切換 explain 後不會命中舊格式的快取", b["cached"] is False, b)
check("切換 explain 後拿到的是符合新設定的結果", b["terms"] == [], b)
check("切回 explain=True 仍能命中原本那筆",
      qt.translate_snippet("switch me", "sk-fake-key",
                           cache=shared)["cached"] is True)
check("兩種設定各自留一份快取", len(shared) == 2, str(len(shared)))


# ===== 6. API 回傳壞掉的 JSON：不丟例外、要有 fallback =====
calls_bad = install_fake_openai("這不是 JSON，只是模型隨口回的一段話")
r5 = qt.translate_snippet("random text", "sk-fake-key")
check("壞 JSON 不會丟例外、有 fallback 譯文",
      r5["translation"] == "這不是 JSON，只是模型隨口回的一段話", r5)
check("壞 JSON 時 terms 是空清單", r5["terms"] == [])

calls_partial = install_fake_openai(json.dumps({"terms": []}))
r6 = qt.translate_snippet("no translation field", "sk-fake-key")
check("JSON 合法但缺 translation 欄位時仍有 fallback 內容",
      bool(r6["translation"]), r6)

calls_fenced = install_fake_openai(
    "```json\n" + json.dumps({"translation": "圍欄內的譯文", "terms": []}) + "\n```")
r7 = qt.translate_snippet("fenced", "sk-fake-key")
check("能解析被 ```json 圍欄包住的回應", r7["translation"] == "圍欄內的譯文", r7)

install_fake_openai(None, raise_error=RuntimeError("network down"))
try:
    qt.translate_snippet("boom", "sk-fake-key")
    check("API 呼叫失敗時應丟出例外", False)
except RuntimeError as exc:
    check("API 失敗訊息維持既有前綴（errors.py 靠它歸類）",
          str(exc).startswith("呼叫 OpenAI API 失敗："), str(exc))
except Exception as exc:  # noqa: BLE001
    check(f"API 失敗不應丟出非預期例外型別（實際 {type(exc)}）", False)


# ===== 7. 沒有金鑰 / 沒裝 openai：既有慣例的 RuntimeError =====
try:
    qt.translate_snippet("hello", "")
    check("空金鑰應丟出例外", False)
except RuntimeError as exc:
    check("空金鑰訊息與 translator.py 慣例一致",
          str(exc) == "已啟用 API 模式，但尚未填入 OpenAI API 金鑰。", str(exc))

try:
    qt.translate_snippet("hello", "   ")
    check("空白金鑰應丟出例外", False)
except RuntimeError as exc:
    check("空白金鑰視同未填",
          str(exc) == "已啟用 API 模式，但尚未填入 OpenAI API 金鑰。", str(exc))

if "openai" in sys.modules:
    del sys.modules["openai"]
_real_import = __import__
def _blocked_import(name, *args, **kwargs):
    if name == "openai":
        raise ImportError("no module named openai")
    return _real_import(name, *args, **kwargs)
import builtins
builtins.__import__ = _blocked_import
try:
    qt.translate_snippet("hello", "sk-fake-key")
    check("未安裝 openai 應丟出例外", False)
except RuntimeError as exc:
    check("未安裝 openai 訊息與 translator.py 慣例一致",
          str(exc) == "未安裝 openai 函式庫。請執行：pip install openai", str(exc))
finally:
    builtins.__import__ = _real_import

# 有快取命中時，即使沒有金鑰或沒裝 openai 也不該碰 API／丟例外。
cache_hit_only = qt.TranslationCache(capacity=5)
cache_hit_only.put("cached phrase", "zh-TW", {
    "source": "cached phrase", "translation": "快取譯文", "terms": [], "cached": False})
r8 = qt.translate_snippet("cached phrase", "", cache=cache_hit_only)
check("快取命中時不需要金鑰也能回傳", r8["translation"] == "快取譯文", r8)
check("快取命中標記為 cached", r8["cached"] is True)


# ===== 8. format_snippet_report：純文字報告 =====
report = qt.format_snippet_report(r1)
check("報告含原文", "hello world" in report)
check("報告含譯文", "你好世界" in report)
check("報告含關鍵詞", "hello" in report and "打招呼用語" in report)
check("報告不用 markdown 粗體", "**" not in report)

report_no_terms = qt.format_snippet_report(
    {"source": "x", "translation": "y", "terms": [], "cached": False})
check("沒有關鍵詞時報告仍正常（不出現空的關鍵詞區塊）",
      "關鍵詞" not in report_no_terms, report_no_terms)

report_cached = qt.format_snippet_report(
    {"source": "x", "translation": "y", "terms": [], "cached": True})
check("報告會標示是否為快取結果", "快取" in report_cached)


# ===== 9. 零 GUI 依賴、重用既有 CJK 定義 =====
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "subtitle", "quicktranslate.py"),
           encoding="utf-8").read()
check("不 import tkinter", "tkinter" not in src)
# 中文判定直接重用 punctstyle.cjk_ratio，不自己再算一次比例。實測九種
# 輸入只有「🎬 今天要剪片」一例比例不同（1.00 vs 0.83），而兩者都遠高於
# 0.15 門檻、判斷結果完全相同——換不到行為差異，卻會留下兩份各自漂移的
# 實作，所以統一用既有的那份。
check("重用 punctstyle 的中文比例判定（不另外抄一份）",
      "from subtitle.punctstyle import cjk_ratio" in src)
check("沒有自己再寫一份 CJK 比例函式",
      "_cjk_ratio" not in src and "def _is_cjk_char" not in src)
check("重用 translator 的語言對照表（不另外抄一份）",
      "from subtitle.translator import LANGUAGE_LABELS" in src)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.48.0 測試全數通過。")
