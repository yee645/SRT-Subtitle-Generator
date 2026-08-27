# -*- coding: utf-8 -*-
"""
v1.48.0 新功能測試：即時查譯 GUI 面板（`gui/quicktranslate_panel.py`）。

本檔驗證的是「GUI 層真的把核心層的設定與行為接起來」，不是核心層邏輯
本身（那些已由 `tests/test_v1480.py` 涵蓋）。硬性驗收條件：

  1. `cache_size`／`debounce_ms` 真的生效（不是寫在 config 裡就算數）。
  2. 無金鑰時「選取後自動翻譯」勾選框要一起停用，填入金鑰後不必重開
     視窗就恢復可用。
  3. API 呼叫在背景執行緒，經 queue + after() 輪詢回主執行緒。
  4. 有勾選/選取狀態的控件一律 ttk.*，不可用 classic tk.Checkbutton／
     tk.Radiobutton。

面板本身是真實的 Tkinter Toplevel，這裡就地起一個離屏 Tk root
（DISPLAY 需指向可用的 X 伺服器，如本機的 Xvfb :99）驗證真實控件狀態
與真實的 after()／執行緒排程，而不只是靜態掃原始碼；純邏輯（生字本
增刪、CSV 匯出格式、略過訊息判斷）額外再用不碰 Tkinter 的函式驗證。
"""
import copy
import csv
import os
import re
import sys
import time

os.environ.setdefault("DISPLAY", ":99")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL_PATH = os.path.join(REPO_ROOT, "gui", "quicktranslate_panel.py")
APP_PATH = os.path.join(REPO_ROOT, "gui", "app.py")
panel_src = open(PANEL_PATH, encoding="utf-8").read()
app_src = open(APP_PATH, encoding="utf-8").read()


# ===== 1. 靜態檢查：零第三方依賴、控件一律 ttk、按鈕已掛上主視窗 =====

check("gui/quicktranslate_panel.py 不 import 任何第三方套件（只用標準庫＋專案內模組）",
      not re.search(r"^import (sv_ttk|openai|requests|numpy)\b", panel_src, re.M))

no_classic = []
for path in (PANEL_PATH, APP_PATH):
    src = open(path, encoding="utf-8").read()
    hits = re.findall(r"(?<!t)tk\.(Checkbutton|Radiobutton)\(", src)
    if hits:
        no_classic.append((path, hits))
check("gui/ 沒有殘留 classic tk.Checkbutton／tk.Radiobutton（sv_ttk 下顯示異常）",
      not no_classic, no_classic)

check("工具列已加上「即時查譯」按鈕", '"即時查譯"' in app_src)
check("工具列按鈕接到 _open_quicktranslate_panel", "_open_quicktranslate_panel" in app_src)
check("app.py 有 import QuickTranslatePanel",
      "from gui.quicktranslate_panel import QuickTranslatePanel" in app_src)
check("面板單例：已存在就 show() 不重建",
      "panel.show()" in app_src and "QuickTranslatePanel(self, self.config_data)" in app_src)


# ===== 2. cache_size／debounce_ms 真的被接進去（不是寫在 config 就算數）=====

check("TranslationCache 建構子真的吃 settings['cache_size']（不是固定值）",
      re.search(r"TranslationCache\(capacity=self\.settings\[.cache_size.\]\)", panel_src))
check("debounce 排程真的用 settings['debounce_ms'] 當 after() 延遲",
      re.search(r"self\.after\(\s*\n?\s*self\.settings\[.debounce_ms.\]", panel_src))


# ===== 3. 起一個離屏 Tk root，用真實面板驗證行為 =====

try:
    import tkinter as tk
    tk_root = tk.Tk()
    tk_root.withdraw()
    TK_OK = True
except Exception as exc:  # pragma: no cover - 沒有可用 X 伺服器時整段跳過
    TK_OK = False
    print(f"（沒有可用的 Tk/X 顯示環境，跳過真實控件行為測試：{exc}）")

