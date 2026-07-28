# -*- coding: utf-8 -*-
"""v1.25.0 新功能測試：Shorts 字幕安全區（避開平台介面遮擋）。"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import shorts
from subtitle.exporter import cues_to_ass

# ===== 1. resolve_shorts_settings：新增欄位的預設值與夾限 =====
s = shorts.resolve_shorts_settings(None)
check("預設啟用安全區", s["safe_zone_enabled"] is True)
check("預設頂端保留 0.06", s["safe_zone_top"] == 0.06)
check("預設底部保留 0.22", s["safe_zone_bottom"] == 0.22)
check("預設左右保留 0.05", s["safe_zone_side"] == 0.05)

s2 = shorts.resolve_shorts_settings({"shorts": {
    "safe_zone_enabled": False, "safe_zone_top": 0.99,
    "safe_zone_bottom": 0.0, "safe_zone_side": 0.9}})
check("安全區可關閉", s2["safe_zone_enabled"] is False)
check("頂端保留夾上限 0.20", s2["safe_zone_top"] == 0.20)
check("底部保留夾下限 0.10", s2["safe_zone_bottom"] == 0.10)
check("左右保留夾上限 0.15", s2["safe_zone_side"] == 0.15)

s3 = shorts.resolve_shorts_settings(
    {"shorts": {"safe_zone_top": "bad"}})
check("非數值回預設", s3["safe_zone_top"] == 0.06)

# ===== 2. apply_safe_zone：垂直位置夾限邏輯 =====
style_bottom_unsafe = {"position_y": 0.95, "font_size": 30}
adjusted = shorts.apply_safe_zone(style_bottom_unsafe, True, 0.06, 0.22)
check("底部超界時夾到安全上限", adjusted["position_y"] == 0.78, str(adjusted))
check("其餘樣式欄位不受影響", adjusted["font_size"] == 30)

style_top_unsafe = {"position_y": 0.01}
adjusted_top = shorts.apply_safe_zone(style_top_unsafe, True, 0.06, 0.22)
check("頂端超界時夾到安全下限", adjusted_top["position_y"] == 0.06, str(adjusted_top))

style_already_safe = {"position_y": 0.5}
same = shorts.apply_safe_zone(style_already_safe, True, 0.06, 0.22)
check("已在安全範圍內時原樣回傳（同一物件）", same is style_already_safe)

disabled = shorts.apply_safe_zone(style_bottom_unsafe, False, 0.06, 0.22)
check("停用安全區時原樣回傳（同一物件）", disabled is style_bottom_unsafe)

check("style 為 None 時原樣回傳 None",
      shorts.apply_safe_zone(None, True, 0.06, 0.22) is None)
check("style 為空 dict 時原樣回傳",
      shorts.apply_safe_zone({}, True, 0.06, 0.22) == {})

# ===== 3. cues_to_ass：margin_lr 覆蓋左右邊界 =====
cues = [{"start": 0.0, "end": 1.0, "text": "測試"}]
ass_default = cues_to_ass(cues, {"position_y": 0.88}, resolution=(1080, 1920))
check("預設左右邊界為 20px",
      ",0,0,1,2,0,2,20,20," in ass_default, ass_default)

ass_custom = cues_to_ass(cues, {"position_y": 0.88},
                         resolution=(1080, 1920), margin_lr=54)
check("自訂左右邊界正確反映在 Style 行",
      ",54,54," in ass_custom, ass_custom)

# ===== 4. config／GUI 靜態掃描 =====
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from config import DEFAULT_CONFIG
shorts_cfg = DEFAULT_CONFIG.get("shorts", {})
check("config 預設含安全區四個欄位",
      all(k in shorts_cfg for k in
          ("safe_zone_enabled", "safe_zone_top",
           "safe_zone_bottom", "safe_zone_side")),
      str(shorts_cfg))

with open(os.path.join(root, "gui", "review_window.py"),
          encoding="utf-8") as fp:
    gui_src = fp.read()
check("GUI 有字幕安全區設定列",
      "字幕安全區" in gui_src and "shorts_safezone_var" in gui_src)
check("GUI 安全區勾選為 ttk.Checkbutton（非 classic tk）",
      "tk.Checkbutton(" not in gui_src.replace("ttk.Checkbutton(", ""))
check("GUI 呼叫 cut_vertical_clip 時有帶入安全區參數",
      "safe_zone_enabled=settings[" in gui_src)

# ===== 5. 真實 ffmpeg 端到端：實際燒錄後以像素驗證字幕確實避開保留區 =====
import shutil
if shutil.which("ffmpeg") and shutil.which("ffprobe"):
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src.mp4")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=blue:s=1920x1080:d=3:r=25",
             "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=3",
             "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-shortest", src],
            capture_output=True, timeout=60)

        # 明顯偏底部（0.95）的字幕位置：真實情境中會被平台底部介面遮住。
        unsafe_style = {
            "font_family": "DejaVu Sans", "font_size": 60,
            "text_color": "#FFFFFF", "stroke_color": "#000000",
            "stroke_width": 2, "position_y": 0.95,
        }
        test_cues = [{"start": 0.0, "end": 3.0, "text": "TEST"}]

        out_unsafe = os.path.join(tmp, "unsafe.mp4")
        shorts.cut_vertical_clip(
            src, 0.0, 3.0, out_unsafe, mode="crop", focus_x=0.5,
            style=unsafe_style, cues=test_cues,
            safe_zone_enabled=False)
        check("實測：關閉安全區時輸出檔已產生", os.path.exists(out_unsafe))

        out_safe = os.path.join(tmp, "safe.mp4")
        shorts.cut_vertical_clip(
            src, 0.0, 3.0, out_safe, mode="crop", focus_x=0.5,
            style=unsafe_style, cues=test_cues,
            safe_zone_enabled=True, safe_zone_top=0.06,
            safe_zone_bottom=0.22, safe_zone_side=0.05)
        check("實測：啟用安全區時輸出檔已產生", os.path.exists(out_safe))

        def probe_size(path):
            proc = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "stream=width,height", "-of",
                 "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, timeout=30)
            parts = proc.stdout.split()
            return int(parts[0]), int(parts[1])

        check("實測：輸出解析度為 1080x1920",
              probe_size(out_unsafe) == (1080, 1920)
              and probe_size(out_safe) == (1080, 1920))

        def bottom_band_ymax(path, band_frac=0.22):
            frame = os.path.join(tmp, "frame_" + os.path.basename(path)
                                 + ".png")
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-i", path, "-ss", "1.5", "-vframes", "1", frame],
                capture_output=True, timeout=30)
            band_h = round(1920 * band_frac)
            band_y = 1920 - band_h
            proc = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "info", "-y",
                 "-i", frame, "-vf",
                 f"crop=1080:{band_h}:0:{band_y},signalstats,"
                 "metadata=print", "-f", "null", "-"],
                capture_output=True, text=True, timeout=30)
            for line in proc.stderr.splitlines():
                if "YMAX=" in line:
                    return float(line.split("YMAX=")[1])
            return None

        ymax_unsafe = bottom_band_ymax(out_unsafe)
        ymax_safe = bottom_band_ymax(out_safe)
        check("實測：關閉安全區時字幕確實落入底部保留區（亮像素）",
              ymax_unsafe is not None and ymax_unsafe > 150,
              f"ymax_unsafe={ymax_unsafe}")
        check("實測：啟用安全區後底部保留區內無字幕亮像素",
              ymax_safe is not None and ymax_safe < 100,
              f"ymax_safe={ymax_safe}")
else:
    print("SKIP 實測（無 ffmpeg／ffprobe）")

print()
if failures:
    print(f"共 {len(failures)} 項失敗：{failures}")
    sys.exit(1)
print("test_v1250 全部通過")
