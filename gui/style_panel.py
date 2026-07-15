# -*- coding: utf-8 -*-
"""
字幕視覺調整面板。

提供位置（X / Y 與頂部/中部/底部快捷鍵）、字型、字級、文字顏色、
邊框顏色與邊框寬度的調整控制項。任一項變動時即透過回呼通知主視窗，
由主視窗負責更新預覽並寫回設定檔（記憶功能）。
"""

import tkinter as tk
from tkinter import colorchooser, messagebox, ttk

from gui.font_picker import open_font_picker

# 字型下拉選單的常用選項（中文字型含繁體常見字型，亦可自行輸入或匯入其他字型）。
FONT_CHOICES = [
    "Microsoft JhengHei",   # 微軟正黑體
    "Microsoft JhengHei UI",
    "微軟正黑體",
    "Microsoft YaHei",      # 微軟雅黑體
    "PMingLiU",             # 新細明體
    "新細明體",
    "MingLiU",              # 細明體
    "細明體",
    "DFKai-SB",             # 標楷體
    "標楷體",
    "KaiTi",                # 楷體
    "SimSun",               # 宋體
    "SimHei",               # 黑體
    "FangSong",             # 仿宋
    "Noto Sans CJK TC",     # 思源黑體
    "Noto Serif CJK TC",    # 思源宋體
    "Arial", "Segoe UI", "Times New Roman", "Tahoma", "Verdana",
]
# 垂直位置快捷鍵對應的相對座標。
VERTICAL_PRESETS = {"頂部": 0.12, "中部": 0.50, "底部": 0.88}

# 逐字動態字幕模式：顯示名稱 ↔ 設定值。
DYNAMIC_MODE_LABELS = {
    "off": "無（整句）",
    "karaoke": "逐字上色（卡拉OK）",
    "word": "單字彈出",
}
_DYNAMIC_LABEL_TO_MODE = {label: mode
                          for mode, label in DYNAMIC_MODE_LABELS.items()}


