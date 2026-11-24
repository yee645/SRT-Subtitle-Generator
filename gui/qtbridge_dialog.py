# -*- coding: utf-8 -*-
"""
「3.0 新介面」提示視窗（3.0 第 12 項 12-5，一般版到 Qt 版的橋）。

規則都在 `subtitle/qtbridge.py`；這裡只管畫面：說明（裝在哪、會送什麼、一般版留著）→〔下載並安裝新介面〕→
進度與〔取消下載〕→ 裝好〔開啟新介面〕；壞掉講原因、可以再試。「不再提醒」勾了就記下來（`on_remember`）。

下載與解壓在背景執行緒，結果經過佇列交回 Tk 的事件迴圈（Tk 的物件只能在主執行緒碰）。
"""
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import ttk

from subtitle import onedirupdate as odu
from subtitle import qtbridge
from subtitle.updatecheck import progress_text

TITLE = "3.0 新介面"
INSTALL_LABEL = "下載並安裝新介面"
LATER_LABEL = "以後再說"
CANCEL_LABEL = "取消下載"
OPEN_LABEL = "開啟新介面"
CLOSE_LABEL = "關閉"
RETRY_LABEL = "再試一次"
NEVER_LABEL = "不再提醒（之後想裝，到 GitHub 的 Release 頁下載 Qt 版的 zip）"
POLL_MS = 100


