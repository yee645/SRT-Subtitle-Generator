# -*- coding: utf-8 -*-
"""
YouTube 章節健檢對話框：貼上章節文字，直接告訴你為什麼章節不顯示。

章節不符規則時 YouTube 不會給任何錯誤訊息，就只是整批章節都不出現，
創作者只能一條一條試錯。這個對話框把規則變成可檢查的項目，並在意圖
明確的情況下一鍵改好。

輸入不限於本工具產生的章節——手寫的、從別的工具拿到的、從說明欄複製
回來的都可以直接貼進來，這才是實務上最常見的求助情境。影片檔為選填，
提供後才能檢查「最後一章是否太短」。
"""

import logging
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from config import save_config
from gui.error_dialog import show_friendly_error
from subtitle.chaptercheck import (fix_chapters, format_chapter_report,
                                   format_chapters_text, parse_chapters,
                                   resolve_chaptercheck_settings,
                                   validate_chapters)
from subtitle.media import probe_duration

logger = logging.getLogger(__name__)

MEDIA_FILETYPES = [
    ("影片與音訊檔", "*.mp4 *.mkv *.mov *.avi *.flv *.mp3 *.wav *.m4a *.aac"),
    ("所有檔案", "*.*"),
]

_PLACEHOLDER = "0:00 開場\n1:30 主題一\n5:20 主題二"


