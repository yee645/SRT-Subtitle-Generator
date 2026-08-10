# -*- coding: utf-8 -*-
"""
自動更新模組。

啟動時向 GitHub Releases 查詢最新版本，若有新版即可下載並就地替換
目前執行中的 exe。僅在打包成 exe（凍結）的情況下能實際替換程式檔。
"""

import json
import os
import sys
import urllib.request

# 目前程式版本，每次發布新版時須同步調整。
APP_VERSION = "1.37.0"

# GitHub 儲存庫資訊。
GITHUB_OWNER = "yee645"
GITHUB_REPO = "SRT-Subtitle-Generator"
# Release 中 exe 附件的固定檔名。
ASSET_NAME = "SRT-Subtitle-Generator.exe"

_API_URL = (f"https://api.github.com/repos/{GITHUB_OWNER}/"
            f"{GITHUB_REPO}/releases/latest")
_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "SRT-Subtitle-Generator",
}


def _parse_version(text):
    """把版本字串（可能帶 v 前綴）轉成數字 tuple，方便比較大小。"""
    text = (text or "").strip().lstrip("vV")
    parts = []
    for piece in text.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)


def check_for_update(timeout=8):
    """
    查詢 GitHub 最新版本。

    回傳 dict {"version", "url", "notes"}；
    無新版、無網路或查詢失敗時皆回傳 None（不影響程式使用）。
    """
    try:
        request = urllib.request.Request(_API_URL, headers=_HEADERS)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        # 連線失敗、無網路、API 異常等一律視為無更新。
        return None

    latest = data.get("tag_name", "")
    if _parse_version(latest) <= _parse_version(APP_VERSION):
        return None

    # 找出 exe 附件的下載連結。
    download_url = None
    for asset in data.get("assets", []):
        if asset.get("name") == ASSET_NAME:
            download_url = asset.get("browser_download_url")
            break
    if not download_url:
        return None

    return {
        "version": latest,
        "url": download_url,
        "notes": data.get("body", "") or "",
    }


def download_and_apply(download_url, progress_cb=None):
    """
    下載新版 exe 並就地替換目前執行中的 exe。

    參數：
        download_url: 新版 exe 的下載連結。
        progress_cb: 可選的進度回呼，接受 0.0~1.0 的下載比例。
    完成後需重新啟動程式才會套用新版。僅在打包成 exe 時可用。
    """
    if not getattr(sys, "frozen", False):
        raise RuntimeError("自動更新僅在打包後的 exe 版本可用。")

    current_exe = sys.executable
    new_path = current_exe + ".new"
    old_path = current_exe + ".old"

    # 下載新版到暫存檔。
    try:
        request = urllib.request.Request(download_url, headers=_HEADERS)
        with urllib.request.urlopen(request, timeout=60) as response:
            total = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            with open(new_path, "wb") as fp:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    fp.write(chunk)
                    downloaded += len(chunk)
                    if callable(progress_cb) and total > 0:
                        progress_cb(downloaded / total)
    except Exception as exc:
        if os.path.exists(new_path):
            try:
                os.unlink(new_path)
            except OSError:
                pass
        raise RuntimeError(f"下載新版本失敗：{exc}") from exc

    # 就地替換：Windows 允許重新命名執行中的 exe。
    # 先把目前 exe 改名保留，再把新檔放回原本路徑。
    try:
        if os.path.exists(old_path):
            os.unlink(old_path)
        os.rename(current_exe, old_path)
        os.rename(new_path, current_exe)
    except OSError as exc:
        raise RuntimeError(f"替換程式檔失敗：{exc}") from exc


def cleanup_old_version():
    """清除上次更新後遺留的舊版 exe 檔（每次啟動時呼叫）。"""
    if not getattr(sys, "frozen", False):
        return
    old_path = sys.executable + ".old"
    if os.path.exists(old_path):
        try:
            os.unlink(old_path)
        except OSError:
            # 舊檔可能仍被佔用，刪除失敗不影響程式運作。
            pass
