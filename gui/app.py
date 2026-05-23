# -*- coding: utf-8 -*-
"""
SRT 自動字幕生成與編輯應用程式 - 主視窗。

整合：模式切換（含手動字幕模式）、檔案選擇、轉寫設定、字幕生成、即時預覽、
視覺調整面板、多格式字幕匯出（SRT/VTT/ASS/TXT）、影片字幕燒錄（hardsub），
以及設定檔的載入與自動儲存（記憶功能）。
"""

import logging
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from config import load_config, make_profile, save_config
from updater import (APP_VERSION, check_for_update, cleanup_old_version,
                     download_and_apply)
from subtitle.aligner import align_transcript
from subtitle.burner import burn_subtitles, ffmpeg_available
from subtitle.exporter import FORMAT_FILETYPES, export, format_srt_timestamp
from subtitle.segmenter import build_cues_from_words
from subtitle.transcriber import transcribe
from gui.cue_editor import CueEditDialog
from gui.preview_panel import PreviewPanel
from gui.scrollable import ScrollableFrame
from gui.style_panel import StylePanel

logger = logging.getLogger(__name__)

# 支援的影音檔副檔名（檔案選擇器用）。
MEDIA_FILETYPES = [
    ("影片與音訊檔", "*.mp4 *.mkv *.mov *.avi *.flv *.mp3 *.wav *.m4a *.aac *.ogg"),
    ("所有檔案", "*.*"),
]
# 模式識別字串。
MODE_TRANSCRIBE = "transcribe"
MODE_ALIGN = "align"
MODE_MANUAL = "manual"


