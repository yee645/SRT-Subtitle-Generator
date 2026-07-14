# -*- coding: utf-8 -*-
"""
統一錯誤對話框：把例外翻譯成「原因＋解決方法」再呈現。

取代散落各處的 messagebox.showerror(str(exc))——技術訊息（原始例外、
ffmpeg stderr）收進可展開的「技術細節」區塊，一鍵複製即可回報；
遇到「缺少 ffmpeg」時直接提供「自動安裝」按鈕。
"""

import tkinter as tk
from tkinter import ttk

from subtitle.errors import KIND_FFMPEG_MISSING, describe_exception


def show_friendly_error(parent, title, exc, on_install_ffmpeg=None):
    """
    顯示友善錯誤對話框。

    參數：
        parent: 父視窗。
        title: 視窗標題（如「處理失敗」）。
        exc: 例外物件或錯誤字串。
        on_install_ffmpeg: 缺 ffmpeg 時「自動安裝」按鈕的回呼；
                           省略則不顯示該按鈕。
    """
    error = describe_exception(exc)
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.minsize(460, 220)

    body = ttk.Frame(dialog, padding=14)
    body.pack(fill="both", expand=True)

    ttk.Label(body, text=f"✘ {error}", foreground="#c01c28",
              font=("Microsoft JhengHei", 11, "bold"),
              wraplength=520, justify="left").pack(anchor="w")

    if error.cause:
        ttk.Label(body, text="原因", font=("Microsoft JhengHei", 10, "bold")
                  ).pack(anchor="w", pady=(10, 2))
        ttk.Label(body, text=error.cause, wraplength=520,
                  justify="left").pack(anchor="w")
    if error.solution:
        ttk.Label(body, text="解決方法",
                  font=("Microsoft JhengHei", 10, "bold")
                  ).pack(anchor="w", pady=(10, 2))
        ttk.Label(body, text=error.solution, wraplength=520,
                  justify="left").pack(anchor="w")

    # 技術細節：預設收合，展開後可全選複製。
    details_text = (error.details or "").strip()
    if details_text:
        holder = ttk.Frame(body)
        holder.pack(fill="both", expand=True, pady=(10, 0))
        text_widget = tk.Text(holder, height=6, wrap="word",
                              font=("Consolas", 9))
        text_widget.insert("1.0", details_text)
        text_widget.configure(state="disabled")

        def toggle_details():
            if text_widget.winfo_ismapped():
                text_widget.pack_forget()
                toggle_btn.configure(text="顯示技術細節 ▸")
            else:
                text_widget.pack(fill="both", expand=True, pady=(4, 0))
                toggle_btn.configure(text="隱藏技術細節 ▾")

        toggle_btn = ttk.Button(holder, text="顯示技術細節 ▸",
                                command=toggle_details)
        toggle_btn.pack(anchor="w")

    buttons = ttk.Frame(body)
    buttons.pack(fill="x", pady=(12, 0))

    if error.kind == KIND_FFMPEG_MISSING and on_install_ffmpeg is not None:
        def install():
            dialog.destroy()
            on_install_ffmpeg()
        ttk.Button(buttons, text="自動安裝 ffmpeg（建議）",
                   command=install).pack(side="left")

    if details_text:
        def copy_details():
            dialog.clipboard_clear()
            dialog.clipboard_append(
                f"{error}\n原因：{error.cause}\n---\n{details_text}")
        ttk.Button(buttons, text="複製技術細節",
                   command=copy_details).pack(side="left", padx=(6, 0))

    ttk.Button(buttons, text="關閉",
               command=dialog.destroy).pack(side="right")
    dialog.grab_set()
    return dialog
