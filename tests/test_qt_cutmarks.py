# -*- coding: utf-8 -*-
"""
3.0 第 5 項第一階段：剪點畫到時間軸上、播放器的「剪點」選單。

剪點怎麼算在 test_cutmarks.py（跟真的剪片對照）；這裡驗畫出來的樣子與接線：

1. 時間軸：剪點的矩形位置＝秒數×縮放、從縮圖列蓋到字幕列；縮放後跟著變；再短也
   至少 2px；抓像素——剪點裡的字幕塊偏紅、尺規列底下有紅線、外面不變；滑鼠停上去
   的說明有秒數與原因；剪點不擋滑鼠（點字幕塊照樣選取、拖邊照樣改時間、點波形照樣
   跳轉）；清掉就從場景拿掉；深色主題換色。
2. 播放器：選單四個選項、預設不顯示；選了就畫出 cutmarks.plan 的結果、旁邊寫摘要；
   config 的參數有傳進去；拖字幕、微調、復原、換字幕後剪點跟著重算；選回「不顯
   示」清掉；還沒開影片時提醒片尾的空白先不算。
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
    print("SKIP 這個環境沒有 PySide6：略過剪點畫面（剪點怎麼算在 test_cutmarks.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer  # noqa: E402
    from PySide6.QtGui import QColor, QPalette  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication, QGraphicsLineItem  # noqa: E402

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

    CUE_Y = tl.ROW_Y["cues"] + tl.CUE_H // 2
    WAVE_Y = tl.ROW_Y["wave"] + tl.WAVE_H // 2

    # ----- 1. 時間軸 -----
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
    marks = [{"source": "retakes", "start": 0.8, "end": 4.2, "reasons": ["跟後面「第二句」相似 90%，剪掉較早這次"]},
             {"source": "retakes", "start": 8.5, "end": 9.5, "reasons": ["段落之間沒講話的空檔", "冷場：（冷場 1.0 秒）"]},
             {"source": "retakes", "start": 15, "end": 15, "reasons": ["零長度"]}]
    view.set_cut_marks(marks)
    rects = view.cut_rects()
    top = tl.ROW_Y["thumbs"]
    check("兩段剪點（零長度的不畫）", len(rects) == 2 and len(view.cut_marks) == 2, str(rects))
    check("矩形＝秒數×每秒像素，從縮圖列頂端蓋到字幕列底端",
          [(r.left(), r.width(), r.top(), r.bottom()) for r in rects]
          == [(32.0, 136.0, top, tl.ROW_Y["cues"] + tl.CUE_H), (340.0, 40.0, top, tl.ROW_Y["cues"] + tl.CUE_H)],
          str([(r.left(), r.width(), r.top(), r.bottom()) for r in rects]))
    check("在字幕塊上面、播放頭底下（被剪到的字幕看得出來）",
          all(item.zValue() > max(c[0].zValue() for c in view.cue_items)
              and item.zValue() < view.playhead.zValue() for item in view.cut_items))
    edges = [c for c in view.cut_items[0].childItems() if isinstance(c, QGraphicsLineItem)]
    check("兩側各一條剪點線", sorted(round(e.line().x1(), 1) for e in edges) == [32.0, 168.0],
          str([e.line() for e in edges]))
    check("剪點線是虛線、播放頭是實線（兩個都是紅色，靠線型分）",
          all(e.pen().style() == Qt.DashLine for e in edges)
          and view.playhead.pen().style() == Qt.SolidLine, str([e.pen().style() for e in edges]))
    tip = view.cut_items[1].toolTip()
    check("滑鼠停上去：剪掉幾秒、從哪到哪、每個原因一行",
          tip == "剪掉 1.00 秒（0:08.5 → 0:09.5）\n・段落之間沒講話的空檔\n・冷場：（冷場 1.0 秒）", repr(tip))
    view.set_zoom(80, 0, 0)
    check("拉近後剪點跟著變寬（每秒 80px）",
          [(r.left(), r.width()) for r in view.cut_rects()] == [(64.0, 272.0), (680.0, 80.0)],
          str(view.cut_rects()))
    view.set_zoom(tl.MIN_PX_PER_SEC, 0, 0)
    view.set_cut_marks([{"source": "jumpcut", "start": 3.0, "end": 3.1, "reasons": ["x"]}])
    check("拉到最遠、0.1 秒的剪點也至少 2px 寬", view.cut_rects()[0].width() == 2.0, str(view.cut_rects()))
    view.set_zoom(40, 0, 0)
    view.set_cut_marks(marks)
    wait(30)

    def pixel(x, y):
        return QColor(view.viewport().grab().toImage().pixel(x, y))

    # 避開字幕塊上的字：第一句 3.5 秒（剪點裡）／第二句 7.5 秒（外面）
    inside, outside = pixel(140, CUE_Y), pixel(300, CUE_Y)
    cue, cut = view.colors["cue"], view.colors["cut"]
    a = cut.alphaF()
    blend = [round(c0 * (1 - a) + c1 * a) for c0, c1 in
             zip(cue.getRgb()[:3], cut.getRgb()[:3])]
    check("抓像素：外面的字幕塊是原本的顏色、剪點裡的是字幕色疊上半透明紅（誤差 2）",
          outside.getRgb()[:3] == cue.getRgb()[:3]
          and all(abs(x - y) <= 2 for x, y in zip(inside.getRgb()[:3], blend))
          and inside.green() < outside.green() - 10,
          f"裡 {inside.getRgb()} 應為 {blend}；外 {outside.getRgb()}")
    bar = pixel(100, tl.ROW_Y["ruler"] + tl.RULER_H - 2)
    no_bar = pixel(260, tl.ROW_Y["ruler"] + tl.RULER_H - 2)
    check("抓像素：尺規列底下有紅線（剪點範圍內），外面沒有",
          bar.getRgb()[:3] == view.colors["cut_edge"].getRgb()[:3] and no_bar != bar,
          f"{bar.getRgb()} / {no_bar.getRgb()}")

    selected, seeks, changes = [], [], []
    view.cueSelected.connect(selected.append)
    view.seekRequested.connect(seeks.append)
    view.cueTimesChanged.connect(lambda i, s, e: changes.append((i, s, e)))
    vp = view.viewport()
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, QPoint(100, CUE_Y))  # 2.5 秒，剪點裡的第一句
    wait(30)
    check("剪點不擋滑鼠：點剪點裡的字幕塊照樣選取並跳到開頭",
          view.selected == 0 and selected[-1:] == [0] and seeks[-1:] == [1000], f"{selected} {seeks}")
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(160, CUE_Y))  # 第一句右邊 4.0 秒
    QTest.mouseMove(vp, QPoint(150, CUE_Y))
    QTest.mouseMove(vp, QPoint(140, CUE_Y))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(140, CUE_Y))
    wait(30)
    check("剪點不擋滑鼠：剪點裡拖字幕塊的右邊照樣改時間（4.0 → 3.5）", changes[-1:] == [(0, 1.0, 3.5)], str(changes))
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, QPoint(360, WAVE_Y))  # 9 秒，第二段剪點的波形列
    wait(30)
    check("剪點不擋滑鼠：點剪點裡的波形照樣跳轉", seeks[-1:] == [9000], str(seeks))
    check("拖曳改時間後剪點還在（時間軸不自己重算，交給播放器）", len(view.cut_items) == 2)

    scene_items = set(view.scene_.items())
    old = list(view.cut_items)
    view.set_cut_marks([])
    check("清掉剪點 → 從場景拿掉（連同邊線）",
          not view.cut_items and not any(o in view.scene_.items() for o in old)
          and len(view.scene_.items()) < len(scene_items), str(len(view.scene_.items())))
    view.set_cut_marks(marks)
    dark = QPalette()
    dark.setColor(QPalette.Base, QColor(35, 35, 35))
    dark.setColor(QPalette.Text, QColor(230, 230, 230))
    view.setPalette(dark)
    wait(30)
    check("深色主題：剪點換成深色用的顏色（重畫過）",
          view.cut_items[0].brush().color() == QColor(255, 90, 90, 80), str(view.cut_items[0].brush().color().getRgb()))
    view.close()

    # ----- 2. 播放器 -----
    video = os.path.join(tmp, "c.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=gray:s=320x180:r=30:d=20",
                    "-f", "lavfi", "-i", "sine=d=20", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", video], check=True)
    srt = os.path.join(tmp, "c.srt")
    with open(srt, "w", encoding="utf-8") as fp:
        fp.write("1\n00:00:00,500 --> 00:00:02,500\n大家好歡迎收看今天的節目\n\n"
                 "2\n00:00:06,000 --> 00:00:08,000\n大家好歡迎收看今天的節目喔\n\n"
                 "3\n00:00:09,000 --> 00:00:10,000\n今天要介紹一個很好用的工具\n\n"
                 "4\n00:00:13,500 --> 00:00:15,500\n我們先來看第一個功能\n")
    win = qt_app.MainWindow({"subtitle_style": {}})
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 800)
    win.show()
    panel = win.player_panel
    combo = panel.cut_combo
    check("選單：不顯示＋三種來源（名稱與 cutmarks 一致），預設不顯示",
          [combo.itemText(i) for i in range(combo.count())] == ["不顯示", "停頓跳剪", "重複片段", "審片建議"]
          and combo.currentIndex() == 0 and panel.cut_plan is None,
          str([combo.itemText(i) for i in range(combo.count())]))
    panel.load_subtitles(srt)
    panel.show_cut_marks("jumpcut")
    check("還沒開影片：照字幕算、提醒片尾的空白先不算",
          panel.cut_plan["marks"] and "還沒開影片" in panel.cut_label.text(), panel.cut_label.text())
    panel.open_video(video)
    wait_until(lambda: abs(panel.timeline.duration - 20) < 0.3)
    wait(50)
    duration = panel.player.duration() / 1000.0
    want = cutmarks.plan("jumpcut", panel.cues, duration)
    want["marks"] = cutmarks.apply_overrides(want["marks"], {})  # 沒有微調：只多 edited=False
    check("開了影片（知道片長）→ 重算，不再提醒；時間軸畫的就是 cutmarks.plan 的結果",
          panel.timeline.cut_marks == want["marks"] and panel.cut_label.text() == cutmarks.summary(want)
          and "還沒開影片" not in panel.cut_label.text(), f"{panel.cut_label.text()} {panel.timeline.cut_marks}")
    check("跳剪：兩處停頓（2.5→6.0、10.0→13.5）",
          [(m["start"], m["end"]) for m in panel.timeline.cut_marks] == [(2.65, 5.85), (10.15, 13.35)],
          str(panel.timeline.cut_marks))
    combo.setCurrentIndex(combo.findData("review"))  # 使用者自己在選單上換
    wait(30)
    rv = cutmarks.plan("review", panel.cues, duration)
    rv["marks"] = cutmarks.apply_overrides(rv["marks"], {})
    check("在選單上換成審片建議 → 立刻重畫（含片尾 15.5→20 的冷場）",
          panel.timeline.cut_marks == rv["marks"] and rv["marks"][-1]["end"] == round(duration, 3)
          and panel.cut_label.text().startswith("審片建議："), panel.cut_label.text())
    panel.show_cut_marks("retakes")
    check("重複片段：第一句（被第二句重講）", [(m["start"], m["end"]) for m in panel.timeline.cut_marks]
          == [(0.3, 2.7)], str(panel.timeline.cut_marks))

    # 改字幕時間 → 重算
    panel.show_cut_marks("jumpcut")
    tv = panel.timeline
    tv.set_zoom(40, 0, 0)
    tv.select_cue(2, seek=False)
    tv.setFocus()
    QTest.keyClick(tv, Qt.Key_Right, Qt.ShiftModifier)  # 第三句 9～10 → 10～11
    wait(30)
    check("Shift+→ 把第三句往後 1 秒 → 停頓變了，剪點跟著重算（前面多出 8→10 的 2 秒停頓、"
          "後面 10.15 → 11.15）",
          [(c["start"], c["end"]) for c in panel.cues][2] == (10.0, 11.0)
          and [(m["start"], m["end"]) for m in tv.cut_marks]
          == [(2.65, 5.85), (8.15, 9.85), (11.15, 13.35)], str(tv.cut_marks))
    QTest.keyClick(tv, Qt.Key_Z, Qt.ControlModifier)
    wait(30)
    check("Ctrl+Z 復原 → 剪點也回來", [(m["start"], m["end"]) for m in tv.cut_marks]
          == [(2.65, 5.85), (10.15, 13.35)], str(tv.cut_marks))
    with open(srt, "w", encoding="utf-8") as fp:
        fp.write("1\n00:00:01,000 --> 00:00:02,000\n一\n\n2\n00:00:02,200 --> 00:00:19,000\n二\n")
    panel.load_subtitles(srt)
    check("換一份字幕 → 重算（這份沒有夠長的停頓，寫出原因）",
          tv.cut_marks == [] and panel.cut_label.text() == "停頓跳剪：沒有超過 1.2 秒的停頓",
          panel.cut_label.text())
    panel.show_cut_marks("")
    check("選回不顯示 → 清掉、摘要空白", tv.cut_items == [] and panel.cut_label.text() == ""
          and panel.cut_plan is None)
    try:
        panel.show_cut_marks("magic")
        check("不認得的來源 → ValueError", False)
    except ValueError:
        check("不認得的來源 → ValueError", True)
    win.close()

    # config 的參數有傳進去（跟一般版同一份設定）
    win2 = qt_app.MainWindow({"subtitle_style": {}, "jumpcut": {"min_gap": 3.6, "pad": 0.5}})
    p2 = win2.player_panel
    p2.set_cues([{"start": 0, "end": 1, "text": "a"}, {"start": 5, "end": 5.5, "text": "b"},
                 {"start": 9, "end": 9.5, "text": "c"}])
    p2.show_cut_marks("jumpcut")
    check("MainWindow 把 config 傳給播放器：門檻 3.6 秒 → 4 秒的停頓剪、3.5 秒的不剪；緩衝 0.5",
          [(m["start"], m["end"]) for m in p2.timeline.cut_marks] == [(1.5, 4.5)], str(p2.timeline.cut_marks))
    win2.close()
    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 剪點畫到時間軸上的測試全數通過。")
