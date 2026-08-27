# -*- coding: utf-8 -*-
"""
即時查譯浮動視窗：在本程式任何文字框選取一段外文，鬆開滑鼠即翻譯。

面板長在哪、觸發時機、文案全數依照設計文件定案（見 PR / 專案內
`docs/ROADMAP_2.0.md`），本檔只是把 `subtitle/quicktranslate.py` 那個
純邏輯層接到 Tkinter：

- 監聽 `bind_all("<<Selection>>")`，但去抖動到期時若滑鼠左鍵仍按著
  （使用者可能還在拖曳中途停下來讀字），改成等 `<ButtonRelease-1>`
  之後才重新排一次去抖動，避免「拖到一半停下來看」被誤判成選完了。
- API 呼叫在背景執行緒進行，結果經 `queue.Queue` 由 `after()` 輪詢
  拿回主執行緒——Tkinter 不是執行緒安全的，不能在背景執行緒直接碰
  任何 widget（作法比照 `gui/subtitle_check_dialog.py`）。
- `settings["cache_size"]` 真的餵進 `TranslationCache(capacity=...)`、
  `settings["debounce_ms"]` 真的是 `after()` 的延遲——這兩個設定在
  `subtitle/quicktranslate.py` 本身是不會自己生效的純資料，串接起來
  是本檔的責任。
- 沒有 API 金鑰時「選取後自動翻譯」勾選框本身要停用（`state=
  "disabled"`），不是勾著卻按了沒反應；金鑰是每次要打 API 前才重讀
  （`config_data["transcription"]["api_key"]`），使用者回主視窗貼上
  金鑰後不必重開這個視窗，下一輪輪詢就會自動恢復可用。
- 生字本與 CSV 匯出的純邏輯（載入、存檔、去重合併、寫檔格式）都寫成
  不碰 Tkinter 的模組層函式，方便測試檔在沒有視窗的情況下也能驗證。

視窗關閉＝隱藏（`withdraw`），不銷毀：快取與生字本都留著，工具列按鈕
再按一次原地復原。
"""

from __future__ import annotations

import csv
import json
import logging
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from config import CONFIG_PATH, save_config
from subtitle import quicktranslate as qt
from subtitle.punctstyle import cjk_ratio
from subtitle.translator import LANGUAGE_LABELS

logger = logging.getLogger(__name__)

_LANGUAGE_CODES_BY_LABEL = {label: code for code, label in LANGUAGE_LABELS.items()}
_CHINESE_CODES = ("zh-TW", "zh-CN")

HINT_FG = "#666666"
STATUS_FG = "#1a5fb4"

# 生字本存檔路徑：放在 config.json 旁邊（本機保存，不進 git）。
VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(CONFIG_PATH)) or ".",
    "quicktranslate_vocab.json")

_CONSECUTIVE_FAILURE_LIMIT = 3
_POLL_MS = 150

# ---------------------------------------------------------------------------
# 文案（對照設計文件的 C1~C22 編號，方便日後對照修改）。

C1_HINT = ("在逐字稿或字幕編輯框裡選取一段外文，鬆開滑鼠就自動翻譯。"
           "每次翻譯呼叫一次 OpenAI API（會計費，短句約千分之一美元）；"
           "同樣的字句直接用快取，不重複計費。")
C2_INITIAL = ("還沒有查過任何內容。到主視窗的逐字稿、或雙擊字幕清單開啟的"
              "編輯框裡，用滑鼠選取一段外文試試。也可以先點字幕清單的某一"
              "列，再按「翻譯選取內容」。")
C3_WAITING = "等待選取。"
C4_LOADING = "翻譯中…（通常 1～2 秒，視 OpenAI 回應速度）"
C5_DONE_SAVED = "翻譯完成。查過的詞已存入生字本。"
C5_DONE = "翻譯完成。"
C5_CACHED = "翻譯完成（快取結果，這次不計費）。"
C6_EXPLAIN_OFF = ("已關閉關鍵詞解說。勾選「附關鍵詞解說」後，下一次查譯會"
                   "一併標出值得學的詞（同一次呼叫順帶回傳，不另外計費）。")
