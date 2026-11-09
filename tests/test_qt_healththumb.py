# -*- coding: utf-8 -*-
"""
3.0 第 11 項第十二階段：③健檢中心的封面圖（加入、移除，多張依分數排名）。

檢查跟一般版同一份（subtitle/healthcheck 的封面健檢，背後是 subtitle/thumbcheck.rank_thumbnails）。
測試圖用 ffmpeg 產生：一張彩色測試畫面（清楚）、一張幾乎全黑（手機上看不清）、一個不是圖片的 .png。

1. 「封面圖」那塊預設收著，點一下展開／收合；寫明只要 ffmpeg、不存檔、不改圖。勾選項有「封面健檢」。
2. 加入：同一張不重複、清單顯示檔名、滑過看完整路徑；移除、清除鈕有圖才能按；上方對象寫幾張。
   按「加入圖片…」開選檔視窗（可多選）；取消的話什麼都不加。
3. 什麼影片字幕都沒開、只加了封面圖：照樣能跑；結果跟直接呼叫 run_health_scan（同樣的對象與項目）
   一模一樣；排名推薦清楚那張；全黑那張抓到「一定要修」；不是圖片的講讀取失敗。
4. 跑的期間再加圖：這次的結果不受影響（送出去的是按下去那一刻的清單）。
5. 移除選取、全部清除；清光了又沒別的對象：不跑、講原因。
6. 勾選：封面照勾選記；圖片路徑不寫進設定；不寫 config.json。
"""
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

