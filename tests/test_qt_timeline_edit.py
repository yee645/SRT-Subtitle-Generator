# -*- coding: utf-8 -*-
"""
3.0 第 4 項第二階段：時間軸上選取字幕塊、拖曳左右邊改時間。

規則本身（不重疊、最短長度、吸附…）在 test_cueedit.py；這裡驗的是**真的用
滑鼠**（QTest 送按下／移動／放開）操作時間軸：

1. 點字幕塊 → 選取、跳到那句開頭、畫面上那塊變成選取色（抓像素）。
2. 點字幕列空白處 → 取消選取、照常跳轉；點其他列不影響選取。
3. 滑鼠移到邊上 → 游標變左右箭頭；移到中間 → 恢復。
4. 拖左邊／右邊 → 方塊跟著變、放開才送 cueTimesChanged；拖進鄰句會停住；
   靠近播放頭會吸附；Esc 放棄；沒動就不送。
5. 接進播放器：拖完之後畫面上的字幕照新時間出現／消失，資訊列標示「尚未存檔」，
   原本傳進去的清單沒被改到。
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
    print("SKIP 這個環境沒有 PySide6：略過時間軸拖曳（規則本身在 test_cueedit.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer  # noqa: E402
    from PySide6.QtGui import QColor  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402

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

    CUE_Y = tl.ROW_Y["cues"] + tl.CUE_H // 2  # 字幕列中間（視窗座標，沒有縱向捲動）

    view = tl.TimelineView()
    view.resize(1000, view.height())
    view.show()
    wait(50)
    view.set_duration(20)
    view.set_zoom(40, 0, 0)  # 每秒 40px，捲動位置 0 → 視窗 x = 秒 × 40
    source = [{"start": 1, "end": 4, "text": "第一句"},
              {"start": 5, "end": 8, "text": "第二句"},
              {"start": 10, "end": 12, "text": "第三句"}]
    view.set_cues(source)

    seeks, selects, changes = [], [], []
    view.seekRequested.connect(seeks.append)
    view.cueSelected.connect(selects.append)
    view.cueTimesChanged.connect(lambda i, s, e: changes.append((i, s, e)))

    def x_of(seconds):
        return int(round(seconds * view.px_per_sec)) - view.horizontalScrollBar().value()

    def pixel(x, y):
        return QColor(view.viewport().grab().toImage().pixel(x, y))

    def close(c1, c2, tol=12):
        return all(abs(a - b) <= tol for a, b in
                   ((c1.red(), c2.red()), (c1.green(), c2.green()), (c1.blue(), c2.blue())))

    # ----- 選取 -----
    check("一開始沒有選取", view.selected == -1)
    wait(50)
    before = pixel(x_of(6.5), CUE_Y)
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(x_of(6.5), CUE_Y))
    wait(50)
    check("點第二句中間 → 選取第二句", view.selected == 1 and selects[-1:] == [1], f"{view.selected} {selects}")
    check("點字幕塊 → 跳到那句開頭（5000 毫秒），不是點的位置",
          seeks[-1:] == [5000] and abs(view.playhead.line().x1() - 200) < 1.5, str(seeks))
    after = pixel(x_of(6.5), CUE_Y)
    check("選取的那塊畫成選取色（抓像素）", close(after, view.colors["cue_sel"]) and not close(before, after),
          f"{before.name()} → {after.name()}（選取色 {view.colors['cue_sel'].name()}）")
    check("其他塊還是一般色", close(pixel(x_of(2.5), CUE_Y), view.colors["cue"]),
          pixel(x_of(2.5), CUE_Y).name())

    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(x_of(15), 60))
    check("點縮圖列 → 照常跳轉、選取不變", view.selected == 1 and abs(seeks[-1] - 15000) <= 30,
          f"{view.selected} {seeks[-1:]}")
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(x_of(9), CUE_Y))
    check("點字幕列空白處（9 秒）→ 取消選取、跳到 9 秒",
          view.selected == -1 and selects[-1] == -1 and abs(seeks[-1] - 9000) <= 30,
          f"{view.selected} {selects} {seeks[-1:]}")

    # ----- 游標 -----
    QTest.mouseMove(view.viewport(), QPoint(x_of(8) - 2, CUE_Y))
    wait(20)
    check("滑鼠移到第二句右邊 → 游標變左右箭頭",
          view.viewport().cursor().shape() == Qt.SizeHorCursor, str(view.viewport().cursor().shape()))
    QTest.mouseMove(view.viewport(), QPoint(x_of(6.5), CUE_Y))
    wait(20)
    check("移到中間 → 游標恢復", view.viewport().cursor().shape() != Qt.SizeHorCursor,
          str(view.viewport().cursor().shape()))
    QTest.mouseMove(view.viewport(), QPoint(x_of(8) - 2, 60))
    wait(20)
    check("同一個 x 但在縮圖列 → 不是左右箭頭（只有字幕列能抓邊）",
          view.viewport().cursor().shape() != Qt.SizeHorCursor)

    def drag(from_x, to_x, y=CUE_Y, steps=4, cancel=False):
        vp = view.viewport()
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(from_x, y))
        for k in range(1, steps + 1):
            QTest.mouseMove(vp, QPoint(from_x + (to_x - from_x) * k // steps, y))
        if cancel:
            QTest.keyClick(view, Qt.Key_Escape)
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(to_x, y))
        wait(20)

    # ----- 拖右邊 -----
    view.set_position(0, follow=False)  # 播放頭放遠一點，免得吸附
    changes.clear()
    seeks.clear()
    vp = view.viewport()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(x_of(8) - 1, CUE_Y))
    QTest.mouseMove(vp, QPoint(x_of(9) - 1, CUE_Y))  # 抓在邊左邊 1px，移動量＝1 秒
    mid_rect = view.cue_rects()[1]
    check("拖曳中方塊就跟著變（右邊到 9 秒 → 寬 160）", abs(mid_rect.width() - 160) < 1.5, str(mid_rect))
    check("拖曳中還沒送出 cueTimesChanged", changes == [])
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(x_of(9) - 1, CUE_Y))
    check("放開 → 送出 (第 1 句, 5, 9)", changes == [(1, 5.0, 9.0)], str(changes))
    check("拖邊不會跳轉播放器", seeks == [], str(seeks))
    check("抓邊時自動選取那句", view.selected == 1)
    check("放開後方塊停在新時間", abs(view.cue_rects()[1].right() - 360) < 1.5, str(view.cue_rects()[1]))
    check("原本傳進來的清單沒被改到", source[1]["end"] == 8)

    changes.clear()
    drag(x_of(9) - 1, x_of(11.5))
    check("右邊拖進第三句 → 停在第三句開頭（10 秒）", changes == [(1, 5.0, 10.0)], str(changes))

    # ----- 拖左邊 -----
    changes.clear()
    drag(x_of(5) + 1, x_of(3))
    check("左邊拖進第一句 → 停在第一句結尾（4 秒）", changes == [(1, 4.0, 10.0)], str(changes))
    changes.clear()
    drag(x_of(4) + 1, x_of(15))
    check("左邊拖過右邊 → 停在結束前 0.1 秒", changes == [(1, 9.9, 10.0)], str(changes))

    # ----- 吸附播放頭 -----
    view.set_cues(source)  # 回到原本的時間
    view.set_position(6200, follow=False)
    changes.clear()
    drag(x_of(5) + 1, x_of(6.2) + 1 - 5)  # 邊停在離播放頭 5px（< SNAP_PX 8px）
    check("拖到離播放頭 5px → 貼上播放頭（6.2 秒）", changes == [(1, 6.2, 8.0)], str(changes))
    view.set_cues(source)
    changes.clear()
    drag(x_of(5) + 1, x_of(6.2) + 1 - 15)  # 差 15px → 不吸
    check("差 15px → 不吸附（邊停在 6.2 − 15/40 = 5.825 秒）", changes == [(1, 5.825, 8.0)], str(changes))
    view.set_cues(source)
    view.set_position(0, follow=False)
    changes.clear()
    drag(x_of(8) - 3, x_of(8) - 3 + 20)
    check("抓在邊旁邊 3px 往右移 20px → 邊移動 0.5 秒（不會一按就跳到滑鼠上）",
          changes == [(1, 5.0, 8.5)], str(changes))

    # ----- 放棄與沒動 -----
    view.set_cues(source)
    view.set_position(0, follow=False)
    changes.clear()
    drag(x_of(8) - 1, x_of(9.5), cancel=True)
    check("拖曳中按 Esc → 不送出、方塊回原位",
          changes == [] and abs(view.cue_rects()[1].right() - 320) < 1.5, f"{changes} {view.cue_rects()[1]}")
    drag(x_of(8) - 1, x_of(8) - 1)
    check("按住邊沒移動就放開 → 不送出", changes == [], str(changes))

    # ----- 拖第一句左邊到片頭以前 -----
    drag(x_of(1) + 1, 0, steps=2)
    view.horizontalScrollBar().setValue(0)
    check("第一句左邊往前拖到底 → 停在 0 秒以後（最多 0）",
          changes and changes[-1][0] == 0 and changes[-1][1] == 0.0, str(changes))

    # ----- set_cues：換一份字幕清掉選取；同一份改完留著 -----
    view.select_cue(2, seek=False)
    view.set_cues(source, keep_selection=True)
    check("keep_selection → 選取留著", view.selected == 2)
    view.set_cues(source)
    check("換一份字幕 → 選取清掉", view.selected == -1)
    view.select_cue(7, seek=False)
    check("選不存在的句子 → 當成取消", view.selected == -1)

    # ----- 重疊的字幕：抓邊優先於另一句的身體 -----
    view.set_cues([{"start": 4, "end": 6, "text": "甲"}, {"start": 5, "end": 9, "text": "乙（蓋住甲的結尾）"}])
    hit = view.cue_hit(QPoint(x_of(6) - 2, CUE_Y))
    check("「甲」的結尾被「乙」蓋住 → 滑鼠在那個邊上抓到的是「甲」的右邊，不是「乙」的身體",
          hit == (0, "end"), str(hit))
    hit = view.cue_hit(QPoint(x_of(7), CUE_Y))
    check("只在「乙」上 → 乙的身體", hit == (1, "body"), str(hit))
    hit = view.cue_hit(QPoint(x_of(5.5), CUE_Y))
    check("兩句的身體重疊處 → 開始得晚的「乙」（與畫面上顯示的那句一致）", hit == (1, "body"), str(hit))
    view.set_cues(source)

    # ----- 拉近後照樣抓得到邊（每秒 200px） -----
    view.set_zoom(200, 4, 0)  # 視窗左邊 = 4 秒
    changes.clear()
    drag(x_of(8) - 1, x_of(8.5) - 1)
    check("拉近到每秒 200px、捲過之後拖右邊 → 8.5 秒", changes == [(1, 5.0, 8.5)], str(changes))
    view.close()

    # ----- 接進播放器 -----
    video = os.path.join(tmp, "edit.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=gray:s=320x180:r=30:d=12",
                    "-f", "lavfi", "-i", "sine=d=12", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", video], check=True)
    win = qt_app.MainWindow({"subtitle_style": {}})
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 800)
    win.show()
    panel = win.player_panel
    panel.open_video(video)
    wait_until(lambda: abs(panel.timeline.duration - 12) < 0.3)
    given = [{"start": 1, "end": 3, "text": "甲"}, {"start": 6, "end": 8, "text": "乙"}]
    panel.set_cues(given, "edit.srt")
    tv = panel.timeline
    tv.set_zoom(80, 0, 0)

    def px(seconds):
        return int(round(seconds * tv.px_per_sec)) - tv.horizontalScrollBar().value()

    panel.player.setPosition(4000)
    wait_until(lambda: panel.player.position() >= 3900, 5000)
    check("改之前：4 秒處沒有字幕", panel.current_subtitle_text() == "", repr(panel.current_subtitle_text()))
    tvp = tv.viewport()
    QTest.mousePress(tvp, Qt.LeftButton, Qt.NoModifier, QPoint(px(3) - 1, CUE_Y))
    QTest.mouseMove(tvp, QPoint(px(4.6) - 1, CUE_Y))
    QTest.mouseRelease(tvp, Qt.LeftButton, Qt.NoModifier, QPoint(px(4.6) - 1, CUE_Y))
    wait(50)
    check("把「甲」的右邊拖到 4.6 秒 → 播放器的字幕清單跟著改",
          panel.cues[0]["end"] == 4.6 and panel.cues[0]["start"] == 1, str(panel.cues[0]))
    check("畫面上 4 秒處立刻出現「甲」（不用重新播放）", panel.current_subtitle_text() == "甲",
          repr(panel.current_subtitle_text()))
    check("資訊列標示改過、尚未存檔", "改過 1 處" in panel.info_label.text()
          and "尚未存檔" in panel.info_label.text(), panel.info_label.text())
    check("呼叫端傳進來的清單沒被改到", given[0]["end"] == 3)
    QTest.mouseClick(tvp, Qt.LeftButton, Qt.NoModifier, QPoint(px(7), CUE_Y))
    check("點「乙」→ 播放器跳到 6 秒",
          wait_until(lambda: abs(panel.player.position() - 6000) < 300, 5000), str(panel.player.position()))
    check("跳過去之後畫面上是「乙」", wait_until(lambda: panel.current_subtitle_text() == "乙", 3000),
          repr(panel.current_subtitle_text()))
    panel.set_cues(given, "edit.srt")
    check("重新載入字幕 → 改過的次數歸零", "改過" not in panel.info_label.text()
          and panel.cues[0]["end"] == 3, panel.info_label.text())

    win.close()
    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 時間軸選取與拖曳測試全數通過。")
