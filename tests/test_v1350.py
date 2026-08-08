# -*- coding: utf-8 -*-
"""v1.35.0 新功能測試：封面健檢（手機尺寸下看不看得清楚）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import thumbcheck as tc


def titles(result, level=None):
    return [f["title"] for f in result["findings"]
            if level is None or f["level"] == level]


def metrics(**kw):
    base = {"path": "/x/cover.png", "name": "cover.png",
            "width": 1280, "height": 720, "file_mb": 0.5,
            "edge_full": 10.0, "edge_mobile": 8.0, "detail_keep": 0.80,
            "contrast": 120.0, "luma": 110.0, "saturation": 50.0}
    base.update(kw)
    return base


S = tc.resolve_thumbcheck_settings(None)

# ===== 1. 設定解析與夾限 =====
check("預設值", S == tc.DEFAULT_THUMBCHECK, str(S))
hi = tc.resolve_thumbcheck_settings({"thumbcheck": {
    "mobile_width": 9999, "min_detail_keep": 9.0, "min_contrast": 9999,
    "min_saturation": 9999, "max_file_mb": 9999}})
check("mobile_width 夾上限", hi["mobile_width"] == 640, str(hi))
check("min_detail_keep 夾上限", hi["min_detail_keep"] == 1.0)
check("min_contrast 夾上限", hi["min_contrast"] == 200.0)
check("max_file_mb 夾上限", hi["max_file_mb"] == 10.0)
lo = tc.resolve_thumbcheck_settings({"thumbcheck": {
    "mobile_width": 1, "min_detail_keep": 0.0, "min_contrast": 0.0,
    "max_file_mb": 0.0}})
check("mobile_width 夾下限", lo["mobile_width"] == 80, str(lo))
check("min_detail_keep 夾下限", lo["min_detail_keep"] == 0.05)
check("min_contrast 夾下限", lo["min_contrast"] == 10.0)
check("max_file_mb 夾下限", lo["max_file_mb"] == 0.5)
check("非數值回預設",
      tc.resolve_thumbcheck_settings(
          {"thumbcheck": {"min_contrast": "bad"}})["min_contrast"] == 40.0)
check("mobile_width 保持整數",
      isinstance(tc.resolve_thumbcheck_settings(None)["mobile_width"], int))

# ===== 2. signalstats 解析 =====
sample = """
[Parsed_metadata_1 @ 0x1] lavfi.signalstats.YMIN=42
[Parsed_metadata_1 @ 0x1] lavfi.signalstats.YLOW=42
[Parsed_metadata_1 @ 0x1] lavfi.signalstats.YAVG=87.8906
[Parsed_metadata_1 @ 0x1] lavfi.signalstats.YHIGH=183
[Parsed_metadata_1 @ 0x1] lavfi.signalstats.SATAVG=51.9
"""
parsed = tc.parse_signalstats(sample)
check("解析出 YAVG", parsed.get("YAVG") == 87.8906, str(parsed))
check("解析出 YHIGH/YLOW",
      parsed.get("YHIGH") == 183.0 and parsed.get("YLOW") == 42.0)
check("解析出 SATAVG", parsed.get("SATAVG") == 51.9)
check("空輸入回空 dict", tc.parse_signalstats("") == {})
check("無關內容回空 dict", tc.parse_signalstats("frame=1 fps=30") == {})

# ===== 3. 判定：主判準是「縮到手機尺寸還看不看得清」 =====
good = tc.evaluate_thumbnail(metrics(), S)
check("合格封面判定通過", good["ok"], str(titles(good, tc.LEVEL_BAD)))
check("合格封面沒有任何 BAD", titles(good, tc.LEVEL_BAD) == [])

busy = tc.evaluate_thumbnail(metrics(detail_keep=0.07), S)
check("畫面太雜判定不合格", not busy["ok"])
check("畫面太雜指出手機尺寸可讀性",
      "手機尺寸可讀性" in titles(busy, tc.LEVEL_BAD), str(titles(busy)))
check("畫面太雜的建議提到簡化",
      "簡化" in [f["advice"] for f in busy["findings"]
                if f["title"] == "手機尺寸可讀性"][0])

flat = tc.evaluate_thumbnail(metrics(contrast=11.0, saturation=3.0), S)
check("低對比判定不合格", not flat["ok"])
check("低對比指出對比問題", "對比" in titles(flat, tc.LEVEL_BAD))
check("低飽和列為提醒而非不合格",
      "色彩鮮明度" in titles(flat, tc.LEVEL_WARN), str(titles(flat)))

# 通過與不通過共用同一個中性標題，報告才讀得順（"✔ 手機上看不清楚" 讀不通）。
check("通過時標題與不通過時一致",
      "手機尺寸可讀性" in titles(good, tc.LEVEL_GOOD))

# ===== 4. 規格檢查 =====
small = tc.evaluate_thumbnail(metrics(width=640, height=360), S)
check("解析度偏低列為提醒", "解析度" in titles(small, tc.LEVEL_WARN))
check("解析度偏低不影響合格判定（僅 WARN）", small["ok"])

square = tc.evaluate_thumbnail(metrics(width=1000, height=1000), S)
check("非 16:9 列為提醒", "長寬比" in titles(square, tc.LEVEL_WARN))
check("16:9 不會被誤報",
      "長寬比" not in titles(tc.evaluate_thumbnail(metrics(), S)))
check("接近 16:9 的尺寸不會被誤報",
      "長寬比" not in titles(
          tc.evaluate_thumbnail(metrics(width=1920, height=1080), S)))

big = tc.evaluate_thumbnail(metrics(file_mb=2.54), S)
check("超過 2MB 判定不合格", not big["ok"])
check("超過 2MB 指出檔案大小", "檔案大小" in titles(big, tc.LEVEL_BAD))
check("剛好在上限內不會被標記",
      "檔案大小" not in titles(tc.evaluate_thumbnail(metrics(file_mb=1.99), S)))

check("沒有量測資料時明確回報",
      not tc.evaluate_thumbnail({}, S)["ok"])
check("沒有量測資料時回報封面內容",
      "封面內容" in titles(tc.evaluate_thumbnail({}, S), tc.LEVEL_BAD))

# ===== 5. 門檻可調要真的生效 =====
loose = tc.resolve_thumbcheck_settings({"thumbcheck": {"min_detail_keep": 0.05}})
check("放寬細節保留門檻後不再標記",
      tc.evaluate_thumbnail(metrics(detail_keep=0.07), loose)["ok"])
strict = tc.resolve_thumbcheck_settings({"thumbcheck": {"min_contrast": 150.0}})
check("收緊對比門檻後原本合格者被標記",
      not tc.evaluate_thumbnail(metrics(), strict)["ok"])
bigger = tc.resolve_thumbcheck_settings({"thumbcheck": {"max_file_mb": 5.0}})
check("放寬檔案上限後 2.54MB 不再被標記",
      "檔案大小" not in titles(tc.evaluate_thumbnail(metrics(file_mb=2.54),
                                                    bigger)))

# ===== 6. 分數：用於同一批候選圖之間排序 =====
check("合格封面分數高", tc.thumbnail_score(metrics(), S) >= 90,
      str(tc.thumbnail_score(metrics(), S)))
check("三項都很差時分數低",
      tc.thumbnail_score(metrics(detail_keep=0.05, contrast=5.0,
                                 saturation=2.0), S) < 25,
      str(tc.thumbnail_score(metrics(detail_keep=0.05, contrast=5.0,
                                     saturation=2.0), S)))
check("分數落在 0~100",
      0.0 <= tc.thumbnail_score(metrics(detail_keep=1.0, contrast=999.0,
                                        saturation=999.0), S) <= 100.0)
check("沒有量測資料時分數為 0", tc.thumbnail_score({}, S) == 0.0)
# 細節保留權重最高（0.5），所以它壞掉的影響應大於飽和度壞掉。
check("細節保留的權重高於飽和度",
      tc.thumbnail_score(metrics(detail_keep=0.05), S)
      < tc.thumbnail_score(metrics(saturation=1.0), S),
      f"{tc.thumbnail_score(metrics(detail_keep=0.05), S)} vs "
      f"{tc.thumbnail_score(metrics(saturation=1.0), S)}")

# ===== 7. 報告文字 =====
report = tc.format_thumb_report(busy, S)
check("報告含檔名", "cover.png" in report)
check("報告不含 markdown 星號（tk.Text 會原樣顯示）", "**" not in report)
check("報告列出量測數值", "量測數值" in report)
check("報告顯示綜合分數", "綜合分數" in report)
check("不合格時結論說明手機吃虧", "手機上會吃虧" in report)
check("合格時給正面結論",
      "可以使用" in tc.format_thumb_report(good, S))
check("空結果不會爆炸",
      "沒有可分析" in tc.format_thumb_report({"findings": []}, S))
check("讀取失敗時報告寫出原因",
      "讀不到" in tc.format_thumb_report(
          {"findings": [], "error": "讀不到圖片內容"}, S))

# ===== 8. 多張候選圖比較 =====
ranking = [
    {"ok": True, "score": 92.0, "findings": [],
     "metrics": metrics(name="a.png"), "error": None},
    {"ok": False, "score": 40.0, "findings": [],
     "metrics": metrics(name="b.png", contrast=11.0), "error": None},
]
text = tc.format_ranking_report(ranking, S)
check("比較報告依序列出", text.index("a.png") < text.index("b.png"))
check("比較報告指出建議使用哪一張", "建議使用：a.png" in text, text)
check("比較報告標示通過與否", "✔" in text and "✘" in text)
check("比較報告說明分數僅供相對比較", "相對比較" in text)
check("全部不合格時不亂推薦",
      "沒有一張通過健檢" in tc.format_ranking_report(
          [{"ok": False, "score": 10.0, "findings": [],
            "metrics": metrics(name="c.png"), "error": None}], S))
check("空清單不會爆炸",
      "沒有可比較" in tc.format_ranking_report([], S))
check("無法分析的項目照實列出",
      "無法分析" in tc.format_ranking_report(
          [{"ok": False, "score": 0.0, "findings": [],
            "metrics": {"name": "x.png"}, "error": "不是圖片檔"}], S))

# ===== 9. 回歸：既有 thumbnails 模組只挑圖、不評估產出 =====
# v1.11.0 的 thumbnails.py 只在「挑哪一格」時算清晰度，挑完就結束，
# 從未評估過產出的封面本身好不好用——這正是本版補上的缺口。
from subtitle import thumbnails
check("既有模組沒有任何評估封面的公開函式",
      not any(name for name in dir(thumbnails)
              if "evaluate" in name or "check" in name.lower()),
      str([n for n in dir(thumbnails) if not n.startswith("_")]))
check("本模組補上了評估入口",
      callable(getattr(tc, "check_thumbnail", None))
      and callable(getattr(tc, "rank_thumbnails", None)))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.35.0 測試全數通過。")
