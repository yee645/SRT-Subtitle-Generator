# -*- coding: utf-8 -*-
"""
資料夾版（onedir）的自動更新核心（3.0 第 12 項 12-2）。

一般版的 `updater.py` 下載單一 exe、就地替換自己；Qt 版打包成一整個資料夾（ROADMAP 第 0 項），那一套不能用。
這裡做資料夾版要的四件事，介面（12-3）與一般版的橋（12-5）都呼叫這裡：

1. **挑檔案**：從 GitHub「最新 Release」的回應挑出 Qt 版的 zip；下載網址只收這個專案自己的 Release 附件。
2. **下載**：存到程式資料夾**旁邊**的暫存檔（同一顆磁碟，之後改名才不用跨磁碟搬）；可以回報進度、可以取消；
   大小跟 Release 寫的不一樣就當作下載壞了。
3. **安全解壓**：zip 只能有一個頂層資料夾、裡面要有 exe；擋路徑穿越（`..`）、絕對路徑、磁碟代號、符號連結，
   解開後的總大小有上限（擋壓縮炸彈）。先解到暫存資料夾，全部成功才改名成「`<程式資料夾>.update-<版本>`」。
4. **帶過去＋切換**：把 `config.json`、生字本、`tools`（一鍵安裝的 ffmpeg、文字辨識）複製到新資料夾；
   產生切換腳本（PowerShell）：等目前的程式關掉 → 舊資料夾改名成 `<程式資料夾>.old` → 新資料夾換上 → 開新版
   （工作目錄設在設定檔所在的地方）；換不過去就把舊的換回來、照樣開舊版。舊資料夾留到新版下次啟動時才刪
   （`cleanup_backup`），新版開不起來的話使用者還能自己換回來。

Windows 上執行中的資料夾不能改名，所以切換一定要等程式關掉、由另一個行程做——這是需要腳本的原因。
容器裡驗不到 Windows 的改名行為：腳本的內容在這裡驗，實際切換交給 CI 的 Windows 工作（12-4）。

**會送出去的**：只有向 GitHub 下載 Release 附件的一般連線請求（固定的 User-Agent），不送任何檔案、字幕、
設定或帳號資訊。

零 GUI 依賴、不 import config。
"""
from __future__ import annotations

import os
import shutil
import stat
import tempfile
import urllib.request
import zipfile
from typing import Callable, Optional

GITHUB_OWNER = "yee645"
GITHUB_REPO = "SRT-Subtitle-Generator"
DOWNLOAD_PREFIX = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/"
ZIP_PREFIX = "SRT-Subtitle-Generator-Qt"
ZIP_SUFFIX = "-win64.zip"
EXE_NAME = "SRT-Subtitle-Generator-Qt.exe"
HEADERS = {"User-Agent": "SRT-Subtitle-Generator"}

# 換新資料夾時要帶過去的東西（相對於設定檔所在的資料夾／程式資料夾）
CARRY_FILES = ("config.json", "quicktranslate_vocab.json")
CARRY_DIRS = ("tools",)

MAX_UNPACKED = 2 * 1024 ** 3  # 解開後最多 2 GB（目前的成品約 150 MB）
STAGING_TAG = ".update-"
BACKUP_SUFFIX = ".old"
SENDS = "更新只會向 GitHub 下載新版的 zip：不送任何檔案、字幕、設定或帳號資訊出去。"

NO_ZIP = "這一版沒有附資料夾版的 zip。"
BAD_URL = "下載網址不是這個專案在 GitHub 上的 Release 附件，不下載。"
SIZE_MISMATCH = "下載的大小跟 Release 上寫的不一樣，可能沒下載完整，請再試一次。"
CANCELLED = "已取消下載。"


class UpdateError(Exception):
    """更新做不下去（訊息可以直接給使用者看）。"""


