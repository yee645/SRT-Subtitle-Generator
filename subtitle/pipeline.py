# -*- coding: utf-8 -*-
"""
一鍵自動化流程模組（pipeline）。

把「字幕生成 → 檔案匯出 → 影片燒錄」串成一條免對話框的自動流程：

- 輸出檔以來源檔名自動命名（``影片.mp4`` → ``影片.srt``、``影片_subtitled.mp4``），
  已存在同名檔時自動改為 ``影片 (1).srt``，不覆蓋舊檔。
- 要匯出哪些格式、是否燒錄、輸出到哪個資料夾，皆由 config 的 ``automation``
  區段決定，GUI 與 CLI 共用同一套邏輯。
- 支援批次：多個檔案依序以相同設定跑完整條流程。

本模組不依賴任何 GUI 元件，可供 gui/app.py 與 cli.py 共同使用。
"""

from __future__ import annotations

import os
from typing import Callable, Iterable, Optional

from .aligner import align_transcript
from .burner import burn_subtitles
from .exporter import export
from .segmenter import build_cues_from_words
from .transcriber import transcribe

# report(message, ratio)；ratio 為 0.0~1.0 或 None（表示無法估算）。
ReportCallback = Callable[[str, Optional[float]], None]

# 自動匯出支援的格式（與 automation 設定的 export_* 欄位對應）。
EXPORT_FORMATS = (".srt", ".vtt", ".ass", ".txt")


def unique_path(path: str) -> str:
    """回傳不與現有檔案衝突的路徑；同名時在檔名後加上 (1)、(2)…流水號。"""
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    counter = 1
    while True:
        candidate = f"{root} ({counter}){ext}"
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def resolve_output_dir(media_path: str, automation_cfg: dict) -> str:
    """決定輸出資料夾：automation 設定有值就用它，留空則用來源檔所在資料夾。"""
    configured = (automation_cfg.get("output_dir") or "").strip()
    if configured:
        return configured
    return os.path.dirname(os.path.abspath(media_path))


def enabled_export_formats(automation_cfg: dict) -> list:
    """從 automation 設定取出勾選的匯出格式清單（如 ['.srt', '.ass']）。"""
    return [
        ext for ext in EXPORT_FORMATS
        if automation_cfg.get(f"export_{ext.lstrip('.')}")
    ]


def find_sidecar_transcript(media_path: str) -> Optional[str]:
    """
    尋找與媒體檔同名的文字稿（sidecar）檔。

    批次跑「模式二：文字稿對齊」時，每部影片的文字稿放在旁邊同名的
    ``影片.txt`` 即可自動帶入，不必逐一貼上。找不到時回傳 None。
    """
    root = os.path.splitext(media_path)[0]
    candidate = root + ".txt"
    if os.path.isfile(candidate):
        return candidate
    return None


def _sub_report(report: Optional[ReportCallback], low: float,
                high: float) -> Optional[ReportCallback]:
    """把子階段回報的 0~1 進度重新映射到整體進度的 [low, high] 區間。"""
    if not report:
        return None

    def wrapped(message, ratio=None):
        if ratio is None:
            report(message, None)
        else:
            span = high - low
            report(message, low + max(0.0, min(float(ratio), 1.0)) * span)

    return wrapped