class QtBridgeDialog(tk.Toplevel):
    """
    參數：
        info：`qtbridge.offer` 的結果。exe_dir：一般版 exe 所在的資料夾；config_dir：一般版設定檔所在的資料夾。
        on_remember(never: bool)：視窗關掉時呼叫一次（勾了「不再提醒」為 True）。
        install_fn／launch_fn：測試換掉用（預設是 `qtbridge.install` 與 `subprocess.Popen`）。
    """

    def __init__(self, master, info, exe_dir, config_dir, on_remember=None,
                 install_fn=None, launch_fn=None):
        super().__init__(master)
        self.title(TITLE)
        self.transient(master)
        self.resizable(False, False)
        self.info = info
        self.exe_dir = exe_dir
        self.config_dir = config_dir
        self.on_remember = on_remember
        self.install_fn = install_fn or qtbridge.install
        self.launch_fn = launch_fn or (lambda args, cwd: subprocess.Popen(args, cwd=cwd))
        self.state = "offer"
        self.qt_exe = None
        self.error = ""
        self._cancel = threading.Event()
        self._queue = queue.Queue()
        self._thread = None

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        self.text_var = tk.StringVar(value=qtbridge.offer_text(info, exe_dir))
        self.text_label = ttk.Label(body, textvariable=self.text_var, wraplength=640, justify="left")
        self.sends_label = ttk.Label(body, text=qtbridge.SENDS, wraplength=640, justify="left")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress = ttk.Progressbar(body, variable=self.progress_var, maximum=100, length=600)
        self.status_var = tk.StringVar(value="")
        self.status_label = ttk.Label(body, textvariable=self.status_var, wraplength=640, justify="left")
        self.never_var = tk.BooleanVar(value=False)
        self.never_check = ttk.Checkbutton(body, text=NEVER_LABEL, variable=self.never_var)

        row = ttk.Frame(body)
        self.install_btn = ttk.Button(row, text=INSTALL_LABEL, command=self.start_install)
        self.cancel_btn = ttk.Button(row, text=CANCEL_LABEL, command=self.cancel_install)
        self.open_btn = ttk.Button(row, text=OPEN_LABEL, command=self.open_qt)
        self.close_btn = ttk.Button(row, text=LATER_LABEL, command=self.close)
        self._row = row
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._show_buttons()

    # ----- 畫面 -----
    def _show_buttons(self):
        for btn in (self.install_btn, self.cancel_btn, self.open_btn, self.close_btn):
            btn.pack_forget()
        if self.state == "offer":
            self.install_btn.configure(text=INSTALL_LABEL)
            self.close_btn.configure(text=LATER_LABEL)
            shown = (self.install_btn, self.close_btn)
        elif self.state in ("downloading", "preparing"):
            self.cancel_btn.configure(state="normal" if self.state == "downloading" else "disabled")
            shown = (self.cancel_btn,)
        elif self.state == "done":
            self.close_btn.configure(text=CLOSE_LABEL)
            shown = (self.open_btn, self.close_btn)
        else:  # error
            self.install_btn.configure(text=RETRY_LABEL)
            self.close_btn.configure(text=CLOSE_LABEL)
            shown = (self.install_btn, self.close_btn)
        for btn in shown:
            btn.pack(side="left", padx=(0, 8))
        # 由上往下：說明、會送什麼（裝好之後不用再講）、進度條（下載與解壓時）、那一行、不再提醒（裝好之後不用）、按鈕
        done = self.state == "done"
        layout = [(self.text_label, 0), (self.sends_label, 8) if not done else None,
                  (self.progress, 12) if self.state in ("downloading", "preparing") else None,
                  (self.status_label, 8) if self.status_var.get() else None,
                  (self.never_check, 12) if not done else None]
        for widget in (self.text_label, self.sends_label, self.progress, self.status_label, self.never_check, self._row):
            widget.pack_forget()
        for item in filter(None, layout):
            item[0].pack(anchor="w", pady=(item[1], 0))
        self._row.pack(fill="x", pady=(12, 0))

    # ----- 動作 -----
    def start_install(self):
        """背景下載並安裝。"""
        if self.state in ("downloading", "preparing"):
            return
        self._cancel.clear()
        self.state = "downloading"
        self.error = ""
        self.progress_var.set(0.0)
        self.status_var.set("正在連線到 GitHub…可以按「取消下載」。")
        self._show_buttons()
        # 背景執行緒不拿 self：視窗關掉之後它的 Tk 變數若在那條執行緒被回收，Tk 會抱怨「不在主執行緒」
        self._thread = threading.Thread(
            target=_work, args=(self.install_fn, self.info, self.exe_dir, self.config_dir, self._queue, self._cancel),
            daemon=True)
        self._thread.start()
        self.after(POLL_MS, self._poll)

    def _poll(self):
        if self.status_var is None:  # 已經關掉了
            return
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "progress":
                    done, total = payload
                    if total > 0:
                        self.progress_var.set(min(100.0, done * 100.0 / total))
                    self.status_var.set(progress_text(done, total))
                elif kind == "preparing":
                    self.state = "preparing"
                    self.status_var.set("下載完成，正在解壓並複製設定與工具…")
                    self._show_buttons()
                elif kind == "done":
                    self.state = "done"
                    self.qt_exe = payload
                    self.text_var.set(qtbridge.done_text(payload))
                    self.status_var.set("")
                    self._show_buttons()
                    return
                elif kind == "error":
                    self.state = "error"
                    self.error = payload
                    self.status_var.set(payload)
                    self._show_buttons()
                    return
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(POLL_MS, self._poll)

    def cancel_install(self):
        """取消下載（解壓與複製時不能取消，按鈕是灰的）。"""
        if self.state == "downloading":
            self._cancel.set()
            self.status_var.set("正在取消…")

    def open_qt(self):
        """開新介面（工作目錄＝新資料夾），然後關掉這個視窗；一般版照樣開著。"""
        if not self.qt_exe:
            return
        args, cwd = qtbridge.launch_args(self.qt_exe)
        try:
            self.launch_fn(args, cwd)
        except OSError as exc:
            self.status_var.set(f"開不起來：{exc}。可以到 {cwd} 直接雙擊 {odu.EXE_NAME}。")
            self._show_buttons()
            return
        self.close()

    def close(self):
        """關掉：下載中先取消；把「不再提醒」回報一次。"""
        if self.never_var is None:  # 已經關掉了
            return
        if self.state == "downloading":
            self._cancel.set()
        if self.on_remember:
            self.on_remember(bool(self.never_var.get()))
        self.destroy()
        # 視窗跟它的按鈕互相參照，要等垃圾回收才收得掉；回收可能剛好發生在背景執行緒，那時 Tk 變數的 __del__
        # 會抱怨「不在主執行緒」。在這裡（主執行緒）先放掉它們。
        self.text_var = self.progress_var = self.status_var = self.never_var = None


def _work(install_fn, info, exe_dir, config_dir, results, cancel):
    """背景執行緒：安裝，結果放進佇列（只碰佇列與事件，不碰 Tk）。"""
    try:
        exe = install_fn(info, exe_dir, config_dir,
                         progress=lambda done, total: results.put(("progress", (done, total))),
                         cancelled=cancel.is_set,
                         preparing=lambda: results.put(("preparing", None)))
        results.put(("done", exe))
    except odu.UpdateError as exc:
        results.put(("error", str(exc)))
    except Exception as exc:  # noqa: BLE001 —— 不認得的錯也講出來，不要讓視窗卡在下載中
        results.put(("error", f"安裝失敗：{exc}"))
