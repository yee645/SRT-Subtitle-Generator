# -*- coding: utf-8 -*-
"""
3.0 第 8 項第二階段：剪點接縫的轉場（剪點那一行的「接縫硬切／溶接／黑場」）。

規則（assemble.seam_durations／apply_cuts／cut_cues）在 test_assemble.py；這裡驗接線，
用 ffmpeg 真的剪：

1. 預設硬切、長度不能改；選溶接後長度能改；素材軌那一行寫接縫用什麼。
2. 硬切時「照剪點輸出…」照舊走裁切引擎（片長＝留下的總長）。
3. 溶接時「照剪點輸出…」：片長再少掉接縫那幾秒、接縫正中間是兩段畫面各半、字幕對齊到
   重疊後的時間、那一行寫幾個接縫用溶接。
4. 黑場時「輸出多軌…」：接縫那一秒裡有一格接近全黑、素材平移、字幕對齊。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過剪點接縫的轉場（核心在 test_assemble.py）")
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

    def wait_until(cond, timeout_ms=120000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(50)
            waited += 50
        return cond()

    def run(*args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)

    def duration(path):
        return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                     "-of", "default=nw=1:nk=1", path], capture_output=True, text=True).stdout)

    def rgb(path, t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1",
                              "-vf", "crop=40:40:10:300,scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True).stdout  # 左下角：素材放右上角，不會蓋到
        return tuple(raw[:3])

    def near(color, want, tol=45):
        return len(color) == 3 and all(abs(c - w) <= tol for c, w in zip(color, want))

    # 主片 8 秒：0～4 紅、4～8 綠；字幕兩句中間 2.65～5.35 會被停頓剪點剪掉
    main = os.path.join(tmp, "main.mp4")
    run("-f", "lavfi", "-i", "color=c=red:size=640x360:rate=30:d=4",
        "-f", "lavfi", "-i", "color=c=0x00ff00:size=640x360:rate=30:d=4",
        "-f", "lavfi", "-i", "sine=frequency=150:sample_rate=48000:d=8",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", main)
    logo = os.path.join(tmp, "logo.png")
    run("-f", "lavfi", "-i", "color=c=white:size=320x180", "-frames:v", "1", logo)

    win = qt_app.MainWindow({"subtitle_style": {}})
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 860)
    win.show()
    panel = win.player_panel
    errors = []
    panel._show_export_error = errors.append
    panel._show_track_error = errors.append
    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0, 20000)
    wait(100)
    panel.set_cues([{"start": 0.2, "end": 2.5, "text": "第一句"}, {"start": 5.5, "end": 7.8, "text": "第二句"}])
    panel.show_cut_marks("jumpcut")
    check("停頓剪點：剪掉 2.65～5.35", [(m["start"], m["end"]) for m in panel.cut_plan["marks"]] == [(2.65, 5.35)],
          str(panel.cut_plan["marks"]))

    # ----- 1. 控件 -----
    check("預設接縫硬切、長度不能改、seam_transition 是 None",
          panel.seam_combo.currentData() == "" and not panel.seam_spin.isEnabled()
          and panel.seam_transition() is None and panel.seam_combo.isVisible())
    check("選單裡有硬切、溶接、黑場", [panel.seam_combo.itemText(i) for i in range(panel.seam_combo.count())]
          == ["接縫硬切", "接縫溶接", "接縫黑場"])
    panel.seam_combo.setCurrentIndex(panel.seam_combo.findData("dissolve"))
    check("選溶接：長度能改、預設 0.5 秒", panel.seam_spin.isEnabled()
          and panel.seam_transition() == {"type": "dissolve", "duration": 0.5}, str(panel.seam_transition()))
    panel.player.setPosition(1000)
    wait_until(lambda: panel.player.position() == 1000, 5000)
    panel.add_track("overlays", logo)
    panel.set_track_props(rect=assemble.position_rect("top_right"))  # 量顏色看左下角，不會蓋到
    check("素材軌那一行寫接縫用溶接", "（會照剪點一起剪掉 1 處、接縫用溶接）" in panel.track_label.text(),
          panel.track_label.text())
    panel.seam_combo.setCurrentIndex(panel.seam_combo.findData(""))
    check("改回硬切：那一行不提接縫、長度又不能改", "接縫" not in panel.track_label.text()
          and not panel.seam_spin.isEnabled(), panel.track_label.text())

    # ----- 2. 硬切：照舊 -----
    hard = os.path.join(tmp, "硬切.mp4")
    panel.export_cuts(hard)
    wait_until(lambda: not panel.exporter.busy)
    wait(100)
    check("硬切照剪點輸出：片長＝留下的 5.3 秒、走原本的裁切引擎（結果裡沒有多軌時間軸）",
          abs(duration(hard) - 5.3) < 0.1 and "timeline" not in panel.last_export and errors == [],
          f"{duration(hard)} {errors}")

    # ----- 3. 溶接：照剪點輸出 -----
    panel.seam_combo.setCurrentIndex(panel.seam_combo.findData("dissolve"))
    soft = os.path.join(tmp, "溶接.mp4")
    check("開始輸出", panel.export_cuts(soft) is True)
    wait_until(lambda: not panel.exporter.busy)
    wait(100)
    result = panel.last_export
    check("溶接照剪點輸出成功：那一行寫 1 個接縫用溶接", result is not None and result["output"] == soft
          and errors == [] and "1 個接縫用溶接" in panel.cut_label.text(),
          f"{errors} {panel.cut_label.text()}")
    check("溶接：片長再少掉 0.5 秒（5.3 − 0.5 ＝ 4.8）", abs(duration(soft) - 4.8) < 0.1, str(duration(soft)))
    colors = {t: rgb(soft, t) for t in (1.8, 2.4, 3.0)}
    check("溶接：接縫前紅、接縫正中間（2.4 秒）紅綠各半、接縫後綠",
          near(colors[1.8], (255, 0, 0)) and near(colors[2.4], (128, 128, 0))
          and near(colors[3.0], (0, 255, 0)), str(colors))
    with open(os.path.join(tmp, "溶接.srt"), encoding="utf-8") as fh:
        srt = fh.read()
    check("溶接：字幕對齊到重疊後的時間（第二句 5.5 → 2.3，第一句收到 2.3 為止）",
          "00:00:00,200 --> 00:00:02,300" in srt and "00:00:02,300 --> 00:00:04,600" in srt, srt)

    # ----- 4. 黑場：輸出多軌 -----
    panel.seam_combo.setCurrentIndex(panel.seam_combo.findData("fadeblack"))
    panel.seam_spin.setValue(1.0)
    check("黑場 1 秒", panel.seam_transition() == {"type": "fadeblack", "duration": 1.0}
          and "接縫用黑場" in panel.track_label.text(), panel.track_label.text())
    multi = os.path.join(tmp, "黑場.mp4")
    check("開始輸出多軌", panel.export_tracks(multi) is True and errors == [], str(errors))
    wait_until(lambda: not panel.track_exporter.busy)
    wait(100)
    check("黑場輸出多軌：片長 5.3 − 1 ＝ 4.3", abs(duration(multi) - 4.3) < 0.1 and errors == [],
          f"{duration(multi)} {errors}")
    window = [rgb(multi, 1.7 + k * 0.1) for k in range(10)]
    check("黑場：接縫那一秒裡有一格接近全黑；之前紅、之後綠",
          max(min(window, key=max)) < 25 and near(rgb(multi, 1.2), (255, 0, 0))
          and near(rgb(multi, 3.0), (0, 255, 0)), str(window))
    def corner(t):  # 右上角：白色標誌原本 1～4 秒；2.65 之後都被剪掉，剪後只剩 1～2.65
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", multi, "-frames:v", "1",
                              "-vf", "crop=40:40:500:40,scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True).stdout
        return tuple(raw[:3])
    check("黑場：標誌跟著剪（1.2 秒、接縫轉場中的 2.3 秒都在右上角；剪掉的那段沒有了，3.0 秒是綠）",
          near(corner(1.2), (255, 255, 255)) and near(corner(2.3), (255, 255, 255))
          and near(corner(3.0), (0, 255, 0)), f"{corner(1.2)} {corner(2.3)} {corner(3.0)}")
    with open(os.path.join(tmp, "黑場.srt"), encoding="utf-8") as fh:
        srt = fh.read()
    check("黑場：字幕對齊（第二句 5.5 → 1.8，第一句收到 1.8 為止）",
          "00:00:00,200 --> 00:00:01,800" in srt and "00:00:01,800 --> 00:00:04,100" in srt, srt)
    panel.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 剪點接縫的轉場測試全數通過。")
