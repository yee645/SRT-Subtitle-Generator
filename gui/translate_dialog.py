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
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from config import save_config
from gui.error_dialog import show_friendly_error
from subtitle.multilang import (build_language_pack, format_pack_report,
                                pack_path, parse_languages,
                                resolve_multilang_settings)
from subtitle.translator import (LANGUAGE_LABELS, resolve_translate_settings,
                                 translate_cues)

logger = logging.getLogger(__name__)

_LANGUAGE_CODES_BY_LABEL = {label: code for code, label in LANGUAGE_LABELS.items()}


class TranslateDialog(tk.Toplevel):
    """字幕翻譯視窗：選目標語言與模式，一鍵輸出雙語或取代版字幕。"""

    def __init__(self, master, config_data, cues, on_done=None,
                 media_path=""):
        super().__init__(master)
        self.title("字幕翻譯（雙語字幕）")
        self.resizable(False, False)
        self.transient(master)

        self.config_data = config_data
        self.cues = cues
        self.on_done = on_done
        self.media_path = media_path or ""
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
            body, foreground="#666666", justify="left", wraplength=430,
            text=("使用「轉寫設定」的 OpenAI API 金鑰（未填時按開始會提示）；"
                  "譯文由 AI 產生，建議抽查幾句。\n"
                  "取代模式會覆蓋目前字幕內容（可重新生成復原）。"),
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 6))

        pack_cfg = resolve_multilang_settings(config_data)
        pack_frame = ttk.LabelFrame(
            body, text="多語字幕包（各語言各一個可上傳的單語檔）",
            padding=(10, 6))
        pack_frame.grid(row=3, column=0, columnspan=2, sticky="we",
                        pady=(2, 8))
        pack_frame.columnconfigure(1, weight=1)
        ttk.Label(pack_frame, text="語言代碼：").grid(
            row=0, column=0, sticky="w")
        self.pack_langs_var = tk.StringVar(value=pack_cfg["languages"])
        ttk.Entry(pack_frame, textvariable=self.pack_langs_var).grid(
            row=0, column=1, sticky="we", padx=(4, 4))
        ttk.Button(pack_frame, text="輸出多語字幕包...",
                   command=self._on_pack).grid(row=0, column=2)
        self.pack_dedupe_var = tk.BooleanVar(value=pack_cfg["dedupe"])
        ttk.Checkbutton(
            pack_frame, text="重複句子只送一次（省 API 費用）",
            variable=self.pack_dedupe_var).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(
            pack_frame, foreground="#666666", justify="left", wraplength=430,
            text=("逗號分隔，如 en,ja,ko。上傳用的字幕每個語言都要是單語檔"
                  "——上面的雙語模式是給燒錄用的。"),
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))

        self.status_var = tk.StringVar(
            value=f"共 {len(cues)} 句字幕，按「開始翻譯」。")
        ttk.Label(body, textvariable=self.status_var,
                 foreground="#1a5fb4", wraplength=430, justify="left").grid(
            row=4, column=0, columnspan=2, sticky="w")

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress = ttk.Progressbar(
            body, mode="determinate", maximum=100.0,
            variable=self.progress_var)
        self.progress.grid(row=5, column=0, columnspan=2, sticky="we",
                          pady=(4, 8))

        buttons = ttk.Frame(body)
        buttons.grid(row=6, column=0, columnspan=2, sticky="we")
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

    def _on_pack(self):
        """
        輸出多語字幕包：一份母帶字幕翻成多國語言，各存一個單語 SRT。

        選段與翻譯完全交給 multilang（內部再呼叫既有的 translator），
        本方法只負責收介面參數、挑資料夾與回報。
        """
        if self.is_processing:
            return
        if not self.cues:
            messagebox.showinfo("提示", "目前沒有字幕可翻譯，請先生成字幕。",
                                parent=self)
            return
        source_language = (self.config_data.get("transcription", {})
                           .get("language", "") or "").strip()
        pack_cfg = resolve_multilang_settings(self.config_data)
        languages = parse_languages(
            self.pack_langs_var.get(), source_language=source_language,
            skip_source=pack_cfg["skip_source"])
        if not languages:
            messagebox.showinfo(
                "多語字幕包", format_pack_report({}, []), parent=self)
            return

        api_key = self.config_data.get("transcription", {}).get(
            "api_key", "").strip()
        if not api_key:
            messagebox.showinfo(
                "多語字幕包",
                "多語字幕包需要 OpenAI API 金鑰，請先於「轉寫設定」填入。",
                parent=self)
            return

        out_dir = filedialog.askdirectory(
            parent=self, title="選擇多語字幕包的輸出資料夾")
        if not out_dir:
            return

        # 記住這次選的語言與去重設定。
        self.config_data["multilang"] = {
            "languages": self.pack_langs_var.get(),
            "skip_source": pack_cfg["skip_source"],
            "dedupe": bool(self.pack_dedupe_var.get()),
        }
        try:
            save_config(self.config_data)
        except OSError:
            pass

        batch_size = resolve_translate_settings(self.config_data)["batch_size"]
        self._set_processing(True)
        threading.Thread(
            target=self._pack_worker,
            args=(list(self.cues), languages, api_key, out_dir, batch_size,
                  bool(self.pack_dedupe_var.get())),
            daemon=True,
        ).start()

    def _pack_worker(self, cues, languages, api_key, out_dir, batch_size,
                     dedupe):
        """背景執行緒：逐語言翻譯並各存一個單語 SRT。"""
        from subtitle.exporter import export
        pack, paths, failed = {}, {}, {}
        try:
            def report(ratio, message):
                self.result_queue.put(("status", (message, ratio)))
            for language in languages:
                try:
                    one = build_language_pack(
                        cues, [language], api_key, batch_size=batch_size,
                        dedupe=dedupe, progress_cb=report)
                    pack[language] = one[language]
                    target = pack_path(
                        self.media_path or "字幕", language, out_dir)
                    export(pack[language], target,
                           self.config_data.get("subtitle_style"))
                    paths[language] = target
                except Exception as exc:   # 單一語言失敗不中斷其他語言。
                    logger.exception("多語字幕包：%s 失敗", language)
                    failed[language] = str(exc)
            self.result_queue.put(
                ("pack_done", format_pack_report(pack, languages, paths,
                                                 failed)))
        except Exception as exc:
            logger.exception("多語字幕包失敗")
            self.result_queue.put(("error", exc))

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
                elif kind == "pack_done":
                    self._set_processing(False)
                    self.progress_var.set(100.0)
                    self.status_var.set("多語字幕包輸出完成。")
                    messagebox.showinfo("多語字幕包", payload, parent=self)
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
