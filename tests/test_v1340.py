# -*- coding: utf-8 -*-
"""v1.34.0 新功能測試：剪輯節奏健檢（畫面太久沒變化）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import pacing as pc


def titles(result, level=None):
    return [f["title"] for f in result["findings"]
            if level is None or f["level"] == level]


S = pc.resolve_pacing_settings(None)

# ===== 1. 設定解析與夾限 =====
check("預設值", S == pc.DEFAULT_PACING, str(S))
s2 = pc.resolve_pacing_settings({"pacing": {
    "scene_threshold": 9.0, "max_static_seconds": 9999}})
check("scene_threshold 夾上限", s2["scene_threshold"] == 0.90, str(s2))
check("max_static_seconds 夾上限", s2["max_static_seconds"] == 300.0)
s3 = pc.resolve_pacing_settings({"pacing": {
    "scene_threshold": 0.0, "max_static_seconds": 0.0}})
check("scene_threshold 夾下限", s3["scene_threshold"] == 0.05, str(s3))
check("max_static_seconds 夾下限", s3["max_static_seconds"] == 5.0)
check("非數值回預設",
      pc.resolve_pacing_settings(
          {"pacing": {"scene_threshold": "bad"}})["scene_threshold"] == 0.30)

# ===== 2. ffmpeg 輸出解析 =====
sample = """
[Parsed_metadata_2 @ 0x1] frame:0    pts:45000   pts_time:30
[Parsed_metadata_2 @ 0x1] frame:1    pts:48000   pts_time:32.5
[Parsed_metadata_2 @ 0x1] frame:2    pts:51000   pts_time:34.25
"""
check("解析出所有時間點",
      pc.parse_scene_times(sample) == [30.0, 32.5, 34.25],
      str(pc.parse_scene_times(sample)))
check("空輸入回空清單", pc.parse_scene_times("") == [])
check("無關內容回空清單", pc.parse_scene_times("frame=100 fps=30") == [])
check("結果已排序",
      pc.parse_scene_times("pts_time:9\npts_time:2\npts_time:5")
      == [2.0, 5.0, 9.0])

# ===== 3. 鏡頭切分 =====
shots = pc.build_shots([30.0, 32.0, 34.0], 38.0)
check("鏡頭數＝剪接點數＋1", len(shots) == 4, str(shots))
check("第一個鏡頭從 0 開始", shots[0]["start"] == 0.0)
check("最後一個鏡頭到片尾", shots[-1]["end"] == 38.0)
check("鏡頭長度正確",
      [round(s["duration"], 2) for s in shots] == [30.0, 2.0, 2.0, 4.0],
      str([s["duration"] for s in shots]))
check("沒有剪接點時為單一鏡頭",
      pc.build_shots([], 60.0) == [{"start": 0.0, "end": 60.0,
                                    "duration": 60.0}])
check("長度為 0 時回空清單", pc.build_shots([10.0], 0.0) == [])
check("超出片長的剪接點被忽略",
      len(pc.build_shots([10.0, 999.0], 30.0)) == 2)
check("剪接點會先排序",
      [s["start"] for s in pc.build_shots([20.0, 10.0], 30.0)]
      == [0.0, 10.0, 20.0])
check("重複剪接點不會產生零長度鏡頭",
      all(s["duration"] > 0 for s in pc.build_shots([10.0, 10.0], 30.0)))

# ===== 4. 判定：本健檢的主判準是「單一畫面太久沒變化」 =====
# 前 30 秒完全沒有剪接——這正是實測既有健檢完全沒有提示的情況。
static = pc.build_shots([30.0, 32.0, 34.0, 36.0], 38.0)
r = pc.evaluate_pacing(static, 38.0, S)
check("抓到過長的靜止鏡頭", "畫面太久沒變化" in titles(r, pc.LEVEL_WARN))
check("點名的是那 30 秒的鏡頭",
      len(r["static_shots"]) == 1 and r["static_shots"][0]["duration"] == 30.0,
      str(r["static_shots"]))
check("有剪接時不會誤報「完全沒有畫面變化」",
      "畫面變化" in titles(r, pc.LEVEL_GOOD))
check("統計數字正確",
      r["stats"]["cut_count"] == 4 and r["stats"]["shot_count"] == 5
      and r["stats"]["longest"] == 30.0, str(r["stats"]))
check("中位數計算正確", r["stats"]["median"] == 2.0, str(r["stats"]["median"]))

# 節奏平均且都不長：應完全通過。
even = pc.build_shots([10.0, 20.0, 30.0, 40.0], 50.0)
r_even = pc.evaluate_pacing(even, 50.0, S)
check("節奏平均者判定通過", r_even["ok"])
check("節奏平均者沒有過長鏡頭警告",
      "畫面太久沒變化" in titles(r_even, pc.LEVEL_GOOD),
      str(titles(r_even)))
check("節奏平均者不報節奏不平均",
      "節奏不平均" not in titles(r_even), str(titles(r_even)))

# 完全沒有畫面變化：整支影片一鏡到底。
one = pc.build_shots([], 120.0)
r_one = pc.evaluate_pacing(one, 120.0, S)
check("一鏡到底判定為不合格", not r_one["ok"])
check("一鏡到底指出畫面變化問題",
      "畫面變化" in titles(r_one, pc.LEVEL_BAD), str(titles(r_one)))
check("一鏡到底不會再重複報一次過長鏡頭",
      "畫面太久沒變化" not in titles(r_one), str(titles(r_one)))

# 節奏忽快忽慢：最長鏡頭遠超中位數。
uneven = pc.build_shots([2.0, 4.0, 6.0, 8.0], 100.0)
r_uneven = pc.evaluate_pacing(uneven, 100.0, S)
check("節奏忽快忽慢會提醒",
      "節奏不平均" in titles(r_uneven, pc.LEVEL_WARN), str(titles(r_uneven)))

check("沒有鏡頭時明確回報",
      not pc.evaluate_pacing([], 0.0, S)["ok"])
check("沒有鏡頭時回報無法分析",
      "節奏分析" in titles(pc.evaluate_pacing([], 0.0, S), pc.LEVEL_BAD))

# ===== 5. 門檻可調要真的生效 =====
loose = pc.resolve_pacing_settings({"pacing": {"max_static_seconds": 60.0}})
check("放寬上限後 30 秒鏡頭不再被標記",
      "畫面太久沒變化" in titles(pc.evaluate_pacing(static, 38.0, loose),
                                pc.LEVEL_GOOD),
      str(titles(pc.evaluate_pacing(static, 38.0, loose))))
# 收緊門檻要用「有中等長度鏡頭」的素材才測得出來：原本的素材鏡頭是
# 30/2/2/2/2 秒，門檻從 25 收到 5 時那些 2 秒的鏡頭一樣不會被標記。
mixed = pc.build_shots([30.0, 40.0, 50.0], 60.0)   # 30/10/10/10 秒
strict = pc.resolve_pacing_settings({"pacing": {"max_static_seconds": 5.0}})
check("上限 25 秒時只有 30 秒的鏡頭被標記",
      len(pc.evaluate_pacing(mixed, 60.0, S)["static_shots"]) == 1)
check("收緊上限到 5 秒後四個鏡頭全被標記",
      len(pc.evaluate_pacing(mixed, 60.0, strict)["static_shots"]) == 4,
      str(len(pc.evaluate_pacing(mixed, 60.0, strict)["static_shots"])))

# ===== 6. B-roll 建議插入點 =====
points = pc.suggest_broll_points([{"start": 0.0, "end": 30.0,
                                   "duration": 30.0}], 25.0)
check("30 秒鏡頭在 25 秒處給一個插入點", points == [25.0], str(points))
long_points = pc.suggest_broll_points(
    [{"start": 0.0, "end": 100.0, "duration": 100.0}], 25.0)
check("長鏡頭每隔上限給一個插入點",
      long_points == [25.0, 50.0, 75.0], str(long_points))
check("插入點不會貼在鏡頭結尾",
      all(p < 100.0 - 1.0 for p in long_points), str(long_points))
check("沒有過長鏡頭時沒有插入點",
      pc.suggest_broll_points([], 25.0) == [])
check("插入點以該鏡頭起點為基準",
      pc.suggest_broll_points([{"start": 60.0, "end": 100.0,
                                "duration": 40.0}], 25.0) == [85.0])

# ===== 7. 報告文字 =====
report = pc.format_pacing_report(r, S)
check("報告含標題列", "剪輯節奏健檢" in report)
check("報告不含 markdown 星號（tk.Text 會原樣顯示）", "**" not in report)
check("報告列出鏡頭長度統計", "鏡頭長度統計" in report)
check("報告給出建議插入點", "建議插入" in report)
check("報告用時間戳標示位置", "0:00～0:30" in report, report[:300])
even_report = pc.format_pacing_report(r_even, S)
check("通過時給正面結論", "沒有明顯拖累留存的問題" in even_report)
check("空結果不會爆炸",
      "沒有可分析" in pc.format_pacing_report({"findings": []}, S))
check("時間格式化省略時位", pc.format_timestamp(65) == "1:05")
check("時間格式化保留時位", pc.format_timestamp(3661) == "1:01:01")

# ===== 8. 回歸：這與凍結畫面偵測是相反的性質 =====
# 凍結畫面看的是「畫面完全靜止」；talking head 長鏡頭裡人是會動的，
# 所以 freezedetect 抓不到，這正是本模組存在的理由。
from subtitle.videocheck import parse_dead_air
frozen = parse_dead_air("", 38.0)
check("沒有凍結訊號時 freezedetect 回報空清單",
      frozen.get("freezes") == [], str(frozen.get("freezes")))
check("同一段素材剪輯節奏健檢仍抓得到問題",
      len(pc.evaluate_pacing(static, 38.0, S)["static_shots"]) == 1,
      str(pc.evaluate_pacing(static, 38.0, S)["static_shots"]))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.34.0 測試全數通過。")
