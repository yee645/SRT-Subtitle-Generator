# -*- coding: utf-8 -*-
"""
3.0 第 12 項 12-7：切換預設＋3.0.0。

1. 入口（`main.py`，各開一個行程，GUI 的進入點換成印一行字的假的）：
   - 沒帶參數、有新介面 → 開新介面（不開一般版）；
   - 沒帶參數、沒有 PySide6（打包好的一般版 exe 就是這樣）→ **安靜地**開一般版，不跳「請安裝」、結束碼 0；
   - gui_qt 內部別的 ImportError 照樣丟出來（不能被當成「沒裝」吞掉、默默開一般版）；
   - 單獨的 `--tk` → 一般版（就算有新介面）；`--qt` → 新介面；
   - 帶影片檔 → 命令列批次（跟以前一樣，拖檔到一般版 exe 上靠這條）；`--tk 影片` 也是命令列批次，不開視窗。
2. 版本：APP_VERSION 是 3.0.0；打包的 zip 名稱不再帶 preview；Qt 版的導覽、標題是正式版那一套。
3. Release notes：用 release.yml 同一條規則從 CHANGELOG 抽 v3.0.0 那一段：講怎麼拿到新介面、檔名對、連結是完整網址
   （Release 頁面上相對連結會壞）、照實講限制。
4. 文件講的 `python main.py --tk` 跟入口一致。
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "packaging"))

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fp:
        return fp.read()


# ----- 1 -----
RUN = r'''
import importlib.abc, runpy, sys, types
mode, args = sys.argv[1], sys.argv[2:]
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[0] in ("PySide6", "shiboken6"):
            raise ImportError(f"blocked {name}", name=name)
        if mode == "broken" and name == "gui_qt.app":
            raise ImportError("No module named 'numpy'", name="numpy")
        return None
sys.meta_path.insert(0, Block())
if mode == "qt":
    fake = types.ModuleType("gui_qt.app")
    fake.main = lambda argv=None: print("QT-MAIN", argv) or 0
    sys.modules["gui_qt.app"] = fake
import gui.app
gui.app.main = lambda: print("TK-MAIN")
import cli
cli.main = lambda *a, **k: print("CLI", sys.argv[1:]) or 0
import tkinter.messagebox
tkinter.messagebox.showinfo = lambda *a, **k: print("ASKED-TO-INSTALL")
sys.argv = ["main.py"] + args
runpy.run_path("main.py", run_name="__main__")
'''
env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
env["PYTHONIOENCODING"] = "utf-8"


def run(mode, *args):
    p = subprocess.run([sys.executable, "-B", "-c", RUN, mode, *args], cwd=ROOT, env=env, capture_output=True,
                       text=True, encoding="utf-8", timeout=120)
    return p.returncode, p.stdout.strip().splitlines(), p.stderr


rc, out, err = run("qt")
check("沒帶參數、有新介面：開新介面、不開一般版", rc == 0 and out == ["QT-MAIN ['main.py']"], f"{rc} {out} {err[-300:]}")
rc, out, err = run("block")
check("沒帶參數、沒有 PySide6（一般版 exe）：安靜地開一般版、結束碼 0", rc == 0 and out == ["TK-MAIN"]
      and "pip install" not in err, f"{rc} {out} {err[-300:]}")
rc, out, err = run("broken")
check("gui_qt 內部別的 ImportError：照樣丟出來，不默默開一般版", rc != 0 and "TK-MAIN" not in out
      and "numpy" in err, f"{rc} {out} {err[-300:]}")
rc, out, err = run("qt", "--tk")
check("單獨的 --tk：一般版（就算有新介面）", rc == 0 and out == ["TK-MAIN"], f"{rc} {out} {err[-300:]}")
rc, out, err = run("qt", "--qt")
check("--qt：新介面", rc == 0 and out == ["QT-MAIN ['main.py']"], f"{rc} {out}")
rc, out, err = run("block", "--qt")
check("--qt、沒有 PySide6：講怎麼裝、結束碼 2", rc == 2 and "pip install PySide6" in err and "TK-MAIN" not in out,
      f"{rc} {out} {err[-300:]}")
rc, out, err = run("qt", "影片.mp4")
check("帶影片檔：命令列批次（拖檔到 exe 上）", rc == 0 and out == ["CLI ['影片.mp4']"], f"{rc} {out}")
rc, out, err = run("qt", "--tk", "影片.mp4")
check("--tk 加影片檔：照舊是命令列批次、不開視窗", rc == 0 and out == ["CLI ['--tk', '影片.mp4']"], f"{rc} {out}")

# ----- 2 -----
import qt_preview  # noqa: E402
import updater  # noqa: E402
from subtitle import qtguide  # noqa: E402

# 3.0 之後 A-3 起 APP_VERSION 往前走（3.0.1）：這兩條改成跟著版本走，3.0 系列都要成立。
check("APP_VERSION 是 3.0 系列、3.0.0 以上",
      re.fullmatch(r"3\.0\.\d+", updater.APP_VERSION) is not None and qtguide.is_formal(updater.APP_VERSION),
      updater.APP_VERSION)
check("打包的 zip 名稱不再帶 preview", qt_preview.zip_name(updater.APP_VERSION, "win64")
      == f"SRT-Subtitle-Generator-Qt-v{updater.APP_VERSION}-win64.zip")
check("Qt 版的導覽、標題、狀態列是正式版那一套", qtguide.is_formal(updater.APP_VERSION)
      and qtguide.guide_version(updater.APP_VERSION) == qtguide.FORMAL_GUIDE_VERSION)

# ----- 3 -----
release_yml = read(".github/workflows/release.yml")
m = re.search(r'pattern = rf"(.+?)"\n', release_yml)
check("讀得到 release.yml 抽 Release notes 的規則", m is not None)
version = updater.APP_VERSION
pattern = m.group(1).replace("{re.escape(version)}", re.escape(version)) if m else ""
notes_m = re.search(pattern, read("CHANGELOG.md"), re.M | re.S) if m else None
notes = notes_m.group(1).strip() if notes_m else ""
check(f"CHANGELOG 有 v{version}、排最上面", read("CHANGELOG.md").split("\n## ")[1].startswith(f"v{version}"))
check("Release notes 講怎麼拿到新介面、檔名對", "〔下載並安裝新介面〕" in notes
      and qt_preview.zip_name(version, "win64") in notes and "SRT-Subtitle-Generator-Qt.exe" in notes
      and "一般版不會被刪掉" in notes, notes[:200])
links = re.findall(r"\]\(([^)]+)\)", notes)
check("Release notes 的連結都是完整網址（Release 頁面上相對連結會壞）", links and all(
    u.startswith("https://github.com/yee645/SRT-Subtitle-Generator/") for u in links), str(links))
if version != "3.0.0":
    # 3.0 之後 A-3：v3.0.0 沒轉正，從 v2.3.6 更新的人直接跳到這一版，只看得到這一版的 notes。
    check("3.0.0 之後的版本：notes 講為什麼換掉 v3.0.0 的 zip、不再指向它",
          "v3.0.0" in notes and "Python 3.12" in notes and "Qt-v3.0.0-win64.zip" not in notes
          and "手動下載過 v3.0.0" in notes, notes[:300])
    check("3.0.0 之後的版本：notes 照樣帶 3.0 的完整重點（不少於 v3.0.0 那一條的主題）",
          all(w in notes for w in ("字幕疊在真的影片畫面上", "時間軸", "剪點看得見", "多段素材與多軌", "專案檔",
                                    "在程式裡更新")))
check("Release notes 照實講限制、會送什麼", "影音同步" in notes and "不送任何檔案、字幕、設定或帳號資訊" in notes
      and "--tk" in notes)

# ----- 4 -----
for rel in ("docs/WHATS_NEW_3.0.md", "docs/USER_GUIDE.md", "README.md", "subtitle/qtguide.py", "main.py"):
    check(f"{rel} 講到 --tk", "--tk" in read(rel))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0.0 切換預設與發版測試全數通過。")
