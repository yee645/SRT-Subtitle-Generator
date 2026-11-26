#!/usr/bin/env python3
"""
剪輯器版面（--editor）截圖：空的、開影片＋字幕後左側四區、匯出視窗。

    FONTCONFIG_FILE=/tmp/srt-fonts.conf QT_QPA_PLATFORM=offscreen \
      /tmp/qtv12/bin/python3 .claude/skills/srt-verify/shot_editor.py dark <輸出前綴> [影片] [字幕]

沒給影片就用 ffmpeg 產生 30 秒的測試片（彩條＋音）與一份 5 句的字幕，放在輸出前綴旁邊。
輸出：<前綴>_empty.png、_media、_subtitles、_smart、_health、_export.png。截完用 Read 看，深淺兩色都要看。
"""
import copy
import os
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import config  # noqa: E402
from gui_qt import editor as ed  # noqa: E402
from gui_qt import timeline as tl  # noqa: E402

SRT = """1\n00:00:01,000 --> 00:00:04,000\n歡迎來到這一集的教學\n\n2\n00:00:04,500 --> 00:00:08,000\n今天要講怎麼把字幕做得又快又好\n
3\n00:00:09,000 --> 00:00:13,000\n先把影片拖進來，自動產生字幕\n\n4\n00:00:14,000 --> 00:00:18,000\n接著在時間軸上調整每一句的時間\n
5\n00:00:19,000 --> 00:00:24,000\n最後選好樣式，一鍵輸出\n"""


def demo_media(folder):
    media, srt = os.path.join(folder, "demo.mp4"), os.path.join(folder, "demo.srt")
    if not os.path.exists(media):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                        "-f", "lavfi", "-i", "sine=frequency=440", "-t", "30", "-pix_fmt", "yuv420p",
                        "-c:v", "libx264", "-c:a", "aac", media], check=True)
    with open(srt, "w", encoding="utf-8") as fp:
        fp.write(SRT)
    return media, srt


def main():
    theme, out = sys.argv[1], sys.argv[2]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    media, srt = (sys.argv[3], sys.argv[4]) if len(sys.argv) > 4 else demo_media(os.path.dirname(os.path.abspath(out)))
    app = QApplication([])
    ed.apply_initial_theme(app, theme)
    tmp = tempfile.mkdtemp()
    tl.CACHE_ROOT = tmp
    config.CONFIG_PATH = os.path.join(tmp, "c.json")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["theme"] = theme
    win = ed.EditorWindow(cfg)
    win.show()
    wait(300)
    win.grab().save(f"{out}_empty.png")
    p = win.player_panel
    p.open_video(media)
    wait(5000)
    p.load_subtitles(srt)
    wait(1500)
    p.player.setPosition(4000)
    wait(800)
    for key in ("media", "subtitles", "smart", "health"):
        win.show_section(key)
        wait(500)
        win.grab().save(f"{out}_{key}.png")
    d = win.open_export()
    wait(500)
    d.grab().save(f"{out}_export.png")
    p._ask_discard = lambda *a: "discard"
    p._ask_project_discard = lambda *a: "discard"
    win.close()
    print("截圖完成：", out + "_*.png")


if __name__ == "__main__":
    main()
