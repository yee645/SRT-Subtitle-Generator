# -*- coding: utf-8 -*-
"""
3.0 第 13 項：線上配樂庫——在剪輯器裡直接搜尋、試聽開放授權的配樂，放進音樂軌。

使用者 2026-10-11：「讓使用者不必下載至本機，直接透過 API 或軟體連結，節省使用者電腦
空間和省下切視窗搜尋各個媒體平台的時間」。規則都在 `subtitle/musiclib.py`（零 GUI 依賴），
這裡只有介面：

* 搜尋：關鍵字、情境、風格至少選一個，查 Openverse（音樂來自 Jamendo 等開放授權來源）。
  預設只列可商用的（CC0／公眾領域／BY／BY-SA），勾「也列非商用」才列 NC；有人聲的預設
  不列（配樂多半墊在講話底下）。一次一頁，「載入更多」接著翻。
* 試聽：QMediaPlayer 直接串流網址，不存檔。
* 放進音樂軌：先用 ffprobe 讀一次網址（`musiclib.check_stream`）確認播得出來、量出長度，
  再交給播放器面板放在播放頭的位置（`PlayerPanel.add_online_music`）。音樂軌記的是網址與
  曲名、授權；輸出時 ffmpeg 直接讀網址，影片旁邊寫一份 `_配樂標註.txt`。
* 「原始頁面」用瀏覽器開那首歌的來源頁（看授權條款、要正式檔時從那裡下載）。

視窗不擋住面板（非強制回應）：可以邊試聽邊移動播放頭，到想放的位置再按「放進音樂軌」。
搜尋與確認都在背景執行緒跑，結果帶編號：送出新的搜尋後，舊的結果晚到就丟掉。
"""
import threading
import urllib.error

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from subtitle import musiclib

COLUMNS = ("曲名", "作者", "長度", "情境", "風格", "授權")
SOURCE_NOTE = ("音樂來自 Openverse（Jamendo 等開放授權來源），不會下載到電腦：試聽與輸出都直接讀網址"
               "（輸出時要連網），輸出時在影片旁邊寫一份標註文字，貼到影片說明欄。")


class Background(QObject):
    """在背景執行緒跑一個函式，結果用訊號送回主執行緒（帶工作名稱與編號，舊的由呼叫端丟掉）。"""

    finished = Signal(str, int, object)
    failed = Signal(str, int, object)

    def run(self, name, gen, func):
        def work():
            try:
                result = func()
            except Exception as exc:  # noqa: BLE001 —— 什麼錯都要送回去，不然畫面一直停在「搜尋中」
                self.failed.emit(name, gen, exc)
                return
            self.finished.emit(name, gen, result)
        threading.Thread(target=work, daemon=True).start()


def describe_error(exc):
    """搜尋失敗 → 給人看的一句話。"""
    if isinstance(exc, musiclib.RateLimited):
        wait = exc.args[0] if exc.args else 60
        return (f"Openverse 的查詢額度暫時用完，約 {wait} 秒後再試"
                "（常用的話可以申請免費金鑰提高額度，見 bgm_collector/README.md）")
    if isinstance(exc, urllib.error.HTTPError):
        return f"Openverse 回應錯誤（HTTP {exc.code}），稍後再試"
    if isinstance(exc, (urllib.error.URLError, OSError)):
        return f"連不上 Openverse（{getattr(exc, 'reason', None) or exc}）：請確認網路"
    return f"搜尋失敗：{exc}"


