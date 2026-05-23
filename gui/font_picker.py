# -*- coding: utf-8 -*-
"""
字型選擇器。

提供一個對話框，讓使用者：
1. 從系統已安裝的所有字型中挑選（附搜尋過濾）。
2. 從本機字型檔（.ttf / .otf）匯入喜歡的字型。

匯入字型檔時會：
- 解析字型檔的 name 表取得字型家族名稱。
- 於 Windows 上以 GDI 的 AddFontResource 將字型載入目前的程式工作階段，
  使其立即可用（不需安裝到系統）。
"""

import os
import struct
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox

# 記錄本程式階段內匯入（註冊）過的字型檔，供關閉時釋放。
_loaded_font_files = []


def open_font_picker(parent, current_family):
    """
    開啟字型選擇對話框。

    參數：
        parent: 父視窗。
        current_family: 目前使用的字型名稱，開啟時預先選取。
    回傳：使用者選定的字型名稱；按取消則回傳 None。
    """
    dialog = _FontPickerDialog(parent, current_family)
    parent.wait_window(dialog)
    return dialog.result


def register_font_file(path):
    """
    將字型檔載入目前工作階段並回傳其字型家族名稱。

    發生問題時拋出 RuntimeError 由呼叫端處理。
    """
    if not os.path.exists(path):
        raise RuntimeError("找不到指定的字型檔。")

    family = _read_font_family(path)
    if not family:
        raise RuntimeError("無法從此檔案讀取字型名稱，請改用其他字型檔。")

    if os.name == "nt":
        # 於 Windows 以 GDI 載入字型，使其在本程式內立即可用。
        import ctypes
        added = ctypes.windll.gdi32.AddFontResourceW(ctypes.c_wchar_p(path))
        if added == 0:
            raise RuntimeError("系統無法載入此字型檔。")
        _loaded_font_files.append(path)
    return family


def release_imported_fonts():
    """釋放本程式階段內匯入的字型資源（程式關閉時呼叫）。"""
    if os.name != "nt":
        return
    import ctypes
    for path in _loaded_font_files:
        try:
            ctypes.windll.gdi32.RemoveFontResourceW(ctypes.c_wchar_p(path))
        except OSError:
            # 釋放失敗不影響程式關閉。
            pass
    _loaded_font_files.clear()


def _read_font_family(path):
    """從 .ttf / .otf 字型檔解析字型家族名稱。"""
    with open(path, "rb") as fp:
        data = fp.read()
    if len(data) < 12:
        raise RuntimeError("字型檔格式不正確。")

    # 檢查 sfnt 版本標記。
    sfnt_version = data[:4]
    if sfnt_version not in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1"):
        raise RuntimeError("僅支援 .ttf 或 .otf 字型檔。")

    # 由表格目錄找出 name 表的位置。
    num_tables = struct.unpack(">H", data[4:6])[0]
    name_offset = None
    for index in range(num_tables):
        record = 12 + index * 16
        tag = data[record:record + 4]
        if tag == b"name":
            name_offset = struct.unpack(">I", data[record + 8:record + 12])[0]
            break
    if name_offset is None:
        return ""

    # 解析 name 表，取出字型家族名稱（nameID 1 與較佳的 nameID 16）。
    count, string_offset = struct.unpack(">HH", data[name_offset + 2:name_offset + 6])
    strings_base = name_offset + string_offset
    family = ""
    preferred_family = ""
    for index in range(count):
        record = name_offset + 6 + index * 12
        platform, _encoding, _language, name_id, length, offset = struct.unpack(
            ">HHHHHH", data[record:record + 12])
        if name_id not in (1, 16):
            continue
        raw = data[strings_base + offset:strings_base + offset + length]
        value = _decode_name_string(raw, platform).strip()
        if not value:
            continue
        if name_id == 16 and not preferred_family:
            preferred_family = value
        elif name_id == 1 and not family:
            family = value
    # nameID 16（偏好家族名稱）較精確，優先採用。
    return preferred_family or family


