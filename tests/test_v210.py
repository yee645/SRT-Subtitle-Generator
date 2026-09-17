# -*- coding: utf-8 -*-
"""
v2.1.0 測試：剪貼簿監聽（選取即翻譯第二階段）的判斷邏輯。

這個功能的核心風險不是「翻得準不準」，而是**該不該送出去**。監聽開著
時，使用者複製的每一樣東西都會經過篩子；篩錯的兩個方向代價完全不對等：

- **漏翻**（正常英文被當成程式碼／密碼）→ 使用者按一下手動翻譯，沒事。
- **誤送**（密碼、金鑰溜過篩子）→ **把機密送進別人的 API**，救不回來。

所以測試對這兩個方向分開施壓，而且對「誤送」那一側特別兇。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


from subtitle.clipwatch import (DEFAULT_CLIPWATCH, classify_clipboard,
                                format_skip_reason, looks_like_code,
                                looks_like_path_or_url, looks_like_secret,
                                resolve_clipwatch_settings)

# ===== 1. 設定 =======================================================
s = resolve_clipwatch_settings()
check("預設是**關閉**的（監聽剪貼簿等於讀取使用者複製的每樣東西，"
      "必須由他主動打開）", s["enabled"] is False)
check("三個篩子預設都開啟",
      s["skip_secrets"] and s["skip_code"] and s["skip_paths"])
check("輪詢間隔夾限下界", resolve_clipwatch_settings(
    {"clipwatch": {"poll_ms": 1}})["poll_ms"] == 200)
check("輪詢間隔夾限上界", resolve_clipwatch_settings(
    {"clipwatch": {"poll_ms": 999999}})["poll_ms"] == 5000)
check("輪詢間隔非數字時回預設", resolve_clipwatch_settings(
    {"clipwatch": {"poll_ms": "abc"}})["poll_ms"] == DEFAULT_CLIPWATCH["poll_ms"])
check("布林欄位被寫成字串時不會當成 True",
      resolve_clipwatch_settings({"clipwatch": {"enabled": "yes"}})["enabled"]
      is False)
check("使用者打開後設定讀得回來",
      resolve_clipwatch_settings({"clipwatch": {"enabled": True}})["enabled"]
      is True)


# ===== 2. 絕不可以送出去的（誤送＝機密外洩，這一側要最嚴）===========
MUST_SKIP_SECRET = [
    ("sk-proj-A1b2C3d4E5f6G7h8", "OpenAI 金鑰"),
    ("ghp_16CharsOfTokenHere123456", "GitHub token"),
    ("github_pat_11ABCDEFG0abcdefgh", "GitHub fine-grained PAT"),
    ("AKIAIOSFODNN7EXAMPLE", "AWS access key"),
    ("AIzaSyD-ExampleKeyForTesting123", "Google API key"),
    ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", "JWT"),
    ("-----BEGIN RSA PRIVATE KEY-----", "私鑰開頭"),
    ("xoxb-123456789012-abcdefghijkl", "Slack token"),
    ("Tr0ub4dor&3xKcd", "混雜大小寫數字符號的密碼"),
    ("P@ssw0rd123456", "常見密碼樣式"),
    ("a1b2c3d4e5f6g7h8i9j0", "英數混雜長字串"),
]
for text, label in MUST_SKIP_SECRET:
    result = classify_clipboard(text)
    check(f"【不可外洩】{label} 不會被送出", result["translate"] is False,
          f"{text[:24]!r} → {result['reason']}")

# 就算使用者把 skip_secrets 關掉，長得像金鑰的東西仍然要能被辨識出來
# （介面可以據此提醒），只是不再自動擋。
check("looks_like_secret 本身認得出金鑰（與設定開關分離）",
      looks_like_secret("sk-proj-A1b2C3d4E5f6"))


# ===== 3. 不該翻的其他東西 ===========================================
for text, label, reason in [
    ("https://example.com/watch?v=abc123", "網址", "path"),
    ("http://localhost:8080/api", "本機網址", "path"),
    ("C:\\Users\\me\\Videos\\raw.mp4", "Windows 路徑", "path"),
    ("/home/user/videos/raw.mp4", "Unix 路徑", "path"),
    ("~/Documents/script.txt", "家目錄路徑", "path"),
    ("\\\\NAS\\share\\clip.mov", "UNC 路徑", "path"),
    ("def transcribe(path):\n    return whisper.load(path)", "Python", "code"),
    ("const timer = setTimeout(fn, 500);", "JavaScript", "code"),
    ("public static void main(String[] args) {", "Java", "code"),
    ("import os\nimport sys", "import 區塊", "code"),
    ("if (a && b) { return c; }", "條件式", "code"),
    ("<div className=\"box\" />", "JSX", "code"),
]:
    result = classify_clipboard(text)
    check(f"{label} 不會被翻譯", result["translate"] is False, str(result))
    check(f"{label} 的理由正確是「{reason}」", result["reason"] == reason,
          f"實際 {result['reason']}——理由錯了使用者會被誤導")

for text, label in [("這是一段中文字幕內容", "已經是中文"),
                    ("我用的是 Premiere Pro 剪片", "中英夾雜但主體是中文"),
                    ("a", "太短"),
                    ("12345", "純數字"),
                    ("!!!???...", "純標點"),
                    ("", "空的")]:
    result = classify_clipboard(text)
    check(f"{label} 不會被翻譯", result["translate"] is False, str(result))


# ===== 4. 正常英文一定要翻得到（漏翻太多這功能就沒用了）=============
MUST_TRANSLATE = [
    "This is a normal English sentence about video editing.",
    "I define my own style for the subtitles.",
    "Let me import this footage and see how it looks.",
    "The return on investment was surprisingly high.",
    "Click the button and then press Enter to continue.",
    "Premiere Pro is a video editing application.",
    "What do you think about this approach?",
    "She said the class was really helpful for beginners.",
]
for text in MUST_TRANSLATE:
    result = classify_clipboard(text)
    check(f"正常英文會被翻譯：{text[:34]!r}", result["translate"] is True,
          f"被 {result['reason']} 擋掉了——這是漏翻")

# 特別針對「含程式關鍵字的正常英文」——最容易誤判的一類。
for text in ["I define my own rules", "The class starts at nine",
             "Please return the book", "A function of time",
             "Let me import some clips", "It was a public event"]:
    check(f"含關鍵字的正常英文不被當成程式碼：{text!r}",
          not looks_like_code(text))

# 正常英文句子也不可以被當成密碼（有空白就不該命中）。
for text in MUST_TRANSLATE:
    check(f"正常英文不被當成密碼：{text[:28]!r}", not looks_like_secret(text))


# ===== 5. 篩子可以個別關閉 ===========================================
off_secrets = {"clipwatch": {"skip_secrets": False}}
result = classify_clipboard("Tr0ub4dor&3xKcd",
                            resolve_clipwatch_settings(off_secrets))
check("關掉 skip_secrets 後密碼特徵不再被該條擋下",
      result["reason"] != "secret", str(result))
off_code = {"clipwatch": {"skip_code": False}}
result = classify_clipboard("const x = 1;",
                            resolve_clipwatch_settings(off_code))
check("關掉 skip_code 後程式碼不再被該條擋下",
      result["reason"] != "code", str(result))


# ===== 6. 跳過時一定要給看得懂的理由 =================================
# 介面沉默地什麼都不做，跟功能壞掉在使用者眼裡是同一件事。
for text in ["sk-proj-abc123def", "const x = 1;",
             "https://example.com/x", "這是中文", ""]:
    result = classify_clipboard(text)
    message = format_skip_reason(result)
    check(f"跳過 {text[:20]!r} 時有給人看得懂的理由",
          bool(message) and len(message) >= 6, repr(message))
check("要翻譯時給的是進行中的訊息，不是跳過理由",
      "翻譯中" in format_skip_reason(
          classify_clipboard("This is a normal English sentence.")))


print()
if failures:
    print(f"失敗 {len(failures)} 項：" + ", ".join(failures[:6])
          + (" …" if len(failures) > 6 else ""))
    sys.exit(1)
print("v2.1.0 剪貼簿監聽判斷邏輯測試全數通過。")
