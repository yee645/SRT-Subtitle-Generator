# -*- coding: utf-8 -*-
"""
3.0 第 12 項 12-3：Qt 版提示列的〔下載並安裝〕（gui_qt/app.py＋gui_qt/update_notice.py 的 InstallWorker）。

核心在 test_onedirupdate.py；這裡 QTest 真的點，下載換成假的連線（不連網），zip 用發版時同一支打包程式做：

1. 從原始碼跑（不是打包好的 Windows 資料夾版）：照舊只有手動下載的說明，沒有〔下載並安裝〕。
2. 打包好的資料夾版、新版有附 zip：說明講會自動換上、多一顆〔下載並安裝〕；滑鼠停上去寫明只下載、不送東西出去。
3. 按下去：背景下載、提示列跟著講百分比；下載中〔取消下載〕可以按，其他按鈕灰掉。
4. 下載完：新版解在程式資料夾旁邊、設定與 tools 帶過去、下載的 zip 刪掉；切換腳本寫好（不放在要被改名的資料夾裡）；
   提示列講準備好、多一顆〔現在重新開啟〕。
5. 關掉程式（〔現在重新開啟〕）：程式真的關掉之後才跑切換腳本；關不掉（取消）就不跑。
6. 下載壞掉：講原因、〔下載並安裝〕回來可以再試；不會有切換腳本。
7. 取消：講已取消、不留檔。
8. 還在下載時關程式：先問；說不要就不關、照樣下載；說要就取消。
9. 新版啟動：刪掉上一次換下來的舊資料夾（`.old`）。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "packaging"))

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
    print("SKIP 這個環境沒有 PySide6：略過資料夾版自動更新介面")
else:
    import tempfile
    import time

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    import qt_preview  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import onedirupdate as odu  # noqa: E402
    from subtitle import updatecheck as uc  # noqa: E402
    from updater import APP_VERSION  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait_until(cond, timeout_ms=8000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(20)
            waited += 20
        return cond()

    # 「已經裝好的」程式資料夾：exe、設定、一鍵安裝的 ffmpeg
    app_dir = os.path.join(tmp, "我的程式", "SRT-Subtitle-Generator-Qt")
    os.makedirs(os.path.join(app_dir, "tools", "ffmpeg", "bin"))
    open(os.path.join(app_dir, odu.EXE_NAME), "wb").write(b"MZ old")
    open(os.path.join(app_dir, "tools", "ffmpeg", "bin", "ffmpeg.exe"), "wb").write(b"ff")
    config.CONFIG_PATH = os.path.join(app_dir, "config.json")
    open(config.CONFIG_PATH, "w", encoding="utf-8").write('{"theme": "dark"}')

    # 新版的 zip：發版時同一支打包程式打的
    dist = os.path.join(tmp, "build", "SRT-Subtitle-Generator-Qt")
    os.makedirs(os.path.join(dist, "_internal"))
    open(os.path.join(dist, odu.EXE_NAME), "wb").write(b"MZ new")
    open(os.path.join(dist, "_internal", "big.bin"), "wb").write(os.urandom(600 * 1024))
    zip_file = os.path.join(tmp, "new.zip")
    qt_preview.make_zip(dist, zip_file)
    payload = open(zip_file, "rb").read()

    url = f"{odu.DOWNLOAD_PREFIX}v99.0.0/SRT-Subtitle-Generator-Qt-v99.0.0-win64.zip"
    asset = {"name": "SRT-Subtitle-Generator-Qt-v99.0.0-win64.zip", "url": url, "size": len(payload)}
    info = {"version": "v99.0.0", "page": "https://github.com/yee645/SRT-Subtitle-Generator/releases/tag/v99.0.0",
            "notes": "", "qt_zip": asset["name"], "qt_asset": asset}

    class Slow(io.BytesIO):
        """每次讀一塊都停一下：看得到進度、來得及按取消。"""
        delay = 0.0

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()

        def read(self, n=-1):
            time.sleep(self.delay)
            return super().read(n)

    served = {"data": payload, "delay": 0.0}
    real_download = odu.download

    def fake_download(asset_, dest_dir, progress=None, cancelled=None, opener=None, timeout=60):
        def opener_(request, timeout=0):
            s = Slow(served["data"])
            s.delay = served["delay"]
            return s
        return real_download(asset_, dest_dir, progress=progress, cancelled=cancelled, opener=opener_)

    odu.download = fake_download
    try:
        cfg = {}
        win = qt_app.MainWindow(cfg)
        p = win.player_panel
        p._ask_discard = lambda *a, **k: "discard"
        p._ask_project_discard = lambda *a, **k: "discard"
        spawned = []
        win._spawn_switch = lambda script: spawned.append(script)
        win.resize(1280, 800)
        win.show()
        wait(100)

        # ----- 1 -----
        win._self_update_dir = lambda: None
        win.show_update(dict(info))
        check("從原始碼跑：只有手動下載的說明、沒有〔下載並安裝〕", win.update_banner.isVisible()
              and not win.update_install_btn.isVisible() and "還不能自動更新" in win.update_label.text())
        check("不能自己更新時硬按：不開始", win.install_update() is False and not win.updating())

        # ----- 2 -----
        win._self_update_dir = lambda: app_dir
        win.show_update(dict(info))
        check("資料夾版、有 zip：講會自動換上、有〔下載並安裝〕", win.update_install_btn.isVisible()
              and win.update_label.text() == uc.auto_notice_text(info, APP_VERSION)
              and "還不能自動更新" not in win.update_label.text())
        check("滑鼠停上去：寫明只下載、不送東西出去", "不送任何檔案、字幕、設定或帳號資訊出去" in win.update_install_btn.toolTip())
        check("〔取消下載〕〔現在重新開啟〕平常收著", not win.update_cancel_btn.isVisible()
              and not win.update_restart_btn.isVisible())

        # ----- 3 -----
        served["delay"] = 0.05
        labels = []
        win.install_worker.progress.connect(lambda d, t: labels.append(win.update_label.text()))
        preparing = []  # 接在主視窗自己的處理之後：看得到處理完的樣子
        win.install_worker.preparing.connect(lambda: preparing.append((win.update_label.text(),
                                                                       win.update_cancel_btn.isEnabled())))
        QTest.mouseClick(win.update_install_btn, Qt.LeftButton)
        check("按下去：背景開始下載、〔取消下載〕可以按、其他灰掉", win.updating() and win.update_cancel_btn.isVisible()
              and win.update_cancel_btn.isEnabled() and not win.update_install_btn.isVisible()
              and not win.update_open_btn.isEnabled() and not win.update_skip_btn.isEnabled())
        wait_until(lambda: len(labels) >= 2)
        check("下載中：提示列跟著講百分比（不是停在 0%）", any(re.match(r"正在下載新版 [1-9]\d*%", t) for t in labels),
              str(labels[:3]))
        check("再按一次不會開第二個下載", win.install_update() is False)
        check("下載完", wait_until(lambda: not win.updating()))
        wait(100)
        check("解壓時：講正在解壓、〔取消下載〕灰掉（解壓、複製不能停一半）", preparing == [(uc.PREPARING_TEXT, False)],
              str(preparing))

        # ----- 4 -----
        new_dir = odu.staging_path(app_dir, "v99.0.0")
        check("新版解在程式資料夾旁邊", open(os.path.join(new_dir, odu.EXE_NAME), "rb").read() == b"MZ new")
        check("設定與 tools 帶過去", open(os.path.join(new_dir, "config.json"), encoding="utf-8").read() == '{"theme": "dark"}'
              and os.path.isfile(os.path.join(new_dir, "tools", "ffmpeg", "bin", "ffmpeg.exe")))
        check("下載的 zip 刪掉", not os.path.exists(os.path.join(os.path.dirname(app_dir), asset["name"]))
              and not [n for n in os.listdir(os.path.dirname(app_dir)) if n.endswith((".zip", ".part"))])
        script = win.pending_switch
        check("切換腳本寫好、不在要被改名的資料夾裡", script and os.path.isfile(script)
              and not script.startswith(app_dir) and not script.startswith(new_dir))
        text = open(script, encoding="utf-8-sig").read() if script else ""
        check("腳本換的是這個程式資料夾、等的是這個程式", f"$app = '{app_dir}'" in text and f"$new = '{new_dir}'" in text
              and f"Wait-Process -Id {os.getpid()} " in text and f"$cwd = '{app_dir}'" in text)
        check("提示列講準備好、多〔現在重新開啟〕", win.update_label.text() == uc.READY_TEXT
              and win.update_restart_btn.isVisible() and not win.update_cancel_btn.isVisible()
              and not win.update_skip_btn.isVisible() and win.update_close_btn.isEnabled())
        check("還沒關：還沒跑切換", spawned == [])
        win.show_update(dict(info))
        check("準備好之後又查到同一版：不再出現〔下載並安裝〕", not win.update_install_btn.isVisible())

        # ----- 5 -----
        real_maybe = p.maybe_close
        p.maybe_close = lambda: False  # 有沒存的東西，使用者按了取消
        win.close()
        wait(50)
        check("關不掉（取消）：不跑切換、腳本留著", win.isVisible() and spawned == [] and win.pending_switch == script)
        p.maybe_close = real_maybe
        QTest.mouseClick(win.update_restart_btn, Qt.LeftButton)
        wait(50)
        check("〔現在重新開啟〕：程式關掉後跑切換腳本（只跑一次）", not win.isVisible() and spawned == [script]
              and win.pending_switch is None)

        # ----- 6 -----
        cfg2 = {}
        win2 = qt_app.MainWindow(cfg2)
        p2 = win2.player_panel
        p2._ask_discard = lambda *a, **k: "discard"
        p2._ask_project_discard = lambda *a, **k: "discard"
        spawned2 = []
        win2._spawn_switch = lambda script: spawned2.append(script)
        win2._self_update_dir = lambda: app_dir
        win2.show()
        served.update(data=b"PK\x03\x04" + b"0" * (len(payload) - 4), delay=0.0)  # 大小對、內容壞掉
        win2.show_update(dict(info))
        win2.install_update()
        wait_until(lambda: not win2.updating())
        wait(100)
        check("下載壞掉：講原因、〔下載並安裝〕回來可以再試、沒有切換腳本",
              "不是完整的 zip" in win2.update_label.text() and "再按一次" in win2.update_label.text()
              and win2.update_install_btn.isVisible() and win2.pending_switch is None
              and win2.update_open_btn.isEnabled(), win2.update_label.text())

        # ----- 7 -----
        served.update(data=payload, delay=0.05)
        win2.install_update()
        wait_until(lambda: "正在下載新版" in win2.update_label.text() and "%" in win2.update_label.text())
        QTest.mouseClick(win2.update_cancel_btn, Qt.LeftButton)
        wait_until(lambda: not win2.updating())
        wait(100)
        check("取消：講已取消、不留檔、可以再按", odu.CANCELLED in win2.update_label.text()
              and win2.update_install_btn.isVisible() and win2.pending_switch is None
              and not [n for n in os.listdir(os.path.dirname(app_dir)) if n.endswith((".zip", ".part"))])

        # ----- 8 -----
        served.update(delay=0.05)
        win2.install_update()
        asked = []
        win2._ask_close_while_updating = lambda: (asked.append(1), False)[1]
        win2.close()
        wait(50)
        check("還在下載時關：先問；說不要就不關、照樣下載", asked == [1] and win2.isVisible() and win2.updating())
        win2._ask_close_while_updating = lambda: (asked.append(2), True)[1]
        win2.close()
        wait_until(lambda: not win2.install_worker.busy)
        wait(100)
        check("說要：關掉、下載取消、不跑切換", asked == [1, 2] and not win2.isVisible() and spawned2 == []
              and win2.pending_switch is None)

        # ----- 9 -----
        old = odu.backup_path(app_dir)
        os.makedirs(old)
        open(os.path.join(old, odu.EXE_NAME), "wb").write(b"MZ older")
        real_dir = odu.self_update_dir
        odu.self_update_dir = lambda frozen, exe, plat: None
        here = os.path.join(tmp, "工作目錄")
        os.makedirs(here)
        os.makedirs(here + ".old")
        cwd = os.getcwd()
        os.chdir(here)
        try:
            qt_app._cleanup_previous_update()
        finally:
            os.chdir(cwd)
        check("從原始碼跑：不刪任何東西（工作目錄旁邊同名的 .old 也不碰）", os.path.isdir(old) and os.path.isdir(here + ".old"))
        odu.self_update_dir = lambda frozen, exe, plat: app_dir
        qt_app._cleanup_previous_update()
        odu.self_update_dir = real_dir
        check("新版啟動：刪掉上一次換下來的舊資料夾", not os.path.exists(old) and os.path.isdir(app_dir))
        main_src = open(qt_app.__file__, encoding="utf-8").read()
        check("main() 一開始就清（在讀設定之前）", main_src.index("    _cleanup_previous_update()\n")
              < main_src.index("    data = config.load_config()"))
    finally:
        odu.download = real_download

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("資料夾版自動更新介面測試全數通過。")
