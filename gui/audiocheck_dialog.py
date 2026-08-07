# -*- coding: utf-8 -*-
"""
音訊健檢對話框：上片前一鍵檢查爆音、音量、底噪與聲道平衡。

聲音出包（爆音、太小聲、單邊聲道）常常是影片上傳後才被留言提醒，
而那時已經救不回來。本對話框選定影片後一鍵掃描音軌，以檢查表呈現
「通過／注意／建議修正」與具體修法，判定門檻皆可調並記憶。
"""

import logging
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from config import save_config
from gui.error_dialog import show_friendly_error
from gui.ffmpeg_dialog import FfmpegInstallDialog
from subtitle.audiocheck import (format_report, resolve_audiocheck_settings,
                                 run_audio_check)
from subtitle.audiofix import (fix_audio, resolve_audiofix_settings,
                               suggest_output_path)
from subtitle.burner import ffmpeg_available
from subtitle.colorcheck import (analyze_color, format_color_report,
                                 resolve_colorcheck_settings)
from subtitle.pipeline import unique_path
from subtitle.pacing import (analyze_pacing, format_pacing_report,
                             resolve_pacing_settings)
from subtitle.videocheck import (format_video_report,
                                 resolve_videocheck_settings,
                                 run_video_check, suggest_output_path
                                 as suggest_trim_output_path,
                                 suggest_trim, trim_video)
from subtitle.volumeconsistency import (analyze_volume_consistency,
                                        fix_volume_consistency,
                                        format_volume_consistency_report,
                                        resolve_volume_consistency_settings,
                                        suggest_output_path as
                                        suggest_volume_output_path)

logger = logging.getLogger(__name__)

MEDIA_FILETYPES = [
    ("影音檔", "*.mp4 *.mkv *.mov *.avi *.flv *.mp3 *.wav *.m4a *.aac"),
    ("所有檔案", "*.*"),
]


