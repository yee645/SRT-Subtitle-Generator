# -*- coding: utf-8 -*-
"""
音訊轉視覺化影片對話框：純音訊素材一鍵轉成可上傳的波形／頻譜影片。

調研顯示 Podcast、廣播剪輯、純錄音訪談這類創作者手上常常只有音訊
檔，YouTube 等平台的慣例卻是上傳「影片」；本對話框把音訊轉成附
波形或頻譜視覺化的 mp4，轉出後可直接接上本工具既有的轉錄、字幕
燒錄、翻譯等整條管線。
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
from subtitle.audiovis import (resolve_audiovis_settings, render_audio_video,
                               suggest_output_path)
from subtitle.burner import ffmpeg_available
from subtitle.pipeline import unique_path

logger = logging.getLogger(__name__)

AUDIO_FILETYPES = [
    ("音訊檔", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg"),
    ("所有檔案", "*.*"),
]
IMAGE_FILETYPES = [
    ("圖片檔", "*.png *.jpg *.jpeg *.bmp"),
    ("所有檔案", "*.*"),
]
_MODE_LABELS = {"waveform": "波形", "spectrum": "頻譜"}
_MODE_VALUES = list(_MODE_LABELS.values())


class AudioVisDialog(tk.Toplevel):
    """音訊轉視覺化影片視窗：設定波形／頻譜樣式，一鍵輸出可上傳影片。"""

    def __init__(self, master, config_data, media_path=""):
        super().__init__(master)
        self.title("音訊轉影片：波形／頻譜視覺化")
        self.geometry("620x400")
        self.minsize(580, 380)
        self.transient(master)

        self.config_data = config_data
        self.result_queue = queue.Queue()
        self.is_processing = False

        settings = resolve_audiovis_settings(config_data)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        row_file = ttk.Frame(body)
        row_file.pack(fill="x")
        ttk.Label(row_file, text="來源音訊：").pack(side="left")
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
                text="⚠ 尚未安裝 ffmpeg：轉換視覺化影片需要它。",
            ).pack(side="left", padx=6, pady=4)
            ttk.Button(banner, text="自動安裝 ffmpeg",
                      command=self._open_ffmpeg_installer).pack(
                side="right", padx=6, pady=2)
            self.ffmpeg_banner = banner

        style_frame = ttk.LabelFrame(
            body, text="視覺化樣式（自動記憶）", padding=(10, 6))
        style_frame.pack(fill="x", pady=(8, 0))

        row_mode = ttk.Frame(style_frame)
        row_mode.pack(fill="x", pady=2)
        ttk.Label(row_mode, text="樣式：").pack(side="left")
        self.mode_var = tk.StringVar(
            value=_MODE_LABELS.get(settings["mode"], "波形"))
        ttk.Combobox(
            row_mode, textvariable=self.mode_var, state="readonly",
            width=8, values=_MODE_VALUES,
        ).pack(side="left", padx=(2, 14))
        ttk.Label(row_mode, text="波形顏色（#RRGGBB）：").pack(side="left")
        self.color_var = tk.StringVar(value=settings["color"])
        ttk.Entry(row_mode, textvariable=self.color_var, width=10).pack(
            side="left", padx=(2, 2))

        row_size = ttk.Frame(style_frame)
        row_size.pack(fill="x", pady=2)
        ttk.Label(row_size, text="解析度：").pack(side="left")
        self.width_var = tk.IntVar(value=settings["width"])
        tk.Spinbox(row_size, from_=640, to=3840, increment=160, width=6,
                   textvariable=self.width_var).pack(side="left", padx=(2, 2))
        ttk.Label(row_size, text="x").pack(side="left")
        self.height_var = tk.IntVar(value=settings["height"])
        tk.Spinbox(row_size, from_=360, to=2160, increment=90, width=6,
                   textvariable=self.height_var).pack(side="left", padx=(2, 2))

        bg_frame = ttk.LabelFrame(
            body, text="背景圖片（自動記憶，留空輸出純黑底全畫面視覺化）",
            padding=(10, 6))
        bg_frame.pack(fill="x", pady=(8, 0))
        row_bg = ttk.Frame(bg_frame)
        row_bg.pack(fill="x", pady=2)
        self.bg_var = tk.StringVar(value=settings["background_image"])
        ttk.Entry(row_bg, textvariable=self.bg_var).pack(
            side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(row_bg, text="瀏覽...", width=8,
                   command=self._choose_background).pack(side="left", padx=(0, 4))
        ttk.Button(row_bg, text="清除", width=6,
                   command=lambda: self.bg_var.set("")).pack(side="left")
        ttk.Label(
            bg_frame, foreground="#666666", anchor="w", justify="left",
            text="有背景圖時，視覺化縮成下緣一條色帶疊加（例如節目封面）；"
                 "背景圖會裁切置中填滿整個畫面。",
        ).pack(fill="x", pady=(4, 0))

        self.status_var = tk.StringVar(
            value="選好音訊素材後按「輸出視覺化影片」；輸出檔可直接接上"
                 "轉錄、字幕燒錄等既有流程。")
        ttk.Label(body, textvariable=self.status_var,
                  foreground="#1a5fb4", wraplength=580, justify="left").pack(
            fill="x", pady=(10, 0))
        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(body, mode="determinate", maximum=100.0,
                        variable=self.progress_var).pack(
            fill="x", pady=(4, 6))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 0))
        self.run_btn = ttk.Button(buttons, text="輸出視覺化影片",
                                  command=self._on_run)
        self.run_btn.pack(side="left")
        ttk.Button(buttons, text="關閉", command=self._on_close).pack(
            side="right")

        self._poll_job = self.after(120, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _choose_media(self):
        path = filedialog.askopenfilename(
            title="選擇來源音訊", filetypes=AUDIO_FILETYPES, parent=self)
        if path:
            self.media_var.set(path)

    def _choose_background(self):
        path = filedialog.askopenfilename(
            title="選擇背景圖片", filetypes=IMAGE_FILETYPES, parent=self)
        if path:
            self.bg_var.set(path)

    def _mode_key(self):
        label = self.mode_var.get()
        for key, value in _MODE_LABELS.items():
            if value == label:
                return key
        return "waveform"

    def _collect_settings(self):
        def safe_int(var, fallback):
            try:
                return int(var.get())
            except (tk.TclError, ValueError):
                return fallback
        self.config_data["audiovis"] = {
            "mode": self._mode_key(),
            "color": self.color_var.get().strip() or "#3fa9f5",
            "width": safe_int(self.width_var, 1920),
            "height": safe_int(self.height_var, 1080),
            "background_image": self.bg_var.get().strip(),
        }
        try:
            save_config(self.config_data)
        except OSError:
            pass
        return resolve_audiovis_settings(self.config_data)

    def _on_run(self):
        if self.is_processing:
            return
        media_path = self.media_var.get().strip()
        if not media_path or not os.path.exists(media_path):
            messagebox.showinfo("提示", "請選擇有效的來源音訊。", parent=self)
            return
        if not ffmpeg_available():
            show_friendly_error(
                self, "轉換視覺化影片需要 ffmpeg",
                RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。"),
                on_install_ffmpeg=self._open_ffmpeg_installer)
            return
        settings = self._collect_settings()
        output = unique_path(suggest_output_path(media_path))
        self._set_processing(True)
        threading.Thread(
            target=self._run_worker, args=(media_path, output, settings),
            daemon=True).start()

    def _run_worker(self, media_path, output, settings):
        try:
            def report(ratio, message):
                self.result_queue.put(("status", (message, ratio)))
            render_audio_video(media_path, output, settings=settings,
                              progress_cb=report)
            self.result_queue.put(("done", output))
        except Exception as exc:
            logger.exception("音訊轉視覺化影片失敗")
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
                    self.status_var.set(f"轉換完成：{payload}")
                    messagebox.showinfo(
                        "轉換完成",
                        f"已輸出視覺化影片：\n{payload}\n\n"
                        "可直接把這支影片當作來源，接上轉錄／字幕燒錄／"
                        "翻譯等既有流程。", parent=self)
                elif kind == "error":
                    self._set_processing(False)
                    self.status_var.set("轉換失敗。")
                    show_friendly_error(
                        self, "音訊轉視覺化影片失敗", payload,
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
