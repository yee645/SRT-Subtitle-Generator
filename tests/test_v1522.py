# -*- coding: utf-8 -*-
"""
v1.52.2 測試：審片產出自動流入／世代鏈。

`docs/UI_AUDIT_2.0.md` ④ 點名三條斷鏈——「產章節→章節健檢要手動貼、產發
佈包→發佈健檢要手動貼、產封面候選圖→封面健檢要手動加檔案」，外加粗剪／
修復版做完之後沒有任何路徑通回主視窗。這一份測的就是那幾條線接上了沒。

分三段：
1. `subtitle/generations.py` 的世代鏈邏輯（純資料，無 GUI）
2. `subtitle/publisher.build_publish_fields` 與 `build_publish_pack` **必須
   同源**——結構化那份與文字那份說法不一致的話，使用者會看到發佈包寫一個
   標題、健檢中心卻檢查另一個標題
3. Xvfb 下的真實回流：adopt_* 三條線、健檢中心對象區預填
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


# ===== 1. 世代鏈 =====================================================
from subtitle import generations as gen

chain = gen.new_chain()
check("空鏈上查不存在的檔案回 None", gen.find(chain, "/x/a.mp4") is None)
check("空鏈上問譜系，回傳「它自己是源頭」而不是空白",
      gen.describe_lineage(chain, "/x/a.mp4") == "原始素材 a.mp4",
      gen.describe_lineage(chain, "/x/a.mp4"))
check("完全沒給路徑時回空字串", gen.describe_lineage(chain, "") == "")

gen.record(chain, "/v/片_粗剪.mp4", "roughcut", "/v/片.mp4")
check("記一筆產出時，沒登記過的來源會自動補成原始素材（否則第一節就斷）",
      len(chain) == 2 and gen.find(chain, "/v/片.mp4")["kind"] == "original",
      str(chain))

gen.record(chain, "/v/片_粗剪_修復.mp4", "audiofix", "/v/片_粗剪.mp4")
gen.record(chain, "/v/片_粗剪_修復_subtitled.mp4", "burned", "/v/片_粗剪_修復.mp4")
check("四代譜系完整且只有源頭寫檔名",
      gen.describe_lineage(chain, "/v/片_粗剪_修復_subtitled.mp4")
      == "原始素材 片.mp4 → 粗剪 → 修復版 → 燒錄版（目前）",
      gen.describe_lineage(chain, "/v/片_粗剪_修復_subtitled.mp4"))

before = len(chain)
gen.record(chain, "/v/片_粗剪.mp4", "roughcut", "/v/片.mp4")
check("同一個路徑重複記錄是更新不是新增（同一支檔案不該在鏈上出現兩次）",
      len(chain) == before, f"{before} → {len(chain)}")

gen.record(chain, "/v/片_粗剪.mp4", "trimmed", "/v/片.mp4")
check("重複記錄會更新種類",
      gen.find(chain, "/v/片_粗剪.mp4")["kind"] == "trimmed")
gen.record(chain, "/v/片_粗剪.mp4", "roughcut", "/v/片.mp4")  # 還原

check("descendants 只列直接子代、不遞迴",
      [e["kind"] for e in gen.descendants(chain, "/v/片.mp4")] == ["roughcut"],
      str(gen.descendants(chain, "/v/片.mp4")))

# 路徑寫法不同但指同一個檔案，不可以被當成兩筆。
alt = gen.new_chain()
gen.record(alt, "/v/out/./a.mp4", "roughcut", "/v/src.mp4")
check("同一個檔案用不同寫法查得到（路徑正規化）",
      gen.find(alt, "/v/out/a.mp4") is not None)

# 環：A 的來源是 B、B 的來源是 A。不能轉不停。
loop = [{"path": "/l/a.mp4", "kind": "roughcut", "source": "/l/b.mp4"},
        {"path": "/l/b.mp4", "kind": "audiofix", "source": "/l/a.mp4"}]
desc = gen.describe_lineage(loop, "/l/a.mp4")
check("鏈上出現環時會停下來，不會無限迴圈", isinstance(desc, str) and desc)

check("不認得的種類代號不會變成空白", gen.kind_label("未知種類") == "未知種類")
check("空的來源視為源頭",
      gen.record(gen.new_chain(), "/s/x.mp4", "roughcut")["source"] is None)
try:
    gen.record(gen.new_chain(), "", "roughcut")
    check("空路徑要擋下來", False)
except ValueError:
    check("空路徑要擋下來", True)


# ===== 2. 發佈素材：結構化版與文字版必須同源 =========================
from subtitle.publisher import build_publish_fields, build_publish_pack
from subtitle.review import build_chapters

ITEMS = [
    {"text": "今天要教大家怎麼用 Premiere 剪片，這個技巧超好用", "start": 0.0,
     "end": 6.0, "kind": "speech", "keep": True, "highlight": True, "review": False},
    {"text": "第一步是先把素材全部匯入，然後建立序列", "start": 7.0, "end": 16.0,
     "kind": "speech", "keep": True, "highlight": False, "review": False},
    {"text": "你知道嗎？其實有更快的方法可以做到同樣的事", "start": 18.0, "end": 27.0,
     "kind": "speech", "keep": True, "highlight": True, "review": False},
    {"text": "最後記得輸出設定要選 H.264，位元率設 15000", "start": 30.0, "end": 42.0,
     "kind": "speech", "keep": True, "highlight": False, "review": False},
]
CHAPTERS = build_chapters(ITEMS, min_chapter_seconds=5.0, break_gap=1.0)

fields = build_publish_fields(ITEMS, chapters=CHAPTERS)
pack = build_publish_pack(ITEMS, chapters=CHAPTERS, source_name="測試.mp4")

check("結構化版有全部五個欄位",
      set(fields) == {"titles", "title", "description", "tags", "chapters"},
      str(sorted(fields)))
check("建議標題就是候選中的第一個",
      fields["title"] == (fields["titles"][0] if fields["titles"] else ""))
check("【同源】結構化的建議標題，在文字版發佈包裡找得到一模一樣的",
      fields["title"] and fields["title"] in pack, fields["title"])
check("【同源】結構化的描述草稿，在文字版發佈包裡一字不差",
      fields["description"] and fields["description"] in pack)
for line in [ln for ln in fields["chapters"].splitlines() if ln.strip()]:
    check(f"【同源】章節「{line[:16]}」在文字版裡也找得到", line in pack, line)
check("章節行數與 build_chapters 的段落數一致",
      len([ln for ln in fields["chapters"].splitlines() if ln.strip()])
      == len(CHAPTERS),
      f"{fields['chapters']!r} vs {len(CHAPTERS)} 章")
check("沒有章節時 chapters 是空字串、不是 None（介面要直接塞進文字框）",
      build_publish_fields(ITEMS)["chapters"] == "")
check("沒有段落時也不會炸，各欄位回空",
      build_publish_fields([])["title"] == "")


# ===== 3. Xvfb 下的真實回流 ==========================================
try:
    import tkinter as tk
except ImportError as exc:
    print(f"SKIP Xvfb 段（無 tkinter：{exc}）")
else:
    import config as app_config
    _tmpcfg = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    _tmpcfg.write(b'{"whatsnew_seen": "never"}')
    _tmpcfg.close()
    app_config.CONFIG_PATH = _tmpcfg.name
    try:
        from gui.app import SrtApp
        from gui.health_center_panel import HealthCenterPanel
        app = SrtApp()
    except tk.TclError as exc:
        # 只有「連不上顯示器」才算合理略過；其餘 TclError 是真的錯誤。
        message = str(exc).lower()
        if "display" in message or "connect" in message:
            print(f"SKIP Xvfb 段（無顯示器：{exc}）")
            app = None
        else:
            check(f"主視窗開得起來（TclError：{exc}）", False)
            app = None

    if app is not None:
        app.geometry("1400x800+0+0")
        app.deiconify()
        for _ in range(60):
            app.update()

        def pump():
            for _ in range(15):
                app.update()

        tmp = tempfile.mkdtemp()
        def touch(name):
            path = os.path.join(tmp, name)
            with open(path, "wb") as fp:
                fp.write(b"x")
            return path

        orig, rough = touch("訪談.mp4"), touch("訪談_粗剪.mp4")
        fixedp, burned = touch("訪談_修復.mp4"), touch("訪談_subtitled.mp4")

        # --- 世代鏈顯示在工作檔案列 ---
        app.file_var.set(orig); pump()
        check("只選了原始檔時，工作檔案列就顯示「原始素材 檔名」",
              app.workfile_video_var.get() == "原始素材 訪談.mp4",
              app.workfile_video_var.get())
        app.adopt_media(rough, "roughcut", orig); pump()
        check("接手粗剪後工作檔案列顯示譜系（不只是換個檔名）",
              app.workfile_video_var.get() == "原始素材 訪談.mp4 → 粗剪（目前）",
              app.workfile_video_var.get())
        check("接手後目前影片真的換成新檔", app._selected_files()[0] == rough)
        app.adopt_media(fixedp, "audiofix", rough); pump()
        app.adopt_media(burned, "burned", fixedp); pump()
        check("四代譜系在工作檔案列上完整顯示",
              app.workfile_video_var.get()
              == "原始素材 訪談.mp4 → 粗剪 → 修復版 → 燒錄版（目前）",
              app.workfile_video_var.get())

        check("接手不存在的檔案會被擋下來、不會把目前影片設成幽靈路徑",
              app.adopt_media(os.path.join(tmp, "不存在.mp4"), "roughcut") is False)

        # 換影片但不動字幕，而且一定要講出來（時間軸可能已經對不上）。
        app.cues = [{"start": 0.0, "end": 1.0, "text": "校對過的字幕"}]
        app.adopt_media(rough, "roughcut", orig); pump()
        check("換影片時字幕清單不被清掉（那是使用者的校對成果）",
              len(app.cues) == 1)
        check("有字幕時接手會明講「時間軸可能對不上」，不是默默換掉",
              "重新生成字幕" in app.status_var.get(), app.status_var.get())
        app.cues = []

        # --- 發佈資料卡 ---
        app.notebook.select(3); pump()
        check("沒有內容時〔送健檢中心〕是停用的",
              str(app.publish_send_btn["state"]) == "disabled")
        check("沒有內容時說明會指路（告訴使用者東西從哪來）",
              "審片助手" in app.publish_summary_var.get(),
              app.publish_summary_var.get())

        app.adopt_publish(title="三分鐘學會剪片", description="說明欄草稿",
                          tags="剪片, premiere", chapters="0:00 開頭\n1:30 重點")
        thumbs = [touch("封面1.png"), touch("封面2.png")]
        app.adopt_thumbnails(thumbs)
        pump()
        summary = app.publish_summary_var.get()
        for token in ("標題", "說明欄", "標籤", "章節 2 行", "封面候選 2 張"):
            check(f"發佈資料摘要列出「{token}」", token in summary, summary)
        check("有內容後〔送健檢中心〕啟用",
              str(app.publish_send_btn["state"]) == "normal")
        check("重複收同一批封面圖不會變成雙份",
              app.adopt_thumbnails(thumbs) == []
              and len(app.publish_data["thumbs"]) == 2)

        check("發佈資料卡整張在視窗內（不是被推到畫面外）",
              (app.publish_card.winfo_rooty() - app.winfo_rooty()
               + app.publish_card.winfo_height()) <= app.winfo_height(),
              f"底端 {app.publish_card.winfo_rooty() - app.winfo_rooty() + app.publish_card.winfo_height()}"
              f" vs 視窗高 {app.winfo_height()}")

        # --- 一鍵送健檢中心：對象區真的被填好 ---
        # v2.2.0：健檢中心是階段③的頁籤內容，「送健檢中心」不再開窗而是
        # 切頁籤＋填對象區。改成直接走使用者真正會走的那條路徑
        # （_on_send_publish_to_health），比原本自己 new 一個視窗更接近實
        # 際情形。
        app._on_send_publish_to_health()
        pump()
        dialog = app.health_panel
        check("送健檢中心會切到階段③（不再另外開一個視窗）",
              app.notebook.select() == str(app.stage_health_tab),
              app.notebook.select())
        check("送健檢後標題欄已填",
              dialog.publish_title_var.get() == "三分鐘學會剪片",
              dialog.publish_title_var.get())
        check("送健檢後標籤欄已填",
              dialog.publish_tags_var.get() == "剪片, premiere")
        check("送健檢後章節欄已填",
              "1:30 重點" in dialog.publish_chapters.get("1.0", "end"))
        check("送健檢後說明欄已填",
              "說明欄草稿" in dialog.publish_desc.get("1.0", "end"))
        check("送健檢後封面候選圖已加入（不必一張張自己加檔案）",
              len(dialog._thumb_paths) == 2, str(dialog._thumb_paths))
        check("有資料時「發佈文字」摺疊區會自動展開（填了卻收著等於沒填）",
              dialog.publish_body.winfo_ismapped() == 1)

        # 不帶 publish 時完全不影響原本行為（另外裝一個乾淨的面板來比）。
        plain_host = tk.Toplevel(app)
        plain_host.geometry("1120x900")
        plain = HealthCenterPanel(plain_host, app.config_data,
                                  media_path="", cues=[])
        plain.pack(fill="both", expand=True)
        plain_host.deiconify(); pump()
        check("不帶發佈資料開啟時，對象區維持空白、摺疊區維持收合",
              plain.publish_title_var.get() == ""
              and plain.publish_body.winfo_ismapped() == 0)
        plain_host.destroy()

        # --- 修復版回流 ---
        received = {}
        hc_host = tk.Toplevel(app)
        hc_host.geometry("1120x900")
        hc = HealthCenterPanel(
            hc_host, app.config_data, media_path=orig, cues=[],
            on_media_fixed=lambda p, s: received.update(path=p, source=s))
        hc.pack(fill="both", expand=True)
        hc_host.deiconify(); pump()
        from tkinter import messagebox as _mb
        _orig_ask = _mb.askyesno
        _mb.askyesno = lambda *a, **k: True      # 使用者按「是」
        hc._offer_adopt_fixed(fixedp)
        check("修復完成選「是」時，修復版回報給主視窗接手",
              received.get("path") == fixedp and received.get("source") == orig,
              str(received))
        check("接手後健檢中心的對象也換成修復版（否則再按健檢還在檢查舊檔）",
              hc.media_var.get() == fixedp)
        received.clear()
        _mb.askyesno = lambda *a, **k: False     # 使用者按「否」
        hc.media_var.set(orig)
        hc._offer_adopt_fixed(fixedp)
        check("選「否」時不接手，目前影片與對象區都不動",
              not received and hc.media_var.get() == orig)
        _mb.askyesno = _orig_ask
        hc_host.destroy()

        # --- 審片助手的三條回流線真的接上了 ---
        from gui.review_window import ReviewWindow
        import inspect
        sig = inspect.signature(ReviewWindow.__init__)
        for name in ("on_media", "on_publish", "on_thumbnails"):
            check(f"審片助手接得住 {name} 回呼", name in sig.parameters)

        app.destroy()
    if os.path.exists(_tmpcfg.name):
        os.unlink(_tmpcfg.name)


# ===== 4. run_all.py 有沒有漏掉測試檔 ================================
# v1.52.1 新增的 tests/test_v1521.py **沒有被登記進 run_all.py**，而且沒有
# 任何東西會發現——`run_all.py` 跑的是自己寫死的清單，漏掉的檔案就只是安
# 靜地不執行，它照樣印「全數通過」。這和 v1.52.0 那個過寬的
# `except tk.TclError` 是同一類毛病：測試沒跑，卻回報通過。
import re as _re

_tests_dir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_tests_dir, "run_all.py"), encoding="utf-8") as _fp:
    _listed = set(_re.findall(r'"(test_\w+\.py)"', _fp.read()))
_actual = {name for name in os.listdir(_tests_dir)
           if name.startswith("test_") and name.endswith(".py")}
check("run_all.py 沒有漏掉任何測試檔（漏登記＝那份測試根本沒跑，"
      "卻還是回報通過）", not (_actual - _listed), str(sorted(_actual - _listed)))
check("run_all.py 沒有列到不存在的測試檔",
      not (_listed - _actual), str(sorted(_listed - _actual)))


print()
if failures:
    print(f"失敗 {len(failures)} 項：" + ", ".join(failures))
    sys.exit(1)
print("v1.52.2 審片產出自動流入／世代鏈測試全數通過。")
