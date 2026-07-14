# -*- coding: utf-8 -*-
"""
ffmpeg 自動安裝模組：一鍵下載安裝，免管理員權限、免設定 PATH。

「請先安裝 ffmpeg 並加入系統 PATH」對一般使用者是很高的門檻
（Issue #24）。本模組把流程收斂成一鍵：

1. 下載 BtbN 的 Windows 靜態建置 zip（GitHub Releases 固定網址，
   單一壓縮檔內含 ffmpeg.exe 與 ffprobe.exe，無其他相依）。
2. 解壓兩個執行檔到程式自己的資料夾（`tools/ffmpeg/bin/`；
   程式資料夾不可寫時退到使用者資料夾）。
3. 把該資料夾加到「本程式行程內」的 PATH——不改動系統設定，
   全專案既有的 `shutil.which("ffmpeg")` 與 `["ffmpeg", ...]`
   命令即可直接找到，一行程式碼都不用改。

程式每次啟動時呼叫 ensure_ffmpeg_on_path()，先前安裝過的
ffmpeg 就會自動生效。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from typing import Callable, Optional

# Windows 靜態建置（GPL、含 ffprobe）。latest 別名固定指向最新建置。
DOWNLOAD_URL = ("https://github.com/BtbN/FFmpeg-Builds/releases/latest/"
                "download/ffmpeg-master-latest-win64-gpl.zip")

# 要從壓縮檔取出的執行檔名（依平台；本專案以 Windows 為主要目標）。
BINARY_NAMES = (("ffmpeg.exe", "ffprobe.exe") if sys.platform == "win32"
                else ("ffmpeg", "ffprobe"))

_APP_DIR_NAME = "SRT-Subtitle-Generator"


def app_root() -> str:
    """程式根目錄：打包成 exe 時為 exe 所在資料夾，否則為專案根目錄。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _user_data_dir() -> str:
    """使用者層級的資料夾（程式資料夾不可寫時的退路）。"""
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, _APP_DIR_NAME)


def install_candidates() -> list:
    """依優先序回傳可能的安裝目錄（bin 層）。"""
    return [
        os.path.join(app_root(), "tools", "ffmpeg", "bin"),
        os.path.join(_user_data_dir(), "ffmpeg", "bin"),
    ]


def installed_dir() -> Optional[str]:
    """回傳已裝好全部執行檔的安裝目錄；尚未安裝時回傳 None。"""
    for candidate in install_candidates():
        if all(os.path.exists(os.path.join(candidate, name))
               for name in BINARY_NAMES):
            return candidate
    return None


def ensure_ffmpeg_on_path() -> Optional[str]:
    """
    若先前自動安裝過 ffmpeg，把其目錄加進本行程的 PATH（冪等）。

    程式啟動時呼叫一次；成功時回傳該目錄，未安裝時回傳 None。
    不改動系統層級的 PATH 設定。
    """
    directory = installed_dir()
    if not directory:
        return None
    current = os.environ.get("PATH", "")
    if directory not in current.split(os.pathsep):
        os.environ["PATH"] = directory + os.pathsep + current
    return directory


def _pick_writable_dir() -> str:
    """挑第一個能建立並寫入的安裝目錄。"""
    last_error = None
    for candidate in install_candidates():
        try:
            os.makedirs(candidate, exist_ok=True)
            probe = os.path.join(candidate, ".write_test")
            with open(probe, "w") as fp:
                fp.write("x")
            os.remove(probe)
            return candidate
        except OSError as exc:
            last_error = exc
    raise RuntimeError(f"找不到可寫入的安裝位置：{last_error}")


def _download(url: str, dest_path: str,
              progress_cb: Optional[Callable[[float, str], None]],
              timeout: int) -> None:
    """串流下載到指定路徑，依 Content-Length 回報進度。"""
    request = urllib.request.Request(
        url, headers={"User-Agent": _APP_DIR_NAME})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        total = int(response.headers.get("Content-Length") or 0)
        received = 0
        with open(dest_path, "wb") as fp:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                fp.write(chunk)
                received += len(chunk)
                if progress_cb and total:
                    # 下載佔整體進度前 85%。
                    progress_cb(min(received / total, 1.0) * 0.85,
                                f"正在下載 ffmpeg... "
                                f"{received // (1024 * 1024)}"
                                f"/{total // (1024 * 1024)} MB")


def _extract_binaries(zip_path: str, target_dir: str) -> None:
    """從壓縮檔取出 ffmpeg／ffprobe 執行檔到安裝目錄。"""
    with zipfile.ZipFile(zip_path) as archive:
        members = {}
        for info in archive.infolist():
            base = os.path.basename(info.filename)
            # 優先取 bin/ 目錄下的（BtbN 的版面），其次任何同名檔。
            if base in BINARY_NAMES and (
                    base not in members
                    or "/bin/" in info.filename.replace("\\", "/")):
                members[base] = info
        missing = [name for name in BINARY_NAMES if name not in members]
        if missing:
            raise RuntimeError(
                f"下載的壓縮檔內找不到 {', '.join(missing)}，"
                "來源格式可能已變更，請改用手動安裝。")
        for name, info in members.items():
            out_path = os.path.join(target_dir, name)
            with archive.open(info) as src, open(out_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            if os.name != "nt":
                os.chmod(out_path, 0o755)


def install_ffmpeg(
    progress_cb: Optional[Callable[[float, str], None]] = None,
    url: str = DOWNLOAD_URL,
    timeout: int = 600,
) -> str:
    """
    下載並安裝 ffmpeg 到程式自己的資料夾，回傳安裝目錄。

    完成後立即對本行程生效（ensure_ffmpeg_on_path），下次啟動也會
    自動載入。下載失敗（離線、防火牆）時拋出附解法的 RuntimeError。
    """
    from .errors import FriendlyError, KIND_NETWORK

    target_dir = _pick_writable_dir()
    if progress_cb:
        progress_cb(0.0, "正在連線下載 ffmpeg（約 80~100 MB，只需一次）...")

    fd, zip_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        try:
            _download(url, zip_path, progress_cb, timeout)
        except OSError as exc:
            raise FriendlyError(
                "ffmpeg 下載失敗",
                cause=f"無法從 GitHub 下載安裝檔（{exc}）。"
                      "常見原因：目前離線、防火牆或公司網路擋下載。",
                solution="確認網路後重試；或手動至 "
                         "https://www.gyan.dev/ffmpeg/builds/ 下載"
                         " release-essentials 壓縮檔，把其中的 ffmpeg.exe 與"
                         " ffprobe.exe 放到程式資料夾的 tools\\ffmpeg\\bin\\ "
                         "內即可（免設定 PATH）。",
                details=str(exc), kind=KIND_NETWORK) from exc

        if progress_cb:
            progress_cb(0.88, "正在解壓安裝...")
        _extract_binaries(zip_path, target_dir)
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)

    ensure_ffmpeg_on_path()
    if progress_cb:
        progress_cb(1.0, f"ffmpeg 安裝完成：{target_dir}")
    return target_dir
