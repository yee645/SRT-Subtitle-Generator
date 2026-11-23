# -*- coding: utf-8 -*-
"""
3.0 第 11 項第三十四階段：執行中切換深淺色（gui_qt/app.py 的〔切換為深色／淺色〕）。

1. 狀態列右邊有切換按鈕，字跟一般版一樣（淺色時寫「切換為深色」、深色時寫「切換為淺色」）。
2. 按一下：整個視窗真的換色（量視窗底色的亮度）、按鈕字跟著換、記進這次開啟的設定（theme）、狀態列講一句。
3. 時間軸跟著換：底色、**字幕列的底色**（以前切換後會留著舊的顏色）、播放頭；字幕塊照新的配色。
4. 再按一下：換回來（設定也回來）。
5. 不認得的主題值當淺色（同一般版）：按鈕寫「切換為深色」，按了變深色。
6. 全程沒寫 config.json（關掉 Qt 版時才存，test_qt_settings_save.py 驗）。
"""
import copy
import os
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

if PySide6 is None:
    print("SKIP 這個環境沒有 PySide6：略過深淺色切換")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtGui import QPalette  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def window_lightness(win):
        return win.palette().color(QPalette.Window).lightness()

    def pixel_lightness(widget, x, y):
        return widget.grab().toImage().pixelColor(x, y).lightness()

    qt_app.apply_theme(app, "light")
    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["theme"] = "light"
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.tabs.setCurrentIndex(1)
    win.show()
    wait(100)
    panel = win.player_panel
    panel._ask_discard = lambda *a, **k: "discard"
    panel._ask_project_discard = lambda *a, **k: "discard"
    panel.set_cues([{"start": 0.0, "end": 1.0, "text": "大家好"}])
    wait(100)
    timeline = panel.timeline

    # ----- 1 -----
    btn = win.theme_btn
    check("狀態列右邊有切換按鈕、淺色時寫「切換為深色」", btn.isVisible() and btn.text() == "切換為深色"
          and btn.parent() is win.statusBar())
    check("一開始是淺色", window_lightness(win) > 200)
    light_row = timeline.cue_bg.brush().color().lightness()

    # ----- 2 -----
    QTest.mouseClick(btn, Qt.LeftButton)
    wait(100)
    check("按一下：視窗真的換成深色", window_lightness(win) < 100, str(window_lightness(win)))
    check("按鈕字跟著換、記進設定、狀態列講一句", btn.text() == "切換為淺色" and cfg["theme"] == "dark"
          and win.statusBar().currentMessage() == "已切換為深色主題。")
    check("畫面真的變暗（量逐句校對清單的像素）", pixel_lightness(win.cue_panel.table, 5,
                                                   win.cue_panel.table.height() - 5) < 100)

    # ----- 3 -----
    dark_row = timeline.cue_bg.brush().color().lightness()
    check("時間軸：字幕列底色跟著換（以前會留著淺色）", dark_row < 100 and dark_row != light_row,
          f"{light_row}→{dark_row}")
    check("時間軸：配色照新的調色盤", timeline.colors == tl._palette_colors(timeline)
          and timeline.colors["bg"].lightness() < 100)
    check("時間軸：播放頭的筆照新的配色", timeline.playhead.pen().color() == timeline.colors["playhead"])
    check("時間軸：字幕塊照新的配色（深色版的字幕塊顏色）",
          all(item.brush().color() == timeline.colors["cue"] for item, _label in timeline.cue_items
              if hasattr(item, "brush")) and timeline.colors["cue"].name() == "#c9892f")

    # ----- 4 -----
    QTest.mouseClick(btn, Qt.LeftButton)
    wait(100)
    check("再按一下：換回淺色", window_lightness(win) > 200 and btn.text() == "切換為深色"
          and cfg["theme"] == "light" and win.statusBar().currentMessage() == "已切換為淺色主題。")
    check("時間軸字幕列也換回來", timeline.cue_bg.brush().color().lightness() == light_row)

    # ----- 5 -----
    check("按鈕字的規則（同一般版）", qt_app.theme_button_text("dark") == "切換為淺色"
          and qt_app.theme_button_text("light") == "切換為深色" and qt_app.theme_button_text("怪") == "切換為深色")
    cfg2 = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg2["theme"] = "怪值"
    win2 = qt_app.MainWindow(cfg2)
    win2.show()
    wait(50)
    check("不認得的值當淺色：寫「切換為深色」", win2.theme_btn.text() == "切換為深色")
    new = win2.toggle_theme()
    wait(50)
    check("按了變深色", new == "dark" and cfg2["theme"] == "dark" and window_lightness(win2) < 100,
          str(window_lightness(win2)))
    qt_app.apply_theme(app, "light")
    p2 = win2.player_panel
    p2._ask_discard = lambda *a, **k: "discard"
    p2._ask_project_discard = lambda *a, **k: "discard"
    win2.close()

    # ----- 6 -----
    check("全程沒寫 config.json", not os.path.exists(config.CONFIG_PATH))
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 深淺色切換測試全數通過。")
