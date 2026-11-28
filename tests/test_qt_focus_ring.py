# -*- coding: utf-8 -*-
"""
剪輯器版面 E-9k：鍵盤焦點看得到（按 Tab 走到按鈕上時，畫面上要看得出焦點在哪）。

之前按鈕有沒有焦點畫出來一模一樣（只有輸入欄有焦點框）。深淺兩色都量：
1. 一般按鈕、圖示按鈕（吸附、左邊圖示列）：有焦點時框線是強調色；沒焦點時沒有強調色的框。
2. 主要按鈕〔匯出〕（本身就是強調色）：有焦點時多一圈主字色的框。
3. 有焦點時按鈕不會變大變小，裡面的字與圖示也不會移動（框加粗時內距跟著減）。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過鍵盤焦點")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtGui import QColor  # noqa: E402
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

    def rgb(hex_color):
        c = QColor(hex_color)
        return c.red(), c.green(), c.blue()

    def edge_has(img, color, tol=30):
        """按鈕的上下左右邊（往內 2 像素）有沒有這個顏色。"""
        w, h = img.width(), img.height()
        pts = [(x, y) for x in range(w) for y in (0, 1, h - 2, h - 1)] + \
              [(x, y) for y in range(h) for x in (0, 1, w - 2, w - 1)]
        return any(max(abs(a - b) for a, b in zip(img.pixelColor(x, y).getRgb()[:3], color)) <= tol for x, y in pts)

    for theme in ("dark", "light"):
        cfg = copy.deepcopy(config.DEFAULT_CONFIG)
        cfg["theme"] = theme
        ed.apply_initial_theme(app, theme)
        win = ed.EditorWindow(cfg)
        win.resize(1440, 900)
        win.show()
        wait(100)
        tok = {k: rgb(v) for k, v in designtokens.TOKENS[theme].items()}
        p = win.player_panel
        cases = (("一般按鈕〔開啟影片〕", p.open_btn, "accent"),
                 ("圖示按鈕〔吸附〕", win.snap_tool, "accent"),
                 ("左邊圖示列〔字幕〕", win.rail_buttons["subtitles"], "accent"),
                 ("主要按鈕〔匯出〕", win.export_button, "text.primary"))
        for label, btn, ring in cases:
            btn.clearFocus()
            win.setFocus()
            wait(40)
            size_before, hint_before = btn.size(), btn.sizeHint()
            plain = btn.grab().toImage()
            btn.setFocus(Qt.TabFocusReason)
            wait(40)
            focused = btn.grab().toImage()
            check(f"{theme}：{label}（準備）拿到焦點", btn.hasFocus())
            check(f"{theme}：{label} 有焦點時框是 {ring}", edge_has(focused, tok[ring]))
            if ring == "accent":
                check(f"{theme}：{label} 沒焦點時沒有強調色的框", not edge_has(plain, tok["accent"]))
            else:
                check(f"{theme}：{label} 沒焦點時沒有主字色的框", not edge_has(plain, tok["text.primary"]))
            w, h = plain.width(), plain.height()
            corner = 7  # 圓角那一小塊的反鋸齒會跟著框變，不算

            def inside(x, y):
                return not ((x < corner or x >= w - corner) and (y < corner or y >= h - corner))

            inner_same = all(plain.pixelColor(x, y) == focused.pixelColor(x, y)
                             for x in range(3, w - 3) for y in range(3, h - 3) if inside(x, y))
            check(f"{theme}：{label} 有焦點時只多框，裡面的字與圖示沒有移動", inner_same)
            check(f"{theme}：{label} 有焦點時不變大變小（實際大小與想要的大小）",
                  btn.size() == size_before and btn.sizeHint() == hint_before,
                  f"{size_before} → {btn.size()}；{hint_before} → {btn.sizeHint()}")
        p.shutdown()
        win.close()
        wait(50)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("鍵盤焦點（E-9k）測試全數通過。")
