# -*- coding: utf-8 -*-
"""
3.0 第 10 項第一階段：專案檔的格式與讀寫（subtitle/project.py）。

1. 存了再讀回來一模一樣（主片、畫面調整、字幕內容、素材軌與各段屬性、剪點微調、接縫）。
2. 路徑：
   - 記相對與絕對兩種。
   - 整個資料夾搬走照樣開得起來。
   - 只有絕對路徑還在時用絕對的。
   - 兩個都找不到列在 missing，不算錯。
3. 版本：
   - 較新的不硬讀。
   - 較舊的照 MIGRATIONS 一步步升上來（用假的第 2 版驗這條路）。
   - 格式不對、不是 JSON、太大，都說清楚。
4. 檢查：不合理的內容都拋 ProjectError，說是哪一項（素材軌照 assemble、調整照 picture 的規則）。
5. 寫入：先寫暫存檔再換名，寫到一半失敗時原本的專案檔不動、也不留暫存檔；沒副檔名補 .srtproj。
6. 真的照專案輸出：讀回來的素材軌與調整交給 assemble 輸出，成品跟直接用原本的狀態輸出一樣大、
   一樣長。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import assemble, project  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def error_of(fn, *args):
    try:
        fn(*args)
    except project.ProjectError as exc:
        return str(exc)
    return None


tmp = tempfile.mkdtemp()
work = os.path.join(tmp, "我的影片")
os.makedirs(os.path.join(work, "素材"))


def touch(*parts):
    path = os.path.join(work, *parts)
    with open(path, "wb") as fh:
        fh.write(b"x")
    return path


main = touch("訪談.mp4")
srt = touch("訪談.srt")
broll = touch("素材", "空景.mp4")
logo = touch("素材", "標誌.png")
song = touch("素材", "配樂.wav")

state = project.new_state()
state.update({
    "media": main,
    "adjust": {"rotate": 90, "brightness": 0.1, "crop": [0.1, 0.0, 0.8, 1.0]},
    "subtitles": srt,
    "cues": [{"start": 0.5, "end": 2.0, "text": "第一句"}, {"start": 3.0, "end": 5.5, "text": "第二句\n兩行",
                                                            "emphasis": ["第二"]}],
    "tracks": {"overlays": [dict(assemble.new_overlay(broll, 1.0, 60.0, 5.0), adjust={"flip_h": True},
                                 rect=[0.65, 0.05, 0.3, 0.3]),
                            assemble.new_overlay(logo, 10.0, 60.0)],
               "music": [assemble.new_music(song, 0.0, 60.0, 30.0)]},
    "cuts": {"source": "jumpcut", "overrides": {"jumpcut:2.650-5.350": {"enabled": False},
                                                 "jumpcut:8.000-9.500": {"start": 8.1, "end": 9.4}}},
    "seam": {"type": "dissolve", "duration": 0.8},
})

# ----- 1. 存了再讀回來 -----
saved = project.save(state, os.path.join(work, "訪談專案"))
check("沒副檔名補上 .srtproj", saved == os.path.join(work, "訪談專案.srtproj") and os.path.isfile(saved))
loaded, missing = project.load(saved)
check("讀回來跟存的一模一樣、沒有找不到的檔案", loaded == project.normalize_state(state) and missing == [],
      f"{missing}\n{loaded}")
with open(saved, encoding="utf-8") as fh:
    doc = json.load(fh)
check("檔案裡記格式名稱與版本", doc["format"] == project.FORMAT and doc["version"] == project.VERSION)
check("路徑記相對（用 /）與絕對兩種", doc["media"]["file"] == {"path": "訪談.mp4", "absolute": main}
      and doc["tracks"]["overlays"][0]["path"]["path"] == "素材/空景.mp4", str(doc["media"]))
check("字幕內容整份存在專案裡（含多的欄位）", doc["subtitles"]["cues"][1]["emphasis"] == ["第二"]
      and doc["subtitles"]["cues"][1]["text"] == "第二句\n兩行")
check("剪點微調整份讀回來（停用與改過的範圍）", loaded["cuts"]["overrides"] == {
    "jumpcut:2.650-5.350": {"enabled": False}, "jumpcut:8.000-9.500": {"start": 8.1, "end": 9.4}},
      str(loaded["cuts"]))
check("沒改過的畫面調整不記", project.normalize_state(dict(state, adjust={"rotate": 0, "contrast": 1}))["adjust"] == {})

# ----- 2. 路徑 -----
moved = os.path.join(tmp, "搬到別處")
shutil.copytree(work, moved)
shutil.rmtree(work)
again, missing = project.load(os.path.join(moved, "訪談專案.srtproj"))
check("整個資料夾搬走：照相對路徑找到每一個檔案", missing == [] and again["media"] == os.path.join(moved, "訪談.mp4")
      and again["tracks"]["music"][0]["path"] == os.path.join(moved, "素材", "配樂.wav"), f"{missing} {again['media']}")
# 只搬專案檔：相對的找不到，用絕對的
shutil.copytree(moved, work)
# 複製一份資料夾（原本的還在）：開複製的那份要用複製那邊的檔案，不能跑回原本的
both, missing = project.load(os.path.join(moved, "訪談專案.srtproj"))
check("原本與複製的都在：先照相對路徑用專案旁邊的檔案", missing == []
      and both["media"] == os.path.join(moved, "訪談.mp4") and both["subtitles"] == os.path.join(moved, "訪談.srt"),
      both["media"])
lonely = os.path.join(tmp, "只有專案檔")
os.makedirs(lonely)
shutil.copy(saved.replace(work, moved), lonely)
alone, missing = project.load(os.path.join(lonely, "訪談專案.srtproj"))
check("只搬專案檔：相對的找不到時用絕對路徑", missing == [] and alone["media"] == main, f"{missing} {alone['media']}")
os.remove(os.path.join(work, "素材", "配樂.wav"))
os.remove(os.path.join(moved, "素材", "配樂.wav"))
os.remove(srt)
_part, missing = project.load(saved)
check("檔案不見了：不算錯，列出是哪一個（音樂第 1 段、字幕檔）",
      [what for what, _p in missing] == ["音樂第 1 段", "字幕檔"]
      and missing[0][1] == os.path.join(work, "素材", "配樂.wav"), str(missing))
check("檔案不見時字幕內容照樣在（存在專案裡）", _part["cues"] == loaded["cues"])
touch("素材", "配樂.wav")
touch("訪談.srt")

# ----- 3. 版本與格式 -----
newer = dict(doc, version=project.VERSION + 1)
check("較新版本存的：不硬讀、說要更新程式",
      "較新版本" in (error_of(project.from_document, newer, saved) or "")
      and "請先更新程式" in (error_of(project.from_document, newer, saved) or ""))
check("格式名稱不對：不是本程式的專案檔", "不是本程式的專案檔" in (error_of(project.from_document,
                                                                      dict(doc, format="other"), saved) or ""))
check("版本號不合理", "版本不合理" in (error_of(project.from_document, dict(doc, version="1"), saved) or "")
      and "版本不合理" in (error_of(project.from_document, dict(doc, version=True), saved) or ""))
# 假裝現在是第 2 版：第 1 版的檔要照 MIGRATIONS 升上來
real_version, real_migrations = project.VERSION, dict(project.MIGRATIONS)
steps = []


def one_to_two(old):
    steps.append(old["version"])
    return dict(old, seam=dict(old["seam"], duration=1.5))


def two_to_three(old):
    steps.append(old["version"])
    return dict(old, seam=dict(old["seam"], duration=old["seam"]["duration"] + 0.5))


project.VERSION = 3
project.MIGRATIONS[1] = one_to_two
project.MIGRATIONS[2] = two_to_three
upgraded_doc = project.upgrade(dict(doc))
upgraded, _m = project.from_document(dict(doc), saved)
check("較舊的版本照 MIGRATIONS 一步步升上來（每一步拿到的版本號對、最後記成現在的版本）",
      steps == [1, 2, 1, 2] and upgraded_doc["version"] == 3 and upgraded["seam"]["duration"] == 2.0, str(steps))
del project.MIGRATIONS[2]
check("缺中間一步：說不知道怎麼升", "不知道怎麼把第 2 版" in (error_of(project.from_document, dict(doc), saved) or ""))
project.VERSION = 2
del project.MIGRATIONS[1]
check("缺一步升級：說不知道怎麼升", "不知道怎麼把第 1 版" in (error_of(project.from_document, dict(doc), saved) or ""))
project.VERSION, project.MIGRATIONS = real_version, real_migrations

junk = os.path.join(tmp, "壞的.srtproj")
with open(junk, "w", encoding="utf-8") as fh:
    fh.write("{這不是 json")
check("不是 JSON：說讀不出內容", "讀不出內容" in (error_of(project.load, junk) or ""))
check("檔案不存在：說打不開", "打不開專案檔" in (error_of(project.load, os.path.join(tmp, "沒有.srtproj")) or ""))
real_max = project.MAX_BYTES
project.MAX_BYTES = 100
check("太大的檔：不讀", "專案檔太大" in (error_of(project.load, saved) or ""))
project.MAX_BYTES = real_max
real_cues = project.MAX_CUES
project.MAX_CUES = 1
check("字幕句數太多：不收", "字幕太多" in (error_of(project.normalize_state, state) or ""))
project.MAX_CUES = real_cues

# ----- 4. 檢查 -----
bad = [
    ({"unknown": 1}, "不認得的項目：unknown"),
    ({"media": 3}, "media 要是檔案路徑"),
    ({"adjust": {"rotate": 45}}, "主片的畫面調整的旋轉"),
    ({"cues": [{"start": 2, "end": 1, "text": "x"}]}, "第 1 句字幕的時間不合理"),
    ({"cues": [{"start": "a", "end": 1}]}, "第 1 句字幕的開始不是數字"),
    ({"cues": [{"start": 0, "end": float("inf")}]}, "不是有限的數字"),
    ({"cues": [{"start": 0, "end": 1, "text": 5}]}, "文字要是字串"),
    ({"tracks": {"overlays": [{"at": 0}]}}, "素材軌 overlays 第 1 段沒有檔案"),
    ({"tracks": {"overlays": [{"path": "a.mp4", "at": 0, "out": 2, "rect": [0, 0, 2, 2]}]}}, "素材軌不合理"),
    ({"tracks": {"overlays": [{"path": "a.mp4", "at": 0, "out": 2, "adjust": {"saturation": 9}}]}}, "飽和度"),
    ({"tracks": {"video": []}}, "素材軌要是"),
    ({"tracks": {"music": [{"path": "m.wav", "at": 0, "out": 2, "volume": object()}]}}, "存不進專案檔的值"),
    ({"cuts": {"source": "magic"}}, "不認得的剪點種類"),
    ({"cuts": {"source": "jumpcut", "overrides": {"k": {"start": 1}}}}, "要同時有 start 與 end"),
    ({"cuts": {"source": "jumpcut", "overrides": {"k": {"start": 3, "end": 1}}}}, "範圍不合理"),
    ({"cuts": {"source": "jumpcut", "overrides": {"k": {"color": "red"}}}}, "只能有 enabled、start、end"),
    ({"seam": {"type": "wipe"}}, "不認得的接縫轉場"),
    ({"seam": {"type": "dissolve", "duration": 9}}, "接縫轉場的長度要在"),
]
wrong = []
for change, want in bad:
    trial = dict(state, **change) if "media" not in change else dict(state, **change)
    message = error_of(project.normalize_state, trial)
    if not message or want not in message:
        wrong.append((want, message))
check(f"不合理的 {len(bad)} 種內容都拋 ProjectError，說是哪一項", not wrong, str(wrong))
check("有素材軌卻沒有主片：不收", "沒有主片" in (error_of(project.normalize_state, dict(state, media="")) or ""))
check("空的專案（還沒開影片）可以存", project.normalize_state(project.new_state()) == project.new_state())

# ----- 5. 寫入 -----
before = open(saved, "rb").read()
real_dumps = json.dumps


def broken_dumps(*args, **kwargs):
    raise RuntimeError("寫到一半當掉")


bad_state = dict(state, cues=[{"start": 0, "end": 1, "text": "改過"}])
project.json.dumps = broken_dumps
try:
    project.save(bad_state, saved)
except RuntimeError:
    pass
project.json.dumps = real_dumps
real_replace = os.replace


def broken_replace(src, dst):
    raise OSError("磁碟滿了")


project.os.replace = broken_replace
try:
    project.save(bad_state, saved)
except OSError:
    pass
project.os.replace = real_replace
leftovers = [n for n in os.listdir(work) if n.startswith(".srtproj-")]
check("寫到一半失敗：原本的專案檔一個 byte 都沒變、不留暫存檔", open(saved, "rb").read() == before and not leftovers,
      str(leftovers))

# ----- 6. 照專案真的輸出 -----
if shutil.which("ffmpeg"):
    def run(*args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)

    real = os.path.join(tmp, "真的")
    os.makedirs(real)
    video = os.path.join(real, "主片.mp4")
    run("-f", "lavfi", "-i", "testsrc=size=320x180:rate=25:d=4", "-f", "lavfi", "-i", "sine=frequency=300:d=4",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", video)
    image = os.path.join(real, "標誌.png")
    run("-f", "lavfi", "-i", "color=c=red:size=64x64", "-frames:v", "1", image)
    live = dict(project.new_state(), media=video, adjust={"rotate": 90, "crop": [0, 0, 0.5, 1]},
                tracks={"overlays": [dict(assemble.new_overlay(image, 1.0, 4.0), rect=[0.5, 0, 0.5, 0.5],
                                          adjust={"brightness": -0.3})], "music": []})
    path = project.save(live, os.path.join(real, "輸出測試"))
    back, missing = project.load(path)

    def timeline(st):
        return {"main": [dict({"path": st["media"], "in": 0.0, "out": 4.0},
                              **({"adjust": st["adjust"]} if st["adjust"] else {}))], **st["tracks"]}

    a, b = os.path.join(real, "直接.mp4"), os.path.join(real, "從專案.mp4")
    assemble.render(timeline(live), a)
    assemble.render(timeline(back), b)

    def probe(p):
        return subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                               "stream=width,height:format=duration", "-of", "csv=p=0", p],
                              capture_output=True, text=True).stdout.split()

    def pixel(p):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "2", "-i", p, "-frames:v", "1", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        return raw

    check("照讀回來的專案輸出：跟直接用原本的狀態輸出一樣大、一樣長、畫面一樣（裁左半再轉 90 度＝180x160）",
          missing == [] and probe(a) == probe(b) and probe(a)[0] == "180,160" and pixel(a) == pixel(b),
          f"{probe(a)} {probe(b)}")
else:
    print("SKIP 沒有 ffmpeg：略過照專案真的輸出")

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 專案檔測試全數通過。")
