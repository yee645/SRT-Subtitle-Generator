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

# sv-ttk（Sun Valley）兩種主題各自的一般背景色（取自套件的 theme/light.tcl、
# theme/dark.tcl 的 colors(-bg)）。Canvas 不是 ttk 元件，換主題時不會自動變色，
# 且經測試 ttk::style lookup 在主題「第一次」套用時會因 sv-ttk 的
# <<ThemeChanged>> 綁定尚未觸發而查不到值，並不可靠；改用這裡的固定對照表，
# 由呼叫端（app.py）直接告知目前主題名稱，簡單且不受該時序問題影響。
_THEME_CANVAS_BG = {
    "light": "#fafafa",
    "dark": "#1c1c1c",
}
_DEFAULT_BG = "#f0f0f0"  # 未安裝 sv-ttk 時的系統預設外觀。


class ScrollableFrame(ttk.Frame):
    """提供垂直與水平捲動的容器。"""

    def __init__(self, master, theme="light", **kwargs):
        super().__init__(master, **kwargs)
        self._theme = theme

        # Canvas 不是 ttk 元件，sv-ttk 換主題時不會自動變色，
        # 因此背景色需自行依目前主題設定（並在切換主題時由 refresh_theme
        # 重新套用），否則深色主題下會露出一塊不搭調的淺色畫布
        # （v1.14.1 修復）。
        self.canvas = tk.Canvas(
            self, highlightthickness=0, background=self._background_for(theme))
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

        # 實際放置內容的內層 Frame（改用 ttk.Frame 才會隨主題變色）。
        self.interior = ttk.Frame(self.canvas)
        self._window_id = self.canvas.create_window(
            (0, 0), window=self.interior, anchor="nw")

        # 內容尺寸改變時更新可捲動範圍。
        self.interior.bind("<Configure>", self._on_interior_configure)
        # 畫布尺寸改變時調整內層寬度，達成自適應。
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        # 滑鼠移入時啟用滾輪捲動，移出時解除。
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

    @staticmethod
    def _background_for(theme):
        return _THEME_CANVAS_BG.get(theme, _DEFAULT_BG)

    def refresh_theme(self, theme):
        """主題切換後呼叫：把 Canvas 背景色同步成新主題的顏色。"""
        self._theme = theme
        self.canvas.configure(background=self._background_for(theme))

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
