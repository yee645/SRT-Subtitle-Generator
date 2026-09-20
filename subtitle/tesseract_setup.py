# -*- coding: utf-8 -*-
"""
tesseract 一鍵安裝：比照 `subtitle/ffmpeg_setup.py`，免管理員權限、免設定
PATH，裝到程式自己的資料夾。

**這件事分成兩半，而且兩半的性質差很多，所以刻意分開做：**

| | 語言檔（`*.traineddata`） | 引擎本體（`tesseract.exe`） |
|---|---|---|
| 大小 | 每個 2~4 MB | 約 50~60 MB |
| 取得方式 | 直接下載單一檔案 | 官方只出 NSIS 安裝檔 |
| 開發時能不能驗 | **可以，已完整實測** | **不行**（見下） |

**語言檔那一半已經實測過**：從 `tessdata_fast` 抓 eng（4.1 MB）／jpn
（2.5 MB）／chi_tra（2.4 MB），把資料夾指給 tesseract 之後真的認得出日
文那張測試圖。下載、驗檔、放到定位這一整條路是驗過的。

**引擎那一半驗不到，這裡照實說**：開發環境的出口網路政策擋掉了
UB-Mannheim 的發行頁與 GitHub API（實測 403），digi.bib.uni-mannheim.de
也連不到，所以**沒有辦法在開發時確認安裝檔的檔名**。硬寫一個猜的網址比
不寫更糟——版本一換就整個壞掉，而且壞在使用者那邊。所以這裡改成**執行
期去問 GitHub API 要最新的資產名稱**（使用者那台機器沒有這個網路限
制），問不到時退回「講清楚怎麼手動裝」。

`resolve_engine_asset()` 是純函式，用真實形狀的 API 回應離線測得到；真正
的下載與安裝則標記為未實測。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from typing import Callable, Optional

from subtitle.ffmpeg_setup import _user_data_dir, app_root

# 語言檔來源：tessdata_fast 是官方的「快且夠準」版本（另有 tessdata_best，
# 大約三倍大、慢很多，螢幕文字用不到那個精度）。
LANGUAGE_URL_TEMPLATE = ("https://raw.githubusercontent.com/tesseract-ocr/"
                         "tessdata_fast/main/{lang}.traineddata")

# 介面上給使用者挑的語言。代碼是 tesseract 的，右邊是人看的名字。
LANGUAGE_LABELS = (
    ("eng", "英文"),
    ("jpn", "日文"),
    ("chi_tra", "繁體中文"),
    ("chi_sim", "簡體中文"),
    ("kor", "韓文"),
    ("deu", "德文"),
    ("fra", "法文"),
    ("spa", "西班牙文"),
    ("rus", "俄文"),
)

# 引擎本體：官方 Windows 建置。**檔名在執行期才解析**，不寫死。
ENGINE_API_URL = ("https://api.github.com/repos/UB-Mannheim/tesseract/"
                  "releases/latest")
ENGINE_ASSET_PREFIX = "tesseract-ocr-w64-setup"
ENGINE_MANUAL_URL = "https://github.com/UB-Mannheim/tesseract/releases"

# traineddata 的檔頭魔術數字（實測 eng/jpn/chi_tra 三個檔案都是這四個
# 位元組開頭）。用來擋下「下載到一頁 HTML 錯誤頁卻當成語言檔存起來」。
_TRAINEDDATA_MAGIC = b"\x18\x00\x00\x00"
_MIN_TRAINEDDATA_BYTES = 100_000

_UA = "SRT-Subtitle-Generator"


class SetupError(RuntimeError):
    """安裝失敗；訊息一律寫成看得懂、而且講得出下一步的話。"""


# ----------------------------------------------------------------------
# 位置
# ----------------------------------------------------------------------
def install_candidates() -> list:
    """依優先序回傳可能的安裝目錄。"""
    return [os.path.join(app_root(), "tools", "tesseract"),
            os.path.join(_user_data_dir(), "tesseract")]


def tessdata_candidates() -> list:
    """語言檔可能放的位置：自己裝的，以及系統既有 tesseract 的。"""
    folders = [os.path.join(base, "tessdata") for base in install_candidates()]
    env = os.environ.get("TESSDATA_PREFIX")
    if env:
        folders.append(env)
    return folders


def installed_languages() -> set:
    """
    已經有的語言代碼。

    兩個來源都要看，缺一個都會問錯問題：

    - **我們自己裝的**（掃資料夾）——引擎可能還沒裝，這時候問不了它。
    - **引擎自己知道的**（`tesseract --list-langs`）——使用者可能早就用
      套件管理員或官方安裝檔裝好了引擎與語言。截圖比對時抓到的就是這一
      種：這台機器上 eng／jpn／chi_tra 都在，對話框卻還勾著要重新下載。
    """
    found = set()
    try:
        from subtitle import ocrengine
        found |= ocrengine.available_languages()
    except Exception:       # 引擎不在或問不到都不影響下面那一半。
        pass
    for folder in tessdata_candidates():
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            if name.endswith(".traineddata"):
                found.add(name[: -len(".traineddata")])
    return found


def engine_tessdata_dir() -> Optional[str]:
    """
    引擎自己在哪裡找語言檔（問它，不用猜）。

    `tesseract --list-langs` 的第一行會印出它實際用的資料夾：
    `List of available languages in "/usr/share/tesseract-ocr/5/tessdata/" (4):`
    """
    from subtitle import ocrengine

    path = ocrengine.tesseract_path()
    if not path:
        return None
    try:
        proc = subprocess.run([path, "--list-langs"], capture_output=True,
                              timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (proc.stdout + proc.stderr).decode("utf-8", "replace")
    first = text.splitlines()[0] if text.splitlines() else ""
    if '"' in first:
        folder = first.split('"')[1]
        if os.path.isdir(folder):
            return folder
    return None


def _writable(folder: str) -> bool:
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, ".write_test")
        with open(probe, "w") as fp:
            fp.write("x")
        os.remove(probe)
        return True
    except OSError:
        return False


def choose_tessdata_target() -> tuple:
    """
    語言檔要裝到哪裡，以及要不要動 `TESSDATA_PREFIX`。

    **優先裝進引擎自己的語言檔資料夾**。原因是踩到過的一個真缺陷：
    `TESSDATA_PREFIX` 只能指向**一個**資料夾，沒有「路徑清單」這種東
    西。所以如果把語言檔裝到我們自己的資料夾再把該環境變數指過去，使用
    者原本系統上那一份（例如用套件管理員裝的 eng）就會**整個消失**——他
    只是想加一個日文，結果英文不見了。

    回傳 ``(資料夾, 要不要設 TESSDATA_PREFIX)``。
    """
    engine_dir = engine_tessdata_dir()
    if engine_dir and _writable(engine_dir):
        return engine_dir, False
    return _pick_writable_dir("tessdata"), True


def _preserve_existing(target: str) -> None:
    """
    退到自己的資料夾時，先把引擎原本有的語言檔複製過來。

    不複製的話，設完 `TESSDATA_PREFIX` 之後使用者原有的語言就不見了
    （見 `choose_tessdata_target` 的說明）。
    """
    engine_dir = engine_tessdata_dir()
    if not engine_dir or os.path.abspath(engine_dir) == os.path.abspath(target):
        return
    try:
        names = os.listdir(engine_dir)
    except OSError:
        return
    for name in names:
        if not name.endswith(".traineddata"):
            continue
        dest = os.path.join(target, name)
        if os.path.exists(dest):
            continue
        try:
            shutil.copy2(os.path.join(engine_dir, name), dest)
        except OSError:
            pass    # 複製不過去不該讓整個安裝失敗，頂多少一個語言。


def _pick_writable_dir(sub: str = "") -> str:
    """挑第一個能建立並寫入的安裝目錄（比照 ffmpeg_setup）。"""
    last_error = None
    for base in install_candidates():
        candidate = os.path.join(base, sub) if sub else base
        try:
            os.makedirs(candidate, exist_ok=True)
            probe = os.path.join(candidate, ".write_test")
            with open(probe, "w") as fp:
                fp.write("x")
            os.remove(probe)
            return candidate
        except OSError as exc:
            last_error = exc
    raise SetupError(f"找不到可寫入的安裝位置：{last_error}")


def ensure_tesseract_on_path() -> Optional[str]:
    """
    先前自動安裝過的話，把它加進本行程的 PATH 並設好語言檔位置（冪等）。

    程式啟動時呼叫一次；沒裝過就回傳 None。不改動系統層級設定。
    """
    binary = "tesseract.exe" if sys.platform == "win32" else "tesseract"
    for base in install_candidates():
        if not os.path.isfile(os.path.join(base, binary)):
            continue
        current = os.environ.get("PATH", "")
        if base not in current.split(os.pathsep):
            os.environ["PATH"] = base + os.pathsep + current
        tessdata = os.path.join(base, "tessdata")
        if os.path.isdir(tessdata):
            os.environ.setdefault("TESSDATA_PREFIX", tessdata)
        return base
    # 引擎在系統 PATH 上、但語言檔是我們自己裝的：也要讓 tesseract 找得到。
    for base in install_candidates():
        tessdata = os.path.join(base, "tessdata")
        if os.path.isdir(tessdata) and any(
                name.endswith(".traineddata") for name in os.listdir(tessdata)):
            os.environ.setdefault("TESSDATA_PREFIX", tessdata)
            return None
    return None


# ----------------------------------------------------------------------
# 語言檔（這一半已完整實測）
# ----------------------------------------------------------------------
def language_url(lang: str) -> str:
    return LANGUAGE_URL_TEMPLATE.format(lang=lang)


def verify_traineddata(path: str) -> bool:
    """
    下載回來的真的是語言檔嗎（純檢查，可離線測）。

    擋的是「下載到一頁 HTML 錯誤頁或 404 訊息，卻被當成語言檔存起來」
    ——那種檔案放進去之後，tesseract 會在使用者按下辨識時才爆掉，而且錯
    誤訊息完全看不出是這裡的問題。
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            head = handle.read(4)
    except OSError:
        return False
    return size >= _MIN_TRAINEDDATA_BYTES and head == _TRAINEDDATA_MAGIC


