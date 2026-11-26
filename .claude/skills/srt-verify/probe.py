#!/usr/bin/env python3
"""
破壞探針：把程式碼改壞一處、跑對應的測試，確認測試會失敗；跑完一定還原。

    python3 .claude/skills/srt-verify/probe.py probes.json [名稱 ...]

probes.json 是一串：
    [{"name": "no-widen", "file": "gui_qt/editor.py", "old": "if want > 0:", "new": "if False:",
      "test": "tests/test_qt_editor.py", "python": "qt"}]
python："qt"＝/tmp/qtv12/bin/python3（offscreen），"tk"＝/tmp/vtk/bin/python3（DISPLAY=:99），或直接給路徑。
"old" 必須在檔案裡剛好出現一次，否則記成 BADPROBE、不跑。

每個探針：備份 → 改 → 刪 __pycache__ → 用 -B 跑（上限 300 秒）→ 還原 → 比對已還原。
最後印出 missed（測試沒抓到的）；有 missed 或 BADPROBE 時結束碼 1。
"""
import filecmp
import json
import os
import shutil
import subprocess
import sys
import tempfile

PY = {"qt": "/tmp/qtv12/bin/python3", "tk": "/tmp/vtk/bin/python3"}
CACHES = ("gui/__pycache__", "gui_qt/__pycache__", "subtitle/__pycache__", "tests/__pycache__", "__pycache__")


def main(argv):
    probes = json.load(open(argv[1], encoding="utf-8"))
    wanted = set(argv[2:])
    env = dict(os.environ, DISPLAY=":99", QT_QPA_PLATFORM="offscreen")
    env.setdefault("FONTCONFIG_FILE", "/tmp/srt-fonts.conf")
    missed, bad = [], []
    for p in probes:
        if wanted and p["name"] not in wanted:
            continue
        path = p["file"]
        src = open(path, encoding="utf-8").read()
        if src.count(p["old"]) != 1:
            print(f"BADPROBE {p['name']}（出現 {src.count(p['old'])} 次）", flush=True)
            bad.append(p["name"])
            continue
        bak = tempfile.mktemp(suffix=".bak")
        shutil.copy(path, bak)
        try:
            open(path, "w", encoding="utf-8").write(src.replace(p["old"], p["new"]))
            assert not filecmp.cmp(path, bak, shallow=False)
            for d in CACHES:
                shutil.rmtree(d, ignore_errors=True)
            py = PY.get(p.get("python", "qt"), p.get("python"))
            try:
                rc = subprocess.run([py, "-B", p["test"]], env=env, capture_output=True, timeout=300).returncode
            except subprocess.TimeoutExpired:
                rc, p["name"] = 99, p["name"] + "（逾時）"
        finally:
            shutil.copy(bak, path)
            os.remove(bak)
        assert open(path, encoding="utf-8").read() == src, f"{path} 沒還原！"
        caught = rc != 0
        print(("caught " if caught else "MISSED ") + p["name"], flush=True)
        if not caught:
            missed.append(p["name"])
    print("missed:", missed, "badprobe:", bad)
    return 1 if missed or bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
