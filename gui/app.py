# -*- coding: utf-8 -*-
"""
SRT 自動字幕生成與編輯應用程式 - 主視窗。

整合：模式切換（含手動字幕模式）、檔案選擇（可多選批次）、轉寫設定、
字幕生成、即時預覽、視覺調整面板、多格式字幕匯出（SRT/VTT/ASS/TXT）、
影片字幕燒錄（hardsub），以及設定檔的載入與自動儲存（記憶功能）。

v1.3 起新增：
- 「一鍵完成」：生成 → 匯出 → 燒錄整條流程免對話框自動完成（subtitle/pipeline）
- 「自動化輸出」設定區：匯出格式勾選、燒錄、輸出資料夾（記憶於 config.json）
- 工具列「審片助手」：文字審片找可用片段（gui/review_window）
"""

import logging
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

try:
    import sv_ttk
    _HAS_SV_TTK = True
except ImportError:
    # 未安裝 sv-ttk 時退回系統預設外觀，不影響程式運作。
    sv_ttk = None
    _HAS_SV_TTK = False

from config import load_config, make_profile, save_config
from updater import (APP_VERSION, check_for_update, cleanup_old_version,
                     download_and_apply)
from subtitle.aligner import align_transcript
from subtitle.burner import burn_subtitles, ffmpeg_available
from subtitle.exporter import FORMAT_FILETYPES, export, format_srt_timestamp
from subtitle.importer import load_subtitle_file
from subtitle.pipeline import run_batch
from subtitle.segmenter import build_cues_from_words
from subtitle.textedit import apply_corrections
from subtitle.transcriber import transcribe
from gui.audiovis_dialog import AudioVisDialog
from gui.branding_dialog import BrandingDialog
from gui.health_center_dialog import HealthCenterDialog
from gui.error_dialog import show_friendly_error
from gui.ffmpeg_dialog import FfmpegInstallDialog
from gui.cue_editor import CueEditDialog
from gui.jumpcut_dialog import JumpCutDialog
from gui.retakes_dialog import RetakesDialog
from gui.music_dialog import MusicDuckingDialog
from gui.preview_panel import PreviewPanel
from gui.quicktranslate_panel import QuickTranslatePanel
from gui.replace_dialog import ReplaceDialog
from gui.review_window import ReviewWindow
from gui.scrollable import ScrollableFrame
from gui.style_panel import StylePanel
from gui.translate_dialog import TranslateDialog

logger = logging.getLogger(__name__)

# 支援的影音檔副檔名（檔案選擇器用）。
MEDIA_FILETYPES = [
    ("影片與音訊檔", "*.mp4 *.mkv *.mov *.avi *.flv *.mp3 *.wav *.m4a *.aac *.ogg"),
    ("所有檔案", "*.*"),
]
# 可匯入的字幕檔副檔名（匯入字幕按鈕用）。
IMPORT_FILETYPES = [
    ("字幕檔（SRT/VTT）", "*.srt *.vtt"),
    ("SRT 字幕檔", "*.srt"),
    ("WebVTT 字幕檔", "*.vtt"),
    ("所有檔案", "*.*"),
]
# 模式識別字串。
MODE_TRANSCRIBE = "transcribe"
MODE_ALIGN = "align"
MODE_MANUAL = "manual"
# 工具列每一列最多放幾個功能按鈕（超過就換行，避免被視窗寬度切掉）。
_TOOLS_PER_ROW = 4
# 三欄主體版面（v1.52.0，修折疊線：docs/UI_AUDIT_2.0.md 1.3-①、
# docs/UI_ARCHITECTURE_2.0.md B.2/B.3）：左欄固定寬（自帶垂直捲動，只
# 捲設定）、右欄固定寬（外觀：樣式組合／預覽／樣式面板），中欄吃剩餘
# 寬度放主動作與字幕清單，兩者同屏永遠可見。
_LEFT_COLUMN_WIDTH = 330
_RIGHT_COLUMN_WIDTH = 420
# 視窗寬度低於此值時右欄先收合讓中欄有喘息空間（docs/UI_ARCHITECTURE_2.0.md
# F-5 點名這是未定案項；v1.52.0 定案為「右欄收合」，見 PR 說明與
# ROADMAP 的偏離規劃記錄）。330(左) + 420(右) + 400(中欄可用最小值) ≈ 1150。
_LAYOUT_COLLAPSE_WIDTH = 1150


