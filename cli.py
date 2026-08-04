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
    python main.py --branding 影片.mp4          # 套用已設定的片頭/片尾/浮水印
    python main.py --review --thumbnails 素材.mp4 # 審片＋精彩段落封面候選
    python main.py --subs 影片.srt --burn 影片.mp4   # 既有字幕直接燒錄（免轉錄）
    python main.py --subcheck 影片.mp4            # 字幕健檢（閱讀速度/行數/時間軸重疊，可與其他模式併用）
    python main.py --jumpcut 影片.mp4             # 自動跳剪：剪掉句間停頓，字幕同步對齊
    python main.py --retakes 影片.mp4             # 重複片段偵測：輸出候選清單（不自動剪）
    python main.py --retakes --retakes-cut 影片.mp4  # 偵測後直接剪掉全部候選重複片段
    python main.py --volumecheck 影片.mp4         # 分段音量一致性分析（免轉錄）
    python main.py --volumefix 影片.mp4           # 一鍵拉平音量落差過大的段落（免轉錄）
    python main.py --audiovis 節目.mp3            # 音訊轉波形／頻譜視覺化影片
    python main.py --colorcheck 影片.mp4          # 畫面曝光與色偏健檢（免轉錄）
    python main.py --adcheck 影片.mp4             # 廣告友善度自查（黃標風險預檢）
    python main.py --subs 舊字幕.srt --synccheck 影片.mp4  # 字幕與語音同步檢查

