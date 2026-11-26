# -*- coding: utf-8 -*-
"""
剪輯器版面 E-7a：四頁籤的位置說法 → 剪輯器的說法（subtitle/placenames.py）。

1. 面板與對話框裡每一段帶 ①～④ 的說明文字（原始碼裡的字串，不含 docstring），換過之後都不再有頁籤編號，
   而且真的換了（不是整段丟掉）。
2. 幾段代表性的文字逐字比對：長的、特定的規則先套（「②字幕頁開著的」是「現在開著的」，不是「開著的」）。
3. 沒有頁籤編號的文字原樣回傳（同一個物件）；不是字串的也不碰。
4. 原始碼檢查：這些檔案的方法裡，帶頁籤編號的字串都經過 here(self, …)（之後才顯示的字也換得到）。
"""
import ast
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from subtitle.placenames import CIRCLED, RULES, for_editor, has_tab_place  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


PAT = re.compile(f"[{CIRCLED}]")
# 只出現在四頁籤外殼的字（頁籤名稱、四頁籤的開場白）與剪輯器自己：不經過換字
SHELL_ONLY = {"app.py", "editor.py", "__init__.py", "places.py"}


def docstring_ids(tree):
    ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and n.body \
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
            ids.add(id(n.body[0].value))
    return ids


def panel_files():
    return [f for f in sorted(glob.glob(os.path.join(ROOT, "gui_qt", "*.py"))) if os.path.basename(f) not in SHELL_ONLY]


# ----- 1 -----
strings = []
for path in panel_files():
    tree = ast.parse(open(path, encoding="utf-8").read())
    docs = docstring_ids(tree)
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and PAT.search(n.value):
            strings.append((os.path.basename(path), n.lineno, n.value))
check("面板裡有帶頁籤編號的說明文字（這份測試量得到東西）", len(strings) >= 55, str(len(strings)))
left = [(f, ln, for_editor(s)) for f, ln, s in strings if has_tab_place(for_editor(s))]
check("換過之後都不再有頁籤編號", not left, str(left[:3]))
same = [(f, ln) for f, ln, s in strings if for_editor(s) == s]
check("每一段都真的換了", not same, str(same[:3]))
gutted = [(f, ln) for f, ln, s in strings if len(s.strip()) > 8 and len(for_editor(s).strip()) < len(s.strip()) // 2]
check("沒有整段被刪掉（換完至少留一半）", not gutted, str(gutted[:3]))

# ----- 2 -----
EXPECT = {
    "檢查對象（②字幕頁開著的）：": "檢查對象（現在開著的）：",
    "②字幕頁還沒有字幕：請先到②按「生成字幕…」或「載入字幕」，再回來分析。":
        "還沒有字幕：請先到左邊「字幕」按「生成字幕…」或「載入字幕」，再回來分析。",
    "②字幕頁還沒開影片：請先到②按「開啟影片」。": "還沒開影片：請先到左邊「媒體」按「開啟影片」。",
    "已加進③健檢中心的「封面圖」（到③按「開始健檢」看手機上讀不讀得清楚）":
        "已加進左邊「健檢」的「封面圖」（到左邊「健檢」按「開始健檢」看手機上讀不讀得清楚）",
    "輸出格式、燒錄與輸出資料夾照④的「輸出設定」，要改請到④。":
        "輸出格式、燒錄與輸出資料夾照〔匯出〕的「輸出設定」，要改請到〔匯出〕。",
    "（②字幕頁按「復原」就還原）": "（按「復原」（Ctrl+Z）就還原）",
    "選一支成功的按〔在②開啟這支〕接著校對。": "選一支成功的按〔開啟這支〕接著校對。",
    "點一段，②的播放器跳到那裡。": "點一段，播放器跳到那裡。",
    "（那些請用②的「照剪點輸出…」「輸出多軌…」）": "（那些請用〔匯出〕的「照剪點輸出…」「輸出多軌…」）",
    "章節與發佈包、封面候選在①審片助手，發佈文字與封面圖的健檢在③。":
        "章節與發佈包、封面候選在左邊「智慧剪輯」，發佈文字與封面圖的檢查在左邊「健檢」。",
    "請改用「③健檢中心」的「開始健檢」。": "請改用左邊「健檢」的「開始健檢」。",
    "或點②字幕清單的一句再按此鈕。": "或點左邊「字幕」的字幕清單的一句再按此鈕。",
}
for src, want in EXPECT.items():
    got = for_editor(src)
    check(f"逐字：{src[:18]}…", got == want, f"\n  得到 {got}\n  應為 {want}")

# 規則的順序：每一條的舊字串，都不是排在它前面某一條舊字串的一部分（不然永遠輪不到它）
shadowed = [(i, old) for i, (old, _n) in enumerate(RULES)
            for prev, _p in RULES[:i] if prev in old]
check("規則順序：特定的排在一般的前面（沒有被前面蓋掉的）", not shadowed, str(shadowed[:3]))
check("規則換完不會產生新的頁籤編號", all(not has_tab_place(new) for _o, new in RULES))

# ----- 3 -----
plain = "還沒有字幕：請先生成字幕。"
check("沒有頁籤編號：原樣回傳同一個物件", for_editor(plain) is plain)
check("不是字串：原樣回傳", for_editor(None) is None and for_editor(3) == 3 and not has_tab_place(None))
check("has_tab_place 認得四個編號", all(has_tab_place(f"到{c}") for c in CIRCLED))

# ----- 4 -----
unwrapped = []
for path in panel_files():
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    docs = docstring_ids(tree)
    consts = {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets
              if isinstance(t, ast.Name) and PAT.search(ast.unparse(n.value))}
    parents = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            parents[id(c)] = n
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for n in ast.walk(fn):
            hit = (isinstance(n, ast.Name) and n.id in consts and isinstance(n.ctx, ast.Load)) or \
                  (isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
                   and PAT.search(n.value))
            if not hit:
                continue
            node = n
            if isinstance(parents.get(id(node)), ast.JoinedStr):
                node = parents[id(node)]
            call = parents.get(id(node))
            ok = isinstance(call, ast.Call) and getattr(call.func, "id", "") == "here" and len(call.args) == 2 \
                and call.args[1] is node and isinstance(call.args[0], ast.Name) and call.args[0].id == "self"
            if not ok:
                unwrapped.append(f"{os.path.basename(path)}:{n.lineno}")
check("方法裡帶頁籤編號的字串都經過 here(self, …)", not unwrapped, str(unwrapped[:5]))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("位置說法（E-7a）測試全數通過。")
