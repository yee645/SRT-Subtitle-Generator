# -*- coding: utf-8 -*-
"""
剪輯器版面 E-9h：匯出視窗左邊目錄的選取項不再多畫一層焦點框（截圖裡圓角的選取底色裡面又有一個方框）。

1. 目錄有焦點跟沒焦點時，畫出來一模一樣（選取底色已經標出現在在哪一段，不另外畫框）；深淺兩色都量。
2. 選取項照樣有 accent.soft 的底色；鍵盤上下鍵照樣換段落（焦點還在目錄上）。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過目錄的焦點框")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtGui import QColor  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import editor as ed  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import designtokens  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def near(a, b, tol=10):
        return max(abs(x - y) for x, y in zip(a, b)) <= tol

    for theme in ("dark", "light"):
        cfg = copy.deepcopy(config.DEFAULT_CONFIG)
        cfg["theme"] = theme
        ed.apply_initial_theme(app, theme)
        win = ed.EditorWindow(cfg)
        win.resize(1440, 900)
        win.show()
        wait(100)
        dialog = win.open_export()
        wait(150)
        nav = win.export_nav
        nav.setFocus()
        wait(60)
        focused = nav.viewport().grab().toImage()
        check(f"{theme}：（準備）目錄有焦點", nav.hasFocus())
        win.export_scroll.setFocus()
        wait(60)
        unfocused = nav.viewport().grab().toImage()
        diff = sum(1 for y in range(focused.height()) for x in range(focused.width())
                   if focused.pixelColor(x, y) != unfocused.pixelColor(x, y))
        check(f"{theme}：有沒有焦點畫出來一樣（沒有另外的焦點框）", diff == 0, f"{diff} 點不一樣")
        rect = nav.visualItemRect(nav.item(0))
        soft = QColor(designtokens.TOKENS[theme]["accent.soft"]).getRgb()[:3]
        at = unfocused.pixelColor(rect.left() + 2, rect.center().y()).getRgb()[:3]  # 字的左邊、還在底色裡
        check(f"{theme}：選取項照樣是 accent.soft 的底", near(at, soft), f"{at} vs {soft}")
        nav.setFocus()
        QTest.keyClick(nav, Qt.Key_Down)
        wait(60)
        check(f"{theme}：鍵盤下鍵照樣換到下一段", nav.currentRow() == 1, str(nav.currentRow()))
        dialog.close()
        win.player_panel.shutdown()
        win.close()
        wait(50)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("目錄的焦點框（E-9h）測試全數通過。")
