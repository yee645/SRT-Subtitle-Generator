# -*- coding: utf-8 -*-
"""
`subtitle/ocrengine.py` 測試：本地 OCR 引擎（tesseract）的包裝層。

ROADMAP 第 9 項第一階段的第 1 項。本檔守住四件事：

  1. **三種模式的結果照信心值挑**，而且空結果不能以 0 分參賽。
  2. **貴的模式（放大重跑）只在可能救得起來時才跑。** 兩頭都不划算：已
     經夠準的不必救、根本沒讀到字的救不起來。這條規則是實測逼出來的
     ——沒有它，那張雜訊圖光放大就跑掉 6.8 秒還是亂碼。
  3. **放大後的座標要換算回原圖**，否則框回去的位置全錯。
  4. **引擎不在時要講得出下一步**，不是丟一個 FileNotFoundError。

純邏輯那幾段不需要 tesseract；最後的實跑段有 tesseract 與 ffmpeg 才跑，
沒有就明講略過（不是靜默通過）。
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import ocrengine as oe

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


BASE = oe.resolve_ocrengine_settings(None)


# ===== 1. 設定 ==========================================================

check("沒有設定檔時取得預設值",
      BASE["good_enough_conf"] == oe.DEFAULT_OCRENGINE["good_enough_conf"]
      and BASE["lang"] == "eng")
check("設定檔的值會被讀進來",
      oe.resolve_ocrengine_settings(
          {"ocrengine": {"lang": "jpn"}})["lang"] == "jpn")
check("離譜的值會被夾回合理範圍",
      oe.resolve_ocrengine_settings(
          {"ocrengine": {"timeout_seconds": 99999}})["timeout_seconds"] == 300
      and oe.resolve_ocrengine_settings(
          {"ocrengine": {"max_upscale_pixels": 1}})["max_upscale_pixels"]
      == 100_000)
check("空白語言設定退回預設，不會送出空字串給 tesseract",
      oe.resolve_ocrengine_settings({"ocrengine": {"lang": "   "}})["lang"]
      == "eng")
check("不認得的鍵不會混進來",
      "nonsense" not in oe.resolve_ocrengine_settings(
          {"ocrengine": {"nonsense": 1}}))


# ===== 2. 貴的模式要不要跑（本模組最重要的一條） ========================

worth, why = oe.upscale_worthwhile(96.0, BASE)
check("已經夠準時不再花時間放大重跑", not worth and "夠準" in why, why)
worth, why = oe.upscale_worthwhile(22.0, BASE)
check("根本沒讀到字時也不放大（實測那張雜訊圖的兩個便宜模式是 0 與 22，"
      "放大跑掉 6.8 秒還是亂碼）",
      not worth and "讀不到" in why, why)
worth, why = oe.upscale_worthwhile(80.3, BASE)
check("落在中間時才放大（細描邊那個案例就是 80→93、CER 4.4%→1.1%）",
      worth and why == "", f"{worth} {why!r}")
worth, _ = oe.upscale_worthwhile(65.0, BASE)
check("彩色場景那個案例（69）同樣落在中間", worth)
check("門檻可以由設定調整（不是寫死的）",
      oe.upscale_worthwhile(80.0, oe.resolve_ocrengine_settings(
          {"ocrengine": {"good_enough_conf": 70}}))[0] is False)


# ===== 3. 面積上限 ======================================================

check("小塊框選允許放大", oe.upscale_allowed((600, 120), 3, BASE))
check("整個 1080p 畫面不放大（放大後 1866 萬像素）",
      not oe.upscale_allowed((1920, 1080), 3, BASE))
check("倍率為 1 時永遠允許（那是不放大）",
      oe.upscale_allowed((9999, 9999), 1, BASE))
check("尺寸量不到時保守地不放大（寧可少一個模式，也不要讓人等）",
      not oe.upscale_allowed(None, 3, BASE))


# ===== 4. TSV 解析 ======================================================

TSV = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\t"
    "width\theight\tconf\ttext\n"
    "5\t1\t1\t1\t1\t1\t62\t40\t120\t27\t96.33\tGraphics\n"
    "5\t1\t1\t1\t1\t2\t194\t40\t112\t27\t95.10\tSettings\n"
    "4\t1\t1\t1\t1\t0\t62\t40\t840\t27\t-1\t\n"
    "5\t1\t1\t1\t2\t1\t63\t96\t141\t27\t-1\tdropped\n"
)
boxes = oe.parse_tsv(TSV)
check("TSV 只留下真的有字的列", len(boxes) == 2, str(len(boxes)))
check("TSV 的座標與信心值有被讀出來",
      boxes[0]["text"] == "Graphics" and boxes[0]["left"] == 62
      and boxes[0]["conf"] == 96.3, str(boxes[0]))
check("conf 為 -1 的列被丟掉（那是 tesseract 的層級列，不是字）",
      all(b["conf"] >= 0 for b in boxes))
check("空 TSV 不會爆掉", oe.parse_tsv("") == [])
check("壞掉的 TSV 不會拋例外",
      oe.parse_tsv("level\tleft\ttext\nx\ty\tz\n") == [])
# parse_tsv 會把信心值四捨五入到小數一位（96.33→96.3、95.10→95.1），
# 所以平均是 95.7 而不是原始值的 95.715。
check("平均信心算得對", abs(oe.mean_conf(boxes) - 95.7) < 0.01,
      str(oe.mean_conf(boxes)))
check("沒有字塊時平均信心是 0，不是除以零", oe.mean_conf([]) == 0.0)


# ===== 5. 放大後的座標要換算回原圖 ======================================

scaled = [{"text": "A", "left": 300, "top": 150, "width": 60, "height": 90,
           "conf": 90.0}]
back = oe.rescale_boxes(scaled, 3)
check("放大 3 倍的座標除得回原圖",
      back[0]["left"] == 100 and back[0]["top"] == 50
      and back[0]["width"] == 20 and back[0]["height"] == 30, str(back[0]))
check("倍率 1 時原樣不動", oe.rescale_boxes(scaled, 1)[0]["left"] == 300)
check("換算不會動到文字與信心值",
      back[0]["text"] == "A" and back[0]["conf"] == 90.0)


# ===== 6. 挑選 ==========================================================

attempts = [
    {"mode": "psm3", "boxes": [{"text": "a"}], "mean_conf": 74.2},
    {"mode": "psm6", "boxes": [{"text": "b"}], "mean_conf": 83.0},
    {"mode": "psm6_x3", "boxes": [{"text": "c"}], "mean_conf": 56.3},
]
check("挑信心值最高的那個模式（亮底描邊字實測就是 psm6 勝出）",
      oe.pick_best(attempts)["mode"] == "psm6")
# 這一條原本寫成「空結果 mean_conf=0 vs 有字的 30」，但那是**空過的測
# 試**：空結果本來就算 0 分，`max` 自己就會選有字的那個，拿掉過濾條件照
# 樣通過。改成給空結果一個高分——守的是「有字才算數，信心值再高也一
# 樣」，而不是「0 分比較低」。
check("沒讀到字的模式不列入，信心值再高也一樣",
      oe.pick_best([{"mode": "empty", "boxes": [], "mean_conf": 99.0},
                    {"mode": "psm6", "boxes": [{"text": "x"}],
                     "mean_conf": 30.0}])["mode"] == "psm6")
check("全部都沒讀到字時回傳 None", oe.pick_best(
    [{"mode": "a", "boxes": [], "mean_conf": 0.0}]) is None)
check("完全沒有嘗試時也回傳 None", oe.pick_best([]) is None)

described = oe.describe_attempts([
    {"mode": "psm3", "skipped": "", "mean_conf": 96.0, "seconds": 0.216},
    {"mode": "psm6_x3", "skipped": "前面的模式已經夠準", "mean_conf": 0.0,
     "seconds": 0.0},
])
check("說明文字寫得出被跳過的原因（不然使用者只覺得有時快有時慢）",
      "略過" in described and "夠準" in described, described)


# ===== 7. 圖片尺寸：只讀檔頭，零第三方依賴 ==============================

with tempfile.TemporaryDirectory() as tmp:
    import struct
    import zlib

    png = os.path.join(tmp, "a.png")
    ihdr = struct.pack(">II", 1280, 200) + bytes([8, 2, 0, 0, 0])
    chunk = b"IHDR" + ihdr
    with open(png, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(struct.pack(">I", len(ihdr)) + chunk
                 + struct.pack(">I", zlib.crc32(chunk)))
    check("讀得出 PNG 的尺寸", oe.image_size(png) == (1280, 200),
          str(oe.image_size(png)))

    bmp = os.path.join(tmp, "a.bmp")
    with open(bmp, "wb") as fh:
        fh.write(b"BM" + b"\0" * 16 + struct.pack("<ii", 640, -480))
    check("讀得出 BMP 的尺寸（高度為負代表由上而下，取絕對值）",
          oe.image_size(bmp) == (640, 480), str(oe.image_size(bmp)))

    junk = os.path.join(tmp, "a.txt")
    with open(junk, "w") as fh:
        fh.write("not an image")
    check("認不出來時回傳 None，不是拋例外", oe.image_size(junk) is None)
    check("檔案不存在時回傳 None",
          oe.image_size(os.path.join(tmp, "nope.png")) is None)


# ===== 8. 語言 ==========================================================

check("問得出缺哪幾個語言",
      oe.missing_languages("eng+jpn", installed={"eng"}) == ["jpn"])
check("全都裝好時回空清單",
      oe.missing_languages("eng", installed={"eng", "jpn"}) == [])
check("空字串不會變成一個假的語言代碼",
      oe.missing_languages("", installed={"eng"}) == [])


# ===== 9. 引擎不在時要講得出下一步 ======================================

_real_which = shutil.which
_real_candidates = oe.install_candidates
try:
    shutil.which = lambda name: None
    oe.install_candidates = lambda: []
    check("找不到引擎時回報不可用", not oe.tesseract_available())
    check("問語言時回空集合，不是拋例外", oe.available_languages() == set())
    try:
        oe.recognize("/tmp/whatever.png")
        check("找不到引擎時要丟 OcrError", False, "沒有丟例外")
    except oe.OcrError as exc:
        check("找不到引擎時丟的是 OcrError", True)
        check("訊息講得出下一步（一鍵安裝／加入 PATH），不是技術錯誤碼",
              "安裝" in str(exc) and "PATH" in str(exc), str(exc))
    except Exception as exc:  # noqa: BLE001 - 這裡就是要抓「丟錯型別」
        check("找不到引擎時丟的是 OcrError", False, repr(exc))
finally:
    shutil.which = _real_which
    oe.install_candidates = _real_candidates


# ===== 10. 實跑（要有 tesseract 與 ffmpeg）==============================

if not oe.tesseract_available():
    print("SKIP 實跑段：這個環境沒有 tesseract"
          "（apt-get install -y tesseract-ocr tesseract-ocr-eng）")
elif not shutil.which("ffmpeg"):
    print("SKIP 實跑段：這個環境沒有 ffmpeg")
else:
    FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    if not os.path.isfile(FONT):
        print("SKIP 實跑段：找不到合成測資要用的字型")
    else:
        LINE = "The gate will not open until you find the three seals."
        with tempfile.TemporaryDirectory() as tmp:
            clean = os.path.join(tmp, "clean.png")
            noise = os.path.join(tmp, "noise.png")
            text = LINE.replace(":", r"\:").replace("'", r"\'")
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "lavfi", "-i",
                 f"color=c=white:s=1100x120,drawtext=fontfile={FONT}:"
                 f"text='{text}':fontsize=32:fontcolor=black:x=20:y=40",
                 "-frames:v", "1", clean], check=True, timeout=90)
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "lavfi", "-i",
                 "nullsrc=s=1100x120,geq=random(1)*255:128:128,format=rgb24",
                 "-frames:v", "1", noise], check=True, timeout=90)

            got = oe.recognize_text(clean, lang="eng")
            check("實跑：乾淨畫面一字不差",
                  got["text"].strip() == LINE, repr(got["text"]))
            check("實跑：乾淨畫面判定為可用", got["verdict"] == "ok",
                  got["verdict"])
            skipped = [a for a in got["attempts"] if a.get("skipped")]
            check("實跑：乾淨畫面不必花時間放大重跑（省下約 0.4 秒）",
                  any("夠準" in a["skipped"] for a in skipped),
                  oe.describe_attempts(got["attempts"]))

            bad = oe.recognize_text(noise, lang="eng")
            check("實跑：畫面上沒有字時判定為讀不到",
                  bad["verdict"] == "unreadable",
                  f"{bad['verdict']} conf={bad['mean_conf']:.1f}")
            check("實跑：判定讀不到時不會把亂碼當正文送出去",
                  bad["text"] == "", repr(bad["text"][:60]))
            skipped = [a for a in bad["attempts"] if a.get("skipped")]
            check("實跑：沒有字的畫面不浪費時間放大（實測省下 6.8 秒）",
                  any("讀不到" in a["skipped"] for a in skipped),
                  oe.describe_attempts(bad["attempts"]))

            try:
                oe.recognize(os.path.join(tmp, "missing.png"))
                check("實跑：圖片不存在時要丟 OcrError", False, "沒有丟例外")
            except oe.OcrError as exc:
                check("實跑：圖片不存在時丟 OcrError 並指出是哪個檔",
                      "找不到" in str(exc), str(exc))


print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("subtitle/ocrengine.py 測試全數通過。")
