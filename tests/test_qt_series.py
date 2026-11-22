# -*- coding: utf-8 -*-
"""
3.0 第 11 項第二十七階段：系列一致性比對視窗（gui_qt/series_dialog.py）。

比對規則在核心的測試；這裡驗介面與接線，ffmpeg 真的量。測試影片用 ffmpeg 產生（各 2 秒、有聲音）：
第一、二集一樣（灰色畫面、音量 0.5、320x240）；第三集偏暗、小聲、解析度不同。

1. ③健檢頁有〔系列一致性比對…〕與說明（另開視窗的理由）；按下去開視窗（不擋住主視窗、只建一個）。
2. 容許差異的初值照目前的設定（seriescheck）、範圍與一格跟一般版一樣。
3. 清單：加入（選檔、同一支不重複、顯示檔名、提示完整路徑）、加入②開著的影片（沒開時灰掉並講原因、已在
   清單上講一聲）、移除選取、全部清除；按鈕灰不灰跟著清單。
4. 不比對的情況講原因：不到 2 支、沒有 ffmpeg（出現提示列）。
5. 比對：背景跑、跑的時候控制項灰掉；報告＝直接呼叫 analyze_series＋format_series_report（同樣的檔案與設定）；
   第三集被標出來；狀態列講幾項不一致；整批一致時講一致。
6. 容許差異寫進這次開啟的 seriescheck，交給背景的是副本。
7. 複製報告、另存報告（補副檔名、取消、寫不進去講原因）。
8. 背景失敗講原因，上一份報告留著。
9. 比對中關掉視窗不會中斷：再打開是同一個視窗、清單還在、報告已經出來。全程不寫 config.json、影片不動。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過系列一致性視窗")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtGui import QGuiApplication  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import series_dialog as sd  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import seriescheck as sc  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")
    work = os.path.join(tmp, "系列 第一季")
    os.makedirs(work)

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait_until(cond, timeout_ms=180000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(50)
            waited += 50
        return cond()

    def make(name, gray, volume, size):
        path = os.path.join(work, name)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={gray}:s={size}:r=25:d=2",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=2:sample_rate=22050",
                        "-af", f"volume={volume}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-shortest", path], check=True)
        return path

    ep1 = make("第一集.mp4", "0x808080", 0.5, "320x240")
    ep2 = make("第二集.mp4", "0x808080", 0.5, "320x240")
    ep3 = make("第三集.mp4", "0x202020", 0.03, "640x360")
    originals = {p: (os.path.getsize(p), os.path.getmtime(p)) for p in (ep1, ep2, ep3)}

    cfg = {"seriescheck": {"loudness_tolerance": 3.0, "luma_tolerance": 30.0, "cast_tolerance": 10.0},
           "自訂": "留著"}
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 900)
    win.show()
    wait(50)
    player = win.player_panel
    player._ask_discard = lambda *a, **k: "discard"
    player._ask_project_discard = lambda *a, **k: "discard"
    win.tabs.setCurrentIndex(2)
    wait(50)
    health = win.health_panel

    # ----- 1. 入口與視窗 -----
    check("③健檢頁有〔系列一致性比對…〕", health is not None and health.isAncestorOf(health.series_btn)
          and health.series_btn.text() == "系列一致性比對…" and health.series_btn.isVisible())
    labels = " ".join(w.text() for w in health.findChildren(type(health.status_label)))
    check("說明另開視窗的理由（比的是多支影片彼此之間）", "系列一致性比的是「多支影片彼此之間」" in labels
          and "所以另開一個視窗、不併進下面的報告" in labels)
    check("狀態列提到③含系列一致性", "③健檢中心（含系列一致性）、" in win.statusBar().currentMessage())
    check("按之前還沒有視窗", health.series_dialog is None)
    QTest.mouseClick(health.series_btn, Qt.LeftButton)
    wait(50)
    dlg = health.series_dialog
    check("按下去開視窗：標題、不擋住主視窗", dlg is not None and dlg.isVisible() and not dlg.isModal()
          and dlg.windowTitle() == "系列一致性：比對同一批影片彼此之間是否一致")
    check("有 ffmpeg：不出現提示列", not dlg.ffmpeg_label.isVisibleTo(dlg))
    check("一開始的說明", dlg.status_label.text() == sd.HINT)
    QTest.mouseClick(health.series_btn, Qt.LeftButton)
    check("再按一次：同一個視窗", health.series_dialog is dlg)

    # ----- 2. 容許差異 -----
    spins = dlg.spins
    check("容許差異初值照目前的設定", (spins["loudness_tolerance"].value(), spins["luma_tolerance"].value(),
                                     spins["cast_tolerance"].value()) == (3.0, 30.0, 10.0))
    check("範圍、一格、小數位跟一般版一樣",
          [(s.minimum(), s.maximum(), s.singleStep(), s.decimals()) for s in spins.values()]
          == [(0.5, 8.0, 0.5, 1), (10.0, 80.0, 5.0, 0), (3.0, 30.0, 1.0, 0)])
    real_ffmpeg = sd.ffmpeg_available
    sd.ffmpeg_available = lambda: False
    try:
        other = sd.SeriesDialog(player)
        check("沒有 ffmpeg：一開就有提示列（講去一般版裝）", other.ffmpeg_label.isVisibleTo(other)
              and "自動安裝 ffmpeg" in other.ffmpeg_label.text())
        other.deleteLater()
    finally:
        sd.ffmpeg_available = real_ffmpeg
    cfg_empty = {}
    player._config, saved_cfg = cfg_empty, player._config
    try:
        fresh = sd.SeriesDialog(player)
        check("沒有設定：用預設值", [s.value() for s in fresh.spins.values()]
              == [sc.DEFAULT_SERIESCHECK[k] for k in fresh.spins])
        fresh.deleteLater()
    finally:
        player._config = saved_cfg

    # ----- 3. 清單 -----
    check("清單空著：移除、清除、複製、另存都灰掉；②沒開影片：加入②的也灰掉",
          not dlg.remove_btn.isEnabled() and not dlg.clear_btn.isEnabled() and not dlg.copy_btn.isEnabled()
          and not dlg.save_btn.isEnabled() and not dlg.add_current_btn.isEnabled() and dlg.add_btn.isEnabled())
    check("②沒開影片時按加入②的：講原因、不加", dlg.add_current() == 0 and dlg.status_label.text() == sd.NO_PLAYER_MEDIA
          and dlg.paths() == [])
    dlg._ask_media_paths = lambda: [ep1, ep2]
    QTest.mouseClick(dlg.add_btn, Qt.LeftButton)
    check("加入影片：照選的順序", dlg.paths() == [ep1, ep2])
    check("清單顯示檔名、提示是完整路徑", [dlg.file_list.item(i).text() for i in range(2)] == ["第一集.mp4", "第二集.mp4"]
          and dlg.file_list.item(0).toolTip() == ep1)
    dlg._ask_media_paths = lambda: [ep2, ep3, ""]
    check("同一支不重複加、空的不加", dlg.add_files() == 1 and dlg.paths() == [ep1, ep2, ep3])
    dlg._ask_media_paths = lambda: []
    check("選檔取消：不變", dlg.add_files() == 0 and dlg.paths() == [ep1, ep2, ep3])
    check("有清單：清除可以按；沒選：移除灰掉", dlg.clear_btn.isEnabled() and not dlg.remove_btn.isEnabled())
    dlg.file_list.item(1).setSelected(True)
    check("選了：移除可以按", dlg.remove_btn.isEnabled())
    QTest.mouseClick(dlg.remove_btn, Qt.LeftButton)
    check("移除選取的那一支", dlg.paths() == [ep1, ep3])
    QTest.mouseClick(dlg.clear_btn, Qt.LeftButton)
    check("全部清除", dlg.paths() == [] and not dlg.clear_btn.isEnabled())
    player.open_video(ep2)
    wait_until(lambda: player.media_path == ep2, 10000)
    dlg.hide()
    health.open_series()
    check("②開了影片：再打開時加入②的可以按", dlg.add_current_btn.isEnabled())
    QTest.mouseClick(dlg.add_current_btn, Qt.LeftButton)
    check("加入②開著的影片", dlg.paths() == [ep2] and dlg.status_label.text() == "已加入：第二集.mp4")
    check("已經在清單上：講一聲、不重複加", dlg.add_current() == 0 and dlg.paths() == [ep2]
          and dlg.status_label.text() == "第二集.mp4 已經在清單上了。")

    # ----- 4. 不比對的情況 -----
    started = []
    real_start = dlg.worker.start
    dlg.worker.start = lambda *a: started.append(a)
    check("只有 1 支：不比對、講要至少 2 支並指向健檢", dlg.start() is False and dlg.status_label.text() == sd.NEED_TWO
          and "至少 2 支" in sd.NEED_TWO and "③健檢中心" in sd.NEED_TWO)
    dlg.add_paths([ep1])
    sd.ffmpeg_available = lambda: False
    try:
        check("沒有 ffmpeg：不比對、出現提示列", dlg.start() is False and dlg.status_label.text() == sd.NO_FFMPEG
              and dlg.ffmpeg_label.isVisibleTo(dlg))
    finally:
        sd.ffmpeg_available = real_ffmpeg
    check("以上都沒有交給背景", started == [])
    dlg.worker.start = real_start
    dlg.ffmpeg_label.setVisible(False)

    # ----- 5. 比對（整批一致） -----
    expected_two = sc.format_series_report(sc.analyze_series([ep2, ep1], dict(cfg)))
    QTest.mouseClick(dlg.run_btn, Qt.LeftButton)
    check("跑的時候：控制項灰掉、按鈕寫「比對中…」、進度條出現", dlg.busy() and not dlg.run_btn.isEnabled()
          and dlg.run_btn.text() == "比對中…" and not dlg.add_btn.isEnabled() and not dlg.clear_btn.isEnabled()
          and not any(s.isEnabled() for s in spins.values()) and dlg.progress_bar.isVisibleTo(dlg))
    check("跑的時候再按：不重跑", dlg.start() is False)
    dlg.worker.progress.emit(0.5, "正在量測（1/2）第二集.mp4...")
    check("進度：狀態列寫核心的訊息、進度條跟著走", dlg.status_label.text() == "正在量測（1/2）第二集.mp4..."
          and dlg.progress_bar.value() == 500)
    check("比完", wait_until(lambda: not dlg.busy()))
    check("整批一致：報告＝直接呼叫核心", dlg.report.toPlainText() == expected_two, dlg.report.toPlainText())
    check("整批一致：狀態列講一致", dlg.status_label.text() == "比對完成：整批各項指標彼此一致。")
    check("比完：控制項回來、進度條收起、可以複製另存", dlg.run_btn.isEnabled() and dlg.run_btn.text() == "開始比對"
          and dlg.copy_btn.isEnabled() and dlg.save_btn.isEnabled() and not dlg.progress_bar.isVisibleTo(dlg))

    # ----- 5b. 第三集不一樣 -----
    dlg.add_paths([ep3])
    spins["loudness_tolerance"].setValue(2.5)
    spins["luma_tolerance"].setValue(25.0)
    seen = []
    real_analyze = sc.analyze_series

    def spy(paths, config, progress_cb=None):
        seen.append((list(paths), config))
        config["被背景改掉"] = True  # 背景拿到的是副本：改它不會動到這次開啟的設定
        return real_analyze(paths, config, progress_cb=progress_cb)
    sc.analyze_series = spy
    try:
        messages = []
        dlg.worker.progress.connect(lambda r, m: messages.append(m))
        check("開始比對", dlg.start() is True)
        check("比完（三支）", wait_until(lambda: not dlg.busy()))
    finally:
        sc.analyze_series = real_analyze
    check("容許差異寫進這次開啟的 seriescheck（別的項目留著）", cfg["seriescheck"] == {
        "loudness_tolerance": 2.5, "luma_tolerance": 25.0, "cast_tolerance": 10.0} and cfg["自訂"] == "留著")
    check("交給背景的是副本、檔案照清單順序", seen and seen[0][0] == [ep2, ep1, ep3] and seen[0][1] is not cfg
          and "被背景改掉" not in cfg)
    check("進度訊息照核心（每一支都講）", any("第三集.mp4" in m for m in messages) and
          any("（1/3）" in m for m in messages))
    result = real_analyze([ep2, ep1, ep3], dict(cfg))
    check("報告＝直接呼叫核心（同樣的檔案與設定）", dlg.report.toPlainText() == sc.format_series_report(result))
    bad = [f["title"] for f in result["findings"] if f["level"] != sc.LEVEL_GOOD]
    check("第三集被標出來：響度、解析度、亮度", "整體響度" in bad and "畫面亮度" in bad
          and any("解析度" in t for t in bad) and "第三集.mp4" in dlg.report.toPlainText(), str(bad))
    check("狀態列講幾項不一致", dlg.status_label.text() == f"比對完成：{len(bad)} 項在整批之間不一致，詳見報告。"
          and sd.issue_count(result) == len(bad))

    # ----- 7. 複製、另存 -----
    QGuiApplication.clipboard().clear()
    QTest.mouseClick(dlg.copy_btn, Qt.LeftButton)
    check("複製報告", QGuiApplication.clipboard().text() == dlg.report.toPlainText()
          and dlg.status_label.text() == "報告已複製到剪貼簿。")
    asked = []
    dlg._ask_save_path = lambda: (asked.append(1), os.path.join(work, "比對結果"))[1]
    saved = dlg.save_report()
    check("另存：沒寫副檔名補 .txt、內容是報告（UTF-8）", saved == os.path.join(work, "比對結果.txt")
          and open(saved, encoding="utf-8").read() == dlg.report.toPlainText()
          and dlg.status_label.text() == "報告已儲存：比對結果.txt")
    dlg._ask_save_path = lambda: ""
    check("另存取消：不存", dlg.save_report() == "" and dlg.status_label.text() == "報告已儲存：比對結果.txt")
    dlg._ask_save_path = lambda: os.path.join(work, "沒有這個資料夾", "報告.txt")
    check("寫不進去：講原因", dlg.save_report() == "" and dlg.status_label.text().startswith("儲存報告失敗："))
    check("另存預設檔名跟一般版一樣", sd.SAVE_NAME == "系列一致性檢查.txt")

    # ----- 8. 背景失敗 -----
    before = dlg.report.toPlainText()

    def boom(paths, config, progress_cb=None):
        raise RuntimeError("量測時壞掉了")
    sc.analyze_series = boom
    try:
        dlg.start()
        check("失敗也會收尾", wait_until(lambda: not dlg.busy(), 10000))
    finally:
        sc.analyze_series = real_analyze
    check("背景失敗：講原因、控制項回來", dlg.status_label.text().startswith("比對失敗：")
          and "量測時壞掉了" in dlg.status_label.text() and dlg.run_btn.isEnabled())
    check("上一份報告留著、還能複製", dlg.report.toPlainText() == before and dlg.copy_btn.isEnabled())

    # ----- 9. 比對中關掉視窗 -----
    gate = []

    def slow(paths, config, progress_cb=None):
        while not gate:
            import time
            time.sleep(0.02)
        return real_analyze(paths, config, progress_cb=progress_cb)
    sc.analyze_series = slow
    try:
        dlg.clear_files()
        dlg.add_paths([ep1, ep2])
        dlg.start()
        dlg.close()
        check("比對中關掉：視窗收起來、背景還在跑", not dlg.isVisible() and dlg.busy())
        gate.append(1)
        check("關著也會比完", wait_until(lambda: not dlg.busy()))
    finally:
        sc.analyze_series = real_analyze
    QTest.mouseClick(health.series_btn, Qt.LeftButton)
    expected_12 = sc.format_series_report(real_analyze([ep1, ep2], dict(cfg)))
    check("再打開：同一個視窗、清單還在、報告已經出來", health.series_dialog is dlg and dlg.isVisible()
          and dlg.paths() == [ep1, ep2] and dlg.report.toPlainText() == expected_12
          and dlg.status_label.text() == "比對完成：整批各項指標彼此一致。")

    check("全程沒寫 config.json", not os.path.exists(config.CONFIG_PATH))
    check("影片到最後都沒動", all((os.path.getsize(p), os.path.getmtime(p)) == v for p, v in originals.items()))

    dlg.close()
    player.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 系列一致性視窗測試全數通過。")
