# -*- coding: utf-8 -*-
"""v1.18.0 新功能測試：字幕翻譯（雙語字幕），沿用 OpenAI API。"""
import json
import os
import subprocess
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


# ===== 0. 替身 openai 模組：mirror 真實 SDK 的 client.chat.completions.create
#          呼叫形狀（無網路、不裝 openai 套件也能跑完整流程）。 =====

class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self):
        self.calls = []
        self.responder = None

    def create(self, model=None, messages=None):
        user_content = messages[-1]["content"]
        batch = json.loads(user_content)
        self.calls.append(batch)
        if self.responder is None:
            raise RuntimeError("測試未設定 responder")
        return _FakeResponse(self.responder(batch))


_completions = _FakeCompletions()


class _FakeChatNamespace:
    completions = _completions


class FakeOpenAI:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.chat = _FakeChatNamespace()


fake_openai_module = types.ModuleType("openai")
fake_openai_module.OpenAI = FakeOpenAI
sys.modules["openai"] = fake_openai_module

from subtitle import translator
from subtitle.errors import KIND_API_KEY, KIND_NETWORK, describe_exception
from config import DEFAULT_CONFIG

# ===== 1. 基本：3 句中文 cue → 目標英文 → 雙語（原文+譯文上下行） =====
_completions.calls.clear()
_completions.responder = lambda batch: json.dumps(
    [f"EN:{t}" for t in batch], ensure_ascii=False)

cues = [
    {"start": 0.0, "end": 1.0, "text": "你好",
     "words": [{"word": "你", "start": 0.0, "end": 0.5},
               {"word": "好", "start": 0.5, "end": 1.0}]},
    {"start": 1.0, "end": 2.0, "text": "早安"},
    {"start": 2.0, "end": 3.0, "text": "謝謝"},
]
settings = translator.resolve_translate_settings(
    {"translate": {"target_language": "en", "mode": "bilingual"}})
result = translator.translate_cues(cues, settings, "sk-test")

check("雙語模式：原文+譯文上下行", result[0]["text"] == "你好\nEN:你好", result[0]["text"])
check("雙語模式：時間軸保留", result[0]["start"] == 0.0 and result[0]["end"] == 1.0)
check("雙語模式：words 已移除", "words" not in result[0])
check("雙語模式：原始清單未被修改",
      "words" in cues[0] and cues[0]["text"] == "你好")
check("雙語模式：3 句都翻譯", len(result) == 3
      and result[1]["text"] == "早安\nEN:早安"
      and result[2]["text"] == "謝謝\nEN:謝謝")

# ===== 2. 取代模式：text 僅譯文 =====
_completions.calls.clear()
_completions.responder = lambda batch: json.dumps(
    [f"EN:{t}" for t in batch], ensure_ascii=False)
settings_replace = translator.resolve_translate_settings(
    {"translate": {"target_language": "en", "mode": "replace"}})
result_replace = translator.translate_cues(cues, settings_replace, "sk-test")
check("取代模式：text 僅譯文", result_replace[0]["text"] == "EN:你好")
check("取代模式：words 仍已移除", "words" not in result_replace[0])

# ===== 3. 批次：70 句、batch_size 30 → 3 次呼叫，大小 30/30/10 =====
_completions.calls.clear()
_completions.responder = lambda batch: json.dumps(batch, ensure_ascii=False)
texts_70 = [f"句子{i}" for i in range(70)]
out_70 = translator.translate_texts(
    texts_70, "en", "sk-test", batch_size=30)
check("批次：3 次呼叫", len(_completions.calls) == 3, str(len(_completions.calls)))
check("批次：大小 30/30/10",
      [len(c) for c in _completions.calls] == [30, 30, 10],
      str([len(c) for c in _completions.calls]))
check("批次：輸出等長", len(out_70) == 70)

# ===== 4. 容錯：回應含 ```json ... ``` 圍欄仍可解析 =====
_completions.calls.clear()
_completions.responder = lambda batch: (
    "```json\n" + json.dumps([f"X{t}" for t in batch], ensure_ascii=False)
    + "\n```")
out_fence = translator.translate_texts(["a", "b"], "en", "sk-test")
check("code fence 容錯", out_fence == ["Xa", "Xb"], str(out_fence))

# ===== 5. 長度不符：缺漏項目保留原文，不拋例外 =====
_completions.calls.clear()
_completions.responder = lambda batch: json.dumps([f"X{batch[0]}"],
                                                   ensure_ascii=False)
