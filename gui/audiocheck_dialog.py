# -*- coding: utf-8 -*-
"""
音訊健檢對話框：上片前一鍵檢查爆音、音量、底噪與聲道平衡。

聲音出包（爆音、太小聲、單邊聲道）常常是影片上傳後才被留言提醒，
而那時已經救不回來。本對話框選定影片後一鍵掃描音軌，以檢查表呈現
「通過／注意／建議修正」與具體修法，判定門檻皆可調並記憶。
"""

import logging
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from config import save_config
from subtitle.audiocheck import (format_report, resolve_audiocheck_settings,
                                 run_audio_check)
from subtitle.pipeline import unique_path

logger = logging.getLogger(__name__)

MEDIA_FILETYPES = [
    ("影音檔", "*.mp4 *.mkv *.mov *.avi *.flv *.mp3 *.wav *.m4a *.aac"),
    ("所有檔案", "*.*"),
]


class AudioCheckDialog(tk.Toplevel):
    """音訊健檢視窗：選檔、調門檻、一鍵掃描並顯示健檢報告。"""

    def __init__(self, master, config_data, media_path=""):
        super().__init__(master)
        self.title("音訊健檢：上片前檢查爆音、音量與底噪")
        self.geometry("640x560")
        self.minsize(560, 460)
        self.transient(master)

        self.config_data = config_data
        self.result_queue = queue.Queue()
        self.is_processing = False
        self.report_text = ""

        settings = resolve_audiocheck_settings(config_data)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        row_file = ttk.Frame(body)
        row_file.pack(fill="x")
        ttk.Label(row_file, text="素材：").pack(side="left")
        self.media_var = tk.StringVar(value=media_path)
        ttk.Entry(row_file, textvariable=self.media_var).pack(
            side="left", fill="x", expand=True, padx=(6, 4))
        ttk.Button(row_file, text="瀏覽...", width=8,
                   command=self._choose_media).pack(side="left")

        # 判定門檻（自動記憶）：不同錄音環境可自行放寬或收緊。
        options = ttk.LabelFrame(body, text="判定門檻（自動記憶）",
                                 padding=(10, 6))
        options.pack(fill="x", pady=(8, 0))
        row1 = ttk.Frame(options)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="太小聲門檻:").pack(side="left")
        self.quiet_var = tk.DoubleVar(value=settings["quiet_lufs"])
        tk.Spinbox(row1, from_=-30.0, to=-10.0, increment=0.5, width=7,
                   textvariable=self.quiet_var, format="%.1f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row1, text="LUFS").pack(side="left", padx=(0, 14))
        ttk.Label(row1, text="底噪門檻:").pack(side="left")
        self.noise_var = tk.DoubleVar(value=settings["noise_floor_db"])
        tk.Spinbox(row1, from_=-90.0, to=-20.0, increment=1.0, width=7,
                   textvariable=self.noise_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row1, text="dB").pack(side="left")
        row2 = ttk.Frame(options)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="爆音峰值門檻:").pack(side="left")
        self.clip_var = tk.DoubleVar(value=settings["clip_peak_db"])
        tk.Spinbox(row2, from_=-6.0, to=0.0, increment=0.1, width=7,
                   textvariable=self.clip_var, format="%.1f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row2, text="dB").pack(side="left", padx=(0, 14))
        ttk.Label(row2, text="聲道差異門檻:").pack(side="left")
        self.balance_var = tk.DoubleVar(value=settings["balance_db"])
        tk.Spinbox(row2, from_=2.0, to=20.0, increment=0.5, width=7,
                   textvariable=self.balance_var, format="%.1f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row2, text="dB").pack(side="left")

        self.status_var = tk.StringVar(
            value="選好素材後按「開始健檢」，掃描不會改動原始檔案。")
        ttk.Label(body, textvariable=self.status_var,
                  foreground="#1a5fb4").pack(fill="x", pady=(6, 0))
        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(body, mode="determinate", maximum=100.0,
                        variable=self.progress_var).pack(
            fill="x", pady=(4, 6))

        # 報告顯示區。
        report_frame = ttk.LabelFrame(body, text="健檢報告", padding=(6, 6))
        report_frame.pack(fill="both", expand=True)
        self.report = tk.Text(report_frame, wrap="word", state="disabled",
                              font=("Microsoft JhengHei", 10), height=12)
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
    def _choose_media(self):
        path = filedialog.askopenfilename(
            title="選擇要健檢的影音檔", filetypes=MEDIA_FILETYPES,
            parent=self)
        if path:
            self.media_var.set(path)

    def _collect_settings(self):
        """把介面上的門檻寫回設定並存檔，回傳解析後的 settings。"""
        def safe(var, fallback):
            try:
                return float(var.get())
            except (tk.TclError, ValueError):
                return fallback
        self.config_data["audiocheck"] = {
            "quiet_lufs": safe(self.quiet_var, -19.0),
            "noise_floor_db": safe(self.noise_var, -50.0),
            "clip_peak_db": safe(self.clip_var, -0.5),
            "balance_db": safe(self.balance_var, 6.0),
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
        media_path = self.media_var.get().strip()
        if not media_path or not os.path.exists(media_path):
            messagebox.showinfo("提示", "請選擇有效的影音檔。", parent=self)
            return
        config = self._collect_settings()
        self._set_processing(True)
        threading.Thread(
            target=self._run_worker, args=(media_path, config),
            daemon=True).start()

    def _run_worker(self, media_path, config):
        try:
            def report(ratio, message):
                self.result_queue.put(("status", (message, ratio)))
            result = run_audio_check(media_path, config, progress_cb=report)
            text = format_report(result, os.path.basename(media_path))
            self.result_queue.put(("done", text))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("音訊健檢失敗")
            self.result_queue.put(("error", str(exc)))

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
                    self.status_var.set("健檢完成，結果如下。")
                elif kind == "error":
                    self._set_processing(False)
                    self.status_var.set("健檢失敗。")
                    messagebox.showerror("音訊健檢", payload, parent=self)
        except queue.Empty:
            pass
        self._poll_job = self.after(120, self._poll_queue)

    def _show_report(self, text):
        self.report_text = text
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", text)
        self.report.configure(state="disabled")
        self.copy_btn.configure(state="normal")
        self.save_btn.configure(state="normal")

    def _on_copy(self):
        if not self.report_text:
            return
        self.clipboard_clear()
        self.clipboard_append(self.report_text)
        self.status_var.set("報告已複製到剪貼簿。")

    def _on_save(self):
        if not self.report_text:
            return
        media_path = self.media_var.get().strip()
        base = os.path.splitext(os.path.basename(media_path))[0] or "音訊健檢"
        initial = unique_path(os.path.join(
            os.path.dirname(media_path) or ".", f"{base}_音訊健檢.txt"))
        path = filedialog.asksaveasfilename(
            title="另存健檢報告", defaultextension=".txt",
            initialfile=os.path.basename(initial),
            initialdir=os.path.dirname(initial) or ".",
            filetypes=[("文字檔", "*.txt"), ("所有檔案", "*.*")],
            parent=self)
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(self.report_text)
        except OSError as exc:
            messagebox.showerror("儲存失敗", str(exc), parent=self)
            return
        self.status_var.set(f"報告已儲存：{path}")

    def _set_processing(self, processing):
        self.is_processing = processing
        self.run_btn.configure(state="disabled" if processing else "normal")

    def _on_close(self):
        if getattr(self, "_poll_job", None):
            self.after_cancel(self._poll_job)
        self.destroy()