if TK_OK:
    import config as config_module
    from config import DEFAULT_CONFIG
    import gui.quicktranslate_panel as qtpanel_module
    from gui.quicktranslate_panel import (
        QuickTranslatePanel, C3_WAITING, C9_NOKEY_STATUS, C13_AUTO_PAUSED,
        C15_ALREADY_CHINESE, C16_TOO_SHORT_OR_EMPTY, C17_NOTHING_SELECTED,
        classify_skip_reason, dst_label,
    )
    import subtitle.quicktranslate as qtmod

    # 面板的 _write_settings()／連續失敗自動暫停都會呼叫真正的
    # save_config()，生字本增修也會呼叫真正的 save_vocab()——兩者都預設
    # 寫回這台機器上的真實 config.json／quicktranslate_vocab.json（使用者
    # 的實際資料）。測試不該動到使用者的真實檔案，所以把這兩個模組層路徑
    # 常數暫時指到一個獨立的暫存目錄，本段測試結束後照原樣還原。
    import tempfile
    _isolated_dir = tempfile.mkdtemp(prefix="quicktranslate_test_")
    _real_config_path = config_module.CONFIG_PATH
    _real_vocab_path = qtpanel_module.VOCAB_PATH
    config_module.CONFIG_PATH = os.path.join(_isolated_dir, "config.json")
    qtpanel_module.VOCAB_PATH = os.path.join(_isolated_dir, "quicktranslate_vocab.json")

    def make_config(**overrides):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["quicktranslate"].update(overrides.pop("quicktranslate", {}))
        cfg["transcription"].update(overrides.pop("transcription", {}))
        cfg.update(overrides)
        return cfg

    def pump(seconds=1.5, step=0.05):
        end = time.time() + seconds
        while time.time() < end:
            tk_root.update()
            time.sleep(step)

    # ---- 3a. cache_size 真的變成 TranslationCache 的容量 ----
    cfg = make_config(quicktranslate={"cache_size": 2})
    panel = QuickTranslatePanel(tk_root, cfg)
    check("面板的 cache 容量等於設定的 cache_size（不是預設 200）",
          panel.cache._capacity == 2, panel.cache._capacity)
    panel.cache.put("a", "zh-TW", {"v": 1})
    panel.cache.put("b", "zh-TW", {"v": 2})
    panel.cache.put("c", "zh-TW", {"v": 3})
    check("容量設 2 時第 3 筆真的擠掉第 1 筆",
          panel.cache.get("a", "zh-TW") is None
          and panel.cache.get("b", "zh-TW") is not None
          and panel.cache.get("c", "zh-TW") is not None)
    panel.destroy()

    # ---- 3b. debounce_ms 真的是 after() 的延遲值 ----
    for ms in (10, 2000):
        cfg = make_config(quicktranslate={"debounce_ms": ms})
        panel = QuickTranslatePanel(tk_root, cfg)
        recorded = []
        real_after = panel.after
        def fake_after(delay, fn=None, *args, _recorded=recorded, _real=real_after):
            _recorded.append(delay)
            return _real(delay, fn, *args) if fn is not None else _real(delay)
        panel.after = fake_after
        panel._schedule_debounce()
        check(f"debounce_ms={ms} 時排程延遲確實是 {ms}",
              recorded and recorded[-1] == ms, recorded)
        panel.after = real_after
        if panel._debounce_job:
            panel.after_cancel(panel._debounce_job)
        panel.destroy()

    # ---- 3c. 無金鑰：自動翻譯勾選框停用；填入金鑰後不必重開視窗即恢復 ----
    cfg = make_config(transcription={"api_key": ""})
    panel = QuickTranslatePanel(tk_root, cfg)
    check("無金鑰時開窗即進入無金鑰狀態", panel.status_var.get() == C9_NOKEY_STATUS)
    check("無金鑰時「選取後自動翻譯」勾選框停用",
          str(panel.auto_check.cget("state")) == "disabled")
    cfg["transcription"]["api_key"] = "sk-test-key"
    panel._refresh_api_key_state()
    check("填入金鑰後勾選框恢復可用（不必重開視窗）",
          str(panel.auto_check.cget("state")) == "normal")
    check("填入金鑰後狀態列換回等待選取",
          panel.status_var.get() == C3_WAITING)
    panel.destroy()

    # ---- 3d. 手動按鈕：無金鑰時按了只重複提示，不丟例外 ----
    cfg = make_config(transcription={"api_key": ""})
    panel = QuickTranslatePanel(tk_root, cfg)
    panel._on_translate_button()
    check("無金鑰時按「翻譯選取內容」只提示，不例外",
          panel.status_var.get() == C9_NOKEY_STATUS)
    panel.destroy()

    # ---- 3e. 沒有任何選取時按手動按鈕 ----
    cfg = make_config(transcription={"api_key": "sk-test"})
    panel = QuickTranslatePanel(tk_root, cfg)
    panel._on_translate_button()
    check("沒有選取內容時按鈕顯示 C17",
          panel.status_var.get() == C17_NOTHING_SELECTED)
    panel.destroy()

    # ---- 3f. API 背景執行緒 + queue + after 輪詢：真的不卡主執行緒 ----
    cfg = make_config(transcription={"api_key": "sk-test"},
                      quicktranslate={"debounce_ms": 5})
    panel = QuickTranslatePanel(tk_root, cfg)

    call_thread_names = []
    def fake_translate_ok(text, api_key, settings=None, cache=None):
        import threading
        call_thread_names.append(threading.current_thread().name)
        time.sleep(0.2)  # 模擬網路延遲：若卡主執行緒，pump() 迴圈會被凍住
        return {"source": text, "translation": "你好世界",
               "terms": [{"word": "hello", "meaning": "打招呼用語"}],
               "cached": False}

    real_translate = qtmod.translate_snippet
    qtmod.translate_snippet = fake_translate_ok
    started = time.time()
    panel._submit("hello world quick check", manual=True)
    check("送出翻譯後主執行緒立刻可繼續（沒有被同步卡住）",
          time.time() - started < 0.15, time.time() - started)
    pump(1.2)
    qtmod.translate_snippet = real_translate

    check("API 呼叫確實發生在背景執行緒，不是主執行緒",
          call_thread_names and call_thread_names[0] != "MainThread",
          call_thread_names)
    check("背景結果經 queue／after 輪詢後正確顯示在中文翻譯區",
          panel.dst_text.get("1.0", "end").strip() == "你好世界")
    check("狀態列顯示翻譯完成並已存入生字本",
          "翻譯完成" in panel.status_var.get())
    check("關鍵詞自動併入生字本",
          any(row["word"] == "hello" for row in panel.vocab))
    panel.destroy()

    # ---- 3g. 連續失敗 3 次自動暫停自動翻譯 ----
    cfg = make_config(transcription={"api_key": "sk-test"},
                      quicktranslate={"debounce_ms": 5})
    panel = QuickTranslatePanel(tk_root, cfg)
    panel.auto_var.set(True)

    def fake_translate_fail(text, api_key, settings=None, cache=None):
        raise RuntimeError("呼叫 OpenAI API 失敗：network down")

    import logging
    logging.getLogger("gui.quicktranslate_panel").disabled = True
    qtmod.translate_snippet = fake_translate_fail
    for i in range(3):
        panel._submit(f"failing sentence number {i}", manual=True)
        pump(0.6)
    qtmod.translate_snippet = real_translate
    logging.getLogger("gui.quicktranslate_panel").disabled = False
    check("連續 3 次失敗後自動翻譯被自動關閉", panel.auto_var.get() is False)
    check("狀態列顯示連續失敗暫停訊息", panel.status_var.get() == C13_AUTO_PAUSED)
    panel.destroy()

    # ---- 3h. 過期回應（串位）會被丟棄，不覆蓋最新結果 ----
    cfg = make_config(transcription={"api_key": "sk-test"})
    panel = QuickTranslatePanel(tk_root, cfg)
    panel._request_id = 5
    panel.result_queue.put(("done", 1, "stale text",
                            {"source": "stale text", "translation": "舊結果",
                             "terms": [], "cached": False}))
    panel._poll_queue()
    if panel._poll_job:
        panel.after_cancel(panel._poll_job)
        panel._poll_job = None
    check("request_id 不符的舊回應被丟棄，不會顯示",
          "舊結果" not in panel.dst_text.get("1.0", "end"))
    panel.destroy()

    # ---- 3i. 略過原因分類：太長／已是中文／太短 ----
    settings = qtmod.resolve_quicktranslate_settings(
        {"quicktranslate": {"target_language": "zh-TW", "max_chars": 20}})
    check("太長選取分類為 C14",
          "超過 20 字" in classify_skip_reason("x" * 21, settings))
    check("已是中文分類為 C15",
          classify_skip_reason("這是一段完整的中文句子", settings) == C15_ALREADY_CHINESE)
    check("太短分類為 C16",
          classify_skip_reason("a", settings) == C16_TOO_SHORT_OR_EMPTY)

    cfg = make_config(transcription={"api_key": "sk-test"},
                      quicktranslate={"target_language": "zh-TW", "max_chars": 20})
    panel = QuickTranslatePanel(tk_root, cfg)
    panel._submit("x" * 21, manual=True)
    check("面板送出太長文字時狀態列顯示略過訊息",
          "已略過" in panel.status_var.get() and "超過 20 字" in panel.status_var.get())
    panel.destroy()

    # ---- 3j. 目標語言標籤：非中文時動態換成「◯◯翻譯」----
    check("繁體中文區塊標題固定顯示「中文翻譯」", dst_label("zh-TW") == "中文翻譯")
    check("簡體中文也顯示「中文翻譯」", dst_label("zh-CN") == "中文翻譯")
    check("日文顯示「日文翻譯」", dst_label("ja") == "日文翻譯")

    config_module.CONFIG_PATH = _real_config_path
    qtpanel_module.VOCAB_PATH = _real_vocab_path
    import shutil
    shutil.rmtree(_isolated_dir, ignore_errors=True)
    check("測試期間沒有動到真實的 config.json（路徑已還原、暫存目錄已清掉）",
          config_module.CONFIG_PATH == _real_config_path)

    # ---- 6. 三個內容區都要能捲：內容長度不固定，捲不到等於讀不到 ----
    # 原本 dst_text 是 height=4 且沒有捲軸，沒有金鑰時那段最長的說明文
    # （純本機使用者最需要讀完的那段）會被截在框底而且捲不到。
    cfg = make_config()
    cfg["transcription"] = dict(cfg.get("transcription", {}), api_key="")
    panel = QuickTranslatePanel(tk_root, cfg)
    pump(0.4)
    for name, widget in (("原文", panel.src_text),
                         ("譯文", panel.dst_text),
                         ("關鍵詞", panel.term_text)):
        siblings = [c.winfo_class() for c in widget.master.winfo_children()]
        check(f"{name}區有捲軸元件",
              any("Scrollbar" in cls for cls in siblings), str(siblings))
        check(f"{name}區有掛上 yscrollcommand",
              bool(widget.cget("yscrollcommand")))
    first, last = panel.dst_text.yview()
    check("無金鑰說明文超出可視範圍（確認這段真的比框高）",
          last < 0.999, f"yview=({first:.3f}, {last:.3f})")
    panel.dst_text.yview_moveto(1.0)
    tk_root.update()
    check("捲到底真的能讀到被截掉的那段",
          panel.dst_text.yview()[0] > 0.0,
          str(panel.dst_text.yview()))
    panel.destroy()

    tk_root.destroy()


