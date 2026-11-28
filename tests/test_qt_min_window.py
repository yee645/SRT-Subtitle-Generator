# -*- coding: utf-8 -*-
"""
剪輯器版面 E-9j：視窗縮到最小（1100×700）時，左側面板的每一頁都放得下（沒有橫捲軸）。

E-9d、E-9e 留下來的：最小視窗時左側面板比智慧剪輯頁要的窄。查到是「封面候選」那一頁把設定與縮圖列左右並排，
兩邊的最窄寬度加起來 519px。剪輯器改成上下排。
1. 1100×700：媒體、字幕、智慧剪輯（四個輸出分頁都看一次）、健檢都沒有橫捲軸。
2. 封面候選：剪輯器裡縮圖列在設定的下面、跟設定一樣寬；四頁籤照舊左右排。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過最小視窗")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
    from PySide6.QtWidgets import QApplication, QBoxLayout, QScrollArea  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
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

    ed.apply_initial_theme(app, "dark")
    win = ed.EditorWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    win.show()
    win.resize(*ed.EDITOR_MIN)
    wait(150)
    check("（準備）視窗是最小的大小", (win.width(), win.height()) == tuple(ed.EDITOR_MIN), str(win.size()))
    rp = win.review_panel

    def no_hbar(key):
        win.show_section(key)
        wait(120)
        areas = win.left_pages[key].findChildren(QScrollArea)
        bad = [f"{a.viewport().width()} < {a.widget().minimumSizeHint().width()}" for a in areas
               if a.horizontalScrollBar().isVisible()]
        return not bad, str(bad)

    # ----- 1 -----
    for key in ("media", "subtitles", "health"):
        ok, info = no_hbar(key)
        check(f"最小視窗：{key} 頁沒有橫捲軸", ok, info)
    for i in range(rp.out_tabs.count()):
        rp.out_tabs.setCurrentIndex(i)
        ok, info = no_hbar("smart")
        check(f"最小視窗：智慧剪輯「{rp.out_tabs.tabText(i)}」沒有橫捲軸", ok, info)

    # ----- 2 -----
    rp.out_tabs.setCurrentIndex([rp.out_tabs.tabText(i) for i in range(rp.out_tabs.count())].index("封面候選"))
    wait(80)
    strip, btn = rp.thumb_strip, rp.thumb_btn
    check("剪輯器：封面候選上下排", rp.thumb_cols.direction() == QBoxLayout.TopToBottom)
    check("剪輯器：縮圖列在設定下面、看得到", strip.isVisible()
          and strip.mapTo(rp, strip.rect().topLeft()).y() > btn.mapTo(rp, btn.rect().bottomLeft()).y(),
          f"{strip.mapTo(rp, strip.rect().topLeft())} {btn.mapTo(rp, btn.rect().bottomLeft())}")
    tabs = qt_app.MainWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    check("四頁籤：封面候選照舊左右排", tabs.review_panel.thumb_cols.direction() == QBoxLayout.LeftToRight)

    for w in (win, tabs):
        w.player_panel.shutdown()
        w.close()
    wait(50)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("最小視窗（E-9j）測試全數通過。")
