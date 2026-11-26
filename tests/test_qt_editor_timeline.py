# -*- coding: utf-8 -*-
"""
剪輯器版面改版 E-2：時間軸（gui_qt/timeline.py、gui_qt/editor.py）。

E-2a：配色、軌道標頭、軌道加高、空狀態
1. 時間軸的每個顏色都取自色票（`subtitle/designtokens.py`），深淺兩套都對；timeline.py 裡沒有寫死的色碼。
2. 四頁籤的時間軸照舊是原本的列高（ROW_Y、TOTAL_H 不變），列上照舊寫怎麼用。
3. 剪輯器版面：軌道加高到 TALL_HEIGHTS；列上不寫說明，改寫在軌道標頭的提示裡；軌道標頭每一列跟時間軸的列
   同高同位置，換列高時跟著重排；點得到的範圍跟著新的列（點字幕列選得到那句、點素材軌選得到素材）。
4. 字幕塊放不下整句時尾巴加「…」，而且字真的塞得進方塊。
5. 沒開影片：時間軸顯示一句話＋〔開啟影片…〕（按了等於按媒體區的〔開啟影片〕）；有片長就換回軌道。
6. 換深淺色：軌道標頭與時間軸一起換色票。

E-2b：工具列
7. 〔分割〕與 Ctrl+B：在播放頭把那句切成兩句（優先選取的那句、不然播放頭底下那句），選後半句，逐句清單跟著多一列，
   Ctrl+Z 合回原樣；播放頭底下沒字幕就在狀態列講原因、什麼都不動。
8. 〔刪除〕與 Delete：刪時間軸上最後選的那個（字幕或素材，兩種可以同時選著），字幕 Ctrl+Z 救得回來；
   沒選東西時按鈕不能按。原本的〔刪除選取〕（只刪素材）換成這顆（REPLACED）。
9. 〔吸附〕：開著拖字幕的邊會貼到播放頭，關掉就照滑鼠的位置。
10. 縮放滑桿：拖滑桿＝縮放（對數刻度、兩頭到最小最大）；用按鈕或整支縮放，滑桿跟著移。
"""
import copy
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


try:
    import PySide6  # noqa: F401
except ImportError:
    PySide6 = None

