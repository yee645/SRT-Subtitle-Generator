# -*- coding: utf-8 -*-
"""
3.0 第 7 項第四階段：播放器上預覽疊加軌。

擺法的算式在 test_assemble.py（overlay_box／fit_inside／overlays_at）；這裡驗畫出來的樣子：

1. 預覽層本身（假的抽格程式，控制什麼時候抽好）：抽好之前畫黑框寫檔名；抽好了換成
   那一格、等比置中；抽不到不重試；疊在影片上、字幕底下；關掉時背景執行緒停下。
2. 播放器面板：
   - 圖片照輸出的位置出現在它的那幾秒，之前之後都沒有；換位置、改大小視窗跟著動。
   - **跟真的輸出比**：同一刻，預覽畫面裡紅色那塊的位置與大小（以影片畫面為準的比例）
     跟輸出檔那一格的紅色那塊差不到 1.5%。
   - 影片素材：顯示的是素材「這一刻」的那一格（前 2 秒藍、後 2 秒綠，量顏色）；換格前先
     顯示上一格（不閃黑框）；後加的疊在上面。
   - 關掉「預覽畫面素材」全部拿掉、那一行不寫預覽；打開又回來。
"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading

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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過疊加預覽（算式在 test_assemble.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QBuffer, QByteArray, QEventLoop, QIODevice, QRectF, QTimer  # noqa: E402
    from PySide6.QtGui import QColor, QImage  # noqa: E402
    from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsSimpleTextItem  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import overlay_preview as op  # noqa: E402
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

    def wait_until(cond, timeout_ms=30000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(50)
            waited += 50
        return cond()

    def run(*args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)

    def png_bytes(color, w=160, h=90):
        image = QImage(w, h, QImage.Format_RGB32)
        image.fill(QColor(color))
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.WriteOnly)
        image.save(buf, "PNG")
        return bytes(data)

    # ----- 1. 預覽層本身 -----
    gate = threading.Event()
    calls = []

    def slow_grabber(path, seconds):
        calls.append((os.path.basename(path), seconds))
        gate.wait(10)
        # 直的畫面放進橫的框：有沒有等比縮放、置中一看就知道（16:9 的畫面跟框幾乎同比例，看不出來）
        return b"" if "broken" in path else png_bytes("#00ff00", 90, 160)

    scene = QGraphicsScene()
    scene.setSceneRect(0, 0, 640, 360)
    pre = op.OverlayPreview(scene, grabber=slow_grabber)
    updates = []
    pre.updated.connect(lambda: updates.append(1))
    area = QRectF(0, 0, 640, 360)
    clip = {"path": os.path.join(tmp, "clip.mp4"), "at": 1.0, "in": 2.0, "out": 6.0,
            "rect": assemble.position_rect("bottom_left")}
    pre.show([clip], 2.6, 10, area, (1280, 720))
    labels = [c for it in pre.items for c in it.childItems() if isinstance(c, QGraphicsSimpleTextItem)]
    check("影片素材還沒抽好：畫黑框、寫檔名與正在載入", len(pre.items) == 1 and pre.shown == [(0, None)]
          and labels and "clip.mp4（正在載入預覽…）" == labels[0].text(), str(pre.shown))
    bx, by, bw, bh = assemble.overlay_box(clip["rect"], 1280, 720)
    check("框的位置：照輸出的畫布（1280x720）算、再縮到畫面上（一半）",
          pre.items[0].rect() == QRectF(bx / 2, by / 2, bw / 2, bh / 2), str(pre.items[0].rect()))
    check("抽的是素材這一刻往下取整秒（進點 2＋過了 1.6 秒＝第 3.6 秒 → 第 3 秒那格）",
          wait_until(lambda: calls == [("clip.mp4", 3.0)], 3000), str(calls))
    check("疊在影片上、字幕底下", 0 < pre.items[0].zValue() < 1)
    pre.show([clip], 2.7, 10, area, (1280, 720))
    check("同一格還沒抽好：不重複要", calls == [("clip.mp4", 3.0)] and pre.shown == [(0, None)])
    gate.set()
    check("抽好了：送出 updated", wait_until(lambda: updates, 5000))
    pre.show([clip], 2.7, 10, area, (1280, 720))
    pics = [c for it in pre.items for c in it.childItems() if not isinstance(c, QGraphicsSimpleTextItem)]
    check("抽好了：換成那一格（不再寫載入中）", pre.shown == [(0, (clip["path"], 3.0))] and len(pics) == 1)
    # 90x160 的格放進 bw/2 x bh/2 的框：等比、置中（左右補黑）
    fx, fy, fw, fh = assemble.fit_inside(90, 160, bw / 2, bh / 2)
    got = pics[0].boundingRect().translated(pics[0].pos())
    check("那一格在框裡等比縮放、置中（直的畫面左右留黑）",
          fx > 20 and abs(got.x() - (bx / 2 + fx)) < 1 and abs(got.y() - (by / 2 + fy)) < 1
          and abs(got.width() - fw) < 1.5 and abs(got.height() - fh) < 1.5, f"{got} {(fx, fy, fw, fh)}")
    gate.clear()
    pre.show([clip], 4.1, 10, area, (1280, 720))  # 第 5.1 秒 → 第 5 秒那格，還沒抽好
    check("換格時先顯示上一格（不閃黑框）", pre.shown == [(0, (clip["path"], 3.0))], str(pre.shown))
    gate.set()
    wait_until(lambda: len(updates) >= 2, 5000)
    broken = dict(clip, path=os.path.join(tmp, "broken.mp4"))
    n = len(calls)
    pre.show([broken], 1.5, 10, area, (1280, 720))
    wait_until(lambda: len(updates) >= 3, 5000)
    pre.show([broken], 1.6, 10, area, (1280, 720))
    pre.show([broken], 1.7, 10, area, (1280, 720))
    wait(200)
    check("抽不到：照舊畫黑框寫檔名、不重試", len(calls) == n + 1 and pre.shown == [(0, None)], str(calls[n:]))
    pre.show([clip], 0.5, 10, area, (1280, 720))
    check("還沒到它的時間：什麼都不畫", pre.items == [] and not [i for i in scene.items() if i.zValue() == op.Z_VALUE])
    pre.show([clip], 2.7, 10, area, (1280, 720), enabled=False)
    check("關掉預覽：什麼都不畫", pre.items == [])
    pre.stop()
    check("stop：背景執行緒停下", not pre._thread.is_alive())

    # ----- 2. 播放器面板 -----
    main = os.path.join(tmp, "main.mp4")
    run("-f", "lavfi", "-i", "color=c=0x808080:size=640x360:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=150:sample_rate=48000", "-t", "6",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", main)
    logo = os.path.join(tmp, "logo.png")
    run("-f", "lavfi", "-i", "color=c=red:size=320x180", "-frames:v", "1", logo)
    broll = os.path.join(tmp, "broll.mp4")  # 前 2 秒藍、後 2 秒綠
    run("-f", "lavfi", "-i", "color=c=blue:size=320x240:rate=30:d=2", "-f", "lavfi",
        "-i", "color=c=green:size=320x240:rate=30:d=2", "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]",
        "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", broll)

    win = qt_app.MainWindow({"subtitle_style": {}})
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 900)
    win.show()
    panel = win.player_panel
    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0 and not panel.video_item.nativeSize().isEmpty(), 20000)
    wait(200)

    def seek(ms):
        panel.player.setPosition(ms)
        wait_until(lambda: panel.player.position() == ms, 5000)
        wait(100)

    seek(500)
    panel.add_track("overlays", logo)
    panel.set_track_props(rect=assemble.position_rect("top_right"))
    seek(1000)
    vr = panel._video_rect()

    def view_pixel(fx, fy):
        """影片畫面裡 (fx, fy)（0～1 的比例）那一點的顏色。"""
        img = panel.view.viewport().grab().toImage()
        return QColor(img.pixel(int(vr.x() + fx * vr.width()), int(vr.y() + fy * vr.height()))).getRgb()[:3]

    def red(rgb):
        return rgb[0] > 200 and rgb[1] < 60 and rgb[2] < 60

    def grey(rgb):
        return all(100 < c < 160 for c in rgb)

    check("圖片在它的時間出現（一個框）", len(panel.overlay_preview.items) == 1)
    check("右上小畫面：右上角是紅色、左下角與中間是原片的灰",
          red(view_pixel(0.79, 0.2)) and grey(view_pixel(0.2, 0.8)) and grey(view_pixel(0.5, 0.5)),
          f"{view_pixel(0.79, 0.2)} {view_pixel(0.2, 0.8)}")
    check("字幕在預覽素材上面", panel.subtitle_item.zValue() > max(i.zValue() for i in panel.overlay_preview.items))

    def red_box_view():
        img = panel.view.viewport().grab().toImage()
        xs, ys = [], []
        for y in range(int(vr.y()), int(vr.y() + vr.height()), 2):
            for x in range(int(vr.x()), int(vr.x() + vr.width()), 2):
                if red(QColor(img.pixel(x, y)).getRgb()[:3]):
                    xs.append(x)
                    ys.append(y)
        return ((min(xs) - vr.x()) / vr.width(), (min(ys) - vr.y()) / vr.height(),
                (max(xs) - vr.x()) / vr.width(), (max(ys) - vr.y()) / vr.height()) if xs else None

    preview_box = red_box_view()
    out = os.path.join(tmp, "成品.mp4")
    panel.export_tracks(out)
    wait_until(lambda: not panel.track_exporter.busy, 120000)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1.0", "-i", out, "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    xs, ys = [], []
    for y in range(0, 360, 2):
        for x in range(0, 640, 2):
            i = (y * 640 + x) * 3
            if red(tuple(raw[i:i + 3])):
                xs.append(x)
                ys.append(y)
    output_box = (min(xs) / 640, min(ys) / 360, max(xs) / 640, max(ys) / 360) if xs else None
    check("跟真的輸出比：紅色那塊的位置與大小差不到 1.5%",
          preview_box and output_box and all(abs(a - b) < 0.015 for a, b in zip(preview_box, output_box)),
          f"預覽 {preview_box} 輸出 {output_box}")
    print("  預覽", preview_box, "輸出", output_box)

    seek(4000)
    check("過了它的時間：拿掉", panel.overlay_preview.items == [] and grey(view_pixel(0.79, 0.2)))
    seek(1000)
    panel.timeline.select_track_item("overlays", 0, seek=False)
    panel.set_track_props(rect=assemble.position_rect("bottom_left"))
    check("換位置：預覽跟著換（左下紅、右上灰）", red(view_pixel(0.2, 0.8)) and grey(view_pixel(0.79, 0.2)))
    old_rect = panel.overlay_preview.items[0].rect()
    win.resize(1000, 860)
    wait_until(lambda: panel.overlay_preview.items and panel.overlay_preview.items[0].rect() != old_rect, 3000)
    vr = panel._video_rect()
    bx, by, bw, bh = assemble.overlay_box(assemble.position_rect("bottom_left"), 640, 360)
    got = panel.overlay_preview.items[0].rect()
    sx = vr.width() / 640
    check("視窗改大小：框跟著影片畫面縮放",
          abs(got.x() - (vr.x() + bx * sx)) < 1 and abs(got.width() - bw * sx) < 1, f"{got} {vr}")

    # 影片素材：這一刻的那一格
    seek(2000)
    panel.add_track("overlays", broll)  # 2～6 秒、蓋滿
    seek(2500)  # 素材第 0.5 秒 → 藍
    check("影片素材：顯示這一刻的那一格（素材前 2 秒是藍）",
          wait_until(lambda: view_pixel(0.5, 0.5)[2] > 200 and view_pixel(0.5, 0.5)[0] < 60, 10000),
          str(view_pixel(0.5, 0.5)))
    check("後加的疊在上面（圖片被蓋住、左下也是藍）", view_pixel(0.2, 0.8)[2] > 200, str(view_pixel(0.2, 0.8)))
    seek(4500)  # 素材第 2.5 秒 → 綠
    check("換到素材後半：變綠", wait_until(lambda: view_pixel(0.5, 0.5)[1] > 100 and view_pixel(0.5, 0.5)[2] < 60,
                                       10000), str(view_pixel(0.5, 0.5)))

    panel.preview_box.setChecked(False)
    check("關掉「預覽畫面素材」：全部拿掉、那一行不寫預覽",
          panel.overlay_preview.items == [] and grey(view_pixel(0.5, 0.5))
          and "預覽" not in panel.track_label.text(), panel.track_label.text())
    panel.preview_box.setChecked(True)
    check("再打開：回來", len(panel.overlay_preview.items) == 1 and "預覽" in panel.track_label.text())
    panel.open_video(main)
    check("換片子：預覽清掉", panel.overlay_preview.items == [])
    wait_until(lambda: panel.player.duration() > 0, 20000)
    panel.shutdown()
    check("關視窗：預覽的背景執行緒停下", not panel.overlay_preview._thread.is_alive())
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 播放器疊加預覽測試全數通過。")
