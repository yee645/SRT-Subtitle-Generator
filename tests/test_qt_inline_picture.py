# -*- coding: utf-8 -*-
"""
剪輯器版面 E-8d：畫面調整攤進屬性面板（gui_qt/picture_panel.py 的 PictureControls；四頁籤照舊開小視窗）。

1. 專案頁（什麼都沒選）直接有主片的亮度、對比、飽和度、裁切、旋轉、翻轉；原本的〔畫面調整…〕藏起來；
   沒開影片不能調，開了就能調。
2. 調了馬上套到主片（播放器的調整跟著變）；別處改了（小視窗、開專案）屬性面板跟著填。
3. 選疊加：素材頁直接有那一段的畫面調整（〔調畫面…〕藏起來）；改的是選的那一段；換一段就換成那一段的值。
   選音樂看不到。
4. 疊加的調整可以復原：拖一次滑桿（放開才算一筆）只記一筆；旋轉、翻轉一次一筆；裁切按住上下鍵一串一筆，
   Enter 之後另一筆。復原之後屬性面板照著填回去。
5. 窄面板放得下：視窗最小（1100×700）時屬性面板沒有橫捲軸，數字、裁切格都看得到。
6. 四頁籤照舊：〔畫面調整…〕看得到、開的是小視窗，小視窗的版面照舊（〔全部還原〕跟〔關閉〕同一排）。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過屬性面板的畫面調整")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import editor as ed  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from gui_qt.picture_panel import PictureControls, PictureDialog  # noqa: E402
    from subtitle import project as project_mod  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait_until(cond, timeout_ms=20000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(50)
            waited += 50
        return cond()

    def run(*args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)

    main = os.path.join(tmp, "main.mp4")
    still = os.path.join(tmp, "logo.png")
    still2 = os.path.join(tmp, "logo2.png")
    song = os.path.join(tmp, "song.m4a")
    run("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-f", "lavfi", "-i", "sine=frequency=440",
        "-t", "12", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", main)
    run("-f", "lavfi", "-i", "testsrc2=size=160x90", "-frames:v", "1", still)
    run("-f", "lavfi", "-i", "color=c=red:size=160x90", "-frames:v", "1", still2)
    run("-f", "lavfi", "-i", "sine=frequency=220", "-t", "3", "-c:a", "aac", song)

    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    ed.apply_initial_theme(app, "dark")
    win = ed.EditorWindow(cfg)
    win.resize(1440, 900)
    win.show()
    wait(100)
    p = win.player_panel
    p._ask_discard = lambda *a, **k: "discard"
    p._ask_project_discard = lambda *a, **k: "discard"
    p._show_track_error = lambda msg: None
    t = p.timeline
    mp, op = win.main_picture, win.overlay_picture

    def inside(widget, ancestor):
        w = widget
        while w is not None:
            if w is ancestor:
                return True
            w = w.parentWidget()
        return False

    def entries():
        return len(p.history._done)

    def overlay_adjust(i):
        return p.tracks["overlays"][i].get("adjust") or {}

    # ----- 1 -----
    check("專案頁有主片的畫面調整（窄版）", isinstance(mp, PictureControls) and inside(mp, win.inspector_pages["project"])
          and mp.isVisible())
    check("原本的〔畫面調整…〕藏起來", not p.picture_btn.isVisible())
    check("沒開影片：不能調", not mp.isEnabled())
    p.open_video(main)
    check("（準備）開好影片", wait_until(lambda: p.media_duration() > 0 and t.duration > 0))
    wait(50)
    check("開了影片：能調", mp.isEnabled())
    check("一開始：都沒調、〔全部還原〕不能按", mp.current() == {} and not mp.reset_btn.isEnabled())

    # ----- 2 -----
    mp.sliders["brightness"].setValue(20)
    wait(20)
    check("拉亮度：主片跟著變", p.main_adjust == {"brightness": 0.2} and mp.value_labels["brightness"].text() == "+20",
          str(p.main_adjust))
    check("〔全部還原〕能按了", mp.reset_btn.isEnabled())
    mp.rotate_combo.setCurrentIndex(mp.rotate_combo.findData(90))
    check("旋轉：主片跟著轉", p.main_adjust.get("rotate") == 90)
    dialog = p.show_picture_dialog()
    check("（別處改）小視窗也調得到主片", isinstance(dialog, PictureDialog) and dialog.target == "main")
    dialog.sliders["saturation"].setValue(150)
    wait(20)
    check("小視窗改了：屬性面板跟著填", mp.sliders["saturation"].value() == 150 and p.main_adjust["saturation"] == 1.5)
    dialog.close()
    mp.reset_btn.click()
    wait(20)
    check("〔全部還原〕：主片回到沒調", p.main_adjust == {} and mp.current() == {} and not mp.reset_btn.isEnabled())

    # ----- 3 -----
    p.player.setPosition(1000)
    wait_until(lambda: abs(p.player.position() - 1000) < 5, 3000)
    check("（準備）放兩段疊加、一段音樂", p.add_track("overlays", still) and p.add_track("overlays", still2, at=6.0)
          and p.add_track("music", song))
    t.select_track_item("overlays", 0, seek=False)
    wait(30)
    check("選疊加：素材頁有那一段的畫面調整、〔調畫面…〕藏起來",
          win.inspector_stack.currentWidget() is win.inspector_pages["track"] and op.isVisible()
          and inside(op, win.inspector_pages["track"]) and not p.overlay_picture_btn.isVisible()
          and op.target == ("overlays", 0))
    p.history.clear()
    op.sliders["contrast"].setValue(140)
    wait(20)
    check("改的是選的那一段", overlay_adjust(0) == {"contrast": 1.4} and overlay_adjust(1) == {}, str(p.tracks["overlays"]))
    t.select_track_item("overlays", 1, seek=False)
    wait(30)
    check("換一段：換成那一段的值", op.target == ("overlays", 1) and op.current() == {})
    op.flip_h_box.setChecked(True)
    check("改第二段", overlay_adjust(1) == {"flip_h": True} and overlay_adjust(0) == {"contrast": 1.4})
    t.select_track_item("overlays", 0, seek=False)
    wait(30)
    check("換回第一段：照它的值填", op.sliders["contrast"].value() == 140 and not op.flip_h_box.isChecked())
    t.select_track_item("music", 0, seek=False)
    wait(30)
    check("選音樂：看不到畫面調整", not op.isVisible() and p.volume_spin.isVisible())

    # ----- 4 -----
    t.select_track_item("overlays", 0, seek=False)
    wait(30)
    p.history.clear()
    slider = op.sliders["brightness"]
    for value in (5, 10, 15, 20):
        slider.setValue(value)
    op.sliderReleased.emit()
    check("拖一次滑桿（放開才算）：只記一筆", entries() == 1 and overlay_adjust(0).get("brightness") == 0.2,
          f"{entries()} {overlay_adjust(0)}")
    slider.setValue(30)
    op.sliderReleased.emit()
    check("再拖一次：另一筆", entries() == 2)
    p.undo()
    check("復原一次：回到第一次拖完、滑桿跟著填", overlay_adjust(0).get("brightness") == 0.2 and slider.value() == 20,
          f"{overlay_adjust(0)} {slider.value()}")
    p.undo()
    check("再復原：回到拖之前", "brightness" not in overlay_adjust(0) and slider.value() == 0, str(overlay_adjust(0)))
    p.history.clear()
    op.rotate_combo.setCurrentIndex(op.rotate_combo.findData(180))
    op.rotate_combo.setCurrentIndex(op.rotate_combo.findData(270))
    op.flip_v_box.setChecked(True)
    check("旋轉兩次、翻轉一次：三筆", entries() == 3, str(entries()))
    p.history.clear()
    spin = op.crop_spins["left"]
    spin.setFocus()
    for _ in range(3):
        QTest.keyClick(spin, Qt.Key_Up)
    wait(20)
    check("裁切按上鍵三次：一筆", entries() == 1 and abs(overlay_adjust(0)["crop"][0] - 0.03) < 1e-9,
          f"{entries()} {overlay_adjust(0).get('crop')}")
    QTest.keyClick(spin, Qt.Key_Return)
    QTest.keyClick(spin, Qt.Key_Up)
    wait(20)
    check("Enter 之後再按：另一筆", entries() == 2)
    p.undo()
    p.undo()
    check("復原兩次：裁切回到 0、格子跟著填", "crop" not in overlay_adjust(0) and spin.value() == 0, str(overlay_adjust(0)))
    t.setFocus()

    # ----- 2（開專案） -----
    p.set_main_adjust({"contrast": 0.5})
    target = os.path.join(tmp, "調整.srtproj")
    p.save_project(target)
    p.set_main_adjust({})
    check("（準備）存好專案、主片改回沒調", mp.current() == {})
    check("開專案：屬性面板照專案的調整填", p.open_project(target) and mp.sliders["contrast"].value() == 50
          and p.main_adjust == {"contrast": 0.5}, str(p.main_adjust))

    # ----- 5 -----
    win.resize(1100, 700)
    for key in ("project", "track"):
        win.inspector_stack.setCurrentWidget(win.inspector_pages[key])
        wait(80)
        page = win.inspector_pages[key]
        check(f"最小視窗：{key} 頁沒有橫捲軸", not page.horizontalScrollBar().isVisible(),
              f"{page.viewport().width()} < {page.widget().minimumSizeHint().width()}")
    win.sync_inspector()
    for controls in (mp,):
        hidden = [k for k, lab in controls.value_labels.items()
                  if lab.mapTo(win, lab.rect().topRight()).x() > win.inspector_panel.mapTo(win, win.inspector_panel.rect().topRight()).x()]
        check("數字沒有超出屬性面板", not hidden, str(hidden))
        check("裁切格放得下「95%」", all(s.lineEdit().width() >= s.fontMetrics().horizontalAdvance("95%")
                                       for s in controls.crop_spins.values()),
              str([s.lineEdit().width() for s in controls.crop_spins.values()]))

    # ----- 6 -----
    tabs = qt_app.MainWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    tabs.show()
    tp = tabs.player_panel
    tp._ask_discard = lambda *a, **k: "discard"
    tp._ask_project_discard = lambda *a, **k: "discard"
    tp.open_video(main)
    wait_until(lambda: tp.media_duration() > 0)
    tabs.tabs.setCurrentIndex(1)  # 播放器在第二頁（逐句校對）
    wait(50)
    check("四頁籤：〔畫面調整…〕看得到", tp.picture_btn.isVisible() and tp.picture_btn.isEnabled())
    tp.picture_btn.click()
    wait(30)
    d = tp.picture_dialog
    check("四頁籤：開的是小視窗", d is not None and d.isVisible() and isinstance(d, PictureDialog))
    check("小視窗：〔全部還原〕跟〔關閉〕同一排、說明照舊攤開", d.reset_btn.parent() is d
          and abs(d.reset_btn.y() - d.close_btn.y()) < 3 and d.note_label.isVisible())
    d.sliders["brightness"].setValue(-30)
    check("小視窗照舊能調", tp.main_adjust == {"brightness": -0.3})
    d.close()

    for w in (win, tabs):
        w.player_panel.shutdown()
        w.close()
    wait(50)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("屬性面板的畫面調整（E-8d）測試全數通過。")
