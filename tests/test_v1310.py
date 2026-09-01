# -*- coding: utf-8 -*-
"""v1.31.0 新功能測試：系列一致性檢查（跨檔比對）。"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import seriescheck as sc
from subtitle.audiocheck import LEVEL_BAD, LEVEL_GOOD, LEVEL_WARN


def entry(name, **kw):
    base = {"path": f"/x/{name}", "name": name, "lufs": None, "width": None,
            "height": None, "fps": None, "codec": None, "luma": None,
            "u": None, "v": None, "error": None}
    base.update(kw)
    return base


# ===== 1. 設定解析與夾限 =====
s = sc.resolve_seriescheck_settings(None)
check("預設值", s == sc.DEFAULT_SERIESCHECK, str(s))
s2 = sc.resolve_seriescheck_settings({"seriescheck": {
    "loudness_tolerance": 999, "luma_tolerance": 1, "cast_tolerance": 999}})
check("loudness_tolerance 夾上限", s2["loudness_tolerance"] == 8.0, str(s2))
check("luma_tolerance 夾下限", s2["luma_tolerance"] == 10.0, str(s2))
check("cast_tolerance 夾上限", s2["cast_tolerance"] == 30.0, str(s2))
check("非數值回預設",
      sc.resolve_seriescheck_settings(
          {"seriescheck": {"loudness_tolerance": "bad"}})
      ["loudness_tolerance"] == 2.0)

# ===== 2. median：用中位數而非平均（單一極端值不該拉走基準） =====
check("奇數個取中間", sc.median([1.0, 5.0, 3.0]) == 3.0)
check("偶數個取平均", sc.median([1.0, 3.0]) == 2.0)
check("忽略 None", sc.median([1.0, None, 3.0]) == 2.0)
check("空清單回 None", sc.median([]) is None)
check("全 None 回 None", sc.median([None, None]) is None)
# 關鍵：極端值不該把基準拉走（這是選中位數而非平均的理由）。
check("極端值不影響中位數", sc.median([10.0, 10.0, 10.0, 200.0]) == 10.0)

# ===== 3. _as_float：ffmpeg loudnorm JSON 的數值是字串 =====
check("字串轉 float", sc._as_float("-23.5") == -23.5)
check("float 原樣", sc._as_float(1.5) == 1.5)
check("None 回 None", sc._as_float(None) is None)
check("非數值字串回 None", sc._as_float("n/a") is None)

# ===== 4. _majority：整批的「標準規格」 =====
check("多數決", sc._majority(["a", "a", "b"]) == "a")
check("忽略 None", sc._majority([None, "a", "a"]) == "a")
check("空清單回 None", sc._majority([]) is None)
check("全 None 回 None", sc._majority([None, None]) is None)

# ===== 5. 相對基準比較：抓「偏離整批」而非「不合格」 =====
# 5a. 整批一致 → 通過（即使絕對值都偏低，那是風格不是失誤）。
uniform = [entry(f"EP{i}.mp4", lufs=-30.0) for i in range(3)]
findings = sc._compare_numeric(uniform, "lufs", 2.0, "整體響度", " LUFS", "x")
check("整批一致時判定通過（不看絕對值）",
      len(findings) == 1 and findings[0]["level"] == LEVEL_GOOD,
      str(findings))

# 5b. 其中一支偏離 → 標記那一支。
outlier = [entry("EP1.mp4", lufs=-14.0), entry("EP2.mp4", lufs=-14.0),
           entry("EP3.mp4", lufs=-25.0)]
findings = sc._compare_numeric(outlier, "lufs", 2.0, "整體響度", " LUFS", "x")
check("偏離者被標記", findings[0]["level"] == LEVEL_WARN, str(findings))
check("報告指名偏離的檔案", "EP3.mp4" in findings[0]["detail"],
      findings[0]["detail"])
check("報告不含正常的檔案",
      "EP1.mp4" not in findings[0]["detail"], findings[0]["detail"])
check("報告標明偏離方向與幅度",
      "低" in findings[0]["detail"] and "11.0" in findings[0]["detail"],
      findings[0]["detail"])

# 5c. 容差可調：離群幅度落在可調範圍內時，調鬆容差就不再標記。
#     （用 5 LU 的落差示範；11 LU 那種等級即使調到容差上限 8.0 仍會標記，
#      這是刻意的——集數之間差到 11 LU 已經是觀眾一定有感的程度。）
mild = [entry("EP1.mp4", lufs=-14.0), entry("EP2.mp4", lufs=-14.0),
        entry("EP3.mp4", lufs=-19.0)]
strict = sc._compare_numeric(mild, "lufs", 2.0, "整體響度", " LUFS", "x")
check("嚴格容差下 5 LU 落差被標記",
      strict[0]["level"] == LEVEL_WARN, str(strict))
loose = sc._compare_numeric(mild, "lufs", 8.0, "整體響度", " LUFS", "x")
check("放寬容差後同一批不再標記",
      loose[0]["level"] == LEVEL_GOOD, str(loose))
# 極端落差即使調到容差上限仍應標記。
extreme = sc._compare_numeric(outlier, "lufs", 8.0, "整體響度", " LUFS", "x")
check("極端落差調到容差上限仍標記",
      extreme[0]["level"] == LEVEL_WARN, str(extreme))

# 5d. 不足 2 個有效值時略過該項（沒有基準可言）。
check("只有一個有效值時略過",
      sc._compare_numeric([entry("A", lufs=-14.0), entry("B")],
                          "lufs", 2.0, "整體響度", " LUFS", "x") == [])

# ===== 6. 規格比較（解析度／更新率／編碼） =====
specs = [entry("EP1", width=1920, height=1080, fps=30.0, codec="h264"),
         entry("EP2", width=1920, height=1080, fps=30.0, codec="h264"),
         entry("EP3", width=1280, height=720, fps=25.0, codec="hevc")]
spec_findings = {f["title"]: f for f in sc._compare_spec(specs)}
check("解析度不一致標為 BAD（畫質忽好忽壞最有感）",
      spec_findings["解析度"]["level"] == LEVEL_BAD,
      str(spec_findings["解析度"]))
check("解析度報告指名偏離者",
      "EP3" in spec_findings["解析度"]["detail"],
      spec_findings["解析度"]["detail"])
check("更新率不一致被標記",
      spec_findings["畫面更新率"]["level"] == LEVEL_WARN,
      str(spec_findings["畫面更新率"]))
check("編碼不一致被標記",
      spec_findings["視訊編碼"]["level"] == LEVEL_WARN,
      str(spec_findings["視訊編碼"]))

same = [entry("EP1", width=1920, height=1080, fps=30.0, codec="h264"),
        entry("EP2", width=1920, height=1080, fps=29.98, codec="h264")]
same_findings = {f["title"]: f for f in sc._compare_spec(same)}
check("規格一致時全數通過",
      all(f["level"] == LEVEL_GOOD for f in same_findings.values()),
      str(same_findings))
check("微小的更新率差異不誤判（29.98 vs 30.0）",
      same_findings["畫面更新率"]["level"] == LEVEL_GOOD)

# ===== 7. 防呆 =====
try:
    sc.analyze_series(["only_one.mp4"])
    check("檔案不足 2 個時報錯", False)
except ValueError as exc:
    check("檔案不足 2 個時報錯", "至少" in str(exc), str(exc))
try:
    sc.analyze_series([])
    check("空清單時報錯", False)
except ValueError:
    check("空清單時報錯", True)

# 友善錯誤分類：不該落到「未預期的錯誤」讓使用者去開 issue。
from subtitle.errors import describe_exception
friendly = describe_exception(
    ValueError("系列一致性檢查需要至少 2 個檔案才有比較基準，請一次選取"))
check("檔案不足有專屬的友善錯誤分類",
      "需要多個檔案" in str(friendly), str(friendly))
check("友善錯誤有指出正確作法",
      "Ctrl" in friendly.solution and "上片前健檢" in friendly.solution,
      friendly.solution)

# ===== 8. 報告文字 =====
report = sc.format_series_report({"entries": outlier, "findings": findings})
check("報告列出每支影片", "EP1.mp4" in report and "EP3.mp4" in report, report)
check("報告有結論", "結論" in report, report)
check("報告說明與單支健檢的差別",
      "彼此之間" in report and "上片前健檢" in report, report)
clean_report = sc.format_series_report(
    {"entries": uniform,
     "findings": sc._compare_numeric(uniform, "lufs", 2.0, "整體響度",
                                     " LUFS", "x")})
check("整批一致時結論為一致", "彼此一致" in clean_report, clean_report)
check("空結果安全", "沒有可比對" in sc.format_series_report({"entries": []}))
# 量測失敗的檔案要照常列出，不能默默消失。
err_report = sc.format_series_report(
    {"entries": [entry("壞檔.mp4", error="找不到檔案")], "findings": []})
check("量測失敗的檔案仍列出並標明原因",
      "壞檔.mp4" in err_report and "找不到檔案" in err_report, err_report)

# ===== 9. config／CLI／GUI 靜態掃描 =====
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from config import DEFAULT_CONFIG
check("config 預設含 seriescheck 區",
      DEFAULT_CONFIG.get("seriescheck") == sc.DEFAULT_SERIESCHECK,
      str(DEFAULT_CONFIG.get("seriescheck")))

with open(os.path.join(root, "cli.py"), encoding="utf-8") as fp:
    cli_src = fp.read()
check("cli.py 有 --seriescheck 旗標", "--seriescheck" in cli_src)
check("cli.py 有系列檢查執行函式", "_run_seriescheck" in cli_src)

with open(os.path.join(root, "gui", "series_dialog.py"), encoding="utf-8") as fp:
    dialog_src = fp.read()
check("對話框有開始比對與檔案管理",
      "開始比對" in dialog_src and "加入影片" in dialog_src
      and "analyze_series" in dialog_src)
check("對話框於背景執行緒跑量測（不凍住 UI）",
      "threading.Thread" in dialog_src and "_run_worker" in dialog_src)
check("對話框無 classic tk.Checkbutton/Radiobutton 殘留",
      "tk.Checkbutton(" not in dialog_src.replace("ttk.Checkbutton(", "")
      and "tk.Radiobutton(" not in dialog_src.replace(
          "ttk.Radiobutton(", ""))

with open(os.path.join(root, "gui", "app.py"), encoding="utf-8") as fp:
    app_src = fp.read()
with open(os.path.join(root, "gui", "health_center_dialog.py"),
         encoding="utf-8") as fp:
    center_src = fp.read()
# v1.51.0：健檢中心（二）把「系列一致性」的入口從主視窗工具列移進健檢
# 中心的對象區（保留為獨立視窗，未併進單支分級報告——見
# docs/UI_AUDIT_2.0.md 2.2 節預留的退路），工具列本身收成 6 顆、不再有
# 系列一致性這顆按鈕；SeriesCheckDialog 改由 gui/health_center_dialog.py
# import 並開啟，能力（開始比對／檔案管理／背景執行緒）完全未變，
# 詳見 tests/test_v1510.py。
check("系列一致性不再是主視窗工具列按鈕，改由健檢中心對象區開啟"
      "（能力未變，入口搬家，見 docs/ROADMAP_2.0.md v1.51 項）",
      "SeriesCheckDialog" not in app_src and "SeriesCheckDialog" in center_src)

# ===== 10. 真實媒體端到端：一批三支、其中一支刻意離群 =====
if sc.ffmpeg_available():
    with tempfile.TemporaryDirectory() as tmp:
        def make(name, size, colour, extra_af=None):
            path = os.path.join(tmp, name)
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                   "-f", "lavfi",
                   "-i", f"color=c={colour}:s={size}:d=4,"
                         "noise=alls=40:allf=t+u",
                   "-f", "lavfi", "-i", "sine=frequency=440:duration=4"]
            if extra_af:
                cmd += ["-af", extra_af]
            cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                    "-c:a", "aac", "-shortest", path]
            subprocess.run(cmd, capture_output=True, timeout=180)
            return path

        ep1 = make("EP01.mp4", "1280x720", "gray")
        ep2 = make("EP02.mp4", "1280x720", "gray")
        # EP03 三處刻意不一致：音量小、解析度低、畫面暗。
        ep3 = make("EP03.mp4", "640x360", "0x303030", extra_af="volume=-14dB")

        result = sc.analyze_series([ep1, ep2, ep3])
        by_title = {f["title"]: f for f in result["findings"]}

        check("實測：三支都完成量測",
              len(result["entries"]) == 3
              and all(not e["error"] for e in result["entries"]),
              str([e["error"] for e in result["entries"]]))
        check("實測：響度為數值（loudnorm JSON 字串已轉型）",
              all(isinstance(e["lufs"], float) for e in result["entries"]),
              str([type(e["lufs"]).__name__ for e in result["entries"]]))

        check("實測：抓到響度離群者",
              by_title["整體響度"]["level"] == LEVEL_WARN
              and "EP03.mp4" in by_title["整體響度"]["detail"],
              str(by_title["整體響度"]))
        check("實測：抓到解析度不一致",
              by_title["解析度"]["level"] == LEVEL_BAD
              and "EP03.mp4" in by_title["解析度"]["detail"],
              str(by_title["解析度"]))
        check("實測：抓到亮度離群者",
              by_title["畫面亮度"]["level"] == LEVEL_WARN
              and "EP03.mp4" in by_title["畫面亮度"]["detail"],
              str(by_title["畫面亮度"]))
        check("實測：更新率與編碼判為一致（無誤判）",
              by_title["畫面更新率"]["level"] == LEVEL_GOOD
              and by_title["視訊編碼"]["level"] == LEVEL_GOOD,
              str({k: v["level"] for k, v in by_title.items()}))

        # 一致的一批不該被誤標（防止假陽性）。
        clean = sc.analyze_series([ep1, ep2])
        check("實測：一致的一批全數通過（無假陽性）",
              all(f["level"] == LEVEL_GOOD for f in clean["findings"]),
              str([(f["title"], f["level"]) for f in clean["findings"]]))

        # 缺檔案照常完成整批，只把該檔標為錯誤。
        partial = sc.analyze_series([ep1, ep2, os.path.join(tmp, "沒有.mp4")])
        check("實測：缺檔不中斷整批比對",
              len(partial["entries"]) == 3
              and partial["entries"][2]["error"] == "找不到檔案",
              str(partial["entries"][2]))

        # CLI 端到端。
        proc = subprocess.run(
            [sys.executable, os.path.join(root, "main.py"),
             "--seriescheck", ep1, ep2, ep3],
            cwd=tmp, capture_output=True, text=True, timeout=600)
        check("實測：CLI --seriescheck 執行成功", proc.returncode == 0,
              proc.stdout[-1500:] + proc.stderr[-800:])
        out_path = os.path.join(tmp, "系列一致性檢查.txt")
        check("實測：CLI 報告已產生", os.path.exists(out_path))
        if os.path.exists(out_path):
            content = open(out_path, encoding="utf-8").read()
            check("實測：CLI 報告標出離群者",
                  "EP03.mp4" in content and "解析度" in content,
                  content[:400])
else:
    print("SKIP 實測（無 ffmpeg）")

print()
if failures:
    print(f"共 {len(failures)} 項失敗：{failures}")
    sys.exit(1)
print("test_v1310 全部通過")
