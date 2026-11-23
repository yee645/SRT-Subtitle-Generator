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
from updater import APP_VERSION

logger = logging.getLogger(__name__)

FFMPEG_BANNER = ("⚠ 找不到 ffmpeg：時間軸的波形與縮圖、燒錄、輸出影片、健檢的影音項目都需要它。"
                 "按右邊一鍵安裝（不需要管理員權限，兩版共用）。")

UPDATE_CHECK_DELAY_MS = 1500  # 跟一般版一樣：開好視窗 1.5 秒後才查新版本
CLOSE_WHILE_INSTALLING = "一鍵安裝還在下載。現在關掉程式，下載會中斷，下次要再安裝一次。還是要關嗎？"

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
        self.tabs.setCornerWidget(self.lookup_btn, Qt.TopRightCorner)
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._build_ffmpeg_banner())
        central_layout.addWidget(self._build_update_banner())
        central_layout.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage(
            "3.0 預覽版：目前有①的審片助手（分析、段落清單、粗剪與匯出、章節與發佈包、封面候選、直式短片）、音訊轉影片與批次一鍵完成、②字幕頁、③健檢中心（含系列一致性）、"
            "④的匯出、燒錄與品牌套版、右上角的即時查譯，其餘請先用一般版。")

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
        """查到新版時頁籤上方一條提示：〔開啟下載頁〕〔這版不再提醒〕〔關閉提示〕。平常收著。"""
        from gui_qt.update_notice import UpdateWorker
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
        for btn in (self.update_open_btn, self.update_skip_btn, self.update_close_btn):
            row.addWidget(btn)
        self.update_banner.setVisible(False)
        self.update_worker = UpdateWorker(self)
        self.update_worker.finished.connect(self.show_update)
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
        self.update_label.setText(updatecheck.notice_text(info, APP_VERSION))
        self.update_banner.setVisible(True)
        return True

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
    return app.exec()
