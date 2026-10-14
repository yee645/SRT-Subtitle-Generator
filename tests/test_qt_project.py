# -*- coding: utf-8 -*-
"""
3.0 第 10 項第二階段：播放器的「存專案」「開專案…」。

核心（subtitle/project.py 的格式、路徑、版本、檢查）在 test_project.py；這裡驗介面：

1. 按鈕：沒開影片時「存專案」灰掉；兩顆都在播放列上看得到。
2. 存：第一次問存到哪（建議跟影片同名 .srtproj），之後存回同一個檔不再問；狀態列寫專案名稱，
   改了東西寫「有變更還沒存」，存完就拿掉。
3. 開（另一個視窗）：影片、字幕（含改過還沒存回字幕檔的時間）、主片的畫面調整、素材軌與各段屬性、
   剪點的種類與微調、接縫轉場全部回到存的時候的樣子；輸出用的時間軸跟原本的一模一樣；剪點照微調
   畫在時間軸上；開完不算有變更。
4. 沒存的變更：關視窗、開別的專案、換影片之前先問；取消就什麼都不動；存專案就存了再關。還沒有專案
   時，只改字幕時間照舊問字幕，做了素材等編輯才問專案。
5. 開不了的情況：影片找不到（不開、說清楚）、壞檔、較新版本的檔；其他素材找不到時照樣開、列出來。
6. 專案的轉場比選單給的長（3 秒）：照樣放得下，不會悄悄改短。
"""
import json
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過專案檔介面（核心在 test_project.py）")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle import assemble, project  # noqa: E402

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

    work = os.path.join(tmp, "我的影片")
    os.makedirs(os.path.join(work, "素材"))
    main = os.path.join(work, "訪談.mp4")
    run("-f", "lavfi", "-i", "color=c=red:size=640x360:rate=30:d=8",
        "-f", "lavfi", "-i", "sine=frequency=150:sample_rate=48000:d=8",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", main)
    logo = os.path.join(work, "素材", "標誌.png")
    run("-f", "lavfi", "-i", "color=c=white:size=320x180", "-frames:v", "1", logo)
    song = os.path.join(work, "素材", "配樂.wav")
    run("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:d=6", song)
    srt = os.path.join(work, "訪談.srt")
    with open(srt, "w", encoding="utf-8") as fh:
        fh.write("1\n00:00:00,200 --> 00:00:02,500\n第一句\n\n2\n00:00:05,500 --> 00:00:07,800\n第二句\n")

    def new_window():
        win = qt_app.MainWindow({"subtitle_style": {}})
        win.tabs.setCurrentIndex(1)
        win.resize(1280, 860)
        win.show()
        panel = win.player_panel
        panel.messages = []
        panel._show_project_message = lambda title, text: panel.messages.append((title, text))
        panel._show_track_error = panel.messages.append
        panel.asked = []
        return win, panel

    def never_ask(*_args):
        raise AssertionError("不該再問")

    # ----- 1. 按鈕 -----
    win0, panel0 = new_window()
    panel0.load_subtitles(srt)
    panel0.show_cut_marks("jumpcut")
    panel0._on_cut_toggled(0, False)
    check("沒開影片、只有剪點微調：不算專案的變更（沒有影片存不了專案，問了也沒用）",
          panel0.cut_overrides and not panel0.project_changed())
    panel0.open_video(main)
    wait_until(lambda: panel0.player.duration() > 0, 20000)
    check("開了影片、剪點停用一個：算專案的變更", panel0.project_changed())
    panel0.cut_overrides = {}
    panel0.refresh_cut_marks()
    check("拿掉微調：不算", not panel0.project_changed())
    panel0.add_track("music", song)
    check("只有一段音樂：算", panel0.project_changed())
    panel0._ask_project_discard = lambda: "discard"
    panel0._ask_discard = lambda: "discard"
    panel0.shutdown()
    win0.close()
    win, panel = new_window()
    check("兩顆按鈕都在播放列上看得到；沒開影片時「存專案」灰掉、「開專案…」可以按",
          panel.open_project_btn.isVisible() and panel.save_project_btn.isVisible()
          and not panel.save_project_btn.isEnabled() and panel.open_project_btn.isEnabled())
    check("沒開影片：存專案什麼都不做", panel.save_project(os.path.join(tmp, "空.srtproj")) is False
          and not os.path.exists(os.path.join(tmp, "空.srtproj")))
    panel.open_video(main)
    wait_until(lambda: panel.player.duration() > 0, 20000)
    wait(100)
    check("開了影片：存專案可以按", panel.save_project_btn.isEnabled())

    # 做一輪剪接：改一句字幕的時間（不存回字幕檔）、主片調亮、疊標誌（右上角、調過）、放音樂、
    # 停頓剪點改範圍、接縫溶接 0.8 秒
    panel.load_subtitles(srt)
    check("只改字幕時間：還不算專案的變更（照舊由存字幕那邊問）",
          (panel._on_cue_times(0, 0.3, 2.5), panel.project_changed())[1] is False and panel.unsaved_changes() == 1)
    panel.set_main_adjust({"brightness": 0.2, "crop": [0.0, 0.0, 0.8, 1.0]})
    panel.player.setPosition(1000)
    wait_until(lambda: panel.player.position() == 1000, 5000)
    panel.add_track("overlays", logo)
    panel.set_track_props(rect=assemble.position_rect("top_right"))
    panel.set_overlay_adjust(0, {"flip_h": True, "saturation": 0.5})
    panel.add_track("music", song)
    panel.set_track_props(volume=0.6, loop=True)
    panel.show_cut_marks("jumpcut")
    panel._on_cut_changed(0, 2.8, 5.2)
    panel.seam_combo.setCurrentIndex(panel.seam_combo.findData("dissolve"))
    panel.seam_spin.setValue(0.8)
    check("做了素材等編輯：還沒有專案也算有變更；狀態列還沒有「專案：」",
          panel.project_changed() and "專案：" not in panel.info_label.text(), panel.info_label.text())

    # ----- 2. 存 -----
    asked = []
    target = os.path.join(work, "訪談專案")
    panel._ask_project_path = lambda suggested: (asked.append(suggested), target)[1]
    check("第一次存：問存到哪（建議跟影片同名 .srtproj），補上副檔名",
          panel.save_project() and asked == [os.path.join(work, "訪談.srtproj")]
          and panel.project_path == target + ".srtproj" and os.path.isfile(target + ".srtproj"), str(asked))
    saved_path = panel.project_path
    check("存完：不算有變更，狀態列寫專案名稱與存到哪",
          not panel.project_changed() and "專案：訪談專案.srtproj（已存到 訪談專案.srtproj）" in panel.info_label.text(),
          panel.info_label.text())
    with open(saved_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    check("檔案裡：影片記相對路徑、改過的字幕時間、標誌的調整、剪點微調、接縫",
          doc["media"]["file"]["path"] == "訪談.mp4" and doc["subtitles"]["cues"][0]["start"] == 0.3
          and doc["tracks"]["overlays"][0]["path"]["path"] == "素材/標誌.png"
          and doc["tracks"]["overlays"][0]["adjust"] == {"flip_h": True, "saturation": 0.5}
          and doc["cuts"] == {"source": "jumpcut", "overrides": {"jumpcut:2.650-5.350": {"start": 2.8, "end": 5.2}}}
          and doc["seam"] == {"type": "dissolve", "duration": 0.8}, json.dumps(doc, ensure_ascii=False)[:400])
    panel.set_track_props(volume=0.5)
    check("再改一個地方：狀態列寫「有變更還沒存」", panel.project_changed()
          and "專案：訪談專案.srtproj（有變更還沒存）" in panel.info_label.text(), panel.info_label.text())
    panel._ask_project_path = never_ask
    check("再存：存回同一個檔、不再問，變更標記拿掉", panel.save_project() and panel.project_path == saved_path
          and not panel.project_changed() and "有變更" not in panel.info_label.text())
    for change, label in ((lambda: panel.set_main_adjust({"brightness": 0.1}), "主片調整"),
                          (lambda: panel._on_cut_toggled(0, False), "剪點停用"),
                          (lambda: panel.seam_spin.setValue(1.2), "轉場長度"),
                          (lambda: panel.show_cut_marks(""), "剪點種類"),
                          (lambda: panel._on_cue_times(1, 5.6, 7.8), "字幕時間")):
        before = panel.project_state()
        change()
        check(f"改{label}：算專案的變更、狀態列跟著寫", panel.project_changed()
              and "有變更還沒存" in panel.info_label.text(), panel.info_label.text())
        panel.apply_project(before)  # 放回去（apply_project 會清掉專案的記號，重記一次）
        panel.project_path, panel._saved_project = saved_path, project.normalize_state(before)
        panel._refresh_info()
    check("放回去後跟存的時候一樣", not panel.project_changed(), str(panel.project_state()["cuts"]))
    panel.proxy_path = os.path.join(tmp, "代理.mp4")  # 播代理檔時：專案照樣記原檔
    check("播代理檔時：專案記的是原檔", panel.project_state()["media"] == main)
    panel.proxy_path = ""
    original = project.normalize_state(panel.project_state())
    original_timeline = panel.timeline_for_export()

    # ----- 3. 開（另一個視窗）-----
    win2, panel2 = new_window()
    check("開專案：成功", panel2.open_project(saved_path) and panel2.messages == [], str(panel2.messages))
    wait_until(lambda: panel2.player.duration() > 0, 20000)
    wait(100)
    check("整條時間軸跟存的時候一樣（影片、字幕、調整、素材軌、剪點、接縫）",
          project.normalize_state(panel2.project_state()) == original,
          f"{panel2.project_state()}")
    check("影片與字幕檔是原本那兩個", panel2.media_path == main and panel2._subtitle_path == srt)
    check("字幕檔沒存的那處照樣算「改過還沒存」（照字幕檔本身算）",
          panel2.unsaved_changes() == 1 and "時間改過 1 處" in panel2.info_label.text(), panel2.info_label.text())
    check("主片的調整：亮度效果掛上、裁切照存的", panel2.picture_effect is not None
          and panel2.main_adjust == {"brightness": 0.2, "crop": [0.0, 0.0, 0.8, 1.0]})
    check("接縫：選單是溶接、0.8 秒、可以調", panel2.seam_combo.currentData() == "dissolve"
          and abs(panel2.seam_spin.value() - 0.8) < 1e-9 and panel2.seam_spin.isEnabled())
    check("剪點：選單是停頓、時間軸上照微調的範圍畫（2.8～5.2）", panel2.cut_combo.currentData() == "jumpcut"
          and [(m["start"], m["end"]) for m in panel2.cut_plan["marks"]] == [(2.8, 5.2)],
          str(panel2.cut_plan and panel2.cut_plan["marks"]))
    check("素材軌：時間軸上兩條軌各一段、那一行照樣寫", "畫面 1 段、音樂 1 段" in panel2.track_label.text(),
          panel2.track_label.text())
    check("輸出用的時間軸跟原本那個視窗的一模一樣", panel2.timeline_for_export() == original_timeline)
    check("開完：不算有變更，狀態列寫專案名稱", not panel2.project_changed()
          and panel2.info_label.text().startswith("專案：訪談專案.srtproj　"), panel2.info_label.text())

    # ----- 4. 沒存的變更 -----
    panel2.set_main_adjust({"brightness": -0.1})
    check("開了之後再改：有變更", panel2.project_changed())
    answers = []
    panel2._ask_project_discard = lambda: (answers.append(1), "cancel")[1]
    win2.close()
    check("關視窗按取消：視窗還開著、什麼都沒動", win2.isVisible() and answers == [1]
          and panel2.main_adjust == {"brightness": -0.1})
    before = panel2.project_state()
    check("開別的專案按取消：不開、原本的都在", panel2.open_project(saved_path) is False
          and panel2.project_state() == before and answers == [1, 1])
    calls = []
    panel2._ask_video_path = lambda: (calls.append(1), "")[1]
    panel2._choose_video()
    check("換影片按取消：連選檔都不問", calls == [] and answers == [1, 1, 1])
    panel2._ask_project_discard = lambda: "discard"
    panel2._choose_video()
    check("換影片選放棄：才問要開哪支", len(calls) == 1)
    panel2._ask_project_discard = lambda: "save"
    win2.close()
    with open(saved_path, encoding="utf-8") as fh:
        doc2 = json.load(fh)
    check("關視窗選存專案：存了再關", not win2.isVisible() and doc2["media"]["adjust"] == {"brightness": -0.1},
          str(doc2["media"]))

    # 還沒有專案：只改字幕時間照舊問字幕；有素材才問專案
    win3, panel3 = new_window()
    panel3.open_video(main)
    wait_until(lambda: panel3.player.duration() > 0, 20000)
    panel3.load_subtitles(srt)
    panel3._on_cue_times(0, 0.4, 2.5)
    asked3 = []
    panel3._ask_discard = lambda: (asked3.append("字幕"), "cancel")[1]
    panel3._ask_project_discard = lambda: (asked3.append("專案"), "cancel")[1]
    check("還沒有專案、只改字幕時間：關之前問的是字幕", panel3.maybe_close() is False and asked3 == ["字幕"])
    panel3.add_track("overlays", logo)
    check("加了素材：問的是專案", panel3.maybe_close() is False and asked3 == ["字幕", "專案"])
    panel3._ask_project_path = lambda _s: ""
    panel3._ask_project_discard = lambda: "save"
    check("選存專案但不選檔：不關", panel3.maybe_close() is False and panel3.project_path == "")
    panel3._ask_project_path = lambda _s: os.path.join(work, "第三個")
    check("選存專案並選檔：存了才繼續；字幕的時間存在專案裡，不再另外問字幕",
          panel3.maybe_close() is True and asked3 == ["字幕", "專案"]
          and os.path.isfile(os.path.join(work, "第三個.srtproj")))
    panel3._ask_discard = never_ask
    panel3._ask_project_discard = never_ask
    check("存過專案、字幕檔還沒存（時間存在專案裡）：關之前什麼都不問",
          panel3.unsaved_changes() == 1 and not panel3.project_changed() and panel3.maybe_close() is True)
    panel3.open_video(main)
    check("換影片：不再是那個專案", panel3.project_path == "" and "專案：" not in panel3.info_label.text())

    # ----- 5. 開不了的情況 -----
    win4, panel4 = new_window()
    panel4._ask_project_discard = never_ask
    junk = os.path.join(tmp, "壞的.srtproj")
    with open(junk, "w", encoding="utf-8") as fh:
        fh.write("{不是 json")
    check("壞檔：不開、說打不開", panel4.open_project(junk) is False and panel4.media_path == ""
          and "打不開這個專案" in panel4.messages[-1][1], str(panel4.messages))
    newer = os.path.join(tmp, "新版.srtproj")
    with open(newer, "w", encoding="utf-8") as fh:
        json.dump(dict(doc2, version=project.VERSION + 1), fh)
    check("較新版本存的：不開、說要更新程式", panel4.open_project(newer) is False
          and "請先更新程式" in panel4.messages[-1][1], panel4.messages[-1][1])
    # 整個資料夾搬走、影片拿掉：不開
    moved = os.path.join(tmp, "搬走的")
    shutil.copytree(work, moved)
    os.rename(main, main + ".藏起來")
    os.remove(os.path.join(moved, "訪談.mp4"))
    check("影片找不到：不開、說是哪支、怎麼辦", panel4.open_project(os.path.join(moved, "訪談專案.srtproj")) is False
          and panel4.media_path == "" and "找不到專案的影片" in panel4.messages[-1][1]
          and os.path.join(moved, "訪談.mp4") in panel4.messages[-1][1], panel4.messages[-1][1])
    os.rename(main + ".藏起來", main)
    # 音樂與字幕檔不見：照樣開、列出來
    os.remove(os.path.join(moved, "素材", "配樂.wav"))
    os.remove(os.path.join(moved, "訪談.srt"))
    shutil.copy(main, os.path.join(moved, "訪談.mp4"))
    os.rename(song, song + ".藏起來")
    os.rename(srt, srt + ".藏起來")
    count = len(panel4.messages)
    check("音樂、字幕檔找不到：照樣開，列出是哪兩個",
          panel4.open_project(os.path.join(moved, "訪談專案.srtproj")) is True
          and [w for w, _p in panel4.last_project_missing] == ["音樂第 1 段", "字幕檔"]
          and len(panel4.messages) == count + 1 and "音樂第 1 段" in panel4.messages[-1][1]
          and "字幕檔" in panel4.messages[-1][1], str(panel4.messages[count:]))
    check("搬走的那份：影片用搬過去那邊的；字幕內容照專案裡的", panel4.media_path == os.path.join(moved, "訪談.mp4")
          and [c["start"] for c in panel4.cues] == [0.3, 5.5] and not panel4.project_changed())
    os.rename(song + ".藏起來", song)
    os.rename(srt + ".藏起來", srt)

    bare = project.save(dict(project.new_state(), cues=[{"start": 0.0, "end": 1.0, "text": "只有字幕"}]),
                        os.path.join(tmp, "只有字幕"))
    still = panel4.media_path
    check("專案裡沒有影片：不開（原本開著的照舊）、說清楚", panel4.open_project(bare) is False and panel4.media_path == still
          and "沒有影片" in panel4.messages[-1][1], panel4.messages[-1][1])
    panel4.track_exporter.busy = True
    check("輸出中：不開專案（也不問）", panel4.open_project(saved_path) is False and panel4.project_path != saved_path)
    panel4.track_exporter.busy = False
    panel4.exporter.busy = True
    check("照剪點輸出中：也不開", panel4.open_project(saved_path) is False and panel4.project_path != saved_path)
    panel4.exporter.busy = False

    # ----- 6. 比選單長的轉場 -----
    long_seam = os.path.join(tmp, "長轉場.srtproj")
    with open(long_seam, "w", encoding="utf-8") as fh:
        json.dump(dict(doc2, seam={"type": "fadeblack", "duration": 3.0}), fh)
    panel4._ask_project_discard = lambda: "discard"
    check("專案的轉場 3 秒（選單原本最多 2 秒）：照樣 3 秒、開完不算有變更",
          panel4.open_project(long_seam) and panel4.seam_combo.currentData() == "fadeblack"
          and abs(panel4.seam_spin.value() - 3.0) < 1e-9 and not panel4.project_changed(),
          f"{panel4.seam_spin.value()} {panel4.seam_combo.currentData()}")

    for w, p in ((win, panel), (win3, panel3), (win4, panel4)):
        p._ask_project_discard = lambda: "discard"
        p._ask_discard = lambda: "discard"
        p.shutdown()
        w.close()
    panel2.shutdown()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 專案檔介面測試全數通過。")
