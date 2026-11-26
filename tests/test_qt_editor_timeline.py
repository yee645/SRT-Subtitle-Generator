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

    win.player_panel.maybe_discard = lambda: True
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("剪輯器時間軸（E-2）測試全數通過。")
