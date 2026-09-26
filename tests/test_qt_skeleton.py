# -*- coding: utf-8 -*-
"""
3.0 第 1 項第一階段：`gui_qt/` 骨架與 `--qt` 入口開關。

這裡守：

1. 入口：`main.py --qt` 走 Qt 版，**不會**被當成影片檔名掉進命令列批次；
   沒有 PySide6 時結束碼 2、講清楚怎麼裝；gui_qt 內部別的 ImportError
   照樣丟出來（不能被包裝成「請安裝」）。
2. 2.x 不受影響：`gui/`、`subtitle/`、`cli.py` 都不 import PySide6 或
   gui_qt；2.x exe 的 spec 排除 PySide6、shiboken6、gui_qt。
3. 有 PySide6 時（offscreen）：主視窗真的建得起來，四個頁籤名稱與 Tk 版
   一字不差、順序相同；標題帶版號；深淺主題跟 config 的 theme 走，量的
   是實際調色盤的亮度；骨架不寫回設定檔。

沒有 PySide6 的環境（2.x 的 CI）第 3 段略過、其餘照跑。
"""
import importlib.abc
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


# ===== 1. 入口 ===========================================================

# 在子行程裡把 PySide6 擋掉再跑 main.py --qt：不管這台有沒有裝，都驗得到
# 「沒裝」那條路。拿掉 DISPLAY，免得 Tk 對話框跳出來等人按。
BLOCK_AND_RUN = r'''
import importlib.abc, runpy, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[0] in ("PySide6", "shiboken6"):
            raise ImportError(f"blocked {name}", name=name)
        return None
sys.meta_path.insert(0, Block())
import cli
cli.main = lambda *a, **k: print("CLI-WAS-CALLED") or 99
sys.argv = ["main.py", "--qt"]
runpy.run_path(sys.argv[0], run_name="__main__")
'''
env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
env["PYTHONIOENCODING"] = "utf-8"
proc = subprocess.run([sys.executable, "-B", "-c", BLOCK_AND_RUN], cwd=ROOT, env=env,
                      capture_output=True, text=True, encoding="utf-8", timeout=60)
check("沒有 PySide6 時 main.py --qt 結束碼是 2", proc.returncode == 2,
      f"{proc.returncode} {proc.stderr[-300:]}")
check("沒有 PySide6 時講明要 pip install PySide6", "pip install PySide6" in proc.stderr,
      proc.stderr[-300:])
check("--qt 不會被當成影片檔名丟給命令列批次", "CLI-WAS-CALLED" not in proc.stdout,
      proc.stdout[-300:])

import main as entry  # noqa: E402  —— main.py 有 __name__ 守衛，匯入不會開視窗


class _BrokenInside(importlib.abc.MetaPathFinder):
    """模擬 gui_qt 內部缺了別的套件：這是程式錯誤，不是「沒裝 Qt」。"""

    def find_spec(self, name, path, target=None):
        if name == "gui_qt.app":
            raise ImportError("No module named 'numpy'", name="numpy")
        return None


sys.modules.pop("gui_qt.app", None)
sys.meta_path.insert(0, _BrokenInside())
try:
    entry.run_qt(["main.py"])
    raised = None
except ImportError as exc:
    raised = exc
finally:
    sys.meta_path.pop(0)
check("gui_qt 內部別的 ImportError 照樣丟出（不包裝成「請安裝」）",
      raised is not None and raised.name == "numpy", repr(raised))

# ===== 2. 2.x 不受影響 ===================================================

IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+(PySide6|shiboken6|gui_qt)\b", re.M)
offenders = []
for folder in ("gui", "subtitle"):
    for name in sorted(os.listdir(os.path.join(ROOT, folder))):
        if name.endswith(".py") and IMPORT_RE.search(_read(f"{folder}/{name}")):
            offenders.append(f"{folder}/{name}")
for rel in ("cli.py", "config.py", "updater.py"):
    if IMPORT_RE.search(_read(rel)):
        offenders.append(rel)