class ChapterCheckDialog(tk.Toplevel):
    """章節健檢視窗：檢查並修正 YouTube 說明欄章節。"""

    def __init__(self, master, config_data, media_path=None,
                 chapters_text=""):
        super().__init__(master)
        self.title("YouTube 章節健檢：找出章節不顯示的原因")
        self.geometry("760x720")
        self.minsize(680, 600)
        self.transient(master)

        self.config_data = config_data
        self.media_path = media_path or ""
        self._duration = None
        self._chapters = []
        self._errors = []

        settings = resolve_chaptercheck_settings(config_data)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body, anchor="w", justify="left", wraplength=700,
            foreground="#666666",
            text="把章節貼進下面的框（每行「時間戳 空白 標題」）。章節不符 "
                 "YouTube 規則時，貼上說明欄後只會靜靜地不顯示、不會有任何"
                 "錯誤訊息——這裡會直接指出是哪一行、哪一條規則出問題。",
        ).pack(fill="x", pady=(0, 8))

        input_frame = ttk.LabelFrame(body, text="章節文字", padding=(6, 6))
        input_frame.pack(fill="both", expand=True)
        self.input = tk.Text(input_frame, wrap="none", height=8,
                             font=("Microsoft JhengHei", 10))
        input_scroll = ttk.Scrollbar(input_frame, orient="vertical",
                                     command=self.input.yview)
        self.input.configure(yscrollcommand=input_scroll.set)
        self.input.pack(side="left", fill="both", expand=True)
        input_scroll.pack(side="right", fill="y")
        if chapters_text:
            self.input.insert("1.0", chapters_text)
        else:
            self.input.insert("1.0", _PLACEHOLDER)

        media_row = ttk.Frame(body)
        media_row.pack(fill="x", pady=(8, 0))
        ttk.Label(media_row, text="影片（選填）:").pack(side="left")
        self.media_var = tk.StringVar(
            value=os.path.basename(self.media_path) if self.media_path
            else "未選擇——最後一章的長度將無法檢查")
        ttk.Label(media_row, textvariable=self.media_var, foreground="#1a5fb4",
                  width=44, anchor="w").pack(side="left", padx=(4, 6))
        ttk.Button(media_row, text="選擇影片...",
                   command=self._choose_media).pack(side="left")
        ttk.Button(media_row, text="清除",
                   command=self._clear_media).pack(side="left", padx=(6, 0))

        options = ttk.LabelFrame(body, text="規則門檻（自動記憶）",
                                 padding=(10, 6))
        options.pack(fill="x", pady=(8, 0))
        row = ttk.Frame(options)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="每章最短:").pack(side="left")
        self.min_seconds_var = tk.DoubleVar(
            value=settings["min_chapter_seconds"])
        tk.Spinbox(row, from_=1, to=120, increment=1, width=5,
                   textvariable=self.min_seconds_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row, text="秒").pack(side="left", padx=(0, 12))
        ttk.Label(row, text="最少章節數:").pack(side="left")
        self.min_count_var = tk.IntVar(value=settings["min_chapter_count"])
        tk.Spinbox(row, from_=2, to=10, increment=1, width=5,
                   textvariable=self.min_count_var).pack(
            side="left", padx=(2, 2))
        ttk.Label(row, text="章").pack(side="left")
        ttk.Label(
            options, foreground="#666666", anchor="w", justify="left",
            wraplength=680,
            text="預設值就是 YouTube 目前的規則（每章 10 秒、至少 3 章），"
                 "一般不需要調整；可調是為了因應規則變動或其他平台。",
        ).pack(fill="x", pady=(4, 0))

        self.status_var = tk.StringVar(
            value="貼上章節後按「開始檢查」，不會改動任何檔案。")
        ttk.Label(body, textvariable=self.status_var, foreground="#1a5fb4",
                  wraplength=700, justify="left").pack(fill="x", pady=(8, 0))

        report_frame = ttk.LabelFrame(body, text="健檢報告", padding=(6, 6))
        report_frame.pack(fill="both", expand=True, pady=(4, 0))
        self.report = tk.Text(report_frame, wrap="word", state="disabled",
                              font=("Microsoft JhengHei", 10), height=10)
        # 「建議：」這種長句換行後要縮排，否則看起來像新的一個項目。
        self.report.tag_configure("report", lmargin2=28)
        scrollbar = ttk.Scrollbar(report_frame, orient="vertical",
                                  command=self.report.yview)
        self.report.configure(yscrollcommand=scrollbar.set)
        self.report.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="開始檢查",
                   command=self._on_check).pack(side="left")
        self.fix_btn = ttk.Button(buttons, text="一鍵修正", state="disabled",
                                  command=self._on_fix)
        self.fix_btn.pack(side="left", padx=(6, 0))
        self.copy_btn = ttk.Button(buttons, text="複製章節", state="disabled",
                                   command=self._on_copy)
        self.copy_btn.pack(side="left", padx=(6, 0))
        self.save_btn = ttk.Button(buttons, text="另存報告...",
                                   state="disabled", command=self._on_save)
        self.save_btn.pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="關閉", command=self.destroy).pack(
            side="right")

    # ------------------------------------------------------------------
    def _choose_media(self):
        path = filedialog.askopenfilename(
            title="選擇影片（用來檢查最後一章的長度）",
            filetypes=MEDIA_FILETYPES, parent=self)
        if not path:
            return
        self.media_path = path
        self._duration = None
        self.media_var.set(os.path.basename(path))

    def _clear_media(self):
        self.media_path = ""
        self._duration = None
        self.media_var.set("未選擇——最後一章的長度將無法檢查")

    def _collect_settings(self):
        def safe(var, fallback, cast=float):
            try:
                return cast(var.get())
            except (tk.TclError, ValueError):
                return fallback
        self.config_data["chaptercheck"] = {
            "min_chapter_seconds": safe(self.min_seconds_var, 10.0),
            "min_chapter_count": safe(self.min_count_var, 3, cast=int),
        }
        try:
            save_config(self.config_data)
        except OSError:
            pass  # 存檔失敗不影響本次使用。
        return resolve_chaptercheck_settings(self.config_data)

    def _resolve_duration(self):
        """取得影片長度；未選影片或探測失敗時回 None（僅少檢查最後一章）。"""
        if not self.media_path:
            return None
        if self._duration is None:
            try:
                self._duration = probe_duration(self.media_path)
            except Exception:
                logger.warning("章節健檢取得影片長度失敗", exc_info=True)
                self.status_var.set(
                    "讀不到影片長度，最後一章的長度無法檢查（其餘照常）。")
                self.media_path = ""
                self.media_var.set("讀取失敗——最後一章的長度將無法檢查")
                return None
        return self._duration

    def _show_report(self, text):
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", text, "report")
        self.report.configure(state="disabled")
        self.save_btn.configure(state="normal")

    # ------------------------------------------------------------------
    def _on_check(self):
        try:
            settings = self._collect_settings()
            raw = self.input.get("1.0", "end")
            chapters, errors = parse_chapters(raw)
            self._errors = errors
            duration = self._resolve_duration()
            result = validate_chapters(chapters, duration, settings, errors)
            self._chapters = chapters
            self._show_report(
                format_chapter_report(result, chapters=chapters))
            self.copy_btn.configure(
                state="normal" if chapters else "disabled")
            self.fix_btn.configure(
                state="disabled" if result["ok"] else "normal")
            if result["ok"]:
                self.status_var.set(
                    "符合 YouTube 章節規則，可直接貼到說明欄。")
            else:
                self.status_var.set(
                    "有不符規則的項目——照這樣貼上去章節不會顯示。"
                    "可按「一鍵修正」讓程式改掉能安全修正的部分。")
        except Exception as exc:  # pragma: no cover - GUI 防護
            logger.exception("章節健檢失敗")
            show_friendly_error(self, exc, title="章節健檢失敗")

    def _on_fix(self):
        try:
            settings = self._collect_settings()
            duration = self._resolve_duration()
            fixed, changes = fix_chapters(
                self._chapters, duration, settings,
                parse_errors=getattr(self, "_errors", None))
            result = validate_chapters(fixed, duration, settings)
            self._chapters = fixed
            text = format_chapters_text(fixed)
            # 修正結果直接寫回輸入框：使用者看得到改成什麼樣，也能再手動微調。
            self.input.delete("1.0", "end")
            self.input.insert("1.0", text)
            self._errors = []
            self._show_report(
                format_chapter_report(result, chapters=fixed, changes=changes))
            self.copy_btn.configure(state="normal" if fixed else "disabled")
            self.fix_btn.configure(
                state="disabled" if result["ok"] else "normal")
            if result["ok"]:
                self.status_var.set(
                    "已修正並通過檢查，可按「複製章節」貼到說明欄。")
            else:
                self.status_var.set(
                    "格式問題已修好，但仍有無法自動解決的項目"
                    "（例如章節數不足）——那需要你決定影片要怎麼分段。")
        except Exception as exc:  # pragma: no cover - GUI 防護
            logger.exception("章節修正失敗")
            show_friendly_error(self, exc, title="章節修正失敗")

    def _on_copy(self):
        text = format_chapters_text(self._chapters)
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("章節已複製到剪貼簿，可直接貼上 YouTube 說明欄。")

    def _on_save(self):
        path = filedialog.asksaveasfilename(
            title="另存章節健檢報告", defaultextension=".txt",
            initialfile="章節健檢.txt",
            filetypes=[("純文字檔", "*.txt")], parent=self)
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(self.report.get("1.0", "end").rstrip() + "\n")
        except OSError as exc:
            messagebox.showerror("儲存失敗", str(exc), parent=self)
            return
        self.status_var.set(f"報告已儲存：{path}")
