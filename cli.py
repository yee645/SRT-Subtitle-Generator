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

命令列旗標僅影響本次執行，不會改寫 config.json 記憶的設定。
"""

from __future__ import annotations

import argparse
import sys

from config import load_config
from subtitle.pipeline import EXPORT_FORMATS, run_batch


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
        "--output-dir", metavar="資料夾",
        help="本次輸出資料夾；未指定時沿用 config.json（留空＝來源資料夾）。")
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
    if args.output_dir is not None:
        automation["output_dir"] = args.output_dir


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()
    _apply_overrides(config, args)

    def report(message, ratio=None):
        percent = f"{int(ratio * 100):3d}% " if ratio is not None else "     "
        print(f"{percent}{message}", flush=True)

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
            lines.append(f"    原因：{item['error']}")
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
