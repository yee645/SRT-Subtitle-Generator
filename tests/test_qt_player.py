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
"""
import json
import os
import random
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from subtitle.cuetime import CueIndex, cue_at  # noqa: E402

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

    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 播放器面板與 cuetime 測試全數通過。")
