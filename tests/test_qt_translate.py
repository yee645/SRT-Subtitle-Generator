# -*- coding: utf-8 -*-
"""
3.0 第 11 項第三階段：逐句校對的「翻譯字幕…」（gui_qt/translate_dialog.py）。

翻譯走一般版同一套 subtitle/translator.py；openai 用替身（不連網、可以卡住或出錯）。QTest 真的點：

1. 按鈕：沒字幕灰掉；有字幕可以按。編輯框裡改到一半的先套用，翻的是套用後的。
2. 沒金鑰：說去一般版「轉寫設定」填，「開始翻譯」灰掉。有金鑰：寫清楚會送幾句、幾個字、什麼不送。
   預設的語言與做法照設定。
3. 翻譯（雙語）：清單、時間軸、畫面上的字幕都換；逐字時間軸拿掉；狀態列「文字改過 3 處」；
   下面寫翻成什麼、改了幾句；視窗關掉。送出去的只有文字。選的語言只記在這次開啟的設定裡，
   不寫 config.json。
4. Ctrl+Z 一次整份退回（逐字時間軸也回來），Ctrl+Y 再翻回去。
5. 只留譯文；有句子解析失敗：沿用原文、寫幾句。
6. 停止：卡在第一批時按停止——第二批不送、字幕不改；翻到一半關視窗＝停止。
7. 出錯（API 失敗、沒裝 openai）：寫原因、字幕不改、視窗留著可以再按。
8. 翻譯的時候字幕被改了：不套用、說原因。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過翻譯字幕的介面（核心在 test_cuetranslate.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    # ---- 替身 openai：照真的 SDK 的呼叫形狀；可以卡住（gate）、可以出錯、可以少回幾句 ----
    calls = []
    behaviour = {"mode": "ok", "prefix": "EN:"}
    gate = threading.Event()
    gate.set()
    entered = threading.Event()

    class _Completions:
        def create(self, model=None, messages=None):
            batch = json.loads(messages[-1]["content"])
            calls.append({"batch": batch, "system": messages[0]["content"]})
            entered.set()
            gate.wait(20)
            if behaviour["mode"] == "error":
                raise ConnectionError("連不上 api.openai.com")
            out = [behaviour["prefix"] + t for t in batch]
            if behaviour["mode"] == "short":
                out = out[:-1]
            content = json.dumps(out, ensure_ascii=False)
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

    main = os.path.join(tmp, "main.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:size=640x360:rate=30:d=8",
                    "-f", "lavfi", "-i", "sine=frequency=150:sample_rate=48000:d=8", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", main], check=True)

    original = [{"start": 0.5, "end": 2.0, "text": "大家好",
                 "words": [{"start": 0.5, "end": 1.0, "word": "大家"}, {"start": 1.0, "end": 2.0, "word": "好"}]},
                {"start": 3.0, "end": 5.0, "text": "上面一行\n下面"},
                {"start": 5.5, "end": 7.0, "text": "第三句"}]

    cfg = {"subtitle_style": {}, "translate": {"target_language": "ja", "mode": "replace"}}
    win = qt_app.MainWindow(cfg)
    win.tabs.setCurrentIndex(1)
    win.resize(1280, 800)
    win.show()
    wait(200)
    panel, cp = win.player_panel, win.cue_panel

    def texts():
        return [c["text"] for c in panel.cues]

    # ----- 1. 按鈕 -----
    check("沒字幕：「翻譯字幕…」灰掉", cp.translate_btn.isVisible() and not cp.translate_btn.isEnabled())
    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0)
    panel.set_cues(original)
    wait(100)
    check("有字幕：可以按", cp.translate_btn.isEnabled())

    # ----- 2. 沒金鑰／有金鑰 -----
    QTest.mouseClick(cp.translate_btn, Qt.LeftButton)
    wait(100)
    dlg = cp.translate_dialog
    check("打開翻譯視窗（擋住主視窗）", dlg is not None and dlg.isVisible()
          and dlg.windowModality() == Qt.WindowModal)
    check("沒金鑰：說去一般版「轉寫設定」填、開始灰掉", "轉寫設定" in dlg.notice.text() and "金鑰" in dlg.notice.text()
          and not dlg.start_btn.isEnabled(), dlg.notice.text())
    check("預設的語言與做法照設定（日文、只留譯文）", dlg.language_box.currentText() == "日文"
          and dlg.mode_buttons["replace"].isChecked())
    dlg.close()
    wait(50)

    cfg["transcription"] = {"api_key": "sk-test"}
    cp.select(0)
    cp.editor.setFocus()
    cp.editor.selectAll()
    cp.editor.insertPlainText("大家好喔")
    cp.translate_btn.click()  # 用 click()：焦點留在編輯框，看按鈕自己會不會先套用
    wait(100)
    check("編輯框裡改到一半：先套用再開視窗", panel.cues[0]["text"] == "大家好喔" and dlg.isVisible(),
          panel.cues[0]["text"])
    check("有金鑰：寫清楚送 3 句、13 個字的文字，時間、檔名、影片和聲音不送；開始可以按",
          "3 句" in dlg.notice.text() and "13 個字" in dlg.notice.text() and "不會送出" in dlg.notice.text()
          and "收費" in dlg.notice.text() and dlg.start_btn.isEnabled() and not dlg.stop_btn.isEnabled(),
          dlg.notice.text())

    # ----- 3. 翻譯（雙語）-----
    dlg.language_box.setCurrentIndex(dlg.language_box.findData("en"))
    dlg.mode_buttons["bilingual"].setChecked(True)
    before_words = dict(panel.cues[0])
    QTest.mouseClick(dlg.start_btn, Qt.LeftButton)
    check("翻好就套用、視窗關掉", wait_until(lambda: not dlg.isVisible()), dlg.status.text())
    check("雙語：原文在上、譯文在下", texts() == ["大家好喔\nEN:大家好喔", "上面一行\n下面\nEN:上面一行\n下面",
                                          "第三句\nEN:第三句"], str(texts()))
    check("送出去的只有那三句的文字，指定翻成英文", calls and calls[-1]["batch"] == ["大家好喔", "上面一行\n下面", "第三句"]
          and "英文" in calls[-1]["system"], str(calls[-1:]))
    check("逐字時間軸拿掉、時間照舊", "words" not in panel.cues[0] and panel.cues[0]["start"] == 0.5)
    check("清單、時間軸跟著換", cp.table.item(0, 2).text() == "大家好喔 / EN:大家好喔"
          and panel.timeline._source[2]["text"] == "第三句\nEN:第三句")
    panel.player.setPosition(6000)
    wait_until(lambda: panel.player.position() == 6000, 5000)
    wait(100)
    check("畫面上的字幕是雙語", panel.current_subtitle_text() == "第三句\nEN:第三句", panel.current_subtitle_text())
    check("下面寫翻成什麼、改了幾句、怎麼退回", "已翻成英文（雙語），改了 3 句" in cp.note.text()
          and "Ctrl+Z" in cp.note.text(), cp.note.text())
    check("狀態列：文字改過 3 處", "文字改過 3 處" in panel.info_label.text(), panel.info_label.text())
    check("選的語言與做法只記在這次開啟的設定裡、沒寫 config.json",
          cfg["translate"]["target_language"] == "en" and cfg["translate"]["mode"] == "bilingual"
          and not os.path.exists(config.CONFIG_PATH))

    # ----- 4. 復原／重做 -----
    win.activateWindow()  # offscreen 不會在對話框關掉後自己把主視窗設回作用中（桌面上會）
    wait_until(lambda: QApplication.activeWindow() is win, 3000)
    cp.table.setFocus()
    QTest.keyClick(cp.table, Qt.Key_Z, Qt.ControlModifier)
    check("Ctrl+Z 一次：整份退回，逐字時間軸也回來", texts() == ["大家好喔", "上面一行\n下面", "第三句"]
          and panel.cues[0].get("words") == before_words.get("words"), str(texts()))
    QTest.keyClick(cp.table, Qt.Key_Y, Qt.ControlModifier)
    check("Ctrl+Y：再翻回去", texts()[2] == "第三句\nEN:第三句")
    QTest.keyClick(cp.table, Qt.Key_Z, Qt.ControlModifier)

    # ----- 5. 只留譯文；有句子解析失敗 -----
    dlg = cp.open_translate()
    check("再開：上次選的英文、雙語還在", dlg.language_box.currentText() == "英文"
          and dlg.mode_buttons["bilingual"].isChecked())
    dlg.mode_buttons["replace"].setChecked(True)
    behaviour.update(mode="short", prefix="JA:")
    dlg.language_box.setCurrentIndex(dlg.language_box.findData("ja"))
    dlg.start()
    check("只留譯文；少回一句的那句沿用原文", wait_until(lambda: not dlg.isVisible())
          and texts() == ["JA:大家好喔", "JA:上面一行\n下面", "第三句"], str(texts()))
    check("寫幾句沿用原文", "1 句因格式問題沿用原文" in cp.note.text() and "改了 2 句" in cp.note.text(), cp.note.text())
    panel.undo()
    behaviour.update(mode="ok", prefix="EN:")

    # ----- 6. 停止 -----
    many = [{"start": i * 1.0, "end": i * 1.0 + 0.8, "text": f"第 {i} 句"} for i in range(7)]
    panel.set_cues(many)
    cfg["translate"]["batch_size"] = 5
    dlg = cp.open_translate()
    sent_before = len(calls)
    gate.clear()
    entered.clear()
    QTest.mouseClick(dlg.start_btn, Qt.LeftButton)
    check("翻譯中：開始灰掉、停止可以按、語言不能換", wait_until(lambda: entered.is_set(), 5000)
          and not dlg.start_btn.isEnabled() and dlg.stop_btn.isEnabled() and not dlg.language_box.isEnabled())
    QTest.mouseClick(dlg.stop_btn, Qt.LeftButton)
    check("按停止：說等這一批回來", "停止中" in dlg.status.text(), dlg.status.text())
    gate.set()
    check("停下來：字幕不改、第二批沒送、視窗留著", wait_until(lambda: not dlg.worker.busy)
          and wait_until(lambda: "已停止" in dlg.status.text(), 5000)
          and panel.cues == many and len(calls) == sent_before + 1 and dlg.isVisible()
          and dlg.start_btn.isEnabled(), f"{len(calls) - sent_before} {dlg.status.text()}")
    gate.clear()
    entered.clear()
    dlg.start()
    wait_until(lambda: entered.is_set(), 5000)
    dlg.close()
    gate.set()
    check("翻到一半關視窗＝停止，字幕不改", wait_until(lambda: not dlg.worker.busy) and wait(300) is None
          and panel.cues == many, str(texts()))

    # ----- 7. 出錯 -----
    panel.set_cues(original)
    dlg = cp.open_translate()
    behaviour["mode"] = "error"
    dlg.start()
    check("API 失敗：寫原因、字幕不改、視窗留著、可以再按", wait_until(lambda: "翻譯失敗" in dlg.status.text())
          and "連不上" in dlg.status.text() and panel.cues == original and dlg.isVisible()
          and dlg.start_btn.isEnabled(), dlg.status.text())
    behaviour["mode"] = "ok"
    sys.modules["openai"] = None
    dlg.start()
    check("沒裝 openai：寫怎麼裝", wait_until(lambda: "pip install openai" in dlg.status.text())
          and panel.cues == original, dlg.status.text())
    sys.modules["openai"] = fake

    dlg.close()
    dlg = cp.open_translate()
    check("關掉再開：上次的失敗訊息清掉", "翻譯失敗" not in dlg.status.text() and "一共 3 句" in dlg.status.text(),
          dlg.status.text())
    try:
        panel.apply_cues(original[:2])
        raised = False
    except ValueError:
        raised = True
    check("句數對不上：拋 ValueError、字幕不動、不記復原", raised and panel.cues == original
          and not panel.history.can_undo(), str(texts()))

    # ----- 8. 翻譯的時候字幕被改了 -----
    gate.clear()
    entered.clear()
    dlg.start()
    wait_until(lambda: entered.is_set(), 5000)
    panel.set_cue_text(2, "翻譯中改的")
    gate.set()
    check("翻譯中字幕被改：不套用、說原因", wait_until(lambda: "改過了" in dlg.status.text())
          and texts()[2] == "翻譯中改的" and texts()[0] == "大家好" and dlg.isVisible(), dlg.status.text())
    dlg.close()

    panel._ask_discard = lambda: "discard"
    panel._ask_project_discard = lambda: "discard"
    panel.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 翻譯字幕介面測試全數通過。")