if PySide6 is None:
    print("SKIP 這個環境沒有 PySide6：略過剪輯器時間軸")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer  # noqa: E402
    from PySide6.QtGui import QColor, QFont, QFontMetrics  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import editor as ed  # noqa: E402
    from gui_qt import theme  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle.designtokens import TOKENS  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def rgb(color):
        return QColor(color).getRgb()[:3]

    # ----- 1. 配色取自色票 -----
    src = open(os.path.join(ROOT, "gui_qt", "timeline.py"), encoding="utf-8").read()
    literals = re.findall(r"QColor\(\s*[\"']#|QColor\(\s*\d", src)
    check("timeline.py 沒有寫死的色碼（QColor(\"#…\")、QColor(數字…)）", not literals, str(literals))
    MAPPING = {"cue": "track.subtitle", "wave": "track.audio", "playhead": "accent", "cut_edge": "track.cut",
               "overlays": "track.overlay", "music": "track.audio", "cue_text": "track.text",
               "track_text": "track.text", "seam": "warning", "row": "bg.raised", "bg": "bg.panel",
               "cue_sel_pen": "text.primary", "track_sel_pen": "text.primary"}
    for name in ("dark", "light"):
        app.setPalette(theme.palette(name))
        view = tl.TimelineView()
        check(f"{name}：時間軸判斷得出深淺", tl.palette_theme(view) == name, tl.palette_theme(view))
        bad = [(k, view.colors[k].name(), TOKENS[name][t]) for k, t in MAPPING.items()
               if rgb(view.colors[k]) != rgb(TOKENS[name][t])]
        check(f"{name}：每個顏色都是對應的色票", not bad, str(bad))
        check(f"{name}：剪點的半透明是剪點色", rgb(view.colors["cut"]) == rgb(TOKENS[name]["track.cut"])
              and 0 < view.colors["cut"].alpha() < 255)
        check(f"{name}：選取的字幕塊比一般的亮", view.colors["cue_sel"].lightness() > view.colors["cue"].lightness())
        check(f"{name}：時間軸的底是面板色（列與列之間的縫看得到）",
              rgb(view.backgroundBrush().color()) == rgb(TOKENS[name]["bg.panel"]))

    # ----- 2. 四頁籤的時間軸不變 -----
    view = tl.TimelineView()
    check("預設列高＝原本的常數", view.row_y == tl.ROW_Y and view.total_h == tl.TOTAL_H
          and view.row_h["cues"] == tl.CUE_H and view.row_h["music"] == tl.TRACK_H, str(view.row_y))
    check("預設在列上寫怎麼用", view.inline_notes is True)

    # ----- 3. 剪輯器版面 -----
    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["theme"] = "dark"
    ed.apply_initial_theme(app, "dark")
    win = ed.EditorWindow(cfg)
    win.show()
    wait(200)
    p = win.player_panel
    t = p.timeline
    header = win.track_header
    check("軌道加高到 TALL_HEIGHTS", t.row_h == tl.TALL_HEIGHTS, str(t.row_h))
    check("軌道比四頁籤高（字幕、素材軌）", t.row_h["cues"] > tl.CUE_H and t.row_h["overlays"] > tl.TRACK_H)
    check("列上不寫說明", t.inline_notes is False)
    check("時間軸高度跟著列高", t.height() >= t.total_h, f"{t.height()} / {t.total_h}")
    names = [n for n, _label, _c in tl.TRACK_HEADERS]
    check("軌道標頭列出六軌", names == ["thumbs", "wave", "cues", "cuts", "overlays", "music"], str(names))
    misaligned = [n for n in names if (header.row_rect(n).top(), header.row_rect(n).height())
                  != (t.row_y[n], t.row_h[n])]
    check("標頭每一列跟時間軸的列同高同位置", not misaligned, str(misaligned))
    check("標頭與時間軸上緣對齊", header.mapTo(win, QPoint(0, 0)).y() == t.mapTo(win, QPoint(0, 0)).y(),
          f"{header.mapTo(win, QPoint(0, 0)).y()} / {t.mapTo(win, QPoint(0, 0)).y()}")
    check("標頭的提示寫原本列上的說明", tl.HEADER_TIPS["cuts"] == tl.CUT_LANE_NOTE
          and tl.HEADER_TIPS["overlays"] == tl.TRACK_NOTES["overlays"]
          and tl.HEADER_TIPS["music"] == tl.TRACK_NOTES["music"]
          and all(tl.HEADER_TIPS[n] for n in names))
    check("標頭照位置找得到列", header.row_at(t.row_y["cues"] + 2) == "cues"
          and header.row_at(t.row_y["music"] + t.row_h["music"] - 1) == "music" and header.row_at(1) is None)

    # ----- 5. 空狀態 -----
    check("沒開影片：顯示空狀態", win.timeline_stack.currentWidget() is win.timeline_empty
          and win.timeline_empty_label.text() == ed.TIMELINE_EMPTY_TEXT and win.timeline_open_btn.isVisible())
    clicked = []
    p.open_btn.setEnabled(True)
    # 不真的開檔案視窗：把 open_btn 原本接的動作換掉，只記有沒有被按
    try:
        p.open_btn.clicked.disconnect()
    except (RuntimeError, TypeError):
        pass
    p.open_btn.clicked.connect(lambda *_: clicked.append(1))
    win.timeline_open_btn.click()
    check("〔開啟影片…〕等於按媒體區的〔開啟影片〕", clicked == [1], str(clicked))

    t.set_duration(30)
    t.set_cues([{"start": 1, "end": 3, "text": "短句"},
                {"start": 4, "end": 5, "text": "這是一句很長很長很長很長很長很長很長很長的字幕放不下"},
                {"start": 7, "end": 9, "text": "最後"}])
    t.set_tracks([{"path": "/x/b.png", "at": 10, "in": 0, "out": 3, "length": 3}], [])
    t.set_zoom(40, 0, 0)
    wait(100)
    check("有片長：換回軌道", win.timeline_stack.currentIndex() == 1 and t.isVisible())

    # 點得到的範圍跟著新的列
    y_cue = t.row_y["cues"] + t.row_h["cues"] // 2
    QTest.mouseClick(t.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(int(2 * 40), y_cue))
    wait(50)
    check("點加高後的字幕列選得到那句", t.selected == 0, str(t.selected))
    y_track = t.row_y["overlays"] + t.row_h["overlays"] - 4  # 原本的列高（20）以外的地方
    QTest.mouseClick(t.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(int(11 * 40), y_track))
    wait(50)
    check("點加高後的疊加軌（舊列高以外）選得到素材", t.track_selected == ("overlays", 0), str(t.track_selected))

    # ----- 4. 字幕塊放不下加「…」 -----
    labels = {i: label for (item, label), (i, _c) in zip(t.cue_items, t.cues)}
    long_label, short_label = labels[1], labels[0]
    font = QFont(long_label.font())
    check("放不下的句子尾巴加「…」", long_label.text().endswith("…") and len(long_label.text()) > 1,
          long_label.text())
    check("加了「…」的字塞得進方塊", QFontMetrics(font).horizontalAdvance(long_label.text()) <= 40 * 1 - 8 + 1,
          f"{QFontMetrics(font).horizontalAdvance(long_label.text())}")
    check("放得下的句子不動", short_label.text() == "短句", short_label.text())

    # ----- 6. 換深淺色 -----
    win.toggle_theme()
    wait(100)
    check("換成淺色：時間軸換淺色色票", rgb(t.colors["cue"]) == rgb(TOKENS["light"]["track.subtitle"])
          and rgb(t.backgroundBrush().color()) == rgb(TOKENS["light"]["bg.panel"]))
    check("換成淺色：標頭也判斷成淺色", tl.palette_theme(header.timeline) == "light")
    win.toggle_theme()
    wait(100)
    check("換回深色", rgb(t.colors["cue"]) == rgb(TOKENS["dark"]["track.subtitle"]))

    # ----- 7. 分割 -----
    src_cues = [{"start": 1.0, "end": 5.0, "text": "今天要講，怎麼把字幕做好"},
                {"start": 6.0, "end": 8.0, "text": "第二句的字"},
                {"start": 10.0, "end": 12.0, "text": "第三句"}]
    p.set_cues(src_cues)
    t.set_duration(30)
    t.set_zoom(40, 0, 0)
    wait(50)
    pos = {"ms": 3000}
    p.player.position = lambda: pos["ms"]
    rows_before = win.cue_panel.table.rowCount()
    check("有字幕：〔分割〕能按、提示寫 Ctrl+B", win.split_tool.isEnabled() and "Ctrl+B" in win.split_tool.toolTip())
    t.setFocus()
    QTest.keyClick(t, Qt.Key_B, Qt.ControlModifier)
    wait(50)
    check("Ctrl+B：播放頭底下那句切成兩句", len(p.cues) == 4
          and (p.cues[0]["end"], p.cues[1]["start"]) == (3.0, 3.0)
          and (p.cues[0]["text"], p.cues[1]["text"]) == ("今天要講，", "怎麼把字幕做好"), str(p.cues[:2]))
    check("切完選後半句", t.selected == 1, str(t.selected))
    check("逐句清單跟著多一列", win.cue_panel.table.rowCount() == rows_before + 1,
          f"{rows_before} → {win.cue_panel.table.rowCount()}")
    check("狀態列講切了哪一句", "第 1 句" in win.statusBar().currentMessage(), win.statusBar().currentMessage())
    QTest.keyClick(t, Qt.Key_Z, Qt.ControlModifier)
    wait(50)
    check("Ctrl+Z：合回原本那一句", p.cues == src_cues, str(p.cues[:2]))
    # 選了別句、播放頭卻在另一句裡：切播放頭底下那句
    t.select_cue(2, seek=False)
    pos["ms"] = 7000
    win.split_tool.click()
    wait(50)
    check("〔分割〕：選的那句不在播放頭底下 → 切播放頭底下那句", len(p.cues) == 4
          and p.cues[1]["end"] == 7.0 and p.cues[2]["start"] == 7.0 and p.cues[3] == src_cues[2], str(p.cues))
    p.undo()
    pos["ms"] = 9000
    win.split_tool.click()
    wait(50)
    check("播放頭底下沒字幕：不動、狀態列講原因", p.cues == src_cues
          and "不能分割" in win.statusBar().currentMessage(), win.statusBar().currentMessage())
    pos["ms"] = 1020
    win.split_tool.click()
    check("離開頭太近：不動、講原因", p.cues == src_cues and "太近" in win.statusBar().currentMessage(),
          win.statusBar().currentMessage())

    # ----- 8. 刪除 -----
    check("〔刪除選取〕換成〔刪除〕", ("player_panel.remove_track_btn", "delete_tool") in ed.REPLACED
          and not p.remove_track_btn.isVisible() and win.delete_tool.isVisible())
    t.select_cue(-1, seek=False)
    t.select_track_item("", -1, seek=False)
    win._update_timeline_tools()
    check("沒選東西：〔刪除〕不能按", not win.delete_tool.isEnabled())
    t.select_cue(1, seek=False)
    check("選了字幕：〔刪除〕能按", win.delete_tool.isEnabled())
    t.setFocus()
    QTest.keyClick(t, Qt.Key_Delete)
    wait(50)
    check("Delete：刪掉選的那句", [c["text"] for c in p.cues] == ["今天要講，怎麼把字幕做好", "第三句"],
          str([c["text"] for c in p.cues]))
    QTest.keyClick(t, Qt.Key_Z, Qt.ControlModifier)
    wait(50)
    check("Ctrl+Z：刪掉的那句回來", p.cues == src_cues, str(p.cues))
    p.tracks["overlays"] = [{"path": os.path.join(tmp, "b.png"), "at": 14.0, "in": 0.0, "out": 3.0, "length": 3.0}]
    p.refresh_tracks()
    t.select_track_item("overlays", 0, seek=False)
    t.select_cue(0, seek=False)  # 兩個都選著，最後選的是字幕
    check("〔刪除〕：最後選字幕 → 刪字幕、素材留著", win.delete_selection() == "cue"
          and len(p.cues) == 2 and len(p.tracks["overlays"]) == 1)
    p.undo()
    t.select_cue(0, seek=False)
    t.select_track_item("overlays", 0, seek=False)  # 最後選的是素材
    check("〔刪除〕：最後選素材 → 刪素材、字幕留著", win.delete_selection() == "track"
          and len(p.cues) == 3 and not p.tracks["overlays"])

    # ----- 9. 吸附 -----
    def x_of(seconds):
        return int(round(seconds * t.px_per_sec)) - t.horizontalScrollBar().value()

    def drag(from_x, to_x, y):
        vp = t.viewport()
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(from_x, y))
        for k in range(1, 5):
            QTest.mouseMove(vp, QPoint(from_x + (to_x - from_x) * k // 4, y))
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(to_x, y))
        wait(20)

    y_cue = t.row_y["cues"] + t.row_h["cues"] // 2
    t.set_position(int(8.4 * 1000), follow=False)
    check("〔吸附〕預設開著", win.snap_tool.isChecked() and t.snap_enabled and t.snap_tolerance() > 0)
    drag(x_of(8) - 1, x_of(8.4) - 6, y_cue)  # 第二句的結尾拖到離播放頭 5px
    check("吸附開著：結尾貼到播放頭", abs(p.cues[1]["end"] - 8.4) < 1e-6, str(p.cues[1]))
    p.undo()
    win.snap_tool.click()
    check("按〔吸附〕關掉", not win.snap_tool.isChecked() and not t.snap_enabled and t.snap_tolerance() == 0)
    drag(x_of(8) - 1, x_of(8.4) - 6, y_cue)
    check("吸附關掉：結尾照滑鼠的位置（沒貼到播放頭）", 8.2 < p.cues[1]["end"] < 8.39, str(p.cues[1]))
    p.undo()
    win.snap_tool.click()
    check("再按一次打開", t.snap_enabled)

    # ----- 10. 縮放滑桿 -----
    check("滑桿兩頭＝最小最大的縮放", abs(tl.slider_to_zoom(0) - tl.MIN_PX_PER_SEC) < 1e-9
          and abs(tl.slider_to_zoom(tl.ZOOM_SLIDER_STEPS) - tl.MAX_PX_PER_SEC) < 1e-6)
    check("滑桿與縮放互為反函數", all(tl.zoom_to_slider(tl.slider_to_zoom(v)) == v for v in range(0, 101, 7)))
    win.zoom_slider.setValue(80)
    wait(20)
    check("拖滑桿＝縮放", abs(t.px_per_sec - tl.slider_to_zoom(80)) < 1e-6, str(t.px_per_sec))
    p.zoom_out_btn.click()
    wait(20)
    check("按〔拉遠〕：滑桿跟著移", win.zoom_slider.value() == tl.zoom_to_slider(t.px_per_sec) < 80,
          f"{win.zoom_slider.value()} / {t.px_per_sec}")
    p.fit_btn.click()
    wait(20)
    check("按〔整支〕：滑桿跟著移", win.zoom_slider.value() == tl.zoom_to_slider(t.px_per_sec),
          f"{win.zoom_slider.value()} / {t.px_per_sec}")

    win.player_panel.maybe_discard = lambda: True
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("剪輯器時間軸（E-2）測試全數通過。")
