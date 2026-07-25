# -*- coding: utf-8 -*-
"""
字幕健檢對話框：檢查目前字幕清單的閱讀速度（CPS）、顯示時間與行數。

CPS（每秒字元數）超標是字幕檔案審核最常被打回的原因（Netflix 成人內容
上限 20、BBC 建議 15 以下）；本工具生成字幕時雖有斷句限制，但翻譯、
匯入既有字幕檔、手動編輯都可能產生從未檢查過的過快字幕。選好素材、
按「開始健檢」掃描目前清單，過快或過短的句子可按「一鍵延長」自動
利用空檔延長顯示時間（不改動文字內容，空檔不足時保留原樣）。
"""

import tkinter as tk
from tkinter import messagebox, ttk

from config import save_config
from subtitle.subtitlecheck import (analyze_cues, fix_cue_durations,
                                    fix_overlaps, format_subtitle_report,
                                    resolve_subcheck_settings)


class SubtitleCheckDialog(tk.Toplevel):
    """字幕健檢視窗：掃描目前字幕清單並可一鍵延長過快／過短的句子。"""

    def __init__(self, master, config_data, cues, on_fixed=None):
        super().__init__(master)
        self.title("字幕健檢：閱讀速度與行數")
        self.geometry("560x520")
        self.minsize(520, 440)
        self.transient(master)

        self.config_data = config_data
        self.cues = cues
        self.on_fixed = on_fixed
        self.last_result = None

        settings = resolve_subcheck_settings(config_data)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        options = ttk.LabelFrame(body, text="判定門檻（自動記憶）",
                                 padding=(10, 6))
        options.pack(fill="x")
        row1 = ttk.Frame(options)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="閱讀速度上限:").pack(side="left")
        self.cps_var = tk.DoubleVar(value=settings["cps_limit"])
        tk.Spinbox(row1, from_=10.0, to=25.0, increment=1.0, width=6,
                   textvariable=self.cps_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row1, text="字/秒").pack(side="left", padx=(0, 14))
        ttk.Label(row1, text="最短顯示秒數:").pack(side="left")
        self.min_dur_var = tk.DoubleVar(value=settings["min_duration"])
        tk.Spinbox(row1, from_=0.3, to=2.0, increment=0.1, width=6,
                   textvariable=self.min_dur_var, format="%.1f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row1, text="秒").pack(side="left")
        row2 = ttk.Frame(options)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="最多行數:").pack(side="left")
        self.max_lines_var = tk.IntVar(value=settings["max_lines"])
        tk.Spinbox(row2, from_=1, to=4, increment=1, width=6,
                   textvariable=self.max_lines_var).pack(
            side="left", padx=(2, 2))
        ttk.Label(row2, text="行").pack(side="left", padx=(0, 14))
        ttk.Label(row2, text="單行字數上限:").pack(side="left")
        self.max_chars_var = tk.IntVar(value=settings["max_chars_per_line"])
        tk.Spinbox(row2, from_=10, to=60, increment=1, width=6,
                   textvariable=self.max_chars_var).pack(
            side="left", padx=(2, 2))
        ttk.Label(row2, text="字").pack(side="left")

        self.status_var = tk.StringVar(
            value=f"共 {len(cues)} 句字幕，按「開始健檢」掃描閱讀速度與行數。")
        ttk.Label(body, textvariable=self.status_var,
                 foreground="#1a5fb4", wraplength=520, justify="left").pack(
            fill="x", pady=(8, 4))

        report_frame = ttk.LabelFrame(body, text="健檢報告", padding=(6, 6))
        report_frame.pack(fill="both", expand=True, pady=(4, 0))
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
        self.fix_btn = ttk.Button(buttons, text="一鍵延長過快字幕",
                                  state="disabled", command=self._on_fix)
        self.fix_btn.pack(side="left", padx=(6, 0))
        self.fix_overlap_btn = ttk.Button(
            buttons, text="一鍵修復重疊", state="disabled",
            command=self._on_fix_overlap)
        self.fix_overlap_btn.pack(side="left", padx=(6, 0))
        self.copy_btn = ttk.Button(buttons, text="複製報告", state="disabled",
                                   command=self._on_copy)
        self.copy_btn.pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="關閉", command=self.destroy).pack(
            side="right")

        self._on_run()

    def _collect_settings(self):
        def safe(var, fallback, cast=float):
            try:
                return cast(var.get())
            except (tk.TclError, ValueError):
                return fallback
        self.config_data["subtitlecheck"] = {
            "cps_limit": safe(self.cps_var, 17.0),
            "min_duration": safe(self.min_dur_var, 0.8),
            "max_lines": safe(self.max_lines_var, 2, cast=int),
            "max_chars_per_line": safe(self.max_chars_var, 21, cast=int),
        }
        try:
            save_config(self.config_data)
        except OSError:
            pass  # 存檔失敗不影響本次使用。
        return resolve_subcheck_settings(self.config_data)

    def _on_run(self):
        settings = self._collect_settings()
        self.last_result = analyze_cues(self.cues, settings)
        text = format_subtitle_report(self.last_result)
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", text)
        self.report.configure(state="disabled")
        self.copy_btn.configure(state="normal")
        issues = self.last_result["issues"]
        fixable = any(i["title"] in ("閱讀速度過快", "顯示時間過短")
                     for i in issues)
        self.fix_btn.configure(state="normal" if fixable else "disabled")
        overlap_fixable = any(i["title"] == "字幕重疊" for i in issues)
        self.fix_overlap_btn.configure(
            state="normal" if overlap_fixable else "disabled")
        if issues:
            self.status_var.set(f"健檢完成，發現 {len(issues)} 項問題，結果如下。")
        else:
            self.status_var.set("健檢完成，全部句子皆通過。")

    def _on_fix(self):
        settings = self._collect_settings()
        new_cues, fixed = fix_cue_durations(self.cues, settings)
        if fixed == 0:
            messagebox.showinfo(
                "提示",
                "沒有句子能在不與下一句重疊的前提下延長，"
                "可考慮精簡文字內容。", parent=self)
            return
        self.cues = new_cues
        if self.on_fixed:
            self.on_fixed(new_cues)
        self.status_var.set(f"已延長 {fixed} 句字幕的顯示時間，重新健檢中...")
        self._on_run()

    def _on_fix_overlap(self):
        new_cues, fixed = fix_overlaps(self.cues)
        if fixed == 0:
            messagebox.showinfo("提示", "沒有偵測到時間軸重疊的句子。",
                               parent=self)
            return
        self.cues = new_cues
        if self.on_fixed:
            self.on_fixed(new_cues)
        self.status_var.set(f"已修復 {fixed} 處時間軸重疊，重新健檢中...")
        self._on_run()

    def _on_copy(self):
        text = self.report.get("1.0", "end").strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("報告已複製到剪貼簿。")
