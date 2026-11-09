# -*- coding: utf-8 -*-
"""
3.0 第 11 項第十階段：③健檢中心的影音修復（輸出音訊修復版、修剪頭尾、拉平音量）。

修復本身跟一般版同一份（subtitle/healthcheck.apply_media_fix）。測試影片用 ffmpeg 產生：開頭 3 秒黑畫面＋
沒聲音（抓得到「開頭廢秒」），後面是小聲的音（「整體響度」太小）。

1. 點影音類：鈕上寫一般版那句、可以按、說明寫另外輸出、原檔不動、做好後問要不要換、不能停。
2. 不能修的情況：②健檢之後換過影片、找不到 ffmpeg、②沒有影片——講原因、不開始。
3. 輸出音訊修復版：背景跑，跑的時候「開始健檢」與修復鈕灰掉、按鈕寫「輸出修復版中…」、不能再開始健檢；
   輸出到建議的檔名（跟一般版同一個規則）、原檔不動、真的是修過的（響度變大）；做好後問要不要換。
   - 選「否」：②還是原檔，狀態列寫輸出到哪。
   - 再修一次、選「是」：檔名不蓋掉前一個（加編號）；②換成修復版、字幕留著；重新健檢就是修好之後的結果
     （整體響度不再是一定要修）。
4. 專案有沒存的變更、選了換：跟②「開影片」一樣先問；按取消就不換、狀態列寫沒有換。
5. 修剪版：問的時候寫明字幕時間不會跟著往前移（沒字幕就不寫）；輸出的檔比原檔短。
6. 修不了（缺偵測結果）：一般版同一句原因；其他錯誤：「修復失敗：…」；按鈕都恢復。
7. 修復版還在輸出時關視窗：先問；選否不關，選是才關。
8. 不寫 config.json。
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading

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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過③健檢中心的影音修復（修復本身在一般版的測試）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import health_panel as hp  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import burner  # noqa: E402
    from subtitle import healthcheck as hc  # noqa: E402
    from subtitle.media import probe_duration  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = tmp
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait_until(cond, timeout_ms=120000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(50)
            waited += 50
        return cond()

    def digest(path):
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()

    def loudness(path):
        out = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", "volumedetect", "-f", "null", "-"],
                             capture_output=True, text=True).stderr
        line = next(x for x in out.splitlines() if "mean_volume" in x)
        return float(line.split("mean_volume:")[1].split("dB")[0])

    work = os.path.join(tmp, "我的影片")
    os.makedirs(work)
    main = os.path.join(work, "訪談.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:size=640x360:rate=30:d=3",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=3", "-f", "lavfi",
                    "-i", "testsrc=size=640x360:rate=30:d=6", "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:d=6",
                    "-filter_complex", "[0:v][1:a][2:v][3:a]concat=n=2:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", main], check=True)
    other = os.path.join(work, "另一支.mp4")
    shutil.copy(main, other)
    srt = os.path.join(work, "訪談.srt")
    with open(srt, "w", encoding="utf-8") as fh:
        fh.write("1\n00:00:03,500 --> 00:00:05,000\n大家好\n\n2\n00:00:06,000 --> 00:00:08,000\n謝謝收看\n")
    main_hash = digest(main)

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
    asked = []
    health._ask_adopt = lambda path, key: asked.append((path, key)) or answers.pop(0)
    answers = []

    def scan():
        return (health.start_scan() and wait_until(lambda: not health.busy())
                and health.last_result is not None)

    def find(fix_key):
        return next(((item, row) for item, row in health.finding_items() if row.get("fix_key") == fix_key),
                    (None, None))

    check("健檢跑完", scan(), health.status_label.text())
    loud, loud_row = find("audiofix")
    trim, trim_row = find("trim")
    check("抓到整體響度太小（音訊修復）與開頭廢秒（修剪）", loud is not None and trim is not None
          and loud_row["level"] == hc.LEVEL_BAD)

    # ----- 1. 點影音類 -----
    health.tree.setCurrentItem(loud)
    check("點整體響度：鈕上寫「輸出音訊修復版」、可以按", health.fix_btn.isEnabled()
          and health.fix_btn.text() == "輸出音訊修復版")
    check("說明：另外輸出、原檔不動、做好後問要不要換、不能停；整體響度這筆寫明會一併做響度正規化",
          health.fix_note.text() == hp.FIX_MEDIA_NOTE + hp.FIX_LOUD_NOTE
          and all(w in hp.FIX_MEDIA_NOTE for w in ("另外輸出", "原檔不動", "要不要在②換成它", "不能停")))

    # ----- 2. 不能修的情況 -----
    panel.open_video(other)
    check("②健檢之後換過影片：不修、講原因", health.apply_fix() is False
          and health.status_label.text() == hp.FIX_STALE_MEDIA and not health.busy())
    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0)
    real_available = burner.ffmpeg_available
    burner.ffmpeg_available = lambda: False
    try:
        check("找不到 ffmpeg：不修、講原因（一般版的自動安裝兩版共用）", health.apply_fix() is False
              and health.status_label.text() == hp.FIX_NO_FFMPEG and not health.busy())
    finally:
        burner.ffmpeg_available = real_available
    saved_media = panel.media_path
    panel.media_path = os.path.join(work, "不見了.mp4")
    check("影片找不到了：不修、講原因", health.apply_fix() is False and health.status_label.text() == hp.FIX_NO_MEDIA)
    panel.media_path = saved_media

    # ----- 3. 輸出音訊修復版 -----
    expected = hc.suggest_fix_output_path("audiofix", main)
    check("建議檔名＝一般版的規則、還不存在", not os.path.exists(expected) and os.path.dirname(expected) == work)
    answers.append(False)
    QTest.mouseClick(health.fix_btn, Qt.LeftButton)
    check("輸出中：開始健檢與修復鈕灰掉、按鈕寫「輸出修復版中…」、不能再開始健檢", health.fixing()
          and health.busy() and not health.run_btn.isEnabled() and health.run_btn.text() == "輸出修復版中…"
          and not health.fix_btn.isEnabled() and health.start_scan() is False
          and (health.status_label.text().startswith("正在輸出修復版：") or "輸出修復版：" in health.status_label.text()),
          health.status_label.text())
    check("輸出完成", wait_until(lambda: not health.fixing()), health.status_label.text())
    check("輸出到建議的檔名、原檔不動", os.path.exists(expected) and health.last_fixed == expected
          and digest(main) == main_hash)
    check("真的修過：聲音變大（一併做了響度正規化）", loudness(expected) > loudness(main) + 3,
          f"{loudness(expected)} vs {loudness(main)}")
    check("響度正規化只在這一次：記著的設定沒有多出 audiofix", "audiofix" not in cfg, str(cfg))
    check("做好後問要不要換（帶著檔名與是哪一種修復）", asked == [(expected, "audiofix")])
    check("選「否」：②還是原檔、狀態列寫輸出到哪、按鈕恢復", panel.media_path == main
          and health.status_label.text() == f"修復版已輸出：{os.path.basename(expected)}（在 {work}）。"
          and health.run_btn.isEnabled() and health.run_btn.text() == "開始健檢" and health.fix_btn.isEnabled())

    cues_before = [dict(c) for c in panel.cues]
    answers.append(True)
    check("再修一次：開始了", health.apply_fix() is True)
    wait_until(lambda: not health.fixing())
    second = asked[-1][0]
    check("再修一次：不蓋掉前一個（加編號）", second != expected and os.path.exists(second) and os.path.exists(expected)
          and os.path.dirname(second) == work, second)
    check("選「是」：②換成修復版、字幕留著、狀態列寫已換", panel.media_path == second and panel.cues == cues_before
          and health.status_label.text().endswith("②已換成修復版，按「開始健檢」就是修好之後的結果。")
          and os.path.basename(second) in health.target_label.text(), health.status_label.text())
    wait_until(lambda: panel.player.duration() > 0)
    check("重新健檢：檢查的是修復版", scan() and health.last_result["media"] == os.path.basename(second))
    after = next((row for _i, row in health.finding_items() if row["source"] == "音訊健檢" and row["title"] == "整體響度"),
                 None)
    check("修好之後：整體響度不再是一定要修", after is not None and after["level"] != hc.LEVEL_BAD, str(after))

    # ----- 4. 專案有沒存的變更 -----
    trim, _row = find("trim")
    health.tree.setCurrentItem(trim)
    check("點開頭廢秒：鈕上寫「輸出修剪版（去頭尾）」、說明不提響度", health.fix_btn.isEnabled()
          and health.fix_btn.text() == "輸出修剪版（去頭尾）" and health.fix_note.text() == hp.FIX_MEDIA_NOTE)
    question = health.adopt_question(os.path.join(work, "x.mp4"), "trim")
    check("修剪版的問句寫明字幕時間不會跟著往前移", "字幕時間不會跟著往前移" in question
          and "素材軌與畫面調整會清掉，字幕留著" in question)
    check("音訊修復版的問句不寫那句", "字幕時間" not in health.adopt_question(os.path.join(work, "x.mp4"), "audiofix"))
    current = panel.media_path
    panel.main_adjust = {"brightness": 0.2}  # 有沒存的編輯（換片子就沒了）
    project_asked = []
    panel._ask_project_discard = lambda: project_asked.append(1) or "cancel"
    answers.append(True)
    check("修剪：開始了", health.apply_fix() is True)
    wait_until(lambda: not health.fixing())
    trimmed = asked[-1][0]
    check("修剪：問的時候帶的是 trim", asked[-1][1] == "trim")
    check("專案有沒存的變更：先問；取消就不換、狀態列寫沒有換", project_asked == [1] and panel.media_path == current
          and panel.main_adjust == {"brightness": 0.2}
          and health.status_label.text().endswith("②沒有換（專案的變更還沒處理）。"), health.status_label.text())
    panel.main_adjust = {}
    check("修剪版比原本短（開頭的黑畫面剪掉了）", probe_duration(trimmed) < probe_duration(current) - 1.5,
          f"{probe_duration(trimmed)} vs {probe_duration(current)}")

    # ----- 6. 修不了、其他錯誤 -----
    clip_row = {"fix_key": "audiofix", "level": "bad", "source": "音訊健檢", "title": "爆音檢查"}
    health._show_row({"fix_key": "volumefix", "level": "warn", "source": "分段音量一致性", "title": "音量落差段落"})
    check("缺偵測結果：開始了（在背景才知道）", health.apply_fix() is True)
    wait_until(lambda: not health.fixing())
    check("缺偵測結果：一般版同一句原因、按鈕恢復", health.status_label.text()
          == "請先跑過健檢並確認偵測到音量落差過大的段落。" and health.run_btn.isEnabled()
          and health.fix_btn.isEnabled() and health.copy_btn.isEnabled())
    real_fix = hc.apply_media_fix
    hc.apply_media_fix = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("假的 ffmpeg 掛了"))
    try:
        health._show_row(clip_row)  # 修好之後整體響度通過了，改用爆音那一筆（同樣是音訊修復版）
        health.apply_fix()
        wait_until(lambda: not health.fixing())
    finally:
        hc.apply_media_fix = real_fix
    check("其他錯誤：「修復失敗：…」、按鈕恢復", health.status_label.text().startswith("修復失敗：")
          and health.run_btn.isEnabled() and not health.busy(), health.status_label.text())

    # ----- 7. 輸出中關視窗 -----
    gate = threading.Event()
    hc.apply_media_fix = lambda key, media, out, *a, **k: (gate.wait(30), out)[1]
    close_asked = []
    health.ask_close_while_fixing = lambda: close_asked.append(health.close_question()) or close_answers.pop(0)
    close_answers = [False, True]
    try:
        health._show_row(clip_row)  # 修好之後整體響度通過了，改用爆音那一筆（同樣是音訊修復版）
        answers.append(False)
        health.apply_fix()
        panel._ask_project_discard = lambda: "discard"
        panel._ask_discard = lambda: "discard"
        win.close()
        check("輸出中關視窗：先問（寫哪個檔、可能不完整）；選否不關", len(close_asked) == 1 and win.isVisible()
              and "還在輸出" in close_asked[0] and "可能不完整" in close_asked[0])
        win.close()
        check("選是：關了", len(close_asked) == 2 and not win.isVisible())
    finally:
        gate.set()
        hc.apply_media_fix = real_fix
    wait(200)

    check("沒寫 config.json", not os.path.exists(config.CONFIG_PATH))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 ③健檢中心影音修復測試全數通過。")