class SrtApp(tk.Tk):
    """應用程式主視窗。"""

    def __init__(self):
        super().__init__()
        self.title(f"SRT 自動字幕生成與編輯工具 v{APP_VERSION}")
        self.geometry("1180x780")
        self.minsize(820, 520)

        # 載入設定檔，達成記憶功能。
        self.config_data = load_config()
        # 生成結果（cue 清單）與背景執行緒通訊佇列。
        self.cues = []
        self.result_queue = queue.Queue()
        self.is_processing = False

        self._build_widgets()
        self._update_mode_state()
        self._refresh_preview()
        # 啟動背景佇列輪詢。
        self.after(120, self._poll_queue)
        # 關閉視窗時先存檔。
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # 清除上次更新遺留的舊檔，並於背景檢查是否有新版本。
        cleanup_old_version()
        self.after(1500, self._start_update_check)

    # ==================================================================
    # 介面建構
    # ==================================================================
    def _build_widgets(self):
        """建立整體版面。"""
        scroll = ScrollableFrame(self)
        scroll.pack(fill="both", expand=True)
        container = scroll.interior

        left = tk.Frame(container, padx=10, pady=10)
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(container, padx=10, pady=10)
        right.pack(side="right", fill="y")

        self._build_mode_section(left)
        self._build_file_section(left)
        self._build_transcription_section(left)
        self._build_segmentation_section(left)
        self._build_transcript_section(left)
        self._build_action_section(left)
        self._build_cue_list(left)
        self._build_cue_edit_controls(left)
        self._build_export_section(left)

        self._build_preset_section(right)
        self._build_preview_section(right)
        self._build_style_section(right)

    def _build_mode_section(self, parent):
        """模式切換區。"""
        frame = tk.LabelFrame(parent, text="運作模式", padx=10, pady=6)
        frame.pack(fill="x", pady=(0, 8))
        self.mode_var = tk.StringVar(value=MODE_TRANSCRIBE)
        tk.Radiobutton(
            frame, text="模式一：音訊轉錄（自動產生逐字稿與時間軸）",
            variable=self.mode_var, value=MODE_TRANSCRIBE,
            command=self._update_mode_state,
        ).pack(anchor="w")
        tk.Radiobutton(
            frame, text="模式二：文字稿對齊（貼上現成文字稿，自動對齊時間軸）",
            variable=self.mode_var, value=MODE_ALIGN,
            command=self._update_mode_state,
        ).pack(anchor="w")
        tk.Radiobutton(
            frame, text="模式三：手動字幕模式（從零建立字幕、手動標記時間）",
            variable=self.mode_var, value=MODE_MANUAL,
            command=self._update_mode_state,
        ).pack(anchor="w")

    def _build_file_section(self, parent):
        """檔案選擇區。"""
        frame = tk.LabelFrame(parent, text="影片 / 音訊檔案", padx=10, pady=6)
        frame.pack(fill="x", pady=(0, 8))
        self.file_var = tk.StringVar()
        tk.Entry(frame, textvariable=self.file_var).pack(
            side="left", fill="x", expand=True, padx=(0, 6))
        tk.Button(frame, text="瀏覽...", command=self._choose_file).pack(side="left")

    def _build_transcription_section(self, parent):
        """轉寫設定區（模式一相關）。"""
        frame = tk.LabelFrame(parent, text="轉寫設定（模式一）", padx=10, pady=6)
        frame.pack(fill="x", pady=(0, 8))
        self.transcription_frame = frame
        transcription_cfg = self.config_data["transcription"]

        row1 = tk.Frame(frame)
        row1.pack(fill="x", pady=2)
        tk.Label(row1, text="本地模型:").pack(side="left")
        self.model_var = tk.StringVar(value=transcription_cfg["model"])
        ttk.Combobox(
            row1, textvariable=self.model_var, width=10, state="readonly",
            values=["tiny", "base", "small", "medium", "large"],
        ).pack(side="left", padx=(0, 12))
        tk.Label(row1, text="語言:").pack(side="left")
        self.language_var = tk.StringVar(value=transcription_cfg["language"])
        ttk.Combobox(
            row1, textvariable=self.language_var, width=10,
            values=["auto", "zh", "zh-TW", "en", "ja", "ko"],
        ).pack(side="left")

        row2 = tk.Frame(frame)
        row2.pack(fill="x", pady=2)
        self.use_api_var = tk.BooleanVar(value=transcription_cfg["use_api"])
        tk.Checkbutton(
            row2, text="改用 OpenAI API", variable=self.use_api_var,
        ).pack(side="left")
        tk.Label(row2, text="API 金鑰:").pack(side="left", padx=(8, 0))
        self.api_key_var = tk.StringVar(value=transcription_cfg["api_key"])
        tk.Entry(
            row2, textvariable=self.api_key_var, show="*", width=30,
        ).pack(side="left", fill="x", expand=True)

        row3 = tk.Frame(frame)
        row3.pack(fill="x", pady=2)
        tk.Label(row3, text="本地 Python:").pack(side="left")
        self.python_path_var = tk.StringVar(
            value=transcription_cfg.get("python_path", ""))
        tk.Entry(
            row3, textvariable=self.python_path_var,
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        tk.Button(
            row3, text="瀏覽...", command=self._choose_python,
        ).pack(side="left")
        tk.Label(
            frame, fg="#666666",
            text="留空則自動偵測；指向已安裝 openai-whisper 的 python.exe 即可使用本地轉錄。",
        ).pack(anchor="w", pady=(2, 0))

        row4 = tk.Frame(frame)
        row4.pack(fill="x", pady=(6, 2))
        tk.Label(row4, text="轉寫提示:").pack(side="left")
        self.prompt_var = tk.StringVar(
            value=transcription_cfg.get("prompt", ""))
        tk.Entry(
            row4, textvariable=self.prompt_var,
        ).pack(side="left", fill="x", expand=True)
        tk.Label(
            frame, fg="#666666",
            text=("可填入常出現的專有名詞、人名或易聽錯的詞彙（以空白或逗號分隔），"
                  "用於導正辨識結果。模式二會與文字稿一併使用。"),
        ).pack(anchor="w", pady=(2, 0))

    def _build_segmentation_section(self, parent):
        """斷句設定區。"""
        frame = tk.LabelFrame(parent, text="斷句設定", padx=10, pady=6)
        frame.pack(fill="x", pady=(0, 8))
        self.segmentation_frame = frame
        seg = self.config_data["segmentation"]

        row1 = tk.Frame(frame)
        row1.pack(fill="x", pady=2)
        tk.Label(row1, text="中文單行上限:").pack(side="left")
        self.cjk_limit_var = tk.IntVar(value=seg["max_chars_cjk"])
        tk.Spinbox(
            row1, from_=4, to=40, width=6, textvariable=self.cjk_limit_var,
        ).pack(side="left", padx=(0, 4))
        tk.Label(row1, text="字").pack(side="left", padx=(0, 14))
        tk.Label(row1, text="英文單行上限:").pack(side="left")
        self.latin_limit_var = tk.IntVar(value=seg["max_chars_latin"])
        tk.Spinbox(
            row1, from_=10, to=90, width=6, textvariable=self.latin_limit_var,
        ).pack(side="left", padx=(0, 4))
        tk.Label(row1, text="字母").pack(side="left")

        row2 = tk.Frame(frame)
        row2.pack(fill="x", pady=2)
        tk.Label(row2, text="最短秒數:").pack(side="left")
        self.min_dur_var = tk.DoubleVar(value=seg["min_duration"])
        tk.Spinbox(
            row2, from_=0.3, to=5.0, increment=0.1, width=5,
            textvariable=self.min_dur_var, format="%.1f",
        ).pack(side="left", padx=(0, 12))
        tk.Label(row2, text="最長秒數:").pack(side="left")
        self.max_dur_var = tk.DoubleVar(value=seg["max_duration"])
        tk.Spinbox(
            row2, from_=2.0, to=15.0, increment=0.5, width=5,
            textvariable=self.max_dur_var, format="%.1f",
        ).pack(side="left", padx=(0, 12))
        tk.Label(row2, text="停頓秒數:").pack(side="left")
        self.pause_gap_var = tk.DoubleVar(value=seg["pause_gap"])
        tk.Spinbox(
            row2, from_=0.2, to=2.0, increment=0.1, width=5,
            textvariable=self.pause_gap_var, format="%.1f",
        ).pack(side="left")

        row3 = tk.Frame(frame)
        row3.pack(fill="x", pady=2)
        tk.Label(row3, text="時間軸微調:").pack(side="left")
        self.time_offset_var = tk.DoubleVar(value=seg.get("time_offset", 0.0))
        tk.Spinbox(
            row3, from_=-10.0, to=10.0, increment=0.1, width=6,
            textvariable=self.time_offset_var, format="%.1f",
        ).pack(side="left", padx=(0, 4))
        tk.Label(
            row3, text="秒（正值整體延後、負值整體提前）", fg="#666666",
        ).pack(side="left")

    def _build_transcript_section(self, parent):
        """文字稿輸入區（模式二相關）。"""
        frame = tk.LabelFrame(parent, text="文字稿（模式二）", padx=10, pady=6)
        frame.pack(fill="both", pady=(0, 8))
        self.transcript_frame = frame
        self.transcript_text = tk.Text(frame, height=6, wrap="word")
        self.transcript_text.pack(fill="both", expand=True)
        hint = "請於此貼上現成逐字稿，系統會依語音長度與停頓自動分配時間軸。"
        tk.Label(frame, text=hint, fg="#666666").pack(anchor="w", pady=(4, 0))

    def _build_action_section(self, parent):
        """生成 / 匯出 / 燒錄按鈕與狀態列。"""
        frame = tk.Frame(parent)
        frame.pack(fill="x", pady=(0, 8))
        self.action_frame = frame
        self.generate_btn = tk.Button(
            frame, text="開始生成字幕", width=16, command=self._on_generate,
        )
        self.generate_btn.pack(side="left")

        self.progress = ttk.Progressbar(frame, mode="indeterminate", length=160)
        self.progress.pack(side="left", padx=6)

        self.status_var = tk.StringVar(value="就緒。")
        tk.Label(parent, textvariable=self.status_var, fg="#1a5fb4",
                 anchor="w").pack(fill="x")

    def _build_cue_list(self, parent):
        """字幕清單（生成結果）。"""
        frame = tk.LabelFrame(parent, text="字幕清單（雙擊可編輯）", padx=6, pady=6)
        frame.pack(fill="both", expand=True, pady=(8, 0))

        columns = ("index", "time", "text")
        self.cue_tree = ttk.Treeview(
            frame, columns=columns, show="headings", height=8,
        )
        self.cue_tree.heading("index", text="#")
        self.cue_tree.heading("time", text="時間")
        self.cue_tree.heading("text", text="字幕內容")
        self.cue_tree.column("index", width=40, anchor="center")
        self.cue_tree.column("time", width=180, anchor="center")
        self.cue_tree.column("text", width=320, anchor="w")

        scrollbar = ttk.Scrollbar(
            frame, orient="vertical", command=self.cue_tree.yview)
        self.cue_tree.configure(yscrollcommand=scrollbar.set)
        self.cue_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.cue_tree.bind("<<TreeviewSelect>>", self._on_cue_selected)
        # 雙擊任一列即進入編輯對話框。
        self.cue_tree.bind("<Double-1>", self._on_cue_double_click)

    def _build_cue_edit_controls(self, parent):
        """字幕列操作按鈕：新增、編輯、刪除、上移、下移、清空。"""
        frame = tk.Frame(parent)
        frame.pack(fill="x", pady=(4, 0))
        self.cue_edit_frame = frame
        tk.Button(frame, text="新增字幕", width=10,
                  command=self._on_add_cue).pack(side="left", padx=2)
        tk.Button(frame, text="編輯選取", width=10,
                  command=self._on_edit_cue).pack(side="left", padx=2)
        tk.Button(frame, text="刪除選取", width=10,
                  command=self._on_delete_cue).pack(side="left", padx=2)
        tk.Button(frame, text="上移", width=6,
                  command=lambda: self._on_move_cue(-1)).pack(side="left", padx=2)
        tk.Button(frame, text="下移", width=6,
                  command=lambda: self._on_move_cue(1)).pack(side="left", padx=2)
        tk.Button(frame, text="清空清單", width=10,
                  command=self._on_clear_cues).pack(side="left", padx=2)

    def _build_export_section(self, parent):
        """匯出與燒錄區：多格式匯出與影片字幕燒錄。"""
        frame = tk.LabelFrame(parent, text="匯出與燒錄", padx=10, pady=6)
        frame.pack(fill="x", pady=(8, 0))
        self.export_frame = frame

        self.export_btn_srt = tk.Button(
            frame, text="匯出 SRT", width=11,
            command=lambda: self._on_export(".srt"), state="disabled",
        )
        self.export_btn_srt.pack(side="left", padx=2)
        self.export_btn_vtt = tk.Button(
            frame, text="匯出 VTT", width=11,
            command=lambda: self._on_export(".vtt"), state="disabled",
        )
        self.export_btn_vtt.pack(side="left", padx=2)
        self.export_btn_ass = tk.Button(
            frame, text="匯出 ASS", width=11,
            command=lambda: self._on_export(".ass"), state="disabled",
        )
        self.export_btn_ass.pack(side="left", padx=2)
        self.export_btn_txt = tk.Button(
            frame, text="匯出 TXT", width=11,
            command=lambda: self._on_export(".txt"), state="disabled",
        )
        self.export_btn_txt.pack(side="left", padx=2)
        self.burn_btn = tk.Button(
            frame, text="燒錄字幕到影片", width=16,
            command=self._on_burn, state="disabled",
        )
        self.burn_btn.pack(side="left", padx=(8, 2))

    def _build_preview_section(self, parent):
        """即時字幕預覽。"""
        frame = tk.LabelFrame(parent, text="即時字幕預覽", padx=8, pady=8)
        frame.pack(fill="x")
        self.preview = PreviewPanel(frame)
        self.preview.pack()

    def _build_style_section(self, parent):
        """字幕視覺調整面板。"""
        self.style_panel = StylePanel(
            parent, self.config_data["subtitle_style"], self._on_style_change,
        )
        self.style_panel.pack(fill="x", pady=(10, 0))

    def _build_preset_section(self, parent):
        """習慣設定區。"""
        frame = tk.LabelFrame(parent, text="習慣設定（樣式組合）", padx=8, pady=6)
        frame.pack(fill="x", pady=(0, 8))

        row = tk.Frame(frame)
        row.pack(fill="x")
        tk.Label(row, text="目前樣式:").pack(side="left")
        self.preset_var = tk.StringVar(value=self.config_data["active_preset"])
        self.preset_box = ttk.Combobox(
            row, textvariable=self.preset_var, state="readonly", width=16,
            values=sorted(self.config_data["presets"].keys()),
        )
        self.preset_box.pack(side="left", padx=(0, 6))
        self.preset_box.bind(
            "<<ComboboxSelected>>", lambda _e: self._apply_preset())

        btn_row = tk.Frame(frame)
        btn_row.pack(fill="x", pady=(6, 0))
        tk.Button(
            btn_row, text="另存新樣式", command=self._save_new_preset,
        ).pack(side="left", padx=(0, 4))
        tk.Button(
            btn_row, text="更新目前樣式", command=self._update_preset,
        ).pack(side="left", padx=4)
        tk.Button(
            btn_row, text="刪除", command=self._delete_preset,
        ).pack(side="left", padx=4)

    # ==================================================================
    # 模式與預覽
    # ==================================================================
    def _update_mode_state(self):
        """依目前模式只顯示該模式需要調整的設定區塊。"""
        mode = self.mode_var.get()
        # 三模式皆隱藏所有可變區塊後，再依模式顯示需要的。
        self.transcription_frame.pack_forget()
        self.transcript_frame.pack_forget()

        if mode == MODE_TRANSCRIBE:
            self.transcription_frame.pack(
                fill="x", pady=(0, 8), before=self.segmentation_frame)
            self.generate_btn.configure(text="開始生成字幕")
        elif mode == MODE_ALIGN:
            self.transcript_frame.pack(
                fill="both", pady=(0, 8), before=self.action_frame)
            self.generate_btn.configure(text="開始生成字幕")
        else:
            # 手動模式：不需轉寫與文字稿，按鈕改為提示直接編輯字幕清單。
            self.generate_btn.configure(text="清空並進入手動編輯")

    def _on_style_change(self, style):
        """樣式面板變動時：更新設定、即時存檔、重繪預覽。"""
        self.config_data["subtitle_style"] = style
        self._save_config_silently()
        self.preview.update_style(style)

    def _refresh_preview(self):
        """以目前選取字幕（或範例文字）重繪預覽。"""
        style = self.config_data["subtitle_style"]
        text = self._current_preview_text()
        self.preview.render(text, style)

    def _current_preview_text(self):
        """取得目前要預覽的文字。"""
        selection = self.cue_tree.selection() if hasattr(self, "cue_tree") else ()
        if selection:
            item = self.cue_tree.item(selection[0])
            return item["values"][2]
        return "字幕預覽範例文字"

    def _on_cue_selected(self, _event):
        """字幕清單選取變動時更新預覽。"""
        self._refresh_preview()

    def _on_cue_double_click(self, _event):
        """雙擊字幕列：直接開啟編輯對話框。"""
        self._on_edit_cue()

    # ==================================================================
    # 字幕列編輯（模式三主要使用，其他模式也可用以微調）
    # ==================================================================
    def _on_add_cue(self):
        """新增一筆空白字幕；時間預設接在最後一句之後。"""
        if self.cues:
            last_end = max(cue["end"] for cue in self.cues)
            start = last_end + 0.5
        else:
            start = 0.0
        cue = {"start": start, "end": start + 2.0, "text": ""}
        dialog = CueEditDialog(self, cue, title="新增字幕")
        if dialog.result is None:
            return
        new_cue = dialog.result
        self.cues.append(new_cue)
        self._sort_and_repopulate(select_text=new_cue["text"])
        self._update_export_state()
        self.status_var.set("已新增字幕。")

    def _on_edit_cue(self):
        """編輯目前選取的字幕。"""
        index = self._selected_cue_index()
        if index is None:
            return
        dialog = CueEditDialog(self, self.cues[index], title="編輯字幕")
        if dialog.result is None:
            return
        self.cues[index] = dialog.result
        self._sort_and_repopulate(select_text=self.cues[index]["text"])
        self.status_var.set("已更新字幕。")

    def _on_delete_cue(self):
        """刪除選取的字幕。"""
        index = self._selected_cue_index()
        if index is None:
            return
        if not messagebox.askyesno("確認刪除", "確定刪除此字幕？"):
            return
        del self.cues[index]
        self._sort_and_repopulate()
        self._update_export_state()
        self.status_var.set("已刪除字幕。")

    def _on_move_cue(self, direction):
        """上移 / 下移目前選取的字幕（不改變時間，僅調整清單順序）。"""
        index = self._selected_cue_index()
        if index is None:
            return
        target = index + direction
        if target < 0 or target >= len(self.cues):
            return
        self.cues[index], self.cues[target] = self.cues[target], self.cues[index]
        # 移動後保留選取在原本字幕上。
        self._populate_cue_list(self.cues)
        children = self.cue_tree.get_children()
        if 0 <= target < len(children):
            self.cue_tree.selection_set(children[target])
            self.cue_tree.focus(children[target])
        self._refresh_preview()

    def _on_clear_cues(self):
        """清空字幕清單。"""
        if not self.cues:
            return
        if not messagebox.askyesno("確認清空", "確定清空所有字幕？"):
            return
        self.cues = []
        self._populate_cue_list([])
        self._update_export_state()
        self.status_var.set("已清空字幕清單。")

    def _selected_cue_index(self):
        """取得選取項目對應到 self.cues 的索引；無選取則回傳 None。"""
        selection = self.cue_tree.selection()
        if not selection:
            messagebox.showinfo("提示", "請先在字幕清單中選取一列。")
            return None
        children = self.cue_tree.get_children()
        try:
            return children.index(selection[0])
        except ValueError:
            return None

    def _sort_and_repopulate(self, select_text=None):
        """依開始時間排序 self.cues 後重新填入清單，可選取特定字幕。"""
        self.cues.sort(key=lambda cue: cue["start"])
        for number, cue in enumerate(self.cues, start=1):
            cue["index"] = number
        self._populate_cue_list(self.cues)
        if select_text is not None:
            for item, cue in zip(self.cue_tree.get_children(), self.cues):
                if cue["text"] == select_text:
                    self.cue_tree.selection_set(item)
                    self.cue_tree.focus(item)
                    break
        self._refresh_preview()

    # ==================================================================
    # 習慣設定（preset）管理
    # ==================================================================
    def _current_profile(self):
        """收集介面上目前的字幕樣式與斷句設定。"""
        self.config_data["subtitle_style"] = self.style_panel.get_style()
        self._collect_segmentation_config()
        return make_profile(
            self.config_data["subtitle_style"],
            self.config_data["segmentation"],
        )

    def _load_segmentation_into_ui(self):
        """把 config_data 中的斷句設定回填到斷句設定區的控制項。"""
        seg = self.config_data["segmentation"]
        self.cjk_limit_var.set(seg["max_chars_cjk"])
        self.latin_limit_var.set(seg["max_chars_latin"])
        self.min_dur_var.set(seg["min_duration"])
        self.max_dur_var.set(seg["max_duration"])
        self.pause_gap_var.set(seg["pause_gap"])
        self.time_offset_var.set(seg.get("time_offset", 0.0))

    def _refresh_preset_box(self, selected):
        """重新整理習慣設定下拉選單並選取指定名稱。"""
        self.preset_box.configure(
            values=sorted(self.config_data["presets"].keys()))
        self.preset_var.set(selected)

    def _apply_preset(self):
        """套用下拉選單中選取的習慣設定。"""
        name = self.preset_var.get()
        preset = self.config_data["presets"].get(name)
        if not preset:
            return
        self.config_data["subtitle_style"] = dict(preset["subtitle_style"])
        self.config_data["segmentation"] = dict(preset["segmentation"])
        self.config_data["active_preset"] = name
        self.style_panel.set_style(self.config_data["subtitle_style"])
        self._load_segmentation_into_ui()
        self.preview.update_style(self.config_data["subtitle_style"])
        self._refresh_preview()
        self._save_config_silently()
        self.status_var.set(f"已套用習慣設定：{name}")

    def _save_new_preset(self):
        """以目前介面設定另存為一組新的習慣設定。"""
        name = simpledialog.askstring(
            "另存新樣式", "請輸入樣式名稱:", parent=self)
        if name is None:
            return
        name = name.strip()
        if not name:
            messagebox.showwarning("提示", "樣式名稱不可為空白。")
            return
        if name in self.config_data["presets"]:
            if not messagebox.askyesno(
                    "確認覆蓋", f"樣式「{name}」已存在，要覆蓋嗎？"):
                return
        self.config_data["presets"][name] = self._current_profile()
        self.config_data["active_preset"] = name
        self._refresh_preset_box(name)
        self._save_config_silently()
        self.status_var.set(f"已儲存習慣設定：{name}")

    def _update_preset(self):
        """以目前介面設定更新下拉選單中選取的習慣設定。"""
        name = self.preset_var.get()
        if name not in self.config_data["presets"]:
            return
        self.config_data["presets"][name] = self._current_profile()
        self._save_config_silently()
        self.status_var.set(f"已更新習慣設定：{name}")

    def _delete_preset(self):
        """刪除選取的習慣設定（至少保留一組）。"""
        name = self.preset_var.get()
        presets = self.config_data["presets"]
        if name not in presets:
            return
        if len(presets) <= 1:
            messagebox.showinfo("提示", "至少需保留一組習慣設定，無法刪除。")
            return
        if not messagebox.askyesno("確認刪除", f"確定要刪除習慣設定「{name}」？"):
            return
        del presets[name]
        fallback = sorted(presets.keys())[0]
        self._refresh_preset_box(fallback)
        self._apply_preset()
        self.status_var.set(f"已刪除習慣設定：{name}")

    # ==================================================================
    # 字幕生成流程
    # ==================================================================
    def _choose_file(self):
        """開啟檔案選擇器。"""
        initial_dir = self.config_data.get("last_dir") or os.getcwd()
        path = filedialog.askopenfilename(
            title="選擇影片或音訊檔", initialdir=initial_dir,
            filetypes=MEDIA_FILETYPES,
        )
        if path:
            self.file_var.set(path)
            self.config_data["last_dir"] = os.path.dirname(path)
            self._save_config_silently()

    def _choose_python(self):
        """選擇外部 Python 直譯器（供本地轉錄使用）。"""
        path = filedialog.askopenfilename(
            title="選擇已安裝 whisper 的 python.exe",
            filetypes=[("Python 執行檔", "python*.exe"), ("所有檔案", "*.*")],
        )
        if path:
            self.python_path_var.set(path)

    def _collect_transcription_config(self):
        """把介面上的轉寫設定寫回設定資料並存檔。"""
        self.config_data["transcription"] = {
            "model": self.model_var.get(),
            "language": self.language_var.get().strip() or "auto",
            "use_api": bool(self.use_api_var.get()),
            "api_key": self.api_key_var.get().strip(),
            "python_path": self.python_path_var.get().strip(),
            "prompt": self.prompt_var.get().strip(),
        }
        self._save_config_silently()

    def _collect_segmentation_config(self):
        """把介面上的斷句設定寫回設定資料並存檔，數值不合理時做夾限校正。"""
        seg = dict(self.config_data["segmentation"])

        def safe_get(var, fallback):
            try:
                return var.get()
            except (tk.TclError, ValueError):
                return fallback

        cjk = int(safe_get(self.cjk_limit_var, seg["max_chars_cjk"]))
        latin = int(safe_get(self.latin_limit_var, seg["max_chars_latin"]))
        min_dur = float(safe_get(self.min_dur_var, seg["min_duration"]))
        max_dur = float(safe_get(self.max_dur_var, seg["max_duration"]))
        pause = float(safe_get(self.pause_gap_var, seg["pause_gap"]))
        offset = float(safe_get(self.time_offset_var, seg.get("time_offset", 0.0)))

        seg["max_chars_cjk"] = max(4, min(cjk, 40))
        seg["max_chars_latin"] = max(10, min(latin, 90))
        seg["min_duration"] = max(0.3, min(min_dur, max_dur))
        seg["max_duration"] = max(seg["min_duration"], min(max_dur, 15.0))
        seg["pause_gap"] = max(0.2, min(pause, 2.0))
        seg["time_offset"] = max(-10.0, min(offset, 10.0))

        self.config_data["segmentation"] = seg
        self._save_config_silently()

    def _on_generate(self):
        """按下「開始生成字幕」（模式三則為清空進入手動編輯）。"""
        if self.is_processing:
            return
        mode = self.mode_var.get()

        if mode == MODE_MANUAL:
            # 模式三：清空現有清單並進入手動編輯流程。
            if self.cues and not messagebox.askyesno(
                    "確認清空", "進入手動編輯會清空目前字幕清單，繼續嗎？"):
                return
            self.cues = []
            self._populate_cue_list([])
            self._collect_segmentation_config()
            self._update_export_state()
            self.status_var.set(
                "已進入手動字幕模式，請按「新增字幕」開始建立字幕。")
            return

        audio_path = self.file_var.get().strip()
        if not audio_path or not os.path.exists(audio_path):
            messagebox.showerror("錯誤", "請先選擇有效的影片或音訊檔案。")
            return

        transcript = ""
        if mode == MODE_ALIGN:
            transcript = self.transcript_text.get("1.0", "end").strip()
            if not transcript:
                messagebox.showerror("錯誤", "模式二需要先貼上文字稿。")
                return

        self._collect_transcription_config()
        self._collect_segmentation_config()

        self._set_processing(True)
        worker = threading.Thread(
            target=self._generate_worker,
            args=(mode, audio_path, transcript),
            daemon=True,
        )
        worker.start()

    def _generate_worker(self, mode, audio_path, transcript):
        """背景執行緒：實際進行轉寫或對齊。"""
        try:
            def report(message):
                self.result_queue.put(("status", message))

            if mode == MODE_TRANSCRIBE:
                words = transcribe(audio_path, self.config_data, report)
                report("正在進行智慧斷句...")
                cues = build_cues_from_words(
                    words, self.config_data["segmentation"])
            else:
                cues = align_transcript(
                    audio_path, transcript, self.config_data, report)

            if not cues:
                raise RuntimeError("未能產生任何字幕內容。")
            self.result_queue.put(("done", cues))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("生成字幕時發生錯誤")
            self.result_queue.put(("error", str(exc)))

    def _poll_queue(self):
        """主執行緒定時輪詢背景結果。"""
        try:
            while True:
                kind, payload = self.result_queue.get_nowait()
                if kind == "status":
                    self.status_var.set(payload)
                elif kind == "done":
                    self._on_generation_done(payload)
                elif kind == "error":
                    self._on_generation_error(payload)
                elif kind == "burn_done":
                    self._on_burn_done(payload)
                elif kind == "burn_error":
                    self._on_burn_error(payload)
                elif kind == "update":
                    self._prompt_update(payload)
                elif kind == "update_done":
                    self._on_update_done()
                elif kind == "update_error":
                    self._on_update_error(payload)
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

    def _on_generation_done(self, cues):
        """生成成功：填入字幕清單。"""
        self.cues = cues
        self._populate_cue_list(cues)
        self._set_processing(False)
        self.status_var.set(f"生成完成，共 {len(cues)} 句字幕。")
        self._update_export_state()
        children = self.cue_tree.get_children()
        if children:
            self.cue_tree.selection_set(children[0])
            self.cue_tree.focus(children[0])
        self._refresh_preview()

    def _on_generation_error(self, message):
        """生成失敗：顯示錯誤訊息。"""
        self._set_processing(False)
        self.status_var.set("生成失敗。")
        messagebox.showerror("生成失敗", message)

    # ==================================================================
    # 自動更新
    # ==================================================================
    def _start_update_check(self):
        """於背景執行緒檢查是否有新版本。"""
        threading.Thread(target=self._update_check_worker, daemon=True).start()

    def _update_check_worker(self):
        """背景執行緒：查詢 GitHub 最新版本。"""
        info = check_for_update()
        if info:
            self.result_queue.put(("update", info))

    def _prompt_update(self, info):
        """偵測到新版本時詢問使用者是否更新。"""
        if not getattr(sys, "frozen", False):
            self.status_var.set(f"有新版本可用：{info['version']}（原始碼模式不自動更新）")
            return
        answer = messagebox.askyesno(
            "發現新版本",
            f"目前版本:v{APP_VERSION}\n"
            f"最新版本:{info['version']}\n\n是否立即下載並更新？",
        )
        if not answer:
            return
        self._set_processing(True)
        self.status_var.set("正在下載新版本...")
        threading.Thread(
            target=self._update_apply_worker, args=(info["url"],), daemon=True,
        ).start()

    def _update_apply_worker(self, url):
        """背景執行緒：下載並套用新版本。"""
        try:
            download_and_apply(
                url,
                progress_cb=lambda ratio: self.result_queue.put(
                    ("status", f"正在下載新版本... {int(ratio * 100)}%")),
            )
            self.result_queue.put(("update_done", None))
        except Exception as exc:
            logger.exception("套用更新時發生錯誤")
            self.result_queue.put(("update_error", str(exc)))

    def _on_update_done(self):
        """更新完成：提示重新啟動。"""
        self._set_processing(False)
        self.status_var.set("更新完成，請重新啟動程式。")
        messagebox.showinfo(
            "更新完成", "新版本已下載完成，請關閉並重新開啟程式以套用更新。")

    def _on_update_error(self, message):
        """更新失敗：顯示錯誤訊息。"""
        self._set_processing(False)
        self.status_var.set("更新失敗。")
        messagebox.showerror("更新失敗", message)

    def _populate_cue_list(self, cues):
        """把 cue 清單填入 Treeview。"""
        self.cue_tree.delete(*self.cue_tree.get_children())
        for number, cue in enumerate(cues, start=1):
            time_label = (f"{format_srt_timestamp(cue['start'])} → "
                          f"{format_srt_timestamp(cue['end'])}")
            self.cue_tree.insert(
                "", "end",
                values=(number, time_label, cue["text"]),
            )

    def _set_processing(self, processing):
        """切換處理中狀態（鎖定按鈕、進度條）。"""
        self.is_processing = processing
        if processing:
            self.generate_btn.configure(state="disabled", text="處理中...")
            self.progress.start(12)
        else:
            mode = self.mode_var.get()
            if mode == MODE_MANUAL:
                self.generate_btn.configure(
                    state="normal", text="清空並進入手動編輯")
            else:
                self.generate_btn.configure(state="normal", text="開始生成字幕")
            self.progress.stop()

    # ==================================================================
    # 匯出與燒錄
    # ==================================================================
    def _update_export_state(self):
        """依目前是否有字幕，啟用或停用匯出 / 燒錄按鈕。"""
        state = "normal" if self.cues else "disabled"
        for btn in (self.export_btn_srt, self.export_btn_vtt,
                    self.export_btn_ass, self.export_btn_txt, self.burn_btn):
            btn.configure(state=state)

    def _default_export_name(self, ext):
        """以來源檔名為基礎組出預設輸出檔名。"""
        source = self.file_var.get().strip()
        if source:
            return os.path.splitext(os.path.basename(source))[0] + ext
        return f"字幕{ext}"

    def _on_export(self, ext):
        """匯出指定格式的字幕檔。"""
        if not self.cues:
            messagebox.showinfo("提示", "目前沒有可匯出的字幕。")
            return
        initial_dir = self.config_data.get("last_dir") or os.getcwd()
        path = filedialog.asksaveasfilename(
            title=f"儲存{ext.upper().lstrip('.')}字幕檔",
            initialdir=initial_dir,
            initialfile=self._default_export_name(ext),
            defaultextension=ext,
            filetypes=FORMAT_FILETYPES,
        )
        if not path:
            return
        # 同步最新樣式給 ASS 匯出使用。
        self.config_data["subtitle_style"] = self.style_panel.get_style()
        try:
            export(self.cues, path, style=self.config_data["subtitle_style"])
        except (OSError, ValueError) as exc:
            messagebox.showerror("匯出失敗", f"無法寫入檔案：{exc}")
            return
        self.status_var.set(f"已匯出:{path}")
        messagebox.showinfo("匯出完成", f"字幕檔已儲存至：\n{path}")

    def _on_burn(self):
        """把字幕燒錄進影片（hardsub via ffmpeg）。"""
        if not self.cues:
            messagebox.showinfo("提示", "目前沒有可燒錄的字幕。")
            return
        if not ffmpeg_available():
            messagebox.showerror(
                "找不到 ffmpeg",
                "燒錄字幕需要 ffmpeg。請依說明安裝 ffmpeg 並加入系統 PATH。")
            return
        # 先選擇來源影片（若主檔案欄已有路徑則預設使用）。
        video_path = self.file_var.get().strip()
        if not video_path or not os.path.exists(video_path):
            video_path = filedialog.askopenfilename(
                title="選擇要燒錄字幕的影片", filetypes=MEDIA_FILETYPES,
            )
        if not video_path:
            return
        # 詢問輸出路徑。
        initial_dir = self.config_data.get("last_dir") or os.getcwd()
        base = os.path.splitext(os.path.basename(video_path))[0]
        output_path = filedialog.asksaveasfilename(
            title="儲存燒錄字幕後的影片",
            initialdir=initial_dir,
            initialfile=f"{base}_subtitled.mp4",
            defaultextension=".mp4",
            filetypes=[("MP4 影片", "*.mp4"), ("所有檔案", "*.*")],
        )
        if not output_path:
            return

        self.config_data["subtitle_style"] = self.style_panel.get_style()
        self._set_processing(True)
        self.status_var.set("正在啟動 ffmpeg 燒錄字幕...")
        threading.Thread(
            target=self._burn_worker,
            args=(video_path, output_path, dict(self.cues)
                  if isinstance(self.cues, dict) else list(self.cues)),
            daemon=True,
        ).start()

    def _burn_worker(self, video_path, output_path, cues):
        """背景執行緒：呼叫 ffmpeg 燒錄字幕。"""
        try:
            burn_subtitles(
                video_path=video_path,
                cues=cues,
                output_path=output_path,
                style=self.config_data["subtitle_style"],
                progress_cb=lambda ratio, msg: self.result_queue.put(
                    ("status", msg)),
            )
            self.result_queue.put(("burn_done", output_path))
        except Exception as exc:
            logger.exception("燒錄字幕時發生錯誤")
            self.result_queue.put(("burn_error", str(exc)))

    def _on_burn_done(self, output_path):
        """燒錄成功通知。"""
        self._set_processing(False)
        self.status_var.set(f"燒錄完成:{output_path}")
        messagebox.showinfo("燒錄完成", f"已輸出影片：\n{output_path}")

    def _on_burn_error(self, message):
        """燒錄失敗通知。"""
        self._set_processing(False)
        self.status_var.set("燒錄失敗。")
        messagebox.showerror("燒錄失敗", message)

    # ==================================================================
    # 設定儲存
    # ==================================================================
    def _save_config_silently(self):
        """靜默存檔；失敗時僅於狀態列提示，不中斷操作。"""
        try:
            save_config(self.config_data)
        except OSError as exc:
            self.status_var.set(f"設定儲存失敗：{exc}")

    def _on_close(self):
        """關閉視窗前保存設定。"""
        self.config_data["subtitle_style"] = self.style_panel.get_style()
        self._collect_transcription_config()
        self._collect_segmentation_config()
        self.destroy()


def main():
    """建立並執行應用程式。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app = SrtApp()
    app.mainloop()
