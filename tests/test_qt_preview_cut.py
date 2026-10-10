# -*- coding: utf-8 -*-
"""
3.0 第 8 項第三階段：預覽剪後（播放時跳過剪掉的段落）與接縫轉場的標示。

規則（cutmarks.preview_jump、assemble.seam_overlaps）在 test_cutmarks.py／test_assemble.py；
這裡讓播放器真的播：

1. 「預覽剪後」什麼時候能勾：沒顯示剪點、剪點全停用 → 不能。
2. 勾了、播放中：走到剪點就跳到下一段，剪掉的那段一格都沒畫到時間軸上；沒勾時照常播進去
   （對照組）。
3. 停著時照樣能點進剪點裡看。
4. 最後一段播完就停（剪點拖到片尾）。
5. 接縫選溶接：剪點列上標出重疊的那兩截（位置照 seam_overlaps）；硬切、不顯示剪點就不標。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過預覽剪後（核心在 test_cutmarks.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
    from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = tmp
    config.CONFIG_PATH = os.path.join(tmp, "config.json")
    PLAYING = QMediaPlayer.PlaybackState.PlayingState

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

    main = os.path.join(tmp, "main.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:d=8",
                    "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:d=8",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", main],
                   check=True)

    win = qt_app.MainWindow({"subtitle_style": {}})
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 860)
    win.show()
    panel = win.player_panel
    tv = panel.timeline
    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0)
    wait(100)
    panel.set_cues([{"start": 0.2, "end": 2.5, "text": "第一句"}, {"start": 5.5, "end": 7.8, "text": "第二句"}])

    # 記下每一個畫到時間軸上的位置（跳過去的那一下不會畫）
    drawn = []
    real_set_position = tv.set_position

    def recording_set_position(ms, *args, **kwargs):
        drawn.append(ms)
        return real_set_position(ms, *args, **kwargs)
    tv.set_position = recording_set_position

    def play_from(ms, until_ms, limit_ms=12000):
        panel.player.pause()
        panel.player.setPosition(ms)
        wait_until(lambda: abs(panel.player.position() - ms) < 50, 5000)
        drawn.clear()
        panel.player.play()
        reached = wait_until(lambda: panel.player.position() >= until_ms
                             or panel.player.playbackState() != PLAYING, limit_ms)
        stopped = panel.player.playbackState() != PLAYING  # 在測試自己按暫停之前看：是播放器自己停的
        panel.player.pause()
        wait(50)
        return reached, stopped

    # ----- 1. 什麼時候能勾 -----
    box = panel.preview_cut_box
    check("沒顯示剪點：不能勾", not box.isEnabled() and box.isVisible())
    panel.show_cut_marks("jumpcut")
    check("停頓剪點 2.65～5.35；顯示後能勾、預設不勾",
          [(m["start"], m["end"]) for m in panel.cut_plan["marks"]] == [(2.65, 5.35)]
          and box.isEnabled() and not box.isChecked(), str(panel.cut_plan["marks"]))
    tv.cutMarkToggled.emit(0, False)
    check("剪點全停用：不能勾", not box.isEnabled())
    tv.cutMarkToggled.emit(0, True)
    check("再啟用：又能勾", box.isEnabled())

    # ----- 2. 對照組：沒勾 → 照常播進剪點裡 -----
    play_from(2000, 3600)
    check("沒勾預覽剪後：播放會走進剪掉的那段（對照組）", any(2800 < ms < 5200 for ms in drawn),
          str(drawn[:40]))

    # ----- 2. 勾了：跳過 -----
    box.setChecked(True)
    reached, _stopped = play_from(2000, 6000)
    inside = [ms for ms in drawn if 2700 < ms < 5300]
    check("勾了預覽剪後：播放中走到剪點就跳到下一段（剪掉的那段一格都沒畫）",
          reached and not inside and any(ms >= 5350 for ms in drawn) and any(ms < 2650 for ms in drawn),
          f"{inside[:10]} {drawn[:60]}")

    # ----- 3. 停著時照樣能點進去看 -----
    panel.player.setPosition(4000)
    wait(400)
    check("停著時點進剪點裡：停在那裡（照樣可以看剪掉的是什麼）",
          abs(panel.player.position() - 4000) < 50 and panel.player.playbackState() != PLAYING,
          str(panel.player.position()))

    # ----- 4. 最後一段播完就停 -----
    tv.cutMarkChanged.emit(0, 2.65, 8.0)  # 把剪點拖到片尾：只留 0～2.65
    check("剪點拖到片尾：只剩一段保留片段", panel._preview_keep == [(0.0, 2.65)], str(panel._preview_keep))
    _reached, stopped = play_from(1500, 7000, limit_ms=6000)
    check("最後一段播完就自己停在它的結尾（2.65 秒），不播進剪掉的片尾",
          stopped and abs(panel.player.position() - 2650) < 80
          and not [ms for ms in drawn if ms > 2700], f"{panel.player.position()} {drawn[-10:]}")
    panel.reset_cut_marks()

    # ----- 5. 接縫轉場的標示 -----
    check("硬切：剪點列不標接縫", tv.seam_rects() == [])
    panel.seam_combo.setCurrentIndex(panel.seam_combo.findData("dissolve"))
    pps = tv.px_per_sec
    rects = [(round(r.left() / pps, 2), round(r.right() / pps, 2)) for r in tv.seam_rects()]
    check("接縫溶接 0.5 秒：剪點列標出 2.15～2.65 與 5.35～5.85 兩截（在剪點列裡）",
          rects == [(2.15, 2.65), (5.35, 5.85)]
          and all(tl.ROW_Y["cuts"] <= r.top() and r.bottom() <= tl.ROW_Y["cuts"] + tl.CUT_LANE_H
                  for r in tv.seam_rects()), str(rects))
    panel.seam_spin.setValue(1.0)
    rects = [(round(r.left() / pps, 2), round(r.right() / pps, 2)) for r in tv.seam_rects()]
    check("改成 1 秒：標的範圍跟著變", rects == [(1.65, 2.65), (5.35, 6.35)], str(rects))
    tv.zoom_in()
    wait(50)
    pps = tv.px_per_sec
    rects = [(round(r.left() / pps, 2), round(r.right() / pps, 2)) for r in tv.seam_rects()]
    check("拉近之後位置照樣對", rects == [(1.65, 2.65), (5.35, 6.35)], str(rects))
    tip = tv.seam_items[0].toolTip() if tv.seam_items else ""
    check("滑鼠提示寫是哪種轉場、幾秒", "接縫溶接" in tip and "1.00 秒" in tip, tip)
    tv.cutMarkToggled.emit(0, False)
    check("剪點停用：不標接縫", tv.seam_rects() == [])
    tv.cutMarkToggled.emit(0, True)
    panel.show_cut_marks("")
    check("不顯示剪點：不標接縫、預覽剪後不能勾", tv.seam_rects() == [] and not box.isEnabled())
    panel.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 預覽剪後測試全數通過。")
