# -*- coding: utf-8 -*-
"""
字幕翻譯對話框：把目前字幕清單一鍵翻成雙語或取代版本。

YouTube 的自動字幕無法輸出雙語軌，調研顯示超過三分之二的觀看時數
來自創作者所在地區以外——本對話框重用「轉寫設定」既有的 OpenAI API
金鑰，選好目標語言與模式後即可翻譯目前的字幕清單，不必再另外上傳到
第三方翻譯工具拼湊雙語字幕。
"""

import logging
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from config import save_config
from gui.error_dialog import show_friendly_error
from subtitle.translator import (LANGUAGE_LABELS, resolve_translate_settings,
                                 translate_cues)

logger = logging.getLogger(__name__)

_LANGUAGE_CODES_BY_LABEL = {label: code for code, label in LANGUAGE_LABELS.items()}


class TranslateDialog(tk.Toplevel):
    """字幕翻譯視窗：選目標語言與模式，一鍵輸出雙語或取代版字幕。"""

    def __init__(self, master, config_data, cues, on_done=None):
        super().__init__(master)
        self.title("字幕翻譯（雙語字幕）")
        self.resizable(False, False)
        self.transient(master)

        self.config_data = config_data
        self.cues = cues
        self.on_done = on_done
        self.result_queue = queue.Queue()
        self.is_processing = False

        settings = resolve_translate_settings(config_data)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text="目標語言：").grid(
            row=0, column=0, sticky="w", pady=3)
        current_label = LANGUAGE_LABELS.get(
            settings["target_language"], LANGUAGE_LABELS["en"])
        self.language_var = tk.StringVar(value=current_label)
        ttk.Combobox(
            body, textvariable=self.language_var, state="readonly", width=14,
            values=list(LANGUAGE_LABELS.values()),
        ).grid(row=0, column=1, sticky="w", padx=(6, 0), pady=3)

        ttk.Label(body, text="模式：").grid(
            row=1, column=0, sticky="nw", pady=(6, 3))
        self.mode_var = tk.StringVar(value=settings["mode"])
        mode_frame = ttk.Frame(body)
        mode_frame.grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(6, 3))
        ttk.Radiobutton(
            mode_frame, text="雙語（原文＋譯文上下行）",
            variable=self.mode_var, value="bilingual",
        ).pack(anchor="w")
        ttk.Radiobutton(
            mode_frame, text="僅保留譯文（取代原文）",
            variable=self.mode_var, value="replace",
        ).pack(anchor="w")

        ttk.Label(
            body, foreground="#666666", justify="left", wraplength=380,
            text=("使用「轉寫設定」的 OpenAI API 金鑰（未填時按開始會提示）；"
                  "譯文由 AI 產生，建議抽查幾句。\n"
                  "取代模式會覆蓋目前字幕內容（可重新生成復原）。"),
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 6))

        self.status_var = tk.StringVar(
            value=f"共 {len(cues)} 句字幕，按「開始翻譯」。")
        ttk.Label(body, textvariable=self.status_var,
                 foreground="#1a5fb4", wraplength=380, justify="left").grid(
            row=3, column=0, columnspan=2, sticky="w")

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress = ttk.Progressbar(
            body, mode="determinate", maximum=100.0,
            variable=self.progress_var)
        self.progress.grid(row=4, column=0, columnspan=2, sticky="we",
                          pady=(4, 8))

        buttons = ttk.Frame(body)
        buttons.grid(row=5, column=0, columnspan=2, sticky="we")
        self.run_btn = ttk.Button(
            buttons, text="開始翻譯", command=self._on_run)
        self.run_btn.pack(side="left")
        ttk.Button(buttons, text="關閉", command=self._on_close).pack(
            side="right")

        self._poll_job = self.after(120, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    def _language_code(self):
        return _LANGUAGE_CODES_BY_LABEL.get(self.language_var.get(), "en")

    def _collect_settings(self):
        """把介面上選取的語言／模式寫回設定並存檔，回傳解析後的 settings。"""
        self.config_data["translate"] = {
            "target_language": self._language_code(),
            "mode": self.mode_var.get(),
            "batch_size": resolve_translate_settings(
                self.config_data)["batch_size"],
        }
        try:
            save_config(self.config_data)
        except OSError:
            pass  # 存檔失敗不影響本次使用。
        return resolve_translate_settings(self.config_data)

    def _on_run(self):
        if self.is_processing:
            return
        if not self.cues:
            messagebox.showinfo("提示", "目前沒有字幕可翻譯，請先生成字幕。",
                                parent=self)
            return
        settings = self._collect_settings()
        api_key = self.config_data.get("transcription", {}).get(
            "api_key", "").strip()
        self._set_processing(True)
        threading.Thread(
            target=self._run_worker,
            args=(list(self.cues), settings, api_key),
            daemon=True,
        ).start()

    def _run_worker(self, cues, settings, api_key):
        try:
            def report(ratio, message):
                self.result_queue.put(("status", (message, ratio)))
            new_cues = translate_cues(
                cues, settings, api_key, progress_cb=report)
            self.result_queue.put(("done", new_cues))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("字幕翻譯失敗")
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
                    self.progress_var.set(100.0)
                    if callable(self.on_done):
                        self.on_done(payload)
                    messagebox.showinfo(
                        "字幕翻譯", f"翻譯完成：{self.status_var.get()}",
                        parent=self)
                elif kind == "error":
                    self._set_processing(False)
                    self.status_var.set("翻譯失敗。")
                    show_friendly_error(self, "字幕翻譯失敗", payload)
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
