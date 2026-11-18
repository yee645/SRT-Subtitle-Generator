# -*- coding: utf-8 -*-
"""
3.0 第 11 項第十九階段：①審片助手的封面候選，以及「輸出」框改成分頁。

取樣、評分、挑選的規則在 test_thumbnails*.py；這裡驗介面與接線，結果跟直接呼叫核心比對。
測試影片用 ffmpeg 產生（40 秒、960 寬：前 20 秒一片灰、後 20 秒是有細節的測試畫面）；字幕四句，第三句又大聲又有
情緒詞（精彩）。

1. 「輸出」框分三頁：影片與匯出、發佈、封面候選；各顆鈕在對的那一頁；一開始停在「影片與匯出」。
2. 封面候選那一頁：張數、最小間隔、優先取精彩段落照目前的設定、範圍跟一般版一樣；說明寫會加進③、不送出去；
   還沒分析時鈕灰著、按了不做事。
3. 不擷取的情況講原因：沒開影片、沒有 ffmpeg。
4. 擷取：背景跑、跑的時候所有鈕灰掉、不能重跑也不能分析或輸出影片；檔名 `_封面01.png`…、放在影片旁邊；
   張數、時間、分數跟直接呼叫核心一樣（照分數排）；寬度照設定（設定裡別的項目留著並照用）。
5. 擷取完：下面列出縮圖（#名次 時間）；點一張，②的播放器跳到那一格；加進③的「封面圖」（那一塊展開）；
   狀態列講幾張、在哪、帶進③。再擷取一次不覆蓋、③多三張；同樣幾張再送一次③不重複加，狀態列照實講。
6. 張數、最小間隔、優先取精彩寫進這次開啟的設定，下一次照著擷取；「輸出設定」指定了資料夾就放那裡。
7. 背景失敗：講原因、鈕亮回來、③不動。擷取中關視窗：先問（講封面候選），選否就不關。沒接③：只輸出。
8. 全程不寫 config.json；原檔不動。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過①審片助手的封面候選")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import review_panel as rp  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import exporter, thumbnails  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")
    work = os.path.join(tmp, "素材夾")
    os.makedirs(work)

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait_until(cond, timeout_ms=90000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(50)
            waited += 50
        return cond()

    def run(*args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)

    def width_of(path):
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width",
                              "-of", "csv=p=0", path], capture_output=True, text=True).stdout
        return int(out.strip() or 0)

    main = os.path.join(work, "素材.mp4")
    flat, busy = os.path.join(tmp, "flat.mp4"), os.path.join(tmp, "busy.mp4")
    run("-f", "lavfi", "-i", "color=c=gray:s=960x540:r=15:d=20", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", flat)
    run("-f", "lavfi", "-i", "testsrc=s=960x540:r=15:d=20", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", busy)
    listing = os.path.join(tmp, "list.txt")
    with open(listing, "w", encoding="utf-8") as f:
        f.write(f"file '{flat}'\nfile '{busy}'\n")
    run("-f", "concat", "-safe", "0", "-i", listing, "-f", "lavfi", "-i",
        "aevalsrc='(0.03+0.9*between(t\\,24\\,27))*sin(2*PI*440*t)':d=40:s=22050",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", main)
    CUES = [{"start": 2.0, "end": 6.0, "text": "大家好今天要來介紹這台新的相機"},
            {"start": 12.0, "end": 16.0, "text": "先看外觀這個握把的手感非常好"},
            {"start": 24.0, "end": 27.0, "text": "天啊這個畫質也太誇張了吧！真的超級無敵厲害！"},
            {"start": 33.0, "end": 37.0, "text": "最後總結一下這台相機值得買"}]
    srt = os.path.join(work, "素材.srt")
    exporter.export(CUES, srt)
    original = (os.path.getsize(main), os.path.getmtime(main))

    cfg = {"thumbnails": {"count": 3, "min_spacing": 4.0, "prefer_highlights": True, "width": 640}}
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.show()
    wait(50)
    panel = win.review_panel
    health = win.health_panel
    player = win.player_panel
    player._ask_discard = lambda *a, **k: "discard"
    player._ask_project_discard = lambda *a, **k: "discard"
    panel._ask_adopt = lambda result: False
    btn = panel.thumb_btn

    def analyze():
        assert panel.start_analysis() is True
        assert wait_until(lambda: not panel.busy())

    def core(settings, folder):
        """直接呼叫核心（同樣的段落、片長、設定），輸出到另一個資料夾：拿來比對。"""
        os.makedirs(folder, exist_ok=True)
        return thumbnails.generate_thumbnails(main, panel.items, panel.duration,
                                              output_paths=lambda rank: os.path.join(folder, f"c{rank}.png"),
                                              settings=settings)

    def summary(results):
        return [(round(r["time"], 3), round(r["score"], 3)) for r in results]

    # ----- 1. 「輸出」框分三頁 -----
    tabs = panel.out_tabs
    check("「輸出」框分三頁：影片與匯出、發佈、封面候選", [tabs.tabText(i) for i in range(tabs.count())]
          == ["影片與匯出", "發佈", "封面候選"])
    check("一開始停在「影片與匯出」", tabs.currentIndex() == 0)
    pages = panel.out_pages
    check("各顆鈕在對的那一頁", all(pages["video"].isAncestorOf(b) for b in
                                   (*panel.cut_buttons.values(), *panel.export_buttons.values(), panel.fillers_box))
          and all(pages["publish"].isAncestorOf(b) for b in (*panel.publish_buttons.values(), panel.chapter_spin,
                                                            panel.ad_spacing_spin, panel.ad_max_spin))
          and all(pages["thumbs"].isAncestorOf(w) for w in (btn, panel.thumb_count_spin, panel.thumb_spacing_spin,
                                                           panel.thumb_highlight_box, panel.thumb_strip)))
    check("頁面說明：封面候選在「輸出」的「封面候選」那一頁，只剩直式短片還在一般版",
          "「封面候選」挑清晰、有內容的畫面輸出 PNG，帶進③的「封面圖」" in rp.PAGE_NOTE
          and "直式短片還在一般版" in rp.PAGE_NOTE and "封面候選、直式短片還在一般版" not in rp.PAGE_NOTE)
    check("狀態列提到封面候選", "章節與發佈包、封面候選）" in win.statusBar().currentMessage())

    # ----- 2. 封面候選那一頁 -----
    check("鈕的文字跟一般版一樣", btn.text() == "擷取封面候選圖")
    check("數值照目前的設定", panel.thumb_count_spin.value() == 3 and panel.thumb_spacing_spin.value() == 4.0
          and panel.thumb_highlight_box.isChecked())
    check("範圍跟一般版一樣", (panel.thumb_count_spin.minimum(), panel.thumb_count_spin.maximum()) == (2, 12)
          and (panel.thumb_spacing_spin.minimum(), panel.thumb_spacing_spin.maximum()) == (1.0, 120.0))
    labels = " ".join(w.text() for w in panel.findChildren(QLabel))
    check("說明寫加進③、點一張會跳、不覆蓋、不送出去", rp.THUMB_NOTE in labels and all(
        w in rp.THUMB_NOTE for w in ("③健檢中心的「封面圖」", "點一張", "不覆蓋", "不送任何東西出去")))
    check("還沒分析：鈕灰著、按了不做事", not btn.isEnabled() and panel.start_thumbnails() is False)
    check("下面的縮圖列一開始是空的", panel.thumb_strip.count() == 0 and panel.last_thumbs == [])

    # ----- 3. 不擷取的情況 -----
    player.set_cues(CUES)
    analyze()
    check("分析完：鈕亮了", btn.isEnabled())
    check("沒開影片：不擷取、講原因", panel.start_thumbnails() is False and panel.status_label.text() == rp.NO_MEDIA
          and not panel.busy())
    player.open_video(main)
    wait_until(lambda: player.player.duration() > 0, 20000)
    wait(100)
    player.load_subtitles(srt)
    analyze()
    real_ffmpeg = rp.ffmpeg_available
    rp.ffmpeg_available = lambda: False
    try:
        check("沒有 ffmpeg：不擷取、講原因", panel.start_thumbnails() is False
              and panel.status_label.text() == rp.NO_FFMPEG_THUMBS and "ffmpeg" in rp.NO_FFMPEG_THUMBS)
    finally:
        rp.ffmpeg_available = real_ffmpeg
    check("到這裡什麼圖都沒輸出", sorted(os.listdir(work)) == ["素材.mp4", "素材.srt"], str(os.listdir(work)))

    # ----- 4. 擷取 -----
    tabs.setCurrentWidget(pages["thumbs"])
    every = [*panel.cut_buttons.values(), *panel.export_buttons.values(), *panel.publish_buttons.values(), btn]
    QTest.mouseClick(btn, Qt.LeftButton)
    state = {"busy": panel.busy(), "cutting": panel.cutting(), "buttons": [b.isEnabled() for b in every],
             "analyze": panel.analyze_btn.isEnabled(), "again": panel.start_thumbnails(),
             "cut": panel.start_cut("roughcut"), "analysis": panel.start_analysis(),
             "progress": panel.progress_bar.isVisibleTo(panel), "status": panel.status_label.text()}
    wait_until(lambda: not panel.busy())
    check("按下去：背景跑、所有鈕灰掉、進度條出現", state["busy"] and state["cutting"] and not any(state["buttons"])
          and not state["analyze"] and state["progress"], str(state))
    check("跑的期間：不能重跑、不能輸出影片、不能分析", state["again"] is False and state["cut"] is False
          and state["analysis"] is False)
    check("跑的期間狀態列講在擷取幾張", "正在擷取封面候選（3 張）" in state["status"] or "評分" in state["status"],
          state["status"])
    results = panel.last_thumbs
    names = [os.path.basename(r["path"]) for r in results]
    check("做完：三張，檔名加「_封面01」…、放在影片旁邊", names == ["素材_封面01.png", "素材_封面02.png", "素材_封面03.png"]
          and all(os.path.dirname(r["path"]) == work and os.path.exists(r["path"]) for r in results), str(names))
    settings = thumbnails.resolve_thumbnail_settings(cfg)
    direct = core(settings, os.path.join(tmp, "核心"))
    check("時間與分數跟直接呼叫核心一樣（照分數排）", summary(results) == summary(direct)
          and [r["score"] for r in results] == sorted((r["score"] for r in results), reverse=True),
          f"{summary(results)} {summary(direct)}")
    check("排第一的是有細節的那一半（灰的那一半清晰度最低）", results[0]["time"] >= 20.0, str(summary(results)))
    check("寬度照設定裡的 640（設定裡別的項目留著並照用；預設 1280 的話會是原寬 960）",
          all(width_of(r["path"]) == 640 for r in results)
          and cfg["thumbnails"]["width"] == 640)
    check("做完：鈕亮回來、進度條收起來", all(b.isEnabled() for b in every) and not panel.progress_bar.isVisibleTo(panel)
          and not panel.cutting())

    # ----- 5. 擷取完 -----
    strip = panel.thumb_strip
    texts = [strip.item(i).text() for i in range(strip.count())]
    check("下面列出三張縮圖：#名次 時間、有圖", texts == [f"#{n} {rp.clock(r['time'])}" for n, r in enumerate(results, 1)]
          and all(not strip.item(i).icon().isNull() for i in range(strip.count())), str(texts))
    check("縮圖的提示寫路徑、時間、分數", results[1]["path"] in strip.item(1).toolTip()
          and rp.clock(results[1]["time"]) in strip.item(1).toolTip() and "清晰度" in strip.item(1).toolTip())
    player.player.setPosition(0)
    wait(100)
    target = strip.item(2)
    rect = strip.visualItemRect(target)
    QTest.mouseClick(strip.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    wait_until(lambda: abs(player.player.position() - results[2]["time"] * 1000) < 150, 5000)
    check("點一張：②的播放器跳到那一格", abs(player.player.position() - results[2]["time"] * 1000) < 150,
          f"{player.player.position()} {results[2]['time']}")
    paths = [r["path"] for r in results]
    check("加進③的「封面圖」、那一塊展開了", health.thumb_paths() == paths and health.thumb_body.isVisibleTo(health))
    status = panel.status_label.text()
    check("狀態列：幾張、在哪、每張的檔名與時間、帶進③", "共 3 張" in status and work in status and rp.SENT_THUMBS in status
          and all(f"{n}（{rp.clock(r['time'])} 處）" in status for n, r in zip(names, results)), status)
    panel._on_thumbs_finished(results)
    check("同樣幾張再送一次③：不重複加，狀態列照實講", health.thumb_paths() == paths
          and "已經有這幾張了" in panel.status_label.text() and rp.SENT_THUMBS not in panel.status_label.text())
    check("沒擷取到：講出來", (panel._on_thumbs_finished([]), panel.status_label.text())[1] == "沒有擷取到封面候選。"
          and panel.thumb_strip.count() == 0)

    # ----- 6. 設定、再擷取、輸出資料夾 -----
    panel.thumb_count_spin.setValue(2)
    panel.thumb_spacing_spin.setValue(6)
    panel.thumb_highlight_box.setChecked(False)
    check("再擷取一次", panel.start_thumbnails() is True and wait_until(lambda: not panel.busy()))
    check("張數、最小間隔、優先取精彩寫進這次開啟的設定（寬度留著）", cfg["thumbnails"] == {
        "count": 2, "min_spacing": 6.0, "prefer_highlights": False, "width": 640}, str(cfg["thumbnails"]))
    second = panel.last_thumbs
    direct = core(thumbnails.resolve_thumbnail_settings(cfg), os.path.join(tmp, "核心2"))
    check("照新的設定擷取（跟核心一樣）", summary(second) == summary(direct) and len(second) == 2, str(summary(second)))
    check("不覆蓋：檔名加編號、第一次的還在", [os.path.basename(r["path"]) for r in second]
          == ["素材_封面01 (1).png", "素材_封面02 (1).png"] and all(os.path.exists(p) for p in paths),
          str([r["path"] for r in second]))
    check("③多了兩張", health.thumb_paths() == paths + [r["path"] for r in second])
    out_dir = os.path.join(tmp, "輸出夾")
    cfg["automation"] = {"output_dir": out_dir}
    check("「輸出設定」指定了資料夾：放那裡", panel.start_thumbnails() is True and wait_until(lambda: not panel.busy())
          and all(os.path.dirname(r["path"]) == out_dir and os.path.exists(r["path"]) for r in panel.last_thumbs),
          str(panel.last_thumbs))
    cfg.pop("automation")
    other = os.path.join(tmp, "別處")
    os.makedirs(other)
    elsewhere = os.path.join(other, "另一份字幕.srt")
    exporter.export(CUES, elsewhere)
    player.load_subtitles(elsewhere)
    check("字幕檔放在別處、名字不同：封面照樣跟著影片取名、放在影片旁邊",
          panel.start_thumbnails() is True and wait_until(lambda: not panel.busy())
          and all(os.path.dirname(r["path"]) == work and os.path.basename(r["path"]).startswith("素材_封面")
                  for r in panel.last_thumbs) and os.listdir(other) == ["另一份字幕.srt"], str(panel.last_thumbs))

    # ----- 7. 背景失敗、關視窗、沒接③ -----
    real_generate = thumbnails.generate_thumbnails

    def boom(*args, **kwargs):
        raise RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。")
    thumbnails.generate_thumbnails = boom
    before = health.thumb_paths()
    try:
        check("背景失敗：開始了", panel.start_thumbnails() is True)
        wait_until(lambda: not panel.busy())
        check("背景失敗：講原因、鈕亮回來、③不動", panel.status_label.text().startswith("擷取封面候選失敗：")
              and btn.isEnabled() and not panel.cutting() and health.thumb_paths() == before, panel.status_label.text())
    finally:
        thumbnails.generate_thumbnails = real_generate

    closing = []
    panel.ask_close_while_cutting = lambda: (closing.append(panel.close_question()), False)[1]
    QTest.mouseClick(btn, Qt.LeftButton)
    check("擷取中", panel.cutting() and panel.thumber.busy)
    win.close()
    check("擷取中關視窗：先問（講的是封面候選），選否就不關", len(closing) == 1 and win.isVisible()
          and "封面候選圖還在輸出" in closing[0] and "可能不完整" in closing[0], str(closing))
    wait_until(lambda: not panel.busy())
    win.close()
    check("擷取完再關：不問", len(closing) == 1)
    win.show()
    wait(50)

    real_hook = panel.on_thumbnails
    panel.on_thumbnails = None
    before = health.thumb_paths()
    panel.start_thumbnails()
    wait_until(lambda: not panel.busy())
    last = panel.last_thumbs
    check("沒接③：只輸出，③不動、狀態列講完輸出就結束（不提③）", last and health.thumb_paths() == before
          and panel.status_label.text() == f"封面候選輸出完成，共 {len(last)} 張（照畫面清晰度排名，在 {work}）："
          + "、".join(f"{os.path.basename(r['path'])}（{rp.clock(r['time'])} 處）" for r in last) + "。",
          panel.status_label.text())
    panel.on_thumbnails = real_hook

    check("全程沒寫 config.json", not os.path.exists(config.CONFIG_PATH))
    check("原檔到最後都沒動", (os.path.getsize(main), os.path.getmtime(main)) == original)

    player.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 ①審片助手（封面候選）測試全數通過。")
