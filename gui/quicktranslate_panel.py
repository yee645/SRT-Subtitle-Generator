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
from subtitle import clipwatch as cw
from subtitle import hotkey as hk
from subtitle import ocrengine
from subtitle import quicktranslate as qt
from subtitle import screencap
from subtitle import screentranslate as st
from subtitle import speech
from subtitle.punctstyle import cjk_ratio
from subtitle.translator import LANGUAGE_LABELS

from gui.region_overlay import RegionOverlay
from gui.tesseract_dialog import TesseractInstallDialog

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
# 全域熱鍵輪詢間隔（見 subtitle/hotkey.py 的 WindowsBackend 說明）。
_HOTKEY_POLL_MS = 120
# 朗讀狀態輪詢：念完要把狀態列改回來，失敗也要講。
_SPEECH_POLL_MS = 300

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

# v2.3.0 螢幕翻譯（第 9 項 5b）。
C30_SCREEN_HINT = ("框選螢幕上任何一塊畫面（遊戲、影片、圖片裡的字），"
                   "在這台電腦上辨識成文字，確認後再翻譯。畫面不會被傳出去。")
C31_OCR_RUNNING = "辨識中…（在這台電腦上跑，通常 1～3 秒）"
C32_OCR_CANCELLED = "已取消框選。"
C33_NEED_TESSERACT = ("螢幕翻譯要先安裝文字辨識引擎。安裝視窗已經打開，"
                      "裝完再按一次「框選螢幕翻譯」。")
C34_NOTHING_TO_SPEAK = "還沒有可以朗讀的內容。"
C35_NOTHING_TO_COPY = "還沒有可以複製的內容。"
C36_SPEECH_OFF = "朗讀功能已在設定裡關閉。"
C37_SECRET_BLOCKED = ("這段內容看起來像密碼或金鑰，不會送去翻譯。"
                      "需要的話仍可在本機朗讀或複製。")
C38_OCR_BUSY = "上一次框選還在辨識，請稍候。"


