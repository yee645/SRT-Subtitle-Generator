# -*- coding: utf-8 -*-
"""
3.0 第 11 項第二階段：逐句校對的新增、刪除、尋找取代（gui_qt/cue_panel.py）。

核心在 test_cuelist.py；這裡驗介面，QTest 真的點、真的按鍵：

1. 版面：三個按鈕在清單上面；尋找取代那一列一開始收著，點按鈕或 Ctrl+F 展開；沒選句子時「刪除這句」灰掉；
   沒打要找的字時尋找那幾顆灰掉。
2. 新增：播放頭在空檔——編輯框清空、說新的一句的時間；沒打字就離開＝不加；打字按 Ctrl+Enter 加進去，
   插在對的位置、選到它、播放頭不動、時間軸也有；狀態列寫「新增 1 句」（後面的句子不算改過）。
   Esc 取消；播放頭在某句裡面＝接在那句後面；沒空位＝說原因、不進新增；打到一半點別句＝先加再換、
   點的那句照樣選到。
3. 刪除：按鈕與 Delete 鍵；選取移到下一句；最後一句刪掉選上一句；Ctrl+Z 救回來。
4. 尋找取代：找下一個（從選到的往下、到底繞回、寫第幾 / 幾句）；取代這句（不是命中的句子先找、
   是就換並跳下一個）；全部取代（說幾處、幾句；Ctrl+Z 一次全退）；會變空的不改、列出來；區分大小寫。
5. 存：新增、刪除過的照存進檔案。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過逐句校對的新增刪除（核心在 test_cuelist.py）")
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
    run("-f", "lavfi", "-i", "color=c=gray:size=640x360:rate=30:d=10",
        "-f", "lavfi", "-i", "sine=frequency=150:sample_rate=48000:d=10",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", main)
    srt = os.path.join(tmp, "字幕.srt")
    with open(srt, "w", encoding="utf-8") as fh:
        fh.write("1\n00:00:00,500 --> 00:00:02,000\n嗯 大家好\n\n"
                 "2\n00:00:03,000 --> 00:00:05,000\nHello 世界\n\n"
                 "3\n00:00:05,000 --> 00:00:06,000\n嗯\n\n"
                 "4\n00:00:08,000 --> 00:00:09,500\nhello 再見\n")

    win = qt_app.MainWindow({"subtitle_style": {}})
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 800)
    win.show()
    wait(200)
    panel, cp = win.player_panel, win.cue_panel
    table, editor = cp.table, cp.editor
    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0)
    panel.load_subtitles(srt)
    wait(100)

    def cell(row, col):
        item = table.item(row, col)
        return item.text() if item else None

    def texts():
        return [c["text"] for c in panel.cues]

    def seek(ms):
        panel.player.setPosition(ms)
        return wait_until(lambda: panel.player.position() == ms, 5000)

    def click(button):
        QTest.mouseClick(button, Qt.LeftButton)
        wait(50)

    # ----- 1. 版面 -----
    check("三個按鈕在清單上面", all(b.isVisible() for b in (cp.add_btn, cp.delete_btn, cp.find_btn))
          and cp.add_btn.mapTo(cp, cp.add_btn.rect().bottomLeft()).y() < table.mapTo(cp, table.rect().topLeft()).y())
    check("尋找取代那一列一開始收著", not cp.find_bar.isVisible())
    check("沒選句子：「刪除這句」灰掉", cp.selected_index() == -1 and not cp.delete_btn.isEnabled())
    cp.select(0)
    check("選了一句：「刪除這句」可以按", cp.delete_btn.isEnabled())

    # ----- 2. 新增 -----
    seek(6500)
    click(cp.add_btn)
    check("空檔裡按「新增一句」：編輯框清空可打字、沒選句子、說新的一句的時間",
          editor.isEnabled() and editor.toPlainText() == "" and cp.selected_index() == -1
          and panel.timeline.selected == -1
          and "0:06.5 → 0:08.0" in cp.note.text(), cp.note.text())
    panel.play_btn.setFocus()
    wait(50)
    check("沒打字就離開編輯框：不加、說沒新增", len(panel.cues) == 4 and "沒有新增" in cp.note.text(), cp.note.text())
    click(cp.add_btn)
    editor.setFocus()
    editor.insertPlainText(" \n  ")
    QTest.keyClick(editor, Qt.Key_Return, Qt.ControlModifier)
    check("只打了空白就按 Ctrl+Enter：不加、說沒新增", len(panel.cues) == 4 and cp._adding is None
          and "沒有新增" in cp.note.text(), cp.note.text())
    click(cp.add_btn)
    editor.setFocus()
    editor.insertPlainText("打到一半")
    panel._on_cue_times(0, 0.4, 2.0)  # 打字的時候字幕變了（時間軸上拖了別句）：清單重畫
    check("新增打字中清單重畫：打到一半的字留著、還在新增", editor.toPlainText() == "打到一半" and editor.isEnabled()
          and cp._adding is not None and cell(0, 1) == "0:00.4 → 0:02.0", editor.toPlainText())
    QTest.keyClick(editor, Qt.Key_Escape)
    panel.undo()
    click(cp.add_btn)
    editor.setFocus()
    editor.insertPlainText(" 新的一句 ")
    QTest.keyClick(editor, Qt.Key_Return, Qt.ControlModifier)
    wait(50)
    check("Ctrl+Enter：插在第 4 個、時間 6.5～8.0、文字整理過", len(panel.cues) == 5
          and panel.cues[3] == {"start": 6.5, "end": 8.0, "text": "新的一句"}, str(panel.cues[3:4]))
    check("清單、時間軸都有；選到新的那句；播放頭沒動", cell(3, 2) == "新的一句" and cell(3, 1) == "0:06.5 → 0:08.0"
          and cell(4, 0) == "5" and cp.selected_index() == 3 and panel.timeline.selected == 3
          and len(panel.timeline._source) == 5 and panel.player.position() == 6500
          and editor.toPlainText() == "新的一句", f"{cp.selected_index()} {panel.player.position()}")
    check("狀態列：「新增 1 句」，後面的句子不算改過", "（新增 1 句，尚未存檔）" in panel.info_label.text()
          and panel.unsaved_changes() == 1, panel.info_label.text())
    wait(100)
    check("畫面上播放頭那裡就是新的那句", panel.current_subtitle_text() == "新的一句", panel.current_subtitle_text())

    seek(1000)
    click(cp.add_btn)
    check("播放頭在某句裡面：接在那句後面（2.0 → 3.0）", "0:02.0 → 0:03.0" in cp.note.text(), cp.note.text())
    editor.insertPlainText("不要了")
    QTest.keyClick(editor, Qt.Key_Escape)
    check("Esc：取消新增", len(panel.cues) == 5 and "沒有新增" in cp.note.text())

    seek(4000)
    click(cp.add_btn)
    check("播放頭在連著的兩句裡面（3～5、5～6）：一路接到 6.0，但 6.5 有新的那句，只到 6.5",
          "0:06.0 → 0:06.5" in cp.note.text(), cp.note.text())
    editor.setFocus()
    editor.insertPlainText("點別句前打的")
    rect = table.visualItemRect(table.item(4, 2))
    QTest.mouseClick(table.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    wait(100)
    check("打到一半點別句：先加進去，點的那句（hello 再見，現在往後挪一格）照樣選到",
          texts()[3] == "點別句前打的" and len(panel.cues) == 6 and cp.selected_index() == 5
          and editor.toPlainText() == "hello 再見", f"{texts()} {cp.selected_index()}")
    check("狀態列：新增 2 句", "新增 2 句" in panel.info_label.text(), panel.info_label.text())

    before = len(panel.cues)
    seek(2950)
    entered = cp.start_add()
    check("沒空位（2.95 秒：離下一句不到 0.1 秒）：說原因、不進新增",
          not entered and "沒辦法新增" in cp.note.text() and cp._adding is None and len(panel.cues) == before,
          cp.note.text())

    # ----- 3. 刪除 -----
    cp.select(3)
    click(cp.delete_btn)
    check("「刪除這句」：拿掉、選到下一句、說怎麼救回來", "點別句前打的" not in texts() and len(panel.cues) == 5
          and cp.selected_index() == 3 and editor.toPlainText() == "新的一句"
          and "Ctrl+Z" in cp.note.text(), f"{texts()} {cp.note.text()}")
    table.setFocus()
    QTest.keyClick(table, Qt.Key_Z, Qt.ControlModifier)
    check("Ctrl+Z：救回來、在原本的位置", texts()[3] == "點別句前打的" and len(panel.cues) == 6
          and cp.selected_index() == 3, f"{texts()} {cp.selected_index()}")
    cp.select(5)
    table.setFocus()
    QTest.keyClick(table, Qt.Key_Delete)
    wait(50)
    check("Delete 鍵；刪最後一句：選到上一句", "hello 再見" not in texts() and cp.selected_index() == 4
          and panel.timeline.selected == 4, f"{texts()} {cp.selected_index()}")
    for _ in range(4):  # 刪 hello、刪點別句前打的、新增點別句前打的、新增新的一句
        QTest.keyClick(table, Qt.Key_Z, Qt.ControlModifier)
    check("一路 Ctrl+Z：新增的兩句也退掉，回到載入時", texts() == ["嗯 大家好", "Hello 世界", "嗯", "hello 再見"]
          and panel.unsaved_changes() == 0, str(texts()))
    check("復原新增後選的那句在範圍內", -1 <= cp.selected_index() < len(panel.cues)
          and panel.timeline.selected < len(panel.cues))

    # ----- 4. 尋找取代 -----
    cp.select(0)
    table.setFocus()
    QTest.keyClick(table, Qt.Key_F, Qt.ControlModifier)
    wait(50)
    check("Ctrl+F：展開尋找取代、游標在「尋找」", cp.find_bar.isVisible() and cp.find_btn.isChecked()
          and cp.find_edit.hasFocus())
    check("沒打要找的字：找下一個、取代灰掉", not cp.find_next_btn.isEnabled() and not cp.replace_all_btn.isEnabled())
    cp.find_edit.setText("hello")
    check("打了字：可以按", cp.find_next_btn.isEnabled() and cp.replace_one_btn.isEnabled())
    QTest.keyClick(cp.find_edit, Qt.Key_Return)
    wait(50)
    check("Enter＝找下一個：從選到的第 1 句往下，到第 2 句、播放器跳過去、寫 1 / 2 句（一共 2 處）",
          cp.selected_index() == 1 and wait_until(lambda: panel.player.position() == 3000, 5000)
          and "第 1 / 2 句" in cp.note.text() and "一共 2 處" in cp.note.text(), cp.note.text())
    click(cp.find_next_btn)
    check("再找：往下到第 4 句、寫 2 / 2", cp.selected_index() == 3 and "第 2 / 2 句" in cp.note.text(), cp.note.text())
    click(cp.find_next_btn)
    check("再找：到底繞回第 2 句", cp.selected_index() == 1 and "第 1 / 2 句" in cp.note.text())
    cp.case_box.setChecked(True)
    cp.select(0)
    click(cp.find_next_btn)
    check("區分大小寫：只找到小寫的那句（第 4 句）", cp.selected_index() == 3 and "1 / 1" in cp.note.text(),
          cp.note.text())
    cp.case_box.setChecked(False)

    cp.replace_edit.setText("Hi")
    cp.select(0)
    click(cp.replace_one_btn)
    check("取代這句：選到的不是命中的句子＝先找到下一個，不換", cp.selected_index() == 1 and texts()[1] == "Hello 世界"
          and "已取代" not in cp.note.text() and "第 1 / 2 句" in cp.note.text(), cp.note.text())
    click(cp.replace_one_btn)
    check("再按：換掉這句、跳到下一個命中的", texts()[1] == "Hi 世界" and texts()[3] == "hello 再見"
          and cp.selected_index() == 3 and "已取代第 2 句" in cp.note.text(), cp.note.text())
    click(cp.replace_one_btn)
    check("最後一個：換掉、說沒有別的了", texts()[3] == "Hi 再見" and "沒有別的" in cp.note.text(), cp.note.text())
    table.setFocus()
    QTest.keyClick(table, Qt.Key_Z, Qt.ControlModifier)
    QTest.keyClick(table, Qt.Key_Z, Qt.ControlModifier)
    check("取代這句是一句一步：兩下 Ctrl+Z 退回", texts()[1] == "Hello 世界" and texts()[3] == "hello 再見")

    cp.find_edit.setText("嗯")
    cp.replace_edit.setText("")
    click(cp.replace_all_btn)
    check("全部取代「嗯」→ 空：第 1 句變「大家好」；第 3 句會變空的不改、列出來",
          texts() == ["大家好", "Hello 世界", "嗯", "hello 再見"] and "已取代 1 處（1 句）" in cp.note.text()
          and "第 3 句取代後會變成空的" in cp.note.text(), f"{texts()} {cp.note.text()}")
    cp.find_edit.setText("hello")
    cp.replace_edit.setText("Hey")
    click(cp.replace_all_btn)
    check("全部取代 hello（不分大小寫）：2 處、2 句；清單跟著換", texts()[1] == "Hey 世界" and texts()[3] == "Hey 再見"
          and "已取代 2 處（2 句）" in cp.note.text() and cell(3, 2) == "Hey 再見", cp.note.text())
    table.setFocus()
    QTest.keyClick(table, Qt.Key_Z, Qt.ControlModifier)
    check("Ctrl+Z 一次：整批退回", texts()[1] == "Hello 世界" and texts()[3] == "hello 再見", str(texts()))
    cp.find_edit.setText("沒有這個字")
    click(cp.replace_all_btn)
    check("找不到：說沒找到、什麼都不動", "沒有找到「沒有這個字」" in cp.note.text()
          and texts() == ["大家好", "Hello 世界", "嗯", "hello 再見"])
    click(cp.find_btn)
    check("再按「尋找取代」：收起來", not cp.find_bar.isVisible())

    # ----- 5. 存 -----
    seek(9600)
    click(cp.add_btn)
    editor.insertPlainText("片尾")
    QTest.keyClick(editor, Qt.Key_Return, Qt.ControlModifier)
    check("加在最後面：選到它（清單與時間軸）", texts()[-1] == "片尾" and cp.selected_index() == 4
          and panel.timeline.selected == 4, f"{cp.selected_index()} {panel.timeline.selected}")
    table.setFocus()
    QTest.keyClick(table, Qt.Key_Z, Qt.ControlModifier)
    check("復原加在最後面的那句：時間軸改選新的最後一句", texts()[-1] == "hello 再見"
          and panel.timeline.selected == 3, str(panel.timeline.selected))
    QTest.keyClick(table, Qt.Key_Y, Qt.ControlModifier)
    cp.select(2)
    click(cp.delete_btn)
    check("狀態列：文字改過 1 處、新增 1 句、刪除 1 句", "文字改過 1 處、新增 1 句、刪除 1 句" in panel.info_label.text(),
          panel.info_label.text())
    table.setFocus()
    QTest.keyClick(table, Qt.Key_S, Qt.ControlModifier)
    saved = load_subtitle_file(srt)["cues"]
    check("Ctrl+S：新增、刪除、取代都照存", [c["text"] for c in saved] == ["大家好", "Hello 世界", "hello 再見", "片尾"]
          and abs(saved[3]["start"] - 9.6) < 0.01 and saved[3]["end"] <= 10.0 + 0.01
          and panel.unsaved_changes() == 0, str([(c["text"], c["start"], c["end"]) for c in saved]))

    panel._ask_discard = lambda: "discard"
    panel._ask_project_discard = lambda: "discard"
    panel.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 逐句校對新增、刪除、尋找取代介面測試全數通過。")
