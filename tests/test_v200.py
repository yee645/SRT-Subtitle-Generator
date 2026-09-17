# -*- coding: utf-8 -*-
"""
v2.0.0 掛版前置條件測試。

使用者 2026-09-13 指示：「到時發布 2.0 記得要寫一份完整的新增功能介紹」，
`docs/ROADMAP_2.0.md` 7-1 節把它列為**掛版的硬性前置條件**。這一份測的就
是那個條件有沒有真的達成——不是「有沒有一個檔案」，而是：

1. **四個產出物都在**（主文件、CHANGELOG 條目、README、程式內速覽）。
2. **範圍對**：涵蓋 1.51.0 → 2.0.0 的全部改動，不是只寫最後一版。這是
   7-1 節點名「最容易寫錯」的地方——使用者的自動更新一直停在 v1.51.0，
   轉正那一刻是一次跳過來的。
3. **數字一致**：主文件、CHANGELOG、程式內速覽三處引用的實測值必須是同
   一組。三個地方各寫各的就是遲早會有一處過期。
4. **程式內速覽補上了「新增了什麼」那一半**（v1.52.1 版只講搬家）。
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


def read(*parts):
    path = os.path.join(ROOT, *parts)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fp:
        return fp.read()


# ===== 1. 四個產出物都在 =============================================
whats_new = read("docs", "WHATS_NEW_2.0.md")
check("產出物①：docs/WHATS_NEW_2.0.md 存在", whats_new is not None)
migration = read("docs", "MIGRATION_1x_TO_2.0.md")
check("1.x→2.0 對照表存在（1.52.3 定稿）", migration is not None)

changelog = read("CHANGELOG.md")
check("產出物②：CHANGELOG 有 v2.0.0 條目",
      changelog is not None and "## v2.0.0" in changelog)

readme = read("README.md")
check("產出物③：README 指向新功能介紹",
      readme is not None and "WHATS_NEW_2.0.md" in readme)

dialog = read("gui", "whatsnew_dialog.py")
check("產出物④：程式內速覽存在", dialog is not None)

updater = read("updater.py")
# 原本寫死 `APP_VERSION == "2.0.0"`，但版號本來就會往前走（v2.1.0 之後這
# 條必然失敗）。真正要守的是「**2.0 之後**的版本都受這份前置條件約束」，
# 所以改成比大小而不是比字串相等。
import re as _re
_m = _re.search(r'APP_VERSION = "(\d+)\.(\d+)\.(\d+)"', updater or "")
check("讀得到 APP_VERSION", _m is not None)
if _m:
    _ver = tuple(int(g) for g in _m.groups())
    check(f"APP_VERSION（{'.'.join(map(str, _ver))}）已達 2.0.0 以上",
          _ver >= (2, 0, 0), str(_ver))

if whats_new is None or changelog is None or dialog is None:
    print()
    print("失敗：產出物缺漏，後續檢查無法進行。")
    sys.exit(1)


# ===== 2. 範圍：涵蓋 1.51.0 → 2.0.0 ==================================
check("主文件開宗明義講清楚讀者是「從 v1.51.0 更新上來的」",
      "1.51.0" in whats_new and "v1.51.0" in whats_new)
check("主文件明講中間幾版是不推自動更新的測試版（否則讀者不知道為什麼"
      "一次跳這麼多）",
      "測試版" in whats_new and "自動更新" in whats_new)

# 中間四版的主題都要被涵蓋到，不能只寫最後一版。
COVERAGE = {
    "v1.52.0 三欄化／主按鈕在畫面外": ["y=826"],
    "v1.52.1 四階段頁籤": ["四個階段", "素材與剪輯"],
    "v1.52.1 拆一鍵完成": ["一鍵完成", "開始生成字幕", "完成輸出"],
    "v1.52.1 輸出面合一": ["輸出設定"],
    "v1.52.2 產出自動流入": ["發佈資料", "送健檢中心"],
    "v1.52.2 世代鏈": ["粗剪", "修復版"],
    "v1.52.3 自動修剪併窗": ["自動修剪", "剪重複片段"],
    "v1.50–1.51 健檢中心": ["健檢中心", "18 項"],
    "選取即翻譯": ["即時查譯"],
}
for topic, needles in COVERAGE.items():
    miss = [n for n in needles if n not in whats_new]
    check(f"主文件涵蓋「{topic}」", not miss, f"缺：{miss}")

check("主文件有寫升級須知（設定沿用、CLI 相容）",
      "設定會沿用" in whats_new and "CLI" in whats_new)
check("主文件有寫「沒有變的事」，讓人確認能力沒被拿掉",
      "沒有變的事" in whats_new)
check("主文件是寫給使用者看的：不出現函式名或內部識別字",
      not any(token in whats_new for token in
              ("_build_", "def ", "ttk.", "self.", "winfo_")),
      "出現了內部識別字")


# ===== 3. 三處引用的實測數字必須一致 =================================
# 這一組是當場量出來的（量法見 docs/UI_AUDIT_2.0.md 1.2 節同一情境）。
# **要連單位一起比對**：只比 "31" 會被 "−31%" 誤中（破壞探針實測：把
# CHANGELOG 的點擊數改成 25 次，因為 "−31%" 還在，檢查竟然照樣通過）。
MEASURED = {"clicks_new": "31 次", "windows_new": "7 個",
            "clicks_old": "43–46 次", "windows_old": "17–19 個",
            "y_new": "y=131", "y_old": "y=826"}

audit = read("docs", "UI_AUDIT_2.0.md")
check("稽核文件已寫回 2.0 的實測值（7-1 節要求量完寫回去）",
      audit is not None and "2.0 實測對照" in audit)

# 只檢查「字串有沒有出現」擋不住不一致：31 次、7 個在文件裡本來就出現多
# 次（例如「剩下的 31 次裡有 17 次是內容工作」），改掉其中一處另一處還
# 在，presence 檢查照樣通過——破壞探針實測證實會漏。所以改成**從各自的對
# 照表列裡把數字抓出來再互比**。
def pull(text, pattern, label):
    match = re.search(pattern, text)
    if match is None:
        check(f"{label}：找得到對照表那一列", False, pattern)
        return None
    return match.group(1)

# CHANGELOG 只抓 v2.0.0 那一節：v2.2.0 起後續版本各自有自己的實測表，
# 拿整份檔案去 re.search 只會抓到最上面那一版的數字（那是 2.2 的，不是
# 2.0 的）。鎖到版本區段之後這條反而比原本更嚴——它現在比的真的是 2.0。
def section(text, heading):
    if heading not in text:
        return ""
    body = text.split(heading, 1)[1]
    nxt = re.search(r"\n## v", body)
    return body[:nxt.start()] if nxt else body


changelog_200 = section(changelog, "## v2.0.0")
check("CHANGELOG 的 v2.0.0 區段抓得到", bool(changelog_200.strip()))

doc_clicks = pull(whats_new, r"\|\s*點擊\s*\|[^|]*\|\s*\*\*(\d+)\s*次\*\*", "主文件點擊")
doc_windows = pull(whats_new, r"\|\s*開啟視窗\s*\|[^|]*\|\s*\*\*(\d+)\s*個\*\*", "主文件視窗")
log_clicks = pull(changelog_200, r"\|\s*點擊\s*\|[^|]*\|\s*\*\*(\d+)\s*次\*\*", "CHANGELOG 點擊")
log_windows = pull(changelog_200, r"\|\s*開啟視窗\s*\|[^|]*\|\s*\*\*(\d+)\s*個\*\*", "CHANGELOG 視窗")

check("2.0 的「點擊數」在主文件與 CHANGELOG v2.0.0 區段是同一個數字",
      doc_clicks == log_clicks == MEASURED["clicks_new"].split()[0],
      f"主文件={doc_clicks} CHANGELOG={log_clicks} "
      f"應為={MEASURED['clicks_new']}")
check("2.0 的「視窗數」是同一個數字",
      doc_windows == log_windows == MEASURED["windows_new"].split()[0],
      f"主文件={doc_windows} CHANGELOG={log_windows} "
      f"應為={MEASURED['windows_new']}")

# 程式內速覽只有一份、跟著最新版走，所以它比的對象是**最新那一份新功能
# 介紹**，不是 2.0 那一份（原本寫死比 2.0，是「當下狀態」的斷言：2.2 起
# 速覽顯示的必然是新數字，寫死就只會逼人把速覽留在過期的數字上）。
def latest_whats_new():
    best = None
    for name in os.listdir(os.path.join(ROOT, "docs")):
        m = re.fullmatch(r"WHATS_NEW_(\d+)\.(\d+)\.md", name)
        if m:
            key = (int(m.group(1)), int(m.group(2)))
            if best is None or key > best[0]:
                best = (key, name)
    return best


_latest = latest_whats_new()
check("找得到最新一份新功能介紹", _latest is not None)
if _latest is not None:
    latest_name = _latest[1]
    latest_doc = read("docs", latest_name)
    latest_clicks = pull(latest_doc,
                         r"\|\s*點擊\s*\|[^|]*\|\s*\*\*(\d+)\s*次\*\*",
                         f"{latest_name} 點擊")
    latest_windows = pull(latest_doc,
                          r"\|\s*開啟視窗\s*\|[^|]*\|\s*\*\*(\d+)\s*個\*\*",
                          f"{latest_name} 視窗")
    dlg_clicks = pull(dialog, r"點擊[^\n]*?→\s*(\d+)\s*次", "速覽點擊")
    dlg_windows = pull(dialog, r"開啟視窗[^\n]*?→\s*(\d+)\s*個", "速覽視窗")
    check(f"程式內速覽的點擊數與最新一份介紹（{latest_name}）一致",
          dlg_clicks == latest_clicks, f"速覽={dlg_clicks} 文件={latest_clicks}")
    check(f"程式內速覽的視窗數與最新一份介紹（{latest_name}）一致",
          dlg_windows == latest_windows,
          f"速覽={dlg_windows} 文件={latest_windows}")

for label, value in MEASURED.items():
    check(f"實測值「{value}」（{label}）在主文件與 CHANGELOG 都出現",
          value in whats_new and value in changelog,
          f"主文件={value in whats_new} CHANGELOG={value in changelog}")
for value in (MEASURED["y_new"], MEASURED["y_old"]):
    check(f"實測值「{value}」也出現在程式內速覽", value in dialog, value)

# 不可以留著「預估」那組數字冒充實測。
check("主文件誠實交代實測比預估差，並寫出原因（不是拿預估值充數）",
      "20 次" in whats_new and "校對" in whats_new,
      "沒有找到對預估落差的說明")
check("CHANGELOG 的 v2.0.0 區段同樣交代了落差", "20 次" in changelog_200)


# ===== 4. 程式內速覽補上「新增了什麼」那一半 =========================
try:
    from gui.whatsnew_dialog import (MOVED, NEW_FEATURES, RENAMED,
                                     SAVINGS_TEXT, SPLIT_TEXT, should_show,
                                     NEVER_SHOW)
except ImportError as exc:
    print(f"SKIP 速覽內容測試（無 tkinter：{exc}）")
else:
    check("速覽有「新增了什麼」那一半（v1.52.1 版只講搬家）",
          len(NEW_FEATURES) >= 5, str(len(NEW_FEATURES)))
    check("速覽仍保留搬家對照（兩半都要有）", len(MOVED) >= 5)
    check("速覽仍保留改名對照", len(RENAMED) >= 2)
    for title, detail in NEW_FEATURES:
        check(f"新能力條目「{title[:16]}」有寫實際內容、不是只有標題",
              len(detail) >= 20, f"{len(detail)} 字")
    # 速覽跟著最新版走，所以這裡驗的是「它和最新那份介紹講同一組數字」，
    # 上面已經逐一比過；這裡只再確認它真的寫了兩個數字、不是空的。
    check("速覽真的寫出了省力數字（不是只有標題）",
          "點擊" in SAVINGS_TEXT and "開啟視窗" in SAVINGS_TEXT
          and re.search(r"→\s*\d+\s*次", SAVINGS_TEXT) is not None)
    check("速覽仍說明「一鍵完成」為什麼拆", "校對" in SPLIT_TEXT)

    # 版本規則：2.0 要對 1.52.x 的使用者再跳一次（他們沒看過新能力那半）。
    check("看過 v1.52.1 速覽的人，2.0.0 會再跳一次（新增的那半他沒看過）",
          should_show({"whatsnew_seen": "1.52.1"}, "2.0.0"))
    check("看過 2.0.0 就不再跳",
          not should_show({"whatsnew_seen": "2.0.0"}, "2.0.0"))
    check("勾過「不再顯示」的人不會被打擾",
          not should_show({"whatsnew_seen": NEVER_SHOW}, "2.0.0"))


# ===== 5. 轉正與這份前置條件的關係 ===================================
# 原本斷言「promote_releases.txt 裡不可以有 v2.0.0」，那是寫在「轉正尚未
# 執行」當下的狀態快照——使用者 2026-09-17 指示轉正之後，這條必然失敗。
#
# 換成真正該永久成立的那條規則：**任何 2.x 被轉正時，四個產出物都必須存
# 在**。轉正會把自動更新推給所有使用者，而這份介紹就是他們唯一會看到的說
# 明；「已經轉正但文件不見了」才是要擋的事，「有沒有轉正」本身不是。
promote = read(".github", "promote_releases.txt")
check("讀得到轉正清單", promote is not None)
if promote is not None:
    promoted_2x = [line.strip() for line in promote.splitlines()
                   if line.strip().startswith("v2.")]
    if promoted_2x:
        check(f"已轉正的 2.x（{', '.join(promoted_2x)}）都有完整的新功能介紹"
              "——轉正就是推給所有使用者，這份介紹是他們唯一看得到的說明",
              whats_new is not None and changelog is not None
              and "WHATS_NEW_2.0.md" in (readme or "")
              and dialog is not None)
    else:
        print("SKIP 尚未有 2.x 被轉正，這一組檢查沒有對象")


print()
if failures:
    print(f"失敗 {len(failures)} 項：" + ", ".join(failures))
    sys.exit(1)
print("v2.0.0 掛版前置條件（完整新功能介紹）測試全數通過。")
