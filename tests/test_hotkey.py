# -*- coding: utf-8 -*-
"""
`subtitle/hotkey.py` 測試：全域熱鍵與它的兩條退路。

ROADMAP 第 9 項第一階段的第 4 項。

**Windows 的 `RegisterHotKey` 在開發環境驗不到**，所以測試分成兩半：組合
鍵的解析／正規化／驗證／換成 Tk 綁定字串全部是純函式，離線測得完；三種
狀態（global／window-only／unavailable）用假的後端把每一條路都走過；而
**視窗內綁定那條退路是在真的 Tk 裡實測的**——那是全域熱鍵搶不到時使用者
唯一還能用的路，不能只靠推論。

守住四件事：

  1. **沒有修飾鍵的全域熱鍵要擋下來。** 註冊一個光禿禿的 Z，整台電腦按
     Z 都會被本程式吃掉。
  2. **註冊失敗絕對不可以靜默。** 使用者按了沒反應又沒有任何說明，只會
     認定功能是壞的。
  3. **訊息要講真話。** 「被別的程式佔走」和「這個系統不支援」是兩回事；
     在不支援的系統上叫使用者去換組合鍵，他怎麼換都不會好。
  4. **換組合鍵時舊的要失效。** 不解除舊綁定的話兩個鍵都有效，使用者以
     為自己換走了。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import hotkey as hk

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


# ===== 1. 設定 ==========================================================

base = hk.resolve_hotkey_settings(None)
check("預設是關閉的（螢幕翻譯的觸發器，由使用者主動打開）",
      base["enabled"] is False)
check("預設組合鍵合法", hk.parse_combo(base["combo"])["text"] == base["combo"])
# 預設熱鍵不可以撞到常見的編輯快捷鍵。第一版的 Ctrl+Shift+Z 是 Premiere／
# Photoshop／Word 的「重做」，註冊成全域熱鍵等於把使用者的重做搶走。
_COMMON_SHORTCUTS = {
    "Ctrl+Z", "Ctrl+Y", "Ctrl+Shift+Z", "Ctrl+C", "Ctrl+V", "Ctrl+X",
    "Ctrl+A", "Ctrl+S", "Ctrl+Shift+S", "Ctrl+O", "Ctrl+N", "Ctrl+W",
    "Ctrl+F", "Ctrl+P", "Ctrl+T", "Ctrl+Shift+T",
    "Alt+F4", "Alt+F8", "Ctrl+K", "Ctrl+M",
    "Ctrl+D", "Ctrl+Shift+E", "Ctrl+Alt+T",
}
_normalized_common = {hk.format_combo(c) for c in _COMMON_SHORTCUTS}
check("預設熱鍵沒有撞到常見的編輯快捷鍵（重做、複製、存檔…）",
      base["combo"] not in _normalized_common, base["combo"])
check("設定檔的值會被讀進來",
      hk.resolve_hotkey_settings(
          {"hotkey": {"combo": "alt+f8", "enabled": True}})["combo"]
      == "Alt+F8")
check("設定檔被手改壞時退回預設，不會讓程式起不來",
      hk.resolve_hotkey_settings(
          {"hotkey": {"combo": "這不是熱鍵"}})["combo"]
      == hk.DEFAULT_HOTKEY["combo"])
check("不認得的鍵不會混進來",
      "nonsense" not in hk.resolve_hotkey_settings({"hotkey": {"nonsense": 1}}))


# ===== 2. 解析與正規化 ==================================================

check("基本組合解析得出來",
      hk.parse_combo("Ctrl+Shift+Z")["vk"] == 0x5A)
check("大小寫與順序不同但是同一個組合",
      hk.format_combo("shift+ctrl+z") == hk.format_combo("Ctrl+Shift+Z")
      == "Ctrl+Shift+Z")
check("用減號分隔也認得", hk.format_combo("Ctrl-Alt-F5") == "Ctrl+Alt+F5")
check("F 鍵的虛擬鍵碼對（F1=0x70）",
      hk.parse_combo("Ctrl+F1")["vk"] == 0x70
      and hk.parse_combo("Ctrl+F12")["vk"] == 0x7B)
check("數字鍵的虛擬鍵碼對", hk.parse_combo("Alt+7")["vk"] == 0x37)
check("有名字的按鍵認得出來",
      hk.parse_combo("Ctrl+PageDown")["vk"] == 0x22
      and hk.parse_combo("Win+Space")["vk"] == 0x20)
check("修飾鍵旗標組得對（Ctrl|Shift|NOREPEAT）",
      hk.parse_combo("Ctrl+Shift+Z")["flags"]
      == (hk.MOD_CONTROL | hk.MOD_SHIFT | hk.MOD_NOREPEAT),
      hex(hk.parse_combo("Ctrl+Shift+Z")["flags"]))
check("一律帶 MOD_NOREPEAT（按著不放不要一直重複觸發）",
      hk.parse_combo("Alt+F5")["flags"] & hk.MOD_NOREPEAT)
check("重複寫同一個修飾鍵不會變成兩個",
      hk.format_combo("Ctrl+Ctrl+Z") == "Ctrl+Z")


# ===== 3. 該擋的都要擋，而且要講得出怎麼改 ==============================

for bad, why in (("", "空的"), ("Ctrl", "只有修飾鍵"),
                 ("Ctrl+Shift", "只有修飾鍵"), ("Ctrl+A+B", "兩個主鍵"),
                 ("Ctrl+F13", "沒有 F13"), ("Ctrl+眼", "中文字"),
                 ("Ctrl+٣", "非 ASCII 數字")):
    try:
        hk.parse_combo(bad)
        check(f"擋下不合法的組合鍵（{why}）", False, f"{bad!r} 沒有被擋")
    except hk.HotkeyError as exc:
        check(f"擋下不合法的組合鍵（{why}）", True)
        check(f"（{why}）的訊息講得出怎麼改", len(str(exc)) > 12, str(exc))

# 這兩個是實跑才發現的：Python 裡「眼」.isalpha() 與「٣」.isdigit() 都是
# True，只看 isalpha/isdigit 會把一個中文字變成虛擬鍵碼 0x773C 送進
# RegisterHotKey。上面那一圈已經涵蓋，這裡單獨再寫一條指名它。
try:
    hk.parse_combo("Ctrl+眼")
    check("中文字不可以被當成按鍵（isalpha() 對 CJK 是 True）", False)
except hk.HotkeyError:
    check("中文字不可以被當成按鍵（isalpha() 對 CJK 是 True）", True)

try:
    hk.parse_combo("Z")
    check("沒有修飾鍵的全域熱鍵要擋（不然整台電腦按 Z 都被吃掉）", False,
          "沒有被擋")
except hk.HotkeyError as exc:
    check("沒有修飾鍵的全域熱鍵要擋（不然整台電腦按 Z 都被吃掉）",
          "Ctrl" in str(exc), str(exc))


# ===== 4. 換成 Tk 綁定字串（window-only 那條退路的基礎）=================

check("一般字母鍵", hk.to_tk_binding("Ctrl+Shift+Z")
      == "<Control-Shift-KeyPress-Z>", hk.to_tk_binding("Ctrl+Shift+Z"))
check("F 鍵", hk.to_tk_binding("Alt+F5") == "<Alt-KeyPress-F5>")
check("有名字的鍵用 Tk 自己的名字（PageDown 是 Next）",
      hk.to_tk_binding("Ctrl+PageDown") == "<Control-KeyPress-Next>",
      hk.to_tk_binding("Ctrl+PageDown"))
check("Win 鍵換成 Super", hk.to_tk_binding("Win+Space")
      == "<Super-KeyPress-space>", hk.to_tk_binding("Win+Space"))


# ===== 5. 三種狀態都要走得到，而且都要有話講 ============================

class FakeBackend:
    def __init__(self, error=None):
        self.error = error
        self.registered = False
        self.hits = 0

    def register(self, parsed):
        if self.error:
            raise self.error
        self.registered = True
        return True

    def unregister(self):
        self.registered = False

    def poll(self):
        if self.hits:
            self.hits -= 1
            return True
        return False


fired = []
manager = hk.HotkeyManager(backend=FakeBackend(),
                           on_trigger=lambda: fired.append(1))
check("全域註冊成功時狀態是 global",
      manager.enable("Ctrl+Shift+Z") == "global")
check("global 的說明講得出「在任何程式裡按都有效」",
      "任何程式" in manager.describe(), manager.describe())
manager.backend.hits = 1
check("global 模式下輪詢到訊息會觸發回呼",
      manager.poll() and len(fired) == 1)
check("沒有訊息時不會亂觸發", not manager.poll() and len(fired) == 1)

bound = []
manager2 = hk.HotkeyManager(
    backend=FakeBackend(hk.HotkeyTakenError("已經被其他程式註冊走了")),
    window_binder=lambda seq: (bound.append(seq), True)[1],
    window_unbinder=lambda seq: bound.remove(seq) if seq in bound else None)
check("全域搶不到時退回 window-only（功能不會整個不能用）",
      manager2.enable("Ctrl+Shift+Z") == "window-only")
check("退回時真的去綁了視窗內的那個組合鍵",
      bound == ["<Control-Shift-KeyPress-Z>"], str(bound))
check("被佔走時說明要指名是哪一個組合鍵、並建議換一個",
      "Ctrl+Shift+Z" in manager2.describe()
      and "佔走" in manager2.describe()
      and "換一個" in manager2.describe(), manager2.describe())

manager3 = hk.HotkeyManager(
    backend=FakeBackend(hk.HotkeyError("這個作業系統沒有支援全域熱鍵")),
    window_binder=lambda seq: True)
manager3.enable("Ctrl+Shift+Z")
check("「系統不支援」不可以被說成「被別的程式佔走」"
      "（在不支援的系統上叫人去換組合鍵，怎麼換都不會好）",
      "佔走" not in manager3.describe(), manager3.describe())
check("「系統不支援」的說明仍然講得出退路",
      "本程式視窗內" in manager3.describe(), manager3.describe())

manager4 = hk.HotkeyManager(
    backend=FakeBackend(hk.HotkeyError("沒得註冊")),
    window_binder=lambda seq: False)
check("連視窗內都綁不上時狀態是 unavailable",
      manager4.enable("Ctrl+Shift+Z") == "unavailable")
check("unavailable 也要有話講，而且要指出還有按鈕可以用",
      "按鈕" in manager4.describe(), manager4.describe())

check("關閉之後狀態回到 off",
      (manager2.disable(), manager2.status)[1] == "off")
check("關閉時會把舊的視窗綁定解掉（不解的話兩個鍵都有效）",
      bound == [], str(bound))

# 後端丟出非預期的例外時不可以讓整個程式掛掉——仍然要退回去。
# 這個後端會丟非預期例外，而管理器會（正確地）把 traceback 記進 log。
# 測試輸出裡冒出一整段 traceback 容易被誤讀成「測試掛了」，所以暫時把這
# 個模組的 log 壓下來——壓的是雜訊，不是斷言。
import logging as _logging

_logging.getLogger("subtitle.hotkey").setLevel(_logging.CRITICAL)


class ExplodingBackend:
    def register(self, parsed):
        raise RuntimeError("意料之外")

    def unregister(self):
        pass

    def poll(self):
        return False


manager5 = hk.HotkeyManager(backend=ExplodingBackend(),
                            window_binder=lambda seq: True)
check("後端丟出非預期例外時仍然退回 window-only，不是整個炸掉",
      manager5.enable("Ctrl+Shift+Z") == "window-only")

try:
    hk.HotkeyManager(backend=FakeBackend()).enable("Ctrl+F13")
    check("啟用不合法的組合鍵要拋 HotkeyError", False, "沒有丟例外")
except hk.HotkeyError:
    check("啟用不合法的組合鍵要拋 HotkeyError", True)


# ===== 6. 視窗內綁定：在真的 Tk 裡實測 ==================================

if not os.environ.get("DISPLAY"):
    print("SKIP Tk 實測段：無 DISPLAY")
else:
    import tkinter as tk

    try:
        root = tk.Tk()
        root.geometry("300x120")
        root.deiconify()
        for _ in range(10):
            root.update()

        hits = []

        def binder(sequence):
            root.bind_all(sequence, lambda _e: live.trigger())
            return True

        def unbinder(sequence):
            root.unbind_all(sequence)

        live = hk.HotkeyManager(
            backend=hk.NullBackend(), window_binder=binder,
            window_unbinder=unbinder, on_trigger=lambda: hits.append(1))
        check("這個平台上全域註冊不起來，會退回 window-only",
              live.enable("Ctrl+Shift+Z") == "window-only", live.status)

        root.focus_force()
        for _ in range(10):
            root.update()
        root.event_generate("<Control-Shift-KeyPress-Z>")
        for _ in range(10):
            root.update()
        check("Tk 實測：視窗內按下組合鍵真的會觸發（這是搶不到全域時"
              "唯一還能用的路）", len(hits) == 1, str(len(hits)))

        # 換一個組合鍵：舊的必須失效，新的必須有效。
        hits.clear()
        live.enable("Alt+F5")
        root.event_generate("<Control-Shift-KeyPress-Z>")
        for _ in range(8):
            root.update()
        check("Tk 實測：換了組合鍵之後，舊的那個不再觸發",
              len(hits) == 0, str(len(hits)))
        root.event_generate("<Alt-KeyPress-F5>")
        for _ in range(8):
            root.update()
        check("Tk 實測：新的組合鍵會觸發", len(hits) == 1, str(len(hits)))

        live.disable()
        hits.clear()
        root.event_generate("<Alt-KeyPress-F5>")
        for _ in range(8):
            root.update()
        check("Tk 實測：關閉之後就不再觸發", len(hits) == 0, str(len(hits)))

        root.destroy()
    except tk.TclError as exc:
        message = str(exc).lower()
        if "display" in message or "connect" in message:
            print(f"SKIP Tk 實測段（無顯示器：{exc}）")
        else:
            check("Tk 實測段沒有丟 TclError", False, str(exc))


print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("subtitle/hotkey.py 測試全數通過。")
