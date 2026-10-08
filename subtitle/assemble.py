# -*- coding: utf-8 -*-
"""
3.0 第 7 項：多段素材與多軌——時間軸的資料模型，以及把它輸出成一支影片。

到第 6 項為止，所有流程都假設「一支輸入影片」。這裡把一條時間軸描述成三種軌：

* **主軌 `main`**：一段接一段播的片段 `{"path", "in", "out"}`（取來源的 in～out 秒）。
  不同尺寸、不同影格率的素材都縮放置中補黑邊到同一張畫布、轉成同一個影格率；
  沒有聲音的片段補靜音，接起來才不會錯位。
* **疊加軌 `overlays`**：B-roll／圖片 `{"path", "at", "in", "out", "rect", "audio"}`，
  在輸出時間 `at` 秒開始蓋在主軌上，長度 `out - in`。`rect` 是畫布上的位置與大小
  （0～1 的比例：`[x, y, w, h]`，省略＝整張蓋滿）。圖片沒有 in/out，用 `duration`。
  `audio` 預設 False：B-roll 通常只要畫面，聲音要的話再打開。
* **音樂軌 `music`**：`{"path", "at", "in", "out", "volume", "loop", "duck"}`，從輸出
  時間 `at` 開始放；`loop` 會重複到片尾；`duck` 講話時自動把音樂壓低（沿用
  `audio.py` 背景音樂閃避：config 的 `ducking` 參數，「自動適應人聲音量」打開時先量
  主軌人聲的響度再算門檻——手動的 0.06 對一般音量的人聲只壓得下 3dB 左右，實測）。

整條時間軸的長度＝主軌總長；疊加與音樂超出片尾的部分剪掉。

資料都是單純的 dict／list（可以直接存成 JSON，第 10 項專案檔會用到）。
`normalize` 檢查並補齊預設值；`build_command` 只組指令（素材的「有沒有畫面／聲音、
是不是圖片」由呼叫端傳進來，測試不必真的有檔案）；`render` 真的跑 ffmpeg。

零 GUI 依賴。
"""
from __future__ import annotations

import os
import subprocess
from typing import Callable, Optional

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff")
SAMPLE_RATE = 48000
MIN_CLIP = 0.05          # 片段最短幾秒（太短的 trim 會讓 concat 出錯）
MAX_MAIN_CLIPS = 200     # filter_complex 太長會很慢；跟 jumpcut.MAX_SEGMENTS 同一個量級
DEFAULT_IMAGE_SECONDS = 3.0
DEFAULT_MUSIC_VOLUME = 0.35   # 與 audio.DEFAULT_DUCKING["music_volume"] 一致
DEFAULT_DUCK = {"threshold": 0.06, "ratio": 8.0}  # 與 audio.DEFAULT_DUCKING 的手動預設值一致


class AssembleError(ValueError):
    """時間軸本身不合理（沒有主軌、片段長度不對、位置超出畫布…）。"""


# ===== 資料模型 ===========================================================

def is_image(path: str) -> bool:
    return os.path.splitext(str(path))[1].lower() in IMAGE_EXTS


def _num(value, name, where):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise AssembleError(f"{where}的 {name} 不是數字：{value!r}") from None
    if value != value or value in (float("inf"), float("-inf")):
        raise AssembleError(f"{where}的 {name} 不是有限的數字")
    return value


def _span(item, where, image_default=None):
    """取出 (in, out)；圖片用 duration。"""
    if image_default is not None and is_image(item.get("path", "")):
        duration = _num(item.get("duration", image_default), "duration", where)
        start, end = 0.0, duration
    else:
        start = _num(item.get("in", 0.0), "in", where)
        if "out" not in item:
            raise AssembleError(f"{where}少了 out（取到來源的第幾秒）")
        end = _num(item["out"], "out", where)
    if start < 0:
        raise AssembleError(f"{where}的 in 不能小於 0")
    if end - start < MIN_CLIP:
        raise AssembleError(f"{where}太短（{end - start:.3f} 秒），至少要 {MIN_CLIP} 秒")
    return round(start, 3), round(end, 3)