def _download(url: str, dest_path: str, progress_cb, timeout: int,
              label: str, span=(0.0, 1.0)) -> None:
    """串流下載，依 Content-Length 把進度回報成 span 區間內的比例。"""
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    low, high = span
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
                    ratio = min(received / total, 1.0)
                    progress_cb(low + (high - low) * ratio,
                                f"正在下載{label}... "
                                f"{received // 1024}/{total // 1024} KB")


def install_languages(langs, progress_cb: Optional[Callable] = None,
                      timeout: int = 300) -> str:
    """
    下載語言檔到自己的 tessdata 資料夾，回傳該資料夾。

    先下載到暫存檔、驗過內容才搬進定位——半個檔案留在 tessdata 裡，
    tesseract 只會在使用者按下辨識時才爆掉。
    """
    wanted = [str(lang).strip() for lang in langs if str(lang).strip()]
    if not wanted:
        raise SetupError("沒有選擇任何語言。")
    target, needs_prefix = choose_tessdata_target()
    if needs_prefix:
        _preserve_existing(target)
    for index, lang in enumerate(wanted):
        label = dict(LANGUAGE_LABELS).get(lang, lang)
        span = (index / len(wanted), (index + 1) / len(wanted))
        fd, tmp_path = tempfile.mkstemp(suffix=".traineddata")
        os.close(fd)
        try:
            try:
                _download(language_url(lang), tmp_path, progress_cb, timeout,
                          f"{label}語言檔", span)
            except OSError as exc:
                raise SetupError(
                    f"{label}語言檔下載失敗（{exc}）。常見原因：目前離線、"
                    "防火牆或公司網路擋下載。確認網路後可以重試；或自行到 "
                    "https://github.com/tesseract-ocr/tessdata_fast 下載 "
                    f"{lang}.traineddata，放進 {target}。") from exc
            if not verify_traineddata(tmp_path):
                raise SetupError(
                    f"{label}語言檔下載回來的內容不對（可能被網路中途攔截"
                    "成一頁錯誤訊息）。請確認網路後重試。")
            shutil.move(tmp_path, os.path.join(target, f"{lang}.traineddata"))
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    if needs_prefix:
        os.environ["TESSDATA_PREFIX"] = target
    if progress_cb:
        progress_cb(1.0, f"語言檔安裝完成：{target}")
    return target


