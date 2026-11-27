# -*- coding: utf-8 -*-
"""
剪輯器版面 E-9d：健檢頁放得進左側面板（gui_qt/editor.py 的 ReflowGrid、HEALTH_*_LABELS）。

之前健檢的勾選項固定三欄（最小 787px），左側面板只有 634px：右邊的字被切掉、底下撐出橫捲軸。
1. 預設視窗（1440×900）：健檢頁沒有橫捲軸；勾選項排兩欄、每一格都在看得到的範圍裡；上面的說明折行、不被切掉。
2. 兩個收合區塊展開也一樣沒有橫捲軸。
3. 依寬度排欄：寬的時候最多三欄、窄的時候一欄；順序照舊（一列一列排）。
4. 收合區塊的字縮短（括號裡的說明放提示）；展開／收合照樣換 ▸／▾。
5. 四頁籤照舊：固定三欄、收合區塊的字一字不改。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過健檢頁的寬度")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QPoint, QTimer  # noqa: E402
    from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import editor as ed  # noqa: E402
    from gui_qt import health_panel as hp_mod  # noqa: E402
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
    win.resize(1440, 900)
    win.show()
    win.show_section("health")
    wait(150)
    hp = win.health_panel
    area = win.left_pages["health"].findChild(QScrollArea)
    boxes = list(hp.check_boxes.values()) + [hp.filename_box]
    grid = hp.filename_box.parentWidget().layout()

    def right_edge(w):
        return w.mapTo(area.viewport(), QPoint(w.width(), 0)).x()

    def positions():
        return [grid.getItemPosition(grid.indexOf(b))[:2] for b in boxes]

    # ----- 1 -----
    check("預設視窗：健檢頁沒有橫捲軸", not area.horizontalScrollBar().isVisible(),
          f"{area.viewport().width()} < {hp.minimumSizeHint().width()}")
    check("勾選項排兩欄", win.health_reflow.columns == 2, str(win.health_reflow.columns))
    hidden = [b.text() for b in boxes if right_edge(b) > area.viewport().width()]
    check("每一格都在看得到的範圍裡", not hidden, str(hidden))
    check("順序照舊：一列一列排", positions() == [(i // 2, i % 2) for i in range(len(boxes))], str(positions()))
    notes = [lab for lab in hp.findChildren(type(hp.target_label)) if lab.isVisible() and lab.wordWrap()]
    cut = [lab.text()[:12] for lab in notes if right_edge(lab) > area.viewport().width()]
    check("說明折行、沒有被切掉", notes and not cut, str(cut))

    # ----- 2 -----
    hp.show_publish(True)
    hp.show_thumbs(True)
    wait(120)
    check("兩個區塊展開：還是沒有橫捲軸", not area.horizontalScrollBar().isVisible(),
          f"{area.viewport().width()} < {hp.minimumSizeHint().width()}")

    # ----- 3 -----
    reflow = win.health_reflow
    reflow.relayout(3000)
    check("很寬：最多三欄", reflow.columns == 3 and positions() == [(i // 3, i % 3) for i in range(len(boxes))])
    reflow.relayout(200)
    check("很窄：一欄", reflow.columns == 1 and positions() == [(i, 0) for i in range(len(boxes))])
    reflow.relayout(area.viewport().width())
    check("回到原本的寬度：兩欄", reflow.columns == 2)
    # 不手動叫 relayout：面板真的變窄、變寬時自己重排（看捲動區的大小變化）
    old_w = area.width()
    area.setFixedWidth(230)
    wait(120)
    check("面板真的變窄：自己排成一欄", reflow.columns == 1 and positions() == [(i, 0) for i in range(len(boxes))],
          f"{reflow.columns} {area.viewport().width()}")
    area.setFixedWidth(old_w)
    wait(120)
    check("面板變回原本的寬度：自己排回兩欄", reflow.columns == 2, f"{reflow.columns} {area.viewport().width()}")
    area.setMinimumWidth(0)
    area.setMaximumWidth(16777215)

    # ----- 4 -----
    check("收合區塊的字縮短（展開中）", hp.publish_toggle.text() == ed.HEALTH_PUBLISH_LABELS[1]
          and hp.thumb_toggle.text() == ed.HEALTH_THUMB_LABELS[1], hp.publish_toggle.text())
    hp.show_publish(False)
    hp.show_thumbs(False)
    check("收合：換回 ▸", hp.publish_toggle.text() == ed.HEALTH_PUBLISH_LABELS[0]
          and hp.thumb_toggle.text().startswith("▸"))
    check("括號裡的說明放提示", "點一下展開或收合" in hp.publish_toggle.toolTip()
          and "依分數排名" in hp.thumb_toggle.toolTip())
    check("短的字比原本短", len(ed.HEALTH_PUBLISH_LABELS[0]) < len(hp_mod.PUBLISH_CLOSED)
          and len(ed.HEALTH_THUMB_LABELS[0]) < len(hp_mod.THUMB_CLOSED))

    # ----- 5 -----
    tabs = qt_app.MainWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    th = tabs.health_panel
    tgrid = th.filename_box.parentWidget().layout()
    tboxes = list(th.check_boxes.values()) + [th.filename_box]
    check("四頁籤：照舊固定三欄", [tgrid.getItemPosition(tgrid.indexOf(b))[:2] for b in tboxes]
          == [(i // hp_mod.CHECK_COLUMNS, i % hp_mod.CHECK_COLUMNS) for i in range(len(tboxes))])
    check("四頁籤：收合區塊的字一字不改", th.publish_toggle.text() == hp_mod.PUBLISH_CLOSED
          and th.thumb_toggle.text() == hp_mod.THUMB_CLOSED)
    th.show_publish(True)
    check("四頁籤：展開的字照舊", th.publish_toggle.text() == hp_mod.PUBLISH_OPEN)

    for w in (win, tabs):
        w.player_panel.shutdown()
        w.close()
    wait(50)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("健檢頁的寬度（E-9d）測試全數通過。")
