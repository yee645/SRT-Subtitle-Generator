# -*- coding: utf-8 -*-
"""
3.0 第 5 項第二階段：時間軸的剪點列——點一下停用／啟用、拖左右邊調整範圍。

規則（不過鄰段、最短、片頭片尾、微調在重算後留不留）在 test_cutmarks.py；這裡用
QTest 真的按下／移動／放開：

1. 剪點列的方塊位置跟上面的半透明區塊對齊；沒有剪點時寫一行怎麼用。
2. 點方塊 → 停用（空框、上面不填色、尺規紅線不見）；再點 → 啟用。按住拖走再放開
   不算點。
3. 拖右邊 → 放開才送出；不過下一段；靠近字幕的邊吸附；Esc 放棄。游標：身體是手指、
   邊是左右箭頭。剪點列空白處照樣跳轉；字幕列照樣選取。
4. 接進播放器：停用與拖過的範圍記成微調、摘要只算啟用的、「還原剪點」清掉；字幕改了
   重算時，沒變的剪點微調留著、變了的放掉；Ctrl+Z 只退字幕不退剪點；換來源再換回來
   微調還在；1280×800 下影片畫面仍有足夠高度、還原按鈕看得到。
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
    print("SKIP 這個環境沒有 PySide6：略過剪點列（規則本身在 test_cutmarks.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer  # noqa: E402
    from PySide6.QtGui import QColor  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import cutmarks  # noqa: E402

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

    LANE_Y = tl.ROW_Y["cuts"] + tl.CUT_LANE_H // 2
    CUE_Y = tl.ROW_Y["cues"] + tl.CUE_H // 2

    # ----- 1～3. 時間軸本身 -----
    view = tl.TimelineView()
    view.resize(1000, view.height())
    view.show()
    wait(50)
    view.set_duration(20)
    view.set_zoom(40, 0, 0)  # 每秒 40px
    view.set_cues([{"start": 1, "end": 4, "text": "第一句"}, {"start": 9, "end": 12, "text": "第二句"}])
    vp = view.viewport()
    check("時間軸高度包含剪點列", view.height() >= tl.TOTAL_H and tl.ROW_Y["cuts"] >= tl.ROW_Y["cues"] + tl.CUE_H)

    def lane_ink(x0, x1):
        img = vp.grab().toImage()
        bg = QColor(img.pixel(x0, tl.ROW_Y["cuts"] + 1))  # 列的最上緣：底色（字在中間）
        return sum(1 for x in range(x0, x1) for y in range(tl.ROW_Y["cuts"] + 2, tl.ROW_Y["cuts"] + tl.CUT_LANE_H - 2)
                   if QColor(img.pixel(x, y)) != bg)

    wait(30)
    check("沒有剪點時剪點列寫一行怎麼用（有字）", lane_ink(0, 400) > 30, str(lane_ink(0, 400)))
    marks = [{"source": "jumpcut", "start": 4.5, "end": 8.5, "reasons": ["句間停頓 5.0 秒"], "key": "a", "enabled": True},
             {"source": "jumpcut", "start": 12.5, "end": 15.0, "reasons": ["句間停頓 3.0 秒"], "key": "b", "enabled": True}]
    view.set_cut_marks(marks)
    wait(30)
    lanes = view.cut_lane_rects()
    check("剪點列的方塊跟上面的區塊左右對齊、在剪點列裡",
          [(r.left(), r.width()) for r in lanes] == [(r.left(), r.width()) for r in view.cut_rects()]
          and all(tl.ROW_Y["cuts"] <= r.top() and r.bottom() <= tl.TOTAL_H for r in lanes),
          str(lanes))
    check("有剪點時不寫說明（片子範圍內、方塊以外的地方沒有字）", lane_ink(620, 790) == 0,
          str(lane_ink(620, 790)))

    toggles, changes, seeks = [], [], []
    view.cutMarkToggled.connect(lambda i, e: toggles.append((i, e)))
    view.cutMarkChanged.connect(lambda i, s, e: changes.append((i, s, e)))
    view.seekRequested.connect(seeks.append)

    def px(sec):
        return int(round(sec * view.px_per_sec)) - view.horizontalScrollBar().value()

    def ruler_red(sec):
        img = vp.grab().toImage()
        return QColor(img.pixel(px(sec), tl.ROW_Y["ruler"] + tl.RULER_H - 2)).getRgb()[:3] \
            == view.colors["cut_edge"].getRgb()[:3]

    QTest.mouseMove(vp, QPoint(px(6.5), LANE_Y))
    body_cursor = vp.cursor().shape()
    QTest.mouseMove(vp, QPoint(px(8.5) - 1, LANE_Y))
    edge_cursor = vp.cursor().shape()
    check("游標：方塊身體是手指、左右邊是左右箭頭",
          body_cursor == Qt.PointingHandCursor and edge_cursor == Qt.SizeHorCursor,
          f"{body_cursor} {edge_cursor}")
    check("點之前：尺規列底下有紅線", ruler_red(6.5))
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(6.5), LANE_Y))
    wait(30)
    check("點方塊 → cutMarkToggled(0, False)、那段變停用", toggles == [(0, False)]
          and view.cut_marks[0]["enabled"] is False and not seeks, f"{toggles} {seeks}")
    check("停用：上面的區塊不填色、剪點列是虛線空框、尺規紅線不見",
          view.cut_items[0].brush().style() == Qt.NoBrush
          and view.cut_lane_items[0].brush().style() == Qt.NoBrush
          and view.cut_lane_items[0].pen().style() == Qt.DashLine and not ruler_red(6.5))
    check("停用：滑鼠說明寫「已停用」與怎麼重新啟用",
          view.cut_items[0].toolTip().startswith("已停用（這 4.00 秒不剪）")
          and "點一下重新啟用" in view.cut_lane_items[0].toolTip(), view.cut_lane_items[0].toolTip())
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(6.5), LANE_Y))
    wait(30)
    check("再點 → 啟用回來", toggles == [(0, False), (0, True)] and view.cut_marks[0]["enabled"] is True
          and ruler_red(6.5), str(toggles))
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(6.0), LANE_Y))
    QTest.mouseMove(vp, QPoint(px(6.0) + 30, LANE_Y))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(6.0) + 30, LANE_Y))
    wait(30)
    check("按住身體拖走再放開 → 不算點（不切換、時間不變）",
          len(toggles) == 2 and view.cut_marks[0]["enabled"] is True and not changes, f"{toggles} {changes}")

    # 拖右邊
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(8.5) - 1, LANE_Y))
    QTest.mouseMove(vp, QPoint(px(7.5), LANE_Y))
    QTest.mouseMove(vp, QPoint(px(7.0), LANE_Y))
    mid = view.cut_times(0)
    check("拖右邊：拖曳中方塊跟著動（8.5 → 7.0）、還沒送出", abs(mid[1] - 7.0) < 0.03 and not changes, str(mid))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(7.0), LANE_Y))
    wait(30)
    check("放開才送出 cutMarkChanged(0, 4.5, ≈7.0)",
          len(changes) == 1 and changes[0][:2] == (0, 4.5) and abs(changes[0][2] - 7.0) < 0.03, str(changes))
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(view.cut_times(0)[1]) - 1, LANE_Y))
    QTest.mouseMove(vp, QPoint(px(10), LANE_Y))
    QTest.mouseMove(vp, QPoint(px(14), LANE_Y))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(14), LANE_Y))
    wait(30)
    check("往右拖過下一段 → 停在下一段的開始（12.5）", changes[-1] == (0, 4.5, 12.5), str(changes))
    check("接縫（12.5）左邊按下抓的是左邊那段的右邊、右邊按下抓的是右邊那段的左邊",
          view.cut_hit(QPoint(px(12.5) - 2, LANE_Y)) == (0, "end")
          and view.cut_hit(QPoint(px(12.5) + 2, LANE_Y)) == (1, "start"),
          f"{view.cut_hit(QPoint(px(12.5) - 2, LANE_Y))} {view.cut_hit(QPoint(px(12.5) + 2, LANE_Y))}")
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(12.5) - 1, LANE_Y))
    QTest.mouseMove(vp, QPoint(px(10), LANE_Y))
    QTest.mouseMove(vp, QPoint(px(9.1), LANE_Y))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(9.1), LANE_Y))
    wait(30)
    check("靠近第二句的開始（9.0，4px 內）→ 吸附在 9.0", changes[-1] == (0, 4.5, 9.0), str(changes))
    n = len(changes)
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(4.5) + 1, LANE_Y))
    QTest.mouseMove(vp, QPoint(px(3.0), LANE_Y))
    QTest.keyClick(view, Qt.Key_Escape)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(3.0), LANE_Y))
    wait(30)
    check("拖左邊拖到一半按 Esc → 回到原本（4.5）、不送出", len(changes) == n
          and view.cut_times(0) == (4.5, 9.0), f"{changes} {view.cut_times(0)}")
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(18), LANE_Y))
    wait(30)
    check("剪點列的空白處 → 照樣跳轉", seeks[-1:] == [18000], str(seeks))
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(10), CUE_Y))
    wait(30)
    check("字幕列照樣選取（剪點列的操作沒搶走）", view.selected == 1, str(view.selected))
    view.close()

    # ----- 4. 接進播放器 -----
    video = os.path.join(tmp, "e.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=gray:s=320x180:r=30:d=20",
                    "-f", "lavfi", "-i", "sine=d=20", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", video], check=True)
    win = qt_app.MainWindow({"subtitle_style": {}})
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 800)
    win.show()
    panel = win.player_panel
    panel.open_video(video)
    wait_until(lambda: abs(panel.timeline.duration - 20) < 0.3)
    cues = [{"start": 0.5, "end": 2.5, "text": "一"}, {"start": 6.0, "end": 8.0, "text": "二"},
            {"start": 9.0, "end": 10.0, "text": "三"}, {"start": 13.5, "end": 15.5, "text": "四"}]
    panel.set_cues(cues)
    panel.show_cut_marks("jumpcut")
    wait(50)
    tv = panel.timeline
    tv.set_zoom(40, 0, 0)
    tvp = tv.viewport()

    def tpx(sec):
        return int(round(sec * tv.px_per_sec)) - tv.horizontalScrollBar().value()

    def span():
        return [(m["start"], m["end"], m["enabled"]) for m in panel.cut_plan["marks"]]

    check("開始：兩段剪點、都啟用、還原按鈕不能按",
          span() == [(2.65, 5.85, True), (10.15, 13.35, True)] and not panel.cut_reset_btn.isEnabled(), str(span()))
    QTest.mouseClick(tvp, Qt.LeftButton, Qt.NoModifier, QPoint(tpx(4.0), LANE_Y))
    wait(30)
    check("點第一段 → 記成微調（停用）、摘要只算啟用的、還原按鈕可以按",
          panel.cut_overrides == {"jumpcut:2.650-5.850": {"enabled": False}}
          and span()[0][2] is False and panel.cut_plan["removed_seconds"] == 3.2
          and panel.cut_label.text() == "停頓跳剪：1 處，共剪掉 3.2 秒（停用 1 處）"
          and panel.cut_reset_btn.isEnabled(), f"{panel.cut_overrides} {panel.cut_label.text()}")
    QTest.mousePress(tvp, Qt.LeftButton, Qt.NoModifier, QPoint(tpx(13.35) - 1, LANE_Y))
    QTest.mouseMove(tvp, QPoint(tpx(12.5), LANE_Y))
    QTest.mouseMove(tvp, QPoint(tpx(12.0), LANE_Y))
    QTest.mouseRelease(tvp, Qt.LeftButton, Qt.NoModifier, QPoint(tpx(12.0), LANE_Y))
    wait(30)
    second = panel.cut_plan["marks"][1]
    check("拖第二段右邊 → 記成微調、標「調過」、摘要寫出來",
          second["start"] == 10.15 and abs(second["end"] - 12.0) < 0.03 and second["edited"]
          and "調過 1 處" in panel.cut_label.text(), f"{second} {panel.cut_label.text()}")
    # 改一句字幕、但兩段停頓都沒變 → 微調都留著
    tv.select_cue(3, seek=False)
    tv.setFocus()
    QTest.keyClick(tv, Qt.Key_Right)  # 第四句 13.5～15.5 → 13.6～15.6：第二段停頓變了
    wait(30)
    check("第四句往後 0.1 秒 → 第二段停頓變了：它的微調放掉（照新算的 10.15～13.45）；第一段仍停用",
          span() == [(2.65, 5.85, False), (10.15, 13.45, True)]
          and not panel.cut_plan["marks"][1]["edited"], str(span()))
    QTest.keyClick(tv, Qt.Key_Z, Qt.ControlModifier)
    wait(30)
    check("Ctrl+Z 只退字幕（第四句回 13.5）；第一段的停用不受影響、第二段的舊微調又對得上 key",
          [(c["start"], c["end"]) for c in panel.cues][3] == (13.5, 15.5)
          and span()[0][2] is False and abs(span()[1][1] - 12.0) < 0.03, str(span()))
    panel.show_cut_marks("review")
    panel.show_cut_marks("jumpcut")
    check("換成審片建議再換回來 → 停頓跳剪的微調還在", span()[0][2] is False and abs(span()[1][1] - 12.0) < 0.03,
          str(span()))
    panel.show_cut_marks("review")
    QTest.mouseClick(tvp, Qt.LeftButton, Qt.NoModifier,
                     QPoint(tpx((panel.cut_plan["marks"][0]["start"] + panel.cut_plan["marks"][0]["end"]) / 2), LANE_Y))
    wait(30)
    review_keys = [k for k in panel.cut_overrides if k.startswith("review:")]
    panel.show_cut_marks("jumpcut")
    panel.reset_cut_marks()
    check("還原剪點：只清掉目前這種（停頓跳剪）的微調，審片建議的留著；按鈕變成不能按",
          span() == [(2.65, 5.85, True), (10.15, 13.35, True)]
          and [k for k in panel.cut_overrides] == review_keys and len(review_keys) == 1
          and not panel.cut_reset_btn.isEnabled(), f"{span()} {panel.cut_overrides}")
    QTest.mouseClick(panel.cut_reset_btn, Qt.LeftButton)  # 按不能按的按鈕：什麼都不做
    check("字幕沒有被剪點的操作改到", [(c["start"], c["end"]) for c in panel.cues]
          == [(0.5, 2.5), (6.0, 8.0), (9.0, 10.0), (13.5, 15.5)])
    wait(50)
    btn = panel.cut_reset_btn
    top_left = btn.mapTo(win, btn.rect().topLeft())
    check("1280×800：影片畫面仍有 300px 以上高、還原按鈕整顆在視窗裡",
          panel.view.height() >= 300 and btn.isVisible()
          and top_left.x() >= 0 and top_left.x() + btn.width() <= win.width()
          and top_left.y() + btn.height() <= win.height(),
          f"影片高 {panel.view.height()}、按鈕 {top_left} {btn.size()}")
    win.close()
    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 剪點列（停用、拖邊）測試全數通過。")
