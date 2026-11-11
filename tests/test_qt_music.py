# -*- coding: utf-8 -*-
"""
3.0 第 11 項第十五階段：音樂軌的「配樂設定」（對照一般版的配樂助手，缺的補在音樂軌上）。

測試素材用 ffmpeg 產生：每 0.5 秒一下的節拍聲（120 BPM）、一段沒有節拍的長音、一支每隔幾秒換顏色
（＝畫面剪接點）的影片。

1. 規則（beatsync.beats_on_timeline）：音樂放上時間軸後拍子落在影片的哪裡——平移、取一段、
   超出片尾不算、循環重複那一段、沒拍子／放在片尾之後是空的。
2. 選了音樂：屬性那一行多一顆「配樂設定…」；選畫面或沒選取時沒有。
3. 小視窗：不擋播放器；閃避強度、靈敏度、自動適應照設定填、範圍跟一般版一樣；自動開著時手動
   靈敏度不能改；改了寫進這次開啟的設定（ducking）、原本的預設音量留著；不寫 config.json。
4. 設定真的用在輸出：多軌輸出拿到的閃避參數就是小視窗上的值（assemble.duck_settings）。
5. 對象跟著選取走：選音樂寫第幾段與檔名、選畫面或取消選取就請先選一段，「分析節拍」跟著亮／灰。
6. 分析節拍：背景跑、跑的時候鈕灰掉；報告跟直接呼叫核心算出來的一樣（照音樂軌上的位置），
   開頭寫擺在哪；速度是 120 BPM；剪點對齊建議列出來。把音樂挪位置再分析：對齊結果跟著變。
   循環：落在影片上的拍子變多。
7. 沒有節拍的長音：報告講沒有穩定的節拍。檔案不見了、沒有 ffmpeg：不跑、講原因。
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import beatsync  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


# ----- 1. 規則 -----
B = [0.25, 0.75, 1.25, 1.75, 2.25, 2.75]
on = beatsync.beats_on_timeline
check("從影片 0 秒整首放：拍子原樣", on(B, 0.0, 0.0, 3.0, 10.0) == B)
check("放在 4 秒：整個平移", on(B, 4.0, 0.0, 3.0, 10.0) == [4.25, 4.75, 5.25, 5.75, 6.25, 6.75])
check("取素材的 1～2 秒：只算那一段、從放的位置起算", on(B, 4.0, 1.0, 2.0, 10.0) == [4.25, 4.75])
check("超出片尾的不算", on(B, 8.0, 0.0, 3.0, 9.0) == [8.25, 8.75])
check("沒給結尾：從進點到最後一拍", on(B, 0.0, 2.0, None, 10.0) == [0.25, 0.75])
check("循環：那一段重複到片尾", on(B, 1.0, 1.0, 2.0, 3.6, loop=True) == [1.25, 1.75, 2.25, 2.75, 3.25])
check("不循環就只有一輪", on(B, 1.0, 1.0, 2.0, 3.6) == [1.25, 1.75])
check("沒有拍子、放在片尾之後：空的", on([], 0.0, 0.0, 3.0, 10.0) == [] and on(B, 12.0, 0.0, 3.0, 10.0) == []
      and on(None, 0.0, 0.0, None, 5.0) == [])
check("循環但那一段裡沒有拍子：空的、不會轉不停", on(B, 0.0, 5.0, 6.0, 30.0, loop=True) == [])

try:
    import PySide6  # noqa: F401
except ImportError:
    PySide6 = None

if PySide6 is None or not shutil.which("ffmpeg"):
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過音樂軌的配樂設定（介面）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import music_dialog as md  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import assemble, audio  # noqa: E402
    from subtitle.pacing import detect_scene_changes, resolve_pacing_settings  # noqa: E402

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

    # 影片 9 秒：2.0、4.1、6.9 秒換顏色（畫面剪接點），帶 440Hz 的聲音
    main = os.path.join(tmp, "main.mp4")
    parts = []
    for n, (color, seconds) in enumerate((("red", 2.0), ("blue", 2.1), ("green", 2.8), ("yellow", 2.1))):
        part = os.path.join(tmp, f"p{n}.mp4")
        run("-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=30:d={seconds}",
            "-f", "lavfi", "-i", f"sine=f=440:d={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", part)
        parts.append(part)
    listing = os.path.join(tmp, "list.txt")
    with open(listing, "w", encoding="utf-8") as f:
        f.writelines(f"file '{p}'\n" for p in parts)
    run("-f", "concat", "-safe", "0", "-i", listing, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", main)
    beat = os.path.join(tmp, "節拍.wav")  # 每 0.5 秒一下＝120 BPM
    run("-f", "lavfi", "-i", "aevalsrc='0.8*sin(2*PI*1000*t)*lt(mod(t\\,0.5)\\,0.04)':d=12:s=22050", beat)
    drone = os.path.join(tmp, "長音.wav")
    run("-f", "lavfi", "-i", "sine=f=330:d=8", drone)
    logo = os.path.join(tmp, "logo.png")
    run("-f", "lavfi", "-i", "color=c=white:s=64x64", "-frames:v", "1", logo)

    cfg = {"ducking": {"music_volume": 0.5, "duck_strength": 12.0, "duck_sensitivity": 0.1,
                       "auto_sensitivity": False}}
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.show()
    panel = win.player_panel
    tv = panel.timeline
    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0, 20000)
    wait(100)
    total = panel.media_duration()

    # ----- 2. 那顆鈕 -----
    btn = panel.music_settings_btn
    check("沒選取：沒有「配樂設定…」", not btn.isVisibleTo(panel))
    panel.add_track("overlays", logo)
    check("選了畫面：沒有「配樂設定…」", not btn.isVisibleTo(panel))
    panel.player.setPosition(1000)
    wait_until(lambda: panel.player.position() == 1000, 5000)
    panel.add_track("music", beat)
    check("選了音樂：有「配樂設定…」、寫著這三個字", btn.isVisibleTo(panel) and btn.isEnabled()
          and btn.text() == "配樂設定…")
    check("「講話時壓低」的說明指到配樂設定", "配樂設定" in panel.duck_box.toolTip())

    # ----- 3. 小視窗與閃避設定 -----
    check("還沒按：沒有小視窗", panel.music_dialog is None)
    QTest.mouseClick(btn, Qt.LeftButton)
    dialog = panel.music_dialog
    check("按了：開小視窗、不擋播放器", dialog is not None and dialog.isVisible() and not dialog.isModal()
          and dialog.windowTitle() == "配樂設定")
    check("照設定填（強度 12、靈敏度 0.10、自動關）", dialog.strength_spin.value() == 12.0
          and round(dialog.sensitivity_spin.value(), 2) == 0.1 and not dialog.auto_box.isChecked())
    check("範圍跟一般版一樣（強度 1～20、靈敏度 0.01～0.5）",
          (dialog.strength_spin.minimum(), dialog.strength_spin.maximum()) == (1.0, 20.0)
          and (round(dialog.sensitivity_spin.minimum(), 2), dialog.sensitivity_spin.maximum()) == (0.01, 0.5))
    check("自動關著：手動靈敏度可以改", dialog.sensitivity_spin.isEnabled())
    check("說明講整支影片共用", "整支影片共用" in md.DUCK_NOTE and "強度" in md.DUCK_NOTE)
    dialog.strength_spin.setValue(5.5)
    check("只改強度：當下就寫進設定", cfg["ducking"]["duck_strength"] == 5.5, str(cfg["ducking"]))
    dialog.sensitivity_spin.setValue(0.2)
    check("改強度、靈敏度：寫進這次開啟的設定", cfg["ducking"]["duck_strength"] == 5.5
          and cfg["ducking"]["duck_sensitivity"] == 0.2 and cfg["ducking"]["auto_sensitivity"] is False,
          str(cfg["ducking"]))
    check("原本的預設音量留著", cfg["ducking"]["music_volume"] == 0.5)

    # ----- 4. 設定真的用在輸出 -----
    timeline = assemble.normalize({"main": [{"path": main, "out": total}], "music": panel.tracks["music"]})
    media = {main: {"audio": True}}
    check("多軌輸出拿到的閃避參數就是小視窗上的值", assemble.duck_settings(timeline, media, dict(panel._config))
          == {"threshold": 0.2, "ratio": 5.5}, str(assemble.duck_settings(timeline, media, dict(panel._config))))
    QTest.mouseClick(dialog.auto_box, Qt.LeftButton, Qt.NoModifier, QPoint(8, dialog.auto_box.height() // 2))
    check("勾自動適應：寫進設定、手動靈敏度灰掉", dialog.auto_box.isChecked()
          and cfg["ducking"]["auto_sensitivity"] is True and not dialog.sensitivity_spin.isEnabled())
    check("解析出來跟一般版同一份", audio.resolve_ducking_settings(cfg) ==
          {"music_volume": 0.5, "duck_strength": 5.5, "duck_sensitivity": 0.2, "auto_sensitivity": True})
    dialog.auto_box.setChecked(False)
    check("沒寫 config.json", not os.path.exists(config.CONFIG_PATH))

    # ----- 5. 對象跟著選取走 -----
    check("選著音樂：寫第幾段與檔名、可以分析", dialog.target == 0 and dialog.target_label.text() == "音樂第 1 段：節拍.wav"
          and dialog.beat_btn.isEnabled(), dialog.target_label.text())
    tv.select_track_item("overlays", 0, seek=False)
    check("改選畫面：請先選一段音樂、分析鈕灰掉", dialog.target is None
          and dialog.target_label.text() == md.NO_TARGET and not dialog.beat_btn.isEnabled())
    check("沒對象硬要分析：不跑、講原因", dialog.start_beats() is False and dialog.status_label.text() == md.NO_TARGET)
    tv.select_track_item("music", 0, seek=False)
    check("選回音樂：又可以分析", dialog.target == 0 and dialog.beat_btn.isEnabled())
    tv.select_track_item("music", -1, seek=False)
    check("取消選取：請先選一段音樂", dialog.target is None and not dialog.beat_btn.isEnabled())
    check("沒選取也能開小視窗（閃避設定共用）", panel.show_music_dialog() is dialog and dialog.target is None)
    tv.select_track_item("music", 0, seek=False)

    # ----- 6. 分析節拍 -----
    def expected(item):
        result = beatsync.analyze_beats(item["path"], cfg)
        placed = beatsync.beats_on_timeline(result["beats"], item["at"], item["in"], item["out"], total,
                                            item["loop"])
        cuts = detect_scene_changes(main, resolve_pacing_settings(cfg))
        return result, placed, cuts, beatsync.snap_times(cuts, placed, 0.25)

    again = []

    def analyze():
        QTest.mouseClick(dialog.beat_btn, Qt.LeftButton)
        started = dialog.busy() and not dialog.beat_btn.isEnabled()
        again.append(dialog.start_beats())
        done = wait_until(lambda: not dialog.busy())
        return started, done

    check("報告框一開始是空的、寫著會列什麼", dialog.report_box.toPlainText() == ""
          and "只出報告" in dialog.report_box.placeholderText())
    started, done = analyze()
    check("按「分析節拍」：背景跑、跑的時候鈕灰掉、跑完亮回來", started and done and dialog.beat_btn.isEnabled()
          and dialog.beat_btn.text() == "分析節拍" and not dialog.progress_bar.isVisible())
    item = dict(panel.tracks["music"][0])
    result, placed, cuts, snapped = expected(item)
    payload = dialog.last_payload
    check("跑的期間再叫一次：不重跑", again == [False], str(again))
    check("速度是 120 BPM", abs(payload["result"]["bpm"] - 120.0) < 1.0, str(payload["result"]["bpm"]))
    check("影片的剪接點抓到三個（2.0、4.1、6.9 秒附近）", len(cuts) == 3
          and all(abs(a - b) < 0.1 for a, b in zip(cuts, (2.0, 4.1, 6.9))), str(cuts))
    check("落在影片上的拍子＝照音樂軌位置換算（音樂從 1 秒放：第一拍不早於 1 秒）",
          payload["placed"] == placed and placed and placed[0] >= 1.0 and placed[-1] < total, str(placed[:4]))
    check("對齊結果跟直接呼叫核心一樣", payload["snapped"] == snapped and len(snapped) == 3, str(payload["snapped"]))
    report = dialog.report_box.toPlainText()
    check("報告＝開頭一行擺放位置＋一般版同一份報告", report == md.placement_line(item, placed) + "\n\n"
          + beatsync.format_beat_report(result, snapped, beatsync.resolve_beatsync_settings(cfg)), report)
    check("報告講得出檔名、從哪裡放、剪點對齊建議", "「節拍.wav」從影片 0:01.0 開始放" in report
          and f"共 {len(placed)} 拍" in report and "剪點對齊建議" in report and "剪點 3" in report
          and "120.0 BPM" in report, report)
    check("狀態寫完成", dialog.status_label.text() == "節拍分析完成。")
    before = [row["shift"] for row in snapped]

    # 把音樂往後挪 0.13 秒再分析：每個剪點離拍子的距離跟著變
    panel.tracks["music"][0] = dict(item, at=1.13)
    panel.refresh_tracks()
    analyze()
    moved = dialog.last_payload
    check("挪了音樂再分析：拍子跟著平移 0.13 秒", moved["placed"][0] == round(placed[0] + 0.13, 3), str(moved["placed"][:2]))
    check("挪了音樂再分析：對齊結果跟著變", [row["shift"] for row in moved["snapped"]] != before
          and moved["snapped"] == expected(panel.tracks["music"][0])[3], str(moved["snapped"]))
    check("報告開頭跟著寫新位置", "從影片 0:01.1 開始放" in dialog.report_box.toPlainText())

    # 取素材的 0～2 秒：不循環只有那幾拍、循環就鋪到片尾
    panel.tracks["music"][0] = dict(item, at=1.0, out=2.0)
    panel.refresh_tracks()
    analyze()
    short = len(dialog.last_payload["placed"])
    panel.loop_box.setChecked(True)
    analyze()
    looped = dialog.last_payload["placed"]
    check("取 2 秒不循環：只有 4 拍左右", 3 <= short <= 5, str(short))
    check("循環：拍子鋪到片尾、報告寫循環", len(looped) > short * 3 and looped[-1] > total - 0.6
          and "循環到片尾" in dialog.report_box.toPlainText(), f"{short} {looped}")

    # ----- 7. 沒有節拍、檔案不見、沒有 ffmpeg -----
    panel.add_track("music", drone)
    check("加了第二段音樂：對象換成它", dialog.target == 1 and "音樂第 2 段：長音.wav" == dialog.target_label.text())
    analyze()
    check("長音：報告講沒有穩定的節拍、不寫擺放位置", "沒有偵測到穩定的節拍" in dialog.report_box.toPlainText()
          and "開始放" not in dialog.report_box.toPlainText(), dialog.report_box.toPlainText())
    os.remove(drone)
    check("檔案不見了：不跑、講原因", dialog.start_beats() is False and dialog.status_label.text() == md.NO_FILE)
    tv.select_track_item("music", 0, seek=False)
    real = md.ffmpeg_available
    md.ffmpeg_available = lambda: False
    try:
        check("沒有 ffmpeg：不跑、講原因", dialog.start_beats() is False and dialog.status_label.text() == md.NO_FFMPEG
              and not dialog.busy())
    finally:
        md.ffmpeg_available = real

    # 讀不了的檔：講失敗、鈕亮回來
    bad = os.path.join(tmp, "壞掉.wav")
    with open(bad, "w", encoding="utf-8") as f:
        f.write("not audio")
    panel.tracks["music"][0] = dict(panel.tracks["music"][0], path=bad)
    panel.refresh_tracks()
    analyze()
    check("讀不了的檔：講分析失敗、鈕亮回來", dialog.status_label.text().startswith("節拍分析失敗：")
          and dialog.beat_btn.isEnabled() and not dialog.progress_bar.isVisible(), dialog.status_label.text())
    check("全程沒寫 config.json", not os.path.exists(config.CONFIG_PATH))

    panel._ask_discard = lambda *a, **k: True  # 收尾關視窗：不要跳「還沒存」的詢問
    panel._ask_project_discard = lambda *a, **k: "discard"
    dialog.close()
    panel.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 音樂軌配樂設定測試全數通過。")