# ----------------------------------------------------------------------
# 1. 挑檔案
# ----------------------------------------------------------------------
def pick_zip(data) -> Optional[dict]:
    """從「最新 Release」的回應挑出 Qt 資料夾版的 zip：{"name", "url", "size"}；沒有（或網址不對）回 None。"""
    if not isinstance(data, dict):
        return None
    for asset in data.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if not (name.startswith(ZIP_PREFIX) and name.endswith(ZIP_SUFFIX)):
            continue
        if not url_allowed(url):
            continue
        try:
            size = int(asset.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        return {"name": name, "url": url, "size": max(size, 0)}
    return None


def url_allowed(url: str) -> bool:
    """只收這個專案自己的 Release 附件（https、github.com、固定的路徑開頭，不能有 ..）。"""
    url = str(url or "")
    return url.startswith(DOWNLOAD_PREFIX) and ".." not in url[len(DOWNLOAD_PREFIX):]


# ----------------------------------------------------------------------
# 2. 下載
# ----------------------------------------------------------------------
def download(asset: dict, dest_dir: str, progress: Optional[Callable] = None,
             cancelled: Optional[Callable] = None, opener: Optional[Callable] = None,
             timeout: float = 60) -> str:
    """
    下載 `pick_zip` 挑出的 zip 到 `dest_dir`（程式資料夾旁邊），回傳檔案路徑。

    progress(已下載, 總共)；cancelled() 回 True 就停（刪掉下載一半的檔、丟 UpdateError(CANCELLED)）。
    大小跟 Release 寫的不一樣也刪掉、丟 UpdateError。
    """
    if not asset or not url_allowed(asset.get("url")):
        raise UpdateError(BAD_URL)
    opener = opener or urllib.request.urlopen
    final = os.path.join(dest_dir, os.path.basename(asset["name"]))
    part = final + ".part"
    expected = int(asset.get("size") or 0)
    done = 0
    try:
        request = urllib.request.Request(asset["url"], headers=HEADERS)
        with opener(request, timeout=timeout) as response, open(part, "wb") as fp:
            total = expected or int(getattr(response, "headers", {}).get("Content-Length", 0) or 0)
            while True:
                if cancelled and cancelled():
                    raise UpdateError(CANCELLED)
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                fp.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if expected and done != expected:
            raise UpdateError(SIZE_MISMATCH)
        os.replace(part, final)
    except UpdateError:
        _remove(part)
        raise
    except Exception as exc:  # noqa: BLE001 —— 斷線、磁碟滿：講原因，不留半個檔
        _remove(part)
        raise UpdateError(f"下載失敗：{exc}") from exc
    return final


# ----------------------------------------------------------------------
# 3. 安全解壓
# ----------------------------------------------------------------------
def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def check_zip(zf: zipfile.ZipFile, exe_name: str = EXE_NAME) -> str:
    """檢查 zip 能不能放心解開，回傳唯一的頂層資料夾名稱；不行就丟 UpdateError（講哪裡不對）。"""
    tops = set()
    total = 0
    has_exe = False
    infos = zf.infolist()
    if not infos:
        raise UpdateError("zip 是空的。")
    for info in infos:
        name = info.filename
        if "\\" in name or name.startswith("/") or (len(name) > 1 and name[1] == ":"):
            raise UpdateError(f"zip 裡有不安全的路徑：{name}")
        parts = [p for p in name.split("/") if p]
        if not parts or any(p in ("..", ".") for p in parts):
            raise UpdateError(f"zip 裡有不安全的路徑：{name}")
        if _is_symlink(info):
            raise UpdateError(f"zip 裡有捷徑（符號連結），不解開：{name}")
        tops.add(parts[0])
        total += max(info.file_size, 0)
        if len(parts) == 2 and parts[1] == exe_name and not info.is_dir():
            has_exe = True
    if len(tops) != 1:
        raise UpdateError("zip 的內容應該只有一個資料夾。")
    if total > MAX_UNPACKED:
        raise UpdateError("zip 解開後太大，不像是這個程式。")
    if not has_exe:
        raise UpdateError(f"zip 裡找不到 {exe_name}。")
    return tops.pop()


def staging_path(app_dir: str, version: str) -> str:
    """新版先放的位置：程式資料夾旁邊的「<程式資料夾>.update-<版本>」。"""
    app_dir = os.path.normpath(os.path.abspath(app_dir))
    version = "".join(ch for ch in str(version or "") if ch.isalnum() or ch in ".-_") or "new"
    return app_dir + STAGING_TAG + version


def backup_path(app_dir: str) -> str:
    """切換時舊資料夾改成的名字：「<程式資料夾>.old」。"""
    return os.path.normpath(os.path.abspath(app_dir)) + BACKUP_SUFFIX


def extract(zip_path: str, app_dir: str, version: str, exe_name: str = EXE_NAME) -> str:
    """
    檢查過再解壓，回傳新版的資料夾（`staging_path`），裡面直接就是 exe。

    先解到同一層的暫存資料夾，全部成功才改名；之前沒切換成功留下的同名資料夾先清掉。
    """
    target = staging_path(app_dir, version)
    parent = os.path.dirname(target)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            top = check_zip(zf, exe_name)
            work = tempfile.mkdtemp(prefix=".unpack-", dir=parent)
            try:
                zf.extractall(work)
                unpacked = os.path.join(work, top)
                if os.path.exists(target):
                    shutil.rmtree(target)
                os.replace(unpacked, target)
            finally:
                shutil.rmtree(work, ignore_errors=True)
    except zipfile.BadZipFile as exc:
        raise UpdateError("下載的檔案不是完整的 zip，請再試一次。") from exc
    except OSError as exc:
        raise UpdateError(f"解壓失敗：{exc}") from exc
    return target


# ----------------------------------------------------------------------
# 4. 帶過去＋切換
# ----------------------------------------------------------------------
def carry_over(app_dir: str, config_dir: str, new_dir: str) -> list:
    """
    把設定、生字本、tools 複製到新資料夾，回傳複製了哪些（相對名稱）。

    只搬**放在程式資料夾裡**的：設定檔不在程式資料夾（例如捷徑的「開始位置」設在別處）就留在原地，
    切換腳本會把新版的工作目錄設在那裡（`work_dir`）。新資料夾已經有的不蓋掉。
    """
    app_dir = os.path.normcase(os.path.normpath(os.path.abspath(app_dir)))
    config_dir = os.path.normpath(os.path.abspath(config_dir))
    copied = []
    if os.path.normcase(config_dir) == app_dir:
        for name in CARRY_FILES:
            src, dst = os.path.join(config_dir, name), os.path.join(new_dir, name)
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
                copied.append(name)
    for name in CARRY_DIRS:
        src, dst = os.path.join(app_dir, name), os.path.join(new_dir, name)
        if os.path.isdir(src) and not os.path.exists(dst):
            shutil.copytree(src, dst, symlinks=False)
            copied.append(name)
    return copied


def work_dir(app_dir: str, config_dir: str) -> str:
    """新版開起來的工作目錄：設定檔本來在程式資料夾就用程式資料夾（換過之後的同一個路徑），否則用設定檔那裡。"""
    app = os.path.normpath(os.path.abspath(app_dir))
    cfg = os.path.normpath(os.path.abspath(config_dir))
    return app if os.path.normcase(cfg) == os.path.normcase(app) else cfg


def _ps(text: str) -> str:
    """PowerShell 的單引號字串（裡面的單引號寫兩次；不展開變數）。"""
    return "'" + str(text).replace("'", "''") + "'"


def switch_script(pid: int, app_dir: str, new_dir: str, start_dir: str, exe_name: str = EXE_NAME) -> str:
    """
    切換腳本（PowerShell）的內容。存檔時要用「UTF-8 加 BOM」（`write_script`），中文路徑才不會亂碼。

    1. 等目前的程式（pid）關掉（最多兩分鐘）。
    2. 舊資料夾改名成 `.old`（被占用就每半秒再試，最多 20 次）；改不了就不動，下次再試。
    3. 新資料夾改成原本的名字；改不了就把舊的換回來。
    4. 開程式（工作目錄＝設定檔所在的地方）。舊資料夾留著，新版下次啟動時才刪。
    """
    app_dir = os.path.normpath(os.path.abspath(app_dir))
    backup = backup_path(app_dir)
    leaf = os.path.basename(app_dir)
    lines = [
        "# SRT-Subtitle-Generator 資料夾版更新：等程式關掉 → 換上新版資料夾 → 重新開啟",
        "$ErrorActionPreference = 'Stop'",
        f"$app = {_ps(app_dir)}",
        f"$new = {_ps(os.path.normpath(os.path.abspath(new_dir)))}",
        f"$old = {_ps(backup)}",
        f"$exe = {_ps(os.path.join(app_dir, exe_name))}",
        f"$cwd = {_ps(os.path.normpath(os.path.abspath(start_dir)))}",
        f"try {{ Wait-Process -Id {int(pid)} -Timeout 120 -ErrorAction SilentlyContinue }} catch {{ }}",
        "$moved = $false",
        "for ($i = 0; $i -lt 20 -and -not $moved; $i++) {",
        "  try {",
        "    if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Recurse -Force }",
        f"    Rename-Item -LiteralPath $app -NewName {_ps(os.path.basename(backup))}",
        "    $moved = $true",
        "  } catch { Start-Sleep -Milliseconds 500 }",
        "}",
        "if (-not $moved) { Start-Process -FilePath $exe -WorkingDirectory $cwd; exit 1 }",
        "try {",
        f"  Rename-Item -LiteralPath $new -NewName {_ps(leaf)}",
        "} catch {",
        f"  Rename-Item -LiteralPath $old -NewName {_ps(leaf)}",
        "  Start-Process -FilePath $exe -WorkingDirectory $cwd",
        "  exit 1",
        "}",
        "Start-Process -FilePath $exe -WorkingDirectory $cwd",
        "exit 0",
    ]
    return "\r\n".join(lines) + "\r\n"


def write_script(text: str, folder: str) -> str:
    """把切換腳本存成 UTF-8 加 BOM（Windows PowerShell 5.1 沒有 BOM 會把中文當成別的編碼），回傳路徑。"""
    path = os.path.join(folder, "srt-update-switch.ps1")
    with open(path, "w", encoding="utf-8-sig", newline="") as fp:
        fp.write(text)
    return path


def script_command(script: str) -> list:
    """執行切換腳本的命令列（不開視窗、不載入使用者設定檔；只對這一次放寬執行原則）。"""
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
            "-ExecutionPolicy", "Bypass", "-File", script]


def cleanup_backup(app_dir: str) -> bool:
    """新版啟動時呼叫：刪掉切換留下的舊資料夾（`.old`）。回傳有沒有刪到；刪不掉（被占用）就下次再試。"""
    old = backup_path(app_dir)
    if not os.path.isdir(old):
        return False
    shutil.rmtree(old, ignore_errors=True)
    return not os.path.exists(old)


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
