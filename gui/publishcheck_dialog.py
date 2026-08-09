# -*- coding: utf-8 -*-
"""
發佈資訊健檢對話框：貼上標題、說明欄與標籤，檢查各項上限。

最要緊的一項是 **hashtag 超過 15 個時 YouTube 會「忽略全部」而且不給
任何提示**——創作者堆了 16 個想要更多曝光，實際上得到零個生效。這與
章節不顯示（v1.32.0）是同一種靜默失敗。

另一個對中文使用者的關鍵差異是**說明欄的上限算的是位元組不是字數**：
中文一個字佔 3 個位元組，所以中文說明大約寫到 1,600 多字就會撞上限，
用字數檢查會完全誤判。

輸入是使用者直接貼上的文字，不限於本工具的發佈包產出——最常見的情境
正是「我自己寫的說明欄，為什麼 hashtag 沒有作用」。
"""

import logging
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from config import save_config
from gui.error_dialog import show_friendly_error
from subtitle.publishcheck import (analyze_publish, format_publish_report,
                                   resolve_publishcheck_settings)

logger = logging.getLogger(__name__)


class PublishCheckDialog(tk.Toplevel):
    """發佈資訊健檢視窗：檢查標題／說明欄／hashtag／標籤的上限。"""

    def __init__(self, master, config_data, title_text="", description="",
                 tags=""):
        super().__init__(master)
        self.title("發佈資訊健檢：標題、說明欄、hashtag 與標籤")
        self.geometry("760x820")
        self.minsize(680, 700)
        self.transient(master)

        self.config_data = config_data
        self.report_text = ""

        settings = resolve_publishcheck_settings(config_data)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body, anchor="w", justify="left", wraplength=700,
            foreground="#666666",
            text="把要發佈的標題與說明欄貼進來。最要緊的是 hashtag："
                 "超過 15 個時 YouTube 會「忽略全部」而且不給任何提示，"
                 "你會得到零個生效的 hashtag。說明欄的上限則是算「位元組」"
                 "不是字數——中文一個字佔 3 個位元組。",
        ).pack(fill="x", pady=(0, 8))

        title_row = ttk.Frame(body)
        title_row.pack(fill="x")
        ttk.Label(title_row, text="標題：", width=7).pack(side="left")
        self.title_var = tk.StringVar(value=title_text)
        ttk.Entry(title_row, textvariable=self.title_var).pack(
            side="left", fill="x", expand=True)

        desc_frame = ttk.LabelFrame(body, text="說明欄", padding=(6, 6))
        desc_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.description = tk.Text(desc_frame, wrap="word", height=8,
                                   font=("Microsoft JhengHei", 10))
        desc_scroll = ttk.Scrollbar(desc_frame, orient="vertical",
                                    command=self.description.yview)
        self.description.configure(yscrollcommand=desc_scroll.set)
        self.description.pack(side="left", fill="both", expand=True)
        desc_scroll.pack(side="right", fill="y")
        if description:
            self.description.insert("1.0", description)

        tags_row = ttk.Frame(body)
        tags_row.pack(fill="x", pady=(8, 0))
        ttk.Label(tags_row, text="標籤：", width=7).pack(side="left")
        self.tags_var = tk.StringVar(value=tags)
        ttk.Entry(tags_row, textvariable=self.tags_var).pack(
            side="left", fill="x", expand=True)
        ttk.Label(body, foreground="#666666", anchor="w",
                  text="（標籤以逗號分隔，就是 YouTube 後台那一欄的填法）"
                  ).pack(fill="x")

        options = ttk.LabelFrame(body, text="上限設定（自動記憶）",
                                 padding=(10, 6))
        options.pack(fill="x", pady=(8, 0))
        row1 = ttk.Frame(options)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="hashtag 上限:").pack(side="left")
        self.max_tag_var = tk.IntVar(value=settings["max_hashtags"])
        tk.Spinbox(row1, from_=1, to=30, increment=1, width=5,
                   textvariable=self.max_tag_var).pack(side="left", padx=(2, 2))
        ttk.Label(row1, text="個").pack(side="left", padx=(0, 12))
        ttk.Label(row1, text="建議上限:").pack(side="left")
        self.rec_tag_var = tk.IntVar(value=settings["recommended_hashtags"])
        tk.Spinbox(row1, from_=1, to=15, increment=1, width=5,
                   textvariable=self.rec_tag_var).pack(side="left", padx=(2, 2))
        ttk.Label(row1, text="個").pack(side="left", padx=(0, 12))
        ttk.Label(row1, text="標題上限:").pack(side="left")
        self.title_limit_var = tk.IntVar(value=settings["title_limit"])
        tk.Spinbox(row1, from_=20, to=200, increment=10, width=5,
                   textvariable=self.title_limit_var).pack(
            side="left", padx=(2, 2))
        ttk.Label(row1, text="字元").pack(side="left")

        row2 = ttk.Frame(options)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="手機可見標題:").pack(side="left")
        self.mobile_var = tk.IntVar(value=settings["title_mobile_visible"])
        tk.Spinbox(row2, from_=10, to=100, increment=5, width=5,
                   textvariable=self.mobile_var).pack(side="left", padx=(2, 2))
        ttk.Label(row2, text="字元").pack(side="left", padx=(0, 12))
        ttk.Label(row2, text="說明欄上限:").pack(side="left")
        self.desc_limit_var = tk.IntVar(
            value=settings["description_byte_limit"])
        tk.Spinbox(row2, from_=500, to=10000, increment=500, width=7,
                   textvariable=self.desc_limit_var).pack(
            side="left", padx=(2, 2))
        ttk.Label(row2, text="位元組").pack(side="left", padx=(0, 12))
        ttk.Label(row2, text="標籤上限:").pack(side="left")
        self.tag_char_var = tk.IntVar(value=settings["tag_char_limit"])
        tk.Spinbox(row2, from_=100, to=1000, increment=50, width=6,
                   textvariable=self.tag_char_var).pack(
            side="left", padx=(2, 2))
        ttk.Label(row2, text="字元").pack(side="left")

        self.status_var = tk.StringVar(
            value="貼上內容後按「開始健檢」，不會改動任何檔案。")
        ttk.Label(body, textvariable=self.status_var, foreground="#1a5fb4",
                  wraplength=700, justify="left").pack(fill="x", pady=(8, 0))

        report_frame = ttk.LabelFrame(body, text="健檢報告", padding=(6, 6))
        report_frame.pack(fill="both", expand=True, pady=(4, 0))
        self.report = tk.Text(report_frame, wrap="word", state="disabled",
                              font=("Microsoft JhengHei", 10), height=9)
        # 「建議：」這種長句換行後要縮排，否則看起來像新的一個項目。
        self.report.tag_configure("report", lmargin2=28)
        scrollbar = ttk.Scrollbar(report_frame, orient="vertical",
                                  command=self.report.yview)
        self.report.configure(yscrollcommand=scrollbar.set)
        self.report.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="開始健檢",
                   command=self._on_run).pack(side="left")
        self.copy_btn = ttk.Button(buttons, text="複製報告", state="disabled",
                                   command=self._on_copy)
        self.copy_btn.pack(side="left", padx=(6, 0))
        self.save_btn = ttk.Button(buttons, text="另存報告...",
                                   state="disabled", command=self._on_save)
        self.save_btn.pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="關閉", command=self.destroy).pack(
            side="right")

    # ------------------------------------------------------------------
    def _collect_settings(self):
        def safe(var, fallback):
            try:
                return int(var.get())
            except (tk.TclError, ValueError):
                return fallback
        self.config_data["publishcheck"] = {
            "title_limit": safe(self.title_limit_var, 100),
            "title_mobile_visible": safe(self.mobile_var, 40),
            "description_byte_limit": safe(self.desc_limit_var, 5000),
            "max_hashtags": safe(self.max_tag_var, 15),
            "recommended_hashtags": safe(self.rec_tag_var, 5),
            "tag_char_limit": safe(self.tag_char_var, 500),
        }
        try:
            save_config(self.config_data)
        except OSError:
            pass  # 存檔失敗不影響本次使用。
        return resolve_publishcheck_settings(self.config_data)

    def _on_run(self):
        try:
            settings = self._collect_settings()
            result = analyze_publish(
                self.title_var.get(),
                self.description.get("1.0", "end"),
                self.tags_var.get(),
                settings)
            self.report_text = format_publish_report(result, settings)
            self.report.configure(state="normal")
            self.report.delete("1.0", "end")
            self.report.insert("1.0", self.report_text, "report")
            self.report.configure(state="disabled")
            self.copy_btn.configure(state="normal")
            self.save_btn.configure(state="normal")

            stats = result.get("stats") or {}
            if result.get("ok"):
                self.status_var.set("符合 YouTube 的各項上限，可以直接使用。")
            elif stats.get("hashtag_count", 0) > settings["max_hashtags"]:
                self.status_var.set(
                    f"hashtag 共 {stats['hashtag_count']} 個，超過上限——"
                    "貼上去之後「全部」都不會生效，詳見報告。")
            else:
                self.status_var.set("有超過上限的項目，詳見報告。")
        except Exception as exc:  # pragma: no cover - GUI 防護
            logger.exception("發佈資訊健檢失敗")
            show_friendly_error(self, exc, title="發佈資訊健檢失敗")

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
            title="另存發佈資訊健檢報告", defaultextension=".txt",
            initialfile="發佈健檢.txt",
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
