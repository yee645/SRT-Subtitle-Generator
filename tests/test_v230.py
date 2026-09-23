# -*- coding: utf-8 -*-
"""
v2.3.0 回歸測試：螢幕畫面翻譯的四個產出物。

`tests/test_v220.py` 守的是「每個次版都要有四個產出物」這條不變式；這裡
守的是 **2.3 這一份的內容講的是真話**——文件寫的按鈕名稱、熱鍵、上限、
語言，要跟程式實際的一致。這幾樣都是之後很可能被改掉、而文件忘了跟著改
的東西（熱鍵就已經改過一次），所以一律**從程式裡把真值抓出來**再比，不
在測試裡再寫死一次。

另外守兩件發佈政策上的事：次版先維持測試版（不在轉正清單裡），以及文件
照實列出沒有在 Windows 上實測的部分。
"""
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


from subtitle import hotkey, ocrengine, speech  # noqa: E402

doc = _read("docs/WHATS_NEW_2.3.md")
readme = _read("README.md")
changelog = _read("CHANGELOG.md")
dialog_src = _read("gui/whatsnew_dialog.py")
panel_src = _read("gui/quicktranslate_panel.py")
promote = _read(".github/promote_releases.txt")

section = changelog.split("\n## v2.3.0", 1)[1] if "\n## v2.3.0" in changelog else ""
nxt = re.search(r"\n## v", section)
section = section[:nxt.start()] if nxt else section
check("CHANGELOG 找得到 v2.3.0 那一條", bool(section.strip()))

import gui.whatsnew_dialog as wd  # noqa: E402
v23_features = [(t, d) for t, d in wd.NEW_FEATURES if "v2.3" in t]
dialog_text = "\n".join(t + d for t, d in v23_features)
check("程式內速覽有 v2.3 的條目", len(v23_features) >= 1)
check("速覽裡 v2.3 排在最前面（從 v2.1.0 跳上來的人最大的新東西）",
      bool(wd.NEW_FEATURES) and "v2.3" in wd.NEW_FEATURES[0][0],
      wd.NEW_FEATURES[0][0] if wd.NEW_FEATURES else "")

# ===== 1. 版本與發佈政策 ================================================

m = re.search(r'APP_VERSION = "(\d+)\.(\d+)\.(\d+)"', _read("updater.py"))
version = tuple(int(g) for g in m.groups()) if m else (0, 0, 0)
check("APP_VERSION 已進到 2.3.0 以上", version >= (2, 3, 0), str(version))
check("次版先維持測試版：v2.3.0 不在轉正清單（等使用者決定）",
      not re.search(r"^v2\.3\.0\s*$", promote, re.M))
check("CHANGELOG 標題標明是測試版", "測試版" in changelog.split("\n", 3)[2]
      if changelog.startswith("# ") else False, changelog.split("\n", 3)[2])

# ===== 2. 文件講的要跟程式一致 ==========================================

combo = hotkey.DEFAULT_HOTKEY["combo"]
places = {"WHATS_NEW_2.3.md": doc, "CHANGELOG v2.3.0": section,
          "README": readme, "速覽 v2.3 條目": dialog_text}
for label, text in places.items():
    check(f"{label} 寫的熱鍵就是程式的預設熱鍵（{combo}）", combo in text)
# 每一處提到的 Ctrl+ 組合鍵都只能是預設那組（README 另有剪貼簿的 Ctrl+C）。
# 熱鍵改過一次（Ctrl+Shift+Z 是剪輯軟體的「重做」），舊的寫法一個都不能留。
for label, text in places.items():
    combos = set(re.findall(r"Ctrl\+[A-Za-z0-9]+(?:\+[A-Za-z0-9]+)*", text))
    allowed = {combo, "Ctrl+C"} if label == "README" else {combo}
    check(f"{label} 沒有其他（或舊的）熱鍵寫法", combos <= allowed,
          str(combos - allowed))

