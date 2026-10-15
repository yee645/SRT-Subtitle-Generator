# -*- coding: utf-8 -*-
"""
3.0 第 11 項第一階段：②字幕頁的逐句校對（gui_qt/cue_panel.py）。

核心（clean_text／with_text／復原）在 test_cuetext.py；這裡驗介面，QTest 真的點、真的按鍵：

1. 版面：1280x800 時播放器與清單左右並排；清單約 420px 寬；影片畫面仍至少 300px 高；播放器
   不比它最小的寬度窄（按鈕不會被擠掉）。沒字幕時編輯框灰掉、寫怎麼載入。
2. 清單：句數、時間（0:00.2 → 0:02.5）、雙行字幕用「 / 」接起來。
3. 點一句：播放器跳到那句開頭、時間軸選到那句、編輯框放那句；時間軸上選一句，清單跟著選。
4. 改文字：Ctrl+Enter 套用——清單、時間軸、畫面上的字幕立刻換；狀態列寫「文字改過 1 處」。
   Esc 放回原本的；點別句先套用再換；改成空的不收、說原因；雙行照存。
5. 復原／重做：焦點在清單時 Ctrl+Z／Ctrl+Y 跟播放器同一疊。
6. 拖時間：清單的時間跟著變，選取留著。
7. 存：編輯框裡改到一半按 Ctrl+S，先套用再存，檔案裡是新的文字。
8. 關視窗：編輯框裡改到一半，先套用，所以問得到要不要存。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過逐句校對介面（核心在 test_cuetext.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle.importer import load_subtitle_file  # noqa: E402

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

    main = os.path.join(tmp, "main.mp4")
    run("-f", "lavfi", "-i", "color=c=gray:size=640x360:rate=30:d=8",
        "-f", "lavfi", "-i", "sine=frequency=150:sample_rate=48000:d=8",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", main)
    srt = os.path.join(tmp, "字幕.srt")
    with open(srt, "w", encoding="utf-8") as fh:
        fh.write("1\n00:00:00,200 --> 00:00:02,500\n第一句\n\n"
                 "2\n00:00:03,000 --> 00:00:05,000\n上面一行\n下面一行\n\n"
                 "3\n00:00:05,500 --> 00:00:07,800\n第三句\n")

    win = qt_app.MainWindow({"subtitle_style": {}})
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 800)
    win.show()
    wait(200)
    panel, cues_panel = win.player_panel, win.cue_panel
    table, editor = cues_panel.table, cues_panel.editor

    # ----- 1. 版面 -----
    check("播放器與清單左右並排、清單約 420px 寬", cues_panel.isVisible() and panel.isVisible()
          and cues_panel.geometry().left() >= panel.geometry().right()
          and 380 <= cues_panel.width() <= 460, f"{panel.geometry()} {cues_panel.geometry()}")
    check("播放器不比它最小的寬度窄（按鈕不會被擠掉）", panel.width() >= panel.minimumSizeHint().width(),
          f"{panel.width()} < {panel.minimumSizeHint().width()}")
    check("影片畫面仍至少 300px 高", panel.view.height() >= 300, str(panel.view.height()))
    check("沒字幕：清單是空的、編輯框灰掉、寫怎麼載入", table.rowCount() == 0 and not editor.isEnabled()
          and "載入字幕" in cues_panel.note.text())

    widths = (panel.width(), cues_panel.width())
    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0)
    panel.load_subtitles(srt)
    wait(100)
    check("開影片、載入字幕之後：兩邊的寬度不跳（狀態那一行變長也不會撐寬播放器）",
          (panel.width(), cues_panel.width()) == widths, f"{widths} → {(panel.width(), cues_panel.width())}")
    check("狀態那一行在清單上面、可以折行", cues_panel.info is panel.info_label and panel.info_label.wordWrap()
          and cues_panel.isAncestorOf(panel.info_label) and panel._footer.indexOf(panel.info_label) == -1
          and panel.info_label.geometry().bottom() <= table.geometry().top()
          and "字幕：字幕.srt，3 句" in panel.info_label.text(), panel.info_label.text())

    # ----- 2. 清單 -----
    def cell(row, col):
        item = table.item(row, col)
        return item.text() if item else None

    check("三句；時間寫成 0:00.2 → 0:02.5；雙行用「 / 」接起來",
          table.rowCount() == 3 and cell(0, 0) == "1" and cell(0, 1) == "0:00.2 → 0:02.5"
          and cell(1, 2) == "上面一行 / 下面一行" and cell(2, 2) == "第三句",
          f"{cell(0, 1)} {cell(1, 2)}")
    check("清單的時間欄整欄看得到（沒有被截成 …）",
          table.columnWidth(1) >= table.fontMetrics().horizontalAdvance(cell(0, 1)), str(table.columnWidth(1)))

    # ----- 3. 點一句 -----
    def click_row(row):
        rect = table.visualItemRect(table.item(row, 2))
        QTest.mouseClick(table.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
        wait(50)

    click_row(1)
    check("點第 2 句：播放器跳到 3.0 秒、時間軸選到、編輯框放那句（雙行照原樣）",
          wait_until(lambda: panel.player.position() == 3000, 5000) and panel.timeline.selected == 1
          and editor.isEnabled() and editor.toPlainText() == "上面一行\n下面一行"
          and "第 2 句" in cues_panel.note.text(), f"{panel.player.position()} {panel.timeline.selected}")
    panel.player.setPosition(1000)
    wait_until(lambda: panel.player.position() == 1000, 5000)
    panel.timeline.select_cue(2, seek=False)
    wait(100)
    check("時間軸上選第 3 句：清單跟著選、編輯框換成那句，播放頭不跳（時間軸說不跳就不跳）",
          cues_panel.selected_index() == 2 and editor.toPlainText() == "第三句"
          and panel.player.position() == 1000, str(panel.player.position()))
    click_row(0)

    # ----- 4. 改文字 -----
    editor.setFocus()
    editor.selectAll()
    editor.insertPlainText("改過的第一句")  # QTest.keyClicks 只打得了 ASCII
    check("還沒套用前：字幕沒變", panel.cues[0]["text"] == "第一句")
    QTest.keyClick(editor, Qt.Key_Return, Qt.ControlModifier)
    wait(50)
    check("Ctrl+Enter 套用：字幕、清單、時間軸都換", panel.cues[0]["text"] == "改過的第一句"
          and cell(0, 2) == "改過的第一句" and panel.timeline._source[0]["text"] == "改過的第一句")
    panel.player.setPosition(1000)
    wait_until(lambda: panel.player.position() == 1000, 5000)
    wait(100)
    check("畫面上的字幕立刻換", panel.current_subtitle_text() == "改過的第一句", panel.current_subtitle_text())
    check("狀態列寫「文字改過 1 處，尚未存檔」", "（文字改過 1 處，尚未存檔）" in panel.info_label.text()
          and panel.unsaved_changes() == 1, panel.info_label.text())
    check("Ctrl+Enter 沒有多塞一個換行", "\n" not in panel.cues[0]["text"] and editor.toPlainText() == "改過的第一句")

    editor.insertPlainText("亂打")
    QTest.keyClick(editor, Qt.Key_Escape)
    check("Esc：放回原本的、字幕不動", editor.toPlainText() == "改過的第一句" and panel.cues[0]["text"] == "改過的第一句")

    editor.setPlainText("點別句前改的")
    click_row(2)
    check("點別句：先套用正在改的，再換成那句", panel.cues[0]["text"] == "點別句前改的"
          and cues_panel.selected_index() == 2 and editor.toPlainText() == "第三句")

    editor.setFocus()
    editor.setPlainText("時間軸選別句前改的")
    panel.timeline.select_cue(0, seek=False)  # 焦點還在編輯框：只有「換句」這件事
    wait(50)
    check("時間軸上換句（焦點沒離開編輯框）：也先套用正在改的", panel.cues[2]["text"] == "時間軸選別句前改的"
          and cues_panel.selected_index() == 0 and editor.toPlainText() == "點別句前改的", repr(panel.cues[2]["text"]))
    editor.setFocus()
    editor.setPlainText("離開編輯框前改的")
    panel.play_btn.setFocus()  # 只有焦點離開，選的還是同一句
    wait(50)
    check("離開編輯框（沒換句）：也套用", panel.cues[0]["text"] == "離開編輯框前改的"
          and cues_panel.selected_index() == 0, repr(panel.cues[0]["text"]))
    table.clearSelection()
    wait(50)
    check("沒選句子：編輯框灰掉、清空", not editor.isEnabled() and editor.toPlainText() == "")
    cues_panel.select(2)
    editor.setFocus()
    editor.setPlainText("  \n ")
    QTest.keyClick(editor, Qt.Key_Return, Qt.ControlModifier)
    check("改成空的：不收、放回原本的、說原因", panel.cues[2]["text"] == "時間軸選別句前改的"
          and editor.toPlainText() == "時間軸選別句前改的"
          and "不能是空的" in cues_panel.note.text(), cues_panel.note.text())

    editor.setPlainText(" 上 \n\n 下 ")
    QTest.keyClick(editor, Qt.Key_Return, Qt.ControlModifier)
    check("雙行：照存（每行去頭尾空白、拿掉空行），清單用「 / 」接", panel.cues[2]["text"] == "上\n下"
          and cell(2, 2) == "上 / 下", repr(panel.cues[2]["text"]))
    check("狀態列：文字改過 2 處（第 1、3 句）", "文字改過 2 處" in panel.info_label.text(), panel.info_label.text())

    # ----- 5. 復原／重做（焦點在清單）-----
    table.setFocus()
    QTest.keyClick(table, Qt.Key_Z, Qt.ControlModifier)
    check("Ctrl+Z：最後一次改的退回去，清單跟著換", panel.cues[2]["text"] == "時間軸選別句前改的"
          and cell(2, 2) == "時間軸選別句前改的")
    QTest.keyClick(table, Qt.Key_Y, Qt.ControlModifier)
    check("Ctrl+Y：再做回來", panel.cues[2]["text"] == "上\n下" and cell(2, 2) == "上 / 下")

    # ----- 6. 拖時間 -----
    panel._on_cue_times(2, 5.6, 7.8)
    check("時間軸上改時間：清單的時間跟著變、選取留著", cell(2, 1) == "0:05.6 → 0:07.8"
          and cues_panel.selected_index() == 2, f"{cell(2, 1)} {cues_panel.selected_index()}")
    check("狀態列：時間改過 1 處、文字改過 2 處", "時間改過 1 處、文字改過 2 處" in panel.info_label.text(),
          panel.info_label.text())

    # ----- 7. 存 -----
    editor.setFocus()
    editor.setPlainText("存檔前改的")
    QTest.keyClick(editor, Qt.Key_S, Qt.ControlModifier)
    saved = [c["text"] for c in load_subtitle_file(srt)["cues"]]
    check("編輯框裡按 Ctrl+S：先套用再存，檔案裡是新的", saved == ["離開編輯框前改的", "上面一行\n下面一行", "存檔前改的"]
          and panel.unsaved_changes() == 0, str(saved))

    # ----- 8. 關視窗 -----
    editor.setPlainText("關之前改的")
    asked = []
    panel._ask_discard = lambda: (asked.append(panel.unsaved_changes()), "cancel")[1]
    win.close()
    check("關視窗：編輯框裡改到一半的先套用，所以會問要不要存；取消就不關", asked == [1] and win.isVisible()
          and panel.cues[2]["text"] == "關之前改的", str(asked))
    panel._ask_discard = lambda: "discard"
    panel.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 逐句校對介面測試全數通過。")
