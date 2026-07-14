# -*- coding: utf-8 -*-
"""
命令列批次模式（免開 GUI）。

沿用 config.json 中記憶的所有設定（轉寫、斷句、樣式、自動化輸出），
直接對一個或多個檔案跑完整自動流程：生成字幕 → 匯出 →（可選）燒錄。

使用範例：
    python main.py 影片1.mp4 影片2.mp4
    python main.py --mode align 演講.mp4          # 文字稿放在同名的 演講.txt
    python main.py --burn *.mp4                   # 匯出並燒錄硬字幕影片
    python main.py --formats srt,ass 影片.mp4     # 本次改匯出 SRT 與 ASS
    python main.py --output-dir D:/out 影片.mp4   # 本次改輸出到指定資料夾
    python main.py --review 素材1.mp4 素材2.mp4   # 批次審片：輸出片段分析 CSV
    python main.py --audiocheck 影片.mp4          # 上片前音訊健檢（免轉錄）
    python main.py --thumbnails 影片.mp4          # 封面候選圖（免轉錄）
    python main.py --audiofix 影片.mp4            # 音訊修復版（降噪等，免轉錄）
    python main.py --review --thumbnails 素材.mp4 # 審片＋精彩段落封面候選

命令列旗標僅影響本次執行，不會改寫 config.json 記憶的設定。
"""

from __future__ import annotations

import argparse
import os
import sys

from config import load_config
from subtitle.adbreaks import resolve_adbreak_settings, suggest_ad_breaks
from subtitle.audiocheck import format_report, run_audio_check
from subtitle.audiofix import (fix_audio, resolve_audiofix_settings,
                               suggest_output_path)
from subtitle.errors import format_error_text
from subtitle.ffmpeg_setup import ensure_ffmpeg_on_path
from subtitle.media import probe_duration
from subtitle.pipeline import EXPORT_FORMATS, run_batch, unique_path
from subtitle.publisher import build_publish_pack, resolve_publish_settings
from subtitle.thumbnails import (generate_thumbnails,
                                 resolve_thumbnail_settings)
from subtitle.review import (analyze, build_chapters, collect_highlights,
                             compute_loudness, export_batch_csv,
                             export_batch_html, export_csv,
                             export_html_report, resolve_settings)
from subtitle.transcriber import transcribe


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="SRT 字幕自動化批次工具：生成字幕 → 匯出 →（可選）燒錄，"
                    "設定沿用 config.json。",
    )
    parser.add_argument(
        "files", nargs="+", metavar="媒體檔",
        help="要處理的影片或音訊檔，可一次列出多個。")
    parser.add_argument(
        "--mode", choices=["transcribe", "align"], default="transcribe",
        help="transcribe＝模式一音訊轉錄（預設）；align＝模式二文字稿對齊"
             "（文字稿放在媒體檔旁的同名 .txt）。")
    parser.add_argument(
        "--formats", metavar="srt,vtt,ass,txt",
        help="本次要匯出的格式（逗號分隔）；未指定時沿用 config.json 的勾選。")
    parser.add_argument(
        "--burn", action="store_true",
        help="本次強制燒錄硬字幕影片（覆寫 config.json 設定）。")
    parser.add_argument(
        "--no-burn", action="store_true",
        help="本次強制不燒錄（覆寫 config.json 設定）。")
    parser.add_argument(
        "--loudnorm", action="store_true",
        help="本次燒錄時強制做響度正規化（目標值沿用 config.json，預設 -14 LUFS）。")
    parser.add_argument(
        "--no-loudnorm", action="store_true",
        help="本次強制不做響度正規化（覆寫 config.json 設定）。")
    parser.add_argument(
        "--output-dir", metavar="資料夾",
        help="本次輸出資料夾；未指定時沿用 config.json（留空＝來源資料夾）。")
    parser.add_argument(
        "--review", action="store_true",
        help="審片模式：不產字幕，改為分析素材（冷場、重複拍攝、口頭禪）"
             "並輸出「檔名_審片清單.csv」，供快速挑選可用片段。")
    parser.add_argument(
        "--audiocheck", action="store_true",
        help="音訊健檢：檢查爆音、音量、底噪與聲道平衡，"
             "輸出「檔名_音訊健檢.txt」報告；可單獨使用或與 --review 併用。")
    parser.add_argument(
        "--thumbnails", action="store_true",
        help="封面候選：自動挑清晰畫面輸出「檔名_封面NN.png」候選圖；"
             "與 --review 併用時優先取精彩段落，單獨使用時整片均勻取樣。")
    parser.add_argument(
        "--audiofix", action="store_true",
        help="音訊修復：依 config.json 的 audiofix 設定（降噪／去低頻／"
             "響度正規化）輸出「檔名_修復」版本，畫面原樣複製。")
    return parser


