# -*- coding: utf-8 -*-
"""
系列一致性對話框：比對同一批（同系列）影片彼此之間是否一致。

批次製作時每一支單獨看都沒問題，彼此之間卻可能不一致——觀眾連看同一
系列時就會遇到某一集突然要調大音量、某一集畫面明顯偏暗、某一集解析度
掉下來。本對話框以整批的中位數為基準，找出偏離整批的那幾支。

與「上片前健檢」的差別：那邊是拿固定門檻檢查單一支影片合不合格，
這邊比的是多支影片彼此之間一不一致。
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
from subtitle.seriescheck import (analyze_series, format_series_report,
                                  resolve_seriescheck_settings)

logger = logging.getLogger(__name__)

MEDIA_FILETYPES = [
    ("影片與音訊檔", "*.mp4 *.mkv *.mov *.avi *.flv *.mp3 *.wav *.m4a *.aac"),
    ("所有檔案", "*.*"),
]


class SeriesCheckDialog(tk.Toplevel):
    """系列一致性視窗：一次比對多支同系列影片的規格與畫面／聲音一致性。"""

    def __init__(self, master, config_data, media_paths=None):
        super().__init__(master)
        self.title("系列一致性：比對同一批影片彼此之間是否一致")
        self.geometry("720x640")
        self.minsize(660, 560)
        self.transient(master)

        self.config_data = config_data
        self.result_queue = queue.Queue()
        self.is_processing = False

        settings = resolve_seriescheck_settings(config_data)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        self.ffmpeg_banner = None
        if not ffmpeg_available():
            banner = tk.Frame(body, bg="#fdf3d7")
            banner.pack(fill="x", pady=(0, 8))
            tk.Label(
                banner, bg="#fdf3d7", fg="#8a5a00", anchor="w",
                text="⚠ 尚未安裝 ffmpeg：系列一致性檢查需要它才能量測。",
            ).pack(side="left", padx=6, pady=4)
            ttk.Button(banner, text="自動安裝 ffmpeg",
                      command=self._open_ffmpeg_installer).pack(
                side="right", padx=6, pady=2)
            self.ffmpeg_banner = banner

        files_frame = ttk.LabelFrame(
            body, text="要比對的影片（同一系列，至少 2 支）", padding=(10, 6))
        files_frame.pack(fill="both", expand=False)
        list_row = ttk.Frame(files_frame)
        list_row.pack(fill="both", expand=True)
        self.file_list = tk.Listbox(list_row, height=6,
                                    font=("Microsoft JhengHei", 9))
        list_scroll = ttk.Scrollbar(list_row, orient="vertical",
                                    command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=list_scroll.set)
        self.file_list.pack(side="left", fill="both", expand=True)
        list_scroll.pack(side="right", fill="y")
        # 清單顯示檔名（完整路徑會被截斷成看不出是哪一支），完整路徑
        # 另存於 self._paths 作為實際比對用的資料來源。
        self._paths = []
        for path in media_paths or []:
            self._append_path(path)

        btn_row = ttk.Frame(files_frame)
        btn_row.pack(fill="x", pady=(6, 0))
        ttk.Button(btn_row, text="加入影片...", command=self._add_files).pack(
            side="left")
        ttk.Button(btn_row, text="移除選取",
                   command=self._remove_selected).pack(side="left", padx=(6, 0))
        ttk.Button(btn_row, text="全部清除", command=self._clear_files).pack(
            side="left", padx=(6, 0))

        options = ttk.LabelFrame(body, text="容許差異（自動記憶）",
                                 padding=(10, 6))
        options.pack(fill="x", pady=(8, 0))
        row = ttk.Frame(options)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="響度差異:").pack(side="left")
        self.loudness_var = tk.DoubleVar(value=settings["loudness_tolerance"])
        tk.Spinbox(row, from_=0.5, to=8.0, increment=0.5, width=5,
                   textvariable=self.loudness_var, format="%.1f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row, text="LU").pack(side="left", padx=(0, 12))
        ttk.Label(row, text="亮度差異:").pack(side="left")
        self.luma_var = tk.DoubleVar(value=settings["luma_tolerance"])
        tk.Spinbox(row, from_=10, to=80, increment=5, width=5,
                   textvariable=self.luma_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row, text="（0~255）").pack(side="left", padx=(0, 12))
        ttk.Label(row, text="色調差異:").pack(side="left")
        self.cast_var = tk.DoubleVar(value=settings["cast_tolerance"])
        tk.Spinbox(row, from_=3, to=30, increment=1, width=5,
                   textvariable=self.cast_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(
            options, foreground="#666666", anchor="w", justify="left",
            wraplength=640,
            text="以整批的中位數為基準，找出偏離整批的那幾支——整批一致但"
                 "整批都偏暗時不會標記（那是風格，不是失誤）。",
        ).pack(fill="x", pady=(4, 0))

        self.status_var = tk.StringVar(
            value="加入同一系列的多支影片後按「開始比對」，掃描不會改動原始檔案。")
        ttk.Label(body, textvariable=self.status_var, foreground="#1a5fb4",
                  wraplength=660, justify="left").pack(fill="x", pady=(8, 0))
        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(body, mode="determinate", maximum=100.0,
                        variable=self.progress_var).pack(fill="x", pady=(4, 6))

        report_frame = ttk.LabelFrame(body, text="比對報告", padding=(6, 6))
        report_frame.pack(fill="both", expand=True)
        self.report = tk.Text(report_frame, wrap="word", state="disabled",
                              font=("Microsoft JhengHei", 10), height=10)
        self.report.tag_configure("report", lmargin2=28)
        scrollbar = ttk.Scrollbar(report_frame, orient="vertical",
                                  command=self.report.yview)
        self.report.configure(yscrollcommand=scrollbar.set)
        self.report.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 0))
        self.run_btn = ttk.Button(buttons, text="開始比對",
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
    def _append_path(self, path):
        """加入一個檔案：清單顯示檔名，完整路徑存進 self._paths。"""
        if path in self._paths:
            return
        self._paths.append(path)
        self.file_list.insert("end", os.path.basename(path))

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="選擇同系列的影片", filetypes=MEDIA_FILETYPES, parent=self)
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
        def safe(var, fallback):
            try:
                return float(var.get())
            except (tk.TclError, ValueError):
                return fallback
        self.config_data["seriescheck"] = {
            "loudness_tolerance": safe(self.loudness_var, 2.0),
            "luma_tolerance": safe(self.luma_var, 25.0),
            "cast_tolerance": safe(self.cast_var, 8.0),
        }
        try:
            save_config(self.config_data)
        except OSError:
            pass  # 存檔失敗不影響本次使用。
        return self.config_data

    def _on_run(self):
        if self.is_processing:
            return
        paths = list(self._paths)
        if len(paths) < 2:
            messagebox.showinfo(
                "提示",
                "系列一致性檢查需要至少 2 支影片才有比較基準。\n"
                "若想檢查單一支影片本身合不合格，請改用「上片前健檢」。",
                parent=self)
            return
        if not ffmpeg_available():
            show_friendly_error(
                self, "系列一致性檢查需要 ffmpeg",
                RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。"),
                on_install_ffmpeg=self._open_ffmpeg_installer)
            return
        config = self._collect_settings()
        self._set_processing(True)
        threading.Thread(target=self._run_worker, args=(paths, config),
                         daemon=True).start()

    def _run_worker(self, paths, config):
        try:
            def progress(ratio, message):
                self.result_queue.put(("status", (message, ratio)))
            result = analyze_series(paths, config, progress_cb=progress)
            self.result_queue.put(("done", result))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("系列一致性檢查失敗")
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
                    self._set_processing(False)
                    self._show_report(payload)
                elif kind == "error":
                    self._set_processing(False)
                    self.status_var.set("比對失敗。")
                    show_friendly_error(
                        self, "系列一致性檢查失敗", payload,
                        on_install_ffmpeg=self._open_ffmpeg_installer)
        except queue.Empty:
            pass
        self._poll_job = self.after(120, self._poll_queue)

    def _show_report(self, result):
        text = format_series_report(result)
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", text, "report")
        self.report.configure(state="disabled")
        self.copy_btn.configure(state="normal")
        self.save_btn.configure(state="normal")
        issues = [f for f in result.get("findings", [])
                  if f["level"] != "good"]
        if issues:
            self.status_var.set(
                f"比對完成：{len(issues)} 項在整批之間不一致，詳見報告。")
        else:
            self.status_var.set("比對完成：整批各項指標彼此一致。")

    def _on_copy(self):
        text = self.report.get("1.0", "end").strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("報告已複製到剪貼簿。")

    def _on_save(self):
        text = self.report.get("1.0", "end").strip()
        if not text:
            return
        path = filedialog.asksaveasfilename(
            title="儲存系列一致性報告", defaultextension=".txt",
            initialfile="系列一致性檢查.txt",
            filetypes=[("文字檔", "*.txt")], parent=self)
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(text)
            self.status_var.set(f"報告已儲存：{os.path.basename(path)}")
        except OSError as exc:
            show_friendly_error(self, "儲存報告失敗", exc)

    def _open_ffmpeg_installer(self):
        def done():
            if self.ffmpeg_banner is not None:
                self.ffmpeg_banner.destroy()
                self.ffmpeg_banner = None
        FfmpegInstallDialog(self, on_done=done)

    def _set_processing(self, processing):
        self.is_processing = processing
        self.run_btn.configure(state="disabled" if processing else "normal")

    def _on_close(self):
        if getattr(self, "_poll_job", None):
            self.after_cancel(self._poll_job)
        self.destroy()
