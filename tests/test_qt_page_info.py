# -*- coding: utf-8 -*-
"""
剪輯器版面 E-9n：智慧剪輯、健檢頁首那段五、六行的說明收進標題旁〔說明〕的提示（editor-ui-review：「說明文字放提示裡，
不要整段攤在畫面上」；E-9b 收了媒體頁與逐句清單，這兩頁還攤著）。

1. 剪輯器：兩頁的說明段藏起來；標題旁一顆〔說明〕（help 圖示），提示＝「<標題>說明：」＋原本那段（剪輯器的說法，逐字）。
2. 提示用 <p> 包起來才會換行（純文字的長提示 Qt 不顯示）：點〔說明〕跳出來的提示是窄的一塊、不是一長行。
3. 螢幕閱讀器：名字是「智慧剪輯說明」「健檢說明」，說明是純文字（沒有 <p> 標記）。
4. 四頁籤照舊：說明段照樣攤開、一字不改。
"""
import copy
import os
import shutil
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

if PySide6 is None or not shutil.which("ffmpeg"):
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過頁首說明")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
    from PySide6.QtWidgets import QApplication, QToolTip  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import editor as ed  # noqa: E402
    from gui_qt import health_panel as hpm  # noqa: E402
    from gui_qt import review_panel as rpm  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from gui_qt.places import for_editor  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    ed.apply_initial_theme(app, "light")
    win = ed.EditorWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    win.resize(1440, 900)
    win.show()
    wait(100)

    pages = (("smart", "智慧剪輯", win.review_panel, rpm.PAGE_NOTE), ("health", "健檢", win.health_panel, hpm.PAGE_NOTE))
    for key, title, panel, raw in pages:
        win.show_section(key)
        wait(40)
        note = panel.page_note
        info = win.page_info.get(title)
        # ----- 1 -----
        check(f"{title}：說明段藏起來", not note.isVisible())
        check(f"{title}：說明段的字還是剪輯器的說法（逐字）", note.text() == for_editor(raw), note.text()[:40])
        check(f"{title}：標題旁有〔說明〕而且看得到", info is not None and info.isVisible())
        tip = info.toolTip() if info else ""
        check(f"{title}：提示＝標題說明＋那段說明，用 <p> 包起來",
              tip == f"<p>{title}說明：{note.text()}</p>", tip[:60])
        title_label = next((w for w in win.left_pages[key].findChildren(ed.QLabel) if w.text() == title), None)
        check(f"{title}：〔說明〕跟標題同一列", title_label is not None and info is not None
              and abs(title_label.mapTo(win, title_label.rect().center()).y()
                      - info.mapTo(win, info.rect().center()).y()) <= 4)
        # ----- 3 -----
        check(f"{title}：螢幕閱讀器念「{title}說明」", info is not None and info.accessibleName() == f"{title}說明",
              info.accessibleName() if info else "")
        check(f"{title}：說明是純文字", info is not None and info.accessibleDescription() == f"{title}說明：{note.text()}",
              info.accessibleDescription()[:40] if info else "")
        # ----- 2 -----
        win.show_page_info(title)
        wait(80)
        shown = [w for w in QApplication.topLevelWidgets()
                 if w.metaObject().className() == "QTipLabel" and w.isVisible()]
        check(f"{title}：點〔說明〕跳出提示", QToolTip.isVisible() and QToolTip.text() == tip and len(shown) == 1,
              QToolTip.text()[:40])
        check(f"{title}：提示換行成一塊（不是一長行）", shown and 150 < shown[0].width() <= 600
              and shown[0].height() > 3 * shown[0].fontMetrics().height(), shown[0].size() if shown else None)
        QToolTip.hideText()
        wait(30)

    check("（對照）沒有 <p> 的提示照舊：〔復原〕的名字", ed.accessible_label("復原：復原上一次（Ctrl+Z）") == "復原"
          and ed.plain_tip("a < b") == "a < b")

    # ----- 4 -----
    tabs = qt_app.MainWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    tabs.resize(1440, 900)
    tabs.show()
    wait(80)
    for idx, panel, raw in ((0, tabs.review_panel, rpm.PAGE_NOTE), (2, tabs.health_panel, hpm.PAGE_NOTE)):
        tabs.tabs.setCurrentIndex(idx)
        wait(40)
        check(f"四頁籤：第 {idx + 1} 頁說明段照樣攤開、一字不改",
              panel.page_note.isVisible() and panel.page_note.text() == raw, panel.page_note.text()[:30])

    for w in (win, tabs):
        w.player_panel.shutdown()
        w.close()
    wait(50)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("頁首說明收進提示（E-9n）測試全數通過。")
