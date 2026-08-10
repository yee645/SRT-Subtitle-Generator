# -*- coding: utf-8 -*-
"""v1.37.0 新功能測試：字幕可讀性健檢（燒錄後會不會糊在背景裡）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import legibility as lg


def titles(result, level=None):
    return [f["title"] for f in result["findings"]
            if level is None or f["level"] == level]


def samples(*rows):
    """rows: (時間, 背景亮度, 帶內落差)"""
    return [{"time": t, "text": f"第 {i} 句", "luma": luma, "spread": spread}
            for i, (t, luma, spread) in enumerate(rows)]


S = lg.resolve_legibility_settings(None)
WHITE = {"position_y": 0.88, "text_color": "#FFFFFF", "stroke_width": 2}

# ===== 1. 設定解析與夾限 =====
check("預設值", S == lg.DEFAULT_LEGIBILITY, str(S))
hi = lg.resolve_legibility_settings({"legibility": {
    "sample_count": 999, "min_contrast": 999, "band_ratio": 9.0}})
check("sample_count 夾上限", hi["sample_count"] == 40, str(hi))
check("min_contrast 夾上限", hi["min_contrast"] == 200.0)
check("band_ratio 夾上限", hi["band_ratio"] == 0.40)
lo = lg.resolve_legibility_settings({"legibility": {
    "sample_count": 0, "min_contrast": 0, "band_ratio": 0.0}})
check("sample_count 夾下限", lo["sample_count"] == 3, str(lo))
check("min_contrast 夾下限", lo["min_contrast"] == 20.0)
check("band_ratio 夾下限", lo["band_ratio"] == 0.05)
check("非數值回預設",
      lg.resolve_legibility_settings(
          {"legibility": {"min_contrast": "bad"}})["min_contrast"] == 60.0)

# ===== 2. 文字亮度換算（要與 signalstats 的 Y 在同一個尺度）=====
check("白色亮度接近 255", abs(lg.text_luma("#FFFFFF") - 255.0) < 0.5)
check("黑色亮度為 0", lg.text_luma("#000000") == 0.0)
check("綠色權重最高（BT.601）",
      lg.text_luma("#00FF00") > lg.text_luma("#FF0000") > lg.text_luma("#0000FF"),
      f"{lg.text_luma('#00FF00')}/{lg.text_luma('#FF0000')}/{lg.text_luma('#0000FF')}")
check("支援不帶 # 的寫法", lg.text_luma("FFFFFF") == lg.text_luma("#FFFFFF"))
check("支援三碼縮寫", lg.text_luma("#FFF") == lg.text_luma("#FFFFFF"))
# 「當作白字」在模組內只有一個值：空值與解析失敗都回純白的實際亮度。
check("無法解析時當作白字（最常見也最保守）",
      lg.text_luma("不是顏色") == 255.0, str(lg.text_luma("不是顏色")))
check("空值當作白字", lg.text_luma("") == 255.0, str(lg.text_luma("")))
check("兩種 fallback 得到同一個值",
      lg.text_luma("") == lg.text_luma("不是顏色") == lg.text_luma("#FFFFFF"))

# ===== 3. 字幕帶位置計算 =====
band = lg.subtitle_band(1920, 1080, WHITE, 0.14)
check("帶寬等於畫面寬", band[0] == 1920, str(band))
check("帶高為畫面高的比例", band[1] == int(1080 * 0.14), str(band))
check("帶的水平起點為 0", band[2] == 0)
check("帶以 position_y 為中心",
      abs(band[3] + band[1] // 2 - int(1080 * 0.88)) <= 1, str(band))
top = lg.subtitle_band(1920, 1080, {"position_y": 0.02}, 0.14)
check("字幕在最上方時帶不會超出畫面", top[3] >= 0, str(top))
bottom = lg.subtitle_band(1920, 1080, {"position_y": 1.0}, 0.14)
check("字幕在最下方時帶不會超出畫面",
      bottom[3] + bottom[1] <= 1080, str(bottom))
check("沒有樣式時用預設位置",
      lg.subtitle_band(1920, 1080)[3] == lg.subtitle_band(1920, 1080, WHITE)[3])
check("極小畫面仍有最低帶高", lg.subtitle_band(64, 36, WHITE, 0.05)[1] >= 8)

# ===== 4. 取樣：逐句解碼太貴，均勻取樣 =====
cues = [{"start": i * 2.0, "end": i * 2.0 + 1.5, "text": f"第 {i} 句"}
        for i in range(50)]
picked = lg.sample_times(cues, 10)
check("取樣數不超過設定", len(picked) == 10, str(len(picked)))
check("取樣點取句子中點", abs(picked[0][0] - 0.75) < 0.01, str(picked[0]))
check("取樣涵蓋整段時間軸", picked[-1][0] > picked[0][0] * 10)
check("句數少於取樣數時全取",
      len(lg.sample_times(cues[:4], 10)) == 4)
check("略過空白句",
      len(lg.sample_times([{"start": 0, "end": 1, "text": "  "},
                           {"start": 1, "end": 2, "text": "有內容"}], 10)) == 1)
check("略過時間無效的句子",
      lg.sample_times([{"start": 5, "end": 5, "text": "零長度"}], 10) == [])
check("沒有字幕回空清單", lg.sample_times([], 10) == [])
check("取樣帶回文字內容", picked[0][1] == "第 0 句", str(picked[0]))

# ===== 5. 判定：主判準是文字與背景的亮度差 =====
# 白字（255）配亮背景（222）→ 對比 33，看不見。
bad = lg.evaluate_legibility(samples((1.0, 222.0, 0.0), (2.0, 222.0, 0.0),
                                     (3.0, 222.0, 0.0)), WHITE, S)
check("亮背景配白字判定不合格", not bad["ok"])
check("指出字幕與背景對比",
      "字幕與背景對比" in titles(bad, lg.LEVEL_BAD), str(titles(bad)))
check("列出所有對比不足的取樣點", len(bad["weak"]) == 3)
check("統計出最低對比", abs(bad["stats"]["min_contrast"] - 33.0) < 1.0,
      str(bad["stats"]["min_contrast"]))

# 白字（255）配暗背景（30）→ 對比 225，清楚。
good = lg.evaluate_legibility(samples((1.0, 30.0, 0.0), (2.0, 30.0, 0.0)),
                              WHITE, S)
check("暗背景配白字判定通過", good["ok"])
check("通過時列為 GOOD",
      "字幕與背景對比" in titles(good, lg.LEVEL_GOOD), str(titles(good)))
check("通過時沒有對比不足的句子", good["weak"] == [])

# 只有少數句子有問題 → WARN 而非 BAD（不該因為一兩句就整支判不合格）。
few = lg.evaluate_legibility(
    samples((1.0, 222.0, 0.0), (2.0, 30.0, 0.0), (3.0, 30.0, 0.0),
            (4.0, 30.0, 0.0), (5.0, 30.0, 0.0)), WHITE, S)
check("少數句子有問題時列為提醒而非不合格", few["ok"], str(titles(few)))
check("少數句子有問題仍會被列出", len(few["weak"]) == 1)
# 過半有問題 → BAD。
half = lg.evaluate_legibility(
    samples((1.0, 222.0, 0.0), (2.0, 222.0, 0.0), (3.0, 30.0, 0.0)),
    WHITE, S)
check("過半句子有問題時判定不合格", not half["ok"], str(titles(half)))

# ===== 6. 描邊寬度 =====
no_stroke = lg.evaluate_legibility(
    samples((1.0, 30.0, 0.0)),
    {"text_color": "#FFFFFF", "stroke_width": 0}, S)
check("沒有描邊會提醒",
      "描邊寬度" in titles(no_stroke, lg.LEVEL_WARN), str(titles(no_stroke)))
check("沒有描邊不影響合格判定（僅 WARN）", no_stroke["ok"])
check("有描邊時列為 GOOD",
      "描邊寬度" in titles(good, lg.LEVEL_GOOD))

# ===== 7. 背景忽亮忽暗：換單一顏色救不了，只有描邊有用 =====
varied = lg.evaluate_legibility(
    samples((1.0, 30.0, 200.0), (2.0, 30.0, 210.0)), WHITE, S)
check("背景明暗變化大會提醒",
      "背景明暗變化大" in titles(varied, lg.LEVEL_WARN), str(titles(varied)))
check("提醒中說明只有描邊救得了",
      "描邊" in [f["advice"] for f in varied["findings"]
                if f["title"] == "背景明暗變化大"][0])
check("背景穩定時不誤報",
      "背景明暗變化大" not in titles(good))

# ===== 8. 建議要照調研的先後順序：描邊 → 加粗 → 最後才底框 =====
advice_thin = [f["advice"] for f in lg.evaluate_legibility(
    samples((1.0, 222.0, 0.0)),
    {"text_color": "#FFFFFF", "stroke_width": 0}, S)["findings"]
    if f["title"] == "字幕與背景對比"][0]
check("沒描邊時第一順位建議是先加描邊",
      advice_thin.index("邊框寬度") < advice_thin.index("底框"), advice_thin)
advice_thick = [f["advice"] for f in bad["findings"]
                if f["title"] == "字幕與背景對比"][0]
check("已有描邊時建議再加粗", "再加粗" in advice_thick, advice_thick)
check("白字時建議可改成淺灰／淡黃", "淺灰" in advice_thick, advice_thick)
check("底框一律排在最後並註明會突兀",
      "突兀" in advice_thick and advice_thick.index("底框")
      > advice_thick.index("邊框寬度"), advice_thick)

# ===== 9. 邊界情況 =====
empty = lg.evaluate_legibility([], WHITE, S)
check("沒有取樣時明確回報", not empty["ok"])
check("沒有取樣時說明無法分析",
      "字幕可讀性" in titles(empty, lg.LEVEL_BAD), str(titles(empty)))
check("沒有取樣時不會有統計", empty["stats"] == {})

# 深色文字配亮背景應該是「合格」的——判準是差距而不是「背景亮不亮」。
dark_text = lg.evaluate_legibility(
    samples((1.0, 222.0, 0.0)),
    {"text_color": "#000000", "stroke_width": 2}, S)
check("深色文字配亮背景判定通過（判準是差距不是背景亮度）", dark_text["ok"],
      str(titles(dark_text)))

# ===== 10. 門檻可調要真的生效 =====
loose = lg.resolve_legibility_settings({"legibility": {"min_contrast": 20.0}})
check("放寬對比門檻後 33 的對比不再被標記",
      lg.evaluate_legibility(samples((1.0, 222.0, 0.0)), WHITE, loose)["ok"])
# 白字配亮度 30 的背景對比高達 225，超過門檻可調的上限（200），
# 任何門檻都標記不了；要測收緊就得用對比落在可調範圍內的背景。
strict = lg.resolve_legibility_settings({"legibility": {"min_contrast": 200.0}})
mid_bg = samples((1.0, 130.0, 0.0))   # 白字 255 − 130 = 對比 125
check("預設門檻下對比 125 不會被標記",
      lg.evaluate_legibility(mid_bg, WHITE, S)["weak"] == [])
check("收緊對比門檻後對比 125 被標記",
      len(lg.evaluate_legibility(mid_bg, WHITE, strict)["weak"]) == 1,
      str(lg.evaluate_legibility(mid_bg, WHITE, strict)["weak"]))

# ===== 11. 報告文字 =====
report = lg.format_legibility_report(bad, S)
check("報告含標題列", "字幕可讀性健檢" in report)
check("報告不含 markdown 星號（tk.Text 會原樣顯示）", "**" not in report)
check("報告列出量測數值", "量測數值" in report)
check("報告列出對比不足的句子", "對比不足的句子" in report)
check("報告用時間戳標示位置", "0:01" in report, report[:400])
check("不合格結論說明這種問題通常燒錄後才發現",
      "燒錄完" in report)
check("合格時給正面結論",
      "可以直接燒錄" in lg.format_legibility_report(good, S))
check("空結果不會爆炸",
      "沒有可分析" in lg.format_legibility_report({"findings": []}, S))
check("過長的句子會截斷顯示",
      "…" in lg.format_legibility_report(
          {"findings": [{"level": "bad", "title": "t", "detail": "d",
                         "advice": ""}],
           "weak": [{"time": 1.0, "text": "字" * 40}], "stats": {}}, S))
check("時間格式化省略時位", lg.format_timestamp(65) == "1:05")
check("時間格式化保留時位", lg.format_timestamp(3661) == "1:01:01")

# ===== 12. 回歸：既有的三項檢查都不看這件事 =====
# 字幕健檢是純文字分析、色彩健檢量的是整張畫面、Shorts 安全區處理的是位置。
from subtitle.subtitlecheck import analyze_cues, resolve_subcheck_settings
plain = [{"start": 1.0, "end": 3.0, "text": "這句字幕會糊在亮背景裡"}]
check("字幕健檢對這種問題沒有任何意見",
      len(analyze_cues(plain, resolve_subcheck_settings(None))
          .get("issues") or []) == 0)
from subtitle import colorcheck
check("色彩健檢量的是整張畫面、沒有字幕帶的概念",
      not any("band" in name or "subtitle" in name
              for name in dir(colorcheck)),
      str([n for n in dir(colorcheck) if not n.startswith("_")]))
check("本模組補上了字幕帶的量測入口",
      callable(getattr(lg, "subtitle_band", None))
      and callable(getattr(lg, "analyze_legibility", None)))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.37.0 測試全數通過。")
