# -*- coding: utf-8 -*-
"""
3.0 第 9 項第四階段：裁切（主片與疊加素材）。

濾鏡（`crop`）與取整（`crop_box`／`output_size`）在 test_picture.py；這裡驗：

1. 換算：「四邊各裁幾 %」與 [x, y, w, h] 互換；`item_geometry` 把裁切範圍的四個角剛好放到
   畫面矩形的四個角（含轉 90 度、翻）。`apply_to_image` 照 `crop_box` 裁。
2. 播放器：
   - 小視窗裡調四邊，畫面只露出裁切那一塊，比例跟著變，外面是黑的。
   - 裁完再轉。
   - 裁太小不收，說原因，數字放回去。
   - 字幕擺在裁完的畫面裡。
   - 那一行寫裁成多少。
3. 輸出：
   - 大小照 `output_size`，顏色跟預覽一樣。
   - 疊加素材裁切後，預覽與成品都只剩那一塊。
   - 主片轉成直的時，疊加素材的框照直的畫布擺，預覽與成品位置一樣。
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

if PySide6 is None or not shutil.which("ffmpeg"):
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過裁切（核心在 test_picture.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QPointF, QRectF, QSizeF, QTimer  # noqa: E402
    from PySide6.QtGui import QColor, QImage  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import picture_panel as pn  # noqa: E402
    from gui_qt import picture_preview as pp  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import assemble, picture  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = tmp
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait_until(cond, timeout_ms=20000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(20)
            waited += 20
        return cond()

    def run(*args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)

    def near(rgb, want, tol=40):
        return all(abs(a - b) <= tol for a, b in zip(rgb, want))

    RED, BLUE, GREEN, WHITE, BLACK, MAGENTA = ((255, 0, 0), (0, 0, 255), (0, 255, 0), (255, 255, 255),
                                               (0, 0, 0), (255, 0, 255))

    # ----- 1. 換算 -----
    sides = {"left": 10, "top": 20, "right": 30, "bottom": 5}
    crop = pn.crop_from_sides(10, 20, 30, 5)
    check("四邊各裁幾 % → [x, y, w, h]，再換回來一樣",
          [round(v, 4) for v in crop] == [0.1, 0.2, 0.6, 0.75] and pn.sides_from_crop(crop) == sides, str(crop))
    native = QSizeF(640, 360)
    worst = 0.0
    for adj in ({"crop": [0.25, 0.1, 0.5, 0.6]}, {"crop": [0.25, 0.1, 0.5, 0.6], "rotate": 90},
                {"crop": [0.0, 0.5, 0.4, 0.5], "rotate": 270, "flip_h": True}, {"rotate": 180, "flip_v": True},
                {}):
        target = pp.fitted_rect(QSizeF(1000, 600), pp.display_size(adj, native))
        size, transform = pp.item_geometry(adj, native, target)
        x, y, w, h = picture.normalize(adj)["crop"]
        corners = [transform.map(QPointF(cx * size.width(), cy * size.height()))
                   for cx in (x, x + w) for cy in (y, y + h)]
        want = [target.topLeft(), target.topRight(), target.bottomLeft(), target.bottomRight()]
        for c in corners:
            worst = max(worst, min(abs(c.x() - t.x()) + abs(c.y() - t.y()) for t in want))
        if sorted((round(c.x()), round(c.y())) for c in corners) != sorted((round(t.x()), round(t.y())) for t in want):
            worst = max(worst, 99.0)
    check(f"item_geometry：裁切範圍的四個角剛好落在畫面矩形的四個角（五種組合，最多差 {worst:.3f}px）",
          worst < 0.01)
    check("display_size：裁一半寬、轉 90 度 → 360x320",
          pp.display_size({"crop": [0, 0, 0.5, 1], "rotate": 90}, native) == QSizeF(360, 320))

    quad_inputs = []
    for c in ("red", "blue", "0x00ff00", "white"):
        quad_inputs += ["-f", "lavfi", "-i", f"color=c={c}:size=320x180:rate=30:d=8"]
    quad_filter = "[0:v][1:v]hstack[t];[2:v][3:v]hstack[b];[t][b]vstack[v]"
    quad_png = os.path.join(tmp, "四色.png")
    run(*quad_inputs, "-filter_complex", quad_filter, "-map", "[v]", "-frames:v", "1", quad_png)
    img = QImage(quad_png)
    cut = pp.apply_to_image(img, {"crop": [0.5, 0.5, 0.5, 0.5]})
    box = picture.crop_box({"crop": [0.5, 0.5, 0.5, 0.5]}, img.width(), img.height())
    check("apply_to_image 裁右下四分之一：大小照 crop_box、整張是白",
          (cut.width(), cut.height()) == box[2:] and all(
              near(QColor(cut.pixel(int(cut.width() * f), int(cut.height() * g))).getRgb()[:3], WHITE)
              for f in (0.05, 0.95) for g in (0.05, 0.95)), f"{cut.width()}x{cut.height()} {box}")

    # ----- 2. 播放器 -----
    quad = os.path.join(tmp, "quad.mp4")
    run(*quad_inputs, "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:d=8",
        "-filter_complex", quad_filter, "-map", "[v]", "-map", "4:a", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv444p", "-c:a", "aac", quad)
    win = qt_app.MainWindow({"subtitle_style": {}})
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 860)
    win.show()
    panel = win.player_panel
    errors = []
    panel._show_track_error = errors.append
    panel.open_video(quad)
    wait_until(lambda: panel.player.duration() > 0)
    panel.player.setPosition(1000)
    wait_until(lambda: abs(panel.player.position() - 1000) < 50, 5000)
    wait(300)
    panel.set_cues([{"start": 0.5, "end": 3.0, "text": "裁切之後字幕也在畫面裡"}])
    full = panel._video_rect()
    dialog = panel.show_picture_dialog()
    wait(50)
    check("小視窗有四邊的裁切（左上右下、預設 0%）",
          [dialog.crop_spins[k].value() for k, _l in pn.CROP_SIDES] == [0, 0, 0, 0]
          and all(dialog.crop_spins[k].isVisible() for k, _l in pn.CROP_SIDES))

    def grab():
        return panel.view.viewport().grab().toImage()

    def view_pixel(fx, fy, image=None):
        vr = panel._video_rect()
        image = image or grab()
        return QColor(image.pixel(int(vr.x() + fx * vr.width()), int(vr.y() + fy * vr.height()))).getRgb()[:3]

    def outside_black():
        """畫面矩形左右（或上下）外面 4px 是黑的：裁掉的部分沒有露出來。"""
        vr, image = panel._video_rect(), grab()
        spots = []
        if vr.left() > 6:
            spots += [(vr.left() - 4, vr.center().y()), (vr.right() + 4, vr.center().y())]
        if vr.top() > 6:
            spots += [(vr.center().x(), vr.top() - 4), (vr.center().x(), vr.bottom() + 4)]
        return bool(spots) and all(max(QColor(image.pixel(int(x), int(y))).getRgb()[:3]) < 30 for x, y in spots)

    dialog.crop_spins["right"].setValue(50)
    wait(200)
    vr = panel._video_rect()
    check("裁掉右邊 50%：記成 [0, 0, 0.5, 1]、畫面比例變 320:360",
          panel.main_adjust == {"crop": [0.0, 0.0, 0.5, 1.0]} and abs(vr.width() / vr.height() - 320 / 360) < 0.01
          and abs(vr.height() - full.height()) < 1, f"{panel.main_adjust} {vr}")
    seen = [view_pixel(0.5, 0.25), view_pixel(0.5, 0.75), view_pixel(0.05, 0.05), view_pixel(0.95, 0.95)]
    check("只露出左半：上紅下綠（四個角也是），右半的藍、白沒露出來，外面是黑的",
          near(seen[0], RED) and near(seen[1], GREEN) and near(seen[2], RED) and near(seen[3], GREEN)
          and outside_black(), str(seen))
    dialog.crop_spins["bottom"].setValue(50)
    wait(200)
    vr = panel._video_rect()
    corners = [view_pixel(fx, fy) for fx in (0.03, 0.97) for fy in (0.03, 0.97)]
    check("再裁掉下面 50%：只剩左上的紅（四個角都紅），比例回到 16:9",
          all(near(c, RED) for c in corners) and abs(vr.width() / vr.height() - 16 / 9) < 0.01, str(corners))
    dialog.crop_spins["bottom"].setValue(0)
    dialog.rotate_combo.setCurrentIndex(dialog.rotate_combo.findData(90))
    wait(200)
    vr = panel._video_rect()
    check("裁左半再順時針轉 90 度：比例 360:320、左邊綠右邊紅（同 ffmpeg 先裁再轉）",
          abs(vr.width() / vr.height() - 360 / 320) < 0.01 and near(view_pixel(0.25, 0.5), GREEN)
          and near(view_pixel(0.75, 0.5), RED) and outside_black(), f"{vr} {view_pixel(0.25, 0.5)}")
    sub = panel.subtitle_item.sceneBoundingRect()
    check("字幕擺在裁完、轉完的畫面裡", panel.subtitle_item.isVisible()
          and abs(sub.center().x() - vr.center().x()) < 3 and vr.top() < sub.center().y() < vr.bottom(),
          f"{sub} {vr}")
    check("那一行寫裁成多少", "裁成原畫面的 50%×100%" in panel.track_label.text(), panel.track_label.text())

    dialog.crop_spins["left"].setValue(60)
    wait(100)
    check("裁太小（左 60%＋右 50%）：不收、說原因、數字放回 0",
          panel.main_adjust == {"crop": [0.0, 0.0, 0.5, 1.0], "rotate": 90} and dialog.crop_spins["left"].value() == 0
          and errors and "裁切" in errors[-1], f"{panel.main_adjust} {errors}")
    errors.clear()

    # ----- 3. 輸出 -----
    def probe_size(path):
        return subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                               "stream=width,height", "-of", "csv=p=0", path], capture_output=True, text=True
                              ).stdout.strip()

    def out_pixel(path, fx, fy, t=1.0):
        w, h = (int(v) for v in probe_size(path).split(","))
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1",
                              "-vf", f"crop=6:6:{max(0, int(w * fx) - 3)}:{max(0, int(h * fy) - 3)},scale=1:1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        return tuple(raw[:3])

    made = os.path.join(tmp, "裁切.mp4")
    check("只調畫面輸出多軌：開始", panel.export_tracks(made) is True, str(errors))
    wait_until(lambda: not panel.track_exporter.busy, 120000)
    wait(100)
    want = picture.output_size(panel.main_adjust, 640, 360)
    check(f"成品大小照 output_size（{want[0]}x{want[1]}）、左綠右紅（跟預覽一樣）",
          probe_size(made) == f"{want[0]},{want[1]}" and near(out_pixel(made, 0.25, 0.5), GREEN)
          and near(out_pixel(made, 0.75, 0.5), RED), f"{probe_size(made)} {out_pixel(made, 0.25, 0.5)}")

    # 疊加素材裁切：主片只轉 90 度（畫布是直的），疊一張右上小畫面
    dialog.reset_btn.click()
    dialog.rotate_combo.setCurrentIndex(dialog.rotate_combo.findData(90))
    wait(100)
    panel.player.setPosition(500)
    wait(200)
    check("加入疊加圖片", panel.add_track("overlays", quad_png))
    panel.set_track_props(rect=assemble.position_rect("top_right"))
    panel.overlay_picture_btn.click()
    check("小視窗改調疊加素材", dialog.target == ("overlays", 0))
    dialog.crop_spins["left"].setValue(50)
    dialog.crop_spins["top"].setValue(50)
    wait(100)
    panel.player.setPosition(1000)
    wait(300)
    check("疊加素材記下裁切（右下四分之一），主片只有轉", panel.tracks["overlays"][0].get("adjust")
          == {"crop": [0.5, 0.5, 0.5, 0.5]} and panel.main_adjust == {"rotate": 90}, str(panel.tracks["overlays"][0]))

    def white_box(image, x0, y0, w, h, step=2):
        xs, ys = [], []
        for yy in range(int(y0), int(y0 + h), step):
            for xx in range(int(x0), int(x0 + w), step):
                if near(QColor(image.pixel(xx, yy)).getRgb()[:3] if isinstance(image, QImage) else image(xx, yy),
                        WHITE, 30):
                    xs.append(xx)
                    ys.append(yy)
        if not xs:
            return None
        return ((min(xs) - x0) / w, (min(ys) - y0) / h, (max(xs) - x0) / w, (max(ys) - y0) / h)

    # 框的像素位置照輸出的畫布（直的 360x640）取整：挑一個會被取整的框，橫的畫布算出來會不一樣
    odd = [0.6013, 0.0517, 0.3311, 0.2903]
    panel.set_track_props(rect=odd)
    wait(100)
    vr = panel._video_rect()

    def expected(cw, ch):
        ox, oy, ow, oh = assemble.overlay_box(odd, cw, ch)
        return (vr.x() + ox * vr.width() / cw, vr.y() + oy * vr.height() / ch,
                ow * vr.width() / cw, oh * vr.height() / ch)

    frame = panel.overlay_preview.items[0].rect()
    got = (frame.x(), frame.y(), frame.width(), frame.height())
    portrait, landscape = expected(360, 640), expected(640, 360)
    check("疊加的框照輸出的直畫布（360x640）取整：跟它算的差 0.05px 以內（橫的算出來會差 0.3px 以上）",
          max(abs(a - b) for a, b in zip(got, portrait)) < 0.05
          and max(abs(a - b) for a, b in zip(portrait, landscape)) > 0.3, f"{got} {portrait} {landscape}")
    panel.set_track_props(rect=assemble.position_rect("top_right"))
    wait(100)

    # 主片原本右下的白轉 90 度後在左下；上半只有疊加素材的白
    vr = panel._video_rect()
    preview_box = white_box(grab(), vr.x(), vr.y(), vr.width(), vr.height() / 2)
    out = os.path.join(tmp, "疊加裁切.mp4")
    check("輸出多軌：開始", panel.export_tracks(out) is True, str(errors))
    wait_until(lambda: not panel.track_exporter.busy, 120000)
    wait(100)
    w, h = (int(v) for v in probe_size(out).split(","))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1.0", "-i", out, "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True).stdout

    def raw_pixel(xx, yy):
        i = (yy * w + xx) * 3
        return tuple(raw[i:i + 3])

    out_box = white_box(raw_pixel, 0, 0, w, h // 2)
    check("成品是直的 360x640", (w, h) == (360, 640), f"{w}x{h}")
    check("疊加素材只剩右下那一塊白，框照直的畫布擺在右上：預覽與成品位置一樣（差 3% 以內）",
          preview_box is not None and out_box is not None and preview_box[0] > 0.5
          and all(abs(a - b) < 0.03 for a, b in zip(preview_box, out_box)), f"預覽 {preview_box} 成品 {out_box}")

    dialog.reset_btn.click()
    wait(50)
    check("疊加素材全部還原：裁切也拿掉", "adjust" not in panel.tracks["overlays"][0])
    dialog.close()
    panel.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 裁切測試全數通過。")
