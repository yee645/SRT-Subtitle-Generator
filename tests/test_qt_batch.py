# -*- coding: utf-8 -*-
"""
3.0 第 11 項第二十二階段：①「素材準備」的批次一鍵完成（gui_qt/batch_dialog.py）。

核心在 test_pipeline.py、test_batch_stop.py；這裡驗介面與接線。Whisper 模型下載被擋（不繞過），放假的
whisper 模組，轉寫走真的 subtitle/transcriber.py 那條路；匯出、燒錄都是真的。測試影片用 ffmpeg 產生。

1. ①「素材準備」一列有〔批次一鍵完成（多支）…〕；開小視窗（不擋住主視窗、只建一個）；②開著影片就先加進清單。
2. 清單：加入（不重複）、加入②開著的、移除選取、清空。
3. 說明：本地 Whisper 不送出去、每一支會輸出什麼（④的輸出設定）、設定在哪改。
4. 不開始的情況講原因：沒有檔案、檔案不見了、沒勾任何輸出、要燒錄但沒有 ffmpeg、文字稿對齊缺 .txt、
   OpenAI 沒金鑰；OpenAI 有金鑰：先問（寫明幾支、送聲音），不同意就不開始、什麼都沒送。
5. 跑：背景跑、控制項灰掉；一支失敗不中斷；結果清單（✔／✘、輸出的檔）、一般版同一句總結；語言照這裡選的；
   檔案真的輸出在影片旁邊。
6. 停止：做完正在跑的這一支就停，沒處理的照實列出。
7. 〔在②開啟這支〕：影片＋它剛匯出的 .srt；失敗的那支不能開；②有沒存的修改、選取消就不開。
8. 燒錄：照④勾的燒錄、檔名 `_subtitled.mp4`；文字稿對齊用各自的 .txt。
9. 跑的時候關小視窗、關主視窗都先問；全程不寫 config.json。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過①的批次一鍵完成")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import batch_dialog as bd  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import pipeline  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")
    work = os.path.join(tmp, "這週的影片")
    os.makedirs(work)

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

    def make_video(name, seconds=4):
        path = os.path.join(work, name)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=gray:size=320x180:rate=15:d={seconds}",
                        "-f", "lavfi", "-i", f"sine=frequency=150:sample_rate=22050:d={seconds}", "-c:v", "libx264",
                        "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path], check=True)
        return path

    A, B, C = make_video("第一集.mp4"), make_video("第二集.mp4"), make_video("第三集.mp4")

    # ----- 假的 whisper：轉寫走真的 transcriber 那條路 -----
    heard = {"segments": [
        {"start": 0.3, "end": 1.6, "text": "大家好歡迎收看", "words": [
            {"word": "大家好", "start": 0.3, "end": 0.9}, {"word": "歡迎收看", "start": 0.9, "end": 1.6}]},
        {"start": 2.0, "end": 3.5, "text": "今天來聊剪輯", "words": [
            {"word": "今天", "start": 2.0, "end": 2.5}, {"word": "來聊剪輯", "start": 2.5, "end": 3.5}]},
    ]}
    heard_paths = []
    fake = {"gate": None, "fail_on": ""}

    class FakeModel:
        def __init__(self, name):
            self.name = name

        def transcribe(self, path, **kwargs):
            heard_paths.append((path, kwargs.get("language")))
            if fake["gate"] is not None:
                fake["gate"].wait(30)
            if fake["fail_on"] and len(heard_paths) == fake["fail_on"]:
                raise RuntimeError("辨識失敗：測試故意的")
            return copy.deepcopy(heard)

    whisper = types.ModuleType("whisper")
    whisper.load_model = lambda name: FakeModel(name)
    sys.modules["whisper"] = whisper

    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["transcription"].update(model="small", language="auto", use_cache=False, use_api=False, api_key="")
    cfg["automation"] = {"export_srt": True, "export_vtt": True, "export_ass": False, "export_txt": False,
                         "burn_video": False, "loudnorm": False, "output_dir": ""}
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.show()
    wait(100)
    player = win.player_panel
    player._ask_discard = lambda *a, **k: "discard"
    player._ask_project_discard = lambda *a, **k: "discard"

    # ----- 1. 按鈕與小視窗 -----
    page = win.tabs.widget(0)
    check("①「素材準備」一列有〔批次一鍵完成（多支）…〕", page.isAncestorOf(win.batch_btn)
          and win.batch_btn.text() == "批次一鍵完成（多支）…" and page.isAncestorOf(win.audiovis_btn))
    check("狀態列提到批次一鍵完成", "音訊轉影片與批次一鍵完成" in win.statusBar().currentMessage(),
          win.statusBar().currentMessage())
    QTest.mouseClick(win.batch_btn, Qt.LeftButton)
    wait(50)
    dlg = win.batch_dialog
    check("開小視窗：標題、不擋住主視窗", dlg is not None and dlg.isVisible() and not dlg.isModal()
          and dlg.windowTitle() == bd.TITLE)
    check("②沒開影片：清單空的、〔加入②開著的〕灰著、〔開始批次〕灰著", dlg.files() == []
          and not dlg.add_current_btn.isEnabled() and not dlg.start_btn.isEnabled())
    check("沒有檔案：不開始、講原因", dlg.start() is False and dlg.status_label.text() == bd.NO_FILES)
    dlg.close()
    player.open_video(A)
    wait_until(lambda: player.player.duration() > 0, 20000)
    QTest.mouseClick(win.batch_btn, Qt.LeftButton)
    check("再開：同一個小視窗；②開著影片、清單空的就先加進去", win.batch_dialog is dlg and dlg.files() == [A])

    # ----- 2. 清單 -----
    dlg._ask_files = lambda: [B, A, C, B]
    QTest.mouseClick(dlg.add_btn, Qt.LeftButton)
    check("〔加入檔案…〕：照順序加、已經在的不重複", dlg.files() == [A, B, C], str(dlg.files()))
    QTest.mouseClick(dlg.add_current_btn, Qt.LeftButton)
    check("〔加入②開著的〕：已經在了就不重複", dlg.files() == [A, B, C])
    check("沒選：〔移除選取〕灰著", not dlg.remove_btn.isEnabled())
    dlg.file_list.item(1).setSelected(True)
    QTest.mouseClick(dlg.remove_btn, Qt.LeftButton)
    check("〔移除選取〕", dlg.files() == [A, C])
    QTest.mouseClick(dlg.clear_btn, Qt.LeftButton)
    check("〔清空〕", dlg.files() == [] and not dlg.clear_btn.isEnabled())
    QTest.mouseClick(dlg.add_current_btn, Qt.LeftButton)
    check("清單空的時候〔加入②開著的〕：加進來", dlg.files() == [A])
    dlg.clear_files()
    dlg.add_files([A, B, C])

    check("還沒跑：進度條藏著", not dlg.progress_bar.isVisibleTo(dlg))
    cfg["transcription"]["language"] = "en"
    other = bd.BatchDialog(player)
    check("語言初值照這次開啟的設定（en）", other.language_box.currentData() == "en")
    other.deleteLater()
    cfg["transcription"]["language"] = "auto"

    # ----- 3. 說明 -----
    text = dlg.notice.text()
    check("說明：本地 Whisper、模型 small、聲音不送出去", "這台電腦上用 Whisper（模型 small）" in text
          and "不會送出去" in text, text)
    check("說明：每一支會輸出什麼（④的輸出設定）", "每一支會輸出：" + pipeline.describe_output_plan(cfg) in text, text)
    check("說明：設定在哪改", bd.SETTINGS_NOTE in text)

    # ----- 4. 不開始的情況 -----
    gone = make_video("會刪掉.mp4", 1)
    dlg.add_files([gone])
    os.remove(gone)
    check("檔案不見了：不開始、講是哪個", dlg.start() is False and dlg.status_label.text() == "找不到這幾個檔案：" + gone)
    dlg.file_list.takeItem(3)
    cfg["automation"].update(export_srt=False, export_vtt=False)
    check("沒勾任何輸出：不開始、講一般版同一句", dlg.start() is False
          and dlg.status_label.text() == pipeline.describe_output_plan(dlg.run_config()))
    cfg["automation"].update(export_srt=True, export_vtt=True, burn_video=True)
    real_ffmpeg = bd.ffmpeg_available
    bd.ffmpeg_available = lambda: False
    try:
        check("要燒錄但沒有 ffmpeg：不開始、講原因", dlg.start() is False and dlg.status_label.text() == bd.NO_FFMPEG)
    finally:
        bd.ffmpeg_available = real_ffmpeg
    cfg["automation"]["burn_video"] = False
    with open(os.path.join(work, "第一集.txt"), "w", encoding="utf-8") as fh:
        fh.write("大家好歡迎收看\n今天來聊剪輯")
    dlg.mode_buttons["align"].setChecked(True)
    check("文字稿對齊：說明列出缺 .txt 的那幾支", "這幾支旁邊沒有同名的 .txt 講稿：第二集.mp4、第三集.mp4" in dlg.notice.text(),
          dlg.notice.text())
    check("文字稿對齊缺 .txt：不開始、講是哪幾支", dlg.start() is False
          and dlg.status_label.text().endswith("這幾支沒有：第二集.mp4、第三集.mp4"), dlg.status_label.text())
    dlg.mode_buttons["transcribe"].setChecked(True)
    cfg["transcription"]["use_api"] = True
    dlg.refresh()
    check("OpenAI 沒金鑰：說明與不開始都講", bd.NO_KEY in dlg.notice.text() and dlg.start() is False
          and dlg.status_label.text() == bd.NO_KEY)
    cfg["transcription"]["api_key"] = "sk-測試用"
    dlg.refresh()
    asked = []
    dlg._ask_send = lambda text: (asked.append(text), False)[1]
    check("OpenAI：說明寫幾支、送聲音", "會把這 3 支的影片的聲音逐支送到 OpenAI" in dlg.notice.text(), dlg.notice.text())
    check("OpenAI：先問（寫明幾支、送聲音），不同意就不開始", dlg.start() is False and len(asked) == 1
          and "這 3 支" in asked[0] and "影片的聲音" in asked[0] and dlg.status_label.text() == bd.DECLINED)
    cfg["transcription"].update(use_api=False, api_key="")
    check("到這裡什麼都沒跑、沒輸出", heard_paths == [] and sorted(f for f in os.listdir(work) if f.endswith((".srt", ".vtt")))
          == [])

    # ----- 5. 跑 -----
    dlg.refresh()
    dlg.language_box.setCurrentIndex(dlg.language_box.findData("zh"))
    fake["fail_on"] = 3
    gate = threading.Event()
    fake["gate"] = gate
    QTest.mouseClick(dlg.start_btn, Qt.LeftButton)
    wait(300)
    state = {"busy": dlg.running(), "again": dlg.start(), "progress": dlg.progress_bar.isVisibleTo(dlg),
             "enabled": [w.isEnabled() for w in (dlg.start_btn, dlg.add_btn, dlg.add_current_btn, dlg.clear_btn,
                                                 dlg.language_box, dlg.mode_buttons["align"], dlg.open_btn)],
             "stop": dlg.stop_btn.isEnabled()}
    cfg["automation"]["export_vtt"] = False  # 跑到一半改④的設定：這一批照開始時的設定
    fake["gate"] = None
    gate.set()
    wait_until(lambda: not dlg.running())
    cfg["automation"]["export_vtt"] = True
    check("按下去：背景跑、控制項灰掉、〔停止〕能按、不能再開始", state["busy"] and state["again"] is False
          and state["progress"] and not any(state["enabled"]) and state["stop"], str(state))
    check("語言照這裡選的（三支都 zh），也記進這次開啟的設定", [lang for _p, lang in heard_paths] == ["zh"] * 3
          and cfg["transcription"]["language"] == "zh", str(heard_paths))
    results = dlg.results
    check("一支失敗不中斷：前兩支成功、第三支失敗", [r["ok"] for r in results] == [True, True, False], str(results))
    check("檔案輸出在影片旁邊", all(os.path.exists(os.path.join(work, n)) for n in
                               ("第一集.srt", "第一集.vtt", "第二集.srt", "第二集.vtt"))
          and not os.path.exists(os.path.join(work, "第三集.srt")))
    tree = dlg.result_tree
    tops = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    check("結果清單：三支、✔／✘、失敗的講原因", [t.text(0) for t in tops] == ["第一集.mp4", "第二集.mp4", "第三集.mp4"]
          and tops[0].text(1) == "✔ 成功" and tops[2].text(1).startswith("✘ ") and "測試故意的" in tops[2].text(1),
          str([t.text(1) for t in tops]))
    check("成功的列出輸出的檔", [tops[0].child(i).text(0) for i in range(tops[0].childCount())]
          == ["→ 第一集.srt", "→ 第一集.vtt"] and tops[2].childCount() == 0)
    check("總結：一般版同一句", dlg.status_label.text().startswith("批次完成：成功 2、失敗 1（共 3 個檔案）。"),
          dlg.status_label.text())
    check("做完：控制項亮回來、〔停止〕灰掉、進度條收起、沒選結果時〔在②開啟這支〕灰著", dlg.start_btn.isEnabled()
          and not dlg.stop_btn.isEnabled() and not dlg.open_btn.isEnabled() and not dlg.progress_bar.isVisibleTo(dlg))

    # ----- 6. 停止 -----
    fake["fail_on"] = ""
    heard_paths.clear()
    gate = threading.Event()
    fake["gate"] = gate
    check("再跑一次", dlg.start())
    wait_until(lambda: len(heard_paths) == 1, 20000)
    QTest.mouseClick(dlg.stop_btn, Qt.LeftButton)
    dlg.worker.progress.emit(0.5, "[1/3] 第一集.mp4：正在進行智慧斷句...")
    stopping = {"stop": dlg.stop_btn.isEnabled(), "status": dlg.status_label.text()}
    fake["gate"] = None
    gate.set()
    wait_until(lambda: not dlg.running())
    check("按停止：〔停止〕灰掉、講做完這一支就停（之後的進度訊息不蓋掉它）", not stopping["stop"]
          and "這一支做完之後停" in stopping["status"],
          str(stopping))
    check("停止：只跑了正在跑的那一支，沒處理的照實列出", len(heard_paths) == 1
          and [r["ok"] for r in dlg.results] == [True, False, False]
          and [bool(r.get("skipped")) for r in dlg.results] == [False, True, True]
          and dlg.result_tree.topLevelItem(1).text(1) == "— 沒有處理（按了停止）")
    check("停止：總結講幾個沒處理（沒處理的不算失敗）", dlg.status_label.text().startswith(
        "批次完成：成功 1、失敗 0（共 3 個檔案），按了停止，其中 2 個沒有處理。"), dlg.status_label.text())
    check("再跑不覆蓋（檔名加編號）", os.path.exists(os.path.join(work, "第一集 (1).srt")))

    # ----- 7. 在②開啟 -----
    player.open_video(B)
    wait_until(lambda: player.player.duration() > 0, 20000)
    dlg.result_tree.topLevelItem(1).setSelected(True)
    check("選了沒處理的那支：〔在②開啟這支〕灰著", not dlg.open_btn.isEnabled() and dlg.open_selected() is False)
    dlg.result_tree.clearSelection()
    dlg.result_tree.topLevelItem(0).child(0).setSelected(True)
    check("選了成功那支的輸出：可以開", dlg.open_btn.isEnabled())
    player._ask_discard = lambda *a, **k: "cancel"
    player.set_generated_cues([{"start": 0.0, "end": 1.0, "text": "改過還沒存"}])
    check("②有沒存的修改、選取消：不開", dlg.open_selected() is False and "沒有開" in dlg.status_label.text()
          and player.cues[0]["text"] == "改過還沒存")
    player._ask_discard = lambda *a, **k: "discard"
    QTest.mouseClick(dlg.open_btn, Qt.LeftButton)
    wait(200)
    srt = dlg.results[0]["result"]["exports"][0]
    check("〔在②開啟這支〕：影片＋它剛匯出的 .srt", player.media_path == A and player._subtitle_path == srt
          and [c["text"] for c in player.cues] == [c["text"] for c in dlg.results[0]["result"]["cues"]]
          and dlg.status_label.text().startswith("已在②開啟：第一集.mp4"), dlg.status_label.text())

    # ----- 8. 燒錄、文字稿對齊 -----
    cfg["automation"].update(export_vtt=False, burn_video=True)
    dlg.clear_files()
    dlg.add_files([A])
    dlg.mode_buttons["align"].setChecked(True)
    heard_paths.clear()
    check("文字稿對齊＋燒錄（只有第一集，旁邊有 .txt）", dlg.start())
    wait_until(lambda: not dlg.running())
    r = dlg.results[0] if dlg.results else {"ok": False, "error": "沒有結果"}
    check("對齊成功、照④燒錄（_subtitled.mp4）", r["ok"] and r["result"]["burned"]
          and os.path.basename(r["result"]["burned"]) == "第一集_subtitled.mp4"
          and os.path.exists(r["result"]["burned"]), str(r.get("error")))
    check("對齊用的是旁邊的 .txt（字幕文字是講稿的兩句）", r["ok"] and [c["text"] for c in r["result"]["cues"]]
          == ["大家好歡迎收看", "今天來聊剪輯"], str(r["result"]["cues"] if r["ok"] else r))
    check("結果清單列出燒錄的影片", dlg.result_tree.topLevelItem(0).child(1).text(0) == "→ 第一集_subtitled.mp4")
    cfg["automation"]["burn_video"] = False
    dlg.mode_buttons["transcribe"].setChecked(True)

    real_batch = bd.pipeline.run_batch

    def broken(*a, **k):
        raise RuntimeError("批次核心壞掉了")
    bd.pipeline.run_batch = broken
    check("核心整個失敗也會開始", dlg.start())
    wait_until(lambda: not dlg.running())
    check("核心整個失敗：講原因、鈕亮回來", dlg.status_label.text().startswith("批次失敗：")
          and "批次核心壞掉了" in dlg.status_label.text() and dlg.start_btn.isEnabled(), dlg.status_label.text())
    bd.pipeline.run_batch = real_batch

    # ----- 9. 關閉 -----
    gate = threading.Event()
    fake["gate"] = gate
    closing = []
    dlg.ask_close_while_running = lambda: (closing.append(dlg.close_question()), False)[1]
    dlg.add_files([B])
    dlg.start()
    dlg.close()
    check("跑的時候關小視窗：先問，選否就不關", len(closing) == 1 and dlg.isVisible() and "批次還在跑" in closing[0]
          and "可能不完整" in closing[0])
    win.close()
    check("跑的時候關主視窗：也先問，選否就不關", len(closing) == 2 and win.isVisible())
    dlg.ask_close_while_running = lambda: (closing.append(dlg.close_question()), True)[1]
    dlg.close()
    check("選是：小視窗關掉，做完這一支就停", len(closing) == 3 and not dlg.isVisible() and dlg.worker.stopping)
    fake["gate"] = None
    gate.set()
    wait_until(lambda: not dlg.running())
    check("關掉後背景照樣收尾：只做了正在跑的第一支", [r["ok"] for r in dlg.results] == [True, False]
          and dlg.results[1].get("skipped"))
    win.close()
    check("跑完再關主視窗：不問", len(closing) == 3)
    win.show()
    wait(50)

    check("全程沒寫 config.json", not os.path.exists(config.CONFIG_PATH))
    del sys.modules["whisper"]
    player.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 ①批次一鍵完成測試全數通過。")
