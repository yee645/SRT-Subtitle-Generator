# -*- coding: utf-8 -*-
"""
3.0 第 7 項第二階段：時間軸上的素材軌（疊加畫面、背景音樂）。

核心（subtitle/assemble.py 的 new_overlay／new_music／item_span／render）在
test_assemble.py；這裡驗介面，QTest 真的按下／移動／放開：

1. 時間軸本身：兩條素材軌在剪點列下面；方塊的位置與寬度照 item_span（圖片 3 秒、
   音樂超出片尾的剪掉）；空的軌寫一行怎麼用。
2. 點方塊＝選取並跳到開頭；拖身體＝改位置（吸附播放頭、字幕的邊、別段素材的頭尾，
   尾巴也能吸）；拖不出片頭片尾；Esc 放回原位；Delete 送出刪除；點空白處取消選取。
3. 播放器面板：沒開片子按鈕全灰；在播放頭的位置加畫面／音樂；放錯軌（沒畫面的檔
   放畫面軌、沒聲音的放音樂軌、不存在的檔）說清楚、不加；拖曳改到面板的資料；
   刪除；換片子清掉。
4. 輸出多軌：圖片真的疊在那幾秒（量畫面的顏色）、音樂真的在那幾秒（量 1000 Hz 的
   音量）、片長＝原片、字幕存一份同檔名 .srt；輸出中按鈕灰掉、輸出檔蓋到素材時
   拒絕並說明。
"""
import os
import re
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

