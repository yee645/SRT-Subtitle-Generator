# -*- coding: utf-8 -*-
"""
3.0 預覽版打包的收尾：PyInstaller（onedir）跑完之後做的事。

`.github/workflows/qt-preview.yml` 在 windows-latest 上呼叫；本機也能跑
（只驗流程，Linux 上不刪檔，見下）。

1. **瘦身**：刪掉 `docs/ROADMAP_3.0.md` 第 0 項驗過可以拿掉的四個檔
   （opengl32sw、Qt6Quick、Qt6Qml、Qt6Pdf，zip 58→43 MB）。**只在 Windows
   刪**：Linux 上 Qt 的多媒體外掛依賴 Quick／Qml，拿掉播放器就不能動（同
   一份實測）。
2. **授權**：PySide6 的 wheel 裡一個授權檔都沒有，PyInstaller 也不會自己
   放，所以這裡把 LGPL-3.0／GPL-3.0／LGPL-2.1 全文（取自 Debian
   base-files 附的 FSF 原文）與第三方元件說明放進 `licenses/`。
3. **自檢**：用打包好的 exe 跑 `--selftest` 真的播放一支影片，**播不出來就
   失敗**——沒刪壞才打 zip。
4. **打 zip**，並把結果寫成 `qt_preview_report.json`＋工作流程摘要。

用法：`python packaging/qt_preview.py <onedir 資料夾> <exe 檔名> <測試影片>`
"""
import importlib.metadata as md
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from updater import APP_VERSION  # noqa: E402

# 比對檔名開頭、不分大小寫。依據：ROADMAP_3.0「四個大檔能否排除」Windows 實測。
WINDOWS_REMOVABLE = ("opengl32sw.", "qt6quick.", "qt6qml.", "qt6pdf.")
LICENSE_FILES = ("LGPL-3.0.txt", "GPL-3.0.txt", "LGPL-2.1.txt")
SELFTEST_RUNS = 3


def slim(dist, windows=None):
    """刪掉可拿掉的大檔；回傳刪掉的相對路徑。非 Windows 不刪。"""
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return []
    removed = []
    for root, _dirs, files in os.walk(dist):
        for name in files:
            if name.lower().startswith(WINDOWS_REMOVABLE):
                full = os.path.join(root, name)
                os.remove(full)
                removed.append(os.path.relpath(full, dist))
    return sorted(removed)


def _version(dist_name):
    try:
        return md.version(dist_name)
    except md.PackageNotFoundError:
        return "（未安裝）"


def qt_version():
    """PySide6 附帶的 Qt 函式庫版本（讀不到回傳 None）。"""
    try:
        from PySide6 import QtCore
        return QtCore.qVersion()
    except Exception:  # noqa: BLE001 —— 打包機上沒有 PySide6 時說明照寫，只是少版本
        return None


FFMPEG_LIB = re.compile(r"^(lib)?(avcodec|avformat|avutil|swresample|swscale)[-.]", re.I)


def ffmpeg_libs(dist):
    """打包進去的 FFmpeg 函式庫檔名（avcodec-61.dll 這類），寫進說明。"""
    hits = set()
    for _root, _dirs, files in os.walk(dist):
        hits.update(name for name in files if FFMPEG_LIB.match(name))
    return sorted(hits)


def _find_lib(dist, stem):
    pat = re.compile(rf"^(lib)?{stem}[-.]", re.I)
    for root, _dirs, files in os.walk(dist):
        for name in sorted(files):
            if pat.match(name) and (name.lower().endswith(".dll") or ".so" in name.lower()
                                    or name.lower().endswith(".dylib")):
                return os.path.join(root, name)
    return None


# 在另一個行程裡載入函式庫問它自己（av_version_info／avutil_license／avcodec_configuration）：
# 載入失敗或當掉都不會拖垮打包。Linux 上 Qt 的 avutil 需要系統的 libcrypto 先載入（2026-11-25 實測）。
_PROBE = r"""
import ctypes, json, os, sys
avutil, avcodec = sys.argv[1], sys.argv[2]
if os.name == "nt":
    os.add_dll_directory(os.path.dirname(os.path.abspath(avutil)))
else:
    for name in ("libcrypto.so.3", "libcrypto.so"):
        try:
            ctypes.CDLL(name, mode=ctypes.RTLD_GLOBAL)
            break
        except OSError:
            pass
out = {}
lib = ctypes.CDLL(avutil)
for key, fn in (("version", "av_version_info"), ("license", "avutil_license")):
    f = getattr(lib, fn)
    f.restype = ctypes.c_char_p
    out[key] = f().decode("utf-8", "replace")
try:  # 編譯設定是加分；avcodec 載不起來（缺相依的函式庫）也要把版本交出去
    f = ctypes.CDLL(avcodec).avcodec_configuration
    f.restype = ctypes.c_char_p
    out["configuration"] = f().decode("utf-8", "replace")
except (OSError, AttributeError):
    pass
print(json.dumps(out))
"""


