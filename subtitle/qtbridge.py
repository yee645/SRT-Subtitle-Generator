# -*- coding: utf-8 -*-
"""
一般版到 3.0 新介面的橋（3.0 第 12 項 12-5）。

現有使用者手上的是 2.x 的單一 exe（Tk 版）。它的自動更新（`updater.py`）只會下載同名的單一 exe、就地替換，
**拿不到** Qt 版那一整個資料夾。3.0.0 的 Release 照樣附一般版的 exe（舊的更新程式靠它），所以使用者會先自動更新
成 3.0.0 的一般版；這一支讓那個一般版提示「3.0 新介面」：

1. **要不要提示**（`bridge_dir`／`should_offer`）：打包好的 Windows 一般版 exe、exe 旁邊還沒有新介面的資料夾、
   使用者沒有勾過「不再提醒」。
2. **提示哪一個**（`offer`）：GitHub「最新 Release」是 **3.0 以後的正式版**、有附資料夾版的 zip（`onedirupdate.pick_zip`）。
   不要求比目前新——一般版更新到 3.0.0 之後，最新版就是自己這一版，正是要提示的時候。3.0 之前附的是預覽版，不提示。
3. **裝**（`install`）：用資料夾版自動更新的同一個核心（`onedirupdate`）下載、安全解壓到 exe 旁邊的
   `SRT-Subtitle-Generator-Qt` 資料夾；**複製**一般版的設定、生字本與一鍵安裝的工具過去（一般版自己的那份不動）。
   新介面沒有在跑，資料夾直接改名就好，不需要切換腳本。
4. **開**（`launch_args`）：開新介面，工作目錄設在新資料夾（設定檔就在那裡；之後它自己會更新自己）。

一般版本身原封不動、隨時可以回去用；兩邊的設定從此各自一份。

**會送出去的**：查最新 Release 的一個連線請求（`api.github.com`）與下載 zip（`github.com` 的 Release 附件），都是
一般的連線請求，不送任何檔案、字幕、設定或帳號資訊。

零 GUI 依賴、不 import config（設定的值由呼叫端傳進來）。
"""
from __future__ import annotations

import json
import os
import shutil
import urllib.request
from typing import Callable, Optional

from subtitle import onedirupdate as odu
from subtitle import updatecheck

TK_EXE_NAME = "SRT-Subtitle-Generator.exe"  # 一般版的單一 exe（跟 updater.ASSET_NAME 一樣，測試比對）
QT_FOLDER = "SRT-Subtitle-Generator-Qt"     # 裝在一般版 exe 旁邊的資料夾名稱（跟打包出來的頂層資料夾同名）
CONFIG_KEY = "qt_bridge"                     # 一般版 config.json 裡記「不再提醒」的地方
NEVER = "never"
MIN_VERSION = (3, 0, 0)                      # 3.0 之前附的是預覽版 zip，不提示

SENDS = ("會向 GitHub 查最新版本、下載新介面的 zip：\n都是一般的連線請求，不送任何檔案、字幕、設定或帳號資訊出去。")
ALREADY = "新介面的資料夾已經在了，不用再裝：{path}"


# ----------------------------------------------------------------------
# 1. 要不要提示
# ----------------------------------------------------------------------
def bridge_dir(frozen, executable: str, platform: str) -> Optional[str]:
    """打包好的 Windows 一般版 exe：回傳 exe 所在的資料夾；從原始碼跑、Linux／macOS、Qt 版的 exe 都回 None。"""
    if not frozen or not str(platform).startswith("win"):
        return None
    if os.path.basename(str(executable or "")).lower() != TK_EXE_NAME.lower():
        return None
    return os.path.dirname(os.path.abspath(executable))


def qt_dir(exe_dir: str) -> str:
    """新介面裝在哪裡：一般版 exe 旁邊的 `SRT-Subtitle-Generator-Qt`。"""
    return os.path.join(os.path.normpath(os.path.abspath(exe_dir)), QT_FOLDER)


def installed_exe(exe_dir: str) -> Optional[str]:
    """新介面已經裝好的話回傳它的 exe。"""
    path = os.path.join(qt_dir(exe_dir), odu.EXE_NAME)
    return path if os.path.isfile(path) else None


def should_offer(exe_dir: Optional[str], remembered) -> bool:
    """要不要查、要不要提示：一般版 exe（`bridge_dir` 有值）、旁邊還沒有新介面的資料夾、沒勾過不再提醒。"""
    if not exe_dir or remembered == NEVER:
        return False
    return not os.path.exists(qt_dir(exe_dir))


