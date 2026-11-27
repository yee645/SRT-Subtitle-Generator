# -*- coding: utf-8 -*-
"""
剪輯器版面 E-8c：拖檔案到時間軸時的落點預覽（gui_qt/timeline.py 的 show_drop_preview；規則在 test_drop_plan.py）。

1. 拖進來（還沒放）：落點畫一條直線（強調色），會放上去的軌道各一個標籤「＋N 個（從 0:06.0）」；狀態列講會怎麼放；
   時間軸上的素材還沒變。
2. 拖著移動：標籤跟著換列、換秒數；同一個落點不重畫。
3. 這一列不收（聲音拖到疊加列、圖片拖到音樂列）：在那一列畫紅色標籤寫原因；收得了的照樣畫在它們要去的軌道。
4. 拖走（離開時間軸）或放下：預覽全部拿掉、狀態列清掉；放下後照預覽放（同一套規則）。
5. 沒開影片：不接、不畫。
6. 標籤的顏色取色票（強調色＋強調色上的字；放不了用剪點色＋方塊上的字），深淺兩色都是。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過拖曳落點預覽（規則在 test_drop_plan.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QMimeData, QPointF, Qt, QTimer, QUrl  # noqa: E402
    from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent  # noqa: E402
    from PySide6.QtWidgets import QApplication, QGraphicsLineItem, QGraphicsPathItem  # noqa: E402

    import config  # noqa: E402
    from gui_qt import editor as ed  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import designtokens  # noqa: E402

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
    broll = os.path.join(tmp, "broll.mp4")
    still = os.path.join(tmp, "logo.png")
    song = os.path.join(tmp, "song.m4a")
    run("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-f", "lavfi", "-i", "sine=frequency=440",
        "-t", "12", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", main)
    run("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-t", "2", "-pix_fmt", "yuv420p", "-c:v", "libx264",
        broll)
    run("-f", "lavfi", "-i", "testsrc2=size=160x90", "-frames:v", "1", still)
    run("-f", "lavfi", "-i", "sine=frequency=220", "-t", "3", "-c:a", "aac", song)

    def make(theme):
        cfg = copy.deepcopy(config.DEFAULT_CONFIG)
        cfg["theme"] = theme
        ed.apply_initial_theme(app, theme)
        win = ed.EditorWindow(cfg)
        win.resize(1440, 900)
        win.show()
        wait(80)
        p = win.player_panel
        p._ask_discard = lambda *a, **k: "discard"
        p._ask_project_discard = lambda *a, **k: "discard"
        p._show_track_error = lambda msg: None
        return win, p

    keep = []  # 事件只拿 QMimeData 的指標：留著參照，別讓 Python 先回收（不然會當掉）

    def mime(files):
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(f) for f in files])
        keep.append(data)
        return data

    def point(t, row, seconds):
        x = seconds * t.px_per_sec - t.horizontalScrollBar().value()
        y = t.row_y[row] + t.row_h[row] / 2 - t.verticalScrollBar().value()
        return QPointF(x, y)

    def enter(t, files, row, seconds):
        ev = QDragEnterEvent(point(t, row, seconds).toPoint(), Qt.CopyAction, mime(files), Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(t.viewport(), ev)
        return ev.isAccepted()

    def move(t, files, row, seconds):
        ev = QDragMoveEvent(point(t, row, seconds).toPoint(), Qt.CopyAction, mime(files), Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(t.viewport(), ev)
        return ev.isAccepted()

    def leave(t):
        QApplication.sendEvent(t.viewport(), QDragLeaveEvent())

    def drop(t, files, row, seconds):
        ev = QDropEvent(point(t, row, seconds), Qt.CopyAction, mime(files), Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(t.viewport(), ev)
        wait(30)
        return ev.isAccepted()

    def line_x(t):
        """直線落在第幾秒（量到一個像素：滑鼠座標是整數像素）。"""
        lines = [i for i in t.drop_items if isinstance(i, QGraphicsLineItem)]
        return [round(round(i.line().x1() / t.px_per_sec * 10) / 10, 1) for i in lines]

    win, p = make("dark")
    t = p.timeline
    status = win.statusBar()

    # ----- 5 -----
    check("沒開影片：不接、不畫", not enter(t, [still], "overlays", 1.0) and t.drop_items == [])

    p.open_video(main)
    check("（準備）開好影片", wait_until(lambda: p.media_duration() > 0 and t.duration > 0))
    wait(30)

    # ----- 1 -----
    check("拖進來：接受", enter(t, [still, broll], "overlays", 6.0))
    chips = t.drop_chips()
    check("落點一條直線在 6 秒", line_x(t) == [6.0], str(line_x(t)))
    check("疊加列一個標籤「＋2 個（從 0:06.0）」", chips == [("overlays", "accept", "＋2 個（從 0:06.0）")], str(chips))
    check("狀態列講會怎麼放", status.currentMessage() == "放到疊加 2 個", status.currentMessage())
    check("還沒放：素材軌沒變", p.tracks["overlays"] == [] and p.tracks["music"] == [])

    # ----- 2 -----
    check("拖著移動到字幕列 2 秒（照種類放）", move(t, [still, song], "cues", 2.0))
    chips = sorted(t.drop_chips())
    check("標籤換到疊加與音樂各一個、從 2 秒", chips == [("music", "accept", "＋1 個（從 0:02.0）"),
                                                ("overlays", "accept", "＋1 個（從 0:02.0）")] and line_x(t) == [2.0],
          f"{chips} {line_x(t)} {t.px_per_sec}")
    check("狀態列跟著換", status.currentMessage() == "放到疊加 1 個、音樂 1 個", status.currentMessage())
    before = list(t.drop_items)
    move(t, [still, song], "cues", 2.0)
    check("同一個落點不重畫", t.drop_items == before)
    move(t, [still, song], "cues", 3.0)
    check("換秒數就重畫（舊的拿掉、不會越畫越多）", t.drop_items != before and len(t.drop_items) == 3
          and all(i.scene() is None for i in before) and line_x(t) == [3.0])

    # ----- 3 -----
    move(t, [song, still], "overlays", 4.0)
    chips = t.drop_chips()
    check("聲音拖到疊加列：疊加列先畫收得了的、再畫紅色的原因", [c[:2] for c in chips] == [("overlays", "accept"), ("overlays", "refuse")]
          and chips[1][2].startswith("疊加列放不了：song.m4a"), str(chips))
    accept, refuse = [i for i in t.drop_items if isinstance(i, QGraphicsPathItem)]
    check("紅色標籤排在收得了的右邊、不疊在一起",
          refuse.boundingRect().left() >= accept.boundingRect().right(), f"{accept.boundingRect()} {refuse.boundingRect()}")
    check("狀態列講兩件事", status.currentMessage().startswith("放到疊加 1 個；疊加列放不了：song.m4a"), status.currentMessage())
    move(t, [still], "music", 4.0)
    chips = t.drop_chips()
    check("圖片拖到音樂列：只有紅色的", chips and all(c[1] == "refuse" for c in chips) and chips[0][0] == "music"
          and "音樂列放不了：logo.png" in chips[0][2], str(chips))
    check("狀態列只講放不了", status.currentMessage().startswith("音樂列放不了：logo.png"), status.currentMessage())

    # ----- 4 -----
    leave(t)
    check("拖走：預覽全部拿掉、狀態列清掉", t.drop_items == [] and t.drop_chips() == [] and status.currentMessage() == "")
    check("拖走：素材軌沒變", p.tracks["overlays"] == [] and p.tracks["music"] == [])
    enter(t, [still, song], "overlays", 5.0)
    check("（再拖一次）有預覽", len(t.drop_chips()) == 2)
    check("放下：接受", drop(t, [still, song], "overlays", 5.0))
    check("放下：預覽拿掉", t.drop_items == [] and t.drop_chips() == [])
    check("照預覽放：圖片從 5 秒放疊加、聲音沒放", [round(i["at"], 1) for i in p.tracks["overlays"]] == [5.0]
          and p.tracks["music"] == [], str(p.tracks))
    check("放下之後狀態列寫為什麼有的沒放（跟預覽同一句）", "疊加列放不了：song.m4a" in p.track_label.text(), p.track_label.text())

    # ----- 6 -----
    for theme in ("dark", "light"):
        w, pp = (win, p) if theme == "dark" else make("light")
        if theme == "light":
            pp.open_video(main)
            wait_until(lambda: pp.media_duration() > 0 and pp.timeline.duration > 0)
        tt = pp.timeline
        enter(tt, [still, song], "overlays", 3.0)
        tok = designtokens.TOKENS[theme]
        paths = [i for i in tt.drop_items if isinstance(i, QGraphicsPathItem)]
        line = [i for i in tt.drop_items if isinstance(i, QGraphicsLineItem)][0]
        colors = [(i.data(0), i.brush().color().name(), i.childItems()[0].brush().color().name()) for i in paths]
        check(f"{theme}：標籤用色票（強調色／放不了用剪點色）", colors == [
            ("accept", tok["accent"], tok["accent.text"]), ("refuse", tok["track.cut"], tok["track.text"])]
              and line.pen().color().name() == tok["accent"], str(colors))
        leave(tt)
        if theme == "light":
            pp.shutdown()
            w.close()

    p.shutdown()
    win.close()
    wait(50)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("拖曳落點預覽（E-8c）介面測試全數通過。")
