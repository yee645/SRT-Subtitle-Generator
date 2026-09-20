# -*- coding: utf-8 -*-
"""
文字辨識（OCR）一鍵安裝對話框：比照 `gui/ffmpeg_dialog.py`。

和 ffmpeg 那個不同的地方只有一處，但很重要：**這裡要裝的是兩樣東西，而
且兩樣的性質差很多**——引擎本體約 50~60 MB、官方只出 Windows 安裝檔；語
言檔每個才 2~4 MB、直接下載單一檔案就好。所以介面上讓使用者看得到自己缺
的是哪一半，也能只補語言檔（很常見：系統上已經有 tesseract，但沒有中文
或日文資料）。

真正的下載與安裝在 `subtitle/tesseract_setup.py`（零 GUI 依賴、可離線
測），這裡只負責畫面與背景執行緒調度。
"""

import logging
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from subtitle import ocrengine, tesseract_setup as ts

logger = logging.getLogger(__name__)

# 預設勾選的語言：介面是中文的，來源語言最常見的是英文與日文。
_DEFAULT_LANGS = ("eng", "jpn", "chi_tra")


class TesseractInstallDialog(tk.Toplevel):
    """自動安裝文字辨識引擎與語言檔；完成後回呼 on_done。"""

    def __init__(self, master, on_done=None, langs=None):
        super().__init__(master)
        self.title("安裝文字辨識（OCR）")
        self.resizable(False, False)
        self.transient(master)
        self._on_done = on_done
        self._queue = queue.Queue()
        self._started = False

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body, wraplength=460, justify="left",
            text=("螢幕翻譯要用到文字辨識。安裝到程式自己的資料夾——"
                  "不需要管理員權限、不會改動系統設定，裝完立即可用。\n"
                  "辨識在這台電腦上跑，畫面不會被傳出去。"),
        ).pack(anchor="w")

        self.engine_var = tk.BooleanVar(value=not ocrengine.tesseract_available())
        have = ocrengine.tesseract_available()
        engine_text = ("辨識引擎（約 50~60 MB，只需一次）"
                       if not have else "辨識引擎（已安裝，可略過）")
        self.engine_check = ttk.Checkbutton(
            body, text=engine_text, variable=self.engine_var)
        self.engine_check.pack(anchor="w", pady=(10, 2))

        langs_frame = ttk.LabelFrame(body, text="語言檔（每個約 2~4 MB）",
                                     padding=(10, 6))
        langs_frame.pack(fill="x", pady=(6, 0))
        installed = ts.installed_languages()
        wanted = set(langs or _DEFAULT_LANGS)
        self.lang_vars = {}
        for index, (code, label) in enumerate(ts.LANGUAGE_LABELS):
            var = tk.BooleanVar(value=code in wanted and code not in installed)
            self.lang_vars[code] = var
            text = f"{label}（已安裝）" if code in installed else label
            ttk.Checkbutton(langs_frame, text=text, variable=var).grid(
                row=index // 3, column=index % 3, sticky="w",
                padx=(0, 16), pady=2)

        self.status_var = tk.StringVar(value=ts.describe_state())
        ttk.Label(body, textvariable=self.status_var, foreground="#1a5fb4",
                  wraplength=460, justify="left").pack(anchor="w", pady=(10, 2))
        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(body, mode="determinate", maximum=100.0, length=460,
                        variable=self.progress_var).pack(fill="x", pady=(0, 10))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        self.start_btn = ttk.Button(buttons, text="開始安裝",
                                    command=self._on_start)
        self.start_btn.pack(side="left")
        ttk.Button(buttons, text="關閉", command=self._on_close).pack(
            side="right")

        self._poll_job = self.after(120, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def selected_languages(self):
        return [code for code, var in self.lang_vars.items() if var.get()]

    def _on_start(self):
        if self._started:
            return
        langs = self.selected_languages()
        if not self.engine_var.get() and not langs:
            messagebox.showinfo("提示", "請至少勾選一項要安裝的東西。",
                                parent=self)
            return
        self._started = True
        self.start_btn.configure(state="disabled", text="安裝中...")
        threading.Thread(target=self._worker, args=(self.engine_var.get(),
                                                    langs),
                         daemon=True).start()

    def _worker(self, want_engine, langs):
        def report(ratio, message):
            self._queue.put(("status", (message, ratio)))

        try:
            done = []
            # 引擎先裝：語言檔沒有引擎也用不了，順序反過來會讓使用者在
            # 引擎失敗時以為「至少語言檔裝好了」。
            if want_engine:
                done.append(ts.install_engine(
                    progress_cb=lambda r, m: report(r * 0.8, m)))
            if langs:
                base = 0.8 if want_engine else 0.0
                span = 0.2 if want_engine else 1.0
                done.append(ts.install_languages(
                    langs, progress_cb=lambda r, m: report(base + r * span, m)))
            self._queue.put(("done", done))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("文字辨識自動安裝失敗")
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
                        "文字辨識已就緒：\n" + "\n".join(payload)
                        + "\n\n不需要重新啟動，現在就可以用。",
                        parent=self)
                    if self._on_done:
                        self._on_done()
                    self._close()
                    return
                elif kind == "error":
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
