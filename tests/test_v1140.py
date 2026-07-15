# -*- coding: utf-8 -*-
"""
v1.14.0 新功能測試：品牌套版（片頭／片尾一鍵接續、浮水印自動疊加）。

1. 單元測試（無需 ffmpeg）：resolve_branding_settings() 的預設值、夾限、
   位置代碼容錯；has_intro_or_outro / has_watermark 邏輯；
   _overlay_position_expr() 五個位置的座標運算式；suggest_output_path()
   命名慣例。
2. 靜態掃描：gui/branding_dialog.py 不應殘留 classic tk.Checkbutton
   （與 test_v1131.py 的既有慣例一致）。
3. 真實 ffmpeg 端到端驗證（若本機裝有 ffmpeg 才會執行；以 lavfi 合成
   極短測試素材，不需真實影片）：
   - 片頭＋片尾（無浮水印）
   - 純浮水印（無片頭片尾，確認保留 -c:a copy、不做 concat）
   - 三者合併於同一次呼叫
   - 缺片頭檔案 → FileNotFoundError 且訊息含「找不到片頭檔案」
   - 完全未設定任何一項 → ValueError
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import branding, errors, media

# ===== 1. resolve_branding_settings：預設值 =====
defaults = branding.resolve_branding_settings(None)
check("預設值與 DEFAULT_BRANDING 一致", defaults == branding.DEFAULT_BRANDING,
      str(defaults))

# ===== 1b. 夾限：opacity/scale/margin 超出範圍會被夾住 =====
clamped = branding.resolve_branding_settings({
    "branding": {
        "watermark_opacity": 5.0,     # 超過 1.0 上限
        "watermark_scale": 0.9,       # 超過 0.5 上限
        "watermark_margin": -50,      # 低於 0 下限
    }
})
check("透明度夾限上界", clamped["watermark_opacity"] == 1.0, str(clamped))
check("大小夾限上界", clamped["watermark_scale"] == 0.5, str(clamped))
check("留白夾限下界", clamped["watermark_margin"] == 0, str(clamped))

low_clamped = branding.resolve_branding_settings({
    "branding": {
        "watermark_opacity": 0.0,     # 低於 0.1 下限
        "watermark_scale": 0.01,      # 低於 0.05 下限
        "watermark_margin": 500,      # 高於 200 上限
    }
})
check("透明度夾限下界", low_clamped["watermark_opacity"] == 0.1, str(low_clamped))
check("大小夾限下界", low_clamped["watermark_scale"] == 0.05, str(low_clamped))
check("留白夾限上界", low_clamped["watermark_margin"] == 200, str(low_clamped))

# ===== 1c. 無效位置代碼回退預設 =====
bad_position = branding.resolve_branding_settings(
    {"branding": {"watermark_position": "middle_of_nowhere"}})
check("無效位置回退 bottom_right",
      bad_position["watermark_position"] == "bottom_right", str(bad_position))

# ===== 1d. 無效數值型別回退預設 =====
bad_values = branding.resolve_branding_settings(
    {"branding": {"watermark_opacity": "abc", "watermark_scale": None,
                  "watermark_margin": [1, 2]}})
check("無效透明度回預設", bad_values["watermark_opacity"] == 0.85, str(bad_values))
check("無效大小回預設", bad_values["watermark_scale"] == 0.15, str(bad_values))
check("無效留白回預設", bad_values["watermark_margin"] == 24, str(bad_values))

# ===== 2. has_intro_or_outro / has_watermark =====
check("皆空時 has_intro_or_outro 為 False",
      not branding.has_intro_or_outro(branding.DEFAULT_BRANDING))
check("皆空時 has_watermark 為 False",
      not branding.has_watermark(branding.DEFAULT_BRANDING))
check("僅片頭時 has_intro_or_outro 為 True",
      branding.has_intro_or_outro({"intro_path": "a.mp4", "outro_path": ""}))
check("僅片尾時 has_intro_or_outro 為 True",
      branding.has_intro_or_outro({"intro_path": "", "outro_path": "b.mp4"}))
check("有浮水印時 has_watermark 為 True",
      branding.has_watermark({"watermark_path": "logo.png"}))

# ===== 3. _overlay_position_expr：五個位置的座標運算式 =====
expected = {
    "top_left": ("10", "10"),
    "top_right": ("main_w-overlay_w-10", "10"),
    "bottom_left": ("10", "main_h-overlay_h-10"),
    "bottom_right": ("main_w-overlay_w-10", "main_h-overlay_h-10"),
    "center": ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
}
for position, (exp_x, exp_y) in expected.items():
    x_expr, y_expr = branding._overlay_position_expr(position, 10)
    check(f"位置運算式 {position}", (x_expr, y_expr) == (exp_x, exp_y),
          f"got=({x_expr}, {y_expr})")

# ===== 4. suggest_output_path 命名 =====
check("建議輸出路徑加上 _套版 後綴",
      branding.suggest_output_path("影片.mp4") == "影片_套版.mp4")
check("無副檔名時補上 .mp4",
      branding.suggest_output_path("影片") == "影片_套版.mp4")

# ===== 5. errors.py：找不到片頭/片尾/浮水印檔案的字串分類 =====
for label in ("片頭", "片尾", "浮水印"):
    text = f"找不到{label}檔案：/tmp/不存在.mp4"
    err = errors.describe_exception(text)
    check(f"純文字「找不到{label}檔案」歸類為缺檔案",
          err.kind == errors.KIND_FILE_MISSING, err.cause)
    err2 = errors.describe_exception(FileNotFoundError(text))
    check(f"例外物件「找不到{label}檔案」歸類為缺檔案",
          err2.kind == errors.KIND_FILE_MISSING, err2.cause)

err3 = errors.describe_exception("品牌套版失敗：某些 ffmpeg stderr")
check("品牌套版失敗歸類為 ffmpeg 執行失敗",
      err3.kind == errors.KIND_FFMPEG_FAILED, err3.cause)

# ===== 6. 靜態掃描：gui/branding_dialog.py 無殘留 classic tk.Checkbutton =====
gui_dir = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "gui")
branding_dialog_path = os.path.join(gui_dir, "branding_dialog.py")
check("gui/branding_dialog.py 存在", os.path.exists(branding_dialog_path))
if os.path.exists(branding_dialog_path):
    text = open(branding_dialog_path, encoding="utf-8").read()
    has_classic_checkbutton = "tk.Checkbutton(" in text.replace(
        "ttk.Checkbutton(", "")
    check("gui/branding_dialog.py 無殘留 tk.Checkbutton",
          not has_classic_checkbutton)

# ===== 7. 真實 ffmpeg 端到端驗證 =====
HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
if not HAVE_FFMPEG:
    print("\n(找不到 ffmpeg／ffprobe，略過端到端驗證——僅單元測試通過與否有效)")
else:
    def run(cmd):
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"合成測試素材失敗：{' '.join(cmd)}\n"
                f"{result.stderr.decode('utf-8', 'ignore')}")

    with tempfile.TemporaryDirectory() as tmp:
        main_path = os.path.join(tmp, "main.mp4")
        intro_path = os.path.join(tmp, "intro.mp4")
        outro_path = os.path.join(tmp, "outro.mp4")
        watermark_path = os.path.join(tmp, "watermark.png")

        # main：2 秒，有畫面＋音訊。
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
             "-shortest", main_path])
        # intro：1 秒，只有畫面，刻意無音軌——驗證 anullsrc 補靜音音軌路徑。
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=red:s=160x120:d=1",
             intro_path])
        # outro：1 秒，畫面＋音訊——驗證一般（非 anullsrc）音訊路徑。
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=green:s=320x240:d=1",
             "-f", "lavfi", "-i", "sine=frequency=220:duration=1",
             "-shortest", outro_path])
        # watermark：64x64 單張圖片。
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=yellow:s=64x64",
             "-frames:v", "1", watermark_path])

        main_duration = media.probe_duration(main_path)
        intro_duration = media.probe_duration(intro_path)
        outro_duration = media.probe_duration(outro_path)
        check("素材時長量測（main≈2s）", abs(main_duration - 2.0) < 0.3,
              str(main_duration))

        progress_events = []
        def progress_cb(ratio, message):
            progress_events.append((ratio, message))

        # --- 案例 1：片頭＋片尾（無浮水印）---
        out1 = os.path.join(tmp, "out1.mp4")
        settings1 = branding.resolve_branding_settings({
            "branding": {"intro_path": intro_path, "outro_path": outro_path}})
        branding.apply_branding(main_path, out1, settings=settings1,
                                progress_cb=progress_cb)
        check("案例1 輸出檔存在", os.path.exists(out1))
        check("案例1 輸出檔非空", os.path.getsize(out1) > 0)
        dur1 = media.probe_duration(out1)
        expected1 = intro_duration + main_duration + outro_duration
        check(f"案例1 時長≈{expected1:.2f}s（實得 {dur1:.2f}s）",
              abs(dur1 - expected1) < 0.3, str(dur1))
        check("案例1 有進度回報", any(m == "品牌套版完成" for _, m in progress_events),
              str(progress_events[-3:]))

        # --- 案例 2：純浮水印（無片頭片尾）---
        out2 = os.path.join(tmp, "out2.mp4")
        settings2 = branding.resolve_branding_settings({
            "branding": {"watermark_path": watermark_path}})
        branding.apply_branding(main_path, out2, settings=settings2)
        check("案例2 輸出檔存在", os.path.exists(out2))
        check("案例2 輸出檔非空", os.path.getsize(out2) > 0)
        dur2 = media.probe_duration(out2)
        check(f"案例2 時長≈main（{main_duration:.2f}s，實得 {dur2:.2f}s）",
              abs(dur2 - main_duration) < 0.2, str(dur2))
        # 純浮水印時應保留 -c:a copy、不做 concat：組出指令直接檢查。
        cmd2, _ = branding._build_command(main_path, out2, settings2)
        check("案例2 指令保留 -c:a copy",
              "-c:a" in cmd2 and cmd2[cmd2.index("-c:a") + 1] == "copy",
              str(cmd2))
        check("案例2 指令不含 concat 濾鏡",
              "concat=" not in cmd2[cmd2.index("-filter_complex") + 1])

        # --- 案例 3：片頭＋片尾＋浮水印全部合併於同一次呼叫 ---
        out3 = os.path.join(tmp, "out3.mp4")
        settings3 = branding.resolve_branding_settings({
            "branding": {
                "intro_path": intro_path, "outro_path": outro_path,
                "watermark_path": watermark_path,
            }})
        branding.apply_branding(main_path, out3, settings=settings3)
        check("案例3 輸出檔存在", os.path.exists(out3))
        check("案例3 輸出檔非空", os.path.getsize(out3) > 0)
        dur3 = media.probe_duration(out3)
        check(f"案例3 時長≈{expected1:.2f}s（實得 {dur3:.2f}s，三者合併）",
              abs(dur3 - expected1) < 0.3, str(dur3))

        # --- 案例 4：缺片頭檔案 → FileNotFoundError ---
        missing_intro = os.path.join(tmp, "不存在的片頭.mp4")
        settings4 = branding.resolve_branding_settings({
            "branding": {"intro_path": missing_intro}})
        try:
            branding.apply_branding(main_path, os.path.join(tmp, "out4.mp4"),
                                    settings=settings4)
            check("案例4 缺片頭應報錯", False)
        except FileNotFoundError as exc:
            check("案例4 訊息含「找不到片頭檔案」",
                  "找不到片頭檔案" in str(exc), str(exc))
        except Exception as exc:  # noqa: BLE001
            check("案例4 缺片頭應報 FileNotFoundError", False, repr(exc))

        # --- 案例 5：完全未設定任何一項 → ValueError ---
        try:
            branding.apply_branding(
                main_path, os.path.join(tmp, "out5.mp4"),
                settings=branding.resolve_branding_settings(None))
            check("案例5 全空應報錯", False)
        except ValueError as exc:
            check("案例5 報 ValueError", True)
        except Exception as exc:  # noqa: BLE001
            check("案例5 應報 ValueError", False, repr(exc))

print("\n" + ("ALL PASS" if not failures else f"FAILURES: {failures}"))
sys.exit(1 if failures else 0)
