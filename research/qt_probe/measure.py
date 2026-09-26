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

**瘦身實驗**（2026-09-26 第二輪）：onedir 最大的檔裡有四個探針根本沒用到
（`opengl32sw.dll`、`Qt6Quick.dll`、`Qt6Qml.dll`、`Qt6Pdf.dll`，約 37 MB）。
這裡把 onedir 複製幾份、各拿掉其中一個或全部四個，再用 `probe_clip.mp4`
**真的播放**，看解不解得出畫格、會不會當掉。完整版也播一次當對照。拿掉後
播不動是要記錄的結果，不算這支腳本失敗。
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
CLIP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe_clip.mp4")
PLAY_RUNS = 3
# 瘦身實驗要拿掉的檔（比對檔名開頭、不分大小寫；Windows 是 xxx.dll，本機
# Linux 是 libxxx.so.6，兩邊都比得到）。
SLIM_CANDIDATES = {
    "opengl32sw": ("opengl32sw",),
    "Qt6Quick": ("qt6quick.", "libqt6quick.so"),
    "Qt6Qml": ("qt6qml.", "libqt6qml.so"),
    "Qt6Pdf": ("qt6pdf.", "libqt6pdf.so"),
}


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


def run_probe(exe, clip="", runs=RUNS):
    rows = []
    for i in range(runs):
        fd, out = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(out)
        start = time.perf_counter()
        args = [exe, out] + ([clip] if clip else [])
        try:
            proc = subprocess.run(args, timeout=180)
        except subprocess.TimeoutExpired:
            rows.append({"run": i + 1, "error": "逾時（180 秒）"})
            continue
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


def slim_variant(onedir, name, prefixes):
    """複製一份 onedir，拿掉檔名以 prefixes 開頭的檔，回傳 (資料夾, 拿掉的檔)。"""
    dest = onedir + "_no_" + name
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(onedir, dest)
    removed = []
    for root, _dirs, files in os.walk(dest):
        for fname in files:
            if fname.lower().startswith(prefixes):
                os.remove(os.path.join(root, fname))
                removed.append(os.path.relpath(os.path.join(root, fname), dest))
    return dest, sorted(removed)


def play_summary(rows):
    """播放結果濃縮成一格：每次解出幾格、最後狀態、有沒有錯誤。"""
    frames = [r.get("frames_decoded", 0) for r in rows]
    status = sorted({r.get("error") or r.get("media_status")
                     or ("播放器不可用（後端沒載入）" if r.get("player_available") is False
                         else "（沒有狀態）") for r in rows})
    errors = sorted({r.get("player_error", "") for r in rows} - {""})
    ok = all(r.get("exit") == 0 and r.get("frames_decoded", 0) > 0
             and r.get("media_status") == "EndOfMedia" for r in rows)
    return {"ok": ok, "frames": frames, "status": status, "errors": errors}


def slim_experiment(onedir, exe_name):
    variants = [("all4", tuple(p for ps in SLIM_CANDIDATES.values() for p in ps))]
    variants += [(k, v) for k, v in SLIM_CANDIDATES.items()]
    out = [{"variant": "full", "removed": [],
            "mb": round(dir_size(onedir)[0] / 1e6, 2),
            "zip_mb": None,
            "play": play_summary(run_probe(os.path.join(onedir, exe_name),
                                           CLIP, PLAY_RUNS))}]
    for name, prefixes in variants:
        dest, removed = slim_variant(onedir, name, prefixes)
        row = {"variant": name, "removed": removed,
               "mb": round(dir_size(dest)[0] / 1e6, 2), "zip_mb": None}
        if name == "all4":
            row["zip_mb"] = round(zipped_size(dest) / 1e6, 2)
        row["play"] = play_summary(run_probe(os.path.join(dest, exe_name),
                                             CLIP, PLAY_RUNS))
        out.append(row)
        shutil.rmtree(dest, ignore_errors=True)
    return out


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
    report["slim"] = slim_experiment(onedir, os.path.basename(onedir_exe))

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
        "### 瘦身實驗（onedir 拿掉檔案後真的播放 probe_clip.mp4，各 "
        f"{PLAY_RUNS} 次）",
        "",
        "| 拿掉 | 大小 | 播放 | 每次解出畫格 | 最後狀態 | 錯誤 |",
        "|---|---|---|---|---|---|",
    ]
    for row in report["slim"]:
        size = f"{row['mb']} MB" + (f"（zip {row['zip_mb']} MB）" if row["zip_mb"] else "")
        play = row["play"]
        lines.append(
            f"| {row['variant']}（{len(row['removed'])} 檔） | {size} | "
            f"{'OK' if play['ok'] else '失敗'} | {play['frames']} | "
            f"{', '.join(play['status'])} | {'; '.join(play['errors']) or '—'} |")
    lines += [
        "",
        "```json",
        json.dumps(report, ensure_ascii=False, indent=2),
        "```",
    ]
    text = "\n".join(lines)
    # 先寫摘要檔、再印：windows-latest 的主控台編碼是 cp1252，印中文會丟
    # UnicodeEncodeError（第一次跑就是死在這裡，數字已經量完卻沒進摘要）。
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(text)
    # 任何一次沒寫出結果就算失敗：量不到的數字不能當成量到了。
    # 完整版也播不動代表探針或片子本身有問題，瘦身結果就不能信，一併算失敗。
    bad = [r for r in report["onefile_runs"] + report["onedir_runs"] if "error" in r]
    return 1 if bad or not report["slim"][0]["play"]["ok"] else 0


if __name__ == "__main__":
    sys.exit(main())
