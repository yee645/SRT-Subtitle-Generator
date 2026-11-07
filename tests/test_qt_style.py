# -*- coding: utf-8 -*-
"""
3.0 第 11 項第四階段：逐句校對的「字幕樣式…」（gui_qt/style_panel.py）。

核心在 test_stylecheck.py；這裡驗介面，QTest 真的點、真的按鍵，看播放器上的字幕真的跟著變：

1. 按「字幕樣式…」：小視窗不擋住主視窗；控件照目前的樣式擺好（位置、字型、字級、邊框、顏色、重點字、動態）。
2. 字級、邊框寬：播放器上的字立刻變大、邊框立刻變粗；設定只記在這次開啟的（不寫 config.json）。
3. 垂直位置：拉到上段字跑到上面、寫「上段」；中段一律正中間、寫「中段」；快捷「頂部」＝12；
   水平位置不動（燒錄一律置中）。
4. 顏色：選色換掉文字顏色、按鈕寫色碼；取消就不變。
5. 重點字：沒勾時字詞欄灰掉；勾了、打字詞，播放器上那幾個字換色。
6. 動態字幕、字型（電腦上沒有的字型要說會用替代字型）。
7. 還原：回到打開預覽版時的樣式；關掉再開：控件照現在的樣式。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過字幕樣式的介面（核心在 test_stylecheck.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtGui import QFontDatabase  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402

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

    main = os.path.join(tmp, "main.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:size=640x360:rate=30:d=8",
                    "-f", "lavfi", "-i", "sine=frequency=150:sample_rate=48000:d=8", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", main], check=True)

    families = QFontDatabase.families()
    have = next((f for f in ("WenQuanYi Zen Hei", "Noto Sans CJK TC", "DejaVu Sans") if f in families), families[0])
    start_style = {"position_x": 0.3, "position_y": 0.88, "font_family": have, "font_size": 30,
                   "text_color": "#ffffff", "stroke_color": "#000000", "stroke_width": 2,
                   "emphasis_enabled": False, "emphasis_color": "#FFD700", "emphasis_words": "",
                   "dynamic_mode": "off"}
    cfg = {"subtitle_style": dict(start_style)}
    win = qt_app.MainWindow(cfg)
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 800)
    win.show()
    wait(200)
    panel, cp = win.player_panel, win.cue_panel
    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0)
    panel.set_cues([{"start": 0.0, "end": 8.0, "text": "大家好今天聊剪輯"}])
    panel.player.setPosition(1000)
    wait_until(lambda: panel.player.position() == 1000, 5000)
    wait(200)
    item = panel.subtitle_item

    def item_height():
        return item.mapRectToScene(item.boundingRect()).height()

    def item_center_y():
        return item.mapRectToScene(item.boundingRect()).center().y()

    video = panel._video_rect()

    # ----- 1. 打開 -----
    check("字幕在畫面上", panel.current_subtitle_text() == "大家好今天聊剪輯")
    QTest.mouseClick(cp.style_btn, Qt.LeftButton)
    wait(100)
    dlg = cp.style_dialog
    check("小視窗打開、不擋住主視窗", dlg is not None and dlg.isVisible() and not dlg.isModal())
    check("控件照目前的樣式擺好", dlg.y_slider.value() == 88 and dlg.font_box.currentText() == have
          and dlg.size_spin.value() == 30 and dlg.stroke_spin.value() == 2 and not dlg.emphasis_box.isChecked()
          and dlg.dynamic_combo.currentData() == "off" and "#FFFFFF" in dlg.color_buttons["text_color"].text())
    check("光是打開、擺控件：不動到樣式（沒有先送一次整理過的）", cfg["subtitle_style"] is not None
          and cfg["subtitle_style"]["text_color"] == "#ffffff" and panel._style["text_color"] == "#ffffff")
    check("寫出現在在下段", "下段" in dlg.zone_note.text() and dlg.y_value.text() == "88", dlg.zone_note.text())

    # ----- 2. 字級、邊框寬 -----
    small = item_height()
    dlg.size_spin.setValue(60)
    wait(50)
    check("字級 30 → 60：播放器上的字立刻變大（高度約兩倍）", item_height() > small * 1.6 and panel._style["font_size"] == 60,
          f"{small} → {item_height()}")
    outline = item._outline
    dlg.stroke_spin.setValue(5)
    check("邊框寬 2 → 5：邊框立刻變粗", item._outline > outline * 2 and panel._style["stroke_width"] == 5,
          f"{outline} → {item._outline}")
    check("只記在這次開啟的設定裡、沒寫 config.json", cfg["subtitle_style"]["font_size"] == 60
          and not os.path.exists(config.CONFIG_PATH))

    # ----- 3. 垂直位置 -----
    bottom_y = item_center_y()
    dlg.y_slider.setValue(20)
    wait(50)
    check("拉到 20：字跑到畫面上方、寫「上段」", item_center_y() < video.center().y() < bottom_y
          and "上段" in dlg.zone_note.text() and panel._style["position_y"] == 0.2,
          f"{item_center_y()} {video.center().y()} {bottom_y}")
    dlg.y_slider.setValue(40)
    wait(50)
    at40 = item_center_y()
    dlg.y_slider.setValue(60)
    wait(50)
    check("中段（40、60）：一律放正中間、寫「中段」", abs(at40 - video.center().y()) < 2
          and abs(item_center_y() - video.center().y()) < 2 and "中段" in dlg.zone_note.text(),
          f"{at40} {item_center_y()} {video.center().y()}")
    QTest.mouseClick(dlg.preset_buttons["頂部"], Qt.LeftButton)
    check("快捷「頂部」＝12", dlg.y_slider.value() == 12 and panel._style["position_y"] == 0.12)
    check("水平位置不動（燒錄一律置中）", panel._style["position_x"] == 0.3 and cfg["subtitle_style"]["position_x"] == 0.3)

    # ----- 4. 顏色 -----
    dlg._ask_color = lambda current, title: "#ff0000"
    QTest.mouseClick(dlg.color_buttons["text_color"], Qt.LeftButton)
    check("選色：文字變紅、按鈕寫色碼", item._text_color.name() == "#ff0000"
          and panel._style["text_color"] == "#FF0000" and "#FF0000" in dlg.color_buttons["text_color"].text())
    dlg._ask_color = lambda current, title: None
    QTest.mouseClick(dlg.color_buttons["text_color"], Qt.LeftButton)
    check("取消選色：不變（還是紅的）", panel._style["text_color"] == "#FF0000" and item._text_color.name() == "#ff0000")

    # ----- 5. 重點字 -----
    check("沒勾重點字：字詞欄與重點字顏色灰掉", not dlg.emphasis_edit.isEnabled()
          and not dlg.color_buttons["emphasis_color"].isEnabled())
    dlg.emphasis_box.setChecked(True)
    dlg.emphasis_edit.setFocus()
    dlg.emphasis_edit.setText("剪輯")
    QTest.keyClick(dlg.emphasis_edit, Qt.Key_Return)
    wait(50)
    check("勾了、打字詞：播放器上那兩個字換色", dlg.emphasis_edit.isEnabled() and item._emphasis_words == ["剪輯"]
          and panel._style["emphasis_enabled"] and panel._style["emphasis_words"] == "剪輯", str(item._emphasis_words))

    # ----- 6. 動態字幕、字型 -----
    dlg.dynamic_combo.setCurrentIndex(dlg.dynamic_combo.findData("karaoke"))
    check("動態字幕：卡拉OK", panel._style["dynamic_mode"] == "karaoke")
    dlg.font_box.setFocus()
    dlg.font_box.setEditText("沒有這個字型")
    QTest.keyClick(dlg.font_box, Qt.Key_Return)
    wait(50)
    check("電腦上沒有的字型：說會用替代字型", panel._style["font_family"] == "沒有這個字型"
          and "這台電腦沒有「沒有這個字型」" in dlg.font_note.text() and "替代字型" in dlg.font_note.text(),
          dlg.font_note.text())
    dlg.font_box.setEditText(have)
    QTest.keyClick(dlg.font_box, Qt.Key_Return)
    check("有的字型：不寫", panel._style["font_family"] == have and dlg.font_note.text() == "")
    dlg.font_box.setFocus()
    dlg.font_box.setEditText("打了沒按 Enter")
    dlg.size_spin.setFocus()  # 直接離開字型欄
    wait(50)
    check("字型打完直接離開欄位（沒按 Enter）：也套用", panel._style["font_family"] == "打了沒按 Enter",
          panel._style["font_family"])

    # ----- 7. 還原；關掉再開 -----
    QTest.mouseClick(dlg.reset_btn, Qt.LeftButton)
    wait(50)
    check("還原：回到打開預覽版時的樣式（顏色大寫）", panel._style == dict(start_style, text_color="#FFFFFF")
          and dlg.size_spin.value() == 30 and dlg.y_slider.value() == 88 and abs(item_height() - small) < 1,
          str(panel._style))
    dlg.size_spin.setValue(44)
    dlg.close()
    wait(50)
    changed = dict(cfg["subtitle_style"], font_size=50, position_y=0.5)
    cfg["subtitle_style"] = changed  # 視窗關著的時候樣式被別處換掉（例如之後開專案帶進來的）
    panel.set_style(changed)
    cp.open_style()
    check("關掉再開：控件照現在的樣式（關著時被換掉的也跟上）", dlg.isVisible() and dlg.size_spin.value() == 50
          and dlg.y_slider.value() == 50 and "中段" in dlg.zone_note.text())
    dlg.close()

    panel._ask_discard = lambda: "discard"
    panel._ask_project_discard = lambda: "discard"
    panel.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 字幕樣式介面測試全數通過。")