class MusicLibraryDialog(QDialog):
    """
    線上配樂庫視窗。client：Openverse 用戶端（省略＝第一次搜尋時照環境變數建一個，測試換成
    替身）；checker：確認網址播得出來的函式（預設 `musiclib.check_stream`）；on_add(紀錄, 秒數)
    → 是否放進去；can_add() → 現在能不能放（沒開片子、輸出中就不行）。
    """

    def __init__(self, parent=None, client=None, checker=musiclib.check_stream,
                 on_add=None, can_add=None):
        super().__init__(parent)
        self.setWindowTitle("線上配樂庫")
        self.resize(860, 520)
        self.client = client
        self.checker = checker
        self.on_add = on_add
        self.can_add = can_add or (lambda: on_add is not None)
        self._client_lock = threading.Lock()
        self.records = []        # 表格上每一列的配樂紀錄（同順序）
        self.page = 0
        self.has_more = False
        self.skipped = {}        # 這次搜尋略過的（原因 → 首數），各頁加總
        self._query = None
        self._search_gen = 0
        self._searching = False
        self._check_gen = 0
        self._checking = None    # 正在確認的那首
        self.previewing = None   # 試聽中那首的 id
        self.worker = Background(self)

        self.keyword_edit = QLineEdit()
        self.keyword_edit.setPlaceholderText("關鍵字（英文較準，例如 piano、summer、chill）")
        self.mood_combo = QComboBox()
        self.mood_combo.addItem("任何情境", None)
        for name in musiclib.MOOD_NAMES:
            self.mood_combo.addItem(name, name)
        self.style_combo = QComboBox()
        self.style_combo.addItem("任何風格", None)
        for name in musiclib.STYLE_NAMES:
            self.style_combo.addItem(name, name)
        self.search_btn = QPushButton("搜尋")
        self.search_btn.setDefault(True)
        self.nc_box = QCheckBox("也列非商用（NC）")
        self.nc_box.setToolTip("CC BY-NC 系列只能用在不營利的影片：開了營利、業配、接案都不能用")
        self.vocal_box = QCheckBox("也列有人聲")
        self.vocal_box.setToolTip("有人唱歌的歌墊在講話底下容易搶戲，預設不列")

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.Stretch)

        self.status_label = QLabel("輸入關鍵字，或選一個情境、風格，按「搜尋」")
        self.status_label.setWordWrap(True)
        self.more_btn = QPushButton("載入更多")
        self.preview_btn = QPushButton("試聽")
        self.page_btn = QPushButton("原始頁面")
        self.page_btn.setToolTip("用瀏覽器開這首歌的來源頁：看授權條款，要正式檔也從那裡下載")
        self.add_btn = QPushButton("放進音樂軌")
        self.add_btn.setToolTip("放在播放器目前的位置；記的是網址，不下載到電腦")
        note = QLabel(SOURCE_NOTE)
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)

        search_row = QHBoxLayout()
        search_row.addWidget(self.keyword_edit, 1)
        for w in (self.mood_combo, self.style_combo, self.search_btn):
            search_row.addWidget(w)
        option_row = QHBoxLayout()
        option_row.addWidget(self.nc_box)
        option_row.addWidget(self.vocal_box)
        option_row.addStretch(1)
        action_row = QHBoxLayout()
        action_row.addWidget(self.status_label, 1)
        for w in (self.more_btn, self.preview_btn, self.page_btn, self.add_btn):
            action_row.addWidget(w)
        layout = QVBoxLayout(self)
        layout.addLayout(search_row)
        layout.addLayout(option_row)
        layout.addWidget(self.table, 1)
        layout.addLayout(action_row)
        layout.addWidget(note)

        self.search_btn.clicked.connect(self.search)
        self.keyword_edit.returnPressed.connect(self.search)
        self.more_btn.clicked.connect(self.load_more)
        self.preview_btn.clicked.connect(self.toggle_preview)
        self.page_btn.clicked.connect(self.open_page)
        self.add_btn.clicked.connect(self.add_selected)
        self.table.itemSelectionChanged.connect(self.update_buttons)
        self.table.itemDoubleClicked.connect(lambda _item: self.toggle_preview())
        self.worker.finished.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.player.playbackStateChanged.connect(lambda _s: self.update_buttons())
        self.player.errorOccurred.connect(self._on_preview_error)
        self.update_buttons()

    # ---- 搜尋 ----------------------------------------------------------

    def search(self):
        """照目前的關鍵字、情境、風格從第一頁重新查。回傳是否送出（條件不夠就說明、不送）。"""
        query = {"keyword": self.keyword_edit.text().strip(),
                 "mood": self.mood_combo.currentData(), "style": self.style_combo.currentData(),
                 "commercial_only": not self.nc_box.isChecked(),
                 "allow_vocal": self.vocal_box.isChecked()}
        try:
            musiclib.search_request(query["keyword"], query["mood"], query["style"])
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return False
        self._query = query
        self.records, self.page, self.has_more, self.skipped = [], 0, False, {}
        self.table.setRowCount(0)
        self._start_search(1)
        return True

    def load_more(self):
        """接著查下一頁，加在表格後面。"""
        if not self._query or not self.has_more or self._searching:
            return False
        self._start_search(self.page + 1)
        return True

    def _start_search(self, page):
        self._search_gen += 1
        self._searching = True
        self.status_label.setText("搜尋中…" if page == 1 else "載入更多…")
        query = dict(self._query)
        self.worker.run("search", self._search_gen,
                        lambda: musiclib.search(self._client(), page=page, **query))
        self.update_buttons()

    def _client(self):
        with self._client_lock:  # 第一次會連網換金鑰（有設環境變數時），只做一次
            if self.client is None:
                self.client = musiclib.client_from_env()
            return self.client

    def _on_search_done(self, result):
        self._searching = False
        known = {rec["id"] for rec in self.records}
        for rec in result["tracks"]:
            if rec["id"] not in known:
                known.add(rec["id"])
                self.records.append(rec)
                self._append_row(rec)
        self.page, self.has_more = result["page"], result["has_more"]
        for reason, count in result["skipped"].items():
            self.skipped[reason] = self.skipped.get(reason, 0) + count
        skipped = "、".join(f"{reason} {count} 首" for reason, count in self.skipped.items())
        if not self.records:
            text = "找不到能用的配樂：換個關鍵字，或放寬情境、風格" + (f"（略過：{skipped}）" if skipped else "")
        else:
            text = f"列出 {len(self.records)} 首" + ("，還有更多" if self.has_more else "") \
                + (f"；略過 {skipped}" if skipped else "")
        self.status_label.setText(text)
        if self.records and self.table.currentRow() < 0:
            self.table.selectRow(0)

    def _append_row(self, rec):
        row = self.table.rowCount()
        self.table.insertRow(row)
        license_tip = musiclib.license_label(rec["license"], rec.get("license_version"))
        warning = musiclib.license_warning(rec)
        cells = (
            (rec["title"], musiclib.attribution_line(rec)),
            (rec["creator"] or "—", rec.get("creator_url") or ""),
            (musiclib.format_duration(rec["duration"]) or "?", ""),
            ("、".join(rec["moods"]), "照 Jamendo 的情緒標籤分的"),
            (rec["style"], "、".join(rec["genres"])),
            (musiclib.license_tag(rec), license_tip + (f"\n{warning}" if warning else "")),
        )
        for col, (text, tip) in enumerate(cells):
            item = QTableWidgetItem(text)
            if tip:
                item.setToolTip(tip)
            self.table.setItem(row, col, item)

    def selected_record(self):
        row = self.table.currentRow()
        return self.records[row] if 0 <= row < len(self.records) else None

    # ---- 試聽 ----------------------------------------------------------

    def toggle_preview(self):
        """試聽選取的那首（串流，不存檔）；正在試聽同一首就停。"""
        rec = self.selected_record()
        if self.previewing is not None and (rec is None or rec["id"] == self.previewing):
            self.stop_preview()
            return False
        if rec is None:
            return False
        self.previewing = rec["id"]
        self.player.setSource(QUrl(rec["audio_url"]))
        self.player.play()
        self.status_label.setText(f"試聽：{rec['title']}（直接串流，不存檔）")
        self.update_buttons()
        return True

    def stop_preview(self):
        self.previewing = None
        self.player.stop()
        self.player.setSource(QUrl())  # 放掉連線
        self.update_buttons()

    def _on_preview_error(self, _error, message=""):
        if self.previewing is not None:
            self.previewing = None
            self.status_label.setText(f"這首試聽不了：{message or self.player.errorString()}")
            self.update_buttons()

    def open_page(self):
        rec = self.selected_record()
        if rec and rec.get("landing_url"):
            QDesktopServices.openUrl(QUrl(rec["landing_url"]))
            return True
        return False

    # ---- 放進音樂軌 ----------------------------------------------------

    def add_selected(self):
        """先在背景確認網址播得出來、量出長度，再交給 on_add。回傳是否開始確認。"""
        rec = self.selected_record()
        if rec is None or self._checking is not None or not self.can_add():
            return False
        self._check_gen += 1
        self._checking = rec
        self.status_label.setText(f"確認「{rec['title']}」播得出來…")
        url = rec["audio_url"]
        self.worker.run("check", self._check_gen, lambda: self.checker(url))
        self.update_buttons()
        return True

    def _on_check_done(self, result):
        rec, self._checking = self._checking, None
        if not result.get("ok"):
            self.status_label.setText(f"「{rec['title']}」放不進去：{result.get('reason') or '讀不到'}")
        elif self.on_add is not None and self.on_add(rec, float(result["seconds"])):
            self.status_label.setText(f"已放進音樂軌：「{rec['title']}」（{musiclib.license_tag(rec)}）")
        else:
            self.status_label.setText(f"「{rec['title']}」沒有放進去")
        self.update_buttons()

    # ---- 背景工作的結果 ------------------------------------------------

    def _on_done(self, name, gen, result):
        if name == "search" and gen == self._search_gen:
            self._on_search_done(result)
        elif name == "check" and gen == self._check_gen:
            self._on_check_done(result)
        self.update_buttons()

    def _on_failed(self, name, gen, exc):
        if name == "search" and gen == self._search_gen:
            self._searching = False
            self.status_label.setText(describe_error(exc))
        elif name == "check" and gen == self._check_gen:
            rec, self._checking = self._checking, None
            self.status_label.setText(f"「{rec['title']}」放不進去：{exc}")
        self.update_buttons()

    def update_buttons(self):
        rec = self.selected_record()
        self.more_btn.setEnabled(bool(self.has_more) and not self._searching)
        self.preview_btn.setEnabled(rec is not None or self.previewing is not None)
        self.preview_btn.setText("停止" if self.previewing is not None
                                 and (rec is None or rec["id"] == self.previewing) else "試聽")
        self.page_btn.setEnabled(bool(rec and rec.get("landing_url")))
        self.add_btn.setEnabled(rec is not None and self._checking is None and bool(self.can_add()))

    def hideEvent(self, event):  # noqa: N802 —— 關掉視窗就停止試聽
        if self.previewing is not None:
            self.stop_preview()
        super().hideEvent(event)
