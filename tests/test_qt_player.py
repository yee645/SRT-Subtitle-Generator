# -*- coding: utf-8 -*-
"""
3.0 第 2 項第一階段：播放器面板，字幕疊在真的影片畫面上。

1. `subtitle/cuetime.py`（不需要 PySide6）：邊界（含開始、不含結束，與燒
   錄一致）、空檔、重疊時取開始得最晚的、長句蓋住短句、壞句略過、輸入沒
   排序、跟暴力解逐點比對；零 GUI 依賴。
2. 有 PySide6 時（offscreen）真的開 `probe_clip.mp4`＋一份真的 SRT：
   - 載入後就有畫面（暫停在第一格，不是一片黑——實際踩過）；
   - 跳到 0.5／1.0／1.5 秒，疊在畫面上的字幕分別是第一句／沒有／第二句；
   - 字幕在影片實際占的矩形裡、下半部、水平置中；
   - 換一份字幕，畫面上那句**立刻**換掉（不必等下一格或再跳一次）；
   - 真的播到結尾；
   - 白字黑邊：字的白色部分沒有被黑邊吃掉（實際踩過：描邊畫在字上面）。
3. 第二階段：`burn_layout`（不需要 PySide6）與 `cues_to_ass` 的對齊、邊距一
   致；有 PySide6＋ffmpeg（libass）＋文泉驛字型時，**跟真的燒錄出來的畫面比
   對**：字的外框四邊差距都在 4px 內（字級換算前差兩成，實際量到的）。樣式
   的文字色、邊框色、無邊框、重點字上色都真的畫出來。
"""
import inspect
import json
import os
import random
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from subtitle.cuetime import CueIndex, cue_at  # noqa: E402
from subtitle.exporter import BURN_PLAY_RES, burn_layout, cues_to_ass  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def _text(cue):
    return cue["text"] if cue else None


# ===== 1. cuetime ========================================================

cues = [{"start": 0.2, "end": 0.9, "text": "A"},
        {"start": 1.2, "end": 1.8, "text": "B"}]
ix = CueIndex(cues)
check("開始那一刻就顯示（含開始）", _text(ix.at(0.2)) == "A")
check("結束那一刻已經不顯示（不含結束，與燒錄一致）", ix.at(0.9) is None)
check("兩句之間的空檔什麼都不顯示", ix.at(1.0) is None)
check("第一句之前、最後一句之後都不顯示", ix.at(0.0) is None and ix.at(5.0) is None)
check("第二句中間顯示第二句", _text(ix.at(1.5)) == "B")

overlap = [{"start": 1.0, "end": 3.0, "text": "舊"}, {"start": 2.0, "end": 2.5, "text": "新"}]
oi = CueIndex(overlap)
check("重疊時顯示開始得最晚的那句", _text(oi.at(2.2)) == "新")
check("短句結束後，還沒結束的長句接著顯示", _text(oi.at(2.7)) == "舊")

long_first = [{"start": 0.0, "end": 10.0, "text": "長"}] + [
    {"start": float(i), "end": i + 0.3, "text": str(i)} for i in range(1, 9)]
li = CueIndex(long_first)
check("長句蓋住後面好幾句短的：短句空檔裡顯示長句", _text(li.at(5.5)) == "長")
check("長句蓋住時短句照樣優先", _text(li.at(5.1)) == "5")

check("結束 ≤ 開始的壞句被略過",
      len(CueIndex([{"start": 1, "end": 1, "text": "x"}, {"start": 2, "end": 1, "text": "y"}])) == 0)
check("空清單不出錯", CueIndex([]).at(1.0) is None)
check("輸入沒照時間排序也對", _text(cue_at(list(reversed(cues)), 0.5)) == "A")
same = [{"start": 1.0, "end": 2.0, "text": "先"}, {"start": 1.0, "end": 2.0, "text": "後"}]
check("同一個開始時間：清單裡後面那句（剛打的）優先", _text(cue_at(same, 1.5)) == "後")


def brute(cs, t):
    live = [(i, c) for i, c in enumerate(cs)
            if c["end"] > c["start"] and c["start"] <= t < c["end"]]
    return max(live, key=lambda ic: (ic[1]["start"], ic[0]))[1] if live else None