class StylePanel(tk.LabelFrame):
    """字幕樣式調整面板元件。"""

    def __init__(self, master, style, on_change):
        """
        參數：
            master: 父容器。
            style: 初始字幕樣式 dict（來自 config["subtitle_style"]）。
            on_change: 樣式變動時呼叫的回呼，傳入最新的樣式 dict。
        """
        super().__init__(master, text="字幕視覺調整", padx=10, pady=8)
        self._on_change = on_change
        # 以複本保存，避免直接修改外部物件（符合不可變原則）。
        self._style = dict(style)
        # 建構期間暫停事件，避免初始化控制項時觸發大量回呼。
        self._suspend_events = True
        self._build_widgets()
        self._suspend_events = False

    # ------------------------------------------------------------------
    # 介面建構
    # ------------------------------------------------------------------
    def _build_widgets(self):
        """建立所有調整控制項。"""
        style = self._style

        # 水平位置 X。
        tk.Label(self, text="水平位置 X").grid(row=0, column=0, sticky="w", pady=3)
        self.pos_x_var = tk.DoubleVar(value=style["position_x"] * 100)
        tk.Scale(
            self, from_=0, to=100, orient="horizontal", variable=self.pos_x_var,
            command=lambda _v: self._emit_change(), length=180, showvalue=True,
        ).grid(row=0, column=1, columnspan=2, sticky="we")

        # 垂直位置 Y。
        tk.Label(self, text="垂直位置 Y").grid(row=1, column=0, sticky="w", pady=3)
        self.pos_y_var = tk.DoubleVar(value=style["position_y"] * 100)
        tk.Scale(
            self, from_=0, to=100, orient="horizontal", variable=self.pos_y_var,
            command=lambda _v: self._emit_change(), length=180, showvalue=True,
        ).grid(row=1, column=1, columnspan=2, sticky="we")

        # 垂直位置快捷鍵。
        preset_frame = tk.Frame(self)
        preset_frame.grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 6))
        tk.Label(preset_frame, text="快捷位置：").pack(side="left")
        for label, value in VERTICAL_PRESETS.items():
            tk.Button(
                preset_frame, text=label, width=6,
                command=lambda v=value: self._apply_vertical_preset(v),
            ).pack(side="left", padx=2)

        # 字型：下拉選單加上「匯入字型」小按鈕。
        tk.Label(self, text="字型").grid(row=3, column=0, sticky="w", pady=3)
        self.font_var = tk.StringVar(value=style["font_family"])
        font_row = tk.Frame(self)
        font_row.grid(row=3, column=1, columnspan=2, sticky="we")
        self.font_box = ttk.Combobox(
            font_row, textvariable=self.font_var, values=FONT_CHOICES, width=18,
        )
        self.font_box.pack(side="left", fill="x", expand=True)
        self.font_box.bind("<<ComboboxSelected>>", lambda _e: self._emit_change())
        self.font_box.bind("<Return>", lambda _e: self._emit_change())
        self.font_box.bind("<FocusOut>", lambda _e: self._emit_change())
        # 小按鈕：開啟字型選擇器，可挑選系統字型或匯入字型檔。
        tk.Button(
            font_row, text="...", width=3, command=self._import_font,
        ).pack(side="left", padx=(4, 0))

        # 字級。
        tk.Label(self, text="字型大小").grid(row=4, column=0, sticky="w", pady=3)
        self.font_size_var = tk.IntVar(value=style["font_size"])
        tk.Spinbox(
            self, from_=10, to=96, textvariable=self.font_size_var, width=8,
            command=self._emit_change,
        ).grid(row=4, column=1, sticky="w")
        # 直接鍵入數值時也即時套用。
        self.font_size_var.trace_add("write", lambda *_a: self._emit_change())

        # 文字顏色。
        tk.Label(self, text="文字顏色").grid(row=5, column=0, sticky="w", pady=3)
        self.text_color_swatch = tk.Label(
            self, width=4, relief="solid", borderwidth=1, bg=style["text_color"],
        )
        self.text_color_swatch.grid(row=5, column=1, sticky="w")
        tk.Button(
            self, text="選擇顏色", command=self._choose_text_color,
        ).grid(row=5, column=2, sticky="w")

        # 邊框顏色。
        tk.Label(self, text="邊框顏色").grid(row=6, column=0, sticky="w", pady=3)
        self.stroke_color_swatch = tk.Label(
            self, width=4, relief="solid", borderwidth=1, bg=style["stroke_color"],
        )
        self.stroke_color_swatch.grid(row=6, column=1, sticky="w")
        tk.Button(
            self, text="選擇顏色", command=self._choose_stroke_color,
        ).grid(row=6, column=2, sticky="w")

        # 邊框寬度。
        tk.Label(self, text="邊框寬度").grid(row=7, column=0, sticky="w", pady=3)
        self.stroke_width_var = tk.IntVar(value=style["stroke_width"])
        tk.Spinbox(
            self, from_=0, to=6, textvariable=self.stroke_width_var, width=8,
            command=self._emit_change,
        ).grid(row=7, column=1, sticky="w")
        self.stroke_width_var.trace_add("write", lambda *_a: self._emit_change())

        # 重點字上色（燒錄與 ASS 匯出時，把指定詞彙換色強調）。
        self.emphasis_var = tk.BooleanVar(
            value=bool(style.get("emphasis_enabled", False)))
        ttk.Checkbutton(
            self, text="重點字上色", variable=self.emphasis_var,
            command=self._emit_change,
        ).grid(row=8, column=0, sticky="w", pady=3)
        self.emphasis_swatch = tk.Label(
            self, width=4, relief="solid", borderwidth=1,
            bg=style.get("emphasis_color", "#FFD700"),
        )
        self.emphasis_swatch.grid(row=8, column=1, sticky="w")
        tk.Button(
            self, text="選擇顏色", command=self._choose_emphasis_color,
        ).grid(row=8, column=2, sticky="w")

        tk.Label(self, text="重點字詞").grid(row=9, column=0, sticky="w", pady=3)
        self.emphasis_words_var = tk.StringVar(
            value=style.get("emphasis_words", ""))
        emphasis_entry = tk.Entry(self, textvariable=self.emphasis_words_var)
        emphasis_entry.grid(row=9, column=1, columnspan=2, sticky="we")
        emphasis_entry.bind("<FocusOut>", lambda _e: self._emit_change())
        emphasis_entry.bind("<Return>", lambda _e: self._emit_change())
        tk.Label(
            self, text="逗號或空白分隔；於燒錄影片與 ASS 匯出時生效",
            fg="#666666",
        ).grid(row=10, column=0, columnspan=3, sticky="w")

        # 逐字動態字幕（卡拉OK／單字彈出，需逐字時間軸）。
        tk.Label(self, text="動態字幕").grid(row=11, column=0, sticky="w", pady=3)
        self.dynamic_var = tk.StringVar(
            value=DYNAMIC_MODE_LABELS.get(
                str(style.get("dynamic_mode", "off")),
                DYNAMIC_MODE_LABELS["off"]))
        dynamic_box = ttk.Combobox(
            self, textvariable=self.dynamic_var, state="readonly", width=18,
            values=list(DYNAMIC_MODE_LABELS.values()))
        dynamic_box.grid(row=11, column=1, columnspan=2, sticky="w")
        dynamic_box.bind("<<ComboboxSelected>>", lambda _e: self._emit_change())
        tk.Label(
            self, text="逐字換色或單字彈出；模式一（音訊轉錄）燒錄與 ASS 匯出時生效",
            fg="#666666",
        ).grid(row=12, column=0, columnspan=3, sticky="w")

    # ------------------------------------------------------------------
    # 事件處理
    # ------------------------------------------------------------------
    def _apply_vertical_preset(self, value):
        """套用垂直位置快捷鍵。"""
        self.pos_y_var.set(value * 100)
        self._emit_change()

    def _import_font(self):
        """開啟字型選擇器，讓使用者挑選系統字型或匯入字型檔。"""
        try:
            family = open_font_picker(self.winfo_toplevel(), self.font_var.get())
        except Exception as exc:  # 字型選擇器發生非預期錯誤時不中斷主程式。
            messagebox.showerror("字型選擇失敗", str(exc))
            return
        if not family:
            return
        # 將選定字型加入下拉清單（若尚未存在）並設為目前字型。
        values = list(self.font_box["values"])
        if family not in values:
            values.append(family)
            self.font_box.configure(values=values)
        self.font_var.set(family)
        self._emit_change()

    def _choose_text_color(self):
        """開啟調色盤選擇文字顏色。"""
        color = colorchooser.askcolor(
            color=self._style["text_color"], title="選擇文字顏色",
        )
        if color and color[1]:
            self.text_color_swatch.configure(bg=color[1])
            self._emit_change()

    def _choose_stroke_color(self):
        """開啟調色盤選擇邊框顏色。"""
        color = colorchooser.askcolor(
            color=self._style["stroke_color"], title="選擇邊框顏色",
        )
        if color and color[1]:
            self.stroke_color_swatch.configure(bg=color[1])
            self._emit_change()

    def _choose_emphasis_color(self):
        """開啟調色盤選擇重點字顏色。"""
        color = colorchooser.askcolor(
            color=self._style.get("emphasis_color", "#FFD700"),
            title="選擇重點字顏色",
        )
        if color and color[1]:
            self.emphasis_swatch.configure(bg=color[1])
            self._emit_change()

    def _emit_change(self):
        """收集目前所有控制項的值，組成樣式 dict 並通知主視窗。"""
        if self._suspend_events:
            return
        try:
            font_size = int(self.font_size_var.get())
        except (tk.TclError, ValueError):
            font_size = self._style["font_size"]
        try:
            stroke_width = int(self.stroke_width_var.get())
        except (tk.TclError, ValueError):
            stroke_width = self._style["stroke_width"]

        self._style = {
            "position_x": round(self.pos_x_var.get() / 100, 4),
            "position_y": round(self.pos_y_var.get() / 100, 4),
            "font_family": self.font_var.get().strip() or "Microsoft JhengHei",
            "font_size": max(10, min(font_size, 96)),
            "text_color": self.text_color_swatch.cget("bg"),
            "stroke_color": self.stroke_color_swatch.cget("bg"),
            "stroke_width": max(0, min(stroke_width, 6)),
            "emphasis_enabled": bool(self.emphasis_var.get()),
            "emphasis_color": self.emphasis_swatch.cget("bg"),
            "emphasis_words": self.emphasis_words_var.get().strip(),
            "dynamic_mode": _DYNAMIC_LABEL_TO_MODE.get(
                self.dynamic_var.get(), "off"),
        }
        if callable(self._on_change):
            self._on_change(dict(self._style))

    def get_style(self):
        """回傳目前樣式的複本。"""
        return dict(self._style)

    def set_style(self, style):
        """以指定樣式重設所有控制項（套用習慣設定時呼叫），過程中不觸發 on_change。"""
        self._suspend_events = True
        try:
            self._style = dict(style)
            self.pos_x_var.set(style["position_x"] * 100)
            self.pos_y_var.set(style["position_y"] * 100)
            self.font_var.set(style["font_family"])
            self.font_size_var.set(style["font_size"])
            self.stroke_width_var.set(style["stroke_width"])
            self.text_color_swatch.configure(bg=style["text_color"])
            self.stroke_color_swatch.configure(bg=style["stroke_color"])
            self.emphasis_var.set(bool(style.get("emphasis_enabled", False)))
            self.emphasis_swatch.configure(
                bg=style.get("emphasis_color", "#FFD700"))
            self.emphasis_words_var.set(style.get("emphasis_words", ""))
            self.dynamic_var.set(DYNAMIC_MODE_LABELS.get(
                str(style.get("dynamic_mode", "off")),
                DYNAMIC_MODE_LABELS["off"]))
        finally:
            self._suspend_events = False
