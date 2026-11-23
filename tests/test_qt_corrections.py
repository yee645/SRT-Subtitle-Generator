# -*- coding: utf-8 -*-
"""
3.0 第 11 項第三十三階段：②逐句校對「尋找取代」的自動修正詞庫（gui_qt/cue_panel.py＋gui_qt/corrections_dialog.py）。

規則在 test_correctionrules.py；這裡 QTest 真的點：

1. 尋找取代展開後有〔存為自動修正〕〔自動修正詞庫…〕；沒打要找的字時〔存為自動修正〕灰掉（沒字幕也能存）。
2. 〔存為自動修正〕：寫進這次開啟的設定（尋找去空白、換成原樣、區分大小寫照勾選）；說明講之後生成自動套用、
   **現在的字幕沒有改**（字幕真的沒動）；同一個尋找再存＝換掉舊的。
3. 〔自動修正詞庫…〕：不擋主視窗；清單照一般版的寫法、講共幾條；選一條〔刪除選取規則〕→ 設定少一條、逐句校對講一句；
   沒選時刪除灰掉、硬按只提示；開著時再存一條，清單跟著多一條。
4. 生成字幕時真的套用存下的規則（pipeline 換成假的 Whisper，看生成出來的字幕）。
5. 全程沒寫 config.json。
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
    print("SKIP 這個環境沒有 PySide6：略過自動修正詞庫介面")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import corrections_dialog as cd  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import pipeline  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["corrections"] = [{"find": "youtube", "replace": "YouTube", "case": True}]
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.tabs.setCurrentIndex(1)
    win.show()
    wait(100)
    panel, cp = win.player_panel, win.cue_panel
    panel._ask_discard = lambda *a, **k: "discard"
    panel._ask_project_discard = lambda *a, **k: "discard"

    # ----- 1 -----
    cp.show_find()
    wait(50)
    check("尋找取代裡有兩顆新按鈕", cp.save_rule_btn.isVisible() and cp.rules_btn.isVisible()
          and cp.save_rule_btn.text() == "存為自動修正" and cp.rules_btn.text() == "自動修正詞庫…")
    check("沒打要找的字：〔存為自動修正〕灰掉", not cp.save_rule_btn.isEnabled() and cp.rules_btn.isEnabled())
    cp.find_edit.setText("   ")
    check("只打空白：一樣灰掉", not cp.save_rule_btn.isEnabled())
    cp.find_edit.setText("達聞西")
    check("沒字幕也能存規則", not panel.cues and cp.save_rule_btn.isEnabled())

    # ----- 2 -----
    panel.set_cues([{"start": 0.0, "end": 2.0, "text": "達聞西說嗯嗯"}])
    cp.find_edit.setText(" 達聞西 ")
    cp.replace_edit.setText("達文西")
    QTest.mouseClick(cp.save_rule_btn, Qt.LeftButton)
    check("存進這次開啟的設定（尋找去空白、放最後）", cfg["corrections"][-1] == {
        "find": "達聞西", "replace": "達文西", "case": False} and len(cfg["corrections"]) == 2, str(cfg["corrections"]))
    check("說明：之後生成自動套用、現在的字幕沒有改", "之後每次生成字幕自動套用" in cp.note.text()
          and "現在的字幕沒有改" in cp.note.text())
    check("字幕真的沒動", panel.cues[0]["text"] == "達聞西說嗯嗯")
    cp.replace_edit.setText("達文西（畫家）")
    cp.case_box.setChecked(True)
    QTest.mouseClick(cp.save_rule_btn, Qt.LeftButton)
    check("同一個尋找再存：換掉舊的（區分大小寫照勾選）", len(cfg["corrections"]) == 2 and cfg["corrections"][-1] == {
        "find": "達聞西", "replace": "達文西（畫家）", "case": True})
    check("有字：直接呼叫也存得了（換掉同一條、不重複）", cp.save_correction() is True and len(cfg["corrections"]) == 2)
    cp.find_edit.setText("")
    check("沒打字硬按：講要先填、不存", cp.save_correction() is False and "「尋找」" in cp.note.text()
          and len(cfg["corrections"]) == 2)

    # ----- 3 -----
    QTest.mouseClick(cp.rules_btn, Qt.LeftButton)
    dlg = cp.corrections_dialog
    check("詞庫視窗：不擋主視窗", dlg is not None and dlg.isVisible() and not dlg.isModal())
    items = [dlg.list.item(i).text() for i in range(dlg.list.count())]
    check("清單照一般版的寫法、講共幾條", items == ["youtube → YouTube（區分大小寫）", "達聞西 → 達文西（畫家）（區分大小寫）"]
          and dlg.count.text() == "共 2 條。", str(items))
    check("說明講生成時自動套用、怎麼新增", dlg.note.text() == cd.NOTE and "生成字幕" in cd.NOTE and "存為自動修正" in cd.NOTE)
    check("沒選：刪除灰掉", not dlg.delete_btn.isEnabled())
    warned = []
    dlg._warn = lambda text: warned.append(text)
    check("沒選硬按：只提示", dlg.delete_selected() is False and warned and len(cfg["corrections"]) == 2)
    cp.find_edit.setText("嗯嗯")
    cp.replace_edit.setText("")
    cp.case_box.setChecked(False)
    QTest.mouseClick(cp.save_rule_btn, Qt.LeftButton)
    check("開著時再存一條：清單跟著多", dlg.list.count() == 3 and dlg.list.item(2).text() == "嗯嗯 → （刪除）"
          and dlg.count.text() == "共 3 條。")
    dlg.list.setCurrentRow(0)
    check("選了：刪除可以按", dlg.delete_btn.isEnabled())
    QTest.mouseClick(dlg.delete_btn, Qt.LeftButton)
    check("刪除選取規則：設定少一條、逐句校對講一句", [r["find"] for r in cfg["corrections"]] == ["達聞西", "嗯嗯"]
          and dlg.list.count() == 2 and cp.note.text() == "已刪除選取的規則。")
    dlg.close()
    cfg["corrections"] = []
    QTest.mouseClick(cp.rules_btn, Qt.LeftButton)
    check("沒有規則：講還沒有", dlg.list.count() == 0 and dlg.count.text() == cd.EMPTY)
    cfg["corrections"] = [{"find": "達聞西", "replace": "達文西", "case": False}]
    dlg.close()

    # ----- 4 -----
    real = pipeline.transcribe  # 開發環境裝不了 Whisper：換掉轉寫那一步，斷句與自動修正照真的跑

    def fake_transcribe(path, config, report=None):
        return [{"start": 0.0, "end": 1.5, "word": "達聞西"}, {"start": 1.5, "end": 3.0, "word": "畫的"}]
    pipeline.transcribe = fake_transcribe
    try:
        try:
            media = os.path.join(tmp, "x.wav")
            open(media, "wb").close()  # 只要檔案在：轉寫換成假的
            cues, corrected = pipeline.generate_cues(media, cfg, "transcribe", "", lambda *a: None)
            ok = "達文西" in "".join(c["text"] for c in cues) and corrected >= 1
            extra = str(cues)
        except Exception as exc:  # noqa: BLE001
            ok, extra = False, repr(exc)
    finally:
        pipeline.transcribe = real
    check("生成字幕時真的套用存下的規則", ok, extra)

    # ----- 5 -----
    check("全程沒寫 config.json", not os.path.exists(config.CONFIG_PATH))
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 自動修正詞庫介面測試全數通過。")
