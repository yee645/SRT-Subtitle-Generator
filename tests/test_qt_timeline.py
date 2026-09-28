# -*- coding: utf-8 -*-
"""
3.0 第 4 項第一階段：`gui_qt/timeline.py`（時間軸）＋接進②頁播放器。

沒有 PySide6 的環境只跑純計算（刻度）；有 PySide6 時：

1. 幾何：場景寬 = 片長 × 每秒像素；字幕塊的位置與寬度；播放頭位置；縮放
   夾在上下限；Ctrl＋滾輪縮放時滑鼠底下那一秒不動；「整支」剛好塞滿。
2. **畫出來的東西對不對**（抓畫面像素）：
   - 波形：測資只有 2～5 秒、9～14 秒大聲，其餘幾乎靜音——大聲段的波形列
     有很多波形色的像素、安靜段幾乎沒有。
   - 縮圖：測資畫面亮度 = 時間 × k，縮圖列由左到右越來越亮。
3. 互動：點時間軸 → seekRequested 帶對的毫秒；播放頭跑出畫面會捲過去。
4. 接進播放器：開片子 → 背景抽完波形與縮圖畫上去；點時間軸 → 播放器跳過
   去；播放器位置 → 播放頭；載字幕 → 字幕塊；沒有音軌的片子 → 波形列寫原
   因、縮圖照常；連開兩支 → 最後畫的是第二支（第一支晚到的結果被丟掉）。
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

# ===== 純計算（刻度）：不需要 PySide6 也要能測，所以另外實作一份對照 ====

if PySide6 is None:
    print("SKIP 這個環境沒有 PySide6：略過時間軸（刻度的測試也在 gui_qt 裡）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QPoint, QPointF, Qt, QTimer  # noqa: E402
    from PySide6.QtGui import QColor, QWheelEvent  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import filmstrip, waveform  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = tmp  # 快取不留在 repo

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

    # ----- 刻度 -----
    check("刻度間距：每秒 40px → 2 秒一格（兩個標籤至少 70px）", tl.tick_step(40) == 2)
    check("刻度間距：每秒 400px → 0.2 秒一格", tl.tick_step(400) == 0.2)
    check("刻度間距：每秒 2px → 60 秒一格", tl.tick_step(2) == 60)
    check("刻度：0～10 秒、每秒 40px → 0,2,4,6,8,10", tl.ticks(0, 10, 40) == [0, 2, 4, 6, 8, 10],
          str(tl.ticks(0, 10, 40)))
    check("刻度：從 3.1 秒開始就從 4 開始（對齊間距）", tl.ticks(3.1, 9, 40)[0] == 4)
    check("刻度標籤：75 秒 → 1:15；0.2 秒間距帶小數 → 0:01.2",
          tl.tick_label(75, 5) == "1:15" and tl.tick_label(1.2, 0.2) == "0:01.2",
          f"{tl.tick_label(75, 5)} {tl.tick_label(1.2, 0.2)}")

    # ----- 測資：畫面亮度＝時間×8、2～5 秒與 9～14 秒大聲 -----
    video = os.path.join(tmp, "tl.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y",
                    "-f", "lavfi", "-i",
                    "color=black:s=320x180:r=30:d=20,format=gray,geq=lum='min(255,T*12)',format=yuv420p",
                    "-f", "lavfi", "-i",
                    "aevalsrc='if(between(t,2,5)+between(t,9,14),0.7,0.01)*sin(2*PI*300*t)':d=20:s=44100",
                    "-c:v", "libx264", "-preset", "ultrafast", "-g", "30",
                    "-c:a", "aac", "-shortest", video], check=True)
    peaks = waveform.load_peaks(video, cache_dir=os.path.join(tmp, "w"))
    strip = filmstrip.load_filmstrip(video, height=108, cache_dir=os.path.join(tmp, "f"))

    view = tl.TimelineView()
    view.resize(1000, view.height())
    view.show()
    wait(50)
    view.set_duration(20)
    view.set_zoom(40, 0, 0)
    check("場景寬 = 片長 × 每秒像素（20 × 40 = 800）",
          abs(view.scene().sceneRect().width() - 800) < 0.5, str(view.scene().sceneRect()))
    cues = [{"start": 1, "end": 4, "text": "第一句"}, {"start": 5.5, "end": 6, "text": "短"},
            {"start": 8, "end": 8, "text": "零長度（不畫）"}]
    view.set_cues(cues)
    rects = view.cue_rects()
    check("字幕塊：零長度的不畫，其餘兩塊", len(rects) == 2, str(len(rects)))
    check("字幕塊位置與寬度照時間（1～4 秒 → x=40、寬 120）",
          abs(rects[0].left() - 40) < 0.5 and abs(rects[0].width() - 120) < 0.5, str(rects[0]))
    view.set_position(2500, follow=False)
    check("播放頭在 2.5 秒 → x=100", abs(view.playhead.line().x1() - 100) < 0.5,
          str(view.playhead.line()))
    view.set_zoom(10000)
    check("縮放有上限", view.px_per_sec == tl.MAX_PX_PER_SEC, str(view.px_per_sec))
    view.set_zoom(0.001)
    check("縮放有下限", view.px_per_sec == tl.MIN_PX_PER_SEC, str(view.px_per_sec))
    view.zoom_to_fit()
    check("整支：片長剛好塞滿視窗寬度",
          abs(view.scene_width() - (view.viewport().width() - 2)) < 1.5,
          f"{view.scene_width()} vs {view.viewport().width()}")
    view.set_zoom(40, 0, 0)
    check("縮放後字幕塊跟著重算（每秒 40px → 1 秒在 x=40）",
          abs(view.cue_rects()[0].left() - 40) < 0.5)

    # Ctrl＋滾輪：滑鼠底下那一秒不動
    view.set_zoom(40, 0, 0)
    x = 300
    before = view.seconds_at(x)
    wheel = QWheelEvent(QPointF(x, 50), QPointF(view.mapToGlobal(QPoint(x, 50))), QPoint(0, 0),
                        QPoint(0, 120), Qt.NoButton, Qt.ControlModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    app.sendEvent(view.viewport(), wheel)
    after = view.seconds_at(x)
    check("Ctrl＋滾輪往上 → 拉近一級", abs(view.px_per_sec - 40 * tl.ZOOM_STEP) < 1e-6,
          str(view.px_per_sec))
    check("Ctrl＋滾輪縮放時滑鼠底下那一秒不動（差 1 像素內）",
          abs(after - before) * view.px_per_sec <= 1.0, f"{before} → {after}")

    # 點一下 → seekRequested
    view.set_zoom(40, 0, 0)
    got = []
    view.seekRequested.connect(got.append)
    from PySide6.QtTest import QTest  # noqa: E402
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(200, 60))
    check("點時間軸 x=200（每秒 40px）→ seekRequested(5000)",
          got and abs(got[-1] - 5000) <= 30, str(got))
    check("點下去播放頭也跟著到那裡", abs(view.playhead.line().x1() - 200) < 1.5)

    # 播放頭跑出畫面會捲過去
    view.set_zoom(200, 0, 0)  # 20 秒 × 200 = 4000px，視窗只有約 1000px
    view.set_position(15000)
    left, right = view.visible_range()
    check("播放頭跑出畫面 → 自動捲到看得到（15 秒在可見範圍內）", left <= 15 <= right,
          f"{left:.1f}～{right:.1f}")

    # ----- 畫出來的東西對不對 -----
    view.set_zoom(40, 0, 0)
    view.set_peaks(peaks)
    view.set_filmstrip(strip)
    wait(50)
    img = view.viewport().grab().toImage()
    wave_color = view.colors["wave"]

    def wave_pixels(t0, t1):
        count = 0
        for xx in range(int(t0 * 40) + 2, int(t1 * 40) - 2):
            for yy in range(tl.ROW_Y["wave"], tl.ROW_Y["wave"] + tl.WAVE_H):
                c = QColor(img.pixel(xx, yy))
                if abs(c.red() - wave_color.red()) + abs(c.green() - wave_color.green()) \
                        + abs(c.blue() - wave_color.blue()) < 60:
                    count += 1
        return count / max(int(t1 * 40) - int(t0 * 40) - 4, 1)

    loud, quiet = wave_pixels(2.2, 4.8), wave_pixels(5.5, 8.5)
    check("波形：大聲段（2～5 秒）每欄的波形像素遠多於安靜段（5～9 秒）",
          loud > 30 and quiet < 5, f"大聲 {loud:.1f}／欄、安靜 {quiet:.1f}／欄")
    check("波形：9～14 秒又大聲", wave_pixels(9.5, 13.5) > 30)

    def thumb_luma(t):
        xx = int(t * 40)
        yy = tl.ROW_Y["thumbs"] + tl.THUMB_H // 2
        return QColor(img.pixel(xx, yy)).lightness()

    lumas = [thumb_luma(t) for t in (1, 5, 9, 13, 17)]
    check("縮圖：畫面亮度＝時間的測資，縮圖列由左到右越來越亮",
          lumas == sorted(lumas) and lumas[-1] - lumas[0] > 100, str(lumas))
    img.save(os.path.join(tmp, "timeline_view.png"))

    # ----- 接進播放器 -----
    win = qt_app.MainWindow({"subtitle_style": {}})
    win.resize(1280, 800)
    win.show()
    panel = win.player_panel
    panel.open_video(video)
    ok = wait_until(lambda: panel.timeline.peaks is not None and panel.timeline.filmstrip is not None)
    check("開片子 → 背景抽完波形與縮圖並畫上去", ok,
          f"{panel.timeline.wave_note} / {panel.timeline.thumb_note}")
    check("時間軸的片長跟著播放器（約 20 秒）", wait_until(lambda: abs(panel.timeline.duration - 20) < 0.2),
          str(panel.timeline.duration))
    check("一開片子整支塞滿時間軸",
          abs(panel.timeline.scene_width() - (panel.timeline.viewport().width() - 2)) < 2,
          f"{panel.timeline.scene_width()} vs {panel.timeline.viewport().width()}")
    check("快取寫在指定的地方，不在程式資料夾",
          os.path.isdir(os.path.join(tmp, waveform.CACHE_DIR))
          and os.path.isdir(os.path.join(tmp, filmstrip.CACHE_DIR)))

    panel.set_cues([{"start": 2, "end": 5, "text": "大聲那段"}])
    check("載字幕 → 時間軸上出現字幕塊", len(panel.timeline.cue_rects()) == 1)

    pps = panel.timeline.px_per_sec
    target_x = int(12 * pps) - panel.timeline.horizontalScrollBar().value()
    QTest.mouseClick(panel.timeline.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(target_x, 60))
    check("點時間軸 12 秒處 → 播放器跳過去", wait_until(lambda: abs(panel.player.position() - 12000) < 400, 5000),
          str(panel.player.position()))

    panel.player.setPosition(3000)
    check("播放器位置 → 播放頭跟著到 3 秒",
          wait_until(lambda: abs(panel.timeline.playhead.line().x1() - 3 * panel.timeline.px_per_sec) < 3, 5000),
          f"{panel.timeline.playhead.line().x1()} vs {3 * panel.timeline.px_per_sec}")

    # 沒有音軌的片子
    silent = os.path.join(tmp, "noaudio.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=gray:s=160x90:r=30:d=3", "-an", "-c:v", "libx264",
                    "-preset", "ultrafast", silent], check=True)
    panel.open_video(silent)
    check("沒有音軌 → 波形列寫出原因、縮圖照常",
          wait_until(lambda: panel.timeline.filmstrip is not None and "沒有可畫的波形" in panel.timeline.wave_note)
          and panel.timeline.peaks is None, panel.timeline.wave_note)

    # 連開兩支：最後畫的是第二支
    other = os.path.join(tmp, "other.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=white:s=160x90:r=30:d=7", "-f", "lavfi", "-i", "sine=d=7",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", other],
                   check=True)
    panel.open_video(video)
    panel.open_video(other)
    wait_until(lambda: panel.timeline.peaks is not None and panel.timeline.filmstrip is not None)
    wait(1500)  # 讓第一支（若沒被取消）有時間把結果送回來
    check("連開兩支 → 最後畫的是第二支（7 秒的波形與縮圖）",
          panel.timeline.peaks is not None and abs(panel.timeline.peaks.duration - 7) < 0.3
          and panel.timeline.filmstrip is not None and abs(panel.timeline.filmstrip.duration - 7) < 0.3,
          f"{panel.timeline.peaks and panel.timeline.peaks.duration} "
          f"{panel.timeline.filmstrip and panel.timeline.filmstrip.duration}")

    win.close()
    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 時間軸測試全數通過。")
