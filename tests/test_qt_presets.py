# -*- coding: utf-8 -*-
"""
3.0 第 11 項第三十一階段：「字幕樣式」視窗裡的習慣設定（樣式組合）與斷句設定（gui_qt/preset_box.py）。

規則在 test_profiles.py；這裡 QTest 真的點，看設定、播放器、生成字幕用的設定真的跟著變：

1. 打開「字幕樣式…」：上面是習慣設定（下拉照名字排、選的是 active_preset）、左邊字幕外觀、右邊斷句設定；
   斷句控件照設定擺好、範圍跟一般版一樣；說明講一組＝字幕外觀＋斷句設定。
2. 改斷句：寫進這次開啟的設定（夾限過、其他鍵留著），生成字幕用的就是它；狀態行說「已改過斷句設定」。
3. 選另一組：字幕外觀（播放器上的字）與斷句設定一起換；active_preset 跟著；狀態行說一致。
4. 〔另存新樣式〕：空白不行（提示、不存）；取消不存；新名字存下並選它；同名先問，不覆蓋就不動、覆蓋就換掉。
5. 〔更新目前樣式〕：現在的值存進選取的那一組，狀態行回到一致。
6. 〔刪除〕：先問，不刪就不動；刪了改用名字排第一的那組並套用；只剩一組時按鈕灰掉、硬按也只提示。
7. 設定裡沒有習慣設定（舊設定、測試）：補一組「預設」＝現在的外觀＋斷句；關掉再開，三塊照設定擺好。
8. 在字詞欄按 Enter 不會順便按到任何按鈕（例如〔另存新樣式〕）。
9. 全程沒寫 config.json（關掉 Qt 版時才存，test_qt_settings_save.py 驗）。
"""
import copy
import os
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
    print("SKIP 這個環境沒有 PySide6：略過習慣設定介面")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import preset_box as pb  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import profiles  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    base_style = dict(cfg["subtitle_style"])
    big = config.make_profile(dict(base_style, font_size=60, text_color="#FF0000"),
                              dict(cfg["segmentation"], max_chars_cjk=10, pause_gap=1.2))
    cfg["presets"]["直式短片"] = big
    cfg["segmentation"]["自訂"] = "留著"
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.show()
    wait(100)
    panel, cp = win.player_panel, win.cue_panel
    panel._ask_discard = lambda *a, **k: "discard"
    panel._ask_project_discard = lambda *a, **k: "discard"

    # ----- 1 -----
    dlg = cp.open_style()
    wait(100)
    box, seg_box = dlg.preset_box, dlg.segmentation_box
    names = [box.combo.itemText(i) for i in range(box.combo.count())]
    check("打開：習慣設定下拉照名字排、選的是 active_preset", names == sorted(["預設", "直式短片"])
          and box.selected() == "預設")
    check("三塊：上面習慣設定、左邊外觀、右邊斷句", box.geometry().bottom() < dlg.look_box.geometry().top()
          and dlg.look_box.geometry().right() < seg_box.geometry().left()
          and box.isVisibleTo(dlg) and seg_box.isVisibleTo(dlg))
    check("斷句控件照設定擺好", all(seg_box.spins[k].value() == cfg["segmentation"][k]
                                for k in profiles.SEGMENTATION_DEFAULTS))
    check("斷句範圍跟一般版一樣", all((seg_box.spins[k].minimum(), seg_box.spins[k].maximum()) == (lo, hi)
                                 for k, _l, lo, hi, _s, _u in profiles.SEGMENTATION_FIELDS))
    check("說明：一組＝字幕外觀＋斷句設定；斷句影響下次生成", box.note.text() == pb.PRESET_NOTE
          and "字幕外觀" in pb.PRESET_NOTE and "斷句設定" in pb.PRESET_NOTE
          and "生成字幕" in seg_box.note.text())
    check("一開始：狀態行說一致", box.state.text() == "目前的值與「預設」一致。", box.state.text())

    # ----- 2 -----
    seg_box.spins["max_chars_cjk"].setValue(22)
    check("改斷句：寫進這次開啟的設定、其他鍵留著", cfg["segmentation"]["max_chars_cjk"] == 22
          and cfg["segmentation"]["自訂"] == "留著")
    check("改斷句：狀態行說已改過斷句設定", "已改過斷句設定" in box.state.text()
          and "字幕外觀" not in box.state.text(), box.state.text())
    seg_box.spins["max_duration"].setValue(3.0)
    seg_box.spins["min_duration"].setValue(5.0)
    check("最短比最長大：存進去的最短夾到最長", cfg["segmentation"]["min_duration"] == 3.0
          and cfg["segmentation"]["max_duration"] == 3.0, str(cfg["segmentation"]))
    seg_box.spins["min_duration"].setValue(1.0)
    seg_box.spins["max_duration"].setValue(7.0)
    from gui_qt.generate_dialog import GenerateDialog  # 沒開影片也能建：只看它拿哪份設定
    gen = GenerateDialog(panel)
    check("生成字幕用的就是這組斷句", gen.config()["segmentation"]["max_chars_cjk"] == 22)
    gen.refresh()
    check("生成視窗講斷句照「字幕樣式…」", "斷句照②「字幕樣式…」裡的斷句設定" in gen.notice.text())
    gen.close()

    # ----- 3 -----
    box.combo.setCurrentIndex(box.combo.findText("直式短片"))
    box.combo.activated.emit(box.combo.currentIndex())
    wait(50)
    check("選另一組：字幕外觀換掉（播放器上也是）", panel._style["font_size"] == 60
          and panel._style["text_color"] == "#FF0000" and dlg.size_spin.value() == 60
          and cfg["subtitle_style"]["font_size"] == 60)
    check("選另一組：斷句設定一起換（控件也是）", cfg["segmentation"]["max_chars_cjk"] == 10
          and cfg["segmentation"]["pause_gap"] == 1.2 and seg_box.spins["max_chars_cjk"].value() == 10
          and cfg["segmentation"]["自訂"] == "留著")
    check("選另一組：active_preset 跟著、狀態行一致", cfg["active_preset"] == "直式短片"
          and box.state.text() == "目前的值與「直式短片」一致。", box.state.text())

    # ----- 4 -----
    warned, asked = [], []
    box._warn = lambda text: warned.append(text)
    box._ask_yes = lambda title, text: (asked.append(text), answer[0])[1]
    answer = [False]
    box._ask_name = lambda: "   "
    QTest.mouseClick(box.save_new_btn, Qt.LeftButton)
    check("另存：空白不行（提示、不存）", warned == [profiles.EMPTY_NAME] and len(cfg["presets"]) == 2)
    box._ask_name = lambda: None
    check("另存：取消不存", box.save_new() is None and len(cfg["presets"]) == 2)
    dlg.size_spin.setValue(44)
    box._ask_name = lambda: " 旅遊 "
    QTest.mouseClick(box.save_new_btn, Qt.LeftButton)
    check("另存：新名字存下並選它（外觀＋斷句）", cfg["presets"]["旅遊"]["subtitle_style"]["font_size"] == 44
          and cfg["presets"]["旅遊"]["segmentation"]["max_chars_cjk"] == 10
          and cfg["active_preset"] == "旅遊" and box.selected() == "旅遊"
          and "旅遊" in [box.combo.itemText(i) for i in range(box.combo.count())])
    check("另存之後狀態行一致", box.state.text() == "目前的值與「旅遊」一致。")
    dlg.size_spin.setValue(50)
    box._ask_name = lambda: "直式短片"
    QTest.mouseClick(box.save_new_btn, Qt.LeftButton)
    check("同名：先問；不覆蓋就不動", asked == ["樣式「直式短片」已存在，要覆蓋嗎？"]
          and cfg["presets"]["直式短片"]["subtitle_style"]["font_size"] == 60 and box.selected() == "旅遊")
    answer[0] = True
    QTest.mouseClick(box.save_new_btn, Qt.LeftButton)
    check("同名：覆蓋就換掉、選它", cfg["presets"]["直式短片"]["subtitle_style"]["font_size"] == 50
          and box.selected() == "直式短片" and cfg["active_preset"] == "直式短片")

    # ----- 5 -----
    dlg.size_spin.setValue(51)
    check("改字幕外觀：狀態行說已改過字幕外觀", "已改過字幕外觀" in box.state.text(), box.state.text())
    dlg.size_spin.setValue(50)
    seg_box.spins["pause_gap"].setValue(0.7)
    check("改了：狀態行說還沒存進去", "還沒存進「直式短片」" in box.state.text())
    QTest.mouseClick(box.update_btn, Qt.LeftButton)
    check("更新目前樣式：存進選取的那一組、狀態行一致",
          cfg["presets"]["直式短片"]["segmentation"]["pause_gap"] == 0.7
          and box.state.text() == "目前的值與「直式短片」一致。")
    check("更新不動別組", cfg["presets"]["旅遊"]["segmentation"]["pause_gap"] == 1.2)

    # ----- 6 -----
    asked.clear()
    answer[0] = False
    QTest.mouseClick(box.delete_btn, Qt.LeftButton)
    check("刪除：先問；不刪就不動", asked == ["確定要刪除習慣設定「直式短片」？"] and "直式短片" in cfg["presets"])
    answer[0] = True
    QTest.mouseClick(box.delete_btn, Qt.LeftButton)
    first = sorted(cfg["presets"])[0]
    check("刪了：改用名字排第一的那組並套用", "直式短片" not in cfg["presets"] and cfg["active_preset"] == first
          and box.selected() == first and panel._style["font_size"] == cfg["presets"][first]["subtitle_style"]["font_size"]
          and "直式短片" not in [box.combo.itemText(i) for i in range(box.combo.count())])
    box.choose("旅遊")
    QTest.mouseClick(box.delete_btn, Qt.LeftButton)
    check("只剩一組：刪除按鈕灰掉", list(cfg["presets"]) == ["預設"] and not box.delete_btn.isEnabled())
    warned.clear()
    check("只剩一組：硬按也只提示、不刪", box.delete_current() is None and warned == [profiles.KEEP_ONE]
          and list(cfg["presets"]) == ["預設"])

    # ----- 8 -----
    clicked = []
    for button in dlg.findChildren(QPushButton):
        button.clicked.connect(lambda _c=False, b=button: clicked.append(b.text()))
    dlg.emphasis_box.setChecked(True)
    dlg.emphasis_edit.setFocus()
    dlg.emphasis_edit.setText("剪輯")
    QTest.keyClick(dlg.emphasis_edit, Qt.Key_Return)
    wait(50)
    check("字詞欄按 Enter：不會順便按到任何按鈕", clicked == [] and panel._style["emphasis_words"] == "剪輯", str(clicked))
    dlg.close()

    # ----- 7 -----
    bare = {"subtitle_style": dict(base_style, font_size=33)}
    win2 = qt_app.MainWindow(bare)
    win2.show()
    wait(50)
    dlg2 = win2.cue_panel.open_style()
    check("沒有習慣設定：補一組「預設」＝現在的外觀＋斷句", list(bare["presets"]) == ["預設"]
          and bare["active_preset"] == "預設" and bare["presets"]["預設"]["subtitle_style"]["font_size"] == 33
          and bare["presets"]["預設"]["segmentation"] == profiles.SEGMENTATION_DEFAULTS
          and dlg2.preset_box.state.text() == "目前的值與「預設」一致。")
    dlg2.close()
    empty = {"subtitle_style": dict(base_style), "presets": {}, "active_preset": "不見了"}
    check("習慣設定是空的：一樣補「預設」並選它", pb.ensure_presets(empty) is empty["presets"]
          and list(empty["presets"]) == ["預設"] and empty["active_preset"] == "預設")
    bare["segmentation"] = dict(profiles.SEGMENTATION_DEFAULTS, max_chars_cjk=30)
    bare["presets"]["另一組"] = config.make_profile(bare["subtitle_style"], bare["segmentation"])
    bare["active_preset"] = "另一組"
    dlg2 = win2.cue_panel.open_style()
    check("關掉再開：三塊照設定擺好", dlg2.segmentation_box.spins["max_chars_cjk"].value() == 30
          and dlg2.preset_box.selected() == "另一組" and dlg2.preset_box.combo.count() == 2
          and dlg2.preset_box.state.text() == "目前的值與「另一組」一致。")
    dlg2.close()
    p2 = win2.player_panel
    p2._ask_discard = lambda *a, **k: "discard"
    p2._ask_project_discard = lambda *a, **k: "discard"
    win2.close()

    # ----- 9 -----
    check("全程沒寫 config.json", not os.path.exists(config.CONFIG_PATH))
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 習慣設定與斷句設定介面測試全數通過。")
