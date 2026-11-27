# -*- coding: utf-8 -*-
"""
剪輯器版面 E-8a：素材庫的清單跟著專案存（gui_qt/media_bin.py ↔ PlayerPanel.bin_paths ↔ subtitle/project.py）。

格式的規則在 test_project_bin.py；這裡驗介面：

1. 匯入、移除都寫回播放器（存專案時一起記）；略過的不記。
2. 存專案 → 另開一個剪輯器視窗開同一個專案：素材庫照存的順序排回來、縮圖與長度重新抽；開專案前已經在素材庫的換掉。
3. 開過或存過專案之後，素材庫增減算專案的變更（頂列加「•」、關掉前會問）；拿回原樣就不算。
   還沒有專案時，只動素材庫不算（跟只改字幕時間一樣，不為了它問）。
4. 素材庫的檔案找不到：專案照樣打開，訊息列出「素材庫第 n 個」並說只是不放進素材庫；找得到的照樣放。
5. 四頁籤（沒有素材庫）開同一個專案再存：素材庫的清單不會被弄丟。
"""
import copy
import json
import os
import shutil
import subprocess
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過素材庫存進專案（格式在 test_project_bin.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    import gui_qt.app as qt_app  # noqa: E402
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

    def wait_until(cond, timeout_ms=20000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(50)
            waited += 50
        return cond()

    def run(*args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)

    work = os.path.join(tmp, "專案")
    os.makedirs(os.path.join(work, "素材"))
    main = os.path.join(work, "主片.mp4")
    broll = os.path.join(work, "素材", "空拍.mp4")
    still = os.path.join(work, "素材", "標誌.png")
    song = os.path.join(work, "素材", "配樂.m4a")
    notes = os.path.join(work, "筆記.txt")
    run("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-f", "lavfi", "-i", "sine=frequency=440",
        "-t", "6", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", main)
    run("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-t", "3", "-pix_fmt", "yuv420p", "-c:v", "libx264",
        broll)
    run("-f", "lavfi", "-i", "testsrc2=size=160x90", "-frames:v", "1", still)
    run("-f", "lavfi", "-i", "sine=frequency=220", "-t", "4", "-c:a", "aac", song)
    open(notes, "w").close()
    target = os.path.join(work, "片子.srtproj")

    windows = []

    def new_editor():
        cfg = copy.deepcopy(config.DEFAULT_CONFIG)
        ed.apply_initial_theme(app, "dark")
        win = ed.EditorWindow(cfg)
        win.resize(1440, 900)
        win.show()
        p = win.player_panel
        p.messages = []
        p._show_project_message = lambda title, text: p.messages.append((title, text))
        p._ask_discard = lambda *a, **k: "discard"
        p._ask_project_discard = lambda *a, **k: "discard"
        windows.append(win)
        wait(50)
        return win, p

    def names(win):
        b = win.media_bin
        return [os.path.basename(b.list.item(i).data(Qt.UserRole)) for i in range(b.list.count())]

    def select(win, *files):
        b = win.media_bin
        b.list.clearSelection()
        for i in range(b.list.count()):
            if b.list.item(i).data(Qt.UserRole) in files:
                b.list.item(i).setSelected(True)

    # ----- 1 -----
    win, p = new_editor()
    bin_ = win.media_bin
    check("一開始播放器記的素材庫是空的", p.bin_paths == [] and p.project_state()["bin"] == [])
    bin_.add_files([song, broll, notes, still, broll])
    check("匯入：寫回播放器（略過的不記、照匯入的順序）", p.bin_paths == [song, broll, still], str(p.bin_paths))
    check("存專案的內容帶著素材庫", p.project_state()["bin"] == [song, broll, still])
    select(win, broll)
    bin_.remove_selected()
    check("移除：寫回播放器", p.bin_paths == [song, still], str(p.bin_paths))
    bin_.add_files([broll])
    check("再加回來：排在最後", p.bin_paths == [song, still, broll])

    # ----- 3（還沒有專案） -----
    p.open_video(main)
    wait_until(lambda: p.player.duration() > 0)
    check("還沒有專案：只動素材庫不算專案的變更", not p.project_changed())

    # ----- 2 -----
    p._ask_project_path = lambda suggested: target
    check("存專案", p.save_project() and os.path.isfile(target))
    with open(target, encoding="utf-8") as fh:
        doc = json.load(fh)
    check("檔案裡記著素材庫（相對位置）", [e["path"] for e in doc["bin"]] == ["素材/配樂.m4a", "素材/標誌.png", "素材/空拍.mp4"],
          str(doc.get("bin")))

    # ----- 3（有專案之後） -----
    check("剛存好：沒有變更", not p.project_changed() and "•" not in win.refresh_project_name())
    select(win, still)
    bin_.remove_selected()
    check("存過專案之後移除一個：算變更、頂列加「•」", p.project_changed() and "•" in win.refresh_project_name())
    bin_.add_files([still])
    check("加回來但順序不一樣：還是算變更（順序也記在專案裡）", p.project_changed())
    select(win, broll)
    bin_.remove_selected()
    bin_.add_files([broll])
    check("排回原樣：不算變更", p.bin_paths == [song, still, broll] and not p.project_changed(), str(p.bin_paths))

    # 另開一個視窗，素材庫裡先放別的
    win2, p2 = new_editor()
    other = os.path.join(tmp, "別的.png")
    run("-f", "lavfi", "-i", "color=c=red:size=64x64", "-frames:v", "1", other)
    win2.media_bin.add_files([other])
    check("開專案", p2.open_project(target) and p2.messages == [], str(p2.messages))
    check("素材庫照存的順序排回來（開之前放的換掉）", names(win2) == ["配樂.m4a", "標誌.png", "空拍.mp4"], str(names(win2)))
    check("播放器記的跟專案一樣、沒有變更", p2.bin_paths == [song, still, broll] and not p2.project_changed())
    check("縮圖與長度重新抽", wait_until(lambda: all(win2.media_bin.info[x]["seconds"] for x in (song, broll))))
    wait(50)
    check("影片有畫面縮圖、圖片用本身", os.path.isfile(win2.media_bin.info[broll]["thumb"])
          and win2.media_bin.info[still]["thumb"] == still)
    check("沒有素材時那行說明收起來", not win2.media_bin.empty_label.isVisible() and win2.media_bin.list.isVisible())
    select(win2, broll)
    check("排回來的素材照樣能用：放到播放頭", win2.media_bin.add_selected() == 1 and len(p2.tracks["overlays"]) == 1)

    # ----- 4 -----
    hidden = still + ".bak"
    os.rename(still, hidden)
    win3, p3 = new_editor()
    check("素材庫的檔案找不到：專案照樣打開", p3.open_project(target))
    text = p3.messages[-1][1] if p3.messages else ""
    check("訊息列出素材庫第幾個、說只是不放進素材庫", "素材庫第 2 個" in text and still in text
          and "素材庫裡找不到的檔案先不放進素材庫" in text, text)
    check("找得到的照樣放", names(win3) == ["配樂.m4a", "空拍.mp4"], str(names(win3)))
    check("找不到的還留在專案的清單裡、不算變更（沒做事，再存不會丟）", p3.bin_paths == [song, still, broll]
          and not p3.project_changed())
    os.rename(hidden, still)
    win4, p4 = new_editor()
    p4.open_project(target)
    wait_until(lambda: p4.player.duration() > 0)
    check("（準備）放一段音樂", p4.add_track("music", song) and len(p4.tracks["music"]) == 1)
    os.rename(song, song + ".bak")
    p4.messages = []
    p4._ask_project_path = lambda suggested: os.path.join(work, "音樂.srtproj")
    p4.save_project(os.path.join(work, "音樂.srtproj"))
    win5, p5 = new_editor()
    p5.bin_paths = []
    p5.open_project(os.path.join(work, "音樂.srtproj"))
    music_text = p5.messages[-1][1] if p5.messages else ""
    check("素材軌與素材庫都找不到：兩個都列、也講素材庫", "音樂第 1 段" in music_text and "素材庫第 1 個" in music_text
          and "素材庫裡找不到的檔案先不放進素材庫" in music_text, music_text)
    os.rename(song + ".bak", song)
    win6, p6 = new_editor()
    p6.open_video(main)
    wait_until(lambda: p6.player.duration() > 0)
    check("（準備）沒有素材庫、放一段音樂", p6.add_track("music", song) and p6.bin_paths == [])
    os.rename(song, song + ".bak")
    p6.save_project(os.path.join(work, "沒素材庫.srtproj"))
    win7, p7 = new_editor()
    p7.open_project(os.path.join(work, "沒素材庫.srtproj"))
    plain_text = p7.messages[-1][1] if p7.messages else ""
    check("只有素材軌找不到：訊息不提素材庫", "音樂第 1 段" in plain_text and "素材庫" not in plain_text, plain_text)
    os.rename(song + ".bak", song)

    # ----- 5 -----
    tabs = qt_app.MainWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    tabs.show()
    tp = tabs.player_panel
    tp.messages = []
    tp._show_project_message = lambda title, text: tp.messages.append((title, text))
    tp._ask_discard = lambda *a, **k: "discard"
    tp._ask_project_discard = lambda *a, **k: "discard"
    check("四頁籤沒有素材庫", not hasattr(tabs, "media_bin"))
    check("四頁籤開同一個專案", tp.open_project(target) and tp.bin_paths == [song, still, broll])
    copy_path = os.path.join(work, "四頁籤存的.srtproj")
    tp.save_project(copy_path)
    with open(copy_path, encoding="utf-8") as fh:
        tabs_doc = json.load(fh)
    check("四頁籤再存：素材庫的清單還在", [e["path"] for e in tabs_doc["bin"]] == ["素材/配樂.m4a", "素材/標誌.png",
                                                                          "素材/空拍.mp4"], str(tabs_doc.get("bin")))

    for w in windows + [tabs]:
        w.player_panel._ask_discard = lambda *a, **k: "discard"
        w.player_panel._ask_project_discard = lambda *a, **k: "discard"
        w.player_panel.shutdown()
        w.close()
    wait(50)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("素材庫存進專案（E-8a）介面測試全數通過。")
