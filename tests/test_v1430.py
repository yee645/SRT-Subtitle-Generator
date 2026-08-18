# -*- coding: utf-8 -*-
"""v1.43.0 新功能測試：多語字幕包（一份母帶翻成多國語言）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import multilang as ml


def cue(start, end, text, words=None):
    row = {"start": start, "end": end, "text": text}
    if words is not None:
        row["words"] = words
    return row


S = ml.resolve_multilang_settings(None)

# ===== 1. 設定解析 =====
check("預設語言為 en,ja", S["languages"] == "en,ja", str(S))
check("預設略過原文語言", S["skip_source"] is True)
check("預設啟用去重", S["dedupe"] is True)
check("可覆寫語言清單",
      ml.resolve_multilang_settings(
          {"multilang": {"languages": "ko"}})["languages"] == "ko")
check("布林值一律轉成 bool",
      ml.resolve_multilang_settings(
          {"multilang": {"dedupe": 0}})["dedupe"] is False)
check("None 不覆蓋預設值",
      ml.resolve_multilang_settings(
          {"multilang": {"languages": None}})["languages"] == "en,ja")
check("空設定等同預設", ml.resolve_multilang_settings({}) == S)

# ===== 2. 語言清單整理 =====
check("逗號與空白都能分隔", ml.parse_languages("en, ja ko") == ["en", "ja", "ko"])
check("全形逗號也能分隔", ml.parse_languages("en，ja") == ["en", "ja"])
check("重複的語言只留一個並保序",
      ml.parse_languages("en,ja,en,ko") == ["en", "ja", "ko"])
check("大小寫不同視為同一個語言",
      ml.parse_languages("en,EN,En") == ["en"])
check("接受清單型別", ml.parse_languages(["en", "ja"]) == ["en", "ja"])
check("空輸入回空清單",
      ml.parse_languages("") == [] and ml.parse_languages(None) == [])
check("未收錄的語言代碼不會被擋掉",
      ml.parse_languages("pt-BR,sw") == ["pt-BR", "sw"])

# 翻成自己沒有意義，還要多付一次 API 費用。
check("略過與原文相同的語言",
      ml.parse_languages("en,zh-TW,ja", source_language="zh-TW")
      == ["en", "ja"])
check("略過時不分大小寫",
      ml.parse_languages("EN,ja", source_language="en") == ["ja"])
check("可關閉略過原文",
      ml.parse_languages("en,zh-TW", source_language="zh-TW",
                         skip_source=False) == ["en", "zh-TW"])
check("原文為空時不略過任何語言",
      ml.parse_languages("en,ja", source_language="") == ["en", "ja"])

# ===== 3. 語言顯示名稱 =====
check("內建語言有中文名稱", ml.language_label("ja") == "日文")
check("未收錄的代碼直接顯示代碼", ml.language_label("sw") == "sw")

# ===== 4. 去重（省 API 費用的關鍵）=====
texts = ["對", "今天要講三個技巧", "對", "嗯", "今天要講三個技巧", "結束"]
unique, mapping = ml.dedupe_texts(texts)
check("重複句子收斂成唯一清單",
      unique == ["對", "今天要講三個技巧", "嗯", "結束"], str(unique))
check("還原索引長度等於原文句數", len(mapping) == len(texts))
check("實際省下的句數", len(unique) == 4 and len(texts) == 6)
check("譯文能原樣攤回每一個位置",
      ml.expand_translations(["A", "B", "C", "D"], mapping)
      == ["A", "B", "A", "C", "B", "D"])
check("去重保持首次出現的順序", unique[0] == "對" and unique[1] == "今天要講三個技巧")
check("空清單不會炸", ml.dedupe_texts([]) == ([], []))
check("None 不會炸", ml.dedupe_texts(None) == ([], []))
check("攤回時索引超界不會炸",
      ml.expand_translations(["A"], [0, 5]) == ["A", ""])
check("攤回空對照表", ml.expand_translations([], []) == [])

# ===== 5. 翻譯成單一語言（以假的 translate_texts 隔離 API）=====
calls = []

def fake_translate(texts, language, api_key, progress_cb=None, batch_size=30):
    calls.append({"texts": list(texts), "language": language,
                  "batch_size": batch_size})
    return [f"[{language}]{t}" for t in texts]

real_translate = ml.translate_texts
ml.translate_texts = fake_translate

cues = [cue(0, 2, "對", words=[{"word": "對", "start": 0, "end": 2}]),
        cue(2, 5, "今天要講三個技巧"),
        cue(5, 7, "對"),
        cue(7, 9, "結束")]

calls.clear()
out = ml.translate_to_language(cues, "en", "KEY", dedupe=True)
check("輸出句數與原文相同", len(out) == len(cues))
check("輸出為單語（不含原文）",
      out[1]["text"] == "[en]今天要講三個技巧", out[1]["text"])
check("時間軸原樣保留",
      out[0]["start"] == 0 and out[0]["end"] == 2)
# 翻譯後逐字時間軸已經對不上新文字。
check("輸出不含 words 欄位", "words" not in out[0])
check("不修改傳入的 cues", cues[1]["text"] == "今天要講三個技巧")
check("去重後只送唯一句子",
      calls[0]["texts"] == ["對", "今天要講三個技巧", "結束"],
      str(calls[0]["texts"]))
check("重複的句子譯文一致",
      out[0]["text"] == out[2]["text"] == "[en]對")

calls.clear()
ml.translate_to_language(cues, "ja", "KEY", dedupe=False)
check("關閉去重時逐句送",
      calls[0]["texts"] == ["對", "今天要講三個技巧", "對", "結束"],
      str(calls[0]["texts"]))

# 譯文為空時要退回原文，避免產生空字幕。
ml.translate_texts = lambda texts, *a, **k: ["" for _ in texts]
blank = ml.translate_to_language(cues, "en", "KEY")
check("譯文為空時退回原文", blank[1]["text"] == "今天要講三個技巧")
ml.translate_texts = fake_translate

check("空字幕不會炸", ml.translate_to_language([], "en", "KEY") == [])
check("None 不會炸", ml.translate_to_language(None, "en", "KEY") == [])

# ===== 6. 多語言包 =====
calls.clear()
pack = ml.build_language_pack(cues, ["en", "ja", "ko"], "KEY")
check("每個語言各一份", sorted(pack) == ["en", "ja", "ko"], str(sorted(pack)))
check("每份句數都與原文相同",
      all(len(v) == len(cues) for v in pack.values()))
check("各語言譯文互不相同",
      pack["en"][1]["text"] != pack["ja"][1]["text"])
check("每個語言各送一次 API", len(calls) == 3, str(len(calls)))
check("空語言清單回空 dict", ml.build_language_pack(cues, [], "KEY") == {})
check("None 語言清單回空 dict",
      ml.build_language_pack(cues, None, "KEY") == {})

progress = []
ml.build_language_pack(cues, ["en", "ja"], "KEY",
                       progress_cb=lambda r, m: progress.append((r, m)))
check("進度回呼有被呼叫", len(progress) > 0)
check("進度比例落在 0~1",
      all(0.0 <= r <= 1.0 for r, _ in progress),
      str([r for r, _ in progress]))
check("進度訊息標示第幾個語言",
      any("1/2" in m for _, m in progress), str(progress[:2]))

ml.translate_texts = real_translate

# ===== 7. 檔名慣例 =====
check("語言代碼放在副檔名之前",
      os.path.basename(ml.pack_path("/x/我的影片.mp4", "en"))
      == "我的影片.en.srt")
check("可指定輸出資料夾",
      ml.pack_path("/x/影片.mp4", "ja", "/out") == "/out/影片.ja.srt")
check("沒有副檔名的來源也能用",
      os.path.basename(ml.pack_path("/x/影片", "ko")) == "影片.ko.srt")

# ===== 8. 報告排版 =====
text = ml.format_pack_report(
    {"en": cues, "ja": cues}, ["en", "ja"],
    {"en": "/out/影片.en.srt", "ja": "/out/影片.ja.srt"})
check("報告有標題", "多語字幕包" in text)
check("報告逐語言列出句數", "4 句" in text)
check("報告列出輸出檔名", "影片.en.srt" in text)
check("報告用中文語言名稱", "英文" in text and "日文" in text)
check("報告總結完成數", "2/2 個語言完成" in text)
check("報告提醒是單語檔可直接上傳", "單語" in text and "YouTube Studio" in text)

partial = ml.format_pack_report(
    {"en": cues}, ["en", "ja"], {"en": "/out/影片.en.srt"},
    {"ja": "API 逾時"})
check("失敗的語言標示叉號", "✘" in partial)
check("失敗原因如實顯示", "API 逾時" in partial)
check("失敗不影響完成數統計", "1/2 個語言完成" in partial)
check("失敗時提示可單獨重跑", "可單獨重跑" in partial)

empty = ml.format_pack_report({}, [])
check("沒有語言時說明原因", "沒有指定任何目標語言" in empty)
check("沒有語言時指出該設哪裡",
      "multilang.languages" in empty and "--languages" in empty)
check("報告不使用 Markdown（tk.Text 會原樣顯示星號）",
      "**" not in text and "**" not in partial and "**" not in empty)

# ===== 9. 設定檔預設值 =====
from config import DEFAULT_CONFIG

check("config 有 multilang 區段", "multilang" in DEFAULT_CONFIG)
check("config 預設值與模組一致",
      DEFAULT_CONFIG["multilang"] == ml.DEFAULT_MULTILANG,
      str(DEFAULT_CONFIG["multilang"]))

# ===== 10. CLI 介面 =====
import cli
import inspect

parser = cli.build_parser()
args = parser.parse_args(["--multilang", "x.mp4"])
check("CLI 有 --multilang", args.multilang is True)
check("--languages 預設為 None", args.languages is None)
check("--languages 可指定",
      parser.parse_args(["--multilang", "--languages", "en,ja",
                         "x.mp4"]).languages == "en,ja")
check("cli 匯入了 resolve_translate_settings（否則會 NameError）",
      hasattr(cli, "resolve_translate_settings"))

src = inspect.getsource(cli._export_multilang)
check("CLI 沒有金鑰時明確報錯而不是靜靜跳過", "API 金鑰" in src)
check("CLI 單一語言失敗不中斷其他語言", "failed[language]" in src)
check("CLI 重用既有的 exporter.export", "export(" in src)
check("CLI 會把原文語言傳給選語言邏輯", "source_language" in src)

# ===== 11. 回歸：本模組不重新實作翻譯 =====
mod_src = inspect.getsource(ml)
check("multilang 呼叫既有的 translate_texts",
      "translate_texts" in mod_src)
check("multilang 沒有自己打 API",
      "openai" not in mod_src and "OpenAI" not in mod_src)
check("multilang 零 GUI 依賴",
      "tkinter" not in mod_src and "import gui" not in mod_src)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.43.0 測試全數通過。")
