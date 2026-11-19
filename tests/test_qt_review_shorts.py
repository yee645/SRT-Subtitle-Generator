# -*- coding: utf-8 -*-
"""
3.0 第 11 項第二十階段：①審片助手的直式短片（「輸出」框的第四頁）。

構圖、字幕平移、安全區、選段規劃的規則在 test_shorts*.py、test_clipplan*.py；這裡驗介面與接線，ffmpeg 真的
輸出、量結果。測試影片用 ffmpeg 產生（40 秒、640×360：左半紅、右半藍）；字幕四句，第三句又大聲又有情緒詞
（精彩）。

1. 第四頁「直式短片」：版式、焦點、燒錄字幕、響度正規化、兩顆鈕、字幕安全區三格照目前的設定、範圍跟一般版一樣；
   焦點只有裁切能調、安全區沒勾三格灰掉；說明寫燒的是②的字幕、不覆蓋、不送出去；還沒分析時鈕灰著。
2. 不輸出的情況講原因：沒開影片、沒有 ffmpeg、沒選也沒有精彩段落、自動選段規劃不出來（講一般版同一份理由）。
3. 選取段落：選了兩段就輸出兩支（檔名 `_短片01.mp4`、`_短片02.mp4`、放在影片旁邊）；1080×1920；片長＝段落長；
   焦點 0 裁到左邊（紅）。背景跑、跑的時候所有鈕灰掉、不能分析也不能輸出別的。燒的是②現在的字幕與樣式、
   安全區照設定傳進去。
4. 沒選：用精彩段落；不覆蓋（檔名加編號）。
5. 模糊背景：整個畫面放在中間（左紅右藍都看得到）；響度正規化與安全區的勾選照實傳進去。不燒字幕：畫面上
   字幕那一塊跟燒了的不一樣。
6. 自動選段：先問（問的話是一般版同一份規劃）；選否不輸出；選是照規劃輸出（片長跟規劃一樣、照 config 的
   clipplan）。
7. 設定寫進這次開啟的 shorts（別的項目留著）。
8. 背景失敗：講原因、列出失敗前已輸出的；輸出中關視窗：先問（講直式短片）。全程不寫 config.json；原檔不動。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過①審片助手的直式短片")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import review_panel as rp  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import clipplan, exporter, review, shorts  # noqa: E402

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

    def wait_until(cond, timeout_ms=180000):
        waited = 0
        while not cond() and waited < timeout_ms:
            wait(50)
            waited += 50
        return cond()

    def probe(path, entries, stream="v:0"):
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", entries,
                              "-of", "csv=p=0", path], capture_output=True, text=True).stdout
        return out.strip()

    def seconds(path):
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True).stdout
        return float(out.strip() or 0)

    def frame(path, t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", path, "-frames:v", "1", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        return raw

    def color(raw, x, y, w=1080):
        r, g, b = raw[(y * w + x) * 3:(y * w + x) * 3 + 3]
        return "紅" if r > 150 and b < 100 else "藍" if b > 150 and r < 100 else f"?{r},{g},{b}"

    main = os.path.join(work, "素材.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=red:s=640x360:r=15:d=40,drawbox=x=320:y=0:w=320:h=360:color=blue:t=fill",
                    "-f", "lavfi", "-i", "aevalsrc='(0.03+0.9*between(t\\,24\\,27))*sin(2*PI*440*t)':d=40:s=22050",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", main],
                   check=True)
    CUES = [{"start": 2.0, "end": 5.0, "text": "大家好今天要來介紹這台新的相機"},
            {"start": 12.0, "end": 15.0, "text": "先看外觀這個握把的手感非常好"},
            {"start": 24.0, "end": 27.0, "text": "天啊這個畫質也太誇張了吧！真的超級無敵厲害！"},
            {"start": 33.0, "end": 36.0, "text": "最後總結一下這台相機值得買"}]
    srt = os.path.join(work, "素材.srt")
    exporter.export(CUES, srt)
    original = (os.path.getsize(main), os.path.getmtime(main))

    STYLE = {"font_size": 64, "position_y": 0.95, "primary_color": "#FFFFFF", "outline_width": 4}
    cfg = {"shorts": {"mode": "crop", "focus_x": 0.0, "burn_subtitles": True, "loudnorm": False,
                      "safe_zone_enabled": True, "safe_zone_top": 0.05, "safe_zone_bottom": 0.25,
                      "safe_zone_side": 0.04, "自訂": "留著"},
           "clipplan": {"count": 2, "min_seconds": 6.0, "max_seconds": 20.0},
           "subtitle_style": dict(STYLE)}
    win = qt_app.MainWindow(cfg)
    win.resize(1280, 800)
    win.show()
    wait(50)
    panel = win.review_panel
    player = win.player_panel
    player._ask_discard = lambda *a, **k: "discard"
    player._ask_project_discard = lambda *a, **k: "discard"
    panel._ask_adopt = lambda result: False
    buttons = panel.shorts_buttons
    spins = panel.shorts_safe_spins
    calls = []
    real_cut = shorts.cut_vertical_clip

    def spy(video, start, end, output, **kwargs):
        calls.append(dict(kwargs, start=start, end=end, output=output))
        return real_cut(video, start, end, output, **kwargs)
    shorts.cut_vertical_clip = spy

    def analyze():
        assert panel.start_analysis() is True
        assert wait_until(lambda: not panel.busy())

    def run(how, click=False):
        before = list(panel.last_shorts)
        if click:
            QTest.mouseClick(buttons[how], Qt.LeftButton)
            ok = panel.shorter.busy
        else:
            ok = panel.start_shorts(how)
        wait_until(lambda: not panel.busy())
        return ok, (panel.last_shorts if panel.last_shorts != before else [])

    # ----- 1. 第四頁 -----
    tabs, pages = panel.out_tabs, panel.out_pages
    check("「輸出」框第四頁是「直式短片」", tabs.count() == 4 and tabs.tabText(3) == "直式短片")
    check("這一頁的東西都在這一頁", all(pages["shorts"].isAncestorOf(w) for w in (
        panel.shorts_mode_box, panel.shorts_focus_spin, panel.shorts_subs_box, panel.shorts_loudnorm_box,
        panel.shorts_safe_box, *spins.values(), *buttons.values())))
    check("鈕與勾選的文字跟一般版一樣", [b.text() for b in buttons.values()] == ["輸出直式短片（選取段落）", "自動選段輸出"]
          and panel.shorts_subs_box.text() == "燒錄字幕" and panel.shorts_loudnorm_box.text() == "響度正規化"
          and [panel.shorts_mode_box.itemText(i) for i in range(panel.shorts_mode_box.count())] == ["裁切", "模糊背景"])
    check("數值照目前的設定", panel.shorts_mode_box.currentData() == "crop" and panel.shorts_focus_spin.value() == 0.0
          and panel.shorts_subs_box.isChecked() and not panel.shorts_loudnorm_box.isChecked()
          and panel.shorts_safe_box.isChecked()
          and [spins[k].value() for k in ("safe_zone_top", "safe_zone_bottom", "safe_zone_side")] == [5.0, 25.0, 4.0])
    shorts_cfg = cfg["shorts"]
    cfg["shorts"] = {"mode": "blur", "focus_x": 0.3, "burn_subtitles": False, "loudnorm": True,
                     "safe_zone_enabled": False, "safe_zone_top": 0.1, "safe_zone_bottom": 0.2, "safe_zone_side": 0.08}
    other = rp.ReviewPanel(player)
    check("另一份設定（模糊背景、不燒字幕、響度、安全區關）：初值也照設定",
          other.shorts_mode_box.currentData() == "blur" and other.shorts_focus_spin.value() == 0.3
          and not other.shorts_subs_box.isChecked() and other.shorts_loudnorm_box.isChecked()
          and not other.shorts_safe_box.isChecked() and not other.shorts_focus_spin.isEnabled()
          and [other.shorts_safe_spins[k].value() for k in ("safe_zone_top", "safe_zone_bottom", "safe_zone_side")]
          == [10.0, 20.0, 8.0])
    other.deleteLater()
    cfg["shorts"] = shorts_cfg
    wait(50)
    check("範圍跟一般版一樣", (panel.shorts_focus_spin.minimum(), panel.shorts_focus_spin.maximum()) == (0.0, 1.0)
          and [(spins[k].minimum(), spins[k].maximum()) for k in ("safe_zone_top", "safe_zone_bottom", "safe_zone_side")]
          == [(0.0, 20.0), (10.0, 35.0), (0.0, 15.0)])
    panel.shorts_mode_box.setCurrentIndex(1)
    blur_focus = panel.shorts_focus_spin.isEnabled()
    panel.shorts_mode_box.setCurrentIndex(0)
    check("焦點只有裁切能調", panel.shorts_focus_spin.isEnabled() and not blur_focus)
    panel.shorts_safe_box.setChecked(False)
    off = [s.isEnabled() for s in spins.values()]
    panel.shorts_safe_box.setChecked(True)
    check("安全區沒勾：三格灰掉", off == [False] * 3 and all(s.isEnabled() for s in spins.values()))
    labels = " ".join(w.text() for w in panel.findChildren(QLabel))
    check("說明寫燒②的字幕、不覆蓋、不能停、在本機", rp.SHORTS_NOTE in labels and all(
        w in rp.SHORTS_NOTE for w in ("②現在的字幕與樣式", "不覆蓋", "不能停", "本機", "1080×1920")))
    check("頁面說明提到直式短片、不再寫「還在一般版」", "「直式短片」把選取的段落（或自動選段）輸出成 9:16 短片" in rp.PAGE_NOTE
          and "還在一般版" not in rp.PAGE_NOTE)
    check("狀態列提到直式短片", "封面候選、直式短片）" in win.statusBar().currentMessage())
    check("還沒分析：鈕灰著、按了不做事", not any(b.isEnabled() for b in buttons.values())
          and panel.start_shorts("selected") is False and panel.start_shorts("auto") is False)
    try:
        panel.start_shorts("nope")
        check("不認得的輸出：不收", False)
    except ValueError:
        check("不認得的輸出：不收", True)

    # ----- 2. 不輸出的情況 -----
    player.set_cues(CUES)
    analyze()
    check("分析完：鈕亮了", all(b.isEnabled() for b in buttons.values()))
    check("沒開影片：不輸出、講原因", panel.start_shorts("selected") is False and panel.status_label.text() == rp.NO_MEDIA)
    player.open_video(main)
    wait_until(lambda: player.player.duration() > 0, 20000)
    wait(100)
    player.load_subtitles(srt)
    analyze()
    items = panel.items
    speech = [n for n, i in enumerate(items) if i["kind"] == "speech"]
    check("分析結果：四句、第三句是精彩", len(speech) == 4
          and [review.TAG_HIGHLIGHT in items[n]["tags"] for n in speech] == [False, False, True, False],
          str([(items[n]["tags"]) for n in speech]))
    real_ffmpeg = rp.ffmpeg_available
    rp.ffmpeg_available = lambda: False
    try:
        check("沒有 ffmpeg：不輸出、講原因", panel.start_shorts("selected") is False
              and panel.status_label.text() == rp.NO_FFMPEG_SHORTS)
    finally:
        rp.ffmpeg_available = real_ffmpeg
    saved = [list(i["tags"]) for i in items]
    for i in items:
        i["tags"] = [t for t in i["tags"] if t != review.TAG_HIGHLIGHT]
    panel.tree.clearSelection()
    check("沒選也沒有精彩段落：不輸出、講原因", panel.start_shorts("selected") is False
          and panel.status_label.text() == rp.NO_SHORTS)
    report = clipplan.format_clip_plan_report([], clipplan.resolve_clipplan_settings(cfg))
    check("自動選段規劃不出來：不問、講一般版同一份理由", panel.start_shorts("auto") is False
          and panel.status_label.text() == report and "沒有規劃出" in report)
    for i, tags in zip(items, saved):
        i["tags"] = tags
    gaps = [n for n, i in enumerate(items) if i["kind"] != "speech"]
    panel.select_segment(gaps[0])
    check("只選了不是講話的段落：不輸出、講原因（只取講話段落）", gaps and panel.selected_segments() == [gaps[0]]
          and panel.start_shorts("selected") is False and panel.status_label.text() == rp.NO_SHORTS)
    panel.tree.clearSelection()
    check("到這裡什麼都沒輸出", sorted(os.listdir(work)) == ["素材.mp4", "素材.srt"] and calls == [])

    # ----- 3. 選取段落 -----
    tabs.setCurrentWidget(pages["shorts"])
    panel.select_segment(speech[0])
    panel.tree.topLevelItem(panel.visible.index(speech[3])).setSelected(True)
    check("清單選了第一、四句", panel.selected_segments() == [speech[0], speech[3]])
    every = [*panel.cut_buttons.values(), *panel.export_buttons.values(), *panel.publish_buttons.values(),
             panel.thumb_btn, *buttons.values()]
    QTest.mouseClick(buttons["selected"], Qt.LeftButton)
    state = {"busy": panel.busy(), "cutting": panel.cutting(), "buttons": [b.isEnabled() for b in every],
             "again": panel.start_shorts("auto"), "cut": panel.start_cut("roughcut"),
             "thumbs": panel.start_thumbnails(), "analysis": panel.start_analysis(),
             "progress": panel.progress_bar.isVisibleTo(panel), "status": panel.status_label.text()}
    wait_until(lambda: not panel.busy())
    check("按下去：背景跑、所有鈕灰掉、進度條出現", state["busy"] and state["cutting"] and not any(state["buttons"])
          and state["progress"], str(state))
    check("跑的期間：不能再輸出、不能粗剪、不能擷取封面、不能分析", state["again"] is False and state["cut"] is False
          and state["thumbs"] is False and state["analysis"] is False)
    check("跑的期間狀態列講幾支、原檔不動、不能停", "2 支" in state["status"] or "[1/2]" in state["status"]
          or "[2/2]" in state["status"], state["status"])
    first = panel.last_shorts
    check("做完：兩支，檔名加「_短片01」「_短片02」、放在影片旁邊",
          [os.path.basename(p) for p in first] == ["素材_短片01.mp4", "素材_短片02.mp4"]
          and all(os.path.dirname(p) == work and os.path.exists(p) for p in first), str(first))
    check("1080×1920", all(probe(p, "stream=width,height") == "1080,1920" for p in first))
    check("片長＝段落長（第一句、第四句各 3 秒）", all(abs(seconds(p) - 3.0) < 0.3 for p in first),
          str([seconds(p) for p in first]))
    raw = frame(first[0], 1.0)
    check("焦點 0：裁到左邊（整個畫面是紅的）", color(raw, 540, 600) == "紅" and color(raw, 1000, 600) == "紅",
          f"{color(raw, 540, 600)} {color(raw, 1000, 600)}")
    check("兩次呼叫核心：時間是那兩段、燒的是②現在的字幕與樣式、安全區照設定", len(calls) == 2
          and [(c["start"], c["end"]) for c in calls] == [(items[speech[0]]["start"], items[speech[0]]["end"]),
                                                          (items[speech[3]]["start"], items[speech[3]]["end"])]
          and all([(x["start"], x["end"], x["text"]) for x in c["cues"]] == [(x["start"], x["end"], x["text"])
                                                                           for x in player.cues] for c in calls)
          and all(c["style"] == STYLE for c in calls)
          and all((c["mode"], c["focus_x"], c["loudnorm_target"], c["safe_zone_enabled"], c["safe_zone_top"],
                   c["safe_zone_bottom"], c["safe_zone_side"]) == ("crop", 0.0, None, True, 0.05, 0.25, 0.04)
                  for c in calls), str(calls)[:600])
    check("做完：鈕亮回來、狀態列講幾支、在哪、檔名", all(b.isEnabled() for b in every) and not panel.cutting()
          and "共 2 支" in panel.status_label.text() and work in panel.status_label.text()
          and "素材_短片02.mp4" in panel.status_label.text(), panel.status_label.text())

    # ----- 4. 沒選：用精彩段落 -----
    panel.tree.clearSelection()
    calls.clear()
    player.cues.append({"start": 38.0, "end": 39.0, "text": "   "})
    ok, hl = run("selected")
    player.cues.pop()
    check("空白字幕不燒（核心收到的字幕不含只有空白的那一句）", calls
          and [x["text"] for x in calls[0]["cues"]] == [x["text"] for x in player.cues], str(calls)[:300])
    check("沒選：用精彩那一段、不覆蓋（檔名加編號）", ok and [os.path.basename(p) for p in hl] == ["素材_短片01 (1).mp4"]
          and [(c["start"], c["end"]) for c in calls] == [(items[speech[2]]["start"], items[speech[2]]["end"])]
          and all(os.path.exists(p) for p in first), str(hl))

    # ----- 5. 模糊背景、響度、安全區、不燒字幕 -----
    panel.shorts_mode_box.setCurrentIndex(1)
    panel.shorts_loudnorm_box.setChecked(True)
    panel.shorts_safe_box.setChecked(False)
    panel.select_segment(speech[1])
    calls.clear()
    ok, blur = run("selected")
    raw = frame(blur[0], 1.0)
    check("模糊背景：整個畫面放在中間（左紅右藍都看得到）", ok and color(raw, 270, 960) == "紅"
          and color(raw, 810, 960) == "藍", f"{color(raw, 270, 960)} {color(raw, 810, 960)}")
    check("響度正規化、安全區關掉照實傳進去", calls and calls[0]["mode"] == "blur" and calls[0]["loudnorm_target"] == -14.0
          and calls[0]["safe_zone_enabled"] is False, str(calls)[:300])
    with_subs = frame(blur[0], 1.5)
    panel.shorts_subs_box.setChecked(False)
    calls.clear()
    ok, plain = run("selected")
    without = frame(plain[0], 1.5)
    bottom = slice(1500 * 1080 * 3, 1900 * 1080 * 3)
    check("不燒字幕：核心不收字幕；畫面下方那一塊跟燒了的不一樣", ok and calls[0]["cues"] is None
          and with_subs[bottom] != without[bottom] and len(with_subs) == len(without) == 1080 * 1920 * 3)

    # ----- 6. 自動選段 -----
    plan = clipplan.plan_clips(items, clipplan.resolve_clipplan_settings(cfg), media_duration=panel.duration)
    asked = []
    answer = {"ok": False}
    panel._ask_plan = lambda text: (asked.append(text), answer["ok"])[1]
    calls.clear()
    check("自動選段：先問，選否不輸出", panel.start_shorts("auto") is False and calls == [] and len(asked) == 1
          and asked[0] == panel.plan_report() and "沒有輸出" in panel.status_label.text())
    check("問的是一般版同一份規劃（照 config 的 clipplan：最短 6 秒）", plan and asked[0]
          == clipplan.format_clip_plan_report(plan, clipplan.resolve_clipplan_settings(cfg))
          and all(c["duration"] >= 6.0 for c in plan), asked[0])
    answer["ok"] = True
    ok, auto = run("auto", click=True)
    check("選是（按〔自動選段輸出〕）：照規劃輸出（支數、片長跟規劃一樣）", ok and len(asked) == 2 and len(auto) == len(plan)
          and [(round(c["start"], 2), round(c["end"], 2)) for c in calls]
          == [(round(c["start"], 2), round(c["end"], 2)) for c in plan]
          and all(abs(seconds(p) - c["duration"]) < 0.4 for p, c in zip(auto, plan)),
          f"{[seconds(p) for p in auto]} {plan}")

    # ----- 7. 設定 -----
    check("設定寫進這次開啟的 shorts（別的項目留著）", cfg["shorts"] == {
        "mode": "blur", "focus_x": 0.0, "burn_subtitles": False, "loudnorm": True, "safe_zone_enabled": False,
        "safe_zone_top": 0.05, "safe_zone_bottom": 0.25, "safe_zone_side": 0.04, "自訂": "留著"}, str(cfg["shorts"]))
    spins["safe_zone_bottom"].setValue(30.0)
    panel.shorts_focus_spin.setValue(0.75)
    got = panel.shorts_settings()
    check("改了再收：照新的值（百分比換成比例）", got["safe_zone_bottom"] == 0.3 and got["focus_x"] == 0.75
          and cfg["shorts"]["safe_zone_bottom"] == 0.3)

    # ----- 8. 背景失敗、關視窗 -----
    count = {"n": 0}

    def flaky(video, start, end, output, **kwargs):
        count["n"] += 1
        if count["n"] == 2:
            raise RuntimeError("短片輸出失敗：磁碟滿了")
        return real_cut(video, start, end, output, **kwargs)
    shorts.cut_vertical_clip = flaky
    panel.select_segment(speech[0])
    panel.tree.topLevelItem(panel.visible.index(speech[1])).setSelected(True)
    ok, _ = run("selected")
    text = panel.status_label.text()
    check("背景失敗：講原因、列出失敗前已輸出的那一支、鈕亮回來", ok and text.startswith("直式短片輸出失敗：")
          and "磁碟滿了" in text and "已經輸出 1 支" in text and len(panel.last_shorts) == 1
          and os.path.basename(panel.last_shorts[0]) in text and all(b.isEnabled() for b in buttons.values()), text)
    shorts.cut_vertical_clip = spy

    closing = []
    panel.ask_close_while_cutting = lambda: (closing.append(panel.close_question()), False)[1]
    QTest.mouseClick(buttons["selected"], Qt.LeftButton)
    check("輸出中", panel.cutting() and panel.shorter.busy)
    win.close()
    check("輸出中關視窗：先問（講直式短片），選否就不關", len(closing) == 1 and win.isVisible()
          and "直式短片還在輸出" in closing[0] and "可能不完整" in closing[0], str(closing))
    wait_until(lambda: not panel.busy())
    win.close()
    check("輸出完再關：不問", len(closing) == 1)
    win.show()
    wait(50)

    check("全程沒寫 config.json", not os.path.exists(config.CONFIG_PATH))
    check("原檔到最後都沒動", (os.path.getsize(main), os.path.getmtime(main)) == original)
    shorts.cut_vertical_clip = real_cut

    player.shutdown()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 ①審片助手（直式短片）測試全數通過。")
