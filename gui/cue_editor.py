# -*- coding: utf-8 -*-
"""
字幕列編輯對話框與時間軸工具。

提供以下功能（模式三手動字幕模式與其他模式皆可使用）：
    1. CueEditDialog：以 mm:ss.fff 文字框編輯單一 cue 的起訖時間與文字。
    2. parse_timestamp / format_timestamp_input：時間字串解析與格式化。

外部使用方式：
    result = CueEditDialog(parent, cue).result
    if result is not None:
        # result 為更新後的 cue dict，使用者按取消時為 None。
        ...
"""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional


# mm:ss.fff 或 hh:mm:ss.fff（毫秒部分可省略）。
_TIME_RE = re.compile(
    r"^\s*(?:(?P<h>\d+):)?(?P<m>\d{1,2}):(?P<s>\d{1,2})(?:[\.,](?P<f>\d{1,3}))?\s*$"
)


def parse_timestamp(text: str) -> float:
    """把 mm:ss.fff / hh:mm:ss.fff 字串解析為秒數；解析失敗時拋出 ValueError。"""
    match = _TIME_RE.match(text or "")
    if not match:
        raise ValueError(f"無法解析時間：{text!r}（請使用 mm:ss.fff 或 hh:mm:ss.fff）")
    hours = int(match.group("h") or 0)
    minutes = int(match.group("m"))
    seconds = int(match.group("s"))
    frac_text = match.group("f") or "0"
    # 把毫秒部分補齊三位（"5" → "500"、"50" → "500"、"500" → "500"）。
    frac_text = (frac_text + "000")[:3]
    millis = int(frac_text)
    if minutes >= 60 or seconds >= 60:
        raise ValueError("分鐘或秒數超過 60。")
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def format_timestamp_input(seconds: float) -> str:
    """把秒數格式化為 mm:ss.fff 字串供編輯框顯示。"""
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours, total_ms = divmod(total_ms, 3_600_000)
    minutes, total_ms = divmod(total_ms, 60_000)
    secs, millis = divmod(total_ms, 1000)
    if hours > 0:
        return f"{hours:d}:{minutes:02d}:{secs:02d}.{millis:03d}"
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


class CueEditDialog(tk.Toplevel):
    """單一字幕列編輯對話框。"""

    def __init__(self, master: tk.Misc, cue: Optional[dict] = None,
                 title: str = "編輯字幕"):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.resizable(False, False)
        self.result: Optional[dict] = None
        # 預填初始值（新增時 cue=None 用零值）。
        cue = cue or {}
        start = float(cue.get("start", 0.0))
        end = float(cue.get("end", max(start + 1.0, 1.0)))
        text = cue.get("text", "")

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="開始時間（mm:ss.fff）：").grid(
            row=0, column=0, sticky="w", pady=4)
        self.start_var = tk.StringVar(value=format_timestamp_input(start))
        ttk.Entry(body, textvariable=self.start_var, width=16).grid(
            row=0, column=1, sticky="we", padx=(6, 0))

        ttk.Label(body, text="結束時間（mm:ss.fff）：").grid(
            row=1, column=0, sticky="w", pady=4)
        self.end_var = tk.StringVar(value=format_timestamp_input(end))
        ttk.Entry(body, textvariable=self.end_var, width=16).grid(
            row=1, column=1, sticky="we", padx=(6, 0))

        ttk.Label(body, text="字幕內容：").grid(
            row=2, column=0, sticky="nw", pady=4)
        self.text_widget = tk.Text(body, height=4, width=36, wrap="word")
        self.text_widget.insert("1.0", text)
        self.text_widget.grid(row=2, column=1, sticky="we", padx=(6, 0))

        btn_row = ttk.Frame(body)
        btn_row.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btn_row, text="取消", command=self._cancel).pack(
            side="right", padx=(6, 0))
        ttk.Button(btn_row, text="確定", command=self._confirm).pack(side="right")

        self.bind("<Return>", lambda _e: self._confirm())
        self.bind("<Escape>", lambda _e: self._cancel())
        # 視窗置中於父視窗。
        self.update_idletasks()
        self._center_on_parent(master)
        self.grab_set()
        self.text_widget.focus_set()
        self.wait_window(self)

    def _center_on_parent(self, master: tk.Misc) -> None:
        """把對話框置中於父視窗。"""
        try:
            parent = master.winfo_toplevel()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            w = self.winfo_width()
            h = self.winfo_height()
            x = px + max((pw - w) // 2, 0)
            y = py + max((ph - h) // 2, 0)
            self.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

    def _confirm(self) -> None:
        """驗證輸入並回傳結果。"""
        try:
            start = parse_timestamp(self.start_var.get())
            end = parse_timestamp(self.end_var.get())
        except ValueError as exc:
            messagebox.showerror("時間格式錯誤", str(exc), parent=self)
            return
        if end <= start:
            messagebox.showerror(
                "時間不合法", "結束時間必須大於開始時間。", parent=self)
            return
        text = self.text_widget.get("1.0", "end").strip()
        if not text:
            messagebox.showerror("字幕為空", "字幕內容不可為空。", parent=self)
            return
        self.result = {"start": start, "end": end, "text": text}
        self.destroy()

    def _cancel(self) -> None:
        """取消編輯。"""
        self.result = None
        self.destroy()