check("gui/、subtitle/、cli.py 等 2.x 程式都不 import PySide6／gui_qt", not offenders,
      str(offenders))
check("main.py 只在 run_qt 裡面才 import gui_qt（Tk 版啟動不碰 Qt）",
      re.findall(r"^\S.*gui_qt", _read("main.py"), re.M) == [],
      str(re.findall(r"^\S.*gui_qt", _read("main.py"), re.M)))

spec = _read("SRT-Subtitle-Generator.spec")
excludes = re.search(r"excludes=\[(.*?)\]", spec, re.S)
excluded = set(re.findall(r"'([^']+)'", excludes.group(1))) if excludes else set()
check("2.x exe 的 spec 排除 PySide6、shiboken6、gui_qt",
      {"PySide6", "shiboken6", "gui_qt"} <= excluded, str(sorted(excluded)))

check("骨架不寫回設定檔（兩個版本同時開時不能互相蓋掉）",
      "save_config" not in _read("gui_qt/app.py"))

# ===== 3. 真的建視窗（需要 PySide6） =====================================

try:
    import PySide6  # noqa: F401
except ImportError:
    PySide6 = None
    print("SKIP 這個環境沒有 PySide6：略過 Qt 視窗實測")

if PySide6 is not None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import config  # noqa: E402

    tmp = tempfile.mkdtemp(prefix="qt_skeleton_")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")
    with open(config.CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump({"theme": "dark"}, fh)
    before = os.path.getmtime(config.CONFIG_PATH)

    from PySide6.QtCore import QTimer  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import gui_qt.app as qt_app  # noqa: E402
    from updater import APP_VERSION  # noqa: E402

    app = QApplication.instance() or QApplication(["test"])
    seen = {}

    def inspect():
        wins = [w for w in app.topLevelWidgets()
                if isinstance(w, qt_app.MainWindow) and w.isVisible()]
        seen["count"] = len(wins)
        if wins:
            win = wins[0]
            seen["tabs"] = [win.tabs.tabText(i) for i in range(win.tabs.count())]
            seen["title"] = win.windowTitle()
            seen["size"] = (win.width(), win.height())
            seen["lightness"] = win.palette().window().color().lightness()
            win.close()
        app.quit()

    QTimer.singleShot(0, inspect)
    rc = qt_app.main(["test"])
    check("gui_qt.main() 真的開出一個主視窗並正常結束", rc == 0 and seen.get("count") == 1,
          f"rc={rc} {seen}")

    tk_tabs = re.findall(r'notebook\.add\(self\.stage_\w+_tab, text="([^"]+)"\)',
                         _read("gui/app.py"))
    check("Tk 版四個頁籤名稱讀得到（比對的基準存在）", len(tk_tabs) == 4, str(tk_tabs))
    check("Qt 版四個頁籤名稱與 Tk 版一字不差、順序相同",
          seen.get("tabs") == tk_tabs, f"{seen.get('tabs')} != {tk_tabs}")
    check("標題講明是 3.0 預覽版並帶版號",
          "3.0 預覽版" in seen.get("title", "") and APP_VERSION in seen.get("title", ""),
          seen.get("title", ""))
    check("預設視窗大小 1280x800", seen.get("size") == qt_app.DEFAULT_SIZE, str(seen.get("size")))
    check("config 的 theme=dark → 視窗底色真的是深的（亮度 < 128）",
          seen.get("lightness", 255) < 128, str(seen.get("lightness")))
    check("骨架跑完沒有動到設定檔", os.path.getmtime(config.CONFIG_PATH) == before)

    qt_app.apply_theme(app, "light")
    app.processEvents()
    light = qt_app.MainWindow({"theme": "light"})
    check("theme=light → 底色是淺的（亮度 > 128）",
          light.palette().window().color().lightness() > 128,
          str(light.palette().window().color().lightness()))
    check("不認得的 theme 當淺色（同 Tk 版）",
          qt_app.theme_scheme("sepia") == qt_app.theme_scheme("light"))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 gui_qt 骨架與 --qt 入口測試全數通過。")
