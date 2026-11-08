# -*- coding: utf-8 -*-
"""
3.0 第 11 項第六階段：生成字幕的核心（subtitle/pipeline.py 的 generate_cues／generation_plan）。

Whisper 模型下載被容器的出口政策擋住（不繞過），所以放一個假的 whisper 模組進 sys.modules：
轉寫走的是真的 `subtitle/transcriber.py` 程式內那條路（載模型、帶語言與提示詞、讀真的音檔長度、
整理逐字結果），只有「聽」這一步是假的。

1. 語音轉寫：模型與語言照設定傳給 Whisper（auto 不傳語言）；生出來的字幕跟一鍵流程的一模一樣
   （兩邊共用 generate_cues）；自動修正詞庫照套、回報改了幾處；進度一路往上、最後到 1。
2. 文字稿對齊：講稿當提示詞傳給 Whisper；講稿空白不跑。
3. 什麼都沒聽到：說清楚（不是生出空字幕）。
4. generation_plan：本地什麼都不送；OpenAI 寫明送聲音（對齊時連講稿、有提示詞時連提示詞）；
   沒金鑰看得出來；語言的中文名稱。
5. 語言清單跟一般版「轉寫設定」的選單是同一份代碼。
"""
import copy
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as config_mod  # noqa: E402
from subtitle import pipeline  # noqa: E402
from subtitle.segmenter import build_cues_from_words  # noqa: E402
from subtitle.transcriber import LANGUAGE_LABELS  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


# ----- 4、5 不需要 ffmpeg -----
base = copy.deepcopy(config_mod.DEFAULT_CONFIG)
local = pipeline.generation_plan(base)
check("本地 Whisper：什麼都不送、模型照設定", local["api"] is False and local["sends"] == []
      and local["model"] == base["transcription"]["model"], str(local))
api_cfg = copy.deepcopy(base)
api_cfg["transcription"].update(use_api=True, api_key=" sk-test ", language="ja")
plan = pipeline.generation_plan(api_cfg)
check("OpenAI：寫明送聲音、有金鑰、語言是日文", plan["api"] and plan["has_key"] and plan["sends"] == ["影片的聲音"]
      and plan["language"] == "ja" and plan["language_label"] == "日文", str(plan))
check("OpenAI＋文字稿對齊：講稿也會送", pipeline.generation_plan(api_cfg, "align")["sends"]
      == ["影片的聲音", "文字稿（當提示詞，幫辨識用對字）"])
api_cfg["transcription"]["prompt"] = "專有名詞"
check("OpenAI＋轉寫設定有提示詞：提示詞也會送", pipeline.generation_plan(api_cfg)["sends"]
      == ["影片的聲音", "轉寫設定裡的提示詞"])
api_cfg["transcription"]["api_key"] = "  "
check("OpenAI 沒金鑰（空白不算）：看得出來", pipeline.generation_plan(api_cfg)["has_key"] is False)
local_prompt = copy.deepcopy(base)
local_prompt["transcription"]["prompt"] = "專有名詞"
check("本地＋提示詞：照樣什麼都不送", pipeline.generation_plan(local_prompt, "align")["sends"] == [])
check("沒設語言：自動偵測", pipeline.generation_plan({})["language_label"] == "自動偵測")

with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui", "app.py"),
          encoding="utf-8") as fh:
    tk_source = fh.read()
tk_values = re.search(r'values=\["auto", [^\]]*\]', tk_source)
tk_codes = re.findall(r'"([^"]+)"', tk_values.group(0)) if tk_values else []
check("語言清單跟一般版轉寫設定的選單同一份代碼", tk_codes and set(tk_codes) == set(LANGUAGE_LABELS)
      and list(LANGUAGE_LABELS)[0] == "auto", str(tk_codes))

if not shutil.which("ffmpeg"):
    print("SKIP 這個環境沒有 ffmpeg：略過真的跑轉寫的那幾項")
