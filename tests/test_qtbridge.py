# -*- coding: utf-8 -*-
"""
3.0 第 12 項 12-5：一般版到 3.0 新介面的橋（subtitle/qtbridge.py）。

1. 名稱對得上：一般版 exe 的名稱跟 updater.ASSET_NAME 一樣；裝新介面的資料夾跟打包流程（release.yml 的 --name）
   打出來的頂層資料夾同名。
2. bridge_dir：只有打包好的 Windows 一般版 exe 才有橋（原始碼、Linux、Qt 版的 exe 都沒有）。
   should_offer：沒有橋、勾過不再提醒、旁邊已經有新介面的資料夾（就算是空的）都不提示。
3. offer：3.0 以後的正式版、附資料夾版 zip 才提示；**不要求比目前新**；3.0 之前的預覽版、草稿、prerelease、
   沒附 zip、網址不是這個專案的都不提示；Release 頁面只開 GitHub 自己的。fetch_offer：換掉連線；離線、回應壞掉回 None。
4. install（換掉連線，zip 用發版時同一支打包程式做）：裝到 exe 旁邊、exe 在、設定與生字本從設定檔的資料夾複製、
   tools 從 exe 旁邊複製、一般版自己的那份不動；進度、preparing 呼叫一次；不留 zip、.part、暫存資料夾。
   已經裝了：不下載、講清楚；取消：什麼都不留；zip 壞掉、複製失敗：講原因、什麼都不留。
5. launch_args：工作目錄＝新資料夾。說明文字講裝在哪、多大、會送什麼、一般版留著。
6. 零 GUI 依賴、不 import config。
"""
import io
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "packaging"))

import qt_preview  # noqa: E402  —— 真的打包程式（發版時用它打 zip）
import updater  # noqa: E402
from subtitle import onedirupdate as odu  # noqa: E402
from subtitle import qtbridge as qb  # noqa: E402
from subtitle import updatecheck  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def error_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except odu.UpdateError as exc:
        return str(exc)
    return None


# ----- 1 -----
release_yml = open(os.path.join(ROOT, ".github", "workflows", "release.yml"), encoding="utf-8").read()
check("一般版 exe 的名稱跟 updater.ASSET_NAME 一樣", qb.TK_EXE_NAME == updater.ASSET_NAME)
check("新介面的資料夾跟打包出來的頂層資料夾同名", f"--name {qb.QT_FOLDER} " in release_yml
      and qb.QT_FOLDER == odu.EXE_NAME[:-4])

# ----- 2 -----
win_exe = r"C:\Users\使用者\字幕工具\SRT-Subtitle-Generator.exe" if os.name == "nt" else "/opt/字幕工具/SRT-Subtitle-Generator.exe"
check("打包好的 Windows 一般版：橋在 exe 的資料夾", qb.bridge_dir(True, win_exe, "win32") == os.path.dirname(win_exe))
check("檔名大小寫不同也認得", qb.bridge_dir(True, win_exe.replace("Generator.exe", "generator.EXE"), "win32")
      == os.path.dirname(win_exe))
check("從原始碼跑：沒有橋", qb.bridge_dir(False, win_exe, "win32") is None)
check("Linux／macOS：沒有橋", qb.bridge_dir(True, win_exe, "linux") is None and qb.bridge_dir(True, win_exe, "darwin") is None)
check("Qt 版的 exe：沒有橋（它自己會更新自己）",
      qb.bridge_dir(True, os.path.join(os.path.dirname(win_exe), odu.EXE_NAME), "win32") is None)
check("python.exe 之類的：沒有橋", qb.bridge_dir(True, "python.exe", "win32") is None and qb.bridge_dir(True, "", "win32") is None)

