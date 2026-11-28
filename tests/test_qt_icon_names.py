# -*- coding: utf-8 -*-
"""
剪輯器版面 E-9l：只有圖示的按鈕給螢幕閱讀器一個名字（之前 13 顆沒有字、也沒有 accessibleName，螢幕閱讀器只念得出「按鈕」）。

1. accessible_label：提示的第一段（「：」「（」之前）。
2. 剪輯器裡每一顆看得到、只有圖示的按鈕都有名字（＝提示的第一段）與說明（＝整段提示）；例如復原、播放、拉近。
3. 提示換了名字跟著換：切換深淺色、播放鍵變暫停。
4. 有字的按鈕不動（螢幕閱讀器念按鈕上的字）。
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
    print("SKIP 這個環境沒有 PySide6 或 ffmpeg：略過按鈕的名字")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
    from PySide6.QtWidgets import QAbstractButton, QApplication  # noqa: E402

    import config  # noqa: E402
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

    # ----- 1 -----
    check("accessible_label：冒號之前", ed.accessible_label("復原：復原上一次改的時間（Ctrl+Z）") == "復原")
    check("accessible_label：括號之前", ed.accessible_label("上一格（←）") == "上一格")
    check("accessible_label：沒有冒號括號就整段", ed.accessible_label("切換為深色") == "切換為深色")
    check("accessible_label：空的還是空的", ed.accessible_label("") == "" and ed.accessible_label(None) == "")

    # ----- 2 -----
    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["theme"] = "light"
    ed.apply_initial_theme(app, "light")
    win = ed.EditorWindow(cfg)
    win.resize(1440, 900)
    win.show()
    wait(100)
    p = win.player_panel
    icon_only = [b for b in win.findChildren(QAbstractButton) if b.isVisible() and not b.text().strip()]
    check("（準備）找得到只有圖示的按鈕", len(icon_only) >= 13, str(len(icon_only)))
    missing = [b.toolTip()[:20] for b in icon_only if not b.accessibleName()]
    check("每一顆只有圖示的按鈕都有名字", not missing, str(missing))
    wrong = [(b.accessibleName(), b.toolTip()[:20]) for b in icon_only
             if b.accessibleName() != ed.accessible_label(b.toolTip()) or b.accessibleDescription() != b.toolTip()]
    check("名字＝提示的第一段、說明＝整段提示", not wrong, str(wrong))
    names = {b.accessibleName() for b in icon_only}
    for want in ("復原", "重做", "拉近", "拉遠", "整支", "播放", "上一格", "下一格", "專注預覽", "即時查譯"):
        check(f"有「{want}」", want in names, str(sorted(names)))

    # ----- 3 -----
    before = win.theme_tool.accessibleName()
    win.theme_tool.click()
    wait(60)
    check("切換深淺色之後名字跟著換", win.theme_tool.accessibleName() != before
          and win.theme_tool.accessibleName() == ed.accessible_label(win.theme_tool.toolTip()),
          f"{before} → {win.theme_tool.accessibleName()}")
    win.play_tool.setToolTip("暫停（Space、K）")  # 播放中 _update_play_icon 會換成這種提示
    check("播放鍵變暫停：名字跟著換", win.play_tool.accessibleName() == "暫停", win.play_tool.accessibleName())

    # ----- 4 -----
    check("有字的按鈕不動（〔匯出〕〔開啟影片〕）", win.export_button.accessibleName() == ""
          and p.open_btn.accessibleName() == "")

    p.shutdown()
    win.close()
    wait(50)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("按鈕的名字（E-9l）測試全數通過。")
