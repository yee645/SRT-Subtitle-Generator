# -*- coding: utf-8 -*-
"""
3.0 第 11 項第十一階段：③健檢中心的發佈文字與章節（含「一鍵修正章節」）。

檢查與修正跟一般版同一份（subtitle/healthcheck：發佈健檢、章節健檢、apply_text_fix）。

1. 「發佈文字與章節」那塊預設收著，點一下展開／收合；寫明標籤怎麼填、說明欄算位元組、不存檔。
2. 什麼影片字幕都沒開、只貼了發佈文字與章節：照樣能跑；結果跟直接呼叫 run_health_scan（同樣的對象
   與項目）一模一樣；上方對象那行寫有另外貼。
3. 點「首章時間」：鈕上寫「一鍵修正章節」、可以按、說明寫直接改章節框、可以 Ctrl+Z。
4. 健檢之後章節框又改過：不修、講原因。
5. 修正：章節框＝apply_text_fix 的結果、自動展開、自動重新健檢；狀態列先講修了什麼；新結果沒有首章時間的
   問題；章節框按 Ctrl+Z 回到修之前。
6. 沒東西可修：講一般版那句、章節框不動。
7. 勾選：發佈資訊、章節、封面都照勾選記；貼的文字不寫進設定；不寫 config.json。
"""
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

