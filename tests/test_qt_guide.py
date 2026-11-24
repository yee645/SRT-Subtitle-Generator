# -*- coding: utf-8 -*-
"""
3.0 第 11 項第三十五階段：Qt 版首次啟動導覽（gui_qt/guide_dialog.py＋gui_qt/app.py 的〔新介面導覽…〕）。

內容與規則在 test_qtguide.py；這裡 QTest 真的點：

1. 狀態列右邊有〔新介面導覽…〕（在深淺色切換的左邊）；狀態列的開場白改成「一般版的功能都搬過來了」、指向導覽，
   不再叫人「其餘請先用一般版」。測試直接建的主視窗不會自己跳導覽。
2. 第一次（設定裡沒有 qt_guide_seen）：maybe_show_guide 跳出導覽；不擋主視窗；內容就是 qtguide.body_text()、
   從頭看；「不再顯示」預設沒勾。
3. 按〔開始使用〕：關掉、記「看過這一版」；再呼叫 maybe_show_guide 不跳。
4. 狀態列按鈕隨時再打開（同一個視窗、叫到前面）；勾「不再顯示」按右上角 × 關：記 never、只回報一次；
   按 Esc 關也要記（以前只接 closeEvent，Esc 走 reject 不經過那裡）；關了再 close() 不會多記一次。
5. 看過舊版導覽：再跳；勾過 never：不跳。
6. 全程（以上）沒寫 config.json。
7. 真的存得回去：從 main() 開（讀設定檔）→ 事件迴圈一跑就跳導覽 → 關掉導覽、關掉主視窗 → config.json 裡有
   qt_guide_seen；下次 main() 不跳。自檢模式不跳。
"""
import copy
import json
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
    print("SKIP 這個環境沒有 PySide6：略過首次啟動導覽")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import guide_dialog as gd  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import qtguide  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def visible_guides():
        return [w for w in QApplication.topLevelWidgets() if isinstance(w, gd.GuideDialog) and w.isVisible()]

    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.show()
    wait(100)

    # ----- 1 -----
    bar = win.statusBar()
    btn = win.guide_btn
    check("狀態列右邊有〔新介面導覽…〕", btn.isVisible() and btn.text() == "新介面導覽…" and btn.parent() is bar)
    check("在深淺色切換的左邊", btn.x() < win.theme_btn.x(), f"{btn.x()} vs {win.theme_btn.x()}")
    msg = bar.currentMessage()
    check("開場白：一般版的功能都搬過來了、指向導覽，不再叫人先用一般版",
          msg == qt_app.STATUS_INTRO and "一般版的功能都搬過來了" in msg and "〔新介面導覽…〕" in msg
          and "先用一般版" not in msg and "還在一般版" not in msg, msg)
    check("測試直接建的主視窗不會自己跳導覽", win.guide_dialog is None and not visible_guides())

    # ----- 2 -----
    check("沒看過：maybe_show_guide 會跳", qtguide.CONFIG_KEY not in cfg and win.maybe_show_guide() is True)
    wait(50)
    dlg = win.guide_dialog
    check("導覽出現、不擋主視窗", dlg is not None and dlg.isVisible() and not dlg.isModal()
          and dlg.windowTitle() == "新介面導覽")
    check("內容就是 qtguide.body_text()、唯讀", dlg.body.toPlainText() == qtguide.body_text(qt_app.APP_VERSION) and dlg.body.isReadOnly())
    check("從頭看、「不再顯示」預設沒勾", dlg.body.verticalScrollBar().value() == 0 and not dlg.never_box.isChecked()
          and dlg.never_box.text() == "不再顯示這個導覽")
    check("開著時主視窗的按鈕點得到（不擋）", win.isEnabled() and win.theme_btn.isEnabled())

    # ----- 3 -----
    QTest.mouseClick(dlg.start_btn, Qt.LeftButton)
    wait(50)
    check("〔開始使用〕：關掉、記看過這一版", not dlg.isVisible() and cfg[qtguide.CONFIG_KEY] == qtguide.guide_version(qt_app.APP_VERSION),
          str(cfg.get(qtguide.CONFIG_KEY)))
    check("看過了：maybe_show_guide 不跳", win.maybe_show_guide() is False and not dlg.isVisible())

    # ----- 4 -----
    reports = []
    dlg.closedWith.connect(reports.append)
    dlg.body.verticalScrollBar().setValue(dlg.body.verticalScrollBar().maximum())
    QTest.mouseClick(btn, Qt.LeftButton)
    wait(50)
    check("狀態列按鈕再打開：同一個視窗、又從頭看", win.guide_dialog is dlg and dlg.isVisible()
          and dlg.body.verticalScrollBar().value() == 0)
    check("已經開著再按：不會多開一個", win.open_guide() is dlg and len(visible_guides()) == 1)
    dlg.never_box.setChecked(True)
    dlg.close()  # 右上角的 ×
    wait(50)
    check("勾「不再顯示」按 × 關：記 never、只回報一次", cfg[qtguide.CONFIG_KEY] == qtguide.NEVER_SHOW
          and reports == [True], str(reports))
    check("勾過了：maybe_show_guide 不跳", win.maybe_show_guide() is False and not dlg.isVisible())
    dlg.close()
    check("已經關了再 close()：不會多記一次", reports == [True], str(reports))
    cfg[qtguide.CONFIG_KEY] = ""
    win.open_guide()
    wait(50)
    dlg.never_box.setChecked(False)
    QTest.keyClick(dlg, Qt.Key_Escape)
    wait(50)
    check("按 Esc 關：也記下來（沒勾＝看過這一版）", not dlg.isVisible() and cfg[qtguide.CONFIG_KEY] == qtguide.guide_version(qt_app.APP_VERSION)
          and reports == [True, False], f"{cfg[qtguide.CONFIG_KEY]!r} {reports}")

    # ----- 5 -----
    cfg[qtguide.CONFIG_KEY] = "3.0-preview-0"
    check("看過舊版導覽：再跳一次", win.maybe_show_guide() is True and dlg.isVisible())
    dlg.never_box.setChecked(False)
    QTest.mouseClick(dlg.start_btn, Qt.LeftButton)
    wait(50)
    check("沒勾就關：記這一版（不是 never）", cfg[qtguide.CONFIG_KEY] == qtguide.guide_version(qt_app.APP_VERSION))

    # ----- 6 -----
    check("全程沒寫 config.json", not os.path.exists(config.CONFIG_PATH))
    win.close()
    wait(50)

    # ----- 7 -----
    qt_app.UPDATE_CHECK_DELAY_MS = 10 ** 9  # 這裡不查新版本
    seen_wins = []

    def fake_exec():
        """main() 最後的 app.exec()：跑一下事件迴圈（讓 singleShot 跳導覽）就回來，不卡住測試。"""
        wait(200)
        seen_wins.extend(w for w in QApplication.topLevelWidgets() if isinstance(w, qt_app.MainWindow)
                         and w.isVisible())
        return 0

    real_exec = app.exec
    app.exec = fake_exec
    try:
        before = {id(w) for w in QApplication.topLevelWidgets()}
        rc = qt_app.main(["prog"])
        guides = visible_guides()
        check("從 main() 開：事件迴圈一跑就跳導覽", rc == 0 and len(guides) == 1 and len(seen_wins) == 1,
              f"{rc} {len(guides)} {len(seen_wins)}")
        mwin = seen_wins[0] if seen_wins else None
        if mwin is not None and guides:
            mwin.player_panel._ask_discard = lambda *a, **k: "discard"
            mwin.player_panel._ask_project_discard = lambda *a, **k: "discard"
            guides[0].never_box.setChecked(True)
            QTest.mouseClick(guides[0].start_btn, Qt.LeftButton)
            wait(50)
            mwin.close()
            wait(50)
        try:
            with open(config.CONFIG_PATH, encoding="utf-8") as fp:
                saved = json.load(fp)
        except (OSError, ValueError) as exc:
            saved = {"錯誤": repr(exc)}
        check("關掉主視窗：qt_guide_seen 存進 config.json", saved.get(qtguide.CONFIG_KEY) == qtguide.NEVER_SHOW,
              str(saved)[:200])
        check("讀回來還在（load_config 不會丟掉這一格）", config.load_config().get(qtguide.CONFIG_KEY) == qtguide.NEVER_SHOW)

        seen_wins.clear()
        rc = qt_app.main(["prog"])
        check("下次 main()：不跳", rc == 0 and not visible_guides() and len(seen_wins) == 1)
        for w in seen_wins:
            w.player_panel._ask_discard = lambda *a, **k: "discard"
            w.player_panel._ask_project_discard = lambda *a, **k: "discard"
            w.close()
        wait(50)

        # 自檢模式：主視窗建好就 return（參數不夠時回 2），不排導覽
        os.remove(config.CONFIG_PATH)
        rc = qt_app.main(["prog", qt_app.SELFTEST_FLAG])
        wait(200)
        check("自檢模式：不跳導覽", rc == 2 and not visible_guides())
    finally:
        app.exec = real_exec

    # ----- 8：3.0.0 發版時（APP_VERSION 一改）標題、開場白、導覽一起換成正式版 -----
    import subprocess  # noqa: E402
    probe = ("import sys, updater; updater.APP_VERSION = sys.argv[1]\n"
             "from gui_qt import app as a; from gui_qt import guide_dialog as d; from subtitle import qtguide as g\n"
             "print(a.WINDOW_TITLE); print(a.STATUS_INTRO); print(d.APP_VERSION == sys.argv[1]); print(a.FORMAL)\n")
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    outs = {}
    for ver in ("3.0.0", "2.9.9"):
        r = subprocess.run([sys.executable, "-B", "-c", probe, ver], cwd=root_dir, capture_output=True, text=True,
                           encoding="utf-8", timeout=120, env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
        outs[ver] = r.stdout.splitlines()
    f, p = outs["3.0.0"], outs["2.9.9"]
    check("APP_VERSION 3.0.0：標題、開場白不再講預覽版、導覽用正式版那一套",
          len(f) == 4 and f[0] == "SRT 字幕生成器 3.0（v3.0.0）" and f[1].startswith("3.0 新介面：")
          and "預覽版" not in f[1] and f[2] == "True" and f[3] == "True", str(f))
    check("APP_VERSION 2.9.9：照舊是預覽版", len(p) == 4 and p[0] == "SRT 字幕生成器 3.0 預覽版（v2.9.9）"
          and p[1].startswith("3.0 預覽版：") and p[3] == "False", str(p))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 首次啟動導覽介面測試全數通過。")