def ffmpeg_info(dist, timeout=60):
    """
    打包進去的 FFmpeg 自報的版本、授權與編譯設定。LGPL-2.1 第 4 節要附「對應的原始碼」，
    所以說明要指向**同一版**；版本號從函式庫本身讀，不靠猜。讀不到的欄位就不在回傳的 dict 裡。
    """
    avutil = _find_lib(dist, "avutil")
    if not avutil:
        return {}
    # 一律絕對路徑：Windows 的 os.add_dll_directory 收到相對路徑會丟 WinError 87（CI 帶的是 dist/…，
    # 2026-11-25 #226 第一輪的 CI 就是這樣讀不到版本）。
    avutil = os.path.abspath(avutil)
    avcodec = os.path.abspath(_find_lib(dist, "avcodec") or "") if _find_lib(dist, "avcodec") else ""
    error = ""
    try:
        proc = subprocess.run([sys.executable, "-I", "-c", _PROBE, avutil, avcodec], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if proc.returncode == 0:
            info = json.loads(proc.stdout.strip().splitlines()[-1])
        else:
            info = {}
            tail = (proc.stderr or "").strip().splitlines()
            error = f"結束碼 {proc.returncode}：{tail[-1] if tail else '（沒有訊息）'}"
    except subprocess.TimeoutExpired:
        info, error = {}, f"逾時（{timeout} 秒）"
    except (ValueError, IndexError, OSError) as exc:
        info, error = {}, f"{type(exc).__name__}：{exc}"
    if "version" not in info:
        # 讀不到時把原因與找到的檔案記進打包報告（說明裡不寫），下次才查得到為什麼。
        info["error"] = error or "沒有回報版本"
        info["lib"] = os.path.relpath(avutil, os.path.abspath(dist))
    version = info.get("version", "")
    # 正式版號長得像 7.1.2；從 git 編的會是 n7.1-xxx 或一串雜湊，那種就不組下載網址。
    info["release"] = bool(re.fullmatch(r"\d+\.\d+(\.\d+)?", version))
    return info


REPO_URL = "https://github.com/yee645/SRT-Subtitle-Generator"


def source_urls(pyside, qt, ffmpeg):
    """
    各元件**同一版**的原始碼位置（GPL-3.0 第 6 節 d：原始碼可以放在第三方的伺服器，但要在目的碼旁邊
    寫清楚去哪裡拿）。版本讀不到就給上層目錄。
    """
    urls = {}
    if pyside and pyside[0].isdigit():
        urls["pyside"] = (f"https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{pyside}-src/")
    else:
        urls["pyside"] = "https://download.qt.io/official_releases/QtForPython/"
    if qt and re.fullmatch(r"\d+\.\d+\.\d+", qt):
        mm = ".".join(qt.split(".")[:2])
        urls["qt"] = f"https://download.qt.io/official_releases/qt/{mm}/{qt}/"
        urls["qt_archive"] = f"https://download.qt.io/archive/qt/{mm}/{qt}/"
    else:
        urls["qt"] = "https://download.qt.io/official_releases/qt/"
    if ffmpeg.get("release"):
        urls["ffmpeg"] = f"https://ffmpeg.org/releases/ffmpeg-{ffmpeg['version']}.tar.xz"
    else:
        urls["ffmpeg"] = "https://ffmpeg.org/download.html"
    return urls


def notices_text(dist, ffmpeg=None):
    from subtitle import qtguide
    formal = qtguide.is_formal(APP_VERSION)
    libs = ffmpeg_libs(dist)
    ffmpeg = ffmpeg_info(dist) if ffmpeg is None else ffmpeg
    pyside, qt = _version("PySide6"), qt_version()
    urls = source_urls(pyside, qt, ffmpeg)
    ff_ver = ffmpeg.get("version") or "（讀不到版本）"
    lines = [
        f"SRT 字幕生成器 {'3.0 新介面' if formal else '3.0 預覽版'} —— 第三方元件與授權",
        "",
        f"本程式版本：v{APP_VERSION}（{'新介面，資料夾版' if formal else 'Qt 預覽版'}）",
        f"本程式的原始碼：{REPO_URL}（tag v{APP_VERSION}）",
        "",
        "本程式以動態連結方式使用下列 LGPL 元件，未經修改。它們是本資料夾",
        "裡獨立的 DLL 檔，你可以自行換成相容的其他版本。",
        "",
        f"* Qt for Python（PySide6 {pyside}、shiboken6 {_version('shiboken6')}）",
        "  授權：LGPL-3.0-only（亦可選 GPL-2.0／GPL-3.0，另有商業授權）",
        f"  原始碼（同一版）：{urls['pyside']}",
        f"* Qt 6 函式庫{' ' + qt if qt else ''}（隨 PySide6 附帶，Qt6*.dll 與 plugins/）",
        "  授權：LGPL-3.0-only",
        f"  原始碼（同一版）：{urls['qt']}",
    ]
    if "qt_archive" in urls:
        lines.append(f"  （較舊的版本會移到：{urls['qt_archive']}）")
    lines += [
        f"* FFmpeg {ff_ver}（Qt Multimedia 內建的解碼器，Qt 公司編譯）",
        f"  檔案：{', '.join(libs) if libs else '（本次打包沒有找到）'}",
        "  授權：LGPL-2.1-or-later"
        + (f"（函式庫自報：{ffmpeg['license']}）" if ffmpeg.get("license") else ""),
        f"  原始碼（同一版）：{urls['ffmpeg']}",
    ]
    if ffmpeg.get("configuration"):
        lines.append(f"  編譯設定（函式庫自報）：{ffmpeg['configuration']}")
    lines += [
        "",
        "你的權利：",
        "  你可以修改上列函式庫、把資料夾裡的 DLL 換成你自己修改過或其他相容的版本，",
        "  也可以為了除錯這類修改而對本程式做逆向工程；本程式的使用條款不限制這些事",
        "  （LGPL-3.0 第 4 節、LGPL-2.1 第 6 節）。",
        "",
        "授權全文在同一個資料夾：LGPL-3.0.txt、GPL-3.0.txt（LGPL-3.0 以它為",
        "基礎，必須一起附）、LGPL-2.1.txt。",
        "",
    ]
    return "\n".join(lines)


def add_licenses(dist, ffmpeg=None):
    dest = os.path.join(dist, "licenses")
    os.makedirs(dest, exist_ok=True)
    for name in LICENSE_FILES:
        shutil.copyfile(os.path.join(HERE, "licenses", name), os.path.join(dest, name))
    with open(os.path.join(dest, "THIRD_PARTY_NOTICES.txt"), "w", encoding="utf-8") as fh:
        fh.write(notices_text(dist, ffmpeg))
    return sorted(os.listdir(dest))


def selftest(exe, clip, runs=SELFTEST_RUNS):
    rows = []
    for i in range(runs):
        fd, out = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(out)
        try:
            proc = subprocess.run([exe, "--selftest", out, clip], timeout=120)
            row = {"run": i + 1, "exit": proc.returncode}
        except subprocess.TimeoutExpired:
            row = {"run": i + 1, "exit": None, "error": "逾時（120 秒）"}
        if os.path.exists(out):
            with open(out, encoding="utf-8") as fh:
                row.update(json.load(fh))
            os.remove(out)
        else:
            row.setdefault("error", "自檢沒有寫出結果檔")
            row["ok"] = False
        rows.append(row)
    return rows


def dir_size(path):
    return sum(os.path.getsize(os.path.join(r, f))
               for r, _d, files in os.walk(path) for f in files)


def zip_name(version, suffix):
    """
    發版附的 zip 檔名。3.0 之前是預覽版（名稱帶 preview）；3.0.0 起 Qt 版是正式版（第 12 項 12-4）。
    兩種名稱都以 `SRT-Subtitle-Generator-Qt` 開頭、`-win64.zip` 結尾，資料夾版自動更新
    （`subtitle/onedirupdate.pick_zip`）都認得。
    """
    major = str(version).lstrip("vV").split(".")[0]
    preview = not (major.isdigit() and int(major) >= 3)
    return f"SRT-Subtitle-Generator-Qt-{'preview-' if preview else ''}v{str(version).lstrip('vV')}-{suffix}.zip"


def make_zip(dist, zip_path):
    base = os.path.basename(os.path.normpath(dist))
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(dist):
            for name in files:
                full = os.path.join(root, name)
                zf.write(full, os.path.join(base, os.path.relpath(full, dist)))
    return os.path.getsize(zip_path)


def check_links(urls, opener=None, timeout=30):
    """
    說明裡的原始碼網址實際連一次（HEAD，必要時退回 GET），回傳 {鍵: 狀態碼或錯誤}。
    只在 CI 上跑（開發容器連不到 download.qt.io／ffmpeg.org）；結果寫進工作流程摘要，不擋打包。
    """
    import urllib.error
    import urllib.request
    opener = opener or urllib.request.urlopen
    out = {}
    for key, url in urls.items():
        status = None
        for method in ("HEAD", "GET"):
            req = urllib.request.Request(url, method=method, headers={"User-Agent": "srt-subtitle-generator-ci"})
            try:
                with opener(req, timeout=timeout) as resp:
                    status = resp.status
                break
            except urllib.error.HTTPError as exc:
                status = exc.code
                if exc.code not in (403, 405):  # 有些伺服器不收 HEAD
                    break
            except (urllib.error.URLError, OSError) as exc:
                status = f"連不上：{exc}"
                break
        out[key] = status
    return out


def links_main(report_path):
    with open(report_path, encoding="utf-8") as fh:
        report = json.load(fh)
    result = check_links(report.get("source_urls", {}))
    lines = ["## 第三方元件原始碼網址", ""] + [
        f"- {'✅' if code == 200 else '❌'} `{key}` {report['source_urls'][key]} → {code}"
        for key, code in result.items()]
    text = "\n".join(lines)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(text)
    return 0 if result and all(code == 200 for code in result.values()) else 1


def main(argv):
    if len(argv) == 3 and argv[1] == "--check-links":
        return links_main(argv[2])
    if len(argv) != 4:
        print(__doc__)
        return 2
    dist, exe_name, clip = argv[1], argv[2], os.path.abspath(argv[3])
    exe = os.path.join(dist, exe_name)
    report = {"version": APP_VERSION, "platform": sys.platform,
              "before_mb": round(dir_size(dist) / 1e6, 2)}
    report["removed"] = slim(dist)
    report["ffmpeg"] = ffmpeg_info(dist)
    report["qt"] = qt_version()
    report["source_urls"] = source_urls(_version("PySide6"), report["qt"], report["ffmpeg"])
    report["licenses"] = add_licenses(dist, report["ffmpeg"])
    report["selftest"] = selftest(exe, clip)
    passed = all(r.get("ok") and r.get("exit") == 0 for r in report["selftest"])
    report["selftest_ok"] = passed
    report["after_mb"] = round(dir_size(dist) / 1e6, 2)
    if passed:
        suffix = "win64" if os.name == "nt" else sys.platform
        zip_path = zip_name(APP_VERSION, suffix)
        report["zip"] = zip_path
        report["zip_mb"] = round(make_zip(dist, zip_path) / 1e6, 2)

    with open("qt_preview_report.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    frames = [r.get("frames_decoded") for r in report["selftest"]]
    lines = [
        "## 3.0 新介面（Qt）打包",
        "",
        f"- 版本：v{APP_VERSION}（{sys.platform}）",
        f"- 大小：{report['before_mb']} MB → 刪檔後 {report['after_mb']} MB"
        + (f"，zip {report['zip_mb']} MB" if passed else ""),
        f"- 刪掉：{report['removed'] or '（無）'}",
        f"- 授權：{report['licenses']}",
        f"- FFmpeg（函式庫自報）：{report['ffmpeg'].get('version') or '讀不到（' + report['ffmpeg'].get('error', '沒有函式庫') + '）'}，"
        f"{report['ffmpeg'].get('license', '讀不到授權')}；Qt {report['qt'] or '讀不到'}",
        f"- 自檢（播放 {os.path.basename(clip)}，{SELFTEST_RUNS} 次）："
        f"{'通過' if passed else '**失敗**'}，每次解出畫格 {frames}",
        "",
        "```json",
        json.dumps(report, ensure_ascii=False, indent=2),
        "```",
    ]
    text = "\n".join(lines)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    # windows-latest 主控台是 cp1252，印中文會丟例外（第 0 項踩過）。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(text)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
