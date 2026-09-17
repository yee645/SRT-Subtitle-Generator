# -*- coding: utf-8 -*-
"""
健檢中心：v1.50.0 起取代「上片前健檢」「字幕健檢」「上片前總體檢」三個
視窗（見 docs/UI_AUDIT_2.0.md 2.2 節、docs/UI_ARCHITECTURE_2.0.md B.5）；
v1.51.0 再併入「發佈健檢」「封面健檢」「章節健檢」三個異質對象的視窗，
對象區隨之擴充加入封面圖（可多選）／發佈文字（標題、說明欄、標籤、章
節四個貼上框，可摺疊）。「系列一致性」比的是多支影片彼此之間一不一
致，與其餘 17 項「檢查單一素材合不合格」性質不同，依 2.2 節預留的退
路保留為獨立視窗，只是入口從主視窗工具列移進本視窗的對象區（見對象區
「系列影片」一列的〔開啟系列一致性比對...〕）。

六個舊視窗背後總共是 18 種既有的健檢邏輯（`subtitle/` 各模組），彼此有
重疊；本視窗把它們收進同一份分級清單：選好檢查對象（影片／字幕／封面
圖／發佈文字／系列影片，皆選填，填什麼檢什麼）→ 勾選要跑的檢查（門檻
收進「進階設定」，不再是開窗就是一片 spinbox 牆）→ 開始健檢 →
`ttk.Treeview` 分級清單，選取一筆發現即顯示詳情與建議，可修的項目按
「修復此項」直接呼叫既有的修復函式。

v2.2.0 起它不再是 Toplevel，而是主視窗階段③的頁籤內容（架構文件 B.5 一
開始就是這樣寫的，1.52.1 只先搬了入口）——檔名也從 health_center_dialog
改成 health_center_panel。結構與能力一項未動，差別只在三處：沒有〔關
閉〕鈕；捲動區高度隨視窗按比例配而不是寫死 560px；佇列輪詢只在背景工作
進行中才排程。

真正的分析與修復邏輯完全在 `gui/health_aggregator.py`（可離線單元測試）
與各 `subtitle/` 模組；本檔案只負責畫面與背景執行緒調度。
"""

import logging
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from config import save_config
from gui import health_aggregator as ha
from gui.error_dialog import show_friendly_error
from gui.ffmpeg_dialog import FfmpegInstallDialog
from gui.scrollable import ScrollableFrame
from gui.series_dialog import SeriesCheckDialog
from subtitle.audiofix import resolve_audiofix_settings
from subtitle.burner import ffmpeg_available
from subtitle.chaptercheck import resolve_chaptercheck_settings
from subtitle.colorcheck import resolve_colorcheck_settings
from subtitle.adfriendly import resolve_adfriendly_settings
from subtitle.hookcheck import resolve_hookcheck_settings
from subtitle.importer import load_subtitle_file
from subtitle.pacing import resolve_pacing_settings
from subtitle.preflight import (LEVEL_BAD, LEVEL_GOOD, LEVEL_WARN,
                                resolve_preflight_settings)
from subtitle.publishcheck import resolve_publishcheck_settings
from subtitle.punctstyle import resolve_punctstyle_settings
from subtitle.subtitlecheck import resolve_subcheck_settings
from subtitle.thumbcheck import resolve_thumbcheck_settings
from subtitle.videocheck import resolve_videocheck_settings
from subtitle.volumeconsistency import resolve_volume_consistency_settings

logger = logging.getLogger(__name__)

MEDIA_FILETYPES = [
    ("影音檔", "*.mp4 *.mkv *.mov *.avi *.flv *.mp3 *.wav *.m4a *.aac"),
    ("所有檔案", "*.*"),
]
SUBTITLE_FILETYPES = [
    ("字幕檔", "*.srt *.vtt"),
    ("所有檔案", "*.*"),
]
IMAGE_FILETYPES = [
    ("圖片檔", "*.png *.jpg *.jpeg *.webp *.bmp"),
    ("所有檔案", "*.*"),
]

_LEVEL_ICONS = {LEVEL_BAD: "✘", LEVEL_WARN: "⚠", LEVEL_GOOD: "✔"}
_LEVEL_LABELS = (("一定要修", LEVEL_BAD), ("建議修", LEVEL_WARN),
                 ("通過", LEVEL_GOOD))
_CHECKLIST_COLUMNS = 3

# 對象區＋檢查清單那塊捲動區的高度預算（見 `_fit_top_height`）。
#
# 先扣掉下半部一定要留的高度、剩下的才給捲動區——不是反過來按比例分。
# 按比例分的話，視窗一矮，下半部就跟著等比縮水，而下半部有一顆「修復此
# 項」按鈕壓不得（1.51.0 踩過：詳情區只分到 64px，按鈕看得到按不到）。
# 上半部本來就在捲動區裡，少看幾列只是多捲一下。
#
# 保留額 = 狀態列＋進度條＋主動作那一列（實測 80px）＋分級報告區下限
#        （286px：清單看得到幾列＋詳情區 170px 容得下四行與按鈕）
#        ＋body 內距 24px
# 數字是量出來的：主視窗預設 1400x800 時本頁籤高 652px，扣掉這 390px 之
# 後上半部拿到 262px，而上半部並排後的內容高度實測 255px——剛好不必捲。
_BOTTOM_RESERVE = 390
# 上半部左右並排（檢查對象｜要跑哪些檢查）所需的最小寬度；比這窄就上下
# 疊回去（沿用 gui/app.py 主視窗三欄退化規則的同一個作法）。
_SIDE_BY_SIDE_WIDTH = 1100

_TOP_HEIGHT_MIN = 120
_TOP_HEIGHT_MAX = 560


def _clamp_top_height(panel_height):
    """由頁籤高度算出捲動區該吃多少高度（純算式，可離線測）。"""
    return max(_TOP_HEIGHT_MIN,
               min(_TOP_HEIGHT_MAX, panel_height - _BOTTOM_RESERVE))