# ----------------------------------------------------------------------
# 引擎本體（這一半在開發環境驗不到，見模組說明）
# ----------------------------------------------------------------------
def resolve_engine_asset(payload: str) -> dict:
    """
    從 GitHub releases API 的回應裡挑出 Windows 64 位元安裝檔（純函式）。

    **不寫死檔名**：UB-Mannheim 的安裝檔名字帶版本與日期
    （`tesseract-ocr-w64-setup-<版本>.<日期>.exe`），寫死等於下次改版就
    壞在使用者那邊。開發環境連不到那個發行頁，更沒有資格硬猜。

    回傳 ``{"name", "url", "size", "tag"}``；挑不到就拋 SetupError。
    """
    try:
        data = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise SetupError("讀不懂下載頁的回應，請改用手動安裝。") from exc
    assets = data.get("assets") or []
    matches = [a for a in assets
               if str(a.get("name", "")).startswith(ENGINE_ASSET_PREFIX)
               and str(a.get("name", "")).endswith(".exe")]
    if not matches:
        raise SetupError(
            "在官方發行頁找不到 Windows 安裝檔（來源格式可能已變更）。"
            f"請改用手動安裝：{ENGINE_MANUAL_URL}")
    # 同一版可能有多個（例如 32 位元），取名字最長的那個沒有意義；取
    # 名稱排序最後的＝版本最新的那一個。
    best = sorted(matches, key=lambda a: str(a.get("name", "")))[-1]
    return {"name": best.get("name", ""),
            "url": best.get("browser_download_url", ""),
            "size": int(best.get("size") or 0),
            "tag": str(data.get("tag_name") or "")}


