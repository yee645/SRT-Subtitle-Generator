# -*- coding: utf-8 -*-
"""
3.0 第 11 項第十八階段：①審片助手的「發佈」——章節草稿、發佈包、廣告插入點。

章節、發佈文字、廣告插入點怎麼算在 test_review*.py、test_publisher*.py、test_adbreaks*.py、
test_chaptercheck*.py；這裡驗介面與接線，結果跟直接呼叫核心比對。
測試影片用 ffmpeg 產生：短的 40 秒（四句字幕，最後一章只有 7 秒——不符 YouTube 規則但修得好）、
長的 10 分鐘（八句，中間都是長停頓——有廣告插入點可以建議）。

1. 「輸出」框多一排「發佈」：章節最短、〔複製 YouTube 章節〕〔匯出發佈包〕、廣告插入點的最小間隔與最多、
   〔複製廣告插入點〕；還沒分析時鈕灰著；數值照目前的設定；說明寫會帶進③、不送出去。
2. 章節草稿：複製到剪貼簿、帶進③健檢中心的章節框（那一塊自動展開）。不符 YouTube 規則而修得好：問要不要
   用修正後的——選否用原始草稿並講哪裡不符；選是用修正後的（跟核心修的一樣）。修不好（段落不夠）：不問、
   照樣複製、講原因。沒有保留的段落：不複製、講原因。③的章節框按 Ctrl+Z 還原。
3. 「章節最短」寫進這次開啟的設定（別的項目留著），章節跟著變。
4. 發佈包：存成 `_發佈包.txt`（內容跟核心一樣）、不覆蓋；標題／標籤／說明欄／章節帶進③，原本填的被換掉、
   Ctrl+Z 還原；存不了講原因；沒接③時只存檔。
5. 廣告插入點：不足 8 分鐘講原因、不動剪貼簿；10 分鐘的素材複製出來的跟核心一樣；「最多」「最小間隔」
   寫進這次開啟的設定（別的項目留著）並照著算；找不到停頓講原因。發佈包裡有廣告插入點那一段。
6. 輸出影片的期間三顆鈕灰掉、按了不做事。全程不寫 config.json。
7. 換開另一支影片不會卡住：播放器不在開檔的當下暫停（回到事件迴圈才暫停）。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過①審片助手的發佈")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import review_panel as rp  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import adbreaks, chaptercheck, exporter, publisher, review  # noqa: E402

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

    def make_video(path, seconds, size, rate):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=gray:s={size}:r={rate}:d={seconds}",
                        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=22050:duration={seconds}",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "32k",
                        "-shortest", path], check=True)

    short = os.path.join(work, "短片.mp4")
    long = os.path.join(work, "長片.mp4")
    make_video(short, 40, "320x180", 15)
    make_video(long, 600, "160x90", 2)
    SHORT_CUES = [{"start": 1.0, "end": 4.0, "text": "大家好今天要來介紹這台新的相機"},
                  {"start": 11.5, "end": 14.5, "text": "先看外觀這個握把的手感非常好"},
                  {"start": 22.0, "end": 25.0, "text": "天啊這個畫質也太誇張了吧！真的超級無敵厲害！"},
                  {"start": 33.0, "end": 36.0, "text": "最後總結一下這台相機值得買"}]
    LONG_TEXTS = ["大家好今天要來開箱這台新的相機", "先看外觀與握把的手感", "接著測試相機自動對焦的速度",
                  "天啊這個畫質也太誇張了吧！真的超級厲害！", "再來看看相機錄影的表現怎麼樣", "電池續航力實際測試的結果",
                  "跟上一代比起來進步了多少", "最後總結一下這台相機值得買嗎"]
    LONG_CUES = [{"start": 5.0 + n * 75.0, "end": 25.0 + n * 75.0, "text": text} for n, text in enumerate(LONG_TEXTS)]
    exporter.export(SHORT_CUES, os.path.join(work, "短片.srt"))
    exporter.export(LONG_CUES, os.path.join(work, "長片.srt"))

    cfg = {"review": {"chapter_min_seconds": 10.0, "cut_filler_words": False},
           "adbreaks": {"min_spacing_minutes": 3.0, "max_breaks": 4, "min_pause": 1.5}}
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
    clip = QApplication.clipboard()
    buttons = panel.publish_buttons
    asked = []
    answer = {"fix": False}
    panel._ask_fix_chapters = lambda problems, changes: (asked.append((list(problems), list(changes))), answer["fix"])[1]

    def analyze():
        assert panel.start_analysis() is True
        assert wait_until(lambda: not panel.busy())

    opening = {"now": False, "paused_inside": 0}
    real_pause = player.player.pause

    def spy_pause():
        opening["paused_inside"] += opening["now"]
        real_pause()
    player.player.pause = spy_pause

    def open_with(video, name):
        opening["now"] = True
        player.open_video(video)
        opening["now"] = False
        wait_until(lambda: player.player.duration() > 0, 20000)
        wait(100)
        player.load_subtitles(os.path.join(work, name))
        analyze()

    def chapter_text(chapters):
        return "\n".join(f"{chaptercheck.format_timestamp(c['start'])} {c['title']}" for c in chapters)

    def core_chapters():
        settings = review.resolve_settings(cfg)
        return review.build_chapters(panel.items, min_chapter_seconds=settings["chapter_min_seconds"],
                                     break_gap=settings["silence_gap"])

    # ----- 1. 「發佈」那一排 -----
    check("三顆鈕，文字跟一般版一樣", [b.text() for b in buttons.values()]
          == ["複製 YouTube 章節", "匯出發佈包", "複製廣告插入點"] and list(buttons) == ["chapters", "pack", "adbreaks"])
    check("還沒分析：三顆鈕灰著", not any(b.isEnabled() for b in buttons.values()))
    check("數值照目前的設定", panel.chapter_spin.value() == 10 and panel.ad_spacing_spin.value() == 3.0
          and panel.ad_max_spin.value() == 4)
    check("範圍跟一般版一樣", (panel.chapter_spin.minimum(), panel.chapter_spin.maximum()) == (10, 600)
          and (panel.ad_spacing_spin.minimum(), panel.ad_spacing_spin.maximum()) == (2.0, 15.0)
          and (panel.ad_max_spin.minimum(), panel.ad_max_spin.maximum()) == (1, 20))
    labels = " ".join(w.text() for w in panel.findChildren(type(panel.status_label)))
    check("說明寫會帶進③、可以 Ctrl+Z、8 分鐘、不送出去", rp.PUBLISH_NOTE in labels and all(
        w in rp.PUBLISH_NOTE for w in ("③健檢中心", "Ctrl+Z", "8 分鐘", "不送任何東西出去")))
    check("頁面說明：章節、發佈包、廣告插入點在「輸出」的「發佈」那一頁",
          "「發佈」產章節草稿、發佈包與廣告插入點" in rp.PAGE_NOTE and "直式短片還在一般版" in rp.PAGE_NOTE)
    check("狀態列提到章節與發佈包", "粗剪與匯出、章節與發佈包、" in win.statusBar().currentMessage())
    check("還沒分析：按了不做事", panel.copy_chapters() == "" and panel.export_publish_pack() == ""
          and panel.copy_ad_breaks() == "")
    check("③的發佈文字那一塊一開始收著、是空的", not health.publish_body.isVisibleTo(health)
          and not any(health.publish_text().values()))

    # ----- 2. 章節草稿 -----
    open_with(short, "短片.srt")
    check("分析完：三顆鈕亮了", all(b.isEnabled() for b in buttons.values()))
    draft = core_chapters()
    check_cfg = chaptercheck.resolve_chaptercheck_settings(cfg)
    verdict = chaptercheck.validate_chapters(draft, panel.duration, check_cfg)
    fixed, changes = chaptercheck.fix_chapters(draft, panel.duration, check_cfg)
    check("素材：四章、最後一章太短（不符規則，但修得好）", len(draft) == 4 and not verdict["ok"] and len(fixed) == 3
          and chaptercheck.validate_chapters(fixed, panel.duration, check_cfg)["ok"], f"{draft} {verdict}")
    clip.setText("原本的剪貼簿")
    health.publish_chapters.setPlainText("0:00 我自己打的")
    QTest.mouseClick(buttons["chapters"], Qt.LeftButton)
    check("不符規則而修得好：問要不要用修正後的，問的話列出問題與會改什麼", len(asked) == 1 and asked[0][0] and asked[0][1] == changes
          and all(p in panel.chapter_fix_question(*asked[0]) for p in asked[0][0])
          and all(c in panel.chapter_fix_question(*asked[0]) for c in changes)
          and "YouTube 不會顯示章節" in panel.chapter_fix_question(*asked[0]), str(asked))
    check("選否：複製原始草稿（四章，跟核心算的一樣）", clip.text() == chapter_text(draft) and clip.text().startswith("0:00 "))
    check("選否：狀態列講這份不符規則", "4 章" in panel.status_label.text() and "不符 YouTube 規則" in panel.status_label.text()
          and asked[0][0][0] in panel.status_label.text(), panel.status_label.text())
    check("章節帶進③的章節框、那一塊展開了、狀態列講到③", health.publish_text()["chapters_text"] == chapter_text(draft)
          and health.publish_body.isVisibleTo(health) and rp.SENT_TO_HEALTH in panel.status_label.text()
          and panel.last_publish == {"chapters": chapter_text(draft)})
    check("只帶章節：③其他三格沒動", health.publish_text()["title"] == "" and health.publish_text()["tags"] == ""
          and health.publish_text()["description"] == "")
    health.publish_chapters.undo()
    check("③的章節框按 Ctrl+Z：回到原本自己打的", health.publish_chapters.toPlainText() == "0:00 我自己打的",
          health.publish_chapters.toPlainText())
    answer["fix"] = True
    text = panel.copy_chapters()
    check("選是：用修正後的（三章，跟核心修的一樣）", len(asked) == 2 and text == chapter_text(fixed) == clip.text()
          and health.publish_text()["chapters_text"] == text and "已修正成符合 YouTube 規則的版本" in panel.status_label.text()
          and "3 章" in panel.status_label.text(), panel.status_label.text())

    # ----- 3. 章節最短 -----
    panel.chapter_spin.setValue(60)
    check("「章節最短」寫進這次開啟的設定（別的項目留著）", cfg["review"]["chapter_min_seconds"] == 60.0
          and cfg["review"]["cut_filler_words"] is False)
    only = core_chapters()
    text = panel.copy_chapters()
    check("章節最短 60 秒：只剩一章——修不好，不問、照樣複製、講原因", len(only) == 1 and len(asked) == 2
          and text == chapter_text(only) == clip.text() and "沒辦法自動修正" in panel.status_label.text()
          and "調低「章節最短」" in panel.status_label.text(), panel.status_label.text())
    panel.chapter_spin.setValue(10)
    kept = [i["keep"] for i in panel.items]
    for i in panel.items:
        i["keep"] = False
    clip.setText("沒被動過")
    check("沒有保留的段落：不複製、講原因", panel.copy_chapters() == "" and clip.text() == "沒被動過"
          and panel.status_label.text() == rp.NO_CHAPTERS)
    for i, k in zip(panel.items, kept):
        i["keep"] = k

    # ----- 4. 發佈包 -----
    settings = review.resolve_settings(cfg)
    pub = publisher.resolve_publish_settings(cfg)
    health.publish_title.setText("我自己打的標題")
    health.publish_tags.setText("自己的標籤")
    pack_path = os.path.join(work, "短片_發佈包.txt")
    QTest.mouseClick(buttons["pack"], Qt.LeftButton)
    expect = publisher.build_publish_pack(panel.items, settings=pub, chapters=core_chapters(), source_name="短片.mp4",
                                          extra_words=settings["extra_excite_words"], ad_breaks=[])
    got = open(pack_path, encoding="utf-8").read() if os.path.exists(pack_path) else ""
    check("發佈包存成「_發佈包.txt」、放在影片旁邊，內容跟核心一樣", got == expect and "短片.mp4" in got and "建議標題" in got
          and panel.last_export == pack_path, got[:200])
    fields = publisher.build_publish_fields(panel.items, settings=pub, chapters=core_chapters(),
                                            extra_words=settings["extra_excite_words"])
    now = health.publish_text()
    check("標題、說明欄、章節帶進③（跟核心算的一樣）", fields["title"] and fields["description"]
          and (now["title"], now["description"], now["chapters_text"])
          == (fields["title"], fields["description"], fields["chapters"]), str(now))
    check("這支短片算不出標籤：③的標籤那一格不動（只換有給值的）", fields["tags"] == "" and now["tags"] == "自己的標籤")
    check("狀態列：存到哪、帶進③", pack_path in panel.status_label.text() and rp.SENT_TO_HEALTH in panel.status_label.text()
          and set(panel.last_publish) == {"title", "description", "chapters"})
    health.publish_title.undo()
    check("③的標題按 Ctrl+Z：回到原本自己打的", health.publish_title.text() == "我自己打的標題", health.publish_title.text())
    second = panel.export_publish_pack()
    check("再匯出一次：不覆蓋（檔名加編號）", second and second != pack_path and os.path.exists(second)
          and os.path.basename(second).startswith("短片_發佈包") and open(pack_path, encoding="utf-8").read() == expect)
    real_default = panel.default_path
    panel.default_path = lambda suffix, ext: work  # 是個資料夾：開不了檔
    before = health.publish_text()
    check("存不了：講原因、回傳空的、③不動", panel.export_publish_pack() == "" and panel.status_label.text().startswith("匯出失敗：")
          and health.publish_text() == before, panel.status_label.text())
    panel.default_path = lambda suffix, ext: ""
    check("不知道存哪：講原因", panel.export_publish_pack() == "" and panel.status_label.text() == rp.NO_BASE)
    panel.default_path = real_default
    real_publish = panel.on_publish
    panel.on_publish = None
    health.publish_chapters.setPlainText("")
    third = panel.export_publish_pack()
    check("沒接③：只存檔，狀態列不提③", third and os.path.exists(third) and rp.SENT_TO_HEALTH not in panel.status_label.text()
          and health.publish_text()["chapters_text"] == "")
    text = panel.copy_chapters()
    check("沒接③：章節只複製，狀態列說可以直接貼", text == clip.text() and "可以直接貼到說明欄" in panel.status_label.text()
          and health.publish_text()["chapters_text"] == "")
    panel.on_publish = real_publish

    # ----- 5. 廣告插入點 -----
    clip.setText("沒被動過")
    QTest.mouseClick(buttons["adbreaks"], Qt.LeftButton)
    check("不足 8 分鐘：講原因、不動剪貼簿", clip.text() == "沒被動過" and panel.status_label.text() == rp.AD_TOO_SHORT
          and "8 分鐘" in rp.AD_TOO_SHORT)

    # ----- 6. 輸出影片的期間 -----
    QTest.mouseClick(panel.cut_buttons["roughcut"], Qt.LeftButton)
    state = (panel.cutting(), [b.isEnabled() for b in buttons.values()], panel.copy_chapters(),
             panel.export_publish_pack(), panel.copy_ad_breaks(), panel.status_label.text() != rp.AD_TOO_SHORT)
    wait_until(lambda: not panel.busy())
    check("輸出影片的期間：三顆鈕灰掉、按了不做事（狀態列也不動）；做完亮回來", state == (True, [False] * 3, "", "", "", True)
          and all(b.isEnabled() for b in buttons.values()), str(state))

    # ----- 5（續）. 10 分鐘的素材 -----
    open_with(long, "長片.srt")
    from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402
    # 開過一支再開一支：載入完成的訊號可能在 setSource 還沒返回時就送出來，那時候直接暫停偶爾會讓 Qt 卡死
    check("換開另一支影片：不在開檔的當下暫停，回到事件迴圈才暫停（第一格照樣出來）", opening["paused_inside"] == 0
          and player.player.playbackState() == QMediaPlayer.PlaybackState.PausedState, str(opening))
    check("長片：10 分鐘、八段講話", abs(panel.duration - 600) < 2
          and sum(1 for i in panel.items if i["kind"] == "speech") == 8, f"{panel.duration}")
    QTest.mouseClick(buttons["adbreaks"], Qt.LeftButton)
    ad_cfg = adbreaks.resolve_adbreak_settings(cfg)
    breaks = adbreaks.suggest_ad_breaks(panel.items, panel.duration, settings=ad_cfg)
    check("複製出來的跟核心算的一樣（照最小間隔 3 分、最多 4 個、設定檔的停頓 1.5 秒）", len(breaks) >= 2
          and clip.text() == adbreaks.format_ad_breaks(breaks) and ad_cfg["min_pause"] == 1.5
          and all(b - a >= 180 for a, b in zip([x["time"] for x in breaks], [x["time"] for x in breaks][1:])),
          clip.text())
    check("狀態列講複製了幾個", f"已複製 {len(breaks)} 個廣告插入點建議" in panel.status_label.text())
    panel.ad_max_spin.setValue(1)
    text = panel.copy_ad_breaks()
    one = adbreaks.suggest_ad_breaks(panel.items, panel.duration, settings=adbreaks.resolve_adbreak_settings(cfg))
    check("「最多」改 1：寫進這次開啟的設定（別的項目留著）、只建議一個", cfg["adbreaks"]["max_breaks"] == 1
          and cfg["adbreaks"]["min_pause"] == 1.5 and len(one) == 1 and text == adbreaks.format_ad_breaks(one) == clip.text()
          and "已複製 1 個" in panel.status_label.text())
    panel.ad_max_spin.setValue(4)
    panel.ad_spacing_spin.setValue(2.0)
    text = panel.copy_ad_breaks()
    more = adbreaks.suggest_ad_breaks(panel.items, panel.duration, settings=adbreaks.resolve_adbreak_settings(cfg))
    check("「最小間隔」改 2 分：寫進設定、建議變多", cfg["adbreaks"]["min_spacing_minutes"] == 2.0 and len(more) > len(breaks)
          and text == adbreaks.format_ad_breaks(more), text)
    long_pack = panel.export_publish_pack()
    expect = publisher.build_publish_pack(panel.items, settings=pub, chapters=core_chapters(), source_name="長片.mp4",
                                          extra_words=settings["extra_excite_words"], ad_breaks=more)
    without = publisher.build_publish_pack(panel.items, settings=pub, chapters=core_chapters(), source_name="長片.mp4",
                                           extra_words=settings["extra_excite_words"], ad_breaks=[])
    check("長片的發佈包：有廣告插入點那一段（跟核心一樣）", long_pack == os.path.join(work, "長片_發佈包.txt")
          and open(long_pack, encoding="utf-8").read() == expect and expect != without)
    long_fields = publisher.build_publish_fields(panel.items, settings=pub, chapters=core_chapters(),
                                                 extra_words=settings["extra_excite_words"])
    now = health.publish_text()
    check("長片算得出標籤（相機講了四次）：四格都帶進③", "相機" in long_fields["tags"] and (now["title"], now["tags"], now["description"],
                                                         now["chapters_text"])
          == (long_fields["title"], long_fields["tags"], long_fields["description"], long_fields["chapters"])
          and set(panel.last_publish) == {"title", "tags", "description", "chapters"}, str(now))
    long_draft = core_chapters()
    count = len(asked)
    text = panel.copy_chapters()
    check("長片的章節合規則：不問、直接複製並帶進③，狀態列沒有警告", len(long_draft) >= 3 and len(asked) == count
          and text == chapter_text(long_draft) == health.publish_text()["chapters_text"]
          and "不符" not in panel.status_label.text() and "修正" not in panel.status_label.text(),
          panel.status_label.text())
    cfg["adbreaks"]["skip_head_minutes"] = 10.0  # 頭尾保留區蓋掉整支：沒有地方可以放
    clip.setText("沒被動過")
    check("找不到停頓：講原因、不動剪貼簿", panel.copy_ad_breaks() == "" and clip.text() == "沒被動過"
          and panel.status_label.text() == rp.AD_NO_PAUSE and "最小間隔" in rp.AD_NO_PAUSE)
    check("全程沒寫 config.json", not os.path.exists(config.CONFIG_PATH))

    player.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 ①審片助手（章節、發佈包、廣告插入點）測試全數通過。")
