# -*- coding: utf-8 -*-
"""
v2.3.1 回歸測試：三個運作模式摘掉舊編號（架構文件 D-1）。

「模式一／二／三」要整行讀完才知道差別（`docs/UI_AUDIT_2.0.md` 1.3-②），
架構文件定案改成直接寫它做什麼：〔語音轉寫〕〔文字稿對齊〕〔手動輸入〕，
舊編號「保留至 2.0.0 之後一版再摘除」。這裡守三件事：

1. 程式裡**使用者看得到的字串**（不含註解與 docstring）不再出現「模式一
   ／二／三」與兩個舊名「音訊轉錄」「手動字幕模式」。用 ast 走字串常數，
   不用 grep——grep 分不出字串與註解，也會把「模式一致」當成命中。
2. 錯誤訊息、README 提到模式時，用的就是介面上 radio 的名字（名字從
   `gui/app.py` 抓，不在這裡再寫死一次）。
3. 發佈政策：v2.3.0 還沒轉正，v2.3.1 就不能轉正（否則等於替使用者把 2.3.0
   的新功能推給所有人）。
"""
import ast
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


OLD_NUMBER = re.compile(r"模式[一二三](?!致)")
OLD_NAMES = ("音訊轉錄", "手動字幕模式")


def _docstring_ids(tree):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                ids.add(id(body[0].value))
    return ids


def user_strings(rel):
    """一個檔案裡所有非 docstring 的字串常數（含 f-string 的字面部分）。"""
    tree = ast.parse(_read(rel))
    skip = _docstring_ids(tree)
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in skip]


# ===== 1. 使用者看得到的字串 ============================================

files = ["cli.py", "config.py", "main.py"]
for folder in ("gui", "subtitle"):
    files += [f"{folder}/{f}" for f in sorted(os.listdir(os.path.join(ROOT, folder)))
              if f.endswith(".py")]
files = [f for f in files if os.path.exists(os.path.join(ROOT, f))]
check("掃描範圍涵蓋 gui/ 與 subtitle/（不是空掃）",
      len(files) > 60 and "gui/app.py" in files and "subtitle/errors.py" in files,
      str(len(files)))

hits = []
for rel in files:
    for s in user_strings(rel):
        if OLD_NUMBER.search(s) or any(n in s for n in OLD_NAMES):
            hits.append(f"{rel}: {s[:40]!r}")
check("程式裡使用者看得到的字串不再用「模式一／二／三」或舊名", not hits,
      "; ".join(hits[:5]))

# 自我檢查：掃描器真的抓得到字串、也真的會略過 docstring 與「模式一致」。
_probe = ast.parse('"""模式一 docstring"""\nx = "模式二：文字稿對齊"\ny = "與其他批次模式一致"\n')
_skip = _docstring_ids(_probe)
_found = [n.value for n in ast.walk(_probe) if isinstance(n, ast.Constant)
          and isinstance(n.value, str) and id(n) not in _skip]
check("掃描器自我檢查：抓得到一般字串、略過 docstring 與「模式一致」",
      [s for s in _found if OLD_NUMBER.search(s)] == ["模式二：文字稿對齊"],
      str(_found))

# ===== 2. 名字從介面抓，再比對其他地方 ==================================

app_src = _read("gui/app.py")
body = app_src.split("def _build_mode_section", 1)[1].split("\n    def ", 1)[0]
radio = dict(re.findall(r'\((MODE_[A-Z]+), "([^"\\]+)\\n', body))
check("從 _build_mode_section 抓得到三個模式的名字",
      set(radio) == {"MODE_TRANSCRIBE", "MODE_ALIGN", "MODE_MANUAL"}, str(radio))
names = [radio.get(k, "?") for k in ("MODE_TRANSCRIBE", "MODE_ALIGN", "MODE_MANUAL")]
check("三個名字互不相同、沒有編號也沒有冒號",
      len(set(names)) == 3 and not any(OLD_NUMBER.search(n) or "：" in n for n in names),
      str(names))
check("架構文件定案的名字（語音轉寫／文字稿對齊／手動輸入）",
      names == ["語音轉寫", "文字稿對齊", "手動輸入"], str(names))
check("各區塊標題不再掛模式編號",
      'text="轉寫設定"' in app_src and 'text="文字稿"' in app_src)

from subtitle import errors  # noqa: E402

e = errors.describe_exception(RuntimeError(
    "找不到可用的本地 Whisper。請先安裝 Python 並執行 pip install..."))
check(f"Whisper 缺失的解法用介面上的名字（「{names[1]}」）",
      f"「{names[1]}」" in e.solution, e.solution)
aligner_src = _read("subtitle/aligner.py")
check(f"對齊失敗時建議改用的模式是介面上的名字（「{names[0]}」）",
      f"請改用「{names[0]}」" in aligner_src)
pipeline_src = _read("subtitle/pipeline.py")
check(f"批次缺文字稿的錯誤用介面上的名字（「{names[1]}」）",
      f'f"「{names[1]}」需要文字稿' in pipeline_src)

import cli  # noqa: E402

help_text = " ".join(a.help or "" for a in cli.build_parser()._actions) \
    if hasattr(cli, "build_parser") else _read("cli.py")
check("命令列 --mode 說明用新名字",
      f"transcribe＝{names[0]}" in help_text and f"align＝{names[1]}" in help_text)

readme = _read("README.md")
bad = [ln for ln in readme.splitlines() if OLD_NUMBER.search(ln) and "舊版" not in ln]
check("README 只剩一行新舊對照提到「模式一／二／三」", not bad, str(bad[:3]))
mapping = [ln for ln in readme.splitlines() if OLD_NUMBER.search(ln)]
check("README 新舊對照那一行列的是介面上的三個名字、順序相同",
      len(mapping) == 1 and "".join(f"〔{n}〕" for n in names) in mapping[0],
      str(mapping))
for n in names:
    check(f"README 使用說明有「### {n}」一節", f"\n### {n}\n" in readme)
# 「影片／音訊轉錄為 SRT 字幕」是一般敘述、不是模式名稱，所以 README 只抓
# 當成名字用的寫法：標題、功能表的欄位、括號引號。
old_as_name = [p for n in OLD_NAMES + ("音訊轉錄字幕",)
               for p in (f"### {n}\n", f"| {n} |", f"「{n}」", f"〔{n}〕")
               if p in readme] + [n for n in ("手動字幕模式",) if n in readme]
check("README 沒有把舊名當名字用", not old_as_name, str(old_as_name))

# ===== 3. 發佈政策 ======================================================

promote = _read(".github/promote_releases.txt")
promoted = set(re.findall(r"^(v\d+\.\d+\.\d+)\s*$", promote, re.M))
m = re.search(r'APP_VERSION = "(\d+)\.(\d+)\.(\d+)"', _read("updater.py"))
version = tuple(int(g) for g in m.groups()) if m else (0, 0, 0)
check("APP_VERSION 已進到 2.3.1 以上", version >= (2, 3, 1), str(version))
if "v2.3.0" not in promoted:
    check("v2.3.0 還沒轉正，v2.3.1 也不能轉正", "v2.3.1" not in promoted)
changelog = _read("CHANGELOG.md")
head = changelog.split("\n## ", 2)[1].split("\n", 1)[0] if "\n## " in changelog else ""
check("CHANGELOG 最新一條是 v2.3.1 且標明測試版",
      head.startswith("v2.3.1") and "測試版" in head, head)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v2.3.1 模式命名測試全數通過。")