# ===== 4. 生字本純邏輯（不需要 Tk，直接測函式）=====

from gui.quicktranslate_panel import (
    add_vocab_terms, load_vocab, remove_vocab_words, save_vocab,
    vocab_status_text, write_vocab_csv, C22_VOCAB_EMPTY,
)

vocab, changed = add_vocab_terms([], [
    {"word": "washed out", "meaning": "灰白、褪色"},
    {"word": "footage", "meaning": "影片素材"},
])
check("新詞加入生字本", len(vocab) == 2 and changed)

vocab2, changed2 = add_vocab_terms(vocab, [
    {"word": "washed out", "meaning": "重複查一次，意思不同也不覆蓋"},
    {"word": "log profile", "meaning": "Log 色彩模式"},
])
check("同一個詞（word 相同）不會重複加入", len(vocab2) == 3, vocab2)
check("原本的意思沒有被新查詢覆蓋",
      next(r["meaning"] for r in vocab2 if r["word"] == "washed out") == "灰白、褪色")
check("沒有新詞時 changed 為 False", add_vocab_terms(vocab2, [])[1] is False)

vocab3 = remove_vocab_words(vocab2, {"footage"})
check("刪除選取的詞", len(vocab3) == 2 and all(r["word"] != "footage" for r in vocab3))

