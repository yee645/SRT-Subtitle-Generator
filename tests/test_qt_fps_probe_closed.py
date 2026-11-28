# -*- coding: utf-8 -*-
"""
剪輯器版面 E-9l：背景量影格率還沒量好、視窗就關了（物件已刪），量好時不能在背景執行緒丟例外。

之前 `_FpsProbe` 的執行緒量完直接 emit，物件已刪就丟 `RuntimeError: Signal source has been deleted`
（Qt 全套偶爾印出一個 Traceback）。
1. 物件還在：結果照常送回。
2. 物件已刪：執行緒安靜結束，沒有未處理的例外。
"""
import os
import shutil
import sys
import threading

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

if PySide6 is None:
    print("SKIP 這個環境沒有 PySide6：略過背景量影格率")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import shiboken6  # noqa: E402
    from PySide6.QtCore import QCoreApplication  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import subtitle.media as media  # noqa: E402
    from gui_qt import editor  # noqa: E402

    app = QApplication.instance() or QApplication(sys.argv)
    errors = []
    old_hook = threading.excepthook
    threading.excepthook = lambda a: errors.append(a.exc_value)
    real_probe = media.probe_fps
    gate = threading.Event()
    workers = []

    def fake_probe(path):
        workers.append(threading.current_thread())
        gate.wait(10)
        return 25.0

    media.probe_fps = fake_probe
    try:
        # 1. 物件還在：結果照常送回
        got = []
        p1 = editor._FpsProbe()
        p1.done.connect(lambda path, fps: got.append((path, fps)))
        gate.set()
        p1.start("a.mp4")
        for _ in range(200):
            QCoreApplication.processEvents()
            if got:
                break
            threading.Event().wait(0.01)
        check("物件還在：量好的影格率照常送回", got == [("a.mp4", 25.0)], got)

        # 2. 物件已刪才量好
        gate.clear()
        workers.clear()
        p2 = editor._FpsProbe()
        p2.start("b.mp4")
        for _ in range(200):
            if workers:
                break
            threading.Event().wait(0.01)
        shiboken6.delete(p2)
        check("物件已刪（前提）", not shiboken6.isValid(p2))
        gate.set()
        for w in workers:
            w.join(5)
        check("背景執行緒已結束", workers and not any(w.is_alive() for w in workers))
        check("物件已刪才量好：沒有未處理的例外", errors == [], errors)
    finally:
        media.probe_fps = real_probe
        threading.excepthook = old_hook

if failures:
    print(f"\n{len(failures)} 項失敗")
    sys.exit(1)
print("\n背景量影格率（E-9l）介面測試全數通過。")