rng = random.Random(20260927)
mismatch = 0
for _trial in range(200):
    cs = []
    for k in range(rng.randint(0, 25)):
        s = round(rng.uniform(0, 20), 2)
        cs.append({"start": s, "end": round(s + rng.uniform(-1, 6), 2), "text": str(k)})
    index = CueIndex(cs)
    for _q in range(50):
        t = round(rng.uniform(-1, 28), 2)
        if index.at(t) is not brute(cs, t):
            mismatch += 1
check("隨機 200 組字幕 × 50 個時間點，與逐句暴力比對完全一致", mismatch == 0, str(mismatch))

src = open(os.path.join(ROOT, "subtitle", "cuetime.py"), encoding="utf-8").read()
check("cuetime 零 GUI 依賴（不 import tkinter／PySide6）",
      not re.search(r"^\s*(from|import)\s+(tkinter|PySide6)", src, re.M))

# ===== 1b. burn_layout：預覽照燒錄的規則算 ================================

for py in (0.0, 0.1, 0.33, 0.34, 0.5, 0.65, 0.66, 0.88, 0.99, 1.0):
    header = cues_to_ass([{"start": 0, "end": 1, "text": "x"}], {"position_y": py})
    fields = re.search(r"^Style: Default,.*$", header, re.M).group(0).split(",")
    align, margin_v = int(fields[18]), int(fields[21])
    look = burn_layout({"position_y": py}, 1920, 1080)
    expect = {2: ("bottom", 1080 - margin_v), 8: ("top", margin_v), 5: ("middle", 540)}[align]
    check(f"position_y={py}：burn_layout 的對齊與基準線 = cues_to_ass 寫進 ASS 的",
          (look["anchor"], round(look["anchor_y"])) == expect, f"{look} vs {expect}")

half = burn_layout({"font_size": 40, "stroke_width": 3, "position_y": 0.9}, 960, 540)
check("畫面一半大（540 高）→ 字級、邊框、邊距都是 1080 時的一半",
      half["font_px"] == 20 and half["outline_px"] == 1.5
      and round(half["anchor_y"]) == 540 - 54, str(half))
check("水平一律置中（燒錄的 ASS 對齊 2／5／8 都置中，position_x 用不到）",
      burn_layout({"position_x": 0.1}, 1000, 500)["center_x"] == 500
      == burn_layout({"position_x": 0.9}, 1000, 500)["center_x"])
check("預覽換算的 PlayRes 與燒錄預設解析度一致",
      inspect.signature(cues_to_ass).parameters["resolution"].default
      == BURN_PLAY_RES)
check("重點字只在啟用時才帶出來",
      burn_layout({"emphasis_words": "甲"}, 10, 10)["emphasis_words"] == []
      and sorted(burn_layout({"emphasis_enabled": True, "emphasis_words": "甲 乙"},
                      10, 10)["emphasis_words"]) == ["乙", "甲"])

# ===== 2. 播放器（需要 PySide6） =========================================

try:
    import PySide6  # noqa: F401
except ImportError:
    PySide6 = None
    print("SKIP 這個環境沒有 PySide6：略過播放器實測")

