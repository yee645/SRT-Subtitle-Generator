# -*- coding: utf-8 -*-
"""
封面健檢對話框：這張縮圖在手機上還看得清楚嗎？

YouTube 七成以上的觀看來自手機，而手機清單裡的縮圖只有大約 200 像素寬。
業界的自我檢查法就是「把封面縮到 10% 大小再看一眼」——本對話框把這件事
變成可量測的項目：畫面太雜（縮小後糊成一團）、對比太低（灰濛濛不顯眼）、
飽和度不足，加上解析度、16:9 比例與 2MB 檔案大小上限。

輸入是**任意圖片檔**，不限於本工具 v1.11.0 產生的封面候選圖——最常見的
情境其實是「我用 Canva／Photoshop 做好封面，這張能不能用」。一次可加入
多張，會依綜合分數排序並指出建議使用哪一張。
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
from subtitle.burner import ffmpeg_available
from subtitle.thumbcheck import (format_ranking_report, format_thumb_report,
                                 rank_thumbnails, resolve_thumbcheck_settings)

logger = logging.getLogger(__name__)

IMAGE_FILETYPES = [
    ("圖片檔", "*.png *.jpg *.jpeg *.webp *.bmp"),
    ("所有檔案", "*.*"),
]


class ThumbCheckDialog(tk.Toplevel):
    """封面健檢視窗：加入封面圖、調門檻、一鍵檢查並比較候選圖。"""

    def __init__(self, master, config_data, image_paths=None):
        super().__init__(master)
        self.title("封面健檢：這張縮圖在手機上看得清楚嗎")
        self.geometry("720x760")
        self.minsize(660, 640)
        self.transient(master)

        self.config_data = config_data
        self.result_queue = queue.Queue()
        self.is_processing = False
        self.report_text = ""

        settings = resolve_thumbcheck_settings(config_data)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body, anchor="w", justify="left", wraplength=660,
            foreground="#666666",
            text="YouTube 七成以上的觀看來自手機，而手機清單裡的縮圖只有大約 "
                 "200 像素寬。畫面太雜、對比太低、灰濛濛的封面在那個尺寸下"
                 "會直接被滑過去——這裡把「縮小後還看不看得清」變成可量測的"
                 "檢查。加入多張候選圖時會依分數排序並指出該用哪一張。",
        ).pack(fill="x", pady=(0, 8))

        self.ffmpeg_banner = None
        if not ffmpeg_available():
            banner = tk.Frame(body, bg="#fdf3d7")
            banner.pack(fill="x", pady=(0, 8))
            tk.Label(
                banner, bg="#fdf3d7", fg="#8a5a00", anchor="w",
                text="⚠ 尚未安裝 ffmpeg：封面健檢需要它才能量測圖片。",
            ).pack(side="left", padx=6, pady=4)
            ttk.Button(banner, text="自動安裝 ffmpeg",
                       command=self._open_ffmpeg_installer).pack(
                side="right", padx=6, pady=2)
            self.ffmpeg_banner = banner

        files_frame = ttk.LabelFrame(body, text="要檢查的封面圖",
                                     padding=(10, 6))
        files_frame.pack(fill="x")
        list_row = ttk.Frame(files_frame)
        list_row.pack(fill="both", expand=True)
        self.file_list = tk.Listbox(list_row, height=5,
                                    font=("Microsoft JhengHei", 9))
        list_scroll = ttk.Scrollbar(list_row, orient="vertical",
                                    command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=list_scroll.set)
        self.file_list.pack(side="left", fill="both", expand=True)
        list_scroll.pack(side="right", fill="y")
        # 清單顯示檔名（完整路徑會被截斷成看不出是哪一張），完整路徑另存
        # 於 self._paths 作為實際量測用的資料來源。
        self._paths = []
        for path in image_paths or []:
            self._append_path(path)

        btn_row = ttk.Frame(files_frame)
        btn_row.pack(fill="x", pady=(6, 0))
        ttk.Button(btn_row, text="加入圖片...",
                   command=self._add_files).pack(side="left")
        ttk.Button(btn_row, text="移除選取",
                   command=self._remove_selected).pack(side="left", padx=(6, 0))
        ttk.Button(btn_row, text="全部清除",
                   command=self._clear_files).pack(side="left", padx=(6, 0))

        options = ttk.LabelFrame(body, text="判定門檻（自動記憶）",
                                 padding=(10, 6))
        options.pack(fill="x", pady=(8, 0))
        row1 = ttk.Frame(options)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="手機縮圖寬度:").pack(side="left")
        self.width_var = tk.IntVar(value=settings["mobile_width"])
        tk.Spinbox(row1, from_=80, to=640, increment=20, width=6,
                   textvariable=self.width_var).pack(side="left", padx=(2, 2))
        ttk.Label(row1, text="像素").pack(side="left", padx=(0, 12))
        ttk.Label(row1, text="細節保留下限:").pack(side="left")
        self.detail_var = tk.DoubleVar(value=settings["min_detail_keep"])
        tk.Spinbox(row1, from_=0.05, to=1.0, increment=0.05, width=6,
                   textvariable=self.detail_var, format="%.2f").pack(
            side="left", padx=(2, 2))
        row2 = ttk.Frame(options)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="對比下限:").pack(side="left")
        self.contrast_var = tk.DoubleVar(value=settings["min_contrast"])
        tk.Spinbox(row2, from_=10, to=200, increment=5, width=6,
                   textvariable=self.contrast_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row2, text="飽和度下限:").pack(side="left", padx=(12, 0))
        self.saturation_var = tk.DoubleVar(value=settings["min_saturation"])
        tk.Spinbox(row2, from_=0, to=120, increment=5, width=6,
                   textvariable=self.saturation_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row2, text="檔案上限:").pack(side="left", padx=(12, 0))
        self.filesize_var = tk.DoubleVar(value=settings["max_file_mb"])
        tk.Spinbox(row2, from_=0.5, to=10.0, increment=0.5, width=6,
                   textvariable=self.filesize_var, format="%.1f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row2, text="MB").pack(side="left")
        ttk.Label(
            options, foreground="#666666", anchor="w", justify="left",
            wraplength=660,
            text="「細節保留」是把圖縮到手機尺寸再放大回來、比較前後的邊緣"
                 "強度——大色塊構成的封面幾乎不掉，細碎雜訊型的封面會崩到"
                 "接近 0，也就是縮小後糊成一團。",
        ).pack(fill="x", pady=(2, 0))

        self.status_var = tk.StringVar(
            value="加入封面圖後按「開始健檢」，不會改動任何檔案。")
        ttk.Label(body, textvariable=self.status_var, foreground="#1a5fb4",
                  wraplength=660, justify="left").pack(fill="x", pady=(8, 0))
        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(body, mode="determinate", maximum=100.0,
                        variable=self.progress_var).pack(fill="x", pady=(4, 6))

        report_frame = ttk.LabelFrame(body, text="健檢報告", padding=(6, 6))
        report_frame.pack(fill="both", expand=True)
        self.report = tk.Text(report_frame, wrap="word", state="disabled",
                              font=("Microsoft JhengHei", 10), height=10)
        # 「建議：」這種長句換行後要縮排，否則看起來像新的一個項目。
        self.report.tag_configure("report", lmargin2=28)
        scrollbar = ttk.Scrollbar(report_frame, orient="vertical",
                                  command=self.report.yview)
        self.report.configure(yscrollcommand=scrollbar.set)
        self.report.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 0))
        self.run_btn = ttk.Button(buttons, text="開始健檢",
                                  command=self._on_run)
        self.run_btn.pack(side="left")
        self.copy_btn = ttk.Button(buttons, text="複製報告", state="disabled",
                                   command=self._on_copy)
        self.copy_btn.pack(side="left", padx=(6, 0))
        self.save_btn = ttk.Button(buttons, text="另存報告...",
                                   state="disabled", command=self._on_save)
        self.save_btn.pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="關閉", command=self._on_close).pack(
            side="right")

        self._poll_job = self.after(120, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    def _open_ffmpeg_installer(self):
        FfmpegInstallDialog(self, on_done=self._on_ffmpeg_ready)

    def _on_ffmpeg_ready(self):
        if self.ffmpeg_banner is not None and ffmpeg_available():
            self.ffmpeg_banner.destroy()
            self.ffmpeg_banner = None

    def _append_path(self, path):
        """加入一張圖：清單顯示檔名，完整路徑存進 self._paths。"""
        if path in self._paths:
            return
        self._paths.append(path)
        self.file_list.insert("end", os.path.basename(path))

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="選擇封面圖片", filetypes=IMAGE_FILETYPES, parent=self)
        for path in paths:
            self._append_path(path)

    def _remove_selected(self):
        for index in reversed(self.file_list.curselection()):
            self.file_list.delete(index)
            del self._paths[index]

    def _clear_files(self):
        self.file_list.delete(0, "end")
        self._paths = []

    def _collect_settings(self):
        def safe(var, fallback, cast=float):
            try:
                return cast(var.get())
            except (tk.TclError, ValueError):
                return fallback
        self.config_data["thumbcheck"] = {
            "mobile_width": safe(self.width_var, 200, cast=int),
            "min_detail_keep": safe(self.detail_var, 0.35),
            "min_contrast": safe(self.contrast_var, 40.0),
            "min_saturation": safe(self.saturation_var, 15.0),
            "max_file_mb": safe(self.filesize_var, 2.0),
        }
        try:
            save_config(self.config_data)
        except OSError:
            pass  # 存檔失敗不影響本次使用。
        return self.config_data

    # ------------------------------------------------------------------
    def _on_run(self):
        if self.is_processing:
            return
        if not self._paths:
            messagebox.showinfo("提示", "請先加入至少一張封面圖片。",
                                parent=self)
            return
        if not ffmpeg_available():
            show_friendly_error(
                self, RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。"),
                title="封面健檢需要 ffmpeg")
            return
        config = self._collect_settings()
        self.is_processing = True
        self.run_btn.configure(state="disabled")
        self.status_var.set("量測中...")
        self.progress_var.set(0.0)
        threading.Thread(target=self._worker, args=(list(self._paths), config),
                         daemon=True).start()

    def _worker(self, paths, config):
        try:
            def progress(ratio, message):
                self.result_queue.put(("status", (message, ratio)))

            settings = resolve_thumbcheck_settings(config)
            results = rank_thumbnails(paths, config, progress_cb=progress)
            parts = [format_thumb_report(r, settings) for r in results]
            if len(results) > 1:
                parts.append(format_ranking_report(results, settings))
            self.result_queue.put(("done", ("\n\n".join(parts), results)))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("封面健檢失敗")
            self.result_queue.put(("error", exc))

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
                    text, results = payload
                    self._finish(text, results)
                elif kind == "error":
                    self._fail(payload)
        except queue.Empty:
            pass
        self._poll_job = self.after(120, self._poll_queue)

    def _finish(self, text, results):
        self.is_processing = False
        self.run_btn.configure(state="normal")
        self.progress_var.set(100.0)
        self.report_text = text
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", text, "report")
        self.report.configure(state="disabled")
        self.copy_btn.configure(state="normal")
        self.save_btn.configure(state="normal")
        usable = [r for r in results if r.get("ok") and not r.get("error")]
        if not results:
            self.status_var.set("沒有可檢查的圖片。")
        elif len(results) == 1:
            self.status_var.set(
                "這張封面可以使用。" if usable
                else "這張封面在手機上會吃虧，詳見報告。")
        elif usable:
            best = (usable[0].get("metrics") or {}).get("name", "")
            self.status_var.set(
                f"共 {len(results)} 張，{len(usable)} 張通過；"
                f"建議使用「{best}」。")
        else:
            self.status_var.set(
                f"共 {len(results)} 張，沒有一張通過健檢——建議重做封面。")

    def _fail(self, exc):
        self.is_processing = False
        self.run_btn.configure(state="normal")
        self.progress_var.set(0.0)
        self.status_var.set("健檢失敗。")
        show_friendly_error(self, exc, title="封面健檢失敗")

    def _on_copy(self):
        if not self.report_text:
            return
        self.clipboard_clear()
        self.clipboard_append(self.report_text)
        self.status_var.set("報告已複製到剪貼簿。")

    def _on_save(self):
        if not self.report_text:
            return
        path = filedialog.asksaveasfilename(
            title="另存封面健檢報告", defaultextension=".txt",
            initialfile="封面健檢.txt",
            filetypes=[("純文字檔", "*.txt")], parent=self)
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(self.report_text + "\n")
        except OSError as exc:
            messagebox.showerror("儲存失敗", str(exc), parent=self)
            return
        self.status_var.set(f"報告已儲存：{path}")

    def _on_close(self):
        if self._poll_job is not None:
            self.after_cancel(self._poll_job)
            self._poll_job = None
        self.destroy()
