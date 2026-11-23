# -*- coding: utf-8 -*-
"""
3.0 第 11 項第二十三階段：即時查譯面板（gui_qt/quicklookup_dialog.py）。

核心在 test_quicktranslate*.py、test_v1520.py（一般版改從 subtitle/quicklookup.py import）；這裡驗介面與接線。
不連網：`translate_snippet` 換成假的（記下送了什麼、照真的一樣寫進快取）。

1. 頁籤列右上角有〔即時查譯…〕，每一頁都看得到；開小視窗（不擋主視窗、只建一個）；關＝收起來，快取與生字本留著。
2. 說明寫明送什麼（只有選取的文字、送到 OpenAI）、不送什麼。
3. 沒金鑰：自動翻譯灰掉、說明指向主視窗右上角〔轉寫與金鑰…〕，選字、按鈕都不送；這次開啟的設定填了金鑰，重新打開就能用。
4. 選字即翻：②的編輯框、①的搜尋框選字、放開滑鼠 → 去抖動後送出；面板收起來就不看；密碼欄位不拿；
   像密碼的內容不送；太短、已經是中文、太長各講原因；同一句不重送；快取命中不再送。
5. 〔翻譯選取內容〕：最近選到的字；沒選字翻②字幕清單選中那一句；都沒有講原因。
6. 結果：原文、譯文、關鍵詞；關閉解說、沒有關鍵詞各一句；譯文區標題跟著目標語言；舊請求作廢。
7. 失敗：講原因；連續 3 次暫停自動翻譯。
8. 生字本：自動收詞（去重、可關）、寫進 config.json 旁邊的檔（跟一般版同一個）、刪除、清空先問、匯出 CSV。
9. 複製原文／譯文；設定只記在這次開啟的設定、不寫 config.json。
"""
import copy
import csv
import json
import os
import shutil
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []


def check(name, cond, extra=""):
    if not cond and "dlg" in globals():
        extra = extra or f"[{dlg.status_label.text()} / 送出 {[x['text'][:30] for x in sent]}]"
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


try:
    import PySide6  # noqa: F401
except ImportError:
    PySide6 = None

