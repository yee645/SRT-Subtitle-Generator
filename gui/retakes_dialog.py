# -*- coding: utf-8 -*-
"""
重複片段（NG 重錄）對話框：找出同一句話講了好幾次的候選片段，勾選確認後剪掉。

與「自動跳剪停頓」不同，這裡動的是實際講話內容，假陽性風險較高
（例如刻意重複的口號、報數測試麥克風），因此設計為「先列出候選逐項
勾選確認，才真正剪」——預設全部勾選（最常見情境就是全部都是真的
NG 重錄），使用者可自行取消勾選誤判的項目。
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
from subtitle.pipeline import unique_path
from subtitle.retakes import (apply_retake_removal, find_retakes,
                              format_retake_removal_report,
                              resolve_retake_settings, suggest_output_path)

logger = logging.getLogger(__name__)

MEDIA_FILETYPES = [
    ("影音檔", "*.mp4 *.mkv *.mov *.avi *.flv *.mp3 *.wav *.m4a *.aac"),
    ("所有檔案", "*.*"),
]


class RetakesDialog(tk.Toplevel):
    """重複片段視窗：偵測候選、勾選確認、剪掉並同步對齊字幕。"""

    def __init__(self, master, config_data, cues, media_path="",
                on_done=None):
        super().__init__(master)
        self.title("重複片段偵測：剪掉講壞掉的重錄")
        self.geometry("660x600")
        self.minsize(600, 480)
        self.transient(master)

        self.config_data = config_data
        self.cues = cues
        self.on_done = on_done
        self.result_queue = queue.Queue()
        self.is_processing = False
        self._retakes = []
        self._check_vars = []

        settings = resolve_retake_settings(config_data)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        row_file = ttk.Frame(body)
        row_file.pack(fill="x")
        ttk.Label(row_file, text="影片：").pack(side="left")
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
                text="⚠ 尚未安裝 ffmpeg：剪掉重複片段需要它。",
            ).pack(side="left", padx=6, pady=4)
            ttk.Button(banner, text="自動安裝 ffmpeg",
                      command=self._open_ffmpeg_installer).pack(
                side="right", padx=6, pady=2)
            self.ffmpeg_banner = banner

        options = ttk.LabelFrame(body, text="判定門檻（自動記憶）",
                                 padding=(10, 6))
        options.pack(fill="x", pady=(8, 0))
        row1 = ttk.Frame(options)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="相似度門檻:").pack(side="left")
        self.similarity_var = tk.DoubleVar(
            value=settings["similarity_threshold"] * 100.0)
        tk.Spinbox(row1, from_=50.0, to=98.0, increment=1.0, width=6,
                   textvariable=self.similarity_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row1, text="%（兩句文字達此相似度才視為重講）").pack(
            side="left", padx=(0, 14))
        ttk.Label(row1, text="比對時間窗:").pack(side="left")
        self.max_gap_var = tk.DoubleVar(value=settings["max_gap_seconds"])
        tk.Spinbox(row1, from_=5.0, to=120.0, increment=5.0, width=6,
                   textvariable=self.max_gap_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row1, text="秒").pack(side="left")
        row2 = ttk.Frame(options)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="剪點外擴秒數:").pack(side="left")
        self.pad_var = tk.DoubleVar(value=settings["pad"])
        tk.Spinbox(row2, from_=0.0, to=1.0, increment=0.05, width=6,
                   textvariable=self.pad_var, format="%.2f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row2, text="秒（連同前後的吸氣停頓一起剪掉）").pack(
            side="left")

        self.status_var = tk.StringVar(
            value=f"共 {len(cues)} 句字幕，按「偵測重複片段」找出候選。")
        ttk.Label(body, textvariable=self.status_var,
                 foreground="#1a5fb4", wraplength=620, justify="left").pack(
            fill="x", pady=(8, 4))
        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(body, mode="determinate", maximum=100.0,
                        variable=self.progress_var).pack(
            fill="x", pady=(0, 6))

        list_frame = ttk.LabelFrame(
            body, text="候選重複片段（預設全選，可自行取消勾選誤判項目）",
            padding=(6, 6))
        list_frame.pack(fill="both", expand=True)
        theme = config_data.get("theme", "light")
        self.scroll = ScrollableFrame(list_frame, theme=theme)
        self.scroll.pack(fill="both", expand=True)
        self.empty_label = ttk.Label(
            self.scroll.interior, text="（尚未偵測，或沒有候選項目）",
            foreground="#666666")
        self.empty_label.pack(anchor="w", padx=4, pady=4)

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 0))
        self.detect_btn = ttk.Button(buttons, text="偵測重複片段",
                                     command=self._on_detect)
        self.detect_btn.pack(side="left")
        self.cut_btn = ttk.Button(buttons, text="剪掉勾選的重複片段",
                                  state="disabled", command=self._on_cut)
        self.cut_btn.pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="關閉", command=self._on_close).pack(
            side="right")

        self._on_detect()
        self._poll_job = self.after(120, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    def _choose_media(self):
        path = filedialog.askopenfilename(
            title="選擇要剪輯的影音檔", filetypes=MEDIA_FILETYPES,
            parent=self)
        if path:
            self.media_var.set(path)

    def _collect_settings(self):
        def safe(var, fallback):
            try:
                return float(var.get())
            except (tk.TclError, ValueError):
                return fallback
        self.config_data["retakes"] = {
            "similarity_threshold": safe(self.similarity_var, 72.0) / 100.0,
            "max_gap_seconds": safe(self.max_gap_var, 25.0),
            "pad": safe(self.pad_var, 0.2),
        }
        try:
            save_config(self.config_data)
        except OSError:
            pass  # 存檔失敗不影響本次使用。
        return resolve_retake_settings(self.config_data)

    def _clear_list(self):
        for child in self.scroll.interior.winfo_children():
            child.destroy()
        self._check_vars = []

    def _on_detect(self):
        settings = self._collect_settings()
        self._retakes = find_retakes(self.cues, settings)
        self._clear_list()
        if not self._retakes:
            ttk.Label(self.scroll.interior, text="未偵測到疑似重複片段。",
                     foreground="#666666").pack(anchor="w", padx=4, pady=4)
            self.cut_btn.configure(state="disabled")
            self.status_var.set("偵測完成，沒有找到候選重複片段。")
            return
        for retake in self._retakes:
            var = tk.BooleanVar(value=True)
            self._check_vars.append(var)
            text = (f"{retake['start']:.1f}s ~ {retake['end']:.1f}s"
                   f"（相似度 {retake['similarity'] * 100:.0f}%）\n"
                   f"這句：{retake['text']}\n"
                   f"後面較晚的版本：{retake['matched_text']}")
            ttk.Checkbutton(self.scroll.interior, text=text,
                           variable=var).pack(
                anchor="w", padx=4, pady=4, fill="x")
        self.cut_btn.configure(state="normal")
        self.status_var.set(
            f"偵測完成，找到 {len(self._retakes)} 處候選重複片段（如下）。")

    def _selected_retakes(self):
        return [r for r, var in zip(self._retakes, self._check_vars)
                if var.get()]

    def _on_cut(self):
        if self.is_processing:
            return
        selected = self._selected_retakes()
        if not selected:
            messagebox.showinfo("提示", "沒有勾選任何要剪掉的重複片段。",
                               parent=self)
            return
        media_path = self.media_var.get().strip()
        if not media_path or not os.path.exists(media_path):
            messagebox.showinfo("提示", "請選擇有效的影音檔。", parent=self)
            return
        if not ffmpeg_available():
            show_friendly_error(
                self, "剪掉重複片段需要 ffmpeg",
                RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。"),
                on_install_ffmpeg=self._open_ffmpeg_installer)
            return
        settings = self._collect_settings()
        output = unique_path(suggest_output_path(media_path))
        self._set_processing(True)
        threading.Thread(
            target=self._run_worker,
            args=(media_path, output, selected, settings), daemon=True,
        ).start()

    def _run_worker(self, media_path, output, selected, settings):
        try:
            def report(ratio, message):
                self.result_queue.put(("status", (message, ratio)))
            result = apply_retake_removal(
                media_path, self.cues, selected, output,
                settings=settings, progress_cb=report)
            style = self.config_data.get("subtitle_style")
            base, _ = os.path.splitext(output)
            sub_path = unique_path(f"{base}.srt")
            export(result["cues"], sub_path, style=style)
            result["subtitle_path"] = sub_path
            self.result_queue.put(("done", result))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("剪掉重複片段失敗")
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
                    self.cues = payload["cues"]
                    if self.on_done:
                        self.on_done(payload["cues"])
                    report_text = format_retake_removal_report(payload)
                    self.status_var.set(report_text)
                    messagebox.showinfo(
                        "剪輯完成",
                        f"{report_text}\n\n"
                        f"影片：{payload['output']}\n"
                        f"字幕：{payload['subtitle_path']}\n\n"
                        "字幕清單已更新為剪後的新時間軸；建議播放確認剪點。",
                        parent=self)
                    self._on_detect()  # 重新偵測，讓清單反映剪掉後的狀態。
                elif kind == "error":
                    self._set_processing(False)
                    self.status_var.set("剪輯失敗。")
                    show_friendly_error(
                        self, "剪掉重複片段失敗", payload,
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
        state = "disabled" if processing else "normal"
        self.cut_btn.configure(state=state)
        self.detect_btn.configure(state=state)

    def _on_close(self):
        if getattr(self, "_poll_job", None):
            self.after_cancel(self._poll_job)
        self.destroy()
