# -*- coding: utf-8 -*-
"""
字幕即時預覽面板。

以 Canvas 模擬影片畫面，並依目前字幕樣式（位置、字級、顏色、邊框、
重點字上色）即時繪製字幕文字，供使用者調整時對照效果。
"""

import tkinter as tk
import tkinter.font as tkfont

from subtitle.exporter import parse_emphasis_words, split_emphasis_segments

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

        # 重點字分段：啟用且為單行、寬度足夠時逐段分色繪製，
        # 其餘情況（多行、超寬）退回單色以維持排版正確。
        segments = self._emphasis_segments(text, style, font, wrap_width)
        if segments:
            self._draw_segments(segments, style, font,
                                center_x, center_y, stroke_width)
            return

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

    def _emphasis_segments(self, text, style, font, wrap_width):
        """
        取得可分色渲染的 (片段, 是否重點, 像素寬) 清單。

        回傳 None 表示不適用分色（未啟用、無命中、多行或超寬），
        呼叫端應退回單色繪製。
        """
        if not style.get("emphasis_enabled") or "\n" in text:
            return None
        words = parse_emphasis_words(str(style.get("emphasis_words") or ""))
        if not words:
            return None
        segments = split_emphasis_segments(text, words)
        if not any(emphasized for _seg, emphasized in segments):
            return None
        try:
            measurer = tkfont.Font(font=font)
            measured = [(seg, emphasized, measurer.measure(seg))
                        for seg, emphasized in segments]
        except tk.TclError:
            return None
        if sum(width for *_x, width in measured) > wrap_width:
            return None  # 會被自動換行，退回單色避免排版錯位。
        return measured

    def _draw_segments(self, measured, style, font,
                       center_x, center_y, stroke_width):
        """逐段繪製（含描邊），重點段以 emphasis_color 上色。"""
        canvas = self.canvas
        total = sum(width for *_x, width in measured)
        cursor = center_x - total / 2
        emphasis_color = style.get("emphasis_color", "#FFD700")
        for segment, emphasized, width in measured:
            if stroke_width > 0:
                for offset_x in range(-stroke_width, stroke_width + 1):
                    for offset_y in range(-stroke_width, stroke_width + 1):
                        if offset_x == 0 and offset_y == 0:
                            continue
                        canvas.create_text(
                            cursor + offset_x, center_y + offset_y,
                            text=segment, fill=style["stroke_color"],
                            font=font, anchor="w",
                        )
            canvas.create_text(
                cursor, center_y, text=segment,
                fill=emphasis_color if emphasized else style["text_color"],
                font=font, anchor="w",
            )
            cursor += width
