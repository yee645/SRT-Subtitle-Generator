# -*- coding: utf-8 -*-
"""
剪輯器版面 E-9c：字幕與素材同時選著時，只有作用中的那個畫實心粗框（gui_qt/timeline.py 的 selection_active）。

1. 只選一句字幕：那句實心粗框、亮底。
2. 再點一段疊加：疊加實心粗框；字幕那句還選著，但換成虛線細框、底色照常。屬性面板是素材頁。
3. 再點回那句字幕：反過來（字幕實心、疊加虛線）；屬性面板是字幕頁。
4. 取消素材的選取：剩下的字幕回到實心。
5. 兩邊同時都是實心的情況不會出現（每一步都量）。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過作用中的選取")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
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

    def run(*args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)

    main = os.path.join(tmp, "main.mp4")
    still = os.path.join(tmp, "logo.png")
    run("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-t", "12", "-pix_fmt", "yuv420p", "-c:v", "libx264", main)
    run("-f", "lavfi", "-i", "testsrc2=size=160x90", "-frames:v", "1", still)

    win = ed.EditorWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    win.resize(1440, 900)
    win.show()
    wait(80)
    p = win.player_panel
    p._ask_discard = lambda *a, **k: "discard"
    p._ask_project_discard = lambda *a, **k: "discard"
    t = p.timeline
    p.open_video(main)
    waited = 0
    while (p.media_duration() <= 0 or t.duration <= 0) and waited < 20000:
        wait(50)
        waited += 50
    p.set_cues([{"start": 1.0, "end": 3.0, "text": "第一句"}, {"start": 4.0, "end": 6.0, "text": "第二句"}])
    check("（準備）開好影片、放一段疊加", p.add_track("overlays", still, at=7.0))
    t.select_track_item("overlays", -1, seek=False)  # 放完會選著那一段：先取消，從什麼都沒選開始
    wait(30)

    def cue_look(i=1):
        item = t.cue_items[i][0]
        pen = item.pen()
        return pen.widthF(), pen.style(), item.brush().color().name()

    def track_look():
        pen = t.track_items["overlays"][0].pen()
        return pen.widthF(), pen.style()

    SOLID, DASH = Qt.SolidLine, Qt.DashLine
    sel_brush = t.colors["cue_sel"].name()
    plain_brush = t.colors["cue"].name()

    def never_both():
        return not (cue_look()[:2] == (2, SOLID) and track_look() == (2, SOLID))

    # ----- 1 -----
    t.select_cue(1, seek=False)
    wait(20)
    check("只選字幕：實心粗框、亮底", cue_look() == (2, SOLID, sel_brush) and t.selection_active("cue"), str(cue_look()))
    check("疊加沒選：一般的框", track_look()[0] == 1 and track_look()[1] == SOLID, str(track_look()))

    # ----- 2 -----
    t.select_track_item("overlays", 0, seek=False)
    wait(20)
    check("再點疊加：疊加實心粗框", track_look() == (2, SOLID) and t.selection_active("track"))
    check("字幕還選著但換成虛線細框、底色照常", t.selected == 1 and cue_look() == (1, DASH, plain_brush)
          and not t.selection_active("cue"), str(cue_look()))
    check("虛線用選取框的顏色", t.cue_items[1][0].pen().color() == t.colors["cue_sel_pen"])
    check("屬性面板跟作用中的走：素材頁", win.inspector_mode() == "track", win.inspector_mode())
    check("不會兩邊都實心（2）", never_both())

    # ----- 3 -----
    t.select_cue(1, seek=False)
    wait(20)
    check("點回字幕：字幕實心、疊加虛線", cue_look() == (2, SOLID, sel_brush) and track_look() == (1, DASH),
          f"{cue_look()} {track_look()}")
    check("疊加的虛線用選取框的顏色", t.track_items["overlays"][0].pen().color() == t.colors["track_sel_pen"])
    check("屬性面板：字幕頁", win.inspector_mode() == "cue", win.inspector_mode())
    check("不會兩邊都實心（3）", never_both())

    # ----- 4 -----
    t.select_track_item("overlays", 0, seek=False)
    wait(20)
    t.select_track_item("overlays", -1, seek=False)
    wait(20)
    check("取消素材：剩下的字幕回到實心", cue_look() == (2, SOLID, sel_brush) and t.selection_active("cue"), str(cue_look()))
    t.select_cue(-1, seek=False)
    t.select_track_item("overlays", 0, seek=False)
    wait(20)
    check("只選素材：實心", track_look() == (2, SOLID) and cue_look()[0] == 1 and cue_look()[1] == SOLID)

    p.shutdown()
    win.close()
    wait(50)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("作用中的選取（E-9c）測試全數通過。")
