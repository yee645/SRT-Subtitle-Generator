# -*- coding: utf-8 -*-
"""
3.0 第 11 項第二十六階段：即時查譯（四）——全域熱鍵（gui_qt/hotkey_qt.py、gui_qt/quicklookup_dialog.py）。

核心在 test_hotkey.py；這裡驗 Qt 的接線。這台是 Linux：真的走「只在本程式視窗內有效」那條路（QShortcut）；
Windows 的 `RegisterHotKey` 沒辦法實測，用假的後端（註冊成功／被佔走）把全域那條路走過，`WM_HOTKEY` 用 ctypes 自己組
一個 MSG 結構餵給原生事件過濾器。不連網、不真的截圖（框選層出來就取消或直接回報範圍）。

1. 框選那一列有「熱鍵 Ctrl+Alt+F8」，預設關、不建任何東西。
2. 打開：Linux 退成視窗內有效並講明；按組合鍵（焦點在主視窗）就叫出框選；面板沒開也行，取消不叫出面板。
3. 關掉：不再觸發、講一句；設定只記在這次開啟的設定、不寫 config.json；設定裡本來就開著，面板一建好就啟用。
4. 假的 Windows 後端：註冊成功＝全域、講明；`WM_HOTKEY`（對的編號）觸發、別的訊息不觸發；關掉就取消註冊、拿掉過濾器；
   被佔走：退成視窗內並講是被佔走；連視窗內都綁不上：講註冊不起來、按鈕照樣能用；組合鍵不合法：講怎麼改。
5. 關主視窗：取消註冊（不然程式關了那個組合鍵還被佔著）。收起面板不會取消。
"""
import copy
import ctypes
import os
import sys
import tempfile
import warnings

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
    print("SKIP 這個環境沒有 PySide6：略過全域熱鍵")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QByteArray, QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtGui import QKeySequence  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import hotkey_qt as hq  # noqa: E402
    from gui_qt import quicklookup_dialog as qd  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import hotkey as hk  # noqa: E402
    from subtitle import ocrengine  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")
    ocrengine.tesseract_available = lambda: True  # 只驗叫不叫得出框選，不真的辨識

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait_until(cond, timeout_ms=3000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(20)
            waited += 20
        return cond()

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

    def overlay_up():
        return wait_until(lambda: dlg._overlay is not None)

    def cancel_overlay():
        if dlg._overlay is not None:
            dlg._overlay.cancel()
            wait(50)

    def press_combo(target=None):
        target = target or win
        target.activateWindow()
        with warnings.catch_warnings():  # offscreen 不會自己換使用中的視窗（真的使用時焦點就在本程式的視窗上）
            warnings.simplefilter("ignore", DeprecationWarning)
            QApplication.setActiveWindow(target)
        target.setFocus()
        QTest.keyClick(target, Qt.Key_F8, Qt.ControlModifier | Qt.AltModifier)
        wait(50)

    # ----- 1. 預設 -----
    check("框選那一列有「熱鍵 Ctrl+Alt+F8」", dlg.hotkey_box.text() == "熱鍵 Ctrl+Alt+F8")
    check("預設關、不建任何東西", not dlg.hotkey_box.isChecked() and dlg._hotkey is None
          and dlg.hotkey_status() == "off")
    press_combo()
    check("沒打開：按組合鍵不會叫出框選", dlg._overlay is None and not dlg.ocr_busy())

    # ----- 2. Linux：視窗內有效 -----
    dlg.hotkey_box.setChecked(True)
    check("打開：這台退成只在本程式視窗內有效", dlg.hotkey_status() == "window-only")
    check("講明是視窗內、哪一個組合鍵", "只在本程式視窗內有效" in dlg.screen_status.text()
          and "Ctrl+Alt+F8" in dlg.screen_status.text(), dlg.screen_status.text())
    shortcut = dlg._hotkey.shortcut
    check("視窗內那條路：掛在主視窗、整個程式有效的快捷鍵", shortcut is not None and shortcut.parent() is win
          and shortcut.context() == Qt.ApplicationShortcut
          and shortcut.key() == QKeySequence("Ctrl+Alt+F8"))
    check("設定記在這次開啟的設定", player._config["hotkey"] == {"enabled": True, "combo": "Ctrl+Alt+F8"})

    press_combo()
    check("焦點在主視窗按組合鍵：叫出框選", overlay_up() and dlg.ocr_busy(), dlg.screen_status.text())
    cancel_overlay()
    check("取消：面板原本開著就回來", dlg.isVisible() and not dlg.ocr_busy())

    dlg.close()
    check("收起面板：熱鍵照樣有效（不取消）", dlg.hotkey_status() == "window-only")
    dlg.screen_status.setText("（標記）")
    press_combo()
    check("面板沒開時按：照樣叫出框選", overlay_up())
    cancel_overlay()
    check("面板原本沒開：取消後不叫出面板", not dlg.isVisible() and dlg.screen_status.text() == "（標記）")

    press_combo()
    overlay_up()
    dlg._overlay.selected.emit((10, 10, 2, 2))  # 範圍太小：一定會講原因、叫出面板
    wait(100)
    check("面板沒開時框完：叫出面板講結果", dlg.isVisible() and "太小" in dlg.screen_status.text())

    # ----- 3. 關掉 -----
    dlg.hotkey_box.setChecked(False)
    check("關掉：講一句、狀態 off", dlg.screen_status.text() == "熱鍵 Ctrl+Alt+F8 已關閉。" and dlg.hotkey_status() == "off")
    check("關掉：快捷鍵拿掉", dlg._hotkey.shortcut is None)
    press_combo()
    check("關掉之後按：不觸發", dlg._overlay is None and not dlg.ocr_busy())
    check("關掉也記進這次開啟的設定", player._config["hotkey"]["enabled"] is False)

    dlg2 = qd.QuickLookupDialog(player, win.cue_panel, win)
    check("下一個面板沿用：關著", not dlg2.hotkey_box.isChecked() and dlg2._hotkey is None)
    dlg2.deleteLater()
    player._config["hotkey"] = {"enabled": True, "combo": "alt+shift+f9"}
    dlg3 = qd.QuickLookupDialog(player, win.cue_panel, win)
    check("設定裡開著：一建好就啟用、組合鍵正規化", dlg3.hotkey_box.isChecked() and dlg3.hotkey_status() == "window-only"
          and dlg3.hotkey_box.text() == "熱鍵 Alt+Shift+F9" and dlg3._hotkey.shortcut.key() == QKeySequence("Alt+Shift+F9"))
    dlg3.shutdown()
    check("關掉那個面板（shutdown）：取消", dlg3.hotkey_status() == "off")
    dlg3.deleteLater()
    player._config["hotkey"] = {"enabled": False, "combo": "Ctrl+Alt+F8"}

    # ----- 4. 假的 Windows 後端 -----
    class FakeWindowsBackend(hk.WindowsBackend):
        def __init__(self, mode="ok"):
            super().__init__(hwnd=1234)
            self.mode = mode
            self.calls = []

        def register(self, parsed):
            self.calls.append(("register", parsed["text"], parsed["vk"], parsed["flags"]))
            if self.mode == "taken":
                raise hk.HotkeyTakenError("已經被其他程式註冊走了")
            self._registered = True
            return True

        def unregister(self):
            self.calls.append(("unregister",))
            self._registered = False

    backend = FakeWindowsBackend()
    real_make = qd.QuickLookupDialog._make_hotkey
    dlg._hotkey = None
    dlg._make_hotkey = lambda: hq.QtHotkey(win, backend=backend)
    dlg.hotkey_box.setChecked(True)
    registered = [c for c in backend.calls if c[0] == "register"]
    check("註冊成功：全域", dlg.hotkey_status() == "global" and registered and registered[0][:2] == ("register", "Ctrl+Alt+F8"))
    check("講明在任何程式裡按都有效", dlg.screen_status.text().startswith("全域熱鍵已啟用")
          and "Ctrl+Alt+F8" in dlg.screen_status.text())
    check("註冊的是 F8、Ctrl＋Alt、不重複觸發", registered[0][2] == 0x77
          and registered[0][3] == hk.MOD_CONTROL | hk.MOD_ALT | hk.MOD_NOREPEAT)
    check("全域：不另外綁視窗內快捷鍵、裝了原生事件過濾器", dlg._hotkey.shortcut is None and dlg._hotkey._filter is not None)

    msg = hq._MSG()
    msg.message = hq.WM_HOTKEY
    msg.wParam = backend.hotkey_id
    native = dlg._hotkey._filter
    other = hq._MSG()
    other.message = 0x0100  # WM_KEYDOWN（編號剛好一樣也不算）
    other.wParam = backend.hotkey_id
    check("別的訊息：不觸發、不攔", native.nativeEventFilter(QByteArray(b"windows_generic_MSG"),
                                                         ctypes.addressof(other))[0] is False and dlg._overlay is None)
    wrong = hq._MSG()
    wrong.message = hq.WM_HOTKEY
    wrong.wParam = backend.hotkey_id + 1
    check("別的熱鍵編號：不觸發", native.nativeEventFilter(QByteArray(b"windows_generic_MSG"),
                                                       ctypes.addressof(wrong))[0] is False and dlg._overlay is None)
    check("不是 Windows 的事件：不觸發", hq.is_hotkey_message(QByteArray(b"xcb_generic_event_t"), ctypes.addressof(msg),
                                                         backend.hotkey_id) is False
          and hq.is_hotkey_message(QByteArray(b"windows_generic_MSG"), 0, backend.hotkey_id) is False)
    handled = native.nativeEventFilter(QByteArray(b"windows_generic_MSG"), ctypes.addressof(msg))
    check("WM_HOTKEY：攔下來、叫出框選", handled[0] is True and overlay_up())
    cancel_overlay()

    dlg.hotkey_box.setChecked(False)
    check("關掉：取消註冊、拿掉過濾器", backend.calls[-1] == ("unregister",) and dlg._hotkey._filter is None)

    taken = FakeWindowsBackend("taken")
    dlg._hotkey = None
    dlg._make_hotkey = lambda: hq.QtHotkey(win, backend=taken)
    dlg.hotkey_box.setChecked(True)
    check("被佔走：退成視窗內、講是被別的程式佔走", dlg.hotkey_status() == "window-only"
          and "已經被別的程式佔走" in dlg.screen_status.text() and dlg._hotkey._filter is None, dlg.screen_status.text())
    press_combo()
    check("被佔走時視窗內照樣有效", overlay_up())
    cancel_overlay()
    dlg.hotkey_box.setChecked(False)

    real_bind = hq.QtHotkey._bind
    hq.QtHotkey._bind = lambda self, seq: False
    dlg._hotkey = None
    dlg._make_hotkey = lambda: hq.QtHotkey(win, backend=hk.NullBackend())
    dlg.hotkey_box.setChecked(True)
    check("連視窗內都綁不上：講註冊不起來、按鈕照樣能用", dlg.hotkey_status() == "unavailable"
          and "註冊不起來" in dlg.screen_status.text() and "按鈕" in dlg.screen_status.text(), dlg.screen_status.text())
    hq.QtHotkey._bind = real_bind
    dlg.hotkey_box.setChecked(False)

    real_seq = hk.to_qt_sequence
    hq.hk.to_qt_sequence = lambda text: ""  # QKeySequence 認不得就是空的
    dlg._hotkey = None
    dlg.hotkey_box.setChecked(True)
    check("換成 Qt 寫法認不得：不綁空的快捷鍵、講註冊不起來", dlg.hotkey_status() == "unavailable"
          and dlg._hotkey.shortcut is None and "註冊不起來" in dlg.screen_status.text())
    hq.hk.to_qt_sequence = real_seq
    dlg.hotkey_box.setChecked(False)

    dlg.hotkey_settings["combo"] = "F8"
    dlg.hotkey_box.setChecked(True)
    check("組合鍵不合法：講怎麼改", "至少要搭" in dlg.screen_status.text() and dlg.hotkey_status() != "global",
          dlg.screen_status.text())
    dlg.hotkey_box.setChecked(False)
    dlg.hotkey_settings["combo"] = "Ctrl+Alt+F8"

    # Qt 的寫法每一個都認得
    combos = ["Ctrl+Space", "Alt+Enter", "Ctrl+Tab", "Ctrl+Insert", "Ctrl+Delete", "Ctrl+Home", "Ctrl+End",
              "Ctrl+PageUp", "Ctrl+PageDown", "Ctrl+Left", "Ctrl+Up", "Ctrl+Right", "Ctrl+Down", "Ctrl+Backslash",
              "Win+Shift+A", "Ctrl+Alt+F12", "Alt+7"]
    bad = [c for c in combos if QKeySequence(hk.to_qt_sequence(c)).isEmpty()
           or QKeySequence(hk.to_qt_sequence(c)).count() != 1]
    check("每一種組合鍵換成 Qt 的寫法都認得", bad == [], bad)
    check("這台（不是 Windows）：不註冊全域、直接退成視窗內", sys.platform == "win32"
          or isinstance(hq.make_backend(win), hk.NullBackend))

    # ----- 5. 關主視窗 -----
    final = FakeWindowsBackend()
    dlg._hotkey = None
    dlg._make_hotkey = lambda: hq.QtHotkey(win, backend=final)
    dlg.hotkey_box.setChecked(True)
    dlg.close()
    check("收起面板：不取消註冊", final.calls[-1][0] == "register" and dlg.hotkey_status() == "global")
    win.close()
    check("關主視窗：取消註冊", final.calls[-1] == ("unregister",) and dlg.hotkey_status() == "off")
    check("全程沒寫 config.json", not os.path.exists(config.CONFIG_PATH))
    qd.QuickLookupDialog._make_hotkey = real_make
    player.shutdown()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 全域熱鍵測試全數通過。")
