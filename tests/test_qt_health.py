# -*- coding: utf-8 -*-
"""
3.0 第 11 項第八階段：③健檢中心搬到 Qt（先搬影片與字幕的檢查）。

1. 檢查邏輯搬進 subtitle/healthcheck.py：舊的 gui/health_aggregator 拿到的是同一個模組物件；
   新檔不碰 GUI、不 import config；一般版的健檢中心改從新位置 import。
2. ③頁籤是健檢頁（不是「還沒搬」的說明）：勾選項是影片與字幕的 14 項、加上第十一階段搬來的發佈資訊與
   章節，共 16 項＋停用的「檔名」；封面不在這頁；勾不勾照目前的設定；頁面寫明還在一般版的部分。
3. 沒開影片也沒字幕、或一項都沒勾：不跑，講原因。
4. 開影片＋載字幕後跑：結果跟直接呼叫 run_health_scan（同樣的項目）一模一樣；分組、計數、
   準備度、詳情與建議、略過的項目、複製報告（＝format_health_report）。跑的期間按鈕停用、
   再按不會重跑。
5. 勾選記在這次開啟的設定：取消的項目寫進 preflight／healthcenter 區塊；這頁看不到的封面
   維持原本的值；不寫 config.json。開始前先套用逐句校對改到一半的（before_scan 接的是 commit）。
6. 背景失敗：講原因、按鈕恢復。
"""
import ast
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


# ----- 1. 搬家：不需要 Qt 也驗得到 -----
from gui import health_aggregator as old_name  # noqa: E402
from subtitle import healthcheck as hc  # noqa: E402

