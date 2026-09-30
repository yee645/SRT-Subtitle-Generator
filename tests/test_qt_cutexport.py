# -*- coding: utf-8 -*-
"""
3.0 第 5 項第三階段：播放器的「照剪點輸出…」。

剪與對齊的規則在 test_cutexport.py；這裡驗接線，用 ffmpeg 真的剪：

1. 按鈕什麼時候能按：還沒開影片、選「不顯示」、全部剪點都停用 → 不能按。
2. 一段停用、一段拖過 → 按下去：輸出中按鈕不能按、那一行寫進度；剪完長度＝保留片段
   總長；旁邊的 .srt 就是對齊後的字幕；原始影片與目前的字幕都不動；結束後按鈕回來。
3. 存檔對話框按取消 → 什麼都不做。
4. 輸出失敗（資料夾不存在、輸出蓋到原檔）→ 跳出說明、按鈕回來、那一行恢復摘要。
5. 目的地已經有同名 .srt → 先留一份 .bak（沿用 cueedit.save_cues）。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過照剪點輸出（規則本身在 test_cutexport.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import cutmarks  # noqa: E402
    from subtitle.importer import load_subtitle_file  # noqa: E402
    from subtitle.media import probe_duration  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = tmp

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

    video = os.path.join(tmp, "src.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "20",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", video], check=True)
    src_stat = (os.path.getsize(video), os.path.getmtime(video))
    cues = [{"start": 0.5, "end": 2.5, "text": "一"}, {"start": 6.0, "end": 8.0, "text": "二"},
            {"start": 9.0, "end": 10.0, "text": "三"}, {"start": 13.5, "end": 15.5, "text": "四"},
            {"start": 15.8, "end": 17.0, "text": "五"}]

    win = qt_app.MainWindow({"subtitle_style": {}})
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 800)
    win.show()
    panel = win.player_panel
    btn = panel.export_btn
    errors, asked = [], []
    panel._show_export_error = errors.append
    answer = {"path": ""}

    def fake_ask(suggested):
        asked.append(suggested)
        return answer["path"]

    panel._ask_export_path = fake_ask

    # ----- 1. 按鈕什麼時候能按 -----
    panel.set_cues(cues)
    panel.show_cut_marks("jumpcut")
    check("還沒開影片 → 不能按（不知道片長）", not btn.isEnabled())
    panel.open_video(video)
    wait_until(lambda: abs(panel.timeline.duration - 20) < 0.3)
    wait(50)
    check("開了影片、有剪點 → 可以按", btn.isEnabled() and len(panel.cut_plan["marks"]) == 2,
          str(panel.cut_plan["marks"]))
    panel.show_cut_marks("")
    check("選「不顯示」→ 不能按", not btn.isEnabled())
    panel.show_cut_marks("jumpcut")
    panel._on_cut_toggled(0, False)
    panel._on_cut_toggled(1, False)
    check("全部停用 → 不能按", not btn.isEnabled())
    check("全部停用時硬呼叫 export_cuts → 說明「沒有啟用的剪點」、不問存到哪",
          panel.export_cuts() is False and errors and "沒有啟用" in errors[-1] and not asked, str(errors))
    panel.reset_cut_marks()

    # ----- 2. 一段停用、一段拖過 → 真的輸出 -----
    panel._on_cut_toggled(0, False)  # 2.65～5.85 不剪
    second = panel.cut_plan["marks"][1]
    panel._on_cut_changed(1, second["start"], 13.0)  # 10.15～13.35 → 10.15～13.0
    expected = cutmarks.export_plan(panel.cut_plan["marks"], 20.0, panel.cues)
    answer["path"] = ""
    check("存檔對話框按取消 → 什麼都不做（建議檔名＝原檔名加「_剪輯」）",
          panel.export_cuts() is False and asked[-1] == os.path.join(tmp, "src_剪輯.mp4")
          and btn.isEnabled() and panel.last_export is None, str(asked))
    out = os.path.join(tmp, "out.mp4")
    answer["path"] = out
    labels = []
    panel.exporter.progress.connect(lambda r, m: labels.append(panel.cut_label.text()))
    before_cues = [dict(c) for c in panel.cues]
    started = panel.export_cuts()
    check("按下去 → 開始輸出、按鈕不能按、那一行寫「正在輸出」",
          started and not btn.isEnabled() and panel.cut_label.text().startswith("正在輸出"),
          panel.cut_label.text())
    panel.refresh_cut_marks()  # 輸出中別的事觸發重算，不能蓋掉進度、不能讓按鈕回來
    check("輸出中重算剪點：進度那一行不被蓋掉、按鈕仍不能按",
          panel.cut_label.text().startswith("正在輸出") and not btn.isEnabled(), panel.cut_label.text())
    wait_until(lambda: panel.last_export is not None or len(errors) > 1)
    wait(50)
    check("輸出成功", panel.last_export is not None and len(errors) == 1, str(errors))
    if panel.last_export is not None:
        got = probe_duration(out)
        check("剪完長度＝保留片段總長（停用那段沒剪、拖過的照新範圍；誤差 0.15 秒）",
              abs(got - expected["kept_seconds"]) <= 0.15 and expected["kept_seconds"] == round(20 - 2.85, 3),
              f"{got} vs {expected['kept_seconds']}")
        srt = os.path.join(tmp, "out.srt")
        saved = [(c["start"], c["end"], c["text"]) for c in load_subtitle_file(srt)["cues"]]
        check("旁邊的 out.srt＝對齊後的字幕", saved == [(c["start"], c["end"], c["text"]) for c in expected["cues"]]
              and saved[3][:2] == (10.65, 12.65), str(saved))
        check("那一行寫輸出了什麼、進度有更新過、按鈕回來",
              panel.cut_label.text() == "已輸出 out.mp4（剪掉 1 處、2.9 秒）＋out.srt"
              and any(t.startswith("正在輸出…") and t.endswith("%") for t in labels) and btn.isEnabled(),
              f"{panel.cut_label.text()} {labels[-2:]}")
        check("原始影片與目前的字幕都沒動",
              (os.path.getsize(video), os.path.getmtime(video)) == src_stat and panel.cues == before_cues)

    # ----- 4. 失敗 -----
    answer["path"] = os.path.join(tmp, "沒有這個資料夾", "x.mp4")
    panel.export_cuts()
    wait_until(lambda: len(errors) > 1)
    wait(50)
    check("資料夾不存在 → 說明「沒有輸出成功」、按鈕回來、那一行恢復摘要",
          len(errors) == 2 and errors[-1].startswith("沒有輸出成功") and btn.isEnabled()
          and panel.cut_label.text() == cutmarks.summary(panel.cut_plan), f"{errors} {panel.cut_label.text()}")
    answer["path"] = video
    panel.export_cuts()
    wait_until(lambda: len(errors) > 2)
    wait(50)
    check("輸出選到原始影片 → 擋下（說明同一個檔案）、原檔沒被蓋",
          len(errors) == 3 and "同一個" in errors[-1]
          and (os.path.getsize(video), os.path.getmtime(video)) == src_stat, str(errors[-1:]))

    # ----- 5. 目的地已有同名 .srt -----
    with open(os.path.join(tmp, "again.srt"), "w", encoding="utf-8") as fp:
        fp.write("1\n00:00:00,000 --> 00:00:01,000\n舊的\n")
    answer["path"] = os.path.join(tmp, "again.mp4")
    panel.last_export = None
    panel.export_cuts()
    wait_until(lambda: panel.last_export is not None or len(errors) > 3)
    check("同名 .srt 已存在 → 先留一份 again.srt.bak（舊內容），再寫新的",
          os.path.exists(os.path.join(tmp, "again.srt.bak"))
          and "舊的" in open(os.path.join(tmp, "again.srt.bak"), encoding="utf-8").read()
          and "舊的" not in open(os.path.join(tmp, "again.srt"), encoding="utf-8").read())
    win.close()
    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 照剪點輸出測試全數通過。")
