# -*- coding: utf-8 -*-
"""
3.0 第 11 項第三階段：翻譯字幕的核心（subtitle/translator.py 的 outgoing_summary，以及翻譯結果
走 cueedit.EditHistory.record_cues 整批復原）。

1. outgoing_summary：只算字幕文字——有字的句數、字數（換行不算）；空的與只有空白的句子不算句數。
2. 翻譯（替身 openai，不連網）：雙語是「原文\\n譯文」、只留譯文是譯文；逐字時間軸拿掉；
   送出去的只有文字（請求內容裡沒有時間、沒有其他欄位）。
3. 整批復原：record_cues 記下翻譯前後，復原一步回到原本的文字，逐字時間軸也回來；重做再翻回去。
"""
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


sent = []


class _Completions:
    def create(self, model=None, messages=None):
        batch = json.loads(messages[-1]["content"])
        sent.append({"model": model, "messages": messages})
        content = json.dumps(["EN:" + t for t in batch], ensure_ascii=False)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))])


class _OpenAI:
    def __init__(self, api_key=None):
        self.chat = types.SimpleNamespace(completions=_Completions())


fake = types.ModuleType("openai")
fake.OpenAI = _OpenAI
sys.modules["openai"] = fake

from subtitle import cueedit, translator  # noqa: E402

# ----- 1. outgoing_summary -----
cues = [{"start": 0.5, "end": 2.0, "text": "大家好", "words": [{"start": 0.5, "end": 1.0, "word": "大家"},
                                                              {"start": 1.0, "end": 2.0, "word": "好"}]},
        {"start": 3.0, "end": 5.0, "text": "上面一行\n下面"},
        {"start": 6.0, "end": 7.0, "text": "Hi"}]
check("三句、字數不算換行（3＋6＋2＝11）", translator.outgoing_summary(cues) == {"lines": 3, "chars": 11},
      str(translator.outgoing_summary(cues)))
check("空的與只有空白的句子不算句數", translator.outgoing_summary(cues + [{"text": ""}, {"text": "  "}])["lines"] == 3)
check("沒有字幕：0 句 0 字", translator.outgoing_summary([]) == {"lines": 0, "chars": 0}
      and translator.outgoing_summary(None) == {"lines": 0, "chars": 0})
check("缺 text 欄位不會出錯", translator.outgoing_summary([{"start": 0, "end": 1}]) == {"lines": 0, "chars": 0})

# ----- 2. 翻譯 -----
settings = {"target_language": "en", "mode": "bilingual", "batch_size": 30}
both = translator.translate_cues(cues, settings, "sk-test")
check("雙語：原文在上、譯文在下", [c["text"] for c in both] == ["大家好\nEN:大家好", "上面一行\n下面\nEN:上面一行\n下面",
                                                           "Hi\nEN:Hi"], str([c["text"] for c in both]))
check("逐字時間軸拿掉、時間照舊", "words" not in both[0] and both[0]["start"] == 0.5 and both[0]["end"] == 2.0)
check("原本的清單不動", cues[0]["text"] == "大家好" and "words" in cues[0])
request = json.dumps(sent[-1]["messages"], ensure_ascii=False)
check("送出去的只有文字：沒有時間、沒有逐字資料", json.loads(sent[-1]["messages"][-1]["content"])
      == ["大家好", "上面一行\n下面", "Hi"] and "0.5" not in request and "word" not in request, request)
only = translator.translate_cues(cues, dict(settings, mode="replace"), "sk-test")
check("只留譯文", [c["text"] for c in only] == ["EN:大家好", "EN:上面一行\n下面", "EN:Hi"])

# ----- 3. 整批復原 -----
h = cueedit.EditHistory()
changed = [i for i, (a, b) in enumerate(zip(cues, both)) if a != b]
h.record_cues(changed, [cues[i] for i in changed], [both[i] for i in changed])
back, focus = h.undo(both)
check("復原一步：文字回來、逐字時間軸也回來", back == cues and focus == 0, str(back))
again, _f = h.redo(back)
check("重做：再翻回去", again == both)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 翻譯字幕的核心測試全數通過。")
