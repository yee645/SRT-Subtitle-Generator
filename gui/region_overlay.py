# -*- coding: utf-8 -*-
"""
框選覆蓋層：蓋住整個螢幕，讓使用者拖出一塊要翻譯的區域。

**叫出來 → 拖 → 放開**，就這樣。放開之後覆蓋層立刻消失，再由呼叫端去擷
取那一塊（擷取本身在 `subtitle/screencap.py`，零 GUI 依賴）。

**為什麼覆蓋層要先自己消失才擷取**：不然抓到的會是覆蓋層自己那層半透明
的灰，而不是底下的畫面。這是這個模組最容易寫錯的一點，所以 `withdraw()`
之後還會等畫面真的更新完（`update_idletasks` ＋ 一小段延遲）才回呼。

**取消一定要留路**：`Esc`、按右鍵、或視窗被關掉都算取消，而且取消要回報
給呼叫端（不是靜靜什麼都不做）。一個蓋住整個螢幕、又關不掉的東西，是能
把人嚇到重開機的。

**Windows 上沒有實測**：`-alpha`／`-topmost`／`-fullscreen` 這三個屬性在
Windows 的行為與 X11 不同（尤其是覆蓋在全螢幕遊戲上時）。這裡每一個屬性
都設成「設不起來也不會壞掉」——`attributes()` 一律包在 try 裡，最差的情
況是覆蓋層不透明，使用者照樣框得到。
"""

import logging
import tkinter as tk

logger = logging.getLogger(__name__)

# 覆蓋層的暗度。太暗會看不清底下要框什麼，太亮則看不出來正在框選。
_DIM_ALPHA = 0.32
# 選取框的顏色（深淺主題下都看得見的亮藍）。
_MARQUEE = "#2f8fef"
# withdraw() 之後等畫面真的更新完的毫秒數（見模組說明）。
_SETTLE_MS = 90


class RegionOverlay(tk.Toplevel):
    """全螢幕框選層；拖完回呼 on_select(region)，取消回呼 on_cancel()。"""

    def __init__(self, master, on_select=None, on_cancel=None,
                 hint="拖出要翻譯的範圍，放開即開始辨識；按 Esc 取消"):
        super().__init__(master)
        self._on_select = on_select
        self._on_cancel = on_cancel
        self._start = None
        self._rect = None
        self._done = False

        self.overrideredirect(True)
        self._cover_screen()
        # 這三個都可能在某些系統上設不起來；設不起來只是比較醜，不該壞掉。
        for attribute, value in (("-alpha", _DIM_ALPHA), ("-topmost", True)):
            try:
                self.attributes(attribute, value)
            except tk.TclError:
                logger.debug("覆蓋層屬性 %s 設定失敗（不影響使用）", attribute)

        self.canvas = tk.Canvas(self, highlightthickness=0, bg="#101010",
                                cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(
            self.winfo_screenwidth() // 2, 40, text=hint, fill="#ffffff",
            font=("Microsoft JhengHei", 14), tags="hint")

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        # 取消的三條路，缺一條都可能讓人被一層關不掉的東西蓋住螢幕。
        self.bind("<Escape>", lambda _e: self.cancel())
        self.canvas.bind("<ButtonPress-3>", lambda _e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        self.after(10, self._grab)

    # ------------------------------------------------------------------
    def _cover_screen(self):
        """蓋住整個螢幕。"""
        width = self.winfo_screenwidth()
        height = self.winfo_screenheight()
        self.geometry(f"{width}x{height}+0+0")

    def _grab(self):
        """把鍵盤焦點抓過來，Esc 才按得到。抓不到也不該壞掉。"""
        try:
            self.lift()
            self.focus_force()
            self.grab_set()
        except tk.TclError:
            logger.debug("覆蓋層取得焦點失敗（Esc 可能要先點一下畫面）")

    def _on_press(self, event):
        self._start = (event.x_root, event.y_root)
        if self._rect is not None:
            self.canvas.delete(self._rect)
        self._rect = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline=_MARQUEE, width=2)

    def _on_drag(self, event):
        if self._start is None or self._rect is None:
            return
        x0 = self._start[0] - self.winfo_rootx()
        y0 = self._start[1] - self.winfo_rooty()
        self.canvas.coords(self._rect, x0, y0, event.x, event.y)

    def _on_release(self, event):
        if self._start is None or self._done:
            return
        from subtitle.screencap import normalize_region

        region = normalize_region(self._start[0], self._start[1],
                                  event.x_root, event.y_root)
        self._finish(region)

    # ------------------------------------------------------------------
    def _finish(self, region):
        """
        收工：**先讓覆蓋層消失**，等畫面更新完才回呼。

        順序反過來的話，擷取到的會是覆蓋層自己那層半透明的灰。
        """
        self._done = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.withdraw()
        self.update_idletasks()
        callback = self._on_select

        def run():
            self.destroy()
            if callback:
                callback(region)

        # 用 master 排程：這個視窗馬上就要被 destroy 了。
        self.master.after(_SETTLE_MS, run)

    def cancel(self):
        """取消框選，並且一定要告訴呼叫端。"""
        if self._done:
            return
        self._done = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        callback = self._on_cancel
        self.destroy()
        if callback:
            callback()
