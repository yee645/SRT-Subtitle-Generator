# -*- coding: utf-8 -*-
"""
轉錄結果快取模組。

語音辨識是整條流程中最耗時、最耗資源的步驟。同一個檔案在
「一鍵完成 → 審片助手」「調整斷句後重新生成」等情境會被轉錄多次，
內容其實完全相同。本模組把逐字時間軸結果以 JSON 存到程式資料夾的
``transcribe_cache/``，下次遇到同一檔案（路徑＋大小＋修改時間一致）
且轉寫設定相同時直接重用，省下整段辨識時間與 CPU。

快取鍵包含：檔案路徑、大小、修改時間、引擎（本地/API）、模型、
語言、提示詞——任一項變動都會重新辨識，不會拿到過期結果。
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Optional

# 快取資料夾：與 config.json 同層（程式工作目錄）。
CACHE_DIR = "transcribe_cache"
# 快取檔數量上限：超過時刪除最舊的，避免無限成長占用磁碟。
MAX_CACHE_FILES = 40


def make_key(audio_path: str, transcription_cfg: dict,
             initial_prompt: str = "") -> str:
    """組出快取鍵（sha1）。檔案不存在時拋出 OSError 由呼叫端處理。"""
    stat = os.stat(audio_path)
    payload = json.dumps({
        "path": os.path.abspath(audio_path),
        "size": stat.st_size,
        "mtime": int(stat.st_mtime),
        "use_api": bool(transcription_cfg.get("use_api")),
        "model": transcription_cfg.get("model", ""),
        "language": transcription_cfg.get("language", ""),
        "prompt": (transcription_cfg.get("prompt") or "").strip(),
        "initial_prompt": (initial_prompt or "").strip(),
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.json")


def load_cached_words(key: str) -> Optional[list]:
    """讀取快取的逐字時間軸；不存在或損毀時回傳 None（重新辨識）。"""
    path = _cache_path(key)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fp:
            words = json.load(fp)
        if (isinstance(words, list) and words
                and all(isinstance(w, dict) and "word" in w for w in words)):
            return words
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return None


def save_cached_words(key: str, words: list) -> None:
    """寫入快取；任何 I/O 失敗都靜默略過，不影響主流程。"""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(key), "w", encoding="utf-8") as fp:
            json.dump(words, fp, ensure_ascii=False)
        _prune_cache()
    except OSError:
        pass


def _prune_cache() -> None:
    """超過上限時刪除最舊的快取檔。"""
    try:
        entries = [os.path.join(CACHE_DIR, name)
                   for name in os.listdir(CACHE_DIR) if name.endswith(".json")]
        if len(entries) <= MAX_CACHE_FILES:
            return
        entries.sort(key=os.path.getmtime)
        for path in entries[:len(entries) - MAX_CACHE_FILES]:
            os.unlink(path)
    except OSError:
        pass


def clear_cache() -> int:
    """清空全部快取，回傳刪除的檔案數。"""
    removed = 0
    try:
        for name in os.listdir(CACHE_DIR):
            if name.endswith(".json"):
                os.unlink(os.path.join(CACHE_DIR, name))
                removed += 1
    except OSError:
        pass
    return removed
