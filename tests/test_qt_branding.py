# -*- coding: utf-8 -*-
"""
3.0 第 11 項第十四階段：④輸出頁的「成品加工：品牌套版」（片頭／片尾／浮水印）。

套版本身跟一般版同一份（subtitle/branding.apply_branding）。測試素材用 ffmpeg 產生：藍色主片 3 秒、
紅色片頭 1 秒（尺寸不同、沒有聲音）、綠色片尾 1 秒、白色方塊當浮水印。

1. ④頁有這一框；欄位照目前的設定（夾過範圍）；說明寫建議順序、原檔不動、不能停。
2. 改欄位立刻寫進這次開啟的設定（branding 區塊）；瀏覽（取消不變）、清除。
3. 不套版的情況：沒有來源、三項都沒設、沒有 ffmpeg、上面的輸出還在跑——都講原因、不開始。
4. 套版（片頭＋片尾＋浮水印）：輸出檔名＝來源加「_套版」；片長＝片頭＋主片＋片尾；開頭是紅的、中間是藍的而且
   右下角有白色浮水印（左上角沒有）、結尾是綠的；原檔不動；跑的期間欄位與按鈕停用、不能重跑、上面的
   〔完成輸出〕也不跑；再套一次不覆蓋（加編號）。
5. 來源：留空＝②開著的影片；另外選的優先；找不到的檔案講原因。
6. 背景失敗：講原因、按鈕恢復。
7. 套版中關視窗先問（問的是套版）。不寫 config.json。
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

if PySide6 is None or not shutil.which("ffmpeg"):
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過④品牌套版")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import branding_box as bb  # noqa: E402
    from gui_qt import output_panel as op  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import branding  # noqa: E402
    from subtitle.media import probe_duration  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def ff(*args):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait_until(cond, timeout_ms=120000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(50)
            waited += 50
        return cond()

    video = os.path.join(tmp, "主片.mp4")
    ff("-f", "lavfi", "-i", "color=c=0x1030C0:size=640x360:rate=25:d=3", "-f", "lavfi", "-i", "sine=frequency=300:d=3",
       "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-shortest", video)
    intro = os.path.join(tmp, "片頭.mp4")
    ff("-f", "lavfi", "-i", "color=c=0xC01010:size=320x240:rate=30:d=1", "-c:v", "libx264", "-preset", "ultrafast",
       "-pix_fmt", "yuv420p", intro)
    outro = os.path.join(tmp, "片尾.mp4")
    ff("-f", "lavfi", "-i", "color=c=0x10A020:size=640x360:rate=25:d=1", "-f", "lavfi", "-i", "sine=frequency=500:d=1",
       "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-shortest", outro)
    logo = os.path.join(tmp, "logo.png")
    ff("-f", "lavfi", "-i", "color=c=white:size=100x100", "-frames:v", "1", logo)
    other = os.path.join(tmp, "另一支.mp4")
    shutil.copy(video, other)

    def pixel(path, seconds, x, y):
        """那一格 (x, y) 的 RGB。"""
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(seconds), "-i", path, "-frames:v", "1",
                              "-vf", f"crop=4:4:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, check=True).stdout
        return tuple(raw[:3])

    cfg = {"branding": {"watermark_position": "不存在的位置", "watermark_opacity": 5, "watermark_scale": 0.2,
                        "watermark_margin": 16}}
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.show()
    win.tabs.setCurrentIndex(3)
    wait(50)
    out = win.output_panel
    box = out.branding
    panel = win.player_panel

    # ----- 1. 這一框 -----
    check("④頁有品牌套版這一框", isinstance(box, bb.BrandingBox) and box.isVisible() and "品牌套版" in box.title())
    check("欄位照目前的設定（位置不認得→右下、不透明度夾到 1.0、大小 20%、留白 16）",
          box.position_combo.currentData() == "bottom_right" and box.opacity_spin.value() == 1.0
          and box.scale_spin.value() == 20 and box.margin_spin.value() == 16
          and all(e.text() == "" for e in box.path_edits.values()))
    check("位置選單＝一般版那五個", [box.position_combo.itemText(i) for i in range(box.position_combo.count())]
          == list(branding.POSITION_LABELS.values()))
    check("範圍跟一般版一樣", (box.scale_spin.minimum(), box.scale_spin.maximum()) == (5, 50)
          and (box.opacity_spin.minimum(), box.opacity_spin.maximum()) == (0.1, 1.0)
          and (box.margin_spin.minimum(), box.margin_spin.maximum()) == (0, 200))
    check("說明：建議順序、來源自動換、原檔不動、不能停", all(w in bb.NOTE for w in ("燒錄→套版", "來源會自動換", "原檔不動", "不能停"))
          and box.status_label.text() == bb.IDLE)

    # ----- 3a. 沒有來源 -----
    check("沒開影片也沒另外選：不開始、講原因", box.start() is False and box.status_label.text() == bb.NO_SOURCE
          and not box.busy())

    panel.open_video(video)
    wait_until(lambda: panel.player.duration() > 0, 10000)
    check("來源留空＝②開著的影片", box.source_path() == video)
    check("三項都沒設：不開始、講原因", box.start() is False and box.status_label.text() == bb.NOTHING_SET)

    # ----- 2. 欄位與設定 -----
    real_open = QFileDialog.getOpenFileName
    asked = []
    try:
        QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (asked.append(a), ("", ""))[1])
        QTest.mouseClick(box.path_btns["intro_path"][0], Qt.LeftButton)
        check("瀏覽片頭按取消：不變；只列影片檔", box.path_edits["intro_path"].text() == "" and len(asked) == 1
              and "*.mp4" in asked[0][3] and "*.png" not in asked[0][3])
        for key, path in (("intro_path", intro), ("outro_path", outro), ("watermark_path", logo)):
            QFileDialog.getOpenFileName = staticmethod(lambda *a, _p=path, **k: (asked.append(a), (_p, ""))[1])
            QTest.mouseClick(box.path_btns[key][0], Qt.LeftButton)
        check("瀏覽選了片頭、片尾、浮水印：欄位與設定都換；浮水印只列圖片檔",
              [box.path_edits[k].text() for k in ("intro_path", "outro_path", "watermark_path")] == [intro, outro, logo]
              and cfg["branding"]["intro_path"] == intro and cfg["branding"]["outro_path"] == outro
              and cfg["branding"]["watermark_path"] == logo and "*.png" in asked[-1][3] and "*.mp4" not in asked[-1][3])
    finally:
        QFileDialog.getOpenFileName = real_open
    box.position_combo.setCurrentIndex(box.position_combo.findData("top_left"))
    check("只改位置：立刻寫進設定", cfg["branding"]["watermark_position"] == "top_left")
    box.position_combo.setCurrentIndex(box.position_combo.findData("bottom_right"))
    box.scale_spin.setValue(25)
    box.opacity_spin.setValue(1.0)
    box.margin_spin.setValue(20)
    check("改位置、大小、不透明度、留白：立刻寫進設定", cfg["branding"]["watermark_position"] == "bottom_right"
          and cfg["branding"]["watermark_scale"] == 0.25 and cfg["branding"]["watermark_opacity"] == 1.0
          and cfg["branding"]["watermark_margin"] == 20.0, str(cfg["branding"]))
    QTest.mouseClick(box.path_btns["outro_path"][1], Qt.LeftButton)
    check("清除片尾：欄位空了、設定跟著", box.path_edits["outro_path"].text() == "" and cfg["branding"]["outro_path"] == "")
    box.path_edits["outro_path"].setText(outro)

    # ----- 3b. 沒有 ffmpeg、上面還在跑 -----
    real_ff = bb.ffmpeg_available
    bb.ffmpeg_available = lambda: False
    try:
        check("沒有 ffmpeg：不開始、講原因", box.start() is False and box.status_label.text() == bb.NO_FFMPEG)
    finally:
        bb.ffmpeg_available = real_ff
    out.worker.busy = True
    check("上面的輸出還在跑：不開始、講原因", box.start() is False and box.status_label.text() == bb.OTHER_BUSY
          and not box.busy())
    out.worker.busy = False

    # ----- 4. 套版 -----
    expected = branding.suggest_output_path(video)
    size_before = os.path.getsize(video)
    QTest.mouseClick(box.run_btn, Qt.LeftButton)
    check("按下去：開始了、按鈕停用寫套版中、進度條出現、說不能停", box.busy() and not box.run_btn.isEnabled()
          and box.run_btn.text() == "套版中…" and box.progress_bar.isVisible() and "不能停" in box.status_label.text()
          and not box.source_edit.isEnabled() and not box.path_edits["intro_path"].isEnabled()
          and not box.path_btns["intro_path"][0].isEnabled() and not box.scale_spin.isEnabled())
    check("跑的期間再按：不會重跑", box.start() is False)
    panel.cues = [{"start": 0.2, "end": 1.0, "text": "一句"}]
    check("套版中：上面的〔完成輸出〕也不跑、講原因", out.finish_output() is False
          and out.status_label.text() == op.BRANDING_BUSY and not out.busy())
    check("套版中算「還有影片在輸出」（關視窗要問）", out.burning())
    asked_close = []
    real_q = QMessageBox.question
    try:
        QMessageBox.question = staticmethod(lambda *a, **k: (asked_close.append(a[2]), QMessageBox.Yes)[1])
        check("套版中關視窗：問的是套版、選「等」＝不關", out.ask_close_while_burning() is False
              and asked_close == [op.CLOSE_QUESTION_BRANDING] and "套版" in op.CLOSE_QUESTION_BRANDING)
    finally:
        QMessageBox.question = real_q
    check("跑完", wait_until(lambda: not box.busy()))
    check("輸出檔名＝來源加「_套版」、狀態列講完成", box.last_output == expected and os.path.exists(expected)
          and expected.endswith("主片_套版.mp4") and box.status_label.text() == f"套版完成：{expected}", box.status_label.text())
    check("跑完：按鈕與欄位恢復、進度條收起來", box.run_btn.isEnabled() and box.run_btn.text() == "輸出套版影片"
          and not box.progress_bar.isVisible() and box.source_edit.isEnabled() and box.scale_spin.isEnabled()
          and not out.burning())
    total = probe_duration(expected)
    check("片長＝片頭 1＋主片 3＋片尾 1", abs(total - 5.0) < 0.25, f"{total:.2f}")
    head, mid, tail = pixel(expected, 0.5, 300, 100), pixel(expected, 2.5, 300, 100), pixel(expected, 4.5, 300, 100)
    check("開頭是紅的（片頭）、中間是藍的（主片）、結尾是綠的（片尾）",
          head[0] > 120 and head[2] < 80 and mid[2] > 120 and mid[0] < 80 and tail[1] > 100 and tail[0] < 80,
          f"{head} {mid} {tail}")
    # 浮水印：寬 25% ＝ 160 px，右下留白 20 → 佔 x 460~620、y 180~340
    corner, opposite = pixel(expected, 2.5, 540, 260), pixel(expected, 2.5, 60, 60)
    check("主片右下角有白色浮水印、左上角沒有", min(corner) > 200 and opposite[2] > 120 and opposite[0] < 80,
          f"{corner} {opposite}")
    check("原檔沒被動", os.path.getsize(video) == size_before and pixel(video, 1.5, 540, 260)[0] < 80)
    check("沒寫 config.json", not os.path.exists(config.CONFIG_PATH))

    # ----- 5. 來源 -----
    box.set_source(other)
    check("另外選的來源優先", box.source_path() == other)
    box.set_source(os.path.join(tmp, "不存在.mp4"))
    check("來源檔找不到：不開始、講原因", box.start() is False and box.status_label.text() == bb.NO_SOURCE)
    QTest.mouseClick(box.source_clear, Qt.LeftButton)
    check("清除來源：回到②開著的影片", box.source_edit.text() == "" and box.source_path() == video)

    # ----- 6. 背景失敗；再套一次不覆蓋 -----
    real_apply = branding.apply_branding
    got = []

    def boom(source, output, settings=None, progress_cb=None):
        got.append((source, output, settings))
        raise RuntimeError("品牌套版失敗：moov atom not found")

    branding.apply_branding = boom
    try:
        check("背景失敗：開始了", box.start() is True)
        check("背景失敗：講原因、按鈕恢復", wait_until(lambda: not box.busy())
              and box.status_label.text().startswith("套版失敗：") and "moov atom" in box.status_label.text()
              and box.run_btn.isEnabled() and not box.progress_bar.isVisible(), box.status_label.text())
    finally:
        branding.apply_branding = real_apply
    check("再套一次：不覆蓋上一支（加編號）；交給背景的是夾過範圍的設定", len(got) == 1
          and got[0][0] == video and got[0][1] == os.path.join(tmp, "主片_套版 (1).mp4")
          and got[0][2] == branding.resolve_branding_settings(cfg) and got[0][2]["watermark_scale"] == 0.25)

    panel._ask_discard = lambda: "discard"
    panel._ask_project_discard = lambda: "discard"
    panel.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 ④品牌套版測試全數通過。")