def _apply_overrides(config: dict, args: argparse.Namespace) -> None:
    """把命令列旗標套進本次使用的設定（不寫回 config.json）。"""
    automation = config["automation"]
    if args.formats is not None:
        wanted = {item.strip().lower().lstrip(".")
                  for item in args.formats.split(",") if item.strip()}
        known = {ext.lstrip(".") for ext in EXPORT_FORMATS}
        unknown = wanted - known
        if unknown:
            raise SystemExit(f"不支援的匯出格式：{', '.join(sorted(unknown))}"
                             f"（可用：{', '.join(sorted(known))}）")
        for ext in known:
            automation[f"export_{ext}"] = ext in wanted
    if args.burn:
        automation["burn_video"] = True
    if args.no_burn:
        automation["burn_video"] = False
    if args.loudnorm:
        automation["loudnorm"] = True
    if args.no_loudnorm:
        automation["loudnorm"] = False
    if args.output_dir is not None:
        automation["output_dir"] = args.output_dir


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    # 先前「自動安裝 ffmpeg」裝好的執行檔在此生效（不改動系統 PATH）。
    ensure_ffmpeg_on_path()
    config = load_config()
    _apply_overrides(config, args)

    def report(message, ratio=None):
        percent = f"{int(ratio * 100):3d}% " if ratio is not None else "     "
        print(f"{percent}{message}", flush=True)

    if args.review:
        results = _run_review_batch(
            args.files, config, report,
            with_audiocheck=args.audiocheck,
            with_thumbnails=args.thumbnails)
    elif args.audiocheck or args.thumbnails or args.audiofix:
        # 免轉錄的輕量工具模式：健檢、封面候選與音訊修復都只需 ffmpeg。
        results = _run_tools_batch(
            args.files, config, report,
            do_audiocheck=args.audiocheck,
            do_thumbnails=args.thumbnails,
            do_audiofix=args.audiofix)
    else:
        results = run_batch(
            args.files, config, mode=args.mode, report=report)

    # 總結報告。
    lines = []
    failed = 0
    for item in results:
        if item["ok"]:
            outputs = list(item["result"]["exports"])
            if item["result"]["burned"]:
                outputs.append(item["result"]["burned"])
            lines.append(f"✔ {item['path']}")
            lines.extend(f"    → {path}" for path in outputs)
        else:
            failed += 1
            lines.append(f"✘ {item['path']}")
            # 翻譯成「原因＋解法」，取代原始技術訊息。
            lines.extend(f"    {line}"
                         for line in format_error_text(
                             item["error"]).splitlines())
    total = len(results)
    summary = f"共 {total} 個檔案，成功 {total - failed}、失敗 {failed}。"

    print("\n===== 執行結果 =====")
    for line in lines:
        print(line)
    print(summary)

    # 打包成無 console 的 exe 時（例如把檔案拖到 exe 圖示上執行），
    # 文字輸出不可見，改以視窗回報結果。
    if getattr(sys, "frozen", False):
        _show_result_window(summary, lines, failed)
    return 1 if failed else 0


def _export_audiocheck(path: str, config: dict, out_dir: str,
                       base: str) -> str:
    """對單檔跑音訊健檢並輸出報告文字檔，回傳報告路徑。"""
    result = run_audio_check(path, config)
    text = format_report(result, os.path.basename(path))
    check_path = unique_path(os.path.join(out_dir, f"{base}_音訊健檢.txt"))
    with open(check_path, "w", encoding="utf-8") as fp:
        fp.write(text)
    print(text, flush=True)
    return check_path


def _export_thumbnails(path: str, items, duration: float, config: dict,
                       out_dir: str, base: str) -> list:
    """對單檔擷取封面候選圖，回傳輸出路徑清單。"""
    results = generate_thumbnails(
        path, items, duration,
        output_paths=lambda rank: unique_path(
            os.path.join(out_dir, f"{base}_封面{rank:02d}.png")),
        settings=resolve_thumbnail_settings(config))
    return [item["path"] for item in results]


def _run_tools_batch(files: list, config: dict, report,
                     do_audiocheck: bool = False,
                     do_thumbnails: bool = False,
                     do_audiofix: bool = False) -> list:
    """輕量工具批次（免轉錄）：音訊健檢與封面候選，回傳與 run_batch 同構的結果。"""
    automation = config.get("automation", {})
    results = []
    total = len(files)
    for index, path in enumerate(files):
        prefix = (f"[{index + 1}/{total}] {os.path.basename(path)}："
                  if total > 1 else "")
        try:
            if not os.path.exists(path):
                raise FileNotFoundError(f"找不到檔案：{path}")
            out_dir = (automation.get("output_dir") or "").strip() \
                or os.path.dirname(os.path.abspath(path))
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(path))[0]
            exports = []
            if do_audiocheck:
                report(f"{prefix}音訊健檢中...")
                exports.append(_export_audiocheck(path, config, out_dir, base))
            if do_thumbnails:
                report(f"{prefix}擷取封面候選中（整片均勻取樣）...")
                exports.extend(_export_thumbnails(
                    path, None, probe_duration(path), config, out_dir, base))
            if do_audiofix:
                report(f"{prefix}輸出音訊修復版中...")
                fix_out = unique_path(os.path.join(
                    out_dir, os.path.basename(suggest_output_path(path))))
                fix_audio(path, fix_out,
                          settings=resolve_audiofix_settings(config))
                exports.append(fix_out)
            report(f"{prefix}完成", (index + 1) / total)
            results.append({
                "path": path, "ok": True, "error": None,
                "result": {"exports": exports, "burned": None, "cues": []},
            })
        except Exception as exc:  # 單檔失敗不中斷批次。
            results.append(
                {"path": path, "ok": False, "result": None, "error": str(exc)})
            report(f"{prefix}失敗：{exc}", (index + 1) / total)
    return results


