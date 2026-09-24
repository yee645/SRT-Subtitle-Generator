# -*- coding: utf-8 -*-
"""
查譯面板的螢幕翻譯介面（ROADMAP 第 9 項 5b-2）。

守住的事：

  1. **真的框、真的截、真的辨識**：在 X 上畫一行字，走面板的流程截下來
     給 tesseract 認，結果要出現在原文框、而且原文框**可以改**。
  2. **像密碼的內容不會送出**——不只按鈕那條路，**在原文框選字觸發的
     選取即翻譯**也要擋（那條路不經過按鈕；實作時才發現的洞）。
  3. **使用者改過的原文**按翻譯前要再檢查一次。
  4. 朗讀／複製**不需要金鑰**；複製進剪貼簿的東西不會被監聽剪貼簿再翻一次。
  5. 熱鍵：這個平台沒有全域熱鍵，要退回本程式視窗內，按下去真的會開始
     框選；關掉要真的解除綁定；面板銷毀時要一起收掉。
  6. 預設視窗大小裝得下全部內容（含 sv_ttk 主題，它的按鈕比較寬）。

沒有 X 或沒有 tesseract 的部分照實報「略過」，不假裝通過。
"""
import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def guarded(name, fn):
    """區塊內丟例外就記成失敗、繼續往下跑（不讓整檔中止）。"""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        check(name + "（區塊內丟出例外）", False, f"{type(exc).__name__}: {exc}")


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
panel_src = open(os.path.join(REPO, "gui", "quicktranslate_panel.py"),
                 encoding="utf-8").read()
app_src = open(os.path.join(REPO, "gui", "app.py"), encoding="utf-8").read()

# ===== 0. 靜態 ==========================================================
check("密碼檢查放在所有路徑都經過的 _submit 裡",
      "st.is_secret(source)" in panel_src.split("def _submit", 1)[1].split("def ", 1)[0])
check("主程式啟動時會為熱鍵在背景建立面板",
      "start_hidden=True" in app_src and "_maybe_start_hotkey" in app_src)

try:
    import tkinter as tk
    root = tk.Tk()
except Exception as exc:  # noqa: BLE001
    print(f"SKIP 介面實測段：開不了 Tk（{exc}）")
    root = None