# ----------------------------------------------------------------------
# 2. 提示哪一個
# ----------------------------------------------------------------------
def offer(data) -> Optional[dict]:
    """
    「最新 Release」的回應能裝新介面的話，回傳 {"version", "asset", "page"}；不行回 None。

    要 3.0 以後的正式版（不是草稿、不是 prerelease）、有附資料夾版的 zip。不要求比目前新。
    """
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    if not tag or updatecheck.parse_version(tag) < MIN_VERSION:
        return None
    asset = odu.pick_zip(data)
    if not asset:
        return None
    page = str(data.get("html_url") or "")
    if not page.startswith("https://github.com/"):
        page = updatecheck.RELEASES_PAGE
    return {"version": tag, "asset": asset, "page": page}


def fetch_offer(timeout: float = 8, opener: Optional[Callable] = None) -> Optional[dict]:
    """查 GitHub 最新 Release，能裝新介面就回傳 `offer` 的結果；查不到（離線、被擋）一律 None，不打擾使用者。"""
    opener = opener or urllib.request.urlopen
    try:
        request = urllib.request.Request(updatecheck.API_URL, headers=updatecheck.HEADERS)
        with opener(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return offer(data)


def offer_text(info: dict, exe_dir: str) -> str:
    """提示視窗的說明。"""
    size = int((info.get("asset") or {}).get("size") or 0)
    about = f"（約 {size / 1e6:.0f} MB）" if size else ""
    # 一句一行：Tk 的 Label 只在空白處換行，中英混排讓它自己折會折在「Qt」和「版」中間
    return (f"{info['version']} 有全新的介面（Qt版）：一般版的功能都搬過去了，\n"
            "畫面更大、操作更順，之後也能在程式裡直接更新。\n\n"
            f"按「下載並安裝新介面」會從 GitHub 下載新介面{about}，裝在這個資料夾：\n{qt_dir(exe_dir)}\n"
            "設定、生字本與一鍵安裝的工具會複製一份過去。\n\n"
            "一般版不會被刪掉，照樣可以用；兩邊的設定從此各自一份。")


# ----------------------------------------------------------------------
# 3. 裝
# ----------------------------------------------------------------------
def carry(exe_dir: str, config_dir: str, new_dir: str) -> list:
    """
    複製一般版的設定、生字本（在設定檔所在的資料夾，也就是一般版的工作目錄）與工具（exe 旁邊的 `tools`）到新資料夾，
    回傳複製了哪些。新資料夾已經有的不蓋；一般版自己的那份不動（是複製不是搬）。
    """
    copied = []
    for name in odu.CARRY_FILES:
        src, dst = os.path.join(config_dir, name), os.path.join(new_dir, name)
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
            copied.append(name)
    for name in odu.CARRY_DIRS:
        src, dst = os.path.join(exe_dir, name), os.path.join(new_dir, name)
        if os.path.isdir(src) and not os.path.exists(dst):
            shutil.copytree(src, dst, symlinks=False)
            copied.append(name)
    return copied


def install(info: dict, exe_dir: str, config_dir: str, progress: Optional[Callable] = None,
            cancelled: Optional[Callable] = None, preparing: Optional[Callable] = None,
            opener: Optional[Callable] = None) -> str:
    """
    下載、安全解壓到 exe 旁邊、複製設定與工具，回傳新介面的 exe。失敗丟 `onedirupdate.UpdateError`（訊息給使用者看），
    不留下載一半的檔、不留解一半的資料夾。

    progress(已下載, 總共)、cancelled()：跟 `onedirupdate.download` 一樣；preparing()：下載完、開始解壓時呼叫一次
    （這之後不能取消）。
    """
    target = qt_dir(exe_dir)
    if os.path.exists(target):
        raise odu.UpdateError(ALREADY.format(path=target))
    zip_path = odu.download(info.get("asset"), exe_dir, progress=progress, cancelled=cancelled, opener=opener)
    staged = None
    try:
        if preparing:
            preparing()
        staged = odu.extract(zip_path, target, info.get("version") or "new")
        carry(exe_dir, config_dir, staged)
        os.replace(staged, target)
        staged = None
    except OSError as exc:
        raise odu.UpdateError(f"安裝失敗：{exc}") from exc
    finally:
        odu._remove(zip_path)
        if staged and os.path.isdir(staged):
            shutil.rmtree(staged, ignore_errors=True)
    return os.path.join(target, odu.EXE_NAME)


# ----------------------------------------------------------------------
# 4. 開
# ----------------------------------------------------------------------
def launch_args(qt_exe: str) -> tuple:
    """開新介面的（命令列, 工作目錄）：工作目錄＝新資料夾（複製過去的設定檔在那裡）。"""
    return [qt_exe], os.path.dirname(os.path.abspath(qt_exe))


def done_text(qt_exe: str) -> str:
    """裝好之後的說明。"""
    return (f"新介面裝好了：\n{qt_exe}\n\n按「開啟新介面」就能開始用。\n"
            "之後想再開，到那個資料夾雙擊它就好（可以在它上面按右鍵建立捷徑放到桌面）。\n一般版照樣留著。")