class SrtApp(tk.Tk):
    """應用程式主視窗。"""

    def __init__(self):
        super().__init__()
        self.title(f"SRT 自動字幕生成與編輯工具 v{APP_VERSION}")
        self.geometry("1400x800")
        # 最小寬度需容納得下功能按鈕列（實測需 968px），否則視窗縮到最小時
        # 最右邊的按鈕會被裁掉。
        self.minsize(980, 560)

        # 載入設定檔，達成記憶功能。
        self.config_data = load_config()
        # 套用使用者偏好的外觀主題（light / dark）；未安裝 sv-ttk 時退回系統預設。
        self._apply_theme(self.config_data.get("theme", "light"))
        # 生成結果（cue 清單）與背景執行緒通訊佇列。
        self.cues = []
        self.result_queue = queue.Queue()
        self.is_processing = False

        self._build_widgets()
        self._update_mode_state()
        self._refresh_preview()
        # 啟動背景佇列輪詢。
        self.after(120, self._poll_queue)
        # 關閉視窗時先存檔。
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # 清除上次更新遺留的舊檔，並於背景檢查是否有新版本。
        cleanup_old_version()
        self.after(1500, self._start_update_check)

    # ==================================================================
    # 主題（dark / light）
    # ==================================================================
    def _apply_theme(self, theme):
        """套用 sv-ttk 主題；未安裝時不執行（程式仍可正常運作）。"""
        if not _HAS_SV_TTK:
            return
        try:
            sv_ttk.set_theme("dark" if theme == "dark" else "light")
        except Exception:
            # 主題套用失敗不影響核心功能。
            pass
        # 捲動容器的 Canvas 不是 ttk 元件，主題切換時需手動同步背景色，
        # 否則深色主題下會露出一塊淺色畫布（見 v1.14.1 修復）。
        scroll_frame = getattr(self, "scroll_frame", None)
        if scroll_frame is not None:
            scroll_frame.refresh_theme(theme)
        # v1.52.0：中欄也包了一層 ScrollableFrame（minsize 980x560 時的
        # 退化保底，見 `_build_widgets`），同一個理由需要同步背景色。
        middle_scroll_frame = getattr(self, "middle_scroll_frame", None)
        if middle_scroll_frame is not None:
            middle_scroll_frame.refresh_theme(theme)

    def _toggle_theme(self):
        """切換淺色與深色主題並寫回設定。"""
        current = self.config_data.get("theme", "light")
        new_theme = "dark" if current != "dark" else "light"
        self.config_data["theme"] = new_theme
        self._apply_theme(new_theme)
        self._save_config_silently()
        # 更新按鈕文字以反映下一次切換的目標。
        if hasattr(self, "theme_btn") and self.theme_btn:
            label = "切換為淺色" if new_theme == "dark" else "切換為深色"
            self.theme_btn.configure(text=label)
        self.status_var.set(
            f"已切換為{'深色' if new_theme == 'dark' else '淺色'}主題。")

    # ==================================================================
    # 介面建構
    # ==================================================================
    def _build_widgets(self):
        """
        建立整體版面：頂部工具列＋三欄主體。

        v1.52.0 三欄化（`docs/UI_ARCHITECTURE_2.0.md` B.2/B.3）：把 v1.x
        「1240px 高的設定長表單」轉九十度——左欄（`_LEFT_COLUMN_WIDTH`，
        自帶垂直捲動）收生成前設定，中欄放主動作＋字幕清單＋清單編輯
        列＋匯出燒錄＋自動化輸出（永遠可見，不隨左欄捲動），右欄（
        `_RIGHT_COLUMN_WIDTH`）收外觀（樣式組合／預覽／樣式面板）。這一
        步只換容器：控件本身、事件處理、config 欄位一概不變（不做頁
        籤、不拆一鍵完成，那些是 v1.53）。
        """
        # 頂部工具列：主題切換等全域控制。
        self._build_toolbar()

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        self.body_frame = body

        # 左欄：固定寬、自帶垂直捲動，只捲設定（生成前才需要調整的區塊）。
        self.left_container = ttk.Frame(body, width=_LEFT_COLUMN_WIDTH)
        self.left_container.pack_propagate(False)
        scroll = ScrollableFrame(
            self.left_container, theme=self.config_data.get("theme", "light"))
        scroll.pack(fill="both", expand=True)
        left = scroll.interior
        # 供 _apply_theme 在主題切換時同步更新 Canvas 背景色。
        self.scroll_frame = scroll

        # 右欄：固定寬，外觀設定（樣式組合／預覽／樣式面板）。
        self.right_container = ttk.Frame(body, width=_RIGHT_COLUMN_WIDTH)
        self.right_container.pack_propagate(False)
        # 水平 padding 只留 6px（垂直仍 10px）：392px 寬的預覽畫布＋外層
        # LabelFrame 邊框，在 420px 右欄裡沒有太多容錯空間，見
        # `_build_preview_section` 同一份理由。
        right = ttk.Frame(self.right_container, padding=(6, 10))
        right.pack(fill="both", expand=True)

        # 中欄：吃剩餘寬度，主動作與字幕清單放最上方、與右欄同高不裁切。
        # 包一層 ScrollableFrame 只當 minsize 980x560 的退化保底——正常
        # 尺寸下中欄內容量得到全部塞得下（見 `_build_widgets` docstring
        # 的 1400x800 實測值），不需要捲動；但 980x560 時中欄全部內容
        # 實測需要 700px 高、只分到約 440px，若中欄本身不能捲動，「自動
        # 化輸出」整區會被 pack 直接擠到 `winfo_ismapped()==0`（不是裁
        # 切，是整個消失、比裁切更嚴重），這裡讓它退化成可捲動而不是憑
        # 空消失。
        self.middle_frame = ttk.Frame(body)
        middle_scroll = ScrollableFrame(
            self.middle_frame, theme=self.config_data.get("theme", "light"))
        middle_scroll.pack(fill="both", expand=True)
        middle = ttk.Frame(middle_scroll.interior, padding=10)
        middle.pack(fill="both", expand=True)
        self.middle_scroll_frame = middle_scroll

        # 先套一次三欄排版（預設展開右欄），內容建好後再依視窗寬度即時調整。
        self._right_collapsed = None
        self._apply_body_layout(collapsed=False)

        self._build_mode_section(left)
        self._build_file_section(left)
        self._build_transcription_section(left)
        self._build_segmentation_section(left)
        self._build_transcript_section(left)

        self._build_action_section(middle)
        self._build_cue_list(middle)
        self._build_cue_edit_controls(middle)
        self._build_export_section(middle)
        # 「自動化輸出」原本在左欄最深處；v1.52.0 移出左欄設定表單，暫放
        # 中欄「匯出與燒錄」附近（見 docs/ROADMAP_2.0.md v1.52 項：v1.53
        # 加頁籤後才是它的最終位置——階段④「輸出與發佈」）。
        self._build_automation_section(middle)

        self._build_preset_section(right)
        self._build_preview_section(right)
        self._build_style_section(right)

        # 視窗寬度變化時（含 minsize 980x560）即時套用三欄退化規則。
        self.bind("<Configure>", self._on_root_configure)

    def _apply_body_layout(self, collapsed):
        """
        依 collapsed 狀態重新排三欄。

        一律整批 `pack_forget()` 再依序重新 `pack()`，不對單一容器做
        forget/re-pack——pack 管理器對同一個 master 內的 slave 是依「最
        近一次 pack() 的呼叫順序」分配剩餘空間，若只把右欄 forget 再
        pack 回來，它會被排到順序最後，此時已 expand 的中欄早已吃光剩
        餘空間，右欄會被擠成 0 寬。整批重排三個容器可以每次都保證
        「左→右→中」的正確分配順序（中欄最後拿剩餘寬度）。
        """
        if collapsed == self._right_collapsed:
            return
        self._right_collapsed = collapsed
        for widget in (self.left_container, self.middle_frame,
                      self.right_container):
            widget.pack_forget()
        self.left_container.pack(side="left", fill="y")
        if not collapsed:
            self.right_container.pack(side="right", fill="y")
        self.middle_frame.pack(side="left", fill="both", expand=True)

    def _on_root_configure(self, event):
        """
        視窗尺寸變動時的三欄退化規則（`docs/UI_ARCHITECTURE_2.0.md` F-5）。

        寬度不足 `_LAYOUT_COLLAPSE_WIDTH`（含 minsize 980x560 的情形）
        時收合右欄（外觀設定），讓中欄的主動作與字幕清單保有可用寬度；
        右欄的內容（樣式面板／預覽）並未銷毀，只是暫時不 pack，加寬視
        窗會自動恢復顯示，不需要另外的展開按鈕。
        """
        if event.widget is not self:
            return
        width = self.winfo_width()
        if width <= 1:
            return  # 視窗尚未真正完成配置（初始事件），量到假值時不套用。
        self._apply_body_layout(collapsed=width < _LAYOUT_COLLAPSE_WIDTH)

    def _build_toolbar(self):
        """
        頂部工具列：標題／版本一列，功能按鈕另起一列並自動換行。

        v1.51.0：11 顆收成 6 顆。「上片前健檢」「上片前總體檢」（v1.50.0
        起原位保留一版轉址）依當時的承諾本版正式移除，改由一顆真正的
        「健檢中心」入口取代；「系列一致性」「章節健檢」「封面健檢」
        「發佈健檢」四顆也一併併入健檢中心——但併入的入口不是留在工具
        列上（那樣工具列會變成 10 顆，直接牴觸本版「11→6」的目標），而
        是搬進健檢中心自己的「檢查對象」區（見
        `gui/health_center_dialog.py` 的封面圖／發佈文字／系列影片三
        區）。這是相對 `docs/UI_ARCHITECTURE_2.0.md` D-3「舊按鈕原位保
        留一版」慣例的一個明確偏離，理由與其他做法記在
        `docs/ROADMAP_2.0.md` v1.51 項。
        """
        toolbar = ttk.Frame(self, padding=(10, 6))
        toolbar.pack(fill="x")
        current_theme = self.config_data.get("theme", "light")
        label = "切換為淺色" if current_theme == "dark" else "切換為深色"
        self.theme_btn = ttk.Button(
            toolbar, text=label, width=14, command=self._toggle_theme,
        )
        self.theme_btn.pack(side="right")
        ttk.Label(
            toolbar, text=f"v{APP_VERSION}", foreground="#888888",
        ).pack(side="right", padx=(0, 10))
        ttk.Label(
            toolbar, text="SRT 自動字幕生成與編輯工具",
            font=("Microsoft JhengHei", 11, "bold"),
        ).pack(side="left")

        # 功能按鈕區：以 grid 排列並自動換行，靠左對齊。
        tools = ttk.Frame(self, padding=(10, 0))
        tools.pack(fill="x", pady=(0, 6))
        for index, (text, width, command) in enumerate((
                ("審片助手（找片段）", 18, self._open_review_window),
                ("配樂助手（自動閃避）", 18, self._open_music_dialog),
                ("健檢中心", 12, self._open_health_center_dialog),
                ("品牌套版", 12, self._open_branding_dialog),
                ("音訊轉影片", 12, self._open_audiovis_dialog),
                ("即時查譯", 12, self._open_quicktranslate_panel))):
            ttk.Button(tools, text=text, width=width, command=command).grid(
                row=index // _TOOLS_PER_ROW, column=index % _TOOLS_PER_ROW,
                sticky="w", padx=(0, 8), pady=(0, 4))
        ttk.Separator(self, orient="horizontal").pack(fill="x")

    def _build_mode_section(self, parent):
        """模式切換區。"""
        frame = ttk.LabelFrame(parent, text="運作模式", padding=(10, 6))
        frame.pack(fill="x", pady=(0, 8))
        self.mode_var = tk.StringVar(value=MODE_TRANSCRIBE)
        # 左欄自 v1.52.0 起固定 330px 窄寬。`ttk.Radiobutton` 不像
        # `ttk.Label` 支援 `wraplength`（實測會丟 TclError: unknown
        # option "-wraplength"），改用明確換行斷字——文字內容完全不變，
        # 只是排成兩行避免撐開欄寬觸發水平捲軸（見
        # docs/UI_ARCHITECTURE_2.0.md B.2：左欄設計成「只捲設定」）。
        for value, text in (
                (MODE_TRANSCRIBE, "模式一：音訊轉錄\n（自動產生逐字稿與時間軸）"),
                (MODE_ALIGN, "模式二：文字稿對齊\n（貼上現成文字稿，自動對齊時間軸）"),
                (MODE_MANUAL, "模式三：手動字幕模式\n（從零建立字幕、手動標記時間）")):
            ttk.Radiobutton(
                frame, text=text, variable=self.mode_var, value=value,
                command=self._update_mode_state,
            ).pack(anchor="w", fill="x", pady=(0, 4))

    def _build_file_section(self, parent):
        """檔案選擇區（可一次選取多個檔案進行批次處理）。"""
        frame = ttk.LabelFrame(
            parent, text="影片 / 音訊檔案（可多選，以 ; 分隔）", padding=(10, 6))
        frame.pack(fill="x", pady=(0, 8))
        self.file_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.file_var).pack(
            side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(frame, text="瀏覽...", command=self._choose_file).pack(side="left")

    def _build_transcription_section(self, parent):
        """
        轉寫設定區（模式一相關）。

        v1.52.0：左欄固定 330px 窄寬，原本擠在同一列的「本地模型／語
        言」「兩個勾選＋API 金鑰」拆成獨立列，長說明文字改 wraplength
        換行，避免撐開欄寬（見 `_build_mode_section` 同一份理由）。控制
        項本身（變數名稱、預設值、行為）完全不變。
        """
        frame = ttk.LabelFrame(parent, text="轉寫設定（模式一）", padding=(10, 6))
        frame.pack(fill="x", pady=(0, 8))
        self.transcription_frame = frame
        transcription_cfg = self.config_data["transcription"]
        hint_wrap = _LEFT_COLUMN_WIDTH - 40

        row1 = ttk.Frame(frame)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="本地模型:").pack(side="left")
        self.model_var = tk.StringVar(value=transcription_cfg["model"])
        ttk.Combobox(
            row1, textvariable=self.model_var, width=10, state="readonly",
            values=["tiny", "base", "small", "medium", "large"],
        ).pack(side="left", padx=(4, 0))

        row1b = ttk.Frame(frame)
        row1b.pack(fill="x", pady=2)
        ttk.Label(row1b, text="語言:").pack(side="left")
        self.language_var = tk.StringVar(value=transcription_cfg["language"])
        ttk.Combobox(
            row1b, textvariable=self.language_var, width=10,
            values=["auto", "zh", "zh-TW", "en", "ja", "ko"],
        ).pack(side="left", padx=(4, 0))

        row2 = ttk.Frame(frame)
        row2.pack(fill="x", pady=2)
        self.use_api_var = tk.BooleanVar(value=transcription_cfg["use_api"])
        ttk.Checkbutton(
            row2, text="改用 OpenAI API", variable=self.use_api_var,
        ).pack(side="left")
        self.use_cache_var = tk.BooleanVar(
            value=transcription_cfg.get("use_cache", True))
        ttk.Checkbutton(
            row2, text="重用轉錄快取", variable=self.use_cache_var,
        ).pack(side="left", padx=(8, 0))

        row2b = ttk.Frame(frame)
        row2b.pack(fill="x", pady=2)
        ttk.Label(row2b, text="API 金鑰:").pack(side="left")
        self.api_key_var = tk.StringVar(value=transcription_cfg["api_key"])
        ttk.Entry(
            row2b, textvariable=self.api_key_var, show="*",
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))

        row3 = ttk.Frame(frame)
        row3.pack(fill="x", pady=2)
        ttk.Label(row3, text="本地 Python:").pack(anchor="w")
        row3b = ttk.Frame(frame)
        row3b.pack(fill="x", pady=2)
        self.python_path_var = tk.StringVar(
            value=transcription_cfg.get("python_path", ""))
        ttk.Entry(
            row3b, textvariable=self.python_path_var,
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(
            row3b, text="瀏覽...", command=self._choose_python,
        ).pack(side="left")
        ttk.Label(
            frame, foreground="#666666", wraplength=hint_wrap, justify="left",
            text="留空則自動偵測；指向已安裝 openai-whisper 的 python.exe 即可使用本地轉錄。",
        ).pack(anchor="w", pady=(2, 0))

        row4 = ttk.Frame(frame)
        row4.pack(fill="x", pady=(6, 2))
        ttk.Label(row4, text="轉寫提示:").pack(anchor="w")
        row4b = ttk.Frame(frame)
        row4b.pack(fill="x", pady=2)
        self.prompt_var = tk.StringVar(
            value=transcription_cfg.get("prompt", ""))
        ttk.Entry(
            row4b, textvariable=self.prompt_var,
        ).pack(side="left", fill="x", expand=True)
        ttk.Label(
            frame, foreground="#666666", wraplength=hint_wrap, justify="left",
            text=("可填入常出現的專有名詞、人名或易聽錯的詞彙（以空白或逗號分隔），"
                  "用於導正辨識結果。模式二會與文字稿一併使用。"),
        ).pack(anchor="w", pady=(2, 0))

    def _build_segmentation_section(self, parent):
        """
        斷句設定區。

        v1.52.0：原本擠 2-3 對「標籤＋數值」在同一列，330px 窄欄放不
        下，拆成每列一對；控制項本身不變。
        """
        frame = ttk.LabelFrame(parent, text="斷句設定", padding=(10, 6))
        frame.pack(fill="x", pady=(0, 8))
        self.segmentation_frame = frame
        seg = self.config_data["segmentation"]

        row1 = ttk.Frame(frame)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="中文單行上限:").pack(side="left")
        self.cjk_limit_var = tk.IntVar(value=seg["max_chars_cjk"])
        tk.Spinbox(
            row1, from_=4, to=40, width=6, textvariable=self.cjk_limit_var,
        ).pack(side="left", padx=(4, 4))
        ttk.Label(row1, text="字").pack(side="left")

        row1b = ttk.Frame(frame)
        row1b.pack(fill="x", pady=2)
        ttk.Label(row1b, text="英文單行上限:").pack(side="left")
        self.latin_limit_var = tk.IntVar(value=seg["max_chars_latin"])
        tk.Spinbox(
            row1b, from_=10, to=90, width=6, textvariable=self.latin_limit_var,
        ).pack(side="left", padx=(4, 4))
        ttk.Label(row1b, text="字母").pack(side="left")

        row2 = ttk.Frame(frame)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="最短秒數:").pack(side="left")
        self.min_dur_var = tk.DoubleVar(value=seg["min_duration"])
        tk.Spinbox(
            row2, from_=0.3, to=5.0, increment=0.1, width=5,
            textvariable=self.min_dur_var, format="%.1f",
        ).pack(side="left", padx=(4, 0))

        row2b = ttk.Frame(frame)
        row2b.pack(fill="x", pady=2)
        ttk.Label(row2b, text="最長秒數:").pack(side="left")
        self.max_dur_var = tk.DoubleVar(value=seg["max_duration"])
        tk.Spinbox(
            row2b, from_=2.0, to=15.0, increment=0.5, width=5,
            textvariable=self.max_dur_var, format="%.1f",
        ).pack(side="left", padx=(4, 0))

        row2c = ttk.Frame(frame)
        row2c.pack(fill="x", pady=2)
        ttk.Label(row2c, text="停頓秒數:").pack(side="left")
        self.pause_gap_var = tk.DoubleVar(value=seg["pause_gap"])
        tk.Spinbox(
            row2c, from_=0.2, to=2.0, increment=0.1, width=5,
            textvariable=self.pause_gap_var, format="%.1f",
        ).pack(side="left", padx=(4, 0))

        row3 = ttk.Frame(frame)
        row3.pack(fill="x", pady=2)
        ttk.Label(row3, text="時間軸微調:").pack(side="left")
        self.time_offset_var = tk.DoubleVar(value=seg.get("time_offset", 0.0))
        tk.Spinbox(
            row3, from_=-10.0, to=10.0, increment=0.1, width=6,
            textvariable=self.time_offset_var, format="%.1f",
        ).pack(side="left", padx=(4, 0))
        ttk.Label(
            frame, text="秒（正值整體延後、負值整體提前）",
            foreground="#666666", wraplength=_LEFT_COLUMN_WIDTH - 40,
            justify="left",
        ).pack(anchor="w", pady=(2, 0))

    def _build_transcript_section(self, parent):
        """文字稿輸入區（模式二相關）。"""
        frame = ttk.LabelFrame(parent, text="文字稿（模式二）", padding=(10, 6))
        frame.pack(fill="both", pady=(0, 8))
        self.transcript_frame = frame
        self.transcript_text = tk.Text(frame, height=6, wrap="word")
        self.transcript_text.pack(fill="both", expand=True)
        hint = "請於此貼上現成逐字稿，系統會依語音長度與停頓自動分配時間軸。"
        ttk.Label(
            frame, text=hint, foreground="#666666",
            wraplength=_LEFT_COLUMN_WIDTH - 40, justify="left",
        ).pack(anchor="w", pady=(4, 0))

    def _build_automation_section(self, parent):
        """
        一鍵自動化輸出設定區：勾選格式與燒錄後，「一鍵完成」全程免對話框。

        v1.52.0：原本擠在中欄一列的內容改拆成多列，理由同
        `_build_export_section`（中欄寬度只剩約 630px，不再是 v1.x 的
        整頁寬）；控制項本身、config 欄位完全不變。
        """
        frame = ttk.LabelFrame(parent, text="自動化輸出（一鍵完成用）", padding=(10, 6))
        frame.pack(fill="x", pady=(0, 8))
        self.automation_frame = frame
        automation = self.config_data["automation"]

        row1 = ttk.Frame(frame)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="自動匯出:").pack(side="left")
        self.auto_export_vars = {}
        for ext in (".srt", ".vtt", ".ass", ".txt"):
            key = f"export_{ext.lstrip('.')}"
            var = tk.BooleanVar(value=bool(automation.get(key)))
            self.auto_export_vars[key] = var
            ttk.Checkbutton(
                row1, text=ext.lstrip(".").upper(), variable=var,
                command=self._collect_automation_config,
            ).pack(side="left", padx=(4, 0))

        row1b = ttk.Frame(frame)
        row1b.pack(fill="x", pady=2)
        self.auto_burn_var = tk.BooleanVar(value=bool(automation.get("burn_video")))
        ttk.Checkbutton(
            row1b, text="燒錄硬字幕影片", variable=self.auto_burn_var,
            command=self._collect_automation_config,
        ).pack(side="left")

        row_ln = ttk.Frame(frame)
        row_ln.pack(fill="x", pady=2)
        self.auto_loudnorm_var = tk.BooleanVar(
            value=bool(automation.get("loudnorm")))
        ttk.Checkbutton(
            row_ln, text="燒錄時響度正規化", variable=self.auto_loudnorm_var,
            command=self._collect_automation_config,
        ).pack(side="left")
        ttk.Label(row_ln, text="目標:").pack(side="left", padx=(8, 2))
        self.auto_loudnorm_target_var = tk.DoubleVar(
            value=float(automation.get("loudnorm_target", -14.0)))
        tk.Spinbox(
            row_ln, from_=-30.0, to=-8.0, increment=0.5, width=6,
            textvariable=self.auto_loudnorm_target_var, format="%.1f",
            command=self._collect_automation_config,
        ).pack(side="left")
        ttk.Label(
            frame, text="LUFS（YouTube 標準 -14；音量偏小的素材建議勾選）",
            foreground="#666666", wraplength=580, justify="left",
        ).pack(anchor="w", pady=(0, 2))

        row2 = ttk.Frame(frame)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="輸出資料夾:").pack(side="left")
        self.auto_output_dir_var = tk.StringVar(
            value=automation.get("output_dir", ""))
        ttk.Entry(row2, textvariable=self.auto_output_dir_var).pack(
            side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(
            row2, text="瀏覽...", command=self._choose_output_dir,
        ).pack(side="left")
        ttk.Label(
            frame, foreground="#666666",
            text="留空＝輸出到來源檔資料夾。輸出檔自動以來源檔名命名，不會跳出任何對話框。",
        ).pack(anchor="w", pady=(2, 0))

    def _build_action_section(self, parent):
        """
        生成 / 匯出 / 燒錄按鈕與狀態列。

        v1.52.0：主鈕、進度條、狀態列原本擠一列，中欄在 minsize
        980x560（右欄收合後仍只有約 650px 寬，扣掉此時中欄自己的垂直
        捲軸又更窄）放不下這一整列（實測「一鍵完成」按鈕本身文字就要
        不少寬度）；拆成兩列讓兩顆主鈕永遠不必跟進度條搶寬度。
        """
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=(0, 8))
        self.action_frame = frame

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x")
        self.generate_btn = ttk.Button(
            btn_row, text="開始生成字幕", width=16, command=self._on_generate,
        )
        self.generate_btn.pack(side="left")
        self.auto_btn = ttk.Button(
            btn_row, text="一鍵完成（生成＋匯出＋燒錄）", width=26,
            command=self._on_auto_run,
        )
        self.auto_btn.pack(side="left", padx=(6, 0))

        # 進度條：可在 determinate（有百分比）與 indeterminate（跑馬燈）兩種模式切換。
        # 預設為 determinate；無法估算時切換為 indeterminate。
        progress_row = ttk.Frame(frame)
        progress_row.pack(fill="x", pady=(4, 0))
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress = ttk.Progressbar(
            progress_row, mode="determinate", length=180, maximum=100.0,
            variable=self.progress_var,
        )
        self.progress.pack(side="left")
        self.progress_label_var = tk.StringVar(value="")
        ttk.Label(progress_row, textvariable=self.progress_label_var, width=6,
                 anchor="w").pack(side="left", padx=(6, 0))

        self.status_var = tk.StringVar(value="就緒。")
        ttk.Label(parent, textvariable=self.status_var, foreground="#1a5fb4",
                 anchor="w").pack(fill="x")

    def _build_cue_list(self, parent):
        """
        字幕清單（生成結果）。

        v1.52.0：中欄自 v1.52.0 起包在 ScrollableFrame 裡（見
        `_build_widgets`——只在 minsize 980x560 這種極窄情形才會真的觸
        發捲動），`expand=True` 對「不受高度限制的捲動內容」沒有作用
        （它只在父容器本身有固定高度、有剩餘空間可分配時才有效），所以
        改用固定列數 `height=16`（原本 8）撐出可視高度——1400x800 實測
        仍完整可見、不需捲動；接近但不強求架構文件原型的 19 列（原型是
        真的用剩餘空間動態撐滿，這裡改用可預期的固定值換取「minsize 時
        還是拿得到自動化輸出」的正確性，屬本版明確的偏離規劃記錄）。
        """
        frame = ttk.LabelFrame(parent, text="字幕清單（雙擊可編輯）", padding=(6, 6))
        frame.pack(fill="both", pady=(8, 0))

        columns = ("index", "time", "text")
        self.cue_tree = ttk.Treeview(
            frame, columns=columns, show="headings", height=16,
        )
        self.cue_tree.heading("index", text="#")
        self.cue_tree.heading("time", text="時間")
        self.cue_tree.heading("text", text="字幕內容")
        self.cue_tree.column("index", width=40, anchor="center")
        self.cue_tree.column("time", width=180, anchor="center")
        self.cue_tree.column("text", width=320, anchor="w")

        scrollbar = ttk.Scrollbar(
            frame, orient="vertical", command=self.cue_tree.yview)
        self.cue_tree.configure(yscrollcommand=scrollbar.set)
        self.cue_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.cue_tree.bind("<<TreeviewSelect>>", self._on_cue_selected)
        # 雙擊任一列即進入編輯對話框。
        self.cue_tree.bind("<Double-1>", self._on_cue_double_click)

    def _build_cue_edit_controls(self, parent):
        """
        字幕列操作按鈕：新增、編輯、刪除、上移、下移、清空、尋找取代、
        翻譯字幕、匯入字幕、字幕健檢。

        v1.52.0：10 顆按鈕擠一列實測需要約 1068px，中欄在 1400x800 只
        分到 630px——不只裁切，後面幾顆會被 pack 擠到寬度 1px 形同消失
        （比裁切更嚴重，等於功能整個不見）。拆成兩列解決，10 顆按鈕、
        command、對應功能一個不少。
        """
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=(4, 0))
        self.cue_edit_frame = frame

        row1 = ttk.Frame(frame)
        row1.pack(fill="x", pady=(0, 2))
        ttk.Button(row1, text="新增字幕", width=10,
                  command=self._on_add_cue).pack(side="left", padx=2)
        ttk.Button(row1, text="編輯選取", width=10,
                  command=self._on_edit_cue).pack(side="left", padx=2)
        ttk.Button(row1, text="刪除選取", width=10,
                  command=self._on_delete_cue).pack(side="left", padx=2)
        ttk.Button(row1, text="上移", width=6,
                  command=lambda: self._on_move_cue(-1)).pack(side="left", padx=2)
        ttk.Button(row1, text="下移", width=6,
                  command=lambda: self._on_move_cue(1)).pack(side="left", padx=2)

        row2 = ttk.Frame(frame)
        row2.pack(fill="x")
        ttk.Button(row2, text="清空清單", width=10,
                  command=self._on_clear_cues).pack(side="left", padx=2)
        ttk.Button(row2, text="尋找取代", width=10,
                  command=self._on_find_replace).pack(side="left", padx=2)
        ttk.Button(row2, text="翻譯字幕", width=10,
                  command=self._open_translate_dialog).pack(side="left", padx=2)
        ttk.Button(row2, text="匯入字幕", width=10,
                  command=self._import_subtitles).pack(side="left", padx=2)
        ttk.Button(row2, text="字幕健檢", width=10,
                  command=self._open_subtitle_check_dialog).pack(
            side="left", padx=2)

    def _build_export_section(self, parent):
        """
        匯出與燒錄區：多格式匯出與影片字幕燒錄。

        v1.52.0：中欄寬度是「視窗寬 - 左欄 330 - 右欄 420」，1400x800 時
        約 630px，原本 7 顆按鈕擠一列（實測需求約 996px）會超出中欄寬
        度、被裁掉——這正是 `docs/UI_AUDIT_2.0.md` 點名的水平裁切問題在
        新版中欄重演。拆成兩列（格式匯出／影片動作）解決，按鈕本身、
        command、disabled 狀態管理完全不變。
        """
        frame = ttk.LabelFrame(parent, text="匯出與燒錄", padding=(10, 6))
        frame.pack(fill="x", pady=(8, 0))
        self.export_frame = frame

        row_fmt = ttk.Frame(frame)
        row_fmt.pack(fill="x", pady=(0, 4))
        self.export_btn_srt = ttk.Button(
            row_fmt, text="匯出 SRT", width=11,
            command=lambda: self._on_export(".srt"), state="disabled",
        )
        self.export_btn_srt.pack(side="left", padx=2)
        self.export_btn_vtt = ttk.Button(
            row_fmt, text="匯出 VTT", width=11,
            command=lambda: self._on_export(".vtt"), state="disabled",
        )
        self.export_btn_vtt.pack(side="left", padx=2)
        self.export_btn_ass = ttk.Button(
            row_fmt, text="匯出 ASS", width=11,
            command=lambda: self._on_export(".ass"), state="disabled",
        )
        self.export_btn_ass.pack(side="left", padx=2)
        self.export_btn_txt = ttk.Button(
            row_fmt, text="匯出 TXT", width=11,
            command=lambda: self._on_export(".txt"), state="disabled",
        )
        self.export_btn_txt.pack(side="left", padx=2)

        row_vid = ttk.Frame(frame)
        row_vid.pack(fill="x")
        self.burn_btn = ttk.Button(
            row_vid, text="燒錄字幕到影片", width=16,
            command=self._on_burn, state="disabled",
        )
        self.burn_btn.pack(side="left", padx=2)
        self.jumpcut_btn = ttk.Button(
            row_vid, text="自動跳剪停頓", width=13,
            command=self._open_jumpcut_dialog, state="disabled",
        )
        self.jumpcut_btn.pack(side="left", padx=2)
        self.retakes_btn = ttk.Button(
            row_vid, text="重複片段偵測", width=13,
            command=self._open_retakes_dialog, state="disabled",
        )
        self.retakes_btn.pack(side="left", padx=2)

    def _build_preview_section(self, parent):
        """
        即時字幕預覽。

        v1.52.0：畫布縮小為 392x200（見 `gui/preview_panel.py`）放進
        420px 右欄；LabelFrame 水平 padding 從 8 收到 4，避免「畫布寬
        + 邊框」超出右欄可用寬度（實測差 10px，Xvfb 通用版面掃描量出來
        的，不是用看的）。
        """
        frame = ttk.LabelFrame(parent, text="即時字幕預覽", padding=(4, 8))
        frame.pack(fill="x")
        self.preview = PreviewPanel(frame)
        self.preview.pack()

    def _build_style_section(self, parent):
        """字幕視覺調整面板。"""
        self.style_panel = StylePanel(
            parent, self.config_data["subtitle_style"], self._on_style_change,
        )
        self.style_panel.pack(fill="x", pady=(10, 0))

    def _build_preset_section(self, parent):
        """習慣設定區。"""
        frame = ttk.LabelFrame(parent, text="習慣設定（樣式組合）", padding=(8, 6))
        frame.pack(fill="x", pady=(0, 8))

        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Label(row, text="目前樣式:").pack(side="left")
        self.preset_var = tk.StringVar(value=self.config_data["active_preset"])
        self.preset_box = ttk.Combobox(
            row, textvariable=self.preset_var, state="readonly", width=16,
            values=sorted(self.config_data["presets"].keys()),
        )
        self.preset_box.pack(side="left", padx=(0, 6))
        self.preset_box.bind(
            "<<ComboboxSelected>>", lambda _e: self._apply_preset())

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x", pady=(6, 0))
        ttk.Button(
            btn_row, text="另存新樣式", command=self._save_new_preset,
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            btn_row, text="更新目前樣式", command=self._update_preset,
        ).pack(side="left", padx=4)
        ttk.Button(
            btn_row, text="刪除", command=self._delete_preset,
        ).pack(side="left", padx=4)

    # ==================================================================
    # 模式與預覽
    # ==================================================================
    def _update_mode_state(self):
        """依目前模式只顯示該模式需要調整的設定區塊。"""
        mode = self.mode_var.get()
        # 三模式皆隱藏所有可變區塊後，再依模式顯示需要的。
        self.transcription_frame.pack_forget()
        self.transcript_frame.pack_forget()

        if mode == MODE_TRANSCRIBE:
            self.transcription_frame.pack(
                fill="x", pady=(0, 8), before=self.segmentation_frame)
            self.generate_btn.configure(text="開始生成字幕")
            self.auto_btn.configure(state="normal")
        elif mode == MODE_ALIGN:
            # 左欄自 v1.52.0 起只剩設定區塊，transcript_frame 是最後一
            # 個，append 到 interior 末端即為正確位置（不再需要 before=
            # 錨定；自動化輸出已搬到中欄，不再是左欄的鄰居）。
            self.transcript_frame.pack(fill="both", pady=(0, 8))
            self.generate_btn.configure(text="開始生成字幕")
            self.auto_btn.configure(state="normal")
        else:
            # 手動模式：不需轉寫與文字稿，按鈕改為提示直接編輯字幕清單。
            self.generate_btn.configure(text="清空並進入手動編輯")
            self.auto_btn.configure(state="disabled")

    def _open_review_window(self):
        """開啟審片助手：以第一個選取檔案為素材；未選檔時先跳檔案選擇。"""
        files = self._selected_files()
        media_path = files[0] if files else ""
        if not media_path or not os.path.exists(media_path):
            initial_dir = self.config_data.get("last_dir") or os.getcwd()
            media_path = filedialog.askopenfilename(
                title="選擇要審片的影片或音訊檔", initialdir=initial_dir,
                filetypes=MEDIA_FILETYPES,
            )
            if not media_path:
                return
            self.file_var.set(media_path)
        # 帶入最新的轉寫設定（模型、語言、API 等），與主流程共用。
        self._collect_transcription_config()
        ReviewWindow(self, self.config_data, media_path)

    def _open_music_dialog(self):
        """開啟配樂助手：以第一個選取檔案為預設影片（可留空自行選擇）。"""
        files = self._selected_files()
        video_path = files[0] if files and os.path.exists(files[0]) else ""
        MusicDuckingDialog(self, self.config_data, video_path)

    def _open_health_center_dialog(self):
        """
        健檢中心：v1.50.0 併音訊／字幕／總體檢三窗，v1.51.0 再併發佈資訊／
        封面／章節三窗（工具列 11→6，見 `_build_toolbar` 的說明）。

        字幕直接沿用主視窗已經有的那一份，使用者不必再挑一次檔案；
        沒有字幕、沒有選影片時對話框會自動略過對應的檢查——健檢中心對
        象區的封面圖／發佈文字／系列影片仍要在對話框內另外加入，因為
        那些對象與主視窗的「目前選取檔案」語意不同（一個是影片，一個
        是圖片或純文字）。
        """
        files = self._selected_files()
        media_path = files[0] if files and os.path.exists(files[0]) else ""

        def on_fixed(new_cues):
            self.cues = new_cues
            self.apply_text_edits()

        HealthCenterDialog(self, self.config_data, media_path=media_path,
                           cues=list(getattr(self, "cues", []) or []),
                           on_fixed=on_fixed)

    def _open_branding_dialog(self):
        """開啟品牌套版：以第一個選取檔案為預設影片（可留空自行選擇）。"""
        files = self._selected_files()
        media_path = files[0] if files and os.path.exists(files[0]) else ""
        BrandingDialog(self, self.config_data, media_path)

    def _open_audiovis_dialog(self):
        """開啟音訊轉影片：以第一個選取檔案為預設音訊（可留空自行選擇）。"""
        files = self._selected_files()
        media_path = files[0] if files and os.path.exists(files[0]) else ""
        AudioVisDialog(self, self.config_data, media_path)

    def _on_style_change(self, style):
        """樣式面板變動時：更新設定、即時存檔、重繪預覽。"""
        self.config_data["subtitle_style"] = style
        self._save_config_silently()
        self.preview.update_style(style)

    def _refresh_preview(self):
        """以目前選取字幕（或範例文字）重繪預覽。"""
        style = self.config_data["subtitle_style"]
        text = self._current_preview_text()
        self.preview.render(text, style)

    def _current_preview_text(self):
        """取得目前要預覽的文字。"""
        selection = self.cue_tree.selection() if hasattr(self, "cue_tree") else ()
        if selection:
            item = self.cue_tree.item(selection[0])
            return item["values"][2]
        return "字幕預覽範例文字"

    def _on_cue_selected(self, _event):
        """字幕清單選取變動時更新預覽。"""
        self._refresh_preview()

    def _on_cue_double_click(self, _event):
        """雙擊字幕列：直接開啟編輯對話框。"""
        self._on_edit_cue()

    # ==================================================================
    # 字幕列編輯（模式三主要使用，其他模式也可用以微調）
    # ==================================================================
    def _on_add_cue(self):
        """新增一筆空白字幕；時間預設接在最後一句之後。"""
        if self.cues:
            last_end = max(cue["end"] for cue in self.cues)
            start = last_end + 0.5
        else:
            start = 0.0
        cue = {"start": start, "end": start + 2.0, "text": ""}
        dialog = CueEditDialog(self, cue, title="新增字幕")
        if dialog.result is None:
            return
        new_cue = dialog.result
        self.cues.append(new_cue)
        self._sort_and_repopulate(select_text=new_cue["text"])
        self._update_export_state()
        self.status_var.set("已新增字幕。")

    def _on_edit_cue(self):
        """編輯目前選取的字幕。"""
        index = self._selected_cue_index()
        if index is None:
            return
        dialog = CueEditDialog(self, self.cues[index], title="編輯字幕")
        if dialog.result is None:
            return
        self.cues[index] = dialog.result
        self._sort_and_repopulate(select_text=self.cues[index]["text"])
        self.status_var.set("已更新字幕。")

    def _on_delete_cue(self):
        """刪除選取的字幕。"""
        index = self._selected_cue_index()
        if index is None:
            return
        if not messagebox.askyesno("確認刪除", "確定刪除此字幕？"):
            return
        del self.cues[index]
        self._sort_and_repopulate()
        self._update_export_state()
        self.status_var.set("已刪除字幕。")

    def _on_move_cue(self, direction):
        """上移 / 下移目前選取的字幕（不改變時間，僅調整清單順序）。"""
        index = self._selected_cue_index()
        if index is None:
            return
        target = index + direction
        if target < 0 or target >= len(self.cues):
            return
        self.cues[index], self.cues[target] = self.cues[target], self.cues[index]
        # 移動後保留選取在原本字幕上。
        self._populate_cue_list(self.cues)
        children = self.cue_tree.get_children()
        if 0 <= target < len(children):
            self.cue_tree.selection_set(children[target])
            self.cue_tree.focus(children[target])
        self._refresh_preview()

    def _on_clear_cues(self):
        """清空字幕清單。"""
        if not self.cues:
            return
        if not messagebox.askyesno("確認清空", "確定清空所有字幕？"):
            return
        self.cues = []
        self._populate_cue_list([])
        self._update_export_state()
        self.status_var.set("已清空字幕清單。")

    def _on_find_replace(self):
        """開啟尋找與取代對話框（單一實例，重複點擊時帶到最前）。"""
        if not self.cues:
            messagebox.showinfo("提示", "目前沒有字幕可搜尋，請先生成或載入字幕。")
            return
        existing = getattr(self, "_replace_dialog", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_set()
            return
        self._replace_dialog = ReplaceDialog(self)

    def _open_quicktranslate_panel(self):
        """開啟即時查譯浮動視窗：獨立視窗、單例，關閉是隱藏不是銷毀。"""
        panel = getattr(self, "_quicktranslate_panel", None)
        if panel is not None and panel.winfo_exists():
            panel.show()
            return
        self._quicktranslate_panel = QuickTranslatePanel(self, self.config_data)

    def _open_translate_dialog(self):
        """開啟字幕翻譯對話框：需先有字幕清單才能翻譯。"""
        if not self.cues:
            messagebox.showinfo("提示", "目前沒有字幕可翻譯，請先生成字幕。")
            return

        def on_done(new_cues):
            self.cues = new_cues
            self.apply_text_edits()
            self.status_var.set("已套用翻譯結果。")

        files = self._selected_files()
        media_path = files[0] if files and os.path.exists(files[0]) else ""
        TranslateDialog(self, self.config_data, self.cues, on_done=on_done,
                        media_path=media_path)

    def _import_subtitles(self):
        """
        匯入既有字幕檔（SRT/VTT）：接上既有的編修／樣式／翻譯／燒錄管線。

        免去使用者只能開記事本手動改字幕檔的窘境（下載的 YouTube 自動字幕、
        其他工具產出的字幕檔都能直接匯入沿用）。已有字幕清單時先確認是否
        取代，避免誤蓋掉手上正在編輯的內容。
        """
        initial_dir = self.config_data.get("last_dir") or os.getcwd()
        path = filedialog.askopenfilename(
            title="選擇要匯入的字幕檔", initialdir=initial_dir,
            filetypes=IMPORT_FILETYPES,
        )
        if not path:
            return
        if self.cues:
            if not messagebox.askyesno(
                    "確認匯入",
                    f"匯入將取代目前的 {len(self.cues)} 句字幕，繼續？"):
                return
        try:
            loaded = load_subtitle_file(path)
        except Exception as exc:
            show_friendly_error(self, "匯入失敗", exc)
            return
        self.cues = loaded["cues"]
        self.config_data["last_dir"] = os.path.dirname(path)
        self._save_config_silently()
        self._populate_cue_list(self.cues)
        self._update_export_state()
        self._refresh_preview()
        message = f"已匯入 {len(self.cues)} 句字幕"
        if loaded["skipped"]:
            message += f"（略過 {loaded['skipped']} 段無法解析、編碼 {loaded['encoding']}）"
        else:
            message += f"（編碼 {loaded['encoding']}）"
        self.status_var.set(message)

    def _open_subtitle_check_dialog(self):
        """
        原「字幕健檢」按鈕：v1.50.0 起改開健檢中心。

        字幕健檢原本不需要選影片就能跑純文字檢查，健檢中心保留這個
        能力——沒有選影片時只會略過需要媒體檔的項目，不會擋住這裡的
        呼叫。按鈕原位保留一版，下一版才移除
        （docs/UI_ARCHITECTURE_2.0.md D-3）。
        """
        if not self.cues:
            messagebox.showinfo("提示", "目前沒有字幕可健檢，請先生成或匯入字幕。")
            return

        def on_fixed(new_cues):
            self.cues = new_cues
            self.apply_text_edits()

        files = self._selected_files()
        media_path = files[0] if files and os.path.exists(files[0]) else ""
        HealthCenterDialog(self, self.config_data, media_path=media_path,
                           cues=self.cues, on_fixed=on_fixed)
        self.status_var.set("「字幕健檢」已整併至健檢中心。")

    def _open_jumpcut_dialog(self):
        """開啟自動跳剪：依目前字幕找出句間停頓，一次剪掉整支影片的冷場。"""
        if not self.cues:
            messagebox.showinfo("提示", "目前沒有字幕，請先生成或匯入字幕。")
            return
        files = self._selected_files()
        media_path = files[0] if files else ""

        def on_done(new_cues):
            self.cues = new_cues
            self.apply_text_edits()

        JumpCutDialog(self, self.config_data, self.cues,
                     media_path=media_path, on_done=on_done)

    def _open_retakes_dialog(self):
        """開啟重複片段偵測：找出同一句話講了好幾次的候選，勾選後剪掉。"""
        if not self.cues:
            messagebox.showinfo("提示", "目前沒有字幕，請先生成或匯入字幕。")
            return
        files = self._selected_files()
        media_path = files[0] if files else ""

        def on_done(new_cues):
            self.cues = new_cues
            self.apply_text_edits()

        RetakesDialog(self, self.config_data, self.cues,
                     media_path=media_path, on_done=on_done)

    def apply_text_edits(self):
        """字幕文字被批次修改後刷新清單與預覽（時間軸不變，不需重排序）。"""
        self._populate_cue_list(self.cues)
        self._refresh_preview()

    def _selected_cue_index(self):
        """取得選取項目對應到 self.cues 的索引；無選取則回傳 None。"""
        selection = self.cue_tree.selection()
        if not selection:
            messagebox.showinfo("提示", "請先在字幕清單中選取一列。")
            return None
        children = self.cue_tree.get_children()
        try:
            return children.index(selection[0])
        except ValueError:
            return None

    def _sort_and_repopulate(self, select_text=None):
        """依開始時間排序 self.cues 後重新填入清單，可選取特定字幕。"""
        self.cues.sort(key=lambda cue: cue["start"])
        for number, cue in enumerate(self.cues, start=1):
            cue["index"] = number
        self._populate_cue_list(self.cues)
        if select_text is not None:
            for item, cue in zip(self.cue_tree.get_children(), self.cues):
                if cue["text"] == select_text:
                    self.cue_tree.selection_set(item)
                    self.cue_tree.focus(item)
                    break
        self._refresh_preview()

    # ==================================================================
    # 習慣設定（preset）管理
    # ==================================================================
    def _current_profile(self):
        """收集介面上目前的字幕樣式與斷句設定。"""
        self.config_data["subtitle_style"] = self.style_panel.get_style()
        self._collect_segmentation_config()
        return make_profile(
            self.config_data["subtitle_style"],
            self.config_data["segmentation"],
        )

    def _load_segmentation_into_ui(self):
        """把 config_data 中的斷句設定回填到斷句設定區的控制項。"""
        seg = self.config_data["segmentation"]
        self.cjk_limit_var.set(seg["max_chars_cjk"])
        self.latin_limit_var.set(seg["max_chars_latin"])
        self.min_dur_var.set(seg["min_duration"])
        self.max_dur_var.set(seg["max_duration"])
        self.pause_gap_var.set(seg["pause_gap"])
        self.time_offset_var.set(seg.get("time_offset", 0.0))

    def _refresh_preset_box(self, selected):
        """重新整理習慣設定下拉選單並選取指定名稱。"""
        self.preset_box.configure(
            values=sorted(self.config_data["presets"].keys()))
        self.preset_var.set(selected)

    def _apply_preset(self):
        """套用下拉選單中選取的習慣設定。"""
        name = self.preset_var.get()
        preset = self.config_data["presets"].get(name)
        if not preset:
            return
        self.config_data["subtitle_style"] = dict(preset["subtitle_style"])
        self.config_data["segmentation"] = dict(preset["segmentation"])
        self.config_data["active_preset"] = name
        self.style_panel.set_style(self.config_data["subtitle_style"])
        self._load_segmentation_into_ui()
        self.preview.update_style(self.config_data["subtitle_style"])
        self._refresh_preview()
        self._save_config_silently()
        self.status_var.set(f"已套用習慣設定：{name}")

    def _save_new_preset(self):
        """以目前介面設定另存為一組新的習慣設定。"""
        name = simpledialog.askstring(
            "另存新樣式", "請輸入樣式名稱:", parent=self)
        if name is None:
            return
        name = name.strip()
        if not name:
            messagebox.showwarning("提示", "樣式名稱不可為空白。")
            return
        if name in self.config_data["presets"]:
            if not messagebox.askyesno(
                    "確認覆蓋", f"樣式「{name}」已存在，要覆蓋嗎？"):
                return
        self.config_data["presets"][name] = self._current_profile()
        self.config_data["active_preset"] = name
        self._refresh_preset_box(name)
        self._save_config_silently()
        self.status_var.set(f"已儲存習慣設定：{name}")

    def _update_preset(self):
        """以目前介面設定更新下拉選單中選取的習慣設定。"""
        name = self.preset_var.get()
        if name not in self.config_data["presets"]:
            return
        self.config_data["presets"][name] = self._current_profile()
        self._save_config_silently()
        self.status_var.set(f"已更新習慣設定：{name}")

    def _delete_preset(self):
        """刪除選取的習慣設定（至少保留一組）。"""
        name = self.preset_var.get()
        presets = self.config_data["presets"]
        if name not in presets:
            return
        if len(presets) <= 1:
            messagebox.showinfo("提示", "至少需保留一組習慣設定，無法刪除。")
            return
        if not messagebox.askyesno("確認刪除", f"確定要刪除習慣設定「{name}」？"):
            return
        del presets[name]
        fallback = sorted(presets.keys())[0]
        self._refresh_preset_box(fallback)
        self._apply_preset()
        self.status_var.set(f"已刪除習慣設定：{name}")

    # ==================================================================
    # 字幕生成流程
    # ==================================================================
    def _choose_file(self):
        """開啟檔案選擇器；可一次選取多個檔案進行批次處理。"""
        initial_dir = self.config_data.get("last_dir") or os.getcwd()
        paths = filedialog.askopenfilenames(
            title="選擇影片或音訊檔（可多選）", initialdir=initial_dir,
            filetypes=MEDIA_FILETYPES,
        )
        if paths:
            self.file_var.set("; ".join(paths))
            self.config_data["last_dir"] = os.path.dirname(paths[0])
            self._save_config_silently()

    def _choose_output_dir(self):
        """選擇自動化輸出資料夾。"""
        path = filedialog.askdirectory(title="選擇輸出資料夾")
        if path:
            self.auto_output_dir_var.set(path)
            self._collect_automation_config()

    def _selected_files(self):
        """解析檔案欄位，回傳以 ; 分隔的檔案路徑清單。"""
        raw = self.file_var.get()
        return [part.strip() for part in raw.split(";") if part.strip()]

    def _choose_python(self):
        """選擇外部 Python 直譯器（供本地轉錄使用）。"""
        path = filedialog.askopenfilename(
            title="選擇已安裝 whisper 的 python.exe",
            filetypes=[("Python 執行檔", "python*.exe"), ("所有檔案", "*.*")],
        )
        if path:
            self.python_path_var.set(path)

    def _collect_transcription_config(self):
        """把介面上的轉寫設定寫回設定資料並存檔。"""
        self.config_data["transcription"] = {
            "model": self.model_var.get(),
            "language": self.language_var.get().strip() or "auto",
            "use_api": bool(self.use_api_var.get()),
            "api_key": self.api_key_var.get().strip(),
            "python_path": self.python_path_var.get().strip(),
            "prompt": self.prompt_var.get().strip(),
            "use_cache": bool(self.use_cache_var.get()),
        }
        self._save_config_silently()

    def _collect_segmentation_config(self):
        """把介面上的斷句設定寫回設定資料並存檔，數值不合理時做夾限校正。"""
        seg = dict(self.config_data["segmentation"])

        def safe_get(var, fallback):
            try:
                return var.get()
            except (tk.TclError, ValueError):
                return fallback

        cjk = int(safe_get(self.cjk_limit_var, seg["max_chars_cjk"]))
        latin = int(safe_get(self.latin_limit_var, seg["max_chars_latin"]))
        min_dur = float(safe_get(self.min_dur_var, seg["min_duration"]))
        max_dur = float(safe_get(self.max_dur_var, seg["max_duration"]))
        pause = float(safe_get(self.pause_gap_var, seg["pause_gap"]))
        offset = float(safe_get(self.time_offset_var, seg.get("time_offset", 0.0)))

        seg["max_chars_cjk"] = max(4, min(cjk, 40))
        seg["max_chars_latin"] = max(10, min(latin, 90))
        seg["min_duration"] = max(0.3, min(min_dur, max_dur))
        seg["max_duration"] = max(seg["min_duration"], min(max_dur, 15.0))
        seg["pause_gap"] = max(0.2, min(pause, 2.0))
        seg["time_offset"] = max(-10.0, min(offset, 10.0))

        self.config_data["segmentation"] = seg
        self._save_config_silently()

    def _collect_automation_config(self):
        """把介面上的自動化輸出設定寫回設定資料並存檔。"""
        automation = dict(self.config_data["automation"])
        for key, var in self.auto_export_vars.items():
            automation[key] = bool(var.get())
        automation["burn_video"] = bool(self.auto_burn_var.get())
        automation["loudnorm"] = bool(self.auto_loudnorm_var.get())
        try:
            automation["loudnorm_target"] = float(
                self.auto_loudnorm_target_var.get())
        except (tk.TclError, ValueError):
            pass  # 欄位輸入中可能暫時非數字，保留原值。
        automation["output_dir"] = self.auto_output_dir_var.get().strip()
        self.config_data["automation"] = automation
        self._save_config_silently()

    def _on_generate(self):
        """按下「開始生成字幕」（模式三則為清空進入手動編輯）。"""
        if self.is_processing:
            return
        mode = self.mode_var.get()

        if mode == MODE_MANUAL:
            # 模式三：清空現有清單並進入手動編輯流程。
            if self.cues and not messagebox.askyesno(
                    "確認清空", "進入手動編輯會清空目前字幕清單，繼續嗎？"):
                return
            self.cues = []
            self._populate_cue_list([])
            self._collect_segmentation_config()
            self._update_export_state()
            self.status_var.set(
                "已進入手動字幕模式，請按「新增字幕」開始建立字幕。")
            return

        files = self._selected_files()
        if not files or not os.path.exists(files[0]):
            messagebox.showerror("錯誤", "請先選擇有效的影片或音訊檔案。")
            return
        audio_path = files[0]
        if len(files) > 1:
            self.status_var.set(
                "已選多個檔案：「開始生成字幕」僅處理第一個；"
                "批次處理請改用「一鍵完成」。")

        transcript = ""
        if mode == MODE_ALIGN:
            transcript = self.transcript_text.get("1.0", "end").strip()
            if not transcript:
                messagebox.showerror("錯誤", "模式二需要先貼上文字稿。")
                return

        self._collect_transcription_config()
        self._collect_segmentation_config()

        self._set_processing(True)
        worker = threading.Thread(
            target=self._generate_worker,
            args=(mode, audio_path, transcript),
            daemon=True,
        )
        worker.start()

    def _on_auto_run(self):
        """按下「一鍵完成」：對所有選取檔案自動跑生成 → 匯出 → 燒錄。"""
        if self.is_processing:
            return
        mode = self.mode_var.get()
        if mode == MODE_MANUAL:
            return

        files = self._selected_files()
        if not files:
            messagebox.showerror("錯誤", "請先選擇影片或音訊檔案。")
            return
        missing = [path for path in files if not os.path.exists(path)]
        if missing:
            messagebox.showerror(
                "錯誤", "找不到以下檔案：\n" + "\n".join(missing))
            return

        transcript = ""
        if mode == MODE_ALIGN and len(files) == 1:
            # 單檔可直接用貼上的文字稿；留空則 pipeline 會找同名 .txt。
            transcript = self.transcript_text.get("1.0", "end").strip()

        self._collect_transcription_config()
        self._collect_segmentation_config()
        self._collect_automation_config()
        self.config_data["subtitle_style"] = self.style_panel.get_style()

        automation = self.config_data["automation"]
        wants_export = any(
            automation.get(f"export_{ext}") for ext in ("srt", "vtt", "ass", "txt"))
        if not wants_export and not automation.get("burn_video"):
            messagebox.showerror(
                "錯誤", "請先在「自動化輸出」勾選至少一種匯出格式或燒錄影片。")
            return
        if automation.get("burn_video") and not ffmpeg_available():
            messagebox.showerror(
                "找不到 ffmpeg",
                "燒錄字幕需要 ffmpeg。請依說明安裝 ffmpeg 並加入系統 PATH，"
                "或取消勾選「燒錄硬字幕影片」。")
            return

        self._set_processing(True)
        threading.Thread(
            target=self._auto_worker,
            args=(mode, files, transcript),
            daemon=True,
        ).start()

    def _auto_worker(self, mode, files, transcript):
        """背景執行緒：批次執行完整自動流程。"""
        try:
            def report(message, ratio=None):
                self.result_queue.put(("status", (message, ratio)))

            results = run_batch(
                files, self.config_data, mode=mode,
                transcript=transcript, report=report)
            self.result_queue.put(("auto_done", results))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("一鍵完成流程發生錯誤")
            self.result_queue.put(("error", exc))

    def _on_auto_done(self, results):
        """一鍵完成結束：載入最後一個成功檔案的字幕供檢視，並顯示總結。"""
        self._set_processing(False)
        succeeded = [item for item in results if item["ok"]]
        failed = [item for item in results if not item["ok"]]

        if succeeded:
            self.cues = succeeded[-1]["result"]["cues"]
            self._populate_cue_list(self.cues)
            self._update_export_state()
            self._refresh_preview()
            # v1.49.0 曾在這裡呼叫 scroll_into_view 把清單捲進視野，那是
            # 折疊線問題（docs/UI_AUDIT_2.0.md）修好前的權宜之計。v1.52.0
            # 三欄化後字幕清單在中欄永遠可見，不會再被捲出視窗，這個呼叫
            # 已不需要（結構修好，不必再靠捲動補救）。

        lines = []
        for item in succeeded:
            outputs = list(item["result"]["exports"])
            if item["result"]["burned"]:
                outputs.append(item["result"]["burned"])
            lines.append("✔ " + os.path.basename(item["path"]))
            lines.extend(f"　→ {path}" for path in outputs)
        for item in failed:
            lines.append(f"✘ {os.path.basename(item['path'])}：{item['error']}")

        summary = (f"一鍵完成：成功 {len(succeeded)}、失敗 {len(failed)}"
                   f"（共 {len(results)} 個檔案）。")
        self.status_var.set(summary)
        if failed:
            messagebox.showwarning("一鍵完成（部分失敗）",
                                   summary + "\n\n" + "\n".join(lines))
        else:
            messagebox.showinfo("一鍵完成", summary + "\n\n" + "\n".join(lines))

    def _generate_worker(self, mode, audio_path, transcript):
        """背景執行緒：實際進行轉寫或對齊。"""
        try:
            def report(message, ratio=None):
                """新版回呼簽名：(訊息, 0.0~1.0 或 None)。"""
                self.result_queue.put(("status", (message, ratio)))

            if mode == MODE_TRANSCRIBE:
                words = transcribe(audio_path, self.config_data, report)
                report("正在進行智慧斷句...", 0.97)
                cues = build_cues_from_words(
                    words, self.config_data["segmentation"])
            else:
                cues = align_transcript(
                    audio_path, transcript, self.config_data, report)

            if not cues:
                raise RuntimeError("未能產生任何字幕內容。")
            # 套用自動修正詞庫（存過的錯字規則，每次生成自動修）。
            cues, corrected = apply_corrections(
                cues, self.config_data.get("corrections"))
            if corrected:
                report(f"已自動修正 {corrected} 處慣性錯字", 0.99)
            self.result_queue.put(("done", cues))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("生成字幕時發生錯誤")
            self.result_queue.put(("error", exc))

    def _poll_queue(self):
        """主執行緒定時輪詢背景結果。"""
        try:
            while True:
                kind, payload = self.result_queue.get_nowait()
                if kind == "status":
                    # 新版 payload 為 (message, ratio)；舊版 payload 為單純字串。
                    if isinstance(payload, tuple):
                        message, ratio = payload
                    else:
                        message, ratio = payload, None
                    self.status_var.set(message)
                    self._update_progress(ratio)
                elif kind == "done":
                    self._on_generation_done(payload)
                elif kind == "auto_done":
                    self._on_auto_done(payload)
                elif kind == "error":
                    self._on_generation_error(payload)
                elif kind == "burn_done":
                    self._on_burn_done(payload)
                elif kind == "burn_error":
                    self._on_burn_error(payload)
                elif kind == "update":
                    self._prompt_update(payload)
                elif kind == "update_done":
                    self._on_update_done()
                elif kind == "update_error":
                    self._on_update_error(payload)
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

    def _on_generation_done(self, cues):
        """生成成功：填入字幕清單。"""
        self.cues = cues
        self._populate_cue_list(cues)
        self._set_processing(False)
        self.status_var.set(f"生成完成，共 {len(cues)} 句字幕。")
        self._update_export_state()
        children = self.cue_tree.get_children()
        if children:
            self.cue_tree.selection_set(children[0])
            self.cue_tree.focus(children[0])
        self._refresh_preview()
        # v1.49.0 曾在這裡呼叫 scroll_into_view，理由與 _on_auto_done 同
        # 一則註解——v1.52.0 三欄化後已不需要，見上方說明。

    def _on_generation_error(self, message):
        """生成失敗：顯示原因與解決方法。"""
        self._set_processing(False)
        self.status_var.set("生成失敗。")
        show_friendly_error(
            self, "生成失敗", message,
            on_install_ffmpeg=lambda: FfmpegInstallDialog(self))

    # ==================================================================
    # 自動更新
    # ==================================================================
    def _start_update_check(self):
        """於背景執行緒檢查是否有新版本。"""
        threading.Thread(target=self._update_check_worker, daemon=True).start()

    def _update_check_worker(self):
        """背景執行緒：查詢 GitHub 最新版本。"""
        info = check_for_update()
        if info:
            self.result_queue.put(("update", info))

    def _prompt_update(self, info):
        """偵測到新版本時詢問使用者是否更新。"""
        if not getattr(sys, "frozen", False):
            self.status_var.set(f"有新版本可用：{info['version']}（原始碼模式不自動更新）")
            return
        answer = messagebox.askyesno(
            "發現新版本",
            f"目前版本:v{APP_VERSION}\n"
            f"最新版本:{info['version']}\n\n是否立即下載並更新？",
        )
        if not answer:
            return
        self._set_processing(True)
        self.status_var.set("正在下載新版本...")
        threading.Thread(
            target=self._update_apply_worker, args=(info["url"],), daemon=True,
        ).start()

    def _update_apply_worker(self, url):
        """背景執行緒：下載並套用新版本。"""
        try:
            download_and_apply(
                url,
                progress_cb=lambda ratio: self.result_queue.put(
                    ("status", (f"正在下載新版本... {int(ratio * 100)}%",
                                ratio))),
            )
            self.result_queue.put(("update_done", None))
        except Exception as exc:
            logger.exception("套用更新時發生錯誤")
            self.result_queue.put(("update_error", str(exc)))

    def _on_update_done(self):
        """更新完成：提示重新啟動。"""
        self._set_processing(False)
        self.status_var.set("更新完成，請重新啟動程式。")
        messagebox.showinfo(
            "更新完成", "新版本已下載完成，請關閉並重新開啟程式以套用更新。")

    def _on_update_error(self, message):
        """更新失敗：顯示錯誤訊息。"""
        self._set_processing(False)
        self.status_var.set("更新失敗。")
        messagebox.showerror("更新失敗", message)

    def _populate_cue_list(self, cues):
        """把 cue 清單填入 Treeview。"""
        self.cue_tree.delete(*self.cue_tree.get_children())
        for number, cue in enumerate(cues, start=1):
            time_label = (f"{format_srt_timestamp(cue['start'])} → "
                          f"{format_srt_timestamp(cue['end'])}")
            self.cue_tree.insert(
                "", "end",
                values=(number, time_label, cue["text"]),
            )

    def _set_processing(self, processing):
        """切換處理中狀態（鎖定按鈕、進度條）。"""
        self.is_processing = processing
        if processing:
            self.generate_btn.configure(state="disabled", text="處理中...")
            self.auto_btn.configure(state="disabled")
            # 起始時先進入 indeterminate 模式並啟動跑馬燈，待收到 ratio 後改 determinate。
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)
            self.progress_label_var.set("")
        else:
            mode = self.mode_var.get()
            if mode == MODE_MANUAL:
                self.generate_btn.configure(
                    state="normal", text="清空並進入手動編輯")
                self.auto_btn.configure(state="disabled")
            else:
                self.generate_btn.configure(state="normal", text="開始生成字幕")
                self.auto_btn.configure(state="normal")
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress_var.set(0.0)
            self.progress_label_var.set("")

    def _update_progress(self, ratio):
        """根據 ratio 更新進度條顯示模式與百分比。"""
        if ratio is None:
            # 未提供 ratio：維持跑馬燈（若還沒處理中則略過）。
            if self.is_processing and str(self.progress.cget("mode")) == "determinate":
                self.progress.configure(mode="indeterminate")
                self.progress.start(12)
                self.progress_label_var.set("")
            return
        # 收到具體 ratio：切回 determinate 模式並顯示百分比。
        ratio = max(0.0, min(float(ratio), 1.0))
        if str(self.progress.cget("mode")) == "indeterminate":
            self.progress.stop()
            self.progress.configure(mode="determinate")
        self.progress_var.set(ratio * 100.0)
        self.progress_label_var.set(f"{int(ratio * 100)}%")

    # ==================================================================
    # 匯出與燒錄
    # ==================================================================
    def _update_export_state(self):
        """依目前是否有字幕，啟用或停用匯出 / 燒錄按鈕。"""
        state = "normal" if self.cues else "disabled"
        for btn in (self.export_btn_srt, self.export_btn_vtt,
                    self.export_btn_ass, self.export_btn_txt, self.burn_btn,
                    self.jumpcut_btn, self.retakes_btn):
            btn.configure(state=state)

    def _default_export_name(self, ext):
        """以來源檔名為基礎組出預設輸出檔名。"""
        files = self._selected_files()
        if files:
            return os.path.splitext(os.path.basename(files[0]))[0] + ext
        return f"字幕{ext}"

    def _on_export(self, ext):
        """匯出指定格式的字幕檔。"""
        if not self.cues:
            messagebox.showinfo("提示", "目前沒有可匯出的字幕。")
            return
        initial_dir = self.config_data.get("last_dir") or os.getcwd()
        path = filedialog.asksaveasfilename(
            title=f"儲存{ext.upper().lstrip('.')}字幕檔",
            initialdir=initial_dir,
            initialfile=self._default_export_name(ext),
            defaultextension=ext,
            filetypes=FORMAT_FILETYPES,
        )
        if not path:
            return
        # 同步最新樣式給 ASS 匯出使用。
        self.config_data["subtitle_style"] = self.style_panel.get_style()
        try:
            export(self.cues, path, style=self.config_data["subtitle_style"])
        except (OSError, ValueError) as exc:
            messagebox.showerror("匯出失敗", f"無法寫入檔案：{exc}")
            return
        self.status_var.set(f"已匯出:{path}")
        messagebox.showinfo("匯出完成", f"字幕檔已儲存至：\n{path}")

    def _on_burn(self):
        """把字幕燒錄進影片（hardsub via ffmpeg）。"""
        if not self.cues:
            messagebox.showinfo("提示", "目前沒有可燒錄的字幕。")
            return
        if not ffmpeg_available():
            messagebox.showerror(
                "找不到 ffmpeg",
                "燒錄字幕需要 ffmpeg。請依說明安裝 ffmpeg 並加入系統 PATH。")
            return
        # 先選擇來源影片（若主檔案欄已有路徑則預設使用第一個）。
        files = self._selected_files()
        video_path = files[0] if files else ""
        if not video_path or not os.path.exists(video_path):
            video_path = filedialog.askopenfilename(
                title="選擇要燒錄字幕的影片", filetypes=MEDIA_FILETYPES,
            )
        if not video_path:
            return
        # 詢問輸出路徑。
        initial_dir = self.config_data.get("last_dir") or os.getcwd()
        base = os.path.splitext(os.path.basename(video_path))[0]
        output_path = filedialog.asksaveasfilename(
            title="儲存燒錄字幕後的影片",
            initialdir=initial_dir,
            initialfile=f"{base}_subtitled.mp4",
            defaultextension=".mp4",
            filetypes=[("MP4 影片", "*.mp4"), ("所有檔案", "*.*")],
        )
        if not output_path:
            return

        self.config_data["subtitle_style"] = self.style_panel.get_style()
        self._set_processing(True)
        self.status_var.set("正在啟動 ffmpeg 燒錄字幕...")
        threading.Thread(
            target=self._burn_worker,
            args=(video_path, output_path, dict(self.cues)
                  if isinstance(self.cues, dict) else list(self.cues)),
            daemon=True,
        ).start()

    def _burn_worker(self, video_path, output_path, cues):
        """背景執行緒：呼叫 ffmpeg 燒錄字幕（依設定同步響度正規化）。"""
        try:
            automation = self.config_data.get("automation", {})
            loudnorm_target = None
            if automation.get("loudnorm"):
                from subtitle.audio import clamp_target
                loudnorm_target = clamp_target(
                    automation.get("loudnorm_target"))
            burn_subtitles(
                video_path=video_path,
                cues=cues,
                output_path=output_path,
                style=self.config_data["subtitle_style"],
                progress_cb=lambda ratio, msg: self.result_queue.put(
                    ("status", (msg, ratio))),
                loudnorm_target=loudnorm_target,
            )
            self.result_queue.put(("burn_done", output_path))
        except Exception as exc:
            logger.exception("燒錄字幕時發生錯誤")
            self.result_queue.put(("burn_error", exc))

    def _on_burn_done(self, output_path):
        """燒錄成功通知。"""
        self._set_processing(False)
        self.status_var.set(f"燒錄完成:{output_path}")
        messagebox.showinfo("燒錄完成", f"已輸出影片：\n{output_path}")

    def _on_burn_error(self, message):
        """燒錄失敗：顯示原因與解決方法。"""
        self._set_processing(False)
        self.status_var.set("燒錄失敗。")
        show_friendly_error(
            self, "燒錄失敗", message,
            on_install_ffmpeg=lambda: FfmpegInstallDialog(self))

    # ==================================================================
    # 設定儲存
    # ==================================================================
    def _save_config_silently(self):
        """靜默存檔；失敗時僅於狀態列提示，不中斷操作。"""
        try:
            save_config(self.config_data)
        except OSError as exc:
            self.status_var.set(f"設定儲存失敗：{exc}")

    def _on_close(self):
        """關閉視窗前保存設定。"""
        self.config_data["subtitle_style"] = self.style_panel.get_style()
        self._collect_transcription_config()
        self._collect_segmentation_config()
        self._collect_automation_config()
        self.destroy()


def main():
    """建立並執行應用程式。"""
    from subtitle.ffmpeg_setup import app_root, ensure_ffmpeg_on_path

    handlers = [logging.StreamHandler()]
    try:
        # 錯誤記錄檔：回報問題時可直接附上（錯誤對話框會提到它）。
        from logging.handlers import RotatingFileHandler
        handlers.append(RotatingFileHandler(
            os.path.join(app_root(), "app.log"),
            maxBytes=1024 * 1024, backupCount=2, encoding="utf-8"))
    except OSError:
        pass  # 程式資料夾不可寫時僅輸出到 console，不影響啟動。
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )
    # 先前「自動安裝 ffmpeg」裝好的執行檔在此生效（不改動系統 PATH）。
    ensure_ffmpeg_on_path()
    app = SrtApp()
    app.mainloop()
