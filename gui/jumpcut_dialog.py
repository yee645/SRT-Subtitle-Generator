# -*- coding: utf-8 -*-
"""
自動跳剪對話框：依目前字幕清單找出句間停頓，一次剪掉整支影片的冷場。

調研顯示「剪掉停頓」是創作者公認最花時間、最想自動化的步驟。本對話框
先讓使用者「預覽跳剪點」（純分析目前字幕清單，免呼叫 ffmpeg、瞬間完成）
確認省下的秒數合理，再按「輸出跳剪版」實際裁切；輸出的新影片會同步
匯出時間軸已對齊的字幕檔，剪完字幕不必再手動調時間軸。
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
from subtitle.exporter import export
from subtitle.jumpcut import (apply_jumpcut, compute_keep_segments,
                              find_cut_gaps, format_jumpcut_report,
                              resolve_jumpcut_settings, suggest_output_path)
from subtitle.media import probe_duration
from subtitle.pipeline import unique_path

logger = logging.getLogger(__name__)

MEDIA_FILETYPES = [
    ("影音檔", "*.mp4 *.mkv *.mov *.avi *.flv *.mp3 *.wav *.m4a *.aac"),
    ("所有檔案", "*.*"),
]


class JumpCutDialog(tk.Toplevel):
    """自動跳剪視窗：預覽停頓點、輸出跳剪版影片＋同步對齊的字幕。"""

    def __init__(self, master, config_data, cues, media_path="",
                on_done=None):
        super().__init__(master)
        self.title("自動跳剪：剪掉句間停頓")
        self.geometry("620x560")
        self.minsize(560, 480)
        self.transient(master)

        self.config_data = config_data
        self.cues = cues
        self.on_done = on_done
        self.result_queue = queue.Queue()
        self.is_processing = False

        settings = resolve_jumpcut_settings(config_data)
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
                text="⚠ 尚未安裝 ffmpeg：跳剪需要它才能裁切影片。",
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
        ttk.Label(row1, text="最短停頓秒數:").pack(side="left")
        self.min_gap_var = tk.DoubleVar(value=settings["min_gap"])
        tk.Spinbox(row1, from_=0.5, to=5.0, increment=0.1, width=6,
                   textvariable=self.min_gap_var, format="%.1f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row1, text="秒（達此長度才剪）").pack(
            side="left", padx=(0, 14))
        ttk.Label(row1, text="緩衝秒數:").pack(side="left")
        self.pad_var = tk.DoubleVar(value=settings["pad"])
        tk.Spinbox(row1, from_=0.0, to=1.0, increment=0.05, width=6,
                   textvariable=self.pad_var, format="%.2f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row1, text="秒（剪點兩側保留）").pack(side="left")
        row2 = ttk.Frame(options)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="安全上限:").pack(side="left")
        self.max_ratio_var = tk.DoubleVar(
            value=settings["max_cut_ratio"] * 100.0)
        tk.Spinbox(row2, from_=10.0, to=90.0, increment=5.0, width=6,
                   textvariable=self.max_ratio_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row2, text="%（跳剪比例超過此值時中止，防誤判）").pack(
            side="left")

        self.status_var = tk.StringVar(
            value=f"共 {len(cues)} 句字幕，按「預覽跳剪點」看看能省下多少時間。")
        ttk.Label(body, textvariable=self.status_var,
                 foreground="#1a5fb4", wraplength=580, justify="left").pack(
            fill="x", pady=(8, 4))
        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(body, mode="determinate", maximum=100.0,
                        variable=self.progress_var).pack(
            fill="x", pady=(0, 6))

        report_frame = ttk.LabelFrame(body, text="跳剪預覽", padding=(6, 6))
        report_frame.pack(fill="both", expand=True)
        self.report = tk.Text(report_frame, wrap="word", state="disabled",
                              font=("Microsoft JhengHei", 10), height=10)
        scrollbar = ttk.Scrollbar(report_frame, orient="vertical",
                                  command=self.report.yview)
        self.report.configure(yscrollcommand=scrollbar.set)
        self.report.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 0))
        self.preview_btn = ttk.Button(buttons, text="預覽跳剪點",
                                      command=self._on_preview)
        self.preview_btn.pack(side="left")
        self.run_btn = ttk.Button(buttons, text="輸出跳剪版",
                                  state="disabled", command=self._on_run)
        self.run_btn.pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="關閉", command=self._on_close).pack(
            side="right")

        self._preview_gaps = []
        self._on_preview()
        self._poll_job = self.after(120, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    def _choose_media(self):
        path = filedialog.askopenfilename(
            title="選擇要跳剪的影音檔", filetypes=MEDIA_FILETYPES,
            parent=self)
        if path:
            self.media_var.set(path)

    def _collect_settings(self):
        def safe(var, fallback):
            try:
                return float(var.get())
            except (tk.TclError, ValueError):
                return fallback
        self.config_data["jumpcut"] = {
            "min_gap": safe(self.min_gap_var, 1.2),
            "pad": safe(self.pad_var, 0.15),
            "max_cut_ratio": safe(self.max_ratio_var, 60.0) / 100.0,
        }
        try:
            save_config(self.config_data)
        except OSError:
            pass  # 存檔失敗不影響本次使用。
        return resolve_jumpcut_settings(self.config_data)

    def _on_preview(self):
        """純分析目前字幕清單找出停頓（免呼叫 ffmpeg，瞬間完成）。"""
        settings = self._collect_settings()
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
        self.status_var.set("預覽完成，結果如下。" if gaps else "預覽完成。")

    def _on_run(self):
        if self.is_processing:
            return
        if not self._preview_gaps:
            messagebox.showinfo("提示", "目前沒有可跳剪的停頓。", parent=self)
            return
        media_path = self.media_var.get().strip()
        if not media_path or not os.path.exists(media_path):
            messagebox.showinfo("提示", "請選擇有效的影音檔。", parent=self)
            return
        if not ffmpeg_available():
            show_friendly_error(
                self, "自動跳剪需要 ffmpeg",
                RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。"),
                on_install_ffmpeg=self._open_ffmpeg_installer)
            return
        settings = self._collect_settings()
        output = unique_path(suggest_output_path(media_path))
        self._set_processing(True)
        threading.Thread(
            target=self._run_worker,
            args=(media_path, output, settings), daemon=True).start()

    def _run_worker(self, media_path, output, settings):
        try:
            def report(ratio, message):
                self.result_queue.put(("status", (message, ratio)))
            result = apply_jumpcut(media_path, self.cues, output,
                                   settings=settings, progress_cb=report)
            style = self.config_data.get("subtitle_style")
            base, _ = os.path.splitext(output)
            sub_path = unique_path(f"{base}.srt")
            export(result["cues"], sub_path, style=style)
            result["subtitle_path"] = sub_path
            self.result_queue.put(("done", result))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("自動跳剪失敗")
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
                    self.status_var.set(format_jumpcut_report(payload))
                    messagebox.showinfo(
                        "跳剪完成",
                        f"{format_jumpcut_report(payload)}\n\n"
                        f"影片：{payload['output']}\n"
                        f"字幕：{payload['subtitle_path']}\n\n"
                        "字幕清單已更新為剪後的新時間軸；建議播放確認剪點。",
                        parent=self)
                elif kind == "error":
                    self._set_processing(False)
                    self.status_var.set("跳剪失敗。")
                    show_friendly_error(
                        self, "自動跳剪失敗", payload,
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
        self.run_btn.configure(state=state)
        self.preview_btn.configure(state=state)

    def _on_close(self):
        if getattr(self, "_poll_job", None):
            self.after_cancel(self._poll_job)
        self.destroy()
