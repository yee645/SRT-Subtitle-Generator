# -*- coding: utf-8 -*-
"""
3.0 第 11 項第二十一階段：①「素材準備」的音訊轉影片（gui_qt/audiovis_dialog.py）。

濾鏡與夾限的規則在 test_audiovis*.py；這裡驗介面與接線，ffmpeg 真的轉、量結果。測試音訊用 ffmpeg 產生
（6 秒 440Hz）；背景圖用 ffmpeg 產生（純藍）。

1. ①頁上方「素材準備」一列有〔音訊轉影片（波形／頻譜）…〕；按下去開小視窗（不擋住主視窗、只建一個）。
2. 初值照目前的設定（audiovis）、範圍與間距跟一般版一樣；頻譜時顏色那格灰掉。
3. 不轉的情況講原因：沒選來源、來源不存在、沒有 ffmpeg、顏色格式不對、背景圖不存在。
4. 選檔、選顏色、選背景圖、清除。
5. 波形：背景跑、跑的時候控制項灰掉；檔名 `_視覺化影片.mp4`、放在來源旁邊；解析度照設定、片長照音訊、有音軌；
   畫面是黑底加波形顏色。轉好問要不要在②開，選否不開。
6. 再轉一次不覆蓋（加編號）；頻譜＋背景圖：背景圖填滿、下緣是頻譜色帶；「輸出設定」指定了資料夾就放那裡。
7. 設定寫進這次開啟的 audiovis（別的項目留著）。
8. 在②開啟：②換成這支影片，字幕不動（同一條時間軸）。
9. 背景失敗講原因；轉換中關小視窗、關主視窗都先問；全程不寫 config.json、來源不動。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過①的音訊轉影片")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import audiovis_dialog as avd  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import audiovis, exporter  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")
    work = os.path.join(tmp, "錄音夾")
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

    def probe(path, entries, stream="v:0"):
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", entries,
                              "-of", "csv=p=0", path], capture_output=True, text=True).stdout
        return out.strip()

    def seconds(path):
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True).stdout
        return float(out.strip() or 0)

    def frame(path, t, w):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", path, "-frames:v", "1", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        return [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)], w

    def count(pixels, pred):
        return sum(1 for p in pixels if pred(p))

    source = os.path.join(work, "訪談.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=6:sample_rate=22050",
                    "-af", "volume=0.8", source], check=True)
    cover = os.path.join(work, "封面.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240", "-frames:v", "1",
                    cover], check=True)
    original = (os.path.getsize(source), os.path.getmtime(source))
    srt = os.path.join(work, "訪談.srt")
    CUES = [{"start": 1.0, "end": 3.0, "text": "歡迎收聽今天的節目"}, {"start": 3.5, "end": 5.5, "text": "我們來聊聊錄音"}]
    exporter.export(CUES, srt)

    cfg = {"audiovis": {"mode": "spectrum", "color": "#ff0000", "width": 1280, "height": 720,
                        "background_image": "", "自訂": "留著"}}
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.show()
    wait(50)
    player = win.player_panel
    player._ask_discard = lambda *a, **k: "discard"
    player._ask_project_discard = lambda *a, **k: "discard"

    # ----- 1. 按鈕與小視窗 -----
    page = win.tabs.widget(0)
    check("①頁上方有「素材準備」的〔音訊轉影片（波形／頻譜）…〕", page.isAncestorOf(win.audiovis_btn)
          and win.audiovis_btn.text() == "音訊轉影片（波形／頻譜）…" and page.isAncestorOf(win.review_panel))
    check("按之前還沒有小視窗", win.audiovis_dialog is None)
    QTest.mouseClick(win.audiovis_btn, Qt.LeftButton)
    wait(50)
    dlg = win.audiovis_dialog
    check("按下去開小視窗：標題、不擋住主視窗", dlg is not None and dlg.isVisible() and not dlg.isModal()
          and dlg.windowTitle() == "音訊轉影片：波形／頻譜視覺化")
    check("②沒開檔：來源空著", dlg.source_edit.text() == "")
    check("有 ffmpeg：不出現提示列", not dlg.ffmpeg_label.isVisibleTo(dlg))
    check("狀態列提到音訊轉影片", "直式短片）、音訊轉影片與" in win.statusBar().currentMessage())
    QTest.mouseClick(win.audiovis_btn, Qt.LeftButton)
    check("再按一次：同一個小視窗", win.audiovis_dialog is dlg)

    # ----- 2. 初值與範圍 -----
    check("初值照目前的設定", dlg.mode_box.currentData() == "spectrum" and dlg.color_edit.text() == "#ff0000"
          and dlg.width_spin.value() == 1280 and dlg.height_spin.value() == 720 and dlg.bg_edit.text() == "")
    check("樣式選項跟一般版一樣", [dlg.mode_box.itemText(i) for i in range(dlg.mode_box.count())] == ["波形", "頻譜"])
    check("範圍與間距跟一般版一樣", (dlg.width_spin.minimum(), dlg.width_spin.maximum(), dlg.width_spin.singleStep())
          == (640, 3840, 160) and (dlg.height_spin.minimum(), dlg.height_spin.maximum(), dlg.height_spin.singleStep())
          == (360, 2160, 90))
    cfg["audiovis"]["background_image"] = cover
    real_ffmpeg = avd.ffmpeg_available
    avd.ffmpeg_available = lambda: False
    try:
        other = avd.AudioVisDialog(player)
    finally:
        avd.ffmpeg_available = real_ffmpeg
    check("另開一個（設定有背景圖、沒有 ffmpeg）：背景圖照設定、提示列出現", other.bg_edit.text() == cover
          and other.ffmpeg_label.isVisibleTo(other))
    other.deleteLater()
    cfg["audiovis"]["background_image"] = ""
    check("頻譜：顏色那格灰掉", not dlg.color_edit.isEnabled() and not dlg.color_btn.isEnabled())
    dlg.mode_box.setCurrentIndex(0)
    check("換成波形：顏色能改", dlg.color_edit.isEnabled() and dlg.color_btn.isEnabled())
    check("還沒轉過：〔在②開啟〕灰著、進度條藏著", not dlg.open_btn.isEnabled()
          and not dlg.progress_bar.isVisibleTo(dlg))

    # ----- 3. 不轉的情況 -----
    check("沒選來源：不轉、講原因", dlg.start() is False and dlg.status_label.text() == avd.NO_SOURCE)
    dlg.source_edit.setText(os.path.join(work, "不存在.wav"))
    check("來源不存在：不轉、講原因", dlg.start() is False and dlg.status_label.text() == avd.NO_SOURCE)
    dlg.source_edit.setText(source)
    real_ffmpeg = avd.ffmpeg_available
    avd.ffmpeg_available = lambda: False
    try:
        check("沒有 ffmpeg：不轉、講原因、提示列出現", dlg.start() is False and dlg.status_label.text() == avd.NO_FFMPEG
              and dlg.ffmpeg_label.isVisibleTo(dlg))
    finally:
        avd.ffmpeg_available = real_ffmpeg
    dlg.color_edit.setText("紅色")
    check("顏色格式不對：不轉、講原因", dlg.start() is False and dlg.status_label.text() == avd.BAD_COLOR)
    dlg.color_edit.setText("#ff0000")
    missing = os.path.join(work, "沒有這張.png")
    dlg.bg_edit.setText(missing)
    check("背景圖不存在：不轉、講原因", dlg.start() is False
          and dlg.status_label.text() == avd.NO_BACKGROUND.format(path=missing))
    check("到這裡什麼都沒轉", sorted(os.listdir(work)) == ["封面.png", "訪談.srt", "訪談.wav"])

    # ----- 4. 選檔、選顏色、清除 -----
    QTest.mouseClick(dlg.bg_clear_btn, Qt.LeftButton)
    check("〔清除〕清掉背景圖", dlg.bg_edit.text() == "")
    dlg.source_edit.clear()
    dlg._ask_source_path = lambda: source
    QTest.mouseClick(dlg.source_btn, Qt.LeftButton)
    check("〔瀏覽…〕選來源", dlg.source_edit.text() == source)
    asked_color = []
    dlg._ask_color = lambda current: (asked_color.append(current), "#00ff00")[1]
    QTest.mouseClick(dlg.color_btn, Qt.LeftButton)
    check("〔選顏色…〕：從目前的顏色開始選、選好填回去", asked_color == ["#ff0000"] and dlg.color_edit.text() == "#00ff00")
    dlg._ask_color = lambda current: ""
    QTest.mouseClick(dlg.color_btn, Qt.LeftButton)
    check("選顏色按取消：不動", dlg.color_edit.text() == "#00ff00")
    dlg._ask_background_path = lambda: cover
    QTest.mouseClick(dlg.bg_btn, Qt.LeftButton)
    check("〔瀏覽…〕選背景圖", dlg.bg_edit.text() == cover)
    dlg.bg_edit.clear()

    # ----- 5. 波形 -----
    dlg.width_spin.setValue(640)
    dlg.height_spin.setValue(360)
    calls = []
    real_render = audiovis.render_audio_video

    def spy(audio_path, output_path, settings=None, progress_cb=None, **kwargs):
        calls.append({"audio": audio_path, "output": output_path, "settings": dict(settings)})
        return real_render(audio_path, output_path, settings=settings, progress_cb=progress_cb, **kwargs)
    audiovis.render_audio_video = spy
    opened = []
    dlg._ask_open = lambda path: (opened.append(path), False)[1]
    QTest.mouseClick(dlg.run_btn, Qt.LeftButton)
    state = {"busy": dlg.rendering(), "again": dlg.start(), "progress": dlg.progress_bar.isVisibleTo(dlg),
             "enabled": [w.isEnabled() for w in (dlg.run_btn, dlg.source_edit, dlg.mode_box, dlg.color_edit,
                                                 dlg.width_spin, dlg.height_spin, dlg.bg_edit, dlg.open_btn)],
             "status": dlg.status_label.text()}
    wait_until(lambda: not dlg.rendering())
    check("按下去：背景跑、控制項灰掉、進度條出現、不能再按一次", state["busy"] and state["again"] is False
          and state["progress"] and not any(state["enabled"]), str(state))
    first = dlg.last_output
    check("檔名加「_視覺化影片」、放在來源旁邊", first == os.path.join(work, "訪談_視覺化影片.mp4")
          and os.path.exists(first), first)
    check("交給核心的設定照畫面", len(calls) == 1 and calls[0]["audio"] == source and calls[0]["settings"]
          == {"mode": "waveform", "color": "#00ff00", "width": 640, "height": 360, "background_image": ""},
          str(calls))
    check("解析度照設定、片長照音訊、有音軌", probe(first, "stream=width,height") == "640,360"
          and abs(seconds(first) - 6.0) < 0.3 and probe(first, "stream=codec_type", "a:0") == "audio")
    pixels, _w = frame(first, 2.0, 640)
    green = count(pixels, lambda p: p[1] > 150 and p[0] < 100 and p[2] < 100)
    black = count(pixels, lambda p: max(p) < 30)
    check("畫面：黑底加波形顏色（綠）", len(pixels) == 640 * 360 and green > 500 and black > len(pixels) * 0.5,
          f"green={green} black={black}")
    check("轉好問要不要在②開（選否不開）", opened == [first] and player.media_path != first)
    check("做完：控制項亮回來、〔在②開啟〕可以按、狀態列講檔名", dlg.run_btn.isEnabled() and dlg.open_btn.isEnabled()
          and not dlg.progress_bar.isVisibleTo(dlg) and first in dlg.status_label.text(), dlg.status_label.text())

    # ----- 6. 不覆蓋；頻譜＋背景圖；輸出資料夾 -----
    dlg.mode_box.setCurrentIndex(1)
    dlg.bg_edit.setText(cover)
    calls.clear()
    check("再轉一次（頻譜＋背景圖）", dlg.start())
    wait_until(lambda: not dlg.rendering())
    second = dlg.last_output
    check("不覆蓋：檔名加編號、第一支還在", os.path.basename(second) == "訪談_視覺化影片 (1).mp4"
          and os.path.exists(first), second)
    pixels, _w = frame(second, 2.0, 640)
    top = pixels[:640 * 200]
    check("背景圖填滿上面（藍）", count(top, lambda p: p[2] > 150 and p[0] < 80) > len(top) * 0.95)
    band = pixels[640 * 270:]
    check("下緣是頻譜色帶（不是背景圖的藍）", count(band, lambda p: p[2] > 150 and p[0] < 80) < len(band) * 0.5)
    outdir = os.path.join(tmp, "成品")
    cfg["automation"] = {"output_dir": outdir}
    dlg.bg_edit.clear()
    check("「輸出設定」指定了資料夾", dlg.start())
    wait_until(lambda: not dlg.rendering())
    check("放在那個資料夾", dlg.last_output == os.path.join(outdir, "訪談_視覺化影片.mp4")
          and os.path.exists(dlg.last_output), dlg.last_output)
    del cfg["automation"]

    # ----- 7. 設定 -----
    check("設定寫進這次開啟的 audiovis（別的項目留著）", cfg["audiovis"] == {
        "mode": "spectrum", "color": "#00ff00", "width": 640, "height": 360, "background_image": "",
        "自訂": "留著"}, str(cfg["audiovis"]))

    # ----- 8. 在②開啟 -----
    player.load_subtitles(srt)
    cues_before = [(c["start"], c["end"], c["text"]) for c in player.cues]
    dlg.last_output = first
    dlg._update_buttons()
    real_changed = player.project_changed
    player.project_changed = lambda: True
    player._ask_project_discard = lambda *a, **k: "cancel"
    check("專案改過、問了選取消：不開", dlg.open_in_player() is False and player.media_path != first)
    player.project_changed = real_changed
    player._ask_project_discard = lambda *a, **k: "discard"
    QTest.mouseClick(dlg.open_btn, Qt.LeftButton)
    wait_until(lambda: player.player.duration() > 0, 20000)
    check("〔在②開啟〕：②換成這支影片", player.media_path == first and dlg.status_label.text().startswith("已在②開啟"))
    check("字幕不動（同一條時間軸）", [(c["start"], c["end"], c["text"]) for c in player.cues] == cues_before)
    dlg._ask_open = lambda path: (opened.append(path), True)[1]
    player.open_video(source)
    wait(200)
    check("轉好時選「是」也會開", dlg.start())
    wait_until(lambda: not dlg.rendering())
    wait(200)
    check("選是：②開的是剛轉好的", player.media_path == dlg.last_output and opened[-1] == dlg.last_output)

    # ----- 9. 失敗、關閉 -----
    def broken(*a, **k):
        raise RuntimeError("音訊轉影片失敗：磁碟滿了")
    audiovis.render_audio_video = broken
    check("背景失敗也開始了", dlg.start())
    wait_until(lambda: not dlg.rendering())
    check("背景失敗：講原因、按鈕亮回來", dlg.status_label.text().startswith("音訊轉影片失敗：")
          and "磁碟滿了" in dlg.status_label.text() and dlg.run_btn.isEnabled(), dlg.status_label.text())
    audiovis.render_audio_video = spy

    asked = []
    dlg.ask_close_while_rendering = lambda: (asked.append(dlg.close_question()), False)[1]
    dlg._ask_open = lambda path: False
    dlg.start()
    dlg.close()
    check("轉換中關小視窗：先問，選否就不關", len(asked) == 1 and dlg.isVisible() and "還在轉換" in asked[0]
          and "可能不完整" in asked[0], str(asked))
    win.close()
    check("轉換中關主視窗：也先問，選否就不關", len(asked) == 2 and win.isVisible())
    wait_until(lambda: not dlg.rendering())
    dlg.close()
    check("轉完再關：不問", len(asked) == 2 and not dlg.isVisible())
    dlg.source_edit.clear()
    QTest.mouseClick(win.audiovis_btn, Qt.LeftButton)
    check("關掉再開：同一個小視窗；來源空著就帶②開著的檔", win.audiovis_dialog is dlg and dlg.isVisible()
          and dlg.source_edit.text() == player.media_path)
    audiovis.render_audio_video = real_render

    check("全程沒寫 config.json", not os.path.exists(config.CONFIG_PATH))
    check("來源到最後都沒動", (os.path.getsize(source), os.path.getmtime(source)) == original)

    dlg.close()
    player.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 ①音訊轉影片測試全數通過。")
