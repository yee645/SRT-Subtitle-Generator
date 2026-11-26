# -*- coding: utf-8 -*-
"""
剪輯器版面（E 系列，`docs/ROADMAP_EDITOR.md`）：照主流剪輯軟體（剪映專業版、Premiere）的單一工作區排版。

```
頂列：程式名稱、專案名稱、開／存專案 ……………… 轉寫與金鑰、即時查譯、導覽、深淺色、〔匯出〕
左邊圖示列＋左側面板（媒體／字幕／智慧剪輯／健檢）｜預覽＋播放控制｜屬性
時間軸工具列（復原、重做、存字幕、刪除選取 …… 拉遠、拉近、整支）＋時間軸
```

E-1 只換外殼：**功能一個不少、也不另寫一份**。`EditorWindow` 繼承四頁籤的 `MainWindow`，建好之後把同一批面板與
按鈕搬到新的位置（Qt 的元件搬家後訊號照舊接著），關視窗前的詢問、自動更新、一鍵安裝、設定存檔全部沿用。
四頁籤那份外殼收起來不顯示（`legacy_central`），裡面已經空了。

播放器面板（`PlayerPanel`）本身不顯示，它的畫面、時間軸、按鈕分散到各區；它與逐句校對原本「焦點在面板裡才有效」
的復原／重做／存字幕／尋找快捷鍵因此改掛在整個視窗上（同一組按鍵、同樣的動作）。

3.1 起（E-7b）新介面預設就是這個版面；`python main.py --qt --tabs`（或狀態列的〔改用四頁籤版面…〕）開回四頁籤。
"""
import os

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSlider, QAbstractSpinBox, QApplication, QButtonGroup, QComboBox, QDialog,
    QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPlainTextEdit, QTextEdit,
    QListWidgetItem, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QSplitter, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from gui_qt import icons, theme
from gui_qt import timeline as timeline_mod
from gui_qt.app import MainWindow, apply_theme
from gui_qt.media_bin import MediaBin
from gui_qt.places import EDITOR, LAYOUT_PROPERTY, relabel_tree
from subtitle import editorguide
from subtitle import playhead
from updater import APP_VERSION

EDITOR_FLAG = editorguide.EDITOR_FLAG
EDITOR_TITLE = f"SRT 字幕生成器（v{APP_VERSION}）"
# 狀態列的開場白（E-7b 起是預設版面，拿掉「試用」）
STATUS_INTRO = "左邊選媒體、字幕、智慧剪輯、健檢；右上角〔匯出〕。第一次用可以按頂列的〔?〕看剪輯器版面介紹。"
GUIDE_TITLE = "剪輯器版面介紹"
EDITOR_SIZE = (1440, 900)
EDITOR_MIN = (1100, 700)
LEFT_WIDTH = 400
# 左側面板各區想要的寬度：審片助手、健檢原本是整頁寬，切過去時把左側面板拉寬（從預覽借），切回來還原
SECTION_WIDTH = {"media": 340, "subtitles": 420, "smart": 660, "health": 660}
INSPECTOR_WIDTH = 300
RAIL_WIDTH = 64
SPLIT_KEY = "Ctrl+B"
# 快捷鍵（E-6a；照 ROADMAP 第四節）。存專案用 Ctrl+Shift+S：Ctrl+S 兩個版面都是「存字幕」，不改習慣。
KEYS = {"play": ("Space",), "rewind": ("J",), "pause": ("K",), "forward": ("L",),
        "prev_frame": ("Left",), "next_frame": ("Right",),
        "zoom_in": ("Ctrl+=", "Ctrl++"), "zoom_out": ("Ctrl+-",), "fit": ("Shift+Z",),
        "export": ("Ctrl+E",), "save_project": ("Ctrl+Shift+S",)}
# 選單列（E-6b）：(選單, [(項目, 目標, 快捷鍵提示) 或 None＝分隔線])。目標是元件路徑（按了＝按那顆，能不能按也照它）
# 或 "@方法名稱"。快捷鍵只寫在選單上給人看，真正的按鍵在 _install_shortcuts（同一組鍵註冊兩次 Qt 會兩個都不觸發）。
MENUS = (
    ("檔案", (("開啟影片…", "player_panel.open_btn", ""), ("載入字幕…", "player_panel.subs_btn", ""),
              ("匯入素材…", "media_bin.import_btn", ""), None,
              ("開專案…", "player_panel.open_project_btn", ""), ("存專案", "player_panel.save_project_btn", "Ctrl+Shift+S"),
              ("存字幕", "player_panel.save_btn", "Ctrl+S"), None,
              ("匯出…", "export_button", "Ctrl+E"), None, ("關閉視窗", "@close", ""))),
    ("編輯", (("復原", "player_panel.undo_btn", "Ctrl+Z"), ("重做", "player_panel.redo_btn", "Ctrl+Shift+Z"), None,
              ("在播放頭分割", "split_tool", "Ctrl+B"), ("刪除選取", "delete_tool", "Delete"), None,
              ("尋找取代", "@_find", "Ctrl+F"))),
    ("檢視", (("媒體", "@show_section:media", ""), ("字幕", "@show_section:subtitles", ""),
              ("智慧剪輯", "@show_section:smart", ""), ("健檢", "@show_section:health", ""), None,
              ("拉近", "player_panel.zoom_in_btn", "Ctrl+="), ("拉遠", "player_panel.zoom_out_btn", "Ctrl+-"),
              ("整支", "player_panel.fit_btn", "Shift+Z"), None,
              ("切換深淺色", "theme_tool", ""), None,
              ("切換下次開啟的版面（四頁籤／剪輯器）", "layout_btn", ""))),
    ("播放", (("播放／暫停", "play_tool", "Space"), ("上一格", "prev_frame_tool", "←"),
              ("下一格", "next_frame_tool", "→"), None,
              ("倒退 1 秒", "@jkl:J", "J"), ("暫停", "@jkl:K", "K"), ("播放／快轉", "@jkl:L", "L"))),
    ("說明", (("剪輯器版面介紹", "guide_tool", ""), ("轉寫與金鑰", "transcription_tool", ""),
              ("即時查譯", "lookup_tool", ""))),
)
# 預覽放大（E-6b）：看字幕邊緣、畫面細節；放大時可以用滑鼠拖著看別的地方
PREVIEW_ZOOMS = (("符合視窗", 1.0), ("放大 2 倍", 2.0), ("放大 4 倍", 4.0))

# 這些元件自己要用方向鍵（清單、數字欄、選單、滑桿、打字的地方）：焦點在它們上面時 ←／→ 不拿去逐格
ARROW_OWNERS = (QAbstractItemView, QAbstractSpinBox, QComboBox, QAbstractSlider, QLineEdit, QPlainTextEdit, QTextEdit)
TIMELINE_EMPTY_TEXT = "開啟影片後，縮圖、波形與字幕會排在這裡。"

# 左邊圖示列：(鍵, 圖示, 名稱, 提示)
RAIL = (
    ("media", "media", "媒體", "開啟影片與字幕、加入畫面與音樂、音訊轉影片、批次處理"),
    ("subtitles", "subtitles", "字幕", "生成字幕、逐句校對、尋找取代、翻譯、字幕樣式"),
    ("smart", "smart", "智慧剪輯", "審片助手：分析、段落清單、粗剪、精彩合輯、章節、封面候選、直式短片"),
    ("health", "health", "健檢", "上架前的 18 項檢查與一鍵修復、發佈文字、封面圖"),
)

# 匯出視窗（E-5）：四段的說明
EXPORT_SIZE = (1080, 760)
EXPORT_NOTES = {
    "finish": "照下面的輸出設定一次做完：勾選的字幕檔、燒錄硬字幕影片。檔名跟著影片、同名加編號，不問存到哪裡。"
              "燒錄是燒在原始影片上，剪點、素材軌、轉場不算進去（那些用「剪好的影片」）。",
    "video": "照剪點輸出：照時間軸上啟用中的剪點剪成新影片。輸出多軌：連同疊加的畫面與音樂、轉場、畫面調整合成一支。"
             "原始影片都不動。",
    "subtitles": "一次匯出一種格式，會問存到哪裡；不看上面的勾選，也不必開影片。要好幾種語言用〔多語字幕包…〕。",
    "branding": "接上片頭、片尾，疊上浮水印（Logo），設定一次、之後每支沿用。輸出成新檔，原檔不動。",
}

