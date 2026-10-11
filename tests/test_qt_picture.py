# -*- coding: utf-8 -*-
"""
3.0 第 9 項第二階段：主片的畫面調整與播放器即時預覽。

濾鏡與資料模型在 test_picture.py；這裡驗：

1. 預覽的調色（`picture_preview.adjust_image`）跟 ffmpeg 真的調出來的顏色差多少：
   亮度、對比、飽和度與組合，六種顏色，最多差 30（0～255）。透明的地方保持透明。
2. 播放器：
   - 沒開影片按不了「畫面調整…」。
   - 拉滑桿畫面立刻變（量播放器畫面上的顏色）。
   - 轉 90 度畫面變直的，字幕跟著擺在轉完的畫面裡。
   - 先轉再翻的方向跟 ffmpeg 一樣。
   - 不合理的數字、輸出中都不改。
   - 全部還原後效果拿掉。
   - 換片子就還原。
3. 輸出：
   - 只調了畫面也能「輸出多軌…」，成品是直的、顏色跟預覽差不多。
   - 「照剪點輸出…」也照調整輸出（走 assemble）。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過畫面調整的預覽（核心在 test_picture.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
    from PySide6.QtGui import QColor, QImage  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import picture_preview as pp  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import picture  # noqa: E402

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

    # ----- 1. 預覽的調色 vs ffmpeg -----
    colors = [(200, 50, 40), (128, 128, 128), (30, 160, 220), (240, 240, 240), (20, 20, 20), (90, 200, 60)]
    cases = [{"brightness": 0.2}, {"brightness": -0.3}, {"contrast": 0.5}, {"contrast": 1.6},
             {"saturation": 0}, {"saturation": 0.5}, {"saturation": 2}, {"saturation": 3},
             {"brightness": 0.1, "contrast": 1.4, "saturation": 1.8}]
    swatch = os.path.join(tmp, "swatch.png")
    worst = []
    for color in colors:
        img = QImage(16, 16, QImage.Format_RGB32)
        img.fill(QColor(*color))
        img.save(swatch)
        for adj in cases:
            raw = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", swatch, "-vf",
                 ",".join(["format=yuv444p"] + picture.filters(adj) + ["format=rgb24"]),
                 "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
            want = tuple(raw[:3])
            got = pp.adjust_image(img, adj).pixelColor(3, 3)
            got = (got.red(), got.green(), got.blue())
            worst.append((max(abs(a - b) for a, b in zip(got, want)), color, adj, got, want))
    worst.sort(key=lambda w: w[0], reverse=True)
    check(f"預覽調色跟 ffmpeg 差不多：{len(worst)} 組最多差 30（實際最多 {worst[0][0]}）",
          worst[0][0] <= 30, str(worst[:3]))
    def dist(x, y):
        return max(abs(a - b) for a, b in zip(x, y))

    moved = [w for w in worst if dist(w[4], w[1]) > 40]
    check(f"比得有意義：ffmpeg 調完差 40 以上的 {len(moved)} 組（至少 20 組）裡，預覽都跟著變了"
          "（離 ffmpeg 比離原色近得多）",
          len(moved) >= 20 and all(dist(w[3], w[4]) * 2 < dist(w[1], w[4]) for w in moved),
          str([w for w in moved if dist(w[3], w[4]) * 2 >= dist(w[1], w[4])][:3]))
    bright_only = max(w[0] for w in worst if set(w[2]) == {"brightness"})
    check(f"只調亮度：差 10 以內（實際 {bright_only}；eq 的亮度是加在 16～235 的 Y 上，要放大 255/219）",
          bright_only <= 10)
    mono = max(w[0] for w in worst if w[2] == {"saturation": 0})
    check(f"飽和度 0 的灰：差 20 以內（實際 {mono}；灰要直接用數值加權，不能先換成線性光）", mono <= 20)
    plain = QImage(8, 8, QImage.Format_ARGB32_Premultiplied)
    plain.fill(QColor(0, 0, 0, 0))
    out = pp.adjust_image(plain, {"brightness": 0.5, "contrast": 0.3, "saturation": 2})
    check("透明的地方調完還是透明（影片還沒有畫面時不會蓋一層灰）", out.pixelColor(2, 2).alpha() == 0)
    check("沒調顏色：不必掛效果", not pp.has_color({"rotate": 90, "flip_h": True})
          and pp.has_color({"contrast": 1.2}))

    # ----- 2. 播放器 -----
    # 四色畫面 8 秒：左上紅、右上藍、左下綠、右下白；聲音只在 0～2.5 與 5.5～8 秒（中間停頓會被剪掉）
    quad = os.path.join(tmp, "quad.mp4")
    run("-f", "lavfi", "-i", "color=c=red:size=320x180:rate=30:d=8",
        "-f", "lavfi", "-i", "color=c=blue:size=320x180:rate=30:d=8",
        "-f", "lavfi", "-i", "color=c=0x00ff00:size=320x180:rate=30:d=8",
        "-f", "lavfi", "-i", "color=c=white:size=320x180:rate=30:d=8",
        "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:d=8",
        "-filter_complex", "[0:v][1:v]hstack[t];[2:v][3:v]hstack[b];[t][b]vstack[v]",
        "-map", "[v]", "-map", "4:a", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv444p",
        "-c:a", "aac", quad)
    other = os.path.join(tmp, "other.mp4")
    run("-f", "lavfi", "-i", "color=c=gray:size=320x180:rate=30:d=3", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", other)

    win = qt_app.MainWindow({"subtitle_style": {}})
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 860)
    win.show()
    panel = win.player_panel
    errors = []
    panel._show_track_error = errors.append
    panel._show_export_error = errors.append
    check("沒開影片：「畫面調整…」按不了", not panel.picture_btn.isEnabled() and panel.picture_btn.isVisible())
    panel.open_video(quad)
    wait_until(lambda: panel.player.duration() > 0)
    panel.player.setPosition(1000)
    wait_until(lambda: abs(panel.player.position() - 1000) < 50, 5000)
    wait(300)
    check("開了影片：按得了", panel.picture_btn.isEnabled())

    def view_pixel(fx, fy):
        """影片畫面裡 (fx, fy)（0～1 的比例）那一點的顏色。"""
        vr = panel._video_rect()
        img = panel.view.viewport().grab().toImage()
        return QColor(img.pixel(int(vr.x() + fx * vr.width()), int(vr.y() + fy * vr.height()))).getRgb()[:3]

    def near(rgb, want, tol=40):
        return all(abs(a - b) <= tol for a, b in zip(rgb, want))

    before = {k: view_pixel(*k) for k in ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75))}
    check("原本：左上紅、右上藍、左下綠、右下白",
          near(before[(0.25, 0.25)], (255, 0, 0)) and near(before[(0.75, 0.25)], (0, 0, 255))
          and near(before[(0.25, 0.75)], (0, 255, 0)) and near(before[(0.75, 0.75)], (255, 255, 255)),
          str(before))
    dialog = panel.show_picture_dialog()
    wait(50)
    check("開出畫面調整的小視窗（不擋住播放器）", dialog.isVisible() and not dialog.isModal()
          and not dialog.reset_btn.isEnabled())

    dialog.sliders["brightness"].setValue(-40)
    wait(150)
    white = view_pixel(0.75, 0.75)
    check("亮度拉到 −40：主片記下來、掛上效果、畫面上的白變暗（差 60 以上）",
          panel.main_adjust == {"brightness": -0.4} and panel.picture_effect is not None
          and white[0] < 195 and dialog.value_labels["brightness"].text() == "-40"
          and dialog.reset_btn.isEnabled(), f"{panel.main_adjust} {white}")
    frames = panel.picture_effect.frames
    check("效果真的在每一格調（畫過）", frames > 0, str(frames))
    dialog.sliders["brightness"].setValue(0)
    dialog.sliders["saturation"].setValue(0)
    wait(150)
    redq = view_pixel(0.25, 0.25)
    check("飽和度拉到 0：紅變灰（三色差 25 以內）、亮度回 0 就不記",
          panel.main_adjust == {"saturation": 0.0} and max(redq) - min(redq) <= 25, f"{panel.main_adjust} {redq}")
    dialog.sliders["brightness"].setValue(30)
    wait(150)
    lifted = view_pixel(0.25, 0.25)
    check("已經掛著效果時再拉亮度：同一個效果跟著改（灰再亮 40 以上）",
          panel.main_adjust == {"saturation": 0.0, "brightness": 0.3} and sum(lifted) / 3 > sum(redq) / 3 + 40,
          f"{redq} {lifted}")
    dialog.sliders["brightness"].setValue(0)
    wait(100)
    check("那一行寫主片調過畫面與細節", "主片調過畫面" in panel.track_label.text()
          and "飽和度 0%" in panel.track_label.text(), panel.track_label.text())
    dialog.sliders["saturation"].setValue(100)
    wait(150)
    check("顏色都回到預設：效果拿掉（不必每一格多算）", panel.main_adjust == {} and panel.picture_effect is None
          and panel.video_item.graphicsEffect() is None)

    landscape = panel._video_rect()
    dialog.rotate_combo.setCurrentIndex(dialog.rotate_combo.findData(90))
    wait(150)
    portrait = panel._video_rect()
    check("轉 90 度：畫面變直的（寬高對調、還是置中）",
          panel.main_adjust == {"rotate": 90} and abs(portrait.width() / portrait.height() - 9 / 16) < 0.02
          and abs(portrait.center().x() - landscape.center().x()) < 2, f"{landscape} {portrait}")
    img = panel.view.viewport().grab().toImage()
    outside = [QColor(img.pixel(int(x), int(portrait.center().y()))).getRgb()[:3]
               for x in (portrait.left() - 4, portrait.right() + 4)]
    edges = [QColor(img.pixel(int(x), int(portrait.center().y() - 20))).getRgb()[:3]
             for x in (portrait.left() + 4, portrait.right() - 4)]
    check("直的畫面剛好填滿算出來的範圍：左右外面是黑的、裡面貼邊的地方有畫面",
          all(max(c) < 30 for c in outside) and all(max(c) > 150 for c in edges), f"{outside} {edges}")
    turned = {k: view_pixel(*k) for k in ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75))}
    check("順時針轉 90 度：左上綠、右上紅、左下白、右下藍（跟 ffmpeg 的 transpose=clock 一樣）",
          near(turned[(0.25, 0.25)], (0, 255, 0)) and near(turned[(0.75, 0.25)], (255, 0, 0))
          and near(turned[(0.25, 0.75)], (255, 255, 255)) and near(turned[(0.75, 0.75)], (0, 0, 255)),
          str(turned))
    panel.set_cues([{"start": 0.2, "end": 2.5, "text": "第一句"}, {"start": 5.5, "end": 7.8, "text": "第二句"}])
    panel.player.setPosition(1100)
    wait(300)
    sub = panel.subtitle_item.sceneBoundingRect()
    check("字幕擺在轉完的直畫面裡（置中、在畫面下半）",
          panel.subtitle_item.isVisible() and abs(sub.center().x() - portrait.center().x()) < 3
          and portrait.top() + portrait.height() / 2 < sub.center().y() < portrait.bottom(), f"{sub} {portrait}")
    dialog.flip_h_box.setChecked(True)
    wait(150)
    check("先轉再翻：轉 90 度後左右翻，左上變紅（跟 ffmpeg 一樣）",
          near(view_pixel(0.25, 0.25), (255, 0, 0)) and panel.main_adjust == {"rotate": 90, "flip_h": True},
          f"{view_pixel(0.25, 0.25)} {panel.main_adjust}")
    dialog.flip_h_box.setChecked(False)
    dialog.flip_v_box.setChecked(True)
    wait(150)
    check("轉 90 度後上下翻：左上變白", near(view_pixel(0.25, 0.25), (255, 255, 255)), str(view_pixel(0.25, 0.25)))
    dialog.flip_v_box.setChecked(False)

    # 不合理、輸出中：不改
    check("不合理的數字：不改、說出原因", panel.set_main_adjust({"rotate": 45}) == {"rotate": 90}
          and errors and "旋轉" in errors[-1], str(errors))
    errors.clear()
    panel.track_exporter.busy = True
    dialog.sliders["contrast"].setValue(150)
    check("輸出中：不改，滑桿放回原本的值", panel.main_adjust == {"rotate": 90}
          and dialog.sliders["contrast"].value() == 100, str(panel.main_adjust))
    panel.track_exporter.busy = False
    panel._update_track_buttons()

    # ----- 3. 輸出 -----
    dialog.sliders["brightness"].setValue(-30)
    wait(200)
    preview_white = view_pixel(0.25, 0.75)  # 轉完左下是原本右下的白
    check("輸出多軌：沒有素材、只調了畫面也按得了", panel.assemble_btn.isEnabled()
          and panel.main_adjust == {"rotate": 90, "brightness": -0.3})
    multi = os.path.join(tmp, "直的.mp4")
    check("開始輸出", panel.export_tracks(multi) is True, str(errors))
    wait_until(lambda: not panel.track_exporter.busy, 120000)
    wait(100)
    size = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                           "-of", "csv=p=0", multi], capture_output=True, text=True).stdout.strip()

    def out_pixel(path, fx, fy, t=1.0):
        w, h = (int(v) for v in subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
             "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip().split(","))
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1",
                              "-vf", f"crop=8:8:{int(w * fx)}:{int(h * fy)},scale=1:1", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        return tuple(raw[:3])

    out_white = out_pixel(multi, 0.25, 0.75)
    def reddish(rgb):  # 調暗過的紅
        return rgb[0] > 120 and rgb[1] < 40 and rgb[2] < 40

    check("輸出：直的 360x640、右上是紅（轉過）", size == "360,640" and reddish(out_pixel(multi, 0.75, 0.25)),
          f"{size} {out_pixel(multi, 0.75, 0.25)} {errors}")
    check("輸出的顏色跟預覽差不多（調暗過的白：差 30 以內，而且都比原本暗 50 以上）",
          near(out_white, preview_white, 30) and out_white[0] < 205 and preview_white[0] < 205,
          f"預覽 {preview_white} 輸出 {out_white}")

    panel.show_cut_marks("jumpcut")
    check("停頓剪點 2.65～5.35", [(m["start"], m["end"]) for m in panel.cut_plan["marks"]] == [(2.65, 5.35)],
          str(panel.cut_plan["marks"]))
    cut = os.path.join(tmp, "剪後.mp4")
    check("照剪點輸出：開始", panel.export_cuts(cut) is True, str(errors))
    wait_until(lambda: not panel.exporter.busy, 120000)
    wait(100)
    duration = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                     "-of", "default=nw=1:nk=1", cut], capture_output=True, text=True).stdout)
    check("照剪點輸出也照調整：片長 5.3 秒、直的、右上紅、那一行寫畫面照調整",
          abs(duration - 5.3) < 0.1 and reddish(out_pixel(cut, 0.75, 0.25, 3.0))
          and "畫面照調整輸出" in panel.cut_label.text() and errors == [],
          f"{duration} {out_pixel(cut, 0.75, 0.25, 3.0)} {panel.cut_label.text()} {errors}")
    panel.show_cut_marks("")

    dialog.reset_btn.click()
    wait(150)
    check("全部還原：沒有調整、畫面回橫的、還原鈕變灰", panel.main_adjust == {}
          and abs(panel._video_rect().width() - landscape.width()) < 1 and not dialog.reset_btn.isEnabled()
          and panel.video_item.transform().isIdentity())
    dialog.sliders["contrast"].setValue(160)
    wait(50)
    panel.open_video(other)
    wait_until(lambda: panel.player.duration() > 0)
    wait(100)
    check("換片子：調整還原、效果拿掉、小視窗跟著歸零", panel.main_adjust == {} and panel.picture_effect is None
          and dialog.sliders["contrast"].value() == 100)
    dialog.close()
    panel.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 畫面調整的預覽測試全數通過。")
