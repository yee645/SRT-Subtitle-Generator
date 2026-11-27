# -*- coding: utf-8 -*-
"""
剪輯器版面 E-9g：還沒開影片時，時間軸的縮放（拉近、拉遠、整支、縮放滑桿）停用（editor-ui-review 清單第 6 條：
空狀態的按鈕是不是正確地停用）。

1. 沒開影片：四個都停用；〔吸附〕是偏好設定，照樣能按；時間軸顯示空狀態。
2. 開了影片：四個都能用，拉近真的有作用。
3. 四頁籤照舊：沒開影片時這三顆按鈕跟原本一樣能按。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過空狀態的縮放")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
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

    main = os.path.join(tmp, "main.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-t", "4",
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", main], check=True)

    # ----- 3（先開四頁籤，看原本的樣子）-----
    tabs = qt_app.MainWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    tp = tabs.player_panel
    check("四頁籤：沒開影片時縮放按鈕照舊能按",
          all(b.isEnabled() for b in (tp.zoom_in_btn, tp.zoom_out_btn, tp.fit_btn)))

    ed.apply_initial_theme(app, "dark")
    win = ed.EditorWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    win.resize(1440, 900)
    win.show()
    wait(100)
    p = win.player_panel
    zoom = (p.zoom_out_btn, win.zoom_slider, p.zoom_in_btn, p.fit_btn)

    # ----- 1 -----
    check("（準備）四個都在時間軸工具列上", tuple(win.timeline_zoom_controls) == zoom
          and all(w.isVisible() for w in zoom))
    check("沒開影片：拉近、拉遠、整支、縮放滑桿都停用", not any(w.isEnabled() for w in zoom),
          str([w.isEnabled() for w in zoom]))
    check("時間軸是空狀態", win.timeline_stack.currentIndex() == 0)
    snap = getattr(win, "snap_tool", None) or getattr(p, "snap_box", None)
    check("〔吸附〕是偏好設定，照樣能按", snap is not None and snap.isEnabled())

    # ----- 2 -----
    p.open_video(main)
    waited = 0
    while p.timeline.duration <= 0 and waited < 20000:
        wait(50)
        waited += 50
    wait(80)
    check("開了影片：四個都能用", all(w.isEnabled() for w in zoom), str([w.isEnabled() for w in zoom]))
    before = p.timeline.px_per_sec
    p.zoom_in_btn.click()
    wait(30)
    check("拉近真的有作用", p.timeline.px_per_sec > before, f"{before} → {p.timeline.px_per_sec}")

    for w in (win, tabs):
        w.player_panel.shutdown()
        w.close()
    wait(50)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("空狀態的縮放（E-9g）測試全數通過。")