check("舊名字拿到的就是 subtitle.healthcheck 本身（不是複本）", old_name is hc and len(hc.CHECK_DEFS) == 18)
tree = ast.parse(_read("subtitle/healthcheck.py"))
imported = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        imported.update(a.name.split(".")[0] for a in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module:
        imported.add(node.module.split(".")[0])
check("subtitle/healthcheck.py 只用標準庫與 subtitle（不碰 gui、tkinter、PySide6、config）",
      not imported & {"gui", "gui_qt", "tkinter", "PySide6", "config"} and "subtitle" in imported, str(imported))
shim = _read("gui/health_aggregator.py")
check("舊檔只剩轉接（沒有任何檢查邏輯）", "def " not in shim and "sys.modules[__name__] = _healthcheck" in shim)
check("一般版健檢中心改從新位置 import",
      "from subtitle import healthcheck as ha\n" in _read("gui/health_center_panel.py"))

try:
    import PySide6  # noqa: F401
except ImportError:
    PySide6 = None

if PySide6 is None or not shutil.which("ffmpeg"):
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過③健檢中心的介面（搬家的部分上面驗過了）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication, QCheckBox  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import health_panel as hp  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402

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

    def run(*args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)

    main = os.path.join(tmp, "訪談 final.mp4")
    run("-f", "lavfi", "-i", "color=c=gray:size=640x360:rate=30:d=6", "-f", "lavfi",
        "-i", "sine=frequency=150:sample_rate=48000:d=6", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", main)
    srt = os.path.join(tmp, "訪談.srt")
    with open(srt, "w", encoding="utf-8") as fh:
        # 第二句太快（CPS 超標）而且跟第三句重疊：字幕健檢一定有「要修」或「建議修」
        fh.write("1\n00:00:00,500 --> 00:00:02,000\n大家好\n\n"
                 "2\n00:00:02,100 --> 00:00:02,600\n今天要講一個非常非常非常長而且講得很快的句子\n\n"
                 "3\n00:00:02,400 --> 00:00:04,000\n謝謝收看\n")

    cfg = {"preflight": {"run_audio": False}, "healthcenter": {"run_publish": False}}
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.show()
    panel = win.player_panel

    # ----- 2. ③頁籤 -----
    page = win.tabs.widget(2)
    check("③頁籤是健檢頁、名稱不變", win.tabs.tabText(2) == "③ 健檢中心" and page is win.health_panel
          and isinstance(page, hp.HealthPanel))
    health = win.health_panel
    expected = [c.key for c in hc.CHECK_DEFS
                if not c.always_on and c.key != "run_thumb"]
    check("勾選項：影片與字幕的 14 項＋發佈資訊與章節（共 16 項）、照 CHECK_DEFS 的順序與文字；封面不在",
          list(health.check_boxes) == expected and len(expected) == 16
          and list(health.check_boxes)[-2:] == ["run_publish", "run_chapter"] and [cb.text() for cb in health.check_boxes.values()]
          == [hc._BY_KEY[k].label for k in expected], str(list(health.check_boxes)))
    check("檔名：勾著、停用（一律跟著跑）", health.filename_box.isChecked() and not health.filename_box.isEnabled())
    off = ("run_audio", "run_subsync", "run_publish")
    check("勾不勾照目前的設定：音訊關、發佈資訊關、語音同步預設關、其他開",
          not any(health.check_boxes[k].isChecked() for k in off)
          and all(cb.isChecked() for k, cb in health.check_boxes.items() if k not in off))
    labels = " ".join(w.text() for w in health.findChildren(type(health.status_label)))
    check("頁面寫明發佈文字、章節、封面圖、系列一致性還在一般版，也寫到「修復此項」",
          all(word in labels for word in ("發佈文字", "章節", "封面圖", "系列一致性", "修復此項", "還在一般版")))
    check("狀態列：有②與③", "③健檢中心" in win.statusBar().currentMessage()
          and "②字幕頁" in win.statusBar().currentMessage(), win.statusBar().currentMessage())
    check("開始前先套用逐句校對改到一半的", health.before_scan == win.cue_panel.commit)

    # ----- 3. 不跑的情況 -----
    win.tabs.setCurrentIndex(2)
    wait(50)
    check("什麼都沒開：上方寫還沒開、沒字幕", "還沒開" in health.target_label.text()
          and "沒有" in health.target_label.text(), health.target_label.text())
    check("什麼都沒開：不跑、講原因", health.start_scan() is False and health.status_label.text() == hp.NOTHING
          and not health.busy())

    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0)
    panel.load_subtitles(srt)
    check("載了字幕：上方對象跟著更新（字幕改了有訊號）", "字幕：3 句" in health.target_label.text(),
          health.target_label.text())
    win.tabs.setCurrentIndex(1)
    health.target_label.setText("舊的")  # 換影片沒有訊號：切回這頁時要重寫
    win.tabs.setCurrentIndex(2)
    wait(50)
    check("切回這頁：重寫上方對象、寫出影片檔名", "訪談 final.mp4" in health.target_label.text(), health.target_label.text())

    saved = {k: cb.isChecked() for k, cb in health.check_boxes.items()}
    for cb in health.check_boxes.values():
        cb.setChecked(False)
    check("一項都沒勾：不跑、講原因", health.start_scan() is False and health.status_label.text() == hp.NONE_CHECKED)
    for k, cb in health.check_boxes.items():
        cb.setChecked(saved[k])

    # ----- 4. 跑 -----
    health.check_boxes["run_color"].setChecked(False)  # 取消一項，等一下看有沒有記住
    keys = health.selected_keys()
    order = []
    health.before_scan = lambda: order.append(("先套用", health.busy()))
    QTest.mouseClick(health.run_btn, Qt.LeftButton)
    health.before_scan = win.cue_panel.commit
    check("按開始：先套用逐句校對（開始跑之前）", order == [("先套用", False)], str(order))
    check("跑的期間：按鈕停用、勾選停用、再按不會重跑", health.busy() and not health.run_btn.isEnabled()
          and not health.check_boxes["run_video"].isEnabled() and health.start_scan() is False)
    shown = []
    real_show = health.show_result
    health.show_result = lambda res: (shown.append(health.busy()), real_show(res))
    check("跑完：結果畫上去之前都還算在忙（不會在空檔又按開始）", wait_until(lambda: not health.busy())
          and health.last_result is not None and shown == [True], health.status_label.text())
    del health.show_result
    result = health.last_result
    direct = hc.run_health_scan(main, [dict(c) for c in panel.cues], dict(cfg), keys)

    def brief(res):
        return [(f["level"], f["source"], f["title"], f.get("detail")) for f in res["findings"]]

    check("結果跟直接呼叫 run_health_scan（同樣的項目）一模一樣", brief(result) == brief(direct)
          and result["skipped"] == direct["skipped"] and result["grade"] == direct["grade"], str(brief(result)))
    ran = {s["name"] for s in result["sections"]}
    check("勾掉的項目沒跑、沒勾的檔名照跑、字幕健檢有跑",
          "畫面曝光與色偏" not in ran and "音訊健檢" not in ran and "檔名" in ran and "字幕健檢" in ran, str(ran))
    findings = result["findings"]
    check("字幕健檢真的抓到問題", any(f["source"] == "字幕健檢" and f["level"] != hc.LEVEL_GOOD for f in findings))

    top = [health.tree.topLevelItem(i) for i in range(health.tree.topLevelItemCount())]
    counts = result["counts"]
    head = [f"一定要修（{counts[hc.LEVEL_BAD]}）", f"建議修（{counts[hc.LEVEL_WARN]}）",
            f"通過（{counts[hc.LEVEL_GOOD]}）"]
    check("分組與計數", [t.text(0) for t in top[:3]] == head
          and [t.childCount() for t in top[:3]] == [counts[hc.LEVEL_BAD], counts[hc.LEVEL_WARN], counts[hc.LEVEL_GOOD]],
          str([t.text(0) for t in top]))
    check("通過的收合、要修的展開", not top[2].isExpanded() and top[1].isExpanded() and top[0].isExpanded())
    rows = health.finding_items()
    check("清單上每一列對到一筆結果（圖示＋標題、來源）", len(rows) == len(findings) and all(
        item.text(0).endswith(row["title"]) and item.text(1) == row["source"] for item, row in rows))
    if result["skipped"]:
        check("略過的項目另外一組", top[3].text(0) == f"略過的項目（{len(result['skipped'])}）")
    else:
        check("沒有略過的項目就沒有那一組", len(top) == 3)
    health.show_result(dict(result, skipped=["語音同步：沒有字幕，已略過", "找不到 ffmpeg"]))
    last = health.tree.topLevelItem(health.tree.topLevelItemCount() - 1)
    check("有略過的項目：另外一組、展開、逐條列出", last.text(0) == "略過的項目（2）" and last.isExpanded()
          and [last.child(i).text(0) for i in range(2)] == ["・語音同步：沒有字幕，已略過", "・找不到 ffmpeg"])
    health.show_result(result)
    rows = health.finding_items()
    top = [health.tree.topLevelItem(i) for i in range(health.tree.topLevelItemCount())]
    grade = result["grade"]
    check("狀態寫準備度", f"準備度 {grade}" in health.status_label.text(), health.status_label.text())

    warn = next((item, row) for item, row in rows if row["level"] != hc.LEVEL_GOOD and row.get("advice"))
    health.tree.setCurrentItem(warn[0])
    text = health.detail.toPlainText()
    check("點一筆：詳情寫來源、標題、內容、建議", text.startswith(f"{hp.LEVEL_ICONS[warn[1]['level']]} "
                                                   f"[{warn[1]['source']}] {warn[1]['title']}")
          and warn[1]["detail"] in text and f"建議：{warn[1]['advice']}" in text, text)
    health.tree.setCurrentItem(top[0])
    check("點分組標題：詳情清空", health.detail.toPlainText() == "")

    QTest.mouseClick(health.copy_btn, Qt.LeftButton)
    check("複製報告＝一般版的純文字報告", QApplication.clipboard().text() == hc.format_health_report(result)
          and "已複製" in health.status_label.text())

    # ----- 5. 記住勾選 -----
    check("取消的項目記在這次開啟的設定（同一份）", health.config is cfg and cfg["preflight"]["run_color"] is False
          and cfg["preflight"]["run_audio"] is False and cfg["preflight"]["run_video"] is True)
    check("發佈資訊照勾選（沒勾）、這頁看不到的封面維持原本的值、章節照勾選（勾著）", cfg["healthcenter"]["run_publish"] is False
          and cfg["healthcenter"]["run_thumb"] is True and cfg["healthcenter"]["run_chapter"] is True,
          str(cfg["healthcenter"]))
    check("沒寫 config.json", not os.path.exists(config.CONFIG_PATH))
    win2 = qt_app.MainWindow(cfg)
    check("同一份設定再開一個視窗：勾選照記住的", not win2.health_panel.check_boxes["run_color"].isChecked()
          and win2.health_panel.check_boxes["run_video"].isChecked())
    win2.player_panel.shutdown()
    win2.close()

    # ----- 6. 背景失敗 -----
    real = hc.run_health_scan

    def boom(*_a, **_k):
        raise RuntimeError("假的掃描失敗")

    hc.run_health_scan = boom
    try:
        check("背景失敗：開始了", health.start_scan() is True)
        wait_until(lambda: not health.busy(), 5000)
        wait(50)
    finally:
        hc.run_health_scan = real
    from subtitle.errors import describe_exception
    check("背景失敗：講原因（同其他地方的白話說明）、按鈕恢復、上次的結果還能複製",
          health.status_label.text() == f"健檢失敗：{describe_exception(RuntimeError('假的掃描失敗'))}"
          and not health.busy() and health.run_btn.isEnabled()
          and health.run_btn.text() == "開始健檢" and health.copy_btn.isEnabled()
          and all(cb.isEnabled() for cb in health.check_boxes.values()), health.status_label.text())
    check("勾選框都還在（不是 QCheckBox 以外的東西）",
          all(isinstance(cb, QCheckBox) for cb in health.check_boxes.values()))

    panel._ask_project_discard = lambda: "discard"
    panel._ask_discard = lambda: "discard"
    panel.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 ③健檢中心測試全數通過。")
