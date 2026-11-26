# -*- coding: utf-8 -*-
"""
剪輯器版面改版 E-3b：素材軌（疊加、音樂）的復原與分割。

規則（assemble.split_item、EditHistory.record_tracks／step_tracks／forget）在 test_assemble.py、test_cueedit.py；
這裡驗播放器面板與剪輯器版面：

1. 素材軌的每一種修改都能 Ctrl+Z／Ctrl+Shift+Z：加入、拖動、修頭尾、改屬性、刪除；復原按鈕跟著能按。
2. 跟字幕的修改排在同一條順序裡：後做的先退。
3. 〔分割〕／Ctrl+B 最後點的是素材：在播放頭把那段切成兩段、選後段；復原合回一段；播放頭不在裡面、循環的音樂
   切不了，狀態列講原因、什麼都不動。最後點的是字幕：照舊切字幕。只選了素材（沒有字幕）〔分割〕也能按。
4. 畫面調整的小視窗開著：分割之後跟著選取改調後段；復原後那段不在了就取消選取、回到調主片。
5. 換片子、開專案：素材軌的舊紀錄拿掉（不會把上一支的素材套回來），字幕的紀錄照舊規則。
6. 四頁籤一樣能復原素材（同一個播放器面板）。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過素材軌的復原與分割（核心在 test_assemble.py、test_cueedit.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import editor as ed  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402

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
    other = os.path.join(tmp, "other.mp4")
    still = os.path.join(tmp, "logo.png")
    song = os.path.join(tmp, "song.m4a")
    run("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-f", "lavfi", "-i", "sine=frequency=440",
        "-t", "10", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", main)
    run("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-t", "4", "-pix_fmt", "yuv420p", "-c:v", "libx264",
        other)
    run("-f", "lavfi", "-i", "testsrc2=size=160x90", "-frames:v", "1", still)
    run("-f", "lavfi", "-i", "sine=frequency=220", "-t", "6", "-c:a", "aac", song)

    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["theme"] = "dark"
    ed.apply_initial_theme(app, "dark")
    win = ed.EditorWindow(cfg)
    win.show()
    wait(100)
    p = win.player_panel
    p._ask_discard = lambda *a, **k: "discard"
    p._ask_project_discard = lambda *a, **k: "discard"
    t = p.timeline
    p.open_video(main)
    check("開好影片", wait_until(lambda: p.media_duration() > 0 and t.duration > 0))

    def seek(seconds):
        p.player.setPosition(int(seconds * 1000))
        wait_until(lambda: abs(p.player.position() - seconds * 1000) < 2, 5000)

    def overlays():
        return [(round(i["at"], 3), round(i.get("duration", i.get("out", 0)), 3)) for i in p.tracks["overlays"]]

    # ----- 1. 每一種修改都能復原 -----
    check("一開始沒得復原", not p.undo_btn.isEnabled())
    seek(2.0)
    check("加入疊加", p.add_track("overlays", still) and overlays() == [(2.0, 3.0)], str(overlays()))
    check("加入後選著它：屬性面板是素材頁", win.inspector_stack.currentWidget() is win.inspector_pages["track"])
    check("加入之後：〔復原〕能按", p.undo_btn.isEnabled())
    win.setFocus()
    QTest.keyClick(win, Qt.Key_Z, Qt.ControlModifier)
    wait(30)
    check("Ctrl+Z：加入的那段拿掉、選取跟著取消", p.tracks["overlays"] == [] and t.track_selected is None)
    check("屬性面板跟著回專案頁", win.inspector_stack.currentWidget() is win.inspector_pages["project"])
    QTest.keyClick(win, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
    wait(30)
    check("Ctrl+Shift+Z：那段回來", overlays() == [(2.0, 3.0)], str(overlays()))
    p._on_track_moved("overlays", 0, 4.0)
    check("拖動", overlays() == [(4.0, 3.0)])
    p.undo()
    check("復原拖動：回到 2 秒", overlays() == [(2.0, 3.0)], str(overlays()))
    trimmed = dict(p.tracks["overlays"][0], duration=1.5)
    p._on_track_changed("overlays", 0, trimmed)
    check("修尾巴", overlays() == [(2.0, 1.5)])
    p.undo()
    check("復原修尾巴", overlays() == [(2.0, 3.0)])
    t.select_track_item("overlays", 0, seek=False)
    check("改屬性（位置）", p.set_track_props(rect=[0.62, 0.04, 0.34, 0.34]))
    p.undo()
    check("復原改屬性：位置回來、屬性面板跟著", "rect" not in p.tracks["overlays"][0]
          and p.position_combo.currentData() == "full", str(p.tracks["overlays"][0]))
    p.redo()
    check("重做改屬性", p.tracks["overlays"][0].get("rect") == [0.62, 0.04, 0.34, 0.34]
          and p.position_combo.currentData() == "top_right")
    p.undo()
    check("刪除", p.remove_track("overlays", 0) and p.tracks["overlays"] == [])
    p.undo()
    check("復原刪除：那段回來", overlays() == [(2.0, 3.0)])

    # ----- 2. 跟字幕同一條順序 -----
    p.set_cues([{"start": 0.5, "end": 1.5, "text": "第一句"}, {"start": 6.0, "end": 8.0, "text": "第二句話"}])
    check("載入字幕：紀錄清空（照舊規則）", not p.undo_btn.isEnabled())
    p._on_cue_times(0, 0.5, 1.8)
    p._on_track_moved("overlays", 0, 3.0)
    p._on_cue_times(1, 6.5, 8.0)
    p.undo()
    check("先退最後的字幕", p.cues[1]["start"] == 6.0 and overlays() == [(3.0, 3.0)])
    p.undo()
    check("再退素材", overlays() == [(2.0, 3.0)] and p.cues[0]["end"] == 1.8)
    p.undo()
    check("最後退第一個字幕", p.cues[0]["end"] == 1.5 and not p.undo_btn.isEnabled())
    p.redo()
    p.redo()
    check("重做也照順序", p.cues[0]["end"] == 1.8 and overlays() == [(3.0, 3.0)] and p.cues[1]["start"] == 6.0)
    p.redo()
    p._on_track_moved("overlays", 0, 2.0)
    check("新的修改清掉重做", not p.redo_btn.isEnabled())

    # ----- 3. 分割素材 -----
    t.select_cue(0, seek=False)
    t.select_track_item("overlays", 0, seek=False)  # 最後點素材
    seek(3.0)
    win.statusBar().clearMessage()
    check("〔分割〕：回傳第 1 段", win.split_at_playhead() == 0)
    check("切成 2＋1 秒兩段、選後段", overlays() == [(2.0, 1.0), (3.0, 2.0)] and t.track_selected == ("overlays", 1),
          str(overlays()))
    check("字幕沒動", len(p.cues) == 2)
    check("狀態列講切了哪一段", "疊加的畫面第 1 段切成兩段" in win.statusBar().currentMessage(),
          win.statusBar().currentMessage())
    p.undo()
    check("復原：合回一段", overlays() == [(2.0, 3.0)], str(overlays()))
    t.select_track_item("overlays", 0, seek=False)
    seek(7.0)
    check("播放頭不在素材裡：切不了", win.split_at_playhead() == -1 and overlays() == [(2.0, 3.0)]
          and "不能分割" in win.statusBar().currentMessage())
    seek(2.5)
    t.setFocus()
    QTest.keyClick(t, Qt.Key_B, Qt.ControlModifier)
    wait(30)
    check("Ctrl+B：一樣切素材", overlays() == [(2.0, 0.5), (2.5, 2.5)], str(overlays()))
    p.undo()
    seek(7.0)
    t.select_track_item("overlays", 0, seek=False)
    t.select_cue(1, seek=False)  # 最後點字幕
    check("最後點字幕：照舊切字幕", win.split_at_playhead() == 1 and len(p.cues) == 3 and overlays() == [(2.0, 3.0)])
    p.undo()
    seek(1.0)
    check("加入音樂", p.add_track("music", song) and len(p.tracks["music"]) == 1)
    t.select_track_item("music", 0, seek=False)
    check("音樂開循環", p.set_track_props(loop=True))
    seek(4.0)
    check("循環的音樂：切不了、講原因", win.split_at_playhead() == -1 and len(p.tracks["music"]) == 1
          and "循環" in win.statusBar().currentMessage(), win.statusBar().currentMessage())
    p.set_track_props(loop=False)
    check("關掉循環就切得了", win.split_at_playhead() == 0 and len(p.tracks["music"]) == 2
          and p.tracks["music"][1]["in"] == 3.0 and p.tracks["music"][0]["volume"] == p.tracks["music"][1]["volume"],
          str(p.tracks["music"]))
    p.undo()
    p.undo()
    p.undo()  # 切、關循環、開循環
    p.undo()  # 加入音樂
    check("音樂的四步都退得回去", p.tracks["music"] == [])
    saved_cues = list(p.cues)
    p.set_cues([])
    t.select_cue(-1, seek=False)
    t.select_track_item("overlays", 0, seek=False)
    win._update_timeline_tools()
    check("沒有字幕、選了素材：〔分割〕能按", win.split_tool.isEnabled())
    t.select_track_item("overlays", -1, seek=False)
    win._update_timeline_tools()
    check("沒有字幕、沒選素材：〔分割〕不能按", not win.split_tool.isEnabled())
    p.set_cues(saved_cues)

    # ----- 4. 畫面調整的小視窗 -----
    seek(6.0)
    p.add_track("overlays", still)  # 第 2 段：6～9 秒
    dialog = p.show_picture_dialog("overlay")
    check("小視窗調第 2 段", dialog is not None and dialog.target == ("overlays", 1))
    t.select_track_item("overlays", 0, seek=False)
    seek(3.0)
    win.split_at_playhead()
    check("切第 1 段：小視窗跟著選取改調後段（第 2 段）", dialog.target == ("overlays", 1), str(dialog.target))
    p.undo()  # 合回
    check("復原合回：選取的第 2 段還在，小視窗照舊調它", dialog.target == ("overlays", 1)
          and len(p.tracks["overlays"]) == 2, str(dialog.target))
    p.undo()  # 拿掉 6 秒那段
    check("復原到那段不在了：選取取消、小視窗回到調主片", dialog.target == "main" and t.track_selected is None
          and len(p.tracks["overlays"]) == 1, str(dialog.target))
    dialog.close()

    # ----- 5. 換片子 -----
    p._on_cue_times(0, 0.5, 1.9)
    p.open_video(other)
    check("換片子：素材清空", wait_until(lambda: p.media_duration() > 0) and p.tracks["overlays"] == [])
    check("換片子：素材的舊紀錄拿掉，下一步復原是字幕", p.history.next_kind() == "times"
          and all(e[0] != "tracks" for e in p.history._done + p.history._undone))
    p.undo()
    check("Ctrl+Z 退的是字幕、不會把上一支的素材套回來", p.cues[0]["end"] == 1.8 and p.tracks["overlays"] == [])
    win.close()

    # ----- 6. 四頁籤 -----
    qt_app.apply_theme(app, "light")
    win2 = qt_app.MainWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    win2.show()
    p2 = win2.player_panel
    p2._ask_discard = lambda *a, **k: "discard"
    p2._ask_project_discard = lambda *a, **k: "discard"
    p2.open_video(main)
    wait_until(lambda: p2.media_duration() > 0)
    p2.add_track("overlays", still)
    p2.undo()
    check("四頁籤：加入的素材也能復原", p2.tracks["overlays"] == [] and not p2.undo_btn.isEnabled())
    win2.close()
    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("素材軌的復原與分割（E-3b）測試全數通過。")
