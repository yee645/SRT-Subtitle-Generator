# -*- coding: utf-8 -*-
"""
`subtitle/screencap.py` 與 `gui/region_overlay.py` 測試。

ROADMAP 第 9 項第一階段的第 3 項（螢幕擷取與框選覆蓋層）。

**這一項比前兩項可驗證得多**：Linux 的擷取後端在 Xvfb 下是真的跑得起來
的，所以「框選 → 擷取 → 辨識」這一整條路在開發環境就走得完（實測：在畫
面上放一張有字的圖，拖一個框，最後真的辨識出那行字）。只有 Windows 的
`ctypes` GDI 那一段沒辦法。

守住五件事：

  1. **往哪個方向拖都要成立。** 由右下往左上拖是很自然的動作，沒處理就
     會得到負的寬高，後面每一步都錯。
  2. **回呼之前覆蓋層一定要先消失。** 順序反過來，擷取到的會是覆蓋層自
     己那層灰，而不是底下的畫面。
  3. **取消一定要留路，而且要回報。** 一個蓋住整個螢幕又關不掉的東西會
     把人嚇壞；靜靜取消則讓人以為程式當了。
  4. **抓到整塊同一個顏色要講出真正的原因**（全螢幕獨佔模式的遊戲），而
     不是丟一句「沒有讀到文字」。
  5. **太小與太大的框選要擋下來並說明**。
"""
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import screencap as sc

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


# ===== 1. 設定 ==========================================================

base = sc.resolve_screencap_settings(None)
check("沒有設定檔時取得預設值",
      base["min_region_px"] == sc.DEFAULT_SCREENCAP["min_region_px"])
check("設定檔的值會被讀進來",
      sc.resolve_screencap_settings(
          {"screencap": {"min_region_px": 20}})["min_region_px"] == 20)
check("離譜的值會被夾回合理範圍",
      sc.resolve_screencap_settings(
          {"screencap": {"min_region_px": 99999}})["min_region_px"] == 200)
check("不認得的鍵不會混進來",
      "nonsense" not in sc.resolve_screencap_settings(
          {"screencap": {"nonsense": 1}}))


# ===== 2. 框選範圍：四個方向都要成立 ====================================

check("由左上往右下拖",
      sc.normalize_region(10, 20, 110, 70) == (10, 20, 100, 50))
check("由右下往左上拖（最容易漏掉的那個方向）",
      sc.normalize_region(110, 70, 10, 20) == (10, 20, 100, 50))
check("由右上往左下拖",
      sc.normalize_region(110, 20, 10, 70) == (10, 20, 100, 50))
check("由左下往右上拖",
      sc.normalize_region(10, 70, 110, 20) == (10, 20, 100, 50))
check("點一下不拖會得到 0x0（交給 validate_region 去擋）",
      sc.normalize_region(50, 50, 50, 50) == (50, 50, 0, 0))

check("拖出螢幕右下角時會被夾回來",
      sc.clamp_region((1500, 900, 400, 300), (0, 0, 1600, 1000))
      == (1500, 900, 100, 100),
      str(sc.clamp_region((1500, 900, 400, 300), (0, 0, 1600, 1000))))
check("拖出螢幕左上角時也會被夾回來",
      sc.clamp_region((-50, -50, 200, 200), (0, 0, 1600, 1000))
      == (0, 0, 150, 150),
      str(sc.clamp_region((-50, -50, 200, 200), (0, 0, 1600, 1000))))
check("完全在螢幕內時不會被動到",
      sc.clamp_region((100, 100, 200, 80), (0, 0, 1600, 1000))
      == (100, 100, 200, 80))

try:
    sc.validate_region((0, 0, 3, 3))
    check("太小的框選要被擋", False, "沒有丟例外")
except sc.CaptureError as exc:
    check("太小的框選被擋下並說明怎麼做", "拖" in str(exc), str(exc))
try:
    sc.validate_region((0, 0, 9000, 9000))
    check("太大的框選要被擋", False, "沒有丟例外")
except sc.CaptureError as exc:
    check("太大的框選被擋下並說明理由", "慢" in str(exc), str(exc))
