# -*- coding: utf-8 -*-
"""
3.0 第 2 項第三階段：播放器疊加層預覽逐字動態字幕（karaoke／word）。

核心規則（這一刻顯示什麼）在 test_dynamic_preview.py；這裡驗畫出來的樣子：

1. 播放器：樣式設 karaoke → 跳到不同時間，亮起的字跟著換；word → 只有當前的字；
   off → 整句；沒有逐字資料的句子 → 整句；換樣式立刻重畫。
2. 畫面：亮起的字是重點色（抓像素）；word 模式剛出現時縮小，**以對齊點為中心**
   （置底時底邊不動、置頂時頂邊不動）。
3. **跟真的燒錄比對**（ffmpeg＋libass、文泉驛字型）：karaoke 亮起那個字的範圍、
   word 模式長到一半與長完的字的範圍，四邊都在 4px 內。
"""
import os
import shutil
import subprocess
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
    print("SKIP 這個環境沒有 PySide6：略過動態字幕預覽的畫面（核心規則在 test_dynamic_preview.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QRectF, QTimer  # noqa: E402
    from PySide6.QtGui import QColor, QFontDatabase, QImage, QPainter  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from gui_qt.player import OutlinedText, place_subtitle  # noqa: E402
    from subtitle.exporter import cues_to_ass, dynamic_frame  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = tmp

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait_until(cond, timeout_ms=10000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(50)
            waited += 50
        return cond()

    # 時間都在 25 fps 的影格上（燒錄比對時抽得到剛好那一格）
    WORDS = [{"word": "今天", "start": 1.0, "end": 1.4}, {"word": "天氣", "start": 1.4, "end": 1.8},
             {"word": "Hello", "start": 1.8, "end": 2.2}, {"word": "world", "start": 2.2, "end": 3.0}]
    CUES = [{"start": 1.0, "end": 3.0, "text": "今天天氣 Hello world", "words": WORDS},
            {"start": 3.5, "end": 4.5, "text": "沒有逐字資料的句子"}]

    # ----- 1. 播放器 -----
    video = os.path.join(tmp, "d.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=gray:s=320x180:r=25:d=6",
                    "-f", "lavfi", "-i", "sine=d=6", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", video], check=True)
    win = qt_app.MainWindow({"subtitle_style": {"dynamic_mode": "karaoke"}})
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 800)
    win.show()
    panel = win.player_panel
    panel.open_video(video)
    wait_until(lambda: panel.player.duration() > 5000)
    panel.set_cues(CUES)

    def at(ms):
        panel.player.setPosition(ms)
        wait_until(lambda: abs(panel.player.position() - ms) < 30, 5000)
        panel._show_at(ms)  # 位置訊號可能比 setPosition 晚到：直接照這個時間畫
        wait(20)

    def lit():
        segs = panel.current_subtitle_segments()
        return [p for p, on in segs if on] if segs is not None else None

    at(1200)
    check("karaoke 1.2 秒：整句都在、亮起的是「今天」",
          panel.current_subtitle_text() == "今天天氣Hello world" and lit() == ["今天"],
          f"{panel.current_subtitle_text()!r} {lit()}")
    at(2000)
    check("karaoke 2.0 秒：亮起的換成「Hello」", lit() == ["Hello"], str(lit()))
    at(3800)
    check("沒有逐字資料的句子 → 照一般整句、沒有片段",
          panel.current_subtitle_text() == "沒有逐字資料的句子" and panel.current_subtitle_segments() is None,
          repr(panel.current_subtitle_text()))
    at(2400)
    panel.set_style({"dynamic_mode": "word"})
    check("換成 word 樣式 → 立刻只剩當前的字「world」", panel.current_subtitle_text() == "world",
          repr(panel.current_subtitle_text()))
    at(2200)
    check("word 剛出現的那一刻縮成 0.8", abs(panel.subtitle_item.scale() - 0.8) < 1e-6,
          str(panel.subtitle_item.scale()))
    at(2280)
    check("80 ms 後長到 0.933", abs(panel.subtitle_item.scale() - (0.8 + 0.2 * 80 / 120)) < 0.01,
          str(panel.subtitle_item.scale()))
    at(2600)
    check("120 ms 以後是原本大小", abs(panel.subtitle_item.scale() - 1.0) < 1e-6, str(panel.subtitle_item.scale()))
    at(2200)  # 回到縮成 0.8 的那一刻再換回 off：縮放要一起復原
    panel.set_style({"dynamic_mode": "off"})
    check("換回 off → 立刻變整句", panel.current_subtitle_text() == "今天天氣 Hello world"
          and panel.current_subtitle_segments() is None and panel.subtitle_item.scale() == 1.0,
          f"{panel.current_subtitle_text()!r} {panel.subtitle_item.scale()}")

    # ----- 2. 畫面 -----
    def render(style, seconds, w=640, h=360):
        """照播放器的畫法把 seconds 那一刻的動態字幕畫在黑底上。"""
        img = QImage(w, h, QImage.Format_RGB32)
        img.fill(QColor(0, 0, 0))
        it = OutlinedText()
        frame = dynamic_frame(CUES[0], style.get("dynamic_mode", "off"), seconds)
        if frame is None:
            it.setText(CUES[0]["text"])
        else:
            it.set_segments(frame["segments"], frame["scale"])
        place_subtitle(it, QRectF(0, 0, w, h), style)
        p = QPainter(img)
        p.setTransform(it.sceneTransform())
        it.paint(p, None)
        p.end()
        return img, it

    def bbox(img, pred):
        xs, ys = [], []
        for y in range(img.height()):
            for x in range(img.width()):
                if pred(QColor(img.pixel(x, y))):
                    xs.append(x)
                    ys.append(y)
        return (min(xs), min(ys), max(xs), max(ys)) if xs else None

    def is_blue(c):
        return c.blue() > 150 and c.red() < 90 and c.green() < 90

    def is_ink(c):
        return c.red() + c.green() + c.blue() > 60

    base = {"font_size": 60, "text_color": "#FFFFFF", "stroke_color": "#808080", "emphasis_color": "#0000FF"}
    img, _it = render(dict(base, dynamic_mode="karaoke"), 2.0)
    blue, ink = bbox(img, is_blue), bbox(img, is_ink)
    width = (ink[2] - ink[0]) if ink else 0
    check("karaoke 畫面：亮起的字是重點色（藍），只佔整句中間的一段（前面有「今天天氣」、後面有「world」）",
          blue is not None and ink is not None and blue[0] > ink[0] + 0.3 * width
          and blue[2] < ink[2] - 0.15 * width and (blue[2] - blue[0]) < 0.4 * width,
          f"藍 {blue} 整句 {ink}")
    img_first, _ = render(dict(base, dynamic_mode="karaoke"), 1.2)
    blue_first = bbox(img_first, is_blue)
    check("karaoke 1.2 秒：亮起的換成句首的「今天」（藍色從整句左邊開始）",
          blue_first is not None and abs(blue_first[0] - ink[0]) <= 3 and blue_first[2] < blue[0],
          f"藍 {blue_first} 整句 {ink}")
    img_off, _ = render(dict(base, dynamic_mode="off"), 2.0)
    check("off 畫面：沒有藍色（沒開重點字）", bbox(img_off, is_blue) is None)

    for pos_y, edge, name in ((0.88, 3, "置底：底邊不動"), (0.15, 1, "置頂：頂邊不動")):
        # 字要夠大，「以中心縮放」與「以對齊點縮放」的差別（高度的 10%）才看得出來
        big = dict(base, dynamic_mode="word", position_y=pos_y, font_size=120)
        small, it_s = render(big, 1.8, 1280, 720)   # 0.8
        full, it_f = render(big, 2.0, 1280, 720)    # 1.0
        # 對齊看的是字的行框（含字身下方的留白），跟 libass 一樣——所以縮放後行框的
        # 那一邊要一模一樣；墨水的邊會因為留白跟著縮而差幾像素（以中心縮放時差 5～8px）。
        box_s = it_s.mapRectToScene(it_s.text_rect())
        box_f = it_f.mapRectToScene(it_f.text_rect())
        line_s = box_s.bottom() if edge == 3 else box_s.top()
        line_f = box_f.bottom() if edge == 3 else box_f.top()
        a, b = bbox(small, is_ink), bbox(full, is_ink)
        check(f"word 彈出以對齊點為中心縮放（{name}、水平置中）",
              a and b and abs(line_s - line_f) < 0.5 and abs(a[edge] - b[edge]) <= 4
              and abs((a[0] + a[2]) - (b[0] + b[2])) <= 3 and (a[2] - a[0]) < 0.9 * (b[2] - b[0]),
              f"行框 {line_s:.1f} vs {line_f:.1f}；墨水 0.8 倍 {a}、原大 {b}")

    # ----- 3. 跟真的燒錄比對 -----
    FONT = "WenQuanYi Zen Hei"
    has_libass = bool(shutil.which("ffmpeg")) and " ass " in subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    if not has_libass or FONT not in QFontDatabase.families():
        print(f"SKIP 沒有 ffmpeg（libass）或 {FONT} 字型：略過與真的燒錄比對")
    else:
        W, H = 1280, 720
        cases = [
            ("karaoke 2.0 秒，亮起的「Hello」", "karaoke", 2.0, is_blue),
            ("karaoke 1.2 秒，亮起的「今天」", "karaoke", 1.2, is_blue),
            ("word 1.80 秒（剛出現，0.8 倍、大字）", "word", 1.80, is_ink),
            ("word 1.88 秒（長到 0.933）", "word", 1.88, is_ink),
            ("word 2.6 秒（原大）", "word", 2.6, is_ink),
            ("word 置頂 2.28 秒", "word", 2.28, is_ink),
        ]
        for name, mode, seconds, pred in cases:
            style = dict(base, font_family=FONT, dynamic_mode=mode, font_size=96 if "大字" in name else 48)
            if "置頂" in name:
                style["position_y"] = 0.15
            ass = os.path.join(tmp, "burn.ass")
            with open(ass, "w", encoding="utf-8") as fh:
                fh.write(cues_to_ass(CUES[:1], style))
            png = os.path.join(tmp, "burn.png")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            f"color=black:s={W}x{H}:r=25:d=4", "-vf", f"ass={ass}",
                            "-ss", f"{seconds:.2f}", "-frames:v", "1", png], check=True, cwd=tmp)
            burned = bbox(QImage(png), pred)
            ours = bbox(render(style, seconds, W, H)[0], pred)
            diff = [ours[i] - burned[i] for i in range(4)] if burned and ours else None
            check(f"跟真的燒錄比對「{name}」：範圍四邊都在 4px 內",
                  diff is not None and max(abs(d) for d in diff) <= 4,
                  f"燒錄 {burned} 預覽 {ours} 差 {diff}")

    win.close()
    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 播放器逐字動態字幕預覽測試全數通過。")
