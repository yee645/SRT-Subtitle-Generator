# -*- coding: utf-8 -*-
"""
剪輯器版面 E-9i：屬性面板「專案」頁那行狀態一項一行（之前在窄的面板裡折成「字幕：demo.srt，」／「5 句」）。

1. 剪輯器：沒開影片寫兩行（還沒開啟影片／字幕：尚未載入）；開了影片、有字幕也是一項一行，每一行都放得下（沒有再折）。
2. 四頁籤照舊：同一個元件放在底下一整行，用全形空白隔開，不換行。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過狀態一項一行")
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

    main = os.path.join(tmp, "訪談剪輯第一集.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-t", "3",
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", main], check=True)
    cues = [{"start": 0.5, "end": 1.5, "text": "第一句"}, {"start": 2.0, "end": 2.8, "text": "第二句"}]

    def lines_fit(label):
        """每一行都放得下：畫出來的高度＝行數 × 行高（沒有哪一行又被折一次）。"""
        n = len(label.text().split("\n"))
        need = label.heightForWidth(label.width())
        return need <= n * label.fontMetrics().lineSpacing() + 2, f"{n} 行、要 {need}px"

    # ----- 1 -----
    ed.apply_initial_theme(app, "dark")
    win = ed.EditorWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    win.resize(1440, 900)
    win.show()
    wait(100)
    p = win.player_panel
    lab = p.info_label
    check("沒開影片：兩行（還沒開啟影片／字幕：尚未載入）", lab.text() == "還沒開啟影片。\n字幕：尚未載入", repr(lab.text()))
    p.open_video(main)
    waited = 0
    while p.media_duration() <= 0 and waited < 20000:
        wait(50)
        waited += 50
    p.set_cues(cues)
    wait(80)
    rows = lab.text().split("\n")
    check("開了影片、有字幕：一項一行", len(rows) == 2 and rows[0].startswith("影片：訪談剪輯第一集.mp4")
          and rows[1].startswith("字幕：") and "2 句" in rows[1], repr(lab.text()))
    check("沒有哪一行停在「，」（之前折在逗號後面）", not any(r.endswith("，") for r in rows), repr(lab.text()))
    check("看得到、每一行都放得下", lab.isVisible() and lines_fit(lab)[0], lines_fit(lab)[1])

    # ----- 2 -----
    tabs = qt_app.MainWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    tp = tabs.player_panel
    check("四頁籤：沒開影片照舊（一行、沒有換行）", tp.info_label.text() == "還沒開啟影片。", repr(tp.info_label.text()))
    tp.set_cues(cues)
    wait(30)
    check("四頁籤：有字幕也不換行", "\n" not in tp.info_label.text() and "　字幕：" in tp.info_label.text(),
          repr(tp.info_label.text()))

    for w in (win, tabs):
        w.player_panel.shutdown()
        w.close()
    wait(50)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("狀態一項一行（E-9i）測試全數通過。")