check("正常大小的框選通過", sc.validate_region((0, 0, 400, 120)))

check("高 DPI 換算：150% 縮放時座標乘上倍率",
      sc.scale_region((100, 200, 300, 80), 1.5) == (150, 300, 450, 120),
      str(sc.scale_region((100, 200, 300, 80), 1.5)))
check("倍率為 1 時不動", sc.scale_region((10, 20, 30, 40), 1)
      == (10, 20, 30, 40))

# dpi_factor：實際像素寬度／本程式看到的寬度。
check("125% 縮放：2400／1920 → 1.25", sc.dpi_factor(2400, 1920) == 1.25,
      str(sc.dpi_factor(2400, 1920)))
check("150% 縮放：2880／1920 → 1.5", sc.dpi_factor(2880, 1920) == 1.5)
check("沒縮放（或本程式已宣告支援高 DPI）：倍率 1", sc.dpi_factor(1920, 1920) == 1.0)
for bad in ((0, 1920), (1920, 0), (None, 1920), ("x", 1), (1000, 1920),
            (99999, 1920)):
    check(f"讀值不合理 {bad} 時不換算（換錯比不換更糟）",
          sc.dpi_factor(*bad) == 1.0, str(sc.dpi_factor(*bad)))


# Windows 擷取那一段在 Linux 上跑不起來，但可以換掉 `ctypes.WinDLL`，驗
# 「框選座標有沒有真的乘上倍率才交給 BitBlt」——只測 dpi_factor 算式的
# 話，呼叫端忘了用它照樣全數通過。
def fake_windows_capture(physical, logical, region):
    import ctypes
    calls = {}

    class Lib:
        def __getattr__(self, name):
            def fn(*args):
                calls.setdefault(name, []).append(args)
                if name == "GetDeviceCaps":
                    return {118: physical, 8: logical}[args[1]]
                return 1
            return fn

    had = hasattr(ctypes, "WinDLL")
    real = getattr(ctypes, "WinDLL", None)
    ctypes.WinDLL = lambda *a, **k: Lib()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            sc._capture_windows(region, os.path.join(tmp, "win.bmp"))
    finally:
        if had:
            ctypes.WinDLL = real
        else:
            del ctypes.WinDLL
    return calls


try:
    calls = fake_windows_capture(2400, 1920, (100, 200, 400, 120))
    blt = calls["BitBlt"][0]
    check("125% 縮放時 BitBlt 拿到的是換算後的實際像素座標",
          blt[6:8] == (125, 250), str(blt))
    check("125% 縮放時擷取的寬高也跟著換算",
          blt[3:5] == (500, 150) and calls["CreateCompatibleBitmap"][0][1:] == (500, 150),
          f"{blt} {calls['CreateCompatibleBitmap']}")
    calls = fake_windows_capture(1920, 1920, (100, 200, 400, 120))
    check("沒縮放時座標原封不動", calls["BitBlt"][0][6:8] == (100, 200),
          str(calls["BitBlt"][0]))
    check("用完一定還回螢幕 DC", "ReleaseDC" in calls)
except Exception as exc:  # noqa: BLE001
    check("假 WinDLL 下的 Windows 擷取（區塊內丟出例外）", False,
          f"{type(exc).__name__}: {exc}")


# ===== 3. BMP：寫得出也讀得回 ===========================================

with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "solid.bmp")
    rows = [bytes([10, 20, 30] * 17) for _ in range(9)]
    sc.write_bmp(path, 17, 9, rows)
    check("寫出來的 BMP 檔頭認得出尺寸（ocrengine 也是靠這個）",
          __import__("subtitle.ocrengine", fromlist=["x"]).image_size(path)
          == (17, 9))
    samples = sc.read_bmp_samples(path, step=1)
    check("讀得回像素，而且顏色就是寫進去的那個",
          samples and all(s == (10, 20, 30) for s in samples),
          str(samples[:2]))
    check("整塊同一個顏色會被判定為 flat", sc.looks_flat(path))

    mixed = os.path.join(tmp, "mixed.bmp")
    rows = [bytes(([10, 20, 30] * 8) + ([200, 210, 220] * 9)) for _ in range(9)]
    sc.write_bmp(mixed, 17, 9, rows)
    check("有明暗變化就不是 flat（不可以把正常畫面誤判成抓不到）",
          not sc.looks_flat(mixed))

    check("不是 BMP 的檔案讀不出樣本，也不會拋例外",
          sc.read_bmp_samples(os.path.join(tmp, "nope.bmp")) == [])
    check("讀不出樣本時不會誤判成 flat",
          not sc.looks_flat(os.path.join(tmp, "nope.bmp")))


