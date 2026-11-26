# -*- coding: utf-8 -*-
"""
剪輯器版面改版 E-5：匯出視窗把原本分散的出口合成一個（gui_qt/editor.py 的 `_build_export_dialog`）。

1. 一個視窗四段，照常用順序：一鍵完成輸出、剪好的影片、字幕檔（單獨匯出＋多語字幕包）、品牌套版；
   左邊目錄同樣四項、同樣順序；每個現有的出口都在它那一段裡。
2. 點目錄捲到那一段（那一段的標題捲到看得到的地方）；`open_export(section=…)` 直接開到那一段，目錄跟著選。
3. 進度與結果釘在最下面（不在捲動區裡）：捲到哪一段都看得到；單獨匯出字幕檔的結果寫在那裡。
4. 〔多語字幕包…〕＝按〔翻譯字幕…〕；那顆不能按時這顆也不能按。
5. 寫四頁籤位置的說明、重複的標題在剪輯器裡收起來；視窗寬度放得下，不必左右捲。
6. 四頁籤的④頁照舊：說明、「只做單獨一件事」、「輸出」標題都在，進度與結果在輸出頁裡。
"""
import copy
import os
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
    print("SKIP 這個環境沒有 PySide6：略過剪輯器匯出視窗")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import editor as ed  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def inside(widget, ancestor):
        w = widget
        while w is not None:
            if w is ancestor:
                return True
            w = w.parentWidget()
        return False

    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["theme"] = "dark"
    ed.apply_initial_theme(app, "dark")
    win = ed.EditorWindow(cfg)
    win.show()
    wait(100)
    p = win.player_panel
    p._ask_discard = lambda *a, **k: "discard"
    p._ask_project_discard = lambda *a, **k: "discard"
    out = win.output_panel
    p.set_cues([{"start": 1.0, "end": 2.0, "text": "第一句"}, {"start": 3.0, "end": 4.0, "text": "第二句"}])
    dialog = win.open_export()
    wait(100)

    # ----- 1 -----
    nav = [win.export_nav.item(i).text() for i in range(win.export_nav.count())]
    keys = [win.export_nav.item(i).data(Qt.UserRole) for i in range(win.export_nav.count())]
    check("目錄四項、照常用順序", nav == ["一鍵完成輸出", "剪好的影片", "字幕檔", "品牌套版"]
          and keys == ["finish", "video", "subtitles", "branding"], str(nav))
    sec = win.export_sections
    order = sorted(sec, key=lambda k: sec[k].y())
    check("四段的上下順序跟目錄一樣", order == keys, str(order))
    homes = {"finish": [out.finish_btn, out.output_box, *out.format_boxes.values(), out.burn_box, out.dir_edit],
             "video": [p.export_btn, p.assemble_btn],
             "subtitles": [out.single_section, *out.export_btns.values(), win.export_pack_btn],
             "branding": [out.branding]}
    wrong = [(k, w.objectName() or type(w).__name__) for k, ws in homes.items() for w in ws if not inside(w, sec[k])]
    check("每個出口都在它那一段", not wrong, str(wrong))
    check("全部都在同一個視窗", all(inside(w, dialog) for ws in homes.values() for w in ws))

    # ----- 2 -----
    bar = win.export_scroll.verticalScrollBar()
    view = win.export_scroll.viewport()

    def shown(key):
        top = sec[key].mapTo(view, QPoint(0, 0)).y()
        return 0 <= top < view.height()

    check("一開始在第一段", win.export_nav.currentRow() == 0 and bar.value() == 0 and shown("finish"))
    win.export_nav.setCurrentRow(3)
    wait(30)
    check("點「品牌套版」：捲到那一段", bar.value() > 0 and shown("branding"), str(bar.value()))
    win.export_nav.setCurrentRow(2)
    wait(30)
    check("點「字幕檔」：捲到那一段", shown("subtitles"))
    dialog.close()
    win.open_export(section="video")
    wait(30)
    check("open_export(section=video)：開到那一段、目錄跟著選", shown("video")
          and win.export_nav.currentItem().data(Qt.UserRole) == "video")
    win.export_nav.setCurrentRow(0)
    check("點回第一段：捲回最上面", bar.value() == 0)

    # ----- 3 -----
    check("進度與結果不在捲動區裡", inside(out.status_area, dialog) and not inside(out.status_area, win.export_scroll))
    win.show_export_section("subtitles")
    wait(30)
    target = os.path.join(tmp, "out.srt")
    check("單獨匯出 SRT", out.export_single("srt", target) == target and os.path.isfile(target))
    check("結果寫在最下面、捲在字幕檔那一段也看得到", out.status_label.isVisible()
          and out.status_label.text() == f"已匯出：{target}" and shown("subtitles"))

    # ----- 4 -----
    clicked = []
    win.cue_panel.translate_btn.clicked.connect(lambda *_: clicked.append(1))
    win.cue_panel.open_translate = lambda: None  # 不真的開翻譯視窗
    win.cue_panel.translate_btn.setEnabled(True)
    win.export_pack_btn.click()
    check("〔多語字幕包…〕＝按〔翻譯字幕…〕", clicked == [1], str(clicked))
    win.cue_panel.translate_btn.setEnabled(False)
    check("那顆不能按：這顆也不能按", not win.export_pack_btn.isEnabled())
    win.cue_panel.translate_btn.setEnabled(True)
    check("那顆能按：這顆也能按", win.export_pack_btn.isEnabled())

    # ----- 5 -----
    check("寫四頁籤位置的說明、重複的標題收起來", not out.page_note.isVisible() and not out.single_heading.isVisible()
          and not out.single_note.isVisible() and out.output_box.title() == "" and out.branding.title() == "")
    check("不必左右捲", win.export_scroll.horizontalScrollBar().maximum() == 0,
          str(win.export_scroll.horizontalScrollBar().maximum()))
    check("目錄用色票的樣式（有自己的名字）", win.export_nav.objectName() == "exportNav"
          and "QListWidget#exportNav" in win.styleSheet())
    dialog.close()
    win.close()

    # ----- 6 -----
    qt_app.apply_theme(app, "light")
    win2 = qt_app.MainWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    win2.show()
    win2.tabs.setCurrentIndex(win2.tabs.count() - 1)
    wait(100)
    out2 = win2.output_panel
    check("四頁籤：④頁照舊有說明、「只做單獨一件事」、「輸出」標題", out2 is not None and out2.page_note.isVisible()
          and out2.single_heading.isVisible() and out2.single_note.isVisible() and out2.output_box.title() == "輸出")
    check("四頁籤：單獨匯出在「輸出」那一塊裡、進度與結果在輸出頁裡", inside(out2.single_section, out2.output_box)
          and inside(out2.status_area, out2) and out2.target_label.parentWidget() is out2)
    p2 = win2.player_panel
    p2._ask_discard = lambda *a, **k: "discard"
    p2._ask_project_discard = lambda *a, **k: "discard"
    win2.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("剪輯器匯出視窗（E-5）測試全數通過。")
