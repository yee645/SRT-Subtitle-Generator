# -*- coding: utf-8 -*-
"""
剪輯器版面 E-8b：屬性面板的數字框連續調整只記一筆復原（核心在 test_history_merge.py）。

1. 音量（一格 5%，從預設的音量開始）：按住上鍵、一個字一個字打（1→15→150）都只記一筆；復原一次回到原本的音量，
   重做一次到最後的。
2. 按 Enter（或離開數字框）之後再改：另一筆。改別段素材：另一筆。
3. 字幕的開始、結束：按上下鍵連續改只記一筆；按 Enter 之後再改、開始改完換結束：另一筆。
4. 其他修改（勾循環、拖素材）照舊一次一筆，夾在中間的會把連續調整切開。
5. 四頁籤（同一個播放器面板）的音量也一樣。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過連續調整的復原（核心在 test_history_merge.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

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

    def wait_until(cond, timeout_ms=20000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(50)
            waited += 50
        return cond()

    def run(*args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)

    main = os.path.join(tmp, "main.mp4")
    song = os.path.join(tmp, "song.m4a")
    run("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-f", "lavfi", "-i", "sine=frequency=440",
        "-t", "10", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", main)
    run("-f", "lavfi", "-i", "sine=frequency=220", "-t", "3", "-c:a", "aac", song)

    def setup(win):
        win.resize(1440, 900)
        win.show()
        wait(80)
        p = win.player_panel
        p._ask_discard = lambda *a, **k: "discard"
        p._ask_project_discard = lambda *a, **k: "discard"
        p.open_video(main)
        wait_until(lambda: p.media_duration() > 0 and p.timeline.duration > 0)
        return p

    def volumes(p):
        return [m["volume"] for m in p.tracks["music"]]

    def undo_count(p):
        n = 0
        while p.history.can_undo():
            p.undo()
            n += 1
        return n

    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    ed.apply_initial_theme(app, "dark")
    win = ed.EditorWindow(cfg)
    p = setup(win)
    t = p.timeline
    spin = p.volume_spin

    p.player.setPosition(0)
    check("（準備）放兩段音樂", p.add_track("music", song) and p.add_track("music", song) and len(p.tracks["music"]) == 2)
    p.history.clear()
    t.select_track_item("music", 0, seek=False)
    wait(30)
    base = volumes(p)[0]

    def v(steps):
        return round(base + 0.05 * steps, 2)

    check("（準備）選第一段：屬性面板有音量（預設的音量）", spin.isVisible() and spin.value() == round(base * 100)
          and 0 < base < 1.5, str(spin.value()))

    # ----- 1 -----
    spin.setFocus()
    wait(20)
    for _ in range(4):
        QTest.keyClick(spin, Qt.Key_Up)
    wait(20)
    check("按上鍵四次：加 20%", volumes(p)[0] == v(4), str(volumes(p)))
    check("只記一筆", len(p.history._done) == 1)
    p.undo()
    check("復原一次：回到原本的音量（數字框也是）", volumes(p)[0] == base and not p.history.can_undo()
          and spin.value() == round(base * 100),
          f"{volumes(p)} {spin.value()}")
    p.redo()
    check("重做一次：到加 20% 那時", volumes(p)[0] == v(4) and not p.history.can_redo())

    p.history.clear()
    spin.setFocus()
    spin.lineEdit().selectAll()
    QTest.keyClicks(spin.lineEdit(), "150")
    wait(20)
    check("一個字一個字打 150：音量 150%", volumes(p)[0] == 1.5, str(volumes(p)))
    check("打字的過程（1→15→150）只記一筆", len(p.history._done) == 1, str(len(p.history._done)))
    p.undo()
    check("復原一次：回到打字前", volumes(p)[0] == v(4), str(volumes(p)))

    # ----- 2 -----
    p.history.clear()
    spin.setFocus()
    QTest.keyClick(spin, Qt.Key_Up)
    QTest.keyClick(spin, Qt.Key_Up)
    QTest.keyClick(spin, Qt.Key_Return)
    QTest.keyClick(spin, Qt.Key_Up)
    wait(20)
    check("按 Enter 之後再改：兩筆", len(p.history._done) == 2 and volumes(p)[0] == v(7), str(volumes(p)))
    p.undo()
    check("復原一次：回到 Enter 那時", volumes(p)[0] == v(6), str(volumes(p)))
    p.history.clear()
    spin.setFocus()
    QTest.keyClick(spin, Qt.Key_Down)
    t.setFocus()  # 離開數字框
    wait(20)
    spin.setFocus()
    QTest.keyClick(spin, Qt.Key_Down)
    wait(20)
    check("離開數字框之後再改：兩筆", len(p.history._done) == 2 and volumes(p)[0] == v(4), str(volumes(p)))

    p.history.clear()
    spin.setFocus()
    QTest.keyClick(spin, Qt.Key_Up)
    t.select_track_item("music", 1, seek=False)
    wait(20)
    spin.setFocus()
    QTest.keyClick(spin, Qt.Key_Up)
    wait(20)
    check("改別段素材：另一筆", len(p.history._done) == 2 and volumes(p) == [v(5), v(1)], str(volumes(p)))
    p.undo()
    check("復原只退第二段", volumes(p) == [v(5), base], str(volumes(p)))
    t.select_track_item("music", 0, seek=False)
    wait(20)

    # ----- 4 -----
    p.history.clear()
    spin.setFocus()
    QTest.keyClick(spin, Qt.Key_Up)
    p.loop_box.setChecked(True)
    spin.setFocus()
    QTest.keyClick(spin, Qt.Key_Up)
    wait(20)
    check("中間勾了循環：三筆（循環照舊一次一筆，把連續調整切開）", len(p.history._done) == 3, str(len(p.history._done)))
    p.undo()
    p.undo()
    check("復原兩次：退掉後來的音量與循環", volumes(p)[0] == v(6) and not p.tracks["music"][0].get("loop"),
          str(p.tracks["music"][0]))
    p.set_track_props(volume=0.5)
    p.set_track_props(volume=0.6)
    check("程式直接改（不是數字框）：照舊一次一筆", len(p.history._done) == 3, str(len(p.history._done)))

    # ----- 3 -----
    p.set_cues([{"start": 1.0, "end": 2.0, "text": "第一句"}, {"start": 5.0, "end": 6.0, "text": "第二句"}])
    p.history.clear()
    t.select_cue(0, seek=False)
    wait(30)
    start_spin, end_spin = win.cue_start_spin, win.cue_end_spin
    check("（準備）選第一句：屬性面板是字幕頁", win.inspector_stack.currentWidget() is win.inspector_pages["cue"]
          and start_spin.value() == 1.0)
    start_spin.setFocus()
    for _ in range(3):
        QTest.keyClick(start_spin, Qt.Key_Up)
    wait(20)
    check("開始按上鍵三次：1.3 秒、只記一筆", abs(p.cues[0]["start"] - 1.3) < 1e-6 and len(p.history._done) == 1,
          f"{p.cues[0]} {len(p.history._done)}")
    end_spin.setFocus()
    QTest.keyClick(end_spin, Qt.Key_Up)
    QTest.keyClick(end_spin, Qt.Key_Up)
    wait(20)
    check("換結束按上鍵兩次：另一筆（共兩筆）", abs(p.cues[0]["end"] - 2.2) < 1e-6 and len(p.history._done) == 2,
          f"{p.cues[0]} {len(p.history._done)}")
    p.undo()
    check("復原一次：結束回到 2.0、開始還是 1.3", abs(p.cues[0]["end"] - 2.0) < 1e-6 and abs(p.cues[0]["start"] - 1.3) < 1e-6,
          str(p.cues[0]))
    p.undo()
    check("再復原一次：開始回到 1.0", abs(p.cues[0]["start"] - 1.0) < 1e-6 and not p.history.can_undo(), str(p.cues[0]))
    t.select_cue(0, seek=False)
    wait(20)
    start_spin.setFocus()
    QTest.keyClick(start_spin, Qt.Key_Up)
    QTest.keyClick(start_spin, Qt.Key_Return)
    QTest.keyClick(start_spin, Qt.Key_Up)
    wait(20)
    check("開始按 Enter 之後再改：兩筆", abs(p.cues[0]["start"] - 1.2) < 1e-6 and len(p.history._done) == 2,
          f"{p.cues[0]} {len(p.history._done)}")
    p.undo()
    p.undo()
    t.select_cue(0, seek=False)
    wait(20)
    start_spin.setFocus()
    QTest.keyClick(start_spin, Qt.Key_Up)
    QTest.keyClick(start_spin, Qt.Key_Down)
    wait(20)
    check("加了又減回原樣：沒得復原", abs(p.cues[0]["start"] - 1.0) < 1e-6 and not p.history.can_undo(),
          str(len(p.history._done)))
    p.history.clear()
    start_spin.setValue(1.1)  # 不換焦點、直接連改開始與結束：鍵不一樣，照樣是兩筆
    end_spin.setValue(2.1)
    wait(20)
    check("開始、結束連著改（沒有離開數字框）：兩筆", len(p.history._done) == 2, str(len(p.history._done)))
    p.undo()
    check("復原一次只退結束", abs(p.cues[0]["end"] - 2.0) < 1e-6 and abs(p.cues[0]["start"] - 1.1) < 1e-6, str(p.cues[0]))
    p.undo()

    # ----- 5 -----
    tabs = qt_app.MainWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    tp = setup(tabs)
    tp.player.setPosition(0)
    tp.add_track("music", song)
    tp.history.clear()
    tp.timeline.select_track_item("music", 0, seek=False)
    tabs.tabs.setCurrentIndex(0)
    wait(30)
    tspin = tp.volume_spin
    tspin.setFocus()
    for _ in range(3):
        QTest.keyClick(tspin, Qt.Key_Down)
    wait(20)
    check("四頁籤：按下鍵三次（減 15%）、只記一筆", volumes(tp)[0] == round(base - 0.15, 2) and len(tp.history._done) == 1,
          f"{volumes(tp)} {len(tp.history._done)}")
    tp.undo()
    check("四頁籤：復原一次回到原本的音量", volumes(tp)[0] == base)

    for w in (win, tabs):
        w.player_panel.shutdown()
        w.close()
    wait(50)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("連續調整的復原（E-8b）介面測試全數通過。")
