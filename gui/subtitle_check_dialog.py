# -*- coding: utf-8 -*-
"""
字幕健檢對話框：檢查目前字幕清單的閱讀速度（CPS）、顯示時間、行數與
廣告友善度（黃標風險）。

CPS（每秒字元數）超標是字幕檔案審核最常被打回的原因（Netflix 成人內容
上限 20、BBC 建議 15 以下）；本工具生成字幕時雖有斷句限制，但翻譯、
匯入既有字幕檔、手動編輯都可能產生從未檢查過的過快字幕。選好素材、
按「開始健檢」掃描目前清單，過快或過短的句子可按「一鍵延長」自動
利用空檔延長顯示時間（不改動文字內容，空檔不足時保留原樣）。

v1.29.0 起同一份報告額外涵蓋**廣告友善度自查**：掃描逐字稿找出
可能觸發 YouTube 廣告友善度審查（黃標）的用詞，並以時間窗叢集分析標出
真正該處理的高風險段落。此段落僅供自查，不會改動任何內容。

v1.33.0 起再加上**開場健檢**：檢查影片開頭多久才進正題、有沒有冗長的
打招呼與自我介紹、有沒有一開場就要訂閱。開頭十幾秒決定觀眾要不要看
下去，而這些正是流失的主因。同樣只報告不改動內容。
"""

import logging
import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from config import save_config
from gui.error_dialog import show_friendly_error
from subtitle.adfriendly import (format_adfriendly_report,
                                 resolve_adfriendly_settings, scan_cues)
from subtitle.burner import ffmpeg_available
from subtitle.hookcheck import (analyze_hook, format_hook_report,
                                resolve_hookcheck_settings)
from subtitle.subsync import (analyze_sync, apply_sync_correction,
                              format_sync_report, resolve_subsync_settings)
from subtitle.subtitlecheck import (analyze_cues, fix_cue_durations,
                                    fix_overlaps, format_subtitle_report,
                                    resolve_subcheck_settings)

logger = logging.getLogger(__name__)


