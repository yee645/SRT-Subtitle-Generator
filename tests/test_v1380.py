# -*- coding: utf-8 -*-
"""v1.38.0 新功能測試：上片前總體檢（彙總所有健檢並依嚴重度排序）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import preflight as pf


def titles(rows, level=None):
    return [r["title"] for r in rows
            if level is None or r.get("level") == level]


S = pf.resolve_preflight_settings(None)

# ===== 1. 設定解析 =====
check("預設全部開啟",
      all(S[k] for k in ("run_audio", "run_video", "run_color", "run_volume",
                         "run_pacing", "run_subtitle", "run_adfriendly",
                         "run_hook", "run_legibility")), str(S))
off = pf.resolve_preflight_settings({"preflight": {"run_pacing": False}})
check("可單獨關閉某一項", off["run_pacing"] is False and off["run_audio"])
check("布林值一律轉成 bool",
      pf.resolve_preflight_settings(
          {"preflight": {"run_audio": 0}})["run_audio"] is False)
check("檔名詞表為字串", isinstance(S["generic_name_terms"], str))
check("空詞表不會變成 None",
      pf.resolve_preflight_settings(
          {"preflight": {"generic_name_terms": None}})["generic_name_terms"]
      == pf.DEFAULT_PREFLIGHT["generic_name_terms"])

# ===== 2. 檔名檢查（既有 16 項健檢都沒有涵蓋的一項）=====
generic = pf.check_filename("/x/final_cut_v2.mp4", S)
check("通用檔名會被標記", generic[0]["level"] == pf.LEVEL_WARN, str(generic))
check("通用檔名指出是哪些字眼", "final" in generic[0]["detail"])
camera = pf.check_filename("/x/IMG_1234.mp4", S)
check("相機預設檔名會被標記", camera[0]["level"] == pf.LEVEL_WARN, str(camera))
check("相機預設檔名說明是裝置預設", "預設檔名" in camera[0]["detail"])
check("純數字檔名會被標記",
      pf.check_filename("/x/20260101_120000.mp4", S)[0]["level"]
      == pf.LEVEL_WARN)
good_name = pf.check_filename("/x/相機隱藏設定實測.mp4", S)
check("有資訊的檔名判定通過", good_name[0]["level"] == pf.LEVEL_GOOD,
      str(good_name))
check("檔名項目帶有 source", generic[0]["source"] == "檔名")
check("讀不到檔名時不會爆炸",
      pf.check_filename("", S)[0]["level"] == pf.LEVEL_WARN)
custom = pf.resolve_preflight_settings(
    {"preflight": {"generic_name_terms": "測試稿"}})
check("自訂詞表生效",
      pf.check_filename("/x/測試稿001.mp4", custom)[0]["level"]
      == pf.LEVEL_WARN)
check("自訂詞表取代預設（final 不再被標記）",
      pf.check_filename("/x/final.mp4", custom)[0]["level"] == pf.LEVEL_GOOD,
      str(pf.check_filename("/x/final.mp4", custom)))

# ===== 3. 正規化：既有模組有三種不同的回傳格式 =====
# (a) findings 格式
rows = pf.normalize_findings(
    {"findings": [{"level": "bad", "title": "位元率", "detail": "太低",
                   "advice": "調高"}]}, "影片畫質健檢")
check("findings 格式可正規化", len(rows) == 1 and rows[0]["title"] == "位元率")
check("正規化後帶上 source", rows[0]["source"] == "影片畫質健檢")
# (b) issues 格式（欄位相同、只有鍵名不同）
rows = pf.normalize_findings(
    {"issues": [{"level": "warn", "title": "曝光", "detail": "偏暗",
                 "advice": ""}]}, "畫面曝光與色偏")
check("issues 格式可正規化", len(rows) == 1 and rows[0]["title"] == "曝光")
check("issues 也會帶上 source", rows[0]["source"] == "畫面曝光與色偏")
check("空結果回空清單", pf.normalize_findings(None, "x") == [])
check("兩個鍵都沒有時回空清單",
      pf.normalize_findings({"stats": {}}, "x") == [])
check("非 dict 的項目會被略過",
      pf.normalize_findings({"findings": ["壞資料", {"level": "bad",
                                                    "title": "t"}]}, "x")
      == [{"level": "bad", "title": "t", "detail": "", "advice": "",
           "source": "x"}])

# (c) 廣告友善度是自己的叢集結構
ad = pf.normalize_adfriendly(
    {"clusters": [{"start": 65.0}, {"start": 130.0}],
     "opening_hits": [{"term": "x"}], "opening_seconds": 7.0}, "廣告友善度")
check("叢集會轉成一個項目",
      "廣告友善度" in titles(ad, pf.LEVEL_WARN), str(titles(ad)))
check("叢集數量寫進說明", "2 處" in ad[0]["detail"], ad[0]["detail"])
check("叢集時間以時間戳呈現", "1:05" in ad[0]["detail"], ad[0]["detail"])
check("開頭命中另外成一項", "開頭用詞" in titles(ad))
clean = pf.normalize_adfriendly({"clusters": [], "opening_hits": []}, "x")
check("沒有風險時給一個通過項目",
      clean[0]["level"] == pf.LEVEL_GOOD, str(clean))
check("廣告友善度空結果回空清單", pf.normalize_adfriendly(None, "x") == [])

# ===== 4. 排序與統計 =====
mixed = [
    {"level": "good", "title": "a"}, {"level": "bad", "title": "b"},
    {"level": "warn", "title": "c"}, {"level": "bad", "title": "d"},
]
ordered = pf.sort_findings(mixed)
check("一定要修排最前面",
      [r["title"] for r in ordered] == ["b", "d", "c", "a"],
      str([r["title"] for r in ordered]))
check("同級維持原本順序",
      [r["title"] for r in ordered[:2]] == ["b", "d"])
counts = pf.summarize(mixed)
check("統計正確",
      counts == {"bad": 2, "warn": 1, "good": 1}, str(counts))
check("空清單統計為 0",
      pf.summarize([]) == {"bad": 0, "warn": 0, "good": 0})

# ===== 5. 準備度評級：一定要修的項目主導 =====
check("全通過為 A+", pf.readiness_grade({"bad": 0, "warn": 0}) == "A+")
check("少量建議修為 A", pf.readiness_grade({"bad": 0, "warn": 2}) == "A")
check("較多建議修為 B", pf.readiness_grade({"bad": 0, "warn": 5}) == "B")
check("一項一定要修為 C", pf.readiness_grade({"bad": 1, "warn": 0}) == "C")
check("數項一定要修為 D", pf.readiness_grade({"bad": 3, "warn": 0}) == "D")
check("很多一定要修為 F", pf.readiness_grade({"bad": 5, "warn": 0}) == "F")
# 這是刻意的設計：只要還有一定要修，再少的建議修也拉不高評級。
check("有一定要修時建議修再少也不會是 A",
      pf.readiness_grade({"bad": 1, "warn": 0}) not in ("A+", "A", "B"))

# ===== 6. 依素材自動略過（不碰 ffmpeg 也能單獨測）=====
names = lambda steps: [n for n, _ in steps]
full = pf._build_steps(S, has_video=True, has_cues=True)
check("有畫面有字幕時全部項目都跑", len(full) == 12, str(names(full)))
audio_only = pf._build_steps(S, has_video=False, has_cues=True)
check("純音訊檔略過所有畫面檢查",
      "影片畫質健檢" not in names(audio_only)
      and "畫面曝光與色偏" not in names(audio_only)
      and "剪輯節奏" not in names(audio_only)
      and "字幕可讀性" not in names(audio_only), str(names(audio_only)))
check("純音訊檔仍會跑聲音與純文字的檢查",
      "音訊健檢" in names(audio_only) and "分段音量一致性" in names(audio_only)
      and "字幕健檢" in names(audio_only), str(names(audio_only)))
no_cues = pf._build_steps(S, has_video=True, has_cues=False)
check("沒有字幕時略過所有字幕相關檢查",
      not any(n in names(no_cues) for n in
              ("字幕健檢", "廣告友善度", "開場健檢", "字幕可讀性")),
      str(names(no_cues)))
check("沒有字幕時畫面與聲音檢查照跑",
      len(names(no_cues)) == 6, str(names(no_cues)))
bare = pf._build_steps(S, has_video=False, has_cues=False)
check("純音訊又沒字幕時只剩不需畫面也不需字幕的項目",
      names(bare) == ["音訊健檢", "分段音量一致性", "片尾空間"],
      str(names(bare)))
# 關閉設定要真的生效。
disabled = pf.resolve_preflight_settings({"preflight": {
    "run_pacing": False, "run_hook": False}})
check("關閉的項目不會被排進來",
      "剪輯節奏" not in names(pf._build_steps(disabled, True, True))
      and "開場健檢" not in names(pf._build_steps(disabled, True, True)))
check("關閉一項不影響其他項",
      "音訊健檢" in names(pf._build_steps(disabled, True, True)))

# ===== 7. 報告文字 =====
result = {
    "media": "測試.mp4",
    "findings": pf.sort_findings([
        {"level": "bad", "title": "位元率", "detail": "太低",
         "advice": "調高輸出位元率", "source": "影片畫質健檢"},
        {"level": "warn", "title": "檔名", "detail": "沒有資訊",
         "advice": "改名", "source": "檔名"},
        {"level": "good", "title": "爆音檢查", "detail": "正常",
         "advice": "", "source": "音訊健檢"},
    ]),
    "counts": {"bad": 1, "warn": 1, "good": 1},
    "grade": "C", "ok": False,
    "skipped": ["沒有字幕，已略過字幕相關檢查"],
}
report = pf.format_preflight_report(result)
check("報告含標題與素材名", "上片前總體檢：測試.mp4" in report)
check("報告顯示準備度", "準備度：C" in report, report[:120])
check("報告不含 markdown 星號（tk.Text 會原樣顯示）", "**" not in report)
check("報告分成三段", all(k in report for k in
                        ("一定要修（1）", "建議修（1）", "通過（1）")))
check("報告標出每一條來自哪一項檢查", "[影片畫質健檢]" in report)
check("一定要修排在建議修之前",
      report.index("一定要修（1）") < report.index("建議修（1）"))
check("通過的項目不列建議（省版面）",
      report.count("建議：") == 2, str(report.count("建議：")))
check("報告列出略過的項目", "略過的項目" in report)
check("不合格結論說明理由", "一定要修" in report.split("結論：")[-1])
ok_report = pf.format_preflight_report(
    {"media": "好.mp4", "findings": [{"level": "good", "title": "a",
                                      "detail": "b", "source": "x"}],
     "counts": {"bad": 0, "warn": 0, "good": 1}, "grade": "A+", "ok": True})
check("全通過時給正面結論", "可以上傳" in ok_report)
check("空結果不會爆炸",
      "沒有可檢查" in pf.format_preflight_report({"findings": []}))
check("缺 source 的資料不會讓報告爆炸",
      "總體檢" in pf.format_preflight_report(
          {"media": "x", "findings": [{"level": "bad", "title": "t",
                                       "detail": "d"}],
           "counts": {"bad": 1, "warn": 0, "good": 0}, "grade": "C"}))

# ===== 8. 回歸：本模組不重新實作分析，只做彙總 =====
# 轉接器應該全部都只是「呼叫既有模組 + 正規化」，不含任何門檻或判斷。
import inspect
for name in ("_run_audio", "_run_video", "_run_color", "_run_volume",
             "_run_pacing", "_run_subtitle", "_run_adfriendly", "_run_hook",
             "_run_legibility"):
    src = inspect.getsource(getattr(pf, name))
    check(f"{name} 沒有自己的判斷邏輯",
          " if " not in src and "LEVEL_" not in src, src[:120])

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.38.0 測試全數通過。")
