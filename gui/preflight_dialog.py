# -*- coding: utf-8 -*-
"""
上片前總體檢對話框：一次跑完所有健檢，給一份依嚴重度排序的清單。

本工具累積到現在已有十幾項健檢，散落在多個入口。要在上傳前確認一支影片
沒問題，使用者得記得開三個視窗、按五個按鈕，還要自己判斷哪些一定要修。
這個視窗就是那個「按一下就好」的入口：選素材（字幕檔選填）→ 開始 →
拿到一份分成「一定要修／建議修／通過」的清單與準備度評級。

各項檢查可單獨關閉並自動記憶——畫面類的掃描要完整解碼影片，長片上並不
便宜，使用者應該能只跑自己在意的。
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
from subtitle.importer import load_subtitle_file
from subtitle.preflight import (format_preflight_report,
                                resolve_preflight_settings, run_preflight)

logger = logging.getLogger(__name__)

MEDIA_FILETYPES = [
    ("影音檔", "*.mp4 *.mkv *.mov *.avi *.flv *.mp3 *.wav *.m4a *.aac"),
    ("所有檔案", "*.*"),
]
SUBTITLE_FILETYPES = [
    ("字幕檔", "*.srt *.vtt"),
    ("所有檔案", "*.*"),
]

# 勾選項目：(設定鍵, 顯示名稱, 需不需要字幕)
_CHECK_ITEMS = (
    ("run_audio", "音訊健檢", False),
    ("run_video", "影片畫質", False),
    ("run_color", "曝光與色偏", False),
    ("run_volume", "音量一致性", False),
    ("run_pacing", "剪輯節奏", False),
    ("run_subtitle", "字幕健檢", True),
    ("run_adfriendly", "廣告友善度", True),
    ("run_hook", "開場健檢", True),
    ("run_legibility", "字幕可讀性", True),
    ("run_endscreen", "片尾空間", False),
)
_COLUMNS = 3


class PreflightDialog(tk.Toplevel):
    """上片前總體檢視窗：一次跑完所有健檢並依嚴重度排序。"""

    def __init__(self, master, config_data, media_path="", cues=None):
        super().__init__(master)
        self.title("上片前總體檢：一次跑完所有健檢")
        self.geometry("780x820")
        self.minsize(700, 700)
        self.transient(master)

        self.config_data = config_data
        self.result_queue = queue.Queue()
        self.is_processing = False
        self.report_text = ""
        # 主視窗已經有字幕時直接沿用，省得使用者再挑一次檔案。
        self._cues = list(cues or [])

        settings = resolve_preflight_settings(config_data)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body, anchor="w", justify="left", wraplength=720,
            foreground="#666666",
            text="一次跑完所有適用的健檢，把結果依嚴重度排成一份清單。"
                 "沒有字幕時會自動略過字幕相關檢查；純音訊檔會自動略過所有"
                 "畫面檢查（那些檢查每一項都要完整解碼一次影片）。",
        ).pack(fill="x", pady=(0, 8))

        self.ffmpeg_banner = None
        if not ffmpeg_available():
            banner = tk.Frame(body, bg="#fdf3d7")
            banner.pack(fill="x", pady=(0, 8))
            tk.Label(
                banner, bg="#fdf3d7", fg="#8a5a00", anchor="w",
                text="⚠ 尚未安裝 ffmpeg：總體檢需要它才能量測素材。",
            ).pack(side="left", padx=6, pady=4)
            ttk.Button(banner, text="自動安裝 ffmpeg",
                       command=self._open_ffmpeg_installer).pack(
                side="right", padx=6, pady=2)
            self.ffmpeg_banner = banner

        row_media = ttk.Frame(body)
        row_media.pack(fill="x")
        ttk.Label(row_media, text="素材：", width=7).pack(side="left")
        self.media_var = tk.StringVar(value=media_path)
        ttk.Entry(row_media, textvariable=self.media_var).pack(
            side="left", fill="x", expand=True, padx=(4, 4))
        ttk.Button(row_media, text="瀏覽...", width=8,
                   command=self._choose_media).pack(side="left")

        row_subs = ttk.Frame(body)
        row_subs.pack(fill="x", pady=(6, 0))
        ttk.Label(row_subs, text="字幕：", width=7).pack(side="left")
        self.subs_var = tk.StringVar(
            value=f"（已沿用主視窗的 {len(self._cues)} 句字幕）"
            if self._cues else "")
        ttk.Entry(row_subs, textvariable=self.subs_var).pack(
            side="left", fill="x", expand=True, padx=(4, 4))
        ttk.Button(row_subs, text="瀏覽...", width=8,
                   command=self._choose_subs).pack(side="left")
        ttk.Label(body, foreground="#666666", anchor="w",
                  text="（字幕選填；沒有字幕就只跑畫面與聲音相關的檢查）"
                  ).pack(fill="x")

        options = ttk.LabelFrame(body, text="要跑哪些檢查（自動記憶）",
                                 padding=(10, 6))
        options.pack(fill="x", pady=(8, 0))
        self.check_vars = {}
        for index, (key, label, needs_cues) in enumerate(_CHECK_ITEMS):
            var = tk.BooleanVar(value=settings[key])
            self.check_vars[key] = var
            text = f"{label}（需字幕）" if needs_cues else label
            ttk.Checkbutton(options, text=text, variable=var).grid(
                row=index // _COLUMNS, column=index % _COLUMNS,
                sticky="w", padx=(0, 16), pady=2)

        name_row = ttk.Frame(options)
        name_row.grid(row=(len(_CHECK_ITEMS) + _COLUMNS - 1) // _COLUMNS,
                      column=0, columnspan=_COLUMNS, sticky="ew", pady=(6, 0))
        ttk.Label(name_row, text="無資訊檔名字眼:").pack(side="left")
        self.name_terms_var = tk.StringVar(
            value=settings["generic_name_terms"])
        ttk.Entry(name_row, textvariable=self.name_terms_var).pack(
            side="left", fill="x", expand=True, padx=(4, 0))

        self.status_var = tk.StringVar(
            value="選好素材後按「開始總體檢」，掃描不會改動原始檔案。")
        ttk.Label(body, textvariable=self.status_var, foreground="#1a5fb4",
                  wraplength=720, justify="left").pack(fill="x", pady=(8, 0))
        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(body, mode="determinate", maximum=100.0,
                        variable=self.progress_var).pack(fill="x", pady=(4, 6))

        report_frame = ttk.LabelFrame(body, text="總體檢報告", padding=(6, 6))
        report_frame.pack(fill="both", expand=True)
        self.report = tk.Text(report_frame, wrap="word", state="disabled",
                              font=("Microsoft JhengHei", 10), height=12)
        # 「建議：」這種長句換行後要縮排，否則看起來像新的一個項目。
        self.report.tag_configure("report", lmargin2=28)
        scrollbar = ttk.Scrollbar(report_frame, orient="vertical",
                                  command=self.report.yview)
        self.report.configure(yscrollcommand=scrollbar.set)
        self.report.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 0))
        self.run_btn = ttk.Button(buttons, text="開始總體檢",
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

    def _choose_media(self):
        path = filedialog.askopenfilename(
            title="選擇要體檢的素材", filetypes=MEDIA_FILETYPES, parent=self)
        if path:
            self.media_var.set(path)

    def _choose_subs(self):
        path = filedialog.askopenfilename(
            title="選擇字幕檔（選填）", filetypes=SUBTITLE_FILETYPES,
            parent=self)
        if not path:
            return
        try:
            self._cues = load_subtitle_file(path)
        except Exception as exc:
            show_friendly_error(self, exc, title="讀取字幕檔失敗")
            return
        self.subs_var.set(path)
        self.status_var.set(f"已載入 {len(self._cues)} 句字幕。")

    def _collect_settings(self):
        self.config_data["preflight"] = {
            key: bool(var.get()) for key, var in self.check_vars.items()
        }
        self.config_data["preflight"]["generic_name_terms"] = \
            self.name_terms_var.get().strip()
        try:
            save_config(self.config_data)
        except OSError:
            pass  # 存檔失敗不影響本次使用。
        return self.config_data

    # ------------------------------------------------------------------
    def _on_run(self):
        if self.is_processing:
            return
        media = self.media_var.get().strip()
        if not media or not os.path.exists(media):
            messagebox.showinfo("提示", "請選擇有效的影音檔。", parent=self)
            return
        if not ffmpeg_available():
            show_friendly_error(
                self, RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。"),
                title="總體檢需要 ffmpeg")
            return
        config = self._collect_settings()
        self.is_processing = True
        self.run_btn.configure(state="disabled")
        self.progress_var.set(0.0)
        self.status_var.set("總體檢進行中...")
        threading.Thread(target=self._worker,
                         args=(media, list(self._cues), config),
                         daemon=True).start()

    def _worker(self, media, cues, config):
        try:
            def progress(ratio, message):
                self.result_queue.put(("status", (message, ratio)))
            result = run_preflight(media, cues, config, progress_cb=progress)
            self.result_queue.put(("done", result))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("總體檢失敗")
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
                    self._finish(payload)
                elif kind == "error":
                    self._fail(payload)
        except queue.Empty:
            pass
        self._poll_job = self.after(120, self._poll_queue)

    def _finish(self, result):
        self.is_processing = False
        self.run_btn.configure(state="normal")
        self.progress_var.set(100.0)
        self.report_text = format_preflight_report(result)
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", self.report_text, "report")
        self.report.configure(state="disabled")
        self.copy_btn.configure(state="normal")
        self.save_btn.configure(state="normal")
        counts = result.get("counts") or {}
        grade = result.get("grade", "?")
        if result.get("ok"):
            self.status_var.set(
                f"總體檢完成，準備度 {grade}：沒有「一定要修」的項目，"
                f"可以上傳（建議修 {counts.get('warn', 0)} 項）。")
        else:
            self.status_var.set(
                f"總體檢完成，準備度 {grade}："
                f"{counts.get('bad', 0)} 項一定要修、"
                f"{counts.get('warn', 0)} 項建議修，詳見報告。")

    def _fail(self, exc):
        self.is_processing = False
        self.run_btn.configure(state="normal")
        self.progress_var.set(0.0)
        self.status_var.set("總體檢失敗。")
        show_friendly_error(self, exc, title="總體檢失敗")

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
            title="另存總體檢報告", defaultextension=".txt",
            initialfile="總體檢.txt",
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