out_short = translator.translate_texts(["a", "b", "c"], "en", "sk-test")
check("長度不符：第一句翻譯", out_short[0] == "Xa", str(out_short))
check("長度不符：其餘沿用原文",
      out_short[1] == "b" and out_short[2] == "c", str(out_short))

# ===== 6. 缺金鑰 → errors.py 歸類為 API 金鑰錯誤 =====
try:
    translator.translate_texts(["a"], "en", "")
    check("缺金鑰擋下", False, "未拋出例外")
except RuntimeError as exc:
    err = describe_exception(exc)
    check("缺金鑰歸入 API 金鑰類", err.kind == KIND_API_KEY, err.kind)

# ===== 7. API 例外 → 訊息以「呼叫 OpenAI API 失敗」開頭並歸類 =====
def _raise_boom(_batch):
    raise ValueError("網路逾時")


_completions.calls.clear()
_completions.responder = _raise_boom
try:
    translator.translate_texts(["a"], "en", "sk-test")
    check("API 例外被包裝", False, "未拋出例外")
except RuntimeError as exc:
    check("API 例外訊息前綴正確", str(exc).startswith("呼叫 OpenAI API 失敗"), str(exc))
    err = describe_exception(exc)
    check("API 例外歸入 network 類", err.kind == KIND_NETWORK, err.kind)

# ===== 8. resolve_translate_settings：預設值／夾限／未知語言退回 =====
check("預設值", translator.resolve_translate_settings(None)
      == translator.DEFAULT_TRANSLATE)
s_bad = translator.resolve_translate_settings({"translate": {
    "mode": "bogus", "target_language": "xx", "batch_size": 999}})
check("夾限與容錯",
      s_bad["mode"] == "bilingual" and s_bad["target_language"] == "en"
      and s_bad["batch_size"] == 80, str(s_bad))
s_low = translator.resolve_translate_settings(
    {"translate": {"batch_size": 1}})
check("batch_size 下限夾限", s_low["batch_size"] == 5, str(s_low))

# ===== 9. 靜態掃描 =====
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dialog_src = open(os.path.join(root, "gui", "translate_dialog.py"),
                  encoding="utf-8").read()
check("翻譯對話框無 classic tk.Checkbutton 殘留",
      "tk.Checkbutton(" not in dialog_src.replace("ttk.Checkbutton(", ""))
check("翻譯對話框無 classic tk.Radiobutton 殘留",
      "tk.Radiobutton(" not in dialog_src.replace("ttk.Radiobutton(", ""))
check("config 含 translate 區", "translate" in DEFAULT_CONFIG
      and DEFAULT_CONFIG["translate"]["target_language"] == "en")
app_src = open(os.path.join(root, "gui", "app.py"), encoding="utf-8").read()
check("app.py 已接上翻譯字幕按鈕",
      "翻譯字幕" in app_src and "_open_translate_dialog" in app_src)

# ===== 10. 真實 ffmpeg 端到端：雙語字幕燒錄 =====
from subtitle.burner import burn_subtitles, ffmpeg_available
from subtitle.media import probe_duration

if ffmpeg_available():
    with tempfile.TemporaryDirectory() as tmp:
        clip = os.path.join(tmp, "src.mp4")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=4",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
             "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
             "-t", "4", clip], capture_output=True, timeout=120)
        check("測試素材產生成功", os.path.exists(clip) and os.path.getsize(clip) > 0)

        bilingual_cues = [
            {"start": 0.5, "end": 3.5, "text": "中文原文\nEnglish translation"},
        ]
        burned = os.path.join(tmp, "burned.mp4")
        burn_subtitles(clip, bilingual_cues, burned, style=None)
        check("雙語燒錄輸出存在", os.path.exists(burned)
              and os.path.getsize(burned) > 0)
        out_dur = probe_duration(burned)
        check("雙語燒錄輸出有時長", out_dur > 3.0, str(out_dur))

        frame_path = os.path.join(tmp, "frame.png")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-ss", "2", "-i", burned, "-frames:v", "1", frame_path],
            capture_output=True, timeout=60)
        check("擷取畫面成功（供人工確認雙語兩行）",
              os.path.exists(frame_path) and os.path.getsize(frame_path) > 0)
else:
    print("SKIP 燒錄實測（無 ffmpeg）")

print()
if failures:
    print(f"共 {len(failures)} 項失敗：{failures}")
    sys.exit(1)
print("test_v1180 全部通過")
