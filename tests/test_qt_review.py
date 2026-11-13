# -*- coding: utf-8 -*-
"""
3.0 第 11 項第十六階段：①素材與剪輯頁的審片助手（分析與段落清單）。

判定本身（冷場、重複拍攝、口頭禪、精彩）在 test_review*.py；這裡驗介面，QTest 真的按。
測試影片用 ffmpeg 產生（30 秒：中間一段特別大聲）；字幕是手寫的一份，含一段 6 秒的冷場、兩句幾乎
一樣的（重複拍攝）、一句滿是口頭禪的。

1. ①頁籤是審片頁（不是「還沒搬」的說明）、名稱不變、開起來停在①；頁面寫明不重新轉錄、哪些還在一般版；
   狀態列提到①的審片助手。
2. 偵測設定照設定填、範圍跟一般版一樣；還沒分析時清單的鈕都灰著。
3. 沒有字幕：不分析、講原因。
4. 分析：背景跑、跑的時候不能重跑；結果跟直接呼叫核心（同樣的字幕、音量、設定）一模一樣；清單每列
   的內容、統計、狀態列；冷場與重複拍攝預設捨棄。設定寫進這次開啟的 review（別的項目留著）、不寫
   config.json；逐句校對改到一半的先套用。
5. 色條：一段一塊、點一塊選到那一段；點清單的一列，②的播放器跳到那一段的開頭。
6. 切換保留（按鈕、雙擊、空白鍵、多選）、全部保留、套用建議；統計跟著變。
7. 篩選：只看精彩／只看待審視；被篩掉的段落從色條點得回來（切回全部）。
8. 搜尋下一個：逐一跳、繞回第一個、找不到講明、只在顯示範圍裡找。
9. 改設定再分析：結果跟著變（冷場門檻調高，6 秒的空檔不再算冷場；相似度調高，不再算重複拍攝）；時間軸的「審片建議」剪點跟著重算。
10. 分析之後②的字幕改過：講清單是舊的；重新分析就不講了。
11. 沒開影片也能分析（只看語速與文字，講明量不到音量）；背景失敗講原因、鈕亮回來。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過①審片助手")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import review_panel as rp  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import cutmarks, review  # noqa: E402

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

    # 30 秒影片：16.5～19.5 秒特別大聲（那一句該算精彩），其他時間小聲
    main = os.path.join(tmp, "素材.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:d=30",
                    "-f", "lavfi", "-i",
                    "aevalsrc='(0.03+0.9*between(t\\,16.5\\,19.5))*sin(2*PI*440*t)':d=30:s=22050",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", main], check=True)
    CUES = [
        {"start": 0.5, "end": 3.0, "text": "大家好今天要來介紹這台新的相機"},
        {"start": 3.6, "end": 5.5, "text": "它的對焦速度真的非常快"},
        # 5.5 → 11.5：六秒沒講話（冷場）
        {"start": 11.5, "end": 13.5, "text": "接下來我們看一下它的錄影功能"},
        {"start": 14.7, "end": 15.9, "text": "接下來我們看一下它的錄影功能好了吧"},  # 跟上一句幾乎一樣：上一句是重複拍攝
        {"start": 16.5, "end": 19.5, "text": "天啊這個畫質也太誇張了吧！真的超級無敵厲害！"},
        {"start": 20.5, "end": 22.5, "text": "呃嗯呃那個嗯呃就是呃嗯"},
        {"start": 24.0, "end": 27.0, "text": "最後總結一下這台相機值得買"},
    ]
    srt = os.path.join(tmp, "素材.srt")

    def stamp(x):
        return f"00:00:{int(x):02d},{int(round((x % 1) * 1000)):03d}"

    with open(srt, "w", encoding="utf-8") as f:
        for n, cue in enumerate(CUES, start=1):
            f.write(f"{n}\n{stamp(cue['start'])} --> {stamp(cue['end'])}\n{cue['text']}\n\n")

    cfg = {"review": {"silence_gap": 3.0, "highlight_sensitivity": 1.5, "chapter_min_seconds": 90.0,
                      "weight_pace": 0.5, "extra_excite_words": "誇張"}}
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.show()
    wait(50)
    panel = win.review_panel
    player = win.player_panel

    # ----- 1. 頁籤 -----
    check("①頁籤是審片頁、名稱不變", win.tabs.tabText(0) == "① 素材與剪輯" and win.tabs.widget(0) is panel
          and isinstance(panel, rp.ReviewPanel))
    check("四個頁籤、順序不變", [win.tabs.tabText(i) for i in range(win.tabs.count())]
          == ["① 素材與剪輯", "② 字幕", "③ 健檢中心", "④ 輸出與發佈"])
    check("開起來停在①", win.tabs.currentIndex() == 0)
    check("頁面寫明不重新轉錄、不送出去", "不重新轉錄" in rp.PAGE_NOTE and "不送任何東西出去" in rp.PAGE_NOTE)
    check("頁面寫明哪些還在一般版", all(w in rp.PAGE_NOTE for w in ("粗剪影片", "精彩合輯", "EDL", "章節", "封面候選",
                                                             "直式短片", "還在一般版")))
    check("狀態列提到①的審片助手", "①的審片助手" in win.statusBar().currentMessage())

    # ----- 2. 偵測設定 -----
    check("偵測設定照設定填", panel.spins["silence_gap"].value() == 3.0
          and panel.spins["highlight_sensitivity"].value() == 1.5 and panel.spins["weight_pace"].value() == 0.5
          and panel.spins["segment_gap"].value() == 1.0 and round(panel.spins["take_similarity"].value(), 2) == 0.72
          and panel.excite_edit.text() == "誇張" and panel.voice_band_box.isChecked()
          and panel.filler_edit.text() == review.resolve_settings({})["filler_words"])
    ranges = {key: (round(spin.minimum(), 2), round(spin.maximum(), 2)) for key, spin in panel.spins.items()}
    check("範圍跟一般版一樣", ranges == {"silence_gap": (0.5, 10.0), "segment_gap": (0.4, 5.0),
                                  "highlight_sensitivity": (0.2, 3.0), "take_similarity": (0.5, 0.95),
                                  "weight_energy": (0.0, 3.0), "weight_pace": (0.0, 3.0),
                                  "weight_excite": (0.0, 3.0), "weight_exclaim": (0.0, 3.0)}, str(ranges))
    list_buttons = (panel.toggle_btn, panel.suggest_btn, panel.keep_all_btn, panel.search_btn)
    check("還沒分析：清單的鈕灰著、「開始分析」亮著", not any(b.isEnabled() for b in list_buttons)
          and panel.analyze_btn.isEnabled() and panel.status_label.text() == rp.IDLE)

    # ----- 3. 沒有字幕 -----
    QTest.mouseClick(panel.analyze_btn, Qt.LeftButton)
    check("沒有字幕：不分析、講原因", not panel.busy() and panel.status_label.text() == rp.NO_CUES
          and "生成字幕" in rp.NO_CUES and panel.items == [])

    # ----- 4. 分析 -----
    player.open_video(main)
    wait_until(lambda: player.player.duration() > 0, 20000)
    wait(100)
    player.load_subtitles(srt)
    wait(100)
    duration = player.media_duration()
    committed = []
    real_before = panel.before_analyze
    panel.before_analyze = lambda: (committed.append(1), real_before())[1]
    panel.spins["segment_gap"].setValue(0.4)
    QTest.mouseClick(panel.analyze_btn, Qt.LeftButton)
    check("按「開始分析」：背景跑、鈕灰掉寫分析中、進度條出現", panel.busy() and not panel.analyze_btn.isEnabled()
          and panel.analyze_btn.text() == "分析中…" and panel.progress_bar.isVisibleTo(panel))
    check("跑的期間再叫一次：不重跑", panel.start_analysis() is False and len(committed) == 1)
    check("跑完", wait_until(lambda: not panel.busy()) and panel.analyze_btn.isEnabled()
          and panel.analyze_btn.text() == "開始分析" and not panel.progress_bar.isVisibleTo(panel))
    check("先套用逐句校對改到一半的", committed == [1])
    check("設定寫進這次開啟的 review、別的項目留著", cfg["review"]["segment_gap"] == 0.4
          and cfg["review"]["silence_gap"] == 3.0 and cfg["review"]["chapter_min_seconds"] == 90.0
          and cfg["review"]["voice_band"] is True and cfg["review"]["extra_excite_words"] == "誇張", str(cfg["review"]))
    check("沒寫 config.json", not os.path.exists(config.CONFIG_PATH))

    def direct(media=main, total=None):
        settings = review.resolve_settings(cfg)
        loud = review.compute_loudness(media, voice_band=settings["voice_band"]) if media else []
        return review.analyze(cutmarks.words_from_cues(player.cues), media_duration=duration if total is None else total,
                              loudness=loud, settings=settings)

    def brief(items):
        return [(i["kind"], round(i["start"], 3), round(i["end"], 3), i["text"], tuple(i["tags"]), i["keep"])
                for i in items]

    expected = direct()
    check("結果跟直接呼叫核心一模一樣", brief(panel.items) == brief(expected), str(brief(panel.items)))
    tags = {i["text"]: i["tags"] for i in panel.items}
    silence = [i for i in panel.items if i["kind"] == "silence"]
    check("六秒的空檔算冷場、預設捨棄", any(abs(i["start"] - 5.5) < 0.01 and abs(i["end"] - 11.5) < 0.01
                                    and not i["keep"] for i in silence), str(brief(silence)))
    check("前一句幾乎一樣的：重複拍攝、預設捨棄；後一句保留",
          review.TAG_REPEATED in tags["接下來我們看一下它的錄影功能"]
          and review.TAG_REPEATED not in tags["接下來我們看一下它的錄影功能好了吧"]
          and [i["keep"] for i in panel.items if i["text"].startswith("接下來")] == [False, True], str(tags))
    check("滿是口頭禪的那句：口頭禪多", review.TAG_FILLER in tags["呃嗯呃那個嗯呃就是呃嗯"])
    check("又大聲又有情緒詞的那句：精彩", review.TAG_HIGHLIGHT in tags["天啊這個畫質也太誇張了吧！真的超級無敵厲害！"],
          str(tags))
    check("量到音量了（沒有「量不到音量」的說明）", panel.loudness_ok and rp.NO_LOUDNESS not in panel.status_label.text())

    def rows():
        return [[panel.tree.topLevelItem(r).text(c) for c in range(6)] for r in range(panel.tree.topLevelItemCount())]

    def expected_row(n, item):
        return ["✔" if item["keep"] else "✘", str(n + 1), f"{rp.clock(item['start'])} → {rp.clock(item['end'])}",
                f"{item['end'] - item['start']:.1f}", "、".join(item["tags"]), item["text"]]

    check("清單一段一列：保留／#／時間／秒數／標記／內容", rows() == [expected_row(n, i) for n, i in enumerate(panel.items)]
          and [panel.tree.headerItem().text(c) for c in range(6)] == ["保留", "#", "時間", "秒數", "標記", "內容"],
          str(rows()))
    check("第一列長這樣", rows()[0] == ["✔", "1", "00:00 → 00:03", "2.5", "", "大家好今天要來介紹這台新的相機"], str(rows()[0]))

    def stats_text(items):
        s = review.summarize(items, duration)
        return (f"保留 {s['kept_seconds'] / 60.0:.1f} 分｜精彩 {s['highlight_seconds'] / 60.0:.1f} 分｜"
                f"冷場 {s['silence_seconds'] / 60.0:.1f} 分｜口頭禪 {s['filler_total']} 次")

    check("統計跟核心算的一樣", panel.stats_label.text() == stats_text(panel.items) and "口頭禪" in panel.stats_label.text(),
          panel.stats_label.text())
    stats = review.summarize(panel.items, duration)
    dropped = sum(1 for i in panel.items if not i["keep"])
    check("狀態列：幾個講話段落、幾段精彩、建議捨棄幾段",
          panel.status_label.text().startswith(f"分析完成：{stats['segment_count']} 個講話段落、"
                                               f"{stats['highlight_count']} 段精彩，建議捨棄 {dropped} 段。")
          and stats["segment_count"] == 7 and dropped >= 2, panel.status_label.text())
    check("分析完：清單的鈕亮了", all(b.isEnabled() for b in list_buttons))
    check("捨棄的列字是淡的、冷場的列有底色", panel.tree.topLevelItem(2).foreground(5).color()
          != panel.tree.topLevelItem(0).foreground(5).color()
          and panel.tree.topLevelItem(2).background(5).style() != Qt.NoBrush
          and panel.tree.topLevelItem(2).background(5).color().alpha() == 55
          and panel.tree.topLevelItem(2).background(5).color().name() == review.CATEGORY_COLORS["silence"]
          and panel.tree.topLevelItem(0).background(5).color().alpha() in (0, 255)
          and panel.tree.topLevelItem(0).background(5).style() == Qt.NoBrush)

    # ----- 5. 色條與跳轉 -----
    strip = panel.strip
    spans = strip.spans()
    check("色條：一段一塊、照時間比例", len(spans) == len(panel.items)
          and abs(spans[2][0] - 5.5 / duration * strip.width()) < 1.0
          and abs(spans[2][1] - 11.5 / duration * strip.width()) < 1.0, str(spans[:3]))
    mid = int((spans[4][0] + spans[4][1]) / 2)
    QTest.mouseClick(strip, Qt.LeftButton, Qt.NoModifier, QPoint(mid, strip.height() // 2))
    check("點色條的一塊：清單選到那一段", panel.current_segment() == 4 and panel.selected_segments() == [4]
          and strip.current == 4)
    check("②的播放器跳到那一段的開頭", wait_until(lambda: player.player.position() == int(panel.items[4]["start"] * 1000), 5000),
          str(player.player.position()))
    panel.tree.setCurrentItem(panel.tree.topLevelItem(6))
    check("點清單的一列：播放器跟著跳、色條標那一段",
          wait_until(lambda: player.player.position() == int(panel.items[6]["start"] * 1000), 5000) and strip.current == 6)
    check("點色條外面（沒有段落的地方）不選", strip.index_at(strip.width() - 1) == -1
          or panel.items[-1]["end"] >= duration - 0.05)

    # ----- 6. 保留／捨棄 -----
    panel.select_segment(0)
    QTest.mouseClick(panel.toggle_btn, Qt.LeftButton)
    check("切換保留：第 1 段變捨棄、還選著它", panel.items[0]["keep"] is False and rows()[0][0] == "✘"
          and panel.selected_segments() == [0])
    check("統計跟著變", panel.stats_label.text() == stats_text(panel.items))
    rect = panel.tree.visualItemRect(panel.tree.topLevelItem(0))
    QTest.mouseClick(panel.tree.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())  # 真的雙擊：先有第一下
    QTest.mouseDClick(panel.tree.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    wait(50)
    check("雙擊：切回保留", panel.items[0]["keep"] is True and rows()[0][0] == "✔")
    panel.tree.setFocus()
    QTest.keyClick(panel.tree, Qt.Key_Space)
    check("空白鍵：切換", panel.items[0]["keep"] is False)
    QTest.keyClick(panel.tree, Qt.Key_Space)
    panel.tree.clearSelection()
    for r in (1, 2, 3):
        panel.tree.topLevelItem(r).setSelected(True)
    before = [panel.items[n]["keep"] for n in (1, 2, 3)]
    check("多選切換：三段各自反過來、選取留著", panel.toggle_selected() == 3
          and [panel.items[n]["keep"] for n in (1, 2, 3)] == [not k for k in before]
          and panel.selected_segments() == [1, 2, 3])
    panel.tree.clearSelection()
    check("沒選取：切換不做事", panel.toggle_selected() == 0)
    QTest.mouseClick(panel.keep_all_btn, Qt.LeftButton)
    check("全部保留", all(i["keep"] for i in panel.items) and all(r[0] == "✔" for r in rows())
          and panel.status_label.text() == "已全部標記為保留。")
    QTest.mouseClick(panel.suggest_btn, Qt.LeftButton)
    check("套用建議：回到冷場與重複拍攝捨棄", [i["keep"] for i in panel.items] == [i["keep"] for i in expected]
          and "套用系統建議" in panel.status_label.text())

    # ----- 7. 篩選 -----
    QTest.mouseClick(panel.filter_buttons["highlight"], Qt.LeftButton, Qt.NoModifier, QPoint(8, 8))
    high = [n for n, i in enumerate(panel.items) if review.categorize(i) == "highlight"]
    check("只看精彩：清單只剩精彩的、# 還是原本的編號", panel.filter == "highlight" and panel.visible == high and high
          and [r[1] for r in rows()] == [str(n + 1) for n in high], str(rows()))
    check("色條不受篩選影響", len(strip.spans()) == len(panel.items))
    QTest.mouseClick(panel.filter_buttons["review"], Qt.LeftButton, Qt.NoModifier, QPoint(8, 8))
    rev = [n for n, i in enumerate(panel.items) if review.categorize(i) == "review"]
    check("只看待審視：重複拍攝與口頭禪多的", panel.visible == rev and len(rev) == 2, str(rows()))
    QTest.mouseClick(strip, Qt.LeftButton, Qt.NoModifier, QPoint(int(strip.spans()[0][0]) + 2, 10))
    check("從色條點被篩掉的段落：切回全部、選到它", panel.filter == "all" and panel.filter_buttons["all"].isChecked()
          and panel.current_segment() == 0 and len(rows()) == len(panel.items))
    try:
        panel.set_filter("nope")
        check("不認得的篩選：不收", False)
    except ValueError:
        check("不認得的篩選：不收", True)

    # ----- 8. 搜尋 -----
    panel.search_edit.setText("相機")
    QTest.mouseClick(panel.search_btn, Qt.LeftButton)
    first = panel.current_segment()
    QTest.keyClick(panel.search_edit, Qt.Key_Return)
    second = panel.current_segment()
    third = panel.search_next()
    hits = review.search_segments(panel.items, "相機")
    check("搜尋下一個：逐一跳、繞回第一個", len(hits) == 2 and [first, second, third] == [hits[0], hits[1], hits[0]],
          f"{first} {second} {third} {hits}")
    check("狀態列寫第幾處", panel.status_label.text() == f"「相機」第 1/2 處：第 {hits[0] + 1} 段。", panel.status_label.text())
    panel.search_edit.setText("找不到的字")
    check("找不到：講明、選取不動", panel.search_next() == -1 and "找不到「找不到的字」" in panel.status_label.text()
          and panel.current_segment() == hits[0])
    panel.set_filter("highlight")
    panel.search_edit.setText("相機")
    check("只在顯示範圍裡找（精彩裡沒有「相機」）", panel.search_next() == -1 and panel.filter == "highlight")
    panel.set_filter("all")

    # ----- 9. 改設定再分析 -----
    player.show_cut_marks(cutmarks.REVIEW)
    cuts_before = [(m["start"], m["end"]) for m in player.cut_plan["marks"]]
    panel.spins["silence_gap"].setValue(8.0)
    panel.spins["take_similarity"].setValue(0.95)
    panel.items[0]["keep"] = False  # 手動改過的保留狀態：重新分析後回到建議
    check("改設定再分析", panel.start_analysis() is True and wait_until(lambda: not panel.busy()))
    check("冷場門檻調到 8 秒：六秒的空檔不再算冷場", cfg["review"]["silence_gap"] == 8.0
          and not any(abs(i["start"] - 5.5) < 0.01 for i in panel.items if i["kind"] == "silence")
          and brief(panel.items) == brief(direct()), str(brief(panel.items)))
    cuts_after = [(m["start"], m["end"]) for m in player.cut_plan["marks"]]
    check("相似度調到 0.95：那兩句不再算重複拍攝", not any(review.TAG_REPEATED in i["tags"] for i in panel.items))
    check("時間軸的「審片建議」剪點跟著重算（那一句不剪了）", cuts_after != cuts_before
          and len(cuts_after) == len(cuts_before) + 1, f"{cuts_before} {cuts_after}")
    check("重新分析：保留狀態回到建議", panel.items[0]["keep"] is True)

    # ----- 10. 字幕改過 -----
    check("剛分析完：沒有「清單是舊的」", not panel.stale())
    changed = [dict(c) for c in player.cues]
    changed[0]["text"] = "大家好今天改了第一句"
    player.set_cues(changed)
    check("②的字幕改過：講清單是舊的", panel.stale() and panel.stale_label.text() == rp.STALE
          and "重新分析" in rp.STALE)
    panel.start_analysis()
    wait_until(lambda: not panel.busy())
    check("重新分析：不講了、清單是新句子", not panel.stale() and rows()[0][5] == "大家好今天改了第一句")

    # ----- 11. 沒開影片、背景失敗 -----
    real_loud = review.compute_loudness
    review.compute_loudness = lambda *a, **k: []
    try:
        panel.start_analysis()
        wait_until(lambda: not panel.busy())
        check("量不到音量：照樣分析、講明只看語速與文字", panel.items and not panel.loudness_ok
              and panel.status_label.text().endswith(rp.NO_LOUDNESS)
              and brief(panel.items) == brief(direct(media="")), panel.status_label.text())

        def boom(*a, **k):
            raise RuntimeError("壞掉了")
        review.compute_loudness = boom
        kept = brief(panel.items)
        panel.start_analysis()
        wait_until(lambda: not panel.busy())
        check("背景失敗：講原因、鈕亮回來、清單留著上一次的", panel.status_label.text().startswith("分析失敗：")
              and panel.analyze_btn.isEnabled() and brief(panel.items) == kept
              and not panel.progress_bar.isVisibleTo(panel), panel.status_label.text())
    finally:
        review.compute_loudness = real_loud
    check("全程沒寫 config.json", not os.path.exists(config.CONFIG_PATH))

    player._ask_discard = lambda *a, **k: "discard"  # 收尾關視窗：不要跳「還沒存」的詢問
    player._ask_project_discard = lambda *a, **k: "discard"
    player.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 ①審片助手（分析與段落清單）測試全數通過。")
