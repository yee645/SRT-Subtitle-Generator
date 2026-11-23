# -*- coding: utf-8 -*-
"""
3.0 第 11 項第三十二階段：轉寫與金鑰設定（gui_qt/transcribe_dialog.py）。

規則在 test_transcribecfg.py；這裡 QTest 真的點、真的打字：

1. 主視窗右上角有〔轉寫與金鑰…〕（在〔即時查譯…〕旁邊）；打開不擋住主視窗，每一格照這次開啟的設定擺好。
2. 金鑰預設遮住；〔顯示〕看得到、再按遮回去；重新打開又遮住。旁邊講存在哪、也用在翻譯與即時查譯。
3. 最下面那行照勾選講會送什麼：本地什麼都不送；勾 OpenAI 講送聲音、有提示詞時提示詞也送。
4. 〔取消〕什麼都不改；〔套用〕寫進這次開啟的設定（整理過、其他鍵留著），狀態列講一句（金鑰只露頭尾）。
5. 套用後，翻譯字幕、即時查譯、生成字幕用的就是新金鑰（不必重開）；沒金鑰時的說明都指向〔轉寫與金鑰…〕。
6. 〔瀏覽…〕選 python：選了填進去、取消不變。語言可以自己打代碼。
7. 生成字幕視窗的〔轉寫設定…〕：蓋在生成視窗上打開同一種設定；套用後生成視窗的語言與說明跟著換；
   生成中灰掉。
8. 全程沒寫 config.json。
"""
import copy
import os
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
    print("SKIP 這個環境沒有 PySide6：略過轉寫與金鑰設定介面")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import generate_dialog as gd  # noqa: E402
    from gui_qt import quicklookup_dialog as qd  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from gui_qt import translate_dialog as td  # noqa: E402
    from gui_qt import transcribe_dialog as tdlg  # noqa: E402
    from subtitle import transcribecfg as tc  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["transcription"].update(model="small", language="ja", api_key="", prompt="", 自訂="留著")
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.show()
    wait(100)
    panel = win.player_panel
    panel._ask_discard = lambda *a, **k: "discard"
    panel._ask_project_discard = lambda *a, **k: "discard"

    # ----- 1 -----
    btn = win.transcription_btn
    check("右上角有〔轉寫與金鑰…〕、在〔即時查譯…〕左邊", btn.isVisible() and btn.text() == "轉寫與金鑰…"
          and btn.mapTo(win, btn.rect().topLeft()).x() < win.lookup_btn.mapTo(win, win.lookup_btn.rect().topLeft()).x())
    QTest.mouseClick(btn, Qt.LeftButton)
    dlg = win.transcription_dialog
    check("打開：不擋住主視窗", dlg is not None and dlg.isVisible() and not dlg.isModal()
          and dlg.windowModality() == Qt.NonModal)
    check("每一格照設定擺好", dlg.model_box.currentText() == "small" and dlg.language() == "ja"
          and not dlg.use_api_box.isChecked() and dlg.use_cache_box.isChecked() and dlg.key_edit.text() == ""
          and dlg.python_edit.text() == "" and dlg.prompt_edit.text() == "")
    check("模型選項跟一般版一樣", [dlg.model_box.itemText(i) for i in range(dlg.model_box.count())] == list(tc.MODELS))

    # ----- 2 -----
    check("金鑰預設遮住", dlg.key_edit.echoMode() == QLineEdit.Password)
    QTest.mouseClick(dlg.show_key_btn, Qt.LeftButton)
    check("〔顯示〕看得到", dlg.key_edit.echoMode() == QLineEdit.Normal and dlg.show_key_btn.text() == "隱藏")
    QTest.mouseClick(dlg.show_key_btn, Qt.LeftButton)
    check("再按遮回去", dlg.key_edit.echoMode() == QLineEdit.Password and dlg.show_key_btn.text() == "顯示")
    check("講金鑰存在哪、也用在翻譯與即時查譯", "config.json" in dlg.key_note.text()
          and "翻譯字幕" in dlg.key_note.text() and "即時查譯" in dlg.key_note.text())

    # ----- 3 -----
    check("本地：講什麼都不送", dlg.sends.text() == tc.sends_text({"use_api": False}) and "不會送出去" in dlg.sends.text())
    dlg.use_api_box.click()
    check("勾 OpenAI、沒金鑰：講送聲音、還沒有金鑰", "影片的聲音送到 OpenAI" in dlg.sends.text()
          and "還沒有金鑰" in dlg.sends.text(), dlg.sends.text())
    dlg.prompt_edit.setText("達文西")  # 中文用 setText（QTest 打不了中文）
    check("有提示詞：提示詞也送", "影片的聲音與提示詞送到 OpenAI" in dlg.sends.text())

    # ----- 4 -----
    QTest.keyClicks(dlg.key_edit, "  sk-proj-1234567890abcdefWXYZ ")
    QTest.mouseClick(dlg.cancel_btn, Qt.LeftButton)
    check("〔取消〕：什麼都不改", not dlg.isVisible() and cfg["transcription"]["api_key"] == ""
          and cfg["transcription"]["use_api"] is False and cfg["transcription"]["prompt"] == "")
    QTest.mouseClick(btn, Qt.LeftButton)
    check("取消後重開：照設定（沒套用的不留）", dlg.isVisible() and dlg.key_edit.text() == ""
          and not dlg.use_api_box.isChecked())
    QTest.mouseClick(dlg.show_key_btn, Qt.LeftButton)
    QTest.keyClicks(dlg.key_edit, "  sk-proj-1234567890abcdefWXYZ ")
    dlg.prompt_edit.setText(" 達文西 ")
    dlg.model_box.setCurrentText("medium")
    QTest.mouseClick(dlg.apply_btn, Qt.LeftButton)
    t = cfg["transcription"]
    check("〔套用〕：寫進這次開啟的設定（整理過、其他鍵留著）", not dlg.isVisible()
          and t["api_key"] == "sk-proj-1234567890abcdefWXYZ" and t["prompt"] == "達文西" and t["model"] == "medium"
          and t["use_api"] is False and t["language"] == "ja" and t["自訂"] == "留著", str(t))
    msg = win.statusBar().currentMessage()
    check("狀態列講一句、金鑰只露頭尾", "轉寫設定已套用" in msg and "sk-…WXYZ" in msg
          and "1234567890" not in msg, msg)
    QTest.mouseClick(btn, Qt.LeftButton)
    check("重開：金鑰又遮住", dlg.key_edit.echoMode() == QLineEdit.Password and dlg.show_key_btn.text() == "顯示")
    dlg.close()

    # ----- 5 -----
    check("翻譯字幕用的就是新金鑰", td.TranslateDialog.api_key(type("P", (), {"player": panel})())
          == "sk-proj-1234567890abcdefWXYZ")
    gen = gd.GenerateDialog(panel)
    check("生成字幕用的就是新設定", gen.config()["transcription"]["api_key"] == "sk-proj-1234567890abcdefWXYZ"
          and gen.config()["transcription"]["model"] == "medium")
    for text in (td.NO_KEY, qd.NOKEY_BODY, gd.NO_KEY):
        check(f"沒金鑰的說明不再叫人去一般版：{text[:12]}…", "一般版" not in text
              and ("〔轉寫與金鑰…〕" in text or "〔轉寫設定…〕" in text))

    # ----- 6 -----
    dlg = win.open_transcription_settings()
    dlg._ask_python = lambda: "C:/Python312/python.exe"
    QTest.mouseClick(dlg.python_btn, Qt.LeftButton)
    check("〔瀏覽…〕：選了填進去", dlg.python_edit.text() == "C:/Python312/python.exe")
    dlg._ask_python = lambda: ""
    QTest.mouseClick(dlg.python_btn, Qt.LeftButton)
    check("〔瀏覽…〕：取消不變", dlg.python_edit.text() == "C:/Python312/python.exe")
    dlg.language_box.setEditText("fr")
    check("語言可以自己打代碼", dlg.values()["language"] == "fr")
    dlg.language_box.setEditText("")
    check("語言空白＝auto", dlg.values()["language"] == "auto")
    dlg.close()

    # ----- 7 -----
    gen.prepare()
    gen.open()
    wait(50)
    check("生成視窗有〔轉寫設定…〕", gen.settings_btn.isVisible() and gen.settings_btn.isEnabled())
    QTest.mouseClick(gen.settings_btn, Qt.LeftButton)
    sub = gen.settings_dialog
    check("蓋在生成視窗上打開", sub is not None and sub.isVisible() and sub.parent() is gen
          and sub.windowModality() != Qt.NonModal)
    sub.language_box.setCurrentIndex(sub.language_box.findData("en"))
    sub.use_api_box.click()
    QTest.mouseClick(sub.apply_btn, Qt.LeftButton)
    check("套用後：設定換掉、生成視窗的語言與說明跟著換", cfg["transcription"]["language"] == "en"
          and cfg["transcription"]["use_api"] is True and gen.language_box.currentData() == "en"
          and "用 OpenAI 轉寫" in gen.notice.text() and "轉寫設定已套用" in gen.status.text(), gen.notice.text())
    gen.worker.busy = True
    gen.refresh()
    check("生成中：〔轉寫設定…〕灰掉", not gen.settings_btn.isEnabled())
    gen.worker.busy = False
    gen.refresh()
    gen.close()

    # ----- 8 -----
    check("全程沒寫 config.json", not os.path.exists(config.CONFIG_PATH))
    win.close()
    check("說明文字", "python.exe" in tdlg.PYTHON_NOTE and "文字稿對齊" in tdlg.PROMPT_NOTE)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 轉寫與金鑰設定介面測試全數通過。")
