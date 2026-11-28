# -*- coding: utf-8 -*-
"""
剪輯器版面 E-9m：開窗時的鍵盤焦點。

之前 Qt 把焦點丟給第一顆能拿焦點的元件——狀態列角落的〔改用四頁籤版面…〕：一開窗那顆就框著強調色，
按 Tab 也從視窗最後面開始走。照主流剪輯軟體改成：
1. 還沒開片子：焦點在時間軸空狀態的〔開啟影片…〕（下一步）。
2. 開了片子：焦點跟著換到時間軸本身（原本那顆藏起來了，不能被 Qt 丟到不相干的地方）。
3. 空白鍵照樣是播放／暫停，不會按到有焦點的按鈕。
4. 焦點不在時間軸區時，開片子不去搶焦點（例如正在字幕表裡）。
"""
import copy
import os
import shutil
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


try:
    import PySide6  # noqa: F401
except ImportError:
    PySide6 = None

if PySide6 is None or not shutil.which("ffmpeg"):
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過開窗時的焦點")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import editor as ed  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def open_and_wait(p, path):
        p.open_video(path)
        waited = 0
        while p.timeline.duration <= 0 and waited < 20000:
            wait(50)
            waited += 50
        wait(80)

    main = os.path.join(tmp, "main.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-t", "3",
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", main], check=True)

    def make():
        w = ed.EditorWindow(copy.deepcopy(config.DEFAULT_CONFIG))
        w.resize(1440, 900)
        w.show()
        w.activateWindow()
        wait(100)
        return w

    ed.apply_initial_theme(app, "dark")
    win = make()
    p = win.player_panel
    corner = next((b for b in win.statusBar().findChildren(ed.QPushButton) if "四頁籤" in b.text()), None)

    # ----- 1 -----
    check("（準備）狀態列角落有〔改用四頁籤版面…〕", corner is not None)
    f = QApplication.focusWidget()
    check("還沒開片子：焦點在〔開啟影片…〕", f is win.timeline_open_btn, repr(f))
    check("不在〔改用四頁籤版面…〕", f is not corner)

    # ----- 3 -----
    hits = []
    win.timeline_open_btn.clicked.connect(lambda *_a: hits.append("open"))
    for sc in win.key_shortcuts["play"]:
        sc.activated.connect(lambda: hits.append("play"))
    real_open = p.open_btn.click
    p.open_btn.click = lambda: hits.append("dialog")  # 萬一真的按到也不要跳出選檔視窗
    QTest.keyClick(QApplication.focusWidget(), Qt.Key_Space)
    wait(30)
    p.open_btn.click = real_open
    check("空白鍵是播放／暫停，沒有按到有焦點的按鈕", hits == ["play"], hits)

    # ----- 2 -----
    open_and_wait(p, main)
    f = QApplication.focusWidget()
    check("開了片子：時間軸區換頁", win.timeline_stack.currentIndex() == 1)
    check("開了片子：焦點跟著換到時間軸", f is p.timeline, repr(f))

    # ----- 4 -----
    win2 = make()
    table = win2.cue_panel.findChild(ed.QAbstractItemView)
    check("（準備）字幕表在", table is not None)
    win2.show_section("subtitles")
    wait(30)
    table.setFocus(Qt.OtherFocusReason)
    wait(30)
    check("（準備）焦點在字幕表", QApplication.focusWidget() is table, repr(QApplication.focusWidget()))
    open_and_wait(win2.player_panel, main)
    check("焦點不在時間軸區：開片子不去搶", QApplication.focusWidget() is table, repr(QApplication.focusWidget()))

    for w in (win, win2):
        w.player_panel.shutdown()
        w.close()
    wait(50)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("開窗時的焦點（E-9m）測試全數通過。")
