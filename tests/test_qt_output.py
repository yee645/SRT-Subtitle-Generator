# -*- coding: utf-8 -*-
"""
3.0 第 11 項第十三階段：④輸出與發佈（輸出設定、〔完成輸出〕、逐格式匯出）。

輸出本身跟一般版同一份（subtitle/pipeline.export_and_burn、subtitle/exporter.export）。這裡在真的視窗裡驗：

1. ④頁籤是輸出頁（不是「還沒搬」的說明）；勾選照目前的設定；頁面寫明燒在原始影片上、哪些還在一般版。
2. 「這次會輸出什麼」＝describe_output_plan，勾選一改立刻跟著變、同時寫進這次開啟的設定；
   響度正規化只有勾了燒錄才能調；輸出資料夾可以選。
3. 不輸出的情況：沒字幕、沒影片、什麼都沒勾、要燒錄但沒有 ffmpeg——都講原因、不開始。
4. 完成輸出（SRT＋ASS＋燒錄）：檔名跟著影片、放在輸出資料夾、內容＝exporter 的結果、燒錄版真的有畫面
   而且字幕那一帶跟原片不一樣；同名不覆蓋（加編號）；跑的期間按鈕停用、再按不會重跑；
   逐句校對改到一半的先套用；跑到一半改勾選不影響這一次。
5. 背景失敗：狀態列講一句、下面的框寫原因與技術細節（上次的檔案清單換掉）、按鈕恢復。
6. 單獨匯出：四種格式，內容＝exporter；沒補副檔名會補；取消不寫；沒字幕講原因；不必開影片；寫不進去講原因。
7. 燒錄中關視窗先問；沒在燒錄不問。不寫 config.json。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過④輸出頁")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import output_panel as op  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import exporter, pipeline  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")
    work = os.path.join(tmp, "素材")
    out_dir = os.path.join(tmp, "輸出")
    os.makedirs(work)
    os.makedirs(out_dir)

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

    video = os.path.join(work, "訪談 final.mp4")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0x202060:size=640x360:rate=25:d=4",
                    "-f", "lavfi", "-i", "sine=frequency=300:d=4", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-shortest", video], check=True)
    srt = os.path.join(work, "訪談.srt")
    with open(srt, "w", encoding="utf-8") as f:
        f.write("1\n00:00:00,200 --> 00:00:01,800\n大家好今天來聊剪輯\n\n"
                "2\n00:00:02,000 --> 00:00:03,600\n字幕其實很重要\n\n")

    cfg = {"automation": {"export_srt": True, "export_vtt": False, "export_ass": False, "export_txt": False,
                          "burn_video": False, "loudnorm": False, "loudnorm_target": -14.0, "output_dir": ""},
           "subtitle_style": config.load_config().get("subtitle_style")}
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.show()
    panel = win.player_panel
    out = win.output_panel
    win.tabs.setCurrentIndex(3)
    wait(50)

    # ----- 1. 頁面 -----
    check("④頁籤是輸出頁、名稱不變", win.tabs.tabText(3) == "④ 輸出與發佈" and win.tabs.widget(3) is out
          and isinstance(out, op.OutputPanel))
    check("勾選照目前的設定：只勾 SRT、沒勾燒錄", [n for n, cb in out.format_boxes.items() if cb.isChecked()] == ["srt"]
          and list(out.format_boxes) == ["srt", "vtt", "ass", "txt"] and not out.burn_box.isChecked())
    labels = " ".join(w.text() for w in out.findChildren(type(out.status_label)))
    check("頁面寫明：燒在原始影片上（剪點、素材軌不算）、不問存哪裡不覆蓋、單獨匯出會問、哪些還在一般版",
          all(w in labels for w in ("原始影片", "剪點、素材軌、轉場、畫面調整不會算進去", "同名就加編號、不覆蓋",
                                    "會另外問你要存到哪裡", "配樂助手、品牌套版、發佈資料還在一般版")))
    check("狀態列提到④的匯出與燒錄", "④的匯出與燒錄" in win.statusBar().currentMessage())
    check("開始前先套用逐句校對改到一半的", out.before_output == win.cue_panel.commit)
    check("還沒字幕：單獨匯出的鈕灰掉", not any(b.isEnabled() for b in out.export_btns.values()))

    # ----- 3a. 沒字幕、沒影片 -----
    check("沒字幕：不開始、講原因", out.finish_output() is False and out.status_label.text() == op.NO_CUES)
    panel.load_subtitles(srt)
    wait(100)
    check("載了字幕：上方對象跟著更新、單獨匯出的鈕可以按", "字幕：2 句" in out.target_label.text()
          and all(b.isEnabled() for b in out.export_btns.values()), out.target_label.text())
    check("沒影片：不開始、講原因（單獨匯出可以用）", out.finish_output() is False
          and out.status_label.text() == op.NO_MEDIA and "單獨匯出" in op.NO_MEDIA)

    # ----- 6a. 不必開影片就能單獨匯出 -----
    check("沒開影片：預設檔名跟著載入的字幕檔", out.default_export_name("vtt") == os.path.join(work, "訪談.vtt"))
    cues_now = [dict(c) for c in panel.cues]
    path = out.export_single("vtt", os.path.join(out_dir, "單獨.vtt"))
    check("沒開影片：單獨匯出 VTT，內容＝exporter", path == os.path.join(out_dir, "單獨.vtt")
          and open(path, encoding="utf-8").read() == exporter.cues_to_vtt(cues_now)
          and out.status_label.text() == f"已匯出：{path}")

    panel.open_video(video)
    wait_until(lambda: panel.player.duration() > 0, 10000)
    win.tabs.setCurrentIndex(1)
    win.tabs.setCurrentIndex(3)
    wait(50)
    check("切回這頁：上方寫出影片檔名", "訪談 final.mp4" in out.target_label.text(), out.target_label.text())

    # ----- 2. 這次會輸出什麼 -----
    check("那句話＝describe_output_plan（放在影片旁邊）",
          out.plan_label.text() == "這次會輸出：" + pipeline.describe_output_plan(cfg, video)
          and work in out.plan_label.text() and "匯出 SRT" in out.plan_label.text(), out.plan_label.text())
    check("沒勾燒錄：響度正規化不能調", not out.loudnorm_box.isEnabled() and not out.loudnorm_spin.isEnabled())
    out.format_boxes["ass"].setChecked(True)
    check("勾 ASS：那句話立刻變、設定跟著記", "匯出 SRT、ASS" in out.plan_label.text() and cfg["automation"]["export_ass"] is True,
          out.plan_label.text())
    out.burn_box.setChecked(True)
    check("勾燒錄：那句話加上燒錄、可以勾響度正規化（目標要勾了才能調）", "燒錄硬字幕影片" in out.plan_label.text()
          and cfg["automation"]["burn_video"] is True and out.loudnorm_box.isEnabled()
          and not out.loudnorm_spin.isEnabled())
    out.loudnorm_box.setChecked(True)
    out.loudnorm_spin.setValue(-16.0)
    check("勾響度正規化、目標 -16：那句話寫出來、設定跟著記", "響度正規化 -16.0 LUFS" in out.plan_label.text()
          and cfg["automation"]["loudnorm"] is True and cfg["automation"]["loudnorm_target"] == -16.0,
          out.plan_label.text())
    check("目標的範圍跟一般版一樣（-30～-8）", out.loudnorm_spin.minimum() == -30.0 and out.loudnorm_spin.maximum() == -8.0)
    out.loudnorm_box.setChecked(False)
    real_dir = QFileDialog.getExistingDirectory
    try:
        QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
        QTest.mouseClick(out.dir_btn, Qt.LeftButton)
        check("選資料夾按取消：不變", out.dir_edit.text() == "" and cfg["automation"]["output_dir"] == "")
        QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: out_dir)
        QTest.mouseClick(out.dir_btn, Qt.LeftButton)
        check("選了輸出資料夾：欄位、設定、那句話都換", out.dir_edit.text() == out_dir
              and cfg["automation"]["output_dir"] == out_dir and out.plan_label.text().endswith("→ " + out_dir),
              out.plan_label.text())
    finally:
        QFileDialog.getExistingDirectory = real_dir

    # ----- 3b. 什麼都沒勾、沒有 ffmpeg -----
    saved = {n: cb.isChecked() for n, cb in out.format_boxes.items()}
    for cb in out.format_boxes.values():
        cb.setChecked(False)
    out.burn_box.setChecked(False)
    check("什麼都沒勾：不開始、講一般版那句", out.finish_output() is False
          and out.status_label.text().startswith("尚未勾選任何輸出") and not out.busy())
    for n, cb in out.format_boxes.items():
        cb.setChecked(saved[n])
    out.burn_box.setChecked(True)
    real_ff = op.ffmpeg_available
    op.ffmpeg_available = lambda: False
    try:
        check("要燒錄但沒有 ffmpeg：不開始、講原因", out.finish_output() is False
              and out.status_label.text() == op.NO_FFMPEG and not out.busy())
    finally:
        op.ffmpeg_available = real_ff

    # ----- 4. 完成輸出 -----
    existing = os.path.join(out_dir, "訪談 final.srt")
    with open(existing, "w", encoding="utf-8") as f:
        f.write("舊檔")
    win.tabs.setCurrentIndex(1)
    row = win.cue_panel
    row.select_row(0) if hasattr(row, "select_row") else row.table.selectRow(0)
    wait(50)
    row.editor.setPlainText("大家好，改過的第一句")  # 改到一半、還沒套用
    win.tabs.setCurrentIndex(3)
    wait(50)
    QTest.mouseClick(out.finish_btn, Qt.LeftButton)
    check("按下去：開始了、按鈕停用寫輸出中、進度條出現、說燒錄不能停", out.busy() and out.burning()
          and not out.finish_btn.isEnabled() and out.finish_btn.text() == "輸出中…"
          and out.progress_bar.isVisible() and "不能停" in out.status_label.text()
          and not out.burn_box.isEnabled() and not any(b.isEnabled() for b in out.export_btns.values()))
    check("逐句校對改到一半的先套用了", panel.cues[0]["text"] == "大家好，改過的第一句", panel.cues[0]["text"])
    check("跑的期間再按：不會重跑", out.finish_output() is False)
    check("跑的期間單獨匯出：不做", out.export_single("srt", os.path.join(out_dir, "不該有.srt")) == ""
          and not os.path.exists(os.path.join(out_dir, "不該有.srt")))
    cfg["automation"]["export_txt"] = True  # 跑到一半設定被改：不影響這一次
    final_cues = [dict(c) for c in panel.cues]
    check("跑完", wait_until(lambda: not out.busy()))
    cfg["automation"]["export_txt"] = False
    new_srt = os.path.join(out_dir, "訪談 final (1).srt")
    ass = os.path.join(out_dir, "訪談 final.ass")
    burned = os.path.join(out_dir, "訪談 final_subtitled.mp4")
    check("產生的檔案：SRT（同名加編號）、ASS、燒錄版；沒有 TXT", out.last_outputs == [new_srt, ass, burned]
          and all(os.path.exists(p) for p in out.last_outputs)
          and not os.path.exists(os.path.join(out_dir, "訪談 final.txt")), str(out.last_outputs))
    check("舊檔沒被覆蓋", open(existing, encoding="utf-8").read() == "舊檔")
    check("SRT 內容＝exporter（含剛套用的那句）", open(new_srt, encoding="utf-8").read() == exporter.cues_to_srt(final_cues)
          and "改過的第一句" in open(new_srt, encoding="utf-8").read())
    check("ASS 內容＝exporter（帶目前的字幕樣式）",
          open(ass, encoding="utf-8").read() == exporter.cues_to_ass(final_cues, cfg["subtitle_style"]))
    check("狀態列與清單：講產生幾個檔、逐一列出", out.status_label.text() == "完成輸出：訪談 final.mp4 共產生 3 個檔案。"
          and out.result_box.toPlainText() == "\n".join(f"→ {p}" for p in out.last_outputs))
    check("跑完：按鈕恢復、進度條收起來", out.finish_btn.isEnabled() and out.finish_btn.text() == "完成輸出（依輸出設定）"
          and not out.progress_bar.isVisible() and out.burn_box.isEnabled())

    def frame_bytes(path, seconds):
        return subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(seconds), "-i", path, "-frames:v", "1",
                               "-vf", "crop=iw:ih/3:0:ih*2/3", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                              capture_output=True, check=True).stdout

    plain, with_sub, between = frame_bytes(video, 1.0), frame_bytes(burned, 1.0), frame_bytes(burned, 1.9)
    # 下方三分之一、原尺寸逐點比：差超過 60 階的點數（字是白的、底是深藍，壓縮雜訊到不了這麼多）
    diff = sum(1 for a, b in zip(plain, with_sub) if abs(a - b) > 60)
    gap = sum(1 for a, b in zip(plain, between) if abs(a - b) > 60)
    check("燒錄版：有字幕的時間下方多了字（至少 80 個亮點）、沒字幕的時間跟原片一樣",
          len(with_sub) == 640 * 120 and diff >= 80 and gap == 0, f"diff={diff} gap={gap}")
    check("原片沒被動", os.path.getsize(video) > 0 and frame_bytes(video, 1.0) == plain)

    # ----- 5. 背景失敗 -----
    real_run = pipeline.export_and_burn

    def boom(*a, **k):
        raise OSError("磁碟滿了")

    pipeline.export_and_burn = boom
    try:
        check("背景失敗：開始了", out.finish_output() is True)
        check("背景失敗：講原因、按鈕恢復", wait_until(lambda: not out.busy())
              and out.status_label.text().startswith("輸出失敗：") and "磁碟滿了" in out.result_box.toPlainText()
              and "技術細節" in out.result_box.toPlainText() and "→" not in out.result_box.toPlainText()
              and out.finish_btn.isEnabled() and not out.progress_bar.isVisible(), out.status_label.text())
    finally:
        pipeline.export_and_burn = real_run

    # ----- 6b. 單獨匯出 -----
    check("開了影片：預設檔名跟著影片", out.default_export_name("ass") == os.path.join(work, "訪談 final.ass"))
    asked = []
    real_save = QFileDialog.getSaveFileName
    try:
        for name, build in (("srt", exporter.cues_to_srt), ("vtt", exporter.cues_to_vtt), ("txt", exporter.cues_to_txt),
                            ("ass", lambda c: exporter.cues_to_ass(c, cfg["subtitle_style"]))):
            target = os.path.join(out_dir, f"另存_{name}")  # 故意不寫副檔名
            QFileDialog.getSaveFileName = staticmethod(
                lambda *a, _t=target, **k: (asked.append(a), (_t, ""))[1])
            QTest.mouseClick(out.export_btns[name], Qt.LeftButton)
            written = target + f".{name}"
            check(f"單獨匯出 {name.upper()}：開存檔視窗、補副檔名、內容＝exporter", os.path.exists(written)
                  and open(written, encoding="utf-8").read() == build(final_cues)
                  and out.status_label.text() == f"已匯出：{written}", out.status_label.text())
        check("存檔視窗：預設檔名跟著影片、只列那一種格式", len(asked) == 4
              and asked[0][2] == os.path.join(work, "訪談 final.srt") and "*.srt" in asked[0][3]
              and "*.ass" in asked[3][3], str([a[2:] for a in asked]))
        before = sorted(os.listdir(out_dir))
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
        out.status_label.setText("")
        QTest.mouseClick(out.export_btns["srt"], Qt.LeftButton)
        check("存檔視窗按取消：什麼都不寫", sorted(os.listdir(out_dir)) == before and out.status_label.text() == "")
    finally:
        QFileDialog.getSaveFileName = real_save
    bad = os.path.join(out_dir, "沒有這個資料夾", "a.srt")
    check("寫不進去：講原因", out.export_single("srt", bad) == "" and out.status_label.text().startswith("匯出失敗："))

    # ----- 7. 關視窗 -----
    panel._ask_discard = lambda: "discard"  # 之後關視窗不要卡在「字幕改過還沒存」的詢問
    panel._ask_project_discard = lambda: "discard"
    check("沒在燒錄：關視窗不問", not out.burning())
    real_q = QMessageBox.question
    asked_close = []
    try:
        QMessageBox.question = staticmethod(lambda *a, **k: (asked_close.append(a[2]), QMessageBox.Yes)[1])
        out.worker.busy, out.worker.burning = True, True
        check("燒錄中：問要不要等，選「等」＝不關", out.ask_close_while_burning() is False
              and asked_close == [op.CLOSE_QUESTION] and "不完整" in op.CLOSE_QUESTION)
        ignored = []

        class Ev:
            def ignore(self):
                ignored.append(1)

            def accept(self):
                ignored.append(0)

        win.closeEvent(Ev())
        check("主視窗關閉時真的會問、選「等」就不關", ignored == [1] and len(asked_close) == 2)
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
        check("選「不等」＝照樣關", out.ask_close_while_burning() is True)
        out.worker.burning = False
        check("只匯出字幕檔（沒燒錄）：不算燒錄中", out.busy() and not out.burning())
    finally:
        QMessageBox.question = real_q
        out.worker.busy = out.worker.burning = False
    check("設定記在這次開啟的設定、沒寫 config.json", cfg["automation"]["output_dir"] == out_dir
          and not os.path.exists(config.CONFIG_PATH))

    panel._ask_discard = lambda: "discard"
    panel._ask_project_discard = lambda: "discard"
    panel.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 ④輸出頁測試全數通過。")
