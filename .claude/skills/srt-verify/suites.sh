#!/bin/bash
# 跑兩套測試並數 PASS／FAIL／Traceback。先跑過 .claude/skills/srt-dev-env/setup.sh。
#   bash .claude/skills/srt-verify/suites.sh [記錄資料夾，預設 /tmp/srt-logs]
LOG="${1:-/tmp/srt-logs}"; mkdir -p "$LOG"
cd "$(git rev-parse --show-toplevel)"
DISPLAY=:99 xdpyinfo >/dev/null 2>&1 || { rm -f /tmp/.X99-lock; (setsid Xvfb :99 -screen 0 1600x1000x24 >/dev/null 2>&1 &); sleep 2; }
DISPLAY=:99 /tmp/vtk/bin/python3 tests/run_all.py > "$LOG/full.log" 2>&1; echo "一般版全套結束碼 $?"
: > "$LOG/qt.log"
for t in tests/test_qt_*.py; do
  FONTCONFIG_FILE="${FONTCONFIG_FILE:-/tmp/srt-fonts.conf}" QT_QPA_PLATFORM=offscreen timeout 400 \
    /tmp/qtv12/bin/python3 -B "$t" >> "$LOG/qt.log" 2>&1 || echo "QTFAIL $t"
done
echo "一般版：PASS $(grep -c '^PASS' "$LOG/full.log")  FAIL $(grep -c '^FAIL' "$LOG/full.log")  Traceback $(grep -c Traceback "$LOG/full.log")"
echo "Qt（$(ls tests/test_qt_*.py | wc -l) 檔）：PASS $(grep -c '^PASS' "$LOG/qt.log")  FAIL $(grep -c '^FAIL' "$LOG/qt.log")  Traceback $(grep -c Traceback "$LOG/qt.log")"
tail -1 "$LOG/full.log"
