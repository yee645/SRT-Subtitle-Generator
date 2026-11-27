# -*- coding: utf-8 -*-
"""
剪輯器版面 E-9e：智慧剪輯頁放得進左側面板（gui_qt/flow_layout.py：放不下就換行）。

之前偵測設定一列五組數字框、輸出分頁一列四到六顆按鈕（最小 1113px），左側面板只有 634px，右邊被切掉。
1. 預設視窗（1440×900）：智慧剪輯頁沒有橫捲軸；每個看得到的元件都在看得到的範圍裡（每一個輸出分頁都量）。
2. 標籤跟它的數字框綁在一起（換行不會拆開）；同一行裡垂直置中。
3. 流式排版：窄的時候行數變多、寬的時候變少；藏起來的元件不佔位置。
4. 搬過去的元件照常能用（按鈕的動作、勾選框的值）。
5. 四頁籤照舊：沒有換成流式排版。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過智慧剪輯頁的寬度")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QPoint, QTimer  # noqa: E402
    from PySide6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QApplication, QComboBox, QLabel,  # noqa: E402
                                   QLineEdit, QScrollArea, QWidget)

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import editor as ed  # noqa: E402
    from gui_qt import flow_layout as fl  # noqa: E402
    from gui_qt import review_panel as rp_mod  # noqa: E402
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
    win.show_section("smart")
    wait(150)
    rp = win.review_panel
    area = win.left_pages["smart"].findChild(QScrollArea)
    vp = area.viewport()

    def right_edge(w):
        return w.mapTo(vp, QPoint(w.width(), 0)).x()

    KINDS = (QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit, QLabel)

    def cut_off():
        out = []
        for w in rp.findChildren(QWidget):
            if isinstance(w, KINDS) and w.isVisible() and w.width() > 0 and right_edge(w) > vp.width() + 1:
                out.append(getattr(w, "text", lambda: type(w).__name__)()[:16])
        return out

    # ----- 1 -----
    check("預設視窗：智慧剪輯頁沒有橫捲軸", not area.horizontalScrollBar().isVisible(),
          f"{vp.width()} < {rp.minimumSizeHint().width()}")
    check("每個看得到的元件都在範圍裡（上半部）", not cut_off(), str(cut_off()))
    for i in range(rp.out_tabs.count()):
        rp.out_tabs.setCurrentIndex(i)
        wait(40)
        check(f"輸出分頁「{rp.out_tabs.tabText(i)}」：沒有被切掉、沒有橫捲軸",
              not cut_off() and not area.horizontalScrollBar().isVisible(), str(cut_off()))
    rp.out_tabs.setCurrentIndex(0)

    # ----- 2 -----
    spins = [rp.spins[key] for key, *_rest in rp_mod.SPINS]
    pairs = [s.parentWidget() for s in spins]
    check("偵測設定：每個數字框跟它的標籤綁成一組", all(p.objectName() == "flowPair" for p in pairs)
          and all(isinstance(p.layout().itemAt(0).widget(), QLabel) for p in pairs))
    check("關鍵字輸入欄跟「關鍵字」綁成一組", rp.search_edit.parentWidget().objectName() == "flowPair")
    rows = win.smart_flows
    check("（準備）有換成流式排版", len(rows) >= 6, str(len(rows)))
    settings_flow = rows[0].flow  # 偵測設定那一框（flow_grid 換的）
    lines = settings_flow.rows(settings_flow.geometry().width())
    centered = True
    for line in lines:
        mids = [w.geometry().center().y() for w in line]
        centered &= max(mids) - min(mids) <= 2
    check("同一行裡垂直置中（標籤跟數字框對齊）", lines and centered, str(lines))

    # ----- 3 -----
    flow = settings_flow
    check("窄的時候行數變多、寬的時候變少", len(flow.rows(200)) > len(flow.rows(600)) >= len(flow.rows(3000)) == 1,
          f"{len(flow.rows(200))} {len(flow.rows(600))} {len(flow.rows(3000))}")
    # 藏起來的元件不佔位置：直接拿 FlowLayout 試（一顆窄的、一顆很寬但藏起來的）
    from PySide6.QtWidgets import QPushButton, QWidget  # noqa: E402
    host = QWidget()
    demo = fl.FlowLayout(host)
    small, wide, other = QPushButton("短"), QPushButton("很長很長很長很長很長很長的按鈕"), QPushButton("另一顆")
    for b in (small, wide, other):
        demo.addWidget(b)
    host.show()
    wait(30)
    wide.hide()
    wait(30)
    in_rows = [w for line in demo.rows(3000) for w in line]
    check("藏起來的元件不佔位置（不排進任何一行、不撐寬最窄寬度）", in_rows == [small, other]
          and demo.minimumSize().width() < wide.sizeHint().width(), f"{in_rows} {demo.minimumSize().width()}")
    host.close()
    check("會折行的說明沒有被塞進流式排版（它自己折行）", rp.status_label.wordWrap()
          and rp.status_label.parentWidget().objectName() != "flowRow")

    # ----- 4 -----
    before = rp.voice_band_box.isChecked()
    rp.voice_band_box.click()
    check("搬過去的勾選框照常能勾", rp.voice_band_box.isChecked() != before)
    rp.voice_band_box.click()

    # ----- 5 -----
    tabs = qt_app.MainWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    def controls(panel):
        return sorted(type(w).__name__ + ":" + w.text() for w in panel.findChildren(QAbstractButton) if w.text())

    check("按鈕、勾選、選項一個都沒少（跟四頁籤的同一個面板比）", controls(rp) == controls(tabs.review_panel),
          str(set(controls(tabs.review_panel)) ^ set(controls(rp))))
    check("四頁籤：沒有換成流式排版", not tabs.review_panel.findChildren(QWidget, "flowRow")
          and not any(isinstance(w.layout(), fl.FlowLayout) for w in tabs.review_panel.findChildren(QWidget)))

    for w in (win, tabs):
        w.player_panel.shutdown()
        w.close()
    wait(50)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("智慧剪輯頁的寬度（E-9e）測試全數通過。")
