# -*- coding: utf-8 -*-
"""
3.0 第 11 項第三十二階段：轉寫設定的規則（subtitle/transcribecfg.py）。

1. 預設值跟設定檔（config.DEFAULT_CONFIG["transcription"]）一樣；模型、語言選項跟一般版下拉一樣。
2. clean_transcription：模型不認得就退回原本的（再不行 base）；語言空白＝auto；文字欄去頭尾空白；勾選是布林；
   缺的欄位用 base／預設；其他鍵留著；不改傳入的。
3. mask_key：空的說還沒填；短的只說幾個字；長的只露頭 3 尾 4（不會露出整把）。
4. sends_text：本地什麼都不送；OpenAI 送聲音（有提示詞時提示詞也送）、照用量收費、沒有金鑰要講。
5. 零 GUI 依賴、不 import config。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from subtitle import transcribecfg as tc  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


# ----- 1 -----
check("預設值跟設定檔一樣", tc.DEFAULTS == config.DEFAULT_CONFIG["transcription"])
gui_src = open(os.path.join(os.path.dirname(config.__file__), "gui", "app.py"), encoding="utf-8").read()
check("模型選項跟一般版一樣", 'values=["tiny", "base", "small", "medium", "large"]' in gui_src
      and tc.MODELS == ("tiny", "base", "small", "medium", "large"))
check("語言選項跟一般版一樣", 'values=["auto", "zh", "zh-TW", "en", "ja", "ko"]' in gui_src
      and tc.LANGUAGES == ("auto", "zh", "zh-TW", "en", "ja", "ko"))

# ----- 2 -----
check("合理的值原樣", tc.clean_transcription(config.DEFAULT_CONFIG["transcription"]) == tc.DEFAULTS)
raw = {"model": " small ", "language": "  ", "use_api": 1, "use_cache": 0, "api_key": "  sk-abc  ",
       "python_path": " C:/py/python.exe ", "prompt": "  剪映 達文西 ", "自訂": "留著"}
out = tc.clean_transcription(raw)
check("去頭尾空白、語言空白＝auto、勾選是布林、其他鍵留著", out == {
    "model": "small", "language": "auto", "use_api": True, "use_cache": False, "api_key": "sk-abc",
    "python_path": "C:/py/python.exe", "prompt": "剪映 達文西", "自訂": "留著"}, str(out))
check("不改傳入的", raw["model"] == " small " and raw["api_key"] == "  sk-abc  ")
check("不認得的模型：退回原本的", tc.clean_transcription({"model": "huge"}, {"model": "medium"})["model"] == "medium")
check("原本的也不認得：base", tc.clean_transcription({"model": "huge"}, {"model": "xl"})["model"] == "base"
      and tc.clean_transcription({"model": None})["model"] == "base")
base = dict(tc.DEFAULTS, api_key="sk-old", use_cache=False, language="ja")
check("缺的欄位：用 base", tc.clean_transcription({}, base) == dict(base))
check("缺的欄位：沒給 base 就用預設", tc.clean_transcription(None) == tc.DEFAULTS)
check("None 的文字欄當空字串", tc.clean_transcription({"api_key": None, "prompt": None})["api_key"] == "")

# ----- 3 -----
key = "sk-proj-1234567890abcdefWXYZ"
masked = tc.mask_key(key)
check("長的金鑰：只露頭 3 尾 4", masked == "sk-…WXYZ" and key[3:-4] not in masked, masked)
check("短的：只說幾個字（不露出）", tc.mask_key("abc123") == "已填（6 個字）" and tc.mask_key("1234567890") == "已填（10 個字）")
check("空的：說還沒填", tc.mask_key("") == "（還沒填）" and tc.mask_key(None) == "（還沒填）" and tc.mask_key("  ") == "（還沒填）")

# ----- 4 -----
local = tc.sends_text({"use_api": False, "api_key": "sk-x", "prompt": "人名"})
check("本地：什麼都不送", "不會送出去" in local and "OpenAI" not in local, local)
api = tc.sends_text({"use_api": True, "api_key": "sk-xxxxxxxxxxxx"})
check("OpenAI：送聲音、照用量收費、檔名字幕不送", "影片的聲音送到 OpenAI" in api and "照用量收費" in api
      and "檔名、字幕與其他檔案不送" in api and "提示詞" not in api and "還沒有金鑰" not in api, api)
api_prompt = tc.sends_text({"use_api": True, "api_key": "sk-xxxxxxxxxxxx", "prompt": " 人名 "})
check("有提示詞：提示詞也送", "影片的聲音與提示詞送到 OpenAI" in api_prompt, api_prompt)
check("沒有金鑰：要講", "還沒有金鑰" in tc.sends_text({"use_api": True}))
check("說明裡金鑰存哪、還用在哪", "config.json" in tc.KEY_STORED and "沒有加密" in tc.KEY_STORED
      and "翻譯字幕" in tc.KEY_USES and "即時查譯" in tc.KEY_USES)

# ----- 5 -----
src = open(tc.__file__, encoding="utf-8").read()
code = [line for line in src.splitlines() if line.startswith(("import ", "from "))]
check("零 GUI 依賴、不 import config", not any(w in " ".join(code) for w in (
    "config", "tkinter", "PySide6", "gui")), str(code))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("轉寫設定規則測試全數通過。")
