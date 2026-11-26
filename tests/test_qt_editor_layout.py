# -*- coding: utf-8 -*-
"""
剪輯器版面 E-7b：切成預設、版面切換、剪輯器版面介紹（gui_qt/app.py main()、gui_qt/editor.py）。

1. main() 什麼都沒給：開剪輯器版面；事件迴圈一跑就跳「剪輯器版面介紹」（剪輯器自己的內容，不是四頁籤講①～④那份）。
   勾「不再顯示」關掉、關掉主視窗：config.json 記 editor_guide_seen，四頁籤的 qt_guide_seen 不動；下次不跳。
2. 版面按鈕（狀態列右邊，兩種版面都有）：剪輯器裡寫〔改用四頁籤版面…〕；按了記下次開四頁籤、字改成可以取消、
   狀態列講清楚這次的視窗不變；再按取消。選單「檢視」也有同一個。
3. 記了四頁籤、關掉：下次 main() 開四頁籤（按鈕寫〔改用剪輯器版面…〕）；--editor 照樣開剪輯器；四頁籤按按鈕改回剪輯器。
4. 剪輯器的頂列〔?〕與選單「說明」打開剪輯器版面介紹；四頁籤的〔新介面導覽…〕照舊是四頁籤那份。
5. 剪輯器的開場白不再寫「試用」；標題不變。
6. `python main.py --tabs`（不加 --qt）：開新介面的四頁籤，不會被當成影片檔名丟給命令列批次。
"""
import copy
import json
import os
import subprocess as sp
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
    print("SKIP 這個環境沒有 PySide6：略過版面切換")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import editor as ed  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from gui_qt.guide_dialog import GuideDialog  # noqa: E402
    from subtitle import editorguide as eg  # noqa: E402
    from subtitle import qtguide  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")
    qt_app.UPDATE_CHECK_DELAY_MS = 10 ** 9  # 這裡不查新版本

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    seen_wins = []

    def fake_exec():
        """main() 最後的 app.exec()：跑一下事件迴圈（讓 singleShot 跳介紹）就回來。"""
        wait(250)
        seen_wins.extend(w for w in QApplication.topLevelWidgets() if isinstance(w, qt_app.MainWindow)
                         and w.isVisible())
        return 0

    def guides():
        return [w for w in QApplication.topLevelWidgets() if isinstance(w, GuideDialog) and w.isVisible()]

    def saved():
        try:
            with open(config.CONFIG_PATH, encoding="utf-8") as fp:
                return json.load(fp)
        except (OSError, ValueError):
            return {}

    def open_main(*args):
        seen_wins.clear()
        rc = qt_app.main(["prog", *args])
        win = seen_wins[0] if seen_wins else None
        if win is not None:
            win.player_panel._ask_discard = lambda *a, **k: "discard"
            win.player_panel._ask_project_discard = lambda *a, **k: "discard"
        return rc, win

    def close(win):
        for g in guides():
            g.close()
        win.close()
        wait(50)

    real_exec = app.exec
    app.exec = fake_exec
    try:
        # ----- 1 -----
        rc, win = open_main()
        check("什麼都沒給：開剪輯器版面", rc == 0 and isinstance(win, ed.EditorWindow), str(type(win)))
        shown = guides()
        check("事件迴圈一跑就跳一個介紹", len(shown) == 1, str(len(shown)))
        g = shown[0] if shown else None
        check("跳的是剪輯器版面介紹（標題、內容）", g is not None and g.windowTitle() == ed.GUIDE_TITLE
              and g.body.toPlainText() == eg.body_text())
        check("介紹裡不是四頁籤那份（沒有①→④）", g is not None and "① 素材與剪輯 →" not in g.body.toPlainText())
        if g is not None:
            g.never_box.setChecked(True)
            QTest.mouseClick(g.start_btn, Qt.LeftButton)
            wait(30)
        check("關掉介紹：這次的設定記不再顯示", win.config_data.get(eg.CONFIG_KEY) == eg.NEVER_SHOW)

        # ----- 2 -----
        btn = win.layout_btn
        check("狀態列右邊有版面按鈕", btn.isVisible() and btn.parent() is win.statusBar())
        check("剪輯器裡寫〔改用四頁籤版面…〕", btn.text() == "改用四頁籤版面…", btn.text())
        check("提示講清楚：下次開啟、這次不變", "下次開啟" in btn.toolTip() and "這次的視窗不變" in btn.toolTip())
        btn.click()
        check("按了：記下次開四頁籤", win.config_data.get(eg.LAYOUT_KEY) == eg.TABS and win.next_layout() == eg.TABS)
        check("字改成可以取消", btn.text() == "下次開：四頁籤版面（按此取消）", btn.text())
        msg = win.statusBar().currentMessage()
        check("狀態列講下次開四頁籤、這次的視窗不變", "下次開啟新介面是四頁籤版面" in msg and "這次的視窗不變" in msg, msg)
        btn.click()
        check("再按：取消（照舊開剪輯器）", win.next_layout() == eg.EDITOR and btn.text() == "改用四頁籤版面…")
        check("取消後狀態列講照舊", "下次開啟照舊是剪輯器版面" in win.statusBar().currentMessage())
        action = win.menu_actions["檢視/切換下次開啟的版面（四頁籤／剪輯器）"]
        action.trigger()
        check("選單「檢視」的同一項：一樣記四頁籤", win.next_layout() == eg.TABS and btn.text().startswith("下次開"))

        # ----- 4、5（剪輯器這一邊） -----
        win.guide_tool.click()
        wait(30)
        shown = guides()
        check("頂列〔?〕打開剪輯器版面介紹", len(shown) == 1 and shown[0].windowTitle() == ed.GUIDE_TITLE)
        for d in shown:
            d.close()
        win.menu_actions["說明/剪輯器版面介紹"].trigger()
        wait(30)
        check("選單「說明」也是", len(guides()) == 1 and guides()[0].windowTitle() == ed.GUIDE_TITLE)
        for d in guides():
            d.close()
        check("開場白不再寫「試用」、指向介紹", ed.STATUS_INTRO and "試用" not in ed.STATUS_INTRO
              and "剪輯器版面介紹" in ed.STATUS_INTRO)
        check("標題照舊", win.windowTitle() == ed.EDITOR_TITLE)
        close(win)
        data = saved()
        check("關掉主視窗：config.json 記 qt_layout=tabs", data.get(eg.LAYOUT_KEY) == eg.TABS, str(data)[:120])
        check("關掉主視窗：記剪輯器版面介紹看過（不再顯示）", data.get(eg.CONFIG_KEY) == eg.NEVER_SHOW)
        check("四頁籤導覽的紀錄不動", qtguide.CONFIG_KEY not in data)

        # ----- 3 -----
        rc, win = open_main()
        check("記了四頁籤：下次開四頁籤", rc == 0 and type(win) is qt_app.MainWindow, str(type(win)))
        check("四頁籤的按鈕寫〔改用剪輯器版面…〕", win.layout_btn.isVisible()
              and win.layout_btn.text() == "改用剪輯器版面…", win.layout_btn.text())
        shown = guides()
        check("四頁籤跳的是四頁籤那份導覽（沒看過）", len(shown) == 1 and shown[0].windowTitle() == "新介面導覽"
              and shown[0].body.toPlainText() == qtguide.body_text(qt_app.APP_VERSION))
        for d in shown:
            d.close()
        win.layout_btn.click()
        check("四頁籤按按鈕：記下次開剪輯器", win.next_layout() == eg.EDITOR
              and win.layout_btn.text() == "下次開：剪輯器版面（按此取消）")
        close(win)
        check("存回去：qt_layout=editor", saved().get(eg.LAYOUT_KEY) == eg.EDITOR)
        rc, win = open_main()
        check("下次開回剪輯器；介紹看過不再跳", isinstance(win, ed.EditorWindow) and not guides())
        close(win)
        data = saved()
        data[eg.LAYOUT_KEY] = eg.TABS
        with open(config.CONFIG_PATH, "w", encoding="utf-8") as fp:
            json.dump(data, fp)
        rc, win = open_main("--editor")
        check("設定是四頁籤，但給 --editor：開剪輯器", isinstance(win, ed.EditorWindow))
        close(win)
        rc, win = open_main()
        check("設定是四頁籤、什麼都沒給：開四頁籤", type(win) is qt_app.MainWindow)
        close(win)

        # 自檢模式不跳介紹、不存設定
        before = saved()
        rc = qt_app.main(["prog", qt_app.SELFTEST_FLAG])
        wait(100)
        check("自檢模式：不跳介紹", rc == 2 and not guides())
        check("自檢模式：設定沒動", saved() == before)
    finally:
        app.exec = real_exec

    # ----- 4（四頁籤這一邊）-----
    win2 = qt_app.MainWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    win2.player_panel._ask_discard = lambda *a, **k: "discard"
    win2.player_panel._ask_project_discard = lambda *a, **k: "discard"
    d = win2.open_guide()
    check("四頁籤的〔新介面導覽…〕照舊是四頁籤那份", d.windowTitle() == "新介面導覽"
          and d.body.toPlainText() == qtguide.body_text(qt_app.APP_VERSION))
    d.close()
    check("editor_requested：設定與旗標", ed.editor_requested([]) and not ed.editor_requested([], "tabs")
          and ed.editor_requested(["--editor"], "tabs") and not ed.editor_requested(["--tabs"]))
    win2.close()

    # ----- 6 -----
    out = os.path.join(tmp, "selftest.json")
    clip = os.path.join(ROOT, "research", "qt_probe", "probe_clip.mp4")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    proc = sp.run([sys.executable, "-B", "main.py", "--tabs", "--selftest", out, clip], cwd=ROOT, env=env,
                  capture_output=True, timeout=180)
    res = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else {}
    check("main.py --tabs（不加 --qt）：開新介面的四頁籤、自檢通過", proc.returncode == 0 and res.get("ok") is True
          and res.get("layout") == "tabs", f"rc={proc.returncode} {res} {proc.stdout[-200:]!r}")
    os.remove(out)
    proc = sp.run([sys.executable, "-B", "main.py", "--editor", "--selftest", out, clip], cwd=ROOT, env=env,
                  capture_output=True, timeout=180)
    res = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else {}
    check("main.py --editor（不加 --qt）：開剪輯器版面", proc.returncode == 0 and res.get("layout") == "editor"
          and res.get("window_title") == ed.EDITOR_TITLE, f"rc={proc.returncode} {res}")

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("切成預設與版面切換（E-7b）測試全數通過。")