if PySide6 is None or not shutil.which("ffmpeg"):
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過素材軌介面（核心在 test_assemble.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer  # noqa: E402
    from PySide6.QtGui import QColor  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import assemble  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = tmp
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait_until(cond, timeout_ms=60000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(50)
            waited += 50
        return cond()

    def run(*args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)

    OV_Y = tl.ROW_Y["overlays"] + tl.TRACK_H // 2
    MU_Y = tl.ROW_Y["music"] + tl.TRACK_H // 2

    # ----- 1. 時間軸本身 -----
    view = tl.TimelineView()
    view.resize(1000, view.height())
    view.show()
    wait(50)
    view.set_duration(20)
    view.set_zoom(40, 0, 0)  # 每秒 40px
    view.set_cues([{"start": 1, "end": 4, "text": "第一句"}, {"start": 9, "end": 12, "text": "第二句"}])
    vp = view.viewport()
    check("兩條素材軌在剪點列下面、都在時間軸高度裡",
          tl.ROW_Y["overlays"] >= tl.ROW_Y["cuts"] + tl.CUT_LANE_H
          and tl.ROW_Y["music"] >= tl.ROW_Y["overlays"] + tl.TRACK_H
          and view.height() >= tl.TOTAL_H == tl.ROW_Y["music"] + tl.TRACK_H)

    def row_ink(kind, x0, x1):
        img = vp.grab().toImage()
        top = tl.ROW_Y[kind]
        bg = QColor(img.pixel(x0, top + 1))
        return sum(1 for x in range(x0, x1) for y in range(top + 2, top + tl.TRACK_H - 2)
                   if QColor(img.pixel(x, y)) != bg)

    wait(30)
    check("空的疊加軌寫一行怎麼用", row_ink("overlays", 0, 400) > 30, str(row_ink("overlays", 0, 400)))
    check("空的音樂軌寫一行怎麼用", row_ink("music", 0, 400) > 30, str(row_ink("music", 0, 400)))

    img_path = os.path.join(tmp, "logo.png")
    overlays = [{"path": img_path, "at": 2.0, "duration": 3.0},
                {"path": os.path.join(tmp, "broll.mp4"), "at": 14.0, "in": 1.0, "out": 3.0}]
    music = [{"path": os.path.join(tmp, "song.wav"), "at": 6.0, "in": 0.0, "out": 30.0,
              "volume": 0.35, "loop": False, "duck": True}]
    view.set_tracks(overlays, music)
    wait(30)
    ov, mu = view.track_rects("overlays"), view.track_rects("music")
    check("疊加方塊：圖片 2～5 秒、影片 14～16 秒（out−in）",
          [(round(r.left()), round(r.width())) for r in ov] == [(80, 120), (560, 80)], str(ov))
    check("音樂方塊：6 秒開始，超出片尾的剪掉（到 20 秒）",
          [(round(r.left()), round(r.right())) for r in mu] == [(240, 800)], str(mu))
    check("方塊在自己那一軌裡",
          all(tl.ROW_Y["overlays"] <= r.top() and r.bottom() <= tl.ROW_Y["overlays"] + tl.TRACK_H for r in ov)
          and all(tl.ROW_Y["music"] <= r.top() and r.bottom() <= tl.ROW_Y["music"] + tl.TRACK_H for r in mu))
    check("有素材時不寫說明（方塊以外的那一段是空白）", row_ink("overlays", 210, 550) == 0,
          str(row_ink("overlays", 210, 550)))
    check("時間軸的資料是複本（改原本的 list 不影響畫面）",
          view.tracks["overlays"] is not overlays and view.tracks["overlays"][0] is not overlays[0])

    sels, moves, dels, seeks = [], [], [], []
    view.trackItemSelected.connect(lambda k, i: sels.append((k, i)))
    view.trackItemMoved.connect(lambda k, i, at: moves.append((k, i, at)))
    view.trackItemDeleteRequested.connect(lambda k, i: dels.append((k, i)))
    view.seekRequested.connect(seeks.append)

    def px(sec):
        return int(round(sec * view.px_per_sec)) - view.horizontalScrollBar().value()

    # ----- 2. 點、拖、Esc、Delete -----
    view.set_position(0)
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(3.0), OV_Y))
    check("點方塊＝選取（送出哪一軌第幾段）", view.track_selected == ("overlays", 0)
          and sels[-1:] == [("overlays", 0)], f"{view.track_selected} {sels}")
    check("點方塊＝跳到它開始的地方", seeks[-1:] == [2000] and view.position_ms == 2000, str(seeks))
    check("點選不算拖（沒有送出移動）", moves == [])
    wait(30)
    img = vp.grab().toImage()
    check("選取的方塊有框（框的顏色）",
          QColor(img.pixel(px(3.5), tl.ROW_Y["overlays"] + 2)).getRgb()[:3]
          == view.colors["track_sel_pen"].getRgb()[:3],
          str(QColor(img.pixel(px(3.5), tl.ROW_Y["overlays"] + 2)).getRgb()))

    # 移動不到 MOVE_START_PX：還是點選（跳到開頭），位置不變。播放頭先移開，免得被它吸回原位
    view.set_position(0)
    seeks.clear()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(3.0), OV_Y))
    QTest.mouseMove(vp, QPoint(px(3.0) + 2, OV_Y))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(3.0) + 2, OV_Y))
    check("移動不到門檻＝點選（跳到開頭），位置不變",
          moves == [] and view.tracks["overlays"][0]["at"] == 2.0 and seeks == [2000], f"{moves} {seeks}")

    # 拖 +2.5 秒（2.0 → 4.5），遠離任何吸附點（播放頭在 2、字幕邊 1/4/9/12、音樂 6、影片 14/16）
    view.set_position(0)
    seeks.clear()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(3.0), OV_Y))
    QTest.mouseMove(vp, QPoint(px(4.0), OV_Y))
    QTest.mouseMove(vp, QPoint(px(5.5), OV_Y))
    check("拖曳中方塊跟著動", round(view.track_rects("overlays")[0].left()) == 180,
          str(view.track_rects("overlays")[0]))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(5.5), OV_Y))
    check("拖完送出新的開始（4.5 秒）、長度不變", moves[-1:] == [("overlays", 0, 4.5)]
          and view.track_span("overlays", 0) == (4.5, 7.5), f"{moves} {view.track_span('overlays', 0)}")
    check("拖完不跳播放頭（拖曳不是點選）", seeks == [], str(seeks))

    # 吸附：頭拖到離字幕的 9 秒 0.1 秒（4px < SNAP_PX）→ 貼到 9
    moves.clear()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(5.0), OV_Y))
    QTest.mouseMove(vp, QPoint(px(7.0), OV_Y))
    QTest.mouseMove(vp, QPoint(px(5.0 + 4.4), OV_Y))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(5.0 + 4.4), OV_Y))
    check("頭吸到字幕的邊（9 秒）", moves[-1:] == [("overlays", 0, 9.0)], str(moves))
    # 尾巴吸：從 9 往前拖，尾巴（at＋3）靠近音樂的開頭 6 → at＝3
    moves.clear()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(10.0), OV_Y))
    QTest.mouseMove(vp, QPoint(px(8.0), OV_Y))
    QTest.mouseMove(vp, QPoint(px(10.0 - 5.9), OV_Y))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(10.0 - 5.9), OV_Y))
    check("尾巴吸到別軌素材的頭（音樂 6 秒 → 開始 3 秒）", moves[-1:] == [("overlays", 0, 3.0)], str(moves))
    # 播放頭也是吸附點
    view.set_position(7300)
    moves.clear()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(4.0), OV_Y))
    QTest.mouseMove(vp, QPoint(px(6.0), OV_Y))
    QTest.mouseMove(vp, QPoint(px(4.0 + 4.25), OV_Y))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(4.0 + 4.25), OV_Y))
    check("頭吸到播放頭（7.3 秒）", moves[-1:] == [("overlays", 0, 7.3)], str(moves))
    view.set_position(0)
    # 拖不出片頭
    moves.clear()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(8.0), OV_Y))
    QTest.mouseMove(vp, QPoint(px(6.0), OV_Y))
    QTest.mouseMove(vp, QPoint(0, OV_Y))
    QTest.mouseMove(vp, QPoint(-200, OV_Y))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(-200, OV_Y))
    check("拖不出片頭（停在 0）", moves[-1:] == [("overlays", 0, 0.0)], str(moves))
    # 拖不出片尾：開始最晚到片尾前 MIN_CLIP
    moves.clear()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(1.0), OV_Y))
    QTest.mouseMove(vp, QPoint(px(3.0), OV_Y))
    QTest.mouseMove(vp, QPoint(px(19.0), OV_Y))
    QTest.mouseMove(vp, QPoint(px(24.0), OV_Y))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(24.0), OV_Y))
    check("拖不出片尾（開始停在 20 − MIN_CLIP）",
          moves[-1:] == [("overlays", 0, round(20 - assemble.MIN_CLIP, 3))]
          and view.track_span("overlays", 0)[1] == 20.0, f"{moves} {view.track_span('overlays', 0)}")
    view.set_tracks(overlays, music)  # 放回 2～5 秒
    # Esc：放回原位、不送出移動
    moves.clear()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(3.0), OV_Y))
    QTest.mouseMove(vp, QPoint(px(5.0), OV_Y))
    QTest.mouseMove(vp, QPoint(px(7.5), OV_Y))
    QTest.keyClick(view, Qt.Key_Escape)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(7.5), OV_Y))
    check("Esc 放回原位、不送出移動", moves == [] and view.track_span("overlays", 0) == (2.0, 5.0)
          and round(view.track_rects("overlays")[0].left()) == 80,
          f"{moves} {view.track_span('overlays', 0)}")
    # 音樂軌一樣能拖
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(7.0), MU_Y))
    QTest.mouseMove(vp, QPoint(px(8.0), MU_Y))
    QTest.mouseMove(vp, QPoint(px(8.5), MU_Y))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(8.5), MU_Y))
    check("音樂軌也能拖（6 → 7.5，尾巴還是剪在片尾）", moves[-1:] == [("music", 0, 7.5)]
          and view.track_span("music", 0) == (7.5, 20.0), f"{moves} {view.track_span('music', 0)}")
    check("拖哪一段就選取哪一段", view.track_selected == ("music", 0))
    # Delete
    view.setFocus()
    QTest.keyClick(view, Qt.Key_Delete)
    check("選取後按 Delete＝送出刪除（由面板決定刪不刪）", dels == [("music", 0)], str(dels))
    # 重疊時點到後加的那段
    view.set_tracks([{"path": img_path, "at": 2.0, "duration": 3.0},
                     {"path": img_path, "at": 3.0, "duration": 3.0}], [])
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(4.0), OV_Y))
    check("重疊時點到後加的（畫在上面的）那段", view.track_selected == ("overlays", 1), str(view.track_selected))
    # 點素材軌的空白處：取消選取
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(15.0), OV_Y))
    check("點素材軌的空白處＝取消選取", view.track_selected is None and sels[-1] == ("", -1), str(sels[-2:]))
    view.set_tracks([], [])
    check("清掉素材軌後沒有方塊", view.track_rects("overlays") == [] and view.track_rects("music") == [])
    view.close()

    # ----- 3. 播放器面板 -----
    main = os.path.join(tmp, "main.mp4")
    # 畫面是灰的、聲音是 150 Hz（量 1000 Hz 時濾得掉的「講話聲」），6 秒
    run("-f", "lavfi", "-i", "color=c=0x808080:size=640x360:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=150:sample_rate=48000", "-t", "6",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", main)
    run("-f", "lavfi", "-i", "color=c=red:size=320x180", "-frames:v", "1", img_path)
    song = os.path.join(tmp, "song.wav")
    run("-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000", "-t", "1.5", song)
    silent = os.path.join(tmp, "silent.mp4")
    run("-f", "lavfi", "-i", "color=c=blue:size=320x180:rate=30", "-t", "2",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", silent)

    win = qt_app.MainWindow({"subtitle_style": {}})
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 860)
    win.show()
    panel = win.player_panel
    errors = []
    panel._show_track_error = errors.append
    buttons = (panel.add_overlay_btn, panel.add_music_btn, panel.remove_track_btn, panel.assemble_btn)
    check("沒開片子：素材軌的按鈕全灰", not any(b.isEnabled() for b in buttons))
    check("沒開片子：add_track 不做事", panel.add_track("overlays", img_path) is False and errors == [])

    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0, 20000)
    wait(100)
    check("開片子後：可以加素材，不能刪、不能輸出（還沒有素材）",
          panel.add_overlay_btn.isEnabled() and panel.add_music_btn.isEnabled()
          and not panel.remove_track_btn.isEnabled() and not panel.assemble_btn.isEnabled())
    panel.set_cues([{"start": 0.5, "end": 2.0, "text": "第一句"}, {"start": 3.0, "end": 5.5, "text": "第二句"}])

    asked = []
    panel._ask_track_file = lambda kind: asked.append(kind) or ""
    check("按「加入畫面…」先問要哪個檔；取消就不加",
          panel.add_track("overlays") is False and asked == ["overlays"] and not any(panel.tracks.values()))

    panel.player.setPosition(1000)
    wait_until(lambda: panel.player.position() == 1000, 5000)
    check("加入畫面：在播放頭的位置（1 秒）放 3 秒的圖片",
          panel.add_track("overlays", img_path) is True
          and panel.tracks["overlays"] == [{"path": img_path, "at": 1.0, "duration": 3.0}],
          str(panel.tracks["overlays"]))
    check("加完就選取那一段、畫到時間軸上",
          panel.timeline.track_selected == ("overlays", 0)
          and len(panel.timeline.track_rects("overlays")) == 1 and panel.remove_track_btn.isEnabled())
    check("有素材之後可以輸出、那一行寫幾段與「播放器還不會疊上去」",
          panel.assemble_btn.isEnabled() and "畫面 1 段" in panel.track_label.text()
          and "還不會" in panel.track_label.text(), panel.track_label.text())

    panel.player.setPosition(3500)
    wait_until(lambda: panel.player.position() == 3500, 5000)
    check("加入音樂：在播放頭（3.5 秒）放整首、預設音量、講話時壓低",
          panel.add_track("music", song) is True
          and panel.tracks["music"] == [{"path": song, "at": 3.5, "in": 0.0, "out": 1.5, "length": 1.5,
                                         "volume": assemble.DEFAULT_MUSIC_VOLUME, "loop": False, "duck": True}],
          str(panel.tracks["music"]))
    check("那一行寫兩種各幾段", "畫面 1 段、音樂 1 段" in panel.track_label.text(), panel.track_label.text())

    errors.clear()
    check("沒聲音的檔放音樂軌：不加、說明", panel.add_track("music", silent) is False
          and len(panel.tracks["music"]) == 1 and errors and "沒有聲音" in errors[-1], str(errors))
    errors.clear()
    check("圖片放音樂軌：不加、說明", panel.add_track("music", img_path) is False
          and len(panel.tracks["music"]) == 1 and errors and "沒有聲音" in errors[-1], str(errors))
    errors.clear()
    check("沒畫面的檔放畫面軌：不加、說明", panel.add_track("overlays", song) is False
          and len(panel.tracks["overlays"]) == 1 and errors and "沒有畫面" in errors[-1], str(errors))
    errors.clear()
    check("不存在的檔：不加、說明找不到", panel.add_track("overlays", os.path.join(tmp, "nope.mp4")) is False
          and len(panel.tracks["overlays"]) == 1 and errors == ["找不到 nope.mp4"], str(errors))
    errors.clear()
    try:
        panel.add_track("subtitles", img_path)
        check("不認得的軌要拋錯", False)
    except ValueError:
        check("不認得的軌要拋錯", True)

    # 在面板的時間軸上拖：面板的資料跟著改
    tv = panel.timeline
    tv.set_zoom(100, 0, 0)
    tvp = tv.viewport()

    def tpx(sec):
        return int(round(sec * tv.px_per_sec)) - tv.horizontalScrollBar().value()

    panel.player.setPosition(0)
    wait_until(lambda: tv.position_ms == 0, 5000)
    QTest.mousePress(tvp, Qt.LeftButton, Qt.NoModifier, QPoint(tpx(2.0), OV_Y))
    QTest.mouseMove(tvp, QPoint(tpx(1.5), OV_Y))
    QTest.mouseMove(tvp, QPoint(tpx(1.2), OV_Y))
    QTest.mouseRelease(tvp, Qt.LeftButton, Qt.NoModifier, QPoint(tpx(1.2), OV_Y))
    check("在時間軸上拖畫面：面板的資料跟著改（1.0 → 0.2）", panel.tracks["overlays"][0]["at"] == 0.2,
          str(panel.tracks["overlays"]))

    # 加第二段音樂再刪（按鈕刪、Delete 刪）
    panel.player.setPosition(0)
    wait_until(lambda: panel.player.position() == 0, 5000)
    panel.add_track("music", song)
    check("第二段音樂加在 0 秒、被選取", panel.tracks["music"][-1]["at"] == 0.0
          and tv.track_selected == ("music", 1))
    panel.remove_track_btn.click()
    check("按「刪除選取」：刪掉選取的那段、取消選取、按鈕灰掉",
          len(panel.tracks["music"]) == 1 and panel.tracks["music"][0]["at"] == 3.5
          and tv.track_selected is None and not panel.remove_track_btn.isEnabled(),
          str(panel.tracks["music"]))
    panel.player.setPosition(500)
    wait_until(lambda: panel.player.position() == 500, 5000)
    panel.add_track("music", song)
    tv.select_track_item("music", 0, seek=False)
    check("刪掉不是最後一段的選取：刪對那段、取消選取（選取不會跳到下一段）",
          panel.remove_selected_track() is True and [m["at"] for m in panel.tracks["music"]] == [0.5]
          and tv.track_selected is None and not panel.remove_track_btn.isEnabled(),
          f"{panel.tracks['music']} {tv.track_selected}")
    panel.tracks["music"][0]["at"] = 3.5
    panel.refresh_tracks()
    panel.add_track("music", song)
    tv.setFocus()
    QTest.keyClick(tv, Qt.Key_Delete)
    check("選取後按 Delete：刪掉", len(panel.tracks["music"]) == 1 and len(tv.track_rects("music")) == 1)
    panel.tracks["music"][0]["at"] = 3.5

    # ----- 4. 輸出多軌 -----
    out = os.path.join(tmp, "成品.mp4")
    started = panel.export_tracks(out)
    check("開始輸出", started is True)
    check("輸出中：素材軌的按鈕全灰、那一行寫正在輸出",
          not any(b.isEnabled() for b in buttons) and "正在輸出" in panel.track_label.text(),
          panel.track_label.text())
    check("輸出中不能再加素材", panel.add_track("overlays", img_path) is False
          and len(panel.tracks["overlays"]) == 1)
    wait_until(lambda: not panel.track_exporter.busy, 120000)
    wait(100)
    result = panel.last_assemble
    check("輸出成功、沒有錯誤訊息", result is not None and result["output"] == out and errors == [],
          f"{result} {errors}")
    check("那一行寫輸出了哪兩個檔", "已輸出 成品.mp4＋成品.srt" in panel.track_label.text(), panel.track_label.text())
    check("輸出完按鈕恢復", panel.assemble_btn.isEnabled() and panel.add_overlay_btn.isEnabled())
    srt = os.path.join(tmp, "成品.srt")
    with open(srt, encoding="utf-8") as fh:
        text = fh.read()
    check("字幕原封不動存一份同檔名 .srt（主軌時間沒變）",
          "00:00:00,500 --> 00:00:02,000" in text and "00:00:03,000 --> 00:00:05,500" in text
          and "第二句" in text, text)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "default=nw=1:nk=1", out], capture_output=True, text=True).stdout)
    check("片長＝原片（6 秒）", abs(dur - 6.0) < 0.1, str(dur))

    def frame_rgb(t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", out, "-frames:v", "1",
                              "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True).stdout
        return tuple(raw[:3])

    red_in, grey_before, grey_after = frame_rgb(1.5), frame_rgb(0.05), frame_rgb(4.5)
    check("0.2～3.2 秒疊著紅色的圖", red_in[0] > 200 and red_in[1] < 60, str(red_in))
    check("疊之前與之後是原片的灰", all(100 < c < 160 for c in grey_before + grey_after),
          f"{grey_before} {grey_after}")

    def tone_db(start, length):
        done = subprocess.run(["ffmpeg", "-v", "info", "-ss", str(start), "-t", str(length), "-i", out,
                               "-af", "highpass=f=700,highpass=f=700,highpass=f=700,highpass=f=700,volumedetect", "-vn", "-f", "null", "-"],
                              capture_output=True, text=True)
        found = re.search(r"mean_volume:\s*(-?[\d.]+|-inf) dB", done.stderr)
        return float(found.group(1)) if found and found.group(1) != "-inf" else -200.0

    in_music, before_music = tone_db(3.7, 1.0), tone_db(1.0, 1.5)
    after_music = tone_db(5.2, 0.7)
    check("音樂在 3.5～5 秒（高頻比沒音樂的前後都大 20 dB 以上；講話時壓低也聽得到）",
          in_music - before_music > 20 and in_music - after_music > 20, f"{in_music} {before_music} {after_music}")

    # 輸出檔蓋到素材：拒絕並說明，素材不動
    size_before = os.path.getsize(song)
    errors.clear()
    panel.export_tracks(song)
    wait_until(lambda: not panel.track_exporter.busy, 20000)
    wait(100)
    check("輸出檔是素材本身：拒絕並說明、素材不動",
          errors and "會把素材蓋掉" in errors[-1] and os.path.getsize(song) == size_before, str(errors))
    check("失敗後那一行回到摘要、按鈕恢復", "畫面 1 段" in panel.track_label.text()
          and panel.assemble_btn.isEnabled(), panel.track_label.text())

    asked_out = []
    panel._ask_assemble_path = lambda suggested: asked_out.append(suggested) or ""
    check("按「輸出多軌…」先問存哪（建議 原檔名_多軌.mp4）；取消就不輸出",
          panel.export_tracks() is False and asked_out == [os.path.join(tmp, "main_多軌.mp4")], str(asked_out))

    # 換片子：素材軌清掉
    panel.open_video(silent)
    check("換片子：素材軌清掉、那一行清空、時間軸沒有方塊",
          panel.tracks == {"overlays": [], "music": []} and panel.track_label.text() == ""
          and tv.track_rects("overlays") == [] and tv.track_rects("music") == [])
    wait_until(lambda: panel.player.duration() > 0, 20000)
    panel.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 素材軌（疊加畫面、背景音樂）測試全數通過。")
