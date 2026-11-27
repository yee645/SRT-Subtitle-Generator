# -*- coding: utf-8 -*-
"""
剪輯器版面 E-9f：預覽下面的時間碼不被切掉（editor-ui-review：「有沒有字被截掉」）。

1. 寬度在樣式表（等寬字）套上之後量：預設視窗寫「播放頭 / 片長」，整串放得下。
2. 預覽區變窄（左側面板開著、視窗變小）就只寫播放頭，片長放提示；變回來又寫完整的。
3. 左右兩邊一樣寬，播放鍵在預覽區正中間（差不到 2 像素）。
4. 換主題之後重量一次，還是放得下。
"""
import copy
import os
import shutil
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過時間碼的寬度")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QPoint, QTimer  # noqa: E402
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

    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["theme"] = "dark"
    ed.apply_initial_theme(app, "dark")
    win = ed.EditorWindow(cfg)
    lab = win.timecode_label
    pre = lab.width()
    lab.ensurePolished()
    need = lab.fontMetrics().horizontalAdvance(lab.text())
    check("還沒顯示就量對了（用樣式表的字量，不是預設字）", pre >= need, f"{pre} < {need}")
    win.resize(1440, 900)
    win.show()
    wait(150)
    panel = win._preview_panel

    def fits():
        return lab.fontMetrics().horizontalAdvance(lab.text()) <= lab.contentsRect().width()

    def centered():
        mid = win.play_tool.mapTo(panel, QPoint(win.play_tool.width() // 2, 0)).x()
        return abs(mid - panel.width() // 2) <= 2, f"{mid} vs {panel.width() // 2}"

    # ----- 1 -----
    check("預設視窗：寫播放頭 / 片長", " / " in lab.text() and not win._timecode_short, lab.text())
    check("整串放得下（等寬字量的）", fits(), f"{lab.fontMetrics().horizontalAdvance(lab.text())} > {lab.width()}")
    check("提示裡有完整的時間", lab.toolTip().startswith(ed.TIMECODE_TIP) and " / " in lab.toolTip(), lab.toolTip())
    ok, info = centered()
    check("播放鍵在預覽區正中間", ok, info)
    full_width = lab.width()

    # ----- 2 -----
    win.show_section("health")
    wait(150)
    check("完整的時間碼不把預覽區撐寬：健檢頁拿到它要的寬度、時間碼改寫短的",
          win.hsplit.sizes()[0] == ed.SECTION_WIDTH["health"] and win._timecode_short and fits(),
          f"{win.hsplit.sizes()} {lab.text()}")
    health_sizes = win.hsplit.sizes()
    win.resize(1100, 700)
    wait(200)
    check("預覽區變窄：只寫播放頭", win._timecode_short and " / " not in lab.text() and lab.text(), lab.text())
    check("變窄還是放得下", fits(), f"{lab.fontMetrics().horizontalAdvance(lab.text())} > {lab.width()}")
    check("片長放提示", " / " in lab.toolTip(), lab.toolTip())
    check("左右兩邊一樣寬", lab.width() == win._timecode_side.width(), f"{lab.width()} {win._timecode_side.width()}")
    ok, info = centered()
    check("變窄：播放鍵還是在正中間", ok, info)
    check("時間碼那一排沒有超出預覽區", win._timecode_side.mapTo(panel, QPoint(win._timecode_side.width(), 0)).x()
          <= panel.width())
    win.resize(1440, 900)
    wait(200)
    # 之前完整的時間碼撐住預覽區的最窄寬度，視窗拉回來時多的寬度都被左側面板拿走、預覽區比縮小前還窄
    check("視窗縮小再拉回來：三欄回到原本的寬度", win.hsplit.sizes() == health_sizes,
          f"{health_sizes} → {win.hsplit.sizes()}")
    win.show_section("media")
    wait(200)
    check("變回來：又寫完整的", not win._timecode_short and " / " in lab.text() and lab.width() == full_width and fits(),
          f"{lab.text()} {lab.width()}")

    # ----- 4 -----
    win.apply_editor_theme("light")
    wait(100)
    check("換主題之後還是放得下", fits() and " / " in lab.text(), lab.text())
    # 樣式表換了字（例如字放大）：換主題時重量，不是沿用舊的寬度
    from gui_qt import theme as theme_mod  # noqa: E402
    plain = theme_mod.stylesheet
    theme_mod.stylesheet = lambda name: plain(name) + "\nQLabel#timecode { font-size: 20px; }"
    narrow = lab.width()
    win.apply_editor_theme("dark")
    wait(100)
    theme_mod.stylesheet = plain
    check("樣式表的字變大：時間碼跟著變寬、還是放得下", lab.width() > narrow and fits(), f"{narrow} → {lab.width()}")
    win.apply_editor_theme("dark")
    wait(100)

    win.player_panel.shutdown()
    win.close()
    wait(50)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("時間碼的寬度（E-9f）測試全數通過。")
