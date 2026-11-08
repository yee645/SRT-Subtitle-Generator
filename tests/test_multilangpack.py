# -*- coding: utf-8 -*-
"""
3.0 第 11 項第七階段：多語字幕包的共用段（subtitle/multilang.py 的 pack_summary／write_language_pack）。

一般版、CLI、3.0 都呼叫 write_language_pack；翻譯用假的 translate_texts（不連網）。

1. pack_summary：每個語言送幾句（去重後）、幾個字（不算換行）、全部加起來幾個字；空白句不算。
2. write_language_pack：每個語言一個讀得回來的單語 SRT（影片.語言.srt），樣式照給的；
   某個語言失敗不中斷其他；進度跨整批一路往上、寫第幾個語言。
3. 停止（progress_cb 丟 PackStopped）：正在翻的那個不存、後面的不做；已經存好的照樣留著；
   最後一個存好之後才停：照實算存好了。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import multilang as ml  # noqa: E402
from subtitle.importer import load_subtitle_file  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


cues = [{"start": 0.5, "end": 1.5, "text": "大家好"}, {"start": 2.0, "end": 2.5, "text": "對"},
        {"start": 3.0, "end": 4.5, "text": "上面一行\n下面"}, {"start": 5.0, "end": 5.5, "text": "對"},
        {"start": 6.0, "end": 6.5, "text": "  "}]

# ----- 1. pack_summary -----
s = ml.pack_summary(cues, ["en", "ja"])
check("去重：3 句、10 個字（不算換行、空白句不算）、2 個語言、共 20 個字",
      s == {"lines": 3, "chars": 10, "languages": 2, "total_chars": 20}, str(s))
check("不去重：4 句、11 個字", ml.pack_summary(cues, ["en"], dedupe=False)
      == {"lines": 4, "chars": 11, "languages": 1, "total_chars": 11})
check("沒有語言、沒有字幕：都是 0", ml.pack_summary([], []) == {"lines": 0, "chars": 0, "languages": 0, "total_chars": 0}
      and ml.pack_summary(None, None)["total_chars"] == 0)

# ----- 2. write_language_pack -----
calls = []


def fake_translate(texts, language, api_key, progress_cb=None, batch_size=30):
    calls.append((language, list(texts)))
    if progress_cb:
        progress_cb(0.0, "正在翻譯字幕（第 1/1 批）...")
    if language == "ja":
        raise RuntimeError("假的 ja 失敗")
    if progress_cb:
        progress_cb(1.0, "字幕翻譯完成")
    return [f"[{language}]{t}" for t in texts]


real = ml.translate_texts
ml.translate_texts = fake_translate
out = tempfile.mkdtemp()
progress = []
result = ml.write_language_pack(cues[:4], ["en", "ja", "ko"], "KEY", "/片/訪談.mp4", out, dedupe=True,
                                progress_cb=lambda r, m: progress.append((r, m)))
check("en、ko 存好；ja 失敗寫原因；沒停", sorted(result["paths"]) == ["en", "ko"]
      and result["failed"] == {"ja": "假的 ja 失敗"} and result["stopped"] is False and result["skipped"] == [],
      str(result["failed"]))
check("檔名是 影片.語言.srt、放在給的資料夾", result["paths"]["en"] == os.path.join(out, "訪談.en.srt")
      and not os.path.exists(os.path.join(out, "訪談.ja.srt")))
en = load_subtitle_file(result["paths"]["en"])["cues"]
check("讀得回來的單語字幕、時間不變", [c["text"] for c in en] == [f"[en]{c['text']}" for c in cues[:4]]
      and [c["start"] for c in en] == [c["start"] for c in cues[:4]] and result["pack"]["en"] == [
          dict(c, text=f"[en]{c['text']}") for c in cues[:4]], str(en))
check("去重：每個語言只送 3 句", [len(t) for _l, t in calls] == [3, 3, 3])
ratios = [r for r, _m in progress]
check("進度跨整批一路往上、到 1、寫第幾個語言", ratios == sorted(ratios) and ratios[-1] == 1.0
      and progress[0][1].startswith("[1/3] 英文：") and any(m.startswith("[3/3]") for _r, m in progress)
      and any("存好 訪談.ko.srt" in m for _r, m in progress), str(progress))

# ----- 3. 停止 -----
calls.clear()
out2 = tempfile.mkdtemp()


def stop_in_second(ratio, message):
    if message.startswith("[2/3]") and "第 1/1 批" in message:
        raise ml.PackStopped()


stopped = ml.write_language_pack(cues[:4], ["en", "ko", "fr"], "KEY", "訪談.mp4", out2, progress_cb=stop_in_second)
check("第二個語言翻到一半停：第一個留著、第二個沒存、第三個沒做", stopped["stopped"] is True
      and list(stopped["paths"]) == ["en"] and stopped["skipped"] == ["ko", "fr"]
      and os.path.exists(os.path.join(out2, "訪談.en.srt")) and not os.path.exists(os.path.join(out2, "訪談.ko.srt"))
      and [lang for lang, _t in calls] == ["en", "ko"], str(stopped))


def stop_after_saved(ratio, message):
    if "存好" in message:
        raise ml.PackStopped()


late = ml.write_language_pack(cues[:4], ["de"], "KEY", "訪談.mp4", out2, progress_cb=stop_after_saved)
check("最後一個存好之後才停：照實算存好了、沒有沒做的", late["stopped"] is True and list(late["paths"]) == ["de"]
      and late["skipped"] == [] and os.path.exists(os.path.join(out2, "訪談.de.srt")), str(late))
ml.translate_texts = real

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 多語字幕包共用段測試全數通過。")
