# -*- coding: utf-8 -*-
"""
3.0 第 11 項第三十階段：Qt 版的「有新版本」提示（gui_qt/app.py 的提示列＋gui_qt/update_notice.py）。

查法在 test_updatecheck.py；這裡換掉 `updatecheck.fetch_latest`，不連網。

1. 平常收著；測試建的主視窗不會自己去查（只有 main() 開的視窗啟動 1.5 秒後才查；自檢模式不查）。
2. 查到新版：頁籤上方出現提示（講新舊版本、下載哪個、不能自動更新）；提示上寫明會送出去的只有查版本的連線請求。
3. 〔開啟下載頁〕開的是那一版的 Release 頁面。
4. 〔這版不再提醒〕：收起來、記進設定（qt_update.skipped_version，別的項目留著）；同一版再查到不提示，更新的版本照樣提示。
5. 〔關閉提示〕：只收起來，不記。
6. 沒有新版（離線、查不到）：不出現。背景查真的走 UpdateWorker（查的是目前的版本）。
"""
import os
import sys

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
    print("SKIP 這個環境沒有 PySide6：略過新版本提示")
else:
    import tempfile

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import updatecheck as uc  # noqa: E402
    from updater import APP_VERSION  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait_until(cond, timeout_ms=5000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(20)
            waited += 20
        return cond()

    calls = []
    real_fetch = uc.fetch_latest
    info = {"version": "v99.0.0", "page": "https://github.com/yee645/SRT-Subtitle-Generator/releases/tag/v99.0.0",
            "notes": "", "qt_zip": "SRT-Subtitle-Generator-Qt-preview-v99.0.0.zip"}
    uc.fetch_latest = lambda current, **kw: (calls.append(current), dict(info))[1]
    try:
        cfg = {"qt_update": {"其他": 1}}
        win = qt_app.MainWindow(cfg)
        p = win.player_panel
        p._ask_discard = lambda *a, **k: "discard"
        p._ask_project_discard = lambda *a, **k: "discard"
        win.resize(1280, 800)
        win.show()
        wait(1800)

        # ----- 1 -----
        check("平常收著", not win.update_banner.isVisible())
        check("測試建的主視窗不會自己去查", calls == [])
        src = open(qt_app.__file__, encoding="utf-8").read()
        main_src = src[src.index("def main("):]
        check("main() 開好視窗 1.5 秒後才查；自檢模式在那之前就回去了（不查）",
              "QTimer.singleShot(UPDATE_CHECK_DELAY_MS, win.start_update_check)" in main_src
              and main_src.index("return selftest.run(") < main_src.index("win.start_update_check")
              and qt_app.UPDATE_CHECK_DELAY_MS == 1500)

        # ----- 6（背景查） -----
        win.start_update_check()
        check("背景查：查的是目前的版本", wait_until(lambda: calls == [APP_VERSION]), str(calls))
        # ----- 2 -----
        check("查到新版：頁籤上方出現提示", wait_until(win.update_banner.isVisible)
              and win.update_banner.geometry().bottom() <= win.tabs.geometry().top() + 1)
        text = win.update_label.text()
        check("提示講新舊版本、下載哪個、不能自動更新", text == uc.notice_text(info, APP_VERSION)
              and "v99.0.0" in text and info["qt_zip"] in text and "還不能自動更新" in text)
        check("寫明會送出去的只有查版本的連線請求", win.update_banner.toolTip() == uc.SENDS)

        # ----- 3 -----
        opened = []
        win._open_url = lambda url: opened.append(url)
        QTest.mouseClick(win.update_open_btn, Qt.LeftButton)
        check("〔開啟下載頁〕開那一版的 Release 頁面", opened == [info["page"]])

        # ----- 4 -----
        QTest.mouseClick(win.update_skip_btn, Qt.LeftButton)
        check("〔這版不再提醒〕：收起來、記進設定（別的項目留著）", not win.update_banner.isVisible()
              and cfg["qt_update"] == {"其他": 1, "skipped_version": "v99.0.0"})
        check("同一版再查到：不提示", win.show_update(dict(info)) is False and not win.update_banner.isVisible())
        newer = dict(info, version="v99.1.0")
        check("更新的版本：照樣提示", win.show_update(newer) is True and win.update_banner.isVisible()
              and "v99.1.0" in win.update_label.text())

        # ----- 5 -----
        QTest.mouseClick(win.update_close_btn, Qt.LeftButton)
        check("〔關閉提示〕：只收起來、不記", not win.update_banner.isVisible()
              and cfg["qt_update"]["skipped_version"] == "v99.0.0")

        # ----- 6 -----
        check("沒有新版：不出現", win.show_update(None) is False and not win.update_banner.isVisible())
        uc.fetch_latest = lambda current, **kw: None
        win.start_update_check()
        wait(300)
        check("離線、查不到：不出現", not win.update_banner.isVisible())
        check("全程沒寫 config.json", not os.path.exists(config.CONFIG_PATH))
        win.close()
    finally:
        uc.fetch_latest = real_fetch

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 新版本提示測試全數通過。")
