---
name: srt-verify
description: Verification checklist for SRT-Subtitle-Generator changes — run both test suites and count PASS/FAIL/Traceback, prove new tests catch bugs with destruction probes, and take dark+light Qt screenshots of the editor layout. Use before committing any change to this repo, and whenever a PR description needs test results.
---

# 驗證（缺一不可，做不到就照實講）

前提：先跑 `bash .claude/skills/srt-dev-env/setup.sh`。

## 1. 兩套測試

```bash
bash .claude/skills/srt-verify/suites.sh          # 約 10～15 分鐘，放背景跑
```

- 新測試一定要登記進 `tests/run_all.py` 的 `TESTS`。
- 結果要數三個數：PASS、FAIL、Traceback。FAIL 先拿 main 對照（`git stash` → 跑那一個 → `git stash pop`），確認是不是自己弄壞的。
- **既有斷言只能收緊**。行為刻意改變時，換成新行為的斷言，並在 PR 寫明；能保留舊斷言就保留（例如原始碼比對的那一行照原樣留著）。

## 2. 破壞探針（證明新測試真的抓得到）

寫一份 probes.json（放 scratchpad，不要放 repo），每一筆把程式改壞一處：

```json
[{"name": "no-widen", "file": "gui_qt/editor.py", "old": "if want > 0:", "new": "if False:",
  "test": "tests/test_qt_editor.py", "python": "qt"}]
```

```bash
python3 .claude/skills/srt-verify/probe.py /path/to/probes.json        # 全部
python3 .claude/skills/srt-verify/probe.py /path/to/probes.json no-widen # 只跑一個
```

腳本會備份、改、刪 `__pycache__`、用 `-B` 跑（上限 300 秒）、還原、確認已還原。`missed` 不是空的就補測試，再跑那一筆。
跑完 `git status` 確認沒有殘留的改動。

## 3. 介面截圖（介面改動一律要）

```bash
for t in dark light; do
  FONTCONFIG_FILE=/tmp/srt-fonts.conf QT_QPA_PLATFORM=offscreen \
    /tmp/qtv12/bin/python3 .claude/skills/srt-verify/shot_editor.py $t /tmp/shots/$t
done
```

每一張都用 Read 打開看，深淺兩色都看。照 `editor-ui-review` 技能的清單檢查。四頁籤的舊視窗要截圖時，照同一個腳本改用 `qt_app.MainWindow`、逐頁 `win.tabs.setCurrentIndex(i)`。

## 4. 能拿真實資料就不要編測資

測試影片與圖用 ffmpeg 產生（`testsrc2`、`sine`）。`research/qt_probe/probe_clip.mp4` 是 2 秒的現成片。
