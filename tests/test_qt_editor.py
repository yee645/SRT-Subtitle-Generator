# -*- coding: utf-8 -*-
"""
剪輯器版面改版 E-1：主流剪輯軟體排版的外殼（gui_qt/editor.py、theme.py、icons.py）。

1. 五區都在：頂列、左邊圖示列＋左側面板、預覽、屬性、時間軸；預設 1440×900，最小 1100×700。
2. **功能一個不少**：FEATURE_MAP 列的每個現有功能都找得到、放在它說的那一區；反過來，四頁籤那份外殼與藏起來的
   播放器面板裡**沒有剩下任何按鈕**，除了 REPLACED 列的五顆（各有一個新元件做同一件事）。
3. 圖示列：四區互斥、切換左側面板；審片助手與健檢把左側面板拉寬，預覽至少留 360。媒體、字幕兩區看得到的按鈕
   字都沒被截掉（左側面板比原本的②頁窄）。
4. 頂列的圖示按鈕與〔匯出〕：轉寫與金鑰、導覽打得開；〔匯出〕打開的視窗裡有④的輸出面板、照剪點輸出、輸出多軌。
5. 開影片：播放鍵跟著原本的〔播放〕能不能按、按了真的播、圖示換成暫停；頂列寫影片名稱。
6. 快捷鍵：焦點在時間軸（已經不在播放器面板裡）照樣 Ctrl+Z 復原、Ctrl+Shift+Z 重做；每組按鍵只有一個有效的
   （播放器、逐句校對自己那份停掉，不會兩個衝突都不觸發）；Ctrl+F 切到字幕區、打開尋找。
7. 深淺色：按頂列的切換，調色盤與樣式表換成另一套色票、設定跟著記、圖示重畫；再按換回來。
8. 圖示：每個都畫得出東西、只用 currentColor、沒有外部連結。樣式表的小圖（箭頭、勾勾）檔案存在。
9. 關視窗前的詢問沿用：字幕改過沒存、選「取消」就不關。
10. 四頁籤的舊視窗不受影響：沒有套剪輯器的樣式表。
11. `main.py --qt --editor --selftest`：打開的是剪輯器版面（看視窗標題），自檢照樣通過。
"""
import copy
import json
import os
import subprocess as sp
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
    print("SKIP 這個環境沒有 PySide6：略過剪輯器版面")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
    from PySide6.QtGui import QKeySequence, QPalette, QShortcut  # noqa: E402
    from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QAbstractButton, QApplication, QTabBar  # noqa: E402

    import config  # noqa: E402
    from gui_qt import app as qt_app  # noqa: E402
    from gui_qt import editor as ed  # noqa: E402
    from gui_qt import icons, theme  # noqa: E402
    from gui_qt import timeline as tl  # noqa: E402
    from subtitle.designtokens import TOKENS  # noqa: E402

    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = os.path.join(tmp, "cache")
    config.CONFIG_PATH = os.path.join(tmp, "config.json")
    CLIP = os.path.join(ROOT, "research", "qt_probe", "probe_clip.mp4")
    SRT = os.path.join(tmp, "demo.srt")
    with open(SRT, "w", encoding="utf-8") as fp:
        fp.write("1\n00:00:00,500 --> 00:00:01,500\n第一句\n\n2\n00:00:02,000 --> 00:00:03,000\n第二句\n")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait_until(cond, ms=8000):
        waited = 0
        while not cond() and waited < ms:
            wait(50)
            waited += 50
        return cond()

    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["theme"] = "dark"
    ed.apply_initial_theme(app, "dark")
    win = ed.EditorWindow(cfg)
    win.show()
    wait(200)
    p = win.player_panel

    # ----- 1. 五區 -----
    for name in ("top_bar", "rail", "left_panel", "preview_panel", "inspector_panel", "timeline_panel"):
        w = getattr(win, name, None)
        check(f"有「{name}」而且看得到", w is not None and w.isVisible())
    check("預設 1440×900", (win.width(), win.height()) == ed.EDITOR_SIZE, f"{win.width()}x{win.height()}")
    check("最小 1100×700", (win.minimumWidth(), win.minimumHeight()) == ed.EDITOR_MIN)
    check("預覽在左側面板與屬性中間、時間軸在下面整條",
          win.left_panel.geometry().right() < win.preview_panel.geometry().left()
          and win.preview_panel.mapTo(win, win.preview_panel.rect().topRight()).x()
          < win.inspector_panel.mapTo(win, win.inspector_panel.rect().topLeft()).x()
          and win.timeline_panel.mapTo(win, win.timeline_panel.rect().topLeft()).y()
          > win.preview_panel.mapTo(win, win.preview_panel.rect().bottomLeft()).y()
          and win.timeline_panel.width() > win.width() * 0.85)
    check("播放器面板本身不顯示、四頁籤外殼不顯示", not p.isVisible() and not win.legacy_central.isVisible())

    # ----- 2. 功能一個不少 -----
    for feature, path, where in ed.FEATURE_MAP:
        try:
            widget = ed.resolve(win, path)
        except AttributeError as exc:
            check(f"找得到：{feature}", False, str(exc))
            continue
        container = ed.region(win, where)
        check(f"{feature} → {where}", container.isAncestorOf(widget), path)
    leftover = []
    allowed = {id(ed.resolve(win, old)) for old, _new in ed.REPLACED}
    for holder in (win.legacy_central, p):
        for btn in holder.findChildren(QAbstractButton):
            if id(btn) not in allowed and not isinstance(btn.parent(), QTabBar):  # 頁籤列自己的左右捲動鈕不算
                leftover.append(btn.text() or btn.toolTip()[:20] or btn.objectName())
    check("四頁籤外殼與播放器面板裡沒有剩下的按鈕（全搬到新版面）", not leftover, str(leftover))
    for old, new in ed.REPLACED:
        check(f"{old} 換成 {new}，看得到", ed.resolve(win, new).isVisible())

    # ----- 3. 圖示列 -----
    check("圖示列四區", [b.text() for b in win.rail_buttons.values()] == ["媒體", "字幕", "智慧剪輯", "健檢"])
    check("一開始在媒體", win.current_section() == "media" and win.rail_buttons["media"].isChecked())
    QTest.mouseClick(win.rail_buttons["subtitles"], Qt.LeftButton)
    wait(50)
    check("點字幕：切到字幕區、只有它按下", win.current_section() == "subtitles"
          and [k for k, b in win.rail_buttons.items() if b.isChecked()] == ["subtitles"]
          and win.cue_panel.isVisible())
    narrow = win.left_panel.width()
    QTest.mouseClick(win.rail_buttons["health"], Qt.LeftButton)
    wait(50)
    check("點健檢：健檢面板看得到、左側面板拉寬、預覽至少 360",
          win.health_panel.isVisible() and win.left_panel.width() > narrow and win.preview_panel.width() >= 360,
          f"{narrow}→{win.left_panel.width()} 預覽 {win.preview_panel.width()}")
    win.show_section("smart")
    wait(50)
    check("智慧剪輯：審片助手看得到", win.review_panel.isVisible())
    from PySide6.QtWidgets import QPushButton  # noqa: E402

    def clipped_buttons():
        """看得到的按鈕裡，寬度放不下自己字的（字被截掉）。"""
        return [b.text() for b in win.findChildren(QPushButton)
                if b.isVisible() and b.text() and b.width() < b.sizeHint().width() - 2]

    for key in ("media", "subtitles"):
        win.show_section(key)
        wait(50)
        check(f"{key}：看得到的按鈕字都沒被截掉", not clipped_buttons(), str(clipped_buttons()))
    win.show_section("media")
    wait(50)
    check("切回媒體：左側面板變回窄的", win.left_panel.width() <= ed.SECTION_WIDTH["media"] + 8,
          str(win.left_panel.width()))

    # ----- 4. 頂列 -----
    QTest.mouseClick(win.transcription_tool, Qt.LeftButton)
    check("轉寫與金鑰打得開", win.transcription_dialog is not None and win.transcription_dialog.isVisible())
    win.transcription_dialog.close()
    QTest.mouseClick(win.guide_tool, Qt.LeftButton)
    check("導覽打得開", win.guide_dialog is not None and win.guide_dialog.isVisible())
    win.guide_dialog.close()
    check("〔匯出〕是唯一一顆主要按鈕",
          [b for b in win.findChildren(QAbstractButton) if b.property("role") == "primary"] == [win.export_button])
    QTest.mouseClick(win.export_button, Qt.LeftButton)
    check("〔匯出〕打開匯出視窗，裡面有輸出面板、照剪點輸出、輸出多軌",
          win.export_dialog.isVisible() and win.output_panel.isVisible() and p.export_btn.isVisible()
          and p.assemble_btn.isVisible())
    win.export_dialog.close()
    check("沒開影片：頂列寫未命名專案", win.refresh_project_name() == "未命名專案")

    # ----- 5. 開影片 -----
    check("沒開影片：播放鍵不能按", not win.play_tool.isEnabled())
    p.open_video(CLIP)
    check("開影片：播放鍵跟著能按", wait_until(lambda: win.play_tool.isEnabled()))
    wait_until(lambda: p.media_duration() > 0)
    check("頂列寫影片名稱", win.refresh_project_name().startswith("probe_clip.mp4"), win.refresh_project_name())
    QTest.mouseClick(win.play_tool, Qt.LeftButton)
    check("按播放鍵：真的播、提示換成暫停",
          wait_until(lambda: p.player.playbackState() == QMediaPlayer.PlayingState)
          and win.play_tool.toolTip() == "暫停")
    QTest.mouseClick(win.play_tool, Qt.LeftButton)
    check("再按：停", wait_until(lambda: p.player.playbackState() != QMediaPlayer.PlayingState)
          and win.play_tool.toolTip() == "播放")

    # ----- 6. 快捷鍵 -----
    p.load_subtitles(SRT)
    wait(100)
    p.set_cue_text(0, "改過的第一句")
    win.activateWindow()
    p.timeline.setFocus()
    wait(50)
    check("焦點在時間軸（已經不在播放器面板裡）", not p.isAncestorOf(app.focusWidget() or win))
    QTest.keyClick(p.timeline, Qt.Key_Z, Qt.ControlModifier)
    wait(50)
    check("Ctrl+Z 復原", p.cues[0]["text"] == "第一句", p.cues[0]["text"])
    QTest.keyClick(p.timeline, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
    wait(50)
    check("Ctrl+Shift+Z 重做", p.cues[0]["text"] == "改過的第一句", p.cues[0]["text"])
    active = {}
    for sc in win.findChildren(QShortcut):
        if sc.isEnabled() and sc.key().toString():
            active.setdefault(sc.key().toString(), []).append(sc)
    dup = {k: len(v) for k, v in active.items() if len(v) > 1}
    check("每組按鍵只有一個有效的快捷鍵（不會衝突）", not dup, str(dup))
    undo_key = QKeySequence(QKeySequence.Undo).toString()
    check("復原是整個視窗都有效的", any(sc.context() == Qt.WindowShortcut for sc in active.get(undo_key, [])))
    QTest.keyClick(p.timeline, Qt.Key_F, Qt.ControlModifier)
    wait(50)
    check("Ctrl+F：切到字幕區、打開尋找", win.current_section() == "subtitles" and win.cue_panel.find_bar.isVisible())

    # ----- 7. 深淺色 -----
    def window_color():
        return app.palette().color(QPalette.Window).name()

    check("一開始是深色色票", window_color() == TOKENS["dark"]["bg.panel"]
          and TOKENS["dark"]["bg.window"] in win.styleSheet())
    QTest.mouseClick(win.theme_tool, Qt.LeftButton)
    wait(50)
    check("按切換：換成淺色色票、設定記成 light、提示換字",
          window_color() == TOKENS["light"]["bg.panel"] and TOKENS["light"]["bg.window"] in win.styleSheet()
          and TOKENS["dark"]["bg.window"] not in win.styleSheet() and cfg["theme"] == "light"
          and win.theme_tool.toolTip() == "切換為深色", f"{window_color()} {cfg['theme']}")
    img = win.top_bar.grab().toImage()
    check("頂列真的變亮", img.pixelColor(img.width() // 2, 4).lightness() > 200,
          str(img.pixelColor(img.width() // 2, 4).name()))
    QTest.mouseClick(win.theme_tool, Qt.LeftButton)
    wait(50)
    check("再按：換回深色", window_color() == TOKENS["dark"]["bg.panel"] and cfg["theme"] == "dark")
    img = win.top_bar.grab().toImage()
    check("頂列真的變暗", img.pixelColor(img.width() // 2, 4).lightness() < 60)

    # ----- 8. 圖示 -----
    empty = []
    for name, body in icons.PATHS.items():
        pm = icons.pixmap(name, "#ff0000", 24)
        image = pm.toImage()
        painted = sum(1 for x in range(24) for y in range(24) if image.pixelColor(x, y).alpha() > 0)
        if painted < 6:
            empty.append(name)
    check(f"{len(icons.PATHS)} 個圖示都畫得出東西", not empty, str(empty))
    check("圖示只用 currentColor、沒有外部連結或寫死的顏色",
          all("href" not in b and "http" not in b and "#" not in b for b in icons.PATHS.values()))
    for t in ("dark", "light"):
        files = theme.assets(t)
        check(f"{t}：樣式表的小圖都在", all(os.path.exists(f) and os.path.getsize(f) > 0 for f in files.values()))
        check(f"{t}：樣式表的路徑用正斜線", all("\\" not in f for f in files.values()))

    # ----- 9. 關視窗前的詢問 -----
    asked = []
    p._ask_discard = lambda *a: asked.append(1) or "cancel"
    win.close()
    wait(50)
    check("字幕改過沒存：會問，選取消就不關", asked and win.isVisible())

    # ----- 10. 舊視窗 -----
    old = qt_app.MainWindow(copy.deepcopy(cfg))
    check("四頁籤的舊視窗沒有套剪輯器的樣式表", old.styleSheet() == "" and old.tabs.count() == 4)
    old.player_panel._ask_discard = lambda *a: "discard"
    old.close()

    p._ask_discard = lambda *a: "discard"
    p._ask_project_discard = lambda *a: "discard"
    win.close()

    # ----- 11. main.py --qt --editor --selftest -----
    out = os.path.join(tmp, "selftest.json")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    proc = sp.run([sys.executable, "-B", "main.py", "--qt", "--editor", "--selftest", out, CLIP], cwd=ROOT, env=env,
                  capture_output=True, timeout=180)
    res = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else {}
    check("main.py --qt --editor：打開剪輯器版面、自檢通過",
          proc.returncode == 0 and res.get("ok") is True and res.get("window_title") == ed.EDITOR_TITLE,
          f"rc={proc.returncode} {res} {proc.stderr[-400:]}")
    app_src = open(os.path.join(ROOT, "gui_qt", "app.py"), encoding="utf-8").read()
    check("main() 開的剪輯器版面也是：會存設定、自檢模式不存",
          "editor.EditorWindow(data, persist=SELFTEST_FLAG not in argv)" in app_src)
    proc = sp.run([sys.executable, "-B", "main.py", "--qt", "--selftest", out, CLIP], cwd=ROOT, env=env,
                  capture_output=True, timeout=180)
    res = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else {}
    check("不加 --editor：照舊是四頁籤", proc.returncode == 0 and len(res.get("tabs", [])) == 4
          and res.get("window_title") == qt_app.WINDOW_TITLE, f"rc={proc.returncode} {res}")

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("剪輯器版面（E-1）測試全數通過。")
