# -*- coding: utf-8 -*-
"""
3.0 第 11 項第二十九階段：依勾選安裝文字辨識（subtitle/tesseract_setup.install_selected）。

下載本身在 test_tesseract_setup.py；這裡換掉 install_engine／install_languages，只驗順序、進度比例與失敗時的行為
（開發環境的出口網路擋官方發行頁，真的下載驗不到）。

1. 兩樣都勾：先裝引擎、再裝語言檔；進度引擎佔 0～0.8、語言檔佔 0.8～1.0；回傳兩個位置（照順序）。
2. 只勾引擎、只勾語言檔：各自佔滿 0～1。
3. 都沒勾：ValueError，什麼都不裝。
4. 引擎失敗：語言檔不裝、例外原樣往外丟。
5. 沒給 progress_cb 也能跑；語言清單照給的順序交下去。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import tesseract_setup as ts  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


calls = []


def fake_engine(progress_cb=None, timeout=900):
    calls.append(("engine",))
    for r in (0.0, 0.5, 1.0):
        if progress_cb:
            progress_cb(r, f"引擎 {r}")
    return "/裝好/引擎"


def fake_langs(langs, progress_cb=None, timeout=300):
    calls.append(("langs", list(langs)))
    for r in (0.0, 0.5, 1.0):
        if progress_cb:
            progress_cb(r, f"語言 {r}")
    return "/裝好/tessdata"


real_engine, real_langs = ts.install_engine, ts.install_languages
ts.install_engine, ts.install_languages = fake_engine, fake_langs
try:
    # ----- 1 -----
    seen = []
    done = ts.install_selected(True, ["jpn", "eng"], progress_cb=lambda r, m: seen.append((round(r, 3), m)))
    check("兩樣都勾：先引擎再語言檔、語言照給的順序", calls == [("engine",), ("langs", ["jpn", "eng"])], str(calls))
    check("回傳兩個位置（照安裝順序）", done == ["/裝好/引擎", "/裝好/tessdata"])
    check("進度：引擎 0～0.8、語言檔 0.8～1.0，訊息原樣",
          seen == [(0.0, "引擎 0.0"), (0.4, "引擎 0.5"), (0.8, "引擎 1.0"),
                   (0.8, "語言 0.0"), (0.9, "語言 0.5"), (1.0, "語言 1.0")], str(seen))

    # ----- 2 -----
    calls.clear()
    seen = []
    done = ts.install_selected(True, [], progress_cb=lambda r, m: seen.append(round(r, 3)))
    check("只勾引擎：只裝引擎、進度佔滿", calls == [("engine",)] and done == ["/裝好/引擎"]
          and seen == [0.0, 0.5, 1.0], str(seen))
    calls.clear()
    seen = []
    done = ts.install_selected(False, ("chi_tra",), progress_cb=lambda r, m: seen.append(round(r, 3)))
    check("只勾語言檔：只裝語言檔、進度佔滿", calls == [("langs", ["chi_tra"])] and done == ["/裝好/tessdata"]
          and seen == [0.0, 0.5, 1.0], str(seen))

    # ----- 3 -----
    calls.clear()
    try:
        ts.install_selected(False, [])
        raised = False
    except ValueError as exc:
        raised = str(exc) == "請至少勾選一項要安裝的東西。"
    check("都沒勾：ValueError（講要勾一項）、什麼都不裝", raised and calls == [])
    try:
        ts.install_selected(False, None)
        raised = False
    except ValueError:
        raised = True
    check("語言給 None 也當沒勾", raised and calls == [])

    # ----- 4 -----
    def broken_engine(progress_cb=None, timeout=900):
        calls.append(("engine",))
        raise ts.SetupError("自動安裝目前只支援 Windows。")
    ts.install_engine = broken_engine
    calls.clear()
    try:
        ts.install_selected(True, ["eng"])
        caught = None
    except ts.SetupError as exc:
        caught = exc
    check("引擎失敗：例外原樣往外丟、語言檔不裝", caught is not None and str(caught) == "自動安裝目前只支援 Windows。"
          and calls == [("engine",)])

    # ----- 5 -----
    ts.install_engine = fake_engine
    calls.clear()
    check("沒給 progress_cb 也能跑", ts.install_selected(True, ["eng"]) == ["/裝好/引擎", "/裝好/tessdata"])
finally:
    ts.install_engine, ts.install_languages = real_engine, real_langs

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("依勾選安裝文字辨識的測試全數通過。")
