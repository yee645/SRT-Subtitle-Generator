# -*- coding: utf-8 -*-
"""
品牌套版對話框：一次設定片頭／片尾與浮水印，之後每支影片一鍵套用。

調研顯示創作者常抱怨「每支影片都要重複手動加一次片頭片尾、調一次
浮水印位置大小」；本對話框把這些設定存進 config.json，選好素材後
按「輸出套版影片」即可，不必再進剪輯軟體重複同一套操作。
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
from subtitle.branding import (POSITION_LABELS, apply_branding,
                               resolve_branding_settings, suggest_output_path)
from subtitle.burner import ffmpeg_available
from subtitle.pipeline import unique_path

logger = logging.getLogger(__name__)

MEDIA_FILETYPES = [
    ("影片檔", "*.mp4 *.mkv *.mov *.avi *.flv"),
    ("所有檔案", "*.*"),
]
IMAGE_FILETYPES = [
    ("圖片檔", "*.png *.jpg *.jpeg *.bmp"),
    ("所有檔案", "*.*"),
]

_POSITION_VALUES = list(POSITION_LABELS.values())


class BrandingDialog(tk.Toplevel):
    """品牌套版視窗：設定片頭／片尾／浮水印，一鍵輸出套版影片。"""

    def __init__(self, master, config_data, media_path=""):
        super().__init__(master)
        self.title("品牌套版：片頭／片尾接續、浮水印疊加")
        self.geometry("640x560")
        self.minsize(600, 520)
        self.transient(master)

        self.config_data = config_data
        self.result_queue = queue.Queue()
        self.is_processing = False

        settings = resolve_branding_settings(config_data)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        row_file = ttk.Frame(body)
        row_file.pack(fill="x")
        ttk.Label(row_file, text="來源影片：").pack(side="left")
        self.media_var = tk.StringVar(value=media_path)
        ttk.Entry(row_file, textvariable=self.media_var).pack(
            side="left", fill="x", expand=True, padx=(6, 4))
        ttk.Button(row_file, text="瀏覽...", width=8,
                   command=self._choose_media).pack(side="left")

        self.ffmpeg_banner = None
        if not ffmpeg_available():
            banner = tk.Frame(body, bg="#fdf3d7")
            banner.pack(fill="x", pady=(8, 0))
            tk.Label(
                banner, bg="#fdf3d7", fg="#8a5a00", anchor="w",
                text="⚠ 尚未安裝 ffmpeg：品牌套版需要它才能處理影片。",
            ).pack(side="left", padx=6, pady=4)
            tk.Button(banner, text="自動安裝 ffmpeg",
                      command=self._open_ffmpeg_installer).pack(
                side="right", padx=6, pady=2)
            self.ffmpeg_banner = banner

        intro_frame = ttk.LabelFrame(body, text="片頭／片尾（自動記憶，留空不套用）",
                                     padding=(10, 6))
        intro_frame.pack(fill="x", pady=(8, 0))
        row_intro = ttk.Frame(intro_frame)
        row_intro.pack(fill="x", pady=2)
        ttk.Label(row_intro, text="片頭：", width=6).pack(side="left")
        self.intro_var = tk.StringVar(value=settings["intro_path"])
        ttk.Entry(row_intro, textvariable=self.intro_var).pack(
            side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(row_intro, text="瀏覽...", width=8,
                   command=self._choose_intro).pack(side="left", padx=(0, 4))
        ttk.Button(row_intro, text="清除", width=6,
                   command=lambda: self.intro_var.set("")).pack(side="left")
        row_outro = ttk.Frame(intro_frame)
        row_outro.pack(fill="x", pady=2)
        ttk.Label(row_outro, text="片尾：", width=6).pack(side="left")
        self.outro_var = tk.StringVar(value=settings["outro_path"])
        ttk.Entry(row_outro, textvariable=self.outro_var).pack(
            side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(row_outro, text="瀏覽...", width=8,
                   command=self._choose_outro).pack(side="left", padx=(0, 4))
        ttk.Button(row_outro, text="清除", width=6,
                   command=lambda: self.outro_var.set("")).pack(side="left")

        wm_frame = ttk.LabelFrame(body, text="浮水印／Logo（自動記憶，留空不套用）",
                                  padding=(10, 6))
        wm_frame.pack(fill="x", pady=(8, 0))
        row_wm = ttk.Frame(wm_frame)
        row_wm.pack(fill="x", pady=2)
        ttk.Label(row_wm, text="圖片：", width=6).pack(side="left")
        self.watermark_var = tk.StringVar(value=settings["watermark_path"])
        ttk.Entry(row_wm, textvariable=self.watermark_var).pack(
            side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(row_wm, text="瀏覽...", width=8,
                   command=self._choose_watermark).pack(side="left", padx=(0, 4))
        ttk.Button(row_wm, text="清除", width=6,
                   command=lambda: self.watermark_var.set("")).pack(side="left")

        row_wm2 = ttk.Frame(wm_frame)
        row_wm2.pack(fill="x", pady=(6, 2))
        ttk.Label(row_wm2, text="位置：").pack(side="left")
        self.position_var = tk.StringVar(
            value=POSITION_LABELS.get(settings["watermark_position"], "右下"))
        ttk.Combobox(
            row_wm2, textvariable=self.position_var, state="readonly",
            width=6, values=_POSITION_VALUES,
        ).pack(side="left", padx=(2, 10))
        ttk.Label(row_wm2, text="大小(佔畫面寬%):").pack(side="left")
        self.scale_var = tk.DoubleVar(
            value=round(settings["watermark_scale"] * 100))
        tk.Spinbox(row_wm2, from_=5, to=50, increment=1, width=4,
                   textvariable=self.scale_var).pack(side="left", padx=(2, 2))
        ttk.Label(row_wm2, text="%").pack(side="left")

        row_wm3 = ttk.Frame(wm_frame)
        row_wm3.pack(fill="x", pady=2)
        ttk.Label(row_wm3, text="透明度:").pack(side="left")
        self.opacity_var = tk.DoubleVar(value=settings["watermark_opacity"])
        tk.Spinbox(row_wm3, from_=0.1, to=1.0, increment=0.05, width=5,
                   textvariable=self.opacity_var, format="%.2f").pack(
            side="left", padx=(2, 14))
        ttk.Label(row_wm3, text="邊緣留白(px):").pack(side="left")
        self.margin_var = tk.DoubleVar(value=settings["watermark_margin"])
        tk.Spinbox(row_wm3, from_=0, to=200, increment=4, width=5,
                   textvariable=self.margin_var, format="%.0f").pack(
            side="left", padx=(2, 2))

        self.status_var = tk.StringVar(
            value="設定好片頭／片尾／浮水印其中至少一項後，按「輸出套版影片」。")
        ttk.Label(body, textvariable=self.status_var,
                  foreground="#1a5fb4", wraplength=600, justify="left").pack(
            fill="x", pady=(10, 0))
        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(body, mode="determinate", maximum=100.0,
                        variable=self.progress_var).pack(
            fill="x", pady=(4, 6))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 0))
        self.run_btn = ttk.Button(buttons, text="輸出套版影片",
                                  command=self._on_run)
        self.run_btn.pack(side="left")
        ttk.Button(buttons, text="關閉", command=self._on_close).pack(
            side="right")

        self._poll_job = self.after(120, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _choose_media(self):
        path = filedialog.askopenfilename(
            title="選擇來源影片", filetypes=MEDIA_FILETYPES, parent=self)
        if path:
            self.media_var.set(path)

    def _choose_intro(self):
        path = filedialog.askopenfilename(
            title="選擇片頭影片", filetypes=MEDIA_FILETYPES, parent=self)
        if path:
            self.intro_var.set(path)

    def _choose_outro(self):
        path = filedialog.askopenfilename(
            title="選擇片尾影片", filetypes=MEDIA_FILETYPES, parent=self)
        if path:
            self.outro_var.set(path)

    def _choose_watermark(self):
        path = filedialog.askopenfilename(
            title="選擇浮水印圖片", filetypes=IMAGE_FILETYPES, parent=self)
        if path:
            self.watermark_var.set(path)

    def _position_key(self):
        label = self.position_var.get()
        for key, value in POSITION_LABELS.items():
            if value == label:
                return key
        return "bottom_right"

    def _collect_settings(self):
        def safe(var, fallback):
            try:
                return float(var.get())
            except (tk.TclError, ValueError):
                return fallback
        self.config_data["branding"] = {
            "intro_path": self.intro_var.get().strip(),
            "outro_path": self.outro_var.get().strip(),
            "watermark_path": self.watermark_var.get().strip(),
            "watermark_position": self._position_key(),
            "watermark_opacity": safe(self.opacity_var, 0.85),
            "watermark_scale": safe(self.scale_var, 15.0) / 100.0,
            "watermark_margin": safe(self.margin_var, 24.0),
        }
        try:
            save_config(self.config_data)
        except OSError:
            pass
        return resolve_branding_settings(self.config_data)

    def _on_run(self):
        if self.is_processing:
            return
        media_path = self.media_var.get().strip()
        if not media_path or not os.path.exists(media_path):
            messagebox.showinfo("提示", "請選擇有效的來源影片。", parent=self)
            return
        if not ffmpeg_available():
            show_friendly_error(
                self, "品牌套版需要 ffmpeg",
                RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。"),
                on_install_ffmpeg=self._open_ffmpeg_installer)
            return
        settings = self._collect_settings()
        if not (settings["intro_path"] or settings["outro_path"]
                or settings["watermark_path"]):
            messagebox.showinfo(
                "提示", "請至少設定片頭、片尾或浮水印其中一項。", parent=self)
            return
        output = unique_path(suggest_output_path(media_path))
        self._set_processing(True)
        threading.Thread(
            target=self._run_worker, args=(media_path, output, settings),
            daemon=True).start()

    def _run_worker(self, media_path, output, settings):
        try:
            def report(ratio, message):
                self.result_queue.put(("status", (message, ratio)))
            apply_branding(media_path, output, settings=settings,
                          progress_cb=report)
            self.result_queue.put(("done", output))
        except Exception as exc:
            logger.exception("品牌套版失敗")
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
                    self.status_var.set(f"套版完成：{payload}")
                    messagebox.showinfo(
                        "套版完成", f"已輸出套版影片：\n{payload}", parent=self)
                elif kind == "error":
                    self._set_processing(False)
                    self.status_var.set("套版失敗。")
                    show_friendly_error(
                        self, "品牌套版失敗", payload,
                        on_install_ffmpeg=self._open_ffmpeg_installer)
        except queue.Empty:
            pass
        self._poll_job = self.after(120, self._poll_queue)

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