if PySide6 is None or not shutil.which("ffmpeg"):
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過③健檢中心的發佈文字與章節")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import health_panel as hp  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import healthcheck as hc  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = tmp
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait_until(cond, timeout_ms=60000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(50)
            waited += 50
        return cond()

    cfg = {"healthcenter": {"run_thumb": False}}
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.show()
    win.tabs.setCurrentIndex(2)
    health = win.health_panel
    wait(50)

    # ----- 1. 收著、展開 -----
    check("預設收著", not health.publish_body.isVisible() and health.publish_toggle.text() == hp.PUBLISH_CLOSED)
    QTest.mouseClick(health.publish_toggle, Qt.LeftButton)
    check("點一下展開", health.publish_body.isVisible() and health.publish_toggle.text() == hp.PUBLISH_OPEN)
    QTest.mouseClick(health.publish_toggle, Qt.LeftButton)
    check("再點一下收合", not health.publish_body.isVisible() and health.publish_toggle.text() == hp.PUBLISH_CLOSED)
    check("說明：標籤逗號分隔、說明欄算位元組、不存檔", all(w in hp.PUBLISH_NOTE for w in ("逗號分隔", "位元組", "不存檔")))
    health.show_publish(True)

    # ----- 2. 只貼發佈文字與章節 -----
    chapters = "0:05 開場\n0:30 第二段\n1:10 第三段\n2:00 結尾"
    health.publish_title.setText("標" * 120)
    health.publish_desc.setPlainText("今天聊剪輯。")
    health.publish_tags.setText("剪輯, 字幕")
    health.publish_chapters.setPlainText(chapters)
    health.refresh_target()
    check("上方對象：寫有另外貼", "另外貼了發佈文字或章節" in health.target_label.text(), health.target_label.text())
    keys = health.selected_keys()
    check("發佈資訊與章節預設勾著", {"run_publish", "run_chapter"} <= keys)
    check("什麼影片字幕都沒開：照樣能跑", health.start_scan() is True)
    check("跑完", wait_until(lambda: not health.busy()) and health.last_result is not None)
    direct = hc.run_health_scan("", [], dict(cfg), keys, publish=health.publish_text())

    def brief(res):
        return [(f["level"], f["source"], f["title"], f.get("detail")) for f in res["findings"]]

    check("結果跟直接呼叫 run_health_scan 一模一樣", brief(health.last_result) == brief(direct), str(brief(direct)))
    sources = {f["source"] for f in health.last_result["findings"]}
    check("有發佈健檢與章節健檢的結果", {"發佈健檢", "章節健檢"} <= sources, str(sources))
    title = next((row for _i, row in health.finding_items() if row["title"] == "標題長度"), None)
    check("標題太長抓到", title is not None and title["level"] == hc.LEVEL_BAD)

    # ----- 3. 點首章時間 -----
    item, row = next(((i, r) for i, r in health.finding_items() if r.get("fix_key") == "chapter_fix"), (None, None))
    check("抓到首章時間（可以一鍵修正）", item is not None and row["title"] == "首章時間")
    health.tree.setCurrentItem(item)
    check("點首章時間：鈕上寫「一鍵修正章節」、可以按、說明寫直接改章節框可以 Ctrl+Z", health.fix_btn.isEnabled()
          and health.fix_btn.text() == "一鍵修正章節" and health.fix_note.text() == hp.FIX_TEXT_NOTE
          and "Ctrl+Z" in hp.FIX_TEXT_NOTE)

    # ----- 4. 健檢之後改過章節 -----
    health.publish_chapters.setPlainText(chapters + "\n2:30 加一段")
    check("健檢之後章節框改過：不修、講原因、章節框不動", health.apply_fix() is False
          and health.status_label.text() == hp.FIX_STALE_TEXT
          and health.publish_chapters.toPlainText() == chapters + "\n2:30 加一段" and not health.busy())
    health.publish_chapters.setPlainText(chapters)

    # ----- 5. 修正 -----
    expected, changes, message = hc.apply_text_fix("chapter_fix", dict(cfg), health.last_result["raw"])
    check("修正前的預期：第一章改成 0:00", expected.startswith("0:00 開場") and changes)
    health.show_publish(False)
    QTest.mouseClick(health.fix_btn, Qt.LeftButton)
    check("修正：章節框＝apply_text_fix 的結果、自動展開、自動重新健檢",
          health.publish_chapters.toPlainText() == expected and health.publish_body.isVisible() and health.busy())
    check("重新健檢跑完", wait_until(lambda: not health.busy()))
    status = health.status_label.text()
    check("狀態列先講修了什麼（Ctrl+Z 還原）、再講新的準備度",
          status.startswith(f"{message}（在章節框按 Ctrl+Z 就還原）健檢完成"), status)
    first = next((r for _i, r in health.finding_items() if r["title"] == "首章時間"), None)
    check("新結果：首章時間通過了", first is not None and first["level"] == hc.LEVEL_GOOD, str(first))
    health.publish_chapters.undo()
    check("章節框按 Ctrl+Z：回到修之前", health.publish_chapters.toPlainText() == chapters,
          health.publish_chapters.toPlainText())

    # ----- 6. 沒東西可修 -----
    check("再健檢一次", health.start_scan() and wait_until(lambda: not health.busy()))
    item, _row = next(((i, r) for i, r in health.finding_items() if r.get("fix_key") == "chapter_fix"), (None, None))
    health.tree.setCurrentItem(item)
    real = hc.apply_text_fix
    hc.apply_text_fix = lambda key, conf, raw: ("", [], "沒有可自動修正的項目（可能需要手動決定影片怎麼分段）。")
    try:
        check("沒東西可修：講一般版那句、章節框不動、不重新健檢", health.apply_fix() is False
              and health.status_label.text() == "沒有可自動修正的項目（可能需要手動決定影片怎麼分段）。"
              and health.publish_chapters.toPlainText() == chapters and not health.busy())
    finally:
        hc.apply_text_fix = real

    # ----- 7. 勾選與設定 -----
    health.check_boxes["run_publish"].setChecked(False)
    check("取消發佈資訊後再跑", health.start_scan() and wait_until(lambda: not health.busy()))
    check("發佈資訊照勾選記（沒勾）、章節勾著、封面照勾選記（設定裡原本沒勾、畫面上也沒勾）",
          cfg["healthcenter"]["run_publish"] is False and cfg["healthcenter"]["run_chapter"] is True
          and cfg["healthcenter"]["run_thumb"] is False, str(cfg["healthcenter"]))
    check("沒勾發佈資訊：結果裡沒有發佈健檢", all(r["source"] != "發佈健檢" for _i, r in health.finding_items()))
    flat = repr(cfg)
    check("貼的文字不寫進設定", "標標標" not in flat and "開場" not in flat and "剪輯, 字幕" not in flat)
    check("沒寫 config.json", not os.path.exists(config.CONFIG_PATH))

    win.player_panel.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 ③健檢中心發佈文字與章節測試全數通過。")
