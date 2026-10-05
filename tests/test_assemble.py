# -*- coding: utf-8 -*-
"""
3.0 第 7 項第一階段：多段素材與多軌的核心（subtitle/assemble.py）。

1. normalize：合理的補齊預設值、不改原本的；不合理的說清楚是哪一軌第幾段哪裡不對。
2. 時間對照：主軌每段在輸出上的位置；輸出第 t 秒播的是哪段的第幾秒（接縫算後一段）。
3. 組指令（不必真的有檔案）：沒聲音的主軌補靜音、只有聲音的不能放主軌、B-roll 預設不帶
   聲音、圖片用 -loop、循環音樂用 -stream_loop、閃避用 sidechaincompress、輸出長度＝主軌。
4. 真的輸出（ffmpeg）：長度、尺寸；每一秒的畫面是對的那一段的對的那一格（跟來源比）；
   子畫面只在它的時間出現、只蓋它的位置；圖片；直式素材補黑邊；
   沒聲音的片段有音樂就有聲音、音量 0 就沒聲音；閃避真的把音樂壓低。
5. 錯誤：素材不存在、輸出蓋到素材、ffmpeg 失敗都不留下檔案。
"""
import copy
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import assemble  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def error_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except assemble.AssembleError as exc:
        return str(exc)
    return None


# ----- 1. normalize -----
raw = {"main": [{"path": "a.mp4", "in": 1, "out": 3}, {"path": "b.mp4", "out": 2},
                {"path": "still.png"}],
       "overlays": [{"path": "c.mp4", "at": 0.5, "out": 1, "rect": [0.5, 0, 0.5, 0.5]},
                    {"path": "logo.png", "at": 6, "duration": 1}],
       "music": [{"path": "m.mp3", "at": 1}]}
before = copy.deepcopy(raw)
tl = assemble.normalize(raw)
check("normalize 不改原本的 dict", raw == before)
check("主軌：in 預設 0、圖片預設 3 秒",
      tl["main"] == [{"path": "a.mp4", "in": 1.0, "out": 3.0}, {"path": "b.mp4", "in": 0.0, "out": 2.0},
                     {"path": "still.png", "in": 0.0, "out": assemble.DEFAULT_IMAGE_SECONDS}], str(tl["main"]))
check("疊加：rect 預設整張、audio 預設關", tl["overlays"][1]["rect"] == [0.0, 0.0, 1.0, 1.0]
      and tl["overlays"][0]["audio"] is False and tl["overlays"][1]["out"] == 1.0, str(tl["overlays"]))
check("音樂：音量預設 0.35、不循環、不閃避、out 不限",
      tl["music"] == [{"path": "m.mp3", "at": 1.0, "in": 0.0, "out": None, "volume": 0.35,
                       "loop": False, "duck": False}], str(tl["music"]))
check("畫布沒指定就留空（render 用主軌第一段量到的）",
      (tl["width"], tl["height"], tl["fps"]) == (None, None, None))
check("畫布寬高取偶數", assemble.normalize(dict(raw, width=1081, height=721))["width"] == 1080)

bad_cases = [
    ({"main": []}, "主軌是空的"),
    ({"main": [{"path": "a.mp4", "in": 1}]}, "主軌第 1 段少了 out"),
    ({"main": [{"path": "a.mp4", "in": 1, "out": 1.02}]}, "主軌第 1 段太短"),
    ({"main": [{"path": "a.mp4", "in": -1, "out": 2}]}, "in 不能小於 0"),
    ({"main": [{"path": "a.mp4", "out": "x"}]}, "out 不是數字"),
    ({"main": [{"out": 2}]}, "主軌第 1 段沒有指定檔案"),
    ({"main": [{"path": "a.mp4", "out": 2}], "overlays": [{"path": "c.mp4", "at": 2, "out": 1}]},
     "疊加軌第 1 段的 at（2.0 秒）要在 0～2.000 秒"),
    ({"main": [{"path": "a.mp4", "out": 2}], "overlays": [{"path": "c.mp4", "out": 1, "rect": [0.6, 0, 0.5, 0.5]}]},
     "疊加軌第 1 段的 rect 要在畫布裡"),
    ({"main": [{"path": "a.mp4", "out": 2}], "music": [{"path": "m.mp3", "volume": 3}]}, "volume 要在 0～2"),
    ({"main": [{"path": "a.mp4", "out": 2}], "music": [{"path": "m.mp3", "at": 5}]}, "音樂軌第 1 段的 at"),
    ({"main": [{"path": "a.mp4", "out": 2}], "width": 8}, "畫布的 width"),
    ({"main": [{"path": "a.mp4", "out": 2}], "fps": 0}, "畫布的 fps"),
    ({"main": [{"path": "a.mp4", "out": 2}] * (assemble.MAX_MAIN_CLIPS + 1)}, "主軌片段太多"),
]
wrong = [(want, error_of(assemble.normalize, case)) for case, want in bad_cases]
wrong = [(want, got) for want, got in wrong if not got or want not in got]
check(f"不合理的 {len(bad_cases)} 種時間軸都拋 AssembleError，訊息寫出哪一軌第幾段哪裡不對",
      not wrong, str(wrong))

