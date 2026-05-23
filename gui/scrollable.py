# -*- coding: utf-8 -*-
"""
可捲動容器元件。

以 Canvas 搭配垂直 / 水平捲軸，包住一個內層 Frame。
當內容高度超過視窗時即出現捲軸可拉動頁面，並支援滑鼠滾輪捲動；
視窗放大時內容會自動跟著拉寬（自適應），縮小時則改由捲軸補足。

使用方式：把所有內容加入 ScrollableFrame 物件的 interior 屬性即可。
"""

import tkinter as tk
from tkinter import ttk


class ScrollableFrame(tk.Frame):
    """提供垂直與水平捲動的容器。"""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self.canvas = tk.Canvas(self, highlightthickness=0)
        v_scroll = ttk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview)
        h_scroll = ttk.Scrollbar(
            self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(
            yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        # 捲軸貼邊，畫布填滿剩餘空間。
        v_scroll.pack(side="right", fill="y")
        h_scroll.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)

        # 實際放置內容的內層 Frame。
        self.interior = tk.Frame(self.canvas)
        self._window_id = self.canvas.create_window(
            (0, 0), window=self.interior, anchor="nw")

        # 內容尺寸改變時更新可捲動範圍。
        self.interior.bind("<Configure>", self._on_interior_configure)
        # 畫布尺寸改變時調整內層寬度，達成自適應。
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        # 滑鼠移入時啟用滾輪捲動，移出時解除。
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

    def _on_interior_configure(self, _event):
        """內容尺寸變動時，重新計算可捲動範圍。"""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        """
        畫布尺寸變動時調整內層 Frame 寬度。

        視窗夠寬時內容跟著拉寬；視窗太窄時保留內容原始寬度，
        不足部分改由水平捲軸補足，避免內容被擠壓變形。
        """
        target_width = max(event.width, self.interior.winfo_reqwidth())
        self.canvas.itemconfigure(self._window_id, width=target_width)

    def _bind_mousewheel(self, _event):
        """滑鼠移入時綁定滾輪事件。"""
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event):
        """滑鼠移出時解除滾輪事件，避免影響其他元件。"""
        self.canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event):
        """處理滑鼠滾輪垂直捲動（Windows 的 delta 為 120 的倍數）。"""
        self.canvas.yview_scroll(int(-event.delta / 120), "units")
