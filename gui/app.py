# -*- coding: utf-8 -*-
"""
SRT 自動字幕生成與編輯應用程式 - 主視窗。

整合：模式切換、檔案選擇、轉寫設定、字幕生成、即時預覽、
視覺調整面板與 SRT 匯出，並負責設定檔的載入與自動儲存（記憶功能）。
"""

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
from subtitle.segmenter import build_cues_from_words
from subtitle.srt_writer import format_timestamp, write_srt
from subtitle.transcriber import transcribe
from gui.preview_panel import PreviewPanel
from gui.scrollable import ScrollableFrame
from gui.style_panel import StylePanel

# 支援的影音檔副檔名（檔案選擇器用）。
MEDIA_FILETYPES = [
    ("影片與音訊檔", "*.mp4 *.mkv *.mov *.avi *.flv *.mp3 *.wav *.m4a *.aac *.ogg"),
    ("所有檔案", "*.*"),
]
# 模式識別字串。
MODE_TRANSCRIBE = "transcribe"
MODE_ALIGN = "align"


class SrtApp(tk.Tk):
    """應用程式主視窗。"""

    def __init__(self):
        super().__init__()
        self.title(f"SRT 自動字幕生成與編輯工具 v{APP_VERSION}")
        # 預設視窗尺寸；最小尺寸放寬，內容超出時由捲軸補足，達成自適應。
        self.geometry("1120x740")
        self.minsize(720, 480)

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
        # 整體版面包進可捲動容器，內容超出視窗時可拉動捲軸。
        scroll = ScrollableFrame(self)
        scroll.pack(fill="both", expand=True)
        container = scroll.interior

        # 左側：操作區；右側：預覽與樣式區。
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

        # 第一列：本地模型與語言。
        row1 = tk.Frame(frame)
        row1.pack(fill="x", pady=2)
        tk.Label(row1, text="本地模型：").pack(side="left")
        self.model_var = tk.StringVar(value=transcription_cfg["model"])
        ttk.Combobox(
            row1, textvariable=self.model_var, width=10, state="readonly",
            values=["tiny", "base", "small", "medium", "large"],
        ).pack(side="left", padx=(0, 12))
        tk.Label(row1, text="語言：").pack(side="left")
        self.language_var = tk.StringVar(value=transcription_cfg["language"])
        ttk.Combobox(
            row1, textvariable=self.language_var, width=10,
            # zh-TW 會強制輸出台灣繁體中文（內部以 zh 辨識後轉繁體）。
            values=["auto", "zh", "zh-TW", "en", "ja", "ko"],
        ).pack(side="left")

        # 第二列：API 模式。
        row2 = tk.Frame(frame)
        row2.pack(fill="x", pady=2)
        self.use_api_var = tk.BooleanVar(value=transcription_cfg["use_api"])
        tk.Checkbutton(
            row2, text="改用 OpenAI API", variable=self.use_api_var,
        ).pack(side="left")
        tk.Label(row2, text="API 金鑰：").pack(side="left", padx=(8, 0))
        self.api_key_var = tk.StringVar(value=transcription_cfg["api_key"])
        tk.Entry(
            row2, textvariable=self.api_key_var, show="*", width=30,
        ).pack(side="left", fill="x", expand=True)

        # 第三列：本地 Python 路徑，供 exe 使用使用者自備的 whisper。
        row3 = tk.Frame(frame)
        row3.pack(fill="x", pady=2)
        tk.Label(row3, text="本地 Python：").pack(side="left")
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

        # 第四列：轉寫提示詞，協助 Whisper 在卡詞、結巴或專有名詞時辨識更準確。
        row4 = tk.Frame(frame)
        row4.pack(fill="x", pady=(6, 2))
        tk.Label(row4, text="轉寫提示：").pack(side="left")
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
        """斷句設定區：字數上限與秒數限制（兩種模式皆適用）。"""
        frame = tk.LabelFrame(parent, text="斷句設定", padx=10, pady=6)
        frame.pack(fill="x", pady=(0, 8))
        self.segmentation_frame = frame
        seg = self.config_data["segmentation"]

        # 第一列：中英文單行字數上限。
        row1 = tk.Frame(frame)
        row1.pack(fill="x", pady=2)
        tk.Label(row1, text="中文單行上限：").pack(side="left")
        self.cjk_limit_var = tk.IntVar(value=seg["max_chars_cjk"])
        tk.Spinbox(
            row1, from_=4, to=40, width=6, textvariable=self.cjk_limit_var,
        ).pack(side="left", padx=(0, 4))
        tk.Label(row1, text="字").pack(side="left", padx=(0, 14))
        tk.Label(row1, text="英文單行上限：").pack(side="left")
        self.latin_limit_var = tk.IntVar(value=seg["max_chars_latin"])
        tk.Spinbox(
            row1, from_=10, to=90, width=6, textvariable=self.latin_limit_var,
        ).pack(side="left", padx=(0, 4))
        tk.Label(row1, text="字母").pack(side="left")

        # 第二列：單句秒數與停頓門檻。
        row2 = tk.Frame(frame)
        row2.pack(fill="x", pady=2)
        tk.Label(row2, text="最短秒數：").pack(side="left")
        self.min_dur_var = tk.DoubleVar(value=seg["min_duration"])
        tk.Spinbox(
            row2, from_=0.3, to=5.0, increment=0.1, width=5,
            textvariable=self.min_dur_var, format="%.1f",
        ).pack(side="left", padx=(0, 12))
        tk.Label(row2, text="最長秒數：").pack(side="left")
        self.max_dur_var = tk.DoubleVar(value=seg["max_duration"])
        tk.Spinbox(
            row2, from_=2.0, to=15.0, increment=0.5, width=5,
            textvariable=self.max_dur_var, format="%.1f",
        ).pack(side="left", padx=(0, 12))
        tk.Label(row2, text="停頓秒數：").pack(side="left")
        self.pause_gap_var = tk.DoubleVar(value=seg["pause_gap"])
        tk.Spinbox(
            row2, from_=0.2, to=2.0, increment=0.1, width=5,
            textvariable=self.pause_gap_var, format="%.1f",
        ).pack(side="left")

        # 第三列：時間軸整體微調，供修正字幕時間偏差。
        row3 = tk.Frame(frame)
        row3.pack(fill="x", pady=2)
        tk.Label(row3, text="時間軸微調：").pack(side="left")
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
        """生成 / 匯出與狀態列。"""
        frame = tk.Frame(parent)
        frame.pack(fill="x", pady=(0, 8))
        self.action_frame = frame
        self.generate_btn = tk.Button(
            frame, text="開始生成字幕", width=16, command=self._on_generate,
        )
        self.generate_btn.pack(side="left")
        self.export_btn = tk.Button(
            frame, text="匯出 SRT", width=12, command=self._on_export,
            state="disabled",
        )
        self.export_btn.pack(side="left", padx=6)

        self.progress = ttk.Progressbar(frame, mode="indeterminate", length=160)
        self.progress.pack(side="left", padx=6)

        self.status_var = tk.StringVar(value="就緒。")
        tk.Label(parent, textvariable=self.status_var, fg="#1a5fb4",
                 anchor="w").pack(fill="x")

    def _build_cue_list(self, parent):
        """字幕清單（生成結果）。"""
        frame = tk.LabelFrame(parent, text="字幕清單（點選可預覽）", padx=6, pady=6)
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
        """習慣設定區：儲存與切換多組樣式（含字幕樣式與斷句設定）。"""
        frame = tk.LabelFrame(parent, text="習慣設定（樣式組合）", padx=8, pady=6)
        frame.pack(fill="x", pady=(0, 8))

        row = tk.Frame(frame)
        row.pack(fill="x")
        tk.Label(row, text="目前樣式：").pack(side="left")
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
        if mode == MODE_TRANSCRIBE:
            # 模式一：顯示轉寫設定，隱藏文字稿輸入區。
            self.transcript_frame.pack_forget()
            self.transcription_frame.pack(
                fill="x", pady=(0, 8), before=self.segmentation_frame)
        else:
            # 模式二：顯示文字稿輸入區，隱藏轉寫設定。
            self.transcription_frame.pack_forget()
            self.transcript_frame.pack(
                fill="both", pady=(0, 8), before=self.action_frame)

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

    # ==================================================================
    # 習慣設定（preset）管理
    # ==================================================================
    def _current_profile(self):
        """收集介面上目前的字幕樣式與斷句設定，打包成一組習慣設定。"""
        # 先把介面最新值同步回 config_data。
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
        # 載入該組設定為目前作用值。
        self.config_data["subtitle_style"] = dict(preset["subtitle_style"])
        self.config_data["segmentation"] = dict(preset["segmentation"])
        self.config_data["active_preset"] = name
        # 同步更新介面控制項與預覽。
        self.style_panel.set_style(self.config_data["subtitle_style"])
        self._load_segmentation_into_ui()
        self.preview.update_style(self.config_data["subtitle_style"])
        self._refresh_preview()
        self._save_config_silently()
        self.status_var.set(f"已套用習慣設定：{name}")

    def _save_new_preset(self):
        """以目前介面設定另存為一組新的習慣設定。"""
        name = simpledialog.askstring(
            "另存新樣式", "請輸入樣式名稱：", parent=self)
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
        # 改選用剩餘的第一組並套用。
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
            """取得 Spinbox 變數值，欄位為空或非法時退回原值。"""
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

        # 夾限至合理範圍，並確保最短秒數不大於最長秒數。
        seg["max_chars_cjk"] = max(4, min(cjk, 40))
        seg["max_chars_latin"] = max(10, min(latin, 90))
        seg["min_duration"] = max(0.3, min(min_dur, max_dur))
        seg["max_duration"] = max(seg["min_duration"], min(max_dur, 15.0))
        seg["pause_gap"] = max(0.2, min(pause, 2.0))
        seg["time_offset"] = max(-10.0, min(offset, 10.0))

        self.config_data["segmentation"] = seg
        self._save_config_silently()

    def _on_generate(self):
        """按下「開始生成字幕」。"""
        if self.is_processing:
            return
        audio_path = self.file_var.get().strip()
        if not audio_path or not os.path.exists(audio_path):
            messagebox.showerror("錯誤", "請先選擇有效的影片或音訊檔案。")
            return

        mode = self.mode_var.get()
        transcript = ""
        if mode == MODE_ALIGN:
            transcript = self.transcript_text.get("1.0", "end").strip()
            if not transcript:
                messagebox.showerror("錯誤", "模式二需要先貼上文字稿。")
                return

        self._collect_transcription_config()
        self._collect_segmentation_config()

        # 進入處理中狀態，啟動背景執行緒避免介面凍結。
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
        self.export_btn.configure(state="normal")
        # 預設選取第一句並預覽。
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
            # 從原始碼執行時無法就地替換，僅於狀態列提示。
            self.status_var.set(f"有新版本可用：{info['version']}（原始碼模式不自動更新）")
            return
        answer = messagebox.askyesno(
            "發現新版本",
            f"目前版本：v{APP_VERSION}\n"
            f"最新版本：{info['version']}\n\n是否立即下載並更新？",
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
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
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
        for cue in cues:
            time_label = (f"{format_timestamp(cue['start'])} → "
                          f"{format_timestamp(cue['end'])}")
            self.cue_tree.insert(
                "", "end",
                values=(cue["index"], time_label, cue["text"]),
            )

    def _set_processing(self, processing):
        """切換處理中狀態（鎖定按鈕、進度條）。"""
        self.is_processing = processing
        if processing:
            self.generate_btn.configure(state="disabled", text="處理中...")
            self.progress.start(12)
        else:
            self.generate_btn.configure(state="normal", text="開始生成字幕")
            self.progress.stop()

    # ==================================================================
    # 匯出與設定儲存
    # ==================================================================
    def _on_export(self):
        """匯出 SRT 檔案。"""
        if not self.cues:
            messagebox.showinfo("提示", "目前沒有可匯出的字幕。")
            return
        initial_dir = self.config_data.get("last_dir") or os.getcwd()
        # 以來源檔名作為預設輸出檔名。
        source = self.file_var.get().strip()
        default_name = "字幕.srt"
        if source:
            default_name = os.path.splitext(os.path.basename(source))[0] + ".srt"

        path = filedialog.asksaveasfilename(
            title="儲存 SRT 字幕檔", initialdir=initial_dir,
            initialfile=default_name, defaultextension=".srt",
            filetypes=[("SRT 字幕檔", "*.srt"), ("所有檔案", "*.*")],
        )
        if not path:
            return
        try:
            write_srt(self.cues, path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("匯出失敗", f"無法寫入檔案：{exc}")
            return
        self.status_var.set(f"已匯出：{path}")
        messagebox.showinfo("匯出完成", f"SRT 字幕檔已儲存至：\n{path}")

    def _save_config_silently(self):
        """靜默存檔；失敗時僅於狀態列提示，不中斷操作。"""
        try:
            save_config(self.config_data)
        except OSError as exc:
            self.status_var.set(f"設定儲存失敗：{exc}")

    def _on_close(self):
        """關閉視窗前保存設定。"""
        # 同步最新樣式、轉寫與斷句設定後存檔。
        self.config_data["subtitle_style"] = self.style_panel.get_style()
        self._collect_transcription_config()
        self._collect_segmentation_config()
        self.destroy()


def main():
    """建立並執行應用程式。"""
    app = SrtApp()
    app.mainloop()