else:
    tmp = tempfile.mkdtemp()
    wav = os.path.join(tmp, "訪談.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=200:sample_rate=16000:d=6",
                    wav], check=True)

    calls = []
    heard = {"segments": [
        {"start": 0.0, "end": 2.4, "text": "大家好今天聊剪輯", "words": [
            {"word": "大家好", "start": 0.0, "end": 0.9}, {"word": "今天", "start": 0.9, "end": 1.4},
            {"word": "聊剪輯", "start": 1.4, "end": 2.4}]},
        {"start": 3.5, "end": 5.6, "text": "先講世界為什麼要字幕", "words": [
            {"word": "先講", "start": 3.5, "end": 4.0}, {"word": "世界", "start": 4.0, "end": 4.5},
            {"word": "為什麼", "start": 4.5, "end": 5.0}, {"word": "要字幕", "start": 5.0, "end": 5.6}]},
    ]}

    class FakeModel:
        def __init__(self, name):
            self.name = name

        def transcribe(self, path, **kwargs):
            calls.append((self.name, path, kwargs))
            return copy.deepcopy(fake["result"])

    fake = {"result": heard}
    whisper = types.ModuleType("whisper")
    whisper.load_model = lambda name: FakeModel(name)
    sys.modules["whisper"] = whisper

    cfg = copy.deepcopy(base)
    cfg["transcription"].update(model="small", language="en", use_cache=False)
    cfg["corrections"] = [{"find": "世界", "replace": "世間", "case": False}]
    progress = []
    cues, corrected = pipeline.generate_cues(wav, cfg, report=lambda m, r=None: progress.append((m, r)))
    check("模型與語言照設定傳給 Whisper（要逐字時間）", len(calls) == 1 and calls[0][0] == "small"
          and calls[0][1] == wav and calls[0][2].get("language") == "en"
          and calls[0][2].get("word_timestamps") is True, str(calls))
    words = [{"word": w["word"], "start": w["start"], "end": w["end"]}
             for seg in heard["segments"] for w in seg["words"]]
    want = build_cues_from_words(words, cfg["segmentation"])
    check("斷句照一般的規則（同一套 build_cues_from_words），再套自動修正",
          [c["start"] for c in cues] == [c["start"] for c in want] and len(cues) >= 2
          and "".join(c["text"] for c in cues).replace("\n", "").replace(" ", "")
          == "".join(c["text"] for c in want).replace("\n", "").replace(" ", "").replace("世界", "世間"),
          f"{cues}\n{want}")
    check("自動修正詞庫：改了 1 處、字幕裡沒有「世界」", corrected == 1
          and not any("世界" in c["text"] for c in cues) and any("世間" in c["text"] for c in cues))
    ratios = [r for _m, r in progress if r is not None]
    check("進度一路往上、最後到 1；有寫斷句與自動修正", ratios == sorted(ratios) and ratios[-1] == 1.0
          and any("智慧斷句" in m for m, _r in progress) and any("自動修正 1 處" in m for m, _r in progress),
          str(progress))

    # 跟一鍵流程比：兩邊共用 generate_cues，生出來的一模一樣
    auto_cfg = copy.deepcopy(cfg)
    auto_cfg["automation"] = dict(auto_cfg.get("automation") or {}, export_srt=True, export_vtt=False,
                                  export_ass=False, export_txt=False, burn_video=False, output_dir=tmp)
    result = pipeline.run_pipeline(wav, auto_cfg)
    check("跟一鍵流程生出來的字幕一模一樣", result["cues"] == cues and len(result["exports"]) == 1)

    calls.clear()
    cfg["transcription"]["language"] = "auto"
    pipeline.generate_cues(wav, cfg)
    check("語言是自動偵測：不傳語言給 Whisper", calls and "language" not in calls[0][2], str(calls))

    # ----- 2. 文字稿對齊 -----
    calls.clear()
    script = "大家好今天聊剪輯\n先講為什麼要字幕"
    aligned, _n = pipeline.generate_cues(wav, cfg, "align", script)
    check("文字稿對齊：講稿當提示詞傳給 Whisper、字幕照講稿的字", calls and "聊剪輯" in calls[0][2].get("initial_prompt", "")
          and aligned and "".join(c["text"] for c in aligned).replace("\n", "").replace(" ", "")
          == script.replace("\n", ""), f"{calls}\n{aligned}")
    calls.clear()
    try:
        pipeline.generate_cues(wav, cfg, "align", "  \n ")
        empty_error = ""
    except ValueError as exc:
        empty_error = str(exc)
    check("講稿空白：不跑、說需要文字稿", "需要文字稿" in empty_error and calls == [])

    # ----- 3. 什麼都沒聽到 -----
    fake["result"] = {"segments": [{"start": 0.0, "end": 1.0, "text": " ", "words": []}]}
    try:
        pipeline.generate_cues(wav, cfg)
        silent_error = ""
    except RuntimeError as exc:
        silent_error = str(exc)
    check("什麼都沒聽到：說清楚（不是生出空字幕）", "未取得任何文字" in silent_error, silent_error)
    del sys.modules["whisper"]

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 生成字幕核心測試全數通過。")
