# -*- coding: utf-8 -*-
"""
3.0 第 13 項：線上配樂庫的介面（gui_qt/music_library.py）與放進音樂軌、輸出（gui_qt/player.py）。

核心（查詢參數、篩選、授權、標註文字、音樂軌讀網址）在 test_musiclib.py；這裡驗介面。
Openverse 換成替身，歌放在本機的 HTTP 伺服器（不連外網）：

1. 配樂庫視窗：條件不夠先說明；搜尋結果列成表（曲名、作者、長度、情境、風格、授權），
   選第一首；載入更多接在後面、沒有更多就灰掉；新的搜尋送出後，舊的結果晚到就丟掉；
   額度用完、連不上說清楚；試聽直接串流網址、再按一次停；放進去前先確認網址播得出來，
   讀不到就說原因、不放；不能放的時候「放進音樂軌」灰掉。
2. 播放器面板：沒開片子也能搜、不能放；開片子後放在播放頭的位置，音樂軌記網址與曲名、
   授權（不下載）；那一行寫放了哪首、授權提醒；屬性列與時間軸寫曲名；摘要寫幾段線上、
   輸出時要連網；網址讀不到就說明、不放。
3. 輸出多軌：音樂從網址讀進成品、在對的那幾秒；影片旁邊多一份 `_配樂標註.txt`；
   輸出中「放進音樂軌」灰掉；關視窗時配樂庫一起關。
"""
import functools
import http.server
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error

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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過線上配樂庫介面（核心在 test_musiclib.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from gui_qt.music_library import MusicLibraryDialog  # noqa: E402
    from subtitle import musiclib  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = tmp
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

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

    def run(*args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)

    served = os.path.join(tmp, "srv")
    os.makedirs(served)
    main = os.path.join(tmp, "main.mp4")
    run("-f", "lavfi", "-i", "color=c=gray:size=320x180:rate=30", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-t", "8", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", main)
    run("-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000", "-t", "3", os.path.join(served, "song.wav"))

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=served))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"

    def track(ident, title, license="by", genres=("lofi",), tags=("happy", "instrumental"), path="song.wav"):
        return {"id": ident, "title": title, "creator": "Tester",
                "creator_url": "", "foreign_landing_url": f"https://www.jamendo.com/track/{ident}",
                "url": f"{base_url}/{path}?trackid={ident}", "license": license, "license_version": "4.0",
                "license_url": f"https://creativecommons.org/licenses/{license}/4.0/", "provider": "jamendo",
                "source": "jamendo", "filetype": "wav", "genres": list(genres),
                "tags": [{"name": t} for t in tags], "duration": 180000}

    class FakeClient:
        def __init__(self, pages, page_count=None, error=None):
            self.pages = pages
            self.page_count = len(pages) if page_count is None else page_count
            self.error = error
            self.calls = []
            self.gate = None  # 設成 threading.Event 時，查詢卡住直到放行（模擬很慢的回應）

        def search(self, params):
            self.calls.append(dict(params))
            gate = self.gate
            if gate is not None:
                gate.wait(10)
            if self.error:
                raise self.error
            page = params["page"]
            results = self.pages[page - 1] if page <= len(self.pages) else []
            return {"result_count": 3, "page_count": self.page_count, "page": page, "results": results}

    page1 = [track("t1", "Sunny Loop"), track("t2", "Gone Tune", path="gone.wav"),
             track("t3", "Quiet Night", license="by-nc", tags=("sad", "instrumental"))]
    page2 = [track("t4", "Second Page Song")]

    # ----- 1. 配樂庫視窗 -----
    added = []
    allow = [True]
    client = FakeClient([page1, page2])
    dlg = MusicLibraryDialog(client=client, on_add=lambda rec, s: added.append((rec["id"], s)) or True,
                             can_add=lambda: allow[0])
    dlg.show()
    wait(50)
    check("什麼條件都沒有：不查，說要怎麼做",
          dlg.search() is False and client.calls == [] and dlg.status_label.text() == "輸入關鍵字，或選一個情境、風格")
    dlg.keyword_edit.setText("sunny")
    dlg.style_combo.setCurrentIndex(dlg.style_combo.findData("LoFi輕音"))
    check("送出搜尋：先寫「搜尋中…」", dlg.search() is True and dlg.status_label.text() == "搜尋中…")
    check("結果回來", wait_until(lambda: not dlg._searching, 10000))
    check("查詢照 musiclib.search_request（關鍵字＋風格，預設只查可商用）",
          client.calls[0] == musiclib.search_request("sunny", None, "LoFi輕音", True, 1), client.calls)
    rows = [[dlg.table.item(r, c).text() for c in range(dlg.table.columnCount())] for r in range(dlg.table.rowCount())]
    check("列成表：曲名、作者、長度、情境、風格、授權",
          rows[0] == ["Sunny Loop", "Tester", "3:00", "輕鬆愉快", "LoFi輕音", "需標註BY"] and len(rows) == 2, rows)
    check("選第一首；可以試聽、開原始頁面、放進去、載入更多",
          dlg.selected_record()["id"] == "openverse:t1" and dlg.preview_btn.isEnabled()
          and dlg.page_btn.isEnabled() and dlg.add_btn.isEnabled() and dlg.more_btn.isEnabled())
    check("那一行寫列出幾首、還有更多、略過的（預設不列非商用）",
          dlg.status_label.text() == "列出 2 首，還有更多；略過 授權不在這次的範圍 1 首", dlg.status_label.text())
    check("載入更多：查第 2 頁", dlg.load_more() is True and wait_until(lambda: not dlg._searching, 10000)
          and client.calls[-1]["page"] == 2)
    check("第 2 頁接在後面、沒有更多就灰掉",
          dlg.table.rowCount() == 3 and dlg.table.item(2, 0).text() == "Second Page Song"
          and not dlg.more_btn.isEnabled() and dlg.load_more() is False, dlg.status_label.text())

    slow = FakeClient([[track("s1", "Old Result")]])
    slow.gate = threading.Event()
    dlg.client = slow
    dlg.search()
    wait(100)
    dlg.client = FakeClient([[track("n1", "New Result")]])
    dlg.search()
    wait_until(lambda: not dlg._searching, 10000)
    slow.gate.set()
    wait(300)
    check("新的搜尋送出後，舊的結果晚到就丟掉",
          [dlg.table.item(r, 0).text() for r in range(dlg.table.rowCount())] == ["New Result"])

    dlg.client = FakeClient([], error=musiclib.RateLimited(60))
    dlg.search()
    wait_until(lambda: not dlg._searching, 10000)
    check("額度用完：說幾秒後再試", "額度暫時用完" in dlg.status_label.text() and "60 秒" in dlg.status_label.text(),
          dlg.status_label.text())
    dlg.client = FakeClient([], error=urllib.error.URLError("Name or service not known"))
    dlg.search()
    wait_until(lambda: not dlg._searching, 10000)
    check("連不上：說請確認網路", dlg.status_label.text().startswith("連不上 Openverse") and dlg.table.rowCount() == 0,
          dlg.status_label.text())

    dlg.client = client
    dlg.nc_box.setChecked(True)
    dlg.search()
    wait_until(lambda: not dlg._searching, 10000)
    check("勾「也列非商用」：NC 的也列，授權寫非商用、滑鼠停著有提醒",
          client.calls[-1]["license"].endswith("by-nc,by-nc-sa") and dlg.table.rowCount() == 3
          and dlg.table.item(2, 5).text() == "非商用BY-NC" and "非商用" in dlg.table.item(2, 5).toolTip())
    check("試聽：直接串流網址，按鈕變「停止」",
          dlg.toggle_preview() is True and dlg.previewing == "openverse:t1"
          and dlg.player.source() == QUrl(page1[0]["url"]) and dlg.preview_btn.text() == "停止")
    check("再按一次就停、放掉連線",
          dlg.toggle_preview() is False and dlg.previewing is None and dlg.player.source() == QUrl()
          and dlg.preview_btn.text() == "試聽")

    check("放進去：先在背景確認網址", dlg.add_selected() is True and not dlg.add_btn.isEnabled()
          and dlg.status_label.text() == "確認「Sunny Loop」播得出來…")
    wait_until(lambda: dlg._checking is None, 30000)
    check("確認播得出來：交給面板，帶量到的長度",
          len(added) == 1 and added[0][0] == "openverse:t1" and abs(added[0][1] - 3.0) < 0.05, added)
    check("那一行寫放進去了", dlg.status_label.text() == "已放進音樂軌：「Sunny Loop」（需標註BY）",
          dlg.status_label.text())
    dlg.table.selectRow(1)
    dlg.add_selected()
    wait_until(lambda: dlg._checking is None, 30000)
    check("網址讀不到：說原因、不放",
          len(added) == 1 and dlg.status_label.text().startswith("「Gone Tune」放不進去：讀不到聲音"),
          dlg.status_label.text())
    allow[0] = False
    dlg.update_buttons()
    check("不能放的時候（沒開片子、輸出中）「放進音樂軌」灰掉",
          not dlg.add_btn.isEnabled() and dlg.add_selected() is False)
    dlg.toggle_preview()
    dlg.close()
    check("關掉視窗就停止試聽", dlg.previewing is None)

    # ----- 2. 播放器面板 -----
    win = qt_app.MainWindow({"subtitle_style": {}})
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 860)
    win.show()
    panel = win.player_panel
    errors = []
    panel._show_track_error = errors.append
    check("素材軌那一行有「線上配樂…」，沒開片子也能開（先找歌）",
          panel.music_lib_btn.isEnabled() and panel.music_lib_btn.text() == "線上配樂…")
    lib = panel.open_music_library(client=FakeClient([page1]))
    check("開的是配樂庫視窗，不擋住面板", isinstance(lib, MusicLibraryDialog) and lib.isVisible() and not lib.isModal()
          and panel.open_music_library() is lib)
    lib.mood_combo.setCurrentIndex(lib.mood_combo.findData("輕鬆愉快"))
    lib.search()
    wait_until(lambda: not lib._searching, 10000)
    check("沒開片子：搜得到，但不能放", lib.table.rowCount() == 2 and not lib.add_btn.isEnabled()
          and panel.add_online_music(musiclib.record_from_openverse(page1[0])) is False)

    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0, 20000)
    wait(100)
    check("開片子後：配樂庫的「放進音樂軌」跟著亮", lib.add_btn.isEnabled())
    panel.player.setPosition(1000)
    wait_until(lambda: panel.player.position() == 1000, 5000)
    lib.table.selectRow(0)
    lib.add_selected()
    check("放進音樂軌", wait_until(lambda: panel.tracks["music"], 30000))
    item = panel.tracks["music"][0] if panel.tracks["music"] else {}
    check("在播放頭的位置（1 秒）放整首；記的是網址，不下載",
          item.get("path") == page1[0]["url"] and item.get("at") == 1.0 and abs(item.get("out", 0) - 3.0) < 0.05
          and item.get("volume") == 0.35 and item.get("duck") is True, item)
    check("另外記曲名、授權與標註文字",
          item.get("title") == "Sunny Loop" and item.get("license") == "by"
          and item.get("credit", "").startswith('Music: "Sunny Loop" by Tester'), item)
    check("那一行寫放了哪首、授權、線上串流",
          panel.track_label.text() == "已放進「Sunny Loop」（需標註BY，線上串流、不佔硬碟）", panel.track_label.text())
    check("選取那一段：屬性列寫曲名（不是網址）、滑鼠停著看標註",
          panel.timeline.track_selected == ("music", 0) and panel.prop_label.text() == "Sunny Loop"
          and panel.prop_label.toolTip() == item.get("credit"))
    wait(50)
    tips = [it.toolTip() for it in panel.timeline.scene_.items() if it.toolTip().startswith("音樂")]
    check("時間軸上的方塊寫曲名、提示是線上配樂", any(t.startswith("音樂：Sunny Loop") and "線上配樂（不下載" in t
                                                     for t in tips), tips)
    nc = musiclib.record_from_openverse(page1[2])
    check("NC 的歌：放進去時提醒不能營利",
          panel.add_online_music(nc, 3.0) is True and "注意：非商用" in panel.track_label.text(),
          panel.track_label.text())
    panel.remove_track("music", 1)
    panel.refresh_tracks()
    check("摘要寫幾段線上、輸出時要連網", "音樂 1 段（1 段線上，輸出時要連網）" in panel.track_label.text(),
          panel.track_label.text())
    gone = musiclib.record_from_openverse(page1[1])
    check("網址讀不到（沒先確認就直接放）：說明、不放",
          panel.add_online_music(gone) is False and len(panel.tracks["music"]) == 1
          and errors and errors[-1].startswith("「Gone Tune」放不進去：讀不到聲音"), errors)

    # ----- 3. 輸出多軌 -----
    out = os.path.join(tmp, "成品.mp4")
    check("輸出多軌", panel.export_tracks(out) is True)
    check("輸出中：配樂庫的「放進音樂軌」灰掉", not lib.add_btn.isEnabled())
    wait_until(lambda: not panel.track_exporter.busy, 120000)
    result = panel.last_assemble or {}
    credits = os.path.join(tmp, "成品_配樂標註.txt")
    check("輸出成功，旁邊寫一份標註", os.path.isfile(out) and result.get("credits") == credits
          and os.path.isfile(credits), str(result) + str(errors))
    text = open(credits, encoding="utf-8-sig").read() if os.path.isfile(credits) else ""
    check("標註寫影片名稱與那首歌的 TASL", text.startswith("這支影片（成品.mp4）用到的線上配樂")
          and item.get("credit", "?") in text, text)
    check("那一行寫輸出了標註", "成品_配樂標註.txt（線上配樂的標註" in panel.track_label.text(),
          panel.track_label.text())

    def tone(path, start, end):
        res = subprocess.run(["ffmpeg", "-v", "info", "-ss", str(start), "-t", str(end - start), "-i", path, "-af",
                              "bandpass=f=880:width_type=h:w=100,volumedetect", "-f", "null", "-"],
                             capture_output=True, text=True).stderr
        return float([l.split("mean_volume:")[1].split()[0] for l in res.splitlines() if "mean_volume" in l][0])

    if os.path.isfile(out):
        loud = [tone(out, 1.3, 3.7), tone(out, 0.1, 0.8), tone(out, 4.4, 7.8)]
        check("音樂從網址讀進成品，在 1～4 秒", loud[0] > -45 and loud[1] < -55 and loud[2] < -55, loud)

    panel.shutdown()
    check("關視窗前配樂庫一起關", not lib.isVisible())
    win.close()
    server.shutdown()
    server.server_close()
    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 線上配樂庫介面測試全數通過。")
