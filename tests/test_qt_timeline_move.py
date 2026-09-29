# -*- coding: utf-8 -*-
"""
3.0 第 4 項第四階段：時間軸上整句拖曳（前後移動、長度不變）與 ←／→ 微調。

規則本身（界線、吸附）在 test_cueedit.py；這裡用 QTest 真的按下／移動／放開與
真的按鍵：

1. 按住字幕塊身體、動不到 4px 就放開 → 點選（跳到開頭），時間不變。
2. 拖超過 4px → 整句移動；拖曳中方塊跟著動、不跳轉、放開才送出；移進鄰句停住；
   靠近播放頭吸附；Esc 放棄；游標在身體上是張開的手、拖曳中是握拳。
3. 選取後 ←／→ 移動 0.1 秒、Shift 1 秒；碰到鄰句停住；沒選取時方向鍵不改時間；
   Ctrl＋方向鍵不算微調。
4. 接進播放器：整句移動與微調都能 Ctrl+Z 復原、存檔存的是移動後的時間。
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    print("SKIP 這個環境沒有 PySide6：略過整句拖曳與微調（規則本身在 test_cueedit.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle.importer import load_subtitle_file  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = tmp

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

    CUE_Y = tl.ROW_Y["cues"] + tl.CUE_H // 2

    view = tl.TimelineView()
    view.resize(1000, view.height())
    view.show()
    wait(50)
    view.set_duration(20)
    view.set_zoom(40, 0, 0)  # 每秒 40px
    source = [{"start": 1, "end": 4, "text": "第一句"},
              {"start": 5, "end": 8, "text": "第二句"},
              {"start": 10, "end": 12, "text": "第三句"}]
    view.set_cues(source)
    vp = view.viewport()
    seeks, changes = [], []
    view.seekRequested.connect(seeks.append)
    view.cueTimesChanged.connect(lambda i, s, e: changes.append((i, s, e)))

    def x_of(seconds):
        return int(round(seconds * view.px_per_sec)) - view.horizontalScrollBar().value()

    def reset(position_ms=0):
        view.set_cues(source)
        view.set_position(position_ms, follow=False)
        seeks.clear()
        changes.clear()

    def drag(from_x, to_x, steps=4, cancel=False):
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(from_x, CUE_Y))
        for k in range(1, steps + 1):
            QTest.mouseMove(vp, QPoint(from_x + (to_x - from_x) * k // steps, CUE_Y))
        if cancel:
            QTest.keyClick(view, Qt.Key_Escape)
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(to_x, CUE_Y))
        wait(20)

    # ----- 點選 vs 拖曳 -----
    reset()
    drag(x_of(6.5), x_of(6.5) + 3)
    check("按住身體動 3px 就放開 → 算點選：時間不變、選取、放開時跳到那句開頭",
          changes == [] and view.selected == 1 and seeks == [5000], f"{changes} {view.selected} {seeks}")

    reset()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(x_of(6.5), CUE_Y))
    QTest.mouseMove(vp, QPoint(x_of(6.5) + 20, CUE_Y))
    QTest.mouseMove(vp, QPoint(x_of(7.5), CUE_Y))
    rect = view.cue_rects()[1]
    check("拖曳中方塊整塊跟著動（5～8 → 6～9，寬度不變 120）",
          abs(rect.left() - 240) < 1.5 and abs(rect.width() - 120) < 1.5, str(rect))
    check("拖曳中游標是握拳", vp.cursor().shape() == Qt.ClosedHandCursor, str(vp.cursor().shape()))
    check("拖曳中不送出、也不跳轉", changes == [] and seeks == [], f"{changes} {seeks}")
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(x_of(7.5), CUE_Y))
    check("放開 → 送出 (第 1 句, 6, 9)", changes == [(1, 6.0, 9.0)], str(changes))
    check("整句拖曳不會跳轉播放器", seeks == [], str(seeks))
    check("放開後游標回到張開的手", vp.cursor().shape() == Qt.OpenHandCursor, str(vp.cursor().shape()))

    reset()
    drag(x_of(6.5), x_of(9.5))
    check("往右拖進第三句 → 停在 7～10（結束貼著第三句開頭）", changes == [(1, 7.0, 10.0)], str(changes))
    reset()
    drag(x_of(6.5), x_of(3))
    check("往左拖進第一句 → 停在 4～7", changes == [(1, 4.0, 7.0)], str(changes))

    reset(position_ms=6600)  # 播放頭 6.6 秒
    drag(x_of(6.5), x_of(6.5) + 20 - 4)  # 開始 5 → 5.4（差播放頭 1.2 秒），結束 8 → 8.4
    check("吸附前的對照：沒靠近吸附點就照滑鼠（5.4～8.4）", changes == [(1, 5.4, 8.4)], str(changes))
    reset(position_ms=6600)
    drag(x_of(6.5), x_of(6.5) + 59)  # 開始 5 → 6.475，離播放頭 6.6 差 5px（< SNAP_PX 8px）
    check("開始拖到離播放頭 5px → 貼上播放頭（6.6～9.6）", changes == [(1, 6.6, 9.6)], str(changes))

    reset()
    drag(x_of(6.5), x_of(7.5), cancel=True)
    check("整句拖曳中按 Esc → 不送出、方塊回原位", changes == [] and abs(view.cue_rects()[1].left() - 200) < 1.5,
          f"{changes} {view.cue_rects()[1]}")

    # ----- 游標 -----
    QTest.mouseMove(vp, QPoint(x_of(6.5), CUE_Y))
    wait(20)
    check("滑鼠在字幕塊身體上 → 張開的手", vp.cursor().shape() == Qt.OpenHandCursor, str(vp.cursor().shape()))
    QTest.mouseMove(vp, QPoint(x_of(9), CUE_Y))
    wait(20)
    check("字幕列空白處 → 一般游標", vp.cursor().shape() not in (Qt.OpenHandCursor, Qt.SizeHorCursor),
          str(vp.cursor().shape()))

    # ----- 鍵盤微調 -----
    reset()
    view.select_cue(1, seek=False)
    view.setFocus()
    QTest.keyClick(view, Qt.Key_Right)
    check("→ → 整句往後 0.1 秒", changes == [(1, 5.1, 8.1)], str(changes))
    QTest.keyClick(view, Qt.Key_Right, Qt.ShiftModifier)
    check("Shift+→ → 再往後 1 秒", changes[-1] == (1, 6.1, 9.1), str(changes))
    QTest.keyClick(view, Qt.Key_Left)
    check("← → 往前 0.1 秒", changes[-1] == (1, 6.0, 9.0), str(changes))
    for _ in range(3):
        QTest.keyClick(view, Qt.Key_Right, Qt.ShiftModifier)
    check("一直往後 → 停在第三句前面（7～10），停住之後不再送出",
          changes[-1] == (1, 7.0, 10.0) and changes.count((1, 7.0, 10.0)) == 1, str(changes))
    check("微調不跳轉播放器", seeks == [], str(seeks))
    n = len(changes)
    QTest.keyClick(view, Qt.Key_Right, Qt.ControlModifier)
    check("Ctrl+→ 不算微調", len(changes) == n, str(changes[n:]))
    view.select_cue(-1, seek=False)
    before_scroll = view.horizontalScrollBar().value()
    QTest.keyClick(view, Qt.Key_Right)
    check("沒選取時 → 不改任何時間", len(changes) == n, str(changes[n:]))
    view.set_zoom(200, 0, 0)
    before_scroll = view.horizontalScrollBar().value()
    QTest.keyClick(view, Qt.Key_Right)
    check("沒選取時 → 照 Qt 原本的行為捲動（拉近之後有得捲）",
          view.horizontalScrollBar().value() > before_scroll, f"{before_scroll} → {view.horizontalScrollBar().value()}")
    view.set_zoom(40, 0, 0)
    view.close()

    # ----- 接進播放器：復原與存檔 -----
    video = os.path.join(tmp, "m.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=gray:s=320x180:r=30:d=12",
                    "-f", "lavfi", "-i", "sine=d=12", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", video], check=True)
    srt = os.path.join(tmp, "m.srt")
    with open(srt, "w", encoding="utf-8") as fp:
        fp.write("1\n00:00:01,000 --> 00:00:03,000\n甲\n\n2\n00:00:06,000 --> 00:00:08,000\n乙\n")
    win = qt_app.MainWindow({"subtitle_style": {}})
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 800)
    win.show()
    panel = win.player_panel
    panel.open_video(video)
    wait_until(lambda: abs(panel.timeline.duration - 12) < 0.3)
    panel.load_subtitles(srt)
    tv = panel.timeline
    tv.set_zoom(80, 0, 0)
    tvp = tv.viewport()

    def px(seconds):
        return int(round(seconds * tv.px_per_sec)) - tv.horizontalScrollBar().value()

    def times():
        return [(c["start"], c["end"]) for c in panel.cues]

    panel.player.setPosition(10000)
    wait_until(lambda: panel.player.position() >= 9900, 5000)
    QTest.mousePress(tvp, Qt.LeftButton, Qt.NoModifier, QPoint(px(2), CUE_Y))
    QTest.mouseMove(tvp, QPoint(px(2) + 10, CUE_Y))
    QTest.mouseMove(tvp, QPoint(px(3.5), CUE_Y))
    QTest.mouseRelease(tvp, Qt.LeftButton, Qt.NoModifier, QPoint(px(3.5), CUE_Y))
    wait(30)
    check("播放器：把「甲」整句拖到 2.5～4.5", times() == [(2.5, 4.5), (6.0, 8.0)], str(times()))
    QTest.keyClick(tv, Qt.Key_Right, Qt.ShiftModifier)
    wait(30)
    check("播放器：Shift+→ 再往後 1 秒（3.5～5.5）", times() == [(3.5, 5.5), (6.0, 8.0)], str(times()))
    check("資訊列：改過 1 處（同一句改兩次算一處）", "改過 1 處" in panel.info_label.text(), panel.info_label.text())
    QTest.keyClick(tv, Qt.Key_Z, Qt.ControlModifier)
    wait(30)
    check("Ctrl+Z → 微調先退（回到 2.5～4.5）", times() == [(2.5, 4.5), (6.0, 8.0)], str(times()))
    QTest.keyClick(tv, Qt.Key_Z, Qt.ControlModifier)
    wait(30)
    check("再 Ctrl+Z → 整句拖曳也退（回到 1～3）", times() == [(1.0, 3.0), (6.0, 8.0)], str(times()))
    QTest.keyClick(tv, Qt.Key_Y, Qt.ControlModifier)
    QTest.keyClick(tv, Qt.Key_S, Qt.ControlModifier)
    wait(30)
    back = [(c["start"], c["end"]) for c in load_subtitle_file(srt)["cues"]]
    check("重做後存檔 → 檔案裡是移動後的時間", back == [(2.5, 4.5), (6.0, 8.0)], str(back))

    win.close()
    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 時間軸整句拖曳與微調測試全數通過。")