class AudioCheckDialog(tk.Toplevel):
    """音訊健檢視窗：選檔、調門檻、一鍵掃描並顯示健檢報告。"""

    def __init__(self, master, config_data, media_path=""):
        super().__init__(master)
        self.title("上片前健檢：音訊＋影片畫質、一鍵去頭尾、音量一致性")
        self.geometry("680x930")
        self.minsize(620, 750)
        self.transient(master)

        self.config_data = config_data
        self.result_queue = queue.Queue()
        self.is_processing = False
        self.report_text = ""
        self._last_volume_result = None

        settings = resolve_audiocheck_settings(config_data)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        row_file = ttk.Frame(body)
        row_file.pack(fill="x")
        ttk.Label(row_file, text="素材：").pack(side="left")
        self.media_var = tk.StringVar(value=media_path)
        ttk.Entry(row_file, textvariable=self.media_var).pack(
            side="left", fill="x", expand=True, padx=(6, 4))
        ttk.Button(row_file, text="瀏覽...", width=8,
                   command=self._choose_media).pack(side="left")

        # 前置檢查：缺 ffmpeg 時開窗即提示並提供一鍵安裝。
        self.ffmpeg_banner = None
        if not ffmpeg_available():
            banner = tk.Frame(body, bg="#fdf3d7")
            banner.pack(fill="x", pady=(8, 0))
            tk.Label(
                banner, bg="#fdf3d7", fg="#8a5a00", anchor="w",
                text="⚠ 尚未安裝 ffmpeg：音訊健檢需要它才能量測音軌。",
            ).pack(side="left", padx=6, pady=4)
            ttk.Button(banner, text="自動安裝 ffmpeg",
                      command=self._open_ffmpeg_installer).pack(
                side="right", padx=6, pady=2)
            self.ffmpeg_banner = banner

        # 判定門檻（自動記憶）：不同錄音環境可自行放寬或收緊。
        options = ttk.LabelFrame(body, text="判定門檻（自動記憶）",
                                 padding=(10, 6))
        options.pack(fill="x", pady=(8, 0))
        row1 = ttk.Frame(options)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="太小聲門檻:").pack(side="left")
        self.quiet_var = tk.DoubleVar(value=settings["quiet_lufs"])
        tk.Spinbox(row1, from_=-30.0, to=-10.0, increment=0.5, width=7,
                   textvariable=self.quiet_var, format="%.1f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row1, text="LUFS").pack(side="left", padx=(0, 14))
        ttk.Label(row1, text="底噪門檻:").pack(side="left")
        self.noise_var = tk.DoubleVar(value=settings["noise_floor_db"])
        tk.Spinbox(row1, from_=-90.0, to=-20.0, increment=1.0, width=7,
                   textvariable=self.noise_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row1, text="dB").pack(side="left")
        row2 = ttk.Frame(options)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="爆音峰值門檻:").pack(side="left")
        self.clip_var = tk.DoubleVar(value=settings["clip_peak_db"])
        tk.Spinbox(row2, from_=-6.0, to=0.0, increment=0.1, width=7,
                   textvariable=self.clip_var, format="%.1f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row2, text="dB").pack(side="left", padx=(0, 14))
        ttk.Label(row2, text="聲道差異門檻:").pack(side="left")
        self.balance_var = tk.DoubleVar(value=settings["balance_db"])
        tk.Spinbox(row2, from_=2.0, to=20.0, increment=0.5, width=7,
                   textvariable=self.balance_var, format="%.1f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row2, text="dB").pack(side="left")
        # 影片畫質門檻（位元率寬嚴、開頭廢秒提醒門檻）。
        vc_settings = resolve_videocheck_settings(config_data)
        row3 = ttk.Frame(options)
        row3.pack(fill="x", pady=2)
        ttk.Label(row3, text="位元率寬嚴:").pack(side="left")
        self.bitrate_margin_var = tk.DoubleVar(
            value=vc_settings["bitrate_margin"])
        tk.Spinbox(row3, from_=0.5, to=2.0, increment=0.1, width=7,
                   textvariable=self.bitrate_margin_var,
                   format="%.1f").pack(side="left", padx=(2, 2))
        ttk.Label(row3, text="× YouTube 建議值").pack(
            side="left", padx=(0, 14))
        ttk.Label(row3, text="開頭廢秒門檻:").pack(side="left")
        self.head_max_var = tk.DoubleVar(
            value=vc_settings["head_max_seconds"])
        tk.Spinbox(row3, from_=0.3, to=10.0, increment=0.1, width=7,
                   textvariable=self.head_max_var, format="%.1f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row3, text="秒").pack(side="left", padx=(0, 14))
        ttk.Label(row3, text="凍結判定秒數:").pack(side="left")
        self.freeze_min_var = tk.DoubleVar(
            value=vc_settings["freeze_min_seconds"])
        tk.Spinbox(row3, from_=0.5, to=5.0, increment=0.1, width=7,
                   textvariable=self.freeze_min_var, format="%.1f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row3, text="秒").pack(side="left")
        # 分段音量一致性門檻（分段長度、與整體中位數響度的容許落差）。
        volc_settings = resolve_volume_consistency_settings(config_data)
        row4 = ttk.Frame(options)
        row4.pack(fill="x", pady=2)
        ttk.Label(row4, text="音量分段秒數:").pack(side="left")
        self.vol_segment_var = tk.DoubleVar(
            value=volc_settings["segment_seconds"])
        tk.Spinbox(row4, from_=10.0, to=60.0, increment=5.0, width=7,
                   textvariable=self.vol_segment_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row4, text="秒").pack(side="left", padx=(0, 14))
        ttk.Label(row4, text="音量落差門檻:").pack(side="left")
        self.vol_deviation_var = tk.DoubleVar(
            value=volc_settings["deviation_lu"])
        tk.Spinbox(row4, from_=1.5, to=8.0, increment=0.5, width=7,
                   textvariable=self.vol_deviation_var, format="%.1f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row4, text="LU").pack(side="left")
        # 畫面曝光與色偏門檻。
        cc_settings = resolve_colorcheck_settings(config_data)
        row5 = ttk.Frame(options)
        row5.pack(fill="x", pady=2)
        ttk.Label(row5, text="過暗門檻:").pack(side="left")
        self.dark_luma_var = tk.DoubleVar(value=cc_settings["dark_luma"])
        tk.Spinbox(row5, from_=20, to=100, increment=5, width=7,
                   textvariable=self.dark_luma_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row5, text="過曝門檻:").pack(side="left", padx=(12, 0))
        self.bright_luma_var = tk.DoubleVar(value=cc_settings["bright_luma"])
        tk.Spinbox(row5, from_=160, to=240, increment=5, width=7,
                   textvariable=self.bright_luma_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row5, text="色偏門檻:").pack(side="left", padx=(12, 0))
        self.color_cast_var = tk.DoubleVar(
            value=cc_settings["cast_threshold"])
        tk.Spinbox(row5, from_=5, to=25, increment=1, width=7,
                   textvariable=self.color_cast_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row5, text="（0~255 亮度值）", foreground="#666666").pack(
            side="left")
        # 剪輯節奏門檻：畫面太久沒變化會流失觀眾。
        pc_settings = resolve_pacing_settings(config_data)
        row6 = ttk.Frame(options)
        row6.pack(fill="x", pady=2)
        ttk.Label(row6, text="畫面不變上限:").pack(side="left")
        self.pace_static_var = tk.DoubleVar(
            value=pc_settings["max_static_seconds"])
        tk.Spinbox(row6, from_=5, to=300, increment=5, width=7,
                   textvariable=self.pace_static_var, format="%.0f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row6, text="秒").pack(side="left", padx=(0, 14))
        ttk.Label(row6, text="剪接偵測靈敏度:").pack(side="left")
        self.pace_threshold_var = tk.DoubleVar(
            value=pc_settings["scene_threshold"])
        tk.Spinbox(row6, from_=0.05, to=0.90, increment=0.05, width=7,
                   textvariable=self.pace_threshold_var, format="%.2f").pack(
            side="left", padx=(2, 2))
        ttk.Label(row6, text="（越小越敏感）", foreground="#666666").pack(
            side="left")

        self.status_var = tk.StringVar(
            value="選好素材後按「開始健檢」，掃描不會改動原始檔案。")
        ttk.Label(body, textvariable=self.status_var,
                  foreground="#1a5fb4").pack(fill="x", pady=(6, 0))
        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(body, mode="determinate", maximum=100.0,
                        variable=self.progress_var).pack(
            fill="x", pady=(4, 6))

        # 報告顯示區。
        report_frame = ttk.LabelFrame(body, text="健檢報告", padding=(6, 6))
        report_frame.pack(fill="both", expand=True)
        self.report = tk.Text(report_frame, wrap="word", state="disabled",
                              font=("Microsoft JhengHei", 10), height=12)
        scrollbar = ttk.Scrollbar(report_frame, orient="vertical",
                                  command=self.report.yview)
        self.report.configure(yscrollcommand=scrollbar.set)
        self.report.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 音訊修復：健檢發現問題後不必離開程式，直接輸出修復版。
        fix_settings = resolve_audiofix_settings(config_data)
        fix_frame = ttk.LabelFrame(
            body, text="音訊修復（畫面原樣複製、僅處理音軌）",
            padding=(10, 6))
        fix_frame.pack(fill="x", pady=(8, 0))
        fix_row = ttk.Frame(fix_frame)
        fix_row.pack(fill="x")
        self.fix_denoise_var = tk.BooleanVar(value=fix_settings["denoise"])
        ttk.Checkbutton(fix_row, text="降噪",
                       variable=self.fix_denoise_var).pack(side="left")
        self.fix_strength_var = tk.DoubleVar(
            value=fix_settings["denoise_strength"])
        tk.Spinbox(fix_row, from_=6.0, to=40.0, increment=1.0, width=4,
                   textvariable=self.fix_strength_var,
                   format="%.0f").pack(side="left", padx=(2, 2))
        ttk.Label(fix_row, text="dB").pack(side="left", padx=(0, 10))
        self.fix_highpass_var = tk.BooleanVar(value=fix_settings["highpass"])
        ttk.Checkbutton(fix_row, text="去低頻隆隆",
                       variable=self.fix_highpass_var).pack(side="left")
        self.fix_hz_var = tk.DoubleVar(value=fix_settings["highpass_hz"])
        tk.Spinbox(fix_row, from_=40.0, to=200.0, increment=10.0, width=5,
                   textvariable=self.fix_hz_var,
                   format="%.0f").pack(side="left", padx=(2, 2))
        ttk.Label(fix_row, text="Hz").pack(side="left", padx=(0, 10))
        self.fix_loudnorm_var = tk.BooleanVar(value=fix_settings["loudnorm"])
        ttk.Checkbutton(fix_row, text="響度正規化",
                       variable=self.fix_loudnorm_var).pack(side="left")
        self.fix_btn = ttk.Button(fix_row, text="輸出修復版",
                                  command=self._on_fix)
        self.fix_btn.pack(side="right")
        ttk.Label(
            fix_frame, foreground="#666666", anchor="w", justify="left",
            text="降噪對冷氣聲、電流聲等穩態底噪有效；強度過高人聲會發悶，"
                 "建議先用預設值試聽。",
        ).pack(fill="x", pady=(2, 0))

        # 一鍵去頭尾：健檢偵測到廢秒後自動帶入建議值，可手動微調。
        trim_frame = ttk.LabelFrame(
            body, text="一鍵去頭尾（健檢後自動帶入偵測到的廢秒）",
            padding=(10, 6))
        trim_frame.pack(fill="x", pady=(8, 0))
        trim_row = ttk.Frame(trim_frame)
        trim_row.pack(fill="x")
        ttk.Label(trim_row, text="去頭:").pack(side="left")
        self.trim_head_var = tk.DoubleVar(value=0.0)
        tk.Spinbox(trim_row, from_=0.0, to=600.0, increment=0.1, width=6,
                   textvariable=self.trim_head_var, format="%.1f").pack(
            side="left", padx=(2, 2))
        ttk.Label(trim_row, text="秒").pack(side="left", padx=(0, 10))
        ttk.Label(trim_row, text="去尾:").pack(side="left")
        self.trim_tail_var = tk.DoubleVar(value=0.0)
        tk.Spinbox(trim_row, from_=0.0, to=600.0, increment=0.1, width=6,
                   textvariable=self.trim_tail_var, format="%.1f").pack(
            side="left", padx=(2, 2))
        ttk.Label(trim_row, text="秒").pack(side="left", padx=(0, 10))
        self.trim_btn = ttk.Button(trim_row, text="輸出修剪版",
                                   command=self._on_trim)
        self.trim_btn.pack(side="right")
        ttk.Label(
            trim_frame, foreground="#666666", anchor="w", justify="left",
            text="開頭空白是留存率殺手；修剪版重新編碼確保剪點精準、"
                 "原始檔不受影響。",
        ).pack(fill="x", pady=(2, 0))

        # 音量一致性拉平：健檢偵測到落差過大的段落後可一鍵套用增益調整。
        volfix_frame = ttk.LabelFrame(
            body, text="音量一致性拉平（只調整落差過大的段落，其餘不動）",
            padding=(10, 6))
        volfix_frame.pack(fill="x", pady=(8, 0))
        volfix_row = ttk.Frame(volfix_frame)
        volfix_row.pack(fill="x")
        self.volfix_btn = ttk.Button(
            volfix_row, text="拉平音量落差", state="disabled",
            command=self._on_volume_fix)
        self.volfix_btn.pack(side="right")
        ttk.Label(
            volfix_frame, foreground="#666666", anchor="w", justify="left",
            wraplength=640,
            text="素材來自不同時段或麥克風距離時常見「忽大忽小」；"
                 "健檢會把影片切成固定長度分段，只對與整體中位數響度差異"
                 "過大的段落套用增益調整，其餘段落原樣不動。",
        ).pack(fill="x", pady=(2, 0))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 0))
        self.run_btn = ttk.Button(buttons, text="開始健檢",
                                  command=self._on_run)
        self.run_btn.pack(side="left")
        self.copy_btn = ttk.Button(buttons, text="複製報告", state="disabled",
                                   command=self._on_copy)
        self.copy_btn.pack(side="left", padx=(6, 0))
        self.save_btn = ttk.Button(buttons, text="另存報告...",
                                   state="disabled", command=self._on_save)
        self.save_btn.pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="關閉", command=self._on_close).pack(
            side="right")

        self._poll_job = self.after(120, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    def _choose_media(self):
        path = filedialog.askopenfilename(
            title="選擇要健檢的影音檔", filetypes=MEDIA_FILETYPES,
            parent=self)
        if path:
            self.media_var.set(path)

    def _collect_settings(self):
        """把介面上的門檻寫回設定並存檔，回傳解析後的 settings。"""
        def safe(var, fallback):
            try:
                return float(var.get())
            except (tk.TclError, ValueError):
                return fallback
        self.config_data["audiocheck"] = {
            "quiet_lufs": safe(self.quiet_var, -19.0),
            "noise_floor_db": safe(self.noise_var, -50.0),
            "clip_peak_db": safe(self.clip_var, -0.5),
            "balance_db": safe(self.balance_var, 6.0),
        }
        self.config_data["audiofix"] = {
            "denoise": bool(self.fix_denoise_var.get()),
            "denoise_strength": safe(self.fix_strength_var, 12.0),
            "highpass": bool(self.fix_highpass_var.get()),
            "highpass_hz": safe(self.fix_hz_var, 80.0),
            "loudnorm": bool(self.fix_loudnorm_var.get()),
        }
        merged_vc = dict(self.config_data.get("videocheck", {}))
        merged_vc.update({
            "bitrate_margin": safe(self.bitrate_margin_var, 1.0),
            "head_max_seconds": safe(self.head_max_var, 1.0),
            "freeze_min_seconds": safe(self.freeze_min_var, 1.0),
        })
        self.config_data["videocheck"] = merged_vc
        self.config_data["volumeconsistency"] = {
            "segment_seconds": safe(self.vol_segment_var, 20.0),
            "deviation_lu": safe(self.vol_deviation_var, 3.0),
        }
        self.config_data["colorcheck"] = {
            "dark_luma": safe(self.dark_luma_var, 60.0),
            "bright_luma": safe(self.bright_luma_var, 200.0),
            "cast_threshold": safe(self.color_cast_var, 10.0),
        }
        self.config_data["pacing"] = {
            "scene_threshold": safe(self.pace_threshold_var, 0.30),
            "max_static_seconds": safe(self.pace_static_var, 25.0),
        }
        try:
            save_config(self.config_data)
        except OSError:
            pass  # 存檔失敗不影響本次使用。
        return self.config_data

    # ------------------------------------------------------------------
    def _on_run(self):
        if self.is_processing:
            return
        media_path = self.media_var.get().strip()
        if not media_path or not os.path.exists(media_path):
            messagebox.showinfo("提示", "請選擇有效的影音檔。", parent=self)
            return
        if not ffmpeg_available():
            show_friendly_error(
                self, "音訊健檢需要 ffmpeg",
                RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。"),
                on_install_ffmpeg=self._open_ffmpeg_installer)
            return
        config = self._collect_settings()
        self._set_processing(True)
        threading.Thread(
            target=self._run_worker, args=(media_path, config),
            daemon=True).start()

    def _on_fix(self):
        """輸出修復版：依勾選套用降噪／去低頻／響度正規化。"""
        if self.is_processing:
            return
        media_path = self.media_var.get().strip()
        if not media_path or not os.path.exists(media_path):
            messagebox.showinfo("提示", "請選擇有效的影音檔。", parent=self)
            return
        if not ffmpeg_available():
            show_friendly_error(
                self, "音訊修復需要 ffmpeg",
                RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。"),
                on_install_ffmpeg=self._open_ffmpeg_installer)
            return
        config = self._collect_settings()
        fix_settings = resolve_audiofix_settings(config)
        if not (fix_settings["denoise"] or fix_settings["highpass"]
                or fix_settings["loudnorm"]):
            messagebox.showinfo(
                "提示", "請至少勾選一個修復項目（降噪、去低頻或響度正規化）。",
                parent=self)
            return
        output = unique_path(suggest_output_path(media_path))
        self._set_processing(True)
        threading.Thread(
            target=self._fix_worker, args=(media_path, output, fix_settings),
            daemon=True).start()

    def _fix_worker(self, media_path, output, fix_settings):
        try:
            def report(ratio, message):
                self.result_queue.put(("status", (message, ratio)))
            fix_audio(media_path, output, settings=fix_settings,
                      progress_cb=report)
            self.result_queue.put(("fix_done", output))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("音訊修復失敗")
            self.result_queue.put(("error", exc))

    def _on_volume_fix(self):
        """拉平音量落差：只調整上次健檢找出的落差過大段落。"""
        if self.is_processing:
            return
        media_path = self.media_var.get().strip()
        if not media_path or not os.path.exists(media_path):
            messagebox.showinfo("提示", "請選擇有效的影音檔。", parent=self)
            return
        if not ffmpeg_available():
            show_friendly_error(
                self, "音量拉平需要 ffmpeg",
                RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。"),
                on_install_ffmpeg=self._open_ffmpeg_installer)
            return
        if not (self._last_volume_result
               and self._last_volume_result.get("issues")):
            messagebox.showinfo(
                "提示", "請先按「開始健檢」偵測音量落差過大的段落。",
                parent=self)
            return
        output = unique_path(suggest_volume_output_path(media_path))
        self._set_processing(True)
        threading.Thread(
            target=self._volumefix_worker,
            args=(media_path, output, self._last_volume_result),
            daemon=True).start()

    def _volumefix_worker(self, media_path, output, volume_result):
        try:
            def report(ratio, message):
                self.result_queue.put(("status", (message, ratio)))
            fix_volume_consistency(media_path, volume_result, output,
                                   progress_cb=report)
            self.result_queue.put(("volumefix_done", output))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("音量拉平失敗")
            self.result_queue.put(("error", exc))

    def _run_worker(self, media_path, config):
        try:
            def report(ratio, message):
                self.result_queue.put(("status", (message, ratio)))
            result = run_audio_check(media_path, config, progress_cb=report)
            text = format_report(result, os.path.basename(media_path))
            # 影片畫質健檢：純音訊檔（無影像串流）自動略過畫質段落。
            report(0.7, "正在檢查影片畫質與頭尾廢秒...")
            video_result = run_video_check(media_path, config)
            video_text = format_video_report(video_result)
            if video_text:
                text = f"{text}\n\n{video_text}"
            trim = suggest_trim(video_result.get("dead_air"),
                                resolve_videocheck_settings(config))
            # 畫面曝光與色偏：純音訊檔（無影像串流）自動略過此段落。
            report(0.78, "正在分析畫面曝光與色調...")
            try:
                color_result = analyze_color(
                    media_path, resolve_colorcheck_settings(config))
                color_text = format_color_report(color_result)
                text = f"{text}\n\n{color_text}"
            except ValueError:
                pass  # 無影像串流，略過此段落。
            # 分段音量一致性：抓出「忽大忽小」的段落（獨立於整體響度健檢）。
            # 無音訊軌（純畫面素材）時優雅略過，不中斷整體健檢流程。
            report(0.85, "正在分析分段音量一致性...")
            volume_result = None
            try:
                volume_result = analyze_volume_consistency(
                    media_path, resolve_volume_consistency_settings(config))
                volume_text = format_volume_consistency_report(volume_result)
                text = (f"{text}\n\n===== 分段音量一致性 =====\n"
                       f"{volume_text}")
            except ValueError:
                pass  # 無音訊軌或素材過短，略過此段落。
            # 剪輯節奏：畫面太久沒變化（與凍結畫面是相反的性質，兩者都要看）。
            # 純音訊檔沒有畫面可分析，優雅略過。
            report(0.93, "正在分析剪輯節奏（畫面變化密度）...")
            try:
                pacing_result = analyze_pacing(media_path, config)
                if pacing_result.get("shots"):
                    text = (f"{text}\n\n"
                            f"{format_pacing_report(pacing_result, resolve_pacing_settings(config))}")
            except (RuntimeError, ValueError):
                pass  # 無影像串流或 ffmpeg 不可用，略過此段落。
            self.result_queue.put(("done", (text, trim, volume_result)))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("健檢失敗")
            self.result_queue.put(("error", exc))

    def _on_trim(self):
        """輸出去頭尾修剪版：依（可微調的）偵測建議重新輸出。"""
        if self.is_processing:
            return
        media_path = self.media_var.get().strip()
        if not media_path or not os.path.exists(media_path):
            messagebox.showinfo("提示", "請選擇有效的影音檔。", parent=self)
            return
        if not ffmpeg_available():
            show_friendly_error(
                self, "影片修剪需要 ffmpeg",
                RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。"),
                on_install_ffmpeg=self._open_ffmpeg_installer)
            return
        try:
            head = max(float(self.trim_head_var.get()), 0.0)
            tail = max(float(self.trim_tail_var.get()), 0.0)
        except (tk.TclError, ValueError):
            head, tail = 0.0, 0.0
        if head <= 0 and tail <= 0:
            messagebox.showinfo(
                "提示", "去頭與去尾秒數皆為 0，沒有需要修剪的內容；"
                "可先按「開始健檢」自動偵測廢秒。", parent=self)
            return
        output = unique_path(suggest_trim_output_path(media_path))
        self._set_processing(True)
        threading.Thread(
            target=self._trim_worker, args=(media_path, output, head, tail),
            daemon=True).start()

    def _trim_worker(self, media_path, output, head, tail):
        try:
            def report(ratio, message):
                self.result_queue.put(("status", (message, ratio)))
            trim_video(media_path, output, head_seconds=head,
                       tail_seconds=tail, progress_cb=report)
            self.result_queue.put(("trim_done", output))
        except Exception as exc:  # 背景執行緒須攔截所有例外回報主執行緒。
            logger.exception("影片修剪失敗")
            self.result_queue.put(("error", exc))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.result_queue.get_nowait()
                if kind == "status":
                    message, ratio = payload
                    self.status_var.set(message)
                    if ratio is not None:
                        self.progress_var.set(ratio * 100.0)
                elif kind == "done":
                    self._set_processing(False)
                    text, trim, volume_result = payload
                    self._show_report(text)
                    self.trim_head_var.set(trim[0])
                    self.trim_tail_var.set(trim[1])
                    self._last_volume_result = volume_result
                    has_volume_issues = bool(
                        volume_result and volume_result.get("issues"))
                    self.volfix_btn.configure(
                        state="normal" if has_volume_issues else "disabled")
                    if trim[0] > 0 or trim[1] > 0:
                        self.status_var.set(
                            "健檢完成；已偵測到頭尾廢秒並帶入下方修剪建議。")
                    else:
                        self.status_var.set("健檢完成，結果如下。")
                elif kind == "trim_done":
                    self._set_processing(False)
                    self.status_var.set(f"修剪版已輸出：{payload}")
                    messagebox.showinfo(
                        "修剪完成",
                        f"已輸出修剪版：\n{payload}\n\n"
                        "建議播放確認剪點；可對修剪版再跑一次健檢。",
                        parent=self)
                elif kind == "fix_done":
                    self._set_processing(False)
                    self.status_var.set(f"修復版已輸出：{payload}")
                    messagebox.showinfo(
                        "修復完成",
                        f"已輸出修復版：\n{payload}\n\n"
                        "建議試聽確認降噪強度合適（過強人聲會發悶），"
                        "也可對修復版再跑一次健檢比對。", parent=self)
                elif kind == "volumefix_done":
                    self._set_processing(False)
                    self.status_var.set(f"音量拉平版已輸出：{payload}")
                    messagebox.showinfo(
                        "音量拉平完成",
                        f"已輸出音量拉平版：\n{payload}\n\n"
                        "建議試聽確認落差已改善，也可對輸出版再跑一次健檢"
                        "比對。", parent=self)
                elif kind == "error":
                    self._set_processing(False)
                    self.status_var.set("健檢失敗。")
                    show_friendly_error(
                        self, "音訊健檢失敗", payload,
                        on_install_ffmpeg=self._open_ffmpeg_installer)
        except queue.Empty:
            pass
        self._poll_job = self.after(120, self._poll_queue)

    def _open_ffmpeg_installer(self):
        """開啟 ffmpeg 一鍵安裝；完成後移除警告條。"""
        def done():
            if self.ffmpeg_banner is not None:
                self.ffmpeg_banner.destroy()
                self.ffmpeg_banner = None
        FfmpegInstallDialog(self, on_done=done)

    def _show_report(self, text):
        self.report_text = text
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", text)
        self.report.configure(state="disabled")
        self.copy_btn.configure(state="normal")
        self.save_btn.configure(state="normal")

    def _on_copy(self):
        if not self.report_text:
            return
        self.clipboard_clear()
        self.clipboard_append(self.report_text)
        self.status_var.set("報告已複製到剪貼簿。")

    def _on_save(self):
        if not self.report_text:
            return
        media_path = self.media_var.get().strip()
        base = os.path.splitext(os.path.basename(media_path))[0] or "音訊健檢"
        initial = unique_path(os.path.join(
            os.path.dirname(media_path) or ".", f"{base}_音訊健檢.txt"))
        path = filedialog.asksaveasfilename(
            title="另存健檢報告", defaultextension=".txt",
            initialfile=os.path.basename(initial),
            initialdir=os.path.dirname(initial) or ".",
            filetypes=[("文字檔", "*.txt"), ("所有檔案", "*.*")],
            parent=self)
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(self.report_text)
        except OSError as exc:
            messagebox.showerror("儲存失敗", str(exc), parent=self)
            return
        self.status_var.set(f"報告已儲存：{path}")

    def _set_processing(self, processing):
        self.is_processing = processing
        state = "disabled" if processing else "normal"
        self.run_btn.configure(state=state)
        self.fix_btn.configure(state=state)
        self.trim_btn.configure(state=state)
        if processing:
            self.volfix_btn.configure(state="disabled")
        else:
            has_volume_issues = bool(
                self._last_volume_result
                and self._last_volume_result.get("issues"))
            self.volfix_btn.configure(
                state="normal" if has_volume_issues else "disabled")

    def _on_close(self):
        if getattr(self, "_poll_job", None):
            self.after_cancel(self._poll_job)
        self.destroy()
