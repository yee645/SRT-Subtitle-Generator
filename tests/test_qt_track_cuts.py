# -*- coding: utf-8 -*-
"""
3.0 第 7 項第五階段：多軌與剪點一起輸出。

規則（assemble.apply_cuts）在 test_assemble.py；這裡驗播放器面板真的照剪點輸出：

1. 時間軸上顯示著剪點、有啟用的剪點 → 素材軌那一行寫「會照剪點一起剪掉 N 處」；
   剪點全停用或選單切到「不顯示」就不寫。
2. 輸出：片長＝剪後、剪掉的那段主軌（藍色）不在成品裡、畫面素材跟著剪與平移、
   音樂平移後一路播、字幕對齊到剪後的時間軸；那一行寫剪掉幾處。
3. 不顯示剪點時照舊：片長＝原片、字幕原封不動。
"""
import os
import re
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過多軌與剪點一起輸出（核心在 test_assemble.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import assemble  # noqa: E402

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

    # 主片 8 秒：灰、3～5 秒藍（會被剪掉的那段）、再灰；聲音 150 Hz（量 1000 Hz 時濾得掉）
    main = os.path.join(tmp, "main.mp4")
    run("-f", "lavfi", "-i", "color=c=0x808080:size=640x360:rate=30:d=3",
        "-f", "lavfi", "-i", "color=c=blue:size=640x360:rate=30:d=2",
        "-f", "lavfi", "-i", "color=c=0x808080:size=640x360:rate=30:d=3",
        "-f", "lavfi", "-i", "sine=frequency=150:sample_rate=48000:d=8",
        "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1[v]", "-map", "[v]", "-map", "3:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", main)
    red = os.path.join(tmp, "red.png")
    run("-f", "lavfi", "-i", "color=c=red:size=320x180", "-frames:v", "1", red)
    song = os.path.join(tmp, "song.wav")
    run("-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000", "-t", "6", song)

    win = qt_app.MainWindow({"subtitle_style": {}})
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 860)
    win.show()
    panel = win.player_panel
    errors = []
    panel._show_track_error = errors.append
    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0, 20000)
    wait(100)
    cues = [{"start": 0.2, "end": 2.5, "text": "第一句"}, {"start": 5.5, "end": 7.8, "text": "第二句"}]
    panel.set_cues(cues)

    # 畫面：紅色圖片放右上角 1～7 秒（跨過剪點）；音樂：1 秒開始放 6 秒（不壓低，量得乾淨）
    panel.player.setPosition(1000)
    wait_until(lambda: panel.player.position() == 1000, 5000)
    panel.add_track("overlays", red)
    panel.set_track_props(duration=6.0, rect=assemble.position_rect("top_right"))
    panel.add_track("music", song)
    panel.set_track_props(duck=False)
    check("素材放好：圖片 1～7 秒在右上角、音樂 1 秒開始 6 秒",
          panel.tracks["overlays"] == [{"path": red, "at": 1.0, "duration": 6.0,
                                        "rect": assemble.position_rect("top_right")}]
          and panel.tracks["music"][0]["at"] == 1.0 and panel.tracks["music"][0]["out"] == 6.0
          and panel.tracks["music"][0]["duck"] is False, f"{panel.tracks}")

    # ----- 1. 那一行寫會不會一起剪 -----
    check("沒顯示剪點：那一行不提剪點", "剪掉" not in panel.track_label.text(), panel.track_label.text())
    panel.show_cut_marks("jumpcut")
    marks = panel.cut_plan["marks"]
    check("停頓剪點：剪掉 2.65～5.35（兩句中間）",
          [(m["start"], m["end"]) for m in marks] == [(2.65, 5.35)], str(marks))
    check("顯示剪點後：那一行緊接在段數後面寫會照剪點一起剪掉 1 處（太長時尾巴會被截掉，這句不能被截）",
          panel.track_label.text().startswith("畫面 1 段、音樂 1 段（會照剪點一起剪掉 1 處）"),
          panel.track_label.text())
    panel.timeline.cutMarkToggled.emit(0, False)
    check("剪點停用：那一行不再說要剪", "剪掉" not in panel.track_label.text(), panel.track_label.text())
    panel.timeline.cutMarkToggled.emit(0, True)
    check("再啟用：又寫要剪", "會照剪點一起剪掉 1 處" in panel.track_label.text(), panel.track_label.text())

    # ----- 2. 照剪點一起輸出 -----
    out = os.path.join(tmp, "剪好.mp4")
    check("開始輸出", panel.export_tracks(out) is True and errors == [], str(errors))
    wait_until(lambda: not panel.track_exporter.busy, 120000)
    wait(100)
    result = panel.last_assemble
    check("輸出成功、那一行寫剪掉幾處與字幕檔",
          result is not None and result["output"] == out and errors == []
          and "已輸出 剪好.mp4（剪掉 1 處）＋剪好.srt" in panel.track_label.text(),
          f"{result} {errors} {panel.track_label.text()}")
    check("結果帶著剪掉幾處、拿掉幾句", result and result.get("cut_count") == 1 and result.get("dropped") == 0,
          str(result))

    def probe_duration(path):
        return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                     "-of", "default=nw=1:nk=1", path], capture_output=True, text=True).stdout)

    dur = probe_duration(out)
    check("片長＝剪後（8 − 2.7 ＝ 5.3 秒）", abs(dur - 5.3) < 0.1, str(dur))

    def rgb(path, t, x, y):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1",
                              "-vf", "scale=64:36", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True).stdout
        i = (y * 64 + x) * 3
        return tuple(raw[i:i + 3])

    def near(color, want, tol=45):
        return len(color) == 3 and all(abs(c - w) <= tol for c, w in zip(color, want))

    # 主軌（左下角）每 0.25 秒看一格：剪掉的藍色那段不在成品裡
    bottom_left = [rgb(out, t / 4.0, 8, 30) for t in range(0, 21)]
    check("剪掉的那段主軌（藍色 3～5 秒）不在成品裡：每一格都是灰",
          all(near(c, (128, 128, 128)) for c in bottom_left), str([c for c in bottom_left
                                                                  if not near(c, (128, 128, 128))]))
    # 圖片在右上角：剪後 1～4.3 秒（1～2.65 ＋ 5.35～7 接起來）
    corner = {t: rgb(out, t, 50, 6) for t in (0.5, 1.5, 2.4, 2.9, 4.0, 4.6, 5.1)}
    check("畫面素材跟著剪：剪後 1～4.3 秒在右上角（接縫 2.65 前後都在），之前之後是主片的灰",
          all(near(corner[t], (255, 0, 0)) for t in (1.5, 2.4, 2.9, 4.0))
          and all(near(corner[t], (128, 128, 128)) for t in (0.5, 4.6, 5.1)), str(corner))

    def tone_db(path, start, length):
        done = subprocess.run(["ffmpeg", "-v", "info", "-ss", str(start), "-t", str(length), "-i", path,
                               "-af", "highpass=f=700,highpass=f=700,highpass=f=700,highpass=f=700,volumedetect",
                               "-vn", "-f", "null", "-"], capture_output=True, text=True)
        found = re.search(r"mean_volume:\s*(-?[\d.]+|-inf) dB", done.stderr)
        return float(found.group(1)) if found and found.group(1) != "-inf" else -200.0

    before, during, after = tone_db(out, 0.1, 0.8), tone_db(out, 1.2, 3.0), tone_db(out, 4.5, 0.7)
    check("音樂平移後一路播：剪後 1～4.3 秒有、之前之後沒有（高頻差 20 dB 以上）",
          during - before > 20 and during - after > 20, f"{before} {during} {after}")
    with open(os.path.join(tmp, "剪好.srt"), encoding="utf-8") as fh:
        srt = fh.read()
    check("字幕對齊到剪後的時間軸（第二句 5.5 → 2.8）",
          "00:00:00,200 --> 00:00:02,500" in srt and "00:00:02,800 --> 00:00:05,100" in srt, srt)
    check("原本的字幕與素材軌不動",
          panel.cues[1]["start"] == 5.5 and panel.tracks["overlays"][0]["at"] == 1.0
          and panel.tracks["overlays"][0]["duration"] == 6.0, f"{panel.cues} {panel.tracks}")

    # ----- 3. 不顯示剪點：照舊 -----
    panel.show_cut_marks("")
    check("不顯示剪點：那一行不提剪點", "剪掉" not in panel.track_label.text(), panel.track_label.text())
    plain = os.path.join(tmp, "不剪.mp4")
    panel.export_tracks(plain)
    wait_until(lambda: not panel.track_exporter.busy, 120000)
    wait(100)
    check("不剪：片長＝原片（8 秒）、那一行不寫剪掉", abs(probe_duration(plain) - 8.0) < 0.1
          and "已輸出 不剪.mp4＋不剪.srt" in panel.track_label.text(), panel.track_label.text())
    with open(os.path.join(tmp, "不剪.srt"), encoding="utf-8") as fh:
        check("不剪：字幕原封不動", "00:00:05,500 --> 00:00:07,800" in fh.read())

    # 剪點把一整句剪掉：說拿掉幾句
    panel.set_cues(cues + [{"start": 3.5, "end": 4.0, "text": "被剪掉的一句"}])
    panel.show_cut_marks("jumpcut")
    panel.timeline.cutMarkChanged.emit(0, 2.65, 5.35)  # 把第一段剪點拖到蓋過那一句
    check("拖成蓋過整句的剪點", [(m["start"], m["end"]) for m in panel.cut_plan["marks"]][:1] == [(2.65, 5.35)],
          str(panel.cut_plan["marks"]))
    dropped_out = os.path.join(tmp, "拿掉.mp4")
    panel.export_tracks(dropped_out)
    wait_until(lambda: not panel.track_exporter.busy, 120000)
    wait(100)
    check("整句被剪掉：那一行寫拿掉幾句", "句整句被剪掉" in panel.track_label.text()
          and panel.last_assemble.get("dropped", 0) >= 1, panel.track_label.text())

    # 剪點不合理（剪到什麼都不剩）：說清楚、不輸出
    errors.clear()
    panel.cut_overrides = {panel.cut_plan["marks"][0]["key"]: {"start": 0.0, "end": 8.0}}
    panel.refresh_cut_marks()
    for m in panel.cut_plan["marks"]:
        if (m["start"], m["end"]) != (0.0, 8.0):
            panel.cut_overrides[m["key"]] = {"enabled": False}
    panel.refresh_cut_marks()
    check("剪到什麼都不剩：說清楚、不輸出", panel.export_tracks(os.path.join(tmp, "空.mp4")) is False
          and errors and "什麼都不剩" in errors[-1] and not os.path.exists(os.path.join(tmp, "空.mp4")),
          f"{errors} {panel.cut_plan['marks']}")
    panel.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 多軌與剪點一起輸出測試全數通過。")
