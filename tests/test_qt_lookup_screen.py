# -*- coding: utf-8 -*-
"""
3.0 第 11 項第二十五階段：即時查譯（三）——框選螢幕翻譯（gui_qt/region_overlay.py、gui_qt/quicklookup_dialog.py）。

核心在 test_screentranslate*.py、test_ocrengine*.py、test_screencap*.py；這裡驗介面與接線。
`translate_snippet` 換成假的（不連網）。**辨識用真的 tesseract**（沒裝就略過需要它的部分）：截圖換成「用 Qt 畫一張
有字的圖」，其餘（存 BMP、辨識、決定送不送）都走真的。最後一段在 Xvfb 上用 xcb 平台真的 `grabWindow` 截一個
有字的視窗再辨識（沒有 DISPLAY 就略過）。

1. 面板上有〔框選螢幕翻譯〕〔翻譯辨識結果〕與說明（畫面不會被傳出去）；沒裝 tesseract 講怎麼裝、不開框選層。
2. 框選層：蓋住螢幕、面板先收起來；Esc、右鍵、被關掉都算取消（面板回來、講一句）；面板原本沒開就不叫出來；
   辨識中再按講「還在辨識」。
3. 拖一塊（兩個方向都行）→ 截那一塊 → 本機辨識 → 原文框（可改）；什麼都沒送；按〔翻譯辨識結果〕才送，送的是改過的原文。
4. 擋下：範圍太小（不截）、整塊同一個顏色、像密碼（按鈕灰掉；改成密碼再按也不送）；沒金鑰：辨識照做、翻譯講沒金鑰。
5. 設定打開自動送出且辨識得清楚：直接送。截圖暫存檔用完就刪。關主視窗時框選層收掉、面板不再叫出來。
"""
import copy
import glob
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

