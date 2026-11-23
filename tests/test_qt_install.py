# -*- coding: utf-8 -*-
"""
3.0 第 11 項第二十九階段：一鍵安裝 ffmpeg、文字辨識（gui_qt/install_dialog.py＋主視窗上方的提示）。

真的下載驗不到（開發環境的出口網路擋官方發行頁、不該在測試裡下載 100 MB）：換掉核心的安裝函式，驗介面與接線。

1. 沒有 ffmpeg：主視窗頁籤上方一條提示＋〔自動安裝 ffmpeg〕；有 ffmpeg 就不出現。各處「找不到 ffmpeg」的說法都指向
   這裡，不再叫人去一般版。
2. ffmpeg 視窗：不擋住主視窗、只建一個；寫明會連到哪（只有從 GitHub 下載）、不送出任何東西。
3. 安裝：背景跑、按鈕灰掉寫「安裝中…」、進度條與訊息跟著核心；裝好講裝在哪、收起視窗、主視窗的提示收起來。
4. 失敗：講原因與解法（白話；核心的 SetupError 原樣）、按鈕變「重試安裝」、可以再按。
5. 安裝中關視窗先問（選否不關）；安裝中關主視窗也先問（選否不關）。
6. 文字辨識視窗：引擎勾不勾照有沒有裝；語言檔照一般版的清單與預設、已安裝的標出來而且不勾；都沒勾講原因；
   交給核心的是勾的那些；安裝中勾選灰掉；裝好列出位置。
7. 即時查譯按「框選螢幕翻譯」時沒裝 tesseract：直接打開主視窗那一個安裝文字辨識視窗。
"""
import os
import sys
import threading
import time

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
    print("SKIP 這個環境沒有 PySide6：略過一鍵安裝")