class SubtitleCheckDialog(tk.Toplevel):
    """字幕健檢視窗：掃描目前字幕清單並可一鍵延長過快／過短的句子。"""

    def __init__(self, master, config_data, cues, on_fixed=None,
                 media_path=""):
        super().__init__(master)
        self.title("字幕健檢：閱讀速度、行數、廣告友善度、開場與語音同步")
        # 三組設定區（判定門檻／廣告友善度／開場健檢）加起來就佔掉約 400px，
        # 視窗高度需一併放大，否則下方的報告區會被擠到只剩幾行。
        self.geometry("720x860")
        self.minsize(660, 740)
        self.transient(master)

        self.config_data = config_data
        self.cues = cues
        self.on_fixed = on_fixed
        self.media_path = media_path
        self.last_result = None
        self.last_ad_result = None
        self.last_hook_result = None
        self.last_sync_result = None
        self.is_syncing = False
        self.result_queue = queue.Queue()

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

        # 廣告友善度自查（黃標風險）：詞表可依頻道題材增補與排除誤判。
        ad_settings = resolve_adfriendly_settings(config_data)
        ad_frame = ttk.LabelFrame(
            body, text="廣告友善度自查（僅提醒，不改動內容）", padding=(10, 6))
        ad_frame.pack(fill="x", pady=(8, 0))
        ad_row1 = ttk.Frame(ad_frame)
        ad_row1.pack(fill="x", pady=2)
        ttk.Label(ad_row1, text="叢集時間窗:").pack(side="left")
        self.ad_window_var = tk.DoubleVar(value=ad_settings["window_seconds"])
        tk.Spinbox(ad_row1, from_=10, to=120, increment=5, width=5,
                   textvariable=self.ad_window_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(ad_row1, text="秒").pack(side="left", padx=(0, 12))
        ttk.Label(ad_row1, text="高風險門檻:").pack(side="left")
        self.ad_threshold_var = tk.DoubleVar(
            value=ad_settings["cluster_threshold"])
        tk.Spinbox(ad_row1, from_=1.0, to=10.0, increment=0.5, width=5,
                   textvariable=self.ad_threshold_var, format="%.1f").pack(
            side="left", padx=(2, 2))
        ttk.Label(ad_row1, text="分").pack(side="left", padx=(0, 12))
        ttk.Label(ad_row1, text="開頭加強檢查:").pack(side="left")
        self.ad_opening_var = tk.DoubleVar(
            value=ad_settings["opening_seconds"])
        tk.Spinbox(ad_row1, from_=0, to=30, increment=1, width=5,
                   textvariable=self.ad_opening_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(ad_row1, text="秒").pack(side="left")

        ad_row2 = ttk.Frame(ad_frame)
        ad_row2.pack(fill="x", pady=2)
        ttk.Label(ad_row2, text="自訂補充詞:", width=11).pack(side="left")
        self.ad_extra_var = tk.StringVar(value=ad_settings["extra_terms"])
        ttk.Entry(ad_row2, textvariable=self.ad_extra_var).pack(
            side="left", fill="x", expand=True, padx=(2, 0))
        ad_row3 = ttk.Frame(ad_frame)
        ad_row3.pack(fill="x", pady=2)
        ttk.Label(ad_row3, text="排除誤判詞:", width=11).pack(side="left")
        self.ad_ignore_var = tk.StringVar(value=ad_settings["ignore_terms"])
        ttk.Entry(ad_row3, textvariable=self.ad_ignore_var).pack(
            side="left", fill="x", expand=True, padx=(2, 0))
        ttk.Label(
            ad_frame, foreground="#666666", anchor="w", justify="left",
            wraplength=600,
            text="頻道題材本來就會提及的詞（新聞、歷史、醫療、遊戲頻道）"
                 "請填入「排除誤判詞」，之後不再重複標記。YouTube 未公布"
                 "官方禁用詞清單，本檢查僅為依規範主題整理的自查工具。",
        ).pack(fill="x", pady=(2, 0))

        # 開場健檢：開頭十幾秒決定觀眾走不走，門檻與排除詞依頻道風格可調。
        hook_settings = resolve_hookcheck_settings(config_data)
        hook_frame = ttk.LabelFrame(
            body, text="開場健檢（僅提醒，不改動內容）", padding=(10, 6))
        hook_frame.pack(fill="x", pady=(8, 0))
        hook_row1 = ttk.Frame(hook_frame)
        hook_row1.pack(fill="x", pady=2)
        ttk.Label(hook_row1, text="幾秒內要進正題:").pack(side="left")
        self.hook_target_var = tk.DoubleVar(
            value=hook_settings["target_seconds"])
        tk.Spinbox(hook_row1, from_=5, to=60, increment=1, width=5,
                   textvariable=self.hook_target_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(hook_row1, text="秒").pack(side="left", padx=(0, 12))
        ttk.Label(hook_row1, text="寒暄上限:").pack(side="left")
        self.hook_greeting_var = tk.DoubleVar(
            value=hook_settings["max_greeting_seconds"])
        tk.Spinbox(hook_row1, from_=1, to=30, increment=1, width=5,
                   textvariable=self.hook_greeting_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(hook_row1, text="秒").pack(side="left", padx=(0, 12))
        ttk.Label(hook_row1, text="開頭乾等上限:").pack(side="left")
        self.hook_silence_var = tk.DoubleVar(
            value=hook_settings["max_head_silence"])
        tk.Spinbox(hook_row1, from_=0, to=10, increment=0.5, width=5,
                   textvariable=self.hook_silence_var, format="%.1f").pack(
            side="left", padx=(2, 2))
        ttk.Label(hook_row1, text="秒").pack(side="left")

        hook_row2 = ttk.Frame(hook_frame)
        hook_row2.pack(fill="x", pady=2)
        ttk.Label(hook_row2, text="自訂套語:", width=11).pack(side="left")
        self.hook_extra_var = tk.StringVar(
            value=hook_settings["extra_filler_terms"])
        ttk.Entry(hook_row2, textvariable=self.hook_extra_var).pack(
            side="left", fill="x", expand=True, padx=(2, 0))
        hook_row3 = ttk.Frame(hook_frame)
        hook_row3.pack(fill="x", pady=2)
        ttk.Label(hook_row3, text="排除誤判詞:", width=11).pack(side="left")
        self.hook_ignore_var = tk.StringVar(value=hook_settings["ignore_terms"])
        ttk.Entry(hook_row3, textvariable=self.hook_ignore_var).pack(
            side="left", fill="x", expand=True, padx=(2, 0))
        ttk.Label(
            hook_frame, foreground="#666666", anchor="w", justify="left",
            wraplength=600,
            text="判斷依據是「扣掉開場套語後這句還剩多少實質內容」，"
                 "所以「廢話不多說，今天要教大家…」會正確算成已進正題。"
                 "頻道固定用語若被誤判，填入「排除誤判詞」即可。",
        ).pack(fill="x", pady=(2, 0))

        self.status_var = tk.StringVar(
            value=f"共 {len(cues)} 句字幕，按「開始健檢」掃描閱讀速度與行數。")
        ttk.Label(body, textvariable=self.status_var,
                 foreground="#1a5fb4", wraplength=520, justify="left").pack(
            fill="x", pady=(8, 4))

        report_frame = ttk.LabelFrame(body, text="健檢報告", padding=(6, 6))
        report_frame.pack(fill="both", expand=True, pady=(4, 0))
        self.report = tk.Text(report_frame, wrap="word", state="disabled",
                              font=("Microsoft JhengHei", 10), height=12)
        # 懸掛縮排：報告裡的「建議：」等縮排行較長時會自動折行，若不設定
        # lmargin2，折行後的續行會掉回第 0 欄，讀起來像另一個一級項目。
        self.report.tag_configure("report", lmargin2=28)
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
        ttk.Button(buttons, text="關閉", command=self._on_close).pack(
            side="right")

        # 語音同步檢查需要讀媒體檔（跑一次 ffmpeg），與純文字檢查分開一列。
        sync_row = ttk.Frame(body)
        sync_row.pack(fill="x", pady=(6, 0))
        self.sync_btn = ttk.Button(
            sync_row, text="檢查與語音同步", command=self._on_sync_check)
        self.sync_btn.pack(side="left")
        self.sync_fix_btn = ttk.Button(
            sync_row, text="一鍵校正同步", state="disabled",
            command=self._on_sync_fix)
        self.sync_fix_btn.pack(side="left", padx=(6, 0))
        ttk.Label(
            sync_row, foreground="#666666",
            text="（掃描素材實際語音，抓出整體偏移或幀率漂移）").pack(
            side="left", padx=(8, 0))

        self._poll_job = self.after(120, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
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
        self.config_data["adfriendly"] = {
            "window_seconds": safe(self.ad_window_var, 30.0),
            "cluster_threshold": safe(self.ad_threshold_var, 3.0),
            "opening_seconds": safe(self.ad_opening_var, 7.0),
            "extra_terms": self.ad_extra_var.get().strip(),
            "ignore_terms": self.ad_ignore_var.get().strip(),
        }
        self.config_data["hookcheck"] = {
            "target_seconds": safe(self.hook_target_var, 15.0),
            "max_greeting_seconds": safe(self.hook_greeting_var, 5.0),
            "max_head_silence": safe(self.hook_silence_var, 1.5),
            "extra_filler_terms": self.hook_extra_var.get().strip(),
            "ignore_terms": self.hook_ignore_var.get().strip(),
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
        # 廣告友善度自查：與字幕品質檢查共用同一份報告，但區塊分明。
        self.last_ad_result = scan_cues(
            self.cues, resolve_adfriendly_settings(self.config_data))
        text = f"{text}\n\n{format_adfriendly_report(self.last_ad_result)}"
        # 開場健檢：同樣是純文字分析，與上面兩項共用一次「開始健檢」。
        hook_settings = resolve_hookcheck_settings(self.config_data)
        self.last_hook_result = analyze_hook(self.cues, hook_settings)
        text = (f"{text}\n\n"
                f"{format_hook_report(self.last_hook_result, hook_settings)}")
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", text, "report")
        self.report.configure(state="disabled")
        self.copy_btn.configure(state="normal")
        issues = self.last_result["issues"]
        fixable = any(i["title"] in ("閱讀速度過快", "顯示時間過短")
                     for i in issues)
        self.fix_btn.configure(state="normal" if fixable else "disabled")
        overlap_fixable = any(i["title"] == "字幕重疊" for i in issues)
        self.fix_overlap_btn.configure(
            state="normal" if overlap_fixable else "disabled")
        clusters = len(self.last_ad_result.get("clusters") or [])
        ad_note = f"、廣告友善度高風險段落 {clusters} 處" if clusters else ""
        hook_ok = self.last_hook_result.get("ok")
        hook_note = "" if hook_ok else "、開場有拖累留存的問題"
        if issues:
            self.status_var.set(
                f"健檢完成，發現 {len(issues)} 項字幕問題"
                f"{ad_note}{hook_note}，結果如下。")
        elif clusters or not hook_ok:
            parts = []
            if clusters:
                parts.append(f"{clusters} 處廣告友善度高風險段落")
            if not hook_ok:
                point = self.last_hook_result.get("time_to_point")
                parts.append("開場太久才進正題" if point else "開場無法判定")
            self.status_var.set(
                "健檢完成，字幕品質全數通過，但有" + "、".join(parts)
                + "，詳見報告。")
        else:
            self.status_var.set(
                "健檢完成，字幕品質、廣告友善度與開場皆通過。")

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

    # ------------------------------------------------------------------
    # 字幕與語音同步（需讀媒體檔，於背景執行緒跑 ffmpeg）
    # ------------------------------------------------------------------
    def _on_sync_check(self):
        if self.is_syncing:
            return
        if not self.media_path or not os.path.exists(self.media_path):
            messagebox.showinfo(
                "提示", "請先在主視窗選好對應的影片／音訊素材，"
                       "同步檢查需要讀取實際語音。", parent=self)
            return
        if not ffmpeg_available():
            show_friendly_error(
                self, "同步檢查需要 ffmpeg",
                RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。"))
            return
        self._set_syncing(True)
        self.status_var.set("正在掃描素材語音區間並比對字幕時間軸...")
        threading.Thread(target=self._sync_worker, daemon=True).start()

    def _sync_worker(self):
        try:
            result = analyze_sync(
                self.media_path, self.cues,
                resolve_subsync_settings(self.config_data))
            self.result_queue.put(("sync_done", result))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("字幕同步檢查失敗")
            self.result_queue.put(("sync_error", exc))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.result_queue.get_nowait()
                if kind == "sync_done":
                    self._set_syncing(False)
                    self.last_sync_result = payload
                    self._append_sync_report(payload)
                elif kind == "sync_error":
                    self._set_syncing(False)
                    self.status_var.set("同步檢查失敗。")
                    show_friendly_error(self, "字幕同步檢查失敗", payload)
        except queue.Empty:
            pass
        self._poll_job = self.after(120, self._poll_queue)

    def _append_sync_report(self, result):
        text = self.report.get("1.0", "end").rstrip()
        # 重複檢查時取代舊的同步段落，避免報告越接越長。
        marker = "===== 字幕與語音同步檢查 ====="
        if marker in text:
            text = text.split(marker)[0].rstrip()
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", f"{text}\n\n{format_sync_report(result)}",
                           "report")
        self.report.configure(state="disabled")
        self.report.see("end")
        fixable = result.get("kind") in ("offset", "drift")
        self.sync_fix_btn.configure(state="normal" if fixable else "disabled")
        if fixable:
            self.status_var.set(
                "同步檢查完成：偵測到字幕與語音不同步，可按「一鍵校正同步」。")
        elif result.get("kind") == "unreliable":
            self.status_var.set("同步檢查完成：無法可靠判定，詳見報告。")
        else:
            self.status_var.set("同步檢查完成：字幕與語音同步正常。")

    def _on_sync_fix(self):
        result = self.last_sync_result
        if not result or result.get("kind") not in ("offset", "drift"):
            messagebox.showinfo("提示", "請先按「檢查與語音同步」。", parent=self)
            return
        new_cues = apply_sync_correction(
            self.cues, result["scale"], result["offset"])
        self.cues = new_cues
        if self.on_fixed:
            self.on_fixed(new_cues)
        self.sync_fix_btn.configure(state="disabled")
        self.last_sync_result = None
        self.status_var.set("已套用同步校正，重新健檢中...")
        self._on_run()

    def _set_syncing(self, syncing):
        self.is_syncing = syncing
        state = "disabled" if syncing else "normal"
        self.sync_btn.configure(state=state)

    def _on_close(self):
        if getattr(self, "_poll_job", None):
            self.after_cancel(self._poll_job)
        self.destroy()

    def _on_copy(self):
        text = self.report.get("1.0", "end").strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("報告已複製到剪貼簿。")