# ===== 4. 後端 ==========================================================

name, available = sc.capture_backend()
check("認得出這個平台要走哪一條擷取路",
      name in ("windows-gdi", "macos-screencapture", "linux-x11"), name)
check("說明文字講得出可不可用",
      "可用" in sc.describe_backend(), sc.describe_backend())


# ===== 5. 實際擷取（Xvfb 下真的跑）======================================

def _have_display():
    return bool(os.environ.get("DISPLAY"))


if not _have_display():
    print("SKIP 實際擷取段：無 DISPLAY")
elif not os.path.isfile(FONT):
    print("SKIP 實際擷取段：找不到合成測資要用的字型")
else:
    import shutil

    if not (shutil.which("ffmpeg") and shutil.which("display")):
        print("SKIP 實際擷取段：缺 ffmpeg 或 ImageMagick 的 display")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            LINE = "Select this line"
            board = os.path.join(tmp, "board.png")
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "lavfi", "-i",
                 f"color=c=white:s=1200x700,drawtext=fontfile={FONT}:"
                 f"text='{LINE}':fontsize=44:fontcolor=black:x=120:y=200",
                 "-frames:v", "1", board], check=True, timeout=90)
            viewer = subprocess.Popen(
                ["display", "-geometry", "+0+0", "-window", "root", board])
            time.sleep(2)
            try:
                shot = os.path.join(tmp, "shot.bmp")
                # 這裡要用 try 包起來：擷取意外失敗時如果讓例外往上竄，
                # 整個檔案會在這裡中止，後面的斷言一條都不會跑——而輸出
                # 看起來只是「少了幾行」，不是「失敗」。（破壞探針就是這
                # 樣露出來的：flat 判定被弄壞之後只看到一個 FAIL，其實後
                # 面整段都沒執行。）
                try:
                    sc.capture_region((100, 180, 520, 90), shot)
                except sc.CaptureError as exc:
                    check("實際擷取：正常畫面不該被判定成擷取失敗",
                          False, str(exc))
                check("實際擷取：檔案真的產出來了",
                      os.path.isfile(shot) and os.path.getsize(shot) > 1000,
                      str(os.path.getsize(shot)) if os.path.isfile(shot) else "無檔案")

                from subtitle import ocrengine as oe
                check("實際擷取：尺寸就是框選的大小",
                      oe.image_size(shot) == (520, 90), str(oe.image_size(shot)))
                if os.path.isfile(shot) and oe.tesseract_available():
                    got = oe.recognize_text(shot, lang="eng")
                    check("實際擷取：辨識得出畫面上那行字（框選→擷取→辨識"
                          "整條路走得通）",
                          LINE in got["text"], repr(got["text"]))
                else:
                    print("SKIP 擷取後辨識：這個環境沒有 tesseract")
            finally:
                viewer.terminate()

            # 整塊純黑＝全螢幕獨佔模式的遊戲抓不到畫面時的樣子。
            black = os.path.join(tmp, "black.png")
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "lavfi", "-i", "color=c=black:s=1200x700",
                 "-frames:v", "1", black], check=True, timeout=90)
            viewer = subprocess.Popen(
                ["display", "-geometry", "+0+0", "-window", "root", black])
            time.sleep(2)
            try:
                try:
                    sc.capture_region((100, 100, 400, 200),
                                      os.path.join(tmp, "flat.bmp"))
                    check("抓到整塊同色時要報錯", False, "沒有丟例外")
                except sc.CaptureError as exc:
                    check("抓到整塊同色時講得出真正的原因（全螢幕獨佔模式），"
                          "而不是只說沒讀到文字",
                          "全螢幕" in str(exc) and "視窗化" in str(exc), str(exc))
            finally:
                viewer.terminate()


