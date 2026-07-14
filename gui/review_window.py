# -*- coding: utf-8 -*-
"""
審片助手視窗：拍完素材後用文字快速找可用片段。

流程：
1. 按「開始分析」→ 背景轉錄素材並自動分段，列出所有講話段落與冷場。
2. 清單自動標記「冷場」「重複拍攝」「口頭禪多」，前兩者預設捨棄。
3. 讀文字掃一遍清單，雙擊（或按空白鍵）切換單段的保留 / 捨棄。
4. 一鍵輸出：粗剪影片（自動跳剪）、EDL（進剪輯軟體精剪）、
   CSV 片段清單、YouTube 章節草稿。
"""

import logging
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from config import save_config
from gui.error_dialog import show_friendly_error
from gui.ffmpeg_dialog import FfmpegInstallDialog
from subtitle.audio import DEFAULT_TARGET_LUFS
from subtitle.burner import ffmpeg_available
from subtitle.exporter import export as export_subtitle
from subtitle.media import probe_duration
from subtitle.pipeline import resolve_output_dir, unique_path
from subtitle.publisher import build_publish_pack, resolve_publish_settings
from subtitle.segmenter import build_cues_from_words
from subtitle.shorts import cut_vertical_clip, resolve_shorts_settings
from subtitle.thumbnails import (generate_thumbnails,
                                 resolve_thumbnail_settings)
from subtitle.review import (CATEGORY_COLORS, CATEGORY_LABELS,
                             TAG_HIGHLIGHT, TAG_REPEATED, TAG_SILENCE,
                             analyze, build_chapters, build_review_cues,
                             categorize, compute_loudness, cut_rough_video,
                             export_csv, export_edl, export_html_report,
                             export_youtube_chapters, resolve_settings,
                             search_segments, summarize)
from subtitle.transcriber import transcribe

logger = logging.getLogger(__name__)


