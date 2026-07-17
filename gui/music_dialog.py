# -*- coding: utf-8 -*-
"""
配樂助手：把背景音樂混進影片，講話時自動閃避（ducking）。

手動幫影片配樂最麻煩的是音樂蓋過講話聲，得逐段拉關鍵影格調音量。
本對話框選定影片與背景音樂後，一鍵輸出混音影片：音樂平時維持設定的
音量，偵測到人聲時自動壓低，安靜時自動恢復，不需手動關鍵影格。
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
from subtitle.audio import mix_background_music, resolve_ducking_settings
from subtitle.burner import ffmpeg_available
from subtitle.pipeline import unique_path

logger = logging.getLogger(__name__)

MEDIA_FILETYPES = [
    ("影片檔", "*.mp4 *.mkv *.mov *.avi *.flv"),
    ("所有檔案", "*.*"),
]
MUSIC_FILETYPES = [
    ("音訊檔", "*.mp3 *.wav *.m4a *.aac *.ogg *.flac"),
    ("所有檔案", "*.*"),
]


class MusicDuckingDialog(tk.Toplevel):
    """配樂助手視窗：選影片與背景音樂、調整強度、輸出混音影片。"""

    def __init__(self, master, config_data, video_path=""):
        super().__init__(master)
        self.title("配樂助手：背景音樂自動閃避")
        self.resizable(False, False)
        self.transient(master)

        self.config_data = config_data
        self.result_queue = queue.Queue()
        self.is_processing = False

        settings = resolve_ducking_settings(config_data)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text="影片：").grid(row=0, column=0, sticky="w", pady=3)
        self.video_var = tk.StringVar(value=video_path)
        ttk.Entry(body, textvariable=self.video_var, width=42).grid(
            row=0, column=1, sticky="we", padx=(6, 4))
        ttk.Button(body, text="瀏覽...", width=8,
                  command=self._choose_video).grid(row=0, column=2)

        ttk.Label(body, text="背景音樂：").grid(row=1, column=0, sticky="w", pady=3)
        self.music_var = tk.StringVar()
        ttk.Entry(body, textvariable=self.music_var, width=42).grid(
            row=1, column=1, sticky="we", padx=(6, 4))
        ttk.Button(body, text="瀏覽...", width=8,
                  command=self._choose_music).grid(row=1, column=2)

        ttk.Label(body, text="音樂音量：").grid(
            row=2, column=0, sticky="w", pady=(10, 3))
        self.volume_var = tk.DoubleVar(value=settings["music_volume"])
        tk.Spinbox(
            body, from_=0.05, to=1.0, increment=0.05, width=6,
            textvariable=self.volume_var, format="%.2f",
        ).grid(row=2, column=1, sticky="w", padx=(6, 0))

        ttk.Label(body, text="閃避強度：").grid(row=3, column=0, sticky="w", pady=3)
        self.strength_var = tk.DoubleVar(value=settings["duck_strength"])
        tk.Spinbox(
            body, from_=1.0, to=20.0, increment=0.5, width=6,
            textvariable=self.strength_var, format="%.1f",
        ).grid(row=3, column=1, sticky="w", padx=(6, 0))

        # 自動適應人聲音量：量測人聲響度後自動算靈敏度（勾選時停用手動旋鈕）。
        self.auto_var = tk.BooleanVar(value=settings["auto_sensitivity"])
        ttk.Checkbutton(
            body, text="自動適應人聲音量（建議：先量測人聲，再自動計算靈敏度）",
            variable=self.auto_var, command=self._sync_auto_state,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 3))

        ttk.Label(body, text="閃避靈敏度：").grid(row=5, column=0, sticky="w", pady=3)
        self.sensitivity_var = tk.DoubleVar(value=settings["duck_sensitivity"])
        self.sensitivity_spin = tk.Spinbox(
            body, from_=0.01, to=0.5, increment=0.01, width=6,
            textvariable=self.sensitivity_var, format="%.2f",
        )
        self.sensitivity_spin.grid(row=5, column=1, sticky="w", padx=(6, 0))

        ttk.Label(
            body, foreground="#666666", justify="left",
            text=("音量：混音前的音樂基礎音量；強度：講話時音樂被壓低的程度；\n"
                  "自動適應開啟時靈敏度自動計算（人聲偏小聲也能正確觸發閃避），\n"
                  "取消勾選才使用手動靈敏度（數值越低，越輕的講話聲就會觸發）。"),
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(4, 8))

        self.status_var = tk.StringVar(
            value="選好影片與背景音樂後按「輸出混音影片」。")
        ttk.Label(body, textvariable=self.status_var,
                 foreground="#1a5fb4").grid(
            row=7, column=0, columnspan=3, sticky="w")

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress = ttk.Progressbar(
            body, mode="determinate", maximum=100.0,
            variable=self.progress_var)
        self.progress.grid(row=8, column=0, columnspan=3, sticky="we",
                          pady=(4, 8))

        buttons = ttk.Frame(body)
        buttons.grid(row=9, column=0, columnspan=3, sticky="we")
        self.run_btn = ttk.Button(
            buttons, text="輸出混音影片", command=self._on_run)
        self.run_btn.pack(side="left")
        ttk.Button(buttons, text="關閉", command=self._on_close).pack(
            side="right")

        self._sync_auto_state()
        self._poll_job = self.after(120, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    def _sync_auto_state(self):
        """自動適應開啟時停用手動靈敏度旋鈕，避免兩者混淆。"""
        self.sensitivity_spin.configure(
            state="disabled" if self.auto_var.get() else "normal")

    def _choose_video(self):
        path = filedialog.askopenfilename(
            title="選擇影片", filetypes=MEDIA_FILETYPES, parent=self)
        if path:
            self.video_var.set(path)

    def _choose_music(self):
        path = filedialog.askopenfilename(
            title="選擇背景音樂", filetypes=MUSIC_FILETYPES, parent=self)
        if path:
            self.music_var.set(path)

    def _collect_settings(self):
        """把介面上的強度旋鈕寫回設定並存檔，回傳解析後的 settings。"""
        def safe(var, fallback):
            try:
                return float(var.get())
            except (tk.TclError, ValueError):
                return fallback
        self.config_data["ducking"] = {
            "music_volume": safe(self.volume_var, 0.35),
            "duck_strength": safe(self.strength_var, 8.0),
            "duck_sensitivity": safe(self.sensitivity_var, 0.06),
            "auto_sensitivity": bool(self.auto_var.get()),
        }
        try:
            save_config(self.config_data)
        except OSError:
            pass  # 存檔失敗不影響本次使用。
        return resolve_ducking_settings(self.config_data)

    # ------------------------------------------------------------------
    def _on_run(self):
        if self.is_processing:
            return
        video_path = self.video_var.get().strip()
        music_path = self.music_var.get().strip()
        if not video_path or not os.path.exists(video_path):
            messagebox.showinfo("提示", "請選擇有效的影片檔。", parent=self)
            return
        if not music_path or not os.path.exists(music_path):
            messagebox.showinfo("提示", "請選擇有效的背景音樂檔。", parent=self)
            return
        if not ffmpeg_available():
            show_friendly_error(
                self, "配樂混音需要 ffmpeg",
                RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。"),
                on_install_ffmpeg=lambda: FfmpegInstallDialog(self))
            return
        settings = self._collect_settings()
        base, ext = os.path.splitext(video_path)
        output_path = unique_path(f"{base}_配樂{ext or '.mp4'}")
        self._set_processing(True)
        threading.Thread(
            target=self._run_worker,
            args=(video_path, music_path, output_path, settings),
            daemon=True,
        ).start()

    def _run_worker(self, video_path, music_path, output_path, settings):
        try:
            def report(ratio, message):
                self.result_queue.put(("status", (message, ratio)))
            mix_background_music(
                video_path, music_path, output_path,
                settings=settings, progress_cb=report)
            self.result_queue.put(("done", output_path))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("配樂混音失敗")
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
                    self.status_var.set(f"完成：{payload}")
                    messagebox.showinfo(
                        "配樂助手", f"已輸出混音影片：\n{payload}", parent=self)
                elif kind == "error":
                    self._set_processing(False)
                    self.status_var.set("混音失敗。")
                    show_friendly_error(
                        self, "配樂混音失敗", payload,
                        on_install_ffmpeg=lambda: FfmpegInstallDialog(self))
        except queue.Empty:
            pass
        self._poll_job = self.after(120, self._poll_queue)

    def _set_processing(self, processing):
        self.is_processing = processing
        self.run_btn.configure(state="disabled" if processing else "normal")

    def _on_close(self):
        if getattr(self, "_poll_job", None):
            self.after_cancel(self._poll_job)
        self.destroy()
