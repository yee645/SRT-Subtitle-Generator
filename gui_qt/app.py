# -*- coding: utf-8 -*-
"""
3.0 預覽版主視窗（第 1 項第一階段：骨架）。

這一階段只立地基：主視窗、四個階段頁籤、狀態列、深淺主題。頁籤裡先放
「這一頁還在 Tk 版」的說明，之後每搬一頁就換掉一頁（見
`docs/ROADMAP_3.0.md` 第 1、11 項）。

**頁籤名稱與 Tk 版一字不差**：2.x 花了好幾版讓使用者記住「① 素材與剪輯
→ ② 字幕 → ③ 健檢中心 → ④ 輸出與發佈」，換工具包不是重新命名的理由。
測試會拿 `gui/app.py` 的原始碼比對。

設定（第 11 項第二十八階段起）：從 `main()` 開的視窗關掉時存回 config.json，而且**只寫這次開啟期間改過的
最上層區塊**（`subtitle/configmerge.py`）：一般版同時開著、在這段期間存的東西不會被這邊開啟當下的舊值蓋掉。
測試直接建 `MainWindow(設定)` 不存（`persist` 預設只有自己讀設定檔時才開）。
"""
import copy
import logging
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

import config
from subtitle.configmerge import changed_sections, merge_for_save
from subtitle import qtguide
from subtitle.onedirupdate import SENDS as _ONEDIR_SENDS
from updater import APP_VERSION

logger = logging.getLogger(__name__)

FFMPEG_BANNER = ("⚠ 找不到 ffmpeg：時間軸的波形與縮圖、燒錄、輸出影片、健檢的影音項目都需要它。"
                 "按右邊一鍵安裝（不需要管理員權限，兩版共用）。")

UPDATE_CHECK_DELAY_MS = 1500  # 跟一般版一樣：開好視窗 1.5 秒後才查新版本
# 狀態列的開場白：一般版的功能都搬過來了（第 11 項做完），指向導覽
STATUS_INTRO = ("3.0 預覽版：一般版的功能都搬過來了，四個頁籤照①→④的順序做。"
                "第一次用可以按右下角的〔新介面導覽…〕看東西在哪。")
CLOSE_WHILE_INSTALLING = "一鍵安裝還在下載。現在關掉程式，下載會中斷，下次要再安裝一次。還是要關嗎？"
CLOSE_WHILE_UPDATING = "新版還在下載或準備中。現在關掉程式，這次的下載會作廢，下次要再按一次「下載並安裝」。還是要關嗎？"

# (頁籤名稱, 還沒搬過來時頁面上的說明)。名稱必須與 gui/app.py 的
# notebook.add(..., text=...) 相同。
STAGES = [
    ("① 素材與剪輯", "選影片、剪停頓、剪重複片段、審片、匯入既有字幕。"),
    ("② 字幕", "生成字幕、逐句校對、翻譯、樣式。"),
    ("③ 健檢中心", "上架前的 18 項檢查與一鍵修復。"),
    ("④ 輸出與發佈", "匯出、燒錄、發佈資料、成品加工。"),
]

WINDOW_TITLE = f"SRT 字幕生成器 3.0 預覽版（v{APP_VERSION}）"

# 與 Tk 版的預設視窗同一個量級；之後放進時間軸時再依實測調整。
DEFAULT_SIZE = (1280, 800)

NOT_YET_TEXT = (
    "這一頁還沒搬到 3.0 預覽版。\n\n"
    "現在要用這些功能，請開一般版（直接執行程式、不加 --qt）：\n"
    "兩個版本讀同一份設定檔，做到一半可以換過去接著做。"
)


def theme_scheme(theme):
    """config 的 theme 字串 → Qt 的色彩配置。不認得的值一律當淺色（同 Tk 版）。"""
    return Qt.ColorScheme.Dark if theme == "dark" else Qt.ColorScheme.Light


def theme_button_text(theme):
    """切換按鈕上的字（同一般版）：現在是深色就寫「切換為淺色」，反之亦然。"""
    return "切換為淺色" if theme == "dark" else "切換為深色"


