# -*- coding: utf-8 -*-
"""
3.0 第 10 項：專案檔——把整條時間軸存成可以重開的檔案。

剪接的決定一多（素材放哪、剪點停用哪幾個、畫面怎麼調），每次重開都要重做就不能用了。專案檔
是一個 JSON（副檔名 `.srtproj`），記：

* `media`：主片（路徑）與它的畫面調整（`subtitle/picture.py` 的格式，只記改過的）。
* `subtitles`：字幕檔的路徑（存字幕時寫回哪裡），以及**字幕內容本身**（`cues`）：字幕可能在
  時間軸上改過還沒存，重開要看到的是存專案那一刻的樣子。
* `tracks`：素材軌（`assemble` 的格式：疊加畫面、背景音樂與各段的屬性、調整）。
* `cuts`：剪點顯示哪一種（`cutmarks.SOURCES`），以及使用者對剪點的微調（停用、改範圍，照剪點的
  key 記）。剪點本身每次照字幕重算，所以只記微調。
* `seam`：剪點接縫的轉場（硬切／溶接／黑場與長度）。

**路徑**：每個檔案記兩種——相對於專案檔的位置（整個資料夾搬走、換電腦還開得起來）與絕對路徑。
讀的時候先找相對的、再找絕對的；兩個都找不到的不算錯，列在 `missing` 讓介面說清楚（使用者可能
只是外接硬碟沒插）。Windows 上不同磁碟機算不出相對路徑，就只記絕對的。

**版本**：`version` 是格式的版本。讀到較舊的照 `MIGRATIONS` 一步一步升到現在的；較新的（新版
程式存的）不硬讀，說清楚要更新程式。

**檢查**：讀進來的每一項都照存的時候同一套規則檢查（素材軌照 `assemble.normalize`、調整照
`picture.normalize`），不合理就拋 `ProjectError`，說是哪一項。檔案寫入先寫暫存檔再換名，存到一半
當掉不會留下半個專案檔。

零 GUI 依賴。
"""
from __future__ import annotations

import json
import math
import os
import tempfile

from . import assemble, cutmarks, picture

FORMAT = "srt-subtitle-generator-project"
VERSION = 1
SUFFIX = ".srtproj"
MAX_BYTES = 20 * 1024 * 1024   # 再大就不是正常的專案檔（字幕幾萬句也才幾 MB）
MAX_CUES = 50000
SEAM_TYPES = ("",) + tuple(assemble.TRANSITIONS)
DEFAULT_SEAM = {"type": "", "duration": 0.5}

# 舊版 → 新一版的轉換：{舊版號: 函式(doc) → 新 doc}。現在只有第 1 版，還沒有要轉的。
MIGRATIONS = {}


class ProjectError(ValueError):
    """專案檔讀不進來或內容不合理。"""


def new_state() -> dict:
    """空的專案狀態（還沒開影片）。"""
    return {"media": "", "adjust": {}, "subtitles": "", "cues": [],
            "tracks": {"overlays": [], "music": []},
            "cuts": {"source": "", "overrides": {}}, "seam": dict(DEFAULT_SEAM)}


# ---- 檢查 ------------------------------------------------------------------

def _finite(value, what):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ProjectError(f"{what}不是數字：{value!r}") from None
    if not math.isfinite(number):
        raise ProjectError(f"{what}不是有限的數字")
    return number


def _plain(value, what):
    """只收 JSON 認得的值（字串、數字、布林、None、清單、dict），其他的（物件）不收。"""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float)):
        _finite(value, what)
        return value
    if isinstance(value, (list, tuple)):
        return [_plain(v, what) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v, what) for k, v in value.items()}
    raise ProjectError(f"{what}有存不進專案檔的值：{type(value).__name__}")


def _cues(cues):
    if not isinstance(cues, list):
        raise ProjectError("字幕要是清單")
    if len(cues) > MAX_CUES:
        raise ProjectError(f"字幕太多（{len(cues)} 句，上限 {MAX_CUES}）")
    out = []
    for i, cue in enumerate(cues, 1):
        if not isinstance(cue, dict):
            raise ProjectError(f"第 {i} 句字幕要是 dict")
        start = _finite(cue.get("start"), f"第 {i} 句字幕的開始")
        end = _finite(cue.get("end"), f"第 {i} 句字幕的結束")
        if start < 0 or end < start:
            raise ProjectError(f"第 {i} 句字幕的時間不合理（{start:g}～{end:g}）")
        if not isinstance(cue.get("text", ""), str):
            raise ProjectError(f"第 {i} 句字幕的文字要是字串")
        out.append(_plain(dict(cue, start=start, end=end, text=cue.get("text", "")), f"第 {i} 句字幕"))
    return out