tmp = tempfile.mkdtemp()
exe_dir = os.path.join(tmp, "字幕 工具 O'Brien")
os.makedirs(exe_dir)
check("旁邊沒有新介面、沒勾過：提示", qb.should_offer(exe_dir, None) is True and qb.should_offer(exe_dir, "") is True)
check("沒有橋：不提示", qb.should_offer(None, None) is False)
check("勾過不再提醒：不提示", qb.should_offer(exe_dir, qb.NEVER) is False)
os.makedirs(qb.qt_dir(exe_dir))
check("旁邊已經有新介面的資料夾（就算是空的）：不提示", qb.should_offer(exe_dir, None) is False
      and qb.installed_exe(exe_dir) is None)
shutil.rmtree(qb.qt_dir(exe_dir))
check("qt_dir 在 exe 旁邊", qb.qt_dir(exe_dir) == os.path.join(exe_dir, qb.QT_FOLDER))

# ----- 3 -----
TAG = "v3.0.0"
ZIP_NAME = qt_preview.zip_name("3.0.0", "win64")
URL = f"{odu.DOWNLOAD_PREFIX}{TAG}/{ZIP_NAME}"


def release(tag=TAG, name=ZIP_NAME, url=URL, size=0, **extra):
    data = {"tag_name": tag, "html_url": f"https://github.com/yee645/SRT-Subtitle-Generator/releases/tag/{tag}",
            "assets": [{"name": "SRT-Subtitle-Generator.exe", "browser_download_url": f"{odu.DOWNLOAD_PREFIX}{tag}/x.exe"},
                       {"name": name, "browser_download_url": url, "size": size}]}
    data.update(extra)
    return data


got = qb.offer(release(size=1234))
check("3.0.0 正式版、附 zip：提示", got == {"version": TAG, "asset": {"name": ZIP_NAME, "url": URL, "size": 1234},
                                       "page": "https://github.com/yee645/SRT-Subtitle-Generator/releases/tag/v3.0.0"},
      str(got))
check("不要求比目前新（一般版更新到 3.0.0 之後，最新版就是自己）",
      qb.offer(release()) is not None and updatecheck.newer_release(release(), "3.0.0") is None)
check("更新的 3.x 也提示", qb.offer(release(tag="v3.2.1")) is not None)
pre = qt_preview.zip_name("2.9.9", "win64")
check("3.0 之前（附的是預覽版 zip）：不提示", qb.offer(release(tag="v2.9.9", name=pre,
                                                       url=f"{odu.DOWNLOAD_PREFIX}v2.9.9/{pre}")) is None
      and "preview" in pre)
check("草稿、prerelease：不提示", qb.offer(release(draft=True)) is None and qb.offer(release(prerelease=True)) is None)
check("沒附 zip：不提示", qb.offer({"tag_name": TAG, "assets": [{"name": "SRT-Subtitle-Generator.exe"}]}) is None)
check("網址不是這個專案的：不提示", qb.offer(release(url=URL.replace("yee645", "someone"))) is None)
check("回應壞掉：不提示", qb.offer(None) is None and qb.offer("x") is None and qb.offer({}) is None
      and qb.offer({"tag_name": "", "assets": []}) is None)
check("Release 頁面不是 GitHub 的：換成固定的最新 Release 頁",
      qb.offer(release(html_url="https://evil.example/x"))["page"] == updatecheck.RELEASES_PAGE)


class FakeResponse(io.BytesIO):
    def __init__(self, data, length=None):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data) if length is None else length)}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


requests = []


def api_opener(payload):
    def opener(request, timeout=None):
        requests.append((request.full_url, dict(request.header_items()), timeout))
        if isinstance(payload, Exception):
            raise payload
        return FakeResponse(payload)
    return opener


got = qb.fetch_offer(opener=api_opener(json.dumps(release()).encode("utf-8")))
check("fetch_offer：查同一個 API、帶固定的 User-Agent、回傳 offer", got is not None and got["version"] == TAG
      and requests[-1][0] == updatecheck.API_URL and requests[-1][1].get("User-agent") == "SRT-Subtitle-Generator",
      str(requests[-1:]))
