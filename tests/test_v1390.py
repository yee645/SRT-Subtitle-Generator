# -*- coding: utf-8 -*-
"""v1.39.0 新功能測試：片尾空間健檢（最後 20 秒留得下結束畫面嗎）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import endscreen as es


def by_title(result, title):
    for row in result["findings"]:
        if row["title"] == title:
            return row
    return None


def cue(start, end, text="說一句話"):
    return {"start": start, "end": end, "text": text}


S = es.resolve_endscreen_settings(None)

# ===== 1. 設定解析與夾限 =====
check("預設時間窗 20 秒（官方最長值）", S["window_seconds"] == 20.0, str(S))
check("預設講話覆蓋率門檻 0.3", S["min_speech_ratio"] == 0.30)
check("預設畫面細節量門檻 12（實測校準）", S["max_busy_edge"] == 12.0)
over = es.resolve_endscreen_settings(
    {"endscreen": {"window_seconds": 999, "min_speech_ratio": 5.0,
                   "max_busy_edge": 999}})
check("時間窗夾限上界", over["window_seconds"] == es._WINDOW_RANGE[1], str(over))
check("覆蓋率夾限到 1.0", over["min_speech_ratio"] == 1.0)
check("細節量夾限上界", over["max_busy_edge"] == es._BUSY_RANGE[1])
under = es.resolve_endscreen_settings(
    {"endscreen": {"window_seconds": 0, "min_speech_ratio": -3}})
check("時間窗夾限下界", under["window_seconds"] == es._WINDOW_RANGE[0])
check("覆蓋率夾限下界", under["min_speech_ratio"] == 0.0)
bad = es.resolve_endscreen_settings({"endscreen": {"max_busy_edge": "很雜"}})
check("無法轉數字時退回預設",
      bad["max_busy_edge"] == es.DEFAULT_ENDSCREEN["max_busy_edge"])
none = es.resolve_endscreen_settings({"endscreen": {"window_seconds": None}})
check("None 不覆蓋預設值", none["window_seconds"] == 20.0)
check("空設定等同預設", es.resolve_endscreen_settings({}) == S)

# ===== 2. 時間窗計算 =====
check("長片取最後 20 秒", es.window_bounds(300, 20) == (280.0, 300.0))
check("影片比時間窗短就從 0 開始", es.window_bounds(8, 20) == (0.0, 8.0))
check("零長度不會變成負數", es.window_bounds(0, 20) == (0.0, 0.0))
check("負長度視為 0", es.window_bounds(-5, 20) == (0.0, 0.0))
check("時間窗剛好等於片長", es.window_bounds(20, 20) == (0.0, 20.0))

# ===== 3. 落在時間窗內的字幕 =====
cues = [cue(10, 15, "開頭"), cue(275, 282, "跨進時間窗"),
        cue(285, 290, "片尾一"), cue(292, 298, "片尾二")]
inside = es.cues_in_window(cues, 280, 300)
check("只取與時間窗重疊的句子", len(inside) == 3, str(len(inside)))
check("跨越邊界的句子算在內", inside[0]["text"] == "跨進時間窗")
check("剛好在邊界結束的句子不算",
      es.cues_in_window([cue(270, 280, "剛好結束")], 280, 300) == [])
check("剛好在邊界開始的句子不算",
      es.cues_in_window([cue(300, 310, "之後才開始")], 280, 300) == [])
check("空白文字的句子不算",
      es.cues_in_window([cue(285, 290, "   ")], 280, 300) == [])
check("沒有字幕清單也不會炸", es.cues_in_window(None, 280, 300) == [])

# ===== 4. 講話覆蓋率 =====
check("覆蓋率＝講話秒數／時間窗長度",
      abs(es.speech_ratio([cue(285, 291)], 280, 300) - 0.30) < 1e-9,
      str(es.speech_ratio([cue(285, 291)], 280, 300)))
check("超出時間窗的部分只算窗內",
      abs(es.speech_ratio([cue(270, 290)], 280, 300) - 0.50) < 1e-9)
# 重疊的句子若不合併，比例會算成 2.0 這種不可能的數字。
overlap = es.speech_ratio([cue(280, 300), cue(281, 299)], 280, 300)
check("重疊的句子先合併，比例不超過 1", overlap == 1.0, str(overlap))
check("相鄰不重疊的句子各自計入",
      abs(es.speech_ratio([cue(280, 285), cue(290, 295)], 280, 300) - 0.5)
      < 1e-9)
check("沒有字幕就是 0", es.speech_ratio([], 280, 300) == 0.0)
check("零長度時間窗回傳 0", es.speech_ratio([cue(0, 10)], 300, 300) == 0.0)

# ===== 5. 字幕位置 vs 結束畫面元素區 =====
# 這是本版最容易寫錯的一項：判斷的是「字幕擺在哪」不是「有沒有字幕」。
# 最後 20 秒本來就該有字幕（沒有反而是死寂片尾），所以預設值必須通過。
default_band = es.subtitle_band_range({})
check("預設字幕帶算在畫面下緣",
      abs(default_band[0] - 0.81) < 1e-9 and abs(default_band[1] - 0.95) < 1e-9,
      str(default_band))
check("預設位置不落進元素區", es.band_hits_element_zone({}) is False)
check("字幕移到畫面中央會落進元素區",
      es.band_hits_element_zone({"position_y": 0.5}) is True)
check("字幕稍微上移就會碰到元素區",
      es.band_hits_element_zone({"position_y": 0.75}) is True)
check("字幕壓到最底部也是安全的",
      es.band_hits_element_zone({"position_y": 1.0}) is False)
check("建議下限比元素區下緣再低半條字幕帶",
      es.safe_position_y() == 0.87, str(es.safe_position_y()))
check("建議下限本身剛好安全",
      es.band_hits_element_zone({"position_y": es.safe_position_y()}) is False)
check("壞掉的 position_y 退回預設",
      es.subtitle_band_range({"position_y": "低一點"}) == default_band)
check("position_y 夾限在 0~1",
      es.subtitle_band_range({"position_y": 9})[1] == 1.0)
check("沒有樣式時用預設值", es.subtitle_band_range(None) == default_band)

# ===== 6. 判定：四種情境 =====
tail = [cue(285, 291, "訂閱一下"), cue(292, 298, "下支影片見")]

good = es.evaluate_endscreen(300, tail, 0.60, 10.0, S, {})
check("理想片尾整體通過", good["ok"] is True)
check("理想片尾沒有任何警告",
      all(f["level"] == es.LEVEL_GOOD for f in good["findings"]),
      str([(f["level"], f["title"]) for f in good["findings"]]))
check("理想片尾有三項檢查", len(good["findings"]) == 3)

covered = es.evaluate_endscreen(300, tail, 0.60, 10.0, S, {"position_y": 0.5})
row = by_title(covered, "字幕位置")
check("字幕擺在元素區會警告", row["level"] == es.LEVEL_WARN, str(row))
check("警告列出實際的字幕高度", "43%" in row["detail"], row["detail"])
check("警告列出被影響的句子", "訂閱一下" in row["detail"])
check("建議給出具體的位置數字", "0.87" in row["advice"], row["advice"])

silent = es.evaluate_endscreen(300, [], 0.0, 10.0, S, {})
row = by_title(silent, "片尾內容")
check("死寂片尾會警告", row["level"] == es.LEVEL_WARN, str(row))
check("死寂片尾指出覆蓋率", "0%" in row["detail"], row["detail"])
check("沒字幕時字幕位置一項是通過的",
      by_title(silent, "字幕位置")["level"] == es.LEVEL_GOOD)

busy = es.evaluate_endscreen(300, tail, 0.60, 40.0, S, {})
row = by_title(busy, "片尾畫面")
check("畫面太雜會警告", row["level"] == es.LEVEL_WARN, str(row))
check("警告同時給出實測值與門檻",
      "40" in row["detail"] and "12" in row["detail"], row["detail"])

short = es.evaluate_endscreen(3, [], 0.0, 10.0, S, {})
check("太短的影片是 bad", short["ok"] is False)
check("太短的影片指出最短長度",
      "5" in by_title(short, "片尾空間")["detail"])
check("太短的影片不再重複報死寂片尾",
      by_title(short, "片尾內容") is None,
      str([f["title"] for f in short["findings"]]))

unknown = es.evaluate_endscreen(0, [], 0.0, None, S, {})
check("讀不到長度是 bad 且只回一項",
      unknown["ok"] is False and len(unknown["findings"]) == 1)

# 邊界：長度剛好等於最短值時不該再報「太短」。
edge = es.evaluate_endscreen(es.MIN_ENDSCREEN_SECONDS, [], 0.0, None, S, {})
check("剛好 5 秒不算太短",
      by_title(edge, "片尾空間") is None,
      str([f["title"] for f in edge["findings"]]))

# 沒有畫面（純音訊）時不該憑空生出畫面檢查。
audio_only = es.evaluate_endscreen(300, tail, 0.60, None, S, {})
check("沒有畫面就不報畫面檢查", by_title(audio_only, "片尾畫面") is None)
check("沒有畫面仍會檢查字幕與內容", len(audio_only["findings"]) == 2)

# 門檻確實可調：同一份資料，門檻放寬後不再警告。
loose = es.resolve_endscreen_settings({"endscreen": {"min_speech_ratio": 0.0}})
check("放寬覆蓋率門檻後死寂片尾不再警告",
      by_title(es.evaluate_endscreen(300, [], 0.0, None, loose, {}),
               "片尾內容")["level"] == es.LEVEL_GOOD)
tight = es.resolve_endscreen_settings({"endscreen": {"max_busy_edge": 5.0}})
check("收緊細節量門檻後原本通過的畫面會警告",
      by_title(es.evaluate_endscreen(300, tail, 0.6, 10.0, tight, {}),
               "片尾畫面")["level"] == es.LEVEL_WARN)

# ===== 7. 統計數值 =====
stats = good["stats"]
check("統計含影片長度", stats["duration"] == 300)
check("統計含時間窗起點", stats["window_start"] == 280.0)
check("短片的時間窗長度是片長不是 20",
      es.evaluate_endscreen(8, [], 0.0, None, S, {})["stats"]["window_seconds"]
      == 8.0)
check("統計含字幕句數", stats["tail_cue_count"] == 2)
check("統計含字幕帶範圍",
      abs(stats["band_top"] - 0.81) < 1e-9)

# ===== 8. 時間顯示 =====
check("秒數排成 M:SS", es.format_timestamp(285) == "4:45")
check("超過一小時排成 H:MM:SS", es.format_timestamp(3725) == "1:02:05")
check("零秒顯示 0:00", es.format_timestamp(0) == "0:00")
check("負數不會變成怪字串", es.format_timestamp(-5) == "0:00")

# ===== 9. 報告排版 =====
text = es.format_endscreen_report(good, S)
check("報告有標題", "片尾空間健檢" in text)
check("報告用勾號標示通過項", "✔" in text)
check("報告含量測數值", "量測數值" in text and "講話覆蓋率" in text)
check("報告含字幕高度與元素區", "字幕高度" in text and "元素區" in text)
check("通過時給出正面結論", "留得下結束畫面" in text)
warn_text = es.format_endscreen_report(covered, S)
check("有警告時列出建議", "建議：" in warn_text)
check("警告用驚嘆號標示", "⚠" in warn_text)
# 有警告卻寫「留得下結束畫面」會讓人以為沒事——結論必須分三種狀態。
check("有警告時結論不說得像全數通過",
      "1 項值得調整" in warn_text, warn_text.splitlines()[-1])
check("全數通過時結論才是正面的", "留得下結束畫面" in text)
check("有 bad 時結論指出有問題",
      "片尾的空間有問題" in es.format_endscreen_report(short, S))
check("報告不使用 Markdown（tk.Text 會原樣顯示星號）",
      "**" not in text and "**" not in warn_text)
check("空結果不會炸",
      "沒有可分析的內容" in es.format_endscreen_report({}, S))
check("None 結果不會炸",
      "沒有可分析的內容" in es.format_endscreen_report(None, S))
check("不給 settings 也能排版", isinstance(es.format_endscreen_report(good), str))

# ===== 10. 與總體檢的整合 =====
from subtitle import preflight as pf

ps = pf.resolve_preflight_settings(None)
check("總體檢預設納入片尾空間", ps["run_endscreen"] is True)
names = [n for n, _ in pf._build_steps(ps, True, True)]
check("有畫面有字幕時會跑片尾空間", "片尾空間" in names, str(names))
audio_names = [n for n, _ in pf._build_steps(ps, False, False)]
check("純音訊無字幕時仍會跑片尾空間（死寂片尾與畫面無關）",
      "片尾空間" in audio_names, str(audio_names))
off_names = [n for n, _ in pf._build_steps(
    pf.resolve_preflight_settings({"preflight": {"run_endscreen": False}}),
    True, True)]
check("可單獨關閉片尾空間", "片尾空間" not in off_names, str(off_names))

import inspect
src = inspect.getsource(pf._run_endscreen)
check("轉接器沒有自己的判斷邏輯",
      " if " not in src and "LEVEL_" not in src, src)

# 正規化後仍保得住 findings 的形狀。
rows = pf.normalize_findings(good, "片尾空間")
check("findings 可被總體檢正規化", len(rows) == 3, str(rows))
check("正規化後帶上來源", all(r["source"] == "片尾空間" for r in rows))

# ===== 11. 設定檔預設值 =====
from config import DEFAULT_CONFIG

check("config 有 endscreen 區段", "endscreen" in DEFAULT_CONFIG)
check("config 預設值與模組一致",
      DEFAULT_CONFIG["endscreen"] == es.DEFAULT_ENDSCREEN,
      str(DEFAULT_CONFIG["endscreen"]))
check("config 的 preflight 有 run_endscreen",
      DEFAULT_CONFIG["preflight"]["run_endscreen"] is True)

# ===== 12. 量測函式的邊界（不呼叫 ffmpeg）=====
check("零長度時間窗直接回 0，不呼叫 ffmpeg",
      es.measure_tail_busyness("/不存在的檔案.mp4", 300, 300) == 0.0)
check("ffmpeg 失敗時回 0 而不是拋例外",
      es.measure_tail_busyness("/不存在的檔案.mp4", 0, 5) == 0.0)

# 回歸：metadata=print 走 info 層級，加 -v error 會把數值全部吞掉。
src = inspect.getsource(es.measure_tail_busyness)
check("量測指令沒有加 -v error", '"-v", "error"' not in src)
check("量測指令有停用音訊解碼", '"-an"' in src)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.39.0 測試全數通過。")
