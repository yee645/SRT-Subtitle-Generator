# -*- coding: utf-8 -*-
"""
3.0 第 4 項第三階段：時間軸改時間的復原／重做、存回字幕檔、沒存就換字幕或關視窗時先問。

規則本身（紀錄、改過幾處、存檔的暫存檔與 .bak）在 test_cueedit.py；這裡用真的
滑鼠拖曳與真的快捷鍵（QTest 送 Ctrl+Z／Ctrl+Y／Ctrl+Shift+Z／Ctrl+S）操作播放器：

1. 拖完 → 復原鍵可以按；Ctrl+Z → 字幕清單、時間軸方塊、畫面上的字幕都回去，而且
   選取改到的那句；Ctrl+Y 與 Ctrl+Shift+Z 都能重做。
2. Ctrl+S → 存回載入的那個檔（讀回來時間對）、第一次留 .bak、資訊列寫存到哪；
   存完再改 → 又顯示改過；復原回存檔時的樣子 → 不再顯示改過。
3. 沒有檔名的字幕 → 存檔時問路徑；按取消 → 不存。
4. 有沒存的修改時關視窗 → 先問：取消就不關、放棄就關、存檔就存完再關。
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
    print("SKIP 這個環境沒有 PySide6：略過復原／存檔的介面（規則本身在 test_cueedit.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle.importer import load_subtitle_file  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = tmp

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

    CUE_Y = tl.ROW_Y["cues"] + tl.CUE_H // 2

    video = os.path.join(tmp, "u.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=gray:s=320x180:r=30:d=12",
                    "-f", "lavfi", "-i", "sine=d=12", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", video], check=True)
    srt = os.path.join(tmp, "u.srt")
    original = ("1\n00:00:01,000 --> 00:00:03,000\n甲\n\n"
                "2\n00:00:06,000 --> 00:00:08,000\n乙\n").encode("utf-8")
    with open(srt, "wb") as fp:
        fp.write(original)

    win = qt_app.MainWindow({"subtitle_style": {}})
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 800)
    win.show()
    panel = win.player_panel
    panel.open_video(video)
    wait_until(lambda: abs(panel.timeline.duration - 12) < 0.3)
    panel.load_subtitles(srt)
    tv = panel.timeline
    tv.set_zoom(80, 0, 0)
    vp = tv.viewport()

    def px(seconds):
        return int(round(seconds * tv.px_per_sec)) - tv.horizontalScrollBar().value()

    def drag(from_s, to_s, side):
        """抓某個邊（side=+1 抓在邊右邊 1px，-1 抓在左邊 1px）拖到 to_s。"""
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(from_s) + side, CUE_Y))
        QTest.mouseMove(vp, QPoint(px(to_s) + side, CUE_Y))
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(px(to_s) + side, CUE_Y))
        wait(30)

    def times():
        return [(c["start"], c["end"]) for c in panel.cues]

    def key(seq, mod=Qt.ControlModifier):
        QTest.keyClick(tv, seq, mod)  # 焦點在時間軸（面板裡）
        wait(30)

    from PySide6.QtGui import QKeySequence  # noqa: E402

    from gui_qt.player import edit_shortcuts  # noqa: E402
    pairs = edit_shortcuts("undo", "redo", "save")
    texts = [seq.toString(QKeySequence.PortableText) for seq, _slot in pairs]
    check("快捷鍵：同一組按鍵只註冊一次（重複註冊 Qt 會判成衝突、兩個都不觸發）",
          len(texts) == len(set(texts)), str(texts))
    by_key = {seq.toString(QKeySequence.PortableText): slot for seq, slot in pairs}
    check("快捷鍵：Ctrl+Z 復原、Ctrl+Y 與 Ctrl+Shift+Z 重做、Ctrl+S 存檔",
          by_key.get("Ctrl+Z") == "undo" and by_key.get("Ctrl+Y") == "redo"
          and by_key.get("Ctrl+Shift+Z") == "redo" and by_key.get("Ctrl+S") == "save", str(by_key))

    check("剛載入：不能復原、不能重做、可以存", not panel.undo_btn.isEnabled()
          and not panel.redo_btn.isEnabled() and panel.save_btn.isEnabled())

    panel.player.setPosition(4000)
    wait_until(lambda: panel.player.position() >= 3900, 5000)
    drag(3, 4.5, -1)      # 甲的右邊 3 → 4.5
    drag(6, 5.0, +1)      # 乙的左邊 6 → 5
    check("拖了兩次 → 兩句都改了", times() == [(1.0, 4.5), (5.0, 8.0)], str(times()))
    check("畫面上 4 秒處出現「甲」", panel.current_subtitle_text() == "甲", repr(panel.current_subtitle_text()))
    check("復原鍵可以按、重做不行", panel.undo_btn.isEnabled() and not panel.redo_btn.isEnabled())
    check("資訊列：改過 2 處、尚未存檔", "改過 2 處" in panel.info_label.text()
          and "尚未存檔" in panel.info_label.text(), panel.info_label.text())

    key(Qt.Key_Z)
    check("Ctrl+Z → 最後那次（乙的左邊）回到 6", times() == [(1.0, 4.5), (6.0, 8.0)], str(times()))
    check("復原後時間軸的方塊跟著回去、並選取改到的「乙」",
          abs(tv.cue_rects()[1].left() - 6 * tv.px_per_sec) < 1.5 and tv.selected == 1,
          f"{tv.cue_rects()[1]} {tv.selected}")
    key(Qt.Key_Z)
    check("再 Ctrl+Z → 整份回到載入時的樣子", times() == [(1.0, 3.0), (6.0, 8.0)], str(times()))
    check("復原改到「甲」→ 選取換到「甲」（原本選的是乙）", tv.selected == 0, str(tv.selected))
    check("畫面上 4 秒處的「甲」消失（復原後字幕照舊時間顯示）", panel.current_subtitle_text() == "",
          repr(panel.current_subtitle_text()))
    check("回到載入時的樣子 → 不顯示改過、復原鍵不能按、重做可以",
          "改過" not in panel.info_label.text() and not panel.undo_btn.isEnabled()
          and panel.redo_btn.isEnabled(), panel.info_label.text())
    key(Qt.Key_Z)
    check("沒得復原時再按 Ctrl+Z → 什麼都不變", times() == [(1.0, 3.0), (6.0, 8.0)])
    key(Qt.Key_Y)
    check("Ctrl+Y → 重做第一次（甲 → 4.5）", times() == [(1.0, 4.5), (6.0, 8.0)], str(times()))
    key(Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
    check("Ctrl+Shift+Z 也能重做（乙 → 5）", times() == [(1.0, 4.5), (5.0, 8.0)], str(times()))
    panel.undo_btn.click()
    panel.redo_btn.click()
    check("按鈕也能復原、重做", times() == [(1.0, 4.5), (5.0, 8.0)], str(times()))

    # ----- 存檔 -----
    key(Qt.Key_S)
    back = load_subtitle_file(srt)["cues"]
    check("Ctrl+S → 存回載入的那個檔，讀回來時間是改過的",
          [(c["start"], c["end"], c["text"]) for c in back] == [(1.0, 4.5, "甲"), (5.0, 8.0, "乙")], str(back))
    with open(srt + ".bak", "rb") as fp:
        check("第一次存：原檔留一份 .bak（內容一模一樣）", fp.read() == original)
    check("資訊列：寫存到哪、原檔在哪，不再說尚未存檔",
          "已存到 u.srt" in panel.info_label.text() and "u.srt.bak" in panel.info_label.text()
          and "尚未存檔" not in panel.info_label.text(), panel.info_label.text())
    check("存完照樣可以復原（紀錄沒清）", panel.undo_btn.isEnabled())
    key(Qt.Key_Z)
    check("存完再復原 → 跟存檔時不一樣了，顯示改過 1 處",
          "改過 1 處" in panel.info_label.text() and "已存到" not in panel.info_label.text(),
          panel.info_label.text())
    key(Qt.Key_Y)
    check("重做回到存檔時的樣子 → 不顯示改過", "改過" not in panel.info_label.text(), panel.info_label.text())

    # ----- 沒有檔名 → 問路徑 -----
    panel.set_cues([{"start": 1, "end": 2, "text": "新的"}])
    key(Qt.Key_Z)
    check("換一份字幕 → 復原紀錄清掉（Ctrl+Z 不會把上一份的修改套到這份）",
          not panel.undo_btn.isEnabled() and times() == [(1.0, 2.0)], str(times()))
    asked = []
    panel._ask_save_path = lambda suggested: asked.append(suggested) or ""
    check("沒有檔名、問路徑時按取消 → 不存", panel.save() is False and asked == [""], str(asked))
    target = os.path.join(tmp, "新檔.vtt")
    panel._ask_save_path = lambda suggested: target
    check("沒有檔名、選了路徑 → 存成那個檔（.vtt）", panel.save() is True and os.path.exists(target)
          and load_subtitle_file(target)["cues"][0]["text"] == "新的")
    check("存完之後的「存檔」直接存回同一個檔", panel._subtitle_path == target)

    # ----- 有沒存的修改時關視窗 -----
    panel.load_subtitles(srt)
    drag(1, 0.5, +1)
    check("測資：有一處沒存", panel.unsaved_changes() == 1, str(times()))
    answers = []
    panel._ask_discard = lambda: answers.append("問了") or "cancel"
    win.close()
    wait(50)
    check("關視窗時先問；按取消 → 視窗沒關、修改還在",
          answers == ["問了"] and win.isVisible() and panel.unsaved_changes() == 1, f"{answers} {win.isVisible()}")
    panel._ask_discard = lambda: "save"
    win.close()
    wait(50)
    check("按存檔 → 存完才關", not win.isVisible()
          and load_subtitle_file(srt)["cues"][0]["start"] == 0.5)
    win.show()
    wait(50)
    drag(0.5, 1.5, +1)
    panel._ask_discard = lambda: "discard"
    win.close()
    wait(50)
    check("按放棄 → 關掉、檔案沒被動", not win.isVisible()
          and load_subtitle_file(srt)["cues"][0]["start"] == 0.5)
    win.show()
    wait(50)
    panel.load_subtitles(srt)
    panel._ask_discard = lambda: answers.append("不該問") or "cancel"
    answers.clear()
    win.close()
    wait(50)
    check("沒改過 → 關視窗不問", answers == [] and not win.isVisible(), str(answers))

    # 換字幕前也先問（載入字幕按鈕走的那條路）
    win.show()
    wait(50)
    drag(0.5, 2.0, +1)  # 檔案裡甲是 0.5 開始（上面存過）
    check("測資：又有一處沒存", panel.unsaved_changes() == 1, str(times()))
    opened = []
    from gui_qt import player as player_mod  # noqa: E402
    real_get = player_mod.QFileDialog.getOpenFileName
    player_mod.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: opened.append(1) or ("", ""))
    try:
        panel._ask_discard = lambda: "cancel"
        panel._choose_subtitles()
        check("有沒存的修改時按「載入字幕」、選取消 → 連選檔視窗都不開", opened == [], str(opened))
        panel._ask_discard = lambda: "discard"
        panel._choose_subtitles()
        check("選放棄 → 才開選檔視窗", opened == [1], str(opened))
    finally:
        player_mod.QFileDialog.getOpenFileName = real_get

    panel._ask_discard = lambda: "discard"
    win.close()
    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 時間軸復原／重做與存檔測試全數通過。")