class HealthCenterPanel(ttk.Frame):
    """健檢中心頁籤：選對象→勾選檢查→開始健檢→分級清單＋逐項修復。"""

    def __init__(self, master, config_data, media_path="", cues=None,
                on_fixed=None, on_media_fixed=None, publish=None,
                get_cues=None):
        super().__init__(master)

        self.config_data = config_data
        self.on_fixed = on_fixed
        # v1.52.2：修復版做出來之後回報給主視窗接手（稽核 ④ 斷鏈修復）。
        self.on_media_fixed = on_media_fixed
        # v2.2.0：內嵌之後字幕不能再是「開窗當下的快照」——使用者在階段②
        # 改完字幕、切回階段③重跑，報告要講新句子。有給 get_cues 就每次
        # 健檢前現拿；使用者若自己用〔瀏覽...〕指定了字幕檔，那是明示的
        # 覆寫，不再被主視窗蓋掉。
        self.get_cues = get_cues
        self.cues_overridden = False
        self.result_queue = queue.Queue()
        self.is_processing = False
        self.is_fixing = False
        self.cues = list(cues or [])
        self.last_result = None
        self._finding_by_item = {}
        self._selected_finding = None
        self._thumb_paths = []
        self._series_paths = []
        self._publish_expanded = False
        self._poll_job = None
        # messagebox／filedialog 的 parent 要的是視窗；本類別是頁籤內容、
        # 自己不是視窗，一律指向所屬主視窗。
        self._window = self.winfo_toplevel()

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        # 對象區在 v1.51.0 擴充（封面圖／發佈文字／系列影片）後，展開
        # 「發佈文字」摺疊區＋18 項檢查清單全展開時的總高度會超過任何
        # 合理的視窗高度（實測需要 1300px 以上）。把這段低頻捲動的內容
        # 包進 `ScrollableFrame`、給一個高度預算，讓「開始健檢」與分級
        # 報告永遠留在下半部可見，不會被對象區展開撐到畫面外。
        #
        # v2.2.0：那個預算原本寫死 560px，是照 1120x900 的獨立視窗算
        # 的。主視窗預設 800 高、minsize 只有 560，沿用會把主動作與報告
        # 整個推出畫面，正是 ROADMAP 點名的那種垂直溢位。改成隨頁籤高度
        # 按比例配（見 `_fit_top_height`）。
        self._top_height = _TOP_HEIGHT_MAX
        self._top_wrap = ttk.Frame(body, height=self._top_height)
        self._top_wrap.pack(fill="x")
        self._top_wrap.pack_propagate(False)
        self.top_scroll = ScrollableFrame(
            self._top_wrap, theme=self.config_data.get("theme", "light"))
        self.top_scroll.pack(fill="both", expand=True)
        top = self.top_scroll.interior

        self._build_ffmpeg_banner(top)
        self._top_columns = ttk.Frame(top)
        self._top_columns.pack(fill="both", expand=True)
        self._object_frame = self._build_object_row(self._top_columns,
                                                   media_path)
        # v1.52.2：階段④〔送健檢中心〕帶進來的發佈資料直接填好，使用者不
        # 必再把審片助手產生的章節與發佈包複製貼上一次。
        if publish:
            self._prefill_publish(publish)
        self._checklist_frame = self._build_checklist(self._top_columns)
        self._top_wide = None
        self._apply_top_layout(False)
        self._build_run_row(body)
        self._build_result_area(body)

        self.bind("<Configure>", self._fit_top_height)

    # ------------------------------------------------------------------
    # 主視窗介面（頁籤版專用）
    # ------------------------------------------------------------------
    def _fit_top_height(self, _event=None):
        """捲動區高度隨頁籤高度重配，並決定上半部要並排還是上下疊。"""
        height = self.winfo_height()
        if height <= 1:
            return
        target = _clamp_top_height(height)
        if target != self._top_height:
            self._top_height = target
            self._top_wrap.configure(height=target)
        self._apply_top_layout(self.winfo_width() >= _SIDE_BY_SIDE_WIDTH)

    def _apply_top_layout(self, wide):
        """
        「檢查對象」與「要跑哪些檢查」左右並排（寬的時候）或上下疊。

        頁籤版的高度比獨立視窗少得多（1400x800 下只有 652px，扣掉報告區
        與主動作，上半部只剩約 250px），但**寬度很夠**（1374px）。上下疊
        的話，18 項勾選與〔進階設定〕整組會沉到捲動區看不見的地方——這正
        是本專案截圖抓過好幾次的「新能力被埋在捲動區最底下」。並排之後
        總高度變成兩欄取大者而不是相加，預設尺寸下一次全看得到。

        視窗窄到放不下兩欄時（minsize 980）退回上下疊，由捲動區處理。
        """
        if wide == self._top_wide:
            return
        self._top_wide = wide
        self._object_frame.pack_forget()
        self._checklist_frame.pack_forget()
        if wide:
            # 右欄拿它自己要的寬度（3 欄勾選文字最長的那幾項＋進階設定
            # 鈕），左欄吃剩下的——寫死寬度會把第三欄的「語音同步（需完
            # 整解碼音訊，較慢）」切掉，截圖抓到過。
            self._object_frame.pack(side="left", fill="both", expand=True)
            self._checklist_frame.pack(side="right", fill="y", padx=(10, 0))
        else:
            self._object_frame.pack(fill="x")
            self._checklist_frame.pack(fill="x", pady=(8, 0))

    def set_media_path(self, path, auto=False):
        """
        主視窗換了「目前影片」時同步過來（對象區沿用工作檔案列）。

        ``auto=True`` 是主視窗切到本頁籤時的自動同步：只有在欄位還空
        著、或內容正是上次自動填進去的那個路徑時才覆蓋。使用者自己用
        〔瀏覽...〕挑過的、或接手修復版換過的，都不動它——自動同步不該
        把使用者明示的選擇洗掉。
        """
        path = path or ""
        if auto:
            current = self.media_var.get().strip()
            if current and current != self._auto_media:
                return
        self.media_var.set(path)
        self._auto_media = path

    def sync_cues(self, cues=None):
        """把最新字幕同步進對象區；使用者自己選過字幕檔就不覆蓋。"""
        if cues is None:
            if self.cues_overridden or self.get_cues is None:
                return
            cues = self.get_cues()
        self.cues = list(cues or [])
        self.subs_var.set(self._subs_summary())

    def prefill_publish(self, publish):
        """階段④〔送健檢中心〕：把發佈資料整包填進對象區。"""
        return self._prefill_publish(publish or {})

    # ------------------------------------------------------------------
    # 版面
    # ------------------------------------------------------------------
    def _build_ffmpeg_banner(self, body):
        self.ffmpeg_banner = None
        if not ffmpeg_available():
            banner = tk.Frame(body, bg="#fdf3d7")
            banner.pack(fill="x", pady=(0, 8))
            tk.Label(
                banner, bg="#fdf3d7", fg="#8a5a00", anchor="w",
                text="⚠ 尚未安裝 ffmpeg：需要媒體檔的健檢項目會被略過"
                     "（純文字的字幕相關檢查不受影響）。",
            ).pack(side="left", padx=6, pady=4)
            ttk.Button(banner, text="自動安裝 ffmpeg",
                      command=self._open_ffmpeg_installer).pack(
                side="right", padx=6, pady=2)
            self.ffmpeg_banner = banner

    def _build_object_row(self, body, media_path):
        frame = ttk.LabelFrame(body, text="檢查對象（皆選填，填什麼檢什麼）",
                               padding=(10, 6))

        row_media = ttk.Frame(frame)
        row_media.pack(fill="x")
        ttk.Label(row_media, text="影片檔：", width=8).pack(side="left")
        self.media_var = tk.StringVar(value=media_path)
        # 上一次「自動同步」填進去的值，用來分辨使用者有沒有手動改過。
        self._auto_media = media_path
        ttk.Entry(row_media, textvariable=self.media_var).pack(
            side="left", fill="x", expand=True, padx=(4, 4))
        ttk.Button(row_media, text="瀏覽...", width=8,
                  command=self._choose_media).pack(side="left")

        row_subs = ttk.Frame(frame)
        row_subs.pack(fill="x", pady=(6, 0))
        ttk.Label(row_subs, text="字幕：", width=8).pack(side="left")
        self.subs_var = tk.StringVar(value=self._subs_summary())
        ttk.Entry(row_subs, textvariable=self.subs_var, state="readonly"
                 ).pack(side="left", fill="x", expand=True, padx=(4, 4))
        ttk.Button(row_subs, text="瀏覽...", width=8,
                  command=self._choose_subs).pack(side="left")

        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=(8, 6))
        self._build_thumb_object(frame)
        self._build_publish_object(frame)
        self._build_series_object(frame)
        return frame

    def _subs_summary(self):
        return f"（沿用目前的 {len(self.cues)} 句字幕）" if self.cues else "（無）"

    # -- 封面圖（可多選，v1.51.0 併自 gui/thumbcheck_dialog.py）---------
    def _build_thumb_object(self, frame):
        # v2.2.0：改成可摺疊、預設收合。頁籤版的上半部只有約 250px，而大
        # 多數健檢只用到「影片檔＋字幕」——封面圖與系列影片攤開在那裡，
        # 等於把每次都要用的 18 項勾選擠到捲不到的地方。
        self._thumb_expanded = False
        self.thumb_toggle_btn = ttk.Button(
            frame, text="▸ 封面圖（可多選，會依分數排名，點一下展開）",
            command=self._toggle_thumb)
        self.thumb_toggle_btn.pack(fill="x")
        sub = ttk.Frame(frame)
        self.thumb_body = sub
        list_row = ttk.Frame(sub)
        list_row.pack(fill="x")
        self.thumb_list = tk.Listbox(list_row, height=3,
                                     font=("Microsoft JhengHei", 9))
        thumb_scroll = ttk.Scrollbar(list_row, orient="vertical",
                                     command=self.thumb_list.yview)
        self.thumb_list.configure(yscrollcommand=thumb_scroll.set)
        self.thumb_list.pack(side="left", fill="both", expand=True)
        thumb_scroll.pack(side="left", fill="y")
        btn_row = ttk.Frame(sub)
        btn_row.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_row, text="加入圖片...",
                  command=self._add_thumbs).pack(side="left")
        ttk.Button(btn_row, text="移除選取",
                  command=self._remove_thumb).pack(side="left", padx=(6, 0))
        ttk.Button(btn_row, text="全部清除",
                  command=self._clear_thumbs).pack(side="left", padx=(6, 0))

    def _toggle_thumb(self, expand=None):
        self._thumb_expanded = (not self._thumb_expanded if expand is None
                                else bool(expand))
        if self._thumb_expanded:
            self.thumb_body.pack(fill="x", pady=(0, 4))
            self.thumb_toggle_btn.configure(
                text="▾ 封面圖（可多選，會依分數排名，點一下收合）")
        else:
            self.thumb_body.pack_forget()
            self.thumb_toggle_btn.configure(
                text="▸ 封面圖（可多選，會依分數排名，點一下展開）")

    def _add_thumbs(self):
        self._toggle_thumb(expand=True)
        paths = filedialog.askopenfilenames(
            title="選擇封面圖片", filetypes=IMAGE_FILETYPES,
            parent=self._window)
        for path in paths:
            if path not in self._thumb_paths:
                self._thumb_paths.append(path)
                self.thumb_list.insert("end", os.path.basename(path))

    def _remove_thumb(self):
        for index in reversed(self.thumb_list.curselection()):
            self.thumb_list.delete(index)
            del self._thumb_paths[index]

    def _clear_thumbs(self):
        self.thumb_list.delete(0, "end")
        self._thumb_paths = []

    # -- 發佈文字（可摺疊，v1.51.0 併自 publishcheck/chapter_dialog）----
    def _build_publish_object(self, frame):
        self.publish_toggle_btn = ttk.Button(
            frame, text="▸ 發佈文字（標題／說明欄／標籤／章節，點一下展開）",
            command=self._toggle_publish)
        self.publish_toggle_btn.pack(fill="x", pady=(6, 0))
        self.publish_body = ttk.Frame(frame)
        # 預設收合，不 pack——門檻與低頻的貼上框不該一開窗就佔滿版面
        # （docs/UI_AUDIT_2.0.md 2.2 節同一原則已用在「進階設定」上）。

        title_row = ttk.Frame(self.publish_body)
        title_row.pack(fill="x", pady=(4, 0))
        ttk.Label(title_row, text="標題：", width=8).pack(side="left")
        self.publish_title_var = tk.StringVar()
        ttk.Entry(title_row, textvariable=self.publish_title_var).pack(
            side="left", fill="x", expand=True)

        desc_frame = ttk.LabelFrame(self.publish_body, text="說明欄",
                                    padding=(6, 4))
        desc_frame.pack(fill="x", pady=(4, 0))
        self.publish_desc = tk.Text(desc_frame, wrap="word", height=4,
                                    font=("Microsoft JhengHei", 9))
        desc_scroll = ttk.Scrollbar(desc_frame, orient="vertical",
                                    command=self.publish_desc.yview)
        self.publish_desc.configure(yscrollcommand=desc_scroll.set)
        self.publish_desc.pack(side="left", fill="both", expand=True)
        desc_scroll.pack(side="left", fill="y")

        tags_row = ttk.Frame(self.publish_body)
        tags_row.pack(fill="x", pady=(4, 0))
        ttk.Label(tags_row, text="標籤：", width=8).pack(side="left")
        self.publish_tags_var = tk.StringVar()
        ttk.Entry(tags_row, textvariable=self.publish_tags_var).pack(
            side="left", fill="x", expand=True)
        ttk.Label(self.publish_body, foreground="#666666", anchor="w",
                 text="（標籤以逗號分隔，就是 YouTube 後台那一欄的填法；"
                      "hashtag 請直接寫在說明欄或標題裡）"
                 ).pack(fill="x")

        chapters_frame = ttk.LabelFrame(
            self.publish_body, text="章節文字（每行「時間戳 空白 標題」）",
            padding=(6, 4))
        chapters_frame.pack(fill="x", pady=(4, 0))
        self.publish_chapters = tk.Text(chapters_frame, wrap="none",
                                        height=4,
                                        font=("Microsoft JhengHei", 9))
        chapters_scroll = ttk.Scrollbar(
            chapters_frame, orient="vertical",
            command=self.publish_chapters.yview)
        self.publish_chapters.configure(yscrollcommand=chapters_scroll.set)
        self.publish_chapters.pack(side="left", fill="both", expand=True)
        chapters_scroll.pack(side="left", fill="y")

        media_row = ttk.Frame(self.publish_body)
        media_row.pack(fill="x", pady=(4, 0))
        ttk.Label(media_row, foreground="#666666", anchor="w", justify="left",
                 wraplength=760,
                 text="說明欄上限算的是位元組，中文一個字佔 3 個位元組；"
                      "hashtag 超過 15 個 YouTube 會「忽略全部」且不提示；"
                      "章節的最後一章長度需要上方「影片檔」欄有選檔才能檢查。"
                 ).pack(fill="x")

    def _toggle_publish(self):
        self._publish_expanded = not self._publish_expanded
        if self._publish_expanded:
            self.publish_body.pack(fill="x", pady=(0, 4))
            self.publish_toggle_btn.configure(
                text="▾ 發佈文字（標題／說明欄／標籤／章節，點一下收合）")
        else:
            self.publish_body.pack_forget()
            self.publish_toggle_btn.configure(
                text="▸ 發佈文字（標題／說明欄／標籤／章節，點一下展開）")

    # -- 系列影片（可多選，保留獨立視窗，v1.51.0 只把入口移進對象區）----
    def _build_series_object(self, frame):
        # v2.2.0：同封面圖，改成可摺疊、預設收合（見 _build_thumb_object）。
        self._series_expanded = False
        self.series_toggle_btn = ttk.Button(
            frame, text="▸ 系列影片（可多選，比對整批彼此是否一致，點一下展開）",
            command=self._toggle_series)
        self.series_toggle_btn.pack(fill="x", pady=(6, 0))
        sub = ttk.Frame(frame)
        self.series_body = sub
        list_row = ttk.Frame(sub)
        list_row.pack(fill="x")
        self.series_list = tk.Listbox(list_row, height=3,
                                      font=("Microsoft JhengHei", 9))
        series_scroll = ttk.Scrollbar(list_row, orient="vertical",
                                      command=self.series_list.yview)
        self.series_list.configure(yscrollcommand=series_scroll.set)
        self.series_list.pack(side="left", fill="both", expand=True)
        series_scroll.pack(side="left", fill="y")
        btn_row = ttk.Frame(sub)
        btn_row.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_row, text="加入影片...",
                  command=self._add_series).pack(side="left")
        ttk.Button(btn_row, text="移除選取",
                  command=self._remove_series).pack(side="left", padx=(6, 0))
        ttk.Button(btn_row, text="全部清除",
                  command=self._clear_series).pack(side="left", padx=(6, 0))
        ttk.Button(btn_row, text="開啟系列一致性比對...",
                  command=self._open_series_check).pack(side="left",
                                                        padx=(6, 0))
        ttk.Label(
            sub, foreground="#666666", anchor="w", justify="left",
            wraplength=760,
            text="系列一致性比的是「多支影片彼此之間」，跟其餘檢查項"
                 "（單支影片合不合格）性質不同，因此獨立開一個比對視窗、"
                 "不併進下方的分級報告。",
        ).pack(fill="x", pady=(2, 0))

    def _toggle_series(self, expand=None):
        self._series_expanded = (not self._series_expanded if expand is None
                                 else bool(expand))
        if self._series_expanded:
            self.series_body.pack(fill="x", pady=(0, 4))
            self.series_toggle_btn.configure(
                text="▾ 系列影片（可多選，比對整批彼此是否一致，點一下收合）")
        else:
            self.series_body.pack_forget()
            self.series_toggle_btn.configure(
                text="▸ 系列影片（可多選，比對整批彼此是否一致，點一下展開）")

    def _add_series(self):
        self._toggle_series(expand=True)
        paths = filedialog.askopenfilenames(
            title="選擇同系列的影片", filetypes=MEDIA_FILETYPES,
            parent=self._window)
        for path in paths:
            if path not in self._series_paths:
                self._series_paths.append(path)
                self.series_list.insert("end", os.path.basename(path))

    def _remove_series(self):
        for index in reversed(self.series_list.curselection()):
            self.series_list.delete(index)
            del self._series_paths[index]

    def _clear_series(self):
        self.series_list.delete(0, "end")
        self._series_paths = []

    def _open_series_check(self):
        SeriesCheckDialog(self._window, self.config_data,
                          list(self._series_paths))

    def _build_checklist(self, body):
        frame = ttk.LabelFrame(body, text="要跑哪些檢查（自動記憶）",
                               padding=(10, 6))

        pf_settings = resolve_preflight_settings(self.config_data)
        hc_settings = ha.resolve_healthcenter_settings(self.config_data)

        # 〔進階設定〕先宣告、且 side="bottom"：pack 是先到先分配，勾選
        # 格線若先 pack 成 side="left"，這顆就只能去搶右邊那條垂直空間，
        # 整個框的「要求寬度」因此多出 149px（實測 893→1062），並排時把
        # 第三欄的「語音同步（需完整解碼音訊，較慢）」推出畫面。宣告順序
        # 換過來之後它改成佔底部一整條，格線拿到完整寬度。
        # （v1.50.1 只改了 side 沒改宣告順序，所以當時只解決了文字被切成
        # 「進階設」，沒解決要求寬度虛胖。）
        settings_btn = ttk.Button(frame, text="進階設定（門檻）⚙",
                                  command=self._open_settings)
        settings_btn.pack(side="bottom", anchor="e", pady=(6, 0))

        grid = ttk.Frame(frame)
        grid.pack(fill="x", side="top", expand=True)
        self.check_vars = {}
        index = 0
        for check in ha.CHECK_DEFS:
            if check.always_on:
                continue
            settings = (hc_settings if check.toggle_group == "healthcenter"
                       else pf_settings)
            var = tk.BooleanVar(value=bool(settings.get(check.key, True)))
            self.check_vars[check.key] = var
            ttk.Checkbutton(grid, text=check.label, variable=var).grid(
                row=index // _CHECKLIST_COLUMNS,
                column=index % _CHECKLIST_COLUMNS,
                sticky="w", padx=(0, 16), pady=2)
            index += 1
        # 檔名一律跟著跑（有素材才有意義），畫成停用的勾選讓使用者知道
        # 這項能力還在，不是被拿掉了。
        filename_var = tk.BooleanVar(value=True)
        cb = ttk.Checkbutton(grid, text="檔名（有選素材就一併檢查）",
                             variable=filename_var, state="disabled")
        cb.grid(row=index // _CHECKLIST_COLUMNS,
               column=index % _CHECKLIST_COLUMNS, sticky="w",
               padx=(0, 16), pady=2)

        return frame

    def _build_run_row(self, body):
        self.status_var = tk.StringVar(
            value="選好要檢查的對象後按「開始健檢」，掃描不會改動原始檔案。")
        ttk.Label(body, textvariable=self.status_var, foreground="#1a5fb4",
                  wraplength=860, justify="left").pack(fill="x", pady=(8, 0))
        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(body, mode="determinate", maximum=100.0,
                        variable=self.progress_var).pack(
            fill="x", pady=(4, 6))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        self.run_btn = ttk.Button(buttons, text="開始健檢",
                                  command=self._on_run)
        self.run_btn.pack(side="left")
        self.copy_btn = ttk.Button(buttons, text="複製報告", state="disabled",
                                   command=self._on_copy)
        self.copy_btn.pack(side="left", padx=(6, 0))
        self.save_btn = ttk.Button(buttons, text="另存報告...",
                                   state="disabled", command=self._on_save)
        self.save_btn.pack(side="left", padx=(6, 0))
        # v2.2.0 拿掉〔關閉〕：頁籤沒有東西可關，留著只會讓人以為按了會
        # 關掉主程式。

    def _build_result_area(self, body):
        pane = ttk.PanedWindow(body, orient="vertical")
        pane.pack(fill="both", expand=True, pady=(8, 0))

        tree_frame = ttk.LabelFrame(pane, text="健檢結果", padding=(6, 6))
        self.tree = ttk.Treeview(
            tree_frame, columns=("source",), show="tree headings",
            selectmode="browse", height=10)
        self.tree.heading("#0", text="狀態／項目")
        self.tree.heading("source", text="來源")
        self.tree.column("#0", width=420, anchor="w")
        self.tree.column("source", width=160, anchor="w")
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical",
                                  command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select_finding)
        pane.add(tree_frame, weight=3)
        self._pane = pane
        self._tree_frame = tree_frame

        detail_frame = ttk.LabelFrame(pane, text="發現詳情", padding=(8, 6))
        # 〔修復此項〕先宣告、且 side="bottom"：pack 是先到先分配空間，
        # 上面三行說明文字遇到長內容會換行變高，詳情區高度不夠時最後才
        # pack 的那個會被擠成 1px。按鈕壓不得，說明文字少看一行還看得到
        # ——所以按鈕先卡位。（只改 side 不改宣告順序沒有用，這是本專案
        # 踩過三次的無效改法之一。）
        fix_row = ttk.Frame(detail_frame)
        fix_row.pack(side="bottom", fill="x", pady=(6, 0))
        self.fix_btn = ttk.Button(fix_row, text="修復此項", state="disabled",
                                  command=self._on_fix_selected)
        self.fix_btn.pack(side="left")
        self.detail_title_var = tk.StringVar(value="（選取上方一筆結果查看詳情）")
        ttk.Label(detail_frame, textvariable=self.detail_title_var,
                 font=("Microsoft JhengHei", 10, "bold"), anchor="w",
                 wraplength=860, justify="left").pack(fill="x")
        self.detail_body_var = tk.StringVar(value="")
        ttk.Label(detail_frame, textvariable=self.detail_body_var,
                 anchor="w", wraplength=860, justify="left").pack(
            fill="x", pady=(4, 0))
        self.detail_advice_var = tk.StringVar(value="")
        ttk.Label(detail_frame, textvariable=self.detail_advice_var,
                 anchor="w", justify="left", wraplength=860,
                 foreground="#1a5fb4").pack(fill="x", pady=(2, 0))
        pane.add(detail_frame, weight=1)
        self._detail_frame = detail_frame
        # PanedWindow 的初始 sash 位置只看子元件的「要求尺寸」，發現詳情區
        # 一開始沒有內容、要求尺寸很小，會被壓到連「修復此項」按鈕都露不
        # 出來；開窗後量出實際可用高度，明確把 sash 往下推、保留詳情區
        # 至少 150px（標題＋內容＋建議＋按鈕四行）。
        self.after(80, self._init_pane_sash)
        pane.bind("<Configure>", self._init_pane_sash)

    def _init_pane_sash(self, _event=None):
        """
        確保「發現詳情」區有下限高度，那顆〔修復此項〕才按得到。

        詳情區的按鈕比清單本身更容易被忽略地壓到 1px 高（v1.51.0 對象區
        擴充後第一次踩到）：舊公式只保住清單至少 140px，detail 區不足額
        時完全沒有下限，`170 - 234` 這種算式會讓 detail 只分到 64px、三
        行文字＋按鈕塞不進去，按鈕變得看得到按不到。改成優先保住 detail
        的 170px 下限，清單只保底 60px（清單本身有自己的捲軸，壓縮只是
        少看到幾列，不像按鈕壓縮到 1px 那樣直接壞掉）。

        v2.2.0：改成綁在 pane 的 `<Configure>` 上重複執行，不再只算一
        次。頁籤版的 pane 高度在顯示過程中還會變（捲動區高度是視窗一量
        到就重配的），只算一次會停在早期那個值——實測 1400x800 下詳情區
        因此只分到 79px，「修復此項」又一次被壓到看不見。只在**低於下
        限**時才動 sash，使用者自己往上拉大詳情區不會被搶回去。
        """
        try:
            self._pane.update_idletasks()
            total = self._pane.winfo_height()
            if total <= 100:
                return
            detail_min, tree_min = 170, 60
            if total - self._pane.sashpos(0) >= detail_min:
                return  # 詳情區已經夠高（含使用者自己拉大的），不動它。
            if total <= detail_min + tree_min:
                sashpos = max(total - detail_min, tree_min)
            else:
                sashpos = total - detail_min
            self._pane.sashpos(0, sashpos)
        except tk.TclError:
            pass  # 視窗已關閉或尚未映射，安全略過。

    # ------------------------------------------------------------------
    # 對象選取
    # ------------------------------------------------------------------
    def _choose_media(self):
        path = filedialog.askopenfilename(
            title="選擇要健檢的影音檔", filetypes=MEDIA_FILETYPES,
            parent=self._window)
        if path:
            self.media_var.set(path)

    def _choose_subs(self):
        path = filedialog.askopenfilename(
            title="選擇字幕檔（選填）", filetypes=SUBTITLE_FILETYPES,
            parent=self._window)
        if not path:
            return
        try:
            loaded = load_subtitle_file(path)
        except Exception as exc:
            show_friendly_error(self._window, "讀取字幕檔失敗", exc)
            return
        self.cues = loaded["cues"]
        # 明示覆寫：之後主視窗的字幕變動不再自動蓋掉這份。
        self.cues_overridden = True
        self.subs_var.set(f"{path}（{len(self.cues)} 句）")
        self.status_var.set(f"已載入 {len(self.cues)} 句字幕。")

    def _open_ffmpeg_installer(self):
        def done():
            if self.ffmpeg_banner is not None:
                self.ffmpeg_banner.destroy()
                self.ffmpeg_banner = None
        FfmpegInstallDialog(self._window, on_done=done)

    # ------------------------------------------------------------------
    # 進階設定（門檻）
    # ------------------------------------------------------------------
    def _open_settings(self):
        HealthSettingsDialog(self._window, self.config_data)

    # ------------------------------------------------------------------
    # 開始健檢
    # ------------------------------------------------------------------
    def _selected_keys(self):
        return {key for key, var in self.check_vars.items() if var.get()}

    def _save_checklist(self):
        ha.save_selected_keys(self.config_data, self._selected_keys())
        try:
            save_config(self.config_data)
        except OSError:
            pass  # 存檔失敗不影響本次使用。

    def _collect_publish(self):
        return {
            "title": self.publish_title_var.get(),
            "description": self.publish_desc.get("1.0", "end"),
            "tags": self.publish_tags_var.get(),
            "chapters_text": self.publish_chapters.get("1.0", "end"),
        }

    def _has_any_object(self, media_path, publish):
        if media_path or self.cues or self._thumb_paths:
            return True
        return ha.has_publish_text(publish) or bool(
            (publish.get("chapters_text") or "").strip())

    def _on_run(self):
        if self.is_processing or self.is_fixing:
            return
        # 每次健檢前向主視窗現拿字幕，報告才會講現在的句子（v2.2.0）。
        self.sync_cues()
        media_path = self.media_var.get().strip()
        publish = self._collect_publish()
        if not self._has_any_object(media_path, publish):
            messagebox.showinfo(
                "提示", "請至少填一項檢查對象：影片、字幕、封面圖，"
                "或發佈文字（標題／說明欄／標籤／章節）。", parent=self._window)
            return
        selected = self._selected_keys()
        if not selected:
            messagebox.showinfo("提示", "請至少勾選一項要跑的檢查。",
                                parent=self._window)
            return
        self._save_checklist()
        self._set_processing(True)
        self._ensure_polling()
        self.status_var.set("健檢進行中...")
        self.progress_var.set(0.0)
        threading.Thread(
            target=self._run_worker,
            args=(media_path, list(self.cues), dict(self.config_data),
                 selected, publish, list(self._thumb_paths)),
            daemon=True).start()

    def _run_worker(self, media_path, cues, config, selected, publish,
                    image_paths):
        try:
            def progress(ratio, message):
                self.result_queue.put(("status", (message, ratio)))
            result = ha.run_health_scan(media_path, cues, config, selected,
                                        progress_cb=progress, publish=publish,
                                        image_paths=image_paths)
            self.result_queue.put(("done", result))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("健檢中心掃描失敗")
            self.result_queue.put(("error", exc))

    # ------------------------------------------------------------------
    # 結果呈現
    # ------------------------------------------------------------------
    def _show_result(self, result):
        self.last_result = result
        self.tree.delete(*self.tree.get_children())
        self._finding_by_item = {}
        findings = result.get("findings") or []
        for label, level in _LEVEL_LABELS:
            rows = [f for f in findings if f.get("level") == level]
            group_id = self.tree.insert(
                "", "end", text=f"{label}（{len(rows)}）",
                open=(level != LEVEL_GOOD), tags=("group",))
            for row in rows:
                icon = _LEVEL_ICONS.get(row.get("level"), "・")
                item_id = self.tree.insert(
                    group_id, "end", text=f"{icon} {row.get('title', '')}",
                    values=(row.get("source", ""),))
                self._finding_by_item[item_id] = row
        self.copy_btn.configure(state="normal" if findings else "disabled")
        self.save_btn.configure(state="normal" if findings else "disabled")
        self._clear_detail()

        counts = result.get("counts") or {}
        grade = result.get("grade", "?")
        if result.get("ok"):
            self.status_var.set(
                f"健檢完成，準備度 {grade}：沒有「一定要修」的項目"
                f"（建議修 {counts.get(LEVEL_WARN, 0)} 項）。")
        else:
            self.status_var.set(
                f"健檢完成，準備度 {grade}："
                f"{counts.get(LEVEL_BAD, 0)} 項一定要修、"
                f"{counts.get(LEVEL_WARN, 0)} 項建議修，詳見下方清單。")

    def _clear_detail(self):
        self._selected_finding = None
        self.detail_title_var.set("（選取上方一筆結果查看詳情）")
        self.detail_body_var.set("")
        self.detail_advice_var.set("")
        self.fix_btn.configure(state="disabled")

    def _on_select_finding(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            self._clear_detail()
            return
        finding = self._finding_by_item.get(selection[0])
        if not finding:
            self._clear_detail()
            return
        self._selected_finding = finding
        icon = _LEVEL_ICONS.get(finding.get("level"), "・")
        source = finding.get("source", "")
        self.detail_title_var.set(
            f"{icon} [{source}] {finding.get('title', '')}")
        self.detail_body_var.set(finding.get("detail", ""))
        advice = finding.get("advice", "")
        self.detail_advice_var.set(f"建議：{advice}" if advice else "")
        fix_key = finding.get("fix_key")
        label = ha.FIX_LABELS.get(fix_key, "修復此項")
        self.fix_btn.configure(
            text=label, state="normal" if fix_key else "disabled")

    # ------------------------------------------------------------------
    # 修復此項
    # ------------------------------------------------------------------
    def _on_fix_selected(self):
        finding = self._selected_finding
        if not finding or not finding.get("fix_key") or self.is_processing \
               or self.is_fixing:
            return
        fix_key = finding["fix_key"]
        if fix_key in ha.CUE_FIX_KEYS:
            self._run_cue_fix(fix_key)
        elif fix_key in ha.MEDIA_FIX_KEYS:
            self._run_media_fix(fix_key)
        elif fix_key in ha.TEXT_FIX_KEYS:
            self._run_text_fix(fix_key)

    def _run_text_fix(self, fix_key):
        """處理修復對象是對象區貼上文字的項目（目前只有章節）。"""
        raw = (self.last_result or {}).get("raw") or {}
        try:
            new_text, changes, message = ha.apply_text_fix(
                fix_key, self.config_data, raw)
        except ha.FixError as exc:
            messagebox.showinfo("提示", str(exc), parent=self._window)
            return
        if not changes:
            messagebox.showinfo("提示", message, parent=self._window)
            return
        if fix_key == "chapter_fix":
            if not self._publish_expanded:
                self._toggle_publish()  # 讓使用者看得到被改動的內容。
            self.publish_chapters.delete("1.0", "end")
            self.publish_chapters.insert("1.0", new_text)
        self.status_var.set(f"{message}重新健檢中...")
        self._on_run()

    def _run_cue_fix(self, fix_key):
        raw = (self.last_result or {}).get("raw") or {}
        try:
            new_cues, changed, message = ha.apply_cue_fix(
                fix_key, self.cues, self.config_data, raw)
        except ha.FixError as exc:
            messagebox.showinfo("提示", str(exc), parent=self._window)
            return
        if changed == 0:
            messagebox.showinfo(
                "提示", "沒有可修復的內容（可能空檔不足，或已經符合規範）。",
                parent=self._window)
            return
        self.cues = new_cues
        if self.on_fixed:
            self.on_fixed(new_cues)
        self.subs_var.set(self._subs_summary())
        self.status_var.set(f"{message}重新健檢中...")
        self._on_run()

    def _prefill_publish(self, publish):
        """
        把主視窗帶來的發佈資料填進對象區（v1.52.2）。

        只填有值的欄位，不覆蓋使用者已經在這裡打的字；有內容時順手把「發
        佈文字」摺疊區展開——資料填進去了卻收在摺疊區裡，跟沒填一樣。
        """
        filled = False
        if publish.get("title"):
            self.publish_title_var.set(publish["title"])
            filled = True
        for widget, key in ((self.publish_desc, "description"),
                            (self.publish_chapters, "chapters")):
            value = publish.get(key)
            if value:
                widget.delete("1.0", "end")
                widget.insert("1.0", value)
                filled = True
        if publish.get("tags"):
            self.publish_tags_var.set(publish["tags"])
            filled = True
        for path in publish.get("thumbs") or []:
            if path not in self._thumb_paths:
                self._thumb_paths.append(path)
                self.thumb_list.insert("end", os.path.basename(path))
                self._toggle_thumb(expand=True)
                filled = True
        if filled and not self._publish_expanded:
            self._toggle_publish()
        return filled

    def _offer_adopt_fixed(self, path):
        """
        修復版做好了，問使用者要不要直接接手為「目前影片」（v1.52.2）。

        舊版只跳一個訊息框報路徑、外加一句「也可對輸出版再跑一次健檢比
        對」——但介面沒有任何做得到那件事的路徑，使用者得自己記住路徑、
        回主視窗重選檔案。這正是稽核 ④「產出端與檢查端斷鏈」點名的情形。

        用詢問而不是自動接手，是因為修復是「可能改壞」的處理（音訊被動過
        濾鏡），使用者本來就該先試聽再決定要不要沿用；自動換掉會讓沒聽過
        的版本悄悄變成後續所有步驟的輸入。
        """
        if not self.on_media_fixed:
            messagebox.showinfo(
                "修復完成", f"已輸出：\n{path}\n\n建議播放／試聽確認結果。",
                parent=self._window)
            return
        source = self.media_var.get().strip()
        adopt = messagebox.askyesno(
            "修復完成",
            f"已輸出：\n{path}\n\n"
            "要把它設為「目前影片」嗎？\n"
            "設為目前影片之後，這裡的對象會換成修復版——再按一次"
            "〔開始健檢〕就是修復前後的比對，不必自己回主視窗重選檔案。\n\n"
            "（建議先播放／試聽確認結果再決定。選「否」則只是輸出檔案，"
            "不改變目前影片。）",
            parent=self._window)
        if not adopt:
            return
        self.on_media_fixed(path, source)
        # 對象區同步換成修復版，否則使用者按〔開始健檢〕還是在檢查舊檔。
        self.media_var.set(path)
        self.status_var.set(
            "已接手修復版為目前影片，按〔開始健檢〕即可比對修復前後。")

    def _run_media_fix(self, fix_key):
        media_path = self.media_var.get().strip()
        if not media_path or not os.path.exists(media_path):
            messagebox.showinfo("提示", "請選擇有效的影音檔。",
                                parent=self._window)
            return
        if not ffmpeg_available():
            show_friendly_error(
                self._window, "修復需要 ffmpeg",
                RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。"),
                on_install_ffmpeg=self._open_ffmpeg_installer)
            return
        try:
            output = ha.suggest_fix_output_path(fix_key, media_path)
        except ha.FixError as exc:
            messagebox.showinfo("提示", str(exc), parent=self._window)
            return
        raw = (self.last_result or {}).get("raw") or {}
        self._set_fixing(True)
        self._ensure_polling()
        self.status_var.set("修復進行中...")
        threading.Thread(
            target=self._media_fix_worker,
            args=(fix_key, media_path, output, dict(self.config_data), raw),
            daemon=True).start()

    def _media_fix_worker(self, fix_key, media_path, output, config, raw):
        try:
            def progress(ratio, message):
                self.result_queue.put(("fix_status", (message, ratio)))
            path = ha.apply_media_fix(fix_key, media_path, output, config,
                                      raw, progress_cb=progress)
            self.result_queue.put(("fix_done", path))
        except ha.FixError as exc:
            self.result_queue.put(("fix_notice", str(exc)))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("健檢中心修復失敗")
            self.result_queue.put(("fix_error", exc))

    # ------------------------------------------------------------------
    def _ensure_polling(self):
        """背景工作開跑時才排輪詢。

        獨立視窗時代是「開窗就每 120ms 跑一次、關窗才停」；內嵌之後這個
        頁籤與程式同壽，照抄等於整個生命週期都在空轉。
        """
        if self._poll_job is None:
            self._poll_job = self.after(120, self._poll_queue)

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.result_queue.get_nowait()
                if kind == "status":
                    message, ratio = payload
                    self.status_var.set(message)
                    if ratio is not None:
                        self.progress_var.set(ratio * 100.0)
                elif kind == "fix_status":
                    message, ratio = payload
                    self.status_var.set(message)
                    if ratio is not None:
                        self.progress_var.set(ratio * 100.0)
                elif kind == "done":
                    self._set_processing(False)
                    self._show_result(payload)
                elif kind == "error":
                    self._set_processing(False)
                    self.status_var.set("健檢失敗。")
                    show_friendly_error(
                        self._window, "健檢失敗", payload,
                        on_install_ffmpeg=self._open_ffmpeg_installer)
                elif kind == "fix_done":
                    self._set_fixing(False)
                    self.status_var.set(f"修復版已輸出：{payload}")
                    self._offer_adopt_fixed(payload)
                elif kind == "fix_notice":
                    self._set_fixing(False)
                    messagebox.showinfo("提示", payload,
                                        parent=self._window)
                elif kind == "fix_error":
                    self._set_fixing(False)
                    self.status_var.set("修復失敗。")
                    show_friendly_error(self._window, "修復失敗", payload)
        except queue.Empty:
            pass
        if self.is_processing or self.is_fixing:
            self._poll_job = self.after(120, self._poll_queue)
        else:
            self._poll_job = None

    def _set_processing(self, processing):
        self.is_processing = processing
        self.run_btn.configure(state="disabled" if processing else "normal")
        self.fix_btn.configure(state="disabled" if processing else (
            "normal" if (self._selected_finding
                        and self._selected_finding.get("fix_key"))
            else "disabled"))

    def _set_fixing(self, fixing):
        self.is_fixing = fixing
        self.run_btn.configure(state="disabled" if fixing else "normal")
        self.fix_btn.configure(state="disabled" if fixing else (
            "normal" if (self._selected_finding
                        and self._selected_finding.get("fix_key"))
            else "disabled"))

    # ------------------------------------------------------------------
    def _on_copy(self):
        if not self.last_result:
            return
        text = ha.format_health_report(self.last_result)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("報告已複製到剪貼簿。")

    def _on_save(self):
        if not self.last_result:
            return
        media = self.media_var.get().strip()
        base = os.path.splitext(os.path.basename(media))[0] or "健檢中心"
        from subtitle.pipeline import unique_path
        initial = unique_path(os.path.join(
            os.path.dirname(media) or ".", f"{base}_健檢中心.txt"))
        path = filedialog.asksaveasfilename(
            title="另存健檢報告", defaultextension=".txt",
            initialfile=os.path.basename(initial),
            initialdir=os.path.dirname(initial) or ".",
            filetypes=[("文字檔", "*.txt"), ("所有檔案", "*.*")],
            parent=self._window)
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(ha.format_health_report(self.last_result))
        except OSError as exc:
            messagebox.showerror("儲存失敗", str(exc), parent=self._window)
            return
        self.status_var.set(f"報告已儲存：{path}")

    def destroy(self):
        if self._poll_job is not None:
            try:
                self.after_cancel(self._poll_job)
            except tk.TclError:
                pass  # 視窗已在拆除中，安全略過。
            self._poll_job = None
        super().destroy()


class HealthSettingsDialog(tk.Toplevel):
    """
    進階設定（門檻）：把三個舊視窗開窗就看到的 14+ 顆 spinbox 收在這裡。

    門檻是一次調好就記憶的低頻操作，不該佔健檢中心的主畫面
    （docs/UI_AUDIT_2.0.md 2.2 節）。內容照抄三個舊視窗原本各自的門檻
    群組，一項不少，只是搬了位置。
    """

    def __init__(self, master, config_data):
        super().__init__(master)
        self.title("健檢中心：進階設定（門檻）")
        self.geometry("560x620")
        self.minsize(480, 420)
        self.transient(master)
        self.grab_set()

        self.config_data = config_data
        theme = config_data.get("theme", "light")

        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)
        self.scroll = ScrollableFrame(outer, theme=theme)
        self.scroll.pack(fill="both", expand=True)
        body = self.scroll.interior

        self._build_audio(body)
        self._build_video(body)
        self._build_volume(body)
        self._build_color(body)
        self._build_pacing(body)
        self._build_audiofix(body)
        self._build_subtitle(body)
        self._build_adfriendly(body)
        self._build_hook(body)
        self._build_punct(body)
        self._build_filename(body)
        self._build_publish(body)
        self._build_thumb(body)
        self._build_chapter(body)

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="儲存並關閉", command=self._on_save).pack(
            side="right")
        ttk.Button(buttons, text="取消", command=self.destroy).pack(
            side="right", padx=(0, 6))

    # -- 小工具：一列「標籤＋Spinbox＋單位」 -----------------------------
    def _spin_row(self, parent, label, var, **kwargs):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label).pack(side="left")
        unit = kwargs.pop("unit", "")
        width = kwargs.pop("width", 7)
        ttk.Spinbox(row, textvariable=var, width=width, **kwargs).pack(
            side="left", padx=(4, 4))
        if unit:
            ttk.Label(row, text=unit).pack(side="left")
        return row

    def _build_audio(self, body):
        settings = resolve_preflight_settings(self.config_data)
        # 音訊健檢門檻沿用 subtitle.audiocheck 的 resolve，不透過 preflight。
        from subtitle.audiocheck import resolve_audiocheck_settings
        s = resolve_audiocheck_settings(self.config_data)
        frame = ttk.LabelFrame(body, text="音訊健檢門檻", padding=(10, 6))
        frame.pack(fill="x", pady=(0, 8))
        self.quiet_var = tk.DoubleVar(value=s["quiet_lufs"])
        self._spin_row(frame, "太小聲門檻:", self.quiet_var, unit="LUFS",
                      from_=-30.0, to=-10.0, increment=0.5, format="%.1f")
        self.noise_var = tk.DoubleVar(value=s["noise_floor_db"])
        self._spin_row(frame, "底噪門檻:", self.noise_var, unit="dB",
                      from_=-90.0, to=-20.0, increment=1.0, format="%.0f")
        self.clip_var = tk.DoubleVar(value=s["clip_peak_db"])
        self._spin_row(frame, "爆音峰值門檻:", self.clip_var, unit="dB",
                      from_=-6.0, to=0.0, increment=0.1, format="%.1f")
        self.balance_var = tk.DoubleVar(value=s["balance_db"])
        self._spin_row(frame, "聲道差異門檻:", self.balance_var, unit="dB",
                      from_=2.0, to=20.0, increment=0.5, format="%.1f")

    def _build_video(self, body):
        s = resolve_videocheck_settings(self.config_data)
        frame = ttk.LabelFrame(body, text="影片畫質門檻", padding=(10, 6))
        frame.pack(fill="x", pady=(0, 8))
        self.bitrate_margin_var = tk.DoubleVar(value=s["bitrate_margin"])
        self._spin_row(frame, "位元率寬嚴:", self.bitrate_margin_var,
                      unit="× YouTube 建議值", from_=0.5, to=2.0,
                      increment=0.1, format="%.1f")
        self.head_max_var = tk.DoubleVar(value=s["head_max_seconds"])
        self._spin_row(frame, "開頭廢秒門檻:", self.head_max_var, unit="秒",
                      from_=0.3, to=10.0, increment=0.1, format="%.1f")
        self.freeze_min_var = tk.DoubleVar(value=s["freeze_min_seconds"])
        self._spin_row(frame, "凍結判定秒數:", self.freeze_min_var, unit="秒",
                      from_=0.5, to=5.0, increment=0.1, format="%.1f")

    def _build_volume(self, body):
        s = resolve_volume_consistency_settings(self.config_data)
        frame = ttk.LabelFrame(body, text="音量一致性門檻", padding=(10, 6))
        frame.pack(fill="x", pady=(0, 8))
        self.vol_segment_var = tk.DoubleVar(value=s["segment_seconds"])
        self._spin_row(frame, "音量分段秒數:", self.vol_segment_var, unit="秒",
                      from_=10.0, to=60.0, increment=5.0, format="%.0f")
        self.vol_deviation_var = tk.DoubleVar(value=s["deviation_lu"])
        self._spin_row(frame, "音量落差門檻:", self.vol_deviation_var,
                      unit="LU", from_=1.5, to=8.0, increment=0.5,
                      format="%.1f")

    def _build_color(self, body):
        s = resolve_colorcheck_settings(self.config_data)
        frame = ttk.LabelFrame(body, text="曝光與色偏門檻", padding=(10, 6))
        frame.pack(fill="x", pady=(0, 8))
        self.dark_luma_var = tk.DoubleVar(value=s["dark_luma"])
        self._spin_row(frame, "過暗門檻:", self.dark_luma_var,
                      from_=20, to=100, increment=5, format="%.0f")
        self.bright_luma_var = tk.DoubleVar(value=s["bright_luma"])
        self._spin_row(frame, "過曝門檻:", self.bright_luma_var,
                      from_=160, to=240, increment=5, format="%.0f")
        self.color_cast_var = tk.DoubleVar(value=s["cast_threshold"])
        self._spin_row(frame, "色偏門檻:", self.color_cast_var,
                      unit="（0~255 亮度值）", from_=5, to=25, increment=1,
                      format="%.0f")

    def _build_pacing(self, body):
        s = resolve_pacing_settings(self.config_data)
        frame = ttk.LabelFrame(body, text="剪輯節奏門檻", padding=(10, 6))
        frame.pack(fill="x", pady=(0, 8))
        self.pace_static_var = tk.DoubleVar(value=s["max_static_seconds"])
        self._spin_row(frame, "畫面不變上限:", self.pace_static_var, unit="秒",
                      from_=5, to=300, increment=5, format="%.0f")
        self.pace_threshold_var = tk.DoubleVar(value=s["scene_threshold"])
        self._spin_row(frame, "剪接偵測靈敏度:", self.pace_threshold_var,
                      unit="（越小越敏感）", from_=0.05, to=0.90,
                      increment=0.05, format="%.2f")

    def _build_audiofix(self, body):
        s = resolve_audiofix_settings(self.config_data)
        frame = ttk.LabelFrame(
            body, text="音訊修復設定（畫面原樣複製、僅處理音軌）",
            padding=(10, 6))
        frame.pack(fill="x", pady=(0, 8))
        row = ttk.Frame(frame)
        row.pack(fill="x")
        self.fix_denoise_var = tk.BooleanVar(value=s["denoise"])
        ttk.Checkbutton(row, text="降噪", variable=self.fix_denoise_var
                       ).pack(side="left")
        self.fix_strength_var = tk.DoubleVar(value=s["denoise_strength"])
        ttk.Spinbox(row, from_=6.0, to=40.0, increment=1.0, width=4,
                  textvariable=self.fix_strength_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row, text="dB").pack(side="left", padx=(0, 10))
        self.fix_highpass_var = tk.BooleanVar(value=s["highpass"])
        ttk.Checkbutton(row, text="去低頻隆隆", variable=self.fix_highpass_var
                       ).pack(side="left")
        self.fix_hz_var = tk.DoubleVar(value=s["highpass_hz"])
        ttk.Spinbox(row, from_=40.0, to=200.0, increment=10.0, width=5,
                  textvariable=self.fix_hz_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row, text="Hz").pack(side="left", padx=(0, 10))
        self.fix_loudnorm_var = tk.BooleanVar(value=s["loudnorm"])
        ttk.Checkbutton(row, text="響度正規化", variable=self.fix_loudnorm_var
                       ).pack(side="left")

    def _build_subtitle(self, body):
        s = resolve_subcheck_settings(self.config_data)
        frame = ttk.LabelFrame(body, text="字幕健檢門檻", padding=(10, 6))
        frame.pack(fill="x", pady=(0, 8))
        self.cps_var = tk.DoubleVar(value=s["cps_limit"])
        self._spin_row(frame, "閱讀速度上限:", self.cps_var, unit="字/秒",
                      from_=10.0, to=25.0, increment=1.0, format="%.0f")
        self.min_dur_var = tk.DoubleVar(value=s["min_duration"])
        self._spin_row(frame, "最短顯示秒數:", self.min_dur_var, unit="秒",
                      from_=0.3, to=2.0, increment=0.1, format="%.1f")
        self.max_lines_var = tk.IntVar(value=s["max_lines"])
        self._spin_row(frame, "最多行數:", self.max_lines_var, unit="行",
                      from_=1, to=4, increment=1)
        self.max_chars_var = tk.IntVar(value=s["max_chars_per_line"])
        self._spin_row(frame, "單行字數上限:", self.max_chars_var, unit="字",
                      from_=10, to=60, increment=1)

    def _build_adfriendly(self, body):
        s = resolve_adfriendly_settings(self.config_data)
        frame = ttk.LabelFrame(body, text="廣告友善度設定", padding=(10, 6))
        frame.pack(fill="x", pady=(0, 8))
        self.ad_window_var = tk.DoubleVar(value=s["window_seconds"])
        self._spin_row(frame, "叢集時間窗:", self.ad_window_var, unit="秒",
                      from_=10, to=120, increment=5, format="%.0f")
        self.ad_threshold_var = tk.DoubleVar(value=s["cluster_threshold"])
        self._spin_row(frame, "高風險門檻:", self.ad_threshold_var, unit="分",
                      from_=1.0, to=10.0, increment=0.5, format="%.1f")
        self.ad_opening_var = tk.DoubleVar(value=s["opening_seconds"])
        self._spin_row(frame, "開頭加強檢查:", self.ad_opening_var, unit="秒",
                      from_=0, to=30, increment=1, format="%.0f")
        self.ad_extra_var = tk.StringVar(value=s["extra_terms"])
        self._text_row(frame, "自訂補充詞:", self.ad_extra_var)
        self.ad_ignore_var = tk.StringVar(value=s["ignore_terms"])
        self._text_row(frame, "排除誤判詞:", self.ad_ignore_var)

    def _build_hook(self, body):
        s = resolve_hookcheck_settings(self.config_data)
        frame = ttk.LabelFrame(body, text="開場健檢設定", padding=(10, 6))
        frame.pack(fill="x", pady=(0, 8))
        self.hook_target_var = tk.DoubleVar(value=s["target_seconds"])
        self._spin_row(frame, "幾秒內要進正題:", self.hook_target_var,
                      unit="秒", from_=5, to=60, increment=1, format="%.0f")
        self.hook_greeting_var = tk.DoubleVar(
            value=s["max_greeting_seconds"])
        self._spin_row(frame, "寒暄上限:", self.hook_greeting_var, unit="秒",
                      from_=1, to=30, increment=1, format="%.0f")
        self.hook_silence_var = tk.DoubleVar(value=s["max_head_silence"])
        self._spin_row(frame, "開頭乾等上限:", self.hook_silence_var,
                      unit="秒", from_=0, to=10, increment=0.5,
                      format="%.1f")
        self.hook_extra_var = tk.StringVar(value=s["extra_filler_terms"])
        self._text_row(frame, "自訂套語:", self.hook_extra_var)
        self.hook_ignore_var = tk.StringVar(value=s["ignore_terms"])
        self._text_row(frame, "排除誤判詞:", self.hook_ignore_var)

    def _build_punct(self, body):
        s = resolve_punctstyle_settings(self.config_data)
        frame = ttk.LabelFrame(body, text="標點規範強度", padding=(10, 6))
        frame.pack(fill="x", pady=(0, 8))
        row = ttk.Frame(frame)
        row.pack(fill="x")
        self.punct_mode_var = tk.StringVar(value=s["mode"])
        for value, label in (("trim", "只拿掉行尾標點"),
                             ("subtitle", "完整字幕慣例"),
                             ("off", "不套用")):
            ttk.Radiobutton(row, text=label, value=value,
                           variable=self.punct_mode_var).pack(
                side="left", padx=(0, 8))

    def _build_filename(self, body):
        s = resolve_preflight_settings(self.config_data)
        frame = ttk.LabelFrame(body, text="檔名判定", padding=(10, 6))
        frame.pack(fill="x", pady=(0, 8))
        self.name_terms_var = tk.StringVar(value=s["generic_name_terms"])
        self._text_row(frame, "無資訊檔名字眼:", self.name_terms_var)

    def _text_row(self, parent, label, var):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, width=11).pack(side="left")
        ttk.Entry(row, textvariable=var).pack(
            side="left", fill="x", expand=True, padx=(2, 0))
        return row

    # -- v1.51.0 新增：發佈／封面／章節三個併入視窗原本的門檻 -----------
    def _build_publish(self, body):
        s = resolve_publishcheck_settings(self.config_data)
        frame = ttk.LabelFrame(body, text="發佈健檢上限（標題／說明欄／標籤）",
                               padding=(10, 6))
        frame.pack(fill="x", pady=(0, 8))
        self.pub_title_limit_var = tk.IntVar(value=s["title_limit"])
        self._spin_row(frame, "標題上限:", self.pub_title_limit_var,
                      unit="字元", from_=20, to=200, increment=10)
        self.pub_mobile_var = tk.IntVar(value=s["title_mobile_visible"])
        self._spin_row(frame, "手機可見標題:", self.pub_mobile_var, unit="字元",
                      from_=10, to=100, increment=5)
        self.pub_desc_limit_var = tk.IntVar(
            value=s["description_byte_limit"])
        self._spin_row(frame, "說明欄上限:", self.pub_desc_limit_var,
                      unit="位元組", from_=500, to=10000, increment=500)
        self.pub_max_tag_var = tk.IntVar(value=s["max_hashtags"])
        self._spin_row(frame, "hashtag 上限:", self.pub_max_tag_var, unit="個",
                      from_=1, to=30, increment=1)
        self.pub_rec_tag_var = tk.IntVar(value=s["recommended_hashtags"])
        self._spin_row(frame, "hashtag 建議上限:", self.pub_rec_tag_var,
                      unit="個", from_=1, to=15, increment=1)
        self.pub_tag_char_var = tk.IntVar(value=s["tag_char_limit"])
        self._spin_row(frame, "標籤總字元上限:", self.pub_tag_char_var,
                      unit="字元", from_=100, to=1000, increment=50)

    def _build_thumb(self, body):
        s = resolve_thumbcheck_settings(self.config_data)
        frame = ttk.LabelFrame(body, text="封面健檢門檻", padding=(10, 6))
        frame.pack(fill="x", pady=(0, 8))
        self.thumb_width_var = tk.IntVar(value=s["mobile_width"])
        self._spin_row(frame, "手機縮圖寬度:", self.thumb_width_var, unit="像素",
                      from_=80, to=640, increment=20)
        self.thumb_detail_var = tk.DoubleVar(value=s["min_detail_keep"])
        self._spin_row(frame, "細節保留下限:", self.thumb_detail_var,
                      from_=0.05, to=1.0, increment=0.05, format="%.2f")
        self.thumb_contrast_var = tk.DoubleVar(value=s["min_contrast"])
        self._spin_row(frame, "對比下限:", self.thumb_contrast_var,
                      from_=10, to=200, increment=5, format="%.0f")
        self.thumb_saturation_var = tk.DoubleVar(value=s["min_saturation"])
        self._spin_row(frame, "飽和度下限:", self.thumb_saturation_var,
                      from_=0, to=120, increment=5, format="%.0f")
        self.thumb_filesize_var = tk.DoubleVar(value=s["max_file_mb"])
        self._spin_row(frame, "檔案上限:", self.thumb_filesize_var, unit="MB",
                      from_=0.5, to=10.0, increment=0.5, format="%.1f")

    def _build_chapter(self, body):
        s = resolve_chaptercheck_settings(self.config_data)
        frame = ttk.LabelFrame(body, text="章節規則門檻", padding=(10, 6))
        frame.pack(fill="x", pady=(0, 8))
        self.chapter_min_seconds_var = tk.DoubleVar(
            value=s["min_chapter_seconds"])
        self._spin_row(frame, "每章最短:", self.chapter_min_seconds_var,
                      unit="秒", from_=1, to=120, increment=1, format="%.0f")
        self.chapter_min_count_var = tk.IntVar(value=s["min_chapter_count"])
        self._spin_row(frame, "最少章節數:", self.chapter_min_count_var,
                      unit="章", from_=2, to=10, increment=1)
        ttk.Label(
            frame, foreground="#666666", anchor="w", justify="left",
            wraplength=460,
            text="預設值就是 YouTube 目前的規則（每章 10 秒、至少 3 章），"
                 "一般不需要調整。",
        ).pack(fill="x", pady=(4, 0))

    # ------------------------------------------------------------------
    def _on_save(self):
        def safe(var, fallback, cast=float):
            try:
                return cast(var.get())
            except (tk.TclError, ValueError):
                return fallback

        self.config_data["audiocheck"] = {
            "quiet_lufs": safe(self.quiet_var, -19.0),
            "noise_floor_db": safe(self.noise_var, -50.0),
            "clip_peak_db": safe(self.clip_var, -0.5),
            "balance_db": safe(self.balance_var, 6.0),
        }
        merged_vc = dict(self.config_data.get("videocheck", {}))
        merged_vc.update({
            "bitrate_margin": safe(self.bitrate_margin_var, 1.0),
            "head_max_seconds": safe(self.head_max_var, 1.0),
            "freeze_min_seconds": safe(self.freeze_min_var, 1.0),
        })
        self.config_data["videocheck"] = merged_vc
        self.config_data["volumeconsistency"] = {
            "segment_seconds": safe(self.vol_segment_var, 20.0),
            "deviation_lu": safe(self.vol_deviation_var, 3.0),
        }
        self.config_data["colorcheck"] = {
            "dark_luma": safe(self.dark_luma_var, 60.0),
            "bright_luma": safe(self.bright_luma_var, 200.0),
            "cast_threshold": safe(self.color_cast_var, 10.0),
        }
        self.config_data["pacing"] = {
            "scene_threshold": safe(self.pace_threshold_var, 0.30),
            "max_static_seconds": safe(self.pace_static_var, 25.0),
        }
        self.config_data["audiofix"] = {
            "denoise": bool(self.fix_denoise_var.get()),
            "denoise_strength": safe(self.fix_strength_var, 12.0),
            "highpass": bool(self.fix_highpass_var.get()),
            "highpass_hz": safe(self.fix_hz_var, 80.0),
            "loudnorm": bool(self.fix_loudnorm_var.get()),
        }
        self.config_data["subtitlecheck"] = {
            "cps_limit": safe(self.cps_var, 17.0),
            "min_duration": safe(self.min_dur_var, 0.8),
            "max_lines": safe(self.max_lines_var, 2, cast=int),
            "max_chars_per_line": safe(self.max_chars_var, 21, cast=int),
        }
        self.config_data["adfriendly"] = {
            "window_seconds": safe(self.ad_window_var, 30.0),
            "cluster_threshold": safe(self.ad_threshold_var, 3.0),
            "opening_seconds": safe(self.ad_opening_var, 7.0),
            "extra_terms": self.ad_extra_var.get().strip(),
            "ignore_terms": self.ad_ignore_var.get().strip(),
        }
        self.config_data["hookcheck"] = {
            "target_seconds": safe(self.hook_target_var, 15.0),
            "max_greeting_seconds": safe(self.hook_greeting_var, 5.0),
            "max_head_silence": safe(self.hook_silence_var, 1.5),
            "extra_filler_terms": self.hook_extra_var.get().strip(),
            "ignore_terms": self.hook_ignore_var.get().strip(),
        }
        self.config_data["punctstyle"] = dict(
            self.config_data.get("punctstyle") or {},
            mode=self.punct_mode_var.get())
        preflight = dict(self.config_data.get("preflight") or {})
        preflight["generic_name_terms"] = self.name_terms_var.get().strip()
        self.config_data["preflight"] = preflight
        self.config_data["publishcheck"] = {
            "title_limit": safe(self.pub_title_limit_var, 100, cast=int),
            "title_mobile_visible": safe(self.pub_mobile_var, 40, cast=int),
            "description_byte_limit": safe(
                self.pub_desc_limit_var, 5000, cast=int),
            "max_hashtags": safe(self.pub_max_tag_var, 15, cast=int),
            "recommended_hashtags": safe(self.pub_rec_tag_var, 5, cast=int),
            "tag_char_limit": safe(self.pub_tag_char_var, 500, cast=int),
        }
        self.config_data["thumbcheck"] = {
            "mobile_width": safe(self.thumb_width_var, 200, cast=int),
            "min_detail_keep": safe(self.thumb_detail_var, 0.35),
            "min_contrast": safe(self.thumb_contrast_var, 40.0),
            "min_saturation": safe(self.thumb_saturation_var, 15.0),
            "max_file_mb": safe(self.thumb_filesize_var, 2.0),
        }
        self.config_data["chaptercheck"] = {
            "min_chapter_seconds": safe(
                self.chapter_min_seconds_var, 10.0),
            "min_chapter_count": safe(
                self.chapter_min_count_var, 3, cast=int),
        }
        try:
            save_config(self.config_data)
        except OSError:
            pass  # 存檔失敗不影響本次使用。
        self.destroy()