else:
    import tempfile

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import install_dialog as idlg  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import burner, ffmpeg_setup, ocrengine  # noqa: E402
    from subtitle import tesseract_setup as ts  # noqa: E402
    from subtitle.errors import FriendlyError  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait_until(cond, timeout_ms=10000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(20)
            waited += 20
        return cond()

    def tame(win):
        p = win.player_panel
        p._ask_discard = lambda *a, **k: "discard"
        p._ask_project_discard = lambda *a, **k: "discard"

    real_ffmpeg = burner.ffmpeg_available

    # ----- 1. 主視窗上方的提示 -----
    burner.ffmpeg_available = lambda: True
    with_ff = qt_app.MainWindow({})
    tame(with_ff)
    with_ff.show()
    wait(30)
    check("有 ffmpeg：上方不出現提示", not with_ff.ffmpeg_banner.isVisible())
    with_ff.close()
    burner.ffmpeg_available = lambda: False
    win = qt_app.MainWindow({})
    tame(win)
    win.resize(1280, 800)
    win.show()
    wait(50)
    banner_text = " ".join(w.text() for w in win.ffmpeg_banner.findChildren(QLabel))
    check("沒有 ffmpeg：頁籤上方一條提示＋〔自動安裝 ffmpeg〕", win.ffmpeg_banner.isVisible()
          and win.ffmpeg_install_btn.text() == "自動安裝 ffmpeg" and "找不到 ffmpeg" in banner_text
          and "不需要管理員權限" in banner_text)
    check("提示在頁籤上面", win.ffmpeg_banner.geometry().bottom() <= win.tabs.geometry().top() + 1)
    sources = {}
    folder = os.path.dirname(qt_app.__file__)
    for name in os.listdir(folder):
        if name.endswith(".py"):
            sources[name] = open(os.path.join(folder, name), encoding="utf-8").read()
    stale = [n for n, src in sources.items() if "一般版按「自動安裝" in src or "Qt 預覽版還沒有一鍵安裝" in src]
    check("各處「找不到 ffmpeg」不再叫人去一般版裝", stale == [], str(stale))
    pointing = [n for n, src in sources.items() if "主視窗上方的「自動安裝 ffmpeg」" in src]
    check("各處都指向主視窗上方（輸出、健檢、審片、套版、配樂、批次、音訊轉影片、系列一致性、時間軸）",
          {"output_panel.py", "health_panel.py", "review_panel.py", "branding_box.py", "music_dialog.py",
           "batch_dialog.py", "audiovis_dialog.py", "series_dialog.py", "timeline.py"} <= set(pointing),
          str(sorted(pointing)))

    # ----- 2. ffmpeg 視窗 -----
    check("按之前還沒有視窗", win.ffmpeg_dialog is None)
    QTest.mouseClick(win.ffmpeg_install_btn, Qt.LeftButton)
    wait(30)
    dlg = win.ffmpeg_dialog
    check("按下去開視窗：標題、不擋住主視窗", dlg is not None and dlg.isVisible() and not dlg.isModal()
          and dlg.windowTitle() == "自動安裝 ffmpeg")
    check("寫明只從 GitHub 下載、不送出任何東西", dlg.sends_label.text() == idlg.FFMPEG_SENDS
          and "GitHub" in idlg.FFMPEG_SENDS and "不會送出任何影片、字幕或設定" in idlg.FFMPEG_SENDS)
    check("一開始的說明跟一般版一樣（大小、不需要管理員權限）", "約 80~100 MB" in idlg.FFMPEG_INTRO
          and "不需要管理員權限" in idlg.FFMPEG_INTRO and dlg.status_label.text() == idlg.FFMPEG_HINT)
    QTest.mouseClick(win.ffmpeg_install_btn, Qt.LeftButton)
    check("再按一次：同一個視窗", win.ffmpeg_dialog is dlg)

    # ----- 3. 安裝 -----
    gate = threading.Event()
    real_install = ffmpeg_setup.install_ffmpeg

    def fake_install(progress_cb=None, **kw):
        progress_cb(0.0, "正在連線下載 ffmpeg…")
        progress_cb(0.5, "下載中 50%")
        gate.wait(10)
        return "/程式/tools/ffmpeg/bin"
    ffmpeg_setup.install_ffmpeg = fake_install
    shown = []
    dlg._show_done = lambda text: shown.append(text)
    installed = []
    dlg.installed.connect(lambda r: installed.append(r))
    try:
        QTest.mouseClick(dlg.start_btn, Qt.LeftButton)
        check("安裝中：按鈕灰掉、寫「安裝中…」", dlg.installing() and not dlg.start_btn.isEnabled()
              and dlg.start_btn.text() == "安裝中…")
        check("進度條與訊息跟著核心", wait_until(lambda: dlg.progress_bar.value() == 500)
              and dlg.status_label.text() == "下載中 50%")
        check("安裝中再按：不重來", dlg.start() is False)
        # 5. 安裝中關視窗、關主視窗都先問
        asked = []
        dlg._ask_close_while_installing = lambda: (asked.append("dlg"), False)[1]
        dlg.close()
        check("安裝中關視窗：先問、選否不關", asked == ["dlg"] and dlg.isVisible())
        win._ask_close_while_installing = lambda: (asked.append("win"), False)[1]
        win.close()
        check("安裝中關主視窗：先問、選否不關", asked == ["dlg", "win"] and win.isVisible())
        check("主視窗的問句講下載會中斷", "下載會中斷" in qt_app.CLOSE_WHILE_INSTALLING)
        burner.ffmpeg_available = lambda: True  # 裝好之後真的找得到了
        gate.set()
        check("裝好", wait_until(lambda: not dlg.installing()))
    finally:
        ffmpeg_setup.install_ffmpeg = real_install
    check("裝好：講裝在哪、可以馬上用", shown and "/程式/tools/ffmpeg/bin" in shown[0] and "無需重新啟動" in shown[0]
          and dlg.status_label.text() == shown[0])
    check("裝好：視窗收起來、進度滿格", not dlg.isVisible() and dlg.progress_bar.value() == 1000)
    check("裝好：發出 installed、主視窗上方的提示收起來", installed == ["/程式/tools/ffmpeg/bin"]
          and not win.ffmpeg_banner.isVisible())

    # ----- 4. 失敗 -----
    burner.ffmpeg_available = lambda: False
    win.refresh_ffmpeg_banner()
    check("又找不到：提示回來", win.ffmpeg_banner.isVisible())
    failing = idlg.FfmpegInstallDialog()

    def net_fail(progress_cb=None, **kw):
        raise FriendlyError("ffmpeg 下載失敗", cause="無法從 GitHub 下載安裝檔（連線逾時）。",
                            solution="確認網路後重試；或手動下載。", details="timeout")
    ffmpeg_setup.install_ffmpeg = net_fail
    try:
        failing.start()
        check("失敗也會收尾", wait_until(lambda: not failing.installing()))
    finally:
        ffmpeg_setup.install_ffmpeg = real_install
    text = failing.status_label.text()
    check("失敗：講原因與解法", text.startswith(idlg.FAILED) and "ffmpeg 下載失敗" in text
          and "無法從 GitHub 下載安裝檔" in text and "確認網路後重試" in text, text)
    check("失敗：按鈕變「重試安裝」、可以再按", failing.start_btn.isEnabled() and failing.start_btn.text() == "重試安裝")
    check("核心的 SetupError 原樣講", idlg.failure_text(ts.SetupError("自動安裝目前只支援 Windows。"))
          == idlg.FAILED + "自動安裝目前只支援 Windows。")
    generic = idlg.failure_text(ValueError("壓縮檔壞了"))
    check("不認得的錯：附技術細節", "技術細節：壓縮檔壞了" in generic, generic)
    failing.deleteLater()

    # ----- 6. 文字辨識視窗 -----
    real_avail, real_langs, real_selected = ocrengine.tesseract_available, ts.installed_languages, ts.install_selected
    ocrengine.tesseract_available = lambda: False
    ts.installed_languages = lambda: {"eng"}
    try:
        ocr = win.open_ocr_install()
        check("文字辨識視窗：標題、不擋住、只建一個", ocr.isVisible() and not ocr.isModal()
              and ocr.windowTitle() == "安裝文字辨識（OCR）" and win.open_ocr_install() is ocr)
        check("寫明辨識在本機、只從 GitHub 下載", "畫面不會被傳出去" in idlg.OCR_INTRO and "GitHub" in idlg.OCR_SENDS
              and ocr.sends_label.text() == idlg.OCR_SENDS)
        check("沒裝引擎：引擎勾著、寫大小", ocr.engine_box.isChecked() and "約 50~60 MB" in ocr.engine_box.text())
        check("講明自動裝引擎只支援 Windows（畫面上看得到）", "只支援 Windows" in ocr.engine_note.text()
              and ocr.engine_note.isVisibleTo(ocr) and ocr.isAncestorOf(ocr.engine_note))
        check("語言檔清單跟一般版一樣", list(ocr.lang_boxes) == [c for c, _l in ts.LANGUAGE_LABELS])
        check("已安裝的標出來而且不勾；預設勾日文、繁中", "（已安裝）" in ocr.lang_boxes["eng"].text()
              and not ocr.lang_boxes["eng"].isChecked() and ocr.lang_boxes["jpn"].isChecked()
              and ocr.lang_boxes["chi_tra"].isChecked() and set(ocr.selected_languages()) == {"jpn", "chi_tra"})
        check("一開始的狀態是核心那一句", ocr.status_label.text() == ts.describe_state())
        ocr.engine_box.setChecked(False)
        for cb in ocr.lang_boxes.values():
            cb.setChecked(False)
        check("都沒勾：不裝、講原因", ocr.start() is False and ocr.status_label.text() == idlg.NOTHING_CHOSEN)
        ocr.engine_box.setChecked(True)
        ocr.lang_boxes["jpn"].setChecked(True)
        got = []
        gate2 = threading.Event()

        def fake_selected(want_engine, langs, progress_cb=None):
            got.append((want_engine, list(langs)))
            progress_cb(0.8, "正在下載語言檔…")
            gate2.wait(10)
            return ["/程式/tools/tesseract", "/程式/tools/tessdata"]
        ts.install_selected = fake_selected
        ocr._show_done = lambda text: shown.append(text)
        ocr.start()
        check("交給核心的是勾的那些", wait_until(lambda: got == [(True, ["jpn"])]), str(got))
        check("安裝中勾選灰掉", not ocr.engine_box.isEnabled() and not any(cb.isEnabled() for cb in ocr.lang_boxes.values()))
        gate2.set()
        check("裝好", wait_until(lambda: not ocr.installing()))
        check("裝好：列出位置、收起來", "/程式/tools/tesseract" in shown[-1] and "/程式/tools/tessdata" in shown[-1]
              and "不需要重新啟動" in shown[-1] and not ocr.isVisible())

        ocrengine.tesseract_available = lambda: True
        ts.installed_languages = lambda: {"eng", "jpn"}
        got.clear()
        only = idlg.TesseractInstallDialog()
        only._show_done = lambda text: None
        only.engine_box.setChecked(False)
        for code, cb in only.lang_boxes.items():
            cb.setChecked(code == "chi_tra")
        only.start()
        check("只補語言檔：交給核心的引擎是不裝", wait_until(lambda: got == [(False, ["chi_tra"])]), str(got))
        wait_until(lambda: not only.installing())
        only.deleteLater()
        have = idlg.TesseractInstallDialog()
        check("已裝引擎：引擎不勾、寫「已安裝，可略過」", not have.engine_box.isChecked()
              and have.engine_box.text() == "辨識引擎（已安裝，可略過）")
        check("可以只補語言檔：日文已裝不勾、繁中照預設勾", not have.lang_boxes["jpn"].isChecked()
              and have.lang_boxes["chi_tra"].isChecked())
        have.deleteLater()

        # ----- 7. 即時查譯 -----
        ocrengine.tesseract_available = lambda: False
        ocr.hide()
        look = win.open_lookup()
        check("即時查譯：沒裝 tesseract 按框選 → 打開主視窗那一個安裝視窗", look.start_screen_capture() is False
              and win.ocr_dialog is ocr and ocr.isVisible())
        look.hide()
    finally:
        ocrengine.tesseract_available, ts.installed_languages = real_avail, real_langs
        ts.install_selected = real_selected
        burner.ffmpeg_available = real_ffmpeg

    check("全程沒寫 config.json", not os.path.exists(config.CONFIG_PATH))
    ocr.close()
    win.close()
    time.sleep(0.05)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 一鍵安裝測試全數通過。")
