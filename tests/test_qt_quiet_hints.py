# -*- coding: utf-8 -*-
"""
剪輯器版面 E-9b：說明放提示，不整段攤在畫面上（editor-ui-review：「說明文字放提示裡」）。

1. 媒體頁：〔加入畫面…〕〔加入音樂…〕下面那段常駐說明拿掉；那句話搬進兩顆按鈕的提示（原本的提示照留）。
2. 逐句清單下面那行選了一句時只講位置（一行放得下）；怎麼套用（Ctrl+Enter、Esc）寫在屬性面板編輯框的提示。
3. 四頁籤照舊：按鈕提示、逐句清單的說明一字不改。
"""
import copy
import os
import shutil
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

if PySide6 is None or not shutil.which("ffmpeg"):
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過說明放提示")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
    from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import cue_panel as cue_mod  # noqa: E402
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

    # 四頁籤先開：按鈕提示是原本的樣子（剪輯器只在自己的按鈕上加一句）
    tabs = qt_app.MainWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    tp = tabs.player_panel
    tabs_tips = (tp.add_overlay_btn.toolTip(), tp.add_music_btn.toolTip())

    ed.apply_initial_theme(app, "dark")
    win = ed.EditorWindow(copy.deepcopy(config.DEFAULT_CONFIG))
    win.resize(1440, 900)
    win.show()
    wait(100)
    p = win.player_panel
    cp = win.cue_panel

    # ----- 1 -----
    labels = [lab.text() for lab in win.findChildren(QLabel)]
    check("媒體頁那段常駐說明拿掉了", not any("加入的畫面與音樂放在播放頭" in t for t in labels))
    for btn, tip in ((p.add_overlay_btn, tabs_tips[0]), (p.add_music_btn, tabs_tips[1])):
        check(f"{btn.text()}：原本的提示照留、多一句放上去之後怎麼調",
              btn.toolTip() == tip + ed.TRACK_ADD_TIP and "時間軸上拖動" in btn.toolTip(), btn.toolTip())

    # ----- 2 -----
    p.set_cues([{"start": 1.0, "end": 3.0, "text": "第一句"}, {"start": 4.0, "end": 5.0, "text": "第二句"}])
    wait(30)
    p.timeline.select_cue(1, seek=False)
    wait(30)
    check("選第 2 句：清單下面只講位置", cp.note.text() == "第 2 句。文字與時間在右邊的屬性裡改。", cp.note.text())
    win.show_section("subtitles")
    wait(30)
    line = cp.note.fontMetrics().lineSpacing()
    check("一行放得下（沒有折成兩行）", cp.note.isVisible() and cp.note.heightForWidth(cp.note.width()) <= line * 1.5,
          f"{cp.note.width()} {cp.note.heightForWidth(cp.note.width())} {line}")
    check("怎麼套用寫在編輯框的提示", cp.editor.toolTip() == ed.CUE_APPLY_TIP
          and "Ctrl+Enter" in cp.editor.toolTip() and "Esc" in cp.editor.toolTip())

    # ----- 3 -----
    tabs.show()
    wait(30)
    tp.set_cues([{"start": 1.0, "end": 3.0, "text": "第一句"}, {"start": 4.0, "end": 5.0, "text": "第二句"}])
    wait(30)
    tabs.cue_panel.table.selectRow(1)
    wait(30)
    check("四頁籤：逐句清單的說明照舊", tabs.cue_panel.note.text() == "第 2 句。" + cue_mod.HINT, tabs.cue_panel.note.text())
    check("四頁籤：按鈕提示照舊", (tp.add_overlay_btn.toolTip(), tp.add_music_btn.toolTip()) == tabs_tips)
    check("四頁籤：編輯框沒有加提示", tabs.cue_panel.editor.toolTip() == "")

    for w in (win, tabs):
        w.player_panel.shutdown()
        w.close()
    wait(50)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("說明放提示（E-9b）測試全數通過。")
