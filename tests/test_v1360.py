# -*- coding: utf-8 -*-
"""v1.36.0 新功能測試：發佈資訊健檢（標題／說明欄／hashtag／標籤上限）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import publishcheck as pc


def titles(result, level=None):
    return [f["title"] for f in result["findings"]
            if level is None or f["level"] == level]


S = pc.resolve_publishcheck_settings(None)

# ===== 1. 設定解析與夾限 =====
check("預設值", S == pc.DEFAULT_PUBLISHCHECK, str(S))
hi = pc.resolve_publishcheck_settings({"publishcheck": {
    "title_limit": 9999, "description_byte_limit": 999999,
    "max_hashtags": 999, "tag_char_limit": 99999}})
check("title_limit 夾上限", hi["title_limit"] == 200, str(hi))
check("description_byte_limit 夾上限", hi["description_byte_limit"] == 10000)
check("max_hashtags 夾上限", hi["max_hashtags"] == 30)
check("tag_char_limit 夾上限", hi["tag_char_limit"] == 1000)
lo = pc.resolve_publishcheck_settings({"publishcheck": {
    "title_limit": 1, "description_byte_limit": 1, "max_hashtags": 0}})
check("title_limit 夾下限", lo["title_limit"] == 20, str(lo))
check("description_byte_limit 夾下限", lo["description_byte_limit"] == 500)
check("max_hashtags 夾下限", lo["max_hashtags"] == 1)
check("非數值回預設",
      pc.resolve_publishcheck_settings(
          {"publishcheck": {"max_hashtags": "bad"}})["max_hashtags"] == 15)
check("全部設定值皆為整數",
      all(isinstance(v, int) for v in S.values()), str(S))

# ===== 2. 位元組計算——對中文使用者是關鍵差異 =====
check("ASCII 一字一位元組", pc.utf8_bytes("abcde") == 5)
check("中文一字三位元組", pc.utf8_bytes("中文字") == 9)
check("空字串為 0", pc.utf8_bytes("") == 0)
check("None 視為 0", pc.utf8_bytes(None) == 0)
# 這是本模組存在的核心理由之一：用字數檢查會完全誤判中文說明欄。
zh = "這是一段中文說明欄的內容。" * 130
check("1690 個中文字超過 5000 位元組上限",
      len(zh) == 1690 and pc.utf8_bytes(zh) > 5000,
      f"{len(zh)} 字 / {pc.utf8_bytes(zh)} 位元組")
check("用字數檢查會誤判為未超過", len(zh) < 5000)

# ===== 3. hashtag 解析 =====
check("找出所有 hashtag",
      pc.find_hashtags("開頭 #攝影 中間 #相機 結尾")
      == ["#攝影", "#相機"], str(pc.find_hashtags("開頭 #攝影 中間 #相機 結尾")))
check("中文標點視為分隔",
      pc.find_hashtags("#攝影，#相機。#教學")
      == ["#攝影", "#相機", "#教學"], str(pc.find_hashtags("#攝影，#相機。#教學")))
check("保留重複項", len(pc.find_hashtags("#a #b #a")) == 3)
check("保留出現順序", pc.find_hashtags("#z #a") == ["#z", "#a"])
check("沒有 hashtag 回空清單", pc.find_hashtags("完全沒有標籤") == [])
check("空輸入回空清單", pc.find_hashtags("") == [])
check("單獨的井字號不算 hashtag", pc.find_hashtags("# ") == [])

# ===== 4. 標籤欄位解析與字元預算 =====
check("逗號分隔", pc.split_tags("攝影,相機,教學") == ["攝影", "相機", "教學"])
check("全形逗號也可分隔", pc.split_tags("攝影，相機") == ["攝影", "相機"])
check("去除空白與空項", pc.split_tags(" 攝影 , , 相機 ") == ["攝影", "相機"])
check("空輸入回空清單", pc.split_tags("") == [])
# 分隔用的逗號也佔預算，否則會低估而放行實際超量的輸入。
check("字元預算包含分隔逗號",
      pc.tags_char_count(["攝影", "相機"]) == 2 + 2 + 1,
      str(pc.tags_char_count(["攝影", "相機"])))
check("單一標籤沒有分隔字元", pc.tags_char_count(["攝影"]) == 2)
check("空清單為 0", pc.tags_char_count([]) == 0)

# ===== 5. hashtag 超量——本健檢最重要的一項（靜默失效）=====
over = pc.analyze_publish(
    description=" ".join(f"#標籤{i}" for i in range(1, 17)), settings=S)
check("16 個 hashtag 判定不合格", not over["ok"])
check("指出 hashtag 數量問題",
      "hashtag 數量" in titles(over, pc.LEVEL_BAD), str(titles(over)))
check("建議明確說明會「忽略全部」",
      "忽略全部" in [f["advice"] for f in over["findings"]
                    if f["title"] == "hashtag 數量"][0])
check("統計出正確的 hashtag 數", over["stats"]["hashtag_count"] == 16)

many = pc.analyze_publish(
    description=" ".join(f"#標籤{i}" for i in range(1, 9)), settings=S)
check("8 個 hashtag 未超上限但偏多，列為提醒",
      "hashtag 數量" in titles(many, pc.LEVEL_WARN), str(titles(many)))
check("偏多不影響合格判定（僅 WARN）", many["ok"])

few = pc.analyze_publish(description="#攝影 #相機 #教學", settings=S)
check("3 個 hashtag 判定通過",
      "hashtag 數量" in titles(few, pc.LEVEL_GOOD), str(titles(few)))
check("列出會顯示在標題上方的前 3 個",
      "顯示在標題上方的 hashtag" in titles(few))
check("前 3 個內容正確",
      "#攝影、#相機、#教學" in [f["detail"] for f in few["findings"]
                              if f["title"] == "顯示在標題上方的 hashtag"][0])

dup = pc.analyze_publish(description="#攝影 #相機 #攝影", settings=S)
check("重複的 hashtag 會提醒",
      "hashtag 重複" in titles(dup, pc.LEVEL_WARN), str(titles(dup)))
check("重複仍佔用額度（總數含重複）", dup["stats"]["hashtag_count"] == 3)

# 標題裡的 hashtag 也要算進去——它同樣佔用那 15 個額度。
both = pc.analyze_publish(title="教學 #攝影", description="#相機", settings=S)
check("標題與說明欄的 hashtag 一起計算",
      both["stats"]["hashtag_count"] == 2, str(both["stats"]))

# ===== 6. 標題長度 =====
check("標題超過 100 字元判定不合格",
      not pc.analyze_publish(title="標" * 101, settings=S)["ok"])
check("標題超長指出標題長度",
      "標題長度" in titles(pc.analyze_publish(title="標" * 101, settings=S),
                          pc.LEVEL_BAD))
mid = pc.analyze_publish(title="標" * 50, settings=S)
check("標題超過手機可見長度列為提醒",
      "標題長度" in titles(mid, pc.LEVEL_WARN), str(titles(mid)))
check("標題偏長不影響合格判定（僅 WARN）", mid["ok"])
check("標題在手機可見長度內判定通過",
      "標題長度" in titles(pc.analyze_publish(title="短標題", settings=S),
                          pc.LEVEL_GOOD))

# ===== 7. 說明欄位元組上限 =====
long_desc = pc.analyze_publish(description=zh, settings=S)
check("中文說明欄超過位元組上限判定不合格", not long_desc["ok"])
check("超長說明欄指出說明欄長度",
      "說明欄長度" in titles(long_desc, pc.LEVEL_BAD))
check("報告同時列出位元組與字數",
      "5070 位元組" in [f["detail"] for f in long_desc["findings"]
                       if f["title"] == "說明欄長度"][0]
      and "1690 個字" in [f["detail"] for f in long_desc["findings"]
                         if f["title"] == "說明欄長度"][0])
check("建議說明上限算的是位元組",
      "位元組" in [f["advice"] for f in long_desc["findings"]
                  if f["title"] == "說明欄長度"][0])
check("同樣字數的英文說明不會超過",
      pc.analyze_publish(description="a" * 1690, settings=S)["ok"])

# ===== 8. 標籤字元預算 =====
# 99 個「標籤N」只有 485 字元、剛好在 500 以內，測不出超量；
# 改用較長的標籤名確保真的超過預算。
big_tags = ",".join(f"攝影器材實測標籤{i}" for i in range(1, 60))
check("標籤超過字元預算判定不合格",
      not pc.analyze_publish(tags=big_tags, settings=S)["ok"])
check("標籤超量指出標籤長度",
      "標籤長度" in titles(pc.analyze_publish(tags=big_tags, settings=S),
                          pc.LEVEL_BAD))
check("正常標籤判定通過",
      "標籤長度" in titles(pc.analyze_publish(tags="攝影,相機,教學", settings=S),
                          pc.LEVEL_GOOD))

# ===== 9. 邊界情況 =====
empty = pc.analyze_publish(settings=S)
check("三個欄位皆空時明確回報", not empty["ok"])
check("三個欄位皆空時說明沒有可檢查的內容",
      "發佈資訊" in titles(empty, pc.LEVEL_BAD), str(titles(empty)))
check("只給說明欄也能檢查（其他欄位不報）",
      titles(pc.analyze_publish(description="#攝影 #相機 #教學", settings=S))
      and "標題長度" not in titles(
          pc.analyze_publish(description="#攝影 #相機 #教學", settings=S)))
check("只給標題也能檢查",
      "標題長度" in titles(pc.analyze_publish(title="測試標題", settings=S)))
check("純空白說明欄不視為有內容",
      "說明欄長度" not in titles(pc.analyze_publish(title="標題",
                                                  description="   ",
                                                  settings=S)))

# ===== 10. 門檻可調要真的生效 =====
loose = pc.resolve_publishcheck_settings({"publishcheck": {"max_hashtags": 20}})
check("放寬 hashtag 上限後 16 個不再判定不合格",
      pc.analyze_publish(
          description=" ".join(f"#標籤{i}" for i in range(1, 17)),
          settings=loose)["ok"])
strict = pc.resolve_publishcheck_settings({"publishcheck": {"max_hashtags": 2}})
check("收緊 hashtag 上限後 3 個就不合格",
      not pc.analyze_publish(description="#a #b #c", settings=strict)["ok"])
bigger = pc.resolve_publishcheck_settings(
    {"publishcheck": {"description_byte_limit": 10000}})
check("放寬說明欄上限後中文長文通過",
      pc.analyze_publish(description=zh, settings=bigger)["ok"])

# ===== 11. 報告文字 =====
report = pc.format_publish_report(over, S)
check("報告含標題列", "發佈資訊健檢" in report)
check("報告不含 markdown 星號（tk.Text 會原樣顯示）", "**" not in report)
check("報告列出統計", "統計：" in report)
check("不合格結論強調靜默失效", "不給任何提示" in report)
check("合格時給正面結論",
      "可以直接使用" in pc.format_publish_report(few, S))
check("空結果不會爆炸",
      "沒有可檢查" in pc.format_publish_report({"findings": []}, S))

# ===== 12. 回歸：既有發佈包完全沒有上限檢查 =====
# v1.10.0 的 publisher.py 會產生標題候選、描述草稿與標籤清單，
# 但從未檢查任何一項上限——這正是本版補上的缺口。
from subtitle.publisher import build_publish_pack, resolve_publish_settings
items = [{"kind": "speech", "keep": True, "start": i * 5.0,
          "end": i * 5.0 + 4.0, "text": f"這是第 {i} 段內容，講攝影器材實測",
          "tags": [], "fillers": 0, "score": 1.0} for i in range(8)]
pack = build_publish_pack(items, settings=resolve_publish_settings(None),
                          source_name="test.mp4")
check("既有發佈包不含任何上限提醒",
      not any(k in pack for k in ("5000", "位元組", "15 個上限", "忽略全部")),
      "發佈包內出現了上限字樣")
check("本模組補上了檢查入口",
      callable(getattr(pc, "analyze_publish", None)))
# 而且本模組確實能檢查既有發佈包的產出。
check("本模組可直接檢查既有發佈包的產出",
      isinstance(pc.analyze_publish(description=pack, settings=S)["stats"]
                 ["hashtag_count"], int))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.36.0 測試全數通過。")
