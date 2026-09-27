# -*- coding: utf-8 -*-
"""
3.0 第 1 項第二階段：Qt 預覽版打包收尾（`packaging/qt_preview.py`）與工作流程。

不需要 PySide6：打包收尾的每一步都能用假的資料夾與假的 exe 驗。這裡守：

1. 瘦身只刪第 0 項驗過的四個檔，**名字相近的不能誤刪**（Qt6QuickWidgets、
   Qt6QmlModels 等）；非 Windows 一個都不刪（Linux 拿掉 Quick／Qml 播放器
   就不能動）。
2. 授權全文是真的 FSF 原文、三份都有；第三方說明列出 PySide6／Qt／FFmpeg
   與實際打包進去的 FFmpeg 檔名。
3. **自檢不通過就不打 zip、結束碼 1**；通過才打，zip 內以資料夾名開頭。
4. 工作流程：qt-preview.yml 只打包不發佈（權限唯讀、不碰 Release）、入口
   是 qt_entry。release.yml（第三階段）：Qt 工作等 exe 附上之後才跑、失敗
   不影響 2.x、只上傳 zip、打包指令與 qt-preview.yml 逐字相同。
"""
import json
import os
import re
import stat
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "packaging"))

import qt_preview as qp  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def make_tree(base, names):
    for rel in names:
        full = os.path.join(base, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(b"x" * 10)


# ===== 1. 瘦身 ===========================================================

REMOVABLE = ["_internal/PySide6/opengl32sw.dll", "_internal/PySide6/Qt6Quick.dll",
             "_internal/PySide6/QT6QML.DLL", "_internal/PySide6/Qt6Pdf.dll"]
KEEP = ["_internal/PySide6/Qt6QuickWidgets.dll", "_internal/PySide6/Qt6QmlModels.dll",
        "_internal/PySide6/Qt6PdfWidgets.dll", "_internal/PySide6/Qt6Core.dll",
        "_internal/PySide6/Qt6Multimedia.dll", "_internal/PySide6/avcodec-61.dll",
        "_internal/PySide6/plugins/multimedia/ffmpegmediaplugin.dll",
        "SRT-Subtitle-Generator-Qt.exe"]

tmp = tempfile.mkdtemp(prefix="qt_pack_")
tree = os.path.join(tmp, "win")
make_tree(tree, REMOVABLE + KEEP)
removed = qp.slim(tree, windows=True)
check("Windows：剛好刪掉四個檔（不分大小寫）",
      sorted(p.replace("\\", "/") for p in removed) == sorted(REMOVABLE), str(removed))
left = {os.path.relpath(os.path.join(r, f), tree).replace("\\", "/")
        for r, _d, fs in os.walk(tree) for f in fs}
check("名字相近的不誤刪（Qt6QuickWidgets、Qt6QmlModels、Qt6PdfWidgets…）",
      left == set(KEEP), str(sorted(set(KEEP) - left)))

tree2 = os.path.join(tmp, "linux")
make_tree(tree2, REMOVABLE + KEEP)
check("非 Windows 一個都不刪（Linux 拿掉 Quick／Qml 播放器就不能動）",
      qp.slim(tree2, windows=False) == [])

# ===== 2. 授權 ===========================================================

HEADS = {"LGPL-3.0.txt": ("GNU LESSER GENERAL PUBLIC LICENSE", "Version 3, 29 June 2007"),
         "GPL-3.0.txt": ("GNU GENERAL PUBLIC LICENSE", "Version 3, 29 June 2007"),
         "LGPL-2.1.txt": ("GNU LESSER GENERAL PUBLIC LICENSE", "Version 2.1, February 1999")}
for name, (title, ver) in HEADS.items():
    text = _read(f"packaging/licenses/{name}")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    check(f"{name} 是 FSF 原文全文（標題、版本、長度）",
          lines[:2] == [title, ver] and len(text) > 7000, str(lines[:2]))
check("LGPL-3.0 引用的 GPL-3.0 條款真的在全文裡（不是截斷的）",
      "END OF TERMS AND CONDITIONS" in _read("packaging/licenses/GPL-3.0.txt"))

got = qp.add_licenses(tree)
check("licenses/ 放了三份全文＋第三方說明",
      got == sorted(list(HEADS) + ["THIRD_PARTY_NOTICES.txt"]), str(got))
notice = open(os.path.join(tree, "licenses", "THIRD_PARTY_NOTICES.txt"), encoding="utf-8").read()
for word in ("PySide6", "Qt 6", "FFmpeg", "LGPL-3.0-only", "LGPL-2.1-or-later",
             "avcodec-61.dll", "LGPL-3.0.txt", "GPL-3.0.txt", "LGPL-2.1.txt"):
    check(f"第三方說明提到「{word}」", word in notice)

# ===== 3. 自檢把關 =======================================================

def fake_exe(folder, ok):
    """假的 exe：照 --selftest 的介面寫結果檔。"""
    path = os.path.join(folder, "fake.exe")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"#!{sys.executable}\n"
                 "import json, sys\n"
                 "out = sys.argv[sys.argv.index('--selftest') + 1]\n"
                 f"json.dump({{'ok': {ok}, 'frames_decoded': {50 if ok else 0}}}, open(out, 'w'))\n"
                 f"sys.exit({0 if ok else 1})\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


if os.name == "nt":
    print("SKIP 假 exe 需要 shebang，Windows 上略過自檢把關實測")
else:
    clip = os.path.join(ROOT, "research", "qt_probe", "probe_clip.mp4")
    for ok in (False, True):
        work = tempfile.mkdtemp(prefix=f"qt_gate_{ok}_")
        dist = os.path.join(work, "SRT-Subtitle-Generator-Qt")
        make_tree(dist, KEEP)
        fake_exe(dist, ok)
        cwd = os.getcwd()
        os.chdir(work)
        try:
            real_stdout = sys.stdout
            rc = qp.main(["qt_preview.py", dist, "fake.exe", clip])
        finally:
            sys.stdout = real_stdout
            os.chdir(cwd)
        zips = [f for f in os.listdir(work) if f.endswith(".zip")]
        report = json.load(open(os.path.join(work, "qt_preview_report.json"), encoding="utf-8"))
        if not ok:
            check("自檢不通過 → 結束碼 1、不打 zip", rc == 1 and not zips, f"rc={rc} {zips}")
            check("自檢不通過 → 報告寫明失敗", report["selftest_ok"] is False)
        else:
            check("自檢通過 → 結束碼 0、打出 zip", rc == 0 and len(zips) == 1, f"rc={rc} {zips}")
            names = zipfile.ZipFile(os.path.join(work, zips[0])).namelist() if zips else []
            check("zip 內每個檔都在 SRT-Subtitle-Generator-Qt/ 底下（解開就是一個資料夾）",
                  names and all(n.startswith("SRT-Subtitle-Generator-Qt/") for n in names))
            check("zip 裡有授權資料夾",
                  "SRT-Subtitle-Generator-Qt/licenses/LGPL-3.0.txt" in names)
            check("zip 檔名帶版號", qp.APP_VERSION in zips[0] if zips else False)

# ===== 4. 工作流程 =======================================================

wf = _read(".github/workflows/qt-preview.yml")
check("qt-preview 工作流程權限唯讀（只打包、不發佈）",
      "contents: read" in wf and "contents: write" not in wf)
check("qt-preview 不碰 Release／tag",
      not any(w in wf for w in ("softprops", "gh release", "create-release", "git tag")))
check("qt-preview 入口是 packaging/qt_entry.py（雙擊就開 Qt 版，不是 Tk 版）",
      "packaging/qt_entry.py" in wf)
check("qt-preview 用 onedir（第 0 項結論）", "--onedir" in wf and "--onefile" not in wf)
check("qt-preview 打包後跑自檢收尾", "packaging/qt_preview.py" in wf)
check("動到 gui_qt 的 PR 會觸發 qt-preview", '"gui_qt/**"' in wf)

# --- release.yml：第三階段把 zip 附到 Release，但 2.x 的 exe 不能被牽連 ---
# 用文字切工作（測試不引入 PyYAML）：頂層 jobs 底下兩格縮排的鍵就是工作名。
rel = _read(".github/workflows/release.yml")
jobs_at = rel.index("\njobs:\n")
job_heads = [(m.start(), m.group(1)) for m in
             re.finditer(r"^  ([\w-]+):\s*$", rel[jobs_at:], re.M)]
jobs = {}
for i, (start, name) in enumerate(job_heads):
    end = job_heads[i + 1][0] if i + 1 < len(job_heads) else len(rel) - jobs_at
    jobs[name] = rel[jobs_at + start:jobs_at + end]
# 註解行不算（下一個工作上方的說明註解會落在前一個工作的切片裡）。
jobs = {k: "\n".join(ln for ln in v.splitlines() if not ln.lstrip().startswith("#"))
        for k, v in jobs.items()}
main_job, qt_job = jobs.get("build-and-release", ""), jobs.get("qt-preview", "")
check("release.yml 有 build-and-release 與 qt-preview 兩個工作",
      set(jobs) == {"build-and-release", "qt-preview"}, str(list(jobs)))
check("2.x 那個工作沒有裝 PySide6（收緊原檢查：只看 2.x 工作本身）",
      "PySide6" not in main_job and "pip install pyinstaller openai zhconv sv-ttk" in main_job)
check("2.x 那個工作照舊上傳 exe、照舊用 spec 打包",
      "dist/SRT-Subtitle-Generator.exe" in main_job
      and "pyinstaller SRT-Subtitle-Generator.spec" in main_job)
check("Qt 工作等 2.x 工作做完才開始（exe 已經附上）",
      re.search(r"^    needs: build-and-release\s*$", qt_job, re.M) is not None)
check("Qt 工作失敗不影響 2.x（continue-on-error: true）",
      re.search(r"^    continue-on-error: true\s*$", qt_job, re.M) is not None)
check("Release 已存在、跳過建置時 Qt 工作也跳過",
      "needs.build-and-release.outputs.created == 'true'" in qt_job
      and "created: ${{ steps.resolve.outputs.exists != 'true' }}" in main_job
      and "id: resolve" in main_job and 'fp.write(f"exists={exists}\\n")' in main_job)
check("Qt 工作只上傳預覽版 zip，不碰 exe",
      "SRT-Subtitle-Generator-Qt-preview-*.zip" in qt_job
      and "SRT-Subtitle-Generator.exe" not in qt_job)
check("自動更新只認 exe（Release 上多一個 zip 不會被誤抓）",
      'ASSET_NAME = "SRT-Subtitle-Generator.exe"' in _read("updater.py"))


def _run_lines(text):
    return [ln.strip() for ln in text.splitlines() if ln.strip().startswith(
        ("run: pip install pyinstaller PySide6", "run: pyinstaller --noconfirm --onedir",
         "run: python packaging/qt_preview.py"))]


check("Release 的 Qt 打包與 PR 上驗過的 qt-preview.yml 逐字相同（不會出現兩套）",
      len(_run_lines(qt_job)) == 3 and _run_lines(qt_job) == _run_lines(wf),
      f"{_run_lines(qt_job)} != {_run_lines(wf)}")
check("qt_entry 直接進 gui_qt（不經 main.py 的 Tk 預設）",
      "from gui_qt.app import main" in _read("packaging/qt_entry.py")
      and "gui.app" not in _read("packaging/qt_entry.py"))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 預覽版打包收尾與工作流程測試全數通過。")
