# -*- coding: utf-8 -*-
"""
3.0 第 12 項 12-4：資料夾版自動更新的 Windows 切換實測（packaging/switch_selftest.py）與 zip 名稱。

切換實測本身只能在 Windows 上跑（CI）；這裡驗本機驗得到的：

1. zip 名稱（packaging/qt_preview.zip_name）：3.0 之前帶 preview、3.0.0 起不帶；兩種都被 onedirupdate.pick_zip 認得。
2. 不是 Windows：印一行略過、回傳 0（不會在 Linux 上假裝驗過）。
3. 兩個工作流程都在打好 zip **之後**跑切換實測；release.yml 裡實測在**上傳 zip 之前**（沒過就不附 zip）；
   PR 的 artifact 收實測報告；release 說明不再寫「目前只有外框」。
4. 實測走的是 onedirupdate 的同一套（extract、carry_over、switch_script、write_script、script_command、cleanup_backup），
   不是另外寫一份；路徑含中文、空白、單引號；有「還開著的程式」佔住舊資料夾。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "packaging"))

import qt_preview as qp  # noqa: E402
from subtitle import onedirupdate as odu  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


# ----- 1 -----
check("3.0 之前：帶 preview", qp.zip_name("2.3.6", "win64") == "SRT-Subtitle-Generator-Qt-preview-v2.3.6-win64.zip"
      and qp.zip_name("v2.9.9", "win64") == "SRT-Subtitle-Generator-Qt-preview-v2.9.9-win64.zip")
check("3.0.0 起：不帶 preview", qp.zip_name("3.0.0", "win64") == "SRT-Subtitle-Generator-Qt-v3.0.0-win64.zip"
      and qp.zip_name("v3.1.2", "win64") == "SRT-Subtitle-Generator-Qt-v3.1.2-win64.zip"
      and qp.zip_name("10.0.0", "win64") == "SRT-Subtitle-Generator-Qt-v10.0.0-win64.zip")
check("版本看不懂：當預覽版（保守）", "preview" in qp.zip_name("abc", "win64"))
for version in ("2.3.6", "3.0.0"):
    name = qp.zip_name(version, "win64")
    got = odu.pick_zip({"assets": [{"name": name, "browser_download_url": f"{odu.DOWNLOAD_PREFIX}v{version}/{name}"}]})
    check(f"自動更新認得 {version} 的 zip", got is not None and got["name"] == name)
check("打包時用的就是 zip_name", "zip_path = zip_name(APP_VERSION, suffix)" in read("packaging/qt_preview.py"))

# ----- 2 -----
if os.name != "nt":
    out = subprocess.run([sys.executable, "-B", os.path.join(ROOT, "packaging", "switch_selftest.py"), "x.zip"],
                         capture_output=True, text=True, timeout=60)
    check("不是 Windows：印一行略過、回傳 0", out.returncode == 0 and out.stdout.startswith("SKIP"), out.stdout + out.stderr)

# ----- 3 -----
qt_wf = read(".github/workflows/qt-preview.yml")
rel = read(".github/workflows/release.yml")
step = 'run: python packaging/switch_selftest.py "SRT-Subtitle-Generator-Qt-*.zip"'
check("PR 的 Qt 工作：打好 zip 之後跑切換實測", step in qt_wf
      and qt_wf.index("run: python packaging/qt_preview.py") < qt_wf.index(step))
check("PR 的 artifact 收實測報告與兩種名稱的 zip", "switch_selftest_report.json" in qt_wf
      and "SRT-Subtitle-Generator-Qt-*.zip" in qt_wf and "Qt-preview-*.zip" not in qt_wf)
check("發版：打好 zip → 切換實測 → 才上傳（沒過就不附）", step in rel
      and rel.index("run: python packaging/qt_preview.py") < rel.index(step)
      < rel.index('gh release upload "$env:RELEASE_TAG" "$($zip.FullName)"'))
check("release 說明不再寫「目前只有外框」、講得到程式裡可以更新", "目前只有外框" not in rel and "下載並安裝" in rel)

# ----- 4 -----
src = read("packaging/switch_selftest.py")
check("走 onedirupdate 的同一套", all(f"odu.{fn}(" in src for fn in (
    "check_zip", "extract", "carry_over", "switch_script", "write_script", "script_command",
    "work_dir", "backup_path")))
check("路徑含中文、空白、單引號", "更新 測試 O'Brien" in src)
check("有「還開著的程式」佔住舊資料夾、驗等它關掉才換", "cwd=app_dir" in src and "等程式關掉才換" in src
      and "HOLD_SECONDS" in src)
check("驗新版真的開起來、從換上的資料夾", "新版真的被開起來" in src and "_running_from(app_dir)" in src)
check("驗 .old 是新版自己刪的（不是實測代刪）", "新版開起來時自己刪掉 .old" in src and "cleanup_backup" not in src.split("def run(")[1])

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("切換實測與 zip 名稱測試全數通過。")