def dark_palette():
    """Fusion 樣式用的深色調色盤（顏色取自 Qt 官方範例的常見深色配置）。"""
    base, window, text = QColor(35, 35, 35), QColor(53, 53, 53), QColor(230, 230, 230)
    disabled = QColor(127, 127, 127)
    pal = QPalette()
    for role, color in (
        (QPalette.Window, window), (QPalette.WindowText, text),
        (QPalette.Base, base), (QPalette.AlternateBase, window),
        (QPalette.ToolTipBase, window), (QPalette.ToolTipText, text),
        (QPalette.Text, text), (QPalette.Button, window),
        (QPalette.ButtonText, text), (QPalette.BrightText, QColor(255, 80, 80)),
        (QPalette.Link, QColor(90, 160, 240)),
        (QPalette.Highlight, QColor(42, 130, 218)),
        (QPalette.HighlightedText, QColor(255, 255, 255)),
        (QPalette.PlaceholderText, disabled),
    ):
        pal.setColor(role, color)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, disabled)
    return pal


def apply_theme(app, theme):
    """
    套用深淺主題。

    Fusion 樣式＋**明確的調色盤**。只呼叫 `setColorScheme` 不夠：它要平台
    的主題外掛配合，offscreen 平台上實測完全不變（深色設定下底色亮度還是
    239），Windows 原生樣式在某些版本也不跟。自己給調色盤，三個平台結果
    一樣。
    """
    app.setStyle("Fusion")
    scheme = theme_scheme(theme)
    app.styleHints().setColorScheme(scheme)
    app.setPalette(dark_palette() if scheme == Qt.ColorScheme.Dark
                   else app.style().standardPalette())


def _placeholder_page(summary):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(24, 24, 24, 24)
    title = QLabel(summary)
    title.setWordWrap(True)
    body = QLabel(NOT_YET_TEXT)
    body.setWordWrap(True)
    layout.addWidget(title)
    layout.addWidget(body)
    layout.addStretch(1)
    return page


# ②字幕頁：播放器與逐句校對左右並排（3.0 第 11 項第一階段），中間可以拖
CUE_PANEL_WIDTH = 420


def _subtitle_page_note():
    return QLabel("這一頁有播放器（字幕疊在真的影片畫面上）、生成字幕與逐句校對（改文字、新增刪除、尋找取代、"
                  "翻譯與多語字幕包、字幕樣式）。一般版②字幕頁的功能都搬過來了。")


