# -*- coding: utf-8 -*-
"""
3.0 第 12 項 12-6：3.0.0 的產出物（新功能介紹、README、使用說明、兩邊的程式內導覽）講的東西對得上程式。

CHANGELOG 的 v3.0.0 條目跟 APP_VERSION 一起在 12-7 寫（CHANGELOG.md 是 release.yml 的觸發路徑，版本沒動時改它
會白跑一次發版流程）；到那時 test_v220.py「跟著 APP_VERSION 走」的四個產出物不變式會一起驗。

1. docs/WHATS_NEW_3.0.md：範圍從 v2.3.6（3.0 之前最後一個正式版）講起；檔名（zip、兩個 exe、資料夾）跟打包流程
   與橋的核心一樣；〔…〕括起來的按鈕在程式裡真的有；數字跟 README 一致；寫明會送什麼、已知限制（影音同步沒量過、
   只打包 Windows）、一般版怎麼回去。
2. README：指向 WHATS_NEW_3.0.md、講兩個介面與下載的檔名；不再說打包版沒有 Qt 版。
3. USER_GUIDE：3.0 那一節不再是「預覽版、exe 不含 Qt 版」；自動更新那一節講新介面怎麼更新。
4. 一般版的程式內速覽：v3.0 的條目排最前面，講的按鈕跟橋的視窗一樣。
5. 講到的 `--tk`：12-7 切預設時才加進 main.py；APP_VERSION 到 3.0.0 時這一條就會驗。
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "packaging"))

import qt_preview  # noqa: E402
import updater  # noqa: E402
from subtitle import onedirupdate as odu  # noqa: E402
from subtitle import qtbridge as qb  # noqa: E402
from subtitle import qtguide  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fp:
        return fp.read()


doc = read("docs/WHATS_NEW_3.0.md")
readme = read("README.md")
guide = read("docs/USER_GUIDE.md")
qt_src = "".join(read(os.path.relpath(p, ROOT)) for p in glob.glob(os.path.join(ROOT, "gui_qt", "*.py")))
tk_src = "".join(read(os.path.relpath(p, ROOT)) for p in glob.glob(os.path.join(ROOT, "gui", "*.py")))

# ----- 1 -----
check("範圍從 v2.3.6 講起（3.0 之前最後一個正式版）", "v2.3.6" in doc.split("---")[0]
      and "## v2.3.6" in read("CHANGELOG.md"))
zip_name = qt_preview.zip_name("3.0.0", "win64")
check("zip 檔名跟打包流程 3.0.0 打出來的一樣", f"`{zip_name}`" in doc and "preview" not in zip_name, zip_name)
check("兩個 exe、資料夾的名稱跟程式一樣", f"`{odu.EXE_NAME}`" in doc and f"`{updater.ASSET_NAME}`" in doc
      and f"`{qb.QT_FOLDER}`" in doc)
buttons = sorted(set(re.findall(r"〔([^〕]+)〕", doc)))
missing = [b for b in buttons if f'"{b}' not in qt_src and f"'{b}" not in qt_src and f'"{b}' not in tk_src]
check("介紹講的每一顆按鈕在程式裡真的有", buttons and not missing, f"找不到：{missing}；全部：{buttons}")
check("橋的按鈕名稱一字不差", f"〔{'下載並安裝新介面'}〕" in doc and "下載並安裝新介面" in read("gui/qtbridge_dialog.py"))
sizes = re.findall(r"zip 約 \*\*(\d+) MB\*\*，解開約 \*\*(\d+) MB\*\*", doc)
check("寫了量到的大小、README 寫的一樣", len(sizes) == 1 and f"zip 約 {sizes[0][0]} MB，解開約 {sizes[0][1]} MB" in readme,
      str(sizes))
check("寫明會送什麼", "不送任何檔案、字幕、設定或帳號資訊" in doc)
check("照實講限制：只打包 Windows、影音同步沒量過、一般版怎麼回去",
      "只打包 Windows" in doc and "影音同步沒有在有音效卡的機器上量過" in doc and "--tk" in doc
      and "SRT-Subtitle-Generator.exe" in doc.split("## 已知的限制")[1])

rows = re.findall(r"^\| [^|]+ \| ([^|]+) \|$", doc.split("## 一般版的東西")[1].split("\n---\n")[0], re.M)[1:]
check("「東西在哪」的對照跟程式內導覽同一套說法（每一列的新位置都在導覽裡）", len(rows) >= 8 and all(
    any(re.split(r"[（，]", new.strip())[0] in n for _o, n in qtguide.WHERE)
    for new in rows), str(rows))
check("不再講預覽版", "預覽版" not in doc)

# ----- 2 -----
check("README 指向 WHATS_NEW_3.0.md", "docs/WHATS_NEW_3.0.md" in readme)
check("README 講兩個介面與下載的檔名", "新介面" in readme and "一般版" in readme and odu.EXE_NAME in readme
      and "SRT-Subtitle-Generator-Qt-v<版本>-win64.zip" in readme and updater.ASSET_NAME in readme)
check("README 的頁籤名稱跟程式一樣", all(t in readme for t in ("① 素材與剪輯", "② 字幕", "③ 健檢中心", "④ 輸出與發佈")))

# ----- 3 -----
check("使用說明：3.0 那一節不再是預覽版、不再說 exe 不含 Qt 版", "### 3.0 新介面" in guide
      and "3.0 預覽版（開發中" not in guide and "目前不含" not in guide)
check("使用說明：自動更新講新介面怎麼更新、指向介紹", "〔下載並安裝〕" in guide and "關掉程式時" in guide
      and "WHATS_NEW_3.0.md" in guide)

# ----- 4 -----
try:
    import gui.whatsnew_dialog as wd
except ImportError as exc:  # 沒有 tkinter
    print(f"SKIP 速覽（{exc}）")
else:
    first_title, first_detail = wd.NEW_FEATURES[0]
    check("一般版速覽：v3.0 排最前面、講新介面與怎麼裝", "v3.0" in first_title and "〔下載並安裝新介面〕" in first_detail
          and "一般版照樣能用" in first_detail and "WHATS_NEW_3.0.md" in first_detail, first_title)

# ----- 5 -----
if qtguide.is_formal(updater.APP_VERSION):
    check("講的 --tk 在 main.py 真的有", '"--tk"' in read("main.py"))
else:
    print("SKIP --tk：12-7 切預設時才加進 main.py（APP_VERSION 到 3.0.0 時這一條就會驗）")

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0.0 產出物測試全數通過。")