REAL_SCRIPT = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel
from gui_qt import region_overlay as ro
from subtitle import screentranslate as st
app = QApplication([])
label = QLabel("Select this line to translate")
label.setWindowFlags(Qt.FramelessWindowHint)
label.setStyleSheet("background: white; color: black; padding: 12px;")
font = QFont(); font.setPixelSize(40); label.setFont(font)
label.move(60, 60); label.resize(760, 90); label.show()
loop = QEventLoop(); QTimer.singleShot(600, loop.quit); loop.exec()
screen = app.primaryScreen()
region = (60, 60, 760, 90)
image = ro.grab_region(screen, region)
result = st.capture_and_recognize(region, capture=ro.image_capture(image))
print("OCR:" + result["text"].replace("\n", " "))
'''

if PySide6 is None:
    print("SKIP 這個環境沒有 PySide6：略過框選螢幕翻譯")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, Qt, QTimer  # noqa: E402
    from PySide6.QtGui import QColor, QFont, QImage, QMouseEvent, QPainter  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import quicklookup_dialog as qd  # noqa: E402
    from gui_qt import region_overlay as ro  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import ocrengine  # noqa: E402
    from subtitle import quicklookup as ql  # noqa: E402
    from subtitle import quicktranslate as qt  # noqa: E402
    from subtitle import screencap  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")
    shots = os.path.join(tmp, "暫存")
    os.makedirs(shots)
    tempfile.tempdir = shots  # 截圖暫存檔放這裡，才看得出有沒有刪
    HAVE_TESSERACT = ocrengine.tesseract_available()

    import shiboken6  # noqa: E402

    def shown(widget):
        """框選層關掉就刪掉自己（WA_DeleteOnClose）：刪掉了也算沒顯示。"""
        return widget is not None and shiboken6.isValid(widget) and widget.isVisible()

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait_until(cond, timeout_ms=20000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(30)
            waited += 30
        return cond()

    sent = []

    def fake_translate(text, api_key, settings=None, cache=None):
        sent.append(text)
        return {"source": qt.normalize_snippet(text), "translation": "這是譯文。", "terms": [], "cached": False}

    qt.translate_snippet = fake_translate

    def text_image(text, width=640, height=110, color="white"):
        image = QImage(width, height, QImage.Format_RGB32)
        image.fill(QColor(color))
        if text:
            painter = QPainter(image)
            font = QFont()
            font.setPixelSize(42)
            painter.setFont(font)
            painter.setPen(QColor("black"))
            painter.drawText(image.rect(), Qt.AlignCenter, text)
            painter.end()
        return image

    grabs = []
    next_image = {"text": None, "color": "white", "null": False}
    TEXT_AT = (40, 300)  # 假螢幕上字畫在這裡（640x110 的一塊）

    def fake_grab(self, screen):
        """假的整個螢幕：白底（或指定顏色），TEXT_AT 那塊寫著字。"""
        grabs.append(screen.geometry().size().toTuple())
        if next_image["null"]:
            return QImage()
        g = screen.geometry()
        image = QImage(g.width(), g.height(), QImage.Format_RGB32)
        image.fill(QColor(next_image["color"]))
        if next_image["text"]:
            painter = QPainter(image)
            painter.drawImage(QPoint(*TEXT_AT), text_image(next_image["text"]))
            painter.end()
        return image

    qd.QuickLookupDialog._grab = fake_grab

    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["transcription"].update(api_key="sk-test-0000")
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.show()
    wait(100)
    player = win.player_panel
    player._ask_discard = lambda *a, **k: "discard"
    player._ask_project_discard = lambda *a, **k: "discard"
    dlg = win.open_lookup()
    wait(50)

    # ----- 1. 一列與說明 -----
    check("有〔框選螢幕翻譯〕〔翻譯辨識結果〕", dlg.screen_btn.text() == "框選螢幕翻譯"
          and dlg.ocr_translate_btn.text() == "翻譯辨識結果")
    check("〔翻譯辨識結果〕一開始灰掉", not dlg.ocr_translate_btn.isEnabled())
    check("說明：畫面不會被傳出去、確認後再翻譯", dlg.screen_status.text() == ql.C30_SCREEN_HINT
          and "畫面不會被傳出去" in ql.C30_SCREEN_HINT and "確認後再翻譯" in ql.C30_SCREEN_HINT)

    real_available = ocrengine.tesseract_available
    ocrengine.tesseract_available = lambda: False
    opened_install = []
    real_open_install = dlg._open_ocr_install
    dlg._open_ocr_install = lambda: opened_install.append(1)
    check("沒裝 tesseract：不開框選層、講怎麼裝", dlg.start_screen_capture() is False and dlg._overlay is None
          and not dlg.ocr_busy() and dlg.screen_status.text() == qd.NEED_TESSERACT and dlg.isVisible())
    check("怎麼裝：直接打開安裝文字辨識的視窗（也可以自行安裝）", opened_install == [1]
          and "已經打開「安裝文字辨識」視窗" in qd.NEED_TESSERACT and "PATH" in qd.NEED_TESSERACT
          and "一般版" not in qd.NEED_TESSERACT)
    dlg._open_ocr_install = real_open_install
    ocrengine.tesseract_available = lambda: True

    # ----- 2. 框選層與取消 -----
    crops = []
    real_crop = ro.crop_image

    def recording_crop(image, screen, region):
        crops.append(tuple(region))
        return real_crop(image, screen, region)

    ro.crop_image = recording_crop

    def start_and_wait_overlay():
        started = dlg.start_screen_capture()
        wait_until(lambda: dlg._overlay is not None, 2000)
        return started, dlg._overlay

    started = dlg.start_screen_capture()
    check("開始框選：回報有開始、面板先收起來、還沒截（等畫面更新）", started is True and not dlg.isVisible()
          and grabs == [] and dlg._overlay is None and dlg.ocr_busy())
    wait_until(lambda: dlg._overlay is not None, 2000)
    overlay = dlg._overlay
    check("等一下才截整個螢幕、鋪在框選層底下", len(grabs) == 1 and overlay.background is dlg._frozen
          and not overlay.background.isNull())
    check("框選層蓋住螢幕", shown(overlay) and overlay.geometry() == app.primaryScreen().geometry())
    check("框選中：忙、按鈕灰掉", dlg.ocr_busy() and not dlg.screen_btn.isEnabled())
    check("框選層：無邊框、置頂、不靠半透明（沒有合成器也看得到）",
          bool(overlay.windowFlags() & Qt.FramelessWindowHint) and bool(overlay.windowFlags() & Qt.WindowStaysOnTopHint)
          and not overlay.testAttribute(Qt.WA_TranslucentBackground))
    check("辨識中再按：講還在辨識、面板叫出來", dlg.start_screen_capture() is False
          and dlg.screen_status.text() == ql.C38_OCR_BUSY and dlg.isVisible())
    dlg.hide()
    QTest.keyClick(overlay, Qt.Key_Escape)
    wait(50)
    check("Esc 取消：框選層收掉、面板回來、講一句", not shown(overlay) and dlg.isVisible()
          and dlg.screen_status.text() == ql.C32_OCR_CANCELLED and not dlg.ocr_busy() and dlg.screen_btn.isEnabled())
    check("取消：沒裁、截圖丟掉", crops == [] and dlg._frozen is None)
    check("取消之後照樣看選取", dlg.watching())

    _, overlay = start_and_wait_overlay()
    QTest.mouseClick(overlay, Qt.RightButton, pos=QPoint(50, 50))
    wait(50)
    check("右鍵取消", not shown(overlay) and dlg.isVisible() and dlg.screen_status.text() == ql.C32_OCR_CANCELLED)

    _, overlay = start_and_wait_overlay()
    overlay.close()
    wait(50)
    check("框選層被關掉也算取消", dlg.isVisible() and not dlg.ocr_busy()
          and dlg.screen_status.text() == ql.C32_OCR_CANCELLED)

    dlg.screen_status.setText("（標記）")
    dlg.close()
    dlg.start_screen_capture()
    dlg._was_visible = False  # 例如熱鍵叫出來的：面板原本沒開
    wait_until(lambda: dlg._overlay is not None, 2000)
    dlg._overlay.cancel()
    wait(50)
    check("面板原本沒開：取消後不叫出來", not dlg.isVisible() and not dlg.ocr_busy()
          and dlg.screen_status.text() == "（標記）")
    win.open_lookup()

    def drag(x0, y0, x1, y1):
        _, overlay = start_and_wait_overlay()
        QTest.mousePress(overlay, Qt.LeftButton, pos=QPoint(x0, y0))
        # QTest.mouseMove 在 offscreen 不會送到視窗：自己送一個按著左鍵的移動事件
        point = QPointF(x1, y1)
        QApplication.sendEvent(overlay, QMouseEvent(QEvent.MouseMove, point, overlay.mapToGlobal(point),
                                                    Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        check_marquee = overlay.marquee()
        QTest.mouseRelease(overlay, Qt.LeftButton, pos=QPoint(x1, y1))
        return overlay, check_marquee

    # ----- 4a. 範圍太小 -----
    overlay, _ = drag(200, 200, 203, 202)
    wait(100)
    check("只點一下：不裁、講範圍太小", crops == [] and "太小" in dlg.screen_status.text()
          and dlg.screen_status.text().startswith("螢幕翻譯失敗：") and not dlg.ocr_busy() and dlg.isVisible())
    check("範圍太小：截圖也丟掉", dlg._frozen is None)

    # ----- 4b. 整塊同一個顏色 -----
    next_image["color"] = "black"
    drag(100, 100, 500, 200)
    check("整塊同一個顏色：講原因", wait_until(lambda: "同一個顏色" in dlg.screen_status.text())
          and not dlg.ocr_busy(), dlg.screen_status.text())
    check("裁的是拖出來那一塊", crops[-1] == (100, 100, 400, 100), crops)
    next_image["color"] = "white"
    next_image["null"] = True
    drag(100, 100, 500, 200)
    check("截不到圖：講擷取結果是空的", wait_until(lambda: screencap.EMPTY_CAPTURE_MESSAGE.rstrip("。") in dlg.screen_status.text()),
          dlg.screen_status.text())
    next_image["null"] = False
    geometry = app.primaryScreen().geometry()
    _, overlay = start_and_wait_overlay()
    overlay.cancel()
    _, overlay = start_and_wait_overlay()
    overlay.selected.emit((geometry.width() - 50, 10, 300, 200))  # 拖到螢幕外面
    wait(100)
    check("拖出螢幕邊緣：夾回螢幕範圍內再裁", crops[-1] == (geometry.width() - 50, 10, 50, 200), crops[-1:])
    wait_until(lambda: not dlg.ocr_busy())
    overlay.close()
    next_image["text"] = "Open the settings menu"
    drag(700, 20, 790, 80)
    check("框到螢幕上沒字的地方（白的）：講同一個顏色", wait_until(lambda: "同一個顏色" in dlg.screen_status.text()),
          dlg.screen_status.text())

    if not HAVE_TESSERACT:
        print("SKIP 這台沒有 tesseract：略過真的辨識")
    else:
        ocrengine.tesseract_available = real_available
        # ----- 3. 真的辨識 -----
        next_image["text"] = "Open the settings menu"
        dlg.status_label.setText("（上一次的翻譯完成）")
        overlay, marquee = drag(680, 410, 40, 300)
        check("拖的時候畫出選取框（跟裁的範圍一樣大）", marquee is not None and marquee.width() == 640
              and marquee.height() == 110)
        check("放開：框選層先收起來", not shown(overlay))
        check("反方向拖也對：裁出字的那一塊", wait_until(lambda: len(crops) >= 3) and crops[-1] == (40, 300, 640, 110), crops)
        check("辨識中：講在這台電腦上跑", dlg.screen_status.text() == ql.C31_OCR_RUNNING and dlg.isVisible())
        check("辨識完成", wait_until(lambda: not dlg.ocr_busy()), dlg.screen_status.text())
        check("辨識出來的字放進原文框", "settings" in dlg.src_text.toPlainText().lower(), dlg.src_text.toPlainText())
        check("講辨識結果與秒數、等確認", dlg.screen_status.text().startswith("辨識完成")
              and "秒" in dlg.screen_status.text(), dlg.screen_status.text())
        check("什麼都還沒送", sent == [])
        check("下面的狀態清掉（免得以為這段也翻好了）", dlg.status_label.text() == "")
        old_text = dlg.src_text.toPlainText()
        dlg._on_ocr_finished(dlg._ocr_id - 1, {"text": "Stale result", "mean_conf": 95, "verdict": "ok"})
        check("舊的辨識結果晚回來：作廢", dlg.src_text.toPlainText() == old_text)
        check("原文框可以改、〔翻譯辨識結果〕可按", not dlg.src_text.isReadOnly() and dlg.ocr_translate_btn.isEnabled())
        check("截圖暫存檔用完就刪", glob.glob(os.path.join(shots, "srtgen_screen_*")) == [])

        dlg.src_text.setPlainText("Open the settings menu now")
        dlg.ocr_translate_btn.click()
        check("按了才送：送的是改過的原文", wait_until(lambda: sent == ["Open the settings menu now"]), sent)
        check("送出後按鈕灰掉", not dlg.ocr_translate_btn.isEnabled())
        wait_until(lambda: dlg.status_label.text() in (qd.DONE, qd.DONE_SAVED))
        check("翻好：原文框回到唯讀、譯文顯示", dlg.src_text.isReadOnly() and dlg.dst_text.toPlainText() == "這是譯文。")

        # ----- 4c. 像密碼 -----
        next_image["text"] = "Password: hunter2"
        drag(40, 300, 680, 410)
        wait_until(lambda: not dlg.ocr_busy())
        check("框到像密碼的：擋下、按鈕灰掉、講原因", not dlg.ocr_translate_btn.isEnabled()
              and "密碼" in dlg.screen_status.text() and len(sent) == 1, dlg.screen_status.text())
        check("擋下來的照樣放進原文框（可以朗讀、複製）", "hunter2" in dlg.src_text.toPlainText(), dlg.src_text.toPlainText())

        next_image["text"] = "Open the settings menu"
        drag(40, 300, 680, 410)
        wait_until(lambda: not dlg.ocr_busy())
        dlg.src_text.setPlainText("sk-proj-abcdefghijklmnopqrstuvwxyz0123456789")
        check("改成像金鑰再按：送之前再檢查一次、不送", dlg.translate_ocr() is False and len(sent) == 1
              and dlg.status_label.text().startswith("框到的內容看起來像密碼"), dlg.status_label.text())
        dlg.src_text.setPlainText("   ")
        check("改成空的再按：不送、講沒讀到字", dlg.translate_ocr() is False and len(sent) == 1
              and "沒有讀到任何文字" in dlg.status_label.text(), dlg.status_label.text())

        # ----- 4d. 沒金鑰 -----
        player._config["transcription"]["api_key"] = ""
        dlg.close()
        win.open_lookup()
        drag(40, 300, 680, 410)
        wait_until(lambda: not dlg.ocr_busy())
        check("沒金鑰：辨識照做、譯文區留著說明", "settings" in dlg.src_text.toPlainText().lower()
              and dlg.dst_text.toPlainText() == qd.NOKEY_BODY)
        check("沒金鑰：按翻譯講沒金鑰、不送、按鈕還能按", dlg.translate_ocr() is False
              and dlg.status_label.text() == qd.NOKEY_STATUS and len(sent) == 1 and dlg.ocr_translate_btn.isEnabled())
        player._config["transcription"]["api_key"] = "sk-test-0000"
        dlg.close()
        win.open_lookup()

        # ----- 5. 自動送出 -----
        dlg.screen_settings["auto_send_ok"] = True
        next_image["text"] = "Restart the game"
        drag(40, 300, 680, 410)
        check("自動送出打開、辨識得清楚：直接送", wait_until(lambda: len(sent) == 2), dlg.screen_status.text())
        check("自動送出：送的是辨識出來的字", "restart" in sent[-1].lower(), sent)
        dlg.screen_settings["auto_send_ok"] = False

        # ----- 真的截圖（Xvfb＋xcb） -----
        display = os.environ.get("DISPLAY") or ":99"
        probe = subprocess.run(["xdpyinfo", "-display", display], capture_output=True) if shutil.which("xdpyinfo") else None
        if probe is None or probe.returncode != 0:
            print("SKIP 沒有 X 顯示：略過真的 grabWindow")
        else:
            script = os.path.join(tmp, "real_grab.py")
            with open(script, "w", encoding="utf-8") as fp:
                fp.write(REAL_SCRIPT)
            env = dict(os.environ, QT_QPA_PLATFORM="xcb", DISPLAY=display)
            run = subprocess.run([sys.executable, script, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))],
                                 env=env, capture_output=True, text=True, timeout=120)
            lines = [line for line in run.stdout.splitlines() if line.startswith("OCR:")]
            check("真的 grabWindow 截一個有字的視窗、真的辨識", bool(lines) and "translate" in lines[0].lower(),
                  run.stdout[-300:] + run.stderr[-300:])

    # ----- 關主視窗 -----
    ocrengine.tesseract_available = lambda: True
    dlg.start_screen_capture()
    win.close()
    wait(400)
    check("面板收起來、還沒截就關主視窗：不截、不開框選層、不忙", dlg._overlay is None and not dlg.ocr_busy()
          and not dlg.isVisible())
    win.show()
    win.open_lookup()
    _, overlay = start_and_wait_overlay()
    dlg.screen_status.setText("（關之前）")
    win.close()
    wait(50)
    check("框選中關主視窗：框選層收掉、面板不叫出來、不講取消", not shown(overlay) and not dlg.isVisible()
          and not dlg.ocr_busy() and dlg.screen_status.text() == "（關之前）")
    check("全程沒寫 config.json", not os.path.exists(config.CONFIG_PATH))
    player.shutdown()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 框選螢幕翻譯測試全數通過。")