class MainWindow(QMainWindow):
    """3.0 預覽版主視窗。"""

    def __init__(self, config_data=None, persist=None):
        super().__init__()
        # 關掉時要不要存回 config.json：沒指定的話，自己讀設定檔的才存（測試給一份設定進來的不存）
        self.persist = (config_data is None) if persist is None else bool(persist)
        self.config_data = config_data if config_data is not None else config.load_config()
        # 開啟當下的樣子：存檔時拿來比，只寫這次改過的區塊
        self._opened_config = copy.deepcopy(self.config_data) if self.persist else None
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(*DEFAULT_SIZE)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.player_panel = None
        self.cue_panel = None
        self.health_panel = None
        self.output_panel = None
        self.review_panel = None
        self.audiovis_dialog = None
        self.batch_dialog = None
        self.lookup_dialog = None
        self.ffmpeg_dialog = None
        self.ocr_dialog = None
        self.transcription_dialog = None
        for name, summary in STAGES:
            if name == "② 字幕":
                self.tabs.addTab(self._subtitle_page(), name)
            elif name == "③ 健檢中心":
                self.tabs.addTab(self._health_page(), name)
            elif name == "④ 輸出與發佈":
                self.tabs.addTab(self._output_page(), name)
            else:
                self.tabs.addTab(_placeholder_page(summary), name)
        # ①審片助手要拿②的播放器與字幕：②建好之後再把①的說明頁換成它（頁籤順序與名稱不變）
        self.tabs.removeTab(0)
        self.tabs.insertTab(0, self._review_page(), STAGES[0][0])
        self.tabs.setCurrentIndex(0)
        # 即時查譯在每一頁都用得到：放在頁籤列右上角
        self.lookup_btn = QPushButton("即時查譯…")
        self.lookup_btn.setToolTip("選取文字就翻譯；會送出去的只有選取的那段文字（送到 OpenAI）")
        self.lookup_btn.clicked.connect(lambda _c=False: self.open_lookup())
        # 轉寫與金鑰設定（第三十二階段）：生成、翻譯、即時查譯、批次共用的那一份，也放右上角
        self.transcription_btn = QPushButton("轉寫與金鑰…")
        self.transcription_btn.setToolTip("Whisper 模型、語言、OpenAI API 金鑰、提示詞（跟一般版「轉寫設定」同一份）")
        self.transcription_btn.clicked.connect(lambda _c=False: self.open_transcription_settings())
        corner = QWidget()
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.addWidget(self.transcription_btn)
        corner_layout.addWidget(self.lookup_btn)
        self.tabs.setCornerWidget(corner, Qt.TopRightCorner)
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._build_ffmpeg_banner())
        central_layout.addWidget(self._build_update_banner())
        central_layout.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage(STATUS_INTRO)
        # 首次啟動導覽（第三十五階段）：一般版的「新版介面速覽」；第一次打開跳一次，這顆按鈕隨時再打開
        self.guide_dialog = None
        self.guide_btn = QPushButton("新介面導覽…")
        self.guide_btn.setToolTip("一般版的東西在 Qt 版的哪裡、這一版多了什麼、還有哪裡不一樣")
        self.guide_btn.clicked.connect(lambda _c=False: self.open_guide())
        self.statusBar().addPermanentWidget(self.guide_btn)
        # 深淺色切換（第三十四階段）：一般版主視窗的〔切換為深色〕；放狀態列右邊，每一頁都看得到
        self.theme_btn = QPushButton(theme_button_text(self.config_data.get("theme", "light")))
        self.theme_btn.setToolTip("整個視窗換成深色或淺色；記進設定，下次打開（一般版也是）就是這個")
        self.theme_btn.clicked.connect(lambda _c=False: self.toggle_theme())
        self.statusBar().addPermanentWidget(self.theme_btn)

    def _subtitle_page(self):
        """② 字幕：播放器面板（第 2 項）＋一行說明其餘功能在哪。"""
        from gui_qt.player import PlayerPanel

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        note = _subtitle_page_note()
        note.setWordWrap(True)
        note.setContentsMargins(12, 8, 12, 0)
        layout.addWidget(note)
        # 字幕樣式與 Tk 版同一份（config 的 subtitle_style），疊加層照燒錄的規則畫。
        # 剪點參數（停頓門檻、相似度…）也是同一份 config，畫出來的就是一般版會剪的。
        self.player_panel = PlayerPanel(style=self.config_data.get("subtitle_style"),
                                        config=self.config_data)
        from gui_qt.cue_panel import CueListPanel
        self.cue_panel = CueListPanel(self.player_panel)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.player_panel)
        self.splitter.addWidget(self.cue_panel)
        self.splitter.setCollapsible(0, False)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([DEFAULT_SIZE[0] - CUE_PANEL_WIDTH, CUE_PANEL_WIDTH])
        layout.addWidget(self.splitter, 1)
        return page

    def _review_page(self):
        """
        ① 素材與剪輯：上面一列「素材準備」（第二十一、二十二階段：音訊轉影片、批次一鍵完成），下面是審片助手（第 11 項第十六～二十階段：
        分析、段落清單、粗剪與匯出、章節與發佈包、封面候選、直式短片）。
        分析的是②開著的字幕；章節、發佈文字與封面候選帶進③健檢中心。
        """
        from gui_qt.review_panel import ReviewPanel

        self.review_panel = ReviewPanel(
            self.player_panel, before_analyze=self.cue_panel.commit,
            on_publish=lambda **fields: self.health_panel.adopt_publish(**fields) if self.health_panel else [],
            on_thumbnails=lambda paths: self.health_panel.add_thumbs(list(paths)) if self.health_panel else 0)
        # 「素材準備」一列（第 11 項第二十一階段起）：一般版①「素材準備」框的工具，開小視窗做
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        prep = QHBoxLayout()
        prep.setContentsMargins(12, 8, 12, 0)
        prep.addWidget(QLabel("素材準備："))
        self.audiovis_btn = QPushButton("音訊轉影片（波形／頻譜）…")
        self.audiovis_btn.setToolTip("只有音訊（Podcast、訪談錄音）：轉成附波形或頻譜的影片，轉好可以直接在②開啟")
        self.audiovis_btn.clicked.connect(lambda _c=False: self.open_audiovis())
        prep.addWidget(self.audiovis_btn)
        self.batch_btn = QPushButton("批次一鍵完成（多支）…")
        self.batch_btn.setToolTip("好幾支影片用同一份設定依序生成字幕、照④的輸出設定匯出／燒錄")
        self.batch_btn.clicked.connect(lambda _c=False: self.open_batch())
        prep.addWidget(self.batch_btn)
        prep.addStretch(1)
        layout.addLayout(prep)
        layout.addWidget(self.review_panel, 1)
        return page

    def open_batch(self):
        """開「批次一鍵完成」小視窗（只建一個；不擋住主視窗）。②開著的影片、清單又是空的就先加進去。"""
        from gui_qt.batch_dialog import BatchDialog

        if self.batch_dialog is None:
            self.batch_dialog = BatchDialog(self.player_panel, self)
        if not self.batch_dialog.running():
            media = self.player_panel.media_path
            if not self.batch_dialog.files() and media and os.path.exists(media):
                self.batch_dialog.add_files([media])
            self.batch_dialog.refresh()  # ④的輸出設定可能改過
        self.batch_dialog.show()
        self.batch_dialog.raise_()
        self.batch_dialog.activateWindow()
        return self.batch_dialog

    # ----- 一鍵安裝（第 11 項第二十九階段） -----
    def _build_ffmpeg_banner(self):
        """沒有 ffmpeg 時頁籤上方一條提示＋〔自動安裝 ffmpeg〕；裝好就收起來。各處「找不到 ffmpeg」都指向這裡。"""
        from subtitle.burner import ffmpeg_available

        self.ffmpeg_banner = QWidget()
        self.ffmpeg_banner.setObjectName("ffmpegBanner")
        self.ffmpeg_banner.setStyleSheet("#ffmpegBanner { background: #fdf3d7; } #ffmpegBanner QLabel { color: #8a5a00; }")
        row = QHBoxLayout(self.ffmpeg_banner)
        row.setContentsMargins(10, 4, 10, 4)
        label = QLabel(FFMPEG_BANNER)
        label.setWordWrap(True)
        row.addWidget(label, 1)
        self.ffmpeg_install_btn = QPushButton("自動安裝 ffmpeg")
        self.ffmpeg_install_btn.clicked.connect(lambda _c=False: self.open_ffmpeg_install())
        row.addWidget(self.ffmpeg_install_btn)
        self.ffmpeg_banner.setVisible(not ffmpeg_available())
        return self.ffmpeg_banner

    # ----- 有新版本的提示（第 11 項第三十階段） -----
    def _build_update_banner(self):
        """
        查到新版時頁籤上方一條提示：〔開啟下載頁〕〔這版不再提醒〕〔關閉提示〕。平常收著。

        第 12 項 12-3 起：打包好的 Windows 資料夾版、新版有附 zip 時多一顆〔下載並安裝〕（下載中變〔取消下載〕，
        準備好變〔現在重新開啟〕）；關掉程式時跑切換腳本換上新版。
        """
        from gui_qt.update_notice import InstallWorker, UpdateWorker
        from subtitle import updatecheck

        self.update_info = None
        self.update_banner = QWidget()
        self.update_banner.setObjectName("updateBanner")
        self.update_banner.setStyleSheet("#updateBanner { background: #e3effd; } #updateBanner QLabel { color: #1a4f8a; }")
        self.update_banner.setToolTip(updatecheck.SENDS)
        row = QHBoxLayout(self.update_banner)
        row.setContentsMargins(10, 4, 10, 4)
        self.update_label = QLabel()
        self.update_label.setWordWrap(True)
        row.addWidget(self.update_label, 1)
        self.update_open_btn = QPushButton("開啟下載頁")
        self.update_open_btn.clicked.connect(lambda _c=False: self.open_update_page())
        self.update_skip_btn = QPushButton("這版不再提醒")
        self.update_skip_btn.clicked.connect(lambda _c=False: self.skip_update())
        self.update_close_btn = QPushButton("關閉提示")
        self.update_close_btn.clicked.connect(lambda _c=False: self.update_banner.setVisible(False))
        self.update_install_btn = QPushButton("下載並安裝")
        self.update_install_btn.setToolTip(updatecheck.SENDS + "\n" + "下載新版：" + _ONEDIR_SENDS)
        self.update_install_btn.clicked.connect(lambda _c=False: self.install_update())
        self.update_cancel_btn = QPushButton("取消下載")
        self.update_cancel_btn.clicked.connect(lambda _c=False: self.cancel_update_install())
        self.update_restart_btn = QPushButton("現在重新開啟")
        self.update_restart_btn.clicked.connect(lambda _c=False: self.close())
        for btn in (self.update_install_btn, self.update_cancel_btn, self.update_restart_btn, self.update_open_btn,
                    self.update_skip_btn, self.update_close_btn):
            row.addWidget(btn)
        for btn in (self.update_install_btn, self.update_cancel_btn, self.update_restart_btn):
            btn.setVisible(False)
        self.update_banner.setVisible(False)
        self.update_worker = UpdateWorker(self)
        self.update_worker.finished.connect(self.show_update)
        self.install_worker = InstallWorker(self)
        self.install_worker.progress.connect(self._on_update_progress)
        self.install_worker.preparing.connect(self._on_update_preparing)
        self.install_worker.finished.connect(self._on_update_installed)
        self.pending_switch = None  # 準備好的切換腳本：關掉程式時執行
        return self.update_banner

    def start_update_check(self):
        """背景查一次 GitHub 最新版本（`main()` 開的視窗啟動後才查；測試、自檢不查）。"""
        self.update_worker.start(APP_VERSION)

    def show_update(self, info):
        """查到的結果：有比目前新、而且不是按過「這版不再提醒」的那一版，就出現提示。回傳有沒有出現。"""
        from subtitle import updatecheck

        skipped = str((self.config_data.get("qt_update") or {}).get("skipped_version") or "")
        if not updatecheck.should_notify(info, skipped):
            return False
        self.update_info = info
        auto = bool(info.get("qt_asset")) and self._self_update_dir() is not None and self.pending_switch is None
        self.update_label.setText(updatecheck.auto_notice_text(info, APP_VERSION) if auto
                                  else updatecheck.notice_text(info, APP_VERSION))
        self.update_install_btn.setVisible(auto)
        self.update_banner.setVisible(True)
        return True

    # ----- 資料夾版自動更新（第 12 項 12-3） -----
    def _self_update_dir(self):  # 測試換掉
        """能自己更新的話回傳程式資料夾（打包好的 Windows 資料夾版）；從原始碼跑、其他平台回 None。"""
        from subtitle import onedirupdate
        return onedirupdate.self_update_dir(getattr(sys, "frozen", False), sys.executable, sys.platform)

    def _config_dir(self):
        return os.path.dirname(os.path.abspath(config.CONFIG_PATH))

    def updating(self):
        """新版還在下載或準備中。"""
        return self.install_worker.busy

    def install_update(self):
        """〔下載並安裝〕：背景下載、解到旁邊、帶上設定與工具、寫好切換腳本。回傳有沒有開始。"""
        from subtitle import updatecheck
        app_dir = self._self_update_dir()
        asset = (self.update_info or {}).get("qt_asset")
        if not app_dir or not asset or self.pending_switch:
            return False
        if not self.install_worker.start(asset, self.update_info["version"], app_dir, self._config_dir(), os.getpid()):
            return False
        self.update_label.setText(updatecheck.progress_text(0, int(asset.get("size") or 0)))
        self.update_install_btn.setVisible(False)
        self.update_cancel_btn.setVisible(True)
        self.update_cancel_btn.setEnabled(True)
        for btn in (self.update_open_btn, self.update_skip_btn, self.update_close_btn):
            btn.setEnabled(False)
        return True

    def cancel_update_install(self):
        self.install_worker.cancel()
        self.update_cancel_btn.setEnabled(False)

    def _on_update_progress(self, done, total):
        from subtitle import updatecheck
        self.update_label.setText(updatecheck.progress_text(done, total))

    def _on_update_preparing(self):
        from subtitle import updatecheck
        self.update_label.setText(updatecheck.PREPARING_TEXT)
        self.update_cancel_btn.setEnabled(False)  # 解壓、複製不能停一半

    def _on_update_installed(self, result):
        from subtitle import updatecheck
        self.update_cancel_btn.setVisible(False)
        for btn in (self.update_open_btn, self.update_skip_btn, self.update_close_btn):
            btn.setEnabled(True)
        if "error" in result:
            self.update_label.setText(f"{result['error']}（可以再按一次「下載並安裝」，或到下載頁自己下載。）")
            self.update_install_btn.setVisible(True)
            return
        self.pending_switch = result["script"]
        self.update_label.setText(updatecheck.READY_TEXT)
        self.update_restart_btn.setVisible(True)
        self.update_skip_btn.setVisible(False)

    def _ask_close_while_updating(self):  # 測試換掉
        from PySide6.QtWidgets import QMessageBox
        return QMessageBox.question(self, "還在下載新版", CLOSE_WHILE_UPDATING) == QMessageBox.Yes

    def _spawn_switch(self, script):  # 測試換掉
        """關掉程式時：另開一個不跟著結束的行程跑切換腳本（等這個程式關掉才換資料夾）。"""
        import subprocess
        from subtitle import onedirupdate
        flags = 0
        for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
            flags |= getattr(subprocess, name, 0)
        subprocess.Popen(onedirupdate.script_command(script), creationflags=flags, close_fds=True)

    def _open_url(self, url):  # 測試換掉
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        return QDesktopServices.openUrl(QUrl(url))

    def open_update_page(self):
        if self.update_info:
            self._open_url(self.update_info["page"])

    def skip_update(self):
        """這一版不再提醒（記在設定裡，關掉 Qt 版時存回；更新的版本還是會提醒）。"""
        if self.update_info:
            data = dict(self.config_data.get("qt_update") or {})
            data["skipped_version"] = self.update_info["version"]
            self.config_data["qt_update"] = data
        self.update_banner.setVisible(False)

    def _ask_close_while_installing(self):  # 測試換掉
        from PySide6.QtWidgets import QMessageBox
        return QMessageBox.question(self, "還在安裝", CLOSE_WHILE_INSTALLING) == QMessageBox.Yes

    def refresh_ffmpeg_banner(self):
        from subtitle.burner import ffmpeg_available

        self.ffmpeg_banner.setVisible(not ffmpeg_available())

    def open_ffmpeg_install(self):
        """開「自動安裝 ffmpeg」（只建一個；不擋住主視窗）。裝好就收起上方的提示。"""
        from gui_qt.install_dialog import FfmpegInstallDialog

        if self.ffmpeg_dialog is None:
            self.ffmpeg_dialog = FfmpegInstallDialog(self)
            self.ffmpeg_dialog.installed.connect(lambda _r: self.refresh_ffmpeg_banner())
        self.ffmpeg_dialog.show()
        self.ffmpeg_dialog.raise_()
        self.ffmpeg_dialog.activateWindow()
        return self.ffmpeg_dialog

    def open_ocr_install(self):
        """開「安裝文字辨識（OCR）」（只建一個；不擋住主視窗）。"""
        from gui_qt.install_dialog import TesseractInstallDialog

        if self.ocr_dialog is None:
            self.ocr_dialog = TesseractInstallDialog(self)
        self.ocr_dialog.show()
        self.ocr_dialog.raise_()
        self.ocr_dialog.activateWindow()
        return self.ocr_dialog

    def toggle_theme(self):
        """深色↔淺色：馬上換（時間軸、審片清單照調色盤重畫），記進這次開啟的設定。回傳換成的主題。"""
        new = "light" if self.config_data.get("theme", "light") == "dark" else "dark"
        self.config_data["theme"] = new  # 關掉 Qt 版時存回 config.json；一般版也讀這一格
        apply_theme(QApplication.instance(), new)
        self.theme_btn.setText(theme_button_text(new))
        self.statusBar().showMessage(f"已切換為{'深色' if new == 'dark' else '淺色'}主題。", 5000)
        return new

    def open_guide(self):
        """打開新介面導覽（不擋主視窗）；已經開著就叫到前面。"""
        from gui_qt.guide_dialog import GuideDialog
        if self.guide_dialog is None:
            self.guide_dialog = GuideDialog(self)
            self.guide_dialog.closedWith.connect(self._on_guide_closed)
        self.guide_dialog.show()
        self.guide_dialog.raise_()
        self.guide_dialog.activateWindow()
        return self.guide_dialog

    def _on_guide_closed(self, never):
        """關掉導覽：記進這次開啟的設定（關掉 Qt 版時存）；勾了「不再顯示」就永遠不跳。"""
        self.config_data[qtguide.CONFIG_KEY] = qtguide.remember(never)

    def maybe_show_guide(self):
        """啟動時呼叫：沒看過這一版的導覽、也沒勾過「不再顯示」才跳。回傳有沒有跳。"""
        if not qtguide.should_show(self.config_data.get(qtguide.CONFIG_KEY)):
            return False
        self.open_guide()
        return True

    def open_transcription_settings(self):
        """打開轉寫與金鑰設定（只建一個；每次打開照這次開啟的設定重擺、金鑰回到遮住）。"""
        from gui_qt.transcribe_dialog import TranscriptionDialog

        if self.transcription_dialog is None:
            self.transcription_dialog = TranscriptionDialog(self.config_data, self)
            self.transcription_dialog.applied.connect(self._on_transcription_applied)
        if not self.transcription_dialog.isVisible():
            self.transcription_dialog.reload()
        self.transcription_dialog.show()
        self.transcription_dialog.raise_()
        self.transcription_dialog.activateWindow()
        return self.transcription_dialog

    def _on_transcription_applied(self, message):
        """套用了：狀態列講一句；開著的生成視窗重寫說明（能不能開始可能變了）。"""
        self.statusBar().showMessage(message, 8000)
        dialog = getattr(self.player_panel, "generate_dialog", None) if self.player_panel else None
        if dialog is not None and dialog.isVisible():
            dialog.refresh()

    def open_lookup(self):
        """打開即時查譯面板（收起來過就原地打開，快取與生字本都留著）。"""
        from gui_qt.quicklookup_dialog import QuickLookupDialog

        if self.lookup_dialog is None:
            self.lookup_dialog = QuickLookupDialog(self.player_panel, self.cue_panel, self)
        self.lookup_dialog.open()
        return self.lookup_dialog

    def open_audiovis(self):
        """開「音訊轉影片」小視窗（只建一個，關掉再開沿用；不擋住主視窗）。"""
        from gui_qt.audiovis_dialog import AudioVisDialog

        if self.audiovis_dialog is None:
            self.audiovis_dialog = AudioVisDialog(self.player_panel, self)
        elif not self.audiovis_dialog.rendering() and not self.audiovis_dialog.isVisible():
            media = self.player_panel.media_path
            if not self.audiovis_dialog.source_edit.text().strip() and media and os.path.exists(media):
                self.audiovis_dialog.source_edit.setText(media)
        self.audiovis_dialog.show()
        self.audiovis_dialog.raise_()
        self.audiovis_dialog.activateWindow()
        return self.audiovis_dialog

    def _health_page(self):
        """③ 健檢中心（第 11 項第八階段：先搬影片與字幕的檢查）。對象是②開著的影片與字幕。"""
        from gui_qt.health_panel import HealthPanel

        # ②先建（STAGES 的順序），這裡拿得到播放器
        self.health_panel = HealthPanel(self.player_panel, before_scan=self.cue_panel.commit)
        return self.health_panel

    def _output_page(self):
        """④ 輸出與發佈（第 11 項第十三階段：輸出設定、完成輸出、逐格式匯出）。對象是②開著的影片與字幕。"""
        from gui_qt.output_panel import OutputPanel

        self.output_panel = OutputPanel(self.player_panel, before_output=self.cue_panel.commit)
        return self.output_panel

    def closeEvent(self, event):  # noqa: N802 —— 專案或字幕改過還沒存：先問（存檔／放棄／取消）
        if (self.health_panel is not None and self.health_panel.fixing()
                and not self.health_panel.ask_close_while_fixing()):  # ③的修復版還在輸出
            event.ignore()
            return
        if (self.review_panel is not None and self.review_panel.cutting()
                and not self.review_panel.ask_close_while_cutting()):  # ①的粗剪／精彩合輯還在輸出
            event.ignore()
            return
        if (self.batch_dialog is not None and self.batch_dialog.running()
                and not self.batch_dialog.ask_close_while_running()):  # ①的批次還在跑
            event.ignore()
            return
        if (self.audiovis_dialog is not None and self.audiovis_dialog.rendering()
                and not self.audiovis_dialog.ask_close_while_rendering()):  # ①的音訊轉影片還在轉換
            event.ignore()
            return
        if (self.output_panel is not None and self.output_panel.burning()
                and not self.output_panel.ask_close_while_burning()):  # ④的硬字幕影片還在燒錄
            event.ignore()
            return
        if self.updating():  # 新版還在下載或解壓
            if not self._ask_close_while_updating():
                event.ignore()
                return
            self.install_worker.cancel()
        for dialog in (self.ffmpeg_dialog, self.ocr_dialog):  # 一鍵安裝還在下載：關掉程式下載就斷了
            if dialog is not None and dialog.installing() and not self._ask_close_while_installing():
                event.ignore()
                return
        if self.cue_panel is not None:
            self.cue_panel.commit()  # 編輯框裡改到一半的先套用，下面才問得到要不要存
        if self.player_panel is not None and not self.player_panel.maybe_close():
            event.ignore()
            return
        if self.lookup_dialog is not None:
            self.lookup_dialog.shutdown()  # 停朗讀（收面板不會停）、停監聽剪貼簿
        if self.player_panel is not None:
            self.player_panel.shutdown()
        self.save_settings()
        super().closeEvent(event)
        if self.pending_switch:  # 走到這裡就是真的要關了（關不掉的上面都 return 了）；準備好的新版：程式關掉後由切換腳本換上並重新開啟
            script, self.pending_switch = self.pending_switch, None
            try:
                self._spawn_switch(script)
            except OSError:
                logging.getLogger(__name__).exception("無法執行更新切換腳本：%s", script)

    def save_settings(self):
        """
        把這次開啟期間改過的設定存回 config.json（只寫改過的最上層區塊，見 `configmerge`）。

        回傳有沒有寫。什麼都沒改就不寫（檔案原封不動）。存不進去（唯讀、磁碟滿）不擋關視窗：記在記錄檔，
        這次改的設定下次開啟就不在了。
        """
        if not self.persist or not changed_sections(self._opened_config, self.config_data):
            return False
        try:
            disk = config.load_config()  # 磁碟上現在的（一般版剛存的也在裡面）
            config.save_config(merge_for_save(disk, self._opened_config, self.config_data))
        except OSError as exc:
            logger.warning("Qt 版存設定失敗（%s）：%s", config.CONFIG_PATH, exc)
            return False
        self._opened_config = copy.deepcopy(self.config_data)
        return True


