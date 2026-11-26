---
name: srt-dev-env
description: Rebuild the SRT-Subtitle-Generator dev/test environment in a fresh cloud container (ffmpeg, Xvfb, CJK fonts, Tk venv /tmp/vtk, PySide6 6.12 venv /tmp/qtv12). Use at the start of any session on this repo before running tests or taking Qt screenshots, or when a test fails because a tool, venv or font is missing.
---

# 開發環境（雲端容器）

容器重建後 venv、Xvfb、字型設定都不在。開工先跑：

```bash
bash .claude/skills/srt-dev-env/setup.sh
```

重複跑沒關係（已經有的就跳過）。建好之後：

| 用途 | 指令 |
|---|---|
| 一般版（Tk）全套 | `DISPLAY=:99 /tmp/vtk/bin/python3 tests/run_all.py` |
| 新介面（Qt）單一測試 | `FONTCONFIG_FILE=/tmp/srt-fonts.conf QT_QPA_PLATFORM=offscreen /tmp/qtv12/bin/python3 -B tests/test_qt_xxx.py` |
| Qt 截圖 | 同上的環境變數，見 `srt-verify` 技能 |

## 要記得的坑

- **Python 一律 3.12**。3.11＋PySide6 6.12.0 每呼叫一次沒有回傳值的 Qt 方法就把 None 的參照數多減一，用久了崩潰（`none_dealloc`），`tests/test_qt_none_refcount.py` 守著。
- **字型**：`fonts.conf` 把程式指定的「Microsoft JhengHei」換成容器裡有的 WenQuanYi Zen Hei，截圖的中文才不會是方塊。若 repo 已經有 `tests/fonts.conf`（`run_all.py` 會自動設 `FONTCONFIG_FILE`），單獨跑像素或版面測試時照 repo 的做法。
- **Whisper 模型檔與 pytorch.org 被出口政策擋 403**：不要繞過或重試，測試用假 whisper 模組。不要關 TLS 驗證、不要拿掉代理設定。
- gnu.org、download.qt.io、ffmpeg.org 被代理擋：不要繞。
- GitHub 的 CI 沒有 `PYTHONUNBUFFERED`、也不是 root；新測試別依賴這兩點（子程序 stdout 要自己 flush、不要寫系統資料夾）。
- 測試若會存設定，先把 `config.CONFIG_PATH` 指到暫存資料夾（不要動到專案根目錄的 config.json）。