# 屬性面板（E-3a）
INSPECTOR_HINT = "點時間軸上的字幕或素材，這裡會換成它的屬性。"
TRACK_TITLES = {"overlays": "疊加的畫面", "music": "音樂"}
CUE_EDIT_HINT = "文字與時間在右邊的屬性裡改：改完按 Ctrl+Enter、點別句或離開編輯框就套用，Esc 放回原本的。"

# 現有功能在新版面的哪裡（PR 的對照表與測試都照這一份）：(功能, 元件的路徑, 區塊)
# 路徑從視窗算起，例如 "player_panel.open_btn"。區塊：top／left:<鍵>／preview／inspector／timeline／export。
FEATURE_MAP = (
    ("開專案", "player_panel.open_project_btn", "top"),
    ("存專案", "player_panel.save_project_btn", "top"),
    ("轉寫與金鑰", "transcription_tool", "top"),
    ("即時查譯", "lookup_tool", "top"),
    ("新介面導覽（剪輯器裡打開的是剪輯器版面介紹，E-7b）", "guide_tool", "top"),
    ("深淺色", "theme_tool", "top"),
    ("匯出", "export_button", "top"),
    ("素材庫（匯入一批、縮圖、拖到時間軸、加到播放頭、開成主片；E-4）", "media_bin", "left:media"),
    ("開啟影片", "player_panel.open_btn", "left:media"),
    ("載入字幕", "player_panel.subs_btn", "left:media"),
    ("加入畫面", "player_panel.add_overlay_btn", "left:media"),
    ("加入音樂", "player_panel.add_music_btn", "left:media"),
    ("音訊轉影片", "audiovis_btn", "left:media"),
    ("批次一鍵完成", "batch_btn", "left:media"),
    ("生成字幕", "player_panel.generate_btn", "left:subtitles"),
    ("逐句校對（新增、刪除、尋找取代、翻譯、字幕樣式、自動修正）", "cue_panel", "left:subtitles"),
    ("審片助手（分析、粗剪、精彩合輯、章節、封面候選、直式短片）", "review_panel", "left:smart"),
    ("健檢中心（18 項檢查、一鍵修復、發佈文字、封面圖、系列一致性）", "health_panel", "left:health"),
    ("影片畫面與字幕疊加", "player_panel.view", "preview"),
    ("播放／暫停", "play_tool", "preview"),
    ("播放進度", "player_panel.slider", "preview"),
    ("時間（E-6a 改成時:分:秒.百分之一秒）", "timecode_label", "preview"),
    ("上一格（E-6a）", "prev_frame_tool", "preview"),
    ("預覽放大（E-6b）", "preview_zoom_combo", "preview"),
    ("專注預覽：收起左右面板（E-6b）", "focus_tool", "preview"),
    ("下一格（E-6a）", "next_frame_tool", "preview"),
    ("影片與字幕狀態（改過幾處沒存）", "player_panel.info_label", "inspector"),
    ("畫面調整", "player_panel.picture_btn", "inspector"),
    ("編輯用代理檔", "player_panel.proxy_box", "inspector"),
    ("剪點種類", "player_panel.cut_combo", "inspector"),
    ("預覽剪後", "player_panel.preview_cut_box", "inspector"),
    ("接縫轉場", "player_panel.seam_combo", "inspector"),
    ("轉場長度", "player_panel.seam_spin", "inspector"),
    ("還原剪點", "player_panel.cut_reset_btn", "inspector"),
    ("素材屬性：音量、循環、講話時壓低、配樂設定", "player_panel.volume_spin", "inspector"),
    ("素材屬性：位置、帶聲音、調畫面", "player_panel.position_combo", "inspector"),
    ("預覽畫面素材", "player_panel.preview_box", "inspector"),
    ("字幕的文字（逐句校對的編輯框，E-3a 搬到屬性面板）", "cue_panel.editor", "inspector"),
    ("字幕的開始／結束時間（E-3a；原本只能在時間軸上拖）", "cue_start_spin", "inspector"),
    ("字幕的開始／結束時間（結束）", "cue_end_spin", "inspector"),
    ("字幕樣式（屬性面板的捷徑，同逐句校對那顆）", "cue_style_btn", "inspector"),
    ("復原", "player_panel.undo_btn", "timeline"),
    ("重做", "player_panel.redo_btn", "timeline"),
    ("存字幕", "player_panel.save_btn", "timeline"),
    ("在播放頭分割字幕（E-2b）", "split_tool", "timeline"),
    ("刪除選取（字幕或素材；原本只刪素材）", "delete_tool", "timeline"),
    ("吸附開關（E-2b）", "snap_tool", "timeline"),
    ("縮放滑桿（E-2b）", "zoom_slider", "timeline"),
    ("時間軸縮放（拉遠、拉近、整支）", "player_panel.fit_btn", "timeline"),
    ("時間軸（字幕、波形、縮圖、剪點、素材軌）", "player_panel.timeline", "timeline"),
    ("照剪點輸出", "player_panel.export_btn", "export"),
    ("輸出多軌", "player_panel.assemble_btn", "export"),
    ("一鍵完成輸出（輸出設定、字幕檔、燒錄）", "output_panel", "export"),
    ("單獨匯出一種字幕檔（E-5 獨立成「字幕檔」一段）", "output_panel.single_section", "export"),
    ("多語字幕包（E-5 在匯出視窗多一顆捷徑，同〔翻譯字幕…〕）", "export_pack_btn", "export"),
    ("品牌套版（片頭／片尾／浮水印）", "output_panel.branding", "export"),
    ("輸出進度與結果（E-5 釘在匯出視窗最下面）", "output_panel.status_area", "export"),
)


# 四頁籤時代的按鈕，在新版面換成別的元件（同一個動作）：(舊的, 新的)
REPLACED = (
    ("player_panel.play_btn", "play_tool"),
    ("transcription_btn", "transcription_tool"),
    ("lookup_btn", "lookup_tool"),
    ("guide_btn", "guide_tool"),
    ("theme_btn", "theme_tool"),
    ("player_panel.remove_track_btn", "delete_tool"),
    ("player_panel.time_label", "timecode_label"),  # E-6a：時間碼換寫法（四頁籤照舊）  # E-2b：刪素材也刪字幕（刪最後選的那個）
)


def region(win, name):
    """FEATURE_MAP 的區塊名稱 → 那一區的容器。"""
    if name.startswith("left:"):
        return win.left_pages[name[5:]]
    return {"top": win.top_bar, "preview": win.preview_panel, "inspector": win.inspector_panel,
            "timeline": win.timeline_panel, "export": win.export_dialog}[name]


def resolve(win, path):
    """FEATURE_MAP 的路徑 → 元件。"""
    obj = win
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


class _FpsProbe(QObject):
    """背景量影格率（ffprobe），量好送回主執行緒；逐格照它走。"""

    done = Signal(str, float)

    def start(self, path):
        import threading

        def run():
            from subtitle.media import probe_fps
            try:
                fps = probe_fps(path)
            except Exception:  # noqa: BLE001 — 量不到就用預設的 30
                fps = playhead.DEFAULT_FPS
            self.done.emit(path, float(fps))

        threading.Thread(target=run, daemon=True).start()


class _EnabledMirror(QObject):
    """把一顆（藏起來的）按鈕能不能按，同步到另一顆。"""

    def __init__(self, src, dst):
        super().__init__(dst)
        self._dst = dst
        dst.setEnabled(src.isEnabled())
        src.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.EnabledChange:
            self._dst.setEnabled(obj.isEnabled())
        return False


def _title(text, name="panelTitle"):
    label = QLabel(text)
    label.setObjectName(name)
    return label


def _secondary(label):
    label.setProperty("secondary", True)
    label.setWordWrap(True)
    return label


def _scroll(widget):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setWidget(widget)
    return area


