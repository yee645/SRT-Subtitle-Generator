# -*- coding: utf-8 -*-
"""
剪輯器版面改版 E-3a：屬性面板跟著選取換頁（gui_qt/editor.py 的 `sync_inspector`）。

1. 沒選東西＝「專案」頁：影片與字幕狀態、主片段、剪點、疊加與音樂的摘要都在這一頁。
2. 選一句字幕（時間軸上點、或逐句清單裡點）＝「字幕」頁：第幾句、開始／結束／長度、文字（逐句校對的編輯框
   搬過來，同一個元件）；換一句跟著換。
3. 在屬性面板改開始／結束：字幕真的改、時間軸跟著、可以復原（復原後數字跟著回來）；照拖邊的規則夾在鄰句與
   片長之間、至少 0.1 秒，夾過在狀態列講；值沒變不記復原。時間軸上拖邊，數字跟著變。
4. 在屬性面板的編輯框改字：套用到那一句。
5. 「新增一句」打字中＝字幕頁寫「新增一句」、時間不能改；加進去之後換成那一句；Esc 取消就回專案頁。
6. 選素材＝素材頁：疊加寫「疊加的畫面」、只看到疊加的屬性；音樂寫「音樂」、只看到音樂的屬性。
7. 字幕與素材都選著：看最後點的那個；都取消回專案頁。
8. 〔字幕樣式…〕捷徑：按了等於按逐句校對那顆；那顆不能按時這顆也不能按。
9. 四頁籤照舊：編輯框還在逐句校對裡；`PlayerPanel.set_cue_times` 單獨也照規則夾。
"""
import copy
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

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
    print("SKIP 這個環境沒有 PySide6：略過剪輯器屬性面板")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import cue_panel as cue_panel_mod  # noqa: E402
    from gui_qt import editor as ed  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def inside(widget, ancestor):
        w = widget
        while w is not None:
            if w is ancestor:
                return True
            w = w.parentWidget()
        return False

    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["theme"] = "dark"
    ed.apply_initial_theme(app, "dark")
    win = ed.EditorWindow(cfg)
    win.resize(1440, 900)
    win.show()
    wait(200)
    p = win.player_panel
    p._ask_discard = lambda *a, **k: "discard"
    p._ask_project_discard = lambda *a, **k: "discard"
    t = p.timeline
    cp = win.cue_panel
    pages = win.inspector_pages

    def page():
        for key, w in pages.items():
            if win.inspector_stack.currentWidget() is w:
                return key
        return None

    # ----- 1. 專案頁 -----
    check("三頁：專案、字幕、素材", set(pages) == {"project", "cue", "track"}, str(set(pages)))
    check("沒選東西：專案頁", page() == "project" and win.inspector_mode() == "project")
    on_project = [n for n in ("info_label", "picture_btn", "proxy_box", "cut_combo", "cut_label", "preview_cut_box",
                              "seam_combo", "seam_spin", "cut_reset_btn", "track_label", "preview_box")
                  if not inside(getattr(p, n), pages["project"])]
    check("主片段、剪點、疊加與音樂的摘要都在專案頁", not on_project, str(on_project))
    check("素材屬性在素材頁", all(inside(w, pages["track"]) for ws in p._prop_widgets.values() for w in ws))
    check("編輯框與時間欄在字幕頁", all(inside(w, pages["cue"]) for w in
                                    (cp.editor, win.cue_start_spin, win.cue_end_spin, win.cue_style_btn)))

    t.set_duration(30)
    p.set_cues([{"start": 1.0, "end": 3.0, "text": "第一句"},
                {"start": 4.0, "end": 5.0, "text": "第二句"},
                {"start": 7.0, "end": 9.0, "text": "第三句"}])
    wait(50)
    check("載入字幕沒選：還是專案頁", page() == "project")

    # ----- 2. 選字幕 -----
    t.select_cue(1, seek=False)
    wait(20)
    check("時間軸選第 2 句：字幕頁", page() == "cue" and win.cue_page_title.text() == "字幕")
    check("寫第幾句", win.cue_pos_label.text() == "第 2 句，共 3 句", win.cue_pos_label.text())
    check("開始／結束／長度", win.cue_start_spin.value() == 4.0 and win.cue_end_spin.value() == 5.0
          and win.cue_length_label.text() == "1.000 秒", f"{win.cue_start_spin.value()} {win.cue_end_spin.value()}")
    check("逐句清單下面的說明寫編輯框在右邊", cp.note.text() == "第 2 句。" + ed.CUE_EDIT_HINT, cp.note.text())
    check("編輯框是那一句、可以打字", cp.editor.toPlainText() == "第二句" and cp.editor.isEnabled()
          and cp.editor.isVisible())
    win.statusBar().showMessage("哨兵")
    depth0 = len(p.history._done)
    cp.table.selectRow(2)
    wait(20)
    check("換一句只是填數字：不送出修改、不記復原、狀態列不動", len(p.history._done) == depth0
          and win.statusBar().currentMessage() == "哨兵", win.statusBar().currentMessage())
    check("逐句清單點第 3 句：跟著換", page() == "cue" and win.cue_pos_label.text() == "第 3 句，共 3 句"
          and win.cue_start_spin.value() == 7.0 and cp.editor.toPlainText() == "第三句")

    # ----- 3. 改時間 -----
    t.select_cue(1, seek=False)
    wait(20)
    win.cue_start_spin.setValue(3.5)
    wait(20)
    check("改開始：字幕真的改", p.cues[1]["start"] == 3.5 and p.cues[1]["end"] == 5.0, str(p.cues[1]))
    check("時間軸跟著", t._source[1]["start"] == 3.5, str(t._source[1]))
    check("長度跟著", win.cue_length_label.text() == "1.500 秒", win.cue_length_label.text())
    check("狀態列講改到哪", "3.500 → 5.000" in win.statusBar().currentMessage(), win.statusBar().currentMessage())
    p.undo()
    wait(20)
    check("復原：字幕回來、數字跟著回來", p.cues[1]["start"] == 4.0 and win.cue_start_spin.value() == 4.0,
          f"{p.cues[1]} {win.cue_start_spin.value()}")
    p.redo()
    p.undo()
    win.cue_start_spin.setValue(2.0)  # 前一句 3.0 結束
    wait(20)
    check("開始不能蓋到前一句：夾到 3.0", p.cues[1]["start"] == 3.0 and win.cue_start_spin.value() == 3.0,
          str(p.cues[1]))
    check("夾過在狀態列講", "已改到 3.000" in win.statusBar().currentMessage(), win.statusBar().currentMessage())
    win.cue_end_spin.setValue(8.0)  # 下一句 7.0 開始
    wait(20)
    check("結束不能蓋到下一句：夾到 7.0", p.cues[1]["end"] == 7.0 and win.cue_end_spin.value() == 7.0,
          str(p.cues[1]))
    win.cue_end_spin.setValue(1.0)
    wait(20)
    check("結束不能早於開始：至少 0.1 秒", abs(p.cues[1]["end"] - 3.1) < 1e-9, str(p.cues[1]))
    t.select_cue(2, seek=False)
    win.cue_end_spin.setValue(40.0)
    wait(20)
    check("結束不能超過片長 30 秒", p.cues[2]["end"] == 30.0, str(p.cues[2]))
    depth = len(p.history._done)
    win.cue_end_spin.setValue(30.0)
    win._set_cue_time(end=30.0)
    check("值沒變：不記復原、狀態列講沒變", len(p.history._done) == depth
          and "沒有變" in win.statusBar().currentMessage(), win.statusBar().currentMessage())
    p.undo()  # 片長那一步
    wait(20)
    check("復原片長那一步", p.cues[2]["end"] == 9.0 and win.cue_end_spin.value() == 9.0, str(p.cues[2]))
    t.cueTimesChanged.emit(2, 7.5, 9.5)  # 時間軸上拖邊
    wait(20)
    check("時間軸上拖：數字跟著變", win.cue_start_spin.value() == 7.5 and win.cue_end_spin.value() == 9.5,
          f"{win.cue_start_spin.value()} {win.cue_end_spin.value()}")

    # ----- 4. 改字 -----
    t.select_cue(0, seek=False)
    wait(20)
    cp.editor.setPlainText("第一句改過")
    check("編輯框改字：套用到那一句", cp.commit() and p.cues[0]["text"] == "第一句改過", str(p.cues[0]))

    # ----- 5. 新增一句 -----
    t.select_cue(-1, seek=False)
    wait(20)
    check("取消選取：回專案頁", page() == "project")
    p.player.setPosition(0)
    wait(20)
    check("新增一句：進入新增", cp.start_add())
    wait(20)
    check("新增中：字幕頁寫「新增一句」、時間不能改", page() == "cue" and win.cue_page_title.text() == "新增一句"
          and not win.cue_start_spin.isEnabled() and not win.cue_end_spin.isEnabled())
    QTest.keyClick(cp.editor, Qt.Key_Escape)
    wait(20)
    check("Esc 取消：回專案頁", page() == "project" and cp._adding is None, page())
    cp.start_add()
    cp.editor.setPlainText("開頭補一句")
    cp.commit()
    wait(20)
    check("加進去之後：換成那一句、時間能改", page() == "cue" and win.cue_page_title.text() == "字幕"
          and win.cue_pos_label.text() == "第 1 句，共 4 句" and win.cue_start_spin.isEnabled()
          and p.cues[0]["text"] == "開頭補一句", win.cue_pos_label.text())

    # ----- 6. 素材 -----
    p.tracks["overlays"] = [{"path": os.path.join(tmp, "b.png"), "at": 14.0, "in": 0.0, "out": 3.0, "length": 3.0}]
    p.tracks["music"] = [{"path": os.path.join(tmp, "m.mp3"), "at": 0.0, "in": 0.0, "out": 20.0, "length": 20.0,
                          "volume": 0.5}]
    p.refresh_tracks()
    t.select_cue(-1, seek=False)
    t.select_track_item("overlays", 0, seek=False)
    wait(20)
    check("選疊加：素材頁「疊加的畫面」", page() == "track" and win.track_page_title.text() == "疊加的畫面")
    check("只看到疊加的屬性", p.position_combo.isVisible() and not p.volume_spin.isVisible())
    check("寫檔名", p.prop_label.text() == "b.png", p.prop_label.text())
    t.select_track_item("music", 0, seek=False)
    wait(20)
    check("選音樂：素材頁「音樂」、只看到音樂的屬性", page() == "track" and win.track_page_title.text() == "音樂"
          and p.volume_spin.isVisible() and not p.position_combo.isVisible() and p.volume_spin.value() == 50)

    # ----- 7. 兩個都選著 -----
    t.select_cue(1, seek=False)
    wait(20)
    check("後點字幕：字幕頁", page() == "cue" and t.track_selected is not None)
    t.select_track_item("overlays", 0, seek=False)
    wait(20)
    check("後點素材：素材頁", page() == "track" and t.selected == 1)
    t.select_track_item("", -1, seek=False)
    wait(20)
    check("素材取消、字幕還選著：字幕頁", page() == "cue")
    t.select_cue(-1, seek=False)
    wait(20)
    check("都取消：專案頁", page() == "project")

    # ----- 8. 字幕樣式捷徑 -----
    pressed = []
    cp.style_btn.clicked.connect(lambda *_: pressed.append(1))
    cp.style_btn.setEnabled(True)
    win.cue_style_btn.click()
    wait(20)
    check("〔字幕樣式…〕捷徑＝按逐句校對那顆", pressed == [1], str(pressed))
    if cp.style_dialog is not None:
        cp.style_dialog.close()
    cp.style_btn.setEnabled(False)
    check("那顆不能按：這顆也不能按", not win.cue_style_btn.isEnabled())
    cp.style_btn.setEnabled(True)
    check("那顆能按：這顆也能按", win.cue_style_btn.isEnabled())
    win.close()

    # ----- 9. 四頁籤照舊 -----
    qt_app.apply_theme(app, "light")
    cfg2 = copy.deepcopy(config.DEFAULT_CONFIG)
    win2 = qt_app.MainWindow(cfg2)
    win2.show()
    wait(50)
    p2 = win2.player_panel
    p2._ask_discard = lambda *a, **k: "discard"
    p2._ask_project_discard = lambda *a, **k: "discard"
    check("四頁籤：編輯框還在逐句校對裡、說明照舊", inside(win2.cue_panel.editor, win2.cue_panel)
          and win2.cue_panel.hint == cue_panel_mod.HINT)
    p2.timeline.set_duration(10)
    p2.set_cues([{"start": 1.0, "end": 2.0, "text": "甲"}, {"start": 3.0, "end": 4.0, "text": "乙"}])
    check("set_cue_times：一次改開始與結束", p2.set_cue_times(0, start=0.5, end=2.5) == (0.5, 2.5)
          and p2.cues[0]["start"] == 0.5 and p2.cues[0]["end"] == 2.5)
    check("set_cue_times：夾在鄰句", p2.set_cue_times(1, start=1.0) == (2.5, 4.0))
    check("set_cue_times：不超過片長", p2.set_cue_times(1, end=99) == (2.5, 10.0))
    p2.undo()
    p2.undo()
    p2.undo()
    check("set_cue_times：三步都能復原", p2.cues[0]["start"] == 1.0 and p2.cues[1]["start"] == 3.0
          and p2.cues[1]["end"] == 4.0, str(p2.cues))
    try:
        p2.set_cue_times(5, start=1.0)
        bad_index = False
    except IndexError:
        bad_index = True
    check("set_cue_times：沒有那句拋 IndexError", bad_index)
    win2.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("剪輯器屬性面板（E-3a）測試全數通過。")