def _tracks(tracks, media):
    if not isinstance(tracks, dict) or set(tracks) - set(assemble.TRACK_KINDS):
        raise ProjectError("素材軌要是 {\"overlays\": [...], \"music\": [...]}")
    out = {kind: [] for kind in assemble.TRACK_KINDS}
    for kind in assemble.TRACK_KINDS:
        items = tracks.get(kind) or []
        if not isinstance(items, list):
            raise ProjectError(f"素材軌 {kind} 要是清單")
        for i, item in enumerate(items, 1):
            if not isinstance(item, dict) or not item.get("path"):
                raise ProjectError(f"素材軌 {kind} 第 {i} 段沒有檔案")
            out[kind].append(_plain(item, f"素材軌 {kind} 第 {i} 段"))
    # 照輸出同一套規則檢查（主軌放一段夠長的假片，只為了讓素材的時間有地方放）
    try:
        assemble.normalize({"main": [{"path": media or "主片", "out": 10.0 ** 6}], **out})
    except assemble.AssembleError as exc:
        raise ProjectError(f"素材軌不合理：{exc}") from None
    return out


def _cuts(cuts):
    if not isinstance(cuts, dict):
        raise ProjectError("剪點要是 dict")
    source = cuts.get("source") or ""
    if source not in ("",) + tuple(cutmarks.SOURCES):
        raise ProjectError(f"不認得的剪點種類：{source!r}")
    overrides = cuts.get("overrides") or {}
    if not isinstance(overrides, dict):
        raise ProjectError("剪點的微調要是 dict")
    out = {}
    for key, change in overrides.items():
        if not isinstance(change, dict) or set(change) - {"enabled", "start", "end"}:
            raise ProjectError(f"剪點 {key} 的微調只能有 enabled、start、end")
        item = {}
        if "enabled" in change:
            item["enabled"] = bool(change["enabled"])
        if ("start" in change) != ("end" in change):
            raise ProjectError(f"剪點 {key} 的範圍要同時有 start 與 end")
        if "start" in change:
            start = _finite(change["start"], f"剪點 {key} 的開始")
            end = _finite(change["end"], f"剪點 {key} 的結束")
            if start < 0 or end <= start:
                raise ProjectError(f"剪點 {key} 的範圍不合理（{start:g}～{end:g}）")
            item["start"], item["end"] = round(start, 3), round(end, 3)
        out[str(key)] = item
    return {"source": source, "overrides": out}


def _seam(seam):
    if not isinstance(seam, dict):
        raise ProjectError("接縫要是 dict")
    kind = seam.get("type") or ""
    if kind not in SEAM_TYPES:
        raise ProjectError(f"不認得的接縫轉場：{kind!r}")
    duration = round(_finite(seam.get("duration", DEFAULT_SEAM["duration"]), "接縫轉場的長度"), 3)
    if not assemble.MIN_TRANSITION <= duration <= assemble.MAX_TRANSITION:
        raise ProjectError(f"接縫轉場的長度要在 {assemble.MIN_TRANSITION:g}～{assemble.MAX_TRANSITION:g} 秒之間")
    return {"type": kind, "duration": duration}


def normalize_state(state) -> dict:
    """檢查一份專案狀態，回傳整理過的新 dict（缺的補預設）；不合理就拋 ProjectError。"""
    if not isinstance(state, dict):
        raise ProjectError("專案內容要是 dict")
    unknown = sorted(set(state) - set(new_state()))
    if unknown:
        raise ProjectError(f"專案裡有不認得的項目：{'、'.join(unknown)}")
    out = new_state()
    for key in ("media", "subtitles"):
        value = state.get(key) or ""
        if not isinstance(value, str):
            raise ProjectError(f"{key} 要是檔案路徑（字串）")
        out[key] = value
    try:
        out["adjust"] = picture.changes(picture.normalize(state.get("adjust") or {}, "主片的畫面調整"))
    except picture.PictureError as exc:
        raise ProjectError(str(exc)) from None
    out["cues"] = _cues(state.get("cues") or [])
    out["tracks"] = _tracks(state.get("tracks") or {}, out["media"])
    out["cuts"] = _cuts(state.get("cuts") or {})
    out["seam"] = _seam(state.get("seam") or DEFAULT_SEAM)
    if (out["tracks"]["overlays"] or out["tracks"]["music"] or out["adjust"]) and not out["media"]:
        raise ProjectError("有素材軌或畫面調整，卻沒有主片")
    return out


# ---- 路徑 ------------------------------------------------------------------

def _portable(path, base):
    """記一個檔案：{"path": 相對於專案檔的路徑（用 /）, "absolute": 絕對路徑}；算不出相對的就只記絕對的。"""
    absolute = os.path.abspath(path)
    entry = {"absolute": absolute}
    try:
        entry["path"] = os.path.relpath(absolute, base).replace(os.sep, "/")
    except ValueError:  # Windows 不同磁碟機
        pass
    return entry


