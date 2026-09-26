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

用法：`qt_probe.py <輸出的 JSON 路徑>`。沒給路徑時印到標準輸出。
"""
import json
import os
import sys
import time

T0 = time.perf_counter()


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else ""

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
        "player_error": "",
    }

    # 給一個不存在的檔案：不需要測試影片，也能逼 Qt 真的去載入多媒體後
    # 端——後端缺了會是另一種錯誤（或完全沒反應），跟「找不到檔案」分得開。
    def on_error(err, message):
        result["player_error"] = f"{err.name}: {message}"
    player.errorOccurred.connect(on_error)
    player.setSource(QUrl.fromLocalFile(os.path.abspath("__qt_probe_missing__.mp4")))

    def finish():
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
    QTimer.singleShot(300, finish)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