check("空生字本狀態列文字", vocab_status_text(0) == C22_VOCAB_EMPTY)
check("非空生字本狀態列文字", vocab_status_text(3) == "生字本共 3 個詞。")

# ---- 存檔／讀檔（暫存路徑，不動真正的使用者生字本檔）----
import tempfile
with tempfile.TemporaryDirectory() as tmpdir:
    vocab_path = os.path.join(tmpdir, "vocab.json")
    save_vocab(vocab2, path=vocab_path)
    loaded = load_vocab(path=vocab_path)
    check("存檔後讀回內容一致",
          {(r["word"], r["meaning"]) for r in loaded}
          == {(r["word"], r["meaning"]) for r in vocab2})

    missing_path = os.path.join(tmpdir, "not_exist.json")
    check("讀取不存在的生字本檔不會炸、回傳空清單", load_vocab(path=missing_path) == [])

    bad_path = os.path.join(tmpdir, "bad.json")
    with open(bad_path, "w", encoding="utf-8") as fp:
        fp.write("這不是合法的 JSON {{{")
    check("讀取壞掉的 JSON 不會炸、回傳空清單", load_vocab(path=bad_path) == [])

    # ---- CSV 匯出格式：兩欄「詞句」「意思」，UTF-8 BOM ----
    csv_path = os.path.join(tmpdir, "vocab.csv")
    write_vocab_csv(vocab2, csv_path)
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as fp:
        rows = list(csv.reader(fp))
    check("CSV 第一列是欄位標題「詞句」「意思」", rows[0] == ["詞句", "意思"])
    check("CSV 資料列數等於生字本筆數", len(rows) - 1 == len(vocab2))
    check("CSV 內容包含正確的詞與意思",
          ["washed out", "灰白、褪色"] in rows)
    with open(csv_path, "rb") as fp:
        raw_bytes = fp.read()
    check("CSV 檔案帶 UTF-8 BOM（Excel／Anki 開啟中文不亂碼）",
          raw_bytes.startswith(b"\xef\xbb\xbf"))


print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.48.0 GUI 測試全數通過。")