def _run_review_batch(files: list, config: dict, report,
                      with_audiocheck: bool = False,
                      with_thumbnails: bool = False) -> list:
    """審片模式批次：逐檔轉錄、分析並輸出審片清單 CSV，回傳與 run_batch 同構的結果。"""
    automation = config.get("automation", {})
    settings = resolve_settings(config)
    results = []
    analyzed = []   # (素材名稱, items)——多檔時輸出跨檔彙總用
    last_out_dir = None
    total = len(files)
    for index, path in enumerate(files):
        prefix = f"[{index + 1}/{total}] {os.path.basename(path)}：" if total > 1 else ""
        try:
            if not os.path.exists(path):
                raise FileNotFoundError(f"找不到檔案：{path}")
            report(f"{prefix}轉錄並分析中...", index / total if total > 1 else None)
            words = transcribe(path, config)
            duration = probe_duration(path)
            items = analyze(
                words, media_duration=duration,
                loudness=compute_loudness(
                    path, voice_band=settings["voice_band"]),
                settings=settings)
            out_dir = (automation.get("output_dir") or "").strip() \
                or os.path.dirname(os.path.abspath(path))
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(path))[0]
            csv_path = unique_path(os.path.join(out_dir, f"{base}_審片清單.csv"))
            export_csv(items, csv_path)
            chapters = build_chapters(
                items,
                min_chapter_seconds=settings["chapter_min_seconds"],
                break_gap=settings["silence_gap"])
            html_path = unique_path(os.path.join(out_dir, f"{base}_審片報告.html"))
            export_html_report(items, html_path, source_name=os.path.basename(path),
                               media_duration=duration, chapters=chapters)
            # 發佈包：建議標題＋描述草稿＋標籤，上傳時直接取用。
            pack_path = unique_path(os.path.join(out_dir, f"{base}_發佈包.txt"))
            with open(pack_path, "w", encoding="utf-8") as fp:
                fp.write(build_publish_pack(
                    items, settings=resolve_publish_settings(config),
                    chapters=chapters, source_name=os.path.basename(path),
                    extra_words=settings["extra_excite_words"],
                    ad_breaks=suggest_ad_breaks(
                        items, duration,
                        settings=resolve_adbreak_settings(config))))
            exports = [csv_path, html_path, pack_path]
            if with_audiocheck:
                report(f"{prefix}音訊健檢中...")
                exports.append(_export_audiocheck(path, config, out_dir, base))
            if with_thumbnails:
                report(f"{prefix}擷取封面候選中（優先精彩段落）...")
                exports.extend(_export_thumbnails(
                    path, items, duration, config, out_dir, base))
            dropped = sum(1 for item in items if not item["keep"])
            report(f"{prefix}分析完成，共 {len(items)} 段（建議捨棄 {dropped} 段）",
                   (index + 1) / total)
            analyzed.append((os.path.basename(path), items))
            last_out_dir = out_dir
            results.append({
                "path": path, "ok": True, "error": None,
                "result": {"exports": exports, "burned": None, "cues": []},
            })
        except Exception as exc:  # 單檔失敗不中斷批次。
            results.append(
                {"path": path, "ok": False, "result": None, "error": str(exc)})
            report(f"{prefix}失敗：{exc}", (index + 1) / total)

    # 多檔審片時另輸出跨檔彙總：整批素材的精彩片段 Top N 一目瞭然。
    if len(analyzed) >= 2 and last_out_dir:
        try:
            top_n = settings["batch_top_n"]
            summary_csv = unique_path(
                os.path.join(last_out_dir, "審片彙總_精彩TopN.csv"))
            export_batch_csv(collect_highlights(analyzed, top_n), summary_csv)
            summary_html = unique_path(
                os.path.join(last_out_dir, "審片彙總.html"))
            export_batch_html(analyzed, summary_html, top_n)
            report(f"已輸出跨檔彙總（{len(analyzed)} 支素材、"
                   f"精彩片段前 {top_n} 段）：{summary_html}")
            for item in results:
                if item["ok"]:
                    item["result"]["exports"].extend(
                        [summary_csv, summary_html])
                    break
        except OSError as exc:
            report(f"跨檔彙總輸出失敗（不影響個別報告）：{exc}")
    return results


def _show_result_window(summary: str, lines: list, failed: int) -> None:
    """以訊息視窗顯示批次結果（無 console 環境用）；失敗時不中斷流程。"""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        show = messagebox.showwarning if failed else messagebox.showinfo
        show("批次處理結果", summary + "\n\n" + "\n".join(lines))
        root.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
