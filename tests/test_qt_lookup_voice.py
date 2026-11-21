# -*- coding: utf-8 -*-
"""
3.0 第 11 項第二十四階段：即時查譯（二）——朗讀與監聽剪貼簿（gui_qt/quicklookup_dialog.py）。

核心在 test_speech.py、test_clipwatch*.py；這裡驗介面與接線。不連網（`translate_snippet` 換成假的），
不真的發聲（語音引擎換成假的程序）。

1. 朗讀：原文用猜的語言、譯文用目標語言；沒東西念、設定關掉、沒有語音引擎、太長截掉都講；念完、失敗、停止各一句；
   不需要金鑰；收面板不停、關主視窗才停。
2. 監聽剪貼簿：預設關、沒金鑰灰掉；勾選當下剪貼簿裡原本的不算；複製外文就翻（只送那段文字）；密碼、路徑、
   程式碼、中文不送並講原因；同一份內容不重送；自己按〔複製〕的不算；收面板就停、再打開恢復；取消勾選就停；
   設定記在這次開啟的設定、不寫 config.json。
3. 第二十三階段的修正：切換「視窗置頂」之後照樣看選取、照樣監聽（換旗標會把視窗收起來再打開）。
"""
import copy
import os
import shutil
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

if PySide6 is None:
    print("SKIP 這個環境沒有 PySide6：略過即時查譯的朗讀與剪貼簿")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer  # noqa: E402
    from PySide6.QtGui import QTextCursor  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import quicklookup_dialog as qd  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import quicklookup as ql  # noqa: E402
    from subtitle import quicktranslate as qt  # noqa: E402
    from subtitle import speech  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait_until(cond, timeout_ms=5000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(20)
            waited += 20
        return cond()

    sent = []

    def fake_translate(text, api_key, settings=None, cache=None):
        sent.append(text)
        source = qt.normalize_snippet(text)
        result = {"source": source, "translation": "這是譯文。", "terms": [], "cached": False}
        if cache is not None:
            cache.put(source, settings["target_language"], result, settings["explain"])
        return result

    qt.translate_snippet = fake_translate

    launched = []
    proc_state = {"code": None, "stderr": b""}

    class FakeStderr:
        def read(self):
            return proc_state["stderr"]

    class FakeProc:
        def __init__(self, cmd, **kw):
            launched.append(cmd)
            self.stderr = FakeStderr()
            self.terminated = False
            procs.append(self)

        def poll(self):
            return 0 if self.terminated else proc_state["code"]

        def wait(self, timeout=None):
            if self.terminated:
                return 0
            if proc_state["code"] is None:
                import subprocess
                raise subprocess.TimeoutExpired("fake", timeout)
            return proc_state["code"]

        def terminate(self):
            self.terminated = True

    procs = []
    engine = {"kind": "espeak", "path": "/usr/bin/espeak-ng"}
    made = []

    def fake_speaker(settings):
        made.append(dict(settings))
        return speech.Speaker(engine=engine, settings=settings, popen=FakeProc)

    qd.QuickLookupDialog._make_speaker = lambda self, settings: fake_speaker(settings)

    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["transcription"].update(api_key="")
    cfg["quicktranslate"] = {"debounce_ms": 50}
    cfg["clipwatch"] = {"poll_ms": 200}
    cfg["speech"] = {"max_chars": 50}
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.show()
    wait(100)
    player = win.player_panel
    player._ask_discard = lambda *a, **k: "discard"
    player._ask_project_discard = lambda *a, **k: "discard"
    clipboard = QApplication.clipboard()

    dlg = win.open_lookup()
    wait(50)

    # ----- 1. 朗讀 -----
    check("朗讀一列：原文、譯文、停止", [b.text() for b in (dlg.speak_src_btn, dlg.speak_dst_btn, dlg.speak_stop_btn)]
          == ["原文", "譯文", "停止"])
    dlg.speak_dst_btn.click()
    check("沒金鑰時譯文區是說明：不念、講沒東西可念", dlg.status_label.text() == ql.C34_NOTHING_TO_SPEAK and not launched)
    dlg.src_text.setPlainText("Open the settings menu")  # 沒金鑰也能念（例如被擋下來的原文）
    dlg.speak_src_btn.click()
    check("沒金鑰也能朗讀原文", len(launched) == 1 and "Open the settings menu" in launched[0], launched)
    check("原文用猜的語言（英文）", "en" in launched[0], launched)
    check("講正在念", dlg.status_label.text() == "朗讀原文中。")
    check("朗讀設定照這次開啟的設定", made and made[0]["max_chars"] == 50)
    wait(700)
    check("還在念：狀態不變、繼續看", dlg.status_label.text() == "朗讀原文中。" and dlg.speech_timer.isActive())
    proc_state["code"] = 0
    check("念完講一句", wait_until(lambda: dlg.status_label.text() == ql.SPEECH_DONE))
    check("念完就不再看", not dlg.speech_timer.isActive())

    proc_state["code"] = None
    dlg.src_text.setPlainText("word " * 30)
    dlg.speak_src_btn.click()
    check("太長：截掉並講截掉幾個字", dlg.status_label.text().startswith("朗讀原文中（太長，後面 ")
          and "字不念" in dlg.status_label.text(), dlg.status_label.text())
    first = procs[-1]
    dlg.dst_text.setPlainText("這是譯文。")
    dlg.speak_dst_btn.click()
    check("念第二句先停掉前一句", first.terminated and len(launched) == 3)
    check("譯文用目標語言", "zh" in " ".join(launched[2]) or "cmn" in " ".join(launched[2]), launched[2])
    check("講正在念譯文", dlg.status_label.text() == "朗讀譯文中。")
    dlg.language_box.setCurrentIndex(dlg.language_box.findData("ja"))
    dlg.dst_text.setPlainText("Plain English text in the result box")
    dlg.speak_dst_btn.click()
    check("譯文用目標語言（不是猜的）", "ja" in launched[-1], launched[-1])
    dlg.language_box.setCurrentIndex(dlg.language_box.findData("zh-TW"))
    dlg.speak_stop_btn.click()
    check("停止：停掉、講一句", procs[-1].terminated and dlg.status_label.text() == ql.SPEECH_STOPPED
          and not dlg.speech_timer.isActive())
    check("沒在念時按停止：不做事", dlg.stop_speaking() is False and dlg.status_label.text() == ql.SPEECH_STOPPED)

    proc_state["code"] = 1
    proc_state["stderr"] = b"espeak: audio device busy\nmore"
    dlg._speaker = speech.Speaker(engine={"kind": "say", "path": "/usr/bin/say"}, settings=made[0], popen=FakeProc)
    dlg.speak_src_btn.click()
    check("失敗：講原因（只取第一行）", wait_until(lambda: dlg.status_label.text().startswith("朗讀失敗"))
          and dlg.status_label.text() == "朗讀失敗：espeak: audio device busy。", dlg.status_label.text())
    proc_state["code"] = None
    proc_state["stderr"] = b""

    dlg._speaker = speech.Speaker(engine=None, settings=made[0])
    check("沒有語音引擎：講出怎麼裝", dlg.speak("src") is False and "語音引擎" in dlg.status_label.text(),
          dlg.status_label.text())
    dlg._speaker = None
    player._config["speech"]["enabled"] = False
    n = len(launched)
    check("朗讀在設定裡關掉：不念、講一句", dlg.speak("src") is False and dlg.status_label.text() == ql.C36_SPEECH_OFF
          and len(launched) == n)
    player._config["speech"]["enabled"] = True

    dlg.speak("src")
    speaking = procs[-1]
    dlg.close()
    check("收面板：朗讀不停（跟一般版一樣）", not speaking.terminated)
    win.open_lookup()
    dlg.stop_speaking()

    # ----- 2. 監聽剪貼簿：沒金鑰 -----
    check("監聽剪貼簿預設關", not dlg.clip_box.isChecked() and not dlg.clipwatching())
    check("沒金鑰：監聽灰掉", not dlg.clip_box.isEnabled())
    check("說明寫明送什麼、不送什麼", "只有複製的那段文字" in qd.CLIP_HINT and "OpenAI" in qd.CLIP_HINT
          and "密碼" in qd.CLIP_HINT and "關掉這個面板就停止監聽" in qd.CLIP_HINT)

    player._config["transcription"]["api_key"] = "sk-test-0000"
    dlg.close()
    win.open_lookup()
    check("填了金鑰重新打開：可以勾", dlg.clip_box.isEnabled())

    clipboard.setText("my old password copied earlier")
    dlg.clip_box.setChecked(True)
    check("勾了就開始監聽、講一句", dlg.clipwatching() and dlg.clip_status.text() == qd.CLIP_WATCHING)
    wait(500)
    check("勾選當下剪貼簿裡原本的不算", sent == [])

    clipboard.setText("Please restart the application")
    check("複製外文：翻（只送那段文字）", wait_until(lambda: sent == ["Please restart the application"]))
    wait_until(lambda: dlg.status_label.text() in (qd.DONE, qd.DONE_SAVED))
    check("翻譯結果顯示在面板", dlg.src_text.toPlainText() == "Please restart the application"
          and dlg.dst_text.toPlainText() == "這是譯文。")
    wait(500)
    check("同一份內容：不重送", len(sent) == 1)

    for text, word in (("sk-proj-abcdefghijklmnopqrstuvwxyz0123456789", "密碼"),
                       ("C:\\Users\\me\\Documents\\report.docx", "路徑"),
                       ("def main():\n    return run(config)\n", "程式碼"),
                       ("這是一句已經是中文的內容", "中文")):
        clipboard.setText(text)
        wait_until(lambda: dlg.clip_status.text() != qd.CLIP_WATCHING and word in dlg.clip_status.text(), 2000)
        check(f"剪貼簿是{word}：不送、講原因", len(sent) == 1 and word in dlg.clip_status.text(), dlg.clip_status.text())

    dlg.clip_status.setText("（標記）")
    wait(500)
    check("擋掉的那份：之後的輪詢不再重判", dlg.clip_status.text() == "（標記）")
    dlg.copy("dst")
    wait(500)
    check("自己按〔複製〕的：不算（連判都不判）", len(sent) == 1 and clipboard.text() == "這是譯文。"
          and dlg.clip_status.text() == "（標記）")

    dlg.clip_settings["skip_paths"] = False
    clipboard.setText("C:\\Program Files\\Example\\readme first please.txt")
    check("篩子照這次開啟的設定（不跳過路徑）：路徑也送", wait_until(lambda: len(sent) == 2, 2000), sent)
    wait_until(lambda: dlg.status_label.text() in (qd.DONE, qd.DONE_SAVED))
    dlg.clip_settings["skip_paths"] = True
    sent.pop()

    dlg.close()
    check("收面板：停止監聽（勾選留著）", not dlg.clipwatching() and dlg.clip_box.isChecked())
    dlg.clip_box.setChecked(False)
    dlg.clip_box.setChecked(True)
    check("收起來時勾選：不開始監聽", not dlg.clipwatching())
    clipboard.setText("Copied while the panel is hidden")
    wait(500)
    check("收起來時複製：不送", len(sent) == 1)
    win.open_lookup()
    check("再打開：恢復監聽", dlg.clipwatching())
    wait(500)
    check("收起來時複製的那份：打開後也不算", len(sent) == 1)

    # ----- 3. 置頂切換之後照樣運作 -----
    dlg.topmost_box.setChecked(False)
    wait(50)
    check("切換置頂：還開著、照樣看選取、照樣監聽", dlg.isVisible() and dlg.watching() and dlg.clipwatching())
    editor = win.cue_panel.editor
    editor.setPlainText("Selection still works after toggling")
    editor.setFocus()
    cursor = editor.textCursor()
    cursor.select(QTextCursor.Document)
    editor.setTextCursor(cursor)
    QTest.mouseRelease(editor.viewport(), Qt.LeftButton, pos=QPoint(5, 5))
    check("切換置頂之後選字照樣翻", wait_until(lambda: len(sent) == 2) and sent[-1] == "Selection still works after toggling")
    clipboard.setText("Clipboard still works after toggling")
    check("切換置頂之後複製照樣翻", wait_until(lambda: len(sent) == 3) and sent[-1] == "Clipboard still works after toggling")
    dlg.topmost_box.setChecked(True)
    wait(50)

    dlg.clip_box.setChecked(False)
    check("取消勾選：停、講一句、記進這次開啟的設定", not dlg.clipwatching() and dlg.clip_status.text() == qd.CLIP_STOPPED
          and player._config["clipwatch"]["enabled"] is False)
    clipboard.setText("Not watching any more")
    wait(500)
    check("取消勾選之後複製：不送", len(sent) == 3)
    dlg.clip_box.setChecked(True)
    data = player._config.get("clipwatch") or {}
    check("監聽設定記在這次開啟的設定", data.get("enabled") is True and data.get("poll_ms") == 200
          and data.get("skip_secrets") is True)
    check("監聽間隔照設定", dlg.clip_timer.interval() == 200)

    player._config["transcription"]["api_key"] = ""
    clipboard.setText("Copied after the key was removed")
    dlg._poll_clipboard()
    check("開著時金鑰被拿掉：輪詢到就停、不送", not dlg.clipwatching() and len(sent) == 3)
    player._config["transcription"]["api_key"] = "sk-test-0000"
    dlg._start_clipwatch()
    player._config["transcription"]["api_key"] = ""
    dlg._refresh_key_state()
    check("開著時重查金鑰：沒有就停監聽", not dlg.clipwatching() and dlg.clip_status.text() == "")
    dlg.close()
    win.open_lookup()
    check("金鑰拿掉：監聽灰掉、停", not dlg.clip_box.isEnabled() and not dlg.clipwatching()
          and dlg.clip_status.text() == "")
    player._config["transcription"]["api_key"] = "sk-test-0000"
    dlg.close()
    win.open_lookup()
    check("金鑰回來：勾選還在、恢復監聽", dlg.clip_box.isChecked() and dlg.clipwatching())

    dlg.src_text.setPlainText("Last words")
    dlg.speak("src")
    speaking = procs[-1]
    win.close()
    check("關主視窗：停朗讀、停監聽、收面板、不再看選取", speaking.terminated and not dlg.clipwatching()
          and not dlg.isVisible() and not dlg.watching())
    check("全程沒寫 config.json", not os.path.exists(config.CONFIG_PATH))
    player.shutdown()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 即時查譯的朗讀與剪貼簿測試全數通過。")
