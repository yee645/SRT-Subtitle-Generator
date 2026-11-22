# -*- coding: utf-8 -*-
"""
3.0 第 11 項第二十八階段：Qt 版關掉時把設定存回 config.json（gui_qt/app.py 的 save_settings）。

合併規則在 test_configmerge.py；這裡驗真的開視窗、改設定、關掉之後磁碟上的檔。

1. 自己讀設定檔的主視窗才存（`main()` 開的那種）；測試給一份設定進來的不存；自檢模式不存。
2. 在 Qt 改了③的勾選、系列一致性的容許差異；開著的期間「一般版」改了別的區塊、加了新區塊——關掉後：
   Qt 改的寫進去、一般版改的與新加的留著、本來就有的自訂區塊留著。
3. 再開一次：Qt 改的值真的讀回來（③的勾選、系列一致性的三格）。
4. 存過一次之後，一般版又改了 Qt 存過的區塊、Qt 沒再改：再存不會把一般版的蓋回去。
5. 關視窗被取消（還沒存的變更選「取消」）：不存。
6. 存不進去（資料夾不存在）：不擋關視窗、不丟例外，回傳沒寫。
7. 頁面上的說明改成「自動記憶」；樣式小視窗講關掉時會存。
"""
import json
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
    print("SKIP 這個環境沒有 PySide6：略過 Qt 版存設定")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
    from PySide6.QtWidgets import QApplication, QGroupBox, QLabel  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import healthcheck as hc  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def disk():
        with open(config.CONFIG_PATH, encoding="utf-8") as fp:
            return json.load(fp)

    def write_disk(data):
        with open(config.CONFIG_PATH, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)

    def tame(win):
        p = win.player_panel
        p._ask_discard = lambda *a, **k: "discard"
        p._ask_project_discard = lambda *a, **k: "discard"

    start = config.load_config()
    start["自訂區塊"] = {"留著": True}
    start["transcription"]["language"] = "zh"
    write_disk(start)

    # ----- 1. 誰會存 -----
    given = qt_app.MainWindow(config.load_config())
    tame(given)
    check("給一份設定進來的：不存", given.persist is False)
    given.config_data["seriescheck"] = {"luma_tolerance": 70.0}
    before = open(config.CONFIG_PATH, encoding="utf-8").read()
    given.close()
    check("給一份設定進來的：關掉也沒寫", open(config.CONFIG_PATH, encoding="utf-8").read() == before
          and given.save_settings() is False)
    forced = qt_app.MainWindow(config.load_config(), persist=True)
    tame(forced)
    forced.config_data["seriescheck"] = {"luma_tolerance": 70.0}
    check("給設定但指定要存：會存", forced.persist is True and forced.save_settings() is True
          and disk()["seriescheck"] == {"luma_tolerance": 70.0})
    forced.config_data["seriescheck"] = {"luma_tolerance": 25.0}
    forced.save_settings()
    forced.close()
    write_disk(start)
    quiet = qt_app.MainWindow(persist=False)
    tame(quiet)
    check("自己讀設定檔但指定不存：不存", quiet.persist is False and quiet.config_data["自訂區塊"] == {"留著": True})
    quiet.config_data["seriescheck"] = {"luma_tolerance": 70.0}
    before = open(config.CONFIG_PATH, encoding="utf-8").read()
    quiet.close()
    check("指定不存：關掉也沒寫", open(config.CONFIG_PATH, encoding="utf-8").read() == before)
    src = open(os.path.join(os.path.dirname(qt_app.__file__), "app.py"), encoding="utf-8").read()
    check("main() 開的會存、自檢模式不存", "MainWindow(data, persist=SELFTEST_FLAG not in argv)" in src)

    untouched = qt_app.MainWindow()
    tame(untouched)
    untouched.show()
    wait(50)
    stamp = (os.path.getmtime(config.CONFIG_PATH), open(config.CONFIG_PATH, encoding="utf-8").read())
    untouched.close()
    check("開了什麼都沒改就關：檔案原封不動", (os.path.getmtime(config.CONFIG_PATH),
                                             open(config.CONFIG_PATH, encoding="utf-8").read()) == stamp
          and untouched.save_settings() is False)
    win = qt_app.MainWindow()
    tame(win)
    win.show()
    wait(50)
    check("自己讀設定檔的：會存、讀到的是磁碟上的", win.persist is True
          and win.config_data["自訂區塊"] == {"留著": True})

    # ----- 7. 說明文字 -----
    titles = [b.title() for b in win.findChildren(QGroupBox)]
    check("③的勾選標題寫「自動記憶」", "要跑哪些檢查（自動記憶）" in titles, str(titles))
    texts = " ".join(w.text() for w in win.findChildren(QLabel))
    check("④的輸出設定寫「自動記憶」", "輸出設定（自動記憶）" in texts)
    check("頁面上不再寫「這次開啟會記住」", "這次開啟會記住" not in texts and "這次開啟會記住" not in " ".join(titles))
    from gui_qt.style_panel import StyleDialog  # noqa: E402
    style = StyleDialog(win.player_panel)
    check("樣式小視窗講關掉時會存、不再叫人去一般版調", "關掉 Qt 版時也會存進設定" in style.note.text()
          and "請在一般版調" not in style.note.text())
    style.deleteLater()

    # ----- 2. 改、關、看磁碟 -----
    health = win.health_panel
    key = next(k for k in health.check_boxes if health.check_boxes[k].isChecked())
    health.check_boxes[key].setChecked(False)
    health.remember_selection()
    dlg = health.open_series()
    check("系列一致性的容許差異寫「自動記憶」", dlg.findChildren(QGroupBox)[1].title() == "容許差異（自動記憶）")
    dlg.spins["loudness_tolerance"].setValue(4.5)
    dlg.spins["luma_tolerance"].setValue(55.0)
    dlg.settings()
    other = disk()  # 「一般版」在 Qt 開著的期間存了東西
    other["transcription"]["language"] = "ja"
    other["一般版新區塊"] = {"x": 1}
    write_disk(other)
    win.close()
    wait(50)
    saved = disk()
    check("Qt 改的系列一致性寫進去", saved["seriescheck"]["loudness_tolerance"] == 4.5
          and saved["seriescheck"]["luma_tolerance"] == 55.0)
    check("Qt 改的③勾選寫進去", key not in hc.default_selected_keys(saved))
    check("一般版改的區塊留著（沒被 Qt 開啟當下的舊值蓋掉）", saved["transcription"]["language"] == "ja")
    check("一般版新加的區塊、本來的自訂區塊都留著", saved["一般版新區塊"] == {"x": 1}
          and saved["自訂區塊"] == {"留著": True})

    # ----- 3. 再開一次 -----
    win2 = qt_app.MainWindow()
    tame(win2)
    win2.show()
    wait(50)
    check("再開：③的勾選讀回來", not win2.health_panel.check_boxes[key].isChecked())
    dlg2 = win2.health_panel.open_series()
    check("再開：系列一致性三格讀回來", (dlg2.spins["loudness_tolerance"].value(), dlg2.spins["luma_tolerance"].value())
          == (4.5, 55.0))

    # ----- 4. 存過一次之後 -----
    dlg2.spins["cast_tolerance"].setValue(20.0)
    dlg2.settings()
    check("存一次", win2.save_settings() is True and disk()["seriescheck"]["cast_tolerance"] == 20.0)
    other = disk()
    other["seriescheck"]["cast_tolerance"] = 5.0  # 一般版又改了 Qt 剛存過的區塊
    write_disk(other)
    before = open(config.CONFIG_PATH, encoding="utf-8").read()
    check("Qt 沒再改：再存不寫（一般版的不會被蓋回去）", win2.save_settings() is False
          and disk()["seriescheck"]["cast_tolerance"] == 5.0
          and open(config.CONFIG_PATH, encoding="utf-8").read() == before)

    # ----- 5. 關視窗被取消 -----
    dlg2.spins["cast_tolerance"].setValue(9.0)
    dlg2.settings()
    before = open(config.CONFIG_PATH, encoding="utf-8").read()
    win2.player_panel.maybe_close = lambda: False
    win2.close()
    check("關視窗被取消：視窗還在、沒存", win2.isVisible()
          and open(config.CONFIG_PATH, encoding="utf-8").read() == before)
    del win2.player_panel.maybe_close

    # ----- 6. 存不進去 -----
    config.CONFIG_PATH = os.path.join(tmp, "沒有這個資料夾", "config.json")
    win2.close()
    wait(50)
    check("存不進去：照樣關掉、不丟例外、回傳沒寫", not win2.isVisible() and win2.save_settings() is False
          and not os.path.exists(config.CONFIG_PATH))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 Qt 版存設定測試全數通過。")
