# -*- coding: utf-8 -*-
"""
3.0 第 11 項第三十階段：Qt 版的「有新版本」提示——查法（subtitle/updatecheck.py）。

不連網：`fetch_latest` 換掉 opener，餵 GitHub API 的回應格式。

1. 版本比較跟一般版 updater._parse_version 一模一樣（逐一比對）。
2. newer_release：比目前新才回傳；一樣、比較舊、草稿、預先發行、格式不對都是 None；Release 頁面只用 GitHub 自己的網址；
   認得 Qt 預覽版 zip（沒有就空字串）。
3. fetch_latest：打的是 GitHub「最新 Release」API、帶固定 User-Agent、**不送任何資料**（GET、沒有 body）；離線、壞掉的
   JSON、API 異常一律 None。
4. should_notify：沒新版不提示；按過「這版不再提醒」的那一版（或更舊）不提示；更新的版本照樣提示。
5. notice_text：講新舊版本、下載哪個、不能自動更新、要把 config.json 與 tools 搬過去。
6. 零 GUI 依賴、不 import config、不 import updater（改 updater.py 會觸發發版）。
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import updater  # noqa: E402
from subtitle import updatecheck as uc  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


# ----- 1 -----
samples = ["2.3.6", "v2.4.0", "V3.0.0", "2.10", "2.3.6-beta", "", None, "  v1.2 ", "abc", "1..2", "3.0.0rc1"]
check("版本比較跟一般版一模一樣", all(uc.parse_version(t) == updater._parse_version(t) for t in samples),
      str([(t, uc.parse_version(t), updater._parse_version(t)) for t in samples]))
check("2.10 比 2.9 新（不是照字串比）", uc.parse_version("2.10") > uc.parse_version("2.9"))

# ----- 2 -----
release = {"tag_name": "v2.4.0", "html_url": "https://github.com/yee645/SRT-Subtitle-Generator/releases/tag/v2.4.0",
           "body": "新功能", "assets": [{"name": "SRT-Subtitle-Generator.exe"},
                                       {"name": "SRT-Subtitle-Generator-Qt-preview-v2.4.0.zip"}]}
info = uc.newer_release(release, "2.3.6")
check("比目前新：回傳版本、頁面、說明、Qt zip", info == {
    "version": "v2.4.0", "page": release["html_url"], "notes": "新功能",
    "qt_zip": "SRT-Subtitle-Generator-Qt-preview-v2.4.0.zip"}, str(info))
check("一樣、比較舊：None", uc.newer_release(release, "2.4.0") is None and uc.newer_release(release, "v2.5") is None)
check("草稿、預先發行：None", uc.newer_release(dict(release, draft=True), "2.3.6") is None
      and uc.newer_release(dict(release, prerelease=True), "2.3.6") is None)
check("格式不對、沒有版本：None", uc.newer_release(None, "2.3.6") is None and uc.newer_release([], "2.3.6") is None
      and uc.newer_release({"tag_name": ""}, "2.3.6") is None)
check("沒給頁面：用最新 Release 的固定網址", uc.newer_release({"tag_name": "v9"}, "2.3.6")["page"] == uc.RELEASES_PAGE)
check("頁面不是 GitHub 的：不開它，改用固定網址",
      uc.newer_release(dict(release, html_url="https://evil.example/x"), "2.3.6")["page"] == uc.RELEASES_PAGE
      and uc.newer_release(dict(release, html_url="http://github.com/x"), "2.3.6")["page"] == uc.RELEASES_PAGE)
check("沒有 Qt zip：空字串（只有 exe 不算）", uc.newer_release(dict(release, assets=[{"name": "SRT-Subtitle-Generator.exe"}]),
                                              "2.3.6")["qt_zip"] == "")
check("Qt 開頭但不是 .zip（例如校驗檔）不算", uc.newer_release(dict(release, assets=[
    {"name": "SRT-Subtitle-Generator-Qt-preview-v2.4.0.zip.sha256"},
    {"name": "SRT-Subtitle-Generator-Qt-preview-v2.4.0.zip"}]), "2.3.6")["qt_zip"]
    == "SRT-Subtitle-Generator-Qt-preview-v2.4.0.zip")
check("固定網址是這個 repo 的", uc.RELEASES_PAGE == "https://github.com/yee645/SRT-Subtitle-Generator/releases/latest"
      and uc.API_URL == "https://api.github.com/repos/yee645/SRT-Subtitle-Generator/releases/latest")

# ----- 3 -----
seen = []


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_with(payload):
    def opener(request, timeout=None):
        seen.append((request, timeout))
        return FakeResponse(payload)
    return opener


got = uc.fetch_latest("2.3.6", opener=opener_with(json.dumps(release).encode("utf-8")))
req, timeout = seen[0]
check("查到新版：回傳 newer_release 的結果", got == info)
check("打的是最新 Release 的 API、帶固定 User-Agent、有逾時", req.full_url == uc.API_URL
      and req.get_header("User-agent") == "SRT-Subtitle-Generator" and timeout == 8)
check("不送任何資料（GET、沒有 body）", req.data is None and req.get_method() == "GET")
check("沒有新版：None", uc.fetch_latest("9.9.9", opener=opener_with(json.dumps(release).encode("utf-8"))) is None)


def offline(request, timeout=None):
    raise OSError("沒有網路")
check("離線：None（不丟例外）", uc.fetch_latest("2.3.6", opener=offline) is None)
check("壞掉的 JSON：None", uc.fetch_latest("2.3.6", opener=opener_with(b"<html>")) is None)
check("API 回傳錯誤訊息（不是 Release）：None",
      uc.fetch_latest("2.3.6", opener=opener_with(b'{"message": "rate limited"}')) is None)

# ----- 4 -----
check("沒新版不提示", not uc.should_notify(None) and not uc.should_notify(None, "v2.4.0"))
check("沒按過不再提醒：提示", uc.should_notify(info, ""))
check("按過這一版（或更新的）：不提示", not uc.should_notify(info, "v2.4.0") and not uc.should_notify(info, "2.4.0")
      and not uc.should_notify(info, "v2.5.0"))
check("按過的是更舊的版本：照樣提示", uc.should_notify(info, "v2.3.9"))

# ----- 5 -----
text = uc.notice_text(info, "2.3.6")
check("提示：新舊版本、下載哪個", "v2.4.0" in text and "目前 v2.3.6" in text
      and "SRT-Subtitle-Generator-Qt-preview-v2.4.0.zip" in text)
check("提示：講明還不能自動更新、要搬 config.json 與 tools", "還不能自動更新" in text and "config.json" in text
      and "tools" in text and "開啟下載頁" in text)
check("沒有 zip：講下載新版", "下載新版" in uc.notice_text(dict(info, qt_zip=""), "v2.3.6")
      and "目前 v2.3.6" in uc.notice_text(dict(info, qt_zip=""), "v2.3.6"))
check("寫明會送出去的只有查版本的連線請求", "GitHub" in uc.SENDS and "不含任何檔案、字幕、設定或帳號資訊" in uc.SENDS)

# ----- 6 -----
src = open(uc.__file__, encoding="utf-8").read()
code = [line for line in src.splitlines() if line.startswith(("import ", "from "))]
check("零 GUI 依賴、不 import config／updater", not any(w in " ".join(code) for w in (
    "config", "tkinter", "PySide6", "gui", "updater")), str(code))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("Qt 版新版本提示（查法）測試全數通過。")
