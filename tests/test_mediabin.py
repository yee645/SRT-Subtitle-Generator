# -*- coding: utf-8 -*-
"""
剪輯器版面改版 E-4：素材庫的規則（subtitle/mediabin.py，零 GUI 依賴）。

1. 副檔名 → 影片／圖片／聲音（大小寫都認；圖片跟 assemble.IMAGE_EXTS 同一份）；不認得是 None。
2. add_paths：加進來的是絕對路徑；不認得、找不到、重複（含同一批裡重複、寫法不同的同一個檔）都略過並寫原因；
   不改原本的清單。remove_paths 一樣不改原本的。
3. track_for：疊加列收影片與圖片、音樂列收聲音與影片（影片的聲音當配樂），其他列照種類放。
4. duration_label、file_filter。
5. 模組不 import 任何 GUI 或 config。
"""
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from subtitle import assemble, mediabin  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


# ----- 1 -----
check("影片", mediabin.kind_of("a.mp4") == "video" and mediabin.kind_of("B.MOV") == "video")
check("圖片（跟 assemble 同一份副檔名）", all(mediabin.kind_of("x" + e.upper()) == "image" for e in assemble.IMAGE_EXTS))
check("聲音", mediabin.kind_of("s.m4a") == "audio" and mediabin.kind_of("s.WAV") == "audio")
check("不認得的是 None", mediabin.kind_of("a.srt") is None and mediabin.kind_of("noext") is None
      and mediabin.kind_of("a.mp4.txt") is None)
check("三種不重疊", not (set(mediabin.VIDEO_EXTS) & set(mediabin.AUDIO_EXTS))
      and not (set(mediabin.VIDEO_EXTS) & set(assemble.IMAGE_EXTS)))

# ----- 2 -----
tmp = tempfile.mkdtemp()
files = {}
for name in ("clip.mp4", "logo.png", "song.mp3", "notes.txt"):
    files[name] = os.path.join(tmp, name)
    open(files[name], "wb").close()
start = [{"path": files["clip.mp4"], "kind": "video"}]
snapshot = [dict(e) for e in start]
twisted = os.path.join(tmp, "sub", "..", "logo.png")
out, added, skipped = mediabin.add_paths(start, [files["logo.png"], files["song.mp3"], files["notes.txt"],
                                                 os.path.join(tmp, "gone.mp4"), files["clip.mp4"], twisted])
check("加了圖片與聲音", [e["kind"] for e in added] == ["image", "audio"] and len(out) == 3, str(added))
reasons = {os.path.basename(p): why for p, why in skipped}
check("略過並寫原因：不認得、找不到、已經在裡面（寫法不同的同一個檔也算）",
      reasons.get("notes.txt") == "不是影片、圖片或聲音" and reasons.get("gone.mp4") == "找不到檔案"
      and reasons.get("clip.mp4") == "已經在素材庫裡" and len(skipped) == 4
      and sum(1 for p, _w in skipped if p == os.path.abspath(twisted)) == 1, str(skipped))
check("同一批裡重複的只加一次", len(mediabin.add_paths([], [files["song.mp3"], files["song.mp3"]])[1]) == 1)
check("存的是絕對路徑", all(os.path.isabs(e["path"]) for e in out))
check("不改原本的清單", start == snapshot)
rel = os.path.relpath(files["song.mp3"])
check("相對路徑轉成絕對", mediabin.add_paths([], [rel])[1][0]["path"] == os.path.abspath(rel))
kept = mediabin.remove_paths(out, [files["logo.png"], os.path.join(tmp, "nope.mp4")])
check("remove_paths：寫法不同的同一個檔也拿得掉", [os.path.basename(e["path"]) for e in
                                               mediabin.remove_paths(out, [twisted, os.path.relpath(files["song.mp3"])])]
      == ["clip.mp4"])
check("remove_paths：拿掉那一個、不在裡面的不管", [os.path.basename(e["path"]) for e in kept] == ["clip.mp4", "song.mp3"]
      and len(out) == 3)

# ----- 3 -----
check("疊加列：影片、圖片放疊加；聲音不收", mediabin.track_for("overlays", "video") == "overlays"
      and mediabin.track_for("overlays", "image") == "overlays" and mediabin.track_for("overlays", "audio") is None)
check("音樂列：聲音、影片放音樂；圖片不收", mediabin.track_for("music", "audio") == "music"
      and mediabin.track_for("music", "video") == "music" and mediabin.track_for("music", "image") is None)
check("其他列（字幕、畫面、列外）照種類放", all(mediabin.track_for(row, "audio") == "music"
                                             and mediabin.track_for(row, "video") == "overlays"
                                             and mediabin.track_for(row, "image") == "overlays"
                                             for row in ("cues", "thumbs", "wave", "cuts", "ruler", "")))
check("不認得的種類不收", mediabin.track_for("overlays", None) is None and mediabin.track_for("", "text") is None)

# ----- 4 -----
check("時間標籤", mediabin.duration_label(5.2) == "0:05" and mediabin.duration_label(65) == "1:05"
      and mediabin.duration_label(3725) == "1:02:05" and mediabin.duration_label(0) == "0:00")
check("量不到是空字串", mediabin.duration_label(None) == "" and mediabin.duration_label(-1) == "")
flt = mediabin.file_filter()
check("檔案篩選：三種一起在最前面、各自一種、所有檔案", flt.startswith("影片、圖片、聲音 (") and "*.png" in flt
      and "*.mp3" in flt and "*.mov" in flt and flt.endswith("所有檔案 (*)") and flt.count(";;") == 4)

# ----- 5 -----
src = open(os.path.join(ROOT, "subtitle", "mediabin.py"), encoding="utf-8").read()
check("零 GUI 依賴、不 import config", not re.search(r"^\s*(import|from)\s+(PySide6|tkinter|config|gui)", src, re.M))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("素材庫規則（E-4）測試全數通過。")
