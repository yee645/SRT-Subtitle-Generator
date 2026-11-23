# -*- coding: utf-8 -*-
"""
Qt 版的「有新版本」提示（3.0 第 11 項第三十階段）。

一般版的 `updater.py` 查到新版之後會下載單一 `SRT-Subtitle-Generator.exe`、就地替換自己。Qt 版打包成 onedir
（一整個資料夾，見 ROADMAP 第 0 項），那一套替換不能用；資料夾版的自動下載與切換要跟 3.0.0 的發版產出物一起設計
（第 12 項之前），所以這裡**只做提示**：查到比目前新的版本，就告訴使用者、給 Release 頁面的連結，讓他自己下載。

為什麼不直接 import `updater`：
- `updater.check_for_update` 找不到 exe 附件就當作「沒有新版」（Qt 版要的是 Release 頁面，不是 exe）；
- 改 `updater.py` 會觸發 `release.yml` 的發版流程（路徑觸發），純 Qt 預覽版的進度不能碰它。
所以這裡自己解析同一個 API 的回應；版本比較的規則跟 `updater._parse_version` 一樣（測試會比對）。

**會送出去的**：一個向 GitHub API（`api.github.com`）查最新 Release 的一般連線請求（帶固定的 User-Agent），不含任何
檔案、字幕、設定或帳號資訊。查不到（離線、被擋、API 異常）一律當作沒有新版，不打擾使用者。

零 GUI 依賴、不 import config。
"""
from __future__ import annotations

import json
import urllib.request
from typing import Callable, Optional

from subtitle import onedirupdate

GITHUB_OWNER = "yee645"
GITHUB_REPO = "SRT-Subtitle-Generator"
API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
QT_ZIP_PREFIX = "SRT-Subtitle-Generator-Qt"  # 發版時附的 Qt 預覽版 zip（release.yml 的 qt-preview 工作）
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "SRT-Subtitle-Generator"}
SENDS = "啟動時會向 GitHub 查一次最新版本：只送出一般的連線請求，不含任何檔案、字幕、設定或帳號資訊。"


def parse_version(text) -> tuple:
    """版本字串（可能帶 v 前綴）轉成數字 tuple；規則跟一般版 `updater._parse_version` 一樣。"""
    text = (text or "").strip().lstrip("vV")
    parts = []
    for piece in text.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)


def newer_release(data, current: str) -> Optional[dict]:
    """
    GitHub「最新 Release」的回應比目前新的話，回傳 {"version", "page", "notes", "qt_zip", "qt_asset"}；不比較新、格式不對回 None。

    `page` 是那一版的 Release 頁面（回應裡沒有就用「最新 Release」的固定網址）；`qt_zip` 是 Qt 預覽版 zip 的檔名
    （那一版有附的話），讓提示可以講「下載哪一個」；`qt_asset` 是資料夾版自動更新能下載的 zip
    （`onedirupdate.pick_zip`：Windows 版、網址是這個專案自己的 Release 附件；沒有就 None）。
    """
    if not isinstance(data, dict):
        return None
    if data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    if not tag or parse_version(tag) <= parse_version(current):
        return None
    page = str(data.get("html_url") or "")
    if not page.startswith("https://github.com/"):
        page = RELEASES_PAGE  # 只開 GitHub 自己的頁面
    qt_zip = ""
    for asset in data.get("assets") or []:
        name = str((asset or {}).get("name") or "")
        if name.startswith(QT_ZIP_PREFIX) and name.endswith(".zip"):
            qt_zip = name
            break
    return {"version": tag, "page": page, "notes": str(data.get("body") or ""), "qt_zip": qt_zip,
            "qt_asset": onedirupdate.pick_zip(data)}


def fetch_latest(current: str, timeout: float = 8,
                 opener: Optional[Callable] = None) -> Optional[dict]:
    """查 GitHub 最新 Release，有比 `current` 新的就回傳 `newer_release` 的結果；查不到一律 None。"""
    opener = opener or urllib.request.urlopen
    try:
        request = urllib.request.Request(API_URL, headers=HEADERS)
        with opener(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 —— 離線、被擋、API 異常：當作沒有新版，不打擾使用者
        return None
    return newer_release(data, current)


def should_notify(info: Optional[dict], skipped: str = "") -> bool:
    """要不要提示：有新版、而且不是使用者按過「這版不再提醒」的那一版（更新的版本還是會提示）。"""
    if not info:
        return False
    return not (skipped and parse_version(skipped) >= parse_version(info["version"]))


def notice_text(info: dict, current: str) -> str:
    """提示列那一句。"""
    where = f"下載 {info['qt_zip']}" if info.get("qt_zip") else "下載新版"
    return (f"有新版本 {info['version']}（目前 v{str(current).lstrip('vV')}）。Qt 預覽版還不能自動更新："
            f"按「開啟下載頁」到 GitHub {where}，解壓到新的資料夾，再把舊資料夾裡的 config.json（設定）與 tools"
            "（一鍵安裝的 ffmpeg、文字辨識）搬過去。")


def auto_notice_text(info: dict, current: str) -> str:
    """能自動更新時（打包好的 Windows 資料夾版、這一版有附 zip）提示列那一句。"""
    size = int((info.get("qt_asset") or {}).get("size") or 0)
    about = f"（約 {size / 1e6:.0f} MB）" if size else ""
    return (f"有新版本 {info['version']}（目前 v{str(current).lstrip('vV')}）。按「下載並安裝」會從 GitHub 下載新版{about}，"
            "準備好之後，關掉程式時自動換上新版並重新開啟；設定、生字本與一鍵安裝的工具會一起帶過去，"
            "舊版留到新版開起來才刪。")


def progress_text(done: int, total: int) -> str:
    """下載中的提示：有總數講百分比與 MB，沒有就只講 MB。"""
    if total > 0:
        pct = min(100, int(done * 100 / total))
        return f"正在下載新版 {pct}%（{done / 1e6:.1f}／{total / 1e6:.1f} MB）…可以按「取消下載」。"
    return f"正在下載新版（{done / 1e6:.1f} MB）…可以按「取消下載」。"


READY_TEXT = ("新版已經準備好：關掉程式時會自動換上新版並重新開啟（也可以按「現在重新開啟」）。"
              "換上之前會先等程式完全關掉；換不過去會照樣開回目前這一版。")
PREPARING_TEXT = "下載完成，正在解壓並帶上設定與工具…"
