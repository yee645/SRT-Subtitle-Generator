# -*- coding: utf-8 -*-
"""
SRT 自動字幕生成與編輯桌面應用程式 - 程式進入點。

安裝相依套件（請於命令列執行）：
    pip install openai-whisper numpy
    pip install openai            # 僅在使用 OpenAI API 模式時需要
另需安裝 ffmpeg 並加入系統 PATH（音訊解碼與轉寫皆會用到）。

Tkinter 為 Python 標準函式庫，無須額外安裝。

執行方式：
    python main.py                         # 開啟 GUI
    python main.py 影片1.mp4 影片2.mp4     # 命令列批次：生成 → 匯出 → 燒錄（詳見 cli.py）
    python main.py --review 素材.mp4       # 命令列批次審片：輸出片段分析 CSV 與 HTML 報告
"""

import os
import sys

# 將專案根目錄加入模組搜尋路徑，確保 gui / subtitle 套件可被正確匯入。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # 帶參數時走命令列批次模式，直接跑「生成 → 匯出 → 燒錄」自動流程。
        from cli import main as cli_main
        sys.exit(cli_main())
    from gui.app import main
    main()
