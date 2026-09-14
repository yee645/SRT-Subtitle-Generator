# -*- coding: utf-8 -*-
"""
自動修剪對話框：剪停頓與剪重複片段兩個偵測器共用一個視窗。

v1.52.3 把 `gui/jumpcut_dialog.py`（296 行）與 `gui/retakes_dialog.py`
（299 行）併成這一個檔案。合併的理由不是「按鈕太多」——兩顆入口在
v1.52.1 就已經搬到階段①了——而是這兩個視窗**高度同構**：同一個對象
（目前影片＋目前字幕）、同一個節奏（偵測 → 確認 → 剪除輸出）、同一套
輸出模式（剪後影片＋時間軸已對齊的字幕），連骨架都幾乎逐行對應：
`_choose_media`、`_collect_settings`、`_run_worker`、`_poll_queue`、
`_open_ffmpeg_installer`、`_set_processing`、`_on_close` 七個方法在兩邊
是同一份東西抄兩次。改一邊忘了改另一邊，只是遲早的事。

**兩個入口都保留**（階段①的〔剪停頓（依字幕）〕與〔剪重複片段〕），各自
開到對應分頁。使用者按下按鈕時心裡想做的事是明確的，先開一個通用視窗再
叫他選分頁是多一步；合併要省的是重複的程式碼與不一致的行為，不是入口。

**兩個偵測器的個性差異刻意保留**：
- 剪停頓動的是「沒有人講話的空檔」，誤判成本低，所以是「預覽 → 直接
  輸出」。
- 剪重複片段動的是**實際講話內容**，假陽性風險高（刻意重複的口號、報數
  測試麥克風都會中），所以是「列出候選 → 逐項勾選確認 → 才剪」。

把它們塞進同一個分頁骨架時，這個差異不能被抹平成同一套流程。
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
from gui.scrollable import ScrollableFrame
from subtitle.burner import ffmpeg_available
from subtitle.exporter import export
from subtitle.jumpcut import (apply_jumpcut, compute_keep_segments,
                              find_cut_gaps, format_jumpcut_report,
                              resolve_jumpcut_settings)
from subtitle.jumpcut import suggest_output_path as suggest_jumpcut_path
from subtitle.media import probe_duration
from subtitle.pipeline import unique_path
from subtitle.retakes import (apply_retake_removal, find_retakes,
                              format_retake_removal_report,
                              resolve_retake_settings)
from subtitle.retakes import suggest_output_path as suggest_retake_path

logger = logging.getLogger(__name__)

MEDIA_FILETYPES = [
    ("影音檔", "*.mp4 *.mkv *.mov *.avi *.flv *.mp3 *.wav *.m4a *.aac"),
    ("所有檔案", "*.*"),
]

# 分頁代號；`AutoTrimDialog(..., tab=...)` 用它決定開哪一頁。
TAB_GAPS = "gaps"
TAB_RETAKES = "retakes"


class AutoTrimDialog(tk.Toplevel):
    """自動修剪視窗：剪停頓（依字幕）與剪重複片段兩個分頁。"""

    def __init__(self, master, config_data, cues, media_path="",
                 on_done=None, on_media=None, tab=TAB_GAPS):
        super().__init__(master)
        self.title("自動修剪：剪掉停頓與重複片段")
        # 尺寸是量出來的，不是估的：兩個分頁的「判定門檻」列實測需要
        # 700px（剪停頓）與 699px（剪重複片段），加上 body/分頁/LabelFrame
        # 三層內距與 Notebook 邊框約 60px，內容總寬需求 792px。minsize 取
        # 780 讓門檻列在任何尺寸下都不被裁切。
        self.geometry("840x720")
        self.minsize(780, 620)
        self.transient(master)

        self.config_data = config_data
        self.cues = cues
        self.on_done = on_done
        # v1.52.2 的產出匯流排：剪出來的新影片也是一代產出，記進世代鏈後
        # 工作檔案列就看得出「原始素材 → 修剪版」。
        self.on_media = on_media
        self.result_queue = queue.Queue()
        self.is_processing = False
        self._preview_gaps = []
        self._retakes = []
        self._check_vars = []
        # 每個分頁各自最後一次的狀態訊息。兩個偵測器開窗時都會跑一次，若
        # 共用一個狀態列而不分頁保存，後跑完的那個會蓋掉前一個——實際看
        # 到的就是「停在剪停頓分頁，狀態列卻寫著重複片段偵測完成」。
        self._tab_status = {TAB_GAPS: "", TAB_RETAKES: ""}

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        # ---- 共用：影片列 ----
        row_file = ttk.Frame(body)
        row_file.pack(fill="x")
        ttk.Label(row_file, text="影片：").pack(side="left")
        self.media_var = tk.StringVar(value=media_path)
        ttk.Entry(row_file, textvariable=self.media_var).pack(
            side="left", fill="x", expand=True, padx=(6, 4))
        ttk.Button(row_file, text="瀏覽...", width=8,
                   command=self._choose_media).pack(side="left")

        # ---- 共用：ffmpeg 橫幅 ----
        self.ffmpeg_banner = None
        if not ffmpeg_available():
            banner = tk.Frame(body, bg="#fdf3d7")
            banner.pack(fill="x", pady=(8, 0))
            tk.Label(
                banner, bg="#fdf3d7", fg="#8a5a00", anchor="w",
                text="⚠ 尚未安裝 ffmpeg：修剪影片需要它才能裁切。",
            ).pack(side="left", padx=6, pady=4)
            ttk.Button(banner, text="自動安裝 ffmpeg",
                       command=self._open_ffmpeg_installer).pack(
                side="right", padx=6, pady=2)
            self.ffmpeg_banner = banner

        # ---- 共用：狀態列、進度條、關閉鈕 ----
        # **先 pack 這三個（side="bottom"）再 pack 分頁區**，順序不能顛倒。
        # pack 依呼叫順序從剩餘空間切給每個 slave，分頁區帶 expand=True 會
        # 先把剩餘空間吃光；若它排在前面，視窗一不夠高，後面的進度條與
        # 〔關閉〕就會被擠到 winfo_ismapped()==0——實測 680x640 時關閉鈕
        # 真的整顆不見了（看得到視窗卻按不到關閉）。先把底部三件事的空間
        # 訂走，分頁區再拿剩下的，這樣任何視窗高度都不會擠掉它們。
        # 同類坑見 docs/ROADMAP_2.0.md 紀律節 v1.52.0 第 4 點。
        # 同一條規則在兩個分頁內部也要遵守（見 `_build_gaps_tab` 與
        # `_build_retakes_tab`）。施工時一度以為分頁內不需要，因為破壞探針
        # 沒抓到——後來發現那個探針是無效的：它只把 `side="bottom"` 拿掉，
        # 沒有把**宣告順序**搬回內容之後，而 pack 預設就是 top、先呼叫的先
        # 拿空間，所以順序沒變就測不出差別。真正把順序搬回去之後，minsize
        # 780x620 下〔偵測重複片段〕〔剪掉勾選的重複片段〕確實整個消失。
        ttk.Button(body, text="關閉", command=self._on_close).pack(
            side="bottom", anchor="e")
        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(body, mode="determinate", maximum=100.0,
                        variable=self.progress_var).pack(
            side="bottom", fill="x", pady=(6, 6))
        self.status_var = tk.StringVar(
            value=f"共 {len(cues)} 句字幕。兩個分頁都吃這份字幕與上面那支影片。")
        ttk.Label(body, textvariable=self.status_var,
                  foreground="#1a5fb4", wraplength=780, justify="left").pack(
            side="bottom", fill="x", pady=(8, 0))

        # ---- 兩個偵測器分頁 ----
        self.notebook = ttk.Notebook(body)
        self.notebook.pack(fill="both", expand=True, pady=(8, 0))
        self.gaps_tab = ttk.Frame(self.notebook, padding=8)
        self.retakes_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.gaps_tab, text="剪停頓（依字幕）")
        self.notebook.add(self.retakes_tab, text="剪重複片段")
        self._build_gaps_tab(self.gaps_tab)
        self._build_retakes_tab(self.retakes_tab)

        self.notebook.select(
            self.retakes_tab if tab == TAB_RETAKES else self.gaps_tab)
        # 兩個偵測器都先跑一次，開窗就看得到結果（原本兩個視窗各自的行為）。
        self._on_preview_gaps()
        self._on_detect_retakes()
        # 這裡不必再呼叫 `_show_tab_status()`：`_set_tab_status` 本身就只在
        # 「正在看那一頁」時才寫進狀態列，所以開窗當下留下的必然是開著那
        # 一頁的訊息。（施工時多寫了一行，破壞探針證明拿掉也不會失敗——
        # 那就是死碼，不留。）
        self.notebook.bind("<<NotebookTabChanged>>",
                           lambda _event: self._show_tab_status())
        self._poll_job = self.after(120, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ==================================================================
    # 分頁一：剪停頓（依字幕）
    # ==================================================================
    def _build_gaps_tab(self, parent):
        settings = resolve_jumpcut_settings(self.config_data)
        ttk.Label(
            parent, foreground="#666666", justify="left", wraplength=700,
            text="依目前字幕清單找出句間沒人講話的空檔，一次剪掉整支影片的"
                 "冷場。剪掉的是空檔、不是內容，所以直接預覽後輸出。",
        ).pack(anchor="w", pady=(0, 6))

        options = ttk.LabelFrame(parent, text="判定門檻（自動記憶）",
                                 padding=(10, 6))
        options.pack(fill="x")
        row1 = ttk.Frame(options)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="最短停頓秒數:").pack(side="left")
        self.min_gap_var = tk.DoubleVar(value=settings["min_gap"])
        ttk.Spinbox(row1, from_=0.5, to=5.0, increment=0.1, width=6,
                    textvariable=self.min_gap_var, format="%.1f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row1, text="秒（達此長度才剪）").pack(side="left", padx=(0, 14))
        ttk.Label(row1, text="緩衝秒數:").pack(side="left")
        self.gap_pad_var = tk.DoubleVar(value=settings["pad"])
        ttk.Spinbox(row1, from_=0.0, to=1.0, increment=0.05, width=6,
                    textvariable=self.gap_pad_var, format="%.2f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row1, text="秒（剪點兩側保留）").pack(side="left")
        row2 = ttk.Frame(options)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="安全上限:").pack(side="left")
        self.max_ratio_var = tk.DoubleVar(
            value=settings["max_cut_ratio"] * 100.0)
        ttk.Spinbox(row2, from_=10.0, to=90.0, increment=5.0, width=6,
                    textvariable=self.max_ratio_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row2, text="%（跳剪比例超過此值時中止，防誤判）").pack(
            side="left")

        # 動作鈕先建立、先 pack（side="bottom"），再 pack 會 expand 的預覽
        # 區。理由與外層底部三件事相同：expand=True 的容器會把剩餘空間吃
        # 光，排在它**後面**的按鈕在空間不夠時會整顆消失。實測見
        # `tests/test_v1523.py` 的 minsize 段。
        buttons = ttk.Frame(parent)
        buttons.pack(side="bottom", fill="x", pady=(8, 0))
        self.preview_btn = ttk.Button(buttons, text="預覽跳剪點",
                                      command=self._on_preview_gaps)
        self.preview_btn.pack(side="left")
        self.run_btn = ttk.Button(buttons, text="輸出跳剪版", state="disabled",
                                  command=self._on_run_gaps)
        self.run_btn.pack(side="left", padx=(6, 0))

        report_frame = ttk.LabelFrame(parent, text="跳剪預覽", padding=(6, 6))
        report_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.report = tk.Text(report_frame, wrap="word", state="disabled",
                              font=("Microsoft JhengHei", 10), height=8)
        # 捲軸先 pack 再 pack 內容區——順序反了會讓捲軸被擠成 1px
        # （v1.48.0 出過這個包，見 docs/ROADMAP_2.0.md 紀律節）。
        scrollbar = ttk.Scrollbar(report_frame, orient="vertical",
                                  command=self.report.yview)
        scrollbar.pack(side="right", fill="y")
        self.report.configure(yscrollcommand=scrollbar.set)
        self.report.pack(side="left", fill="both", expand=True)

    def _collect_gap_settings(self):
        def safe(var, fallback):
            try:
                return float(var.get())
            except (tk.TclError, ValueError):
                return fallback
        self.config_data["jumpcut"] = {
            "min_gap": safe(self.min_gap_var, 1.2),
            "pad": safe(self.gap_pad_var, 0.15),
            "max_cut_ratio": safe(self.max_ratio_var, 60.0) / 100.0,
        }
        self._save_config()
        return resolve_jumpcut_settings(self.config_data)

    def _on_preview_gaps(self):
        """純分析目前字幕清單找出停頓（免呼叫 ffmpeg，瞬間完成）。"""
        settings = self._collect_gap_settings()
        gaps = find_cut_gaps(self.cues, settings["min_gap"])
        self._preview_gaps = gaps
        if not gaps:
            text = ("目前字幕沒有偵測到達門檻的停頓，可調低「最短停頓秒數」"
                    "再試，或影片節奏本來就很緊湊，不需要跳剪。")
            self.run_btn.configure(state="disabled")
        else:
            media_path = self.media_var.get().strip()
            duration = probe_duration(media_path) if (
                media_path and os.path.exists(media_path)) else None
            if duration:
                keep, cut_count = compute_keep_segments(
                    duration, gaps, settings["pad"])
                removed = duration - sum(e - s for s, e in keep)
                lines = [
                    f"偵測到 {len(gaps)} 處停頓，緩衝後可跳剪 {cut_count} 處。",
                    f"預估：原長度 {duration:.1f} 秒 → 剪後約 "
                    f"{duration - removed:.1f} 秒（省下約 {removed:.1f} 秒）。",
                ]
            else:
                lines = [
                    f"偵測到 {len(gaps)} 處達門檻的句間停頓。",
                    "（選好影片檔後可預估實際能省下的秒數。）",
                ]
            for index, (start, end) in enumerate(gaps, start=1):
                lines.append(
                    f"  {index}. {start:.1f}s ~ {end:.1f}s"
                    f"（停頓 {end - start:.1f} 秒）")
            text = "\n".join(lines)
            self.run_btn.configure(state="normal")
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", text)
        self.report.configure(state="disabled")
        self._set_tab_status(
            TAB_GAPS,
            f"跳剪預覽完成，找到 {len(gaps)} 處可剪的停頓。" if gaps
            else "跳剪預覽完成，沒有達門檻的停頓。")

    def _on_run_gaps(self):
        if self.is_processing:
            return
        if not self._preview_gaps:
            messagebox.showinfo("提示", "目前沒有可跳剪的停頓。", parent=self)
            return
        media_path = self._require_media("自動跳剪")
        if not media_path:
            return
        settings = self._collect_gap_settings()
        output = unique_path(suggest_jumpcut_path(media_path))
        self._set_processing(True)
        threading.Thread(
            target=self._gaps_worker,
            args=(media_path, output, settings), daemon=True).start()

    def _gaps_worker(self, media_path, output, settings):
        try:
            def report(ratio, message):
                self.result_queue.put(("status", (message, ratio)))
            result = apply_jumpcut(media_path, self.cues, output,
                                   settings=settings, progress_cb=report)
            result["source"] = media_path
            result["kind_label"] = "跳剪"
            result["report"] = format_jumpcut_report(result)
            self._export_cues(result, output)
            self.result_queue.put(("done", result))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("自動跳剪失敗")
            self.result_queue.put(("error", exc))

    # ==================================================================
    # 分頁二：剪重複片段
    # ==================================================================
    def _build_retakes_tab(self, parent):
        settings = resolve_retake_settings(self.config_data)
        ttk.Label(
            parent, foreground="#666666", justify="left", wraplength=700,
            text="找出同一句話講了好幾次的候選片段。這裡動的是實際講話內容，"
                 "刻意重複的口號、報數測試麥克風都可能被誤判，所以是"
                 "「列出候選、逐項確認、才剪」。",
        ).pack(anchor="w", pady=(0, 6))

        options = ttk.LabelFrame(parent, text="判定門檻（自動記憶）",
                                 padding=(10, 6))
        options.pack(fill="x")
        row1 = ttk.Frame(options)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="相似度門檻:").pack(side="left")
        self.similarity_var = tk.DoubleVar(
            value=settings["similarity_threshold"] * 100.0)
        ttk.Spinbox(row1, from_=50.0, to=98.0, increment=1.0, width=6,
                    textvariable=self.similarity_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row1, text="%（兩句文字達此相似度才視為重講）").pack(
            side="left", padx=(0, 14))
        ttk.Label(row1, text="比對時間窗:").pack(side="left")
        self.max_gap_var = tk.DoubleVar(value=settings["max_gap_seconds"])
        ttk.Spinbox(row1, from_=5.0, to=120.0, increment=5.0, width=6,
                    textvariable=self.max_gap_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row1, text="秒").pack(side="left")
        row2 = ttk.Frame(options)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="剪點外擴秒數:").pack(side="left")
        self.retake_pad_var = tk.DoubleVar(value=settings["pad"])
        ttk.Spinbox(row2, from_=0.0, to=1.0, increment=0.05, width=6,
                    textvariable=self.retake_pad_var, format="%.2f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row2, text="秒（連同前後的吸氣停頓一起剪掉）").pack(side="left")

        # 動作鈕先訂位，理由同分頁一。**這一頁是實測會出事的那一頁**：
        # 候選清單是 ScrollableFrame（expand=True），minsize 780x620 下把
        # 順序改回去，〔偵測重複片段〕〔剪掉勾選的重複片段〕真的整個不見。
        buttons = ttk.Frame(parent)
        buttons.pack(side="bottom", fill="x", pady=(8, 0))
        self.detect_btn = ttk.Button(buttons, text="偵測重複片段",
                                     command=self._on_detect_retakes)
        self.detect_btn.pack(side="left")
        self.cut_btn = ttk.Button(buttons, text="剪掉勾選的重複片段",
                                  state="disabled",
                                  command=self._on_cut_retakes)
        self.cut_btn.pack(side="left", padx=(6, 0))

        list_frame = ttk.LabelFrame(
            parent, text="候選重複片段（預設全選，可自行取消勾選誤判項目）",
            padding=(6, 6))
        list_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.scroll = ScrollableFrame(
            list_frame, theme=self.config_data.get("theme", "light"))
        self.scroll.pack(fill="both", expand=True)
        self.empty_label = ttk.Label(
            self.scroll.interior, text="（尚未偵測，或沒有候選項目）",
            foreground="#666666")
        self.empty_label.pack(anchor="w", padx=4, pady=4)

    def _collect_retake_settings(self):
        def safe(var, fallback):
            try:
                return float(var.get())
            except (tk.TclError, ValueError):
                return fallback
        self.config_data["retakes"] = {
            "similarity_threshold": safe(self.similarity_var, 72.0) / 100.0,
            "max_gap_seconds": safe(self.max_gap_var, 25.0),
            "pad": safe(self.retake_pad_var, 0.2),
        }
        self._save_config()
        return resolve_retake_settings(self.config_data)

    def _clear_retake_list(self):
        for child in self.scroll.interior.winfo_children():
            child.destroy()
        self._check_vars = []

    def _on_detect_retakes(self):
        settings = self._collect_retake_settings()
        self._retakes = find_retakes(self.cues, settings)
        self._clear_retake_list()
        if not self._retakes:
            ttk.Label(self.scroll.interior, text="未偵測到疑似重複片段。",
                      foreground="#666666").pack(anchor="w", padx=4, pady=4)
            self.cut_btn.configure(state="disabled")
            self._set_tab_status(TAB_RETAKES, "重複片段偵測完成，沒有找到候選。")
            return
        for retake in self._retakes:
            var = tk.BooleanVar(value=True)
            self._check_vars.append(var)
            text = (f"{retake['start']:.1f}s ~ {retake['end']:.1f}s"
                    f"（相似度 {retake['similarity'] * 100:.0f}%）\n"
                    f"這句：{retake['text']}\n"
                    f"後面較晚的版本：{retake['matched_text']}")
            ttk.Checkbutton(self.scroll.interior, text=text,
                            variable=var).pack(anchor="w", padx=4, pady=4,
                                               fill="x")
        self.cut_btn.configure(state="normal")
        self._set_tab_status(
            TAB_RETAKES,
            f"重複片段偵測完成，找到 {len(self._retakes)} 處候選（如下）。")

    def _selected_retakes(self):
        return [r for r, var in zip(self._retakes, self._check_vars)
                if var.get()]

    def _on_cut_retakes(self):
        if self.is_processing:
            return
        selected = self._selected_retakes()
        if not selected:
            messagebox.showinfo("提示", "沒有勾選任何要剪掉的重複片段。",
                                parent=self)
            return
        media_path = self._require_media("剪掉重複片段")
        if not media_path:
            return
        settings = self._collect_retake_settings()
        output = unique_path(suggest_retake_path(media_path))
        self._set_processing(True)
        threading.Thread(
            target=self._retakes_worker,
            args=(media_path, output, selected, settings), daemon=True).start()

    def _retakes_worker(self, media_path, output, selected, settings):
        try:
            def report(ratio, message):
                self.result_queue.put(("status", (message, ratio)))
            result = apply_retake_removal(
                media_path, self.cues, selected, output,
                settings=settings, progress_cb=report)
            result["source"] = media_path
            result["kind_label"] = "剪重複片段"
            result["report"] = format_retake_removal_report(result)
            self._export_cues(result, output)
            self.result_queue.put(("done", result))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("剪掉重複片段失敗")
            self.result_queue.put(("error", exc))

    # ==================================================================
    # 共用
    # ==================================================================
    def _active_tab_key(self):
        try:
            return (TAB_RETAKES
                    if self.notebook.index(self.notebook.select()) == 1
                    else TAB_GAPS)
        except tk.TclError:
            return TAB_GAPS

    def _set_tab_status(self, tab_key, message):
        """記下某個分頁的狀態訊息；正在看那一頁時才真的顯示出來。"""
        self._tab_status[tab_key] = message
        if self._active_tab_key() == tab_key:
            self.status_var.set(message)

    def _show_tab_status(self):
        """切換分頁時把狀態列換成該分頁自己的訊息。"""
        message = self._tab_status.get(self._active_tab_key())
        if message:
            self.status_var.set(message)

    def _save_config(self):
        try:
            save_config(self.config_data)
        except OSError:
            pass  # 存檔失敗不影響本次使用。

    def _choose_media(self):
        path = filedialog.askopenfilename(
            title="選擇要修剪的影音檔", filetypes=MEDIA_FILETYPES, parent=self)
        if path:
            self.media_var.set(path)

    def _require_media(self, action_label):
        """兩個分頁共用的前置檢查：影片存在、ffmpeg 可用。"""
        media_path = self.media_var.get().strip()
        if not media_path or not os.path.exists(media_path):
            messagebox.showinfo("提示", "請選擇有效的影音檔。", parent=self)
            return ""
        if not ffmpeg_available():
            show_friendly_error(
                self, f"{action_label}需要 ffmpeg",
                RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。"),
                on_install_ffmpeg=self._open_ffmpeg_installer)
            return ""
        return media_path

    def _export_cues(self, result, output):
        """剪後字幕與影片同名輸出，時間軸已對齊，不必手動調。"""
        base, _ = os.path.splitext(output)
        sub_path = unique_path(f"{base}.srt")
        export(result["cues"], sub_path,
               style=self.config_data.get("subtitle_style"))
        result["subtitle_path"] = sub_path

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.result_queue.get_nowait()
                if kind == "status":
                    message, ratio = payload
                    self.status_var.set(message)
                    if ratio is not None:
                        self.progress_var.set(ratio * 100.0)
                elif kind == "done":
                    self._on_trim_done(payload)
                elif kind == "error":
                    self._set_processing(False)
                    self.status_var.set("修剪失敗。")
                    show_friendly_error(
                        self, "自動修剪失敗", payload,
                        on_install_ffmpeg=self._open_ffmpeg_installer)
        except queue.Empty:
            pass
        self._poll_job = self.after(120, self._poll_queue)

    def _on_trim_done(self, result):
        """兩個分頁共用的完成處理：更新字幕、重跑偵測、問要不要接手。"""
        self._set_processing(False)
        self.cues = result["cues"]
        if self.on_done:
            self.on_done(result["cues"])
        label = result.get("kind_label", "修剪")
        self.status_var.set(result["report"])
        # 剪過之後兩個偵測器的結果都過期了（時間軸整個換掉），一起重跑。
        self._on_preview_gaps()
        self._on_detect_retakes()

        detail = (f"{result['report']}\n\n"
                  f"影片：{result['output']}\n"
                  f"字幕：{result['subtitle_path']}\n\n"
                  "字幕清單已更新為剪後的新時間軸；建議播放確認剪點。")
        if self.on_media:
            # v1.52.2 的產出匯流排：修剪版也是一代產出。問而不自動接手，
            # 理由同該版——剪輯是可能剪壞的處理，使用者該先看過再決定。
            if messagebox.askyesno(
                    f"{label}完成",
                    detail + "\n\n要把剪後的影片設為「目前影片」嗎？",
                    parent=self):
                self.on_media(result["output"], "trimmed", result["source"])
                self.media_var.set(result["output"])
                self.status_var.set(
                    f"已把{label}版設為目前影片："
                    f"{os.path.basename(result['output'])}")
            return
        messagebox.showinfo(f"{label}完成", detail, parent=self)

    def _open_ffmpeg_installer(self):
        def done():
            if self.ffmpeg_banner is not None:
                self.ffmpeg_banner.destroy()
                self.ffmpeg_banner = None
        FfmpegInstallDialog(self, on_done=done)

    def _set_processing(self, processing):
        self.is_processing = processing
        state = "disabled" if processing else "normal"
        # 兩個分頁的四顆動作鈕一起鎖——背景只跑得動一件事，另一個分頁的
        # 按鈕還能按的話，使用者會同時送出兩個 ffmpeg 工作。
        for button in (self.preview_btn, self.run_btn,
                       self.detect_btn, self.cut_btn):
            button.configure(state=state)
        if not processing:
            # 沒有偵測結果時輸出鈕本來就該是灰的，不要被解鎖一併打開。
            if not self._preview_gaps:
                self.run_btn.configure(state="disabled")
            if not self._retakes:
                self.cut_btn.configure(state="disabled")

    def _on_close(self):
        if getattr(self, "_poll_job", None):
            self.after_cancel(self._poll_job)
        self.destroy()