def run_pipeline(
    media_path: str,
    config: dict,
    mode: str = "transcribe",
    transcript: str = "",
    report: Optional[ReportCallback] = None,
) -> dict:
    """
    對單一媒體檔執行完整自動流程：生成字幕 → 匯出檔案 →（可選）燒錄影片。

    參數：
        media_path: 影片或音訊檔路徑。
        config: 完整設定 dict（含 segmentation / transcription / automation）。
        mode: "transcribe"（模式一）或 "align"（模式二）。
        transcript: 模式二使用的文字稿；留空時自動尋找同名 .txt sidecar 檔。
        report: (message, ratio) 進度回呼。
    回傳：
        {"cues": cue 清單, "exports": [匯出的檔案路徑], "burned": 燒錄輸出路徑或 None}
    """
    if not os.path.exists(media_path):
        raise FileNotFoundError(f"找不到檔案：{media_path}")

    automation = config.get("automation", {})
    formats = enabled_export_formats(automation)
    burn = bool(automation.get("burn_video"))
    if not formats and not burn:
        raise ValueError("自動化輸出未勾選任何項目（匯出格式或燒錄影片）。")

    # 進度區間分配：燒錄通常最耗時，有燒錄時生成占前半、燒錄占後半。
    generate_high = 0.5 if burn else 0.93

    if mode == "align":
        if not transcript.strip():
            sidecar = find_sidecar_transcript(media_path)
            if not sidecar:
                raise ValueError(
                    f"模式二需要文字稿：請貼上文字稿，或在媒體檔旁放置同名的"
                    f"「{os.path.splitext(os.path.basename(media_path))[0]}.txt」。")
            with open(sidecar, "r", encoding="utf-8") as fp:
                transcript = fp.read()
        cues = align_transcript(
            media_path, transcript, config,
            _sub_report(report, 0.0, generate_high))
    else:
        words = transcribe(
            media_path, config, _sub_report(report, 0.0, generate_high))
        if report:
            report("正在進行智慧斷句...", generate_high)
        cues = build_cues_from_words(words, config.get("segmentation", {}))

    if not cues:
        raise RuntimeError("未能產生任何字幕內容。")

    # 匯出勾選的字幕格式。
    out_dir = resolve_output_dir(media_path, automation)
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(media_path))[0]
    style = config.get("subtitle_style", {})
    exports = []
    for ext in formats:
        target = unique_path(os.path.join(out_dir, base + ext))
        export(cues, target, style=style)
        exports.append(target)
        if report:
            report(f"已匯出 {os.path.basename(target)}", generate_high + 0.02)

    # 燒錄硬字幕影片。
    burned = None
    if burn:
        burned = unique_path(os.path.join(out_dir, f"{base}_subtitled.mp4"))
        burn_subtitles(
            video_path=media_path,
            cues=cues,
            output_path=burned,
            style=style,
            progress_cb=_burn_report(_sub_report(report, 0.55, 1.0)),
        )

    if report:
        report("自動流程完成。", 1.0)
    return {"cues": cues, "exports": exports, "burned": burned}


def _burn_report(report: Optional[ReportCallback]):
    """把 burner 的 (ratio, message) 回呼轉成 pipeline 的 (message, ratio) 順序。"""
    if not report:
        return None

    def wrapped(ratio, message):
        report(message, ratio)

    return wrapped


def run_batch(
    media_paths: Iterable[str],
    config: dict,
    mode: str = "transcribe",
    transcript: str = "",
    report: Optional[ReportCallback] = None,
) -> list:
    """
    批次執行自動流程：多個檔案依序以相同設定跑 run_pipeline。

    單一檔案失敗不會中斷整批，失敗原因記錄在該檔的結果中。
    模式二批次時，文字稿一律改由各檔案的同名 .txt sidecar 提供
    （只有單一檔案時才使用傳入的 transcript）。

    回傳：每個檔案一筆結果 dict：
        {"path": 檔案路徑, "ok": bool, "result": run_pipeline 回傳值或 None,
         "error": 錯誤訊息或 None}
    """
    paths = [p for p in media_paths if p]
    total = len(paths)
    results = []
    for index, path in enumerate(paths):
        name = os.path.basename(path)
        prefix = f"[{index + 1}/{total}] {name}：" if total > 1 else ""

        def file_report(message, ratio=None,
                        _prefix=prefix, _index=index):
            if report:
                overall = None
                if ratio is not None:
                    overall = (_index + max(0.0, min(float(ratio), 1.0))) / total
                report(f"{_prefix}{message}", overall)

        # 批次（多檔）時各檔用自己的 sidecar 文字稿，避免同一份文字稿套到每部影片。
        file_transcript = transcript if total == 1 else ""
        try:
            result = run_pipeline(
                path, config, mode=mode, transcript=file_transcript,
                report=file_report)
            results.append(
                {"path": path, "ok": True, "result": result, "error": None})
        except Exception as exc:  # 單檔失敗不中斷批次，收集錯誤後繼續。
            results.append(
                {"path": path, "ok": False, "result": None, "error": str(exc)})
            file_report(f"失敗：{exc}", 1.0)
    return results
