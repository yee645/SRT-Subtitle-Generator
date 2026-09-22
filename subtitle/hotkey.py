# -*- coding: utf-8 -*-
"""
全域熱鍵：讓使用者在別的程式裡（遊戲、瀏覽器、播放器）按一個組合鍵，就
能叫出框選翻譯。

**這個模組最重要的設計是「失敗的時候怎麼辦」，不是「成功的時候怎麼做」。**
`docs/ROADMAP_2.0.md` 的技術現實表早就記著全域熱鍵「理論可行但脆弱」：組
合鍵可能已經被別的程式佔走、可能被系統保留、在某些環境根本註冊不起來。
所以這裡定義了**三種狀態**，而不是「成功／失敗」兩種：

| 狀態 | 意思 | 使用者體驗 |
|---|---|---|
| `global` | 全域熱鍵註冊成功 | 在任何程式裡按都有效 |
| `window-only` | 註冊不起來，退回只在本程式視窗內有效 | 焦點在本程式時按有效 |
| `unavailable` | 連視窗內的綁定都失敗 | 只能用按鈕 |

**退回 `window-only` 是這個模組的關鍵**：全域熱鍵搶不到不代表功能要整個
不能用。使用者切回本程式再按一樣能用，而且介面會明講現在是哪一種狀態、
是哪一個組合鍵搶不到——**絕對不可以靜默失敗**，那會變成「我按了沒反應，
這功能是壞的嗎」。

**Windows 那一段（`RegisterHotKey`）在開發環境驗不到**，所以：

- 組合鍵的**解析、正規化、驗證、換成 Tk 綁定字串**全部寫成純函式，離線
  測得到（也就是說「Ctrl+Shift+Z 到底代表什麼」這件事是驗過的）。
- 平台相關的部分收在 `WindowsBackend`，每一個 API 呼叫都檢查回傳值；
  `HotkeyManager` 對後端只認一個小介面，測試用假的後端把三種狀態都走過。
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

DEFAULT_HOTKEY = {
    # 預設關閉：這是「螢幕翻譯」的觸發器，而螢幕內容比剪貼簿更敏感，
    # 沿用 v2.1.0 的原則由使用者主動打開。
    "enabled": False,
    "combo": "Ctrl+Shift+Z",
}

# Windows 的修飾鍵旗標（MOD_ALT/CONTROL/SHIFT/WIN）。
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x0001, 0x0002, 0x0004, 0x0008
# MOD_NOREPEAT：按著不放不要一直重複觸發。
MOD_NOREPEAT = 0x4000

_MODIFIER_ALIASES = {
    "ctrl": "Ctrl", "control": "Ctrl",
    "alt": "Alt",
    "shift": "Shift",
    "win": "Win", "super": "Win", "cmd": "Win", "meta": "Win",
}
_MODIFIER_FLAGS = {"Ctrl": MOD_CONTROL, "Alt": MOD_ALT,
                   "Shift": MOD_SHIFT, "Win": MOD_WIN}
# 換成 Tk 的 bind 字串時用的名字。
_MODIFIER_TK = {"Ctrl": "Control", "Alt": "Alt", "Shift": "Shift",
                "Win": "Super"}

# 有名字的按鍵 → (顯示名, 虛擬鍵碼, Tk 的鍵名)。
_NAMED_KEYS = {
    "space": ("Space", 0x20, "space"),
    "enter": ("Enter", 0x0D, "Return"),
    "return": ("Enter", 0x0D, "Return"),
    "tab": ("Tab", 0x09, "Tab"),
    "insert": ("Insert", 0x2D, "Insert"),
    "delete": ("Delete", 0x2E, "Delete"),
    "home": ("Home", 0x24, "Home"),
    "end": ("End", 0x23, "End"),
    "pageup": ("PageUp", 0x21, "Prior"),
    "pagedown": ("PageDown", 0x22, "Next"),
    "left": ("Left", 0x25, "Left"),
    "up": ("Up", 0x26, "Up"),
    "right": ("Right", 0x27, "Right"),
    "down": ("Down", 0x28, "Down"),
    "backslash": ("Backslash", 0xDC, "backslash"),
}


class HotkeyError(ValueError):
    """組合鍵不合法；訊息一律寫成使用者看得懂、講得出怎麼改的話。"""


class HotkeyTakenError(HotkeyError):
    """組合鍵被別的程式佔走了——和「這個系統不支援」是不同的事。

    分成兩種例外不是潔癖：**訊息要講真話**。第一版兩種都寫成「被別的程式
    佔用了」，於是在根本不支援全域熱鍵的系統上，使用者會被告知一個不存在
    的原因，然後去改組合鍵——怎麼改都不會好。
    """


def _clamp(value, low, high):
    return max(low, min(high, value))


def resolve_hotkey_settings(config=None):
    """取出本模組的設定，缺漏補預設值；組合鍵壞掉時退回預設。"""
    raw = dict(DEFAULT_HOTKEY)
    if config:
        raw.update({k: v for k, v in (config.get("hotkey") or {}).items()
                    if k in DEFAULT_HOTKEY})
    combo = str(raw["combo"] or "").strip() or DEFAULT_HOTKEY["combo"]
    try:
        # 正規化之後再存回去：整個程式只流通一種寫法，介面上也不會一下
        # 顯示「alt+f8」一下顯示「Alt+F8」。
        combo = format_combo(combo)
    except HotkeyError:
        # 設定檔被手改壞不該讓程式起不來，退回預設並留下記錄。
        logger.warning("設定檔裡的熱鍵「%s」不合法，退回預設值", combo)
        combo = DEFAULT_HOTKEY["combo"]
    return {"enabled": bool(raw["enabled"]), "combo": combo}


# ----------------------------------------------------------------------
# 組合鍵：解析、正規化、驗證（純函式，離線測得到）
# ----------------------------------------------------------------------
def parse_combo(text):
    """
    把「Ctrl+Shift+Z」拆成修飾鍵與主鍵。

    回傳 ``{"modifiers", "key", "vk", "flags", "text"}``。不合法時拋出
    `HotkeyError`，而且訊息要講得出**怎麼改**——使用者看到的是設定裡的
    一行字，不是堆疊追蹤。
    """
    if not str(text or "").strip():
        raise HotkeyError("還沒有設定熱鍵。請輸入像「Ctrl+Shift+Z」這樣的組合。")
    parts = [p.strip() for p in str(text).replace("-", "+").split("+")]
    parts = [p for p in parts if p]
    if not parts:
        raise HotkeyError("熱鍵格式看不懂。請輸入像「Ctrl+Shift+Z」這樣的組合。")

    modifiers, key_parts = [], []
    for part in parts:
        alias = _MODIFIER_ALIASES.get(part.lower())
        if alias:
            if alias not in modifiers:
                modifiers.append(alias)
        else:
            key_parts.append(part)

    if len(key_parts) != 1:
        raise HotkeyError(
            "熱鍵要有剛好一個主鍵，例如「Ctrl+Shift+Z」。"
            + (f"目前看到 {len(key_parts)} 個主鍵。" if key_parts
               else "目前只有修飾鍵。"))
    if not modifiers:
        # 沒有修飾鍵的全域熱鍵會把那個鍵整台電腦都吃掉，一定要擋。
        raise HotkeyError(
            "全域熱鍵至少要搭一個 Ctrl／Alt／Shift／Win，"
            "不然那個按鍵在所有程式裡都會被本程式吃掉。")

    raw_key = key_parts[0]
    named = _NAMED_KEYS.get(raw_key.lower())
    if named:
        key, vk, _tk = named
    # 一定要連 isascii() 一起擋：`"眼".isalpha()` 與 `"٣".isdigit()` 在
    # Python 裡都是 True，只看 isalpha/isdigit 會讓一個中文字變成虛擬鍵碼
    # 0x773C 這種東西送進 RegisterHotKey。（實跑才發現的。）
    elif len(raw_key) == 1 and raw_key.isascii() and raw_key.isalpha():
        key, vk = raw_key.upper(), ord(raw_key.upper())
    elif len(raw_key) == 1 and raw_key.isascii() and raw_key.isdigit():
        key, vk = raw_key, ord(raw_key)
    elif (len(raw_key) in (2, 3) and raw_key[0].lower() == "f"
          and raw_key[1:].isdigit() and 1 <= int(raw_key[1:]) <= 12):
        number = int(raw_key[1:])
        key, vk = f"F{number}", 0x70 + number - 1
    else:
        raise HotkeyError(
            f"認不得按鍵「{raw_key}」。可以用英文字母、數字、F1~F12，"
            "或 Space、Enter、Insert 這類名稱。")

    # 修飾鍵固定排成 Ctrl → Alt → Shift → Win，同一個組合只有一種寫法。
    order = ["Ctrl", "Alt", "Shift", "Win"]
    modifiers = [m for m in order if m in modifiers]
    flags = MOD_NOREPEAT
    for modifier in modifiers:
        flags |= _MODIFIER_FLAGS[modifier]
    return {"modifiers": modifiers, "key": key, "vk": vk, "flags": flags,
            "text": "+".join(modifiers + [key])}


def format_combo(text):
    """正規化寫法：「shift+ctrl+z」與「Ctrl+Shift+Z」是同一個。"""
    return parse_combo(text)["text"]


def to_tk_binding(text):
    """
    換成 Tk 的 bind 字串，例如 ``<Control-Shift-KeyPress-Z>``。

    這個換算是 `window-only` 那條退路的基礎——全域熱鍵註冊不起來時，同一
    個組合鍵改綁在本程式視窗上，使用者切回來還是按得到。
    """
    parsed = parse_combo(text)
    named = _NAMED_KEYS.get(parsed["key"].lower())
    if named:
        key_name = named[2]
    elif parsed["key"].startswith("F") and parsed["key"][1:].isdigit():
        key_name = parsed["key"]
    else:
        key_name = parsed["key"]
    prefix = "".join(f"{_MODIFIER_TK[m]}-" for m in parsed["modifiers"])
    return f"<{prefix}KeyPress-{key_name}>"


def describe_status(status, combo, reason="", taken=False):
    """
    把狀態換成一句使用者看得懂的話。

    **靜默失敗是這裡最該避免的事**：使用者按了沒反應卻沒有任何說明，只會
    認定這個功能是壞的。所以每一種狀態都有話講，而且一定講出是哪一個組合
    鍵。
    """
    combo = combo or "（未設定）"
    if status == "global":
        return f"全域熱鍵已啟用：在任何程式裡按 {combo} 都能框選翻譯。"
    if status == "window-only":
        common = (f"改成只在本程式視窗內有效——切回本程式再按 {combo} "
                  "一樣可以用。")
        if taken:
            return (f"{combo} 已經被別的程式佔走，{common}"
                    "要在遊戲裡直接按的話，請在設定裡換一個沒被佔用的組合鍵。")
        tail = f"（{reason}）" if reason else ""
        return f"這個系統上註冊不了全域熱鍵{tail}，{common}"
    if status == "unavailable":
        tail = f"（{reason}）" if reason else ""
        return (f"熱鍵 {combo} 註冊不起來{tail}。這個功能仍然可以用畫面上的"
                "按鈕啟動。")
    return f"熱鍵 {combo} 尚未啟用。"


# ----------------------------------------------------------------------
# 後端
# ----------------------------------------------------------------------
class WindowsBackend:
    """
    Windows 的 `RegisterHotKey`。**開發環境無法實測。**

    刻意不自己開執行緒跑訊息迴圈：那會多一個很難除錯的東西。改成註冊到
    Tk 視窗的 handle 上，再由 `HotkeyManager` 用 Tk 的計時器輪詢訊息佇
    列——慢一點點（120ms），但可預期得多。
    """

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.hotkey_id = 1
        self._registered = False

    def register(self, parsed):
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        if not user32.RegisterHotKey(self.hwnd, self.hotkey_id,
                                     parsed["flags"], parsed["vk"]):
            code = ctypes.get_last_error()
            # 1409 = ERROR_HOTKEY_ALREADY_REGISTERED，最常見的情形。
            if code == 1409:
                raise HotkeyTakenError("已經被其他程式註冊走了")
            raise HotkeyError(f"系統拒絕註冊（錯誤碼 {code}）")
        self._registered = True
        return True

    def unregister(self):
        if not self._registered:
            return
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.UnregisterHotKey(self.hwnd, self.hotkey_id)
        self._registered = False

    def poll(self):
        """有沒有被按到；被按到回傳 True。"""
        if not self._registered:
            return False
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)

        class MSG(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                        ("wParam", wintypes.WPARAM),
                        ("lParam", wintypes.LPARAM),
                        ("time", wintypes.DWORD),
                        ("pt_x", ctypes.c_long), ("pt_y", ctypes.c_long)]

        message = MSG()
        wm_hotkey = 0x0312
        hit = False
        # PM_REMOVE=1：取出來就從佇列移除，不然會一直重複觸發。
        while user32.PeekMessageW(ctypes.byref(message), None,
                                  wm_hotkey, wm_hotkey, 1):
            if message.message == wm_hotkey:
                hit = True
        return hit


class NullBackend:
    """沒有全域熱鍵可用的平台（Linux／macOS）；一律註冊失敗，退回視窗內。"""

    def register(self, parsed):
        raise HotkeyError("這個作業系統沒有支援全域熱鍵")

    def unregister(self):
        pass

    def poll(self):
        return False


def make_backend(hwnd=None):
    """依平台挑後端。"""
    if sys.platform == "win32" and hwnd:
        return WindowsBackend(hwnd)
    return NullBackend()


# ----------------------------------------------------------------------
# 管理器
# ----------------------------------------------------------------------
class HotkeyManager:
    """
    三種狀態的熱鍵管理器（見模組說明的表）。

    只依賴兩個很小的東西：一個 `backend`（register/unregister/poll）與一
    個 `window_binder`（把同一個組合鍵綁在本程式視窗上，回傳有沒有成
    功）。測試用假的把三條路都走過，不必有 Windows。
    """

    def __init__(self, backend=None, window_binder=None, on_trigger=None,
                 window_unbinder=None):
        self.backend = backend or NullBackend()
        self.window_binder = window_binder
        # 換組合鍵時要把舊的視窗綁定解掉，否則舊的那個還會繼續觸發——
        # 使用者以為自己換走了，結果兩個鍵都有效。（實跑才發現的。）
        self.window_unbinder = window_unbinder
        self.on_trigger = on_trigger
        self.status = "off"
        self.combo = ""
        self.reason = ""
        self.taken = False
        self._bound_sequence = ""

    def enable(self, combo):
        """
        啟用熱鍵，回傳最後落在哪一種狀態。

        順序是刻意的：先試全域，搶不到才退回視窗內，兩個都不行才是真的不
        能用。每一步都把原因記下來，介面才講得出「為什麼」。
        """
        parsed = parse_combo(combo)          # 不合法就讓它往上拋
        self.disable()
        self.combo = parsed["text"]
        self.taken = False
        try:
            self.backend.register(parsed)
            self.status = "global"
            self.reason = ""
            return self.status
        except HotkeyTakenError as exc:
            self.taken = True
            self.reason = str(exc)
            logger.info("全域熱鍵 %s 被佔走：%s", self.combo, exc)
        except HotkeyError as exc:
            self.reason = str(exc)
            logger.info("全域熱鍵 %s 註冊失敗：%s", self.combo, exc)
        except Exception as exc:       # 後端出乎意料的錯誤不該讓程式掛掉
            self.reason = str(exc)
            logger.exception("全域熱鍵 %s 註冊時發生非預期錯誤", self.combo)

        if self.window_binder:
            try:
                sequence = to_tk_binding(self.combo)
                if self.window_binder(sequence):
                    self._bound_sequence = sequence
                    self.status = "window-only"
                    return self.status
            except Exception as exc:   # 綁不上去也只是再退一步
                logger.exception("視窗內熱鍵綁定失敗")
                self.reason = self.reason or str(exc)
        self.status = "unavailable"
        return self.status

    def disable(self):
        try:
            self.backend.unregister()
        except Exception:              # 取消註冊失敗不該擋住任何事
            logger.debug("取消註冊熱鍵時發生錯誤", exc_info=True)
        if self._bound_sequence and self.window_unbinder:
            try:
                self.window_unbinder(self._bound_sequence)
            except Exception:
                logger.debug("解除視窗內熱鍵綁定時發生錯誤", exc_info=True)
        self._bound_sequence = ""
        self.status = "off"
        self.reason = ""
        self.taken = False

    def poll(self):
        """全域模式下由計時器定期呼叫；被按到就觸發回呼。"""
        if self.status != "global":
            return False
        try:
            if self.backend.poll():
                self.trigger()
                return True
        except Exception:
            logger.exception("輪詢熱鍵訊息時發生錯誤")
        return False

    def trigger(self):
        """視窗內綁定那條路直接呼叫這個。"""
        if self.on_trigger:
            self.on_trigger()

    def describe(self):
        return describe_status(self.status, self.combo, self.reason,
                               self.taken)
