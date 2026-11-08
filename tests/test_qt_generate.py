# -*- coding: utf-8 -*-
"""
3.0 第 11 項第六階段：播放列的「生成字幕…」（gui_qt/generate_dialog.py）。

核心在 test_generate.py；這裡驗介面。Whisper 模型下載被擋（不繞過），放假的 whisper 模組，
轉寫走真的 subtitle/transcriber.py 程式內那條路。

1. 按鈕：沒開影片灰掉；開了可以按。
2. 打開：寫明在這台電腦上辨識、聲音不送出；語言照設定；沒有字幕時不寫「會換掉」。
3. 生成：選英文、按開始——Whisper 拿到 en；視窗關掉、清單與播放器上有字幕；狀態列寫「新增 N 句，
   尚未存檔」；逐句校對下面寫生成完成；選的語言只記在這次開啟的設定裡，不寫 config.json。
4. 存字幕：建議檔名跟影片同名（.srt）。
5. 有還沒存的修改再生成：先問；取消就不開始、字幕不動。寫明「會換掉目前的 N 句」。
6. 取消：Whisper 跑到一半按取消——寫明背景跑完才停、停之前不能再開始；跑完結果不套用。
   關掉視窗＝取消。
7. 失敗：寫原因與解法，字幕沒有改。
8. OpenAI 模式：沒金鑰不能按開始；有金鑰寫明送聲音、照用量收費。
9. 文字稿對齊：影片旁同名 .txt 自動帶入；講稿清空就不能按開始；講稿當提示詞送給 Whisper。
"""
import copy
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import types

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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過生成字幕的介面（核心在 test_generate.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import generate_dialog as gd  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = tmp
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

    work = os.path.join(tmp, "我的影片")
    os.makedirs(work)
    main = os.path.join(work, "訪談.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:size=640x360:rate=30:d=8",
                    "-f", "lavfi", "-i", "sine=frequency=150:sample_rate=48000:d=8", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", main], check=True)

    # ----- 假的 whisper：轉寫走真的 transcriber 程式內那條路 -----
    calls = []
    heard = {"segments": [
        {"start": 0.5, "end": 2.6, "text": "大家好今天聊剪輯", "words": [
            {"word": "大家好", "start": 0.5, "end": 1.2}, {"word": "今天", "start": 1.2, "end": 1.7},
            {"word": "聊剪輯", "start": 1.7, "end": 2.6}]},
        {"start": 4.0, "end": 6.0, "text": "先講為什麼要字幕", "words": [
            {"word": "先講", "start": 4.0, "end": 4.5}, {"word": "為什麼", "start": 4.5, "end": 5.2},
            {"word": "要字幕", "start": 5.2, "end": 6.0}]},
    ]}
    fake = {"gate": None, "fail": None}

    class FakeModel:
        def __init__(self, name):
            self.name = name

        def transcribe(self, path, **kwargs):
            calls.append((self.name, path, kwargs))
            if fake["gate"] is not None:
                fake["gate"].wait(20)
            return copy.deepcopy(heard)

    def load_model(name):
        if fake["fail"]:
            raise RuntimeError(fake["fail"])
        return FakeModel(name)

    whisper = types.ModuleType("whisper")
    whisper.load_model = load_model
    sys.modules["whisper"] = whisper

    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["transcription"].update(model="small", language="auto", use_cache=False)
    win = qt_app.MainWindow(cfg)
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 800)
    win.show()
    wait(200)
    panel, cp = win.player_panel, win.cue_panel

    # ----- 1. 按鈕 -----
    check("沒開影片：「生成字幕…」灰掉、在播放列上看得到", panel.generate_btn.isVisible()
          and not panel.generate_btn.isEnabled() and panel.open_generate() is None)
    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0)
    check("開了影片：可以按", panel.generate_btn.isEnabled())

    # ----- 2. 打開 -----
    QTest.mouseClick(panel.generate_btn, Qt.LeftButton)
    wait(100)
    dlg = panel.generate_dialog
    check("打開：擋住這個視窗（生成時字幕不能改）", dlg is not None and dlg.isVisible()
          and dlg.windowModality() == Qt.WindowModal)
    check("寫明在這台電腦上辨識、聲音不送出、模型 small", "這台電腦上用 Whisper（模型 small）" in dlg.notice.text()
          and "聲音不會送出去" in dlg.notice.text(), dlg.notice.text())
    check("沒有字幕：不寫會換掉", "會換掉" not in dlg.notice.text())
    check("語言照設定（自動偵測）、做法預設語音轉寫、講稿欄藏起來", dlg.language_box.currentData() == "auto"
          and dlg.mode() == "transcribe" and not dlg.transcript_edit.isVisible() and dlg.start_btn.isEnabled())

    # ----- 3. 生成 -----
    dlg.language_box.setCurrentIndex(dlg.language_box.findData("en"))
    QTest.mouseClick(dlg.start_btn, Qt.LeftButton)
    check("生成完：視窗關掉", wait_until(lambda: not dlg.isVisible() and not dlg.worker.busy))
    check("Whisper 拿到選的英文、模型照設定", calls and calls[-1][0] == "small" and calls[-1][1] == main
          and calls[-1][2].get("language") == "en", str(calls))
    texts = "".join(c["text"] for c in panel.cues).replace("\n", "")
    check("清單與播放器上有生成的字幕", len(panel.cues) >= 2 and "聊剪輯" in texts and "要字幕" in texts
          and cp.table.rowCount() == len(panel.cues), str(panel.cues))
    panel.player.setPosition(1000)
    wait_until(lambda: panel.player.position() == 1000, 5000)
    wait(150)
    check("播放器上那一刻的字幕是生成的", "大家好" in panel.current_subtitle_text(), panel.current_subtitle_text())
    check("狀態列：新增 N 句、尚未存檔（還沒有字幕檔）", f"新增 {len(panel.cues)} 句" in panel.info_label.text()
          and "尚未存檔" in panel.info_label.text() and "（目前的字幕）" in panel.info_label.text(),
          panel.info_label.text())
    check("逐句校對下面寫生成完成、提醒存字幕", f"生成完成，共 {len(panel.cues)} 句" in cp.note.text()
          and "存字幕" in cp.note.text(), cp.note.text())
    check("選的語言只記在這次開啟的設定裡、沒寫 config.json", cfg["transcription"]["language"] == "en"
          and not os.path.exists(config.CONFIG_PATH))
    check("不能用 Ctrl+Z 退回到生成前（生成是重新開始）", not panel.history.can_undo())

    # ----- 4. 存字幕 -----
    suggested = []
    srt = os.path.join(work, "訪談.srt")
    panel._ask_save_path = lambda s: suggested.append(s) or srt
    check("存字幕：建議跟影片同名、存了就不算沒存", panel.save() is True and suggested
          and os.path.splitext(suggested[0])[0] == os.path.splitext(main)[0] and os.path.isfile(srt)
          and panel.unsaved_changes() == 0, str(suggested))

    # ----- 5. 有還沒存的修改再生成 -----
    panel.set_cue_text(0, "改過的第一句")
    dlg = panel.open_generate()
    check("再打開：寫明會換掉目前的 N 句；語言是剛剛選的", f"會換掉目前的 {len(panel.cues)} 句" in dlg.notice.text()
          and dlg.language_box.currentData() == "en", dlg.notice.text())
    asked = []
    panel._ask_discard = lambda: asked.append("字幕") or "cancel"
    count = len(calls)
    check("有沒存的修改：先問；取消就不開始、字幕不動", dlg.start() is False and asked == ["字幕"]
          and len(calls) == count and panel.cues[0]["text"] == "改過的第一句" and "沒有開始" in dlg.status.text())

    # ----- 6. 取消 -----
    fake["gate"] = threading.Event()
    panel._ask_discard = lambda: "discard"
    check("選放棄修改：開始", dlg.start() is True and dlg.worker.busy)
    wait_until(lambda: len(calls) > count, 5000)
    check("跑的時候：開始灰掉、取消可以按、語言與做法不能改", not dlg.start_btn.isEnabled()
          and dlg.cancel_btn.isEnabled() and not dlg.language_box.isEnabled())
    QTest.mouseClick(dlg.cancel_btn, Qt.LeftButton)
    check("按取消：寫明背景跑完才停、停之前不能再開始", "背景跑完才停" in dlg.status.text()
          and not dlg.start_btn.isEnabled() and not dlg.cancel_btn.isEnabled() and dlg.start() is False)
    fake["gate"].set()
    check("背景跑完：結果不套用、字幕沒有改", wait_until(lambda: not dlg.worker.busy, 10000)
          and wait_until(lambda: "已取消，字幕沒有改" in dlg.status.text(), 5000)
          and panel.cues[0]["text"] == "改過的第一句" and dlg.start_btn.isEnabled(), dlg.status.text())
    fake["gate"] = threading.Event()
    panel.set_cue_text(0, "大家好今天聊剪輯")
    panel.save()
    count = len(calls)
    dlg.start()
    wait_until(lambda: len(calls) > count, 5000)
    dlg.close()
    check("跑到一半關掉視窗＝取消", dlg.worker.cancelling)
    fake["gate"].set()
    wait_until(lambda: not dlg.worker.busy, 10000)
    wait(100)
    check("關掉後跑完：字幕沒有改", panel.cues[0]["text"] == "大家好今天聊剪輯" and panel.unsaved_changes() == 0)
    fake["gate"] = None

    # ----- 7. 失敗 -----
    fake["fail"] = "CUDA out of memory"
    dlg = panel.open_generate()
    before = [dict(c) for c in panel.cues]
    dlg.start()
    check("失敗：寫生成失敗與原因，字幕沒有改", wait_until(lambda: "生成失敗，字幕沒有改" in dlg.status.text(), 10000)
          and "原因：" in dlg.status.text() and panel.cues == before and dlg.start_btn.isEnabled()
          and dlg.isVisible(), dlg.status.text())
    fake["fail"] = None
    dlg.close()

    # ----- 8. OpenAI 模式 -----
    cfg["transcription"].update(use_api=True, api_key="")
    dlg = panel.open_generate()
    check("OpenAI 沒金鑰：不能按開始、說去哪裡填", not dlg.start_btn.isEnabled() and gd.NO_KEY in dlg.notice.text())
    cfg["transcription"]["api_key"] = "sk-test"
    dlg.prepare()
    check("OpenAI 有金鑰：寫明送聲音、照用量收費", dlg.start_btn.isEnabled()
          and "會把影片的聲音送到 OpenAI" in dlg.notice.text() and "照用量收費" in dlg.notice.text()
          and "不會送出去" not in dlg.notice.text(), dlg.notice.text())
    cfg["transcription"].update(use_api=False, api_key="")
    dlg.close()

    # ----- 9. 文字稿對齊 -----
    script = "大家好今天聊剪輯\n先講為什麼要字幕\n"
    with open(os.path.join(work, "訪談.txt"), "w", encoding="utf-8") as fh:
        fh.write(script)
    dlg = panel.open_generate()
    dlg.mode_buttons["align"].setChecked(True)
    check("文字稿對齊：影片旁的 .txt 自動帶入、講稿欄出現", dlg.transcript_edit.isVisible()
          and dlg.transcript_edit.toPlainText() == script and "訪談.txt" in dlg.transcript_note.text())
    dlg.transcript_edit.setPlainText("   ")
    check("講稿清空：不能按開始", not dlg.start_btn.isEnabled())
    dlg.transcript_edit.setPlainText(script)
    count = len(calls)
    dlg.start()
    check("對齊完：視窗關掉、講稿當提示詞送給 Whisper、字幕照講稿",
          wait_until(lambda: not dlg.isVisible() and not dlg.worker.busy)
          and len(calls) == count + 1 and "要字幕" in calls[-1][2].get("initial_prompt", "")
          and "".join(c["text"] for c in panel.cues).replace("\n", "").replace(" ", "")
          == script.replace("\n", ""), str(panel.cues))

    panel._ask_discard = lambda: "discard"
    panel._ask_project_discard = lambda: "discard"
    panel.shutdown()
    win.close()
    del sys.modules["whisper"]

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 生成字幕介面測試全數通過。")
