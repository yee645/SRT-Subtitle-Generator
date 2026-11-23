# -*- coding: utf-8 -*-
"""
3.0 第 12 項 12-2：資料夾版（onedir）自動更新的核心（subtitle/onedirupdate.py）。

1. pick_zip：挑出 Qt 資料夾版的 zip；別的附件、別的專案或 http 的網址、路徑裡有 .. 都不收；回應壞掉回 None。
   名稱規則跟打包流程（release.yml、packaging/qt_preview.py）對得上。
2. download（換掉連線，不連網）：進度、存到 dest 裡；大小不對、取消、斷線都刪掉下載一半的檔；網址不對不下載。
3. check_zip／extract：用**真的打包程式**（packaging/qt_preview.make_zip）做 zip 再解；擋 ..、絕對路徑、反斜線、
   磁碟代號、符號連結、兩個頂層資料夾、沒有 exe、太大、空的；解壞了不留暫存資料夾；之前留下的同名資料夾換掉；
   不是 zip 講清楚。
4. carry_over／work_dir：設定檔在程式資料夾才帶設定與生字本；tools 一律帶；新資料夾已經有的不蓋；
   設定檔在別處時新版的工作目錄設在那裡。
5. switch_script：順序對（先等程式關掉、再改舊的、再換新的、最後開）；路徑裡的單引號、中文、空白照樣對；
   失敗會換回來；存成 UTF-8 加 BOM、CRLF；執行命令列不開視窗。
6. cleanup_backup：刪掉 .old；沒有就說沒有。
7. 零 GUI 依賴、不 import config。
"""
import io
import os
import re
import stat
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "packaging"))

import qt_preview  # noqa: E402  —— 真的打包程式（發版時用它打 zip）
from subtitle import onedirupdate as u  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def expect_error(fn, *args, **kwargs):
    """回傳 UpdateError 的訊息；沒丟就回 None。"""
    try:
        fn(*args, **kwargs)
    except u.UpdateError as exc:
        return str(exc)
    return None


TAG = "v3.0.1"
GOOD_URL = f"{u.DOWNLOAD_PREFIX}{TAG}/SRT-Subtitle-Generator-Qt-v3.0.1-win64.zip"

# ----- 1 -----
release = {"tag_name": TAG, "assets": [
    {"name": "SRT-Subtitle-Generator.exe", "browser_download_url": f"{u.DOWNLOAD_PREFIX}{TAG}/SRT-Subtitle-Generator.exe",
     "size": 100},
    {"name": "SRT-Subtitle-Generator-Qt-v3.0.1-win64.zip", "browser_download_url": GOOD_URL, "size": "4321"},
]}
check("挑出 Qt 資料夾版的 zip（不是單一 exe）", u.pick_zip(release) == {
    "name": "SRT-Subtitle-Generator-Qt-v3.0.1-win64.zip", "url": GOOD_URL, "size": 4321}, str(u.pick_zip(release)))
for bad_url, why in ((GOOD_URL.replace("yee645", "someone"), "別的專案"),
                     (GOOD_URL.replace("https://", "http://"), "http"),
                     (f"{u.DOWNLOAD_PREFIX}../../evil/x-win64.zip", "路徑裡有 .."),
                     ("https://example.com/SRT-Subtitle-Generator-Qt-win64.zip", "別的網站")):
    data = {"assets": [{"name": "SRT-Subtitle-Generator-Qt-v3.0.1-win64.zip", "browser_download_url": bad_url}]}
    check(f"網址不對不收：{why}", u.pick_zip(data) is None and not u.url_allowed(bad_url))
check("不是 win64 的 zip 不收", u.pick_zip({"assets": [{"name": "SRT-Subtitle-Generator-Qt-v3.0.1-linux.zip",
                                                       "browser_download_url": GOOD_URL}]}) is None)
check("回應壞掉：None", u.pick_zip(None) is None and u.pick_zip({"assets": None}) is None
      and u.pick_zip({"assets": ["壞", None]}) is None and u.pick_zip("x") is None)
check("大小寫不出數字：當 0", u.pick_zip({"assets": [{"name": "SRT-Subtitle-Generator-Qt-win64.zip",
                                                   "browser_download_url": GOOD_URL, "size": "壞"}]})["size"] == 0)
