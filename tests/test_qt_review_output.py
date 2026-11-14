# -*- coding: utf-8 -*-
"""
3.0 第 11 項第十七階段：①審片助手的輸出（粗剪影片、精彩合輯、剪除口頭禪字、四種匯出）。

剪片與匯出的規則在 test_review*.py；這裡驗介面與接線，ffmpeg 真的剪、量結果。
測試影片用 ffmpeg 產生（30 秒：0～10 秒紅、10～20 秒綠、20～30 秒藍；12～15 秒特別大聲）；字幕三句，
各落在一種顏色裡，第二句又大聲又有情緒詞（精彩），第一、二句中間隔八秒（冷場）。

1. 「輸出」框：兩顆輸出鈕、剪除口頭禪字、四顆匯出鈕；還沒分析時都灰著；說明寫原檔不動、不能停。
   「剪除口頭禪字」照設定勾、勾了寫進這次開啟的設定、時間軸的審片建議剪點跟著重算。
2. 不輸出的情況都講原因：沒開影片、沒有保留的段落、沒有精彩片段、沒有 ffmpeg；匯出時沒影片也沒字幕檔。
3. 粗剪：背景跑、跑的時候鈕灰掉、不能重跑也不能分析；檔名 `_粗剪.mp4`、放在影片旁邊；片長＝保留段落的
   總長；畫面依序是紅、綠、藍（冷場真的剪掉了）；旁邊的字幕跟直接呼叫核心對齊的一樣；原檔不動。
4. 做好後問要不要在②換成它：選否，②不變。再輸出一次不覆蓋（檔名加編號）；清單改過（捨棄一段）片子跟著短。
5. 精彩合輯：只有標了精彩的那一段（綠）、檔名 `_精彩合輯.mp4`；那一段在清單上被捨棄也照樣進合輯。
6. 「輸出設定」指定了資料夾：放那裡。
7. 四種匯出：檔名跟一般版一樣、內容跟直接呼叫核心一模一樣；EDL 照「剪除口頭禪字」；匯出失敗講原因。
8. 背景失敗：講原因、鈕亮回來。輸出中關視窗：先問，選否就不關。
9. 選「是」：專案或字幕有沒存的變更先問，沒處理就不換；處理了就換——②的影片是剪好的那支、字幕是對齊好
   的那一份；清單標成舊的。
"""
import filecmp
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過①審片助手的輸出")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import review_panel as rp  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import cutmarks, exporter, review  # noqa: E402
    from subtitle.importer import load_subtitle_file  # noqa: E402

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

    def seconds(path):
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True).stdout
        return float(out.strip())

    def color_at(path, t):
        """t 秒那一格是紅、綠還是藍。"""
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", path, "-frames:v", "1", "-vf", "scale=1:1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        return ("紅", "綠", "藍")[max(range(3), key=lambda n: raw[n])] if len(raw) == 3 else "?"

    main = os.path.join(work, "素材.mp4")
    parts = []
    for n, color in enumerate(("red", "green", "blue")):
        part = os.path.join(tmp, f"p{n}.mp4")
        run("-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=30:d=10", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", part)
        parts.append(part)
    listing = os.path.join(tmp, "list.txt")
    with open(listing, "w", encoding="utf-8") as f:
        f.writelines(f"file '{p}'\n" for p in parts)
    run("-f", "concat", "-safe", "0", "-i", listing, "-f", "lavfi", "-i",
        "aevalsrc='(0.03+0.9*between(t\\,12\\,15))*sin(2*PI*440*t)':d=30:s=22050",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", main)
    CUES = [{"start": 1.0, "end": 4.0, "text": "大家好今天要來介紹這台新的相機"},
            {"start": 12.0, "end": 15.0, "text": "天啊這個畫質也太誇張了吧！真的超級無敵厲害！"},
            {"start": 22.0, "end": 25.0, "text": "最後總結一下這台相機值得買"}]
    srt = os.path.join(work, "素材.srt")
    exporter.export(CUES, srt)
    original = (os.path.getsize(main), os.path.getmtime(main))

    cfg = {"review": {"cut_filler_words": True, "chapter_min_seconds": 10.0}}
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.show()
    wait(50)
    panel = win.review_panel
    player = win.player_panel
    asked = []
    answer = {"adopt": False}
    panel._ask_adopt = lambda result: (asked.append(dict(result)), answer["adopt"])[1]
    cut_btns = panel.cut_buttons
    all_buttons = [*cut_btns.values(), *panel.export_buttons.values()]

    def analyze():
        assert panel.start_analysis() is True
        assert wait_until(lambda: not panel.busy())

    def cut(kind):
        """按那顆鈕，等它做完。回傳 (按下去那一刻的樣子, 結果)。"""
        before = panel.last_cut
        QTest.mouseClick(cut_btns[kind], Qt.LeftButton)
        state = {"busy": panel.busy(), "cutting": panel.cutting(), "buttons": [b.isEnabled() for b in all_buttons],
                 "analyze": panel.analyze_btn.isEnabled(), "again": panel.start_cut(kind),
                 "analysis": panel.start_analysis(), "export": panel.export("csv"),
                 "progress": panel.progress_bar.isVisibleTo(panel), "status": panel.status_label.text(),
                 "fillers": panel.fillers_box.isEnabled()}
        wait_until(lambda: not panel.busy())
        return state, (panel.last_cut if panel.last_cut is not before else None)

    # ----- 1. 「輸出」框 -----
    check("兩顆輸出鈕、四顆匯出鈕，文字跟一般版一樣",
          [b.text() for b in all_buttons] == ["輸出粗剪影片（自動跳剪）", "輸出精彩合輯（短影音素材）", "匯出 EDL（進剪輯軟體）",
                                              "匯出審片標記字幕", "匯出 CSV 清單", "匯出 HTML 審片報告"])
    check("還沒分析：輸出與匯出的鈕都灰著", not any(b.isEnabled() for b in all_buttons))
    check("說明寫原檔不動、不能停、會放對齊的字幕", all(w in rp.OUTPUT_NOTE for w in ("原檔不動", "不能停", "對齊到剪後時間的字幕")))
    check("頁面說明：粗剪與匯出在這頁，章節、封面候選、直式短片還在一般版",
          "下面「輸出」照保留的段落輸出粗剪影片、精彩合輯" in rp.PAGE_NOTE
          and "章節與發佈包、廣告插入點、封面候選、直式短片還在一般版" in rp.PAGE_NOTE)
    check("狀態列提到粗剪與匯出", "①的審片助手（分析、段落清單、粗剪與匯出）" in win.statusBar().currentMessage())
    check("「剪除口頭禪字」照設定勾", panel.fillers_box.isChecked() and panel.fillers_box.isEnabled())
    refreshed = []
    real_refresh = player.refresh_cut_marks
    player.refresh_cut_marks = lambda: (refreshed.append(1), real_refresh())[1]
    panel.fillers_box.setChecked(False)
    check("取消勾選：寫進這次開啟的設定（別的項目留著）、時間軸剪點跟著重算",
          cfg["review"]["cut_filler_words"] is False and cfg["review"]["chapter_min_seconds"] == 10.0 and refreshed == [1])
    player.refresh_cut_marks = real_refresh
    check("沒寫 config.json", not os.path.exists(config.CONFIG_PATH))

    # ----- 2. 不輸出的情況 -----
    player.set_cues(CUES)  # 只有字幕、沒有影片也沒有字幕檔
    analyze()
    check("分析完：輸出與匯出的鈕亮了", all(b.isEnabled() for b in all_buttons))
    check("沒開影片：不輸出、講原因", panel.start_cut("roughcut") is False and panel.status_label.text() == rp.NO_MEDIA
          and not panel.cutting())
    check("沒影片也沒字幕檔：不匯出、講原因", panel.export("csv") == "" and panel.status_label.text() == rp.NO_BASE
          and panel.default_path("_x", ".csv") == "")
    player.load_subtitles(srt)
    analyze()
    path = panel.export("csv")
    check("只載了字幕檔：匯出放在字幕檔旁邊", path == os.path.join(work, "素材_審片清單.csv") and os.path.exists(path), path)
    os.remove(path)

    player.open_video(main)
    wait_until(lambda: player.player.duration() > 0, 20000)
    wait(100)
    analyze()
    items = panel.items
    kinds = [(i["kind"], review.categorize(i), i["keep"]) for i in items]
    check("分析結果：三句講話、中間與前後的冷場；第二句是精彩", [k for k in kinds if k[0] == "speech"]
          == [("speech", "normal", True), ("speech", "highlight", True), ("speech", "normal", True)]
          and any(k[0] == "silence" for k in kinds), str(kinds))
    speech = [n for n, i in enumerate(items) if i["kind"] == "speech"]
    for i in items:
        i["keep"] = False
    panel.repopulate()
    check("沒有保留的段落：不輸出、講原因", panel.start_cut("roughcut") is False and panel.status_label.text() == rp.NO_KEPT)
    panel.apply_suggestions()
    saved_tags = [list(i["tags"]) for i in items]
    for i in items:
        i["tags"] = [t for t in i["tags"] if t != review.TAG_HIGHLIGHT]
    check("沒有精彩片段：合輯不輸出、講原因", panel.start_cut("highlight") is False
          and panel.status_label.text() == rp.NO_HIGHLIGHT and "輸出粗剪影片" in rp.NO_HIGHLIGHT)
    for i, tags in zip(items, saved_tags):
        i["tags"] = tags
    real_ffmpeg = rp.ffmpeg_available
    rp.ffmpeg_available = lambda: False
    try:
        check("沒有 ffmpeg：不輸出、講原因", panel.start_cut("roughcut") is False
              and panel.status_label.text() == rp.NO_FFMPEG and not panel.cutting())
    finally:
        rp.ffmpeg_available = real_ffmpeg
    try:
        panel.start_cut("nope")
        check("不認得的輸出：不收", False)
    except ValueError:
        check("不認得的輸出：不收", True)
    check("到這裡什麼影片都沒輸出", sorted(os.listdir(work)) == ["素材.mp4", "素材.srt"], str(os.listdir(work)))

    # ----- 3. 粗剪 -----
    keep = review.kept_ranges(items)
    total = sum(e - s for s, e in keep)
    state, result = cut("roughcut")
    check("按「輸出粗剪影片」：背景跑、鈕都灰掉、進度條出現", state["busy"] and state["cutting"]
          and not any(state["buttons"]) and not state["analyze"] and state["progress"], str(state))
    check("跑的期間：不能重跑、不能分析、不能匯出", state["again"] is False and state["analysis"] is False
          and state["export"] == "")
    check("跑的期間狀態列寫檔名、原檔不動、不能停", "素材_粗剪.mp4" in state["status"] and "原檔不動" in state["status"]
          and "不能停" in state["status"], state["status"])
    check("跑的期間「剪除口頭禪字」也灰掉（做完亮回來）", state["fillers"] is False and panel.fillers_box.isEnabled())
    rough = os.path.join(work, "素材_粗剪.mp4")
    check("做完：檔名加「_粗剪」、放在影片旁邊", result is not None and result["kind"] == "roughcut"
          and result["output"] == rough and os.path.exists(rough), str(result))
    check("做完：鈕亮回來、進度條收起來", all(b.isEnabled() for b in all_buttons) and panel.analyze_btn.isEnabled()
          and not panel.progress_bar.isVisibleTo(panel) and not panel.cutting())
    check("片長＝保留段落的總長（三句加前後緩衝，約 9.9 秒）", abs(seconds(rough) - total) < 0.25 and 9.5 < total < 10.3,
          f"{seconds(rough)} {total}")
    colors = [color_at(rough, t) for t in (1.5, 5.0, 8.5)]
    check("畫面依序是紅、綠、藍（冷場剪掉了）", colors == ["紅", "綠", "藍"], str(colors))
    aligned, dropped = cutmarks.remap_cues(CUES, keep)
    subs = os.path.join(work, "素材_粗剪.srt")
    got = load_subtitle_file(subs)["cues"] if os.path.exists(subs) else []
    check("旁邊放一份對齊到剪後時間的字幕（跟核心算的一樣）", result["subtitles"] == subs and result["dropped"] == dropped == 0
          and [(round(c["start"], 2), round(c["end"], 2), c["text"]) for c in got]
          == [(round(c["start"], 2), round(c["end"], 2), c["text"]) for c in aligned]
          and abs(got[1]["start"] - 3.45) < 0.02, str(got))
    check("原檔不動", (os.path.getsize(main), os.path.getmtime(main)) == original)
    check("狀態列：輸出到哪、旁邊有字幕", "粗剪已輸出：素材_粗剪.mp4" in panel.status_label.text()
          and "素材_粗剪.srt" in panel.status_label.text(), panel.status_label.text())
    check("沒有整句被剪掉：狀態列不提", "整句被剪掉" not in panel.status_label.text())

    # ----- 4. 問要不要換、再輸出一次 -----
    check("做好後問要不要在②換成它（選否：②不變）", len(asked) == 1 and asked[0]["output"] == rough
          and player.media_path == main and len(player.cues) == 3 and player.cues[1]["start"] == 12.0)
    question = panel.adopt_question(result)
    check("問的那段話：講字幕會換成對齊好的、選否只是輸出檔案", "素材_粗剪.mp4" in question and "對齊到剪後時間" in question
          and "選「否」只是輸出檔案" in question and "素材軌與畫面調整會清掉" in question, question)
    check("沒有對齊字幕時，問的話講字幕會清掉", "②的字幕會清掉" in panel.adopt_question(dict(result, subtitles="")))
    panel.select_segment(speech[2])
    panel.toggle_selected()
    state, second = cut("roughcut")
    check("再輸出一次：不覆蓋（檔名加編號）", second is not None and second["output"] != rough
          and os.path.basename(second["output"]).startswith("素材_粗剪") and os.path.exists(second["output"])
          and abs(seconds(rough) - total) < 0.25, str(second))
    check("清單上捨棄了第三句：片子跟著短、沒有藍色、字幕剩兩句", abs(seconds(second["output"]) - (total - 3.3)) < 0.25
          and color_at(second["output"], seconds(second["output"]) - 0.5) == "綠"
          and len(load_subtitle_file(second["subtitles"])["cues"]) == 2 and second["dropped"] == 1,
          f"{seconds(second['output'])} {second}")
    check("狀態列寫有幾句整句被剪掉", "（1 句整句被剪掉）" in panel.status_label.text(), panel.status_label.text())

    # ----- 5. 精彩合輯 -----
    panel.select_segment(speech[1])
    panel.toggle_selected()  # 精彩那一句在清單上標成捨棄：合輯照樣收
    check("精彩那一句標成捨棄了", items[speech[1]]["keep"] is False)
    state, reel = cut("highlight")
    reel_path = os.path.join(work, "素材_精彩合輯.mp4")
    check("精彩合輯：檔名加「_精彩合輯」", reel is not None and reel["kind"] == "highlight" and reel["output"] == reel_path
          and os.path.exists(reel_path), str(reel))
    check("合輯只有精彩那一段（約 3.3 秒、全是綠的）", abs(seconds(reel_path) - 3.3) < 0.25
          and [color_at(reel_path, t) for t in (0.3, 1.5, 2.8)] == ["綠", "綠", "綠"], str(seconds(reel_path)))
    check("合輯的字幕只有那一句、從 0.15 秒開始", [c["text"] for c in load_subtitle_file(reel["subtitles"])["cues"]]
          == [CUES[1]["text"]] and abs(load_subtitle_file(reel["subtitles"])["cues"][0]["start"] - 0.15) < 0.02)
    check("合輯不改清單的保留狀態", items[speech[1]]["keep"] is False and "精彩合輯已輸出" in panel.status_label.text())
    panel.apply_suggestions()

    # ----- 6. 輸出資料夾 -----
    out_dir = os.path.join(tmp, "指定的資料夾")
    cfg["automation"] = {"output_dir": out_dir}
    state, placed = cut("highlight")
    check("「輸出設定」指定了資料夾：放那裡（資料夾沒有就建）", placed is not None
          and placed["output"] == os.path.join(out_dir, "素材_精彩合輯.mp4") and os.path.exists(placed["output"])
          and placed["subtitles"] == os.path.join(out_dir, "素材_精彩合輯.srt"), str(placed))
    cfg["automation"] = {}

    # ----- 7. 匯出 -----
    settings = review.resolve_settings(cfg)
    direct = {
        "edl": lambda p, fillers=False: review.export_edl(items, p, clip_name="素材.mp4", drop_filler_words=fillers),
        "srt": lambda p: exporter.export(review.build_review_cues(items), p),
        "csv": lambda p: review.export_csv(items, p),
        "html": lambda p: review.export_html_report(
            items, p, source_name="素材.mp4", media_duration=panel.duration,
            chapters=review.build_chapters(items, min_chapter_seconds=settings["chapter_min_seconds"],
                                           break_gap=settings["silence_gap"])),
    }
    names = {"edl": "素材_粗剪.edl", "srt": "素材_審片標記.srt", "csv": "素材_審片清單.csv", "html": "素材_審片報告.html"}
    for key in ("edl", "srt", "csv", "html"):
        QTest.mouseClick(panel.export_buttons[key], Qt.LeftButton)
        path = panel.last_export
        ref = os.path.join(tmp, f"ref_{key}{os.path.splitext(names[key])[1]}")
        direct[key](ref)
        check(f"匯出 {key}：檔名跟一般版一樣、內容跟直接呼叫核心一模一樣", path == os.path.join(work, names[key])
              and os.path.exists(path) and filecmp.cmp(path, ref, shallow=False)
              and path in panel.status_label.text(), f"{path} {panel.status_label.text()}")
    check("審片標記字幕裡有【冷場】【建議剪掉】與【精彩】",
          all(w in open(os.path.join(work, names["srt"]), encoding="utf-8").read() for w in ("【冷場】", "【建議剪掉】", "【精彩】")))
    check("HTML 報告寫著來源檔名", "素材.mp4" in open(os.path.join(work, names["html"]), encoding="utf-8").read())
    again = panel.export("csv")
    check("再匯出一次：不覆蓋（檔名加編號）", again != os.path.join(work, names["csv"]) and os.path.exists(again)
          and os.path.basename(again).startswith("素材_審片清單"))
    calls = []
    real_edl = review.export_edl
    review.export_edl = lambda *a, **k: (calls.append(k), real_edl(*a, **k))[1]
    try:
        panel.fillers_box.setChecked(True)
        panel.export("edl")
        panel.fillers_box.setChecked(False)
        panel.export("edl")
        check("EDL 照「剪除口頭禪字」的勾選", [k.get("drop_filler_words") for k in calls] == [True, False], str(calls))
    finally:
        review.export_edl = real_edl
    real_csv = review.export_csv

    def bad_csv(*a, **k):
        raise OSError("磁碟滿了")
    review.export_csv = bad_csv
    try:
        check("匯出失敗：講原因、回傳空的", panel.export("csv") == "" and panel.status_label.text() == "匯出失敗：磁碟滿了")
    finally:
        review.export_csv = real_csv
    try:
        panel.export("nope")
        check("不認得的匯出：不收", False)
    except ValueError:
        check("不認得的匯出：不收", True)

    # ----- 8. 背景失敗、輸出中關視窗 -----
    real_cut = review.cut_rough_video
    seen = {}

    def boom(media, cut_items, output, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("ffmpeg 粗剪失敗：壞掉了")
    review.cut_rough_video = boom
    try:
        panel.fillers_box.setChecked(True)
        count = len(asked)
        state, failed = cut("roughcut")
        check("背景失敗：講原因、鈕亮回來、不問要不要換", failed is None and panel.status_label.text().startswith("輸出失敗：")
              and all(b.isEnabled() for b in all_buttons) and not panel.cutting() and len(asked) == count,
              panel.status_label.text())
        check("勾了「剪除口頭禪字」：粗剪時帶進去", seen.get("drop_filler_words") is True, str(seen))
        panel.fillers_box.setChecked(False)
    finally:
        review.cut_rough_video = real_cut

    closing = []
    panel.ask_close_while_cutting = lambda: (closing.append(panel.close_question()), False)[1]
    player._ask_discard = lambda *a, **k: "discard"
    player._ask_project_discard = lambda *a, **k: "discard"
    QTest.mouseClick(cut_btns["highlight"], Qt.LeftButton)
    check("輸出中", panel.cutting())
    win.close()
    check("輸出中關視窗：先問，選否就不關", len(closing) == 1 and win.isVisible() and "還在輸出" in closing[0]
          and "素材_精彩合輯" in closing[0] and "可能不完整" in closing[0], str(closing))
    wait_until(lambda: not panel.busy())
    win.close()
    check("輸出完再關：不問", len(closing) == 1)
    win.show()
    wait(50)

    # ----- 9. 選「是」 -----
    answer["adopt"] = True
    blocked = []
    real_close = player.maybe_close
    player.maybe_close = lambda: (blocked.append(1), False)[1]
    state, kept_out = cut("roughcut")
    check("選是、但還沒存的變更沒處理：②不換、講明", blocked == [1] and player.media_path == main
          and len(player.cues) == 3 and "②沒有換" in panel.status_label.text(), panel.status_label.text())
    player.maybe_close = real_close
    state, adopted = cut("roughcut")
    wait_until(lambda: player.player.duration() > 0 and player.media_path == adopted["output"], 20000)
    now = [(round(c["start"], 2), round(c["end"], 2), c["text"]) for c in player.cues]
    check("選是：②的影片換成剪好的那支", player.media_path == adopted["output"]
          and abs(player.media_duration() - total) < 0.3, f"{player.media_path} {player.media_duration()}")
    check("選是：②的字幕換成對齊好的那一份", now == [(round(c["start"], 2), round(c["end"], 2), c["text"]) for c in aligned]
          and player._subtitle_path == adopted["subtitles"], str(now))
    check("狀態列講②已換成這支粗剪", "②已換成這支粗剪" in panel.status_label.text())
    check("換了之後清單標成舊的（請重新分析）", panel.stale())
    check("全程沒寫 config.json", not os.path.exists(config.CONFIG_PATH))
    check("原檔到最後都沒動", (os.path.getsize(main), os.path.getmtime(main)) == original)

    player.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 ①審片助手（粗剪、精彩合輯與匯出）測試全數通過。")
