# -*- coding: utf-8 -*-
"""
審片助手視窗：拍完素材後用文字快速找可用片段。

流程：
1. 按「開始分析」→ 背景轉錄素材並自動分段，列出所有講話段落與冷場。
2. 清單自動標記「冷場」「重複拍攝」「口頭禪多」，前兩者預設捨棄。
3. 讀文字掃一遍清單，雙擊（或按空白鍵）切換單段的保留 / 捨棄。
4. 一鍵輸出：粗剪影片（自動跳剪）、EDL（進剪輯軟體精剪）、
   CSV 片段清單、YouTube 章節草稿。
"""

import logging
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from subtitle.burner import ffmpeg_available
from subtitle.media import probe_duration
from subtitle.pipeline import unique_path
from subtitle.review import (DEFAULT_SEGMENT_GAP, DEFAULT_SILENCE_GAP,
                             TAG_REPEATED, TAG_SILENCE, analyze,
                             cut_rough_video, export_csv, export_edl,
                             export_youtube_chapters, search_segments)
from subtitle.transcriber import transcribe

logger = logging.getLogger(__name__)


class ReviewWindow(tk.Toplevel):
    """審片助手：以逐字稿審素材、標記可剪片段、輸出粗剪與剪輯清單。"""

    def __init__(self, master, config_data, media_path):
        super().__init__(master)
        self.title("審片助手：快速找可用片段")
        self.geometry("960x640")
        self.minsize(720, 480)

        self.config_data = config_data
        self.media_path = media_path
        self.items = []              # analyze() 的段落清單
        self.result_queue = queue.Queue()
        self.is_processing = False
        self._search_hits = []       # 目前關鍵字命中的段落索引
        self._search_pos = -1        # 下一個要跳到的命中位置

        self._build_widgets()
        self._poll_job = self.after(120, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ==================================================================
    # 介面
    # ==================================================================
    def _build_widgets(self):
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        ttk.Label(
            top, text=f"素材：{os.path.basename(self.media_path)}",
            font=("Microsoft JhengHei", 10, "bold"),
        ).pack(side="left")

        # 分析參數與開始按鈕。
        options = ttk.Frame(self, padding=(10, 0))
        options.pack(fill="x")
        tk.Label(options, text="冷場門檻:").pack(side="left")
        self.silence_var = tk.DoubleVar(value=DEFAULT_SILENCE_GAP)
        tk.Spinbox(
            options, from_=0.5, to=10.0, increment=0.5, width=5,
            textvariable=self.silence_var, format="%.1f",
        ).pack(side="left", padx=(2, 10))
        tk.Label(options, text="秒　段落切分停頓:").pack(side="left")
        self.gap_var = tk.DoubleVar(value=DEFAULT_SEGMENT_GAP)
        tk.Spinbox(
            options, from_=0.4, to=5.0, increment=0.2, width=5,
            textvariable=self.gap_var, format="%.1f",
        ).pack(side="left", padx=(2, 10))
        tk.Label(options, text="秒").pack(side="left")
        self.analyze_btn = tk.Button(
            options, text="開始分析", width=12, command=self._on_analyze)
        self.analyze_btn.pack(side="left", padx=(16, 0))

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress = ttk.Progressbar(
            options, mode="determinate", length=160, maximum=100.0,
            variable=self.progress_var)
        self.progress.pack(side="left", padx=8)

        self.status_var = tk.StringVar(
            value="按「開始分析」轉錄素材並自動標記可剪片段。")
        tk.Label(self, textvariable=self.status_var, fg="#1a5fb4",
                 anchor="w", padx=10).pack(fill="x")

        # 段落清單。
        frame = ttk.LabelFrame(
            self, text="段落清單（雙擊或空白鍵切換保留／捨棄）", padding=(6, 6))
        frame.pack(fill="both", expand=True, padx=10, pady=(4, 0))
        columns = ("keep", "index", "time", "duration", "tags", "text")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings")
        headers = [("keep", "保留", 44), ("index", "#", 40),
                   ("time", "時間", 150), ("duration", "秒數", 56),
                   ("tags", "標記", 110), ("text", "內容", 460)]
        for key, label, width in headers:
            self.tree.heading(key, text=label)
            anchor = "w" if key == "text" else "center"
            self.tree.column(key, width=width, anchor=anchor,
                             stretch=(key == "text"))
        scrollbar = ttk.Scrollbar(frame, orient="vertical",
                                  command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _e: self._toggle_selected())
        self.tree.bind("<space>", lambda _e: self._toggle_selected())
        # 捨棄的段落以灰字顯示，一眼可分。
        self.tree.tag_configure("dropped", foreground="#999999")

        # 段落操作與搜尋。
        ops = ttk.Frame(self, padding=(10, 4))
        ops.pack(fill="x")
        tk.Button(ops, text="切換保留", width=9,
                  command=self._toggle_selected).pack(side="left", padx=2)
        tk.Button(ops, text="套用建議", width=9,
                  command=self._apply_suggestions).pack(side="left", padx=2)
        tk.Button(ops, text="全部保留", width=9,
                  command=self._keep_all).pack(side="left", padx=2)
        tk.Label(ops, text="關鍵字:").pack(side="left", padx=(14, 2))
        self.search_var = tk.StringVar()
        entry = tk.Entry(ops, textvariable=self.search_var, width=18)
        entry.pack(side="left")
        entry.bind("<Return>", lambda _e: self._on_search())
        tk.Button(ops, text="搜尋下一個", width=10,
                  command=self._on_search).pack(side="left", padx=4)

        # 匯出列。
        exports = ttk.LabelFrame(self, text="輸出", padding=(10, 6))
        exports.pack(fill="x", padx=10, pady=(2, 10))
        self.export_buttons = []
        for label, command in [
                ("輸出粗剪影片（自動跳剪）", self._on_rough_cut),
                ("匯出 EDL（進剪輯軟體）", self._on_export_edl),
                ("匯出 CSV 清單", self._on_export_csv),
                ("複製 YouTube 章節", self._on_copy_chapters)]:
            btn = tk.Button(exports, text=label, command=command,
                            state="disabled")
            btn.pack(side="left", padx=3)
            self.export_buttons.append(btn)

    # ==================================================================
    # 分析
    # ==================================================================
    def _on_analyze(self):
        if self.is_processing:
            return
        self._set_processing(True)
        silence_gap = max(0.5, float(self.silence_var.get()))
        segment_gap = max(0.4, float(self.gap_var.get()))
        threading.Thread(
            target=self._analyze_worker, args=(segment_gap, silence_gap),
            daemon=True).start()

    def _analyze_worker(self, segment_gap, silence_gap):
        try:
            def report(message, ratio=None):
                if ratio is not None:
                    ratio *= 0.95  # 轉錄後還有分析步驟，保留尾段進度。
                self.result_queue.put(("status", (message, ratio)))

            words = transcribe(self.media_path, self.config_data, report)
            report("正在分析段落與標記...", None)
            duration = probe_duration(self.media_path)
            items = analyze(
                words, media_duration=duration,
                segment_gap=segment_gap, silence_gap=silence_gap)
            self.result_queue.put(("done", items))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("審片分析失敗")
            self.result_queue.put(("error", str(exc)))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.result_queue.get_nowait()
                if kind == "status":
                    message, ratio = payload
                    self.status_var.set(message)
                    self.progress_var.set(
                        (ratio or 0.0) * 100.0 if ratio is not None
                        else self.progress_var.get())
                elif kind == "done":
                    self._on_analyze_done(payload)
                elif kind == "cut_done":
                    self._set_processing(False)
                    self.status_var.set(f"粗剪完成：{payload}")
                    messagebox.showinfo(
                        "粗剪完成", f"已輸出影片：\n{payload}", parent=self)
                elif kind == "error":
                    self._set_processing(False)
                    self.status_var.set("處理失敗。")
                    messagebox.showerror("處理失敗", payload, parent=self)
        except queue.Empty:
            pass
        self._poll_job = self.after(120, self._poll_queue)

    def _on_analyze_done(self, items):
        self.items = items
        self._set_processing(False)
        self._repopulate()
        speech = sum(1 for i in items if i["kind"] == "speech")
        dropped = sum(1 for i in items if not i["keep"])
        kept_seconds = sum(i["end"] - i["start"] for i in items if i["keep"])
        self.status_var.set(
            f"分析完成：{speech} 個講話段落，建議捨棄 {dropped} 段；"
            f"保留內容約 {kept_seconds / 60.0:.1f} 分鐘。請掃一遍清單微調。")

    # ==================================================================
    # 清單操作
    # ==================================================================
    def _repopulate(self, keep_selection=False):
        selected = self.tree.selection()
        selected_index = None
        if keep_selection and selected:
            selected_index = self.tree.index(selected[0])
        self.tree.delete(*self.tree.get_children())
        for number, item in enumerate(self.items, start=1):
            minutes, secs = divmod(int(item["start"]), 60)
            end_m, end_s = divmod(int(item["end"]), 60)
            self.tree.insert(
                "", "end",
                values=("✔" if item["keep"] else "✘",
                        number,
                        f"{minutes:02d}:{secs:02d} → {end_m:02d}:{end_s:02d}",
                        f"{item['end'] - item['start']:.1f}",
                        "、".join(item["tags"]),
                        item["text"]),
                tags=() if item["keep"] else ("dropped",))
        children = self.tree.get_children()
        if selected_index is not None and selected_index < len(children):
            self.tree.selection_set(children[selected_index])
            self.tree.focus(children[selected_index])
        self._update_export_state()

    def _toggle_selected(self):
        selection = self.tree.selection()
        if not selection or not self.items:
            return
        for item_id in selection:
            index = self.tree.index(item_id)
            self.items[index]["keep"] = not self.items[index]["keep"]
        self._repopulate(keep_selection=True)

    def _apply_suggestions(self):
        """回復到系統建議：冷場與重複拍攝捨棄、其餘保留。"""
        for item in self.items:
            item["keep"] = (item["kind"] == "speech"
                            and not set(item["tags"]) & {TAG_SILENCE,
                                                         TAG_REPEATED})
        self._repopulate()
        self.status_var.set("已套用系統建議（捨棄冷場與重複拍攝）。")

    def _keep_all(self):
        for item in self.items:
            item["keep"] = True
        self._repopulate()
        self.status_var.set("已全部標記為保留。")

    def _on_search(self):
        """搜尋關鍵字並逐一跳到命中的段落。"""
        keyword = self.search_var.get()
        hits = search_segments(self.items, keyword)
        if not hits:
            self.status_var.set(f"找不到「{keyword}」。")
            return
        if hits != self._search_hits:
            self._search_hits, self._search_pos = hits, -1
        self._search_pos = (self._search_pos + 1) % len(hits)
        target = hits[self._search_pos]
        children = self.tree.get_children()
        self.tree.selection_set(children[target])
        self.tree.focus(children[target])
        self.tree.see(children[target])
        self.status_var.set(
            f"「{keyword}」共 {len(hits)} 段，"
            f"目前第 {self._search_pos + 1} 段。")

    # ==================================================================
    # 匯出
    # ==================================================================
    def _default_path(self, suffix, ext):
        base = os.path.splitext(os.path.basename(self.media_path))[0]
        out_dir = os.path.dirname(os.path.abspath(self.media_path))
        return unique_path(os.path.join(out_dir, f"{base}{suffix}{ext}"))

    def _on_rough_cut(self):
        if self.is_processing or not self.items:
            return
        if not ffmpeg_available():
            messagebox.showerror(
                "找不到 ffmpeg",
                "粗剪輸出需要 ffmpeg。請依說明安裝並加入系統 PATH。",
                parent=self)
            return
        output = self._default_path("_粗剪", ".mp4")
        self._set_processing(True)
        threading.Thread(
            target=self._cut_worker, args=(output,), daemon=True).start()

    def _cut_worker(self, output):
        try:
            cut_rough_video(
                self.media_path, self.items, output,
                progress_cb=lambda ratio, msg: self.result_queue.put(
                    ("status", (msg, ratio))))
            self.result_queue.put(("cut_done", output))
        except Exception as exc:
            logger.exception("粗剪輸出失敗")
            self.result_queue.put(("error", str(exc)))

    def _on_export_edl(self):
        if not self.items:
            return
        path = self._default_path("_粗剪", ".edl")
        try:
            export_edl(self.items, path,
                       clip_name=os.path.basename(self.media_path))
        except (OSError, ValueError) as exc:
            messagebox.showerror("匯出失敗", str(exc), parent=self)
            return
        self.status_var.set(f"已匯出 EDL：{path}")
        messagebox.showinfo(
            "匯出完成",
            f"EDL 已儲存至：\n{path}\n\n"
            "可匯入 Premiere Pro / DaVinci Resolve，時間軸即為保留段落。",
            parent=self)

    def _on_export_csv(self):
        if not self.items:
            return
        path = self._default_path("_審片清單", ".csv")
        try:
            export_csv(self.items, path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("匯出失敗", str(exc), parent=self)
            return
        self.status_var.set(f"已匯出 CSV：{path}")
        messagebox.showinfo("匯出完成", f"片段清單已儲存至：\n{path}",
                            parent=self)

    def _on_copy_chapters(self):
        if not self.items:
            return
        text = export_youtube_chapters(self.items)
        if not text:
            messagebox.showinfo(
                "沒有內容", "目前沒有保留中的講話段落。", parent=self)
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("YouTube 章節草稿已複製到剪貼簿，可直接貼上說明欄。")

    # ==================================================================
    # 狀態
    # ==================================================================
    def _set_processing(self, processing):
        self.is_processing = processing
        state = "disabled" if processing else "normal"
        self.analyze_btn.configure(
            state=state, text="處理中..." if processing else "開始分析")
        if not processing:
            self.progress_var.set(0.0)
        self._update_export_state()

    def _update_export_state(self):
        state = "normal" if (self.items and not self.is_processing) \
            else "disabled"
        for btn in self.export_buttons:
            btn.configure(state=state)

    def _on_close(self):
        if self._poll_job:
            self.after_cancel(self._poll_job)
        self.destroy()