check("fetch_offer：離線回 None", qb.fetch_offer(opener=api_opener(OSError("offline"))) is None)
check("fetch_offer：回應不是 JSON 回 None", qb.fetch_offer(opener=api_opener(b"<html>")) is None)

# ----- 4 -----
dist = os.path.join(tmp, "dist", qb.QT_FOLDER)
os.makedirs(os.path.join(dist, "_internal"))
open(os.path.join(dist, odu.EXE_NAME), "wb").write(b"MZ qt")
open(os.path.join(dist, "_internal", "lib.dll"), "wb").write(b"dll")
zip_path = os.path.join(tmp, ZIP_NAME)
qt_preview.make_zip(dist, zip_path)
zip_bytes = open(zip_path, "rb").read()
asset = {"name": ZIP_NAME, "url": URL, "size": len(zip_bytes)}
info = {"version": TAG, "asset": asset, "page": ""}

config_dir = os.path.join(tmp, "設定在別處")
os.makedirs(config_dir)
open(os.path.join(config_dir, "config.json"), "w", encoding="utf-8").write('{"theme": "dark"}')
open(os.path.join(config_dir, "quicktranslate_vocab.json"), "w", encoding="utf-8").write("[]")
open(os.path.join(exe_dir, "config.json"), "w", encoding="utf-8").write('{"這份": "不是設定檔所在的那份"}')
os.makedirs(os.path.join(exe_dir, "tools", "ffmpeg", "bin"))
open(os.path.join(exe_dir, "tools", "ffmpeg", "bin", "ffmpeg.exe"), "wb").write(b"ff")
open(os.path.join(exe_dir, qb.TK_EXE_NAME), "wb").write(b"MZ tk")

downloads = []


def zip_opener(data=zip_bytes):
    def opener(request, timeout=None):
        downloads.append(request.full_url)
        return FakeResponse(data)
    return opener


def leftovers():
    """exe 資料夾裡除了一般版原本的東西與新介面以外還剩什麼（zip、.part、暫存資料夾）。"""
    return sorted(set(os.listdir(exe_dir)) - {qb.TK_EXE_NAME, "config.json", "tools", qb.QT_FOLDER})


progress, preparing = [], []
qt_exe = qb.install(info, exe_dir, config_dir, progress=lambda d, t: progress.append((d, t)),
                    preparing=lambda: preparing.append(1), opener=zip_opener())
target = qb.qt_dir(exe_dir)
check("裝到 exe 旁邊、回傳新介面的 exe", qt_exe == os.path.join(target, odu.EXE_NAME) and os.path.isfile(qt_exe)
      and open(qt_exe, "rb").read() == b"MZ qt" and os.path.isfile(os.path.join(target, "_internal", "lib.dll")))
check("下載的是 Release 附件的網址", downloads == [URL])
check("進度回報到總大小、preparing 呼叫一次", progress and progress[-1] == (len(zip_bytes), len(zip_bytes))
      and preparing == [1], f"{progress[-1:]} {preparing}")
check("設定與生字本從設定檔所在的資料夾複製", open(os.path.join(target, "config.json"), encoding="utf-8").read()
      == '{"theme": "dark"}' and os.path.isfile(os.path.join(target, "quicktranslate_vocab.json")))
check("tools 從 exe 旁邊複製", open(os.path.join(target, "tools", "ffmpeg", "bin", "ffmpeg.exe"), "rb").read() == b"ff")
check("一般版自己的那份不動（是複製不是搬）", os.path.isfile(os.path.join(config_dir, "config.json"))
      and os.path.isdir(os.path.join(exe_dir, "tools")) and os.path.isfile(os.path.join(exe_dir, qb.TK_EXE_NAME)))