C7_NO_TERMS = "這段文字太短或太簡單，這次沒有值得特別解說的詞。"
C9_NOKEY_STATUS = "尚未填入 OpenAI API 金鑰，選取暫時不會觸發翻譯。"
C10_NOKEY_BODY = (
    "即時查譯需要連網呼叫 OpenAI API。你目前用的是純本機 Whisper 流程、"
    "沒有填過 API 金鑰，所以這個功能還不能用。\n\n"
    "想啟用：到 platform.openai.com 申請金鑰，回主視窗「轉寫設定」的"
    "「API 金鑰」欄位貼上即可，不必勾選「改用 OpenAI API」。查譯用的是"
    "最便宜的文字模型，選一句話約千分之一美元。")
C13_AUTO_PAUSED = ("連續 3 次翻譯失敗，已先暫停自動翻譯，避免每選一次就"
                    "失敗一次。問題排除後重新勾選「選取後自動翻譯」即可。")
C15_ALREADY_CHINESE = "已略過：選取內容已是中文。"
C16_TOO_SHORT_OR_EMPTY = "已略過：選取內容太短或沒有可翻的文字。"
C17_NOTHING_SELECTED = ("沒有選取內容。先選取一段文字，或點字幕清單的一列"
                         "再按此鈕。")
C18_VOCAB_HINT = ("查譯時的關鍵詞會自動收進這裡（本機保存，不佔 API 費用）。"
                   "匯出的 CSV 前欄是詞、後欄是意思，可直接匯入 Anki 做"
                   "記憶卡。")
C21_CLEAR_TITLE = "清空生字本"
C22_VOCAB_EMPTY = "生字本還是空的。查譯幾句附關鍵詞的外文，就會自動收詞進來。"


def C14_TOO_LONG(max_chars: int) -> str:
    return (f"已略過：選取超過 {max_chars} 字"
            "（快速查譯是查詞句用的，整批翻譯請用「翻譯字幕」）。")


def C20_EXPORTED(n: int, path: str) -> str:
    return f"已匯出 {n} 個詞到 {path}。"


def vocab_status_text(n: int) -> str:
    return f"生字本共 {n} 個詞。" if n else C22_VOCAB_EMPTY


def dst_label(target_language: str) -> str:
    """『中文翻譯』區塊標題：目標語言非中文時動態換成「◯◯翻譯」。"""
    if target_language in _CHINESE_CODES:
        return "中文翻譯"
    return f"{LANGUAGE_LABELS.get(target_language, target_language)}翻譯"


def classify_skip_reason(source: str, settings: dict) -> str:
    """
    `looks_translatable()` 回傳 False 時，判斷該顯示哪一句略過訊息。

    只在已知 `not looks_translatable(source, settings)` 的前提下呼叫；
    判斷順序與 `looks_translatable` 內部一致（太長 → 已是中文 → 其餘
    歸類為「太短或沒有可翻的文字」，涵蓋太短與純數字/純標點兩種情況，
    設計文件的 C16 本來就是同一句文案，不必細分）。
    """
    length = len(source)
    if length > settings["max_chars"]:
        return C14_TOO_LONG(settings["max_chars"])
    target = settings.get("target_language", "")
    if (length >= settings["min_chars"] and target.startswith("zh")
            and cjk_ratio(source) >= 0.15):
        return C15_ALREADY_CHINESE
    return C16_TOO_SHORT_OR_EMPTY


# ---------------------------------------------------------------------------
# 生字本：純邏輯（不碰 Tkinter），方便測試檔直接呼叫。

def load_vocab(path: Optional[str] = None) -> list:
    """讀取生字本 JSON；檔案不存在或壞掉一律回傳空清單，不丟例外。"""
    # path 預設用 None 而不是直接把 VOCAB_PATH 當參數預設值：後者在函式
    # 定義當下就會被綁死，日後（例如測試）改指派模組層的 VOCAB_PATH 也
    # 不會反映到這裡；改成呼叫當下才查一次，行為才會跟著模組層的值走。
    path = path or VOCAB_PATH
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [dict(word=str(row["word"]), meaning=str(row["meaning"]))
            for row in data
            if isinstance(row, dict) and row.get("word") and row.get("meaning")]


