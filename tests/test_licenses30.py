# -*- coding: utf-8 -*-
"""
3.0 之後 A-2：第三方授權說明（LGPL 原文核對，第 0 項最後一件容器做得到的事）。

2026-11-25 拿 `packaging/licenses/` 的三份全文跟 PyPI 上另外三個套件附的 FSF 原文逐位元組比對
（GPL-3.0 ← ansible-core 2.17.5 的 COPYING、LGPL-3.0 ← psycopg 3.2.3、LGPL-2.1 ← chardet 5.2.0），
三份都一模一樣。再照條文本身逐條對 `THIRD_PARTY_NOTICES.txt`，補上缺的：

1. 全文**逐位元組**是 FSF 原文（md5 鎖住；以前只驗標題與長度）。
2. 說明的稱呼跟版本走：3.0.0 起是「新介面」，不再寫「預覽版」。
3. LGPL-3.0 §4、LGPL-2.1 §6：整個作品的條款不能限制「修改函式庫」與「為除錯這類修改而逆向工程」。
   本專案沒有 LICENSE 檔，所以說明裡要明寫允許。
4. GPL-3.0 §6(d)／LGPL-2.1 §4：散布函式庫的目的碼要讓人拿得到**對應的**原始碼——網址指向同一版；
   FFmpeg 的版本、授權、編譯設定從函式庫本身讀（`av_version_info` 等），讀不到才退回上層網址。
5. 讀版本是在另一個行程裡載入函式庫，載不起來、當掉都不能拖垮打包。
6. 網址在 CI 上實際連一次（開發容器連不到 download.qt.io／ffmpeg.org），不擋打包。
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "packaging"))

import qt_preview as qp  # noqa: E402
import updater  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fp:
        return fp.read()


# ----- 1. 全文逐位元組是 FSF 原文 -----
FSF_MD5 = {"GPL-3.0.txt": "1ebbd3e34237af26da5dc08a4e440464",
           "LGPL-3.0.txt": "3000208d539ec061b899bce1d9ce9404",
           "LGPL-2.1.txt": "4fbd65380cdd255951079008b364516c"}
for name, want in FSF_MD5.items():
    with open(os.path.join(ROOT, "packaging", "licenses", name), "rb") as fh:
        got = hashlib.md5(fh.read()).hexdigest()
    check(f"{name} 逐位元組是 FSF 原文（跟 PyPI 上另一份獨立的副本同一個 md5）", got == want, got)
check("打包附的就是這三份", set(qp.LICENSE_FILES) == set(FSF_MD5))

# ----- 2～4. 說明的內容 -----
FF = {"version": "7.1.2", "license": "LGPL version 2.1 or later", "release": True,
      "configuration": "--disable-programs --enable-shared --disable-static"}
tmp = tempfile.mkdtemp(prefix="lic30_")
dist = os.path.join(tmp, "SRT-Subtitle-Generator-Qt")
os.makedirs(os.path.join(dist, "_internal", "PySide6"))
for name in ("avcodec-61.dll", "avutil-59.dll", "swresample-5.dll"):
    open(os.path.join(dist, "_internal", "PySide6", name), "w").close()
got = qp.add_licenses(dist, FF)
check("licenses/ 放了三份全文＋第三方說明", got == sorted(list(FSF_MD5) + ["THIRD_PARTY_NOTICES.txt"]), str(got))
with open(os.path.join(dist, "licenses", "THIRD_PARTY_NOTICES.txt"), encoding="utf-8") as fh:
    notice = fh.read()

check("APP_VERSION 3.0.0 起說明寫「新介面」、不再寫預覽版",
      updater.APP_VERSION.startswith("3.") and "3.0 新介面" in notice and "預覽版" not in notice, notice[:120])
check("寫明本程式的版本與原始碼（GitHub、同一個 tag）",
      f"v{updater.APP_VERSION}" in notice and f"{qp.REPO_URL}（tag v{updater.APP_VERSION}）" in notice)
check("LGPL 要求的權利寫明了：可以修改函式庫、換 DLL、為除錯而逆向工程（LGPL-3.0 §4、LGPL-2.1 §6）",
      all(w in notice for w in ("修改上列函式庫", "換成你自己修改過", "逆向工程", "不限制這些事",
                                "LGPL-3.0 第 4 節", "LGPL-2.1 第 6 節")))
check("FFmpeg：版本、函式庫自報的授權、編譯設定都寫進去",
      "FFmpeg 7.1.2" in notice and "函式庫自報：LGPL version 2.1 or later" in notice
      and f"編譯設定（函式庫自報）：{FF['configuration']}" in notice)
check("FFmpeg 原始碼指向同一版的原始碼包", "原始碼（同一版）：https://ffmpeg.org/releases/ffmpeg-7.1.2.tar.xz" in notice)
check("實際打包的 FFmpeg 檔名都列出來", all(n in notice for n in ("avcodec-61.dll", "avutil-59.dll", "swresample-5.dll")))
check("三份全文都點名、說 GPL-3.0 為什麼一起附", all(n in notice for n in FSF_MD5) and "必須一起附" in notice)
check("PySide6、Qt、FFmpeg 三個元件與授權都在",
      all(w in notice for w in ("PySide6", "Qt 6 函式庫", "LGPL-3.0-only", "LGPL-2.1-or-later")))

u = qp.source_urls("6.12.0", "6.12.0", FF)
check("PySide6 原始碼：同一版的資料夾",
      u["pyside"] == "https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/", u["pyside"])
check("Qt 原始碼：同一版的資料夾，另附舊版會搬去的 archive",
      u["qt"] == "https://download.qt.io/official_releases/qt/6.12/6.12.0/"
      and u["qt_archive"] == "https://download.qt.io/archive/qt/6.12/6.12.0/", str(u))
u2 = qp.source_urls("（未安裝）", None, {"version": "n7.1-23-gabc", "release": False})
check("版本讀不到或不是正式版號：退回上層網址、不組出不存在的網址",
      u2 == {"pyside": "https://download.qt.io/official_releases/QtForPython/",
             "qt": "https://download.qt.io/official_releases/qt/",
             "ffmpeg": "https://ffmpeg.org/download.html"}, str(u2))
plain = qp.notices_text(dist, {"release": False})
check("讀不到 FFmpeg 版本：照實寫讀不到、不寫編譯設定、網址退回下載頁",
      "FFmpeg （讀不到版本）" in plain and "編譯設定" not in plain and "https://ffmpeg.org/download.html" in plain)

# ----- 5. 從函式庫本身讀版本 -----
empty = os.path.join(tmp, "empty")
os.makedirs(empty)
check("沒有 FFmpeg 函式庫：回傳空的", qp.ffmpeg_info(empty) == {})
info = qp.ffmpeg_info(dist)  # 空檔案冒充的 DLL：載不起來
check("函式庫載不起來：不丟例外、標成讀不到，原因與檔案記進報告（說明裡不寫）",
      info.get("release") is False and "version" not in info and info.get("error", "").startswith("結束碼")
      and info.get("lib", "").replace("\\", "/") == "_internal/PySide6/avutil-59.dll"
      and info["error"] not in qp.notices_text(dist, info), str(info))

cc = shutil.which("cc") or shutil.which("gcc")
if not cc or os.name == "nt":
    print("SKIP 編假的 avutil／avcodec 共享函式庫（沒有 C 編譯器）")
else:
    lib = os.path.join(tmp, "lib")
    os.makedirs(lib)
    src = os.path.join(tmp, "fake.c")
    with open(src, "w") as fh:
        fh.write('const char *av_version_info(void){return "7.1.2";}\n'
                 'const char *avutil_license(void){return "LGPL version 2.1 or later";}\n'
                 'const char *avcodec_configuration(void){return "--enable-shared --disable-gpl";}\n')
    subprocess.run([cc, "-shared", "-fPIC", "-o", os.path.join(lib, "libavutil.so.59"), src], check=True)
    real = qp.ffmpeg_info(lib)
    check("真的載入函式庫讀版本：avutil 讀得到、avcodec 不在也不影響版本",
          real == {"version": "7.1.2", "license": "LGPL version 2.1 or later", "release": True}, str(real))
    subprocess.run([cc, "-shared", "-fPIC", "-o", os.path.join(lib, "libavcodec.so.61"), src], check=True)
    real = qp.ffmpeg_info(lib)
    check("avcodec 也在：連編譯設定一起讀", real.get("configuration") == "--enable-shared --disable-gpl"
          and real.get("version") == "7.1.2", str(real))
    with open(src, "w") as fh:
        fh.write('const char *av_version_info(void){return "N-112233-gdeadbeef";}\n'
                 'const char *avutil_license(void){return "LGPL version 2.1 or later";}\n')
    subprocess.run([cc, "-shared", "-fPIC", "-o", os.path.join(lib, "libavutil.so.59"), src], check=True)
    os.remove(os.path.join(lib, "libavcodec.so.61"))
    real = qp.ffmpeg_info(lib)
    check("從 git 編的版本（不是正式版號）：照實記版本、不當成可下載的正式版",
          real.get("version") == "N-112233-gdeadbeef" and real.get("release") is False, str(real))
    with open(src, "w") as fh:
        fh.write('#include <stdlib.h>\nconst char *av_version_info(void){abort();}\n'
                 'const char *avutil_license(void){return "x";}\n')
    subprocess.run([cc, "-shared", "-fPIC", "-o", os.path.join(lib, "libavutil.so.59"), src], check=True)
    crash = qp.ffmpeg_info(lib)
    check("函式庫一呼叫就當掉：打包照常、標成讀不到、記下結束碼",
          crash.get("release") is False and "version" not in crash and crash.get("error", "").startswith("結束碼"),
          str(crash))

# ----- 6. CI 上連一次網址 -----


class Resp:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_for(table):
    calls = []

    def opener(req, timeout=None):
        calls.append((req.get_method(), req.full_url))
        code = table[(req.get_method(), req.full_url)]
        if isinstance(code, Exception):
            raise code
        if code != 200:
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
        return Resp(200)
    return opener, calls


op, calls = opener_for({("HEAD", "https://a/"): 200,
                        ("HEAD", "https://b/"): 405, ("GET", "https://b/"): 200,
                        ("HEAD", "https://c/"): 404,
                        ("HEAD", "https://d/"): urllib.error.URLError("refused")})
res = qp.check_links({"a": "https://a/", "b": "https://b/", "c": "https://c/", "d": "https://d/"}, opener=op)
check("網址檢查：200 算通、不收 HEAD 的退回 GET、404 照實記、連不上記原因",
      res["a"] == 200 and res["b"] == 200 and res["c"] == 404 and str(res["d"]).startswith("連不上"), str(res))
check("404 不會再多打一次 GET", ("GET", "https://c/") not in calls)

wf = read(".github/workflows/qt-preview.yml")
step = wf.split("- name: Check third-party source links")[1].split("- name:")[0] if "Check third-party" in wf else ""
check("qt-preview 打包後檢查原始碼網址，網站一時不通不擋打包",
      "--check-links qt_preview_report.json" in step and "continue-on-error: true" in step)
check("網址檢查排在打出報告之後",
      wf.index("Slim, licenses, self-test, zip") < wf.index("Check third-party source links") if step else False)
src = read("packaging/qt_preview.py")
check("打包報告帶著 FFmpeg 版本與原始碼網址（網址檢查讀這份）",
      'report["ffmpeg"] = ffmpeg_info(dist)' in src and 'report["source_urls"]' in src)

# ----- ROADMAP -----
road = read("docs/ROADMAP_3.0.md")
check("ROADMAP 記下 LGPL 原文核對的結果與留給維護者決定的事",
      "### 3.0 之後 A-2" in road and "LICENSE" in road.split("### 3.0 之後 A-2")[1])

shutil.rmtree(tmp, ignore_errors=True)
print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("第三方授權說明測試全數通過。")
