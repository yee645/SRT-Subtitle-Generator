# -*- coding: utf-8 -*-
"""
v2.3.6 回歸測試：字幕「垂直位置」拉到上方（置頂）時，燒出來真的在上方。

v2.3.5 以前，`position_y` ≤ 0.33 走 ASS 置頂（Alignment 8），但上邊距仍用
`1 - position_y` 算——`0.15` 的上邊距是 85% 畫面高，字燒在接近底部的地方；
Tk 的即時預覽卻畫在上方 15%，**預覽和成品不一致**。

這裡守：

1. ASS 標頭：置頂邊距 = `position_y`、置底邊距 = `1 - position_y`（沒有被
   連帶改到）、置中對齊不變；邊距下限 10。
2. **真的燒一格**（ffmpeg＋libass，有才跑）：量白字實際落在畫面哪幾列——
   置頂時字的頂邊在 `position_y` 那條線上、整句在畫面上半部；置底時字的底
   邊在 `position_y` 上；位置越小字越高（單調）。
3. 燒錄位置與 Tk 預覽（以 `position_y` 為字的中心）差不到一個字高。
4. 版號與 CHANGELOG。
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle.exporter import _ass_margin_v, cues_to_ass  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def style_fields(position_y):
    ass = cues_to_ass([{"start": 0, "end": 1, "text": "a"}],
                      {"position_y": position_y})
    line = next(x for x in ass.splitlines() if x.startswith("Style:"))
    fields = line.split(",")
    return int(fields[18]), int(fields[21])


# ===== 1. ASS 標頭 ======================================================

check("置頂 0.15：Alignment 8、上邊距 162（=1080×0.15），不再是 918",
      style_fields(0.15) == (8, 162), str(style_fields(0.15)))
check("置頂 0.33（置頂的上限）：上邊距 356",
      style_fields(0.33) == (8, 356), str(style_fields(0.33)))
check("置頂 0.0：邊距下限 10", style_fields(0.0) == (8, 10), str(style_fields(0.0)))
check("置底 0.88（預設）沒被連帶改到：Alignment 2、下邊距 129",
      style_fields(0.88) == (2, 129), str(style_fields(0.88)))
check("置底 1.0：邊距下限 10", style_fields(1.0) == (2, 10), str(style_fields(1.0)))
check("置中 0.5：Alignment 5", style_fields(0.5)[0] == 5, str(style_fields(0.5)))
check("置頂時邊距隨位置遞增（越往下邊距越大）",
      [_ass_margin_v(p, 1080) for p in (0.05, 0.15, 0.25, 0.33)]
      == sorted(_ass_margin_v(p, 1080) for p in (0.05, 0.15, 0.25, 0.33)))

# ===== 2. 真的燒一格 ====================================================

W, H = 1280, 720
FONT_SIZE = 48
FONT = "WenQuanYi Zen Hei"


def has_libass():
    if not shutil.which("ffmpeg"):
        return False
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                         capture_output=True, text=True).stdout
    return " ass " in out


def burn_rows(position_y, tmp):
    """燒一格黑底白字，回傳有字的列範圍 (最上列, 最下列)。"""
    ass = os.path.join(tmp, "burn.ass")
    with open(ass, "w", encoding="utf-8") as fh:
        fh.write(cues_to_ass([{"start": 0, "end": 5, "text": "Subtitle Test"}],
                             {"position_y": position_y, "font_family": FONT,
                              "font_size": FONT_SIZE, "stroke_width": 0}))
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
         f"color=black:s={W}x{H}:d=1", "-vf", "ass=burn.ass",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True, cwd=tmp).stdout
    rows = [y for y in range(H) if max(raw[y * W:(y + 1) * W]) > 128]
    return (rows[0], rows[-1]) if rows else None


if not has_libass():
    print("SKIP 沒有 ffmpeg（libass）：略過真的燒錄")
else:
    with tempfile.TemporaryDirectory() as tmp:
        got = {p: burn_rows(p, tmp) for p in (0.10, 0.15, 0.30, 0.88)}
        print("    量到的字列範圍（畫面高 %d）：%s" % (H, got))
        check("每一格都真的燒出字", all(got.values()), str(got))
        if all(got.values()):
            top15, bottom15 = got[0.15]
            # ASS 字級是整行高，以 PlayRes 1080 為基準等比縮放。
            line_h = FONT_SIZE * H / 1080
            # 字的頂邊在 position_y 那條線上：ASS 的字框（行高）上緣就在線上，
            # 墨跡再往下一點點（行高與字形之間的空白），容許 12px（720p）。
            check("置頂 0.15：字的頂邊在畫面 15% 那條線上（12px 內）",
                  0 <= top15 - int(H * 0.15) <= 12, f"{top15} vs {int(H * 0.15)}")
            check("置頂 0.15：整句都在畫面上半部（修正前在 85% 附近）",
                  bottom15 < H / 2, f"最下列 {bottom15}")
            check("置頂 0.30：整句仍在畫面上半部",
                  got[0.30][1] < H / 2, str(got[0.30]))
            check("位置越小字越高：0.10 < 0.15 < 0.30 < 0.88",
                  got[0.10][0] < got[0.15][0] < got[0.30][0] < got[0.88][0],
                  str(got))
            bottom88 = got[0.88][1]
            check("置底 0.88：字的底邊在畫面 88% 那條線上（12px 內）",
                  0 <= int(H * 0.88) - bottom88 <= 12, f"{bottom88} vs {int(H * 0.88)}")
            # Tk 預覽以 position_y 為字的中心畫；燒錄以它為頂邊（置頂）或
            # 底邊（置底），差半個字高左右，不會再差到半個畫面。
            for p, (a, b) in ((0.15, got[0.15]), (0.88, got[0.88])):
                center = (a + b) / 2
                check(f"位置 {p}：燒錄的字心與 Tk 預覽的字心差不到一個字高",
                      abs(center - H * p) <= line_h,
                      f"燒錄字心 {center} 預覽 {H * p} 行高 {line_h}")

# ===== 3. 版號與 CHANGELOG ==============================================

m = re.search(r'APP_VERSION = "(\d+)\.(\d+)\.(\d+)"', _read("updater.py"))
version = tuple(int(x) for x in m.groups()) if m else (0, 0, 0)
check("APP_VERSION 已進到 2.3.6 以上", version >= (2, 3, 6), str(version))
heads = re.findall(r"^## (v2\.3\.6\D.*)$", _read("CHANGELOG.md"), re.M)
check("CHANGELOG 有 v2.3.6 這一條（只有一條）", len(heads) == 1, str(heads))
check("CHANGELOG 的 v2.3.6 講到置頂燒錄位置",
      bool(re.search(r"## v2\.3\.6[^\n]*\n(?:(?!\n## ).)*置頂", _read("CHANGELOG.md"), re.S)))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v2.3.6 置頂燒錄位置測試全數通過。")
