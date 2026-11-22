# -*- coding: utf-8 -*-
"""
全域熱鍵的 Qt 接線（3.0 第 11 項第二十六階段）：叫出框選螢幕翻譯。

核心 `subtitle/hotkey.py` 原封沿用：三種狀態（`global`／`window-only`／`unavailable`）、組合鍵解析與驗證、
每一種狀態都講得出一句話。這裡只換兩件事：

- **視窗內那條退路**：一般版用 Tk 的 `bind_all`；這裡用掛在主視窗上的 `QShortcut`（`Qt.ApplicationShortcut`：
  焦點在本程式任何一個視窗都有效），組合鍵用 `hotkey.to_qt_sequence` 換成 Qt 的寫法。
- **Windows 的全域熱鍵**：註冊一樣用 `RegisterHotKey`（沿用 `WindowsBackend`），但**不輪詢**——Qt 的事件迴圈
  會先把 `WM_HOTKEY` 拿走，一般版那種 `PeekMessage` 輪詢會搶不到。改成裝一個原生事件過濾器
  （`QAbstractNativeEventFilter`），在訊息經過時認出 `WM_HOTKEY`（ROADMAP 參考表 2026-09-23 就是這樣規劃的）。
  **開發環境沒有 Windows，這一段沒有實測**；認訊息的那個函式（`is_hotkey_message`）寫成純的，用 ctypes 自己組一個
  MSG 結構測得到。Linux／macOS 照一般版退成「只在本程式視窗內有效」，並明講。

熱鍵只會叫出框選（在這台電腦截圖、辨識），本身不送任何東西出去。預設關。
"""
import ctypes
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication

from subtitle import hotkey as hk

WM_HOTKEY = 0x0312
NATIVE_EVENT_TYPES = (b"windows_generic_MSG", b"windows_dispatcher_MSG")


class _MSG(ctypes.Structure):
    """Windows 的 MSG 結構（只用到 message 與 wParam；欄位照官方定義排，位址才對得上）。"""

    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint), ("wParam", ctypes.c_size_t),
                ("lParam", ctypes.c_ssize_t), ("time", ctypes.c_ulong), ("pt_x", ctypes.c_long),
                ("pt_y", ctypes.c_long)]


def is_hotkey_message(event_type, message, hotkey_id):
    """原生事件是不是我們註冊的那個熱鍵（`message` 是 MSG 結構的位址）。"""
    try:
        kind = bytes(event_type)
    except TypeError:
        return False
    if kind not in NATIVE_EVENT_TYPES or not message:
        return False
    msg = _MSG.from_address(int(message))
    return msg.message == WM_HOTKEY and msg.wParam == hotkey_id


class _NativeFilter(QAbstractNativeEventFilter):
    def __init__(self, hotkey_id, on_hit):
        super().__init__()
        self.hotkey_id = hotkey_id
        self.on_hit = on_hit

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        if is_hotkey_message(event_type, message, self.hotkey_id):
            self.on_hit()
            return True, 0
        return False, 0


def make_backend(window):
    if sys.platform == "win32":
        # 註冊、取消照 WindowsBackend；它的 poll（PeekMessage）在 Qt 裡不呼叫——HotkeyManager.poll 只在一般版的
        # 計時器裡叫，這裡改由原生事件過濾器接 WM_HOTKEY
        return hk.WindowsBackend(int(window.winId()))
    return hk.NullBackend()


class QtHotkey(QObject):
    """一個熱鍵：`enable(combo)` 回傳落在哪一種狀態；按到就發 `triggered`。"""

    triggered = Signal()

    def __init__(self, window, backend=None):
        super().__init__(window)
        self.window = window
        self.shortcut = None
        self._filter = None
        self.manager = hk.HotkeyManager(backend=backend if backend is not None else make_backend(window),
                                        window_binder=self._bind, window_unbinder=self._unbind,
                                        on_trigger=self.triggered.emit)

    @property
    def status(self):
        return self.manager.status

    def enable(self, combo):
        """組合鍵不合法時拋 `hotkey.HotkeyError`（訊息講得出怎麼改）。"""
        self._remove_filter()
        status = self.manager.enable(combo)
        if status == "global" and isinstance(self.manager.backend, hk.WindowsBackend):
            self._filter = _NativeFilter(self.manager.backend.hotkey_id, self.manager.trigger)
            QApplication.instance().installNativeEventFilter(self._filter)
        return status

    def disable(self):
        self._remove_filter()
        self.manager.disable()

    def describe(self):
        return self.manager.describe()

    def _remove_filter(self):
        if self._filter is not None:
            QApplication.instance().removeNativeEventFilter(self._filter)
            self._filter = None

    def _bind(self, _tk_sequence):
        sequence = QKeySequence(hk.to_qt_sequence(self.manager.combo))
        if sequence.isEmpty():
            return False
        self.shortcut = QShortcut(sequence, self.window)
        self.shortcut.setContext(Qt.ApplicationShortcut)  # 焦點在本程式任何一個視窗都有效
        self.shortcut.activated.connect(self.manager.trigger)
        return True

    def _unbind(self, _tk_sequence):
        if self.shortcut is not None:
            self.shortcut.setEnabled(False)
            self.shortcut.setParent(None)
            self.shortcut.deleteLater()
            self.shortcut = None
