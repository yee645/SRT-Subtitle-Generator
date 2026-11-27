# -*- coding: utf-8 -*-
"""
剪輯器版面 E-8a：素材庫的清單存進專案檔（subtitle/project.py 的 `bin`）。

1. 新的狀態有空的素材庫；存進檔案記相對＋絕對兩種位置，讀回來一樣（整個資料夾搬走也找得回來）。
2. 選填、不升版本：格式還是第 2 版；沒有 `bin` 的檔（3.1.0 以前存的）讀進來素材庫是空的；
   3.1.0 的讀檔程式（git 裡那一版）看到有 `bin` 的新檔照樣打得開（只是沒有素材庫）。
3. 整理：重複的（同一個檔）只留第一個、順序照舊；不是影片、圖片、聲音，不是字串，不是清單，太多——說清楚。
4. 找不到的素材庫檔案：不擋開專案，列在找不到的清單最後面（主片、字幕、素材軌之後），寫「素材庫第 n 個」。
5. 素材庫的檔案不必是主片在的資料夾；只有素材庫、沒有主片的狀態照樣合理（素材庫不是時間軸）。
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from subtitle import project  # noqa: E402

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
work = os.path.join(tmp, "專案")
os.makedirs(os.path.join(work, "素材"))
files = {}
for name in ("主片.mp4", "字幕.srt", os.path.join("素材", "空拍.mp4"), os.path.join("素材", "標誌.png"),
             os.path.join("素材", "配樂.m4a")):
    path = os.path.join(work, name)
    with open(path, "wb") as fh:
        fh.write(b"x")
    files[os.path.basename(name)] = path

# ----- 1 -----
check("新的狀態有空的素材庫", project.new_state()["bin"] == [])
bin_paths = [files["空拍.mp4"], files["標誌.png"], files["配樂.m4a"]]
state = dict(project.new_state(), media=files["主片.mp4"], subtitles=files["字幕.srt"],
             cues=[{"start": 0.0, "end": 1.0, "text": "一"}], bin=list(bin_paths))
saved = project.save(state, os.path.join(work, "片子"))
with open(saved, encoding="utf-8") as fh:
    doc = json.load(fh)
check("存進檔案：每個都記相對與絕對位置", doc["bin"] == [
    {"absolute": p, "path": "素材/" + os.path.basename(p)} for p in bin_paths], str(doc.get("bin")))
loaded, missing = project.load(saved)
check("讀回來一樣、沒有找不到的", loaded["bin"] == bin_paths and missing == [], f"{loaded['bin']} {missing}")
check("其他東西照舊", dict(loaded, bin=[]) == project.normalize_state(dict(state, bin=[])))

moved = os.path.join(tmp, "搬走了")
shutil.copytree(work, moved)
shutil.rmtree(work)
moved_state, moved_missing = project.load(os.path.join(moved, "片子.srtproj"))
check("整個資料夾搬走：照相對位置找回來", moved_missing == []
      and moved_state["bin"] == [os.path.join(moved, "素材", os.path.basename(p)) for p in bin_paths],
      f"{moved_state['bin']} {moved_missing}")
work, saved = moved, os.path.join(moved, "片子.srtproj")
files = {k: v.replace(os.path.join(tmp, "專案"), moved) for k, v in files.items()}
bin_paths = [p.replace(os.path.join(tmp, "專案"), moved) for p in bin_paths]

# ----- 2 -----
check("選填、不升版本：還是第 2 版", project.VERSION == 2 and doc["version"] == 2)
old_doc = {k: v for k, v in doc.items() if k != "bin"}
old_state, old_missing = project.from_document(old_doc, saved)
check("沒有 bin 的檔（3.1.0 以前存的）：素材庫是空的、其他照舊", old_state["bin"] == []
      and dict(old_state, bin=moved_state["bin"]) == moved_state and old_missing == [])
check("bin 是 null：當成空的", project.from_document(dict(doc, bin=None), saved)[0]["bin"] == [])


def released_reader():
    """3.1.0 發版那一刻的 subtitle/project.py（git 裡的），當成一個獨立的套件載入。"""
    try:
        source = subprocess.run(["git", "-C", ROOT, "show", "7a71975:subtitle/project.py"],
                                capture_output=True, check=True).stdout.decode("utf-8")
    except (OSError, subprocess.CalledProcessError):
        return None
    pkg = os.path.join(tmp, "released", "subtitle")
    shutil.copytree(os.path.join(ROOT, "subtitle"), pkg)
    with open(os.path.join(pkg, "project.py"), "w", encoding="utf-8") as fh:
        fh.write(source)
    spec = importlib.util.spec_from_file_location("released_subtitle", os.path.join(pkg, "__init__.py"),
                                                  submodule_search_locations=[pkg])
    module = importlib.util.module_from_spec(spec)
    sys.modules["released_subtitle"] = module
    spec.loader.exec_module(module)
    return importlib.import_module("released_subtitle.project")


old_reader = released_reader()
if old_reader is None:
    print("SKIP 拿不到 git 裡 3.1.0 的 project.py：略過「舊程式打得開新檔」")
else:
    check("拿到的真的是 3.1.0 的讀檔程式（不認得 bin）", "bin" not in old_reader.new_state()
          and old_reader.VERSION == 2)
    try:
        old_view, old_view_missing = old_reader.load(saved)
        opened = True
    except Exception as exc:  # noqa: BLE001
        opened, old_view, old_view_missing = False, {}, [str(exc)]
    check("3.1.0 的程式打得開有素材庫的新檔（只是沒有素材庫）", opened and old_view_missing == []
          and old_view.get("cues") == moved_state["cues"] and old_view.get("media") == moved_state["media"],
          str(old_view_missing))

# ----- 3 -----
dup = project.normalize_state(dict(state, media=files["主片.mp4"], bin=[
    files["配樂.m4a"], files["空拍.mp4"], files["配樂.m4a"], os.path.join(work, "素材", ".", "空拍.mp4")]))
check("重複的只留第一個、順序照舊", dup["bin"] == [files["配樂.m4a"], files["空拍.mp4"]], str(dup["bin"]))
check("不是影片、圖片、聲音：說是第幾個", "素材庫第 2 個不是影片、圖片或聲音" in (
    error_of(project.normalize_state, dict(state, bin=[files["空拍.mp4"], files["字幕.srt"]])) or ""))
check("不是字串、空字串：說清楚", "素材庫第 1 個要是檔案路徑" in (
    error_of(project.normalize_state, dict(state, bin=[3])) or "")
      and "素材庫第 1 個要是檔案路徑" in (error_of(project.normalize_state, dict(state, bin=[""])) or ""))
check("不是清單：說清楚", "素材庫要是檔案路徑的清單" in (error_of(project.normalize_state, dict(state, bin="a.mp4")) or "")
      and "素材庫要是清單" in (error_of(project.from_document, dict(doc, bin={"a": 1}), saved) or ""))
too_many = [os.path.join(work, f"{i}.mp4") for i in range(project.MAX_BIN + 1)]
check("太多：說上限", f"上限 {project.MAX_BIN}" in (error_of(project.normalize_state, dict(state, bin=too_many)) or ""))
check("剛好上限：收", len(project.normalize_state(dict(state, bin=too_many[:-1]))["bin"]) == project.MAX_BIN)

# ----- 4 -----
os.remove(files["標誌.png"])
os.remove(files["字幕.srt"])
gone_state, gone = project.load(saved)
check("找不到的素材庫檔案：不擋開專案，列在最後、寫第幾個", [what for what, _w in gone] == ["字幕檔", "素材庫第 2 個"]
      and gone[-1][1] == files["標誌.png"], str(gone))
check("找不到的照樣留在清單裡（介面只放找得到的；再存一次不會悄悄丟掉）", gone_state["bin"] == bin_paths)

# ----- 5 -----
only_bin = project.normalize_state(dict(project.new_state(), bin=[files["空拍.mp4"]]))
check("只有素材庫、沒有主片：合理（素材庫不是時間軸）", only_bin["bin"] == [files["空拍.mp4"]] and only_bin["media"] == "")
elsewhere = os.path.join(tmp, "別處", "外接.mp3")
os.makedirs(os.path.dirname(elsewhere))
open(elsewhere, "wb").close()
far = project.save(dict(state, media=files["主片.mp4"], subtitles="", bin=[elsewhere]), os.path.join(work, "遠"))
check("素材庫的檔案在別的資料夾：記 ../ 的相對位置，讀得回來", json.load(open(far, encoding="utf-8"))["bin"][0]["path"]
      == "../別處/外接.mp3" and project.load(far)[0]["bin"] == [elsewhere])

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("素材庫存進專案（E-8a）測試全數通過。")