def normalize(timeline: dict) -> dict:
    """
    檢查時間軸並補齊預設值，回傳新的 dict（不改原本的）。不合理就拋 AssembleError，
    訊息寫出是哪一軌第幾段、哪裡不對。不檢查檔案存不存在（那是 render 的事）。
    """
    if not isinstance(timeline, dict):
        raise AssembleError("時間軸要是 dict")
    main = timeline.get("main") or []
    if not main:
        raise AssembleError("主軌是空的：至少要放一段素材")
    if len(main) > MAX_MAIN_CLIPS:
        raise AssembleError(f"主軌片段太多（{len(main)} 段，上限 {MAX_MAIN_CLIPS}）")
    out = {"width": None, "height": None, "fps": None, "main": [], "overlays": [], "music": []}
    for key in ("width", "height"):
        if timeline.get(key) is not None:
            value = int(_num(timeline[key], key, "畫布"))
            if value < 16 or value > 7680:
                raise AssembleError(f"畫布的 {key} 要在 16～7680 之間")
            out[key] = value - value % 2
    if timeline.get("fps") is not None:
        fps = _num(timeline["fps"], "fps", "畫布")
        if not 1 <= fps <= 120:
            raise AssembleError("畫布的 fps 要在 1～120 之間")
        out["fps"] = fps

    for i, clip in enumerate(main, 1):
        where = f"主軌第 {i} 段"
        if not clip.get("path"):
            raise AssembleError(f"{where}沒有指定檔案")
        start, end = _span(clip, where, image_default=DEFAULT_IMAGE_SECONDS)
        out["main"].append({"path": str(clip["path"]), "in": start, "out": end})
    total = main_duration(out)

    for i, item in enumerate(timeline.get("overlays") or [], 1):
        where = f"疊加軌第 {i} 段"
        if not item.get("path"):
            raise AssembleError(f"{where}沒有指定檔案")
        start, end = _span(item, where, image_default=DEFAULT_IMAGE_SECONDS)
        at = round(_num(item.get("at", 0.0), "at", where), 3)
        if at < 0 or at >= total:
            raise AssembleError(f"{where}的 at（{at} 秒）要在 0～{total:.3f} 秒（片長）之間")
        rect = item.get("rect") or [0.0, 0.0, 1.0, 1.0]
        try:
            rect = [float(v) for v in rect]
        except (TypeError, ValueError):
            raise AssembleError(f"{where}的 rect 要是四個數字 [x, y, w, h]") from None
        if len(rect) != 4 or rect[2] <= 0 or rect[3] <= 0 or min(rect[:2]) < 0 \
                or rect[0] + rect[2] > 1.0001 or rect[1] + rect[3] > 1.0001:
            raise AssembleError(f"{where}的 rect 要在畫布裡（0～1 的比例，[x, y, w, h]）")
        out["overlays"].append({"path": str(item["path"]), "at": at, "in": start, "out": end,
                                "rect": rect, "audio": bool(item.get("audio", False))})

    for i, item in enumerate(timeline.get("music") or [], 1):
        where = f"音樂軌第 {i} 段"
        if not item.get("path"):
            raise AssembleError(f"{where}沒有指定檔案")
        at = round(_num(item.get("at", 0.0), "at", where), 3)
        if at < 0 or at >= total:
            raise AssembleError(f"{where}的 at（{at} 秒）要在 0～{total:.3f} 秒（片長）之間")
        start = round(_num(item.get("in", 0.0), "in", where), 3)
        end = item.get("out")
        if end is not None:
            end = round(_num(end, "out", where), 3)
            if end - start < MIN_CLIP:
                raise AssembleError(f"{where}太短")
        volume = _num(item.get("volume", DEFAULT_MUSIC_VOLUME), "volume", where)
        if not 0 <= volume <= 2:
            raise AssembleError(f"{where}的 volume 要在 0～2 之間")
        out["music"].append({"path": str(item["path"]), "at": at, "in": start, "out": end,
                             "volume": volume, "loop": bool(item.get("loop", False)),
                             "duck": bool(item.get("duck", False))})
    return out