def save_vocab(vocab: list, path: Optional[str] = None) -> None:
    path = path or VOCAB_PATH
    try:
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(vocab, fp, ensure_ascii=False, indent=2)
    except OSError:
        logger.warning("生字本存檔失敗：%s", path)


def add_vocab_terms(vocab: list, terms: list) -> tuple:
    """
    把關鍵詞併入生字本，回傳 `(新清單, 是否有變動)`。

    同一個詞（完全相同字串）只留第一次查到的意思，避免使用者反覆查
    同一個詞時生字本被灌成一長串重複列。
    """
    existing = {row["word"] for row in vocab}
    merged = list(vocab)
    changed = False
    for term in terms or []:
        word = str(term.get("word") or "").strip()
        meaning = str(term.get("meaning") or "").strip()
        if not word or not meaning or word in existing:
            continue
        merged.append({"word": word, "meaning": meaning})
        existing.add(word)
        changed = True
    return merged, changed


def remove_vocab_words(vocab: list, words) -> list:
    """回傳移除指定詞句之後的生字本清單（`words` 為要刪除的詞句集合）。"""
    drop = set(words)
    return [row for row in vocab if row["word"] not in drop]


def write_vocab_csv(vocab: list, path: str) -> None:
    """匯出生字本 CSV（UTF-8 BOM，Excel 與 Anki 皆可直接匯入）。"""
    with open(path, "w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(["詞句", "意思"])
        for row in vocab:
            writer.writerow([row["word"], row["meaning"]])


# ---------------------------------------------------------------------------

def _scrolled_text(parent, height):
    """
    帶垂直捲軸的唯讀文字區。

    三個內容區的長度都不固定：長段落的譯文、關鍵詞清單、以及沒有金鑰時
    那段最長的說明文，都會超過固定行高。沒有捲軸的話超出的部分不只看不
    到、還捲不到——無金鑰說明正是純本機使用者最需要讀完的那段字。
    """
    holder = ttk.Frame(parent)
    holder.pack(fill="both", expand=True)
    widget = tk.Text(holder, height=height, wrap="word",
                     relief="flat", highlightthickness=0)
    bar = ttk.Scrollbar(holder, orient="vertical", command=widget.yview)
    widget.configure(yscrollcommand=bar.set)
    # 捲軸要先 pack：pack() 是按呼叫順序分配版面，若 fill+expand 的文字
    # 區先佔走整個 holder，之後才 pack 的捲軸會被擠成 1px 寬、實質上不會
    # 顯示（實測 winfo_ismapped() 是 0）。捲軸（固定寬度）先佔好右側欄
    # 位，文字區（fill+expand）再吃剩下的空間，才會兩者都正常顯示。
    bar.pack(side="right", fill="y")
    widget.pack(side="left", fill="both", expand=True)
    return widget

class QuickTranslatePanel(tk.Toplevel):
    """即時查譯浮動視窗（獨立 Toplevel，可置頂，關閉即隱藏）。"""

    def __init__(self, master, config_data: dict):
        super().__init__(master)
        self.config_data = config_data
        self.settings = qt.resolve_quicktranslate_settings(config_data)
        # cache_size 真的餵進容量——這是硬性驗收條件，不是寫在 config
        # 裡就算數。
        self.cache = qt.TranslationCache(capacity=self.settings["cache_size"])
        self.result_queue: "queue.Queue" = queue.Queue()

        self.vocab = load_vocab()

        self._visible = False
        self._poll_job = None
        self._debounce_job = None
        self._button1_down = False
        self._pending_after_release = False
        self._request_id = 0
        self._last_success_source = None
        self._consecutive_failures = 0
        self._had_key = None          # None＝尚未檢查過，強制第一次一定套用
        self._in_nokey_state = False

        self.title("即時查譯（選字即翻）")
        self.geometry("520x600")
        self.minsize(480, 560)
        self.transient(master)

        raw_prefs = config_data.get("quicktranslate") or {}
        self.auto_var = tk.BooleanVar(value=bool(raw_prefs.get("auto_translate", True)))
        self.explain_var = tk.BooleanVar(value=self.settings["explain"])
        self.save_vocab_var = tk.BooleanVar(value=bool(raw_prefs.get("save_to_vocab", True)))
        self.topmost_var = tk.BooleanVar(value=bool(raw_prefs.get("topmost", True)))

        self._build_ui()
        self.attributes("-topmost", bool(self.topmost_var.get()))

        self.bind_all("<<Selection>>", self._on_selection_event, add="+")
        self.bind_all("<ButtonPress-1>", self._on_button1_press, add="+")
        self.bind_all("<ButtonRelease-1>", self._on_button1_release, add="+")
        self.protocol("WM_DELETE_WINDOW", self._hide)

        self._refresh_api_key_state(force=True)
        self._refresh_vocab_tree()
        self.show()

    # ------------------------------------------------------------------
    # 版面
    def _build_ui(self):
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(body, foreground=HINT_FG, justify="left", wraplength=492,
                  text=C1_HINT).pack(anchor="w", pady=(0, 8))

        self.notebook = ttk.Notebook(body)
        self.notebook.pack(fill="both", expand=True)

        self._build_translate_page()
        self._build_vocab_page()

    def _build_translate_page(self):
        page = ttk.Frame(self.notebook, padding=(8, 8))
        self.notebook.add(page, text="查譯")

        self.src_frame = ttk.LabelFrame(page, text="原文", padding=(8, 4))
        self.src_frame.pack(fill="x")
        self.src_text = _scrolled_text(self.src_frame, 3)

        self.dst_frame = ttk.LabelFrame(
            page, text=dst_label(self.settings["target_language"]),
            padding=(8, 4))
        self.dst_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.dst_text = _scrolled_text(self.dst_frame, 4)

        term_frame = ttk.LabelFrame(page, text="值得學的關鍵詞", padding=(8, 4))
        term_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.term_text = _scrolled_text(term_frame, 4)

        self.status_var = tk.StringVar(value=C3_WAITING)
        ttk.Label(page, textvariable=self.status_var, foreground=STATUS_FG,
                  wraplength=460, justify="left").pack(anchor="w", pady=(6, 4))

        ctrl1 = ttk.Frame(page)
        ctrl1.pack(fill="x", pady=(0, 2))
        self.translate_btn = ttk.Button(
            ctrl1, text="翻譯選取內容", width=14, command=self._on_translate_button)
        self.translate_btn.pack(side="left")
        self.auto_check = ttk.Checkbutton(
            ctrl1, text="選取後自動翻譯", variable=self.auto_var,
            command=self._write_settings)
        self.auto_check.pack(side="left", padx=(10, 0))
        ttk.Checkbutton(ctrl1, text="附關鍵詞解說", variable=self.explain_var,
                        command=self._write_settings).pack(
            side="left", padx=(10, 0))

        ctrl2 = ttk.Frame(page)
        ctrl2.pack(fill="x", pady=(4, 0))
        ttk.Label(ctrl2, text="翻譯成:").pack(side="left")
        current_label = LANGUAGE_LABELS.get(
            self.settings["target_language"], LANGUAGE_LABELS["zh-TW"])
        self.language_var = tk.StringVar(value=current_label)
        language_combo = ttk.Combobox(
            ctrl2, textvariable=self.language_var, state="readonly", width=10,
            values=list(LANGUAGE_LABELS.values()))
        language_combo.pack(side="left", padx=(4, 0))
        language_combo.bind("<<ComboboxSelected>>", self._on_language_changed)
        ttk.Checkbutton(ctrl2, text="查過的存入生字本",
                        variable=self.save_vocab_var,
                        command=self._write_settings).pack(
            side="left", padx=(10, 0))
        ttk.Checkbutton(ctrl2, text="視窗置頂", variable=self.topmost_var,
                        command=self._on_topmost_toggle).pack(
            side="left", padx=(10, 0))

        self._set_text(self.dst_text, C2_INITIAL)

    def _build_vocab_page(self):
        page = ttk.Frame(self.notebook, padding=(8, 8))
        self.notebook.add(page, text="生字本")

        ttk.Label(page, foreground=HINT_FG, justify="left", wraplength=460,
                  text=C18_VOCAB_HINT).pack(anchor="w", pady=(0, 6))

        tree_frame = ttk.Frame(page)
        tree_frame.pack(fill="both", expand=True)
        self.vocab_tree = ttk.Treeview(
            tree_frame, columns=("word", "meaning"), show="headings")
        self.vocab_tree.heading("word", text="詞句")
        self.vocab_tree.heading("meaning", text="意思")
        self.vocab_tree.column("word", width=130, anchor="w")
        self.vocab_tree.column("meaning", width=240, anchor="w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical",
                            command=self.vocab_tree.yview)
        self.vocab_tree.configure(yscrollcommand=vsb.set)
        self.vocab_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        vbtns = ttk.Frame(page)
        vbtns.pack(fill="x", pady=(8, 0))
        ttk.Button(vbtns, text="匯出 CSV...", width=12,
                  command=self._on_vocab_export).pack(side="left")
        ttk.Button(vbtns, text="刪除選取", width=10,
                  command=self._on_vocab_delete).pack(side="left", padx=(8, 0))
        ttk.Button(vbtns, text="清空生字本", width=10,
                  command=self._on_vocab_clear).pack(side="left", padx=(8, 0))

        self.vocab_status_var = tk.StringVar(value=vocab_status_text(0))
        ttk.Label(page, textvariable=self.vocab_status_var,
                  foreground=STATUS_FG).pack(anchor="w", pady=(6, 0))

    # ------------------------------------------------------------------
    # 顯示 / 隱藏（關閉＝隱藏，保留快取與生字本）
    def show(self):
        self.deiconify()
        self.lift()
        self._visible = True
        if self._poll_job is None:
            self._poll_job = self.after(_POLL_MS, self._poll_queue)

    def _hide(self):
        self.withdraw()
        self._visible = False
        if self._debounce_job is not None:
            self.after_cancel(self._debounce_job)
            self._debounce_job = None
        if self._poll_job is not None:
            self.after_cancel(self._poll_job)
            self._poll_job = None

    def _is_visible(self) -> bool:
        return self._visible

    # ------------------------------------------------------------------
    # 設定存取
    def _language_code(self) -> str:
        return _LANGUAGE_CODES_BY_LABEL.get(self.language_var.get(), "zh-TW")

    def _current_settings(self) -> dict:
        """把介面上目前的目標語言／解說開關套進 settings，其餘沿用開窗時的值。"""
        settings = dict(self.settings)
        settings["target_language"] = self._language_code()
        settings["explain"] = bool(self.explain_var.get())
        return settings

    def _write_settings(self):
        data = dict(self.config_data.get("quicktranslate") or {})
        data.update({
            "target_language": self._language_code(),
            "debounce_ms": self.settings["debounce_ms"],
            "cache_size": self.settings["cache_size"],
            "max_chars": self.settings["max_chars"],
            "min_chars": self.settings["min_chars"],
            "explain": bool(self.explain_var.get()),
            "auto_translate": bool(self.auto_var.get()),
            "save_to_vocab": bool(self.save_vocab_var.get()),
            "topmost": bool(self.topmost_var.get()),
        })
        self.config_data["quicktranslate"] = data
        try:
            save_config(self.config_data)
        except OSError:
            pass

    def _on_language_changed(self, _event=None):
        self.dst_frame.configure(text=dst_label(self._language_code()))
        self._write_settings()

    def _on_topmost_toggle(self):
        self.attributes("-topmost", bool(self.topmost_var.get()))
        self._write_settings()

    def _get_api_key(self) -> str:
        # 每次要打 API 前重讀金鑰：使用者回主視窗貼上金鑰不必重開這個視窗。
        return (self.config_data.get("transcription", {})
               .get("api_key", "") or "").strip()

    def _refresh_api_key_state(self, force: bool = False):
        has_key = bool(self._get_api_key())
        if not force and has_key == self._had_key:
            return
        self._had_key = has_key
        if has_key:
            self.auto_check.configure(state="normal")
            if self._in_nokey_state:
                self._in_nokey_state = False
                self._set_state_initial()
        else:
            self.auto_check.configure(state="disabled")
            self._in_nokey_state = True
            self._set_state_nokey()

    # ------------------------------------------------------------------
    # 狀態呈現
    @staticmethod
    def _set_text(widget: tk.Text, content: str):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    def _set_state_initial(self):
        self._set_text(self.src_text, "")
        self._set_text(self.dst_text, C2_INITIAL)
        self._set_text(self.term_text, "")
        self.status_var.set(C3_WAITING)

    def _set_state_nokey(self):
        self._set_text(self.src_text, "")
        self._set_text(self.dst_text, C10_NOKEY_BODY)
        self._set_text(self.term_text, "")
        self.status_var.set(C9_NOKEY_STATUS)

    def _set_state_loading(self, source: str):
        self._set_text(self.src_text, source)
        self._set_text(self.dst_text, "")
        self._set_text(self.term_text, "")
        self.status_var.set(C4_LOADING)

    def _set_state_result(self, result: dict, source: str):
        self._set_text(self.src_text, result.get("source", source))
        self._set_text(self.dst_text, result.get("translation", ""))
        terms = result.get("terms") or []
        if terms:
            term_text = "\n".join(
                f"・「{t['word']}」：{t['meaning']}" for t in terms)
        elif not self.explain_var.get():
            term_text = C6_EXPLAIN_OFF
        else:
            term_text = C7_NO_TERMS
        self._set_text(self.term_text, term_text)

        saved = False
        if terms and self.save_vocab_var.get():
            self.vocab, saved = add_vocab_terms(self.vocab, terms)
            if saved:
                save_vocab(self.vocab)
                self._refresh_vocab_tree()

        if result.get("cached"):
            self.status_var.set(C5_CACHED)
        elif saved:
            self.status_var.set(C5_DONE_SAVED)
        else:
            self.status_var.set(C5_DONE)

    def _set_state_error(self, exc: Exception):
        reason = str(exc).strip()
        reason = reason.splitlines()[0] if reason else "未知錯誤"
        self.status_var.set(
            f"翻譯失敗：{reason}。稍後選取同一段文字、或按「翻譯選取內容」重試。")

    # ------------------------------------------------------------------
    # 觸發：選取事件與去抖動
    def _on_selection_event(self, _event=None):
        if not self._is_visible():
            return
        self._schedule_debounce()

    def _on_button1_press(self, _event=None):
        self._button1_down = True

    def _on_button1_release(self, _event=None):
        self._button1_down = False
        if self._pending_after_release:
            self._pending_after_release = False
            self._schedule_debounce()

    def _schedule_debounce(self):
        if self._debounce_job is not None:
            self.after_cancel(self._debounce_job)
        # debounce_ms 真的是這個 after() 呼叫的延遲——硬性驗收條件。
        self._debounce_job = self.after(
            self.settings["debounce_ms"], self._on_debounce_fire)

    def _on_debounce_fire(self):
        self._debounce_job = None
        if self._button1_down:
            # 拖曳中途停下來讀字、左鍵還沒放：不觸發，等放開後再排一次。
            self._pending_after_release = True
            return
        if not self.auto_var.get():
            return
        if not self._get_api_key():
            return  # 無金鑰：靜默略過，不用每選一次跳一次錯（見狀態列既有提示）。
        try:
            raw = self.selection_get()
        except tk.TclError:
            return
        self._submit(raw, manual=False)

    # ------------------------------------------------------------------
    # 手動按鈕
    def _on_translate_button(self):
        if not self._get_api_key():
            self.status_var.set(C9_NOKEY_STATUS)
            return
        text = self._manual_selection_text()
        if not text.strip():
            self.status_var.set(C17_NOTHING_SELECTED)
            return
        self._submit(text, manual=True)

    def _manual_selection_text(self) -> str:
        try:
            raw = self.selection_get()
            if raw and raw.strip():
                return raw
        except tk.TclError:
            pass
        cue_tree = getattr(self.master, "cue_tree", None)
        if cue_tree is not None:
            selection = cue_tree.selection()
            if selection:
                values = cue_tree.item(selection[0]).get("values") or []
                if len(values) >= 3:
                    return str(values[2])
        return ""

    # ------------------------------------------------------------------
    # 送出翻譯（快取命中直接顯示；未命中才進背景執行緒）
    def _submit(self, raw_text: str, manual: bool):
        settings = self._current_settings()
        source = qt.normalize_snippet(raw_text)
        if not source:
            if manual:
                self.status_var.set(C17_NOTHING_SELECTED)
            return
        if not qt.looks_translatable(source, settings):
            self.status_var.set(classify_skip_reason(source, settings))
            return
        if not manual and source == self._last_success_source:
            return  # 與上次已翻譯的文字相同：連快取查詢都省。

        cache_hit = self.cache.get(
            source, settings["target_language"], settings["explain"])
        if cache_hit is not None:
            result = dict(cache_hit)
            result["cached"] = True
            self._last_success_source = source
            self._consecutive_failures = 0
            self._set_state_result(result, source)
            return

        api_key = self._get_api_key()
        if not api_key:
            self.status_var.set(C9_NOKEY_STATUS)
            return

        self._set_state_loading(source)
        self._request_id += 1
        request_id = self._request_id
        threading.Thread(
            target=self._worker, args=(source, api_key, settings, request_id),
            daemon=True,
        ).start()

    def _worker(self, source, api_key, settings, request_id):
        try:
            result = qt.translate_snippet(
                source, api_key, settings=settings, cache=self.cache)
            self.result_queue.put(("done", request_id, source, result))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("即時查譯失敗")
            self.result_queue.put(("error", request_id, source, exc))

    # ------------------------------------------------------------------
    def _poll_queue(self):
        self._refresh_api_key_state()
        try:
            while True:
                kind, request_id, source, payload = self.result_queue.get_nowait()
                if request_id != self._request_id:
                    continue  # 已經有更新的選取取代了它，這筆結果作廢、不顯示。
                if kind == "done":
                    self._last_success_source = source
                    self._consecutive_failures = 0
                    self._set_state_result(payload, source)
                elif kind == "error":
                    self._consecutive_failures += 1
                    self._set_state_error(payload)
                    if self._consecutive_failures >= _CONSECUTIVE_FAILURE_LIMIT:
                        self._consecutive_failures = 0
                        if self.auto_var.get():
                            self.auto_var.set(False)
                            self._write_settings()
                            self.status_var.set(C13_AUTO_PAUSED)
        except queue.Empty:
            pass
        self._poll_job = self.after(_POLL_MS, self._poll_queue)

    # ------------------------------------------------------------------
    # 生字本
    def _refresh_vocab_tree(self):
        self.vocab_tree.delete(*self.vocab_tree.get_children())
        for row in self.vocab:
            self.vocab_tree.insert("", "end", values=(row["word"], row["meaning"]))
        self.vocab_status_var.set(vocab_status_text(len(self.vocab)))

    def _on_vocab_delete(self):
        selection = self.vocab_tree.selection()
        if not selection:
            return
        words = {self.vocab_tree.item(item_id, "values")[0]
                for item_id in selection}
        self.vocab = remove_vocab_words(self.vocab, words)
        save_vocab(self.vocab)
        self._refresh_vocab_tree()

    def _on_vocab_clear(self):
        if not self.vocab:
            self.vocab_status_var.set(C22_VOCAB_EMPTY)
            return
        n = len(self.vocab)
        if not messagebox.askyesno(
                C21_CLEAR_TITLE,
                f"確定刪除全部 {n} 個詞？此動作無法復原（建議先匯出 CSV 備份）。",
                parent=self):
            return
        self.vocab = []
        save_vocab(self.vocab)
        self._refresh_vocab_tree()

    def _on_vocab_export(self):
        if not self.vocab:
            self.vocab_status_var.set(C22_VOCAB_EMPTY)
            return
        path = filedialog.asksaveasfilename(
            title="匯出生字本 CSV", defaultextension=".csv",
            initialfile="quicktranslate_vocab.csv",
            filetypes=[("CSV 檔", "*.csv")], parent=self)
        if not path:
            return
        try:
            write_vocab_csv(self.vocab, path)
        except OSError as exc:
            messagebox.showerror("匯出失敗", str(exc), parent=self)
            return
        self.vocab_status_var.set(C20_EXPORTED(len(self.vocab), path))
