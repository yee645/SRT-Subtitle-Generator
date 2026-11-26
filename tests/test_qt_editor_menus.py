# -*- coding: utf-8 -*-
"""
剪輯器版面改版 E-6b：選單列、面板收合、預覽放大（gui_qt/editor.py）。

1. 選單列五個：檔案、編輯、檢視、播放、說明；每一項都接到現有的按鈕或動作（`MENUS`），寫上快捷鍵（只是提示，
   不另外註冊：同一組鍵註冊兩次 Qt 會兩個都不觸發——按鍵照樣有效）。
2. 選單項目按了＝按那顆按鈕；打開選單時照那顆能不能按。
3. 「檢視」選單：切到左側四區；顯示／收起左側面板與屬性面板（打勾跟著實際狀態）；收起時預覽變寬。
4. 〔專注預覽〕：兩個面板一起收起來、再按放回；手動把兩個都收起來，按鈕也跟著亮。
5. 預覽放大：符合視窗、2 倍、4 倍；放大時可以拖著看；選單與下拉選單同步；換回符合視窗還原。
6. 四頁籤沒有選單列。
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
    print("SKIP 這個環境沒有 PySide6：略過剪輯器選單列")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtGui import QShortcut  # noqa: E402
    from PySide6.QtWidgets import QApplication, QGraphicsView  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
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

    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["theme"] = "dark"
    ed.apply_initial_theme(app, "dark")
    win = ed.EditorWindow(cfg)
    win.resize(1440, 900)
    win.show()
    wait(100)
    p = win.player_panel
    p._ask_discard = lambda *a, **k: "discard"
    p._ask_project_discard = lambda *a, **k: "discard"

    # ----- 1 -----
    bar = win.menuBar()
    titles = [a.text() for a in bar.actions()]
    check("選單列五個", titles == ["檔案", "編輯", "檢視", "播放", "說明"], str(titles))
    wanted = sum(1 for _t, entries in ed.MENUS for e in entries if e is not None)
    check("每一項都建出來了", len(win.menu_actions) == wanted, f"{len(win.menu_actions)} / {wanted}")
    bad = []
    for title, entries in ed.MENUS:
        for entry in entries or ():
            if entry is None:
                continue
            text, target, key = entry
            if not target.startswith("@"):
                try:
                    ed.resolve(win, target)
                except AttributeError:
                    bad.append(target)
            action = win.menu_actions[f"{title}/{text}"]
            if key and not action.text().endswith("\t" + key):
                bad.append(action.text())
            if not action.shortcut().isEmpty():
                bad.append("註冊了鍵：" + text)
    check("目標都找得到、快捷鍵寫在選單上、沒有另外註冊", not bad, str(bad))
    keys = {sc.key().toString() for sc in win.findChildren(QShortcut)}
    check("按鍵照樣註冊在視窗上（Ctrl+E、Ctrl+B、Space）", {"Ctrl+E", "Ctrl+B", "Space"} <= keys)

    # ----- 2 -----
    clicked = []
    p.redo_btn.clicked.connect(lambda *_: clicked.append("redo"))
    p.redo_btn.setEnabled(True)
    win._sync_menus()
    redo = win.menu_actions["編輯/重做"]
    check("能按的那顆：選單項目也能按", redo.isEnabled())
    redo.trigger()
    check("選單項目＝按那顆", clicked == ["redo"], str(clicked))
    p.redo_btn.setEnabled(False)
    win.menuBar().actions()[1].menu().aboutToShow.emit()
    check("那顆不能按：打開選單時跟著不能按", not redo.isEnabled())
    win.menu_actions["檢視/健檢"].trigger()
    check("檢視／健檢：切到健檢", win.current_section() == "health")
    win.menu_actions["檢視/字幕"].trigger()
    check("檢視／字幕：切到字幕", win.current_section() == "subtitles")
    win.menu_actions["檔案/匯出…"].trigger()
    check("檔案／匯出…：開匯出視窗", win.export_dialog.isVisible())
    win.export_dialog.close()

    # ----- 3 -----
    preview_w = win.preview_panel.width()
    win.left_panel_action.setChecked(False)
    wait(50)
    check("收起左側面板", not win.left_panel.isVisible() and win.inspector_panel.isVisible())
    check("預覽變寬", win.preview_panel.width() > preview_w, f"{preview_w} → {win.preview_panel.width()}")
    win.set_panel_visible("inspector", False)
    wait(50)
    check("用方法收起屬性面板：選單的勾跟著拿掉", not win.inspector_action.isChecked()
          and not win.inspector_panel.isVisible())
    check("兩個都收起來：〔專注預覽〕跟著亮", win.focus_tool.isChecked())
    win.left_panel_action.setChecked(True)
    wait(50)
    check("放回左側面板：〔專注預覽〕不亮", win.left_panel.isVisible() and not win.focus_tool.isChecked())
    win.inspector_action.setChecked(True)
    wait(50)

    # ----- 4 -----
    win.focus_tool.click()
    wait(50)
    check("〔專注預覽〕：兩個面板一起收起來", not win.left_panel.isVisible() and not win.inspector_panel.isVisible()
          and not win.left_panel_action.isChecked() and not win.inspector_action.isChecked())
    win.focus_tool.click()
    wait(50)
    check("再按一次：放回來", win.left_panel.isVisible() and win.inspector_panel.isVisible()
          and win.left_panel_action.isChecked() and win.inspector_action.isChecked())

    # ----- 5 -----
    view = p.view
    check("預覽放大三種", [win.preview_zoom_combo.itemText(i) for i in range(win.preview_zoom_combo.count())]
          == ["符合視窗", "放大 2 倍", "放大 4 倍"])
    check("一開始符合視窗、不能拖", view.transform().m11() == 1.0 and view.dragMode() == QGraphicsView.NoDrag)
    win.preview_zoom_combo.setCurrentIndex(1)
    check("2 倍：畫面放大、可以拖著看", view.transform().m11() == 2.0
          and view.dragMode() == QGraphicsView.ScrollHandDrag)
    check("選單的勾跟著下拉選單", [a.isChecked() for a in win.preview_zoom_actions] == [False, True, False])
    win.preview_zoom_actions[2].trigger()
    check("選單選 4 倍：下拉選單跟著、畫面 4 倍", win.preview_zoom_combo.currentIndex() == 2
          and view.transform().m11() == 4.0)
    win.set_preview_zoom(1.0)
    check("換回符合視窗：還原、不能拖", view.transform().isIdentity() and view.dragMode() == QGraphicsView.NoDrag
          and win.preview_zoom_combo.currentIndex() == 0 and win.preview_zoom_actions[0].isChecked())
    win.close()

    # ----- 6 -----
    qt_app.apply_theme(app, "light")
    win2 = qt_app.MainWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    win2.show()
    wait(50)
    check("四頁籤沒有選單列", not win2.menuBar().actions())
    p2 = win2.player_panel
    p2._ask_discard = lambda *a, **k: "discard"
    p2._ask_project_discard = lambda *a, **k: "discard"
    win2.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("剪輯器選單列與面板收合（E-6b）測試全數通過。")
