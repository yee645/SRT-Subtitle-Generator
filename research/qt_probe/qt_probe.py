# -*- coding: utf-8 -*-
"""
3.0 工作清單第 0 項的量測探針：Qt（PySide6）版打包後有多大、多快開起來。

這支程式**不是產品的一部分**，只給 `.github/workflows/qt-probe.yml` 在
windows-latest 上用 PyInstaller 打包、實際執行、量數字。它載入 3.0 會用到
的模組（Widgets、Multimedia、MultimediaWidgets），建一個帶影片元件與播放器
的主視窗，畫出第一個畫面後把量測結果寫成 JSON 就自己關掉。

量的是：

- `import_ms`：匯入 PySide6 三個模組花的時間。
- `shown_ms`：從 Python 開始執行本檔到主視窗顯示、事件迴圈第一次空下來
  （show() 產生的繪製已處理完）。onefile 版的解壓時間
  **不在這裡面**（解壓發生在 Python 啟動之前），所以工作流程另外在外面用牆
  上時間量整個行程。
- `player_error`：給播放器一個不存在的檔案，後端正常時會回報「找不到檔案」
  （ResourceError）。後端外掛沒被打包進去時是另一種錯誤或完全沒反應。實際
  用的是哪個後端看 Qt 印在標準錯誤的那一行（「Using Qt multimedia with
  FFmpeg …」），工作流程會一併收下來。

- 第二個參數給一支真的影片時（`probe_clip.mp4`：2 秒、320x180、H.264＋
  AAC，用 ffmpeg 的測試圖樣產生），改成**真的播放**並數解出來的畫格：
  `frames_decoded`、`first_frame`（寬x高）、`media_status`、`duration_ms`。
  `player_available` 為 False 代表多媒體後端根本沒載入。
  這是用來驗「拿掉某些 DLL 之後播放器還能不能動」——對不存在的檔案回報
  ResourceError 只證明後端載入了，證明不了真的解得出畫面。聲音設成靜音，
  CI 機器沒有音效裝置。

用法：`qt_probe.py <輸出的 JSON 路徑> [影片]`。沒給路徑（或給空字串）時
印到標準輸出。
"""
import json
import os
import sys
import time

T0 = time.perf_counter()


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else ""
    clip = sys.argv[2] if len(sys.argv) > 2 else ""

    t_import = time.perf_counter()
    from PySide6.QtCore import QTimer, QUrl, qVersion
    from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
    from PySide6.QtWidgets import QApplication, QMainWindow
    import_ms = (time.perf_counter() - t_import) * 1000

    app = QApplication(sys.argv[:1])
    win = QMainWindow()
    win.setWindowTitle("qt_probe")
    video = QVideoWidget()
    win.setCentralWidget(video)
    player = QMediaPlayer()
    audio = QAudioOutput()
    player.setAudioOutput(audio)
    player.setVideoOutput(video)
    win.resize(640, 360)

    result = {
        "qt_version": qVersion(),
        "python": sys.version.split()[0],
        "frozen": bool(getattr(sys, "frozen", False)),
        "import_ms": round(import_ms, 1),
        "audio_outputs": len(QMediaDevices.audioOutputs()),
        # 多媒體後端外掛沒載入時播放器是「不可用」，而且不會發出任何錯誤
        # 訊號——本機拿掉 Qt6Quick 時就是這樣，只看 player_error 會以為
        # 一切正常。--windowed 的 exe 沒有標準錯誤可收，只能靠這一格。
        "player_available": player.isAvailable(),
        "player_error": "",
    }

    def on_error(err, message):
        result["player_error"] = f"{err.name}: {message}"
    player.errorOccurred.connect(on_error)

    if clip:
        # 真的播放：從影片元件的 sink 數畫格。播到結尾（EndOfMedia）或
        # 等太久就收工。
        result.update({"clip": os.path.basename(clip), "frames_decoded": 0,
                       "first_frame": "", "media_status": "", "duration_ms": 0})

        def on_frame(frame):
            if frame.isValid():
                if not result["frames_decoded"]:
                    size = frame.size()
                    result["first_frame"] = f"{size.width()}x{size.height()}"
                    result["first_frame_ms"] = round(
                        (time.perf_counter() - T0) * 1000, 1)
                result["frames_decoded"] += 1

        def on_status(status):
            result["media_status"] = status.name
            if status == QMediaPlayer.MediaStatus.EndOfMedia:
                QTimer.singleShot(0, finish)

        video.videoSink().videoFrameChanged.connect(on_frame)
        player.mediaStatusChanged.connect(on_status)
        player.durationChanged.connect(
            lambda ms: result.__setitem__("duration_ms", ms))
        audio.setMuted(True)
        player.setSource(QUrl.fromLocalFile(os.path.abspath(clip)))
        player.play()
    else:
        # 給一個不存在的檔案：不需要測試影片，也能逼 Qt 真的去載入多媒體
        # 後端——後端缺了會是另一種錯誤（或完全沒反應），跟「找不到檔案」
        # 分得開。
        player.setSource(QUrl.fromLocalFile(os.path.abspath("__qt_probe_missing__.mp4")))

    done = []

    def finish():
        if done:
            return
        done.append(True)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if out_path:
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(text)
        else:
            print(text)
        app.quit()

    win.show()
    # 事件迴圈跑起來、第一個畫面畫完之後才記時間：singleShot(0) 排在
    # show() 產生的繪製事件後面。再多等 300ms 讓播放器的錯誤回報回來。
    QTimer.singleShot(0, lambda: result.__setitem__(
        "shown_ms", round((time.perf_counter() - T0) * 1000, 1)))
    # 播影片時最多等 15 秒（2 秒的片子正常播完就提早收工）。
    QTimer.singleShot(15000 if clip else 300, finish)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