def _resolve(entry, base, what, missing):
    """照專案檔的位置找回檔案：先相對、再絕對；都找不到就記進 missing，回傳最可能的那個。"""
    if isinstance(entry, str):
        entry = {"absolute": entry}
    if not isinstance(entry, dict) or not (entry.get("path") or entry.get("absolute")):
        raise ProjectError(f"{what}的檔案位置不合理")
    candidates = []
    if entry.get("path"):
        candidates.append(os.path.normpath(os.path.join(base, *str(entry["path"]).split("/"))))
    if entry.get("absolute"):
        candidates.append(os.path.normpath(str(entry["absolute"])))
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    missing.append((what, candidates[0]))
    return candidates[0]


# ---- 文件 ------------------------------------------------------------------

def to_document(state, project_path) -> dict:
    """專案狀態 → 要寫進檔案的 dict（路徑換成相對＋絕對兩種）。"""
    state = normalize_state(state)
    base = os.path.dirname(os.path.abspath(project_path))
    tracks = {kind: [dict(item, path=_portable(item["path"], base)) for item in items]
              for kind, items in state["tracks"].items()}
    return {
        "format": FORMAT,
        "version": VERSION,
        "media": {"file": _portable(state["media"], base) if state["media"] else None,
                  "adjust": state["adjust"]},
        "subtitles": {"file": _portable(state["subtitles"], base) if state["subtitles"] else None,
                      "cues": state["cues"]},
        "tracks": tracks,
        "cuts": state["cuts"],
        "seam": state["seam"],
    }


def upgrade(doc) -> dict:
    """舊版的專案檔一步一步升到現在的版本；較新的（新版程式存的）不硬讀。"""
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ProjectError("這不是本程式的專案檔")
    version = doc.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ProjectError(f"專案檔的版本不合理：{version!r}")
    if version > VERSION:
        raise ProjectError(f"這個專案檔是較新版本的程式存的（格式第 {version} 版，這個程式只認得到第 {VERSION} 版），"
                           "請先更新程式")
    while version < VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise ProjectError(f"不知道怎麼把第 {version} 版的專案檔升上來")
        doc = step(dict(doc))
        version += 1
        doc["version"] = version
    return doc


def from_document(doc, project_path):
    """檔案裡的 dict → (專案狀態, 找不到的檔案 [(哪一個, 路徑)])。"""
    doc = upgrade(doc)
    base = os.path.dirname(os.path.abspath(project_path))
    missing = []
    media = doc.get("media") or {}
    subtitles = doc.get("subtitles") or {}
    if not isinstance(media, dict) or not isinstance(subtitles, dict):
        raise ProjectError("專案檔的 media／subtitles 要是 dict")
    tracks = doc.get("tracks") or {}
    if not isinstance(tracks, dict):
        raise ProjectError("素材軌要是 dict")
    resolved = {}
    for kind, items in tracks.items():
        if not isinstance(items, list):
            raise ProjectError(f"素材軌 {kind} 要是清單")
        resolved[kind] = []
        for i, item in enumerate(items, 1):
            if not isinstance(item, dict):
                raise ProjectError(f"素材軌 {kind} 第 {i} 段要是 dict")
            label = "疊加素材" if kind == "overlays" else "音樂"
            resolved[kind].append(dict(item, path=_resolve(item.get("path"), base, f"{label}第 {i} 段", missing)))
    state = {
        "media": _resolve(media["file"], base, "主片", missing) if media.get("file") else "",
        "adjust": media.get("adjust") or {},
        "subtitles": _resolve(subtitles["file"], base, "字幕檔", missing) if subtitles.get("file") else "",
        "cues": subtitles.get("cues") or [],
        "tracks": resolved,
        "cuts": doc.get("cuts") or {},
        "seam": doc.get("seam") or DEFAULT_SEAM,
    }
    # 字幕檔找不到不要緊（內容在專案裡），只是存字幕時要另外選地方：照樣列出來
    return normalize_state(state), missing


def save(state, path) -> str:
    """存成專案檔（先寫暫存檔再換名）。回傳實際寫入的路徑（沒有副檔名時補上 .srtproj）。"""
    path = os.path.abspath(path)
    if not path.lower().endswith(SUFFIX):
        path += SUFFIX
    doc = to_document(state, path)
    data = json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
    folder = os.path.dirname(path)
    fd, temp = tempfile.mkstemp(prefix=".srtproj-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp, path)
    except BaseException:
        try:
            os.remove(temp)
        except OSError:
            pass
        raise
    return path


def load(path):
    """讀專案檔 → (專案狀態, 找不到的檔案)。讀不進來或內容不合理就拋 ProjectError。"""
    path = os.path.abspath(path)
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise ProjectError(f"打不開專案檔：{exc}") from None
    if size > MAX_BYTES:
        raise ProjectError(f"專案檔太大（{size // 1024 // 1024} MB），不像是本程式存的")
    try:
        with open(path, "rb") as fh:
            doc = json.loads(fh.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise ProjectError("這不是本程式的專案檔（讀不出內容）") from None
    return from_document(doc, path)
