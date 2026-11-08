# -*- coding: utf-8 -*-
"""
3.0 第 11 項第七階段：「翻譯字幕」視窗裡的多語字幕包（gui_qt/translate_dialog.py）。

翻譯與存檔走一般版、CLI 同一段（subtitle/multilang.write_language_pack）；openai 用替身（照真的 SDK
的呼叫形狀，可以指定某個語言卡住或出錯）。QTest 真的點：

1. 說明：每個語言送幾句（重複的只送一次）、幾個字、幾個語言；跟原文同一種的略過；沒金鑰不能按。
2. 輸出：問資料夾（取消就不送）；每個語言一個單語 .srt（影片.en.srt），讀得回來、時間不變；
   重複的句子只送一次；目前的字幕不改；視窗留著、寫存好哪幾個；只記在這次開啟的設定裡。
3. 已經有同名的檔：先問；不蓋就什麼都不送。
4. 某個語言失敗：寫哪個失敗，其他照樣存。
5. 停止：英文存好、日文翻到一半按停止——英文的檔留著、日文沒存，寫明存了哪個、哪個沒做。
   跑的時候「開始翻譯」與「輸出多語字幕包」都灰掉。關掉視窗＝停止。
"""
import json
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過多語字幕包的介面（核心在 test_v1430.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    # ---- 替身 openai：照真的 SDK 的呼叫形狀；譯文前面加 [語言]；可以讓某個語言卡住或出錯 ----
    calls = []
    behaviour = {"fail": "", "block": ""}
    gate = threading.Event()
    gate.set()
    entered = threading.Event()

    class _Completions:
        def create(self, model=None, messages=None):
            batch = json.loads(messages[-1]["content"])
            system = messages[0]["content"]
            language = system.split(" into ", 1)[1].split(".", 1)[0]
            calls.append({"batch": batch, "language": language})
            if behaviour["block"] and behaviour["block"] == language:
                entered.set()
                gate.wait(20)
            if behaviour["fail"] and behaviour["fail"] == language:
                raise ConnectionError("連不上 api.openai.com")
            content = json.dumps([f"[{language}]{t}" for t in batch], ensure_ascii=False)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content=content))])

    class _OpenAI:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.chat = types.SimpleNamespace(completions=_Completions())

    fake = types.ModuleType("openai")
    fake.OpenAI = _OpenAI
    sys.modules["openai"] = fake

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle.importer import load_subtitle_file  # noqa: E402
    from subtitle.translator import LANGUAGE_LABELS  # noqa: E402

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

    main = os.path.join(tmp, "訪談.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:size=640x360:rate=30:d=8",
                    "-f", "lavfi", "-i", "sine=frequency=150:sample_rate=48000:d=8", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", main], check=True)

    # 7 句、6 句不重複；一批最少 5 句（translator 的下限），所以每個語言分兩批送
    original = [{"start": 0.5, "end": 1.5, "text": "大家好"}, {"start": 2.0, "end": 2.5, "text": "對"},
                {"start": 3.0, "end": 4.5, "text": "上面一行\n下面"}, {"start": 5.0, "end": 5.5, "text": "對"},
                {"start": 6.0, "end": 6.4, "text": "第五句"}, {"start": 6.5, "end": 6.9, "text": "第六句"},
                {"start": 7.0, "end": 7.5, "text": "第七句"}]
    unique = ["大家好", "對", "上面一行\n下面", "第五句", "第六句", "第七句"]
    cfg = {"subtitle_style": {}, "transcription": {"language": "ja", "api_key": ""},
           "translate": {"batch_size": 5}}
    win = qt_app.MainWindow(cfg)
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 800)
    win.show()
    wait(200)
    panel, cp = win.player_panel, win.cue_panel
    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0)
    panel.set_cues(original)
    EN, JA = LANGUAGE_LABELS["en"], LANGUAGE_LABELS["ja"]

    def folder(name):
        path = os.path.join(tmp, name)
        os.makedirs(path, exist_ok=True)
        return path

    # ----- 1. 說明 -----
    dlg = cp.open_translate()
    wait(100)
    check("沒金鑰：「輸出多語字幕包…」灰掉", not dlg.pack_btn.isEnabled() and dlg.pack_btn.isVisible())
    cfg["transcription"]["api_key"] = "sk-test"
    dlg.pack_edit.setText("en, ja, EN")
    check("跟原文（日文）同一種的略過、重複的去掉：只剩英文", dlg.pack_languages() == ["en"], str(dlg.pack_languages()))
    dlg.pack_edit.setText("en,ko")
    note = dlg.pack_note.text()
    check("說明：6 句（重複的只送一次）、約 19 個字、2 個語言、檔名、字幕不改", "6 句字幕的文字（約 19 個字）" in note
          and "2 個語言（英文、韓文）" in note and "一共約 38 個字" in note and "訪談.en.srt" in note
          and "目前的字幕不會改" in note and dlg.pack_btn.isEnabled(), note)
    dlg.pack_dedupe.setChecked(False)
    check("不去重：7 句、20 個字", "7 句字幕的文字（約 20 個字）" in dlg.pack_note.text(), dlg.pack_note.text())
    dlg.pack_dedupe.setChecked(True)
    dlg.pack_edit.setText("ja")
    check("只填原文的語言：說要填語言代碼、不能按", not dlg.pack_btn.isEnabled() and "填語言代碼" in dlg.pack_note.text())

    # ----- 2. 輸出 -----
    dlg.pack_edit.setText("en,ko")
    dlg._ask_folder = lambda: ""
    check("問資料夾按取消：不送", dlg.start_pack() is False and calls == [])
    out = folder("輸出一")
    dlg._ask_folder = lambda: out
    QTest.mouseClick(dlg.pack_btn, Qt.LeftButton)
    check("跑的時候：開始翻譯與輸出多語字幕包都灰掉、停止可以按", dlg.busy() and not dlg.start_btn.isEnabled()
          and not dlg.pack_btn.isEnabled() and dlg.stop_btn.isEnabled())
    check("跑完", wait_until(lambda: not dlg.busy() and dlg.last_pack is not None))
    en_file, ko_file = os.path.join(out, "訪談.en.srt"), os.path.join(out, "訪談.ko.srt")
    en = load_subtitle_file(en_file)["cues"] if os.path.exists(en_file) else []
    check("每個語言一個單語 .srt、時間不變", os.path.exists(ko_file) and [c["text"] for c in en]
          == [f"[{EN}]{c['text']}" for c in original]
          and [c["start"] for c in en] == [c["start"] for c in original], str(en))
    en_batches = [c["batch"] for c in calls if c["language"] == EN]
    check("重複的句子只送一次（每個語言 6 句、分兩批 5＋1）", len(calls) == 4
          and en_batches == [unique[:5], unique[5:]], str(calls))
    check("目前的字幕不改", panel.cues == original)
    check("視窗留著、寫存好哪幾個與資料夾", dlg.isVisible() and "多語字幕包完成：2 個語言都存好了" in dlg.status.text()
          and "訪談.en.srt、訪談.ko.srt" in dlg.status.text() and out in dlg.status.text(), dlg.status.text())
    check("只記在這次開啟的設定裡、沒寫 config.json", cfg["multilang"]["languages"] == "en,ko"
          and cfg["multilang"]["dedupe"] is True and not os.path.exists(config.CONFIG_PATH))

    # ----- 3. 已經有同名的檔 -----
    asked = []
    dlg._ask_overwrite = lambda names: asked.append(list(names)) or False
    count = len(calls)
    check("已經有同名的檔：先問、不蓋就不送", dlg.start_pack() is False and asked == [["訪談.en.srt", "訪談.ko.srt"]]
          and len(calls) == count and "沒有輸出" in dlg.status.text(), str(asked))

    # ----- 4. 某個語言失敗 -----
    out2 = folder("輸出二")
    dlg._ask_folder = lambda: out2
    behaviour["fail"] = JA
    dlg.pack_edit.setText("en,ja,ko")
    cfg["transcription"]["language"] = "zh"
    check("開始（日文會失敗）", dlg.start_pack() is True)
    wait_until(lambda: not dlg.busy())
    wait(100)
    check("日文失敗：寫出來；英文、韓文照樣存", f"{JA}失敗" in dlg.status.text()
          and "其他語言不受影響" in dlg.status.text() and os.path.exists(os.path.join(out2, "訪談.en.srt"))
          and os.path.exists(os.path.join(out2, "訪談.ko.srt"))
          and not os.path.exists(os.path.join(out2, "訪談.ja.srt")), dlg.status.text())
    behaviour["fail"] = ""

    # ----- 5. 停止 -----
    out3 = folder("輸出三")
    dlg._ask_folder = lambda: out3
    dlg.pack_edit.setText("en,ja")
    behaviour["block"] = JA
    gate.clear()
    entered.clear()
    dlg.start_pack()
    check("英文翻完、日文卡在第一批", entered.wait(20) and os.path.exists(os.path.join(out3, "訪談.en.srt")))
    check("多語字幕包跑的時候：直接叫「開始翻譯」也不會開始", dlg.start() is False and not dlg.worker.busy)
    QTest.mouseClick(dlg.stop_btn, Qt.LeftButton)
    check("按停止：寫停止中、已經存好的留著", "停止中" in dlg.status.text() and "已經存好的語言照樣留著" in dlg.status.text()
          and not dlg.stop_btn.isEnabled())
    count = len(calls)
    gate.set()
    wait_until(lambda: not dlg.busy())
    wait(100)
    check("停了：英文的檔留著、日文沒存，寫明存了哪個、哪個沒做", "已停止" in dlg.status.text()
          and "訪談.en.srt" in dlg.status.text() and f"沒做：{JA}" in dlg.status.text()
          and os.path.exists(os.path.join(out3, "訪談.en.srt"))
          and not os.path.exists(os.path.join(out3, "訪談.ja.srt")), dlg.status.text())
    check("停了之後日文剩下的批次沒有再送", len(calls) == count, f"{count} → {len(calls)}")
    check("停完：按鈕回來", dlg.pack_btn.isEnabled() and dlg.start_btn.isEnabled())

    out4 = folder("輸出四")
    dlg._ask_folder = lambda: out4
    gate.clear()
    entered.clear()
    dlg.start_pack()
    entered.wait(20)
    dlg.close()
    check("跑到一半關掉視窗＝停止", dlg.pack_worker._stop.is_set())
    gate.set()
    wait_until(lambda: not dlg.busy())
    wait(100)
    check("關掉之後：日文沒存", not os.path.exists(os.path.join(out4, "訪談.ja.srt")))
    behaviour["block"] = ""

    panel._ask_discard = lambda: "discard"
    panel._ask_project_discard = lambda: "discard"
    panel.shutdown()
    win.close()
    del sys.modules["openai"]

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 多語字幕包介面測試全數通過。")