# ----- 2. 時間對照 -----
spans = assemble.main_spans(tl)
check("主軌每段在輸出上的位置", [(s, e) for s, e, _c in spans] == [(0.0, 2.0), (2.0, 4.0), (4.0, 7.0)]
      and assemble.main_duration(tl) == 7.0, str(spans))
probes = {0: (0, 1.0), 1.5: (0, 2.5), 2.0: (1, 0.0), 3.999: (1, 1.999), 4.0: (2, 0.0), 6.9: (2, 2.9),
          7.0: None, 9: None}
got = {t: assemble.source_at(tl, t) for t in probes}
check("輸出第 t 秒播哪段的第幾秒（接縫算後一段、超出片長回 None）", got == probes, str(got))

# ----- 3. 組指令 -----
media = {"a.mp4": {"video": True, "audio": True}, "b.mp4": {"video": True, "audio": False},
         "c.mp4": {"video": True, "audio": True}, "m.mp3": {"video": False, "audio": True}}
cmd = assemble.build_command(tl, "out.mp4", media, (640, 360, 30))
fc = cmd[cmd.index("-filter_complex") + 1]
check("沒聲音的主軌補靜音（長度＝片段長）、有聲音的取 in～out",
      "anullsrc=r=48000:cl=stereo,atrim=duration=2[ma1]" in fc
      and "[0:a]atrim=start=1:end=3," in fc, fc)
check("主軌接起來：每段縮放置中補黑邊、同一影格率，concat 3 段",
      fc.count("scale=640:360:force_original_aspect_ratio=decrease,pad=640:360") >= 3
      and "[mv0][ma0][mv1][ma1][mv2][ma2]concat=n=3:v=1:a=1[base0][voice]" in fc, fc)
check("圖片用 -loop 1 -t 長度；疊加超出片尾的剪到片尾",
      cmd[cmd.index("still.png") - 7:cmd.index("still.png")] == ["-loop", "1", "-framerate", "30", "-t", "3", "-i"]
      and "between(t,6,7)" in fc, " ".join(cmd))
check("B-roll 子畫面：右上四分之一、只在 0.5～1.5 秒，預設不帶聲音",
      "overlay=320:0:eof_action=pass:enable='between(t,0.5,1.5)'" in fc
      and "[ov0]" in fc and "[oa0]" not in fc, fc)
check("輸出長度＝主軌總長、只有一條聲音時直接用它",
      cmd[cmd.index("-t", len(cmd) - 12) + 1] == "7" and "amix" in fc, " ".join(cmd[-12:]))
tl_audio = assemble.normalize(dict(raw, overlays=[dict(raw["overlays"][0], audio=True)], music=[]))
fc2 = assemble.build_command(tl_audio, "o.mp4", media)[assemble.build_command(tl_audio, "o.mp4", media).index("-filter_complex") + 1]
check("B-roll 打開聲音 → 延後到 at 再混進去", "adelay=500|500[oa0]" in fc2
      and "[voice][oa0]amix=inputs=2" in fc2, fc2)
tl_music = assemble.normalize({"main": raw["main"][:2], "music": [
    {"path": "m.mp3", "at": 1, "loop": True, "duck": True},
    {"path": "m.mp3", "at": 0, "in": 0, "out": 0.5, "loop": True, "duck": True, "volume": 0}]})
cmd3 = assemble.build_command(tl_music, "o.mp4", media)
fc3 = cmd3[cmd3.index("-filter_complex") + 1]
check("循環音樂：整首循環用 -stream_loop、循環一小段用 aloop；從 at 開始、剪到片尾",
      cmd3.count("-stream_loop") == 2 and "aloop=loop=-1" in fc3 and "adelay=1000|1000[mu0]" in fc3
      and "atrim=duration=3,volume=0.35" in fc3 and "volume=0," in fc3, fc3)
check("兩段都閃避：人聲分成三份（一份輸出、兩份當側鏈）；沒給閃避參數用手動預設值",
      "threshold=0.0600:ratio=8" in fc3 and
      "[voice]asplit=2[voice][sidechain]" in fc3 and "[sidechain]asplit=2[sc0][sc1]" in fc3
      and fc3.count("sidechaincompress") == 2 and "[voice][md0][md1]amix=inputs=3" in fc3, fc3)