def _decode_name_string(raw, platform):
    """依平台代碼解碼 name 表中的字串。"""
    try:
        if platform in (0, 3):
            # Unicode 與 Windows 平台採 UTF-16 大端序。
            return raw.decode("utf-16-be", errors="ignore")
        if platform == 1:
            return raw.decode("mac-roman", errors="ignore")
        return raw.decode("latin-1", errors="ignore")
    except (UnicodeDecodeError, LookupError):
        return ""


class _FontPickerDialog(tk.Toplevel):
    """字型選擇對話框。"""

    def __init__(self, parent, current_family):
        super().__init__(parent)
        self.title("選擇字型")
        self.result = None
        self.transient(parent)
        self.resizable(False, False)

        # 取得系統所有字型家族並排序。
        self._all_fonts = sorted(set(tkfont.families()))

        self._build_widgets(current_family)

        # 設為強制焦點的對話框。
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _build_widgets(self, current_family):
        """建立對話框內容。"""
        # 搜尋列。
        search_row = tk.Frame(self, padx=10, pady=8)
        search_row.pack(fill="x")
        tk.Label(search_row, text="搜尋字型：").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_a: self._refresh_list())
        tk.Entry(
            search_row, textvariable=self.search_var, width=24,
        ).pack(side="left", fill="x", expand=True)

        # 字型清單。
        list_row = tk.Frame(self, padx=10)
        list_row.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(list_row, height=14, width=36)
        scrollbar = tk.Scrollbar(
            list_row, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.listbox.bind("<Double-Button-1>", lambda _e: self._on_confirm())

        self._refresh_list()
        # 預先選取目前字型。
        if current_family in self._all_fonts:
            items = self.listbox.get(0, "end")
            if current_family in items:
                idx = items.index(current_family)
                self.listbox.selection_set(idx)
                self.listbox.see(idx)

        # 底部按鈕列。
        button_row = tk.Frame(self, padx=10, pady=10)
        button_row.pack(fill="x")
        tk.Button(
            button_row, text="從字型檔匯入 (.ttf/.otf)",
            command=self._import_from_file,
        ).pack(side="left")
        tk.Button(
            button_row, text="取消", width=8, command=self._on_cancel,
        ).pack(side="right")
        tk.Button(
            button_row, text="確定", width=8, command=self._on_confirm,
        ).pack(side="right", padx=6)

    def _refresh_list(self):
        """依搜尋字串重新整理字型清單。"""
        keyword = self.search_var.get().strip().lower()
        self.listbox.delete(0, "end")
        for family in self._all_fonts:
            if not keyword or keyword in family.lower():
                self.listbox.insert("end", family)

    def _import_from_file(self):
        """從本機字型檔匯入字型。"""
        path = filedialog.askopenfilename(
            title="匯入字型檔", parent=self,
            filetypes=[("字型檔", "*.ttf *.otf"), ("所有檔案", "*.*")],
        )
        if not path:
            return
        try:
            family = register_font_file(path)
        except (RuntimeError, OSError) as exc:
            messagebox.showerror("匯入失敗", str(exc), parent=self)
            return

        # 將匯入的字型加入清單並選取。
        if family not in self._all_fonts:
            self._all_fonts = sorted(set(self._all_fonts) | {family})
        self._refresh_list()
        items = self.listbox.get(0, "end")
        if family in items:
            idx = items.index(family)
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(idx)
            self.listbox.see(idx)
        messagebox.showinfo(
            "匯入成功", f"已匯入字型：{family}", parent=self)

    def _on_confirm(self):
        """確定選取。"""
        selection = self.listbox.curselection()
        if selection:
            self.result = self.listbox.get(selection[0])
        self.destroy()

    def _on_cancel(self):
        """取消。"""
        self.result = None
        self.destroy()
