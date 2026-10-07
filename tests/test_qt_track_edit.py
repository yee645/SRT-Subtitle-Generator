# -*- coding: utf-8 -*-
"""
3.0 第 7 項第三階段：素材修頭尾與素材屬性。

規則（assemble.trim_item／OVERLAY_POSITIONS）在 test_assemble.py；這裡驗介面，QTest 真的按：

1. 時間軸：游標移到素材的左右邊變左右箭頭、身體是手；循環音樂的尾巴算身體。
   拖頭＝開始與進點一起動、尾巴不動；拖尾最多到素材長度；照移動量算（抓在邊旁邊
   不會跳）；會吸附；Esc 放回原樣；
   放開時送出 trackItemChanged（沒改不送）；按邊也會選取那段。
2. 播放器面板「素材屬性」那一行：沒選取時寫怎麼用；選音樂顯示音量／循環／壓低、選
   畫面顯示位置／帶聲音（圖片不能帶聲音）；改了寫回素材、時間軸跟著變（循環到片尾、
   方塊上寫位置）；不合理的值不收；在面板的時間軸上修頭尾，面板的資料跟著改；輸出中灰掉。
3. 輸出：右上小畫面真的只蓋右上角（量畫面）；循環的音樂真的放到片尾（量音量）。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過素材修頭尾與屬性（核心在 test_assemble.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import player as player_mod  # noqa: E402
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

    # ----- 1. 時間軸 -----
    view = tl.TimelineView()
    view.resize(1000, view.height())
    view.show()
    wait(50)
    view.set_duration(20)
    view.set_zoom(40, 0, 0)  # 每秒 40px
    view.set_cues([{"start": 13, "end": 14, "text": "一句"}])
    vp = view.viewport()

    def px(sec):
        return int(round(sec * view.px_per_sec)) - view.horizontalScrollBar().value()

    clip = {"path": os.path.join(tmp, "broll.mp4"), "at": 2.0, "in": 1.0, "out": 4.0, "length": 5.0}
    pic = {"path": os.path.join(tmp, "logo.png"), "at": 8.0, "duration": 3.0}
    looped = {"path": os.path.join(tmp, "song.wav"), "at": 12.0, "in": 0.0, "out": 2.0, "length": 2.0,
              "volume": 0.35, "loop": True, "duck": True}
    view.set_tracks([clip, pic], [looped])
    changes, moves = [], []
    view.trackItemChanged.connect(lambda k, i, item: changes.append((k, i, item)))
    view.trackItemMoved.connect(lambda k, i, at: moves.append((k, i, at)))

    def cursor_at(x, y):
        QTest.mouseMove(vp, QPoint(x, y))
        return vp.cursor().shape()

    check("游標在素材的左邊：左右箭頭", cursor_at(px(2.0) + 1, OV_Y) == Qt.SizeHorCursor)
    check("游標在素材的右邊：左右箭頭", cursor_at(px(5.0) - 1, OV_Y) == Qt.SizeHorCursor)
    check("游標在素材的身體：手", cursor_at(px(3.5), OV_Y) == Qt.OpenHandCursor)
    check("循環音樂的尾巴不能修（算身體：手）", cursor_at(px(20.0) - 1, MU_Y) == Qt.OpenHandCursor
          and view.track_part(QPoint(px(20.0) - 1, MU_Y)) == ("music", 0, "body"))
    check("循環音樂的頭可以修", view.track_part(QPoint(px(12.0) + 1, MU_Y)) == ("music", 0, "start"))

    def drag(x0, y, *xs):
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(x0, y))
        for x in xs:
            QTest.mouseMove(vp, QPoint(x, y))
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(xs[-1], y))

    view.set_position(0)
    drag(px(2.0) + 1, OV_Y, px(2.5), px(3.0) + 1)
    check("拖頭往右：開始與進點一起動、尾巴不動",
          changes[-1:] == [("overlays", 0, dict(clip, at=3.0, **{"in": 2.0}))]
          and view.track_span("overlays", 0) == (3.0, 5.0), f"{changes} {view.track_span('overlays', 0)}")
    check("按邊也會選取那段", view.track_selected == ("overlays", 0))
    check("修頭尾不算移動", moves == [])
    check("拖曳中方塊跟著變、放開後時間軸的資料是新的",
          round(view.track_rects("overlays")[0].left()) == 120
          and view.tracks["overlays"][0]["in"] == 2.0)
    drag(px(3.0) + 1, OV_Y, px(2.0), px(0.0))
    check("拖頭往左：最多拉到素材的開頭（進點 0 → 開始 1 秒）",
          changes[-1][2]["at"] == 1.0 and changes[-1][2]["in"] == 0.0, str(changes[-1]))
    drag(px(5.0) - 1, OV_Y, px(6.0), px(9.0))
    check("拖尾往右：最多到素材本身的長度（out＝5）", changes[-1][2]["out"] == 5.0
          and view.track_span("overlays", 0) == (1.0, 6.0), str(changes[-1]))
    view.set_position(4500)
    drag(px(6.0) - 1, OV_Y, px(5.0), px(4.55))
    check("拖尾吸到播放頭（4.5 秒 → out＝3.5）", changes[-1][2]["out"] == 3.5, str(changes[-1]))
    view.set_position(0)
    n = len(changes)
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(4.5) - 1, OV_Y))
    QTest.mouseMove(vp, QPoint(px(5.5), OV_Y))
    QTest.keyClick(view, Qt.Key_Escape)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(5.5), OV_Y))
    check("Esc 放回原樣、不送出", len(changes) == n and view.track_span("overlays", 0) == (1.0, 4.5)
          and view.tracks["overlays"][0]["out"] == 3.5, str(view.tracks["overlays"][0]))
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(4.5) - 1, OV_Y))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(4.5) - 1, OV_Y))
    check("按邊沒拖：不送出", len(changes) == n)
    drag(px(11.0) - 1, OV_Y, px(12.0), px(15.0) - 1)
    check("圖片拖尾：長度變長（3 → 7 秒）", changes[-1] == ("overlays", 1, dict(pic, duration=7.0)), str(changes[-1]))
    drag(px(12.0) + 1, MU_Y, px(12.5), px(13.1) + 1)
    check("循環音樂修頭：吸到字幕的開頭（13 秒），還是到片尾",
          changes[-1][0] == "music" and changes[-1][2]["at"] == 13.0 and changes[-1][2]["in"] == 1.0
          and view.track_span("music", 0) == (13.0, 20.0), str(changes[-1]))
    n = len(changes)
    drag(px(20.0) - 2, MU_Y, px(19.0), px(17.0) - 2)
    check("循環音樂抓尾巴：整段移動，不是修尾", len(changes) == n and moves[-1:] == [("music", 0, 10.0)],
          f"{changes[n:]} {moves}")
    view.close()

    # ----- 2. 播放器面板 -----
    main = os.path.join(tmp, "main.mp4")
    run("-f", "lavfi", "-i", "color=c=0x808080:size=640x360:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=150:sample_rate=48000", "-t", "6",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", main)
    logo = os.path.join(tmp, "logo.png")
    run("-f", "lavfi", "-i", "color=c=red:size=320x180", "-frames:v", "1", logo)
    song = os.path.join(tmp, "song.wav")
    run("-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000", "-t", "1.5", song)

    win = qt_app.MainWindow({"subtitle_style": {}})
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 900)
    win.show()
    panel = win.player_panel
    errors = []
    panel._show_track_error = errors.append
    tv = panel.timeline
    music_w = (panel.volume_spin, panel.loop_box, panel.duck_box)
    overlay_w = (panel.position_combo, panel.overlay_audio_box)

    def shown(widgets):
        return all(w.isVisibleTo(panel) for w in widgets)

    def hidden(widgets):
        return not any(w.isVisibleTo(panel) for w in widgets)

    check("沒選取：屬性那一行只寫怎麼用", panel.prop_label.text() == player_mod.PROP_HINT
          and hidden(music_w) and hidden(overlay_w))
    check("沒選取：改屬性不做事", panel.set_track_props(volume=1.0) is False)

    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0, 20000)
    wait(100)
    panel.player.setPosition(500)
    wait_until(lambda: panel.player.position() == 500, 5000)
    panel.add_track("overlays", logo)
    check("選了圖片：顯示位置與帶聲音、不顯示音樂的；那一行寫檔名",
          shown(overlay_w) and hidden(music_w) and panel.prop_label.text() == "logo.png")
    check("圖片：位置是「蓋滿」、不能帶聲音",
          panel.position_combo.currentData() == "full" and not panel.overlay_audio_box.isEnabled()
          and not panel.overlay_audio_box.isChecked())
    panel.position_combo.setCurrentIndex(panel.position_combo.findData("top_right"))
    check("選「右上小畫面」：寫回素材的 rect",
          panel.tracks["overlays"][0].get("rect") == assemble.position_rect("top_right"),
          str(panel.tracks["overlays"][0]))
    label_texts = [c.text() for item in tv.track_items["overlays"] for c in item.childItems()
                   if hasattr(c, "text")]
    check("時間軸的方塊上寫位置", any("右上小畫面" in t for t in label_texts), str(label_texts))
    check("改了屬性還是選取著同一段", tv.track_selected == ("overlays", 0)
          and panel.position_combo.currentData() == "top_right")

    panel.player.setPosition(3500)
    wait_until(lambda: panel.player.position() == 3500, 5000)
    panel.add_track("music", song)
    check("選了音樂：顯示音量／循環／壓低、不顯示畫面的", shown(music_w) and hidden(overlay_w))
    check("音樂：照素材填（35%、不循環、壓低）", panel.volume_spin.value() == 35
          and not panel.loop_box.isChecked() and panel.duck_box.isChecked())
    panel.volume_spin.setValue(80)
    check("改音量：寫回素材（0.8）", panel.tracks["music"][0]["volume"] == 0.8, str(panel.tracks["music"][0]))
    panel.duck_box.setChecked(False)
    check("取消壓低：寫回素材", panel.tracks["music"][0]["duck"] is False)
    panel.loop_box.setChecked(True)
    check("勾循環：寫回素材、時間軸上一路到片尾",
          panel.tracks["music"][0]["loop"] is True and tv.track_span("music", 0) == (3.5, panel.media_duration()),
          str(tv.track_span("music", 0)))
    check("方塊上寫音量與循環", any("音量 80%" in c.text() and "循環" in c.text()
                                 for c in tv.track_items["music"][0].childItems() if hasattr(c, "text")))
    errors.clear()
    check("不合理的值不收、說明、畫面照舊", panel.set_track_props(volume=5) is False
          and panel.tracks["music"][0]["volume"] == 0.8 and errors and "volume" in errors[-1]
          and panel.volume_spin.value() == 80, str(errors))
    errors.clear()

    tv.select_track_item("overlays", 0, seek=False)
    check("換選畫面：那一行換成畫面的、照素材填", shown(overlay_w) and hidden(music_w)
          and panel.position_combo.currentData() == "top_right")
    check("填的時候不送出修改（音樂沒被改到）", panel.tracks["music"][0]["volume"] == 0.8
          and panel.tracks["overlays"][0].get("rect") == assemble.position_rect("top_right"))
    # 選單停在「右上小畫面」時再加一段（沒設位置的）畫面：填值把選單拉回「蓋滿」，不能順手
    # 把 rect 寫進新的那段
    panel.add_track("overlays", logo)
    fresh = panel.tracks["overlays"][1]
    check("換選到另一段畫面：選單照它填（蓋滿），它本身沒被改",
          panel.position_combo.currentData() == "full" and "rect" not in fresh
          and fresh == {"path": logo, "at": fresh["at"], "duration": 3.0}, str(fresh))
    panel.remove_track("overlays", 1)
    tv.select_track_item("overlays", -1, seek=False)
    check("取消選取：回到說明", panel.prop_label.text() == player_mod.PROP_HINT
          and hidden(music_w) and hidden(overlay_w))

    # 在面板的時間軸上修頭尾：面板的資料跟著改
    tv.set_zoom(100, 0, 0)
    tvp = tv.viewport()

    def tpx(sec):
        return int(round(sec * tv.px_per_sec)) - tv.horizontalScrollBar().value()

    panel.player.setPosition(0)
    wait_until(lambda: tv.position_ms == 0, 5000)
    QTest.mousePress(tvp, Qt.LeftButton, Qt.NoModifier, QPoint(tpx(3.5) - 1, OV_Y))
    QTest.mouseMove(tvp, QPoint(tpx(4.0), OV_Y))
    QTest.mouseMove(tvp, QPoint(tpx(4.2) - 1, OV_Y))
    QTest.mouseRelease(tvp, Qt.LeftButton, Qt.NoModifier, QPoint(tpx(4.2) - 1, OV_Y))
    check("在面板的時間軸上拖圖片的尾巴：面板的資料跟著改（0.5～4.2 秒）",
          panel.tracks["overlays"][0]["duration"] == 3.7 and panel.tracks["overlays"][0]["at"] == 0.5
          and panel.tracks["overlays"][0].get("rect") == assemble.position_rect("top_right"),
          str(panel.tracks["overlays"][0]))
    check("修完還是選取著、屬性那一行是它", tv.track_selected == ("overlays", 0) and shown(overlay_w))

    # ----- 3. 輸出 -----
    out = os.path.join(tmp, "成品.mp4")
    panel.export_tracks(out)
    check("輸出中：屬性那一行灰掉", not panel.position_combo.isEnabled())
    check("輸出中：改屬性不做事", panel.set_track_props(rect=assemble.position_rect("full")) is False
          and panel.tracks["overlays"][0]["rect"] == assemble.position_rect("top_right"))
    wait_until(lambda: not panel.track_exporter.busy, 120000)
    wait(100)
    check("輸出成功", panel.last_assemble is not None and errors == [], f"{panel.last_assemble} {errors}")
    check("輸出完屬性那一行恢復", panel.position_combo.isEnabled())

    def pixel(t, x, y):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", out, "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        i = (y * 640 + x) * 3
        return tuple(raw[i:i + 3])

    top_right, bottom_left, center = pixel(2.0, 520, 60), pixel(2.0, 100, 300), pixel(2.0, 320, 180)
    check("右上小畫面：右上角是紅色", top_right[0] > 200 and top_right[1] < 60, str(top_right))
    check("右上小畫面：左下角與中間還是原片的灰",
          all(100 < c < 160 for c in bottom_left + center), f"{bottom_left} {center}")
    after = pixel(4.8, 520, 60)
    check("修過尾巴：4.2 秒之後右上角回到灰", all(100 < c < 160 for c in after), str(after))

    def tone_db(start, length):
        done = subprocess.run(["ffmpeg", "-v", "info", "-ss", str(start), "-t", str(length), "-i", out,
                               "-af", "highpass=f=700,highpass=f=700,highpass=f=700,highpass=f=700,volumedetect",
                               "-vn", "-f", "null", "-"], capture_output=True, text=True)
        found = re.search(r"mean_volume:\s*(-?[\d.]+|-inf) dB", done.stderr)
        return float(found.group(1)) if found and found.group(1) != "-inf" else -200.0

    late, early = tone_db(5.2, 0.7), tone_db(1.0, 2.0)
    check("循環的音樂放到片尾（原本 1.5 秒、3.5 秒開始，5 秒之後還聽得到）", late - early > 20,
          f"{late} {early}")
    panel.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 素材修頭尾與屬性測試全數通過。")