if PySide6 is None:
    print("SKIP 這個環境沒有 PySide6：略過即時查譯面板")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer  # noqa: E402
    from PySide6.QtGui import QTextCursor  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import quicklookup_dialog as qd  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import quicklookup as ql  # noqa: E402
    from subtitle import quicktranslate as qt  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")
    VOCAB = os.path.join(tmp, ql.VOCAB_FILENAME)

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
    fake = {"fail": None, "gate": None, "terms": True}

    def fake_translate(text, api_key, settings=None, cache=None):
        sent.append({"text": text, "key": api_key, "settings": dict(settings or {})})
        if fake["gate"] is not None:
            fake["gate"].wait(5)
        if fake["fail"]:
            raise RuntimeError(fake["fail"])
        source = qt.normalize_snippet(text)
        terms = ([{"word": source.split()[0], "meaning": "（測試）" + source.split()[0]}]
                 if fake["terms"] and settings.get("explain") else [])
        result = {"source": source, "translation": f"譯：{source}（{settings['target_language']}）",
                  "terms": terms, "cached": False}
        if cache is not None:
            cache.put(source, settings["target_language"], result, settings["explain"])
        return result

    qt.translate_snippet = fake_translate

    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["transcription"].update(api_key="")
    cfg["quicktranslate"] = {"debounce_ms": 50}
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.show()
    wait(100)
    player = win.player_panel
    player._ask_discard = lambda *a, **k: "discard"
    player._ask_project_discard = lambda *a, **k: "discard"

    # ----- 1. 按鈕與小視窗 -----
    btn = win.lookup_btn
    check("頁籤列右上角有〔即時查譯…〕", win.tabs.cornerWidget(Qt.TopRightCorner) is btn and btn.text() == "即時查譯…")
    for i in range(win.tabs.count()):
        win.tabs.setCurrentIndex(i)
        wait(10)
        if not btn.isVisible():
            break
    check("每一頁都看得到這顆鈕", btn.isVisible())
    check("狀態列提到即時查譯", "、右上角的即時查譯，其餘" in win.statusBar().currentMessage())
    win.tabs.setCurrentIndex(1)
    check("按之前沒有建小視窗", win.lookup_dialog is None)
    btn.click()
    wait(50)
    dlg = win.lookup_dialog
    check("按了開小視窗、不擋主視窗", dlg is not None and dlg.isVisible() and not dlg.isModal())
    check("開著就在看選取", dlg.watching())
    check("兩頁：查譯、生字本", [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())] == ["查譯", "生字本"])
    check("說明寫明送什麼、送到哪", "只有選取的那段文字" in qd.HINT and "OpenAI" in qd.HINT and "密碼" in qd.HINT)
    check("選項初值：自動、附解說、繁中、存生字本、置頂",
          dlg.auto_box.isChecked() and dlg.explain_box.isChecked() and dlg.language_box.currentData() == "zh-TW"
          and dlg.save_vocab_box.isChecked() and dlg.topmost_box.isChecked()
          and bool(dlg.windowFlags() & Qt.WindowStaysOnTopHint))
    check("譯文區標題：中文翻譯", dlg.dst_box.title() == "中文翻譯")
    dlg.close()
    check("關＝收起來、不再看選取", not dlg.isVisible() and not dlg.watching())
    btn.click()
    check("再按一次：同一個小視窗原地打開", win.lookup_dialog is dlg and dlg.isVisible() and dlg.watching())

    # ----- 3. 沒金鑰 -----
    check("沒金鑰：自動翻譯灰掉", not dlg.auto_box.isEnabled())
    # 第三十二階段起 Qt 版自己有轉寫與金鑰設定：改成指向主視窗右上角〔轉寫與金鑰…〕
    check("沒金鑰：說明指向〔轉寫與金鑰…〕", dlg.dst_text.toPlainText() == qd.NOKEY_BODY
          and "〔轉寫與金鑰…〕" in qd.NOKEY_BODY and "一般版" not in qd.NOKEY_BODY
          and dlg.status_label.text() == qd.NOKEY_STATUS)
    editor = win.cue_panel.editor
    editor.setPlainText("The quick brown fox jumps over the lazy dog")
    editor.setFocus()
    editor.selectAll()
    QTest.mouseRelease(editor.viewport(), Qt.LeftButton, pos=QPoint(5, 5))
    wait(200)
    check("沒金鑰：選字不送", sent == [])
    check("沒金鑰：按〔翻譯選取內容〕也不送、講原因", dlg.translate_selection() is False and sent == []
          and dlg.status_label.text() == qd.NOKEY_STATUS)
    check("沒金鑰：複製沒東西可複製", dlg.copy("dst") is False and dlg.status_label.text() == qd.NOTHING_TO_COPY)
    player._config["transcription"]["api_key"] = "sk-test-0000"
    dlg.close()
    btn.click()
    check("填了金鑰重新打開：自動翻譯可用、等待選取", dlg.auto_box.isEnabled() and dlg.status_label.text() == qd.WAITING
          and dlg.dst_text.toPlainText() == qd.INITIAL)

    # ----- 4. 選字即翻 -----
    def select_and_release(widget, text=None, start=None, end=None):
        widget.setFocus()
        app.processEvents()
        if isinstance(widget, QLineEdit):
            widget.setText(text) if text is not None else None
            widget.selectAll()
            QTest.keyRelease(widget, Qt.Key_Shift)
            return
        if text is not None:
            widget.setPlainText(text)
        cursor = widget.textCursor()
        if start is None:
            cursor.select(QTextCursor.Document)
        else:
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.KeepAnchor)
        widget.setTextCursor(cursor)
        QTest.mouseRelease(widget.viewport(), Qt.LeftButton, pos=QPoint(5, 5))

    select_and_release(editor, "Hello there, how are you doing today", 0, 11)
    check("去抖動之前還沒送", sent == [])
    check("等到結果", wait_until(lambda: dlg.status_label.text() == qd.DONE_SAVED))
    check("送出去的只有選取的那段文字", [s["text"] for s in sent] == ["Hello there"] and sent[0]["key"] == "sk-test-0000")
    check("送出的設定：目標語言、附解說", sent[0]["settings"]["target_language"] == "zh-TW" and sent[0]["settings"]["explain"])
    check("顯示原文、譯文、關鍵詞", dlg.src_text.toPlainText() == "Hello there"
          and dlg.dst_text.toPlainText() == "譯：Hello there（zh-TW）"
          and dlg.term_text.toPlainText() == "・「Hello」：（測試）Hello")
    check("關鍵詞收進生字本、寫進 config.json 旁邊的檔", ql.load_vocab(VOCAB) == [{"word": "Hello", "meaning": "（測試）Hello"}]
          and dlg.vocab_table.rowCount() == 1 and dlg.vocab_table.item(0, 0).text() == "Hello")
    check("生字本狀態", dlg.vocab_status.text() == "生字本共 1 個詞。")

    QTest.mouseRelease(editor.viewport(), Qt.LeftButton, pos=QPoint(5, 5))
    wait(200)
    check("同一句再放開一次：不重送、連快取都不查（狀態不變）", len(sent) == 1 and dlg.status_label.text() == qd.DONE_SAVED)

    dlg.src_text.setFocus()
    dlg.src_text.selectAll()
    QTest.mouseRelease(dlg.src_text.viewport(), Qt.LeftButton, pos=QPoint(5, 5))
    check("面板自己的框選字：不算", not dlg.debounce.isActive() and dlg._last_selection == "Hello there")
    wait(200)
    check("面板自己的框選字：不送", len(sent) == 1)

    select_and_release(editor, "Deselected before the delay")
    cursor = editor.textCursor()
    cursor.clearSelection()
    editor.setTextCursor(cursor)
    wait(200)
    check("去抖動期間取消選取：不送", len(sent) == 1)
    select_and_release(editor, "Unchecked before the delay")
    dlg.auto_box.setChecked(False)
    wait(200)
    check("去抖動期間關掉自動翻譯：不送", len(sent) == 1)
    dlg.auto_box.setChecked(True)

    win.tabs.setCurrentIndex(0)
    wait(50)
    select_and_release(win.review_panel.search_edit, "Welcome to the channel everyone")
    check("①的搜尋框選字也會翻", wait_until(lambda: len(sent) == 2) and sent[1]["text"] == "Welcome to the channel everyone")
    wait_until(lambda: dlg.status_label.text() in (qd.DONE_SAVED, qd.DONE))
    win.tabs.setCurrentIndex(1)
    wait(50)

    n = len(sent)
    select_and_release(editor, "x")
    wait(200)
    check("太短：不送、講原因", len(sent) == n and dlg.status_label.text() == ql.C16_TOO_SHORT_OR_EMPTY)
    select_and_release(editor, "這是一段已經是中文的字幕內容")
    wait(200)
    check("已經是中文：不送、講原因", len(sent) == n and dlg.status_label.text() == ql.C15_ALREADY_CHINESE)
    select_and_release(editor, "word " * 200)
    wait(200)
    check("太長：不送、講原因", len(sent) == n and dlg.status_label.text().startswith("已略過：選取超過"))
    select_and_release(editor, "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789ABCD")
    wait(200)
    check("像金鑰的內容：不送、講原因", len(sent) == n and dlg.status_label.text() == qd.SECRET_BLOCKED)

    editor.setPlainText("first line\nsecond line")
    cursor = editor.textCursor()
    cursor.select(QTextCursor.Document)
    editor.setTextCursor(cursor)
    check("多行選取：段落分隔換成換行", qd.selected_text_of(editor) == "first line\nsecond line")
    check("不是文字框：沒有選取", qd.selected_text_of(win.lookup_btn) == "" and qd.text_widget_of(win.lookup_btn) is None)
    check("滑鼠事件落在 viewport：找得到文字框", qd.text_widget_of(editor.viewport()) is editor)

    pw = QLineEdit(win)
    pw.setEchoMode(QLineEdit.Password)
    pw.show()
    select_and_release(pw, "Some secret phrase here")
    wait(200)
    check("密碼欄位選字：不拿", len(sent) == n and qd.selected_text_of(pw) == "")
    plain = QLineEdit(win)
    plain.show()
    select_and_release(plain, "Good morning friends")
    check("一般單行文字框選字（放開 Shift）：會翻", wait_until(lambda: len(sent) == n + 1)
          and sent[-1]["text"] == "Good morning friends")
    wait_until(lambda: dlg.status_label.text() in (qd.DONE_SAVED, qd.DONE))
    n = len(sent)

    dlg.close()
    select_and_release(editor, "This should not be sent anywhere")
    wait(200)
    check("面板收起來：選字不送", len(sent) == n)
    btn.click()
    wait(50)

    dlg.auto_box.setChecked(False)
    select_and_release(editor, "Automatic translation is turned off")
    check("關掉自動翻譯：選字不啟動去抖動", not dlg.debounce.isActive())
    wait(200)
    check("關掉自動翻譯：選字不送", len(sent) == n)

    # ----- 5. 〔翻譯選取內容〕 -----
    check("按鈕不搶焦點", dlg.translate_btn.focusPolicy() == Qt.NoFocus)
    dlg.translate_btn.click()
    check("按鈕：翻最近選到的字", wait_until(lambda: len(sent) == n + 1) and sent[-1]["text"] == "Automatic translation is turned off")
    wait_until(lambda: dlg.status_label.text() in (qd.DONE_SAVED, qd.DONE))
    n = len(sent)
    dlg.translate_btn.click()
    wait(100)
    check("按鈕再按同一句：快取命中、不再送", len(sent) == n and dlg.status_label.text() == qd.CACHED)
    dlg._last_selection = ""
    player.set_generated_cues([{"start": 0.0, "end": 1.0, "text": "First line of the subtitles"},
                               {"start": 1.0, "end": 2.0, "text": "Second line goes here"}])
    wait(50)
    win.cue_panel.select(1)
    wait(50)
    dlg._last_selection = ""
    dlg.translate_btn.click()
    check("沒選字：翻②字幕清單選中那一句", wait_until(lambda: len(sent) == n + 1) and sent[-1]["text"] == "Second line goes here")
    wait_until(lambda: dlg.status_label.text() in (qd.DONE_SAVED, qd.DONE))
    n = len(sent)
    player.set_generated_cues([])
    wait(50)
    dlg._last_selection = ""
    check("都沒有：講原因", dlg.translate_selection() is False and dlg.status_label.text() == qd.NOTHING_SELECTED
          and len(sent) == n)

    # ----- 6. 結果顯示 -----
    dlg.explain_box.setChecked(False)
    dlg.submit("Turn off the explanations please", manual=True)
    wait_until(lambda: dlg.status_label.text() == qd.DONE)
    check("關掉解說：送出的設定不附解說、關鍵詞區講一句", sent[-1]["settings"]["explain"] is False
          and dlg.term_text.toPlainText() == qd.EXPLAIN_OFF)
    dlg.explain_box.setChecked(True)
    fake["terms"] = False
    dlg.submit("Nothing interesting in here", manual=True)
    wait_until(lambda: dlg.status_label.text() == qd.DONE)
    check("沒有關鍵詞：講一句", dlg.term_text.toPlainText() == qd.NO_TERMS)
    fake["terms"] = True
    at = dlg.language_box.findData("ja")
    dlg.language_box.setCurrentIndex(at)
    check("目標語言換日文：譯文區標題跟著換", dlg.dst_box.title() == "日文翻譯")
    dlg.submit("Change the target language", manual=True)
    wait_until(lambda: dlg.status_label.text() in (qd.DONE_SAVED, qd.DONE))
    check("送出的目標語言跟著換", sent[-1]["settings"]["target_language"] == "ja"
          and dlg.dst_text.toPlainText().endswith("（ja）"))
    dlg.language_box.setCurrentIndex(dlg.language_box.findData("zh-TW"))

    gate = threading.Event()
    fake["gate"] = gate
    dlg.submit("The first slow request", manual=True)
    check("送出中：講在翻", dlg.status_label.text() == qd.LOADING)
    fake["gate"] = None
    dlg.submit("The second quick request", manual=True)
    wait_until(lambda: dlg.src_text.toPlainText() == "The second quick request" and dlg.status_label.text() != qd.LOADING)
    gate.set()
    wait(300)
    check("舊請求晚回來：作廢、不蓋掉新的", dlg.src_text.toPlainText() == "The second quick request"
          and dlg.dst_text.toPlainText().startswith("譯：The second quick request"))

    # ----- 7. 失敗 -----
    dlg.auto_box.setChecked(True)
    fake["fail"] = "連線失敗：測試故意的\n第二行"
    for i, text in enumerate(["Failure number one", "Failure number two"]):
        dlg.submit(text, manual=True)
        wait_until(lambda: dlg.status_label.text().startswith("翻譯失敗"))
    check("失敗：講原因（只取第一行）", dlg.status_label.text().startswith("翻譯失敗：連線失敗：測試故意的。")
          and "第二行" not in dlg.status_label.text())
    check("失敗兩次：自動翻譯還開著", dlg.auto_box.isChecked())
    dlg.submit("Failure number three", manual=True)
    wait_until(lambda: dlg.status_label.text() == qd.AUTO_PAUSED)
    check("連續 3 次失敗：暫停自動翻譯", not dlg.auto_box.isChecked() and dlg.status_label.text() == qd.AUTO_PAUSED)
    fake["fail"] = None
    dlg.auto_box.setChecked(True)
    fake["fail"] = "又失敗"
    for text in ("Reset counter one", "Reset counter two"):
        dlg.submit(text, manual=True)
        wait_until(lambda: dlg.status_label.text().startswith("翻譯失敗"))
    fake["fail"] = None
    dlg.submit("A success in between", manual=True)
    wait_until(lambda: dlg.status_label.text() in (qd.DONE_SAVED, qd.DONE))
    fake["fail"] = "再失敗"
    dlg.submit("Reset counter three", manual=True)
    wait_until(lambda: dlg.status_label.text().startswith("翻譯失敗"))
    check("中間成功一次：失敗次數重算、不暫停", dlg.auto_box.isChecked())
    fake["fail"] = None

    # ----- 8. 生字本 -----
    words_before = [e["word"] for e in dlg.vocab]
    dlg.submit("Hello again my friend", manual=True)
    wait_until(lambda: dlg.status_label.text() in (qd.DONE_SAVED, qd.DONE))
    check("同一個詞不重複收", [e["word"] for e in dlg.vocab] == words_before and dlg.status_label.text() == qd.DONE)
    dlg.save_vocab_box.setChecked(False)
    dlg.submit("Unsaved words stay out", manual=True)
    wait_until(lambda: dlg.status_label.text() in (qd.DONE_SAVED, qd.DONE))
    check("關掉存生字本：不收", "Unsaved" not in [e["word"] for e in dlg.vocab])
    dlg.save_vocab_box.setChecked(True)
    on_disk = ql.load_vocab(VOCAB)
    check("檔案跟畫面一致", on_disk == dlg.vocab and len(on_disk) == dlg.vocab_table.rowCount() >= 3)

    dlg.tabs.setCurrentIndex(1)
    check("沒選列：刪除灰掉", not dlg.delete_btn.isEnabled())
    dlg.vocab_table.selectRow(0)
    check("選了列：刪除可按", dlg.delete_btn.isEnabled())
    first = dlg.vocab[0]["word"]
    dlg.delete_btn.click()
    check("刪除選取：畫面與檔案都少了那個詞", first not in [e["word"] for e in dlg.vocab]
          and first not in [e["word"] for e in ql.load_vocab(VOCAB)])

    out = os.path.join(tmp, "匯出", "生字本.csv")
    os.makedirs(os.path.dirname(out))
    dlg._ask_export_path = lambda: out
    dlg.export_btn.click()
    with open(out, encoding="utf-8-sig", newline="") as fp:
        rows = list(csv.reader(fp))
    check("匯出 CSV：表頭＋每個詞", rows[0] == ["詞句", "意思"] and [r[0] for r in rows[1:]] == [e["word"] for e in dlg.vocab])
    check("匯出：講匯出幾個詞到哪", dlg.vocab_status.text() == ql.C20_EXPORTED(len(dlg.vocab), out))
    dlg._ask_export_path = lambda: ""
    check("匯出選取消：不做事", dlg.export_vocab() == "" and dlg.vocab_status.text() == ql.C20_EXPORTED(len(dlg.vocab), out))

    asked = []
    dlg._ask_clear = lambda count: (asked.append(count), False)[1]
    count = len(dlg.vocab)
    dlg.clear_btn.click()
    check("清空先問（寫明幾個詞）、選否就不清", asked == [count] and len(dlg.vocab) == count)
    dlg._ask_clear = lambda count: True
    dlg.clear_btn.click()
    check("清空：畫面與檔案都空了", dlg.vocab == [] and ql.load_vocab(VOCAB) == [] and dlg.vocab_table.rowCount() == 0)
    check("空了：匯出、清空灰掉、狀態講一句", not dlg.export_btn.isEnabled() and not dlg.clear_btn.isEnabled()
          and dlg.vocab_status.text() == ql.C22_VOCAB_EMPTY)

    with open(VOCAB, "w", encoding="utf-8") as fp:
        json.dump([{"word": "shared", "meaning": "一般版收的詞"}], fp, ensure_ascii=False)
    dlg.close()
    btn.click()
    check("重新打開：讀到一般版那邊收的詞（同一本）", [e["word"] for e in dlg.vocab] == ["shared"])
    dlg.tabs.setCurrentIndex(0)

    # ----- 9. 複製、設定 -----
    dlg.submit("Copy this sentence please", manual=True)
    wait_until(lambda: dlg.status_label.text() in (qd.DONE_SAVED, qd.DONE))
    dlg.copy_src_btn.click()
    check("複製原文", QApplication.clipboard().text() == "Copy this sentence please" and dlg.status_label.text() == "已複製原文。")
    dlg.copy_dst_btn.click()
    check("複製譯文", QApplication.clipboard().text().startswith("譯：Copy this sentence") and dlg.status_label.text() == "已複製譯文。")

    dlg.topmost_box.setChecked(False)
    check("取消置頂：視窗旗標跟著、還開著", not (dlg.windowFlags() & Qt.WindowStaysOnTopHint) and dlg.isVisible())
    data = player._config.get("quicktranslate") or {}
    check("選項記在這次開啟的設定", data.get("topmost") is False and data.get("auto_translate") is True
          and data.get("target_language") == "zh-TW" and data.get("debounce_ms") == 50)
    dlg.auto_box.setChecked(False)
    dlg2 = qd.QuickLookupDialog(player, win.cue_panel, win)
    check("下一個面板沿用這次開啟的設定", not dlg2.topmost_box.isChecked() and not dlg2.auto_box.isChecked()
          and dlg2.cache is not dlg.cache)
    dlg2.deleteLater()

    win.close()
    check("關主視窗：面板跟著收、不再看選取", not dlg.watching())
    check("全程沒寫 config.json", not os.path.exists(config.CONFIG_PATH))
    player.shutdown()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 即時查譯面板測試全數通過。")