if PySide6 is not None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QRectF, QTimer  # noqa: E402
    from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
    from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import gui_qt.app as qt_app  # noqa: E402
    from gui_qt.player import OutlinedText, format_clock  # noqa: E402

    app = QApplication.instance() or QApplication(["test"])

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait_for(cond, timeout_ms=8000, step=50):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(step)
            waited += step
        return cond()

    tmp = tempfile.mkdtemp(prefix="qt_player_")
    srt = os.path.join(tmp, "clip.srt")
    with open(srt, "w", encoding="utf-8") as fh:
        fh.write("1\n00:00:00,200 --> 00:00:00,900\n第一句 Hello\n\n"
                 "2\n00:00:01,200 --> 00:00:01,800\n第二句疊在畫面上\n")
    clip = os.path.join(ROOT, "research", "qt_probe", "probe_clip.mp4")

    win = qt_app.MainWindow({"theme": "light"})
    win.tabs.setCurrentIndex(1)
    win.show()
    panel = win.player_panel
    check("② 字幕頁放了播放器面板", panel is not None
          and win.tabs.tabText(win.tabs.currentIndex()) == "② 字幕")

    panel.open_video(clip)
    data = panel.load_subtitles(srt)
    check("用既有的 importer 載入字幕（2 句）", len(data["cues"]) == 2)
    loaded = wait_for(lambda: not panel.video_item.nativeSize().isEmpty())
    check("載入後就有畫面：暫停在第一格、知道影片尺寸（不是一片黑）",
          loaded and panel.player.playbackState() == QMediaPlayer.PlaybackState.PausedState
          and panel.video_item.nativeSize().width() == 320,
          f"{panel.player.playbackState()} {panel.video_item.nativeSize()}")

    def seek(ms):
        panel.player.setPosition(ms)
        wait_for(lambda: abs(panel.player.position() - ms) < 60)
        wait(150)

    seek(500)
    check("跳到 0.5 秒：畫面上是第一句", panel.current_subtitle_text() == "第一句 Hello",
          repr(panel.current_subtitle_text()))
    check("時間顯示跟著跳", panel.time_label.text().startswith("00:00.5"),
          panel.time_label.text())
    seek(1000)
    check("跳到 1.0 秒（空檔）：畫面上沒有字幕", panel.current_subtitle_text() == "",
          repr(panel.current_subtitle_text()))
    seek(1500)
    check("跳到 1.5 秒：畫面上是第二句", panel.current_subtitle_text() == "第二句疊在畫面上",
          repr(panel.current_subtitle_text()))

    video_rect = panel._video_rect()
    sub_rect = panel.subtitle_item.mapRectToScene(panel.subtitle_item.boundingRect())
    check("字幕整塊在影片實際占的矩形裡", video_rect.contains(sub_rect),
          f"{sub_rect} not in {video_rect}")
    check("字幕在畫面下半部", sub_rect.top() > video_rect.center().y())
    check("字幕水平置中（誤差 2px 內）",
          abs(sub_rect.center().x() - video_rect.center().x()) <= 2,
          f"{sub_rect.center().x()} vs {video_rect.center().x()}")
    check("影片保持比例（16:9 的片子不被拉伸）",
          abs(video_rect.width() / video_rect.height() - 16 / 9) < 0.02,
          f"{video_rect.width()}x{video_rect.height()}")

    panel.set_cues([{"start": 1.4, "end": 1.9, "text": "換過的字幕"}])
    check("換一份字幕：畫面上那句立刻換掉（不必再跳一次）",
          panel.current_subtitle_text() == "換過的字幕", repr(panel.current_subtitle_text()))
    check("資訊列寫明字幕句數", "1 句" in panel.info_label.text(), panel.info_label.text())

    seek(0)
    panel.toggle_play()
    ended = wait_for(lambda: panel.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia,
                     timeout_ms=10000)
    check("真的播到結尾", ended, str(panel.player.mediaStatus()))

    bad = os.path.join(tmp, "empty.srt")
    open(bad, "w", encoding="utf-8").write("這不是字幕\n")
    try:
        panel.load_subtitles(bad)
        raised = False
    except RuntimeError:
        raised = True
    check("解析不出字幕的檔案丟 RuntimeError（介面接住顯示訊息，不當掉）", raised)
    check("format_clock：分:秒.十分之一秒", format_clock(83456) == "01:23.4")

    # --- 白字黑邊：白色部分不能被黑邊吃掉 ---
    def white_pixels(paint):
        img = QImage(400, 120, QImage.Format_ARGB32)
        img.fill(QColor(128, 128, 128))
        painter = QPainter(img)
        paint(painter)
        painter.end()
        return sum(1 for y in range(img.height()) for x in range(img.width())
                   if QColor(img.pixel(x, y)).lightness() > 240)

    item = OutlinedText()
    font = item.font()
    font.setPixelSize(48)
    item.setFont(font)
    item.setText("字幕 Test")

    def outlined(p):
        p.translate(10, 10)
        item.paint(p, None)

    def fill_only(p):
        p.translate(10, 10)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillPath(item._path, QColor(255, 255, 255))

    got, ref = white_pixels(outlined), white_pixels(fill_only)
    check("白字黑邊：白色部分至少保留單純填字的 90%（黑邊畫在字外面、不是蓋在字上）",
          ref > 0 and got >= 0.9 * ref, f"{got} vs {ref}")

    # --- 第二階段：樣式真的套上 ---
    from PySide6.QtCore import QRectF as _QRectF  # noqa: E402
    from gui_qt.player import place_subtitle  # noqa: E402

    def render(text, style, w=640, h=360):
        img = QImage(w, h, QImage.Format_RGB32)
        img.fill(QColor(0, 0, 0))
        it = OutlinedText()
        it.setText(text)
        place_subtitle(it, _QRectF(0, 0, w, h), style)
        p = QPainter(img)
        p.translate(it.pos())
        it.paint(p, None)
        p.end()
        return img

    def count(img, pred):
        return sum(1 for y in range(0, img.height()) for x in range(0, img.width())
                   if pred(QColor(img.pixel(x, y))))

    red = render("紅字 Red", {"text_color": "#FF0000", "stroke_color": "#00FF00",
                              "stroke_width": 3, "font_size": 60})
    check("文字色照樣式（紅）", count(red, lambda c: c.red() > 200 and c.green() < 60) > 50)
    check("邊框色照樣式（綠）", count(red, lambda c: c.green() > 200 and c.red() < 60) > 50)
    bare = render("無邊框", {"text_color": "#FFFFFF", "stroke_color": "#00FF00",
                            "stroke_width": 0, "font_size": 60})
    check("邊框寬 0 → 沒有邊框色", count(bare, lambda c: c.green() > 200 and c.red() < 60) == 0)
    emph = render("這是重點字", {"text_color": "#FFFFFF", "font_size": 60,
                              "emphasis_enabled": True, "emphasis_words": "重點",
                              "emphasis_color": "#0000FF"})
    check("重點字上色（藍）", count(emph, lambda c: c.blue() > 200 and c.red() < 60) > 50)

    panel.set_style({"font_size": 80, "position_y": 0.5})
    mid = panel.subtitle_item.mapRectToScene(panel.subtitle_item.text_rect())
    vr = panel._video_rect()
    check("set_style：換成置中，畫面上那句立刻移到畫面中央（誤差 3px）",
          abs(mid.center().y() - vr.center().y()) <= 3, f"{mid.center().y()} vs {vr.center().y()}")

    # --- 跟真的燒錄比對（ffmpeg＋libass） ---
    import shutil  # noqa: E402
    import subprocess  # noqa: E402
    from PySide6.QtGui import QFontDatabase  # noqa: E402

    FONT = "WenQuanYi Zen Hei"
    has_libass = bool(shutil.which("ffmpeg")) and " ass " in subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    if not has_libass or FONT not in QFontDatabase.families():
        print(f"SKIP 沒有 ffmpeg（libass）或 {FONT} 字型：略過與真的燒錄比對")
    else:
        W, H = 1280, 720

        def bbox(img):
            xs, ys = [], []
            for y in range(img.height()):
                for x in range(img.width()):
                    c = QColor(img.pixel(x, y))
                    if c.red() + c.green() + c.blue() > 60:
                        xs.append(x)
                        ys.append(y)
            return (min(xs), min(ys), max(xs), max(ys)) if xs else None

        cases = {
            "預設（置底 0.88、26、邊 2）": ({}, "第二句 Subtitle Test"),
            "大字（60、邊 4）": ({"font_size": 60, "stroke_width": 4}, "第二句 Subtitle Test"),
            "置中 0.5": ({"position_y": 0.5, "font_size": 48}, "第二句 Subtitle Test"),
            "置頂 0.15（v2.3.6 修正後在上方）": ({"position_y": 0.15, "font_size": 48},
                                             "第二句 Subtitle Test"),
            "兩行": ({"font_size": 48}, "第一行字幕\n第二行 Test"),
        }
        for name, (extra, text) in cases.items():
            style = dict({"font_family": FONT, "stroke_color": "#808080"}, **extra)
            ass = os.path.join(tmp, "burn.ass")
            with open(ass, "w", encoding="utf-8") as fh:
                fh.write(cues_to_ass([{"start": 0, "end": 5, "text": text}], style))
            png = os.path.join(tmp, "burn.png")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            f"color=black:s={W}x{H}:d=1", "-vf", f"ass={ass}",
                            "-frames:v", "1", png], check=True, cwd=tmp)
            burned = bbox(QImage(png))
            ours = bbox(render(text, style, W, H))
            diff = [ours[i] - burned[i] for i in range(4)] if burned and ours else None
            check(f"跟真的燒錄比對「{name}」：字的外框四邊都在 4px 內",
                  diff is not None and max(abs(d) for d in diff) <= 4,
                  f"燒錄 {burned} 預覽 {ours} 差 {diff}")

    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 播放器面板與 cuetime 測試全數通過。")