check("沒畫面的放主軌 → 說清楚（只有聲音的請放音樂軌）",
      "只有聲音的請放音樂軌" in (error_of(assemble.build_command, assemble.normalize(
          {"main": [{"path": "m.mp3", "out": 2}]}), "o.mp4", media) or ""))
check("沒聲音的放音樂軌 → 說清楚", "沒有聲音" in (error_of(assemble.build_command, assemble.normalize(
    {"main": [{"path": "a.mp4", "out": 2}], "music": [{"path": "b.mp4"}]}), "o.mp4", media) or ""))

if not shutil.which("ffmpeg"):
    print("SKIP 這個環境沒有 ffmpeg：略過真的輸出")
else:
    tmp = tempfile.mkdtemp()

    def run(*args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)

    def p(name):
        return os.path.join(tmp, name)

    run("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-f", "lavfi", "-i", "sine=frequency=440",
        "-t", "4", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", p("a.mp4"))
    run("-f", "lavfi", "-i", "color=c=red:size=360x640:rate=25", "-t", "3", "-c:v", "libx264",
        "-preset", "ultrafast", p("b.mp4"))
    run("-f", "lavfi", "-i", "color=c=blue:size=320x180:rate=30", "-t", "5", "-c:v", "libx264",
        "-preset", "ultrafast", p("c.mp4"))
    run("-f", "lavfi", "-i", "color=c=0x00c000:size=200x200", "-frames:v", "1", p("g.png"))
    run("-f", "lavfi", "-i", "sine=frequency=880", "-t", "1.5", p("m.m4a"))

    def pixel(path, t, x, y, size="640x360"):
        raw_rgb = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1",
                                  "-s", size, "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                                 capture_output=True, check=True).stdout
        w = int(size.split("x")[0])
        i = (y * w + x) * 3
        return tuple(raw_rgb[i:i + 3])

    def gray(path, t):
        return subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1",
                               "-vf", "scale=96:54,format=gray", "-f", "rawvideo", "pipe:1"],
                              capture_output=True, check=True).stdout

    def diff(a, b):
        return sum(abs(x - y) for x, y in zip(a, b)) / max(len(a), 1)

    def loudness(path, start, length):
        out = subprocess.run(["ffmpeg", "-v", "info", "-ss", str(start), "-t", str(length), "-i", path,
                              "-vn", "-af", "volumedetect", "-f", "null", "-"],
                             capture_output=True, text=True).stderr
        for line in out.splitlines():
            if "mean_volume" in line:
                return float(line.split("mean_volume:")[1].split("dB")[0])
        return None

    def near(color, want, tol=40):
        return all(abs(c - w) <= tol for c, w in zip(color, want))

    timeline = {"main": [{"path": p("a.mp4"), "in": 1, "out": 3}, {"path": p("b.mp4"), "in": 0, "out": 2}],
                "overlays": [{"path": p("c.mp4"), "at": 0.5, "out": 1, "rect": [0.5, 0, 0.5, 0.5]},
                             {"path": p("g.png"), "at": 2.5, "duration": 1}],
                "music": [{"path": p("m.m4a"), "at": 2, "loop": True}]}
    out = p("out.mp4")
    ratios = []
    result = assemble.render(timeline, out, lambda r, _m: ratios.append(r))
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height",
                            "-of", "csv=p=0", out], capture_output=True, text=True).stdout.split()
    check("輸出：4 秒、畫布＝主軌第一段的 640x360、進度走到 1.0",
          result["duration"] == 4.0 and (result["width"], result["height"]) == (640, 360)
          and "640,360" in probe and abs(float(probe[-1]) - 4.0) < 0.1 and ratios[-1] == 1.0,
          f"{result} {probe}")
    same = [diff(gray(out, t), gray(p("a.mp4"), t + 1)) for t in (0.1, 0.3, 1.9)]
    other = [diff(gray(out, t), gray(p("a.mp4"), t + 1 + 1 / 30.0)) for t in (0.1, 0.3, 1.9)]
    check("主軌第一段：輸出第 t 秒＝來源第 t+1 秒那一格（差一格就明顯不同）",
          max(same) < 1.5 and min(other) > 2 * max(same),
          f"{[round(x, 2) for x in same]} {[round(x, 2) for x in other]}")
    check("子畫面只在 0.5～1.5 秒、只蓋右上角",
          near(pixel(out, 0.9, 480, 90), (0, 0, 255)) and not near(pixel(out, 0.3, 480, 90), (0, 0, 255))
          and not near(pixel(out, 1.7, 480, 90), (0, 0, 255)) and not near(pixel(out, 0.9, 160, 270), (0, 0, 255)),
          f"{pixel(out, 0.9, 480, 90)} {pixel(out, 0.3, 480, 90)} {pixel(out, 1.7, 480, 90)}")
    check("接縫之後是第二段（直式紅色、左右補黑邊）",
          near(pixel(out, 2.05, 320, 180), (255, 0, 0)) and near(pixel(out, 2.05, 20, 180), (0, 0, 0)),
          f"{pixel(out, 2.05, 320, 180)} {pixel(out, 2.05, 20, 180)}")
    check("圖片在 2.5～3.5 秒蓋滿（正方形補黑邊），之後回到主軌",
          near(pixel(out, 3.0, 320, 180), (0, 192, 0)) and near(pixel(out, 3.0, 20, 180), (0, 0, 0))
          and near(pixel(out, 3.8, 320, 180), (255, 0, 0)),
          f"{pixel(out, 3.0, 320, 180)} {pixel(out, 3.8, 320, 180)}")
    music_part = loudness(out, 2.2, 1.6)
    check("第二段本身沒聲音，從 2 秒開始的循環音樂讓它有聲音", music_part is not None and music_part > -40,
          str(music_part))
    quiet = dict(timeline, music=[dict(timeline["music"][0], volume=0)])
    assemble.render(quiet, p("quiet.mp4"))
    silent = loudness(p("quiet.mp4"), 2.2, 1.6)
    check("音樂音量 0 → 那一段沒聲音（對照組，證明上面的聲音是音樂來的）", silent is not None and silent < -80,
          str(silent))
    plain = {"main": [{"path": p("a.mp4"), "in": 0, "out": 4}],
             "music": [{"path": p("m.m4a"), "loop": True, "volume": 1.0}]}
    assemble.render(plain, p("plain.mp4"))
    assemble.render(dict(plain, music=[dict(plain["music"][0], duck=True)]), p("duck.mp4"))

    def band(path, freq):
        """只留某個頻率附近再量音量：分開人聲（440）與音樂（880）。"""
        out = subprocess.run(["ffmpeg", "-v", "info", "-i", path, "-vn", "-af",
                              f"bandpass=f={freq}:width_type=h:w=60,volumedetect", "-f", "null", "-"],
                             capture_output=True, text=True).stderr
        return float(out.split("mean_volume:")[1].split("dB")[0])

    loud, ducked = band(p("plain.mp4"), 880), band(p("duck.mp4"), 880)
    voice_a, voice_b = band(p("plain.mp4"), 440), band(p("duck.mp4"), 440)
    check("閃避（預設自動適應人聲音量）：講話時音樂（880Hz）壓低 10dB 以上，人聲（440Hz）不變",
          loud - ducked > 10 and abs(voice_a - voice_b) < 1, f"音樂 {loud}→{ducked}，人聲 {voice_a}→{voice_b}")
    assemble.render(dict(plain, music=[dict(plain["music"][0], duck=True)]), p("duck_manual.mp4"),
                    config={"ducking": {"auto_sensitivity": False, "duck_sensitivity": 0.3}})
    manual = band(p("duck_manual.mp4"), 880)
    check("關掉自動、手動門檻 0.3（比人聲大）→ 幾乎不壓（照 config 的 ducking 走）",
          loud - manual < 1, f"{loud}→{manual}")

    # ----- 5. 錯誤 -----
    msg = error_of(assemble.render, {"main": [{"path": p("none.mp4"), "out": 1}]}, p("x.mp4"))
    check("素材不存在 → 說是哪個檔", msg is not None and "none.mp4" in msg and not os.path.exists(p("x.mp4")),
          str(msg))
    size = os.path.getsize(p("a.mp4"))
    msg = error_of(assemble.render, timeline, p("a.mp4"))
    check("輸出選到其中一個素材 → 擋下、素材沒被蓋", msg is not None and "同一個檔案" in msg
          and os.path.getsize(p("a.mp4")) == size, str(msg))
    with open(p("broken.mp4"), "wb") as fh:
        fh.write(b"\x00" * 4096)
    real_probe = assemble.probe_media
    assemble.probe_media = lambda path: {"video": True, "audio": False, "width": 640, "height": 360, "fps": 30}
    try:
        try:
            assemble.render({"main": [{"path": p("broken.mp4"), "out": 1}]}, p("y.mp4"))
            msg = None
        except RuntimeError as exc:
            msg = str(exc)
    finally:
        assemble.probe_media = real_probe
    check("ffmpeg 失敗 → RuntimeError（組合失敗）、不留下半支檔案",
          msg is not None and msg.startswith("組合失敗") and not os.path.exists(p("y.mp4")), str(msg))
    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 多段素材與多軌核心測試全數通過。")
