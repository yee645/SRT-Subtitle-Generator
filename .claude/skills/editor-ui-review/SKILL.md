---
name: editor-ui-review
description: Design rules and review checklist for the SRT-Subtitle-Generator Qt editor layout (gui_qt/editor.py, theme.py, icons.py) — mainstream video-editor structure like CapCut/Premiere, design tokens from subtitle/designtokens.py, and a screenshot checklist for both themes. Use when building or changing any part of the editor UI, and when reviewing editor screenshots. If the hallmark design skill is available, use it alongside this.
---

# 剪輯器版面：設計規則與截圖檢查

規格全文：`docs/ROADMAP_EDITOR.md`（版面、色票、快捷鍵、E-0～E-7 階段）。這份是動手與檢查時的濃縮版。

## 結構（照主流剪輯軟體）

頂列（專案名稱、圖示按鈕、右上角唯一一顆主要按鈕〔匯出〕）｜左邊圖示列＋左側面板（媒體／字幕／智慧剪輯／健檢）｜
中間預覽＋播放控制｜右邊屬性｜下方整條時間軸＋工具列。預覽與時間軸是主角，說明文字放提示（tooltip）裡，不要整段攤在畫面上。

## 寫程式的規則

- **顏色只用名稱**：`theme.tokens(theme)["text.primary"]` 這種；新顏色先加進 `subtitle/designtokens.py` 的兩套色票（名稱一樣），
  需要配字的組合加進 `TEXT_PAIRS`（測試量 ≥ 4.5:1），再同步 `docs/ROADMAP_EDITOR.md` 的色表（`test_designtokens.py` 比對）。
- **不寫死樣式**：用 `objectName` 或 `setProperty("role", ...)`，樣式寫在 `gui_qt/theme.py` 的 `stylesheet()`。按鈕三種：
  `role="primary"`（一個畫面只有一顆）、一般、`role="ghost"`／QToolButton（圖示）。左側清單式按鈕用 `role="list"`。
- **圖示**自己畫在 `gui_qt/icons.py`（24 格、線條 1.6、只用 `currentColor`、不引用外部檔案或第三方圖示庫）；每顆圖示按鈕要有提示文字（含快捷鍵）。
- **不另寫一份功能**：新版面搬現有元件（`EditorWindow` 繼承 `MainWindow`）；搬過去的元件加進 `FEATURE_MAP`，
  換成新元件的加進 `REPLACED`。`test_qt_editor.py` 會確認舊外殼裡沒有剩下的按鈕。
- 間距 4／8／12／16／24，面板內距 12，圓角：控制項 6、面板 8、時間軸上的塊 4。

## 截圖檢查清單（深淺兩色都要過）

截圖方法見 `srt-verify` 技能第 3 節。逐張用 Read 看：

1. 有沒有字被截掉（按鈕、下拉選單、標籤）？窄的面板裡尤其注意。
2. 一個畫面是不是只有一顆強調色實心按鈕？
3. 文字看得清楚嗎（淺色主題的灰字、深色主題的停用字）？勾選框、下拉箭頭、捲軸看得到嗎？
4. 面板之間的層次：視窗底（`bg.window`）比面板（`bg.panel`）深／淺一階，縫隙一致。
5. 圖示顏色跟主題走（換主題後沒有殘留舊顏色），選取中的圖示用強調色。
6. 空狀態（還沒開影片）也看一次：有沒有說明下一步、按鈕是不是正確地停用。
7. 跟上一版的截圖並排比較，確認沒有意外的退步。

有 hallmark 設計技能可用時，拿它對同一批截圖再審一輪，結論與改了什麼記進 `docs/ROADMAP_EDITOR.md`。
