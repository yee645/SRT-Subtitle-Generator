# -*- coding: utf-8 -*-
"""
資料夾版自動更新的切換實測（3.0 第 12 項 12-4）——**只在 Windows 上跑**（CI 的 qt-preview 工作）。

容器裡驗不到 Windows「執行中的資料夾不能改名」、PowerShell 5.1 讀中文路徑、Start-Process 開 exe 這幾件事，
這裡用**這次 CI 剛打包好的真 zip** 走一遍 `subtitle/onedirupdate.py` 的完整流程：

1. 在「含中文、空白、單引號」的路徑放一份舊版（同一份成品加上記號檔）、設定、一鍵安裝的工具。
2. 起一個工作目錄在舊版資料夾裡的行程（模擬還開著的程式：Windows 上它在就不能改名），4 秒後自己結束。
3. 解壓新版、帶上設定與工具、寫切換腳本、用 `script_command` 的同一套命令列跑 PowerShell。
4. 驗：腳本等到那個行程結束才換；舊的變成 `.old`、新的換上原本的名字、暫存資料夾不見；設定與工具在；
   新版的 exe 真的被開起來（從換上的資料夾，工作目錄就是那裡）、而且**新版自己**把 `.old` 刪掉
   （`gui_qt/app.py` 的 `_cleanup_previous_update`，不是由這裡代刪）。最後關掉它。

用法：`python packaging/switch_selftest.py <zip>`。結果寫進 `switch_selftest_report.json` 與工作流程摘要；
有一項不對就回傳 1。不是 Windows 就印一行略過、回傳 0（本機的單元測試在 tests/test_onedirupdate.py）。
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from subtitle import onedirupdate as odu  # noqa: E402

HOLD_SECONDS = 4


def _ps(command):
    """跑一行 PowerShell，回傳 stdout（去頭尾空白）。"""
    out = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    return out.stdout.strip()


def _running_from(folder):
    """Qt 版的 exe 有沒有從 folder 開起來；回傳那些行程的 pid。"""
    name = odu.EXE_NAME[:-4]
    text = _ps(f"Get-Process -Name '{name}' -ErrorAction SilentlyContinue | "
               "ForEach-Object { \"$($_.Id)`t$($_.Path)\" }")
    pids = []
    for line in text.splitlines():
        pid, _, path = line.partition("\t")
        if path and os.path.normcase(os.path.dirname(path)) == os.path.normcase(folder):
            pids.append(int(pid))
    return pids


def run(zip_path):
    checks = []

    def check(name, cond, extra=""):
        checks.append({"name": name, "ok": bool(cond), "extra": str(extra)[:300]})
        print(("PASS " if cond else "FAIL ") + name + (f"（{extra}）" if extra and not cond else ""), flush=True)

    work = tempfile.mkdtemp(prefix="switch-")
    parent = os.path.join(work, "更新 測試 O'Brien")
    app_dir = os.path.join(parent, "SRT-Subtitle-Generator-Qt")
    os.makedirs(parent)

    # 1. 舊版：同一份成品＋記號檔、設定、工具
    with zipfile.ZipFile(zip_path) as zf:
        top = odu.check_zip(zf)
        zf.extractall(work)
    shutil.move(os.path.join(work, top), app_dir)
    open(os.path.join(app_dir, "old.marker"), "w").write("old")
    open(os.path.join(app_dir, "config.json"), "w", encoding="utf-8").write('{"theme": "dark", "qt_guide_seen": "never"}')
    os.makedirs(os.path.join(app_dir, "tools", "ffmpeg", "bin"))
    open(os.path.join(app_dir, "tools", "ffmpeg", "bin", "marker.txt"), "w").write("ff")

    # 2. 還開著的程式：工作目錄在舊版資料夾裡（在的時候資料夾不能改名）
    holder = subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({HOLD_SECONDS})"], cwd=app_dir)
    started = time.time()

    # 3. 解壓、帶過去、寫腳本、跑
    new_dir = odu.extract(zip_path, app_dir, "v-selftest")
    copied = odu.carry_over(app_dir, app_dir, new_dir)
    check("帶過去設定與工具", sorted(copied) == ["config.json", "tools"], copied)
    script = odu.write_script(odu.switch_script(holder.pid, app_dir, new_dir, odu.work_dir(app_dir, app_dir)),
                              tempfile.mkdtemp(prefix="srt-update-"))
    proc = subprocess.run(odu.script_command(script), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=240)
    elapsed = time.time() - started
    holder.wait(timeout=30)
    check("切換腳本成功結束", proc.returncode == 0, f"exit {proc.returncode} {proc.stdout} {proc.stderr}")
    check(f"等程式關掉才換（至少 {HOLD_SECONDS} 秒）", elapsed >= HOLD_SECONDS - 0.5, f"{elapsed:.1f} 秒")

    # 4. 驗結果
    old = odu.backup_path(app_dir)
    check("舊的變成 .old", os.path.isfile(os.path.join(old, "old.marker")))
    check("新的換上原本的名字", os.path.isfile(os.path.join(app_dir, odu.EXE_NAME))
          and not os.path.exists(os.path.join(app_dir, "old.marker")))
    check("暫存資料夾不見", not os.path.exists(new_dir))
    check("設定與工具在新版裡", open(os.path.join(app_dir, "config.json"), encoding="utf-8").read().startswith('{"theme": "dark"')
          and os.path.isfile(os.path.join(app_dir, "tools", "ffmpeg", "bin", "marker.txt")))
    pids = []
    for _ in range(60):
        pids = _running_from(app_dir)
        if pids:
            break
        time.sleep(0.5)
    # 新版的 main() 一開始就刪上一次換下來的 .old（gui_qt/app.py 的 _cleanup_previous_update）：
    # 等它自己刪（剛寫下的檔可能被防毒掃描占住一下），不是由這裡代刪
    for _ in range(40):
        if not os.path.exists(old):
            break
        time.sleep(0.5)
    left = []
    for root, _dirs, files in os.walk(old):
        left += [os.path.relpath(os.path.join(root, f), old) for f in files]
    check("新版開起來時自己刪掉 .old", not os.path.exists(old), f"還在，剩 {len(left)} 個檔：{left[:10]}")
    check("新版真的被開起來（從換上的資料夾）", pids, _ps(f"Get-Process -Name '{odu.EXE_NAME[:-4]}' "
                                                   "-ErrorAction SilentlyContinue | Select-Object Id,Path | Out-String"))
    for pid in pids:
        _ps(f"Stop-Process -Id {pid} -Force")
    for _ in range(40):
        if not _running_from(app_dir):
            break
        time.sleep(0.25)
    shutil.rmtree(work, ignore_errors=True)
    return checks, round(elapsed, 2)


def main(argv):
    if os.name != "nt":
        print("SKIP 切換實測只在 Windows 上跑（本機單元測試見 tests/test_onedirupdate.py）")
        return 0
    if len(argv) != 2:
        print(__doc__)
        return 2
    zips = sorted(glob.glob(argv[1]))
    if not zips:
        print(f"找不到 zip：{argv[1]}")
        return 1
    checks, elapsed = run(zips[0])
    passed = all(c["ok"] for c in checks)
    with open("switch_selftest_report.json", "w", encoding="utf-8") as fh:
        json.dump({"zip": os.path.basename(zips[0]), "passed": passed, "elapsed": elapsed, "checks": checks},
                  fh, ensure_ascii=False, indent=2)
    lines = ["## 資料夾版自動更新：切換實測", "", f"- zip：{os.path.basename(zips[0])}",
             f"- 結果：{'全部通過' if passed else '有失敗'}（腳本等了 {elapsed} 秒）", ""]
    lines += [f"- {'✅' if c['ok'] else '❌'} {c['name']}" for c in checks]
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