check("不留 zip、.part、暫存資料夾", leftovers() == [], str(leftovers()))
check("裝好之後 installed_exe 找得到、不再提示", qb.installed_exe(exe_dir) == qt_exe
      and qb.should_offer(exe_dir, None) is False)

downloads.clear()
msg = error_of(qb.install, info, exe_dir, config_dir, opener=zip_opener())
check("已經裝了：不下載、講清楚在哪", downloads == [] and msg == qb.ALREADY.format(path=target), str(msg))
shutil.rmtree(target)

msg = error_of(qb.install, info, exe_dir, config_dir, cancelled=lambda: True, opener=zip_opener())
check("取消：講已取消、什麼都不留", msg == odu.CANCELLED and not os.path.exists(target) and leftovers() == [],
      f"{msg} {leftovers()}")

bad = b"PK" + b"\0" * (len(zip_bytes) - 2)
msg = error_of(qb.install, dict(info, asset=dict(asset, size=len(bad))), exe_dir, config_dir, opener=zip_opener(bad))
check("zip 壞掉：講原因、什麼都不留", msg and "zip" in msg and not os.path.exists(target) and leftovers() == [],
      f"{msg} {leftovers()}")

real_copytree = shutil.copytree


def broken_copytree(*a, **k):
    raise OSError("磁碟滿了")


shutil.copytree = broken_copytree
try:
    msg = error_of(qb.install, info, exe_dir, config_dir, opener=zip_opener())
finally:
    shutil.copytree = real_copytree
check("複製工具失敗：講原因、不留解一半的資料夾", msg and msg.startswith("安裝失敗") and "磁碟滿了" in msg
      and not os.path.exists(target) and leftovers() == [], f"{msg} {leftovers()}")

msg = error_of(qb.install, dict(info, asset=dict(asset, url=URL.replace("yee645", "x"))), exe_dir, config_dir,
               opener=zip_opener())
check("網址不對：不下載", msg == odu.BAD_URL and not os.path.exists(target))

# carry：新資料夾已經有的不蓋
fresh = os.path.join(tmp, "fresh")
os.makedirs(os.path.join(fresh, "tools"))
open(os.path.join(fresh, "config.json"), "w").write("新的")
check("carry：新資料夾已經有的不蓋", qb.carry(exe_dir, config_dir, fresh) == ["quicktranslate_vocab.json"]
      and open(os.path.join(fresh, "config.json")).read() == "新的")

# ----- 5 -----
args, cwd = qb.launch_args(qt_exe)
check("開新介面：工作目錄＝新資料夾（複製過去的設定檔在那裡）", args == [qt_exe] and cwd == target)
text = qb.offer_text(dict(info, asset=dict(asset, size=150_000_000)), exe_dir)
check("說明：版本、多大、裝在哪、帶什麼、一般版留著", TAG in text and "約 150 MB" in text and target in text
      and "設定、生字本與一鍵安裝的工具" in text and "一般版不會被刪掉" in text, text)
check("說明：沒寫大小時不亂講", "MB" not in qb.offer_text(dict(info, asset=dict(asset, size=0)), exe_dir))
check("會送什麼：只有查版本與下載，不送檔案、字幕、設定、帳號", "不送任何檔案、字幕、設定或帳號資訊" in qb.SENDS
      and "GitHub" in qb.SENDS)
check("裝好的說明：路徑、怎麼再開、一般版留著", qt_exe in qb.done_text(qt_exe) and "一般版照樣留著" in qb.done_text(qt_exe))

# ----- 6 -----
src = open(qb.__file__, encoding="utf-8").read()
imports = [ln.strip() for ln in src.splitlines() if ln.strip().startswith(("import ", "from "))]
check("零 GUI 依賴、不 import config", imports and not any(
    w in ln for ln in imports for w in ("tkinter", "PySide6", "gui", "import config", "from config")), str(imports))

shutil.rmtree(tmp, ignore_errors=True)
print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 一般版到新介面的橋（核心）測試全數通過。")
