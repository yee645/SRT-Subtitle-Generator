# -*- coding: utf-8 -*-
"""
3.0 第 11 項第五階段：字幕樣式存進專案檔（介面）。

核心（格式第 2 版、第 1 版升上來）在 test_project.py；這裡在真的視窗裡驗：

1. 存專案：樣式一起存進去（檔案是第 2 版）。存完再用「字幕樣式…」改字級：算專案的變更
   （狀態列寫「有變更還沒存」、關之前會問）；改回原本的就不算。
2. 另一個視窗開專案：播放器上的字照專案的樣式畫（字級、位置）；開完不算有變更；樣式的小視窗
   開著的話控件跟著換，「還原」回到專案裡的樣式。不寫 config.json。
3. 真的第 1 版專案檔（tests/data/project_v1.srtproj）：照樣打得開、樣式沿用目前的（不換成預設）、
   開完不算有變更；再存一次就是第 2 版、記著目前的樣式。
4. ②字幕頁上方的說明不再寫「樣式還在一般版」。
"""
import json
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過樣式存進專案的介面（核心在 test_project.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import exporter, project  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = tmp
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait_until(cond, timeout_ms=20000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(50)
            waited += 50
        return cond()

    def run(*args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)

    work = os.path.join(tmp, "我的影片")
    os.makedirs(os.path.join(work, "素材"))
    main = os.path.join(work, "訪談.mp4")
    run("-f", "lavfi", "-i", "color=c=gray:size=640x360:rate=30:d=8", "-f", "lavfi",
        "-i", "sine=frequency=150:sample_rate=48000:d=8", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", main)
    song = os.path.join(work, "素材", "配樂.wav")
    run("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:d=6", song)
    srt = os.path.join(work, "訪談.srt")
    with open(srt, "w", encoding="utf-8") as fh:
        fh.write("1\n00:00:00,500 --> 00:00:02,000\n第一句\n\n2\n00:00:03,000 --> 00:00:05,500\n第二句\n")

    start_style = dict(exporter.STYLE_DEFAULTS, font_size=30, position_y=0.88)

    def new_window(style):
        cfg = {"subtitle_style": dict(style)}
        win = qt_app.MainWindow(cfg)
        win.tabs.setCurrentIndex(1)
        win.resize(1280, 800)
        win.show()
        panel = win.player_panel
        panel.messages = []
        panel._show_project_message = lambda title, text: panel.messages.append((title, text))
        return win, panel, cfg

    def read_json(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def show_line(panel):
        wait_until(lambda: panel.player.duration() > 0)
        panel.player.setPosition(1000)
        wait_until(lambda: panel.player.position() == 1000, 5000)
        wait(150)

    def item_height(panel):
        item = panel.subtitle_item
        return item.mapRectToScene(item.boundingRect()).height()

    def item_center_y(panel):
        item = panel.subtitle_item
        return item.mapRectToScene(item.boundingRect()).center().y()

    # ----- 1. 存專案：樣式一起存 -----
    win, panel, cfg = new_window(start_style)
    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0)
    panel.load_subtitles(srt)
    show_line(panel)
    small = item_height(panel)
    saved = os.path.join(work, "訪談專案.srtproj")
    check("存專案", panel.save_project(saved) is True)
    with open(saved, encoding="utf-8") as fh:
        doc = json.load(fh)
    check("檔案是第 2 版、記著目前的樣式（整理過）", doc["version"] == 2
          and doc["style"] == exporter.clean_style(start_style), str(doc.get("style")))
    check("存完：不算有變更", not panel.project_changed())

    cp = win.cue_panel
    QTest.mouseClick(cp.style_btn, Qt.LeftButton)
    wait(100)
    dlg = cp.style_dialog
    dlg.size_spin.setValue(60)
    wait(50)
    check("用「字幕樣式…」改字級：算專案的變更、狀態列寫有變更還沒存",
          panel.project_changed() and "有變更還沒存" in panel.info_label.text(), panel.info_label.text())
    asked = []
    panel._ask_project_discard = lambda: asked.append("專案") or "cancel"
    check("關之前會問（取消就不關）", panel.maybe_close() is False and asked == ["專案"])
    dlg.size_spin.setValue(30)
    wait(50)
    check("改回原本的字級：不算變更", not panel.project_changed())
    dlg.size_spin.setValue(60)
    dlg.y_slider.setValue(12)
    wait(50)
    big_style = exporter.clean_style(cfg["subtitle_style"])
    check("再存一次：檔案裡是新的樣式、不算有變更", panel.save_project() is True and not panel.project_changed()
          and project.load(saved)[0]["style"] == big_style and big_style["font_size"] == 60
          and big_style["position_y"] == 0.12)
    show_line(panel)
    big = item_height(panel)
    top_y = item_center_y(panel)
    dlg.close()

    # ----- 2. 另一個視窗開專案 -----
    other_style = dict(exporter.STYLE_DEFAULTS, font_size=20)
    win2, panel2, cfg2 = new_window(other_style)
    cp2 = win2.cue_panel
    dlg2 = cp2.open_style()  # 樣式的小視窗先開著
    check("開專案前：小視窗是這個視窗原本的樣式", dlg2.size_spin.value() == 20)
    check("開專案", panel2.open_project(saved) is True, str(panel2.messages))
    show_line(panel2)
    check("播放器照專案的樣式畫（字級 60、位置 12）", panel2._style == big_style
          and abs(item_height(panel2) - big) < 1 and abs(item_center_y(panel2) - top_y) < 2,
          f"{item_height(panel2)} vs {big}, {item_center_y(panel2)} vs {top_y}")
    check("這次開啟的設定也換成專案的樣式", cfg2["subtitle_style"] == big_style)
    check("開完不算有變更", not panel2.project_changed() and "有變更還沒存" not in panel2.info_label.text())
    check("開著的小視窗跟著換", dlg2.size_spin.value() == 60 and dlg2.y_slider.value() == 12
          and "上段" in dlg2.zone_note.text())
    dlg2.size_spin.setValue(40)
    wait(50)
    check("在小視窗改：算專案的變更", panel2.project_changed() and panel2._style["font_size"] == 40)
    QTest.mouseClick(dlg2.reset_btn, Qt.LeftButton)
    wait(50)
    check("「還原」：回到專案裡的樣式（不是開專案前的 20）", panel2._style == big_style
          and dlg2.size_spin.value() == 60 and not panel2.project_changed(), str(panel2._style))
    dlg2.close()
    check("沒寫 config.json", not os.path.exists(config.CONFIG_PATH))

    # ----- 3. 真的第 1 版專案檔 -----
    v1_dir = os.path.join(tmp, "第一版")
    os.makedirs(os.path.join(v1_dir, "素材"))
    shutil.copy(main, os.path.join(v1_dir, "訪談.mp4"))
    shutil.copy(srt, os.path.join(v1_dir, "訪談.srt"))
    shutil.copy(song, os.path.join(v1_dir, "素材", "配樂.wav"))
    v1_path = os.path.join(v1_dir, "第一版專案.srtproj")
    shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "project_v1.srtproj"), v1_path)
    keep_style = dict(exporter.STYLE_DEFAULTS, font_size=44, text_color="#00FF00")
    win3, panel3, cfg3 = new_window(keep_style)
    check("第 1 版專案：照樣打得開、檔案都找到", panel3.open_project(v1_path) is True
          and panel3.last_project_missing == [] and [c["text"] for c in panel3.cues] == ["第一句", "第二句"]
          and len(panel3.tracks["music"]) == 1, str(panel3.messages))
    check("第 1 版專案：樣式沿用目前的（不換成預設）", panel3._style == keep_style
          and cfg3["subtitle_style"] == keep_style, str(panel3._style))
    check("第 1 版專案：開完不算有變更", not panel3.project_changed())
    check("第 1 版專案再存一次：變成第 2 版、記著目前的樣式", panel3.save_project() is True
          and read_json(v1_path)["version"] == 2
          and project.load(v1_path)[0]["style"] == exporter.clean_style(keep_style))

    # ----- 4. ②字幕頁上方的說明：樣式已經搬過來，不再寫「還在一般版」 -----
    note = qt_app._subtitle_page_note().text()
    check("②字幕頁說明：逐句校對有字幕樣式；第六、七階段生成字幕與多語字幕包也搬過來，不再寫「還在一般版」",
          "翻譯與多語字幕包、字幕樣式）" in note and "、生成字幕與逐句校對" in note
          and note.endswith("。一般版②字幕頁的功能都搬過來了。") and "還在一般版" not in note, note)

    for w, p in ((win, panel), (win2, panel2), (win3, panel3)):
        p._ask_project_discard = lambda: "discard"
        p._ask_discard = lambda: "discard"
        p.shutdown()
        w.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 字幕樣式存進專案的介面測試全數通過。")
