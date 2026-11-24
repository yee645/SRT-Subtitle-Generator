# -*- coding: utf-8 -*-
"""
SRT 自動字幕生成與編輯桌面應用程式 - 程式進入點。

安裝相依套件（請於命令列執行）：
    pip install openai-whisper numpy
    pip install openai            # 僅在使用 OpenAI API 模式時需要
另需安裝 ffmpeg 並加入系統 PATH（音訊解碼與轉寫皆會用到）。

Tkinter 為 Python 標準函式庫，無須額外安裝。

執行方式：
    python main.py                         # 開啟 GUI：3.0.0 起是新介面（Qt）；沒有 PySide6 就開一般版
    python main.py --tk                    # 一般版（Tk）
    python main.py --qt                    # 一定開新介面（沒有 PySide6 會講怎麼裝）
    python main.py 影片1.mp4 影片2.mp4     # 命令列批次：生成 → 匯出 → 燒錄（詳見 cli.py）
    python main.py --review 素材.mp4       # 命令列批次審片：輸出片段分析 CSV 與 HTML 報告

打包好的一般版 exe（SRT-Subtitle-Generator.exe）沒有附 PySide6，雙擊照舊開一般版；新介面另外打包成資料夾
（packaging/qt_entry.py，SRT-Subtitle-Generator-Qt-*-win64.zip）。
"""

import os
import sys

# 將專案根目錄加入模組搜尋路徑，確保 gui / subtitle 套件可被正確匯入。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

QT_FLAG = "--qt"
TK_FLAG = "--tk"

QT_MISSING_TEXT = (
    "新介面（--qt）需要 PySide6，這個環境沒有：\n"
    "    pip install PySide6\n"
    "打包好的新介面是 Releases 上的 SRT-Subtitle-Generator-Qt-…-win64.zip；加 --tk 或直接執行一般版的 exe 是一般版。"
)


def load_qt_main():
    """
    匯入新介面的進入點；PySide6／gui_qt 本身不存在時回 None（沒帶參數時就改開一般版）。

    只把「PySide6／gui_qt 本身不存在」當成沒裝；gui_qt 內部的其他 ImportError 是程式錯誤，照樣丟出來。
    打包好的一般版 exe 排除了 PySide6 與 gui_qt（SRT-Subtitle-Generator.spec），一定走回 None。
    """
    try:
        from gui_qt.app import main as qt_main
    except ImportError as exc:
        if (exc.name or "").split(".")[0] not in ("PySide6", "shiboken6", "gui_qt"):
            raise
        return None
    return qt_main


def run_default(argv):
    """沒帶參數時：有新介面就開新介面（3.0.0 起的預設），沒有就照舊開一般版。回傳結束碼。"""
    qt_main = load_qt_main()
    if qt_main is not None:
        return qt_main(argv)
    from gui.app import main as tk_main
    tk_main()
    return 0


def run_qt(argv):
    """
    一定開新介面（--qt）。沒有 PySide6（或 exe 沒打包 gui_qt）時講清楚並回傳 2。

    只把「PySide6／gui_qt 本身不存在」當成沒裝；gui_qt 內部的其他
    ImportError 是程式錯誤，照樣丟出來，不能被包裝成「請安裝」。
    """
    qt_main = load_qt_main()
    if qt_main is None:
        print(QT_MISSING_TEXT, file=sys.stderr)
        try:
            # 視窗版 exe 沒有主控台，stderr 看不到；能開 Tk 就用對話框講。
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo("新介面", QT_MISSING_TEXT, parent=root)
            root.destroy()
        except Exception:  # noqa: BLE001 —— 沒有顯示器時 stderr 那行就夠了
            pass
        return 2
    return qt_main(argv)


if __name__ == "__main__":
    if QT_FLAG in sys.argv[1:]:
        # 放在命令列批次判斷前面：否則 --qt 會被當成影片檔名丟給 cli。
        sys.exit(run_qt([a for a in sys.argv if a != QT_FLAG]))
    if sys.argv[1:] == [TK_FLAG]:
        # 一般版（3.0.0 起要指名）。只認單獨的 --tk：跟影片檔一起給就照舊是命令列批次（cli 會講不認得的參數）。
        from gui.app import main
        main()
        sys.exit(0)
    if len(sys.argv) > 1:
        # 帶參數時走命令列批次模式，直接跑「生成 → 匯出 → 燒錄」自動流程。
        from cli import main as cli_main
        sys.exit(cli_main())
    sys.exit(run_default(sys.argv[:1]))
