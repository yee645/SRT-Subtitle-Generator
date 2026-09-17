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


# ===== 7. Xvfb 下的真實面板行為 ======================================
import tempfile

try:
    import tkinter as tk
except ImportError as exc:
    print(f"SKIP 面板測試（無 tkinter：{exc}）")
else:
    import config as app_config
    _cfg = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    _cfg.write(b'{"whatsnew_seen": "never"}')
    _cfg.close()
    app_config.CONFIG_PATH = _cfg.name
    app = panel = None
    try:
        from gui.app import SrtApp
        from gui.quicktranslate_panel import QuickTranslatePanel
        app = SrtApp()
    except tk.TclError as exc:
        message = str(exc).lower()
        if "display" in message or "connect" in message:
            print(f"SKIP 面板測試（無顯示器：{exc}）")
        else:
            check(f"主視窗開得起來（TclError：{exc}）", False)

    if app is not None:
        app.deiconify()
        for _ in range(30):
            app.update()
        panel = QuickTranslatePanel(app, app.config_data)
        panel.deiconify()
        for _ in range(30):
            app.update()

        submitted = []
        panel._submit = lambda raw, manual: submitted.append((raw, manual))

        def pump(n=8):
            for _ in range(n):
                app.update()

        def setclip(text):
            app.clipboard_clear()
            app.clipboard_append(text)
            pump()

        check("面板預設沒有在監聽剪貼簿",
              panel.clipwatch_var.get() is False and panel._clip_job is None)

        # 打開監聽的當下，剪貼簿裡「本來就躺著」的東西不可以被送出——那
        # 是使用者稍早複製的，不是他「剛複製要翻」的。
        #
        # 這裡刻意用**會通過篩子的正常英文**當測資：用密碼當測資的話，就
        # 算這條規則壞掉也會被篩子擋下來，測試等於在驗篩子而不是驗這條規
        # 則（破壞探針實測證實：把 `_last_clip` 改成 None 時測試照樣通
        # 過）。另外要**明確呼叫一次 `_poll_clipboard()`**——`after()` 排
        # 的 500ms 計時器不會在 `update()` 迴圈裡到期，不主動觸發的話這段
        # 根本沒被執行到。
        setclip("This English was already sitting in the clipboard before.")
        panel.clipwatch_var.set(True)
        panel._on_clipwatch_toggle()
        pump()
        panel._poll_clipboard()
        pump()
        check("開啟監聽時，剪貼簿裡本來就有的內容不會被當成「剛複製的」送出",
              submitted == [], str(submitted))
        check("開啟監聽後有告訴使用者正在監聽",
              "監聽中" in panel.clip_status_var.get(),
              panel.clip_status_var.get())

        setclip("This is a normal English sentence about editing.")
        panel._poll_clipboard()
        pump()
        check("複製正常英文會送出翻譯", len(submitted) == 1, str(submitted))
        check("送出時標記為非手動（沿用自動翻譯那條路徑的去重與快取）",
              submitted and submitted[0][1] is False)

        submitted.clear()
        setclip("ghp_16CharsOfTokenHere123456")
        panel._poll_clipboard()
        pump()
        check("【不可外洩】複製 GitHub token 不會被送出",
              submitted == [], str(submitted))
        check("跳過時狀態列講得出理由（沉默＝使用者以為壞了）",
              "密碼" in panel.clip_status_var.get()
              or "金鑰" in panel.clip_status_var.get(),
              panel.clip_status_var.get())

        submitted.clear()
        setclip("Another normal English sentence here.")
        panel._poll_clipboard()
        pump()
        first = len(submitted)
        panel._poll_clipboard()
        pump()
        panel._poll_clipboard()
        pump()
        check("剪貼簿沒變時不會重複送出（否則每 500ms 打一次 API）",
              len(submitted) == first == 1, f"{first} → {len(submitted)}")

        # 翻譯結果是中文，就算被使用者複製也不會被再翻一次——迴圈防線。
        submitted.clear()
        setclip("這是翻譯出來的中文結果")
        panel._poll_clipboard()
        pump()
        check("翻譯結果（中文）被複製時不會形成翻譯迴圈",
              submitted == [], str(submitted))

        # 收起面板＝停止讀取剪貼簿。
        panel._hide()
        pump()
        check("收起面板就停止監聽（「關掉視窗」＝別再讀我複製的東西）",
              panel._clip_job is None)
        check("勾選狀態保留，不會因為收起面板就被關掉",
              panel.clipwatch_var.get() is True)
        panel.show()
        pump()
        check("重新開窗自動恢復監聽", panel._clip_job is not None)

        submitted.clear()
        panel.clipwatch_var.set(False)
        panel._on_clipwatch_toggle()
        pump()
        setclip("Yet another English sentence to translate.")
        pump()
        check("取消勾選後就算剪貼簿變了也不送出",
              panel._clip_job is None and submitted == [], str(submitted))

        # 設定要寫回 config，下次開程式才記得。
        import json as _json
        with open(_cfg.name, encoding="utf-8") as fp:
            saved = _json.load(fp)
        check("剪貼簿監聽設定有寫回 config.json",
              isinstance(saved.get("clipwatch"), dict)
              and "skip_secrets" in saved["clipwatch"], str(saved.get("clipwatch")))

        # 沒有 API 金鑰時，「監聽剪貼簿」要跟「選取後自動翻譯」一起停用
        # ——否則使用者打開它、複製了東西卻什麼都沒發生，也不知道為什麼。
        # （截圖比對時發現的：當時只停用了後者。）
        has_key = bool(panel._get_api_key())
        check("測試環境確實沒有 API 金鑰（這一段才有意義）", not has_key,
              "有金鑰的話下面兩項驗不到東西")
        if not has_key:
            panel._refresh_api_key_state(force=True)
            pump()
            check("沒有金鑰時「選取後自動翻譯」停用（既有行為）",
                  str(panel.auto_check["state"]) == "disabled")
            check("沒有金鑰時「監聽剪貼簿」也一起停用（不要讓它空轉讀剪貼簿）",
                  str(panel.clip_check["state"]) == "disabled",
                  str(panel.clip_check["state"]))
            check("沒有金鑰時監聽確實停下來了",
                  panel._clip_job is None)

        # 剪貼簿放非文字（圖片）或空的時候不可以把輪詢打斷。
        app.clipboard_clear()
        pump()
        check("剪貼簿空的時候讀取不會拋例外",
              panel._read_clipboard() is None
              or isinstance(panel._read_clipboard(), str))

        panel.destroy()
        app.destroy()
    if os.path.exists(_cfg.name):
        os.unlink(_cfg.name)


print()
if failures:
    print(f"失敗 {len(failures)} 項：" + ", ".join(failures[:6])
          + (" …" if len(failures) > 6 else ""))
    sys.exit(1)
print("v2.1.0 剪貼簿監聽判斷邏輯測試全數通過。")