if PySide6 is None or not shutil.which("ffmpeg"):
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過③健檢中心的封面圖")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import health_panel as hp  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import healthcheck as hc  # noqa: E402
    from subtitle.preflight import LEVEL_BAD, LEVEL_GOOD, LEVEL_WARN  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = tmp
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def make(name, source):
        path = os.path.join(tmp, name)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", source,
                        "-frames:v", "1", path], check=True)
        return path

    good = make("清楚的封面.png", "testsrc2=size=1280x720")
    dark = make("全黑.png", "color=c=0x101010:size=1280x720")
    third = make("第三張.png", "testsrc=size=1280x720")
    broken = os.path.join(tmp, "不是圖片.png")
    with open(broken, "w", encoding="utf-8") as f:
        f.write("not an image")

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

    cfg = {}
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.show()
    win.tabs.setCurrentIndex(2)
    health = win.health_panel
    wait(50)

    # ----- 1. 收著、展開、勾選項 -----
    check("預設收著", not health.thumb_body.isVisible() and health.thumb_toggle.text() == hp.THUMB_CLOSED)
    QTest.mouseClick(health.thumb_toggle, Qt.LeftButton)
    check("點一下展開", health.thumb_body.isVisible() and health.thumb_toggle.text() == hp.THUMB_OPEN)
    QTest.mouseClick(health.thumb_toggle, Qt.LeftButton)
    check("再點一下收合", not health.thumb_body.isVisible() and health.thumb_toggle.text() == hp.THUMB_CLOSED)
    check("說明：只要 ffmpeg、不存檔、不改圖", all(w in hp.THUMB_NOTE for w in ("ffmpeg", "不存檔", "不會被改")))
    check("勾選項有封面健檢、文字跟一般版一樣、預設勾著", "run_thumb" in health.check_boxes
          and health.check_boxes["run_thumb"].text() == hc._BY_KEY["run_thumb"].label
          and health.check_boxes["run_thumb"].isChecked())
    check("還沒加圖：移除、清除鈕灰掉", not health.thumb_remove_btn.isEnabled() and not health.thumb_clear_btn.isEnabled())

    # ----- 2. 加入 -----
    check("加入三張（其中一張重複）：只加兩張", health.add_thumbs([good, dark, good]) == 2)
    check("清單顯示檔名、順序照加入、滑過看完整路徑", health.thumb_paths() == [good, dark]
          and [health.thumb_list.item(i).text() for i in range(2)] == ["清楚的封面.png", "全黑.png"]
          and health.thumb_list.item(0).toolTip() == good)
    check("加入時自動展開", health.thumb_body.isVisible())
    check("有圖了：移除、清除鈕可以按", health.thumb_remove_btn.isEnabled() and health.thumb_clear_btn.isEnabled())
    check("上方對象寫幾張", "封面圖 2 張" in health.target_label.text(), health.target_label.text())

    real_dialog = QFileDialog.getOpenFileNames
    asked = []
    try:
        QFileDialog.getOpenFileNames = staticmethod(
            lambda *a, **k: (asked.append(a), ([broken], "圖片檔"))[1])
        QTest.mouseClick(health.thumb_add_btn, Qt.LeftButton)
        check("按「加入圖片…」：開選檔視窗、只列圖片檔、選的加進來", len(asked) == 1
              and "*.png" in asked[0][-1] and "*.jpg" in asked[0][-1] and health.thumb_paths() == [good, dark, broken],
              str(asked))
        QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([], ""))
        QTest.mouseClick(health.thumb_add_btn, Qt.LeftButton)
        check("選檔視窗按取消：什麼都不加", health.thumb_paths() == [good, dark, broken])
    finally:
        QFileDialog.getOpenFileNames = real_dialog

    # ----- 3. 只加了封面圖就能跑 -----
    keys = health.selected_keys()
    check("什麼影片字幕都沒開：照樣能跑", health.start_scan() is True)
    # ----- 4. 跑的期間再加一張：這次的結果不受影響 -----
    health.add_thumbs([third])
    check("跑完", wait_until(lambda: not health.busy()) and health.last_result is not None)
    direct = hc.run_health_scan("", [], dict(cfg), keys, publish=health.publish_text(),
                                image_paths=[good, dark, broken])

    def brief(res):
        return [(f["level"], f["source"], f["title"], f.get("detail")) for f in res["findings"]]

    check("結果跟直接呼叫 run_health_scan 一模一樣（跑的期間加的那張不算）", brief(health.last_result) == brief(direct),
          str(brief(health.last_result)))
    rows = [row for _i, row in health.finding_items()]
    rank = next((r for r in rows if r["title"] == "封面候選排名"), None)
    check("排名推薦清楚那張", rank is not None and rank["level"] == LEVEL_GOOD
          and "共 3 張" in rank["detail"] and "「清楚的封面.png」" in rank["detail"], str(rank))
    check("全黑那張抓到一定要修（標題前面有檔名）",
          any(r["level"] == LEVEL_BAD and r["title"].startswith("全黑.png：") for r in rows))
    check("不是圖片的：講讀取失敗", any(r["level"] == LEVEL_WARN and r["title"] == "「不是圖片.png」讀取失敗"
                                        for r in rows))
    check("結果都在封面健檢底下", all(r["source"] == "封面健檢" for r in rows))
    check("清單裡現在是四張（跑的期間加的留著）", len(health.thumb_paths()) == 4)

    # ----- 5. 移除、清除 -----
    health.thumb_list.item(1).setSelected(True)
    health.thumb_list.item(2).setSelected(True)
    QTest.mouseClick(health.thumb_remove_btn, Qt.LeftButton)
    check("移除選取（可多選）", health.thumb_paths() == [good, third], str(health.thumb_paths()))
    check("上方對象跟著改", "封面圖 2 張" in health.target_label.text())
    QTest.mouseClick(health.thumb_clear_btn, Qt.LeftButton)
    check("全部清除：清單空了、鈕灰掉、上方不再提封面", health.thumb_paths() == []
          and not health.thumb_remove_btn.isEnabled() and not health.thumb_clear_btn.isEnabled()
          and "封面圖" not in health.target_label.text())
    check("清光了又沒別的對象：不跑、講原因", health.start_scan() is False and health.status_label.text() == hp.NOTHING
          and "封面圖" in hp.NOTHING)

    # ----- 6. 勾選與設定 -----
    health.add_thumbs([good])
    health.check_boxes["run_thumb"].setChecked(False)
    health.publish_title.setText("標題")  # 留一個對象，才跑得起來
    check("取消封面後再跑", health.start_scan() and wait_until(lambda: not health.busy()))
    check("封面照勾選記（沒勾）", cfg["healthcenter"]["run_thumb"] is False, str(cfg.get("healthcenter")))
    check("沒勾封面：結果裡沒有封面健檢", all(r["source"] != "封面健檢" for _i, r in health.finding_items()))
    flat = repr(cfg)
    check("圖片路徑不寫進設定", "清楚的封面" not in flat and tmp not in flat)
    check("沒寫 config.json", not os.path.exists(config.CONFIG_PATH))

    win.player_panel.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 ③健檢中心封面圖測試全數通過。")
