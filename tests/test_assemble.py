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
5. 錯誤：素材不存在、輸出蓋到素材、ffmpeg 失敗、中途停下都不留下檔案，目的地原本的
   檔案不動。
6. 給時間軸介面用（第二階段）：新加的素材長什麼樣（圖片 3 秒、影片整段、音樂整首＋
   預設音量＋閃避）、開始時間夾在片內、每段佔輸出的哪一段（超出片尾剪掉、循環到片尾）、
   量素材長度（量不到回 None，不猜）。
7. 修頭尾與子畫面位置（第三階段）：拖頭時進點跟著動、尾巴不動；拖尾最多到素材長度與
   片尾；至少留 MIN_CLIP；循環音樂只能修頭；預設位置認得出來、不認得的算自訂。
8. 預覽用的幾何（第四階段）：疊加的框（輸出指令用的就是它）、素材在框裡等比置中、
   第 t 秒有哪幾段疊加與素材的第幾秒。
"""
import copy
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import assemble  # noqa: E402
from subtitle import cutmarks  # noqa: E402

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
                    {"path": "logo.png", "at": 6, "duration": 2}],
       "music": [{"path": "m.mp3", "at": 1}]}
before = copy.deepcopy(raw)
tl = assemble.normalize(raw)
check("normalize 不改原本的 dict", raw == before)
check("主軌：in 預設 0、圖片預設 3 秒",
      tl["main"] == [{"path": "a.mp4", "in": 1.0, "out": 3.0}, {"path": "b.mp4", "in": 0.0, "out": 2.0},
                     {"path": "still.png", "in": 0.0, "out": assemble.DEFAULT_IMAGE_SECONDS}], str(tl["main"]))
check("疊加：rect 預設整張、audio 預設關", tl["overlays"][1]["rect"] == [0.0, 0.0, 1.0, 1.0]
      and tl["overlays"][0]["audio"] is False and tl["overlays"][1]["out"] == 2.0, str(tl["overlays"]))
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
a_at = cmd.index("a.mp4")
check("沒聲音的主軌補靜音（長度＝片段長）、有聲音的取 in～out（在輸入端跳到進點、只讀那一段）",
      "anullsrc=r=48000:cl=stereo,atrim=duration=2[ma1]" in fc
      and cmd[a_at - 5:a_at] == ["-ss", "1", "-t", "2", "-i"]
      and "[0:a]asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo,apad,"
          "atrim=duration=2[ma0]" in fc
      and "[0:v]setpts=PTS-STARTPTS,scale=" in fc and ":v]trim=" not in fc, " ".join(cmd))
check("主軌接起來：每段縮放置中補黑邊、同一影格率，concat 3 段",
      fc.count("scale=640:360:force_original_aspect_ratio=decrease,pad=640:360") >= 3
      and "[mv0][ma0][mv1][ma1][mv2][ma2]concat=n=3:v=1:a=1[base0][voice]" in fc, fc)
check("圖片用 -loop 1 -t 長度；疊加超出片尾的剪到片尾（2 秒的圖放在 6 秒、片長 7 秒 → 只放 1 秒）",
      cmd[cmd.index("still.png") - 7:cmd.index("still.png")] == ["-loop", "1", "-framerate", "30", "-t", "3", "-i"]
      and cmd[cmd.index("logo.png") - 3:cmd.index("logo.png")] == ["-t", "1", "-i"]
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

# ----- 6. 給時間軸介面用 -----
check("clamp_at：夾在 0～片尾前 MIN_CLIP、取到毫秒",
      [assemble.clamp_at(v, 10) for v in (-3, 0, 4.12345, 9.99, 50)]
      == [0.0, 0.0, 4.123, round(10 - assemble.MIN_CLIP, 3), round(10 - assemble.MIN_CLIP, 3)])
check("new_overlay：圖片放 3 秒、不用量長度",
      assemble.new_overlay("logo.PNG", 2.5, 10) == {"path": "logo.PNG", "at": 2.5, "duration": 3.0})
check("new_overlay：影片整段（in 0、out＝片長、記下素材長度）、開始夾在片內",
      assemble.new_overlay("b.mp4", 12, 10, seconds=4.25)
      == {"path": "b.mp4", "at": round(10 - assemble.MIN_CLIP, 3), "in": 0.0, "out": 4.25, "length": 4.25})
check("new_overlay：影片量不到長度 → 說清楚、不猜",
      "量不到" in (error_of(assemble.new_overlay, "b.mp4", 1, 10, None) or ""))
check("new_overlay：影片太短 → 說清楚",
      "量不到" in (error_of(assemble.new_overlay, "b.mp4", 1, 10, assemble.MIN_CLIP / 2) or ""))
check("new_music：整首（記下素材長度）、預設音量、不循環、講話時壓低",
      assemble.new_music("s.mp3", -1, 10, seconds=95.5)
      == {"path": "s.mp3", "at": 0.0, "in": 0.0, "out": 95.5, "length": 95.5,
          "volume": assemble.DEFAULT_MUSIC_VOLUME, "loop": False, "duck": True})
check("new_music：圖片 → 說清楚", "圖片" in (error_of(assemble.new_music, "a.jpg", 0, 10, 3) or ""))
check("new_music：量不到長度 → 說清楚", "量不到" in (error_of(assemble.new_music, "s.mp3", 0, 10, None) or ""))
check("新加的素材都過得了 normalize（介面加進來的就能直接輸出）",
      len(assemble.normalize({"main": [{"path": "a.mp4", "out": 10}],
                              "overlays": [assemble.new_overlay("logo.png", 9.99, 10),
                                           assemble.new_overlay("b.mp4", 3, 10, 2)],
                              "music": [assemble.new_music("s.mp3", 9.99, 10, 60)]})["music"]) == 1)
check("item_span：圖片用 duration（沒給用預設 3 秒）",
      assemble.item_span("overlays", {"path": "x.png", "at": 1, "duration": 2}, 10) == (1.0, 3.0)
      and assemble.item_span("overlays", {"path": "x.png", "at": 1}, 10) == (1.0, 4.0))
check("item_span：影片用 out−in；超出片尾的剪掉",
      assemble.item_span("overlays", {"path": "b.mp4", "at": 2, "in": 1, "out": 4}, 10) == (2.0, 5.0)
      and assemble.item_span("overlays", {"path": "b.mp4", "at": 8, "in": 0, "out": 5}, 10) == (8.0, 10.0))
check("item_span：音樂循環或沒給 out → 一路到片尾",
      assemble.item_span("music", {"path": "s.mp3", "at": 3, "in": 0, "out": 2, "loop": True}, 10) == (3.0, 10.0)
      and assemble.item_span("music", {"path": "s.mp3", "at": 4, "out": None}, 10) == (4.0, 10.0)
      and assemble.item_span("music", {"path": "s.mp3", "at": 4, "in": 1, "out": 3}, 10) == (4.0, 6.0))
try:
    assemble.item_span("main", {}, 10)
    check("item_span：不認得的軌拋錯", False)
except ValueError:
    check("item_span：不認得的軌拋錯", True)
check("probe_seconds：圖片與不存在的檔回 None（不猜）",
      assemble.probe_seconds("logo.png") is None
      and assemble.probe_seconds(os.path.join(tempfile.gettempdir(), "沒有這個檔.mp4")) is None)

# ----- 7. 修頭尾與子畫面位置 -----
clip = {"path": "b.mp4", "at": 2.0, "in": 1.0, "out": 4.0, "length": 5.0}
before = copy.deepcopy(clip)
check("拖頭往右：開始與進點一起動、尾巴不動（剪掉前面一段）",
      assemble.trim_item("overlays", clip, "start", 3.0, 10)
      == dict(clip, at=3.0, **{"in": 2.0}) and clip == before)
check("拖頭往左：最多拉到進點 0（不能比素材的開頭更早）",
      assemble.trim_item("overlays", clip, "start", 0.0, 10) == dict(clip, at=1.0, **{"in": 0.0}))
check("拖頭往右超過尾巴：至少留 MIN_CLIP",
      assemble.trim_item("overlays", clip, "start", 9.0, 10)
      == dict(clip, at=round(5.0 - assemble.MIN_CLIP, 3), **{"in": round(4.0 - assemble.MIN_CLIP, 3)}))
check("拖尾往右：最多到素材本身的長度（length）",
      assemble.trim_item("overlays", clip, "end", 9.0, 10) == dict(clip, out=5.0))
check("拖尾往右：也不超過片尾", assemble.trim_item("overlays", clip, "end", 9.0, 5.5) == dict(clip, out=4.5))
check("拖尾往左：至少留 MIN_CLIP",
      assemble.trim_item("overlays", clip, "end", 0.0, 10) == dict(clip, out=round(1.0 + assemble.MIN_CLIP, 3)))
check("沒記 length：拖尾只受片尾限制",
      assemble.trim_item("music", {"path": "s.mp3", "at": 0, "in": 0, "out": 2}, "end", 7.5, 10)["out"] == 7.5)
pic = {"path": "x.png", "at": 2.0, "duration": 3.0}
check("圖片拖頭：只改開始與長度（尾巴不動、可以拉到 0）",
      assemble.trim_item("overlays", pic, "start", 0.5, 10) == {"path": "x.png", "at": 0.5, "duration": 4.5})
check("圖片拖尾：沒有素材長度限制，只到片尾",
      assemble.trim_item("overlays", pic, "end", 30, 10) == {"path": "x.png", "at": 2.0, "duration": 8.0})
check("開始時間夾在片內（片尾前 MIN_CLIP）",
      assemble.trim_item("overlays", pic, "start", 20, 3.0)["at"] == round(3.0 - assemble.MIN_CLIP, 3))
looped = {"path": "s.mp3", "at": 1.0, "in": 0.0, "out": 2.0, "loop": True}
check("循環的音樂只能修頭（尾巴一路到片尾）",
      assemble.trimmable_edges("music", looped) == ("start",)
      and assemble.trim_item("music", looped, "end", 5, 10) == looped
      and assemble.trimmable_edges("music", dict(looped, loop=False)) == ("start", "end")
      and assemble.trimmable_edges("music", {"path": "s.mp3", "out": None}) == ("start",))
check("修完的素材過得了 normalize",
      len(assemble.normalize({"main": [{"path": "a.mp4", "out": 10}],
                              "overlays": [assemble.trim_item("overlays", clip, "start", 0, 10),
                                           assemble.trim_item("overlays", pic, "end", 30, 10)]})["overlays"]) == 2)
check("預設位置：沒給 rect＝蓋滿；四個角落認得出來；其他算自訂",
      assemble.overlay_position({}) == "full"
      and [assemble.overlay_position({"rect": assemble.position_rect(k)})
           for k, _l, _r in assemble.OVERLAY_POSITIONS] == [k for k, _l, _r in assemble.OVERLAY_POSITIONS]
      and assemble.overlay_position({"rect": [0.1, 0.1, 0.5, 0.5]}) == "custom")
check("預設位置都在畫布裡（normalize 收得下）",
      len(assemble.normalize({"main": [{"path": "a.mp4", "out": 10}],
                              "overlays": [{"path": "x.png", "rect": r} for _k, _l, r in assemble.OVERLAY_POSITIONS]})
          ["overlays"]) == len(assemble.OVERLAY_POSITIONS))
try:
    assemble.position_rect("middle")
    check("不認得的位置拋錯", False)
except ValueError:
    check("不認得的位置拋錯", True)
r1 = assemble.position_rect("top_right")
r1[0] = 0.5
check("position_rect 回傳複本（改了不影響預設）", assemble.position_rect("top_right")[0] == 0.62)

# ----- 8. 預覽用的幾何 -----
check("overlay_box：蓋滿＝整張畫布；沒給 rect 也是",
      assemble.overlay_box([0, 0, 1, 1], 1280, 720) == (0, 0, 1280, 720)
      and assemble.overlay_box(None, 1280, 720) == (0, 0, 1280, 720))
check("overlay_box：右上小畫面（寬高取偶數）",
      assemble.overlay_box(assemble.position_rect("top_right"), 1280, 720) == (794, 29, 436, 244),
      str(assemble.overlay_box(assemble.position_rect("top_right"), 1280, 720)))
check("overlay_box：奇數尺寸也取偶數",
      all(v % 2 == 0 for v in assemble.overlay_box([0.1, 0.1, 0.333, 0.333], 641, 359)[2:]))
box_tl = {"main": [{"path": "a.mp4", "out": 6}],
          "overlays": [{"path": "x.png", "at": 1, "duration": 2, "rect": [0.62, 0.04, 0.34, 0.34]}]}
fc_box = assemble.build_command(assemble.normalize(box_tl), "o.mp4",
                                {"a.mp4": {"video": True, "audio": True, "width": 640, "height": 360, "fps": 30}},
                                (640, 360, 30))
bx, by, bw, bh = assemble.overlay_box([0.62, 0.04, 0.34, 0.34], 640, 360)
fc_box = fc_box[fc_box.index("-filter_complex") + 1]
check("輸出指令的疊加位置與大小就是 overlay_box（預覽與輸出擺在同一個地方）",
      f"scale={bw}:{bh}:" in fc_box and f"overlay={bx}:{by}:" in fc_box, fc_box)
check("fit_inside：寬的素材放進方框：上下補黑、置中",
      assemble.fit_inside(1920, 1080, 400, 400) == (0.0, 87.5, 400.0, 225.0))
check("fit_inside：直的素材放進寬框：左右補黑、置中",
      assemble.fit_inside(1080, 1920, 640, 360) == (218.75, 0.0, 202.5, 360.0))
check("fit_inside：量不到尺寸就蓋滿框", assemble.fit_inside(0, 0, 100, 50) == (0.0, 0.0, 100.0, 50.0))
ovs = [{"path": "x.png", "at": 1.0, "duration": 2.0},
       {"path": "b.mp4", "at": 2.0, "in": 5.0, "out": 9.0},
       {"path": "c.mp4", "at": 8.0, "in": 0.0, "out": 10.0}]
check("overlays_at：之前沒有", assemble.overlays_at(ovs, 0.5, 10) == [])
check("overlays_at：圖片沒有「第幾秒」", assemble.overlays_at(ovs, 1.0, 10) == [(0, None)])
check("overlays_at：重疊時照順序（後加的在後面＝疊在上面）、影片算出素材的第幾秒",
      assemble.overlays_at(ovs, 2.5, 10) == [(0, None), (1, 5.5)])
check("overlays_at：結束那一刻就不在了（跟輸出的 between 一樣算到結束前）",
      assemble.overlays_at(ovs, 3.0, 10) == [(1, 6.0)])
check("overlays_at：超出片尾的剪掉", assemble.overlays_at(ovs, 9.5, 10) == [(2, 1.5)]
      and assemble.overlays_at(ovs, 10.0, 10) == [])
check("overlays_at：沒有疊加", assemble.overlays_at([], 1, 10) == [] and assemble.overlays_at(None, 1, 10) == [])

# ----- 9. 跟剪點一起輸出 -----
cut_tl = {"main": [{"path": "v.mp4", "in": 0, "out": 20}], "width": 1280,
          "overlays": [{"path": "b.mp4", "at": 3, "in": 1, "out": 9, "rect": [0.62, 0.04, 0.34, 0.34],
                        "audio": True, "length": 10},
                       {"path": "p.png", "at": 4, "duration": 6},
                       {"path": "q.png", "at": 5.2, "duration": 0.5}],
          "music": [{"path": "m.mp3", "at": 2, "in": 0.5, "out": 12.5, "volume": 0.5, "loop": False,
                     "duck": True, "length": 30},
                    {"path": "n.mp3", "at": 5.5, "in": 0, "out": None, "loop": True},
                    {"path": "o.mp3", "at": 5.2, "in": 0, "out": 0.5}]}
cut_keep = [(0, 5), (6, 8), (9.5, 20)]
before = copy.deepcopy(cut_tl)
cut = assemble.apply_cuts(cut_tl, cut_keep)
check("apply_cuts：不改原本的時間軸", cut_tl == before)
check("apply_cuts：主軌只留沒剪掉的那幾段", cut["main"] == [
    {"path": "v.mp4", "in": 0.0, "out": 5.0}, {"path": "v.mp4", "in": 6.0, "out": 8.0},
    {"path": "v.mp4", "in": 9.5, "out": 20.0}], str(cut["main"]))
check("apply_cuts：主軌以外的欄位（畫布）照抄", cut["width"] == 1280)
check("apply_cuts：影片素材跨過剪點切成幾段，進點跟著跳、時間平移、其他欄位照抄", cut["overlays"][:3] == [
    {"path": "b.mp4", "at": 3.0, "in": 1.0, "out": 3.0, "rect": [0.62, 0.04, 0.34, 0.34], "audio": True,
     "length": 10},
    {"path": "b.mp4", "at": 5.0, "in": 4.0, "out": 6.0, "rect": [0.62, 0.04, 0.34, 0.34], "audio": True,
     "length": 10},
    {"path": "b.mp4", "at": 7.0, "in": 7.5, "out": 9.0, "rect": [0.62, 0.04, 0.34, 0.34], "audio": True,
     "length": 10}], str(cut["overlays"]))
check("apply_cuts：圖片剪完頭尾相接、接回一段（1＋2＋0.5 秒）",
      cut["overlays"][3:] == [{"path": "p.png", "at": 4.0, "duration": 3.5}], str(cut["overlays"][3:]))
check("apply_cuts：整段都在剪掉的地方的素材拿掉", all(o["path"] != "q.png" for o in cut["overlays"]))
check("apply_cuts：音樂不跟著剪——平移後從同一個進點一路播，長度縮成剪後那一段", cut["music"][0] == {
    "path": "m.mp3", "at": 2.0, "in": 0.5, "out": 10.0, "volume": 0.5, "loop": False, "duck": True,
    "length": 30}, str(cut["music"][0]))
check("apply_cuts：循環的音樂開頭落在剪掉的地方 → 從接縫開始、一路到片尾",
      cut["music"][1] == {"path": "n.mp3", "at": 5.0, "in": 0, "out": None, "loop": True}, str(cut["music"][1:]))
check("apply_cuts：整段都在剪掉的地方的音樂拿掉", len(cut["music"]) == 2)
norm = assemble.normalize(cut)
check("apply_cuts：結果過得了 normalize、片長＝留下的總長（17.5 秒）",
      assemble.main_duration(norm) == 17.5 and len(norm["overlays"]) == 4, str(assemble.main_duration(norm)))
check("apply_cuts：剪後的素材時間跟字幕用同一套對時（cutmarks.remap_time）",
      [o["at"] for o in cut["overlays"]] == [cutmarks.remap_time(t, cut_keep) for t in (3, 6, 9.5, 4)])

multi = {"main": [{"path": "a.mp4", "in": 10, "out": 14}, {"path": "s.png", "duration": 3},
                  {"path": "c.mp4", "in": 0, "out": 5}]}
cut = assemble.apply_cuts(multi, [(1, 5), (6.5, 12)])
check("apply_cuts：剪點跨過主軌接縫 → 切成兩段；圖片片段用 duration", cut["main"] == [
    {"path": "a.mp4", "in": 11.0, "out": 14.0}, {"path": "s.png", "duration": 1.0},
    {"path": "s.png", "duration": 0.5}, {"path": "c.mp4", "in": 0.0, "out": 5.0}], str(cut["main"]))
cut = assemble.apply_cuts({"main": [{"path": "a.mp4", "in": 0, "out": 3}, {"path": "c.mp4", "in": 0, "out": 5}]},
                          [(0, 3.02), (4, 8)])
check("apply_cuts：保留片段只跨過主軌接縫一點點（後一段只剩 0.02 秒）→ 那一點點不接（接不起來）",
      cut["main"] == [{"path": "a.mp4", "in": 0.0, "out": 3.0}, {"path": "c.mp4", "in": 1.0, "out": 5.0}],
      str(cut["main"]))
check("usable_keep：比 MIN_CLIP 短的保留片段不算（主軌接不起來）",
      assemble.usable_keep([(0, 2), (3, 3.02), (4, 6)]) == [(0.0, 2.0), (4.0, 6.0)])
cut = assemble.apply_cuts({"main": [{"path": "v.mp4", "in": 0, "out": 10}],
                           "overlays": [{"path": "b.mp4", "at": 1.98, "in": 0, "out": 1}]}, [(0, 2), (2.5, 10)])
check("apply_cuts：剪後不到 MIN_CLIP 的那一截拿掉（1.98～2 只剩 0.02 秒），其餘照常",
      cut["overlays"] == [{"path": "b.mp4", "at": 2.0, "in": 0.52, "out": 1.0}], str(cut["overlays"]))
check("apply_cuts：剪完什麼都不剩 → 說清楚",
      "什麼都不剩" in error_of(assemble.apply_cuts, {"main": [{"path": "v.mp4", "out": 5}]}, [(0, 0.01)])
      and "什麼都不剩" in error_of(assemble.apply_cuts, {"main": [{"path": "v.mp4", "out": 5}]}, [(6, 9)]))
many = [(i * 2.0, i * 2.0 + 1.0) for i in range(assemble.MAX_MAIN_CLIPS + 1)]
check("apply_cuts：剪完主軌片段太多 → 說上限",
      "片段太多" in error_of(assemble.apply_cuts, {"main": [{"path": "v.mp4", "out": 1000}]}, many))
check("apply_cuts：剪完畫面素材太多段 → 說上限", "畫面素材太多段" in error_of(
    assemble.apply_cuts, {"main": [{"path": "v.mp4", "out": 400}],
                          "overlays": [{"path": "b.mp4", "at": 0, "out": 300}, {"path": "c.mp4", "at": 0, "out": 300}]},
    [(i * 2.0, i * 2.0 + 1.0) for i in range(150)]))

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
    moving = p("moving.mp4")
    assemble.render({"width": 640, "height": 360, "main": [{"path": p("b.mp4"), "out": 2}],
                     "overlays": [{"path": p("a.mp4"), "at": 0.5, "in": 2, "out": 3}]}, moving)
    same = [diff(gray(moving, t), gray(p("a.mp4"), t - 0.5 + 2)) for t in (0.6, 1.0, 1.4)]
    other = [diff(gray(moving, t), gray(p("a.mp4"), t - 0.5 + 2 + 1 / 30.0)) for t in (0.6, 1.0, 1.4)]
    check("疊加的影片從它自己的 in 開始播：輸出第 t 秒＝來源第 t-0.5+2 秒那一格；1.5 秒後回到主軌",
          max(same) < 1.5 and min(other) > 2 * max(same) and near(pixel(moving, 1.7, 320, 180), (255, 0, 0)),
          f"{[round(x, 2) for x in same]} {[round(x, 2) for x in other]} {pixel(moving, 1.7, 320, 180)}")
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

    # ----- 9. 跟剪點一起輸出：真的剪 -----
    # 主軌 a.mp4（0～4 秒）剪掉 1.5～2.5；B-roll 前 2 秒綠、後 2 秒黃，從 0.5 秒開始蓋在右半邊
    run("-f", "lavfi", "-i", "color=c=0x00c000:size=320x180:rate=30:d=2", "-f", "lavfi",
        "-i", "color=c=yellow:size=320x180:rate=30:d=2", "-filter_complex", "[0:v][1:v]concat=n=2:v=1",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", p("gy.mp4"))
    cut_out = p("cut.mp4")
    cut_result = assemble.render(assemble.apply_cuts(
        {"main": [{"path": p("a.mp4"), "in": 0, "out": 4}],
         "overlays": [{"path": p("gy.mp4"), "at": 0.5, "in": 0, "out": 3.5, "rect": [0.5, 0, 0.5, 1]}]},
        [(0, 1.5), (2.5, 4)]), cut_out)
    check("跟剪點一起輸出：片長＝留下的總長（3 秒）", abs(cut_result["duration"] - 3.0) < 1e-6
          and abs(assemble.probe_seconds(cut_out) - 3.0) < 0.1, str(assemble.probe_seconds(cut_out)))
    early, seam = pixel(cut_out, 1.0, 480, 180), pixel(cut_out, 1.8, 480, 180)
    check("B-roll 跟著剪：接縫前是素材的第 0.5 秒（綠），接縫後直接跳到素材的第 2.3 秒（黃）",
          near(early, (0, 192, 0)) and near(seam, (255, 255, 0)), f"{early} {seam}")
    def left(frame):
        return [frame[r * 96 + c] for r in range(54) for c in range(40)]
    main_after = left(gray(cut_out, 1.8))
    same, unshifted = diff(main_after, left(gray(p("a.mp4"), 2.8))), diff(main_after, left(gray(p("a.mp4"), 1.8)))
    check("主軌接縫後是原片的第 2.8 秒（中間 1 秒剪掉）：左半邊跟原片那一格一樣、跟沒平移的那格不一樣",
          same < 1.5 and unshifted > 4 * max(same, 0.5), f"{same:.2f} {unshifted:.2f}")

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
    check("ffmpeg 失敗 → RuntimeError（組合失敗）、不留下半支檔案（含暫存檔）",
          msg is not None and msg.startswith("組合失敗") and not os.path.exists(p("y.mp4"))
          and not [n for n in os.listdir(tmp) if ".tmp-" in n], str(msg))
    class HalfWritten:
        """假的 ffmpeg：先寫出半支輸出檔，再失敗（真的 ffmpeg 寫到一半出錯就是這樣）。"""

        def __init__(self, command, **_kw):
            with open(command[-1], "wb") as fh:
                fh.write(b"half")
            self.stdout = type("O", (), {"__iter__": lambda _s: iter(["out_time_us=500000\n"]),
                                         "close": lambda _s: None})()
            self.stderr = type("E", (), {"read": lambda _s: "寫到一半壞了", "close": lambda _s: None})()

        def wait(self):
            return 1

        def kill(self):
            pass

    real_subprocess = assemble.subprocess  # 只換 assemble 自己啟動 ffmpeg 的那一個，量素材的 ffprobe 照真的跑
    assemble.subprocess = type("FakeSubprocess", (), {"Popen": HalfWritten, "PIPE": -1})
    try:
        try:
            assemble.render(timeline, p("half.mp4"))
            msg = None
        except RuntimeError as exc:
            msg = str(exc)
    finally:
        assemble.subprocess = real_subprocess
    check("ffmpeg 寫到一半失敗 → 說原因、半支的暫存檔清掉、目的地沒有檔案",
          msg == "組合失敗：寫到一半壞了" and not os.path.exists(p("half.mp4"))
          and not [n for n in os.listdir(tmp) if ".tmp-" in n], f"{msg} {os.listdir(tmp)}")
    keep = p("keep.mp4")
    with open(keep, "wb") as fh:
        fh.write(b"old")

    def stop(ratio, _msg):
        if ratio > 0:
            raise KeyboardInterrupt("使用者按了取消")
    try:
        assemble.render(timeline, keep, stop)
        stopped = False
    except KeyboardInterrupt:
        stopped = True
    leftovers = [n for n in os.listdir(tmp) if ".tmp-" in n]
    check("中途停下（進度回呼拋例外）→ ffmpeg 停掉、暫存檔清掉、目的地原本的檔案不動",
          stopped and not leftovers and open(keep, "rb").read() == b"old", f"{stopped} {leftovers}")
    m_len, b_len = assemble.probe_seconds(p("m.m4a")), assemble.probe_seconds(p("b.mp4"))
    check("probe_seconds：量得到聲音檔與影片的長度（到毫秒）",
          m_len is not None and abs(m_len - 1.5) < 0.05 and b_len is not None and abs(b_len - 3) < 0.05,
          f"{m_len} {b_len}")
    broken = p("broken.mp4")
    with open(broken, "wb") as fh:
        fh.write(b"not a video")
    check("probe_seconds：壞掉的檔回 None", assemble.probe_seconds(broken) is None)
    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 多段素材與多軌核心測試全數通過。")