命令列旗標僅影響本次執行，不會改寫 config.json 記憶的設定。
"""

from __future__ import annotations

import argparse
import os
import sys

from config import load_config
from subtitle.adbreaks import resolve_adbreak_settings, suggest_ad_breaks
from subtitle.adfriendly import (format_adfriendly_report,
                                 resolve_adfriendly_settings, scan_cues)
from subtitle.audiocheck import format_report, run_audio_check
from subtitle.audiofix import (fix_audio, resolve_audiofix_settings,
                               suggest_output_path)
from subtitle.audiovis import (render_audio_video, resolve_audiovis_settings,
                               suggest_output_path as
                               suggest_audiovis_output_path)
from subtitle.branding import (apply_branding, resolve_branding_settings,
                               suggest_output_path as
                               suggest_branding_output_path)
from subtitle.colorcheck import (analyze_color, format_color_report,
                                 resolve_colorcheck_settings)
from subtitle.errors import format_error_text
from subtitle.exporter import export
from subtitle.ffmpeg_setup import ensure_ffmpeg_on_path
from subtitle.importer import load_subtitle_file
from subtitle.jumpcut import (apply_jumpcut, format_jumpcut_report,
                              resolve_jumpcut_settings, suggest_output_path
                              as suggest_jumpcut_output_path)
from subtitle.retakes import (apply_retake_removal, find_retakes,
                              format_retake_removal_report,
                              format_retakes_report, resolve_retake_settings,
                              suggest_output_path as
                              suggest_retakes_output_path)
from subtitle.media import probe_duration
from subtitle.pipeline import (EXPORT_FORMATS, enabled_export_formats,
                               export_and_burn, run_batch, unique_path)
from subtitle.publisher import build_publish_pack, resolve_publish_settings
from subtitle.seriescheck import (analyze_series, format_series_report,
                                  resolve_seriescheck_settings)
from subtitle.subsync import (analyze_sync, apply_sync_correction,
                              format_sync_report, resolve_subsync_settings)
from subtitle.subtitlecheck import (analyze_cues, format_subtitle_report,
                                    resolve_subcheck_settings)
from subtitle.videocheck import (format_video_report, run_video_check)
from subtitle.volumeconsistency import (analyze_volume_consistency,
                                        fix_volume_consistency,
                                        format_volume_consistency_report,
                                        resolve_volume_consistency_settings,
                                        suggest_output_path as
                                        suggest_volume_output_path)
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
        "--videocheck", action="store_true",
        help="影片畫質健檢：位元率／解析度／更新率／編碼對照 YouTube 建議，"
             "並偵測頭尾廢秒，附加於健檢報告；可與 --audiocheck 併用。")
    parser.add_argument(
        "--audiofix", action="store_true",
        help="音訊修復：依 config.json 的 audiofix 設定（降噪／去低頻／"
             "響度正規化）輸出「檔名_修復」版本，畫面原樣複製。")
    parser.add_argument(
        "--branding", action="store_true",
        help="品牌套版：套用 config.json 已設定的片頭／片尾／浮水印，"
             "輸出「檔名_套版」版本；未設定任何一項時單檔略過並提示。")
    parser.add_argument(
        "--volumecheck", action="store_true",
        help="分段音量一致性分析：把影片切成固定長度分段逐段量測響度，"
             "找出與整體中位數落差過大（忽大忽小）的段落，輸出"
             "「檔名_音量一致性.txt」報告；可與 --audiocheck 併用。")
    parser.add_argument(
        "--volumefix", action="store_true",
        help="一鍵拉平音量：對音量落差過大的段落套用增益調整到接近整體"
             "中位數響度，其餘段落不動，輸出「檔名_音量平衡」版本"
             "（畫面原樣複製，僅音軌重新編碼）；沒有偵測到落差時單檔"
             "略過並提示。")
    parser.add_argument(
        "--colorcheck", action="store_true",
        help="畫面曝光與色偏健檢：全片均勻取樣，偵測曝光不足／過曝與明顯"
             "色偏（白平衡問題），輸出「檔名_色彩健檢.txt」報告（僅列出"
             "建議，不自動校色）；可與 --audiocheck／--videocheck 併用。")
    parser.add_argument(
        "--audiovis", action="store_true",
        help="音訊轉視覺化影片：把純音訊檔（podcast／錄音訪談等）轉成附"
             "波形或頻譜視覺化的 mp4，輸出「檔名_視覺化影片.mp4」；樣式"
             "（波形/頻譜、顏色、解析度、背景圖）依 config.json 的 "
             "audiovis 設定。輸出檔可直接當作來源接上轉錄／字幕燒錄等"
             "既有流程。")
    parser.add_argument(
        "--subs", metavar="字幕檔",
        help="使用既有字幕檔（.srt/.vtt）跳過語音辨識：搭配一個媒體檔，"
             "依自動化輸出設定匯出其他格式並可 --burn 燒錄硬字幕。")
    parser.add_argument(
        "--subcheck", action="store_true",
        help="字幕健檢：檢查產生（或 --subs 匯入）的字幕閱讀速度（CPS）、"
             "顯示時間、行數與時間軸重疊，輸出「檔名_字幕健檢.txt」報告"
             "（僅列出問題，修復請於 GUI 字幕健檢對話框操作）；可與一般"
             "轉錄／對齊模式或 --subs 併用（--review 等不產生字幕的"
             "模式無效果）。")
    parser.add_argument(
        "--seriescheck", action="store_true",
        help="系列一致性檢查：比對一次給定的多支影片「彼此之間」的響度、"
             "解析度、更新率、編碼與畫面亮度／色調是否一致（以整批中位數"
             "為基準，抓出偏離整批的那幾支），輸出「系列一致性檢查.txt」。"
             "與單支影片是否合格的健檢（--audiocheck 等）是不同的問題；"
             "需一次給至少 2 個檔案。")
    parser.add_argument(
        "--synccheck", action="store_true",
        help="字幕與語音同步檢查：掃出素材實際語音區間，檢查字幕是否對得上，"
             "並自動算出建議的線性校正（同時涵蓋整體偏移與幀率漂移），"
             "輸出「檔名_同步檢查.txt」。特別適合搭配 --subs 匯入的既有"
             "字幕檔使用。")
    parser.add_argument(
        "--syncfix", action="store_true",
        help="搭配 --synccheck 使用：偵測到不同步時直接套用建議校正，另存"
             "「檔名_同步校正.ext」字幕（只調整時間軸、不改動文字內容，"
             "原始字幕檔不受影響）；判定為同步正常或無法可靠判定時略過。")
    parser.add_argument(
        "--adcheck", action="store_true",
        help="廣告友善度自查（黃標風險預檢）：掃描產生（或 --subs 匯入）的"
             "字幕，找出可能觸發 YouTube 廣告友善度審查的用詞，並以時間窗"
             "叢集分析標出「短時間內風險詞密集」的高風險段落，輸出"
             "「檔名_廣告友善度.txt」；詞表可於 config.json 的 adfriendly "
             "增補（extra_terms）與排除誤判（ignore_terms）。僅供自查，"
             "不自動改動內容。可與一般轉錄／對齊模式或 --subs 併用。")
    parser.add_argument(
        "--jumpcut", action="store_true",
        help="自動跳剪：依產生（或 --subs 匯入）的字幕找出句間過長停頓，"
             "一次剪掉整支影片的停頓並輸出「檔名_跳剪.mp4」，同步匯出"
             "時間軸已對齊的字幕「檔名_跳剪.ext」；門檻依 config.json 的"
             "jumpcut 設定。可與一般轉錄／對齊模式或 --subs 併用"
             "（--review 等不產生字幕的模式無效果）；注意 --burn 燒錄的"
             "仍是原始（未跳剪）影片，兩者不會自動串接。")
    parser.add_argument(
        "--retakes", action="store_true",
        help="重複片段偵測：找出同一時間窗內文字高度相似的句子（同一句話"
             "講了好幾次），輸出候選清單「檔名_重複片段.txt」；預設只列出"
             "候選、不自動剪（假陽性風險比跳剪高，例如刻意重複的口號）。"
             "可與一般轉錄／對齊模式或 --subs 併用。")
    parser.add_argument(
        "--retakes-cut", action="store_true",
        help="搭配 --retakes 使用：偵測後直接剪掉全部候選重複片段（只保留"
             "每組最後一次），輸出「檔名_去重複.mp4」＋同步對齊的字幕；"
             "命令列無法逐項確認，請先用 --retakes 看過候選清單再決定是否"
             "加上此旗標。")
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

    if args.seriescheck:
        # 系列一致性是「整批比一批」，產出單一份跨檔報告，
        # 與其他逐檔處理的模式結構不同，因此獨立成一個分支。
        results = _run_seriescheck(args.files, config, report)
    elif args.subs:
        if len(args.files) != 1:
            raise SystemExit(
                "--subs 需搭配「剛好一個」媒體檔（跳過語音辨識，"
                "直接用既有字幕匯出／燒錄），目前給了 "
                f"{len(args.files)} 個檔案。")
        results = _run_subs_batch(args.files[0], args.subs, config, report)
    elif args.review:
        results = _run_review_batch(
            args.files, config, report,
            with_audiocheck=args.audiocheck,
            with_thumbnails=args.thumbnails)
    elif (args.audiocheck or args.thumbnails or args.audiofix
            or args.branding or args.videocheck or args.volumecheck
            or args.volumefix or args.audiovis or args.colorcheck):
        # 免轉錄的輕量工具模式：健檢、封面候選、音訊修復與品牌套版都只需 ffmpeg。
        results = _run_tools_batch(
            args.files, config, report,
            do_audiocheck=args.audiocheck,
            do_thumbnails=args.thumbnails,
            do_audiofix=args.audiofix,
            do_branding=args.branding,
            do_videocheck=args.videocheck,
            do_volumecheck=args.volumecheck,
            do_volumefix=args.volumefix,
            do_audiovis=args.audiovis,
            do_colorcheck=args.colorcheck)
    else:
        results = run_batch(
            args.files, config, mode=args.mode, report=report)

    if args.jumpcut:
        automation = config.get("automation", {})
        out_dir_override = (automation.get("output_dir") or "").strip()
        formats = enabled_export_formats(automation)
        for item in results:
            cues = (item.get("result") or {}).get("cues") if item["ok"] else None
            if not cues:
                continue
            out_dir = out_dir_override or os.path.dirname(
                os.path.abspath(item["path"]))
            os.makedirs(out_dir, exist_ok=True)
            try:
                new_paths = _export_jumpcut(
                    item["path"], cues, config, out_dir, formats, report)
            except (RuntimeError, ValueError, FileNotFoundError) as exc:
                report(f"{os.path.basename(item['path'])}：跳剪略過（{exc}）")
                continue
            item["result"]["exports"].extend(new_paths)

    if args.retakes:
        automation = config.get("automation", {})
        out_dir_override = (automation.get("output_dir") or "").strip()
        formats = enabled_export_formats(automation)
        retake_settings = resolve_retake_settings(config)
        for item in results:
            cues = (item.get("result") or {}).get("cues") if item["ok"] else None
            if not cues:
                continue
            out_dir = out_dir_override or os.path.dirname(
                os.path.abspath(item["path"]))
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(item["path"]))[0]
            found = find_retakes(cues, retake_settings)
            report_text = format_retakes_report(found)
            report_path = unique_path(
                os.path.join(out_dir, f"{base}_重複片段.txt"))
            with open(report_path, "w", encoding="utf-8") as fp:
                fp.write(report_text)
            print(report_text, flush=True)
            item["result"]["exports"].append(report_path)
            if found and args.retakes_cut:
                try:
                    new_paths = _export_retakes(
                        item["path"], cues, found, config, out_dir, formats,
                        report)
                except (RuntimeError, ValueError, FileNotFoundError) as exc:
                    report(f"{os.path.basename(item['path'])}："
                          f"去重複略過（{exc}）")
                    continue
                item["result"]["exports"].extend(new_paths)

    if args.subcheck:
        automation = config.get("automation", {})
        out_dir_override = (automation.get("output_dir") or "").strip()
        for item in results:
            cues = (item.get("result") or {}).get("cues") if item["ok"] else None
            if not cues:
                continue
            out_dir = out_dir_override or os.path.dirname(
                os.path.abspath(item["path"]))
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(item["path"]))[0]
            check_path = _export_subcheck(cues, config, out_dir, base)
            item["result"]["exports"].append(check_path)

    if args.synccheck:
        automation = config.get("automation", {})
        out_dir_override = (automation.get("output_dir") or "").strip()
        formats = enabled_export_formats(automation)
        for item in results:
            cues = (item.get("result") or {}).get("cues") if item["ok"] else None
            if not cues:
                continue
            out_dir = out_dir_override or os.path.dirname(
                os.path.abspath(item["path"]))
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(item["path"]))[0]
            try:
                item["result"]["exports"].extend(_export_synccheck(
                    item["path"], cues, config, out_dir, base,
                    formats, args.syncfix))
            except (RuntimeError, ValueError, FileNotFoundError) as exc:
                report(f"{os.path.basename(item['path'])}："
                      f"同步檢查略過（{exc}）")

    if args.adcheck:
        automation = config.get("automation", {})
        out_dir_override = (automation.get("output_dir") or "").strip()
        for item in results:
            cues = (item.get("result") or {}).get("cues") if item["ok"] else None
            if not cues:
                continue
            out_dir = out_dir_override or os.path.dirname(
                os.path.abspath(item["path"]))
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(item["path"]))[0]
            item["result"]["exports"].append(
                _export_adcheck(cues, config, out_dir, base))

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


def _export_subcheck(cues: list, config: dict, out_dir: str, base: str) -> str:
    """對字幕清單跑閱讀速度／行數健檢並輸出報告文字檔，回傳報告路徑。"""
    result = analyze_cues(cues, resolve_subcheck_settings(config))
    text = format_subtitle_report(result)
    check_path = unique_path(os.path.join(out_dir, f"{base}_字幕健檢.txt"))
    with open(check_path, "w", encoding="utf-8") as fp:
        fp.write(text)
    print(text, flush=True)
    return check_path


def _run_seriescheck(files: list, config: dict, report) -> list:
    """
    系列一致性檢查：整批比一批，產出單一份跨檔報告。

    回傳與其他批次模式同構的結果清單（單一項目代表整批），供總結報告
    統一列印。
    """
    def progress(ratio, message):
        report(message, ratio)

    label = f"系列一致性檢查（{len(files)} 支影片）"
    try:
        result = analyze_series(files, config, progress_cb=progress)
        text = format_series_report(result)
        print(text, flush=True)
        automation = config.get("automation", {})
        out_dir = (automation.get("output_dir") or "").strip() \
            or os.path.dirname(os.path.abspath(files[0]))
        os.makedirs(out_dir, exist_ok=True)
        out_path = unique_path(os.path.join(out_dir, "系列一致性檢查.txt"))
        with open(out_path, "w", encoding="utf-8") as fp:
            fp.write(text)
        return [{"path": label, "ok": True, "error": None,
                 "result": {"exports": [out_path], "burned": None,
                            "cues": []}}]
    except Exception as exc:
        report(f"失敗：{exc}", 1.0)
        return [{"path": label, "ok": False, "result": None,
                 "error": str(exc)}]


def _export_synccheck(media_path: str, cues: list, config: dict, out_dir: str,
                      base: str, formats: list, do_fix: bool) -> list:
    """
    對單檔跑字幕與語音同步檢查，輸出報告；do_fix 時另存校正後的字幕。

    回傳輸出路徑清單。無音訊軌等無法檢查的情況由呼叫端攔截例外處理。
    """
    result = analyze_sync(media_path, cues, resolve_subsync_settings(config))
    text = format_sync_report(result)
    report_path = unique_path(os.path.join(out_dir, f"{base}_同步檢查.txt"))
    with open(report_path, "w", encoding="utf-8") as fp:
        fp.write(text)
    print(text, flush=True)
    exports = [report_path]

    if do_fix and result["kind"] in ("offset", "drift"):
        fixed = apply_sync_correction(cues, result["scale"], result["offset"])
        style = config.get("subtitle_style", {})
        for ext in formats or [".srt"]:
            out_path = unique_path(os.path.join(out_dir, f"{base}_同步校正{ext}"))
            export(fixed, out_path, style)
            exports.append(out_path)
    return exports


def _export_adcheck(cues: list, config: dict, out_dir: str, base: str) -> str:
    """對字幕清單跑廣告友善度自查並輸出報告文字檔，回傳報告路徑。"""
    result = scan_cues(cues, resolve_adfriendly_settings(config))
    text = format_adfriendly_report(result)
    check_path = unique_path(os.path.join(out_dir, f"{base}_廣告友善度.txt"))
    with open(check_path, "w", encoding="utf-8") as fp:
        fp.write(text)
    print(text, flush=True)
    return check_path


def _export_jumpcut(path: str, cues: list, config: dict, out_dir: str,
                    formats: list, report) -> list:
    """
    對單檔跑自動跳剪：輸出跳剪版影片＋時間軸已對齊的字幕，回傳輸出路徑清單。

    找不到可跳剪的停頓（節奏已經很緊湊）或觸發安全防呆時皆拋出例外，
    由呼叫端決定如何回報（單檔失敗不中斷整批）。
    """
    base = os.path.splitext(os.path.basename(path))[0]
    video_out = unique_path(os.path.join(
        out_dir, os.path.basename(suggest_jumpcut_output_path(path))))
    report(f"{os.path.basename(path)}：正在偵測停頓並跳剪...")
    result = apply_jumpcut(path, cues, video_out,
                           settings=resolve_jumpcut_settings(config))
    report(format_jumpcut_report(result))
    outputs = [video_out]
    for ext in (formats or [".srt"]):
        target = unique_path(os.path.join(out_dir, f"{base}_跳剪{ext}"))
        export(result["cues"], target, style=config.get("subtitle_style"))
        outputs.append(target)
    return outputs


def _export_retakes(path: str, cues: list, found: list, config: dict,
                    out_dir: str, formats: list, report) -> list:
    """
    對單檔剪掉全部偵測到的重複片段：輸出去重複版影片＋對齊後的字幕。

    找不到 ffmpeg、來源檔或觸發安全防呆時皆拋出例外，由呼叫端決定如何
    回報（單檔失敗不中斷整批）。
    """
    base = os.path.splitext(os.path.basename(path))[0]
    video_out = unique_path(os.path.join(
        out_dir, os.path.basename(suggest_retakes_output_path(path))))
    report(f"{os.path.basename(path)}：正在剪掉 {len(found)} 處重複片段...")
    result = apply_retake_removal(path, cues, found, video_out,
                                  settings=resolve_retake_settings(config))
    report(format_retake_removal_report(result))
    outputs = [video_out]
    for ext in (formats or [".srt"]):
        target = unique_path(os.path.join(out_dir, f"{base}_去重複{ext}"))
        export(result["cues"], target, style=config.get("subtitle_style"))
        outputs.append(target)
    return outputs


def _export_thumbnails(path: str, items, duration: float, config: dict,
                       out_dir: str, base: str) -> list:
    """對單檔擷取封面候選圖，回傳輸出路徑清單。"""
    results = generate_thumbnails(
        path, items, duration,
        output_paths=lambda rank: unique_path(
            os.path.join(out_dir, f"{base}_封面{rank:02d}.png")),
        settings=resolve_thumbnail_settings(config))
    return [item["path"] for item in results]


def _run_subs_batch(media_path: str, subs_path: str, config: dict,
                    report) -> list:
    """
    --subs 模式：讀入既有字幕檔，跳過轉錄，直接沿用自動化匯出／燒錄設定。

    回傳結構與 run_batch 相同（單一元素的清單），供 main() 的總結報告共用。
    """
    try:
        if not os.path.exists(media_path):
            raise FileNotFoundError(f"找不到檔案：{media_path}")
        automation = config.get("automation", {})
        if not enabled_export_formats(automation) \
                and not automation.get("burn_video"):
            raise ValueError("自動化輸出未勾選任何項目（匯出格式或燒錄影片）。")
        report(f"正在讀取字幕檔：{os.path.basename(subs_path)}...")
        loaded = load_subtitle_file(subs_path)
        cues = loaded["cues"]
        if loaded["skipped"]:
            report(f"已略過 {loaded['skipped']} 段無法解析的字幕區塊。")
        report(f"已讀入 {len(cues)} 句字幕（編碼：{loaded['encoding']}），"
              "開始匯出／燒錄...")
        exports, burned = export_and_burn(cues, media_path, config, report)
        report("完成", 1.0)
        return [{
            "path": media_path, "ok": True, "error": None,
            "result": {"cues": cues, "exports": exports, "burned": burned},
        }]
    except Exception as exc:  # 與其他批次模式一致：失敗時仍回傳同構結果。
        report(f"失敗：{exc}", 1.0)
        return [{"path": media_path, "ok": False, "result": None,
                 "error": str(exc)}]


def _run_tools_batch(files: list, config: dict, report,
                     do_audiocheck: bool = False,
                     do_thumbnails: bool = False,
                     do_audiofix: bool = False,
                     do_branding: bool = False,
                     do_videocheck: bool = False,
                     do_volumecheck: bool = False,
                     do_volumefix: bool = False,
                     do_audiovis: bool = False,
                     do_colorcheck: bool = False) -> list:
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
            if do_videocheck:
                report(f"{prefix}影片畫質健檢中...")
                vc_text = format_video_report(run_video_check(path, config))
                if vc_text:
                    vc_path = unique_path(os.path.join(
                        out_dir, f"{base}_影片健檢.txt"))
                    with open(vc_path, "w", encoding="utf-8") as fp:
                        fp.write(vc_text)
                    print(vc_text, flush=True)
                    exports.append(vc_path)
                else:
                    report(f"{prefix}無影像串流，略過影片健檢。")
            if do_colorcheck:
                report(f"{prefix}分析畫面曝光與色調中...")
                try:
                    color_result = analyze_color(
                        path, resolve_colorcheck_settings(config))
                    color_text = format_color_report(color_result)
                    color_path = unique_path(os.path.join(
                        out_dir, f"{base}_色彩健檢.txt"))
                    with open(color_path, "w", encoding="utf-8") as fp:
                        fp.write(color_text)
                    print(color_text, flush=True)
                    exports.append(color_path)
                except ValueError:
                    report(f"{prefix}無影像串流，略過色彩健檢。")
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
            if do_volumecheck or do_volumefix:
                report(f"{prefix}分析分段音量一致性中...")
                vol_result = analyze_volume_consistency(
                    path, resolve_volume_consistency_settings(config))
                if do_volumecheck:
                    vol_text = format_volume_consistency_report(vol_result)
                    vol_path = unique_path(os.path.join(
                        out_dir, f"{base}_音量一致性.txt"))
                    with open(vol_path, "w", encoding="utf-8") as fp:
                        fp.write(vol_text)
                    print(vol_text, flush=True)
                    exports.append(vol_path)
                if do_volumefix:
                    if vol_result.get("issues"):
                        report(f"{prefix}正在拉平 "
                              f"{len(vol_result['issues'])} 段音量落差...")
                        vol_out = unique_path(os.path.join(
                            out_dir, os.path.basename(
                                suggest_volume_output_path(path))))
                        fix_volume_consistency(path, vol_result, vol_out)
                        exports.append(vol_out)
                    else:
                        report(f"{prefix}未偵測到音量落差過大的段落，"
                              "略過音量拉平。")
            if do_branding:
                branding_settings = resolve_branding_settings(config)
                if (branding_settings["intro_path"]
                        or branding_settings["outro_path"]
                        or branding_settings["watermark_path"]):
                    report(f"{prefix}套用品牌套版中...")
                    brand_out = unique_path(os.path.join(
                        out_dir, os.path.basename(
                            suggest_branding_output_path(path))))
                    apply_branding(path, brand_out, settings=branding_settings)
                    exports.append(brand_out)
                else:
                    report(f"{prefix}尚未設定片頭／片尾／浮水印，略過品牌套版。")
            if do_audiovis:
                report(f"{prefix}正在產生視覺化影片...")
                vis_out = unique_path(os.path.join(
                    out_dir, os.path.basename(
                        suggest_audiovis_output_path(path))))
                render_audio_video(
                    path, vis_out,
                    settings=resolve_audiovis_settings(config))
                exports.append(vis_out)
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