class EditorWindow(MainWindow):
    """主流剪輯軟體排版的主視窗（E 系列）。"""

    LAYOUT = editorguide.EDITOR

    def __init__(self, config_data=None, persist=None):
        super().__init__(config_data, persist)
        # 面板的說明文字照剪輯器的位置講（「②字幕頁」→「左邊「字幕」」…，gui_qt/places.py）；之後才顯示的字由 here() 換
        self.setProperty(LAYOUT_PROPERTY, EDITOR)
        self.setWindowTitle(EDITOR_TITLE)
        self.resize(*EDITOR_SIZE)
        self.setMinimumSize(*EDITOR_MIN)
        self._icon_buttons = []   # [(按鈕, 圖示名稱)]：換主題時重畫
        p = self.player_panel

        # 四頁籤的外殼收起來（面板搬走之後是空的）；不刪，舊程式碼與自檢讀得到 tabs
        self.legacy_central = self.takeCentralWidget()
        root = QWidget()
        root.setObjectName("editorRoot")
        self.legacy_central.setParent(root)
        self.legacy_central.hide()
        # 播放器面板不顯示（裡面的元件搬到各區），播放器、匯出工作這些照舊掛在它底下
        p.setParent(root)
        p.hide()
        for btn in (self.guide_btn, self.theme_btn):  # 搬到頂列，改成圖示按鈕
            self.statusBar().removeWidget(btn)
            btn.setParent(self.legacy_central)
        for banner in (self.ffmpeg_banner, self.update_banner):
            banner.setStyleSheet("")  # 改用設計基準的提示列顏色

        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.top_bar = self._build_top_bar()
        outer.addWidget(self.top_bar)
        outer.addWidget(self.ffmpeg_banner)
        outer.addWidget(self.update_banner)
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(6, 6, 6, 6)
        body_layout.setSpacing(6)
        self.rail = self._build_rail()
        body_layout.addWidget(self.rail)
        self.hsplit = QSplitter(Qt.Horizontal)
        self.hsplit.setHandleWidth(6)
        self.left_panel = self._build_left()
        self.preview_panel = self._build_preview()
        self.inspector_panel = self._build_inspector()
        for w in (self.left_panel, self.preview_panel, self.inspector_panel):
            self.hsplit.addWidget(w)
        self.hsplit.setCollapsible(1, False)
        self.hsplit.setStretchFactor(0, 0)
        self.hsplit.setStretchFactor(1, 1)
        self.hsplit.setStretchFactor(2, 0)
        self.hsplit.setSizes([LEFT_WIDTH, EDITOR_SIZE[0] - LEFT_WIDTH - INSPECTOR_WIDTH - RAIL_WIDTH,
                              INSPECTOR_WIDTH])
        self.vsplit = QSplitter(Qt.Vertical)
        self.vsplit.setHandleWidth(6)
        self.vsplit.addWidget(self.hsplit)
        self.timeline_panel = self._build_timeline()
        self.vsplit.addWidget(self.timeline_panel)
        self.vsplit.setCollapsible(0, False)
        self.vsplit.setCollapsible(1, False)
        self.vsplit.setStretchFactor(0, 1)
        self.vsplit.setStretchFactor(1, 0)
        body_layout.addWidget(self.vsplit, 1)
        outer.addWidget(body, 1)
        self.setCentralWidget(root)
        self.export_dialog = self._build_export_dialog()
        self._build_menus()
        relabel_tree(self, skip=(self.legacy_central,))  # 已經建好的字換成剪輯器的說法；收起來的外殼不動

        self._install_shortcuts()
        p.player.playbackStateChanged.connect(lambda _s: self._update_play_icon())
        self._project_timer = QTimer(self)
        self._project_timer.setInterval(700)
        self._project_timer.timeout.connect(self.refresh_project_name)
        self._project_timer.start()
        self.show_section("media")
        self.apply_editor_theme(self.config_data.get("theme", "light"))
        self.refresh_project_name()
        self.statusBar().showMessage(STATUS_INTRO)

    # ----- 各區 -----
    def _tool(self, icon_name, tip, slot, checkable=False, text=""):
        btn = QToolButton()
        btn.setToolTip(tip)
        btn.setCheckable(checkable)
        btn.setAutoRaise(True)
        if text:
            btn.setText(text)
        btn.clicked.connect(lambda _c=False: slot())
        self._icon_buttons.append((btn, icon_name))
        return btn

    def _iconify(self, btn, icon_name, text=None, role=None):
        """現有的按鈕加上圖示（`text` 給空字串＝只留圖示，說明在提示文字裡）。"""
        if text is not None:
            if not text and btn.text():
                tip = btn.toolTip()
                btn.setToolTip(btn.text() + ("：" + tip if tip else ""))
            btn.setText(text)
        if role:
            btn.setProperty("role", role)
        self._icon_buttons.append((btn, icon_name))
        return btn

    def _build_top_bar(self):
        p = self.player_panel
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(48)
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(6)
        self.logo_label = QLabel()
        row.addWidget(self.logo_label)
        name = QLabel("SRT 字幕生成器")
        name.setObjectName("appName")
        row.addWidget(name)
        row.addSpacing(16)
        self.project_name_label = QLabel()
        self.project_name_label.setObjectName("projectName")
        row.addWidget(self.project_name_label)
        row.addSpacing(8)
        for btn, icon_name in ((p.open_project_btn, "open"), (p.save_project_btn, "save")):
            self._iconify(btn, icon_name, role="ghost")
            row.addWidget(btn)
        row.addStretch(1)
        self.transcription_tool = self._tool("key", "轉寫與金鑰：" + self.transcription_btn.toolTip(),
                                             self.open_transcription_settings)
        self.lookup_tool = self._tool("translate", "即時查譯：" + self.lookup_btn.toolTip(), self.open_lookup)
        self.guide_tool = self._tool("help", "剪輯器版面介紹：版面、這一版多了什麼、四頁籤的東西在哪、快捷鍵", self.open_guide)
        self.theme_tool = self._tool("moon", "切換深色／淺色", self.toggle_theme)
        for btn in (self.transcription_tool, self.lookup_tool, self.guide_tool, self.theme_tool):
            row.addWidget(btn)
        row.addSpacing(8)
        self.export_button = QPushButton("匯出")
        self.export_button.setProperty("role", "primary")
        self.export_button.setToolTip("匯出字幕檔、燒錄硬字幕、照剪點輸出、輸出多軌、品牌套版、多語字幕包")
        self.export_button.clicked.connect(lambda _c=False: self.open_export())
        self._icon_buttons.append((self.export_button, "export"))
        row.addWidget(self.export_button)
        return bar

    def _build_rail(self):
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(RAIL_WIDTH)
        col = QVBoxLayout(rail)
        col.setContentsMargins(4, 8, 4, 8)
        col.setSpacing(4)
        self.rail_group = QButtonGroup(self)
        self.rail_group.setExclusive(True)
        self.rail_buttons = {}
        for key, icon_name, label, tip in RAIL:
            btn = QToolButton()
            btn.setText(label)
            btn.setToolTip(tip)
            btn.setCheckable(True)
            btn.setProperty("role", "rail")
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.clicked.connect(lambda _c=False, k=key: self.show_section(k))
            self.rail_group.addButton(btn)
            self.rail_buttons[key] = btn
            self._icon_buttons.append((btn, icon_name))
            col.addWidget(btn)
        col.addStretch(1)
        return rail

    def _build_left(self):
        p = self.player_panel
        panel = QFrame()
        panel.setObjectName("leftPanel")
        panel.setMinimumWidth(300)
        col = QVBoxLayout(panel)
        col.setContentsMargins(0, 0, 0, 0)
        self.left_stack = QStackedWidget()
        col.addWidget(self.left_stack)
        self.left_pages = {}

        # 媒體
        media = QWidget()
        m = QVBoxLayout(media)
        m.setContentsMargins(12, 12, 12, 12)
        m.setSpacing(6)
        m.addWidget(_title("媒體"))
        m.addWidget(_title("素材庫", "sectionTitle"))
        self.media_bin = MediaBin(p, icon_for=lambda name: icons.icon(
            name, theme.tokens(getattr(self, "_theme", "light"))["text.secondary"], size=40))
        p.timeline.durationChanged.connect(lambda _d: self.media_bin._update_buttons())
        m.addWidget(self.media_bin, 1)
        m.addWidget(_title("匯入", "sectionTitle"))
        for btn, icon_name in ((p.open_btn, "film"), (p.subs_btn, "subtitles"),
                               (p.add_overlay_btn, "image"), (p.add_music_btn, "music")):
            m.addWidget(self._iconify(btn, icon_name, role="list"))
        m.addWidget(_secondary(QLabel("加入的畫面與音樂放在播放頭的位置，放上去之後在時間軸上拖動、"
                                      "在右邊的屬性裡調整。")))
        m.addWidget(_title("素材準備", "sectionTitle"))
        for btn, icon_name in ((self.audiovis_btn, "wave"), (self.batch_btn, "batch")):
            m.addWidget(self._iconify(btn, icon_name, role="list"))
        self._add_page("media", _scroll(media))  # 多出來的高度給素材庫

        # 字幕
        subs = QWidget()
        s = QVBoxLayout(subs)
        s.setContentsMargins(12, 12, 12, 4)
        s.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(_title("字幕"))
        head.addStretch(1)
        # 翻譯、樣式從逐句校對那一排搬上來：左側面板比原本的②頁窄，五顆擠一排會被截掉
        for btn in (self.cue_panel.translate_btn, self.cue_panel.style_btn):
            head.addWidget(btn)
        head.addWidget(self._iconify(p.generate_btn, "generate"))
        s.addLayout(head)
        self.cue_panel.layout().setContentsMargins(0, 0, 0, 0)
        self.cue_panel.title.hide()  # 「逐句校對」那行標題：上面已經有「字幕」
        s.addWidget(self.cue_panel, 1)
        self._add_page("subtitles", subs)

        # 智慧剪輯、健檢：原本整頁寬，放進可以捲的區塊
        self._add_page("smart", self._titled("智慧剪輯", _scroll(self.review_panel)))
        self._add_page("health", self._titled("健檢", _scroll(self.health_panel)))
        return panel

    def _titled(self, text, widget):
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(12, 12, 4, 4)
        col.setSpacing(6)
        col.addWidget(_title(text))
        col.addWidget(widget, 1)
        return page

    def _add_page(self, key, widget):
        self.left_pages[key] = widget
        self.left_stack.addWidget(widget)

    def _build_preview(self):
        p = self.player_panel
        panel = QFrame()
        panel.setObjectName("previewPanel")
        col = QVBoxLayout(panel)
        col.setContentsMargins(8, 8, 8, 8)
        col.setSpacing(6)
        p.view.setObjectName("previewView")
        p.view.setMinimumSize(320, 180)
        col.addWidget(p.view, 1)
        col.addWidget(p.slider)
        row = QHBoxLayout()
        # E-6a：時間碼改成「時:分:秒.百分之一秒」（播放器原本那個「分:秒.十分之一秒」收起來，四頁籤照舊）
        p.time_label.setParent(self.legacy_central)  # 換父元件就藏起來了（收起來的外殼）
        self.timecode_label = QLabel()
        self.timecode_label.setObjectName("timecode")
        self.timecode_label.setToolTip("播放頭／片長（時:分:秒.百分之一秒）")
        row.addWidget(self.timecode_label)
        row.addStretch(1)
        self.prev_frame_tool = self._tool("step_back", "上一格（←）", lambda: self.step_frame(-1))
        self.prev_frame_tool.setProperty("role", "ghost")
        row.addWidget(self.prev_frame_tool)
        self.play_tool = QToolButton()
        self.play_tool.setProperty("role", "play")
        self.play_tool.setFixedSize(36, 36)
        self.play_tool.setToolTip("播放／暫停")
        self.play_tool.clicked.connect(lambda _c=False: p.toggle_play())
        self._play_mirror = _EnabledMirror(p.play_btn, self.play_tool)
        p.play_btn.setParent(self.legacy_central)
        row.addWidget(self.play_tool)
        self.next_frame_tool = self._tool("step_forward", "下一格（→）", lambda: self.step_frame(1))
        self.next_frame_tool.setProperty("role", "ghost")
        row.addWidget(self.next_frame_tool)
        row.addStretch(1)
        self.media_fps = playhead.DEFAULT_FPS
        self._fps_probe = _FpsProbe(self)
        self._fps_probe.done.connect(self._on_fps)
        p.player.positionChanged.connect(lambda _ms: self._update_timecode())
        p.player.durationChanged.connect(lambda _ms: self._update_timecode())
        p.timeline.durationChanged.connect(lambda _d: self._probe_fps())
        self._update_timecode()
        # 右邊：預覽放大、專注預覽（E-6b）；跟左邊的時間一樣寬，播放鍵才會在正中間
        right = QWidget()
        tools = QHBoxLayout(right)
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(4)
        tools.addStretch(1)
        self.preview_zoom_combo = QComboBox()
        for label, factor in PREVIEW_ZOOMS:
            self.preview_zoom_combo.addItem(label, factor)
        self.preview_zoom_combo.setToolTip("預覽放大（看字幕邊緣、畫面細節；放大時用滑鼠拖著看別的地方）")
        self.preview_zoom_combo.currentIndexChanged.connect(
            lambda i: self.set_preview_zoom(self.preview_zoom_combo.itemData(i)))
        tools.addWidget(self.preview_zoom_combo)
        view = self.player_panel.view  # 放大時收起／放回面板，預覽變寬變窄，還是看正中間
        view.resized.connect(lambda: view.centerOn(view.sceneRect().center())
                             if self.preview_zoom_combo.currentIndex() > 0 else None)
        self.focus_tool = self._tool("fit", "專注預覽：收起左側面板與屬性面板（再按一次放回來）",
                                     lambda: self.set_focus_preview(self.focus_tool.isChecked()), checkable=True)
        self.focus_tool.setProperty("role", "ghost")
        tools.addWidget(self.focus_tool)
        right.setFixedWidth(max(self.timecode_label.sizeHint().width(), right.sizeHint().width()))
        self.timecode_label.setMinimumWidth(right.width())
        row.addWidget(right)
        col.addLayout(row)
        return panel

    def _inspector_page(self, key, title):
        """屬性面板的一頁（可以捲）：回傳那一頁的直排。"""
        content = QWidget()
        col = QVBoxLayout(content)
        col.setContentsMargins(12, 12, 12, 12)
        col.setSpacing(6)
        head = _title(title)
        col.addWidget(head)
        self.inspector_pages[key] = _scroll(content)
        self.inspector_stack.addWidget(self.inspector_pages[key])
        return col, head

    def _build_inspector(self):
        """
        屬性面板跟著選取換頁（E-3a）：沒選＝專案（主片段、剪點、疊加與音樂的摘要），選字幕＝那一句的時間與文字，
        選素材＝那一段的屬性。時間軸上字幕與素材都選著時，看最後點的那個（`TimelineView.last_pick`）。
        """
        p = self.player_panel
        panel = QFrame()
        panel.setObjectName("inspector")
        panel.setMinimumWidth(240)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        self.inspector_stack = QStackedWidget()
        outer.addWidget(self.inspector_stack)
        self.inspector_pages = {}

        # 專案（沒選東西）
        col, _head = self._inspector_page("project", "專案")
        col.addWidget(_secondary(p.info_label))
        col.addWidget(_title("主片段", "sectionTitle"))
        col.addWidget(self._iconify(p.picture_btn, "picture", role="list"))
        col.addWidget(p.proxy_box)
        col.addWidget(_title("剪點", "sectionTitle"))
        col.addWidget(p.cut_combo)
        p.cut_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        col.addWidget(_secondary(p.cut_label))
        col.addWidget(p.preview_cut_box)
        seam = QHBoxLayout()
        seam.addWidget(p.seam_combo, 1)
        seam.addWidget(p.seam_spin)
        col.addLayout(seam)
        col.addWidget(p.cut_reset_btn)
        col.addWidget(_title("疊加與音樂", "sectionTitle"))
        p.track_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        col.addWidget(_secondary(p.track_label))
        col.addWidget(p.preview_box)
        col.addStretch(1)
        col.addWidget(_secondary(QLabel(INSPECTOR_HINT)))

        # 字幕（選了一句，或「新增一句」打字中）
        col, self.cue_page_title = self._inspector_page("cue", "字幕")
        self.cue_pos_label = _secondary(QLabel(""))
        col.addWidget(self.cue_pos_label)
        col.addWidget(_title("時間", "sectionTitle"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self.cue_start_spin = self._time_spin("這句從幾秒開始（不會蓋到前一句；可以復原）")
        self.cue_end_spin = self._time_spin("這句到幾秒結束（不會蓋到下一句、不超過片長；可以復原）")
        self.cue_length_label = QLabel("")
        for row, (name, widget) in enumerate((("開始", self.cue_start_spin), ("結束", self.cue_end_spin),
                                               ("長度", self.cue_length_label))):
            grid.addWidget(_secondary(QLabel(name)), row, 0)
            grid.addWidget(widget, row, 1)
        grid.setColumnStretch(1, 1)
        col.addLayout(grid)
        self.cue_start_spin.valueChanged.connect(lambda v: self._set_cue_time(start=v))
        self.cue_end_spin.valueChanged.connect(lambda v: self._set_cue_time(end=v))
        col.addWidget(_title("文字", "sectionTitle"))
        col.addWidget(self.cue_panel.editor)  # 逐句校對的編輯框搬過來（同一個，套用、Esc、新增都照舊）
        self.cue_panel.hint = CUE_EDIT_HINT
        self.cue_panel._load_editor(self.cue_panel.selected_index())
        col.addWidget(_title("全部字幕", "sectionTitle"))
        self.cue_style_btn = QPushButton("字幕樣式…")
        self.cue_style_btn.setToolTip(self.cue_panel.style_btn.toolTip() or "字型、大小、顏色、位置（套用到全部字幕）")
        self.cue_style_btn.clicked.connect(lambda _c=False: self.cue_panel.style_btn.click())
        _EnabledMirror(self.cue_panel.style_btn, self.cue_style_btn)
        col.addWidget(self.cue_style_btn)
        col.addStretch(1)

        # 素材（疊加或音樂）
        col, self.track_page_title = self._inspector_page("track", "素材")
        p.prop_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        col.addWidget(_secondary(p.prop_label))
        for widgets in p._prop_widgets.values():
            for w in widgets:
                col.addWidget(w)
        col.addStretch(1)

        p.timeline.cueSelected.connect(lambda _i: self.sync_inspector())
        p.timeline.trackItemSelected.connect(lambda _k, _i: self.sync_inspector())
        # 字幕改了（拖邊、復原、分割…）逐句校對會重載編輯框，editorChanged 就涵蓋了
        self.cue_panel.editorChanged.connect(self.sync_inspector)
        self.sync_inspector()
        return panel

    def _time_spin(self, tip):
        spin = QDoubleSpinBox()
        spin.setDecimals(3)
        spin.setRange(0.0, 24 * 3600.0)
        spin.setSingleStep(0.1)
        spin.setSuffix(" 秒")
        spin.setKeyboardTracking(False)  # 打字打到一半不改；按 Enter、離開或按上下才改
        spin.setToolTip(tip)
        return spin

    def inspector_mode(self):
        """屬性面板該顯示哪一頁："project"／"cue"／"track"。"""
        p = self.player_panel
        tl = p.timeline
        if self.cue_panel._adding is not None:
            return "cue"
        cue = 0 <= tl.selected < len(p.cues)
        sel = tl.track_selected
        track = bool(sel) and 0 <= sel[1] < len(p.tracks.get(sel[0], ()))
        if cue and track:
            return "cue" if tl.last_pick == "cue" else "track"
        return "cue" if cue else "track" if track else "project"

    def sync_inspector(self):
        """照選取換頁、填這一頁的值（填的時候不送出修改）。"""
        p = self.player_panel
        mode = self.inspector_mode()
        self.inspector_stack.setCurrentWidget(self.inspector_pages[mode])
        if mode == "track":
            kind = p.timeline.track_selected[0]
            self.track_page_title.setText(TRACK_TITLES.get(kind, "素材"))
        if mode != "cue":
            return
        adding = self.cue_panel._adding
        index = p.timeline.selected
        if adding is not None:
            self.cue_page_title.setText("新增一句")
            self.cue_pos_label.setText("打好字按 Ctrl+Enter 或離開編輯框就加進去，Esc 取消；"
                                       "加進去之後才能改時間。")
            start = end = float(adding)
        else:
            cue = p.cues[index]
            start, end = float(cue["start"]), float(cue["end"])
            self.cue_page_title.setText("字幕")
            self.cue_pos_label.setText(f"第 {index + 1} 句，共 {len(p.cues)} 句")
        for spin, value in ((self.cue_start_spin, start), (self.cue_end_spin, end)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.setEnabled(adding is None)
            spin.blockSignals(False)
        self.cue_length_label.setText("" if adding is not None else f"{end - start:.3f} 秒")

    def _set_cue_time(self, start=None, end=None):
        """屬性面板改了開始或結束：照拖邊的規則夾好、記進復原，夾過的值填回去。"""
        p = self.player_panel
        index = p.timeline.selected
        if self.cue_panel._adding is not None or not 0 <= index < len(p.cues):
            return
        before = (float(p.cues[index]["start"]), float(p.cues[index]["end"]))
        after = p.set_cue_times(index, start=start, end=end)
        wanted = start if start is not None else end
        got = after[0] if start is not None else after[1]
        if after == before:
            self.statusBar().showMessage("時間沒有變：會蓋到鄰句、超過片長，或短於 0.1 秒。")
        elif abs(got - wanted) > 0.0005:
            self.statusBar().showMessage(f"已改到 {got:.3f} 秒（不能蓋到鄰句、超過片長，或短於 0.1 秒）。")
        else:
            self.statusBar().showMessage(f"第 {index + 1} 句：{after[0]:.3f} → {after[1]:.3f} 秒（可以復原）。")
        self.sync_inspector()

    def _build_timeline(self):
        p = self.player_panel
        panel = QFrame()
        panel.setObjectName("timelinePanel")
        col = QVBoxLayout(panel)
        col.setContentsMargins(8, 4, 8, 8)
        col.setSpacing(4)
        bar = QHBoxLayout()
        bar.setSpacing(2)
        for btn, icon_name, text in ((p.undo_btn, "undo", ""), (p.redo_btn, "redo", ""),
                                     (p.save_btn, "save", None)):
            bar.addWidget(self._iconify(btn, icon_name, text, role="ghost"))
        bar.addWidget(self._separator())
        # E-2b：分割、刪除（字幕或素材）、吸附、縮放滑桿（照剪映的工具列）
        self.split_tool = self._tool("split", "在播放頭把字幕切成兩句（Ctrl+B）", self.split_at_playhead, text="分割")
        self.delete_tool = self._tool("delete", "刪除時間軸上選取的字幕或素材（Delete）", self.delete_selection,
                                      text="刪除")
        p.remove_track_btn.setParent(self.legacy_central)  # 換成 delete_tool（同一個動作再加上刪字幕）
        p.remove_track_btn.hide()
        for tool in (self.split_tool, self.delete_tool):
            bar.addWidget(tool)
        bar.addStretch(1)
        self.snap_tool = self._tool("magnet", "拖曳時貼到播放頭與鄰句的邊（關掉就自由拖）", lambda: None,
                                    checkable=True, text="吸附")
        self.snap_tool.setChecked(p.timeline.snap_enabled)
        self.snap_tool.toggled.connect(p.timeline.set_snap)
        for tool in (self.split_tool, self.delete_tool, self.snap_tool):
            tool.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        bar.addWidget(self.snap_tool)
        bar.addWidget(self._separator())
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(0, timeline_mod.ZOOM_SLIDER_STEPS)
        self.zoom_slider.setFixedWidth(120)
        self.zoom_slider.setToolTip("縮放時間軸（Ctrl＋滾輪也可以）")
        self.zoom_slider.setValue(timeline_mod.zoom_to_slider(p.timeline.px_per_sec))
        self.zoom_slider.valueChanged.connect(self._zoom_from_slider)
        p.timeline.zoomChanged.connect(self._sync_zoom_slider)
        for btn, icon_name in ((p.zoom_out_btn, "zoom_out"), (self.zoom_slider, None), (p.zoom_in_btn, "zoom_in"),
                               (p.fit_btn, "fit")):
            bar.addWidget(btn if icon_name is None else self._iconify(btn, icon_name, "", role="ghost"))
        col.addLayout(bar)
        for signal in (p.timeline.cueSelected, p.timeline.trackItemSelected, p.cuesChanged, p.timeline.durationChanged):
            signal.connect(self._update_timeline_tools)
        self._update_timeline_tools()
        # E-2：軌道加高、列上不寫說明（改寫在軌道標頭的提示裡）、左邊一欄軌道標頭
        p.timeline.set_row_heights(timeline_mod.TALL_HEIGHTS, inline_notes=False)
        self.track_header = timeline_mod.TrackHeader(p.timeline)
        tracks = QWidget()
        row = QHBoxLayout(tracks)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.track_header, 0, Qt.AlignTop)
        row.addWidget(p.timeline, 1, Qt.AlignTop)
        # 還沒開影片：一句話＋〔開啟影片〕（同一顆按鈕的動作），不攤一排空的列
        self.timeline_empty = QWidget()
        self.timeline_empty.setObjectName("timelineEmpty")
        empty = QVBoxLayout(self.timeline_empty)
        empty.addStretch(1)
        self.timeline_empty_label = _secondary(QLabel(TIMELINE_EMPTY_TEXT))
        self.timeline_empty_label.setAlignment(Qt.AlignCenter)
        empty.addWidget(self.timeline_empty_label)
        self.timeline_open_btn = QPushButton("開啟影片…")
        self.timeline_open_btn.setToolTip(p.open_btn.toolTip() or "開啟要上字幕或剪輯的影片")
        self.timeline_open_btn.clicked.connect(p.open_btn.click)
        self._iconify(self.timeline_open_btn, "open")
        empty.addWidget(self.timeline_open_btn, 0, Qt.AlignHCenter)
        empty.addStretch(1)
        self.timeline_stack = QStackedWidget()
        self.timeline_stack.addWidget(self.timeline_empty)
        self.timeline_stack.addWidget(tracks)
        self.timeline_stack.setFixedHeight(p.timeline.height())
        p.timeline.durationChanged.connect(self._sync_timeline_empty)
        p.timeline.rowsChanged.connect(lambda: self.timeline_stack.setFixedHeight(p.timeline.height()))
        self._sync_timeline_empty()
        col.addWidget(self.timeline_stack)
        return panel

    def _zoom_from_slider(self, value):
        self.player_panel.timeline.set_zoom(timeline_mod.slider_to_zoom(value))

    def _sync_zoom_slider(self, px_per_sec):
        """時間軸的縮放（按鈕、Ctrl＋滾輪、整支）變了，滑桿跟著移（不再回頭觸發縮放）。"""
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(timeline_mod.zoom_to_slider(px_per_sec))
        self.zoom_slider.blockSignals(False)

    def _update_timeline_tools(self, *_args):
        """分割：有字幕或選了素材就能按（切不了會講原因）；刪除：時間軸上選了字幕或素材才能按。"""
        p = self.player_panel
        t = p.timeline
        self.split_tool.setEnabled((bool(p.cues) or t.track_selected is not None) and t.duration > 0)
        self.delete_tool.setEnabled(t.track_selected is not None or 0 <= t.selected < len(p.cues))

    def split_at_playhead(self):
        """
        〔分割〕、Ctrl+B：最後點的是素材就切那段素材（E-3b），不然切字幕。切不了就在狀態列講原因。
        回傳切的是第幾句（或第幾段素材；切不了是 -1）。
        """
        p = self.player_panel
        sel = p.timeline.track_selected
        if sel and p.timeline.last_pick == "track" and 0 <= sel[1] < len(p.tracks.get(sel[0], ())):
            try:
                kind, index = p.split_track_at_playhead()
            except ValueError as exc:
                self.statusBar().showMessage(f"不能分割：{exc}", 5000)
                return -1
            self.statusBar().showMessage(f"已把{TRACK_TITLES.get(kind, '素材')}第 {index + 1} 段切成兩段"
                                         "（Ctrl+Z 可以復原）", 5000)
            return index
        try:
            index = self.player_panel.split_at_playhead()
        except ValueError as exc:
            self.statusBar().showMessage(f"不能分割：{exc}", 5000)
            return -1
        self.statusBar().showMessage(f"已把第 {index + 1} 句切成兩句（Ctrl+Z 可以復原）", 5000)
        return index

    def delete_selection(self):
        """〔刪除〕、Delete：刪時間軸上最後選的字幕或素材。"""
        what = self.player_panel.delete_selection()
        if what == "cue":
            self.statusBar().showMessage("已刪除選取的字幕（Ctrl+Z 可以復原）", 5000)
        elif what == "track":
            self.statusBar().showMessage("已刪除選取的素材", 5000)
        self._update_timeline_tools()
        return what

    def _sync_timeline_empty(self, *_args):
        """時間軸沒有片子時顯示空狀態，有片長就換回軌道。回傳現在是不是空狀態。"""
        empty = self.player_panel.timeline.duration <= 0
        self.timeline_stack.setCurrentIndex(0 if empty else 1)
        return empty

    def _separator(self):
        holder = QWidget()
        holder.setFixedWidth(13)
        row = QHBoxLayout(holder)
        row.setContentsMargins(6, 6, 6, 6)
        line = QWidget()
        line.setObjectName("vsep")
        line.setAttribute(Qt.WA_StyledBackground, True)
        line.setFixedWidth(1)
        row.addWidget(line)
        return holder

    def _build_export_dialog(self):
        """
        〔匯出〕（E-5）：原本分在三個地方的出口合成一個視窗，照常用的順序排四段，左邊目錄點了捲過去：
        一鍵完成輸出（字幕檔＋燒錄，依輸出設定）、剪好的影片（照剪點、多軌）、單獨匯出字幕檔與多語字幕包、品牌套版。
        進度與結果釘在最下面，捲到哪一段都看得到。
        """
        p = self.player_panel
        out = self.output_panel
        dialog = QDialog(self)
        dialog.setWindowTitle("匯出")
        dialog.resize(EXPORT_SIZE[0], EXPORT_SIZE[1])
        row = QHBoxLayout(dialog)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self.export_nav = QListWidget()
        self.export_nav.setObjectName("exportNav")
        self.export_nav.setFixedWidth(168)
        self.export_nav.setFrameShape(QFrame.NoFrame)
        row.addWidget(self.export_nav)

        right = QWidget()
        col = QVBoxLayout(right)
        col.setContentsMargins(16, 16, 16, 12)
        col.setSpacing(8)
        col.addWidget(_title("匯出"))
        out.target_label.setProperty("secondary", True)
        col.addWidget(out.target_label)
        body = QWidget()
        sections = QVBoxLayout(body)
        sections.setContentsMargins(0, 0, 8, 0)
        sections.setSpacing(16)
        self.export_sections = {}

        def section(key, title, note, *widgets):
            frame = QFrame()
            frame.setObjectName("exportSection")
            lay = QVBoxLayout(frame)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(6)
            lay.addWidget(_title(title, "sectionTitle"))
            if note:
                lay.addWidget(_secondary(QLabel(note)))
            for w in widgets:
                if isinstance(w, QHBoxLayout):
                    lay.addLayout(w)
                else:
                    lay.addWidget(w)
            sections.addWidget(frame)
            self.export_sections[key] = frame
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, key)
            self.export_nav.addItem(item)

        out.page_note.hide()  # 寫的是四頁籤的位置（②④）；各段自己有說明
        section("finish", "一鍵完成輸出", EXPORT_NOTES["finish"], out)
        out.show()  # 原本在④頁籤裡（收起來的那一份外殼）
        out.output_box.setTitle("")  # 段落標題已經寫了
        videos = QHBoxLayout()
        for btn, icon_name in ((p.export_btn, "cut"), (p.assemble_btn, "batch")):
            videos.addWidget(self._iconify(btn, icon_name))
        videos.addStretch(1)
        section("video", "剪好的影片", EXPORT_NOTES["video"], videos)
        out.single_heading.hide()  # 這一段的標題、說明就是它
        out.single_note.hide()
        self.export_pack_btn = QPushButton("多語字幕包…")
        self.export_pack_btn.setToolTip("一次翻成好幾個語言、每個語言存一份上傳用的字幕檔（開翻譯視窗，同〔翻譯字幕…〕）")
        self.export_pack_btn.clicked.connect(lambda _c=False: self.cue_panel.translate_btn.click())
        _EnabledMirror(self.cue_panel.translate_btn, self.export_pack_btn)
        pack = QHBoxLayout()
        pack.addWidget(self._iconify(self.export_pack_btn, "translate"))
        pack.addStretch(1)
        section("subtitles", "字幕檔", EXPORT_NOTES["subtitles"], out.single_section, pack)
        out.branding.setTitle("")  # 段落標題已經寫了
        section("branding", "品牌套版", EXPORT_NOTES["branding"], out.branding)
        sections.addStretch(1)
        self.export_scroll = _scroll(body)
        col.addWidget(self.export_scroll, 1)
        out.status_area.setMaximumHeight(128)
        col.addWidget(out.status_area)
        row.addWidget(right, 1)
        self.export_nav.currentRowChanged.connect(
            lambda r: self.show_export_section(self.export_nav.item(r).data(Qt.UserRole)) if r >= 0 else None)
        self.export_nav.setCurrentRow(0)
        return dialog

    def show_export_section(self, key):
        """匯出視窗捲到某一段（finish／video／subtitles／branding），目錄跟著選。"""
        frame = self.export_sections[key]
        bar = self.export_scroll.verticalScrollBar()
        bar.setValue(min(frame.y(), bar.maximum()))
        for i in range(self.export_nav.count()):
            if self.export_nav.item(i).data(Qt.UserRole) == key and self.export_nav.currentRow() != i:
                self.export_nav.blockSignals(True)
                self.export_nav.setCurrentRow(i)
                self.export_nav.blockSignals(False)
        return key

    # ----- 動作 -----
    def show_section(self, key):
        """左邊圖示列切到某一區（media／subtitles／smart／health）。"""
        self.rail_buttons[key].setChecked(True)
        self.left_stack.setCurrentWidget(self.left_pages[key])
        sizes = self.hsplit.sizes()
        total = sum(sizes)
        if total > 0:
            # 預覽至少留 360（影片看得到），屬性面板不動
            want = min(SECTION_WIDTH[key], total - sizes[2] - 360)
            if want > 0:
                self.hsplit.setSizes([want, total - want - sizes[2], sizes[2]])
        return key

    def current_section(self):
        page = self.left_stack.currentWidget()
        return next(k for k, w in self.left_pages.items() if w is page)

    def open_export(self, section=None):
        """打開匯出視窗（不擋主視窗）；字幕編輯框改到一半的先套用。section：直接捲到哪一段。"""
        self.cue_panel.commit()
        self.export_dialog.show()
        self.export_dialog.raise_()
        self.export_dialog.activateWindow()
        if section:
            QApplication.processEvents()  # 版面排好才知道每一段在哪
            self.show_export_section(section)
        return self.export_dialog

    def _find(self):
        self.show_section("subtitles")
        self.cue_panel.show_find()

    def _install_shortcuts(self):
        """播放器、逐句校對自己那份（焦點在面板裡才有效）停掉，改成整個視窗都有效的同一組。"""
        from gui_qt.player import edit_shortcuts

        for owner in (self.player_panel, self.cue_panel):
            for sc in owner.findChildren(QShortcut, options=Qt.FindDirectChildrenOnly):
                sc.setEnabled(False)
        p = self.player_panel
        bindings = list(edit_shortcuts(p.undo, p.redo, self.cue_panel.save))
        bindings.append((QKeySequence(QKeySequence.Find), self._find))
        # E-2b：剪映的分割、刪除（Delete 在打字的地方是那個欄位自己的，不會被這裡搶走）
        bindings.append((QKeySequence(SPLIT_KEY), self.split_at_playhead))
        bindings.append((QKeySequence(QKeySequence.Delete), self.delete_selection))
        # E-6a：播放、J／K／L、逐格、縮放、匯出、存專案（打字的地方會自己留下這些字，不會被搶走）
        actions = {"play": p.toggle_play, "rewind": lambda: self.jkl("J"), "pause": lambda: self.jkl("K"),
                   "forward": lambda: self.jkl("L"), "prev_frame": lambda: self.step_frame(-1),
                   "next_frame": lambda: self.step_frame(1), "zoom_in": p.timeline.zoom_in,
                   "zoom_out": p.timeline.zoom_out, "fit": p.timeline.zoom_to_fit, "export": self.open_export,
                   "save_project": p.save_project_btn.click}
        self.key_shortcuts = {}
        for name, keys in KEYS.items():
            for key in keys:
                bindings.append((QKeySequence(key), actions[name]))
                self.key_shortcuts.setdefault(name, []).append(len(bindings) - 1)
        self.shortcuts = []
        for seq, slot in bindings:
            sc = QShortcut(seq, self)
            sc.setContext(Qt.WindowShortcut)
            sc.setAutoRepeat(True)
            sc.activated.connect(slot)
            self.shortcuts.append(sc)
        self.key_shortcuts = {name: [self.shortcuts[i] for i in idx] for name, idx in self.key_shortcuts.items()}
        QApplication.instance().focusChanged.connect(lambda _old, _new: self._update_arrow_keys())
        p.timeline.cueSelected.connect(lambda _i: self._update_arrow_keys())
        self._update_arrow_keys()
        for btn, name, text in ((p.zoom_in_btn, "zoom_in", "拉近"), (p.zoom_out_btn, "zoom_out", "拉遠"),
                                (p.fit_btn, "fit", "整支"), (self.export_button, "export", "匯出"),
                                (p.save_project_btn, "save_project", "存專案")):
            tip = btn.toolTip() or text
            btn.setToolTip(f"{tip}（{KEYS[name][0]}）")

    def _update_arrow_keys(self):
        """←／→ 逐格只在焦點不在「自己要用方向鍵」的元件上時有效；時間軸選了字幕時留給它微調那句。"""
        w = QApplication.focusWidget()
        tl = self.player_panel.timeline
        ok = not isinstance(w, ARROW_OWNERS)
        if ok and w is not None and (w is tl or tl.isAncestorOf(w)) and tl.selected >= 0:
            ok = False
        for name in ("prev_frame", "next_frame"):
            for sc in self.key_shortcuts[name]:
                sc.setEnabled(ok)
        return ok

    # ----- 選單列、面板收合、預覽放大（E-6b） -----
    def _build_menus(self):
        """選單列：每一項都是現有的按鈕或動作（按了＝按那顆；打開選單時照那顆能不能按）。"""
        bar = self.menuBar()
        self.menu_actions = {}
        self._menu_sources = []
        for title, entries in MENUS:
            menu = bar.addMenu(title)
            for entry in entries:
                if entry is None:
                    menu.addSeparator()
                    continue
                text, target, key = entry
                action = menu.addAction(f"{text}\t{key}" if key else text)
                if target.startswith("@"):
                    name, _, arg = target[1:].partition(":")
                    slot = getattr(self, name)
                    action.triggered.connect(lambda _c=False, f=slot, a=arg: f(a) if a else f())
                else:
                    widget = resolve(self, target)
                    action.triggered.connect(lambda _c=False, w=widget: w.click())
                    self._menu_sources.append((action, widget))
                self.menu_actions[f"{title}/{text}"] = action
            menu.aboutToShow.connect(self._sync_menus)
            if title == "檢視":
                menu.addSeparator()
                self.left_panel_action = menu.addAction("顯示左側面板")
                self.inspector_action = menu.addAction("顯示屬性面板")
                for action, key in ((self.left_panel_action, "left"), (self.inspector_action, "inspector")):
                    action.setCheckable(True)
                    action.setChecked(True)
                    action.toggled.connect(lambda on, k=key: self.set_panel_visible(k, on))
                zoom = menu.addMenu("預覽放大")
                self.preview_zoom_actions = []
                for i, (label, _factor) in enumerate(PREVIEW_ZOOMS):
                    act = zoom.addAction(label)
                    act.setCheckable(True)
                    act.triggered.connect(lambda _c=False, n=i: self.preview_zoom_combo.setCurrentIndex(n))
                    self.preview_zoom_actions.append(act)
                self._sync_zoom_actions()
        self._sync_menus()

    def _sync_menus(self):
        for action, widget in self._menu_sources:
            action.setEnabled(widget.isEnabled())

    def _sync_zoom_actions(self):
        for i, act in enumerate(getattr(self, "preview_zoom_actions", ())):
            act.setChecked(i == self.preview_zoom_combo.currentIndex())

    def set_panel_visible(self, which, shown):
        """收起或放回左側面板（"left"）／屬性面板（"inspector"）；空出來的寬度給預覽。回傳之後是否顯示。"""
        panel = self.left_panel if which == "left" else self.inspector_panel
        panel.setVisible(bool(shown))
        action = self.left_panel_action if which == "left" else self.inspector_action
        if action.isChecked() != bool(shown):
            action.blockSignals(True)
            action.setChecked(bool(shown))
            action.blockSignals(False)
        both_hidden = not self.left_panel.isVisible() and not self.inspector_panel.isVisible()
        if self.focus_tool.isChecked() != both_hidden:
            self.focus_tool.setChecked(both_hidden)
        return bool(shown)

    def set_focus_preview(self, on):
        """專注預覽：左側面板與屬性面板一起收起來（或一起放回來）。"""
        self.set_panel_visible("left", not on)
        self.set_panel_visible("inspector", not on)
        self.statusBar().showMessage("專注預覽：再按一次放回左側面板與屬性面板" if on else "", 3000)
        return bool(on)

    def set_preview_zoom(self, factor):
        """預覽放大（1＝符合視窗）。放大時可以用滑鼠拖著看；字幕與疊加的預覽跟著一起放大（同一個畫面）。"""
        view = self.player_panel.view
        factor = float(factor or 1.0)
        view.resetTransform()
        if factor != 1.0:
            view.scale(factor, factor)
        view.setDragMode(view.DragMode.ScrollHandDrag if factor > 1.0 else view.DragMode.NoDrag)
        view.centerOn(view.sceneRect().center())  # 從畫面正中間開始看，不是從左上角
        index = next((i for i, (_l, f) in enumerate(PREVIEW_ZOOMS) if f == factor), 0)
        if self.preview_zoom_combo.currentIndex() != index:
            self.preview_zoom_combo.setCurrentIndex(index)
        self._sync_zoom_actions()
        return factor

    # ----- 播放頭（E-6a） -----
    def _update_timecode(self):
        pl = self.player_panel.player
        text = f"{playhead.format_timecode(pl.position())} / {playhead.format_timecode(pl.duration())}"
        if self.timecode_label.text() != text:
            self.timecode_label.setText(text)
        return text

    def _probe_fps(self):
        path = self.player_panel.media_path
        self.media_fps = playhead.DEFAULT_FPS
        if path:
            self._fps_probe.start(path)

    def _on_fps(self, path, fps):
        if path == self.player_panel.media_path:
            self.media_fps = playhead.clean_fps(fps)

    def step_frame(self, frames):
        """上一格（-1）／下一格（+1）：先暫停，再照影格率走；回傳新的位置（毫秒），沒開影片是 None。"""
        pl = self.player_panel.player
        if pl.duration() <= 0:
            return None
        pl.pause()
        ms = playhead.step_frames(pl.position(), frames, self.media_fps, pl.duration())
        pl.setPosition(ms)
        self.player_panel.timeline.set_position(ms)
        return ms

    def jkl(self, key):
        """J 倒退 1 秒、K 暫停（速度回 1 倍）、L 播放（在播再按一次快一級：1→2→4 倍）。回傳之後的速度或位置。"""
        pl = self.player_panel.player
        if pl.duration() <= 0:
            return None
        if key == "K":
            pl.pause()
            pl.setPlaybackRate(1.0)
            self.statusBar().showMessage("暫停", 1500)
            return 1.0
        if key == "L":
            playing = pl.playbackState() == QMediaPlayer.PlayingState
            rate = playhead.next_rate(pl.playbackRate(), playing)
            pl.setPlaybackRate(rate)
            if not playing:
                pl.play()
            self.statusBar().showMessage(f"播放 {rate:g} 倍速（K 暫停）", 1500)
            return rate
        ms = playhead.rewind(pl.position())
        pl.setPosition(ms)
        self.player_panel.timeline.set_position(ms)
        return ms

    def refresh_project_name(self):
        """頂列的專案名稱：沒開專案寫影片名稱；有變更還沒存加「•」。"""
        p = self.player_panel
        if p.project_path:
            text = os.path.basename(p.project_path) + ("  •" if p.project_changed() else "")
        elif p.media_path:
            text = os.path.basename(p.media_path) + "（還沒存成專案）"
        else:
            text = "未命名專案"
        if self.project_name_label.text() != text:
            self.project_name_label.setText(text)
        return text

    def _update_play_icon(self):
        p = self.player_panel
        playing = p.player.playbackState() == QMediaPlayer.PlayingState
        t = theme.tokens(self._theme)
        self.play_tool.setIcon(icons.icon("pause" if playing else "play", t["accent.text"], t["text.muted"], size=18))
        self.play_tool.setToolTip("暫停（Space、K）" if playing else "播放（Space、L）")

    def apply_editor_theme(self, name):
        """套用設計基準的調色盤與樣式表，圖示照主題重畫。"""
        self._theme = name if name in ("dark", "light") else "light"
        app = QApplication.instance()
        app.setPalette(theme.palette(self._theme))
        self.setStyleSheet(theme.stylesheet(self._theme))
        t = theme.tokens(self._theme)
        for btn, icon_name in self._icon_buttons:
            if btn is self.export_button:
                btn.setIcon(icons.icon(icon_name, t["accent.text"], size=16))
                continue
            if icon_name == "moon" and self._theme == "dark":
                icon_name = "sun"
            rail = btn.property("role") == "rail"
            btn.setIcon(icons.icon(icon_name, t["text.secondary"] if rail else t["text.primary"],
                                   t["text.muted"], t["accent"], size=22 if rail else 18))
            btn.setIconSize(QSize(22, 22) if rail else QSize(18, 18))
        self.logo_label.setPixmap(icons.pixmap("logo", t["accent"], 22, self.devicePixelRatioF()))
        self.theme_tool.setToolTip("切換為淺色" if self._theme == "dark" else "切換為深色")
        self._update_play_icon()
        p = self.player_panel
        p.timeline.update()
        self.track_header.update()
        self.media_bin._refresh()  # 沒有縮圖的素材用圖示：照新的顏色重畫
        return self._theme

    # ----- 剪輯器版面介紹（E-7b；四頁籤的導覽講的是①～④，這裡換成自己的一份、另外記看過沒） -----
    def open_guide(self):
        from gui_qt.guide_dialog import GuideDialog
        if self.guide_dialog is None:
            self.guide_dialog = GuideDialog(self, body=editorguide.body_text(), title=GUIDE_TITLE)
            self.guide_dialog.closedWith.connect(self._on_guide_closed)
        self.guide_dialog.show()
        self.guide_dialog.raise_()
        self.guide_dialog.activateWindow()
        return self.guide_dialog

    def _on_guide_closed(self, never):
        self.config_data[editorguide.CONFIG_KEY] = editorguide.remember(never)

    def maybe_show_guide(self):
        """啟動時呼叫：沒看過這一版的剪輯器版面介紹、也沒勾過「不再顯示」才跳。回傳有沒有跳。"""
        if not editorguide.should_show(self.config_data.get(editorguide.CONFIG_KEY)):
            return False
        self.open_guide()
        return True

    def toggle_theme(self):
        new = super().toggle_theme()
        self.apply_editor_theme(new)
        return new


def editor_requested(argv, stored=None):
    """開不開剪輯器版面：--editor／--tabs 優先，其次設定的 qt_layout，都沒有就是剪輯器（3.1 起的預設，E-7b）。"""
    return editorguide.choose_layout(argv, stored) == editorguide.EDITOR


def apply_initial_theme(app, theme_name):
    """`main()` 開剪輯器版面時的主題：先照舊套 Fusion，再換成設計基準的調色盤。"""
    apply_theme(app, theme_name)
    app.setPalette(theme.palette(theme_name))
