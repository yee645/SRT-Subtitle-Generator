# -*- coding: utf-8 -*-
"""
剪輯器關掉、刪掉之後，焦點再換也不會丟例外（E-9a 順手修）。

之前 `focusChanged` 接的是 lambda，視窗刪掉後 Qt 不會斷開，焦點一換就去動已經刪掉的快捷鍵
（RuntimeError: Internal C++ object already deleted）——「改用四頁籤版面」就會碰到。
"""
import copy
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


try:
    import PySide6  # noqa: F401
except ImportError:
    PySide6 = None

if PySide6 is None or not shutil.which("ffmpeg"):
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過剪輯器關掉之後的焦點")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
    from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

    import config  # noqa: E402
    from gui_qt import editor as ed  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")
    errors = []
    sys.excepthook = lambda *exc: errors.append(exc[1])

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    win = ed.EditorWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    win.show()
    wait(80)
    win.activateWindow()
    win.cue_start_spin.setFocus()
    wait(30)
    off = not win.key_shortcuts["next_frame"][0].isEnabled()
    win.player_panel.timeline.setFocus()
    wait(30)
    on = win.key_shortcuts["next_frame"][0].isEnabled()
    check("開著的時候：換焦點照常更新方向鍵（數字框裡關、時間軸上開）", not errors and off and on, f"{off} {on} {errors}")
    a, b = QLineEdit(), QLineEdit()
    for w in (a, b):
        w.show()
    win.player_panel.shutdown()
    win.close()
    win.deleteLater()
    wait(80)
    b.activateWindow()
    b.setFocus()
    wait(30)
    a.activateWindow()
    a.setFocus()
    wait(30)
    check("刪掉之後換焦點：不丟例外", not errors, repr(errors))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("剪輯器關掉之後的焦點測試全數通過。")
