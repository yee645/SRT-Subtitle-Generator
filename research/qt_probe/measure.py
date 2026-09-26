# -*- coding: utf-8 -*-
"""
在 windows-latest 上量 qt_probe 打包後的大小與啟動時間（給
`.github/workflows/qt-probe.yml` 用，不是產品的一部分）。

輸入：PyInstaller 產出的 `dist/qt_probe_onefile.exe` 與
`dist/qt_probe_onedir/`。輸出：`qt_probe_report.json`，並把一份 Markdown
摘要附加到 `$GITHUB_STEP_SUMMARY`、同時印到標準輸出（日誌裡看得到）。

啟動時間量兩種：

- **牆上時間**：從 `subprocess` 啟動到行程結束，減去探針自己等的 300ms。
  onefile 的解壓時間只算得進這一種。
- **探針自報的 `shown_ms`**：Python 開始執行到主視窗顯示。

每種各跑 RUNS 次，第一次通常最慢（磁碟快取是冷的），分開列。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

RUNS = 5
PROBE_WAIT_MS = 300  # qt_probe.py 顯示視窗後多等的時間，牆上時間要扣掉。
DIST = "dist"


def dir_size(path):
    total, count = 0, 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            total += os.path.getsize(os.path.join(root, name))
            count += 1
    return total, count


def biggest_files(path, n=12):
    rows = []
    for root, _dirs, files in os.walk(path):
        for name in files:
            full = os.path.join(root, name)
            rows.append((os.path.getsize(full), os.path.relpath(full, path)))
    rows.sort(reverse=True)
    return [{"file": rel, "mb": round(size / 1e6, 2)} for size, rel in rows[:n]]


def zipped_size(path):
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "onedir.zip")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(path):
                for name in files:
                    full = os.path.join(root, name)
                    zf.write(full, os.path.relpath(full, path))
        return os.path.getsize(out)


def run_probe(exe):
    rows = []
    for i in range(RUNS):
        fd, out = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(out)
        start = time.perf_counter()
        proc = subprocess.run([exe, out], timeout=180)
        wall_ms = (time.perf_counter() - start) * 1000 - PROBE_WAIT_MS
        row = {"run": i + 1, "exit": proc.returncode, "wall_ms": round(wall_ms, 1)}
        if os.path.exists(out):
            with open(out, encoding="utf-8") as fh:
                row.update(json.load(fh))
            os.remove(out)
        else:
            row["error"] = "探針沒有寫出結果檔"
        rows.append(row)
    return rows


def summarize(rows, key):
    values = [r[key] for r in rows if key in r]
    if not values:
        return {}
    rest = sorted(values[1:]) or values
    return {"first": values[0], "median_rest": rest[len(rest) // 2],
            "min": min(values), "max": max(values)}


def find_any(path, needles):
    hits = []
    for root, _dirs, files in os.walk(path):
        for name in files:
            low = name.lower()
            if any(n in low for n in needles):
                hits.append(os.path.relpath(os.path.join(root, name), path))
    return sorted(hits)


def main():
    # Windows 上才有 .exe 副檔名；本機（Linux）先跑一次驗證本檔用的是無副檔名。
    ext = ".exe" if os.name == "nt" else ""
    onefile = os.path.join(DIST, "qt_probe_onefile" + ext)
    onedir = os.path.join(DIST, "qt_probe_onedir")
    onedir_exe = os.path.join(onedir, "qt_probe_onedir" + ext)

    report = {"python": sys.version.split()[0]}
    report["onefile_mb"] = round(os.path.getsize(onefile) / 1e6, 2)
    total, count = dir_size(onedir)
    report["onedir_mb"] = round(total / 1e6, 2)
    report["onedir_files"] = count
    report["onedir_zip_mb"] = round(zipped_size(onedir) / 1e6, 2)
    report["onedir_biggest"] = biggest_files(onedir)
    report["multimedia_plugins"] = find_any(onedir, ("ffmpegmediaplugin", "windowsmediaplugin"))
    report["ffmpeg_dlls"] = find_any(onedir, ("avcodec", "avformat", "avutil", "swscale", "swresample"))
    report["license_files"] = find_any(onedir, ("license", "copying", "lgpl"))

    report["onefile_runs"] = run_probe(onefile)
    report["onedir_runs"] = run_probe(onedir_exe)
    for kind in ("onefile", "onedir"):
        rows = report[f"{kind}_runs"]
        report[f"{kind}_wall"] = summarize(rows, "wall_ms")
        report[f"{kind}_shown"] = summarize(rows, "shown_ms")

    with open("qt_probe_report.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    lines = [
        "## qt_probe（PySide6）Windows 打包量測",
        "",
        "| 項目 | onefile | onedir |",
        "|---|---|---|",
        f"| 大小 | {report['onefile_mb']} MB | {report['onedir_mb']} MB"
        f"（{report['onedir_files']} 個檔，zip 後 {report['onedir_zip_mb']} MB） |",
        f"| 啟動（牆上時間，第一次） | {report['onefile_wall'].get('first')} ms"
        f" | {report['onedir_wall'].get('first')} ms |",
        f"| 啟動（牆上時間，其餘中位數） | {report['onefile_wall'].get('median_rest')} ms"
        f" | {report['onedir_wall'].get('median_rest')} ms |",
        f"| 探針自報 shown_ms（其餘中位數） | {report['onefile_shown'].get('median_rest')} ms"
        f" | {report['onedir_shown'].get('median_rest')} ms |",
        "",
        f"- 多媒體外掛：{report['multimedia_plugins'] or '（沒找到）'}",
        f"- FFmpeg DLL：{report['ffmpeg_dlls'] or '（沒找到）'}",
        f"- 授權檔：{report['license_files'] or '（沒找到）'}",
        f"- 播放器回報（onedir 第一次）：{report['onedir_runs'][0].get('player_error', '')}",
        "",
        "```json",
        json.dumps(report, ensure_ascii=False, indent=2),
        "```",
    ]
    text = "\n".join(lines)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    # 任何一次沒寫出結果就算失敗：量不到的數字不能當成量到了。
    bad = [r for r in report["onefile_runs"] + report["onedir_runs"] if "error" in r]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
