# -*- coding: utf-8 -*-
"""
3.0 預覽版的自檢模式：打包後的成品自己證明「還能動」。

`--selftest <結果.json> <影片>`：開主視窗、用 Qt Multimedia 真的播放那支
影片、數解出幾格，播完（或逾時）把結果寫成 JSON，結束碼 0＝通過、1＝不
通過。給 `.github/workflows/qt-preview.yml` 在打包、刪檔之後跑——第 0 項
實測過，拿掉不該拿的 DLL 時播放器會「不可用」而且**不發任何錯誤訊號**，
只看有沒有當掉會誤判，所以這裡看的是真的解出了畫格。

聲音設成靜音：CI 機器沒有音效裝置，影音同步本來就驗不到。

另外量一件事（3.0 之後 A-1）：**None 的參照數有沒有被多減**。PySide6 6.12.0 在 Python 3.11 上，每呼叫
一次沒有回傳值的方法就把 None 的參照數多減一，用久了整個程式崩潰（`none_dealloc`，第 10 項第二階段實測）。
v3.0.0 的發版流程就是用 3.11 打的；這裡在成品裡直接量，Python／PySide6 的組合再錯也會被擋下。
"""
import json
import os
import sys
import time

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget

TIMEOUT_MS = 20000
NONE_PROBE_CALLS = 1000


def none_refcount_drift(calls=NONE_PROBE_CALLS):
    """
    呼叫 `calls` 次沒有回傳值的 Qt 方法，回傳 None 參照數的變化。正常是 0（3.12 起 None 是永生物件，
    數字根本不動）；有那個錯時大約是 -calls。
    """
    from PySide6.QtWidgets import QLabel
    label = QLabel()
    before = sys.getrefcount(None)
    for _ in range(calls):
        label.setText("x")
    return sys.getrefcount(None) - before


def none_refcount_ok(drift, calls=NONE_PROBE_CALLS):
    """少掉一半以上就算有錯（正常的雜訊只有個位數）。"""
    return drift > -calls // 2


def run(app, win, out_path, clip):
    """在已建立的主視窗上跑自檢；回傳事件迴圈結束碼（0＝通過）。"""
    t0 = time.perf_counter()
    video = QVideoWidget()
    player = QMediaPlayer()
    audio = QAudioOutput()
    audio.setMuted(True)
    player.setAudioOutput(audio)
    player.setVideoOutput(video)
    # 放在主視窗裡一起顯示：驗的是「主視窗＋播放器」這個組合，不是另開
    # 一個孤立的影片視窗。
    win.statusBar().addPermanentWidget(video)
    video.setFixedSize(160, 90)

    result = {
        "window_title": win.windowTitle(),
        "tabs": [win.tabs.tabText(i) for i in range(win.tabs.count())],
        "layout": getattr(win, "LAYOUT", ""),  # E-7b：剪輯器版面是預設，四頁籤要 --tabs
        "clip": os.path.basename(clip),
        "player_available": player.isAvailable(),
        "frames_decoded": 0,
        "first_frame": "",
        "media_status": "",
        "player_error": "",
        "python": sys.version.split()[0],
        "none_refcount_drift": none_refcount_drift(),
    }
    done = []

    def finish():
        if done:
            return
        done.append(True)
        result["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        result["ok"] = bool(result["player_available"]
                            and result["frames_decoded"] > 0
                            and result["media_status"] == "EndOfMedia"
                            and not result["player_error"]
                            and none_refcount_ok(result["none_refcount_drift"]))
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
        player.stop()
        app.exit(0 if result["ok"] else 1)

    def on_frame(frame):
        if frame.isValid():
            if not result["frames_decoded"]:
                size = frame.size()
                result["first_frame"] = f"{size.width()}x{size.height()}"
            result["frames_decoded"] += 1

    def on_status(status):
        result["media_status"] = status.name
        if status in (QMediaPlayer.MediaStatus.EndOfMedia,
                      QMediaPlayer.MediaStatus.InvalidMedia):
            QTimer.singleShot(0, finish)

    def on_error(err, message):
        result["player_error"] = f"{err.name}: {message}"
        QTimer.singleShot(0, finish)

    video.videoSink().videoFrameChanged.connect(on_frame)
    player.mediaStatusChanged.connect(on_status)
    player.errorOccurred.connect(on_error)
    win.show()
    if not result["player_available"]:
        # 後端外掛沒載入：不會有任何訊號，直接收工。
        QTimer.singleShot(0, finish)
    else:
        player.setSource(QUrl.fromLocalFile(os.path.abspath(clip)))
        player.play()
    QTimer.singleShot(TIMEOUT_MS, finish)
    # 讓區域變數（播放器等）活到事件迴圈結束。
    win._selftest_keepalive = (video, player, audio)
    return app.exec()
