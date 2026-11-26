# -*- coding: utf-8 -*-
"""
剪輯器版面改版 E-6a：快捷鍵與預覽區（gui_qt/editor.py）。規則（時間碼、逐格、J／K／L）在 test_playhead.py。

1. 預覽區：時間碼寫「時:分:秒.百分之一秒 / 片長」，跟著播放頭變；播放器原本的時間收起來（四頁籤照舊）；
   播放鍵兩邊有〔上一格〕〔下一格〕。
2. 影格率在背景量（25 fps 的片子量到 25）；逐格照它走、先暫停；按鈕與 ←／→ 都行。
3. ←／→ 不搶別人的方向鍵：焦點在逐句清單時不動播放頭；時間軸選了字幕時照舊微調那句。
4. Space 播放／暫停；在編輯框裡打空白照樣是打字。
5. J／K／L：L 播放、再按 2 倍速；K 暫停回 1 倍；J 倒退 1 秒。
6. Ctrl+= 拉近、Ctrl+- 拉遠、Shift+Z 整支；Ctrl+E 開匯出；Ctrl+Shift+S 存專案。
7. 提示文字寫快捷鍵。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過剪輯器快捷鍵（規則在 test_playhead.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import editor as ed  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import playhead as ph  # noqa: E402

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
            wait(30)
            waited += 30
        return cond()

    clip = os.path.join(tmp, "clip.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "6", "-pix_fmt", "yuv420p", "-c:v", "libx264",
                    "-c:a", "aac", clip], check=True)

    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["theme"] = "dark"
    ed.apply_initial_theme(app, "dark")
    win = ed.EditorWindow(cfg)
    win.resize(1440, 900)
    win.show()
    win.activateWindow()
    wait(100)
    p = win.player_panel
    p._ask_discard = lambda *a, **k: "discard"
    p._ask_project_discard = lambda *a, **k: "discard"
    t = p.timeline
    pl = p.player

    def inside(widget, ancestor):
        w = widget
        while w is not None:
            if w is ancestor:
                return True
            w = w.parentWidget()
        return False

    def key(k, mod=Qt.NoModifier, target=None):
        QTest.keyClick(target or QApplication.focusWidget() or win, k, mod)
        wait(30)

    def seek(ms):
        pl.setPosition(ms)
        wait_until(lambda: pl.position() == ms, 5000)

    # ----- 1 -----
    check("時間碼在預覽區、播放器原本的時間收起來", inside(win.timecode_label, win.preview_panel)
          and win.timecode_label.isVisible() and not p.time_label.isVisible())
    check("沒開影片：00:00:00.00 / 00:00:00.00", win.timecode_label.text() == "00:00:00.00 / 00:00:00.00",
          win.timecode_label.text())
    check("播放鍵兩邊有上一格、下一格", inside(win.prev_frame_tool, win.preview_panel)
          and inside(win.next_frame_tool, win.preview_panel)
          and win.prev_frame_tool.x() < win.play_tool.x() < win.next_frame_tool.x())
    p.open_video(clip)
    check("開影片", wait_until(lambda: pl.duration() > 0 and t.duration > 0))
    check("量到 25 fps", wait_until(lambda: abs(win.media_fps - 25.0) < 0.01), str(win.media_fps))
    seek(1230)
    check("時間碼跟著播放頭", wait_until(lambda: win.timecode_label.text().startswith("00:00:01.23 / 00:00:06.0")),
          win.timecode_label.text())

    # ----- 2 -----
    seek(1000)
    check("下一格：1000 → 1040", win.step_frame(1) == 1040 and wait_until(lambda: pl.position() == 1040))
    win.next_frame_tool.click()
    check("〔下一格〕按鈕", wait_until(lambda: pl.position() == 1080), str(pl.position()))
    win.prev_frame_tool.click()
    check("〔上一格〕按鈕", wait_until(lambda: pl.position() == 1040), str(pl.position()))
    win.play_tool.setFocus()
    key(Qt.Key_Right)
    check("→：下一格", wait_until(lambda: pl.position() == 1080), str(pl.position()))
    key(Qt.Key_Left)
    key(Qt.Key_Left)
    check("←←：退兩格", wait_until(lambda: pl.position() == 1000), str(pl.position()))
    pl.play()
    wait_until(lambda: pl.playbackState() == QMediaPlayer.PlayingState, 5000)
    win.step_frame(1)
    check("逐格先暫停", pl.playbackState() != QMediaPlayer.PlayingState)

    # ----- 3 -----
    p.set_cues([{"start": 0.5, "end": 1.5, "text": "第一句"}, {"start": 3.0, "end": 4.0, "text": "第二句"}])
    t.select_cue(-1, seek=False)
    seek(2000)
    win.cue_panel.table.setFocus()
    wait(30)
    check("焦點在逐句清單：←／→ 不拿去逐格", win._update_arrow_keys() is False)
    win.cue_panel.table.selectRow(0)  # 先選好一句（選句子會跳到那句開頭）；之後按 → 播放頭不能再動
    wait(50)
    here = pl.position()
    key(Qt.Key_Right, target=win.cue_panel.table)
    check("清單裡按 →：播放頭不動", pl.position() == here, f"{here} → {pl.position()}")
    t.setFocus()
    t.select_cue(1, seek=False)
    wait(30)
    check("時間軸選了字幕：←／→ 留給它微調", win._update_arrow_keys() is False)
    here = pl.position()
    key(Qt.Key_Right, target=t)
    check("→ 微調那句（不是逐格）", p.cues[1]["start"] > 3.0 and pl.position() == here, f"{p.cues[1]} {pl.position()}")
    p.undo()
    t.select_cue(-1, seek=False)
    wait(30)
    check("時間軸沒選字幕：←／→ 逐格", win._update_arrow_keys() is True)
    here = pl.position()
    key(Qt.Key_Right, target=t)
    check("時間軸上 →：下一格", wait_until(lambda: pl.position() == ph.step_frames(here, 1, 25)),
          f"{here} → {pl.position()}")

    # ----- 4 -----
    t.select_cue(-1, seek=False)
    t.setFocus()  # 焦點不在播放鍵上（不然 Space 只是「按下那顆按鈕」，量不到快捷鍵）
    wait(30)
    key(Qt.Key_Space, target=t)
    check("Space：播放", wait_until(lambda: pl.playbackState() == QMediaPlayer.PlayingState, 5000))
    key(Qt.Key_Space, target=t)
    check("再按 Space：暫停", wait_until(lambda: pl.playbackState() != QMediaPlayer.PlayingState, 5000))
    t.select_cue(0, seek=False)
    wait(30)
    editor = win.cue_panel.editor
    editor.setFocus()
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    key(Qt.Key_Space, target=editor)
    check("編輯框裡打空白：是打字、不播放", editor.toPlainText().endswith(" ")
          and pl.playbackState() != QMediaPlayer.PlayingState, repr(editor.toPlainText()))
    QTest.keyClick(editor, Qt.Key_Escape)
    t.select_cue(-1, seek=False)

    # ----- 5 -----
    win.play_tool.setFocus()
    key(Qt.Key_L)
    check("L：1 倍速播放", wait_until(lambda: pl.playbackState() == QMediaPlayer.PlayingState, 5000)
          and pl.playbackRate() == 1.0)
    key(Qt.Key_L)
    check("再按 L：2 倍速", pl.playbackRate() == 2.0 and "2 倍速" in win.statusBar().currentMessage())
    key(Qt.Key_K)
    check("K：暫停、回 1 倍", wait_until(lambda: pl.playbackState() != QMediaPlayer.PlayingState, 5000)
          and pl.playbackRate() == 1.0)
    seek(3000)
    key(Qt.Key_J)
    check("J：倒退 1 秒", wait_until(lambda: pl.position() == 2000), str(pl.position()))

    # ----- 6 -----
    before = t.px_per_sec
    key(Qt.Key_Equal, Qt.ControlModifier)
    check("Ctrl+=：拉近", t.px_per_sec > before, f"{before} → {t.px_per_sec}")
    zoomed = t.px_per_sec
    key(Qt.Key_Minus, Qt.ControlModifier)
    check("Ctrl+-：拉遠", t.px_per_sec < zoomed)
    key(Qt.Key_Equal, Qt.ControlModifier)
    key(Qt.Key_Equal, Qt.ControlModifier)
    key(Qt.Key_Z, Qt.ShiftModifier)
    t.zoom_to_fit()
    fit = t.px_per_sec
    key(Qt.Key_Equal, Qt.ControlModifier)
    key(Qt.Key_Z, Qt.ShiftModifier)
    check("Shift+Z：整支", abs(t.px_per_sec - fit) < 1e-6, f"{t.px_per_sec} / {fit}")
    asked = []
    p._ask_project_path = lambda suggested: asked.append(suggested) or ""
    key(Qt.Key_S, Qt.ControlModifier | Qt.ShiftModifier)
    check("Ctrl+Shift+S：存專案（問存到哪）", len(asked) == 1, str(asked))
    key(Qt.Key_E, Qt.ControlModifier)
    check("Ctrl+E：開匯出", wait_until(lambda: win.export_dialog.isVisible(), 3000))
    win.export_dialog.close()

    # ----- 7 -----
    tips = {"拉近": p.zoom_in_btn.toolTip(), "拉遠": p.zoom_out_btn.toolTip(), "整支": p.fit_btn.toolTip(),
            "匯出": win.export_button.toolTip(), "存專案": p.save_project_btn.toolTip(),
            "上一格": win.prev_frame_tool.toolTip(), "下一格": win.next_frame_tool.toolTip()}
    want = {"拉近": "Ctrl+=", "拉遠": "Ctrl+-", "整支": "Shift+Z", "匯出": "Ctrl+E", "存專案": "Ctrl+Shift+S",
            "上一格": "←", "下一格": "→"}
    missing = [k for k, v in want.items() if f"（{v}）" not in tips[k]]
    check("提示文字寫快捷鍵", not missing, str({k: tips[k] for k in missing}))
    check("播放鍵提示寫 Space", "Space" in win.play_tool.toolTip())
    win.close()

    # 四頁籤：時間照舊
    qt_app.apply_theme(app, "light")
    win2 = qt_app.MainWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    win2.tabs.setCurrentIndex(1)
    win2.show()
    wait(50)
    check("四頁籤：播放器的時間照舊", win2.player_panel.time_label.isVisible()
          and win2.player_panel.time_label.text().count(":") == 2 or win2.player_panel.time_label.text() == "",
          win2.player_panel.time_label.text())
    win2.close()
    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("剪輯器快捷鍵與預覽區（E-6a）測試全數通過。")