if root is not None:
    import gui.quicktranslate_panel as qp
    from subtitle import ocrengine, speech

    qp.save_config = lambda *a, **k: None
    qp.save_vocab = lambda *a, **k: None
    qp.load_vocab = lambda *a, **k: []
    root.geometry("900x200+0+0")

    def pump(seconds=0.2):
        end = time.time() + seconds
        while time.time() < end:
            root.update()
            time.sleep(0.02)

    def make(key="sk-test", **kw):
        panel = qp.QuickTranslatePanel(root, {"transcription": {"api_key": key}}, **kw)
        panel.geometry("+920+0")
        pump(0.1)
        return panel

    def spy_worker(panel):
        """把真的 API 呼叫換掉，只記下有沒有被送出去。"""
        sent = []
        panel._worker = lambda source, *a: sent.append(source)
        return sent

    # ===== 1. 版面 ======================================================
    def layout():
        themes = ["（預設主題）"]
        try:
            import sv_ttk  # noqa: F401
            themes += ["light", "dark"]
        except ImportError:
            print("SKIP sv_ttk 主題下的版面（沒有 sv_ttk）")
        for theme in themes:
            if theme != "（預設主題）":
                import sv_ttk
                sv_ttk.set_theme(theme)
            p = make()
            pump(0.2)
            check(f"[{theme}] 預設高度裝得下全部內容",
                  p.winfo_height() >= p.winfo_reqheight(),
                  (p.winfo_height(), p.winfo_reqheight()))
            row = p.screen_btn.master
            right = p.hotkey_check.winfo_x() + p.hotkey_check.winfo_reqwidth()
            check(f"[{theme}] 框選列（含熱鍵勾選）沒有被右邊截掉",
                  right <= row.winfo_width(), (right, row.winfo_width()))
            voice = p.speak_src_btn.master
            check(f"[{theme}] 朗讀／複製列沒有被截掉",
                  voice.winfo_reqwidth() <= voice.winfo_width(),
                  (voice.winfo_reqwidth(), voice.winfo_width()))
            p.destroy()
    guarded("版面", layout)

    # ===== 2. 真實框選 → 截圖 → 辨識 ====================================
    def real_flow():
        if not ocrengine.tesseract_available():
            print("SKIP 真實辨識（沒有 tesseract）")
            return
        label = tk.Label(root, text="The quick brown fox jumps",
                         font=("DejaVu Sans", 28), bg="white", fg="black")
        label.place(x=20, y=40)
        pump(0.3)
        p = make()
        sent = spy_worker(p)
        region = (label.winfo_rootx(), label.winfo_rooty(),
                  label.winfo_rootx() + label.winfo_width(),
                  label.winfo_rooty() + label.winfo_height())
        p._ocr_busy = True
        p._on_region_selected(region)
        end = time.time() + 30
        while p._ocr_busy and time.time() < end:
            pump(0.05)
        text = p.src_text.get("1.0", "end-1c")
        check("真的截圖並辨識出畫面上的字", "quick brown fox" in text, repr(text))
        check("辨識結果的原文框可以編輯", str(p.src_text.cget("state")) == "normal")
        check("預設不自動送出（先給人看）", sent == [], sent)
        check("「翻譯辨識結果」可以按", str(p.ocr_translate_btn.cget("state")) == "normal")
        check("狀態列講了信心與耗時", "信心" in p.screen_status_var.get()
              and "秒" in p.screen_status_var.get(), p.screen_status_var.get())
        check("框選按鈕恢復可按", str(p.screen_btn.cget("state")) == "normal")
        # 使用者修正錯字後按翻譯 → 以改過的為準送出
        p.src_text.delete("1.0", "end")
        p.src_text.insert("1.0", "The quick brown fox jumps high")
        p._on_ocr_translate()
        check("按下翻譯送出的是使用者改過的原文",
              sent == ["The quick brown fox jumps high"], sent)
        p.destroy()
        label.destroy()
    guarded("真實流程", real_flow)

    # ===== 3. 密碼：三條路都要擋 =========================================
    def secrets():
        p = make()
        sent = spy_worker(p)
        p._show_ocr_result({"text": "password: hunter2xyz", "verdict": "ok",
                            "mean_conf": 92, "seconds": 0.2})
        check("辨識到像密碼的內容：翻譯鈕停用",
              str(p.ocr_translate_btn.cget("state")) == "disabled")
        check("被擋下來的內容仍顯示在原文框（本機朗讀、複製用）",
              "hunter2xyz" in p.src_text.get("1.0", "end-1c"))
        p._submit("password: hunter2xyz", manual=False)
        check("在原文框選字觸發的選取即翻譯也擋下密碼", sent == [], sent)
        check("擋下時有講原因", "密碼" in p.status_var.get(), p.status_var.get())
        # 先辨識出普通句子，使用者把它改成含密碼的內容再按翻譯
        p._show_ocr_result({"text": "Open the settings menu", "verdict": "ok",
                            "mean_conf": 95, "seconds": 0.2})
        p.src_text.delete("1.0", "end")
        p.src_text.insert("1.0", "token: ghp_abcdefghijklmnopqrstuvwx1234")
        p._on_ocr_translate()
        check("改過的原文像密碼：按翻譯也不送出", sent == [], sent)
        # 使用者打開自動送出時，清楚的普通句子直接送
        p.screen_settings = {"auto_send_ok": True}
        p._show_ocr_result({"text": "Open the settings menu", "verdict": "ok",
                            "mean_conf": 95, "seconds": 0.2})
        check("打開自動送出：清楚的結果直接送翻譯",
              sent == ["Open the settings menu"], sent)
        p.destroy()
    guarded("密碼", secrets)

    # ===== 4. 沒有金鑰也能看、念、複製 ===================================
    def nokey():
        p = make(key="")
        sent = spy_worker(p)
        p._show_ocr_result({"text": "Open the settings menu", "verdict": "ok",
                            "mean_conf": 95, "seconds": 0.2})
        check("沒有金鑰也看得到辨識結果",
              p.src_text.get("1.0", "end-1c") == "Open the settings menu")
        check("沒有金鑰時保留金鑰說明（不被清掉）",
              p.dst_text.get("1.0", "end-1c") == qp.C10_NOKEY_BODY)
        p._on_ocr_translate()
        check("沒有金鑰按翻譯：講原因、不送", sent == [] and
              p.status_var.get() == qp.C9_NOKEY_STATUS, p.status_var.get())
        p._copy("src")
        check("複製原文進剪貼簿", root.clipboard_get() == "Open the settings menu")
        check("自己複製的內容不會被剪貼簿監聽再翻一次",
              p._last_clip == "Open the settings menu")
        p._copy("dst")
        check("說明文字不會被當成譯文複製", p.status_var.get() == qp.C35_NOTHING_TO_COPY,
              p.status_var.get())

        launched = []

        class FakeProc:
            def __init__(self, cmd, **kw):
                launched.append(cmd)
                self.stderr = None

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return 0

        engine = {"kind": "espeak", "path": "/usr/bin/espeak-ng"}
        p._speaker = speech.Speaker(engine=engine, popen=FakeProc)
        p._speak("src")
        check("沒有金鑰也能朗讀原文", len(launched) == 1 and
              "Open the settings menu" in launched[0], launched)
        check("朗讀原文用辨識出來的語言（英文）", "en" in launched[0], launched)
        pump(0.5)
        check("念完狀態列會說念完了", p.status_var.get() == "朗讀完畢。", p.status_var.get())
        p._speak("dst")
        check("沒有譯文時朗讀譯文：講原因", p.status_var.get() == qp.C34_NOTHING_TO_SPEAK)
        p._speaker = speech.Speaker(engine=None)
        p._speak("src")
        check("沒有語音引擎：講出怎麼裝", "語音引擎" in p.status_var.get(),
              p.status_var.get())
        p.destroy()
    guarded("無金鑰", nokey)

    # ===== 5. 框選前後 ===================================================
    def capture_states():
        p = make()
        real_available = ocrengine.tesseract_available
        opened = []
        qp.ocrengine.tesseract_available = lambda: False
        real_dialog = qp.TesseractInstallDialog
        qp.TesseractInstallDialog = lambda master, **kw: opened.append(master)
        try:
            p._hide()
            p.start_screen_capture()
            check("沒裝辨識引擎：直接開安裝視窗", opened == [p], opened)
            check("沒裝辨識引擎：把面板叫出來說明", p._visible and
                  p.screen_status_var.get() == qp.C33_NEED_TESSERACT)
        finally:
            qp.ocrengine.tesseract_available = real_available
            qp.TesseractInstallDialog = real_dialog

        overlays = []

        class FakeOverlay:
            def __init__(self, master, on_select=None, on_cancel=None):
                overlays.append(self)
                self.on_cancel = on_cancel

        real_overlay = qp.RegionOverlay
        qp.RegionOverlay = FakeOverlay
        qp.ocrengine.tesseract_available = lambda: True
        try:
            p.show()
            p.start_screen_capture()
            check("框選時面板先收起來（不然會截到自己）",
                  not p._visible and len(overlays) == 1)
            check("框選中按鈕停用", str(p.screen_btn.cget("state")) == "disabled")
            p.start_screen_capture()
            check("框選中再按一次不會疊第二層", len(overlays) == 1
                  and p.screen_status_var.get() == qp.C38_OCR_BUSY)
            overlays[0].on_cancel()
            check("取消框選：按鈕恢復、講已取消", not p._ocr_busy and
                  str(p.screen_btn.cget("state")) == "normal" and
                  p.screen_status_var.get() == qp.C32_OCR_CANCELLED)
            p._hide()
            p.start_screen_capture()
            overlays[-1].on_cancel()
            check("從收起狀態（熱鍵）框選後取消：不把面板叫出來", not p._visible)
        finally:
            qp.RegionOverlay = real_overlay
            qp.ocrengine.tesseract_available = real_available

        p._ocr_id = 5
        p._ocr_busy = True
        p._ocr_queue.put(("error", 5, RuntimeError("截不到畫面，請再試一次")))
        p._poll_ocr()
        check("截圖／辨識失敗：原因寫在狀態列",
              "截不到畫面" in p.screen_status_var.get(), p.screen_status_var.get())
        p.destroy()
    guarded("框選前後", capture_states)

    # ===== 6. 熱鍵 =======================================================
    def hotkeys():
        p = make()
        fired = []
        p.start_screen_capture = lambda: fired.append(1)
        p.hotkey_var.set(True)
        p._on_hotkey_toggle()
        check("非 Windows：熱鍵退回本程式視窗內",
              p._hotkey.status == "window-only", p._hotkey.status)
        check("熱鍵狀態寫在面板上", "Ctrl+Alt+F8" in p.screen_status_var.get(),
              p.screen_status_var.get())
        check("熱鍵開關存進設定", p.config_data["hotkey"]["enabled"] is True)
        p.focus_force()
        pump(0.1)
        p.event_generate("<Control-Alt-KeyPress-F8>", when="tail")
        pump(0.2)
        check("按下熱鍵真的開始框選", fired == [1], fired)
        p.hotkey_var.set(False)
        p._on_hotkey_toggle()
        check("關掉熱鍵：解除綁定", root.bind_all("<Control-Alt-KeyPress-F8>") == "",
              root.bind_all("<Control-Alt-KeyPress-F8>"))
        check("關掉熱鍵存進設定", p.config_data["hotkey"]["enabled"] is False)
        p.destroy()

        p = qp.QuickTranslatePanel(
            root, {"transcription": {"api_key": ""}, "hotkey": {"enabled": True}},
            start_hidden=True)
        pump(0.2)
        check("背景建立的面板不顯示", not p._visible and not p.winfo_viewable())
        check("背景建立的面板熱鍵已啟用", p._hotkey is not None and
              p._hotkey.status == "window-only")
        p.destroy()
        check("面板銷毀時熱鍵一起解除", root.bind_all("<Control-Alt-KeyPress-F8>") == "")
    guarded("熱鍵", hotkeys)

    # ===== 7. 主程式啟動時建面板 =========================================
    def app_start():
        import gui.app as app
        made = []
        real = app.QuickTranslatePanel
        app.QuickTranslatePanel = lambda master, cfg, **kw: made.append(kw) or "panel"
        try:
            fake = types.SimpleNamespace(config_data={"hotkey": {"enabled": False}})
            app.SrtApp._maybe_start_hotkey(fake)
            check("熱鍵沒開：啟動時不建面板", made == [])
            fake.config_data = {"hotkey": {"enabled": True}}
            app.SrtApp._maybe_start_hotkey(fake)
            check("熱鍵有開：啟動時在背景建面板", made == [{"start_hidden": True}], made)
            app.SrtApp._maybe_start_hotkey(fake)
            check("已經建過就不重建", len(made) == 1)
        finally:
            app.QuickTranslatePanel = real
    guarded("主程式", app_start)

    root.destroy()

if failures:
    print(f"\n{len(failures)} 項失敗：")
    for name in failures:
        print(" -", name)
    sys.exit(1)
print("\n查譯面板螢幕翻譯介面測試全數通過。")