# ===== 6. 框選覆蓋層 ====================================================

if not _have_display():
    print("SKIP 覆蓋層段：無 DISPLAY")
else:
    import tkinter as tk

    try:
        from gui.region_overlay import RegionOverlay

        root = tk.Tk()
        root.geometry("200x80")
        root.update()

        # --- 拖曳 ---
        result = {}
        overlay = RegionOverlay(
            root, on_select=lambda r: result.setdefault("region", r),
            on_cancel=lambda: result.setdefault("cancel", True))
        for _ in range(20):
            root.update()
            time.sleep(0.02)
        check("覆蓋層蓋住整個螢幕",
              overlay.winfo_width() == root.winfo_screenwidth()
              and overlay.winfo_height() == root.winfo_screenheight(),
              f"{overlay.winfo_width()}x{overlay.winfo_height()}")

        canvas = overlay.canvas
        canvas.event_generate("<ButtonPress-1>", x=180, y=280,
                              rootx=180, rooty=280)
        for x in range(200, 720, 60):
            canvas.event_generate("<B1-Motion>", x=x, y=370, rootx=x, rooty=370)
            root.update()
        # 放開的那一刻：覆蓋層必須已經不在畫面上，回呼才會拿到底下的畫面。
        mapped_at_release = {}

        def _note(region):
            # 回呼跑到的時候，覆蓋層其實已經整個被 destroy 了——比「還在但
            # 沒顯示」更徹底，所以 winfo_ismapped() 會直接拋 TclError。那
            # 一樣滿足這條不變式（畫面上看不到它），不是失敗。
            try:
                mapped_at_release["mapped"] = bool(overlay.winfo_ismapped())
            except tk.TclError:
                mapped_at_release["mapped"] = False
            result["region"] = region

        overlay._on_select = _note
        canvas.event_generate("<ButtonRelease-1>", x=700, y=370,
                              rootx=700, rooty=370)
        end = time.time() + 1.5
        while time.time() < end:
            root.update()
            time.sleep(0.01)

        check("拖完拿得到框選範圍", result.get("region") == (180, 280, 520, 90),
              str(result.get("region")))
        check("回呼的時候覆蓋層已經消失了（順序反過來會擷取到覆蓋層自己"
              "那層灰）",
              mapped_at_release.get("mapped") is False,
              str(mapped_at_release))

        # --- Esc 取消 ---
        cancelled = {}
        overlay2 = RegionOverlay(root, on_select=lambda r: cancelled.setdefault(
            "region", r), on_cancel=lambda: cancelled.setdefault("cancel", True))
        for _ in range(10):
            root.update()
            time.sleep(0.02)
        overlay2.event_generate("<Escape>")
        for _ in range(10):
            root.update()
            time.sleep(0.02)
        check("按 Esc 會取消，而且有回報（靜靜取消讓人以為當了）",
              cancelled.get("cancel") is True and "region" not in cancelled,
              str(cancelled))
        check("取消之後覆蓋層真的被拆掉了（不可以留一層關不掉的東西）",
              not overlay2.winfo_exists())

        # --- 右鍵取消 ---
        cancelled2 = {}
        overlay3 = RegionOverlay(root, on_cancel=lambda: cancelled2.setdefault(
            "cancel", True))
        for _ in range(10):
            root.update()
            time.sleep(0.02)
        overlay3.canvas.event_generate("<ButtonPress-3>", x=10, y=10)
        for _ in range(10):
            root.update()
            time.sleep(0.02)
        check("按右鍵也可以取消（多一條路，少一次被困住）",
              cancelled2.get("cancel") is True, str(cancelled2))

        root.destroy()
    except tk.TclError as exc:
        message = str(exc).lower()
        if "display" in message or "connect" in message:
            print(f"SKIP 覆蓋層段（無顯示器：{exc}）")
        else:
            check("覆蓋層段沒有丟 TclError", False, str(exc))


print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("subtitle/screencap.py 測試全數通過。")
