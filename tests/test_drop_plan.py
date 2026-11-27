# -*- coding: utf-8 -*-
"""
剪輯器版面 E-8c：拖曳落點預覽的規則（subtitle/mediabin.py 的 drop_plan、drop_hint、refused_note）。

1. drop_plan 跟 track_for 是同一套：疊加列收影片與圖片、音樂列收聲音與影片、其他列照種類；順序照拖進來的。
2. 不認得的種類（文字檔）在哪一列都放不了。
3. refused_note：講哪一列、哪幾個檔（只寫檔名）、規則；列外寫「這一列」。真的放（PlayerPanel.drop_files）用同一句。
4. drop_hint：放到哪幾軌各幾個；有放不了的接在後面；都放不了只講放不了；什麼都沒有是空字串。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from subtitle import mediabin  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


folder = os.path.join("素材", "a")
video, image, audio, text = (os.path.join(folder, n) for n in ("空拍.mp4", "標誌.png", "配樂.m4a", "筆記.txt"))
batch = [audio, video, text, image]

# ----- 1、2 -----
check("疊加列：影片、圖片放疊加，聲音與文字放不了（順序照舊）", mediabin.drop_plan(batch, "overlays")
      == {"overlays": [video, image], "music": [], "refused": [audio, text]})
check("音樂列：聲音、影片放音樂，圖片與文字放不了", mediabin.drop_plan(batch, "music")
      == {"overlays": [], "music": [audio, video], "refused": [text, image]})
for row in ("cues", "thumbs", "wave", "cuts", "ruler", ""):
    check(f"其他列（{row or '列外'}）：照種類放", mediabin.drop_plan(batch, row)
          == {"overlays": [video, image], "music": [audio], "refused": [text]})
check("跟 track_for 一致（每一列、每一種）", all(
    (path in mediabin.drop_plan([path], row)[mediabin.track_for(row, mediabin.kind_of(path)) or "refused"])
    for row in ("overlays", "music", "cues", "") for path in batch))
check("沒有檔案：三個都空", mediabin.drop_plan([], "music") == {"overlays": [], "music": [], "refused": []})

# ----- 3 -----
check("refused_note：列名、只寫檔名、規則", mediabin.refused_note("overlays", [audio, text])
      == "疊加列放不了：配樂.m4a、筆記.txt（疊加列放影片或圖片、音樂列放聲音或影片）")
check("refused_note：音樂列", mediabin.refused_note("music", [image]).startswith("音樂列放不了：標誌.png（"))
check("refused_note：列外寫「這一列」", mediabin.refused_note("cues", [text]).startswith("這一列放不了：筆記.txt（"))

# ----- 4 -----
check("drop_hint：都放得了", mediabin.drop_hint(mediabin.drop_plan([video, audio, image], "cues"), "cues")
      == "放到疊加 2 個、音樂 1 個")
check("drop_hint：有放不了的接在後面", mediabin.drop_hint(mediabin.drop_plan(batch, "overlays"), "overlays")
      == "放到疊加 2 個；疊加列放不了：配樂.m4a、筆記.txt（疊加列放影片或圖片、音樂列放聲音或影片）")
check("drop_hint：都放不了只講放不了", mediabin.drop_hint(mediabin.drop_plan([image], "music"), "music")
      == mediabin.refused_note("music", [image]))
check("drop_hint：沒有東西是空字串", mediabin.drop_hint(mediabin.drop_plan([], "music"), "music") == "")

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("拖曳落點的規則（E-8c）測試全數通過。")
