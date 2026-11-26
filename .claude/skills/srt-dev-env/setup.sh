#!/bin/bash
# 重建 SRT-Subtitle-Generator 的開發與測試環境（雲端容器重建後跑一次；重複跑沒關係）。
#   bash .claude/skills/srt-dev-env/setup.sh
# 建好之後：
#   /tmp/vtk/bin/python3   一般版（Tk）全套用，DISPLAY=:99
#   /tmp/qtv12/bin/python3 新介面（PySide6 6.12.0，Python 3.12）用，QT_QPA_PLATFORM=offscreen
#   /tmp/srt-fonts.conf    Qt 截圖與像素測試用的字型設定（FONTCONFIG_FILE）
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV_TK="${VENV_TK:-/tmp/vtk}"
VENV_QT="${VENV_QT:-/tmp/qtv12}"

need=()
for pkg in ffmpeg x11-utils xvfb imagemagick fonts-wqy-zenhei python3-tk python3.12-venv; do
  dpkg -s "$pkg" >/dev/null 2>&1 || need+=("$pkg")
done
if [ ${#need[@]} -gt 0 ]; then
  echo "安裝系統套件：${need[*]}"
  (apt-get update -qq && apt-get install -y -qq "${need[@]}") || echo "⚠ apt 安裝失敗（${need[*]}），相關測試會跑不了"
fi

if [ ! -x "$VENV_TK/bin/python3" ]; then
  python3.12 -m venv --system-site-packages "$VENV_TK"
fi
"$VENV_TK/bin/python3" -c "import tkinter" || echo "⚠ $VENV_TK 沒有 tkinter"

if [ ! -x "$VENV_QT/bin/python3" ]; then
  python3.12 -m venv --system-site-packages "$VENV_QT"
fi
if ! "$VENV_QT/bin/python3" -c "import PySide6, sys; sys.exit(PySide6.__version__ != '6.12.0')" 2>/dev/null; then
  # 3.11＋PySide6 6.12 會把 None 的參照數多減（見 tests/test_qt_none_refcount.py），一律用 3.12
  "$VENV_QT/bin/pip" install -q "PySide6==6.12.0" || echo "⚠ PySide6 安裝失敗"
fi

cp "$HERE/fonts.conf" /tmp/srt-fonts.conf

if ! DISPLAY=:99 xdpyinfo >/dev/null 2>&1; then
  rm -f /tmp/.X99-lock
  (setsid Xvfb :99 -screen 0 1600x1000x24 >/dev/null 2>&1 &)
  sleep 2
fi

echo "---- 檢查 ----"
"$VENV_TK/bin/python3" --version
"$VENV_QT/bin/python3" -c "import PySide6; print('PySide6', PySide6.__version__)"
ffmpeg -version 2>/dev/null | head -1
DISPLAY=:99 xdpyinfo >/dev/null 2>&1 && echo "Xvfb :99 活著" || echo "⚠ Xvfb 沒起來"
