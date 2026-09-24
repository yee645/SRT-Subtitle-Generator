# -*- coding: utf-8 -*-
"""
`subtitle/screentranslate.py` 測試：辨識完之後送、等、還是擋。

ROADMAP 第 9 項第一階段第 5 項（介面）底下的流程層。守住五件事：

  1. **預設不自動送出**——辨識結果要先顯示（調研文件第 4 節）。
  2. **讀不到字絕不送出。**
  3. **像密碼的內容絕不送出**，但也**不能把普通句子誤判成密碼**——
     逐詞套 `clipwatch.looks_like_secret` 會把 iPhone15Pro 這種詞判成金
     鑰、整段擋掉（實測過，所以寫成測資）。
  4. **使用者改過原文再按翻譯時要再檢查一次**——原文框是可以改的。
  5. **截圖用完一定刪**，成功、失敗都一樣。

辨識那一段用**真的 tesseract** 跑一張現做的圖（容器裡有裝才跑；沒裝就
照實報「略過」，不假裝通過）。
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import screentranslate as st

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def guarded(name, fn):
    """區塊內丟例外就記成失敗、繼續往下跑（不讓整檔中止）。"""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        check(name + "（區塊內丟出例外）", False, f"{type(exc).__name__}: {exc}")


OK = {"text": "Select this line", "mean_conf": 96.4, "verdict": "ok"}
WEAK = {"text": "Se1ect th1s", "mean_conf": 55.0, "verdict": "weak"}
JUNK = {"text": "~!@ ;;", "mean_conf": 21.9, "verdict": "unreadable"}

# ===== 1. 設定 ==========================================================
check("預設不自動送出", st.resolve_screentranslate_settings(None)["auto_send_ok"] is False)
check("不認得的鍵被丟掉", "x" not in st.resolve_screentranslate_settings(
    {"screentranslate": {"x": 1, "auto_send_ok": 1}}))
auto = st.resolve_screentranslate_settings({"screentranslate": {"auto_send_ok": True}})

# ===== 2. 送、等、擋 ====================================================
d = st.decide(OK)
check("清楚的結果預設是『等』不是『送』", d["action"] == st.ACTION_HOLD, d)
check("等的時候告訴使用者要按哪個鈕", "翻譯辨識結果" in d["message"], d["message"])
d = st.decide(OK, auto)
check("使用者打開自動送出，清楚的結果才直接送", d["action"] == st.ACTION_SEND, d)
d = st.decide(WEAK, auto)
check("就算開了自動送出，信心偏低的也要等", d["action"] == st.ACTION_HOLD, d)
check("信心偏低時講出可能有錯字、原文可改", "錯字" in d["message"]
      and "修改" in d["message"], d["message"])
for settings in (None, auto):
    d = st.decide(JUNK, settings)
    check(f"讀不到字絕不送出（auto={bool(settings)}）",
          d["action"] == st.ACTION_BLOCK and d["reason"] == st.BLOCK_UNREADABLE, d)
d = st.decide({"text": "  ", "mean_conf": 90, "verdict": "ok"}, auto)
check("空白結果不送出", d["action"] == st.ACTION_BLOCK and d["reason"] == st.BLOCK_EMPTY, d)
d = st.decide({"text": "API Key\nsk-abcdef1234567890XYZ", "mean_conf": 95,
               "verdict": "ok"}, auto)
check("像金鑰的內容就算開了自動送出也擋",
      d["action"] == st.ACTION_BLOCK and d["reason"] == st.BLOCK_SECRET, d)
check("被擋下來的文字照樣給（本機朗讀、複製用）",
      d["text"].startswith("API Key"), d["text"])
check("被擋下來時講出朗讀複製仍可用", "朗讀" in d["message"], d["message"])
check("每一種結果都有話講",
      all(st.decide(r, s)["message"] for r in (OK, WEAK, JUNK) for s in (None, auto)))

# ===== 3. 像不像密碼：兩個方向都要對 =====================================
secret = [
    "API Key\nsk-abcdef1234567890XYZ",
    "Password: hunter2",
    "密碼：abc123",
    "PIN: 1234",
    "OTP=839201",
    "Your token is ghp_abcdefghijklmnop1234",
    "Session a8f3k2j9d8s7f6g5h4j3k2l1 expired",
    "Password123!",
]
normal = [
    "The new iPhone15Pro is great",
    "COVID-19 cases rose in 2020",
    "Export at 1080p60fps for Windows11",
    "Enter your password below",
    "Spin: 3 times",
    "Tokens: many words here",
    "Hello world",
    "設定 → 帳號 → 變更密碼",
]
for text in secret:
    check(f"判成密碼：{text!r}", st.is_secret(text))
for text in normal:
    check(f"普通句子不能判成密碼：{text!r}", not st.is_secret(text))

ok, why = st.may_send("Password: hunter2")
check("使用者改過原文、貼了密碼再按翻譯：擋", not ok and "密碼" in why, why)
ok, why = st.may_send("Select this line")
check("正常原文可以送", ok and why == "")
check("空的原文不送", not st.may_send("   ")[0])

# ===== 4. 朗讀猜語言 =====================================================
for text, lang in (("日本語のテキスト", "ja"), ("漢字だけではない", "ja"),
                   ("안녕하세요", "ko"), ("這是中文", "zh-TW"),
                   ("Hello there", "en"), ("12345 !!", None),
                   ("中文裡夾 Premiere Pro", "zh-TW")):
    check(f"猜語言 {text!r} → {lang}", st.guess_speech_lang(text) == lang,
          st.guess_speech_lang(text))

# ===== 5. 截圖用完一定刪 =================================================
workdir = tempfile.mkdtemp(prefix="st_test_")
seen = {}


def fake_capture(region, path, config=None, bounds=None):
    seen["path"] = path
    with open(path, "wb") as fh:
        fh.write(b"BM" + b"\0" * 100)


def fake_recognize(path, config=None):
    seen["existed_during_ocr"] = os.path.isfile(path)
    return dict(OK, seconds=0.2)


def _block_cleanup_ok():
    result = st.capture_and_recognize((1, 2, 30, 40), workdir=workdir,
                                      capture=fake_capture, recognize=fake_recognize)
    check("辨識時圖還在", seen.get("existed_during_ocr") is True)
    check("辨識完圖就刪掉了", not os.path.exists(seen["path"]), seen.get("path"))
    check("回傳實際擷取的範圍", result["region"] == (1, 2, 30, 40), result.get("region"))
    check("暫存資料夾裡沒留下任何東西", os.listdir(workdir) == [], os.listdir(workdir))


def _block_cleanup_fail():
    def boom(path, config=None):
        raise RuntimeError("OCR 掛了")
    try:
        st.capture_and_recognize((0, 0, 10, 10), workdir=workdir,
                                 capture=fake_capture, recognize=boom)
        check("辨識失敗要往上拋", False)
    except RuntimeError:
        check("辨識失敗要往上拋", True)
    check("辨識失敗時圖也刪掉了", os.listdir(workdir) == [], os.listdir(workdir))

    def capture_boom(region, path, config=None, bounds=None):
        with open(path, "wb") as fh:
            fh.write(b"partial")
        raise RuntimeError("擷取到一半失敗")
    try:
        st.capture_and_recognize((0, 0, 10, 10), workdir=workdir,
                                 capture=capture_boom, recognize=fake_recognize)
    except RuntimeError:
        pass
    check("擷取到一半失敗，半個檔也刪掉了", os.listdir(workdir) == [], os.listdir(workdir))


guarded("截圖用完就刪", _block_cleanup_ok)
guarded("失敗時也刪", _block_cleanup_fail)

# ===== 6. 真的 tesseract：現做一張圖 → 辨識 → 決定 ========================


def _block_real_ocr():
    if not (shutil.which("tesseract") and shutil.which("convert")):
        print("SKIP 真實辨識（容器裡沒有 tesseract 或 ImageMagick）")
        return
    src = os.path.join(workdir, "src.png")
    subprocess.run(["convert", "-size", "560x90", "xc:white", "-fill", "black",
                    "-pointsize", "36", "-annotate", "+20+60",
                    "Select this line to translate", src], check=True)

    def copy_capture(region, path, config=None, bounds=None):
        shutil.copyfile(src, path)

    result = st.capture_and_recognize((0, 0, 560, 90), workdir=workdir,
                                      capture=copy_capture)
    check("真實辨識讀出原句", result["text"].strip() == "Select this line to translate",
          repr(result["text"]))
    d = st.decide(result)
    check("真實辨識的結果預設等使用者確認", d["action"] == st.ACTION_HOLD, d)
    check("狀態列有秒數", "秒" in st.format_status(result, d), st.format_status(result, d))
    left = [n for n in os.listdir(workdir) if n.startswith("srtgen_screen_")]
    check("真實辨識完也沒留下截圖", left == [], left)


guarded("真實辨識", _block_real_ocr)
shutil.rmtree(workdir, ignore_errors=True)

print()
if failures:
    print(f"{len(failures)} 項失敗")
    sys.exit(1)
print("全部通過")
