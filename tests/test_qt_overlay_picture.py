# -*- coding: utf-8 -*-
"""
3.0 第 9 項第三階段：疊加素材的畫面調整（同一個小視窗改調選取的那段疊加素材）。

1. `picture_preview.apply_to_image`：轉、翻的方向跟 ffmpeg 一樣，調色照第二階段的算法。
2. 播放器：
   - 選取疊加素材後屬性那一行有「調畫面…」，小視窗標題寫調的是哪一段。
   - 轉 90 度後播放器上的預覽變直的（框裡左右補黑），影片素材抽出來的預覽格與圖片都照調整。
   - 調疊加素材不動主片；回頭按「畫面調整…」又調主片。
   - 小視窗開著時改選別段，跟著改調那一段；刪掉前面的段，跟著往前；刪掉正在調的，回到主片。
   - 修頭尾之後調整還在；輸出中、數字不合理都不改。
3. 輸出：成品裡疊加素材照調整（直的、補黑、調暗），顏色跟預覽差 30 以內。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過疊加素材的畫面調整（核心在 test_picture.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
    from PySide6.QtGui import QColor, QImage  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import picture_preview as pp  # noqa: E402
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

    RED, BLUE, GREEN, WHITE, BLACK = (255, 0, 0), (0, 0, 255), (0, 255, 0), (255, 255, 255), (0, 0, 0)

    # 四色圖：左上紅、右上藍、左下綠、右下白
    quad_filter = "[0:v][1:v]hstack[t];[2:v][3:v]hstack[b];[t][b]vstack[v]"
    quad_inputs = []
    for c in ("red", "blue", "0x00ff00", "white"):
        quad_inputs += ["-f", "lavfi", "-i", f"color=c={c}:size=160x90:rate=30:d=8"]
    quad_png = os.path.join(tmp, "四色.png")
    run(*quad_inputs, "-filter_complex", quad_filter, "-map", "[v]", "-frames:v", "1", quad_png)
    quad_mp4 = os.path.join(tmp, "四色.mp4")
    run(*quad_inputs, "-filter_complex", quad_filter, "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv444p", quad_mp4)

    # ----- 1. apply_to_image -----
    img = QImage(quad_png)

    def corners(image):
        w, h = image.width(), image.height()
        return [QColor(image.pixel(int(w * fx), int(h * fy))).getRgb()[:3]
                for fx, fy in ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75))]

    def match(got, want):
        return all(near(g, w) for g, w in zip(got, want))

    turned = pp.apply_to_image(img, {"rotate": 90})
    check("順時針轉 90 度：圖變直的，左上綠、右上紅、左下白、右下藍（同 ffmpeg transpose=clock）",
          (turned.width(), turned.height()) == (img.height(), img.width())
          and match(corners(turned), [GREEN, RED, WHITE, BLUE]), str(corners(turned)))
    ccw = pp.apply_to_image(img, {"rotate": 270})
    check("逆時針轉 90 度：左上藍", match(corners(ccw)[:1], [BLUE]), str(corners(ccw)))
    both = pp.apply_to_image(img, {"rotate": 90, "flip_h": True})
    check("先轉再翻：轉 90 度後左右翻，左上紅", match(corners(both)[:1], [RED]), str(corners(both)))
    upside = pp.apply_to_image(img, {"flip_v": True})
    check("上下翻：左上綠、大小不變", (upside.width(), upside.height()) == (img.width(), img.height())
          and match(corners(upside)[:1], [GREEN]))
    dark = pp.apply_to_image(img, {"brightness": -0.4})
    check("調暗：右下的白變暗（還是灰白）", max(corners(dark)[3]) < 170 and min(corners(dark)[3]) > 60,
          str(corners(dark)))
    check("沒有調整：原圖原封不動（不多算）", pp.apply_to_image(img, {}) is img)

    # ----- 2. 播放器 -----
    main = os.path.join(tmp, "main.mp4")
    run("-f", "lavfi", "-i", "color=c=0x808080:size=640x360:rate=30:d=8",
        "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:d=8",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", main)

    win = qt_app.MainWindow({"subtitle_style": {}})
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 860)
    win.show()
    panel = win.player_panel
    tv = panel.timeline
    errors = []
    panel._show_track_error = errors.append
    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0)
    wait(100)

    def seek(ms):
        panel.player.setPosition(ms)
        wait_until(lambda: abs(panel.player.position() - ms) < 50, 5000)
        wait(150)

    seek(0)
    check("加入影片素材（0～8 秒、蓋滿）", panel.add_track("overlays", quad_mp4) and errors == [], str(errors))
    check("選取疊加素材：屬性那一行有「調畫面…」", panel.overlay_picture_btn.isVisible()
          and panel.overlay_picture_btn.isEnabled() and not panel.volume_spin.isVisible())
    seek(1000)
    wait_until(lambda: panel.overlay_preview.shown and panel.overlay_preview.shown[0][1] is not None, 20000)
    wait(100)
    vr = panel._video_rect()

    def view_pixel(fx, fy):
        img = panel.view.viewport().grab().toImage()
        return QColor(img.pixel(int(vr.x() + fx * vr.width()), int(vr.y() + fy * vr.height()))).getRgb()[:3]

    check("沒調：素材蓋滿，左上紅、右下白", near(view_pixel(0.25, 0.25), RED) and near(view_pixel(0.75, 0.75), WHITE),
          f"{view_pixel(0.25, 0.25)} {view_pixel(0.75, 0.75)}")
    panel.overlay_picture_btn.click()
    dialog = panel.picture_dialog
    wait(50)
    check("按「調畫面…」：小視窗調的是疊加第 1 段（標題寫檔名）",
          dialog is not None and dialog.isVisible() and dialog.target == ("overlays", 0)
          and "疊加第 1 段：四色.mp4" in dialog.windowTitle(), dialog.windowTitle() if dialog else "")
    dialog.rotate_combo.setCurrentIndex(dialog.rotate_combo.findData(90))
    wait(200)
    # 640x360 的框裡放直的 360x640：等比縮成 202.5x360，左右補黑
    check("轉 90 度：素材記下調整、主片不動", panel.tracks["overlays"][0].get("adjust") == {"rotate": 90}
          and panel.main_adjust == {} and panel.picture_effect is None, str(panel.tracks["overlays"][0]))
    seen = [view_pixel(fx, fy) for fx, fy in ((0.40, 0.25), (0.60, 0.25), (0.40, 0.75), (0.60, 0.75), (0.15, 0.5))]
    check("預覽變直的：框中間左上綠、右上紅、左下白、右下藍，兩旁補黑（影片素材的預覽格也照調整）",
          match(seen, [GREEN, RED, WHITE, BLUE, BLACK]), str(seen))
    dialog.sliders["brightness"].setValue(-40)
    wait(200)
    preview_white = view_pixel(0.40, 0.75)
    check("調暗：預覽裡的白變暗", panel.tracks["overlays"][0]["adjust"] == {"rotate": 90, "brightness": -0.4}
          and max(preview_white) < 180 and min(preview_white) > 60, str(preview_white))

    # 輸出：成品裡疊加素材照調整
    out = os.path.join(tmp, "成品.mp4")
    check("輸出多軌：開始", panel.export_tracks(out) is True, str(errors))
    wait_until(lambda: not panel.track_exporter.busy, 120000)
    wait(100)

    def out_pixel(fx, fy, t=1.0):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", out, "-frames:v", "1",
                              "-vf", f"crop=8:8:{int(640 * fx) - 4}:{int(360 * fy) - 4},scale=1:1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        return tuple(raw[:3])

    made = [out_pixel(fx, fy) for fx, fy in ((0.40, 0.25), (0.60, 0.25), (0.15, 0.5))]
    check("成品：疊加素材轉成直的、兩旁補黑（左上綠偏暗、右上紅偏暗、旁邊黑）",
          made[0][1] > 120 and made[0][0] < 40 and made[1][0] > 120 and made[1][1] < 40 and max(made[2]) < 30,
          str(made))
    out_white = out_pixel(0.40, 0.75)
    check("成品的顏色跟預覽差不多（調暗過的白，差 30 以內）", near(out_white, preview_white, 30),
          f"預覽 {preview_white} 成品 {out_white}")

    # 修頭尾之後調整還在
    # 照時間軸拖尾的流程：從時間軸自己那一份修，再送出去
    item = assemble.trim_item("overlays", tv.tracks["overlays"][0], "end", 6.0, panel.media_duration())
    tv.trackItemChanged.emit("overlays", 0, item)
    check("修尾之後調整還在", panel.tracks["overlays"][0].get("adjust") == {"rotate": 90, "brightness": -0.4}
          and panel.tracks["overlays"][0]["out"] == 6.0, str(panel.tracks["overlays"][0]))

    # 不合理、輸出中：不改
    check("數字不合理：不改、說原因", panel.set_overlay_adjust(0, {"saturation": 9})
          == {"rotate": 90, "brightness": -0.4} and errors and "飽和度" in errors[-1], str(errors))
    errors.clear()
    panel.track_exporter.busy = True
    dialog.flip_h_box.setChecked(True)
    check("輸出中：不改，勾勾放回去", panel.tracks["overlays"][0]["adjust"] == {"rotate": 90, "brightness": -0.4}
          and not dialog.flip_h_box.isChecked())
    panel.track_exporter.busy = False

    # 換對象
    seek(6500)
    check("加入第二段（圖片，6.5 秒起）", panel.add_track("overlays", quad_png))
    wait(100)
    check("小視窗開著時改選第二段：跟著改調第二段（滑桿歸零、標題換檔名）",
          dialog.target == ("overlays", 1) and "疊加第 2 段：四色.png" in dialog.windowTitle()
          and dialog.sliders["brightness"].value() == 0 and dialog.rotate_combo.currentData() == 0,
          dialog.windowTitle())
    dialog.flip_v_box.setChecked(True)
    wait(200)
    check("調第二段不動第一段", panel.tracks["overlays"][1].get("adjust") == {"flip_v": True}
          and panel.tracks["overlays"][0]["adjust"] == {"rotate": 90, "brightness": -0.4})
    panel.set_main_adjust({"saturation": 0.5})
    check("小視窗在調疊加素材時主片的調整變了：小視窗照舊是疊加素材的值",
          dialog.target == ("overlays", 1) and dialog.flip_v_box.isChecked()
          and dialog.sliders["saturation"].value() == 100)
    panel.set_main_adjust({})
    seek(7000)
    check("圖片素材也照調整預覽：上下翻後左上綠", near(view_pixel(0.25, 0.25), GREEN), str(view_pixel(0.25, 0.25)))
    panel.remove_track("overlays", 0)
    wait(50)
    check("刪掉前面那段：小視窗跟著往前（還是調同一張圖）",
          dialog.target == ("overlays", 0) and "疊加第 1 段：四色.png" in dialog.windowTitle()
          and dialog.flip_v_box.isChecked(), dialog.windowTitle())
    panel.remove_track("overlays", 0)
    wait(50)
    check("刪掉正在調的那段：小視窗回到調主片", dialog.target == "main" and dialog.windowTitle() == "畫面調整（主片）")
    dialog.sliders["contrast"].setValue(130)
    wait(100)
    check("回到主片：調的是主片", panel.main_adjust == {"contrast": 1.3})
    panel.add_track("overlays", quad_png)
    panel.overlay_picture_btn.click()
    wait(50)
    check("再按疊加的「調畫面…」：改調疊加素材，滑桿是它的（不是主片的）",
          dialog.target == ("overlays", 0) and dialog.sliders["contrast"].value() == 100)
    panel.picture_btn.click()
    wait(50)
    check("按主片的「畫面調整…」：回到調主片，滑桿是主片的",
          dialog.target == "main" and dialog.sliders["contrast"].value() == 130)
    panel.overlay_picture_btn.click()
    dialog.flip_h_box.setChecked(True)
    dialog.reset_btn.click()
    wait(50)
    check("疊加素材全部還原：不留空的 adjust", "adjust" not in panel.tracks["overlays"][0], str(panel.tracks["overlays"][0]))
    song = os.path.join(tmp, "配樂.wav")
    run("-f", "lavfi", "-i", "sine=frequency=500:sample_rate=48000:d=3", song)
    seek(0)
    panel.add_track("music", song)
    check("選取的是音樂：show_picture_dialog('overlay') 不開、小視窗還在調疊加",
          panel.show_picture_dialog("overlay") is None and dialog.target == ("overlays", 0))
    tv.select_track_item("overlays", -1, seek=False)
    wait(50)
    check("沒選取：show_picture_dialog('overlay') 不開", panel.show_picture_dialog("overlay") is None)
    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0)
    check("換片子（小視窗原本在調疊加素材）：回到調主片、歸零",
          dialog.target == "main" and dialog.windowTitle() == "畫面調整（主片）" and panel.main_adjust == {}
          and dialog.sliders["contrast"].value() == 100)
    dialog.close()
    panel.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 疊加素材的畫面調整測試全數通過。")
