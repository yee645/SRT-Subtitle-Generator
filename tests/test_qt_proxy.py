# -*- coding: utf-8 -*-
"""
3.0 第 6 項：播放器接上代理檔。

代理檔本身怎麼做在 test_proxy.py；這裡驗播放器什麼時候播哪一個，用 ffmpeg 真的做：

1. 1080p 第一次開：先播原檔、背景做代理檔、那一行寫進度；做好了換成代理檔，
   停在同一個位置、還是暫停；片長照原檔。
2. 同一支再開：直接播代理檔，不再做。
3. 播代理檔時「照剪點輸出」：剪的是原檔（輸出 1920x1080）。
4. 關掉「編輯用代理檔」：換回原檔、位置不變、記在這次的設定裡（不寫回 config.json）；
   再打開：快取有、立刻換過去。播放中切換也接著播。
5. 720p：不做代理檔、快取裡沒有檔案、那一行不寫代理檔。
6. 做到一半換片子：舊的結果丟掉（不會把別支的代理檔換上來）、不留下 .tmp。
7. 做不成（ffmpeg 失敗）：那一行說明、照樣用原檔。代理檔播不了：退回原檔。
8. config 的 qt_proxy 是 False：勾選框沒勾、不做代理檔。
9. 關視窗：還在做的代理檔停掉、不留 .tmp。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過播放器的代理檔（核心在 test_proxy.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
    from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import proxy  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = tmp
    cache = os.path.join(tmp, proxy.CACHE_DIR)

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait_until(cond, timeout_ms=60000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(50)
            waited += 50
        return cond()

    def make(name, size, seconds):
        path = os.path.join(tmp, name)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", str(seconds),
                        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", path],
                       check=True)
        return path

    def source(panel):
        return os.path.abspath(panel.player.source().toLocalFile())

    def tmp_files():
        return [n for n in (os.listdir(cache) if os.path.isdir(cache) else []) if n.endswith(".tmp")]

    big = make("big.mp4", "1920x1080", 8)
    big2 = make("big2.mp4", "1920x1080", 30)
    small = make("small.mp4", "1280x720", 4)
    # 設定檔指到暫存資料夾：量的是「這個視窗有沒有寫設定檔」，不受同時在跑的別的測試影響
    config.CONFIG_PATH = os.path.join(tmp, "config.json")
    with open(config.CONFIG_PATH, "w", encoding="utf-8") as fh:
        fh.write('{"theme": "dark"}')
    config_stat = os.stat(config.CONFIG_PATH)

    cfg = {"subtitle_style": {}}
    win = qt_app.MainWindow(cfg)
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 800)
    win.show()
    panel = win.player_panel
    check("預設勾著「編輯用代理檔」", panel.proxy_box.isChecked())

    # ----- 1. 第一次開 1080p -----
    notes = []
    panel.proxy_maker.progress.connect(lambda _g, _r: notes.append(panel.info_label.text()))
    panel.open_video(big)
    check("第一次開：先播原檔、那一行寫正在準備", source(panel) == big and panel.proxy_path == ""
          and "正在準備代理檔" in panel.info_label.text(), panel.info_label.text())
    wait_until(lambda: panel.player.duration() > 0 or panel.proxy_path, 10000)
    check("原檔載入好的時候代理檔還沒做好（下面才驗得到「換過去停在同一個位置」）",
          not panel.proxy_path)
    panel.player.setPosition(5200)
    wait_until(lambda: bool(panel.proxy_path))
    wait_until(lambda: panel.player.mediaStatus() == QMediaPlayer.MediaStatus.LoadedMedia
               and abs(panel.player.position() - 5200) < 150, 10000)
    wait(200)
    made = proxy.cache_path(big, cache)
    check("做好了 → 換成代理檔（快取資料夾裡、檔名＝快取鍵）",
          panel.proxy_path == made and source(panel) == made and os.path.getsize(made) > 0,
          f"{panel.proxy_path} {source(panel)}")
    check("做的時候那一行寫進度（先用原檔）",
          any("正在做代理檔" in n and "%" in n and "先用原檔" in n for n in notes), str(notes[-2:]))
    check("換過去停在同一個位置、還是暫停",
          abs(panel.player.position() - 5200) < 150
          and panel.player.playbackState() == QMediaPlayer.PlaybackState.PausedState,
          f"{panel.player.position()} {panel.player.playbackState()}")
    check("那一行寫「編輯用代理檔，輸出用原檔」", "big.mp4（編輯用代理檔，輸出用原檔）" in panel.info_label.text(),
          panel.info_label.text())
    orig = proxy.probe_video(big)["duration"]
    check("片長照原檔（剪點、時間軸都用這個）",
          panel.media_duration() == orig and abs(panel.timeline.duration - orig) < 1e-6,
          f"{panel.media_duration()} {panel.timeline.duration} {orig}")
    check("縮圖與波形用原檔（時間軸的背景工作收到的是原檔）", panel.media_path == big)

    # ----- 2. 再開一次：直接用快取 -----
    gen = panel.proxy_maker.generation
    panel.open_video(small)
    wait_until(lambda: panel.proxy_maker.generation > gen and panel.proxy_note == "", 20000)
    gen = panel.proxy_maker.generation
    panel.open_video(big)
    check("同一支再開：直接播代理檔、不再做一次", source(panel) == made and panel.proxy_path == made
          and panel.proxy_maker.generation == gen and "編輯用代理檔" in panel.info_label.text(),
          f"{source(panel)} {panel.proxy_maker.generation} {gen}")
    wait_until(lambda: panel.player.duration() > 0, 10000)
    wait(100)

    # ----- 3. 播代理檔時輸出：剪原檔 -----
    panel._show_export_error = lambda msg: failures.append(f"輸出錯誤：{msg}")
    panel.set_cues([{"start": 0.5, "end": 2.0, "text": "一"}, {"start": 5.0, "end": 7.0, "text": "二"}])
    panel.show_cut_marks("jumpcut")
    out = os.path.join(tmp, "cut.mp4")
    started = panel.export_cuts(out)
    wait_until(lambda: panel.last_export is not None, 60000)
    size = proxy.probe_video(out) if os.path.exists(out) else None
    check("播代理檔時照剪點輸出：剪的是原檔（輸出 1920x1080）",
          started and size is not None and (size["width"], size["height"]) == (1920, 1080), str(size))

    # ----- 4. 關掉／打開 -----
    panel.player.setPosition(3300)
    wait_until(lambda: abs(panel.player.position() - 3300) < 100, 5000)
    panel.proxy_box.setChecked(False)
    wait_until(lambda: panel.player.mediaStatus() == QMediaPlayer.MediaStatus.LoadedMedia
               and source(panel) == big and abs(panel.player.position() - 3300) < 150, 10000)
    check("關掉 → 換回原檔、位置不變、那一行不寫代理檔",
          source(panel) == big and panel.proxy_path == "" and abs(panel.player.position() - 3300) < 150
          and "代理檔" not in panel.info_label.text(), f"{source(panel)} {panel.player.position()}")
    check("記在這次的設定裡（qt_proxy=False），不寫回 config.json（Qt 預覽版不寫設定檔）",
          cfg.get("qt_proxy") is False and win.config_data.get("qt_proxy") is False
          and os.stat(config.CONFIG_PATH) == config_stat)
    gen = panel.proxy_maker.generation
    panel.proxy_box.setChecked(True)
    check("再打開：快取有、立刻換過去（不再做）", panel.proxy_path == made and source(panel) == made
          and panel.proxy_maker.generation == gen and cfg.get("qt_proxy") is True)
    wait_until(lambda: panel.player.mediaStatus() == QMediaPlayer.MediaStatus.LoadedMedia
               and abs(panel.player.position() - 3300) < 150, 10000)
    check("換過去位置一樣", abs(panel.player.position() - 3300) < 150, str(panel.player.position()))

    panel.player.play()
    wait_until(lambda: panel.player.position() > 3600, 5000)
    panel.proxy_box.setChecked(False)
    wait_until(lambda: source(panel) == big and panel.player.position() > 3700, 10000)
    playing_off = panel.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    at = panel.player.position()
    panel.proxy_box.setChecked(True)
    wait_until(lambda: panel.player.position() > at + 300, 10000)
    check("播放中切換：換回原檔、再換成代理檔都接著播（不跳回開頭）",
          playing_off and source(panel) == made and panel.player.position() > at
          and panel.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState,
          f"{playing_off} {at} {panel.player.position()}")
    panel.player.pause()

    # ----- 5. 720p -----
    before = sorted(os.listdir(cache))
    panel.open_video(small)
    wait_until(lambda: panel.proxy_note == "", 20000)
    wait(100)
    check("720p：不做代理檔、快取沒多檔案、播原檔、那一行不寫代理檔",
          source(panel) == small and panel.proxy_path == "" and sorted(os.listdir(cache)) == before
          and "代理檔" not in panel.info_label.text(), f"{os.listdir(cache)} {panel.info_label.text()}")

    # ----- 6. 做到一半換片子 -----
    panel.open_video(big2)
    wait_until(lambda: "正在做代理檔" in panel.info_label.text(), 20000)
    panel.open_video(small)
    wait_until(lambda: panel.proxy_note == "", 20000)
    wait(3000)
    check("做到一半換片子：舊的不會換上來、沒留下 .tmp、也沒進快取",
          source(panel) == small and panel.proxy_path == "" and not tmp_files()
          and proxy.cached_proxy(big2, cache) is None, f"{source(panel)} {tmp_files()}")

    # ----- 7. 做不成、播不了 -----
    real_load = proxy.load_proxy
    proxy.load_proxy = lambda *a, **k: (_ for _ in ()).throw(proxy.ProxyError("ffmpeg 轉檔失敗：測試"))
    try:
        panel.open_video(big2)
        wait_until(lambda: "沒做成" in panel.info_label.text(), 10000)
        check("做不成 → 那一行說明、照樣播原檔",
              "代理檔沒做成（ffmpeg 轉檔失敗：測試），用原檔編輯" in panel.info_label.text()
              and source(panel) == big2 and panel.proxy_path == "", panel.info_label.text())
    finally:
        proxy.load_proxy = real_load
    bad = proxy.cache_path(big2, cache)
    with open(bad, "wb") as fh:
        fh.write(b"\x00" * 2048)
    panel.open_video(big2)
    check("快取裡有（壞掉的）代理檔 → 先拿它來播", source(panel) == bad)
    wait_until(lambda: "播不了" in panel.info_label.text() and source(panel) == big2, 15000)
    check("代理檔播不了 → 退回原檔、那一行說明", source(panel) == big2 and panel.proxy_path == ""
          and "代理檔播不了" in panel.info_label.text() and "改用原檔" in panel.info_label.text(),
          f"{source(panel)} {panel.info_label.text()}")
    os.unlink(bad)

    # ----- 9. 關視窗停掉還在做的 -----
    panel.open_video(big2)
    wait_until(lambda: "正在做代理檔" in panel.info_label.text(), 20000)
    thread = panel.proxy_maker._thread
    win.close()
    check("關視窗：還在做的代理檔停掉、不留 .tmp、沒進快取",
          thread is not None and not thread.is_alive() and not tmp_files()
          and proxy.cached_proxy(big2, cache) is None, str(tmp_files()))

    # ----- 8. config 關著 -----
    win2 = qt_app.MainWindow({"subtitle_style": {}, "qt_proxy": False})
    panel2 = win2.player_panel
    gen = panel2.proxy_maker.generation
    panel2.open_video(big)
    check("config 的 qt_proxy 是 False：沒勾、播原檔、不做代理檔",
          not panel2.proxy_box.isChecked() and source(panel2) == big and panel2.proxy_path == ""
          and panel2.proxy_maker.generation == gen)
    win2.close()

    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 播放器代理檔測試全數通過。")