def fetch_engine_asset(timeout: int = 60) -> dict:
    """問官方發行頁要最新的 Windows 安裝檔資訊（需要網路）。"""
    request = urllib.request.Request(
        ENGINE_API_URL,
        headers={"User-Agent": _UA, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8", "replace")
    except OSError as exc:
        raise SetupError(
            f"連不上官方發行頁（{exc}）。確認網路後可以重試；"
            f"或自行到 {ENGINE_MANUAL_URL} 下載 Windows 安裝檔。") from exc
    return resolve_engine_asset(payload)


def install_engine(progress_cb: Optional[Callable] = None,
                   timeout: int = 900) -> str:
    """
    下載並安裝 tesseract 引擎本體，回傳安裝目錄。

    **開發環境無法實測**（出口網路擋掉官方發行頁），所以每一步都寫成
    「失敗時講得出下一步」。官方只提供 NSIS 安裝檔，用它的靜默參數裝到
    程式自己的資料夾（`/S` 靜默、`/D=` 指定位置），不碰系統目錄、不需要
    管理員權限。
    """
    asset = fetch_engine_asset(timeout=min(timeout, 60))
    if not asset["url"]:
        raise SetupError(
            f"官方發行頁沒有給下載連結，請改用手動安裝：{ENGINE_MANUAL_URL}")
    target = _pick_writable_dir()
    fd, exe_path = tempfile.mkstemp(suffix=".exe")
    os.close(fd)
    try:
        megabytes = asset["size"] // (1024 * 1024)
        if progress_cb:
            progress_cb(0.0, f"正在下載 {asset['name']}"
                             f"（約 {megabytes} MB，只需一次）...")
        try:
            _download(asset["url"], exe_path, progress_cb, timeout,
                      "文字辨識引擎", (0.0, 0.85))
        except OSError as exc:
            raise SetupError(
                f"下載失敗（{exc}）。確認網路後可以重試；"
                f"或自行到 {ENGINE_MANUAL_URL} 下載安裝。") from exc

        if sys.platform != "win32":
            raise SetupError(
                "自動安裝目前只支援 Windows。其他系統請用套件管理員安裝"
                "tesseract（例如 apt install tesseract-ocr）。")
        if progress_cb:
            progress_cb(0.88, "正在安裝（不需要管理員權限）...")
        try:
            completed = subprocess.run([exe_path, "/S", f"/D={target}"],
                                       capture_output=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SetupError(
                f"安裝程式無法執行（{exc}）。"
                f"請改用手動安裝：{ENGINE_MANUAL_URL}") from exc
        if completed.returncode != 0:
            raise SetupError(
                f"安裝程式回報失敗（錯誤碼 {completed.returncode}）。"
                f"請改用手動安裝：{ENGINE_MANUAL_URL}")
    finally:
        if os.path.exists(exe_path):
            os.remove(exe_path)

    if not os.path.isfile(os.path.join(target, "tesseract.exe")):
        raise SetupError(
            "安裝完成了，但在預期的位置找不到 tesseract.exe。"
            f"請改用手動安裝：{ENGINE_MANUAL_URL}")
    ensure_tesseract_on_path()
    if progress_cb:
        progress_cb(1.0, f"文字辨識引擎安裝完成：{target}")
    return target


def describe_state(lang: str = "eng") -> str:
    """一句話說明現在缺什麼（給介面的狀態列）。"""
    from subtitle import ocrengine

    have_engine = ocrengine.tesseract_available()
    missing = [code for code in str(lang).split("+") if code.strip()
               and code.strip() not in installed_languages()]
    if not have_engine and missing:
        return "還沒有文字辨識引擎與語言檔，按「開始安裝」一次裝好。"
    if not have_engine:
        return "語言檔已備妥，但還沒有文字辨識引擎。"
    if missing:
        names = "、".join(dict(LANGUAGE_LABELS).get(m, m) for m in missing)
        return f"引擎已備妥，還缺 {names} 語言檔。"
    return "文字辨識引擎與語言檔都已備妥。"
