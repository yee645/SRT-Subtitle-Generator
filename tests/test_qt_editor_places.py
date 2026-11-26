# -*- coding: utf-8 -*-
"""
剪輯器版面 E-7a：面板的說明文字照所在版面的位置講（gui_qt/places.py）。

1. 剪輯器版面：建好之後看得到的字（標籤、按鈕、提示、佔位字、群組標題、頁籤，含〔匯出〕對話框）都沒有
   「②」這類頁籤編號；收起來的四頁籤外殼不動。
2. 之後才顯示的字也換：審片助手沒字幕、健檢的檢查對象、輸出面板沒字幕；開出來的對話框（批次）也是剪輯器的說法。
3. 四頁籤一字不差：同樣的情況顯示原本的字（含頁籤編號）。
4. here() 看的是元件當下所在的視窗（往上找父元件；對話框找它的父視窗），沒有全域開關：兩種視窗並存互不影響。
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
    print("SKIP 這個環境沒有 PySide6：略過位置說法")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
    from PySide6.QtWidgets import (  # noqa: E402
        QAbstractButton, QApplication, QGroupBox, QLabel, QLineEdit, QPlainTextEdit, QTabWidget, QTextEdit, QWidget,
    )

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import editor as ed  # noqa: E402
    from gui_qt import health_panel as hp  # noqa: E402
    from gui_qt import output_panel as op  # noqa: E402
    from gui_qt import places  # noqa: E402
    from gui_qt import review_panel as rp  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle.placenames import for_editor, has_tab_place  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def texts(root, skip=None):
        """root 底下每個元件顯示的字：[(元件, 字)]。"""
        out = []
        for w in [root] + root.findChildren(QWidget):
            if skip is not None and (w is skip or skip.isAncestorOf(w)):
                continue
            items = [w.toolTip()]
            if isinstance(w, (QLabel, QAbstractButton)):
                items.append(w.text())
            if isinstance(w, (QLineEdit, QPlainTextEdit, QTextEdit)):
                items.append(w.placeholderText())
            if isinstance(w, QGroupBox):
                items.append(w.title())
            if isinstance(w, QTabWidget):
                items += [w.tabText(i) for i in range(w.count())] + [w.tabToolTip(i) for i in range(w.count())]
            out += [(w, t) for t in items if t]
        return out

    def stub(win):
        p = win.player_panel
        p._ask_discard = lambda *a, **k: "discard"
        p._ask_project_discard = lambda *a, **k: "discard"

    # ----- 1 -----
    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    ed.apply_initial_theme(app, "dark")
    win = ed.EditorWindow(cfg)
    stub(win)
    win.resize(1440, 900)
    win.show()
    wait(100)
    check("剪輯器視窗標了版面", places.layout_of(win) == places.EDITOR)
    for key in ("media", "subtitles", "smart", "health"):
        win.show_section(key)
        wait(30)
    left = [(type(w).__name__, w.objectName(), t[:30]) for w, t in texts(win, skip=win.legacy_central)
            if has_tab_place(t)]
    check("剪輯器裡看得到的字都沒有頁籤編號（含匯出對話框）", not left, str(left[:4]))
    shell = [t for _w, t in texts(win.legacy_central) if has_tab_place(t)]
    check("收起來的四頁籤外殼不動（頁籤名稱照舊）", any("② 字幕" in t for t in shell), str(shell[:3]))
    check("審片助手的說明換成剪輯器的說法（逐字）",
          any(isinstance(w, QLabel) and w.text() == for_editor(rp.PAGE_NOTE) for w, _t in texts(win.review_panel)))
    check("輸出面板的說明（在匯出對話框裡）也換了",
          win.output_panel.page_note.text() in ("", for_editor(op.PAGE_NOTE)) and
          not has_tab_place(win.output_panel.page_note.text()))

    # ----- 2 -----
    win.review_panel.start_analysis()
    check("審片助手沒字幕：剪輯器的說法", win.review_panel.status_label.text() == for_editor(rp.NO_CUES),
          win.review_panel.status_label.text())
    win.health_panel.refresh_target()
    target = win.health_panel.target_label.text()
    check("健檢的檢查對象：剪輯器的說法", target.startswith("檢查對象（現在開著的）：") and not has_tab_place(target),
          target)
    win.output_panel.finish_output()
    check("輸出面板沒字幕：剪輯器的說法", win.output_panel.status_label.text() == for_editor(op.NO_CUES),
          win.output_panel.status_label.text())
    win.open_batch()
    wait(50)
    dlg = win.batch_dialog
    check("批次對話框：找得到剪輯器版面（找父視窗）", places.layout_of(dlg) == places.EDITOR)
    bad = [t[:30] for _w, t in texts(dlg) if has_tab_place(t)]
    check("批次對話框裡沒有頁籤編號", not bad, str(bad[:3]))
    dlg.close()

    # ----- 3 -----
    qt_app.apply_theme(app, "light")
    win2 = qt_app.MainWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    stub(win2)
    win2.show()
    wait(50)
    check("四頁籤：視窗沒有標版面", places.layout_of(win2) == "tabs")
    check("四頁籤：審片助手的說明一字不差",
          any(isinstance(w, QLabel) and w.text() == rp.PAGE_NOTE for w, _t in texts(win2.review_panel)))
    win2.review_panel.start_analysis()
    check("四頁籤：審片助手沒字幕一字不差", win2.review_panel.status_label.text() == rp.NO_CUES)
    win2.health_panel.refresh_target()
    check("四頁籤：健檢的檢查對象一字不差",
          win2.health_panel.target_label.text().startswith("檢查對象（②字幕頁開著的）："))
    win2.output_panel.finish_output()
    check("四頁籤：輸出面板沒字幕一字不差", win2.output_panel.status_label.text() == op.NO_CUES)
    win2.open_batch()
    wait(50)
    check("四頁籤：批次對話框照舊寫④", any("④" in t for _w, t in texts(win2.batch_dialog)))
    win2.batch_dialog.close()

    # ----- 4 -----
    check("here：剪輯器裡的元件換", places.here(win.review_panel, rp.STALE) == for_editor(rp.STALE))
    check("here：四頁籤裡的元件不換", places.here(win2.review_panel, rp.STALE) == rp.STALE)
    loose = QLabel()
    check("here：沒有父元件＝四頁籤的說法", places.here(loose, hp.NOTHING) == hp.NOTHING)
    loose.setParent(win.health_panel)
    check("here：搬進剪輯器之後就換", places.here(loose, hp.NOTHING) == for_editor(hp.NOTHING))
    check("here：沒有頁籤編號的原樣", places.here(loose, "沒有編號") == "沒有編號")
    lbl = QLabel(rp.STALE)
    holder = QWidget()
    holder.setProperty(places.LAYOUT_PROPERTY, places.EDITOR)
    lbl.setParent(holder)
    check("relabel_tree：換了幾處就回傳幾", places.relabel_tree(holder) == 1 and lbl.text() == for_editor(rp.STALE))
    check("relabel_tree：再跑一次沒有東西可換", places.relabel_tree(holder) == 0)
    tabs = QTabWidget(holder)
    tabs.addTab(QWidget(), "②的字幕")
    tabs.setTabToolTip(0, "到④匯出")
    places.relabel_tree(holder)
    check("relabel_tree：頁籤名稱與提示也換", tabs.tabText(0) == "字幕" and tabs.tabToolTip(0) == "到〔匯出〕匯出",
          f"{tabs.tabText(0)} / {tabs.tabToolTip(0)}")
    win2.close()
    win.close()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("剪輯器位置說法（E-7a）測試全數通過。")
