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


def ffmpeg_libs(dist):
    """打包進去的 FFmpeg 函式庫檔名（avcodec-61.dll 這類），寫進說明。"""
    pat = re.compile(r"^(lib)?(avcodec|avformat|avutil|swresample|swscale)[-.]", re.I)
    hits = set()
    for _root, _dirs, files in os.walk(dist):
        hits.update(name for name in files if pat.match(name))
    return sorted(hits)


def notices_text(dist):
    libs = ffmpeg_libs(dist)
    return "\n".join([
        "SRT 字幕生成器 3.0 預覽版 —— 第三方元件與授權",
        "",
        f"本程式版本：v{APP_VERSION}（Qt 預覽版）",
        "",
        "本程式以動態連結方式使用下列 LGPL 元件，未經修改。它們是本資料夾",
        "裡獨立的 DLL 檔，你可以自行換成相容的其他版本。",
        "",
        f"* Qt for Python（PySide6 {_version('PySide6')}、shiboken6 {_version('shiboken6')}）",
        "  授權：LGPL-3.0-only（亦可選 GPL-2.0／GPL-3.0，另有商業授權）",
        "  原始碼：https://download.qt.io/official_releases/QtForPython/",
        "* Qt 6 函式庫（隨 PySide6 附帶，Qt6*.dll 與 plugins/）",
        "  授權：LGPL-3.0-only",
        "  原始碼：https://download.qt.io/official_releases/qt/",
        "* FFmpeg（Qt Multimedia 內建的解碼器）",
        f"  檔案：{', '.join(libs) if libs else '（本次打包沒有找到）'}",
        "  授權：LGPL-2.1-or-later",
        "  原始碼：https://ffmpeg.org/download.html",
        "",
        "授權全文在同一個資料夾：LGPL-3.0.txt、GPL-3.0.txt（LGPL-3.0 以它為",
        "基礎，必須一起附）、LGPL-2.1.txt。",
        "",
    ])


def add_licenses(dist):
    dest = os.path.join(dist, "licenses")
    os.makedirs(dest, exist_ok=True)
    for name in LICENSE_FILES:
        shutil.copyfile(os.path.join(HERE, "licenses", name), os.path.join(dest, name))
    with open(os.path.join(dest, "THIRD_PARTY_NOTICES.txt"), "w", encoding="utf-8") as fh:
        fh.write(notices_text(dist))
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


def make_zip(dist, zip_path):
    base = os.path.basename(os.path.normpath(dist))
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(dist):
            for name in files:
                full = os.path.join(root, name)
                zf.write(full, os.path.join(base, os.path.relpath(full, dist)))
    return os.path.getsize(zip_path)


def main(argv):
    if len(argv) != 4:
        print(__doc__)
        return 2
    dist, exe_name, clip = argv[1], argv[2], os.path.abspath(argv[3])
    exe = os.path.join(dist, exe_name)
    report = {"version": APP_VERSION, "platform": sys.platform,
              "before_mb": round(dir_size(dist) / 1e6, 2)}
    report["removed"] = slim(dist)
    report["licenses"] = add_licenses(dist)
    report["selftest"] = selftest(exe, clip)
    passed = all(r.get("ok") and r.get("exit") == 0 for r in report["selftest"])
    report["selftest_ok"] = passed
    report["after_mb"] = round(dir_size(dist) / 1e6, 2)
    if passed:
        suffix = "win64" if os.name == "nt" else sys.platform
        zip_path = f"SRT-Subtitle-Generator-Qt-preview-v{APP_VERSION}-{suffix}.zip"
        report["zip"] = zip_path
        report["zip_mb"] = round(make_zip(dist, zip_path) / 1e6, 2)

    with open("qt_preview_report.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    frames = [r.get("frames_decoded") for r in report["selftest"]]
    lines = [
        "## 3.0 預覽版打包",
        "",
        f"- 版本：v{APP_VERSION}（{sys.platform}）",
        f"- 大小：{report['before_mb']} MB → 刪檔後 {report['after_mb']} MB"
        + (f"，zip {report['zip_mb']} MB" if passed else ""),
        f"- 刪掉：{report['removed'] or '（無）'}",
        f"- 授權：{report['licenses']}",
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
