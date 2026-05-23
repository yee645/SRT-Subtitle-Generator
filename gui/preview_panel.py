# -*- coding: utf-8 -*-
"""
字幕即時預覽面板。

以 Canvas 模擬影片畫面，並依目前字幕樣式（位置、字級、顏色、邊框）
即時繪製字幕文字，供使用者調整時對照效果。
"""

import tkinter as tk

# 預覽畫布尺寸，採 16:9 比例。
PREVIEW_WIDTH = 560
PREVIEW_HEIGHT = 315


class PreviewPanel(tk.Frame):
    """字幕預覽畫布元件。"""

    def __init__(self, master):
        super().__init__(master)
        self.canvas = tk.Canvas(
            self, width=PREVIEW_WIDTH, height=PREVIEW_HEIGHT,
            highlightthickness=1, highlightbackground="#888888",
        )
        self.canvas.pack()
        self._current_text = "字幕預覽範例文字"
        self._current_style = None

    def render(self, text, style):
        """依指定文字與樣式重繪預覽畫面。"""
        self._current_text = text or ""
        self._current_style = style
        self._redraw()

    def update_style(self, style):
        """僅更新樣式並沿用目前文字（樣式面板調整時呼叫）。"""
        self._current_style = style
        self._redraw()

    def _redraw(self):
        """實際的繪圖流程。"""
        canvas = self.canvas
        canvas.delete("all")

        # 模擬影片畫面背景。
        canvas.create_rectangle(
            0, 0, PREVIEW_WIDTH, PREVIEW_HEIGHT, fill="#202020", outline="",
        )
        canvas.create_text(
            PREVIEW_WIDTH / 2, 16, text="影片預覽畫面（字幕效果即時預覽）",
            fill="#555555", font=("Microsoft JhengHei", 9),
        )

        style = self._current_style
        text = self._current_text
        if not style or not text:
            return

        # 由 0.0 ~ 1.0 的相對座標換算成畫布像素座標。
        center_x = style["position_x"] * PREVIEW_WIDTH
        center_y = style["position_y"] * PREVIEW_HEIGHT
        font = (style["font_family"], int(style["font_size"]))
        stroke_width = int(style["stroke_width"])
        wrap_width = int(PREVIEW_WIDTH * 0.92)

        # 先以邊框顏色在四周偏移描繪，模擬文字描邊效果。
        if stroke_width > 0:
            for offset_x in range(-stroke_width, stroke_width + 1):
                for offset_y in range(-stroke_width, stroke_width + 1):
                    if offset_x == 0 and offset_y == 0:
                        continue
                    canvas.create_text(
                        center_x + offset_x, center_y + offset_y,
                        text=text, fill=style["stroke_color"], font=font,
                        anchor="center", width=wrap_width, justify="center",
                    )

        # 再以文字顏色繪製主體。
        canvas.create_text(
            center_x, center_y, text=text, fill=style["text_color"],
            font=font, anchor="center", width=wrap_width, justify="center",
        )
