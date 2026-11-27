# -*- coding: utf-8 -*-
"""
剪輯器版面 E-9a：停用的樣子一致（gui_qt/theme.py 的 :disabled 規則）。

看真的畫出來的像素（不是只看樣式表字串），深淺兩色都量：
1. 滑桿：能調時左半段是強調色；停用時整條沒有強調色、左半段換成 text.muted。
2. 字（QLabel、勾選框的字）：能調時是 text.primary，停用時是 text.muted。
3. 數字框、下拉選單：停用時字是 text.muted、底退成 bg.panel（能調時是 bg.raised）。
4. 剪輯器沒開影片：屬性面板的畫面調整整組停用，畫出來沒有強調色；開了影片就有。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過停用的樣子")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
    from PySide6.QtGui import QColor  # noqa: E402
    from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QLabel, QSlider, QSpinBox,  # noqa: E402
                                   QVBoxLayout, QWidget)
    from PySide6.QtCore import Qt  # noqa: E402

    import config  # noqa: E402
    from gui_qt import editor as ed  # noqa: E402
    from gui_qt import theme as theme_mod  # noqa: E402
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

    def near(a, b, tol=24):
        return max(abs(x - y) for x, y in zip(a, b)) <= tol

    def pixels(widget, right_margin=0):
        """畫出來的每一點；right_margin：右邊留掉幾個像素（數字框的上下箭頭、下拉箭頭是圖，不算字）。"""
        img = widget.grab().toImage()
        return [img.pixelColor(x, y).getRgb()[:3] for y in range(img.height()) for x in range(img.width() - right_margin)]

    def has(widget, color, tol=24):
        return any(near(p, color, tol) for p in pixels(widget))

    def ink(widget, bg, right_margin=0):
        """畫出來的字是什麼顏色：離底色最遠的那一點（字夠大，最濃的那一點就是字的顏色）。"""
        return max(pixels(widget, right_margin), key=lambda p: sum(abs(x - y) for x, y in zip(p, bg)))

    def sample(widget, x, y):
        img = widget.grab().toImage()
        return img.pixelColor(x, y).getRgb()[:3]

    main = os.path.join(tmp, "main.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-t", "4",
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", main], check=True)

    for theme in ("dark", "light"):
        ed.apply_initial_theme(app, theme)
        tok = {k: rgb(v) for k, v in designtokens.TOKENS[theme].items()}
        box = QWidget()
        box.setStyleSheet(theme_mod.stylesheet(theme))  # 跟剪輯器一樣：樣式表掛在最外層
        col = QVBoxLayout(box)
        label = QLabel("亮度亮度")
        check_box = QCheckBox("左右翻")
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(80)
        slider.setFixedWidth(160)
        spin = QSpinBox()
        spin.setSuffix("%")
        spin.setValue(88)
        spin.setFixedWidth(90)
        combo = QComboBox()
        combo.addItems(["不轉轉"])
        for w in (label, check_box, slider, spin, combo):
            col.addWidget(w)
        box.resize(260, 220)
        box.show()
        wait(60)

        # ----- 能調 -----
        check(f"{theme}：能調的滑桿有強調色", has(slider, tok["accent"]))
        panel_bg = sample(box, 2, 2)
        check(f"{theme}：能調的字是主色", near(ink(label, panel_bg), tok["text.primary"]), str(ink(label, panel_bg)))
        check(f"{theme}：能調的數字框底是 bg.raised", near(sample(spin, 6, 3), tok["bg.raised"], 8), str(sample(spin, 6, 3)))

        # ----- 停用 -----
        box.setEnabled(False)
        wait(60)
        check(f"{theme}：停用的滑桿沒有強調色", not has(slider, tok["accent"], 40))
        check(f"{theme}：停用的滑桿左半段是 text.muted", near(sample(slider, 40, slider.height() // 2), tok["text.muted"]),
              str(sample(slider, 40, slider.height() // 2)))
        check(f"{theme}：停用的字是 text.muted", near(ink(label, panel_bg), tok["text.muted"]), str(ink(label, panel_bg)))
        check(f"{theme}：停用的勾選框字是 text.muted", near(ink(check_box, panel_bg), tok["text.muted"]),
              str(ink(check_box, panel_bg)))
        spin_bg = sample(spin, 6, 3)
        check(f"{theme}：停用的數字框底退成 bg.panel", near(spin_bg, tok["bg.panel"], 8), str(spin_bg))
        check(f"{theme}：停用的數字框字是 text.muted", near(ink(spin, spin_bg, 24), tok["text.muted"]), str(ink(spin, spin_bg, 24)))
        combo_bg = sample(combo, 6, 3)
        check(f"{theme}：停用的下拉選單底是 bg.panel、字是 text.muted", near(combo_bg, tok["bg.panel"], 8)
              and near(ink(combo, combo_bg, 26), tok["text.muted"]), f"{combo_bg} {ink(combo, combo_bg, 26)}")
        box.close()

    # ----- 4 -----
    ed.apply_initial_theme(app, "dark")
    tok = {k: rgb(v) for k, v in designtokens.TOKENS["dark"].items()}
    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["theme"] = "dark"
    win = ed.EditorWindow(cfg)
    win.resize(1440, 900)
    win.show()
    wait(100)
    p = win.player_panel
    mp = win.main_picture
    check("沒開影片：畫面調整整組停用、畫出來沒有強調色", not mp.isEnabled() and not has(mp, tok["accent"], 40))
    p.open_video(main)
    waited = 0
    while p.media_duration() <= 0 and waited < 20000:
        wait(50)
        waited += 50
    wait(80)
    check("開了影片：能調、滑桿有強調色", mp.isEnabled() and has(mp, tok["accent"]),
          str(sorted(set(QColor(*px).name() for px in pixels(mp.sliders["brightness"])))[:12]))
    p.shutdown()
    win.close()
    wait(50)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("停用的樣子（E-9a）測試全數通過。")
