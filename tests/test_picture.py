# -*- coding: utf-8 -*-
"""
3.0 第 9 項第一階段：畫面調整的核心（subtitle/picture.py）與它接進多軌輸出（assemble）。

1. normalize：預設值、範圍、錯誤訊息；changes 只留改過的；is_identity。
2. filters：順序（裁 → 轉 → 翻 → 調色）、算式；什麼都不做時是空的。
3. crop_box／output_size：跟 ffmpeg 真的裁出來的大小一模一樣（奇數寬高也是）。
4. ffmpeg 真的跑：亮度、對比、飽和度、裁切、旋轉、翻轉都量像素驗。
5. assemble：主軌與畫面素材帶 adjust；normalize 只記改過的；濾鏡放在縮放之前；
   第一段轉成直的時畫布跟著變；輸出量像素驗。
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import assemble, picture  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def error_of(fn, *args):
    try:
        fn(*args)
    except picture.PictureError as exc:
        return str(exc)
    return None


# ----- 1. normalize -----
check("沒給＝全部預設", picture.normalize(None) == {
    "brightness": 0.0, "contrast": 1.0, "saturation": 1.0, "crop": [0.0, 0.0, 1.0, 1.0],
    "rotate": 0, "flip_h": False, "flip_v": False})
raw = {"brightness": "0.25", "rotate": 450, "crop": (0.1, 0.2, 0.5, 0.6), "flip_v": 1}
got = picture.normalize(raw)
check("數字字串、轉 450 度（＝90）、tuple 的裁切、1 當 True 都收，不改原本的 dict",
      got["brightness"] == 0.25 and got["rotate"] == 90 and got["crop"] == [0.1, 0.2, 0.5, 0.6]
      and got["flip_v"] is True and raw["rotate"] == 450, str(got))
check("changes：只留跟預設不一樣的", picture.changes(raw) == {
    "brightness": 0.25, "crop": [0.1, 0.2, 0.5, 0.6], "rotate": 90, "flip_v": True})
check("is_identity：轉 360 度、亮度 0、裁整張＝什麼都不做",
      picture.is_identity({"rotate": 360, "brightness": 0, "crop": [0, 0, 1, 1]})
      and not picture.is_identity({"saturation": 0}))
bad = [
    ("x", "要是 dict"),
    ({"gamma": 2}, "不認得的項目：gamma"),
    ({"brightness": 1.5}, "亮度要在 -1～1 之間（現在是 1.5）"),
    ({"contrast": -0.1}, "對比要在 0～2 之間"),
    ({"saturation": 4}, "飽和度要在 0～3 之間"),
    ({"brightness": "亮"}, "亮度不是數字"),
    ({"brightness": float("nan")}, "亮度不是有限的數字"),
    ({"crop": [0, 0, 0.02, 1]}, "裁切太小"),
    ({"crop": [0.6, 0, 0.5, 1]}, "裁切要在畫面裡"),
    ({"crop": [0, 0, 1]}, "四個數字"),
    ({"crop": "全部"}, "四個數字"),
    ({"crop": [0, 0, 1, 1, 0]}, "四個數字"),
    ({"crop": [0, 0, float("nan"), 1]}, "四個數字"),
    ({"rotate": 45}, "旋轉只能是 0／90／180／270 度（現在是 45）"),
    ({"rotate": 90.5}, "旋轉只能是"),
]
wrong = [(want, error_of(picture.normalize, case)) for case, want in bad]
wrong = [(want, msg) for want, msg in wrong if not msg or want not in msg]
check(f"不合理的 {len(bad)} 種調整都拋 PictureError，說哪一項怎麼不對", not wrong, str(wrong))
check("錯誤訊息帶上是哪一段（where）", "主軌第 2 段的亮度" in (error_of(
    picture.normalize, {"brightness": 9}, "主軌第 2 段") or ""))

# ----- 2. filters -----
check("什麼都不做：沒有濾鏡", picture.filters(None) == [] and picture.filters({"rotate": 0}) == [])
check("順序：裁 → 轉 → 翻 → 調色；裁切用 iw／ih 的算式、寬高取偶數", picture.filters(
    {"brightness": 0.2, "crop": [0.1, 0, 0.5, 1], "rotate": 90, "flip_h": True}) == [
    "crop=w=trunc(iw*0.5/2)*2:h=trunc(ih*1/2)*2:x=trunc(iw*0.1):y=trunc(ih*0)",
    "transpose=clock", "hflip", "eq=brightness=0.2:contrast=1:saturation=1"])
check("轉 180 度＝左右加上下翻；270 度＝逆時針", picture.filters({"rotate": 180}) == ["hflip", "vflip"]
      and picture.filters({"rotate": 270}) == ["transpose=cclock"])
check("只調色：一個 eq", picture.filters({"saturation": 0, "contrast": 1.5}) == [
    "eq=brightness=0:contrast=1.5:saturation=0"])

# ----- 3. crop_box／output_size -----
check("crop_box：像素、寬高取偶數", picture.crop_box({"crop": [0.1, 0.2, 0.5, 0.5]}, 641, 361)
      == (64, 72, 320, 180), str(picture.crop_box({"crop": [0.1, 0.2, 0.5, 0.5]}, 641, 361)))
check("output_size：轉 90／270 寬高對調、180 不對調",
      picture.output_size({"rotate": 90}, 640, 360) == (360, 640)
      and picture.output_size({"rotate": 270, "crop": [0, 0, 0.5, 1]}, 640, 360) == (360, 320)
      and picture.output_size({"rotate": 180}, 640, 360) == (640, 360))

if not shutil.which("ffmpeg"):
    print("SKIP 這個環境沒有 ffmpeg：略過真的輸出")
else:
    tmp = tempfile.mkdtemp()

    def p(name):
        return os.path.join(tmp, name)

    def run(*args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)

    def probe_size(path):
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=width,height", "-of", "csv=p=0", path], capture_output=True, text=True).stdout
        w, h = out.strip().split(",")[:2]
        return int(w), int(h)

    def pixel(path, x, y, t=0.5):
        w, h = probe_size(path)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        i = (int(y * h) * w + int(x * w)) * 3
        return tuple(raw[i:i + 3])

    def near(color, want, tol=40):
        return len(color) == 3 and all(abs(c - v) <= tol for c, v in zip(color, want))

    # 測試畫面：左上紅、右上藍、左下綠、右下白（看得出裁、轉、翻）；另一支是灰
    run("-f", "lavfi", "-i", "color=c=red:size=320x180:d=1", "-f", "lavfi", "-i", "color=c=blue:size=320x180:d=1",
        "-f", "lavfi", "-i", "color=c=0x00ff00:size=320x180:d=1", "-f", "lavfi", "-i", "color=c=white:size=320x180:d=1",
        "-filter_complex", "[0][1]hstack[t];[2][3]hstack[b];[t][b]vstack", "-r", "30",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", p("quad.mp4"))
    run("-f", "lavfi", "-i", "color=c=0x808080:size=320x180:d=1", "-r", "30",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", p("gray.mp4"))
    run("-f", "lavfi", "-i", "color=c=0xc03030:size=320x180:d=1", "-r", "30",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", p("red.mp4"))

    def apply(src, adjust, name):
        run("-i", p(src), "-vf", ",".join(picture.filters(adjust)), "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", p(name))
        return p(name)

    # 裁切大小跟 crop_box 一模一樣（原畫面 640x360；再加一支奇數大小的）
    # color 濾鏡會把奇數大小捨成偶數，所以先產 640x360 再縮成 641x361（yuv444p 才放得下奇數寬高）
    run("-f", "lavfi", "-i", "color=c=red:size=640x360:d=1", "-vf", "scale=641:361,format=yuv444p",
        "-c:v", "libx264", "-preset", "ultrafast", p("odd.mp4"))
    check("奇數大小的測試片真的是 641x361", probe_size(p("odd.mp4")) == (641, 361), str(probe_size(p("odd.mp4"))))
    sizes_ok = []
    for src, (w, h) in (("quad.mp4", (640, 360)), ("odd.mp4", (641, 361))):
        for crop in ([0.1, 0.2, 0.5, 0.5], [0.33, 0.07, 0.41, 0.77], [0, 0, 0.999, 0.999]):
            for rotate in (0, 90):
                adj = {"crop": crop, "rotate": rotate}
                out = apply(src, adj, "size.mp4")
                sizes_ok.append((src, crop, rotate, probe_size(out), picture.output_size(adj, w, h)))
    mismatched = [s for s in sizes_ok if s[3] != s[4]]
    check("crop_box／output_size 跟 ffmpeg 真的裁出來的大小一模一樣（12 種，含奇數寬高與轉 90 度）",
          not mismatched, str(mismatched))

    out = apply("quad.mp4", {"crop": [0, 0, 0.5, 0.5]}, "crop.mp4")
    check("裁左上四分之一：整張都是紅", near(pixel(out, 0.1, 0.1), (255, 0, 0)) and near(pixel(out, 0.9, 0.9), (255, 0, 0)),
          f"{pixel(out, 0.1, 0.1)} {pixel(out, 0.9, 0.9)}")
    out = apply("quad.mp4", {"crop": [0.5, 0.5, 0.5, 0.5]}, "crop2.mp4")
    check("裁右下四分之一：整張都是白（x、y 起點對）", near(pixel(out, 0.5, 0.5), (255, 255, 255)),
          str(pixel(out, 0.5, 0.5)))
    out = apply("quad.mp4", {"rotate": 90}, "rot90.mp4")
    check("順時針轉 90 度：原本左上的紅跑到右上、左下的綠跑到左上",
          near(pixel(out, 0.75, 0.25), (255, 0, 0)) and near(pixel(out, 0.25, 0.25), (0, 255, 0))
          and probe_size(out) == (360, 640), f"{pixel(out, 0.75, 0.25)} {pixel(out, 0.25, 0.25)}")
    out = apply("quad.mp4", {"rotate": 270}, "rot270.mp4")
    check("逆時針轉（270 度）：原本右上的藍跑到左上", near(pixel(out, 0.25, 0.25), (0, 0, 255)),
          str(pixel(out, 0.25, 0.25)))
    out = apply("quad.mp4", {"rotate": 180}, "rot180.mp4")
    check("轉 180 度：左上變成白（原本右下）", near(pixel(out, 0.25, 0.25), (255, 255, 255)),
          str(pixel(out, 0.25, 0.25)))
    out = apply("quad.mp4", {"flip_h": True}, "fliph.mp4")
    check("左右翻：左上變成藍", near(pixel(out, 0.25, 0.25), (0, 0, 255)), str(pixel(out, 0.25, 0.25)))
    out = apply("quad.mp4", {"flip_v": True}, "flipv.mp4")
    check("上下翻：左上變成綠", near(pixel(out, 0.25, 0.25), (0, 255, 0)), str(pixel(out, 0.25, 0.25)))
    out = apply("quad.mp4", {"rotate": 90, "flip_h": True}, "rotflip.mp4")
    check("先轉再翻（翻的是轉完的方向）：轉 90 度後左右翻，左上變成紅",
          near(pixel(out, 0.25, 0.25), (255, 0, 0)), str(pixel(out, 0.25, 0.25)))
    gray = pixel(p("gray.mp4"), 0.5, 0.5)
    bright = pixel(apply("gray.mp4", {"brightness": 0.2}, "bright.mp4"), 0.5, 0.5)
    dark = pixel(apply("gray.mp4", {"brightness": -0.2}, "dark.mp4"), 0.5, 0.5)
    check("亮度 +0.2／−0.2：灰變亮／變暗（各差 40 以上）",
          bright[0] - gray[0] > 40 and gray[0] - dark[0] > 40, f"{dark} {gray} {bright}")
    red = pixel(p("red.mp4"), 0.5, 0.5)
    mono = pixel(apply("red.mp4", {"saturation": 0}, "mono.mp4"), 0.5, 0.5)
    vivid = pixel(apply("red.mp4", {"saturation": 2}, "vivid.mp4"), 0.5, 0.5)
    check("飽和度 0：紅變灰（三色差 10 以內）；飽和度 2：更紅（紅綠差變大）",
          max(mono) - min(mono) < 10 and (vivid[0] - vivid[1]) > (red[0] - red[1]) + 20, f"{red} {mono} {vivid}")
    # eq 的對比只動亮度：白往中間灰靠、灰（正中間）不動；對比 2 時偏亮的灰更亮
    flat = pixel(apply("quad.mp4", {"contrast": 0.3}, "flat.mp4"), 0.75, 0.75)
    still = pixel(apply("gray.mp4", {"contrast": 0.3}, "still.mp4"), 0.5, 0.5)
    check("對比 0.3：白那一格變成中間的灰（三色都在 120～200）、正中間的灰幾乎不動",
          all(120 < c < 200 for c in flat) and all(abs(a - b) < 12 for a, b in zip(still, gray)),
          f"{flat} {still} {gray}")

    # ----- 5. assemble -----
    tl = assemble.normalize({"main": [{"path": "a.mp4", "out": 2, "adjust": {"rotate": 0, "saturation": 0}},
                                      {"path": "b.mp4", "out": 2, "adjust": {"rotate": 0}}],
                             "overlays": [{"path": "c.mp4", "at": 0, "out": 1, "adjust": {"flip_h": True}}]})
    check("assemble.normalize：只記改過的；什麼都沒改就不記 adjust",
          tl["main"][0]["adjust"] == {"saturation": 0.0} and "adjust" not in tl["main"][1]
          and tl["overlays"][0]["adjust"] == {"flip_h": True}, str(tl))
    msg = None
    try:
        assemble.normalize({"main": [{"path": "a.mp4", "out": 2}, {"path": "b.mp4", "out": 2,
                                                                   "adjust": {"rotate": 33}}]})
    except assemble.AssembleError as exc:
        msg = str(exc)
    check("assemble.normalize：調整不合理時說是哪一段", msg is not None and "主軌第 2 段的旋轉" in msg, str(msg))
    cmd = assemble.build_command(tl, "o.mp4", {}, (640, 360, 30))
    fc = cmd[cmd.index("-filter_complex") + 1]
    check("build_command：調色放在 setpts 之後、縮放置中之前；沒調整的那段沒有", (
        "[0:v]setpts=PTS-STARTPTS,eq=brightness=0:contrast=1:saturation=0,scale=640:360" in fc
        and "[1:v]setpts=PTS-STARTPTS,scale=640:360" in fc
        and "[2:v]setpts=PTS-STARTPTS,hflip,scale=" in fc), fc)
    stills = assemble.normalize({"main": [{"path": "a.png", "duration": 2, "adjust": {"flip_v": True}}],
                                 "overlays": [{"path": "c.png", "at": 0, "duration": 1, "adjust": {"rotate": 180}}]})
    cmd = assemble.build_command(stills, "o.mp4", {}, (640, 360, 30))
    fc = cmd[cmd.index("-filter_complex") + 1]
    check("build_command：主軌、疊加放圖片時也照調整加濾鏡",
          "[0:v]setpts=PTS-STARTPTS,vflip,scale=640:360" in fc
          and "[1:v]setpts=PTS-STARTPTS,hflip,vflip,scale=640:360" in fc, fc)

    portrait = p("portrait.mp4")
    result = assemble.render({"main": [{"path": p("quad.mp4"), "out": 1, "adjust": {"rotate": 90}}],
                              "overlays": [{"path": p("gray.mp4"), "at": 0, "out": 1, "rect": [0, 0.5, 1, 0.5],
                                            "adjust": {"brightness": 0.3}}]}, portrait)
    check("render：第一段轉成直的 → 畫布跟著變直的（360x640），不會補一圈黑邊",
          (result["width"], result["height"]) == (360, 640) and probe_size(portrait) == (360, 640),
          f"{result} {probe_size(portrait)}")
    check("render：主軌轉過（右上是紅）、疊加的灰調亮過（下半比原本的灰亮）",
          near(pixel(portrait, 0.75, 0.25), (255, 0, 0)) and pixel(portrait, 0.5, 0.75)[0] > gray[0] + 40,
          f"{pixel(portrait, 0.75, 0.25)} {pixel(portrait, 0.5, 0.75)}")
    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 畫面調整核心測試全數通過。")
