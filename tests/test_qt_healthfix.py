# -*- coding: utf-8 -*-
"""
3.0 第 11 項第九階段：③健檢中心的「修復此項」（先接字幕類）。

修復本身跟一般版同一份（subtitle/healthcheck.apply_cue_fix）。這裡在真的視窗裡驗：

1. 還沒點任何一筆：修復鈕灰掉、寫「修復此項」。
2. 點字幕類的（重疊、太快、術語）：鈕上寫一般版的那句（例如「一鍵修復重疊」）、可以按、下面寫會直接改②
   的字幕、可以復原。點影音類的（整體響度）：鈕上寫「輸出音訊修復版」（第十階段起可以按，輸出流程在
   test_qt_healthmedia.py）。
   點通過的：灰掉、沒有說明。
3. 健檢之後字幕又改過：不修、講原因（結果講的是舊句子）。
4. 修重疊：②的字幕＝apply_cue_fix 對健檢時那份字幕的結果；整批一步，②按復原就整個還原；改完自動重新健檢，
   跑的時候鈕灰掉；跑完狀態列先講修了什麼、再講新的準備度；新的結果裡沒有重疊了。開始前先套用逐句校對改到
   一半的（before_scan）。
5. 統一術語：YouTube／youtube 統一成多數的寫法。
6. 修不了（缺偵測結果）、沒東西可修：講原因、不動字幕；勾選全取消時修好的照樣留著、講明沒重新健檢。
7. 不寫 config.json。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過③健檢中心的修復（修復本身在 test_v1500.py 等）")
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

    main = os.path.join(tmp, "訪談.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:size=640x360:rate=30:d=8",
                    "-f", "lavfi", "-i", "sine=frequency=150:sample_rate=48000:d=8", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", main], check=True)
    srt = os.path.join(tmp, "訪談.srt")
    with open(srt, "w", encoding="utf-8") as fh:
        # 第二句跟第三句重疊；YouTube 兩次、youtube 一次（有明確的多數寫法）
        fh.write("1\n00:00:00,500 --> 00:00:02,000\n歡迎來到 YouTube 頻道\n\n"
                 "2\n00:00:02,200 --> 00:00:03,600\n今天聊 YouTube 的演算法\n\n"
                 "3\n00:00:03,300 --> 00:00:05,000\n記得在 youtube 訂閱\n\n"
                 "4\n00:00:05,500 --> 00:00:07,000\n謝謝收看\n")

    cfg = {}
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.show()
    panel = win.player_panel
    health = win.health_panel
    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0)
    panel.load_subtitles(srt)
    win.tabs.setCurrentIndex(2)
    wait(50)

    # ----- 1. 還沒點 -----
    check("還沒點任何一筆：修復鈕灰掉、寫「修復此項」、沒有說明", not health.fix_btn.isEnabled()
          and health.fix_btn.text() == "修復此項" and health.fix_note.text() == "")
    labels = " ".join(w.text() for w in health.findChildren(type(health.status_label)))
    check("頁面寫明：字幕類直接改②的字幕、影音類另外輸出修復版、章節直接改章節框；封面圖等還在一般版",
          "可以直接按「修復此項」：字幕類直接改②的字幕，影音類另外輸出一個修復版，章節直接改章節框" in labels
          and "封面圖、系列一致性的檢查還在一般版" in labels)

    def scan():
        ok = health.start_scan()
        return ok and wait_until(lambda: not health.busy()) and health.last_result is not None

    def find(fix_key=None, source=None, level=None):
        for item, row in health.finding_items():
            if ((fix_key is None or row.get("fix_key") == fix_key) and (source is None or row["source"] == source)
                    and (level is None or row["level"] == level)):
                return item, row
        return None, None

    check("健檢跑完", scan(), health.status_label.text())

    # ----- 2. 點各種的 -----
    item, row = find("fix_overlap")
    check("抓到重疊（可以一鍵修）", item is not None and row["title"] == "字幕重疊")
    health.tree.setCurrentItem(item)
    check("點重疊：鈕上寫一般版那句、可以按、寫會直接改②的字幕可以復原", health.fix_btn.isEnabled()
          and health.fix_btn.text() == "一鍵修復重疊" and health.fix_note.text() == hp.FIX_CUE_NOTE
          and "復原" in hp.FIX_CUE_NOTE)

    loud, loud_row = find("audiofix")
    check("抓到整體響度（影音類）", loud is not None)
    health.tree.setCurrentItem(loud)
    before = [dict(c) for c in panel.cues]
    check("點影音類：鈕上寫「輸出音訊修復版」、可以按、說明寫另外輸出（第十階段起）", health.fix_btn.isEnabled()
          and health.fix_btn.text() == "輸出音訊修復版" and health.fix_note.text() == hp.FIX_MEDIA_NOTE + hp.FIX_LOUD_NOTE
          and "另外輸出" in hp.FIX_MEDIA_NOTE and panel.cues == before)

    good, _ = find(level=hc.LEVEL_GOOD)
    health.tree.setCurrentItem(good)
    check("點通過的：灰掉、沒有說明", not health.fix_btn.isEnabled() and health.fix_btn.text() == "修復此項"
          and health.fix_note.text() == "")

    # ----- 3. 健檢之後字幕又改過 -----
    health.tree.setCurrentItem(item)
    panel.set_cue_text(3, "謝謝大家收看")
    changed = [dict(c) for c in panel.cues]
    check("健檢之後改過字幕：不修、講原因", health.apply_fix() is False
          and health.status_label.text() == hp.FIX_STALE and panel.cues == changed and not health.busy())
    panel.undo()
    check("復原回健檢時的字幕", panel.cues == health.last_result["cues"])

    # ----- 4. 修重疊 -----
    snapshot = [dict(c) for c in health.last_result["cues"]]
    expected, count, message = hc.apply_cue_fix("fix_overlap", [dict(c) for c in snapshot], dict(cfg),
                                                health.last_result["raw"])
    order = []
    health.before_scan = lambda: order.append((health.busy(), panel.cues == snapshot))
    QTest.mouseClick(health.fix_btn, Qt.LeftButton)
    health.before_scan = win.cue_panel.commit
    check("修重疊：先套用逐句校對改到一半的（在改字幕之前），重新健檢時再套用一次",
          order == [(False, True), (False, False)], str(order))
    check("修重疊：②的字幕＝apply_cue_fix 的結果、真的有改", panel.cues == expected and expected != snapshot
          and count == 1, str(panel.cues))
    check("修完自動重新健檢、跑的時候修復鈕灰掉", health.busy() and not health.fix_btn.isEnabled()
          and not health.run_btn.isEnabled())
    check("重新健檢跑完", wait_until(lambda: not health.busy()))
    status = health.status_label.text()
    check("狀態列先講修了什麼（可以復原）、再講新的準備度",
          status.startswith(f"{message}（②字幕頁按「復原」就還原）健檢完成，準備度 "), status)
    check("新的結果講的是修好的字幕、沒有重疊了", health.last_result["cues"] == expected
          and find("fix_overlap")[0] is None)
    check("修完右邊清空、修復鈕回到灰掉", health.detail.toPlainText() == "" and not health.fix_btn.isEnabled())
    panel.undo()
    check("②按一次復原：整批還原成修之前", panel.cues == snapshot, str(panel.cues))
    panel.redo()
    check("再重做：回到修好的", panel.cues == expected)

    # ----- 5. 統一術語 -----
    check("再健檢一次", scan())
    term, term_row = find("term_fix")
    check("抓到術語寫法不一致", term is not None, str([r["title"] for _i, r in health.finding_items()]))
    health.tree.setCurrentItem(term)
    check("點術語：鈕上寫「一鍵統一術語寫法」", health.fix_btn.isEnabled() and health.fix_btn.text() == "一鍵統一術語寫法")
    check("統一術語：有改", health.apply_fix() is True)
    check("統一成多數的寫法 YouTube", [c["text"] for c in panel.cues][:3]
          == ["歡迎來到 YouTube 頻道", "今天聊 YouTube 的演算法", "記得在 YouTube 訂閱"], str(panel.cues))
    wait_until(lambda: not health.busy())

    # ----- 6. 修不了、沒東西可修、不能重新健檢 -----
    cues_now = [dict(c) for c in panel.cues]
    health._show_row({"fix_key": "sync_fix", "level": "warn", "source": "語音同步", "title": "固定偏移"})
    check("缺偵測結果：講一般版的那句原因、不動字幕", health.apply_fix() is False
          and health.status_label.text() == "請先跑過健檢並確認偵測到同步偏移。" and panel.cues == cues_now)

    real = hc.apply_cue_fix
    hc.apply_cue_fix = lambda key, cues, conf, raw: (cues, 0, "沒改")
    try:
        health._show_row({"fix_key": "extend_cues", "level": "warn", "source": "字幕健檢", "title": "顯示時間過短"})
        check("沒東西可修：講原因、不動字幕、不重新健檢", health.apply_fix() is False
              and health.status_label.text() == hp.FIX_NOTHING and panel.cues == cues_now and not health.busy())
    finally:
        hc.apply_cue_fix = real

    check("再健檢一次（準備改句子長度）", scan())
    panel.apply_cues([dict(c, end=c["start"] + 0.3) if i == 3 else c for i, c in enumerate(panel.cues)])
    check("把最後一句改得很短後重新健檢", scan())
    short, short_row = find("extend_cues")
    check("抓到顯示時間過短（可以一鍵延長）", short is not None, str([r["title"] for _i, r in health.finding_items()]))
    health.tree.setCurrentItem(short)
    for cb in health.check_boxes.values():
        cb.setChecked(False)
    check("勾選全取消時修：照樣修好", health.apply_fix() is True and panel.cues[3]["end"] > panel.cues[3]["start"] + 0.3)
    status = health.status_label.text()
    check("講明修了什麼、沒有重新健檢、為什麼", status.startswith("已延長 ") and "沒有重新健檢：" in status
          and status.endswith(hp.NONE_CHECKED) and not health.busy(), status)
    for cb in health.check_boxes.values():
        cb.setChecked(True)
    check("下一次健檢的狀態列不會再帶著上次修了什麼", scan() and health.status_label.text().startswith("健檢完成"),
          health.status_label.text())

    check("沒寫 config.json", not os.path.exists(config.CONFIG_PATH))

    panel._ask_project_discard = lambda: "discard"
    panel._ask_discard = lambda: "discard"
    panel.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 ③健檢中心修復測試全數通過。")
