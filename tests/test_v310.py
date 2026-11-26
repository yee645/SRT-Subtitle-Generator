# -*- coding: utf-8 -*-
"""
v3.1.0（剪輯器版面 E-7c）：發版與文件講的東西對得上程式。

1. APP_VERSION 是 3.1 系列（正式版那一套標題、導覽照舊）；打包的 zip 名稱跟著版本。
2. CHANGELOG 的 v3.1.0（Release notes 抽這一段）：講剪輯器版面、怎麼切回四頁籤（按鈕名稱、--tabs）、
   連到 WHATS_NEW_3.1.md（完整網址）。
3. docs/WHATS_NEW_3.1.md：寫到的按鈕、區塊、視窗名稱在程式裡真的有（原始碼裡找得到同一串字）；
   快捷鍵跟剪輯器版面介紹（editorguide.KEYS）一致；四頁籤的四頁都講了在哪；寫了會送出去什麼；
   沒有點擊數表（那是 2.x 速覽比對用的，這份沒有實測點擊數）。
4. README、使用說明指向 WHATS_NEW_3.1.md，講預設是剪輯器版面與 --tabs。
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
from subtitle import editorguide, qtguide  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fp:
        return fp.read()


# ----- 1 -----
version = updater.APP_VERSION
check("APP_VERSION 是 3.1 系列", re.fullmatch(r"3\.1\.\d+", version) is not None, version)
check("正式版那一套（標題、四頁籤導覽）照舊", qtguide.is_formal(version))
check("zip 名稱跟著版本", qt_preview.zip_name(version, "win64") == f"SRT-Subtitle-Generator-Qt-v{version}-win64.zip")

# ----- 2 -----
changelog = read("CHANGELOG.md")
m = re.search(rf"^## v{re.escape(version)}.*?$(.*?)(?=^## |\Z)", changelog, re.M | re.S)
notes = m.group(1).strip() if m else ""
check("CHANGELOG 有這一版的段落", bool(notes))
check("notes 講剪輯器版面是預設", "預設換成剪輯器版面" in changelog.split("\n## ")[1])
check("notes 講怎麼切回四頁籤（按鈕名稱、--tabs）", "〔改用四頁籤版面…〕" in notes and "〔改用剪輯器版面…〕" in notes
      and "--tabs" in notes)
check("notes 連到 WHATS_NEW_3.1.md（完整網址）",
      "https://github.com/yee645/SRT-Subtitle-Generator/blob/main/docs/WHATS_NEW_3.1.md" in notes)
check("notes 講剪輯器版面介紹", "剪輯器版面介紹" in notes)

# ----- 3 -----
doc = read("docs", "WHATS_NEW_3.1.md")
src = "\n".join(open(p, encoding="utf-8").read() for d in ("gui_qt", "gui")  # 〔下載並安裝新介面〕在一般版
                for p in glob.glob(os.path.join(ROOT, d, "*.py")))
src += read("subtitle", "editorguide.py")
for name in ("〔匯入素材…〕", "〔加到播放頭〕", "〔開成主片〕", "〔匯出〕", "〔分割〕", "〔字幕樣式…〕", "〔配樂設定…〕",
             "〔編輯用代理檔〕", "〔下載並安裝〕", "〔下載並安裝新介面〕"):
    check(f"介紹寫的 {name} 在程式裡有", name in doc and name.strip("〔〕") in src, name)
for name in ("一鍵完成輸出", "剪好的影片", "字幕檔", "品牌套版"):
    check(f"匯出視窗的「{name}」在程式裡有", name in doc and f'"{name}"' in src)
for name in ("媒體", "字幕", "智慧剪輯", "健檢"):
    check(f"左邊「{name}」在程式裡有", f"左邊「{name}」" in doc or f"**{name}**" in doc)
check("介紹的名稱跟程式一致（剪輯器版面介紹）", "剪輯器版面介紹" in doc and "剪輯器版面介紹" in src)
check("按鈕字樣跟程式一致（改用四頁籤版面…、按此取消）", "〔改用四頁籤版面…〕" in doc and "〔改用剪輯器版面…〕" in doc
      and "下次開：四頁籤版面（按此取消）" in doc and "改用{name}…" in src and "（按此取消）" in src)
table = doc.split("### 快捷鍵")[1].split("\n### ")[0] if "### 快捷鍵" in doc else ""
for key, _what in editorguide.KEYS:
    check(f"快捷鍵表有 {key} 這一列（跟剪輯器版面介紹一致）", f"| {key} |" in table, key)
check("四頁籤的四頁都講了在哪", all(c in doc.split("## 四頁籤的東西在哪裡")[1].split("\n## ")[0] for c in "①②③④"))
check("講了 --tabs 與 --editor", "--tabs" in doc and "--editor" in doc)
check("講了會送出去什麼", "**會送出去的**" in doc)
check("沒有點擊數表（不會被拿去跟 2.x 速覽比）", not re.search(r"\|\s*點擊\s*\|", doc))
check("zip 檔名格式跟打包流程一樣", qt_preview.zip_name("3.1.0", "win64").replace("v3.1.0", "v<版本>") in doc)
check("指回 3.0 的介紹（給還沒裝過新介面的人）", "WHATS_NEW_3.0.md" in doc)

# ----- 4 -----
readme = read("README.md")
check("README：3.1 一節連到介紹", "見 **[3.1 新功能介紹](docs/WHATS_NEW_3.1.md)**" in readme)
check("README：介紹清單把 3.1 排在 3.0 前面", "[3.1 新功能介紹（剪輯器版面）](docs/WHATS_NEW_3.1.md)" in readme
      and readme.index("[3.1 新功能介紹（剪輯器版面）]") < readme.index("[3.0 新功能介紹（新介面）]"))
check("README：3.1 一節排在 3.0 一節前面", "## 3.1：剪輯器版面" in readme
      and readme.index("## 3.1：剪輯器版面") < readme.index("## 3.0：新介面"))
check("README 講預設剪輯器版面與 --tabs", "剪輯器版面" in readme and "--tabs" in readme)
guide = read("docs", "USER_GUIDE.md")
check("使用說明有 3.1 剪輯器版面一節", "### 3.1 剪輯器版面" in guide and "WHATS_NEW_3.1.md" in guide
      and "--tabs" in guide)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v3.1.0 發版與文件測試全數通過。")
