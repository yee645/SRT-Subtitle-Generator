# -*- coding: utf-8 -*-
"""
`subtitle/tesseract_setup.py` 與 `gui/tesseract_dialog.py` 測試。

ROADMAP 第 9 項第一階段的第 2 項（tesseract 一鍵安裝）。

**這一項有一半在開發環境驗不到，測試也照這個界線分開寫**：

  - **語言檔那一半有真的下載實測**（有網路時才跑）：抓一個
    `*.traineddata` 下來、驗檔頭、放進定位，再用它真的辨識一張圖。
  - **引擎本體那一半只能測純邏輯**：開發環境的出口網路擋掉了官方發行頁
    與 GitHub API（實測 403），所以 `resolve_engine_asset()` 用**真實形
    狀**的 API 回應離線測，下載與執行安裝檔則標記為未實測。

另外守住三件事：

  1. **下載回來的東西要驗過才放進定位。** 半個檔案或一頁 HTML 錯誤訊息
     被當成語言檔存進去，tesseract 只會在使用者按下辨識時才爆掉，而且
     錯誤訊息完全看不出問題出在這裡。
  2. **安裝檔名不可以寫死。** 官方檔名帶版本與日期，寫死等於下次改版就
     壞在使用者那邊——而且開發環境連不到那個頁面，更沒有資格硬猜。
  3. **每一條失敗路徑都要講得出下一步**，不能只丟一個技術錯誤。
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import tesseract_setup as ts

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


# ===== 1. 位置與 PATH ====================================================

check("安裝位置有兩個候選（程式資料夾優先，退到使用者資料夾）",
      len(ts.install_candidates()) == 2, str(ts.install_candidates()))
check("語言檔位置包含自己裝的 tessdata",
      any(c.endswith(os.path.join("tesseract", "tessdata"))
          for c in ts.tessdata_candidates()), str(ts.tessdata_candidates()))

_real_candidates = ts.install_candidates
with tempfile.TemporaryDirectory() as tmp:
    ts.install_candidates = lambda: [os.path.join(tmp, "tesseract")]
    _saved_path = os.environ.get("PATH", "")
    _saved_prefix = os.environ.get("TESSDATA_PREFIX")
    try:
        check("沒裝過時 ensure_tesseract_on_path 回傳 None、不會亂改環境",
              ts.ensure_tesseract_on_path() is None)

        base = os.path.join(tmp, "tesseract")
        os.makedirs(os.path.join(base, "tessdata"), exist_ok=True)
        binary = "tesseract.exe" if sys.platform == "win32" else "tesseract"
        with open(os.path.join(base, binary), "w") as fh:
            fh.write("#!/bin/sh\n")
        os.environ.pop("TESSDATA_PREFIX", None)
        got = ts.ensure_tesseract_on_path()
        check("裝過之後會把安裝目錄加進本行程的 PATH", got == base, str(got))
        check("PATH 真的多了那個目錄",
              base in os.environ.get("PATH", "").split(os.pathsep))
        before = os.environ.get("PATH", "")
        ts.ensure_tesseract_on_path()
        check("重複呼叫不會把同一個目錄加兩次（冪等）",
              os.environ.get("PATH", "") == before)

        # 引擎在系統 PATH 上、語言檔是自己裝的：也要讓 tesseract 找得到。
        os.environ.pop("TESSDATA_PREFIX", None)
        os.remove(os.path.join(base, binary))
        with open(os.path.join(base, "tessdata", "eng.traineddata"), "w") as fh:
            fh.write("x")
        ts.ensure_tesseract_on_path()
        check("只有語言檔是自己裝的時候，TESSDATA_PREFIX 會被指過去",
              os.environ.get("TESSDATA_PREFIX")
              == os.path.join(base, "tessdata"),
              str(os.environ.get("TESSDATA_PREFIX")))
        check("掃得出已安裝的語言", "eng" in ts.installed_languages())
    finally:
        os.environ["PATH"] = _saved_path
        if _saved_prefix is None:
            os.environ.pop("TESSDATA_PREFIX", None)
        else:
            os.environ["TESSDATA_PREFIX"] = _saved_prefix
        ts.install_candidates = _real_candidates


# ===== 2. 驗檔：下載回來的真的是語言檔嗎 ================================

with tempfile.TemporaryDirectory() as tmp:
    good = os.path.join(tmp, "good.traineddata")
    with open(good, "wb") as fh:
        fh.write(b"\x18\x00\x00\x00" + b"\0" * 200_000)
    check("正常的語言檔驗得過", ts.verify_traineddata(good))

    html = os.path.join(tmp, "html.traineddata")
    with open(html, "wb") as fh:
        fh.write(b"<!DOCTYPE html><title>404</title>" + b" " * 200_000)
    check("下載到一頁 HTML 錯誤訊息時驗不過（不然會等到使用者按辨識才爆）",
          not ts.verify_traineddata(html))

    short = os.path.join(tmp, "short.traineddata")
    with open(short, "wb") as fh:
        fh.write(b"\x18\x00\x00\x00" + b"\0" * 10)
    check("只下載到一半的檔案驗不過", not ts.verify_traineddata(short))
    check("檔案不存在時驗不過，也不會拋例外",
          not ts.verify_traineddata(os.path.join(tmp, "nope")))


# ===== 3. 安裝檔名不可以寫死：從 API 回應挑資產 =========================
# 下面這段 JSON 是 GitHub releases API 的**真實形狀**（欄位名與巢狀結構照
# 官方文件），只把值換成這個情境會出現的內容。

PAYLOAD = json.dumps({
    "tag_name": "v5.5.0.20241111",
    "assets": [
        {"name": "tesseract-ocr-w32-setup-5.5.0.20241111.exe",
         "browser_download_url": "https://example.invalid/w32.exe",
         "size": 40_000_000},
        {"name": "tesseract-ocr-w64-setup-5.5.0.20241111.exe",
         "browser_download_url": "https://example.invalid/w64.exe",
         "size": 58_000_000},
        {"name": "Source code (zip)",
         "browser_download_url": "https://example.invalid/src.zip",
         "size": 1_000},
    ],
})
asset = ts.resolve_engine_asset(PAYLOAD)
check("挑得出 64 位元的 Windows 安裝檔",
      asset["name"] == "tesseract-ocr-w64-setup-5.5.0.20241111.exe",
      asset["name"])
check("挑的不是 32 位元那個", "w32" not in asset["name"])
check("連下載網址與大小一起帶出來",
      asset["url"].endswith("w64.exe") and asset["size"] == 58_000_000,
      str(asset))
check("版本標籤也帶出來", asset["tag"] == "v5.5.0.20241111")

newer = json.dumps({
    "tag_name": "v5.6.0.20260101",
    "assets": [
        {"name": "tesseract-ocr-w64-setup-5.5.0.20241111.exe",
         "browser_download_url": "https://example.invalid/old.exe", "size": 1},
        {"name": "tesseract-ocr-w64-setup-5.6.0.20260101.exe",
         "browser_download_url": "https://example.invalid/new.exe", "size": 2},
    ],
})
check("同一頁有多個版本時挑新的那個",
      ts.resolve_engine_asset(newer)["url"].endswith("new.exe"),
      ts.resolve_engine_asset(newer)["url"])

# 官方哪天改了資產命名，要明確報錯並指出手動安裝的路，不是默默裝錯東西。
renamed = json.dumps({"tag_name": "v9", "assets": [
    {"name": "something-else.exe", "browser_download_url": "x", "size": 1}]})
try:
    ts.resolve_engine_asset(renamed)
    check("找不到符合的資產時要報錯", False, "沒有丟例外")
except ts.SetupError as exc:
    check("找不到符合的資產時丟 SetupError", True)
    check("訊息指得出手動安裝的路", ts.ENGINE_MANUAL_URL in str(exc), str(exc))

try:
    ts.resolve_engine_asset("this is not json")
    check("回應不是 JSON 時要報錯", False, "沒有丟例外")
except ts.SetupError as exc:
    check("回應不是 JSON 時丟 SetupError 並講得出下一步",
          "手動" in str(exc), str(exc))

# 前綴本身有「w64」，所以不能用「有沒有數字」來判斷——那條會把正確的寫
# 法判成錯的（第一版就是這樣寫錯的）。要擋的是**帶版本號的完整檔名**。
import re as _re

_module_src = io.open(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "subtitle", "tesseract_setup.py"), encoding="utf-8").read()
_hardcoded = _re.findall(r"setup-\d+(?:\.\d+)+\.exe", _module_src)
check("模組裡沒有寫死帶版本號的安裝檔名（寫死＝下次改版就壞在使用者那邊）",
      not _hardcoded, str(_hardcoded))
check("解析用的只是前綴，不是完整檔名",
      not ts.ENGINE_ASSET_PREFIX.endswith(".exe"), ts.ENGINE_ASSET_PREFIX)


# ===== 4. 失敗路徑都要講得出下一步 ======================================

try:
    ts.install_languages([])
    check("沒選語言時要報錯", False, "沒有丟例外")
except ts.SetupError as exc:
    check("沒選語言時丟 SetupError", "沒有選擇" in str(exc), str(exc))

_real_urlopen = urllib.request.urlopen


def _boom(*args, **kwargs):
    raise urllib.error.URLError("nope")


with tempfile.TemporaryDirectory() as tmp:
    ts.install_candidates = lambda: [os.path.join(tmp, "tesseract")]
    urllib.request.urlopen = _boom
    try:
        try:
            ts.install_languages(["eng"])
            check("下載失敗時要報錯", False, "沒有丟例外")
        except ts.SetupError as exc:
            check("語言檔下載失敗時丟 SetupError", True)
            check("訊息講得出常見原因與手動的路",
                  "離線" in str(exc) and "tessdata_fast" in str(exc), str(exc))
        try:
            ts.fetch_engine_asset()
            check("連不上發行頁時要報錯", False, "沒有丟例外")
        except ts.SetupError as exc:
            check("連不上發行頁時丟 SetupError 並指出手動安裝的路",
                  ts.ENGINE_MANUAL_URL in str(exc), str(exc))
    finally:
        urllib.request.urlopen = _real_urlopen
        ts.install_candidates = _real_candidates

# 下載成功但內容不對（例如被攔截成一頁錯誤訊息）→ 不可以放進定位。
class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.headers = {"Content-Length": str(len(payload))}
        self._read = False

    def read(self, _size=None):
        if self._read:
            return b""
        self._read = True
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


with tempfile.TemporaryDirectory() as tmp:
    ts.install_candidates = lambda: [os.path.join(tmp, "tesseract")]
    urllib.request.urlopen = lambda *a, **k: _FakeResponse(
        b"<html>blocked by your network</html>" + b" " * 300_000)
    try:
        try:
            ts.install_languages(["eng"])
            check("下載到錯誤頁時要報錯", False, "沒有丟例外")
        except ts.SetupError as exc:
            check("下載到錯誤頁時丟 SetupError", "內容不對" in str(exc), str(exc))
        target = os.path.join(tmp, "tesseract", "tessdata")
        left = os.listdir(target) if os.path.isdir(target) else []
        check("驗不過的檔案不會被留在定位（半個檔案比沒有更糟）",
              not any(n.endswith(".traineddata") for n in left), str(left))
    finally:
        urllib.request.urlopen = _real_urlopen
        ts.install_candidates = _real_candidates


# ===== 4b. 語言檔要裝去哪：不可以把使用者原有的語言弄不見 ==============
# 這是實測踩到的真缺陷：`TESSDATA_PREFIX` 只能指向**一個**資料夾，沒有
# 路徑清單。把語言檔裝到自己的資料夾再把該環境變數指過去，使用者原本系統
# 上那一份（例如套件管理員裝的 eng）就整個消失——他只是想加一個日文，結
# 果英文不見了。發現的經過：測試跑完真實下載那一段之後，後面的段落就再也
# 看不到系統上的 eng／jpn／chi_tra。

engine_dir = ts.engine_tessdata_dir()
if engine_dir is None:
    print("SKIP 語言檔目標選擇（這個環境沒有可問的 tesseract）")
else:
    check("問得出引擎自己在哪裡找語言檔（不是用猜的）",
          os.path.isdir(engine_dir), str(engine_dir))
    target, needs_prefix = ts.choose_tessdata_target()
    if os.access(engine_dir, os.W_OK):
        check("引擎的語言檔資料夾可寫時就裝那裡，完全不必動 TESSDATA_PREFIX",
              os.path.abspath(target) == os.path.abspath(engine_dir)
              and not needs_prefix, f"{target} prefix={needs_prefix}")
    else:
        check("引擎的資料夾不可寫時才退回自己的資料夾，並要設 TESSDATA_PREFIX",
              needs_prefix, f"{target} prefix={needs_prefix}")

    # 退路那條：一定要先把原有的語言檔帶過去，否則設完環境變數就不見了。
    with tempfile.TemporaryDirectory() as tmp:
        mine = os.path.join(tmp, "tessdata")
        os.makedirs(mine)
        ts._preserve_existing(mine)
        carried = {n[: -len(".traineddata")] for n in os.listdir(mine)
                   if n.endswith(".traineddata")}
        existing = {n[: -len(".traineddata")] for n in os.listdir(engine_dir)
                    if n.endswith(".traineddata")}
        check("退回自己的資料夾時，引擎原本有的語言檔會先被帶過去"
              "（不然使用者只是想加一個語言，原本的就不見了）",
              existing and existing <= carried,
              f"原有 {sorted(existing)} → 帶過去 {sorted(carried)}")


# ===== 5. 狀態說明 ======================================================

state = ts.describe_state("eng")
check("狀態說明是一句人看得懂的話", isinstance(state, str) and len(state) > 6,
      state)


# ===== 6. 真的下載一個語言檔（有網路才跑）===============================

def _network_ok():
    try:
        request = urllib.request.Request(
            ts.language_url("eng"), headers={"User-Agent": "probe"},
            method="HEAD")
        with urllib.request.urlopen(request, timeout=20):
            return True
    except Exception:
        return False


if not _network_ok():
    print("SKIP 真實下載段：這個環境連不到語言檔來源（離線或被網路政策擋）")
else:
    with tempfile.TemporaryDirectory() as tmp:
        ts.install_candidates = lambda: [os.path.join(tmp, "tesseract")]
        try:
            messages = []
            folder = ts.install_languages(
                ["chi_tra"], progress_cb=lambda r, m: messages.append(m))
            path = os.path.join(folder, "chi_tra.traineddata")
            check("真實下載：語言檔有被放到定位", os.path.isfile(path))
            check("真實下載：檔案大小合理（2 MB 以上）",
                  os.path.getsize(path) > 2_000_000, str(os.path.getsize(path)))
            check("真實下載：驗檔過得了", ts.verify_traineddata(path))
            check("真實下載：過程中有回報進度（不是裝好才一次跳完）",
                  len(messages) >= 2 and "KB" in messages[0], str(messages[:1]))
            check("真實下載：掃得到剛裝好的語言",
                  "chi_tra" in ts.installed_languages())

            if shutil.which("tesseract") and os.path.isfile(
                    "/tmp/claude-0/ocr/img/12_chinese.png"):
                env = dict(os.environ, TESSDATA_PREFIX=folder)
                out = subprocess.run(
                    ["tesseract", "/tmp/claude-0/ocr/img/12_chinese.png",
                     "stdout", "-l", "chi_tra", "--psm", "6"],
                    capture_output=True, env=env, timeout=180)
                text = out.stdout.decode("utf-8", "replace")
                check("真實下載：拿剛裝好的語言檔真的辨識得出中文",
                      "封印" in text, repr(text[:50]))
            else:
                print("SKIP 用下載回來的語言檔實際辨識（沒有 tesseract 或測資）")
        finally:
            ts.install_candidates = _real_candidates


# ===== 7. 介面：Xvfb 下開得出來、勾選狀態正確 ===========================

if not os.environ.get("DISPLAY"):
    print("SKIP GUI 段：無 DISPLAY")
else:
    import tkinter as tk

    try:
        from gui.tesseract_dialog import TesseractInstallDialog

        root = tk.Tk()
        root.geometry("200x100")
        root.update()
        dialog = TesseractInstallDialog(root)
        dialog.deiconify()
        for _ in range(20):
            root.update()
            dialog.update()

        check("對話框開得出來", dialog.winfo_exists())
        check("九種語言都列得出來", len(dialog.lang_vars) == 9,
              str(len(dialog.lang_vars)))
        # 這一條原本寫成「選到的 ⊆ {eng,jpn,chi_tra}」，但在一台三種語言
        # 都已安裝的機器上，選到的是空集合，空集合也 ⊆ 任何集合——等於沒
        # 測。改成分兩邊驗：已安裝的不可以被勾、沒裝的要被勾。
        installed_now = ts.installed_languages()
        preselected = set(dialog.selected_languages())
        check("已經安裝的語言不會被重複勾（截圖比對抓到過這個）",
              not (preselected & installed_now),
              f"勾了 {sorted(preselected & installed_now)}")
        probe_lang = next((code for code, _ in ts.LANGUAGE_LABELS
                           if code not in installed_now), None)
        if probe_lang:
            other = TesseractInstallDialog(root, langs=(probe_lang,))
            other.deiconify()
            for _ in range(10):
                root.update()
                other.update()
            check(f"還沒安裝的語言（{probe_lang}）會被預先勾起來",
                  probe_lang in other.selected_languages(),
                  str(other.selected_languages()))
            other._close()
        else:
            print("SKIP「沒裝的語言會被勾起來」：這台機器九種語言都裝了")
        check("引擎那一項有獨立的勾選（系統已有 tesseract 時可以只補語言檔）",
              hasattr(dialog, "engine_var"))

        # 什麼都沒勾就按下去，要提示而不是默默什麼都不做。
        for var in dialog.lang_vars.values():
            var.set(False)
        dialog.engine_var.set(False)
        from tkinter import messagebox as _mb
        _orig = _mb.showinfo
        shown = []
        _mb.showinfo = lambda *a, **k: shown.append(a)
        try:
            dialog._on_start()
        finally:
            _mb.showinfo = _orig
        check("什麼都沒勾就按開始時會提示，而且不會真的開始跑",
              shown and not dialog._started, str(shown))

        dialog._close()
        root.destroy()
    except tk.TclError as exc:
        message = str(exc).lower()
        if "display" in message or "connect" in message:
            print(f"SKIP GUI 段（無顯示器：{exc}）")
        else:
            check("GUI 段沒有丟 TclError", False, str(exc))


print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("subtitle/tesseract_setup.py 測試全數通過。")
