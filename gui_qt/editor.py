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

在 E-7 之前用 `python main.py --qt --editor` 打開；不加 `--editor` 照舊是四頁籤。
"""
import os

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QSplitter, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from gui_qt import icons, theme
from gui_qt.app import MainWindow, apply_theme
from updater import APP_VERSION

EDITOR_FLAG = "--editor"
EDITOR_TITLE = f"SRT 字幕生成器（v{APP_VERSION}）"
EDITOR_SIZE = (1440, 900)
EDITOR_MIN = (1100, 700)
LEFT_WIDTH = 400
# 左側面板各區想要的寬度：審片助手、健檢原本是整頁寬，切過去時把左側面板拉寬（從預覽借），切回來還原
SECTION_WIDTH = {"media": 340, "subtitles": 420, "smart": 660, "health": 660}
INSPECTOR_WIDTH = 300
RAIL_WIDTH = 64

# 左邊圖示列：(鍵, 圖示, 名稱, 提示)
RAIL = (
    ("media", "media", "媒體", "開啟影片與字幕、加入畫面與音樂、音訊轉影片、批次處理"),
    ("subtitles", "subtitles", "字幕", "生成字幕、逐句校對、尋找取代、翻譯、字幕樣式"),
    ("smart", "smart", "智慧剪輯", "審片助手：分析、段落清單、粗剪、精彩合輯、章節、封面候選、直式短片"),
    ("health", "health", "健檢", "上架前的 18 項檢查與一鍵修復、發佈文字、封面圖"),
)

# 現有功能在新版面的哪裡（PR 的對照表與測試都照這一份）：(功能, 元件的路徑, 區塊)
# 路徑從視窗算起，例如 "player_panel.open_btn"。區塊：top／left:<鍵>／preview／inspector／timeline／export。
FEATURE_MAP = (
    ("開專案", "player_panel.open_project_btn", "top"),
    ("存專案", "player_panel.save_project_btn", "top"),
    ("轉寫與金鑰", "transcription_tool", "top"),
    ("即時查譯", "lookup_tool", "top"),
    ("新介面導覽", "guide_tool", "top"),
    ("深淺色", "theme_tool", "top"),
    ("匯出", "export_button", "top"),
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
    ("時間", "player_panel.time_label", "preview"),
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
    ("復原", "player_panel.undo_btn", "timeline"),
    ("重做", "player_panel.redo_btn", "timeline"),
    ("存字幕", "player_panel.save_btn", "timeline"),
    ("刪除選取的素材", "player_panel.remove_track_btn", "timeline"),
    ("時間軸縮放（拉遠、拉近、整支）", "player_panel.fit_btn", "timeline"),
    ("時間軸（字幕、波形、縮圖、剪點、素材軌）", "player_panel.timeline", "timeline"),
    ("照剪點輸出", "player_panel.export_btn", "export"),
    ("輸出多軌", "player_panel.assemble_btn", "export"),
    ("完成輸出與逐格式匯出、品牌套版、多語字幕包", "output_panel", "export"),
)


# 四頁籤時代的按鈕，在新版面換成別的元件（同一個動作）：(舊的, 新的)
REPLACED = (
    ("player_panel.play_btn", "play_tool"),
    ("transcription_btn", "transcription_tool"),
    ("lookup_btn", "lookup_tool"),
    ("guide_btn", "guide_tool"),
    ("theme_btn", "theme_tool"),
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

    def __init__(self, config_data=None, persist=None):
        super().__init__(config_data, persist)
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

        self._install_shortcuts()
        p.player.playbackStateChanged.connect(lambda _s: self._update_play_icon())
        self._project_timer = QTimer(self)
        self._project_timer.setInterval(700)
        self._project_timer.timeout.connect(self.refresh_project_name)
        self._project_timer.start()
        self.show_section("media")
        self.apply_editor_theme(self.config_data.get("theme", "light"))
        self.refresh_project_name()
        self.statusBar().showMessage("剪輯器版面（試用）：左邊選媒體、字幕、智慧剪輯、健檢；右上角〔匯出〕。")

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
        self.guide_tool = self._tool("help", "新介面導覽：" + self.guide_btn.toolTip(), self.open_guide)
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
        m.addWidget(_title("匯入", "sectionTitle"))
        for btn, icon_name in ((p.open_btn, "film"), (p.subs_btn, "subtitles"),
                               (p.add_overlay_btn, "image"), (p.add_music_btn, "music")):
            m.addWidget(self._iconify(btn, icon_name, role="list"))
        m.addWidget(_secondary(QLabel("加入的畫面與音樂放在播放頭的位置，放上去之後在時間軸上拖動、"
                                      "在右邊的屬性裡調整。")))
        m.addWidget(_title("素材準備", "sectionTitle"))
        for btn, icon_name in ((self.audiovis_btn, "wave"), (self.batch_btn, "batch")):
            m.addWidget(self._iconify(btn, icon_name, role="list"))
        m.addStretch(1)
        self._add_page("media", _scroll(media))

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
        p.time_label.setObjectName("timecode")
        row.addWidget(p.time_label)
        row.addStretch(1)
        self.play_tool = QToolButton()
        self.play_tool.setProperty("role", "play")
        self.play_tool.setFixedSize(36, 36)
        self.play_tool.setToolTip("播放／暫停")
        self.play_tool.clicked.connect(lambda _c=False: p.toggle_play())
        self._play_mirror = _EnabledMirror(p.play_btn, self.play_tool)
        p.play_btn.setParent(self.legacy_central)
        row.addWidget(self.play_tool)
        row.addStretch(1)
        spacer = QWidget()  # 跟左邊的時間一樣寬，播放鍵才會在正中間
        spacer.setFixedWidth(p.time_label.sizeHint().width())
        row.addWidget(spacer)
        col.addLayout(row)
        return panel

    def _build_inspector(self):
        p = self.player_panel
        panel = QFrame()
        panel.setObjectName("inspector")
        panel.setMinimumWidth(240)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        col = QVBoxLayout(content)
        col.setContentsMargins(12, 12, 12, 12)
        col.setSpacing(6)
        col.addWidget(_title("屬性"))

        col.addWidget(_title("專案", "sectionTitle"))
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

        col.addWidget(_title("選取的素材", "sectionTitle"))
        p.prop_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        col.addWidget(_secondary(p.prop_label))
        for widgets in p._prop_widgets.values():
            for w in widgets:
                col.addWidget(w)
        p.track_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        col.addWidget(_secondary(p.track_label))
        col.addWidget(p.preview_box)
        col.addStretch(1)
        outer.addWidget(_scroll(content))
        return panel

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
        bar.addWidget(self._iconify(p.remove_track_btn, "delete", role="ghost"))
        bar.addStretch(1)
        for btn, icon_name in ((p.zoom_out_btn, "zoom_out"), (p.zoom_in_btn, "zoom_in"), (p.fit_btn, "fit")):
            bar.addWidget(self._iconify(btn, icon_name, "", role="ghost"))
        col.addLayout(bar)
        col.addWidget(p.timeline)
        return panel

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
        """〔匯出〕：照剪點輸出、輸出多軌，加上原本④的輸出設定與完成輸出（E-5 再合成一個流程）。"""
        p = self.player_panel
        dialog = QDialog(self)
        dialog.setWindowTitle("匯出")
        dialog.resize(860, 700)
        col = QVBoxLayout(dialog)
        col.setContentsMargins(16, 16, 16, 16)
        col.setSpacing(8)
        col.addWidget(_title("匯出成影片"))
        row = QHBoxLayout()
        for btn, icon_name in ((p.export_btn, "cut"), (p.assemble_btn, "batch")):
            row.addWidget(self._iconify(btn, icon_name))
        row.addStretch(1)
        col.addLayout(row)
        col.addWidget(_secondary(QLabel("照剪點輸出：照時間軸上啟用中的剪點剪成新影片。輸出多軌：連同疊加的畫面與音樂"
                                        "合成一支。原始影片都不動。")))
        col.addWidget(_title("字幕檔、燒錄與發佈"))
        col.addWidget(_scroll(self.output_panel), 1)
        return dialog

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

    def open_export(self):
        """打開匯出視窗（不擋主視窗）；字幕編輯框改到一半的先套用。"""
        self.cue_panel.commit()
        self.export_dialog.show()
        self.export_dialog.raise_()
        self.export_dialog.activateWindow()
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
        self.shortcuts = []
        for seq, slot in bindings:
            sc = QShortcut(seq, self)
            sc.setContext(Qt.WindowShortcut)
            sc.activated.connect(slot)
            self.shortcuts.append(sc)

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
        self.play_tool.setToolTip("暫停" if playing else "播放")

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
        return self._theme

    def toggle_theme(self):
        new = super().toggle_theme()
        self.apply_editor_theme(new)
        return new


def editor_requested(argv):
    return EDITOR_FLAG in argv


def apply_initial_theme(app, theme_name):
    """`main()` 開剪輯器版面時的主題：先照舊套 Fusion，再換成設計基準的調色盤。"""
    apply_theme(app, theme_name)
    app.setPalette(theme.palette(theme_name))