def main_duration(timeline: dict) -> float:
    """主軌總長（＝輸出片長）。"""
    return round(sum(c["out"] - c["in"] for c in timeline["main"]), 3)


def main_spans(timeline: dict) -> list:
    """主軌每一段在輸出時間軸上的位置：[(開始, 結束, 片段), ...]。"""
    spans, t = [], 0.0
    for clip in timeline["main"]:
        end = round(t + clip["out"] - clip["in"], 3)
        spans.append((round(t, 3), end, clip))
        t = end
    return spans


def source_at(timeline: dict, t: float):
    """
    輸出時間 t 秒播的是主軌哪一段的第幾秒：回傳 (第幾段, 來源秒數)；超出片長回 None。
    接縫上算後一段（跟播放器「到了就換下一段」一致）。
    """
    spans = main_spans(timeline)
    for index, (start, end, clip) in enumerate(spans):
        if start <= t < end:
            return index, round(clip["in"] + (t - start), 3)
    return None


# ===== 組指令 =============================================================

def _fmt(value):
    return f"{value:.3f}".rstrip("0").rstrip(".") or "0"


def build_command(timeline: dict, output_path: str, media: dict,
                  canvas: Optional[tuple] = None, duck: Optional[dict] = None) -> list:
    """
    組出 ffmpeg 指令。timeline 要先 normalize。

    media：{路徑: {"video": bool, "audio": bool}}——每個素材有沒有畫面、有沒有聲音
    （圖片看副檔名）。canvas：(寬, 高, fps)，時間軸沒指定的部分用它補（render 會拿主軌
    第一段量到的值）；兩邊都沒有就用 1920x1080、30fps。duck：閃避的 {"threshold", "ratio"}，
    省略用 DEFAULT_DUCK。
    """
    duck = dict(DEFAULT_DUCK, **(duck or {}))
    cw, ch, cfps = canvas or (None, None, None)
    width = timeline["width"] or cw or 1920
    height = timeline["height"] or ch or 1080
    fps = timeline["fps"] or cfps or 30.0
    width, height = int(width) - int(width) % 2, int(height) - int(height) % 2
    total = main_duration(timeline)

    inputs, filters = [], []

    def add_input(path, image_seconds=None, loop=False):
        if image_seconds is not None:
            inputs.extend(["-loop", "1", "-framerate", _fmt(fps), "-t", _fmt(image_seconds), "-i", path])
        elif loop:
            inputs.extend(["-stream_loop", "-1", "-i", path])
        else:
            inputs.extend(["-i", path])
        return inputs.count("-i") - 1

    def info(path):
        found = media.get(path) or media.get(os.path.abspath(path)) or {}
        if is_image(path):
            return {"video": True, "audio": False}
        return {"video": bool(found.get("video", True)), "audio": bool(found.get("audio", False))}

    def fit(label_in, label_out, w, h, trim=None, pts_offset=0.0):
        chain = [f"[{label_in}]"]
        parts = []
        if trim:
            parts.append(f"trim=start={_fmt(trim[0])}:end={_fmt(trim[1])}")
        parts.append("setpts=PTS-STARTPTS" + (f"+{_fmt(pts_offset)}/TB" if pts_offset else ""))
        parts.append(f"scale={w}:{h}:force_original_aspect_ratio=decrease")
        parts.append(f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black")
        parts.append("setsar=1")
        parts.append(f"fps={_fmt(fps)}")
        filters.append("".join(chain) + ",".join(parts) + f"[{label_out}]")

    # ---- 主軌 ----
    for n, clip in enumerate(timeline["main"]):
        meta = info(clip["path"])
        length = clip["out"] - clip["in"]
        if is_image(clip["path"]):
            idx = add_input(clip["path"], image_seconds=length)
            fit(f"{idx}:v", f"mv{n}", width, height)
        else:
            idx = add_input(clip["path"])
            if not meta["video"]:
                raise AssembleError(f"主軌第 {n + 1} 段沒有畫面：{os.path.basename(clip['path'])}"
                                    "（只有聲音的請放音樂軌）")
            fit(f"{idx}:v", f"mv{n}", width, height, trim=(clip["in"], clip["out"]))
        if meta["audio"]:
            filters.append(f"[{idx}:a]atrim=start={_fmt(clip['in'])}:end={_fmt(clip['out'])},"
                           f"asetpts=PTS-STARTPTS,aformat=sample_rates={SAMPLE_RATE}:"
                           f"channel_layouts=stereo,apad,atrim=duration={_fmt(length)}[ma{n}]")
        else:
            filters.append(f"anullsrc=r={SAMPLE_RATE}:cl=stereo,atrim=duration={_fmt(length)}[ma{n}]")
    pairs = "".join(f"[mv{n}][ma{n}]" for n in range(len(timeline["main"])))
    filters.append(f"{pairs}concat=n={len(timeline['main'])}:v=1:a=1[base0][voice]")

    # ---- 疊加軌 ----
    video = "base0"
    extra_audio = []
    for n, item in enumerate(timeline["overlays"]):
        meta = info(item["path"])
        length = min(item["out"] - item["in"], total - item["at"])
        ox, oy, ow, oh = overlay_box(item["rect"], width, height)
        if is_image(item["path"]):
            idx = add_input(item["path"], image_seconds=length)
            fit(f"{idx}:v", f"ov{n}", ow, oh, pts_offset=item["at"])
        else:
            if not meta["video"]:
                raise AssembleError(f"疊加軌第 {n + 1} 段沒有畫面：{os.path.basename(item['path'])}")
            idx = add_input(item["path"])
            fit(f"{idx}:v", f"ov{n}", ow, oh, trim=(item["in"], item["in"] + length),
                pts_offset=item["at"])
        end = round(item["at"] + length, 3)
        filters.append(f"[{video}][ov{n}]overlay={ox}:{oy}:eof_action=pass:"
                       f"enable='between(t,{_fmt(item['at'])},{_fmt(end)})'[base{n + 1}]")
        video = f"base{n + 1}"
        if item["audio"] and meta["audio"] and not is_image(item["path"]):
            delay = int(round(item["at"] * 1000))
            filters.append(f"[{idx}:a]atrim=start={_fmt(item['in'])}:end={_fmt(item['in'] + length)},"
                           f"asetpts=PTS-STARTPTS,aformat=sample_rates={SAMPLE_RATE}:"
                           f"channel_layouts=stereo,adelay={delay}|{delay}[oa{n}]")
            extra_audio.append(f"oa{n}")

    # ---- 音樂軌 ----
    music = []
    ducked = any(m["duck"] for m in timeline["music"])
    if ducked:
        filters.append("[voice]asplit=2[voice][sidechain]")
        side_count = sum(1 for m in timeline["music"] if m["duck"])
        if side_count > 1:
            filters.append("[sidechain]asplit=" + str(side_count)
                           + "".join(f"[sc{k}]" for k in range(side_count)))
            side_labels = [f"sc{k}" for k in range(side_count)]
        else:
            side_labels = ["sidechain"]
    for n, item in enumerate(timeline["music"]):
        meta = info(item["path"])
        if not meta["audio"]:
            raise AssembleError(f"音樂軌第 {n + 1} 段沒有聲音：{os.path.basename(item['path'])}")
        room = round(total - item["at"], 3)
        idx = add_input(item["path"], loop=item["loop"])
        trim = f"atrim=start={_fmt(item['in'])}"
        if item["out"] is not None and not item["loop"]:
            trim += f":end={_fmt(item['out'])}"
        length_cap = room
        if item["loop"] and item["out"] is not None:
            # 循環一段（in～out）：先取那一段再重複
            trim = f"atrim=start={_fmt(item['in'])}:end={_fmt(item['out'])},aloop=loop=-1:size=2e9"
        delay = int(round(item["at"] * 1000))
        filters.append(f"[{idx}:a]{trim},asetpts=PTS-STARTPTS,"
                       f"aformat=sample_rates={SAMPLE_RATE}:channel_layouts=stereo,"
                       f"atrim=duration={_fmt(length_cap)},volume={_fmt(item['volume'])},"
                       f"adelay={delay}|{delay}[mu{n}]")
        label = f"mu{n}"
        if item["duck"]:
            side = side_labels.pop(0)
            filters.append(f"[{label}][{side}]sidechaincompress=threshold={duck['threshold']:.4f}:"
                           f"ratio={_fmt(duck['ratio'])}:attack=5:release=300:makeup=1[md{n}]")
            label = f"md{n}"
        music.append(label)

    mix = ["voice"] + extra_audio + music
    if len(mix) > 1:
        filters.append("".join(f"[{m}]" for m in mix)
                       + f"amix=inputs={len(mix)}:duration=first:dropout_transition=0:normalize=0[aout]")
        audio_label = "aout"
    else:
        audio_label = "voice"

    return (["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y"] + inputs
            + ["-filter_complex", ";".join(filters),
               "-map", f"[{video}]", "-map", f"[{audio_label}]",
               "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-t", _fmt(total),
               "-progress", "pipe:1", output_path])


# ===== 給時間軸介面用 =====================================================
# 介面（gui_qt）只負責畫與拖；「新加進來的素材長什麼樣、佔時間軸的哪一段、拖到哪裡
# 要夾住」都在這裡，之後換介面不用重寫。

TRACK_KINDS = ("overlays", "music")


def probe_seconds(path: str) -> Optional[float]:
    """
    素材片長（秒）。量不到（沒有 ffprobe、檔案壞掉、圖片）回傳 None——不猜：
    `media.probe_duration` 失敗時回 60 秒，拿來當素材長度會憑空多出一段。
    """
    import shutil
    if is_image(path) or not shutil.which("ffprobe"):
        return None
    try:
        done = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                               "-of", "default=noprint_wrappers=1:nokey=1", path],
                              capture_output=True, timeout=30)
        value = float((done.stdout or b"").decode("utf-8", errors="ignore").strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return round(value, 3) if done.returncode == 0 and value > 0 else None


def clamp_at(at: float, total: float) -> float:
    """開始時間夾在 0～片尾前 MIN_CLIP 秒（再往後就放不下任何東西）。"""
    return round(max(0.0, min(float(at), float(total) - MIN_CLIP)), 3)


def new_overlay(path: str, at: float, total: float, seconds: Optional[float] = None) -> dict:
    """
    在 at 秒加一段疊加：圖片放 DEFAULT_IMAGE_SECONDS 秒；影片整段（seconds＝它的片長，
    量不到就拋 AssembleError）。位置預設蓋滿整張畫面，聲音預設關。

    影片與音樂另外記 `length`（素材本身多長），修頭尾時才知道最多能拉到哪；normalize
    不看它，輸出不受影響。
    """
    at = clamp_at(at, total)
    if is_image(path):
        return {"path": path, "at": at, "duration": DEFAULT_IMAGE_SECONDS}
    if not seconds or seconds < MIN_CLIP:
        raise AssembleError(f"量不到這段影片有多長：{os.path.basename(path)}")
    seconds = round(float(seconds), 3)
    return {"path": path, "at": at, "in": 0.0, "out": seconds, "length": seconds}


def new_music(path: str, at: float, total: float, seconds: Optional[float] = None) -> dict:
    """在 at 秒加一段音樂：整首、預設音量、不循環、講話時自動壓低（配樂最常見的用法）。"""
    if is_image(path):
        raise AssembleError(f"圖片不能放音樂軌：{os.path.basename(path)}")
    if not seconds or seconds < MIN_CLIP:
        raise AssembleError(f"量不到這段聲音有多長：{os.path.basename(path)}")
    seconds = round(float(seconds), 3)
    return {"path": path, "at": clamp_at(at, total), "in": 0.0, "out": seconds, "length": seconds,
            "volume": DEFAULT_MUSIC_VOLUME, "loop": False, "duck": True}


def item_span(kind: str, item: dict, total: float) -> tuple:
    """
    這段素材佔輸出時間軸的 (開始, 結束)，超出片尾的剪掉（跟輸出時一樣）。
    循環的音樂、沒給 out 的音樂一路到片尾。
    """
    if kind not in TRACK_KINDS:
        raise ValueError(f"不認得的軌：{kind!r}")
    at = float(item.get("at", 0.0))
    if kind == "overlays" and is_image(item.get("path", "")):
        length = float(item.get("duration", DEFAULT_IMAGE_SECONDS))
    elif kind == "music" and (item.get("loop") or item.get("out") is None):
        length = float(total) - at
    else:
        length = float(item["out"]) - float(item.get("in", 0.0))
    return round(at, 3), round(min(at + length, float(total)), 3)


def trimmable_edges(kind: str, item: dict) -> tuple:
    """這段素材哪些邊能拖：循環或沒給 out 的音樂一路到片尾，只有頭能修。"""
    if kind == "music" and (item.get("loop") or item.get("out") is None):
        return ("start",)
    return ("start", "end")


def trim_item(kind: str, item: dict, edge: str, t: float, total: float) -> dict:
    """
    把一段素材的頭（edge="start"）或尾（"end"）拖到輸出的第 t 秒，回傳新的 dict（不改
    原本的）。跟剪片軟體一樣：

    * 拖頭：開始時間與素材的進點一起動，尾巴不動（影片／音樂往右拖＝剪掉前面一段）。
      進點不能小於 0；圖片沒有進點，只改 duration。
    * 拖尾：只改出點（圖片改 duration），最多到素材本身的長度（`length`，沒記就不限）
      與片尾。
    * 不論哪一邊，至少留 MIN_CLIP 秒；開始時間夾在片內。
    """
    if edge not in trimmable_edges(kind, item):
        return dict(item)
    total = float(total)
    out = dict(item)
    at = float(item.get("at", 0.0))
    image = kind == "overlays" and is_image(item.get("path", ""))
    if image:
        length = float(item.get("duration", DEFAULT_IMAGE_SECONDS))
    else:
        start_in = float(item.get("in", 0.0))
        length = float(item["out"]) - start_in
    end = at + length
    t = float(t)
    if edge == "start":
        low = 0.0 if image else max(0.0, at - start_in)
        new_at = min(max(t, low), end - MIN_CLIP, total - MIN_CLIP)
        new_at = round(max(new_at, low), 3)
        out["at"] = new_at
        if image:
            out["duration"] = round(end - new_at, 3)
        else:
            out["in"] = round(start_in + (new_at - at), 3)
        return out
    if image:
        out["duration"] = round(min(max(t - at, MIN_CLIP), max(total - at, MIN_CLIP)), 3)
        return out
    limit = start_in + (total - at)
    if item.get("length"):
        limit = min(limit, float(item["length"]))
    out["out"] = round(min(max(start_in + (t - at), start_in + MIN_CLIP), max(limit, start_in + MIN_CLIP)), 3)
    return out


# 子畫面的預設位置（rect 是畫布上 0～1 的比例 [x, y, w, h]）。小畫面佔寬高的三分之一，
# 離邊 4%：常見的「右上角放一個講者」。
OVERLAY_POSITIONS = (
    ("full", "蓋滿整個畫面", [0.0, 0.0, 1.0, 1.0]),
    ("top_right", "右上小畫面", [0.62, 0.04, 0.34, 0.34]),
    ("top_left", "左上小畫面", [0.04, 0.04, 0.34, 0.34]),
    ("bottom_right", "右下小畫面", [0.62, 0.62, 0.34, 0.34]),
    ("bottom_left", "左下小畫面", [0.04, 0.62, 0.34, 0.34]),
)


def overlay_box(rect, width: int, height: int) -> tuple:
    """
    疊加在 width x height 的畫布上佔的框 (x, y, w, h)（像素，寬高取偶數，x264 的要求）。
    輸出與播放器的預覽都用這一個，兩邊才會擺在同一個地方。素材在框裡等比縮小、置中，
    空出來的地方補黑（見 fit_inside）。
    """
    x, y, w, h = (float(v) for v in (rect or [0.0, 0.0, 1.0, 1.0]))
    ow = max(2, int(round(width * w / 2.0)) * 2)
    oh = max(2, int(round(height * h / 2.0)) * 2)
    return int(round(width * x)), int(round(height * y)), ow, oh


def fit_inside(src_w: float, src_h: float, box_w: float, box_h: float) -> tuple:
    """素材在框裡的位置 (x, y, w, h)：等比縮放到放得進框、置中（同 ffmpeg 的 decrease＋pad）。"""
    if src_w <= 0 or src_h <= 0:
        return 0.0, 0.0, float(box_w), float(box_h)
    scale = min(box_w / float(src_w), box_h / float(src_h))
    w, h = src_w * scale, src_h * scale
    return (box_w - w) / 2.0, (box_h - h) / 2.0, w, h


def overlays_at(overlays, t: float, total: float) -> list:
    """
    輸出第 t 秒有哪幾段疊加：[(第幾段, 素材的第幾秒)]，照疊上去的順序（後加的在上面）。
    圖片沒有「第幾秒」，回傳 None。給播放器的預覽用，時間範圍跟輸出一樣（item_span）。
    """
    t = float(t)
    out = []
    for index, item in enumerate(overlays or []):
        start, end = item_span("overlays", item, total)
        if start <= t < end:
            source = None if is_image(item.get("path", "")) else \
                round(float(item.get("in", 0.0)) + (t - float(item.get("at", 0.0))), 3)
            out.append((index, source))
    return out


def overlay_position(item: dict) -> str:
    """這段疊加用的是哪個預設位置；不是任何一個時回傳 "custom"。沒給 rect＝蓋滿。"""
    rect = [float(v) for v in (item.get("rect") or [0.0, 0.0, 1.0, 1.0])]
    for key, _label, preset in OVERLAY_POSITIONS:
        if all(abs(a - b) < 1e-6 for a, b in zip(rect, preset)):
            return key
    return "custom"


def position_rect(key: str) -> list:
    for name, _label, rect in OVERLAY_POSITIONS:
        if name == key:
            return list(rect)
    raise ValueError(f"不認得的位置：{key!r}")


# ===== 真的輸出 ===========================================================

def probe_media(path: str) -> dict:
    """有沒有畫面、有沒有聲音、畫面尺寸與影格率（給 build_command 與畫布預設值用）。"""
    from .media import has_audio_stream, has_video_stream, probe_dimensions, probe_fps
    if is_image(path):
        width, height = probe_dimensions(path)
        return {"video": True, "audio": False, "width": width, "height": height, "fps": None}
    video = has_video_stream(path)
    info = {"video": video, "audio": has_audio_stream(path), "width": None, "height": None, "fps": None}
    if video:
        info["width"], info["height"] = probe_dimensions(path)
        info["fps"] = probe_fps(path)
    return info


def all_paths(timeline: dict) -> list:
    seen = []
    for key in ("main", "overlays", "music"):
        for item in timeline[key]:
            if item["path"] not in seen:
                seen.append(item["path"])
    return seen


def duck_settings(timeline: dict, media: dict, config: Optional[dict] = None) -> dict:
    """
    閃避參數：照 config 的 ducking（同一般版的背景音樂閃避）。「自動適應人聲音量」打開時，
    量主軌第一段有聲音的片段（in～out）的響度，換算門檻；量不到就用手動值。
    """
    from . import audio
    settings = audio.resolve_ducking_settings(config)
    result = {"threshold": settings["duck_sensitivity"], "ratio": settings["duck_strength"]}
    if settings["auto_sensitivity"]:
        for clip in timeline["main"]:
            if (media.get(clip["path"]) or {}).get("audio"):
                measured = audio.measure_loudness(clip["path"], clip["in"], clip["out"] - clip["in"])
                value = audio.compute_auto_sensitivity(measured.get("input_i")) if measured else None
                if value is not None:
                    result["threshold"] = value
                break
    return result


def render(timeline: dict, output_path: str,
           progress_cb: Optional[Callable[[float, str], None]] = None,
           config: Optional[dict] = None) -> dict:
    """
    照時間軸輸出一支影片。回傳 {"output", "duration", "width", "height", "fps"}。
    config：完整設定（只用到 ducking）。

    素材不存在、輸出蓋到任何一個素材、ffmpeg 失敗 → 拋錯（AssembleError／RuntimeError）。
    先寫到同資料夾的暫存檔，成功才換名：失敗或中途停下（progress_cb 拋例外，例如使用者
    按取消）不留下半支檔案，目的地原本就有的檔案也不會被動到。
    """
    timeline = normalize(timeline)
    paths = all_paths(timeline)
    missing = [p for p in paths if not os.path.isfile(p)]
    if missing:
        raise AssembleError("找不到素材：" + "、".join(os.path.basename(p) for p in missing))
    target = os.path.abspath(output_path)
    if any(os.path.abspath(p) == target for p in paths):
        raise AssembleError("輸出檔跟其中一個素材是同一個檔案，會把素材蓋掉；請換個檔名")
    media = {p: probe_media(p) for p in paths}
    first = media[timeline["main"][0]["path"]]
    canvas = (first.get("width"), first.get("height"), first.get("fps"))
    duck = duck_settings(timeline, media, config) if any(m["duck"] for m in timeline["music"]) else None
    root, ext = os.path.splitext(output_path)
    temp = f"{root}.tmp-{os.getpid()}{ext or '.mp4'}"
    command = build_command(timeline, temp, media, canvas, duck)
    total = main_duration(timeline)
    if progress_cb:
        progress_cb(0.0, "正在組合時間軸…")
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="ignore")
    except OSError as exc:
        raise RuntimeError(f"無法啟動 ffmpeg：{exc}") from exc
    try:
        for line in process.stdout:
            key, _, value = line.strip().partition("=")
            if key in ("out_time_us", "out_time_ms") and progress_cb and total > 0:
                try:
                    ratio = min(int(value) / 1e6 / total, 0.99)
                except ValueError:
                    continue
                progress_cb(ratio, "正在組合時間軸…")
        stderr = process.stderr.read() or ""
        ret = process.wait()
    except BaseException:
        process.kill()
        process.wait()
        _remove(temp)
        raise
    finally:
        process.stdout.close()
        process.stderr.close()
    if ret != 0:
        _remove(temp)
        detail = stderr.strip().splitlines()
        raise RuntimeError("組合失敗" + (f"：{detail[-1]}" if detail else ""))
    try:
        os.replace(temp, output_path)
    except OSError:
        _remove(temp)
        raise
    if progress_cb:
        progress_cb(1.0, "組合完成")
    width = timeline["width"] or canvas[0] or 1920
    height = timeline["height"] or canvas[1] or 1080
    return {"output": output_path, "duration": total, "width": width - width % 2,
            "height": height - height % 2, "fps": timeline["fps"] or canvas[2] or 30.0}


def _remove(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
