# -*- coding: utf-8 -*-
"""
世代鏈（generations）：記錄「這個檔案是從哪個檔案生出來的」。

`docs/UI_AUDIT_2.0.md` ④ 點名的斷鏈問題，最具體的症狀長這樣——健檢中心
修完音訊會說「修復版已輸出：D:\\片_修復.mp4」，訊息裡甚至寫著「也可對輸
出版再跑一次健檢比對」，但介面沒有給任何做得到這件事的路徑：使用者得自
己記住路徑、回主視窗重選檔案。粗剪、精彩合輯、燒錄版也都是同一個死路。

這個模組管的是那條被切斷的線：每次產生新檔案就記一筆「新檔 ← 來源檔」，
於是隨時問得出「我現在手上這支是怎麼來的」。它只是資料與規則，完全不碰
GUI，CLI 也能拿去印產出譜系。

**刻意不做持久化**：世代鏈裡全是絕對路徑，存進 config.json 後使用者搬動
或刪除檔案就會留下一串指向空氣的紀錄，比沒有更糟。這是一次工作階段內的
記憶，關掉程式就忘掉。
"""

from __future__ import annotations

import os
from typing import List, Optional

# 世代種類 → 顯示名稱。key 是程式用的代號，value 是介面上給人看的字。
KIND_ORIGINAL = "original"
KIND_LABELS = {
    KIND_ORIGINAL: "原始素材",
    "roughcut": "粗剪",
    "highlight": "精彩合輯",
    "shorts": "直式短片",
    "audiofix": "修復版",
    "trimmed": "修剪版",
    "burned": "燒錄版",
}

# lineage() 往回追的上限。正常的鏈頂多四、五代，這個數字純粹是防呆：
# 萬一哪天有人記出一個環（A 的來源是 B、B 的來源是 A），不能讓它轉不停。
MAX_DEPTH = 32


def kind_label(kind: str) -> str:
    """世代種類的顯示名稱；不認得的代號原樣回傳，不要讓介面變成空白。"""
    return KIND_LABELS.get(kind, kind or "")


def new_chain() -> list:
    """建立一條空的世代鏈。"""
    return []


def _norm(path: str) -> str:
    """統一路徑寫法，讓同一個檔案不會因為大小寫或斜線方向被記成兩筆。"""
    return os.path.normcase(os.path.normpath(os.path.abspath(path or "")))


def find(chain: list, path: str) -> Optional[dict]:
    """找出某個路徑在鏈上的那一筆；沒有就回 None。"""
    if not path:
        return None
    key = _norm(path)
    for entry in chain:
        if _norm(entry["path"]) == key:
            return entry
    return None


def record(chain: list, path: str, kind: str,
           source: Optional[str] = None) -> dict:
    """
    記一筆「``path`` 是由 ``source`` 產生的 ``kind`` 版本」，回傳該筆。

    就地修改 ``chain``。同一個路徑重複記錄時**更新而非新增**，避免同一支
    檔案在鏈上出現兩次（例如同一個輸出被覆蓋重做）。

    ``source`` 沒有給、或指的就是自己時視為源頭。來源不在鏈上時會自動補一
    筆原始素材——實務上使用者常常是先開了審片助手才第一次產出東西，此時
    來源檔根本還沒被記過，少了這個自動補登就會斷在第一節。
    """
    if not path:
        raise ValueError("path 不可為空")

    source_entry = None
    if source and _norm(source) != _norm(path):
        source_entry = find(chain, source)
        if source_entry is None:
            source_entry = {"path": source, "kind": KIND_ORIGINAL,
                            "source": None}
            chain.append(source_entry)

    entry = find(chain, path)
    if entry is None:
        entry = {"path": path, "kind": kind,
                 "source": source_entry["path"] if source_entry else None}
        chain.append(entry)
    else:
        entry["kind"] = kind
        entry["source"] = source_entry["path"] if source_entry else None
    return entry


def lineage(chain: list, path: str) -> List[dict]:
    """
    回傳從源頭到 ``path`` 的整條譜系（由舊到新）。

    ``path`` 不在鏈上時回傳一筆臨時的原始素材——使用者選了一個與任何產出
    都無關的檔案時，答案就是「它自己是源頭」，而不是一片空白。
    """
    entry = find(chain, path)
    if entry is None:
        if not path:
            return []
        return [{"path": path, "kind": KIND_ORIGINAL, "source": None}]

    trail = [entry]
    seen = {_norm(entry["path"])}
    for _ in range(MAX_DEPTH):
        source = trail[0].get("source")
        if not source:
            break
        key = _norm(source)
        if key in seen:  # 環：停在這裡，不要轉不停
            break
        parent = find(chain, source)
        if parent is None:
            break
        trail.insert(0, parent)
        seen.add(key)
    return trail


def describe_lineage(chain: list, path: str) -> str:
    """
    把譜系寫成一行給人看的字，例如
    ``原始素材 訪談.mp4 → 粗剪 → 修復版（目前）``。

    只有源頭寫出檔名，中間各代只寫種類——整條鏈的檔名多半只差一個後綴，
    全寫出來會又長又難讀，而使用者想知道的是「經過哪些處理」。
    """
    trail = lineage(chain, path)
    if not trail:
        return ""
    parts = [f"{kind_label(trail[0]['kind'])} {os.path.basename(trail[0]['path'])}"]
    parts.extend(kind_label(item["kind"]) for item in trail[1:])
    if len(parts) == 1:
        return parts[0]
    return " → ".join(parts) + "（目前）"


def descendants(chain: list, path: str) -> List[dict]:
    """列出直接由 ``path`` 產生的下一代（不遞迴）。"""
    if not path:
        return []
    key = _norm(path)
    return [entry for entry in chain
            if entry.get("source") and _norm(entry["source"]) == key]