SELFTEST_FLAG = "--selftest"


def _cleanup_previous_update():
    """上一次自動更新換下來的舊資料夾（`<程式資料夾>.old`）：新版開得起來了才刪（第 12 項 12-3）。"""
    from subtitle import onedirupdate
    app_dir = onedirupdate.self_update_dir(getattr(sys, "frozen", False), sys.executable, sys.platform)
    if app_dir:
        onedirupdate.cleanup_backup(app_dir)


def main(argv=None):
    """
    建立並執行 Qt 版。回傳事件迴圈的結束碼。

    `--selftest <結果.json> <影片>`：打包後的自檢模式（見 gui_qt/selftest.py）。
    """
    argv = list(sys.argv if argv is None else argv)
    # 一般版「自動安裝 ffmpeg」裝好的執行檔兩版共用：加進本行程的 PATH
    # （時間軸的波形與縮圖要用；不改系統設定）。
    from subtitle.ffmpeg_setup import ensure_ffmpeg_on_path
    ensure_ffmpeg_on_path()
    app = QApplication.instance() or QApplication(argv[:1])
    _cleanup_previous_update()
    data = config.load_config()
    apply_theme(app, data.get("theme", "light"))
    win = MainWindow(data, persist=SELFTEST_FLAG not in argv)  # 自檢模式不碰使用者的設定檔
    if SELFTEST_FLAG in argv:
        at = argv.index(SELFTEST_FLAG)
        if len(argv) < at + 3:
            print("用法：--selftest <結果.json> <影片>", file=sys.stderr)
            return 2
        from gui_qt import selftest
        return selftest.run(app, win, argv[at + 1], argv[at + 2])
    win.show()
    from PySide6.QtCore import QTimer
    QTimer.singleShot(UPDATE_CHECK_DELAY_MS, win.start_update_check)  # 啟動後再查，不拖慢開視窗
    QTimer.singleShot(0, win.maybe_show_guide)  # 主視窗畫好再跳導覽（自檢模式上面已經 return，不會跳）
    return app.exec()