def hotkey_check_label(combo: str) -> str:
    return f"熱鍵 {combo}"


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

    def __init__(self, master, config_data: dict, start_hidden: bool = False):
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
        # v2.1.0 剪貼簿監聽（「複製即翻譯」）。
        self.clip_settings = cw.resolve_clipwatch_settings(config_data)
        self._clip_job = None
        self._last_clip = None        # 上一次看到的剪貼簿內容，用來只在「變了」時才動作
        # v2.3.0 螢幕翻譯。辨識結果走自己的佇列與輪詢——框選時面板是收起
        # 來的，不能靠只在面板可見時才跑的 `_poll_queue`。
        self.screen_settings = st.resolve_screentranslate_settings(config_data)
        self._ocr_queue: "queue.Queue" = queue.Queue()
        self._ocr_job = None
        self._ocr_busy = False
        self._ocr_id = 0
        self._speaker = None
        self._speech_job = None
        self.hotkey_settings = hk.resolve_hotkey_settings(config_data)
        self._hotkey = None
        self._hotkey_job = None

        self.title("即時查譯（選字即翻）")
        self.geometry("520x720")
        self.minsize(480, 680)
        self.transient(master)

        raw_prefs = config_data.get("quicktranslate") or {}
        self.auto_var = tk.BooleanVar(value=bool(raw_prefs.get("auto_translate", True)))
        self.explain_var = tk.BooleanVar(value=self.settings["explain"])
        self.save_vocab_var = tk.BooleanVar(value=bool(raw_prefs.get("save_to_vocab", True)))
        self.topmost_var = tk.BooleanVar(value=bool(raw_prefs.get("topmost", True)))
        self.clipwatch_var = tk.BooleanVar(value=self.clip_settings["enabled"])
        self.hotkey_var = tk.BooleanVar(value=self.hotkey_settings["enabled"])

        self._build_ui()
        self.attributes("-topmost", bool(self.topmost_var.get()))

        self.bind_all("<<Selection>>", self._on_selection_event, add="+")
        self.bind_all("<ButtonPress-1>", self._on_button1_press, add="+")
        self.bind_all("<ButtonRelease-1>", self._on_button1_release, add="+")
        self.protocol("WM_DELETE_WINDOW", self._hide)

        self._refresh_api_key_state(force=True)
        self._refresh_vocab_tree()
        if self.hotkey_var.get():
            self._enable_hotkey()
        if start_hidden:
            # 只為了熱鍵而在背景建好面板：不要在使用者眼前閃一下。
            self.withdraw()
            self._visible = False
        else:
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

        # v2.3.0 螢幕翻譯放最上面：它是另一個「文字從哪來」的入口，跟
        # 選取、剪貼簿並列，但不需要先有文字才能按。
        screen_row = ttk.Frame(page)
        screen_row.pack(fill="x")
        self.screen_btn = ttk.Button(
            screen_row, text="框選螢幕翻譯", width=12,
            command=self.start_screen_capture)
        self.screen_btn.pack(side="left")
        self.ocr_translate_btn = ttk.Button(
            screen_row, text="翻譯辨識結果", width=12, state="disabled",
            command=self._on_ocr_translate)
        self.ocr_translate_btn.pack(side="left", padx=(8, 0))
        self.hotkey_check = ttk.Checkbutton(
            screen_row, text=hotkey_check_label(self.hotkey_settings["combo"]),
            variable=self.hotkey_var, command=self._on_hotkey_toggle)
        self.hotkey_check.pack(side="left", padx=(10, 0))
        self.screen_status_var = tk.StringVar(value=C30_SCREEN_HINT)
        ttk.Label(page, textvariable=self.screen_status_var, foreground=HINT_FG,
                  wraplength=460, justify="left").pack(anchor="w", pady=(4, 6))

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

        # 朗讀／複製：不需要 API 金鑰，辨識被擋下來（像密碼）時也照樣能用。
        voice_row = ttk.Frame(page)
        voice_row.pack(fill="x", pady=(0, 4))
        ttk.Label(voice_row, text="朗讀:").pack(side="left")
        self.speak_src_btn = ttk.Button(
            voice_row, text="原文", width=5,
            command=lambda: self._speak("src"))
        self.speak_src_btn.pack(side="left", padx=(4, 0))
        self.speak_dst_btn = ttk.Button(
            voice_row, text="譯文", width=5,
            command=lambda: self._speak("dst"))
        self.speak_dst_btn.pack(side="left", padx=(4, 0))
        self.speak_stop_btn = ttk.Button(
            voice_row, text="停止", width=5, command=self._stop_speaking)
        self.speak_stop_btn.pack(side="left", padx=(4, 0))
        ttk.Label(voice_row, text="複製:").pack(side="left", padx=(14, 0))
        self.copy_src_btn = ttk.Button(
            voice_row, text="原文", width=5, command=lambda: self._copy("src"))
        self.copy_src_btn.pack(side="left", padx=(4, 0))
        self.copy_dst_btn = ttk.Button(
            voice_row, text="譯文", width=5, command=lambda: self._copy("dst"))
        self.copy_dst_btn.pack(side="left", padx=(4, 0))

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

        # v2.1.0：剪貼簿監聽自成一列，因為它跟上面那些「怎麼翻」的選項不
        # 同——它決定的是「要不要讀取你複製的每一樣東西」，屬於另一個層
        # 級的決定，不該跟語言選單擠在一起讓人順手勾到。
        clip_row = ttk.Frame(page)
        clip_row.pack(fill="x", pady=(6, 0))
        self.clip_check = ttk.Checkbutton(
            clip_row, text="監聽剪貼簿（複製即翻譯）",
            variable=self.clipwatch_var, command=self._on_clipwatch_toggle)
        self.clip_check.pack(side="left")
        self.clip_status_var = tk.StringVar(value="")
        ttk.Label(clip_row, textvariable=self.clip_status_var,
                  foreground=HINT_FG).pack(side="left", padx=(8, 0))
        ttk.Label(
            page, foreground=HINT_FG, justify="left", wraplength=460,
            text="開啟後，在任何軟體按 Ctrl+C 複製外文就會自動翻譯——"
                 "本程式之外也能用。密碼、金鑰、檔案路徑、網址與程式碼會"
                 "自動跳過，不會送出。關掉這個面板就停止監聽。",
        ).pack(anchor="w", pady=(2, 0))

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
        if self.clipwatch_var.get():
            self._start_clipwatch()

    def _hide(self):
        self.withdraw()
        self._visible = False
        if self._debounce_job is not None:
            self.after_cancel(self._debounce_job)
            self._debounce_job = None
        if self._poll_job is not None:
            self.after_cancel(self._poll_job)
            self._poll_job = None
        # 面板收起來就停止監聽剪貼簿。「關掉視窗」在使用者的預期裡就是
        # 「別再讀我複製的東西」——而且翻譯結果沒人看得到也沒有意義。
        # 勾選狀態保留，下次開窗會自動恢復監聽。
        self._stop_clipwatch()

    # ------------------------------------------------------------------
    # 剪貼簿監聽（v2.1.0，選取即翻譯第二階段）
    def _on_clipwatch_toggle(self):
        """使用者勾選／取消「監聽剪貼簿」。"""
        if self.clipwatch_var.get():
            self._start_clipwatch()
        else:
            self._stop_clipwatch()
            self.clip_status_var.set("已停止監聽。")
        self._write_settings()

    def _start_clipwatch(self):
        """
        開始監聽。

        開始的當下**先把目前剪貼簿內容記下來但不翻譯**——使用者按下勾選
        的那一刻，剪貼簿裡多半躺著他稍早複製的東西（很可能就是密碼或路
        徑），沒有理由把它當成「剛複製的」送出去。從下一次變動才算數。
        """
        if self._clip_job is not None:
            return
        self._last_clip = self._read_clipboard()
        self.clip_status_var.set("監聽中——複製外文即翻譯。")
        self._clip_job = self.after(
            self.clip_settings["poll_ms"], self._poll_clipboard)

    def _stop_clipwatch(self):
        if self._clip_job is not None:
            self.after_cancel(self._clip_job)
            self._clip_job = None

    def _read_clipboard(self):
        """
        讀取剪貼簿文字；讀不到就回 None。

        剪貼簿裡放的是圖片、檔案或空的時候，`clipboard_get()` 會丟
        TclError——那是正常情形不是錯誤，不能讓它把輪詢打斷。
        """
        try:
            return self.clipboard_get()
        except tk.TclError:
            return None

    def _poll_clipboard(self):
        """
        定時看剪貼簿有沒有變。Tk 沒有「剪貼簿變了」的事件，只能輪詢。

        只在**內容真的變了**時才動作，否則同一段文字會被重複送出。變動之
        後先過 `subtitle/clipwatch.py` 的篩子——密碼、金鑰、路徑、程式碼
        一律不送，並且把「為什麼沒翻」寫在面板上：介面沉默地什麼都不做，
        跟功能壞掉在使用者眼裡是同一件事。
        """
        self._clip_job = None
        if not self.clipwatch_var.get() or not self._is_visible():
            return
        current = self._read_clipboard()
        if current is not None and current != self._last_clip:
            self._last_clip = current
            verdict = cw.classify_clipboard(
                current, self.clip_settings, self._current_settings())
            self.clip_status_var.set(cw.format_skip_reason(verdict))
            if verdict["translate"]:
                self._submit(current, manual=False)
        self._clip_job = self.after(
            self.clip_settings["poll_ms"], self._poll_clipboard)

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
        clip = dict(self.config_data.get("clipwatch") or {})
        clip.update({
            "enabled": bool(self.clipwatch_var.get()),
            "poll_ms": self.clip_settings["poll_ms"],
            "skip_secrets": self.clip_settings["skip_secrets"],
            "skip_code": self.clip_settings["skip_code"],
            "skip_paths": self.clip_settings["skip_paths"],
        })
        self.config_data["clipwatch"] = clip
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
            self.clip_check.configure(state="normal")
            if self._in_nokey_state:
                self._in_nokey_state = False
                self._set_state_initial()
        else:
            self.auto_check.configure(state="disabled")
            # v2.1.0：沒有金鑰時「監聽剪貼簿」也要一起停用。截圖比對時發現
            # 只停用了「選取後自動翻譯」，剪貼簿那顆還能勾——使用者打開它、
            # 然後複製了東西卻什麼都沒發生，也不知道是為什麼。順手把監聽
            # 停下來，不要讓它在沒有金鑰的情況下空轉讀取剪貼簿。
            self.clip_check.configure(state="disabled")
            self._stop_clipwatch()
            self.clip_status_var.set("")
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
        # v2.3.0：辨識結果放在可編輯的原文框裡，在那裡選字也會觸發選取即
        # 翻譯——那條路不經過 `_on_ocr_translate`。所以密碼檢查放在所有
        # 路徑都會經過的這裡，而不是只放在按鈕上。寧可漏翻、不可誤送。
        if st.is_secret(source):
            self.status_var.set(C37_SECRET_BLOCKED)
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
    # 螢幕翻譯（v2.3.0，第 9 項 5b）
    def start_screen_capture(self):
        """
        框選一塊螢幕 → 本機辨識 → 顯示在原文框。

        熱鍵和按鈕都走這裡。框選前先把面板收起來，否則面板自己會蓋在要框
        的東西上面，也會被截進去。
        """
        if self._ocr_busy:
            self._reveal()
            self.screen_status_var.set(C38_OCR_BUSY)
            return
        if not ocrengine.tesseract_available():
            # 沒裝引擎就直接開安裝視窗，不要讓使用者先框一次才被告知。
            self._reveal()
            self.screen_status_var.set(C33_NEED_TESSERACT)
            TesseractInstallDialog(self)
            return
        self._ocr_busy = True
        self.screen_btn.configure(state="disabled")
        self._was_visible = self._visible
        self.withdraw()
        self._visible = False
        self.update_idletasks()
        RegionOverlay(self, on_select=self._on_region_selected,
                      on_cancel=self._on_region_cancelled)

    def _reveal(self):
        """把面板叫出來（熱鍵觸發時面板可能根本沒開過）。"""
        if not self._visible:
            self.show()
        else:
            self.lift()

    def _on_region_cancelled(self):
        self._ocr_busy = False
        self.screen_btn.configure(state="normal")
        if getattr(self, "_was_visible", True):
            self._reveal()
            self.screen_status_var.set(C32_OCR_CANCELLED)

    def _on_region_selected(self, region):
        self._ocr_id += 1
        ocr_id = self._ocr_id
        width, height = self.winfo_screenwidth(), self.winfo_screenheight()
        self._reveal()
        self.screen_status_var.set(C31_OCR_RUNNING)
        threading.Thread(
            target=self._ocr_worker,
            args=(region, (0, 0, width, height), ocr_id), daemon=True,
        ).start()
        if self._ocr_job is None:
            self._ocr_job = self.after(_POLL_MS, self._poll_ocr)

    def _ocr_worker(self, region, bounds, ocr_id):
        try:
            result = st.capture_and_recognize(
                region, config=self.config_data, bounds=bounds)
            self._ocr_queue.put(("done", ocr_id, result))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            # 擷取與辨識的例外訊息本來就寫成使用者看得懂的話，照原樣顯示；
            # 其他例外多半是程式錯誤，留完整記錄。
            if not isinstance(exc, (ocrengine.OcrError, screencap.CaptureError)):
                logger.exception("螢幕翻譯失敗")
            self._ocr_queue.put(("error", ocr_id, exc))

    def _poll_ocr(self):
        self._ocr_job = None
        try:
            kind, ocr_id, payload = self._ocr_queue.get_nowait()
        except queue.Empty:
            self._ocr_job = self.after(_POLL_MS, self._poll_ocr)
            return
        self._ocr_busy = False
        self.screen_btn.configure(state="normal")
        if ocr_id != self._ocr_id:
            return
        self._reveal()
        if kind == "error":
            reason = str(payload).strip().splitlines()
            self.screen_status_var.set(
                "螢幕翻譯失敗：%s" % (reason[0] if reason else "未知錯誤"))
            return
        self._show_ocr_result(payload)

    def _show_ocr_result(self, result: dict):
        decision = st.decide(result, self.screen_settings)
        self.notebook.select(0)
        # 辨識結果常有錯字，原文框開放編輯，讓使用者改好再送。
        self._set_text(self.src_text, decision["text"])
        self.src_text.configure(state="normal")
        if not self._in_nokey_state:
            self._set_text(self.dst_text, "")
        self._set_text(self.term_text, "")
        # 結論只寫在上方那一行（離按鈕最近）；下方狀態列清掉，免得留著上
        # 一次查譯的「翻譯完成」讓人以為這段也翻好了。
        self.screen_status_var.set(st.format_status(result, decision))
        self.status_var.set("")
        if decision["action"] == st.ACTION_BLOCK:
            self.ocr_translate_btn.configure(state="disabled")
        else:
            self.ocr_translate_btn.configure(state="normal")
            if decision["action"] == st.ACTION_SEND:
                self._on_ocr_translate()

    def _on_ocr_translate(self):
        """按下「翻譯辨識結果」：以使用者**改過之後**的原文為準再檢查一次。"""
        text = self.src_text.get("1.0", "end-1c")
        ok, why = st.may_send(text)
        if not ok:
            self.status_var.set(why)
            return
        if not self._get_api_key():
            self.status_var.set(C9_NOKEY_STATUS)
            return
        self.ocr_translate_btn.configure(state="disabled")
        self._submit(text, manual=True)

    # ------------------------------------------------------------------
    # 熱鍵
    def _on_hotkey_toggle(self):
        if self.hotkey_var.get():
            self._enable_hotkey()
        else:
            self._disable_hotkey()
            self.screen_status_var.set(
                f"熱鍵 {self.hotkey_settings['combo']} 已關閉。")
        data = dict(self.config_data.get("hotkey") or {})
        data.update({"enabled": bool(self.hotkey_var.get()),
                     "combo": self.hotkey_settings["combo"]})
        self.config_data["hotkey"] = data
        try:
            save_config(self.config_data)
        except OSError:
            pass

    def _hotkey_hwnd(self):
        """RegisterHotKey 要的是主視窗的最外層 handle（只在 Windows 用得到）。"""
        try:
            return int(self.master.winfo_toplevel().wm_frame(), 16)
        except (tk.TclError, ValueError, AttributeError):
            return None

    def _enable_hotkey(self):
        if self._hotkey is None:
            import sys
            hwnd = self._hotkey_hwnd() if sys.platform == "win32" else None
            self._hotkey = hk.HotkeyManager(
                backend=hk.make_backend(hwnd),
                window_binder=self._bind_hotkey,
                window_unbinder=self._unbind_hotkey,
                on_trigger=lambda: self.after(0, self.start_screen_capture))
        try:
            status = self._hotkey.enable(self.hotkey_settings["combo"])
        except hk.HotkeyError as exc:
            status = "unavailable"
            self.screen_status_var.set(str(exc))
        else:
            self.screen_status_var.set(self._hotkey.describe())
        if status == "global" and self._hotkey_job is None:
            self._hotkey_job = self.after(_HOTKEY_POLL_MS, self._poll_hotkey)
        return status

    def _disable_hotkey(self):
        if self._hotkey_job is not None:
            self.after_cancel(self._hotkey_job)
            self._hotkey_job = None
        if self._hotkey is not None:
            self._hotkey.disable()

    def _bind_hotkey(self, sequence):
        # bind_all：焦點在本程式任何一個視窗都有效，不只這個面板。
        self.bind_all(sequence, lambda _e: self._hotkey.trigger())
        return True

    def _unbind_hotkey(self, sequence):
        self.unbind_all(sequence)

    def _poll_hotkey(self):
        self._hotkey_job = None
        if self._hotkey is None or self._hotkey.status != "global":
            return
        self._hotkey.poll()
        self._hotkey_job = self.after(_HOTKEY_POLL_MS, self._poll_hotkey)

    # ------------------------------------------------------------------
    # 朗讀／複製（不需要 API 金鑰）
    _PLACEHOLDERS = (C2_INITIAL, C10_NOKEY_BODY)

    def _panel_text(self, which: str) -> str:
        widget = self.src_text if which == "src" else self.dst_text
        text = widget.get("1.0", "end-1c").strip()
        return "" if text in self._PLACEHOLDERS else text

    def _speak(self, which: str):
        text = self._panel_text(which)
        if not text:
            self.status_var.set(C34_NOTHING_TO_SPEAK)
            return
        settings = speech.resolve_speech_settings(self.config_data)
        if not settings["enabled"]:
            self.status_var.set(C36_SPEECH_OFF)
            return
        if self._speaker is None:
            self._speaker = speech.Speaker(settings=settings)
        lang = (st.guess_speech_lang(text) if which == "src"
                else self._language_code())
        try:
            dropped = self._speaker.speak(text, lang)
        except speech.SpeechError as exc:
            self.status_var.set(str(exc))
            return
        label = "原文" if which == "src" else "譯文"
        if dropped:
            self.status_var.set(f"朗讀{label}中（太長，後面 {dropped} 字不念）。")
        else:
            self.status_var.set(f"朗讀{label}中。")
        if self._speech_job is None:
            self._speech_job = self.after(_SPEECH_POLL_MS, self._poll_speech)

    def _poll_speech(self):
        self._speech_job = None
        speaker = self._speaker
        if speaker is None or speaker._proc is None:
            return
        code = speaker.wait(timeout=0)
        if code is None:
            self._speech_job = self.after(_SPEECH_POLL_MS, self._poll_speech)
            return
        if code != 0:
            detail = speaker.last_error or speaker._read_stderr()
            self.status_var.set(
                "朗讀失敗%s。" % (f"：{detail.splitlines()[0]}" if detail else ""))
        else:
            self.status_var.set("朗讀完畢。")

    def _stop_speaking(self):
        if self._speaker is not None and self._speaker.is_speaking():
            self._speaker.stop()
            self.status_var.set("已停止朗讀。")

    def _copy(self, which: str):
        text = self._panel_text(which)
        if not text:
            self.status_var.set(C35_NOTHING_TO_COPY)
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        # 自己放進剪貼簿的東西不要被「監聽剪貼簿」當成新複製的再翻一次。
        self._last_clip = text
        label = "原文" if which == "src" else "譯文"
        self.status_var.set(f"已複製{label}。")

    def destroy(self):
        for job in ("_ocr_job", "_hotkey_job", "_speech_job"):
            if getattr(self, job, None) is not None:
                try:
                    self.after_cancel(getattr(self, job))
                except tk.TclError:
                    pass
                setattr(self, job, None)
        if getattr(self, "_hotkey", None) is not None:
            self._hotkey.disable()
        if getattr(self, "_speaker", None) is not None:
            self._speaker.stop()
        super().destroy()

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
