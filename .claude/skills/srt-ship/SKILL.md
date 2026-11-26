---
name: srt-ship
description: House rules and the commit → PR → CI → squash-merge flow for yee645/SRT-Subtitle-Generator (branch claude/video-editing-workflow-irx149), including code-placement, privacy, versioning and blocked-host rules. Use when starting a work session on this repo, before committing, and when opening or merging a PR.
---

# 規則與發佈流程

## 程式放哪裡

- 核心邏輯放 `subtitle/`：**零 GUI 依賴、不 import `config`**。新檔加進 `tests/test_v1520.py` 的白名單並寫理由。
- 新介面（Qt）在 `gui_qt/`；剪輯器版面是 `gui_qt/editor.py`（E 系列，見 `docs/ROADMAP_EDITOR.md`）。一般版（Tk）在 `gui/`，只修錯。
- 搬功能或換版面：列「現有功能 → 新位置」對照表放 PR；剪輯器版面的對照表在 `gui_qt/editor.py` 的 `FEATURE_MAP`，測試逐項比對。

## 不能做的事

- 隱私「寧可漏翻、不可誤送」：會送到外部服務的動作，送出前寫明會送什麼。
- 只是新介面的進度，不動 `updater.py` 的 `APP_VERSION`、不寫 CHANGELOG 新版條目（發版那一階段才動）。
- `.github/promote_releases.txt` 的提交若被拒絕：不要重試或繞過，記下來收工。
- Whisper 模型檔、pytorch.org（403）、gnu.org、download.qt.io、ffmpeg.org 被擋：不要繞過或重試。不要關 TLS 驗證、不要拿掉代理設定。

## 流程

1. 開工：`git fetch origin main`；上一個 PR 已合併就 `git checkout -B claude/video-editing-workflow-irx149 origin/main`。
   `git config user.email noreply@anthropic.com`、`git config user.name Claude`。看 `git log` 與 ROADMAP 確認做到哪。
2. 做完一個小階段就 commit＋push，並把進度與下一步寫進對應的 ROADMAP（context 隨時會被壓縮，之後以 ROADMAP 與 git log 為準）。
3. 驗證照 `srt-verify` 技能。
4. 開**正式 PR（非草稿）**，描述用中文：做了什麼、對照表、還沒做的、驗證數字（PASS/FAIL/Traceback、探針、截圖）。
5. CI：
   - 動到 `gui_qt/**`、`packaging/**`、`qt-preview.yml` 的 PR 會跑 Windows 打包與自檢（約 3 分鐘）。
   - 有 `.github/workflows/tests.yml`（「Tests」）的話，每個 PR 都要等它綠燈（約 10～15 分鐘）。
   - 紅燈就看記錄、找到原因修好再推，不要帶著紅燈合併。
6. 綠燈後 squash 合併，帶完整的 `expectedHeadSha`；合併後 `git fetch origin main && git checkout -B <分支> origin/main && git push --force-with-lease`。
7. 收工：簡短中文總結（做了哪幾個階段、測試結果、CI、PR 連結、沒能實測的、下一步）。
