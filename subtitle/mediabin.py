# -*- coding: utf-8 -*-
"""
素材庫（剪輯器版面 E-4）的規則：哪些檔收、算哪一種、去重、拖到時間軸的哪一列該放進哪一軌、時間標籤。

只放資料與純計算（零 GUI 依賴、不 import config）；介面在 `gui_qt/media_bin.py`，拖放的落點在
`gui_qt/timeline.py`，真正放上素材軌的是 `PlayerPanel.drop_files`（照舊走 `add_track` 的檢查）。
"""
import os

from .assemble import IMAGE_EXTS

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")
AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus")
KINDS = ("video", "image", "audio")
KIND_NAMES = {"video": "影片", "image": "圖片", "audio": "聲音"}

# 拖到哪一列 → 這一種放哪一軌（None＝這一列不收這一種）。其他列（畫面、聲音、字幕、剪點）照種類放：
# 影片與圖片疊在畫面上、聲音當音樂。
ROW_TRACKS = {
    "overlays": {"video": "overlays", "image": "overlays", "audio": None},
    "music": {"video": "music", "image": None, "audio": "music"},
}
DEFAULT_TRACK = {"video": "overlays", "image": "overlays", "audio": "music"}


def kind_of(path):
    """副檔名 → "video"／"image"／"audio"；不認得是 None（不看檔案內容，真的讀不讀得出來交給 add_track）。"""
    ext = os.path.splitext(str(path))[1].lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in AUDIO_EXTS:
        return "audio"
    return None


def _key(path):
    return os.path.normcase(os.path.abspath(path))


def add_paths(entries, paths):
    """
    把 paths 加進素材庫 entries（[{"path", "kind"}]，不改原本的清單）。回傳 (新的清單, 加了哪些, 略過哪些)；
    略過的是 [(路徑, 原因)]：不認得的種類、找不到檔案、已經在裡面（同一次匯入重複的也算）。
    """
    out = [dict(e) for e in entries]
    seen = {_key(e["path"]) for e in out}
    added, skipped = [], []
    for raw in paths:
        path = os.path.abspath(str(raw))
        kind = kind_of(path)
        if kind is None:
            skipped.append((path, "不是影片、圖片或聲音"))
        elif not os.path.isfile(path):
            skipped.append((path, "找不到檔案"))
        elif _key(path) in seen:
            skipped.append((path, "已經在素材庫裡"))
        else:
            seen.add(_key(path))
            entry = {"path": path, "kind": kind}
            out.append(entry)
            added.append(entry)
    return out, added, skipped


def remove_paths(entries, paths):
    """從素材庫拿掉 paths（不改原本的清單；不在裡面的不管）。"""
    gone = {_key(p) for p in paths}
    return [dict(e) for e in entries if _key(e["path"]) not in gone]


def track_for(row, kind):
    """拖到第 row 列（"overlays"／"music"／其他）的這一種要放哪一軌；不收是 None。"""
    if kind not in KINDS:
        return None
    if row in ROW_TRACKS:
        return ROW_TRACKS[row][kind]
    return DEFAULT_TRACK[kind]


ROW_NAMES = {"overlays": "疊加列", "music": "音樂列"}
TRACK_NAMES = {"overlays": "疊加", "music": "音樂"}
ROW_RULE = "疊加列放影片或圖片、音樂列放聲音或影片"


def drop_plan(paths, row):
    """
    拖到第 row 列會怎麼放（剪輯器版面 E-8c 的落點預覽，跟真的放 `PlayerPanel.drop_files` 同一套規則）：
    {"overlays": [路徑], "music": [路徑], "refused": [路徑]}，順序照拖進來的。
    """
    plan = {"overlays": [], "music": [], "refused": []}
    for path in paths:
        track = track_for(row, kind_of(path))
        plan[track if track else "refused"].append(path)
    return plan


def refused_note(row, paths):
    """這一列不收哪些檔：「疊加列放不了：a.mp3、b.wav（疊加列放影片或圖片、音樂列放聲音或影片）」。"""
    where = ROW_NAMES.get(row, "這一列")
    names = "、".join(os.path.basename(p) for p in paths)
    return f"{where}放不了：{names}（{ROW_RULE}）"


def drop_hint(plan, row):
    """預覽框旁邊的一句話：放到哪幾軌各幾個；有放不了的接在後面。都放不了就只講放不了。"""
    parts = [f"{TRACK_NAMES[t]} {len(plan[t])} 個" for t in ("overlays", "music") if plan.get(t)]
    text = "放到" + "、".join(parts) if parts else ""
    if plan.get("refused"):
        text = (text + "；" if text else "") + refused_note(row, plan["refused"])
    return text


def duration_label(seconds):
    """5.2 → "0:05"、3725 → "1:02:05"；量不到（None、負的）是空字串。"""
    if seconds is None or seconds < 0:
        return ""
    total = int(round(float(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def file_filter():
    """檔案對話框的篩選字串：三種一起、各自一種、所有檔案。"""
    def globs(exts):
        return " ".join("*" + e for e in exts)
    every = VIDEO_EXTS + IMAGE_EXTS + AUDIO_EXTS
    return (f"影片、圖片、聲音 ({globs(every)});;影片 ({globs(VIDEO_EXTS)});;圖片 ({globs(IMAGE_EXTS)});;"
            f"聲音 ({globs(AUDIO_EXTS)});;所有檔案 (*)")