# 按鈕名稱從面板原始碼抓，不在這裡再寫一次。
labels = re.findall(r'text="(框選螢幕翻譯|翻譯辨識結果)"', panel_src)
check("從面板原始碼抓得到兩顆按鈕的名稱", sorted(labels) == ["框選螢幕翻譯", "翻譯辨識結果"],
      str(labels))
check("熱鍵勾選的字是『熱鍵 ＋ 預設組合鍵』",
      'return f"熱鍵 {combo}"' in panel_src)
for name in labels:
    for label, text in places.items():
        check(f"{label} 用的按鈕名稱與介面一致（〔{name}〕）", name in text)

limit = speech.DEFAULT_SPEECH["max_chars"]
check(f"文件寫的朗讀上限就是程式的上限（{limit} 字）", f"{limit} 字" in doc)

size = re.search(r'self\.geometry\("(\d+)x(\d+)"\)',
                 panel_src.split("class QuickTranslatePanel", 1)[1])
w, h = size.groups() if size else ("?", "?")
check(f"README 寫的面板預設大小就是程式的（{w}×{h}）", f"{w}×{h}" in readme)
check(f"CHANGELOG 寫的新高度就是程式的（{h}）", f"→ {h}" in section)

names = {"eng": "英", "jpn": "日", "chi_tra": "繁中", "chi_sim": "簡中", "kor": "韓"}
listed = "、".join(names.get(code, code) for code in ocrengine.AUTO_LANGS)
for label, text in (("WHATS_NEW_2.3.md", doc), ("CHANGELOG v2.3.0", section),
                    ("README", readme)):
    # 要整串相符：只比子字串的話，程式少掉後面幾種語言（「英、日、繁中」
    # 是「英、日、繁中、簡中、韓」的子字串）照樣通過——破壞探針抓到的。
    check(f"{label} 列的自動辨識語言與程式一致（{listed}）",
          re.search("(?<!、)" + re.escape(listed) + "(?!、)", text) is not None)
check("程式的預設辨識語言是 auto（文件說『不用選』）",
      ocrengine.DEFAULT_OCRENGINE["lang"] == "auto")

# ===== 3. 涵蓋上一個正式版以來的全部改動 ================================

last = re.findall(r"^v(\d+\.\d+\.\d+)\s*$", promote, re.M)[-1]
check(f"文件寫給上一個正式版（v{last}）的使用者看", f"v{last}" in doc)
check("文件交代中間的測試版 v2.2.0 並連到它的介紹",
      "v2.2.0" in doc and "WHATS_NEW_2.2.md" in doc)

# ===== 4. 照實寫：隱私與沒實測的部分 ====================================

for phrase in ("不會被傳出去", "只截你框的那一塊", "先給你看", "像密碼或金鑰",
               "讀不到字"):
    check(f"文件講清楚隱私規則：「{phrase}」", phrase in doc)
check("文件寫明熱鍵預設關閉", "預設**關閉**" in doc)
unverified = doc.split("哪些在 Windows 上還沒親眼看過", 1)[-1].split("\n## ", 1)[0]
for item in ("截圖", "縮放", "熱鍵", "朗讀", "安裝"):
    check(f"未實測清單列了「{item}」", item in unverified)
check("未實測清單每一列都寫了萬一不行會怎樣",
      all(row.count("|") >= 4 for row in unverified.splitlines()
          if row.startswith("| ") and "---" not in row))
check("限制照實寫（獨佔全螢幕、不做連續翻譯、只支援主螢幕）",
      all(p in doc for p in ("全螢幕獨佔", "不做連續即時翻譯", "只支援主螢幕")))
check("介紹文件是寫給使用者看的：不出現函式名或內部識別字",
      not any(t in doc for t in ("_build_", "def ", "ttk.", "self.", "winfo_",
                                 "is_secret", "scale_region", "AUTO_LANGS",
                                 "tesseract_available")))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v2.3.0 四個產出物內容測試全數通過。")
