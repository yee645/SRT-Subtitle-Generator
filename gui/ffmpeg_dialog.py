# -*- coding: utf-8 -*-
"""
ffmpeg 一鍵安裝對話框：下載進度＋完成回呼。

背景執行緒跑 subtitle/ffmpeg_setup.install_ffmpeg()，完成後立即對
本行程生效（既有功能不需重啟即可使用），並通知呼叫端刷新介面
（例如隱藏「缺少 ffmpeg」警告條）。
"""

import logging
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from subtitle.ffmpeg_setup import install_ffmpeg

logger = logging.getLogger(__name__)


class FfmpegInstallDialog(tk.Toplevel):
    """自動安裝 ffmpeg：顯示下載與解壓進度，完成後回呼 on_done。"""

    def __init__(self, master, on_done=None):
        super().__init__(master)
        self.title("自動安裝 ffmpeg")
        self.resizable(False, False)
        self.transient(master)
        self._on_done = on_done
        self._queue = queue.Queue()
        self._started = False

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body, wraplength=440, justify="left",
            text=("將下載 ffmpeg（約 80~100 MB，只需一次）並安裝到程式"
                  "自己的資料夾——不需要管理員權限、不會改動系統設定，"
                  "安裝完成後立即可用。"),
        ).pack(anchor="w")

        self.status_var = tk.StringVar(value="按「開始安裝」後請保持網路連線。")
        ttk.Label(body, textvariable=self.status_var,
                  foreground="#1a5fb4").pack(anchor="w", pady=(8, 2))
        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(body, mode="determinate", maximum=100.0,
                        length=440, variable=self.progress_var).pack(
            fill="x", pady=(0, 10))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        self.start_btn = ttk.Button(buttons, text="開始安裝",
                                    command=self._on_start)
        self.start_btn.pack(side="left")
        ttk.Button(buttons, text="關閉", command=self._on_close).pack(
            side="right")

        self._poll_job = self.after(120, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_start(self):
        if self._started:
            return
        self._started = True
        self.start_btn.configure(state="disabled", text="安裝中...")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            target = install_ffmpeg(
                progress_cb=lambda ratio, message: self._queue.put(
                    ("status", (message, ratio))))
            self._queue.put(("done", target))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("ffmpeg 自動安裝失敗")
            self._queue.put(("error", exc))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "status":
                    message, ratio = payload
                    self.status_var.set(message)
                    if ratio is not None:
                        self.progress_var.set(ratio * 100.0)
                elif kind == "done":
                    messagebox.showinfo(
                        "安裝完成",
                        f"ffmpeg 已安裝到：\n{payload}\n\n"
                        "所有影音功能現在即可使用，無需重新啟動。",
                        parent=self)
                    if self._on_done:
                        self._on_done()
                    self._close()
                    return
                elif kind == "error":
                    # 延遲載入避免循環相依。
                    from gui.error_dialog import show_friendly_error
                    self._started = False
                    self.start_btn.configure(state="normal", text="重試安裝")
                    self.status_var.set("安裝失敗，可重試或改手動安裝。")
                    show_friendly_error(self, "安裝失敗", payload)
        except queue.Empty:
            pass
        self._poll_job = self.after(120, self._poll_queue)

    def _close(self):
        if getattr(self, "_poll_job", None):
            self.after_cancel(self._poll_job)
        self.destroy()

    def _on_close(self):
        if self._started and self.progress_var.get() < 100.0:
            if not messagebox.askyesno(
                    "安裝進行中", "安裝仍在進行，確定要關閉嗎？",
                    parent=self):
                return
        self._close()
