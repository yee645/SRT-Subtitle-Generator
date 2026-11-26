# -*- coding: utf-8 -*-
"""
剪輯器版面改版 E-4：素材庫（gui_qt/media_bin.py）與拖到時間軸（gui_qt/timeline.py、PlayerPanel.drop_files）。

規則（收哪些檔、去重、拖到哪一列放哪一軌）在 test_mediabin.py；這裡驗介面：

1. 媒體區最上面是素材庫：沒有素材時寫怎麼用、不顯示空的格子。
2. 匯入一批：收影片、圖片、聲音，略過的講原因；背景抽好縮圖與長度（影片有畫面縮圖、名字下面寫長度；
   圖片用本身當縮圖）；已經拿掉的素材晚到的結果丟掉。
3. 按鈕：沒選不能按；〔開成主片〕只有選一支影片才能按，按了照〔開啟影片〕的規則換主片；
   沒開主片時〔加到播放頭〕不能按，開了就能按。
4. 〔加到播放頭〕／雙擊：選的素材放到播放頭，影片與圖片放疊加、聲音放音樂，每一軌各自一個接一個；可以復原。
5. 從素材庫拖出去的是檔案網址（時間軸、別的程式都認得）。
6. 拖到時間軸：落在疊加列放疊加、音樂列放音樂，從落下的秒數開始；疊加列放聲音不收、講原因；沒開影片時不接。
7. 〔移除〕：從素材庫拿掉（不刪檔、時間軸上的不動）。
8. 換深淺色：沒有縮圖的素材照新顏色重畫，不出錯。
"""
import copy
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過素材庫（規則在 test_mediabin.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QMimeData, QPointF, Qt, QTimer, QUrl  # noqa: E402
    from PySide6.QtGui import QDragEnterEvent, QDropEvent  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import editor as ed  # noqa: E402
    from gui_qt import media_bin as mb  # noqa: E402
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

    main = os.path.join(tmp, "main.mp4")
    broll = os.path.join(tmp, "broll.mp4")
    still = os.path.join(tmp, "logo.png")
    song = os.path.join(tmp, "song.m4a")
    notes = os.path.join(tmp, "notes.txt")
    run("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-f", "lavfi", "-i", "sine=frequency=440",
        "-t", "12", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", main)
    run("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-f", "lavfi", "-i", "sine=frequency=330",
        "-t", "3", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", broll)
    run("-f", "lavfi", "-i", "testsrc2=size=160x90", "-frames:v", "1", still)
    run("-f", "lavfi", "-i", "sine=frequency=220", "-t", "4", "-c:a", "aac", song)
    open(notes, "w").close()

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
    errors = []
    p._show_track_error = lambda msg: errors.append(msg)
    t = p.timeline
    bin_ = win.media_bin

    def inside(widget, ancestor):
        w = widget
        while w is not None:
            if w is ancestor:
                return True
            w = w.parentWidget()
        return False

    def names():
        return [os.path.basename(bin_.list.item(i).data(Qt.UserRole)) for i in range(bin_.list.count())]

    def select(*files):
        bin_.list.clearSelection()
        for i in range(bin_.list.count()):
            if bin_.list.item(i).data(Qt.UserRole) in files:
                bin_.list.item(i).setSelected(True)

    # ----- 1 -----
    win.show_section("media")
    wait(30)
    check("素材庫在媒體區", inside(bin_, win.left_pages["media"]) and bin_.isVisible())
    check("沒有素材：寫怎麼用、不顯示空格子", bin_.empty_label.isVisible() and bin_.empty_label.text() == mb.EMPTY_TEXT
          and not bin_.list.isVisible())
    check("沒選：三顆都不能按", not bin_.add_btn.isEnabled() and not bin_.main_btn.isEnabled()
          and not bin_.remove_btn.isEnabled())

    # ----- 2 -----
    added, skipped = bin_.add_files([main, broll, still, song, notes, still])
    check("匯入一批：收影片、圖片、聲音", names() == ["main.mp4", "broll.mp4", "logo.png", "song.m4a"]
          and len(added) == 4, str(names()))
    check("略過的講原因", len(skipped) == 2 and "notes.txt（不是影片、圖片或聲音）" in bin_.empty_label.text()
          and "已經在素材庫裡" in bin_.empty_label.text() and bin_.empty_label.isVisible(), bin_.empty_label.text())
    check("背景抽好縮圖與長度", wait_until(lambda: all(bin_.info[x]["seconds"] for x in (main, broll, song))))
    wait(50)
    check("影片有畫面縮圖", os.path.isfile(bin_.info[broll]["thumb"]) and bin_.info[still]["thumb"] == still
          and bin_.info[song]["thumb"] == "")
    texts = [bin_.list.item(i).text() for i in range(bin_.list.count())]
    check("名字下面寫長度（圖片沒有）", texts == ["main.mp4\n0:12", "broll.mp4\n0:03", "logo.png", "song.m4a\n0:04"],
          str(texts))
    check("每一格都有圖示（縮圖或種類圖示）", all(not bin_.list.item(i).icon().isNull() for i in range(4)))
    bin_._on_probed(os.path.join(tmp, "removed.mp4"), "", 9.0)
    check("已經不在素材庫的晚到結果丟掉", len(bin_.entries) == 4 and os.path.join(tmp, "removed.mp4") not in bin_.info)

    # ----- 3 -----
    select(still)
    check("沒開主片：〔加到播放頭〕不能按；選圖片不能開成主片；能移除",
          not bin_.add_btn.isEnabled() and not bin_.main_btn.isEnabled() and bin_.remove_btn.isEnabled())
    select(main, broll)
    check("選兩支影片：不能開成主片", not bin_.main_btn.isEnabled())
    select(main)
    check("選一支影片：能開成主片", bin_.main_btn.isEnabled())
    asked = []
    p._maybe_drop_project = lambda: asked.append(1) or False
    check("換主片前先問（不換就不開）", bin_.open_selected_as_main() is False and asked == [1] and not p.media_path)
    p._maybe_drop_project = lambda: True
    check("開成主片", bin_.open_selected_as_main() and wait_until(lambda: p.media_duration() > 0 and t.duration > 0)
          and os.path.samefile(p.media_path, main))
    wait(30)
    check("開了主片：〔加到播放頭〕能按", bin_.add_btn.isEnabled())

    # ----- 4 -----
    p.player.setPosition(2000)
    wait_until(lambda: p.player.position() == 2000, 5000)
    select(broll, still, song)
    check("〔加到播放頭〕放了三個", bin_.add_selected() == 3, str(errors))
    ov = [(os.path.basename(i["path"]), i["at"]) for i in p.tracks["overlays"]]
    mu = [(os.path.basename(i["path"]), i["at"]) for i in p.tracks["music"]]
    check("影片與圖片放疊加、一個接一個", ov == [("broll.mp4", 2.0), ("logo.png", 5.0)], str(ov))
    check("聲音放音樂、也從播放頭開始（每一軌各自接）", mu == [("song.m4a", 2.0)], str(mu))
    p.undo()
    p.undo()
    p.undo()
    check("三個都能復原", not p.tracks["overlays"] and not p.tracks["music"])
    select(still)
    bin_.list.itemDoubleClicked.emit(bin_.list.selectedItems()[0])
    check("雙擊＝加到播放頭", [os.path.basename(i["path"]) for i in p.tracks["overlays"]] == ["logo.png"])
    p.undo()

    # ----- 5 -----
    data = bin_.list.mimeData(bin_.list.selectedItems())
    check("拖出去的是檔案網址", data.hasUrls() and [u.toLocalFile() for u in data.urls()] == [still]
          and "text/uri-list" in bin_.list.mimeTypes())
    check("可以拖", bin_.list.dragEnabled())

    # ----- 6 -----
    def drop(files, row, seconds):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(f) for f in files])
        x = seconds * t.px_per_sec - t.horizontalScrollBar().value()
        y = t.row_y[row] + t.row_h[row] / 2 - t.verticalScrollBar().value()
        pos = QPointF(x, y)
        enter = QDragEnterEvent(pos.toPoint(), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(t.viewport(), enter)
        ev = QDropEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(t.viewport(), ev)
        wait(30)
        return enter.isAccepted(), ev.isAccepted()

    check("落點：列與秒數", t.drop_target(t.mapFromScene(6 * t.px_per_sec, t.row_y["music"] + 2)) == ("music", 6.0))
    accepted = drop([still], "overlays", 6.0)
    check("拖到疊加列：接受、從 6 秒放疊加", accepted == (True, True)
          and [(os.path.basename(i["path"]), round(i["at"], 1)) for i in p.tracks["overlays"]] == [("logo.png", 6.0)],
          f"{accepted} {p.tracks['overlays']}")
    drop([broll], "music", 1.0)
    check("影片拖到音樂列：放音樂（用它的聲音）", [os.path.basename(i["path"]) for i in p.tracks["music"]] == ["broll.mp4"]
          and round(p.tracks["music"][0]["at"], 1) == 1.0)
    before = copy.deepcopy(p.tracks)
    drop([song], "overlays", 3.0)
    check("聲音拖到疊加列：不收、講原因", p.tracks == before and "疊加列放不了：song.m4a" in p.track_label.text(),
          p.track_label.text())
    drop([song], "cues", 8.0)
    check("拖到字幕列：照種類放（聲音放音樂）", [os.path.basename(i["path"]) for i in p.tracks["music"]]
          == ["broll.mp4", "song.m4a"])
    p.undo()
    check("拖進來的也能復原", len(p.tracks["music"]) == 1)
    t.set_duration(0)
    check("沒有片長：拖進來不接", drop([still], "overlays", 1.0) == (False, False))
    t.set_duration(p.media_duration())
    p.media_path = ""
    errors.clear()
    check("沒開主片：drop_files 不放、講一聲", p.drop_files([still], "overlays", 1.0) == 0
          and errors == ["先開啟影片（主片），再把素材放上時間軸"])
    p.media_path = main

    # ----- 7 -----
    select(song, still)
    on_timeline = copy.deepcopy(p.tracks)
    check("〔移除〕兩個", bin_.remove_selected() == 2 and names() == ["main.mp4", "broll.mp4"]
          and os.path.isfile(song) and p.tracks == on_timeline)

    # ----- 8 -----
    bin_.add_files([song])
    wait_until(lambda: bin_.info.get(song, {}).get("seconds"))
    win.toggle_theme()
    wait(30)
    check("換淺色：素材庫照樣有圖示", all(not bin_.list.item(i).icon().isNull() for i in range(bin_.list.count())))
    win.toggle_theme()
    win.close()
    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("素材庫（E-4）測試全數通過。")