release_yml = open(os.path.join(ROOT, ".github", "workflows", "release.yml"), encoding="utf-8").read()
check("exe 名稱跟打包流程一樣", f"--name {u.EXE_NAME[:-4]} " in release_yml)
zip_name = f"SRT-Subtitle-Generator-Qt-preview-v{qt_preview.APP_VERSION}-win64.zip"
check("打包流程現在打的 zip 名稱也挑得到（名稱規則對得上）", 'zip_path = f"SRT-Subtitle-Generator-Qt-preview-v{APP_VERSION}-{suffix}.zip"'
      in open(qt_preview.__file__, encoding="utf-8").read() and 'suffix = "win64" if os.name == "nt"' in open(
          qt_preview.__file__, encoding="utf-8").read()
      and u.pick_zip({"assets": [{"name": zip_name, "browser_download_url": u.DOWNLOAD_PREFIX + "v1/" + zip_name}]}))


# ----- 2 -----
class FakeResponse(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


payload = os.urandom(700 * 1024)  # 跨好幾個讀取區塊
seen_requests = []


def opener_for(data):
    def opener(request, timeout=0):
        seen_requests.append(request)
        return FakeResponse(data)
    return opener


tmp = tempfile.mkdtemp()
dl_dir = os.path.join(tmp, "dl")
os.makedirs(dl_dir)
asset = {"name": "SRT-Subtitle-Generator-Qt-v3.0.1-win64.zip", "url": GOOD_URL, "size": len(payload)}
ticks = []
path = u.download(asset, dl_dir, progress=lambda d, t: ticks.append((d, t)), opener=opener_for(payload))
check("下載：存到指定資料夾、內容一樣", path == os.path.join(dl_dir, asset["name"]) and open(path, "rb").read() == payload)
check("進度：遞增、最後到總數", ticks and ticks[-1] == (len(payload), len(payload))
      and all(a[0] < b[0] for a, b in zip(ticks, ticks[1:])) and len(ticks) >= 3)
check("連線只帶固定的 User-Agent", seen_requests[-1].get_header("User-agent") == "SRT-Subtitle-Generator"
      and seen_requests[-1].full_url == GOOD_URL)
check("說明講只下載、不送東西出去", "不送任何檔案、字幕、設定或帳號資訊" in u.SENDS)
os.remove(path)
err = expect_error(u.download, dict(asset, size=len(payload) + 1), dl_dir, opener=opener_for(payload))
check("大小不對：講沒下載完整、不留檔", err == u.SIZE_MISMATCH and os.listdir(dl_dir) == [], str(os.listdir(dl_dir)))
calls = []
err = expect_error(u.download, asset, dl_dir, opener=opener_for(payload),
                   cancelled=lambda: calls.append(1) or len(calls) > 2)
check("取消：停下、不留檔", err == u.CANCELLED and os.listdir(dl_dir) == [])


def broken_opener(request, timeout=0):
    raise OSError("連線被重設")


err = expect_error(u.download, asset, dl_dir, opener=broken_opener)
check("斷線：講原因、不留檔", err and "連線被重設" in err and os.listdir(dl_dir) == [])
err = expect_error(u.download, dict(asset, url="https://example.com/x.zip"), dl_dir, opener=opener_for(payload))
check("網址不對：不下載", err == u.BAD_URL and os.listdir(dl_dir) == [])

# ----- 3 -----
app_parent = os.path.join(tmp, "程式 O'Brien")  # 中文、空白、單引號
os.makedirs(app_parent)
app_dir = os.path.join(app_parent, "SRT-Subtitle-Generator-Qt")
dist = os.path.join(tmp, "build", "SRT-Subtitle-Generator-Qt")
os.makedirs(os.path.join(dist, "_internal", "PySide6"))
open(os.path.join(dist, u.EXE_NAME), "wb").write(b"MZ new")
open(os.path.join(dist, "_internal", "PySide6", "Qt6Core.dll"), "wb").write(b"dll" * 1000)
real_zip = os.path.join(tmp, "real.zip")
qt_preview.make_zip(dist, real_zip)  # 發版時的同一支
with zipfile.ZipFile(real_zip) as zf:
    check("真的打包程式打的 zip：檢查通過、頂層資料夾就是成品名稱", u.check_zip(zf) == "SRT-Subtitle-Generator-Qt")

stale = u.staging_path(app_dir, "v3.0.1")
os.makedirs(os.path.join(stale, "舊的殘留"))
new_dir = u.extract(real_zip, app_dir, "v3.0.1")
check("解到程式資料夾旁邊的 .update-<版本>", new_dir == os.path.join(app_parent, "SRT-Subtitle-Generator-Qt.update-v3.0.1")
      and open(os.path.join(new_dir, u.EXE_NAME), "rb").read() == b"MZ new"
      and os.path.isfile(os.path.join(new_dir, "_internal", "PySide6", "Qt6Core.dll")))
check("之前沒切換成功留下的同名資料夾：換掉", not os.path.exists(os.path.join(new_dir, "舊的殘留")))
check("暫存解壓資料夾不留", not [n for n in os.listdir(app_parent) if n.startswith(".unpack-")], str(os.listdir(app_parent)))
check("版本字串裡怪字元拿掉（不會跑出資料夾）", u.staging_path(app_dir, "../x\\y") == app_dir + ".update-..xy"
      and os.path.dirname(u.staging_path(app_dir, "../x/../y")) == app_parent)


def make(entries, symlink=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries:
            zf.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
    buf.seek(0)
    return zipfile.ZipFile(buf)


ok_entries = [("App/" + u.EXE_NAME, "MZ"), ("App/_internal/a.dll", "x")]
check("自己做的正常 zip：通過", u.check_zip(make(ok_entries)) == "App")
bad_cases = [
    ("路徑穿越 ..", ok_entries + [("App/../../evil.txt", "x")]),
    ("絕對路徑", ok_entries + [("/etc/evil", "x")]),
    ("反斜線（同一個頂層資料夾裡藏 ..\\）", ok_entries + [("App/..\\..\\evil.txt", "x")]),
    ("磁碟代號（整包都在 C: 底下）", [("C:/" + u.EXE_NAME, "MZ")]),
    ("兩個頂層資料夾", ok_entries + [("Other/x", "x")]),
    ("沒有 exe", [("App/_internal/a.dll", "x")]),
    ("exe 不在頂層資料夾正下方", [("App/sub/" + u.EXE_NAME, "MZ")]),
    ("空的", []),
]
for why, entries in bad_cases:
    err = expect_error(u.check_zip, make(entries))
    check(f"擋：{why}", bool(err), why)
check("擋：符號連結", "符號連結" in (expect_error(u.check_zip, make(ok_entries, symlink="App/link")) or ""))
real_max = u.MAX_UNPACKED
u.MAX_UNPACKED = 100
check("擋：解開後太大（壓縮炸彈）", "太大" in (expect_error(u.check_zip, make(ok_entries + [("App/big", "0" * 200)])) or ""))
u.MAX_UNPACKED = real_max

evil_zip = os.path.join(tmp, "evil.zip")
with zipfile.ZipFile(evil_zip, "w") as zf:
    zf.writestr("App/" + u.EXE_NAME, "MZ")
    zf.writestr("App/../../逃出去.txt", "x")
before = sorted(os.listdir(app_parent))
err = expect_error(u.extract, evil_zip, app_dir, "v9")
check("解壓前就擋：什麼都沒解出來、外面沒有多檔案", err and sorted(os.listdir(app_parent)) == before
      and not os.path.exists(os.path.join(tmp, "逃出去.txt")))
not_zip = os.path.join(tmp, "half.zip")
open(not_zip, "wb").write(b"PK\x03\x04" + "只下載了一半".encode("utf-8"))
check("不是完整的 zip：講清楚", "不是完整的 zip" in (expect_error(u.extract, not_zip, app_dir, "v9") or ""))

# ----- 4 -----
os.makedirs(os.path.join(app_dir, "tools", "ffmpeg", "bin"))
open(os.path.join(app_dir, "tools", "ffmpeg", "bin", "ffmpeg.exe"), "wb").write(b"ff")
open(os.path.join(app_dir, "config.json"), "w", encoding="utf-8").write('{"theme": "dark"}')
open(os.path.join(app_dir, "quicktranslate_vocab.json"), "w", encoding="utf-8").write("[]")
open(os.path.join(app_dir, "app.log"), "w").write("log")
copied = u.carry_over(app_dir, app_dir, new_dir)
check("設定檔在程式資料夾：設定、生字本、tools 都帶過去", sorted(copied) == ["config.json", "quicktranslate_vocab.json", "tools"]
      and open(os.path.join(new_dir, "config.json"), encoding="utf-8").read() == '{"theme": "dark"}'
      and os.path.isfile(os.path.join(new_dir, "tools", "ffmpeg", "bin", "ffmpeg.exe")), str(copied))
check("其他（記錄檔）不帶", not os.path.exists(os.path.join(new_dir, "app.log")))
open(os.path.join(app_dir, "config.json"), "w", encoding="utf-8").write('{"theme": "light"}')
check("新資料夾已經有的不蓋", u.carry_over(app_dir, app_dir, new_dir) == []
      and '"dark"' in open(os.path.join(new_dir, "config.json"), encoding="utf-8").read())
elsewhere = os.path.join(tmp, "我的設定")
os.makedirs(elsewhere)
open(os.path.join(elsewhere, "config.json"), "w").write("{}")
new2 = os.path.join(tmp, "new2")
os.makedirs(new2)
check("設定檔在別處：設定留在原地、只帶 tools", u.carry_over(app_dir, elsewhere, new2) == ["tools"]
      and not os.path.exists(os.path.join(new2, "config.json")))
check("工作目錄：設定在程式資料夾就用程式資料夾，否則用設定那裡", u.work_dir(app_dir, app_dir) == app_dir
      and u.work_dir(app_dir, elsewhere) == elsewhere)

# ----- 5 -----
text = u.switch_script(4321, app_dir, new_dir, app_dir)
lines = text.split("\r\n")
check("CRLF、結尾換行", text.endswith("\r\n") and "\n" not in text.replace("\r\n", ""))
q_app = "'" + app_dir.replace("'", "''") + "'"
check("路徑用單引號、裡面的單引號寫兩次（中文、空白照樣）", f"$app = {q_app}" in lines
      and "O''Brien" in text and "程式 O''Brien" in text and "O'Brien" not in text.replace("O''Brien", ""))
check("新資料夾、備份、exe、工作目錄都寫對", f"$new = '{new_dir.replace(chr(39), chr(39) * 2)}'" in lines
      and f"$old = '{(app_dir + '.old').replace(chr(39), chr(39) * 2)}'" in lines
      and f"$exe = '{os.path.join(app_dir, u.EXE_NAME).replace(chr(39), chr(39) * 2)}'" in lines
      and f"$cwd = {q_app}" in lines)


def first(pattern):
    for i, line in enumerate(lines):
        if re.search(pattern, line):
            return i
    return -1


order = [first(r"Wait-Process -Id 4321 "), first(r"Rename-Item -LiteralPath \$app "),
         first(r"Rename-Item -LiteralPath \$new "), first(r"^Start-Process -FilePath \$exe -WorkingDirectory \$cwd$")]
check("順序：等程式關掉 → 改舊的 → 換新的 → 開新版", -1 not in order and order == sorted(order), str(order))
check("舊的改成 .old、新的改成原本的名字", "Rename-Item -LiteralPath $app -NewName 'SRT-Subtitle-Generator-Qt.old'" in text
      and "  Rename-Item -LiteralPath $new -NewName 'SRT-Subtitle-Generator-Qt'" in text)
check("被占用會重試、改不了舊的就不動並開回原本的", "for ($i = 0; $i -lt 20 -and -not $moved; $i++) {" in text
      and "if (-not $moved) { Start-Process -FilePath $exe -WorkingDirectory $cwd; exit 1 }" in text)
check("換新的失敗：把舊的換回來再開", "  Rename-Item -LiteralPath $old -NewName 'SRT-Subtitle-Generator-Qt'" in text
      and text.index("} catch {\r\n  Rename-Item -LiteralPath $old") > text.index("Rename-Item -LiteralPath $new"))
check("pid 只能是整數（不會被塞指令）", "Wait-Process -Id 12 " in u.switch_script("12", app_dir, new_dir, app_dir))
try:
    u.switch_script("12; Remove-Item C:\\", app_dir, new_dir, app_dir)
    injected = True
except ValueError:
    injected = False
check("pid 不是數字：直接拒絕", not injected)
text2 = u.switch_script(1, app_dir, new_dir, elsewhere)
check("設定檔在別處：新版開在那裡", "$cwd = '" + elsewhere + "'" in text2.split("\r\n"))
script = u.write_script(text, tmp)
raw = open(script, "rb").read()
check("存成 UTF-8 加 BOM、CRLF 原樣、中文不亂", raw.startswith(b"\xef\xbb\xbf") and raw[3:].decode("utf-8") == text
      and script.endswith(".ps1"))
cmd = u.script_command(script)
check("執行命令列：不開視窗、不讀使用者設定、只放寬這一次", cmd[0] == "powershell.exe" and cmd[-2:] == ["-File", script]
      and "-NoProfile" in cmd and cmd[cmd.index("-WindowStyle") + 1] == "Hidden"
      and cmd[cmd.index("-ExecutionPolicy") + 1] == "Bypass")

# ----- 6 -----
check("沒有 .old：說沒有", u.cleanup_backup(app_dir) is False)
os.makedirs(os.path.join(app_dir + ".old", "_internal"))
open(os.path.join(app_dir + ".old", u.EXE_NAME), "wb").write(b"MZ old")
check("新版啟動：刪掉 .old", u.cleanup_backup(app_dir) is True and not os.path.exists(app_dir + ".old")
      and os.path.isdir(app_dir))

# ----- 7 -----
src = open(u.__file__, encoding="utf-8").read()
code = [line for line in src.splitlines() if line.startswith(("import ", "from "))]
check("零 GUI 依賴、不 import config", not any(w in " ".join(code) for w in (
    "config", "tkinter", "PySide6", "gui", "updater")), str(code))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("資料夾版自動更新核心測試全數通過。")