class ReviewWindow(tk.Toplevel):
    """審片助手：以逐字稿審素材、標記可剪片段、輸出粗剪與剪輯清單。"""

    def __init__(self, master, config_data, media_path):
        super().__init__(master)
        self.title("審片助手：快速找可用片段")
        # 預設尺寸需容納偵測設定（4 列，含訊號權重）、時間軸與 4 排輸出按鈕。
        self.geometry("1020x820")
        self.minsize(840, 580)

        self.config_data = config_data
        self.media_path = media_path
        self.items = []              # analyze() 的段落清單
        self.words = []              # 轉錄的逐字時間軸（供短片字幕重建）
        self.media_duration = 0.0    # 素材總長（分析完成後更新）
        self.result_queue = queue.Queue()
        self.is_processing = False
        self._search_hits = []       # 目前關鍵字命中的段落索引
        self._search_pos = -1        # 下一個要跳到的命中位置
        self._filter = "all"         # 清單篩選：all / highlight / review
        self._visible = []           # 清單列 → items 索引的對照表

        self._build_widgets()
        self._poll_job = self.after(120, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ==================================================================
    # 介面
    # ==================================================================
    def _build_widgets(self):
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        ttk.Label(
            top, text=f"素材：{os.path.basename(self.media_path)}",
            font=("Microsoft JhengHei", 10, "bold"),
        ).pack(side="left")

        # 前置檢查：缺 ffmpeg 時開窗即提示並提供一鍵安裝，不必等輸出才報錯。
        self.ffmpeg_banner = None
        if not ffmpeg_available():
            banner = tk.Frame(self, bg="#fdf3d7")
            banner.pack(fill="x", padx=10, pady=(2, 0))
            tk.Label(
                banner, bg="#fdf3d7", fg="#8a5a00", anchor="w",
                text="⚠ 尚未安裝 ffmpeg：轉錄、粗剪、短片等功能需要它。",
            ).pack(side="left", padx=6, pady=4)
            tk.Button(banner, text="自動安裝 ffmpeg",
                      command=self._open_ffmpeg_installer).pack(
                side="right", padx=6, pady=2)
            self.ffmpeg_banner = banner

        # 偵測設定：所有參數可調並記憶於 config.json，下次分析生效。
        settings = resolve_settings(self.config_data)
        options = ttk.LabelFrame(
            self, text="偵測設定（自動記憶，按「開始分析」套用）", padding=(10, 6))
        options.pack(fill="x", padx=10, pady=(4, 0))

        row1 = ttk.Frame(options)
        row1.pack(fill="x", pady=2)
        tk.Label(row1, text="冷場門檻:").pack(side="left")
        self.silence_var = tk.DoubleVar(value=settings["silence_gap"])
        tk.Spinbox(
            row1, from_=0.5, to=10.0, increment=0.5, width=5,
            textvariable=self.silence_var, format="%.1f",
        ).pack(side="left", padx=(2, 2))
        tk.Label(row1, text="秒").pack(side="left", padx=(0, 12))
        tk.Label(row1, text="段落切分停頓:").pack(side="left")
        self.gap_var = tk.DoubleVar(value=settings["segment_gap"])
        tk.Spinbox(
            row1, from_=0.4, to=5.0, increment=0.2, width=5,
            textvariable=self.gap_var, format="%.1f",
        ).pack(side="left", padx=(2, 2))
        tk.Label(row1, text="秒").pack(side="left", padx=(0, 12))
        tk.Label(row1, text="精彩敏感度:").pack(side="left")
        self.sensitivity_var = tk.DoubleVar(
            value=settings["highlight_sensitivity"])
        tk.Spinbox(
            row1, from_=0.2, to=3.0, increment=0.1, width=5,
            textvariable=self.sensitivity_var, format="%.1f",
        ).pack(side="left", padx=(2, 2))
        tk.Label(row1, text="倍", fg="#666666").pack(side="left", padx=(0, 12))
        tk.Label(row1, text="重複判定相似度:").pack(side="left")
        self.similarity_var = tk.DoubleVar(value=settings["take_similarity"])
        tk.Spinbox(
            row1, from_=0.5, to=0.95, increment=0.05, width=5,
            textvariable=self.similarity_var, format="%.2f",
        ).pack(side="left", padx=(2, 0))

        row2 = ttk.Frame(options)
        row2.pack(fill="x", pady=2)
        tk.Label(row2, text="自訂情緒詞:").pack(side="left")
        self.excite_var = tk.StringVar(
            value=settings["extra_excite_words"])
        tk.Entry(row2, textvariable=self.excite_var).pack(
            side="left", fill="x", expand=True, padx=(2, 12))
        tk.Label(row2, text="口頭禪字:").pack(side="left")
        self.filler_var = tk.StringVar(value=settings["filler_words"])
        tk.Entry(row2, textvariable=self.filler_var, width=14).pack(
            side="left", padx=(2, 12))
        tk.Label(row2, text="章節最短:").pack(side="left")
        self.chapter_min_var = tk.DoubleVar(
            value=settings["chapter_min_seconds"])
        tk.Spinbox(
            row2, from_=10, to=600, increment=10, width=5,
            textvariable=self.chapter_min_var, format="%.0f",
        ).pack(side="left", padx=(2, 0))
        tk.Label(row2, text="秒").pack(side="left")
        # 精彩訊號個別權重：讓不同內容類型自訂判定依據
        # （例如教學型調低情緒詞、遊戲實況調高音量）。
        row_w = ttk.Frame(options)
        row_w.pack(fill="x", pady=2)
        tk.Label(row_w, text="精彩訊號權重:").pack(side="left")
        self.weight_vars = {}
        for key, label in (("weight_energy", "音量"),
                           ("weight_pace", "語速"),
                           ("weight_excite", "情緒詞"),
                           ("weight_exclaim", "驚嘆句")):
            tk.Label(row_w, text=label).pack(side="left", padx=(10, 2))
            var = tk.DoubleVar(value=settings[key])
            tk.Spinbox(
                row_w, from_=0.0, to=3.0, increment=0.1, width=4,
                textvariable=var, format="%.1f",
            ).pack(side="left")
            self.weight_vars[key] = var
        tk.Label(row_w, text="（0＝停用該訊號、1＝預設）",
                 fg="#666666").pack(side="left", padx=(10, 0))
        self.voice_band_var = tk.BooleanVar(value=settings["voice_band"])
        tk.Checkbutton(
            row_w, text="音量聚焦人聲頻帶",
            variable=self.voice_band_var).pack(side="left", padx=(12, 0))

        tk.Label(
            options, fg="#666666",
            text=("敏感度 >1 更容易標記精彩、<1 更嚴格；情緒詞以逗號或空白分隔，"
                  "附加於內建詞庫；口頭禪字連寫（逐字比對）。"),
        ).pack(anchor="w", pady=(2, 0))

        row3 = ttk.Frame(options)
        row3.pack(fill="x", pady=(4, 0))
        self.analyze_btn = tk.Button(
            row3, text="開始分析", width=12, command=self._on_analyze)
        self.analyze_btn.pack(side="left")

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress = ttk.Progressbar(
            row3, mode="determinate", length=200, maximum=100.0,
            variable=self.progress_var)
        self.progress.pack(side="left", padx=8, fill="x", expand=True)

        self.status_var = tk.StringVar(
            value="按「開始分析」轉錄素材並自動標記可剪片段。")
        tk.Label(self, textvariable=self.status_var, fg="#1a5fb4",
                 anchor="w", padx=10).pack(fill="x")

        # 彩色時間軸：一眼看出精彩（綠）、待審視（琥珀）、冷場（灰）分佈。
        timeline_frame = ttk.LabelFrame(
            self, text="素材時間軸（點色塊跳到段落）", padding=(8, 6))
        timeline_frame.pack(fill="x", padx=10, pady=(4, 0))
        self.timeline = tk.Canvas(
            timeline_frame, height=44, bg="#e8e8e8", highlightthickness=0)
        self.timeline.pack(fill="x")
        self.timeline.bind("<Configure>", lambda _e: self._draw_timeline())
        self.timeline.bind("<Button-1>", self._on_timeline_click)
        legend = ttk.Frame(timeline_frame)
        legend.pack(fill="x", pady=(4, 0))
        for key in ("highlight", "normal", "review", "silence"):
            tk.Label(legend, text="■", fg=CATEGORY_COLORS[key]).pack(side="left")
            tk.Label(legend, text=CATEGORY_LABELS[key],
                     fg="#555555").pack(side="left", padx=(0, 10))
        self.stats_var = tk.StringVar(value="")
        tk.Label(legend, textvariable=self.stats_var,
                 fg="#555555").pack(side="right")

        # 段落清單。
        frame = ttk.LabelFrame(
            self, text="段落清單（雙擊或空白鍵切換保留／捨棄）", padding=(6, 6))
        frame.pack(fill="both", expand=True, padx=10, pady=(4, 0))
        columns = ("keep", "index", "time", "duration", "tags", "text")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings")
        headers = [("keep", "保留", 44), ("index", "#", 40),
                   ("time", "時間", 150), ("duration", "秒數", 56),
                   ("tags", "標記", 110), ("text", "內容", 460)]
        for key, label, width in headers:
            self.tree.heading(key, text=label)
            anchor = "w" if key == "text" else "center"
            self.tree.column(key, width=width, anchor=anchor,
                             stretch=(key == "text"))
        scrollbar = ttk.Scrollbar(frame, orient="vertical",
                                  command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _e: self._toggle_selected())
        self.tree.bind("<space>", lambda _e: self._toggle_selected())
        # 列底色依分類上色、捨棄段以灰字顯示，一眼可分。
        self.tree.tag_configure("dropped", foreground="#999999")
        self.tree.tag_configure("cat_highlight", background="#dff5e1")
        self.tree.tag_configure("cat_review", background="#fdf3d7")
        self.tree.tag_configure("cat_silence", background="#efefef")

        # 段落操作、篩選與搜尋。
        ops = ttk.Frame(self, padding=(10, 4))
        ops.pack(fill="x")
        tk.Button(ops, text="切換保留", width=9,
                  command=self._toggle_selected).pack(side="left", padx=2)
        tk.Button(ops, text="套用建議", width=9,
                  command=self._apply_suggestions).pack(side="left", padx=2)
        tk.Button(ops, text="全部保留", width=9,
                  command=self._keep_all).pack(side="left", padx=2)
        tk.Label(ops, text="顯示:").pack(side="left", padx=(14, 2))
        self.filter_var = tk.StringVar(value="all")
        for value, label in (("all", "全部"), ("highlight", "只看精彩"),
                             ("review", "只看待審視")):
            tk.Radiobutton(
                ops, text=label, value=value, variable=self.filter_var,
                command=self._on_filter_change,
            ).pack(side="left")
        tk.Label(ops, text="關鍵字:").pack(side="left", padx=(14, 2))
        self.search_var = tk.StringVar()
        entry = tk.Entry(ops, textvariable=self.search_var, width=16)
        entry.pack(side="left")
        entry.bind("<Return>", lambda _e: self._on_search())
        tk.Button(ops, text="搜尋下一個", width=10,
                  command=self._on_search).pack(side="left", padx=4)

        # 匯出列（兩排：影片輸出與清單交付）。
        exports = ttk.LabelFrame(self, text="輸出", padding=(10, 6))
        exports.pack(fill="x", padx=10, pady=(2, 10))
        self.export_buttons = []
        row1 = ttk.Frame(exports)
        row1.pack(fill="x")
        row2 = ttk.Frame(exports)
        row2.pack(fill="x", pady=(4, 0))
        for parent, label, command in [
                (row1, "輸出粗剪影片（自動跳剪）", self._on_rough_cut),
                (row1, "輸出精彩合輯（短影音素材）", self._on_highlight_cut),
                (row1, "匯出 HTML 審片報告", self._on_export_html),
                (row2, "匯出 EDL（進剪輯軟體）", self._on_export_edl),
                (row2, "匯出審片標記字幕", self._on_export_review_srt),
                (row2, "匯出 CSV 清單", self._on_export_csv),
                (row2, "複製 YouTube 章節", self._on_copy_chapters),
                (row2, "匯出發佈包", self._on_export_publish_pack)]:
            btn = tk.Button(parent, text=label, command=command,
                            state="disabled")
            btn.pack(side="left", padx=3)
            self.export_buttons.append(btn)

        # 粗剪選項：同時剪掉口頭禪字詞（Descript 式 filler-word removal）。
        self.cut_fillers_var = tk.BooleanVar(
            value=settings["cut_filler_words"])
        tk.Checkbutton(
            row1, text="剪除口頭禪字",
            variable=self.cut_fillers_var).pack(side="left", padx=(8, 0))

        # 第三排：Shorts 直式短片（9:16）輸出與其版式設定。
        shorts_cfg = resolve_shorts_settings(self.config_data)
        row3 = ttk.Frame(exports)
        row3.pack(fill="x", pady=(4, 0))
        tk.Label(row3, text="直式短片:").pack(side="left")
        tk.Label(row3, text="版式").pack(side="left", padx=(6, 2))
        self.shorts_mode_var = tk.StringVar(
            value="模糊背景" if shorts_cfg["mode"] == "blur" else "裁切")
        ttk.Combobox(
            row3, textvariable=self.shorts_mode_var, state="readonly",
            width=8, values=["裁切", "模糊背景"],
        ).pack(side="left")
        tk.Label(row3, text="焦點").pack(side="left", padx=(8, 2))
        self.shorts_focus_var = tk.DoubleVar(value=shorts_cfg["focus_x"])
        tk.Spinbox(
            row3, from_=0.0, to=1.0, increment=0.05, width=5,
            textvariable=self.shorts_focus_var, format="%.2f",
        ).pack(side="left")
        tk.Label(row3, text="（0 左、0.5 中、1 右）",
                 fg="#666666").pack(side="left")
        self.shorts_subs_var = tk.BooleanVar(
            value=shorts_cfg["burn_subtitles"])
        tk.Checkbutton(row3, text="燒錄字幕",
                       variable=self.shorts_subs_var).pack(side="left",
                                                           padx=(8, 0))
        self.shorts_loudnorm_var = tk.BooleanVar(value=shorts_cfg["loudnorm"])
        tk.Checkbutton(row3, text="響度正規化",
                       variable=self.shorts_loudnorm_var).pack(side="left")
        shorts_btn = tk.Button(
            row3, text="輸出直式短片（選取段落）",
            command=self._on_export_shorts, state="disabled")
        shorts_btn.pack(side="left", padx=(8, 3))
        self.export_buttons.append(shorts_btn)

        # 第四排：封面候選圖擷取（精彩高峰＋畫面清晰度自動評分）。
        thumbs_cfg = resolve_thumbnail_settings(self.config_data)
        row4 = ttk.Frame(exports)
        row4.pack(fill="x", pady=(4, 0))
        tk.Label(row4, text="封面候選:").pack(side="left")
        tk.Label(row4, text="張數").pack(side="left", padx=(6, 2))
        self.thumb_count_var = tk.IntVar(value=thumbs_cfg["count"])
        tk.Spinbox(
            row4, from_=2, to=12, increment=1, width=4,
            textvariable=self.thumb_count_var).pack(side="left")
        tk.Label(row4, text="最小間隔").pack(side="left", padx=(8, 2))
        self.thumb_spacing_var = tk.DoubleVar(
            value=thumbs_cfg["min_spacing"])
        tk.Spinbox(
            row4, from_=1.0, to=120.0, increment=1.0, width=5,
            textvariable=self.thumb_spacing_var, format="%.0f",
        ).pack(side="left")
        tk.Label(row4, text="秒").pack(side="left")
        self.thumb_highlight_var = tk.BooleanVar(
            value=thumbs_cfg["prefer_highlights"])
        tk.Checkbutton(
            row4, text="優先取精彩段落",
            variable=self.thumb_highlight_var).pack(side="left", padx=(8, 0))
        thumbs_btn = tk.Button(
            row4, text="擷取封面候選圖",
            command=self._on_export_thumbnails, state="disabled")
        thumbs_btn.pack(side="left", padx=(8, 3))
        self.export_buttons.append(thumbs_btn)
        tk.Label(row4, text="（自動挑清晰、有內容的畫面，輸出 PNG）",
                 fg="#666666").pack(side="left")

    # ==================================================================
    # 分析
    # ==================================================================
    def _collect_review_settings(self):
        """把介面上的偵測參數寫回設定並存檔，回傳解析後的 settings。"""
        def safe(var, fallback):
            try:
                return var.get()
            except (tk.TclError, ValueError):
                return fallback

        current = dict(self.config_data.get("review", {}))
        current.update({
            "silence_gap": float(safe(self.silence_var, 2.0)),
            "segment_gap": float(safe(self.gap_var, 1.0)),
            "highlight_sensitivity": float(safe(self.sensitivity_var, 1.0)),
            "take_similarity": float(safe(self.similarity_var, 0.72)),
            "extra_excite_words": self.excite_var.get().strip(),
            "filler_words": self.filler_var.get().strip(),
            "chapter_min_seconds": float(safe(self.chapter_min_var, 60.0)),
        })
        current.update({
            key: float(safe(var, 1.0))
            for key, var in self.weight_vars.items()
        })
        current["voice_band"] = bool(safe(self.voice_band_var, True))
        current["cut_filler_words"] = bool(safe(self.cut_fillers_var, False))
        self.config_data["review"] = current
        try:
            save_config(self.config_data)
        except OSError:
            pass  # 存檔失敗不影響本次分析。
        return resolve_settings(self.config_data)

    def _on_analyze(self):
        if self.is_processing:
            return
        settings = self._collect_review_settings()
        self._set_processing(True)
        threading.Thread(
            target=self._analyze_worker, args=(settings,),
            daemon=True).start()

    def _analyze_worker(self, settings):
        try:
            def report(message, ratio=None):
                if ratio is not None:
                    ratio *= 0.95  # 轉錄後還有分析步驟，保留尾段進度。
                self.result_queue.put(("status", (message, ratio)))

            words = transcribe(self.media_path, self.config_data, report)
            report("正在分析音量能量（偵測精彩片段）...", 0.96)
            loudness = compute_loudness(
                self.media_path, voice_band=settings["voice_band"])
            report("正在分析段落與標記...", 0.98)
            duration = probe_duration(self.media_path)
            items = analyze(
                words, media_duration=duration,
                loudness=loudness, settings=settings)
            self.result_queue.put(("done", (items, duration, words)))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("審片分析失敗")
            self.result_queue.put(("error", exc))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.result_queue.get_nowait()
                if kind == "status":
                    message, ratio = payload
                    self.status_var.set(message)
                    self.progress_var.set(
                        (ratio or 0.0) * 100.0 if ratio is not None
                        else self.progress_var.get())
                elif kind == "done":
                    self._on_analyze_done(payload)
                elif kind == "cut_done":
                    self._set_processing(False)
                    self.status_var.set(f"粗剪完成：{payload}")
                    messagebox.showinfo(
                        "粗剪完成", f"已輸出影片：\n{payload}", parent=self)
                elif kind == "shorts_done":
                    self._set_processing(False)
                    self.status_var.set(
                        f"直式短片輸出完成，共 {len(payload)} 支。")
                    messagebox.showinfo(
                        "短片輸出完成",
                        "已輸出直式短片：\n" + "\n".join(payload),
                        parent=self)
                elif kind == "thumbs_done":
                    self._set_processing(False)
                    self.status_var.set(
                        f"封面候選輸出完成，共 {len(payload)} 張。")
                    lines = [
                        (f"{os.path.basename(item['path'])}"
                         f"（{int(item['time']) // 60:02d}:"
                         f"{int(item['time']) % 60:02d} 處）")
                        for item in payload]
                    messagebox.showinfo(
                        "封面候選完成",
                        "已依畫面清晰度排序輸出候選圖：\n" + "\n".join(lines),
                        parent=self)
                elif kind == "error":
                    self._set_processing(False)
                    self.status_var.set("處理失敗。")
                    show_friendly_error(
                        self, "處理失敗", payload,
                        on_install_ffmpeg=self._open_ffmpeg_installer)
        except queue.Empty:
            pass
        self._poll_job = self.after(120, self._poll_queue)

    def _open_ffmpeg_installer(self):
        """開啟 ffmpeg 一鍵安裝；完成後移除警告條。"""
        def done():
            if self.ffmpeg_banner is not None:
                self.ffmpeg_banner.destroy()
                self.ffmpeg_banner = None
        FfmpegInstallDialog(self, on_done=done)

    def _require_ffmpeg(self, action_label):
        """輸出前檢查 ffmpeg；缺少時顯示友善錯誤（含一鍵安裝）。"""
        if ffmpeg_available():
            return True
        show_friendly_error(
            self, f"{action_label}需要 ffmpeg",
            RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。"),
            on_install_ffmpeg=self._open_ffmpeg_installer)
        return False

    def _on_analyze_done(self, payload):
        items, duration, words = payload
        self.items = items
        self.words = words
        self.media_duration = duration
        self._set_processing(False)
        self._repopulate()
        stats = summarize(items, duration)
        dropped = sum(1 for i in items if not i["keep"])
        self.status_var.set(
            f"分析完成：{stats['segment_count']} 個講話段落、"
            f"{stats['highlight_count']} 段精彩，建議捨棄 {dropped} 段。"
            "時間軸綠色為精彩、琥珀色待審視、灰色冷場。")
        self.stats_var.set(
            f"保留 {stats['kept_seconds'] / 60.0:.1f} 分｜"
            f"精彩 {stats['highlight_seconds'] / 60.0:.1f} 分｜"
            f"冷場 {stats['silence_seconds'] / 60.0:.1f} 分｜"
            f"口頭禪 {stats['filler_total']} 次")

    # ==================================================================
    # 清單操作
    # ==================================================================
    def _visible_indexes(self):
        """依目前篩選條件回傳要顯示的 items 索引。"""
        if self._filter == "all":
            return list(range(len(self.items)))
        return [i for i, item in enumerate(self.items)
                if categorize(item) == self._filter]

    def _repopulate(self, keep_selection=False):
        selected = self.tree.selection()
        selected_row = None
        if keep_selection and selected:
            selected_row = self.tree.index(selected[0])
        self.tree.delete(*self.tree.get_children())
        self._visible = self._visible_indexes()
        for row, index in enumerate(self._visible):
            item = self.items[index]
            minutes, secs = divmod(int(item["start"]), 60)
            end_m, end_s = divmod(int(item["end"]), 60)
            row_tags = [f"cat_{categorize(item)}"]
            if not item["keep"]:
                row_tags.append("dropped")
            self.tree.insert(
                "", "end",
                values=("✔" if item["keep"] else "✘",
                        index + 1,
                        f"{minutes:02d}:{secs:02d} → {end_m:02d}:{end_s:02d}",
                        f"{item['end'] - item['start']:.1f}",
                        "、".join(item["tags"]),
                        item["text"]),
                tags=tuple(row_tags))
        children = self.tree.get_children()
        if selected_row is not None and selected_row < len(children):
            self.tree.selection_set(children[selected_row])
            self.tree.focus(children[selected_row])
        self._update_export_state()
        self._draw_timeline()

    def _on_filter_change(self):
        self._filter = self.filter_var.get()
        self._search_hits, self._search_pos = [], -1
        self._repopulate()

    def _draw_timeline(self):
        """把段落畫成整條素材的彩色時間軸；捨棄段以斜線網點淡化。"""
        canvas = self.timeline
        canvas.delete("all")
        if not self.items:
            return
        width = max(canvas.winfo_width(), 1)
        height = int(canvas.cget("height") or 44)
        total = max(self.media_duration,
                    max(item["end"] for item in self.items), 0.1)
        for index, item in enumerate(self.items):
            x0 = item["start"] / total * width
            x1 = max(item["end"] / total * width, x0 + 1.5)
            color = CATEGORY_COLORS[categorize(item)]
            stipple = "" if item["keep"] else "gray50"
            canvas.create_rectangle(
                x0, 2, x1, height - 2, fill=color, width=0,
                stipple=stipple, tags=("blk", f"idx{index}"))

    def _on_timeline_click(self, event):
        """點時間軸色塊：切回全部顯示並選取、捲動到該段落。"""
        hits = self.timeline.find_withtag("current")
        if not hits:
            return
        index = None
        for tag in self.timeline.gettags(hits[0]):
            if tag.startswith("idx"):
                index = int(tag[3:])
                break
        if index is None:
            return
        if index not in self._visible:
            self.filter_var.set("all")
            self._filter = "all"
            self._repopulate()
        row = self._visible.index(index)
        children = self.tree.get_children()
        self.tree.selection_set(children[row])
        self.tree.focus(children[row])
        self.tree.see(children[row])

    def _toggle_selected(self):
        selection = self.tree.selection()
        if not selection or not self.items:
            return
        for item_id in selection:
            index = self._visible[self.tree.index(item_id)]
            self.items[index]["keep"] = not self.items[index]["keep"]
        self._repopulate(keep_selection=True)

    def _apply_suggestions(self):
        """回復到系統建議：冷場與重複拍攝捨棄、其餘保留。"""
        for item in self.items:
            item["keep"] = (item["kind"] == "speech"
                            and not set(item["tags"]) & {TAG_SILENCE,
                                                         TAG_REPEATED})
        self._repopulate()
        self.status_var.set("已套用系統建議（捨棄冷場與重複拍攝）。")

    def _keep_all(self):
        for item in self.items:
            item["keep"] = True
        self._repopulate()
        self.status_var.set("已全部標記為保留。")

    def _on_search(self):
        """搜尋關鍵字並逐一跳到命中的段落（只在目前顯示範圍內）。"""
        keyword = self.search_var.get()
        hits = [i for i in search_segments(self.items, keyword)
                if i in set(self._visible)]
        if not hits:
            self.status_var.set(f"目前顯示範圍找不到「{keyword}」。")
            return
        if hits != self._search_hits:
            self._search_hits, self._search_pos = hits, -1
        self._search_pos = (self._search_pos + 1) % len(hits)
        row = self._visible.index(hits[self._search_pos])
        children = self.tree.get_children()
        self.tree.selection_set(children[row])
        self.tree.focus(children[row])
        self.tree.see(children[row])
        self.status_var.set(
            f"「{keyword}」共 {len(hits)} 段，"
            f"目前第 {self._search_pos + 1} 段。")

    # ==================================================================
    # 匯出
    # ==================================================================
    def _default_path(self, suffix, ext):
        """組出輸出路徑：尊重「自動化輸出」的輸出資料夾設定（留空＝來源資料夾）。"""
        base = os.path.splitext(os.path.basename(self.media_path))[0]
        out_dir = resolve_output_dir(
            self.media_path, self.config_data.get("automation", {}))
        os.makedirs(out_dir, exist_ok=True)
        return unique_path(os.path.join(out_dir, f"{base}{suffix}{ext}"))

    def _on_rough_cut(self):
        if self.is_processing or not self.items:
            return
        if not self._require_ffmpeg("粗剪輸出"):
            return
        output = self._default_path("_粗剪", ".mp4")
        self._set_processing(True)
        threading.Thread(
            target=self._cut_worker,
            args=(self.items, output, self._cut_fillers_enabled()),
            daemon=True).start()

    def _on_highlight_cut(self):
        """只把精彩片段串成合輯（短影音、預告素材）。"""
        if self.is_processing or not self.items:
            return
        highlights = [dict(item, keep=True) for item in self.items
                      if TAG_HIGHLIGHT in item["tags"]]
        if not highlights:
            messagebox.showinfo(
                "沒有精彩片段",
                "本素材未偵測到精彩片段。可於清單手動確認內容，"
                "或改用「輸出粗剪影片」。", parent=self)
            return
        if not self._require_ffmpeg("輸出合輯"):
            return
        output = self._default_path("_精彩合輯", ".mp4")
        self._set_processing(True)
        threading.Thread(
            target=self._cut_worker,
            args=(highlights, output, self._cut_fillers_enabled()),
            daemon=True).start()

    def _cut_fillers_enabled(self):
        """讀取「剪除口頭禪字」勾選並記憶於設定檔。"""
        enabled = bool(self.cut_fillers_var.get())
        current = dict(self.config_data.get("review", {}))
        current["cut_filler_words"] = enabled
        self.config_data["review"] = current
        try:
            save_config(self.config_data)
        except OSError:
            pass
        return enabled

    def _cut_worker(self, items, output, drop_filler_words=False):
        try:
            cut_rough_video(
                self.media_path, items, output,
                progress_cb=lambda ratio, msg: self.result_queue.put(
                    ("status", (msg, ratio))),
                drop_filler_words=drop_filler_words)
            self.result_queue.put(("cut_done", output))
        except Exception as exc:
            logger.exception("剪輯輸出失敗")
            self.result_queue.put(("error", exc))

    def _collect_shorts_settings(self):
        """把介面上的短片設定寫回設定並存檔，回傳解析後的 settings。"""
        current = dict(self.config_data.get("shorts", {}))
        try:
            focus = float(self.shorts_focus_var.get())
        except (tk.TclError, ValueError):
            focus = 0.5
        current.update({
            "mode": "blur" if self.shorts_mode_var.get() == "模糊背景"
                    else "crop",
            "focus_x": focus,
            "burn_subtitles": bool(self.shorts_subs_var.get()),
            "loudnorm": bool(self.shorts_loudnorm_var.get()),
        })
        self.config_data["shorts"] = current
        try:
            save_config(self.config_data)
        except OSError:
            pass
        return resolve_shorts_settings(self.config_data)

    def _on_export_shorts(self):
        """輸出直式短片：選取的段落各輸出一支 9:16 影片；未選取時用精彩段落。"""
        if self.is_processing or not self.items:
            return
        if not self._require_ffmpeg("輸出短片"):
            return
        selection = self.tree.selection()
        if selection:
            picked = [self.items[self._visible[self.tree.index(item_id)]]
                      for item_id in selection]
        else:
            picked = [item for item in self.items
                      if TAG_HIGHLIGHT in item["tags"]]
        picked = [item for item in picked if item["kind"] == "speech"]
        if not picked:
            messagebox.showinfo(
                "沒有可輸出的段落",
                "請先在清單選取要輸出的段落（可多選），"
                "或先讓系統偵測到精彩片段。", parent=self)
            return

        settings = self._collect_shorts_settings()
        # 為每個片段從逐字時間軸重建字幕（時間軸由輸出流程平移）。
        seg_cfg = self.config_data.get("segmentation", {})
        jobs = []
        for item in picked:
            cues = []
            if settings["burn_subtitles"] and self.words:
                clip_words = [w for w in self.words
                              if w["end"] > item["start"] - 0.05
                              and w["start"] < item["end"] + 0.05]
                if clip_words:
                    cues = build_cues_from_words(clip_words, seg_cfg)
            jobs.append({"start": item["start"], "end": item["end"],
                         "cues": cues})

        self._set_processing(True)
        threading.Thread(
            target=self._shorts_worker, args=(jobs, settings),
            daemon=True).start()

    def _shorts_worker(self, jobs, settings):
        """背景執行緒：逐一輸出直式短片。"""
        try:
            style = self.config_data.get("subtitle_style", {})
            loudnorm_target = (DEFAULT_TARGET_LUFS
                               if settings["loudnorm"] else None)
            outputs = []
            total = len(jobs)
            for index, job in enumerate(jobs, start=1):
                output = self._default_path(f"_短片{index:02d}", ".mp4")

                def report(ratio, message, _i=index):
                    overall = ((_i - 1) + max(0.0, min(ratio, 1.0))) / total
                    self.result_queue.put(
                        ("status", (f"[{_i}/{total}] {message}", overall)))

                cut_vertical_clip(
                    self.media_path, job["start"], job["end"], output,
                    mode=settings["mode"], focus_x=settings["focus_x"],
                    style=style, cues=job["cues"],
                    loudnorm_target=loudnorm_target,
                    progress_cb=report)
                outputs.append(output)
            self.result_queue.put(("shorts_done", outputs))
        except Exception as exc:
            logger.exception("直式短片輸出失敗")
            self.result_queue.put(("error", exc))

    def _collect_thumbnail_settings(self):
        """把介面上的封面候選參數寫回設定並存檔，回傳解析後的 settings。"""
        current = dict(self.config_data.get("thumbnails", {}))
        try:
            count = int(self.thumb_count_var.get())
        except (tk.TclError, ValueError):
            count = 6
        try:
            spacing = float(self.thumb_spacing_var.get())
        except (tk.TclError, ValueError):
            spacing = 8.0
        current.update({
            "count": count,
            "min_spacing": spacing,
            "prefer_highlights": bool(self.thumb_highlight_var.get()),
        })
        self.config_data["thumbnails"] = current
        try:
            save_config(self.config_data)
        except OSError:
            pass
        return resolve_thumbnail_settings(self.config_data)

    def _on_export_thumbnails(self):
        """擷取封面候選圖：精彩高峰取樣、清晰度評分，輸出 PNG。"""
        if self.is_processing or not self.items:
            return
        if not self._require_ffmpeg("擷取封面候選"):
            return
        settings = self._collect_thumbnail_settings()
        self._set_processing(True)
        threading.Thread(
            target=self._thumbs_worker, args=(settings,),
            daemon=True).start()

    def _thumbs_worker(self, settings):
        try:
            results = generate_thumbnails(
                self.media_path, self.items, self.media_duration,
                output_paths=lambda rank: self._default_path(
                    f"_封面{rank:02d}", ".png"),
                settings=settings,
                progress_cb=lambda ratio, msg: self.result_queue.put(
                    ("status", (msg, ratio))))
            self.result_queue.put(("thumbs_done", results))
        except Exception as exc:
            logger.exception("封面候選輸出失敗")
            self.result_queue.put(("error", exc))

    def _on_export_html(self):
        """匯出 HTML 審片報告（彩色時間軸 + 統計 + 段落表，單檔可分享）。"""
        if not self.items:
            return
        path = self._default_path("_審片報告", ".html")
        settings = self._collect_review_settings()
        try:
            export_html_report(
                self.items, path,
                source_name=os.path.basename(self.media_path),
                media_duration=self.media_duration,
                chapters=build_chapters(
                    self.items,
                    min_chapter_seconds=settings["chapter_min_seconds"],
                    break_gap=settings["silence_gap"]))
        except (OSError, ValueError) as exc:
            messagebox.showerror("匯出失敗", str(exc), parent=self)
            return
        self.status_var.set(f"已匯出審片報告：{path}")
        messagebox.showinfo(
            "匯出完成",
            f"HTML 審片報告已儲存至：\n{path}\n\n"
            "用瀏覽器開啟即可檢視彩色時間軸與段落表，可直接傳給剪輯師。",
            parent=self)

    def _on_export_review_srt(self):
        """匯出審片標記字幕：與素材一起載入剪輯軟體，拉軸即見標記。"""
        if not self.items:
            return
        path = self._default_path("_審片標記", ".srt")
        try:
            export_subtitle(build_review_cues(self.items), path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("匯出失敗", str(exc), parent=self)
            return
        self.status_var.set(f"已匯出審片標記字幕：{path}")
        messagebox.showinfo(
            "匯出完成",
            f"審片標記字幕已儲存至：\n{path}\n\n"
            "在剪輯軟體或播放器載入此字幕與原始素材，"
            "拉時間軸時即可看到【精彩】【冷場】等標記。",
            parent=self)

    def _on_export_edl(self):
        if not self.items:
            return
        path = self._default_path("_粗剪", ".edl")
        try:
            export_edl(self.items, path,
                       clip_name=os.path.basename(self.media_path),
                       drop_filler_words=self._cut_fillers_enabled())
        except (OSError, ValueError) as exc:
            messagebox.showerror("匯出失敗", str(exc), parent=self)
            return
        self.status_var.set(f"已匯出 EDL：{path}")
        messagebox.showinfo(
            "匯出完成",
            f"EDL 已儲存至：\n{path}\n\n"
            "可匯入 Premiere Pro / DaVinci Resolve，時間軸即為保留段落。",
            parent=self)

    def _on_export_csv(self):
        if not self.items:
            return
        path = self._default_path("_審片清單", ".csv")
        try:
            export_csv(self.items, path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("匯出失敗", str(exc), parent=self)
            return
        self.status_var.set(f"已匯出 CSV：{path}")
        messagebox.showinfo("匯出完成", f"片段清單已儲存至：\n{path}",
                            parent=self)

    def _on_copy_chapters(self):
        if not self.items:
            return
        settings = self._collect_review_settings()
        text = export_youtube_chapters(
            self.items,
            min_chapter_seconds=settings["chapter_min_seconds"],
            break_gap=settings["silence_gap"])
        if not text:
            messagebox.showinfo(
                "沒有內容", "目前沒有保留中的講話段落。", parent=self)
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("YouTube 章節草稿已複製到剪貼簿，可直接貼上說明欄。")

    def _on_export_publish_pack(self):
        """匯出發佈包：建議標題＋描述草稿＋標籤，上傳時直接取用。"""
        if not self.items:
            return
        settings = self._collect_review_settings()
        chapters = build_chapters(
            self.items,
            min_chapter_seconds=settings["chapter_min_seconds"],
            break_gap=settings["silence_gap"])
        pack = build_publish_pack(
            self.items,
            settings=resolve_publish_settings(self.config_data),
            chapters=chapters,
            source_name=os.path.basename(self.media_path),
            extra_words=settings["extra_excite_words"])
        path = self._default_path("_發佈包", ".txt")
        try:
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(pack)
        except OSError as exc:
            messagebox.showerror("匯出失敗", str(exc), parent=self)
            return
        self.status_var.set(f"已匯出發佈包：{path}")
        messagebox.showinfo(
            "匯出完成",
            f"發佈包已儲存至：\n{path}\n\n"
            "內含建議標題、描述草稿（含章節）與建議標籤，"
            "上傳 YouTube 時直接取用、自行潤飾。", parent=self)

    # ==================================================================
    # 狀態
    # ==================================================================
    def _set_processing(self, processing):
        self.is_processing = processing
        state = "disabled" if processing else "normal"
        self.analyze_btn.configure(
            state=state, text="處理中..." if processing else "開始分析")
        if not processing:
            self.progress_var.set(0.0)
        self._update_export_state()

    def _update_export_state(self):
        state = "normal" if (self.items and not self.is_processing) \
            else "disabled"
        for btn in self.export_buttons:
            btn.configure(state=state)

    def _on_close(self):
        if self._poll_job:
            self.after_cancel(self._poll_job)
        self.destroy()
