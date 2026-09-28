# -*- coding: utf-8 -*-
"""
配樂庫收集器（bgm_collector/collect_bgm.py）測試。

不連網：Openverse API 與音檔下載都換成替身，回傳的欄位照 Openverse 原始碼
（api/serializers/audio_serializers.py、Jamendo 匯入腳本）的真實格式寫。
"""
import csv
import email.message
import io
import json
import os
import sys
import tempfile
import urllib.error

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "bgm_collector"))

import collect_bgm as cb  # noqa: E402

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def track(ident, title, license="by", tags=(), genres=(), duration=180000,
          filetype="mp32", creator="Artist", version="3.0"):
    """一筆 Openverse 音訊搜尋結果（Jamendo 來源的真實欄位）。"""
    return {
        "id": ident, "title": title, "creator": creator,
        "creator_url": f"https://www.jamendo.com/artist/1/{creator}",
        "foreign_landing_url": f"https://www.jamendo.com/track/{ident}",
        "url": f"https://prod-1.storage.jamendo.com/?trackid={ident}&format=mp32",
        "license": license, "license_version": version,
        "license_url": f"https://creativecommons.org/licenses/{license}/{version}/",
        "provider": "jamendo", "source": "jamendo", "category": "music",
        "filetype": filetype, "genres": list(genres),
        "tags": [{"name": t, "accuracy": None, "unstable__provider": "jamendo"}
                 for t in tags],
        "duration": duration, "mature": False,
    }


class FakeHttp:
    def __init__(self, pages, fail_urls=(), errors=None):
        self.pages = pages            # 搜尋標籤的第一個字 → 各頁結果
        self.calls = []
        self.downloads = []
        self.fail_urls = set(fail_urls)
        self.errors = list(errors or [])

    def get_json(self, url, params=None):
        self.calls.append(dict(params or {}))
        if self.errors:
            raise self.errors.pop(0)
        pages = self.pages.get(params["tags"].split()[0], [])
        page = params["page"]
        results = pages[page - 1] if page <= len(pages) else []
        return {"result_count": sum(map(len, pages)), "page_count": len(pages),
                "page_size": 20, "page": page, "results": results}

    def download(self, url, dest):
        self.downloads.append(url)
        if url in self.fail_urls:
            raise urllib.error.URLError("connection reset")
        with open(dest, "wb") as handle:
            handle.write(b"\xff\xfb" * 20000)
        return 40000


def http_error(code, retry_after=None):
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError("https://api.openverse.org/v1/audio/", code,
                                  "err", headers, io.BytesIO(b"{}"))


OPTIONS = {"licenses": cb.ALL_USABLE_LICENSES, "per_mood": 3, "min_sec": 30,
           "max_sec": 600, "allow_vocal": False, "allow_ogg": False, "sources": []}
NO_SLEEP = lambda seconds: None  # noqa: E731
QUIET = lambda *a, **k: None  # noqa: E731


# ---- 分類 ----------------------------------------------------------------

moods = cb.classify_moods(
    tags=["instrumental", "speed_medium", "piano", "relaxing", "calm", "romantic"],
    genres=["lounge", "easylistening"], title="Evening Tea")
check("情緒標籤決定主情境（放鬆療癒）", moods[0] == "放鬆療癒", moods)
check("第二個情境有標籤命中才列（浪漫甜蜜）", moods == ["放鬆療癒", "浪漫甜蜜"], moods)
check("曲風決定風格（lounge → LoFi輕音）",
      cb.classify_style(["piano"], ["lounge", "easylistening"], "") == "LoFi輕音")
check("曲風權重高於樂器標籤（hiphop 勝過 piano）",
      cb.classify_style(["piano"], ["hiphop"], "") == "嘻哈")
check("沒有曲風時看樂器標籤（piano → 古典鋼琴）",
      cb.classify_style(["piano"], [], "") == "古典鋼琴")
check("標題兩字相連也對得上（Lo Fi → LoFi輕音）",
      cb.classify_style([], [], "Lo Fi Morning") == "LoFi輕音")
check("Hip-Hop 這類寫法正規化後對得上",
      cb.classify_style([], ["Hip-Hop"], "") == "嘻哈")
check("完全沒線索時用搜尋時的情境",
      cb.classify_moods([], [], "Untitled 3", hint="商務簡報") == ["商務簡報"])
check("沒線索也沒提示 → 未分類情境", cb.classify_moods() == [cb.UNSORTED_MOOD])
check("只靠標題一個字不會多掛第二個情境",
      cb.classify_moods(["happy"], [], "Sad Clown") == ["輕鬆愉快"],
      cb.classify_moods(["happy"], [], "Sad Clown"))
check("沒有風格線索 → 其他風格", cb.classify_style() == cb.OTHER_STYLE)
check("instrumental → 純音樂", cb.detect_vocal(["instrumental", "piano"]) is False)
check("vocal／male → 有人聲", cb.detect_vocal(["vocal"]) and cb.detect_vocal(["male"]))
check("沒標示 → 不明", cb.detect_vocal(["piano"]) is None)
check("speed_high → 快", cb.detect_speed(["speed_high"]) == "快")

# ---- 版權 ----------------------------------------------------------------

def rec_of(**kw):
    return cb.record_from_openverse(track("1", "T", **kw), query_mood="輕鬆愉快")

check("ND 授權不收（配進影片算改作）",
      cb.skip_reason(rec_of(license="by-nd"), OPTIONS) == "授權不能當配樂")
check("BY-NC-ND 也不收",
      cb.skip_reason(rec_of(license="by-nc-nd"), OPTIONS) == "授權不能當配樂")
commercial = dict(OPTIONS, licenses=cb.COMMERCIAL_LICENSES)
check("--commercial-only 排除非商用",
      cb.skip_reason(rec_of(license="by-nc"), commercial) == "授權不在這次的範圍")
check("CC BY 可收", cb.skip_reason(rec_of(license="by"), commercial) is None)
check("預設不收人聲", cb.skip_reason(rec_of(tags=["vocal"]), OPTIONS) == "有人聲")
check("--allow-vocal 就收",
      cb.skip_reason(rec_of(tags=["vocal"]), dict(OPTIONS, allow_vocal=True)) is None)
check("太長不收", cb.skip_reason(rec_of(duration=900000), OPTIONS) == "長度不在範圍內")
check("ogg 預設不收（Premiere 等吃不下）",
      cb.skip_reason(rec_of(filetype="ogg"), OPTIONS) == "音檔格式剪輯軟體不一定吃得下")
check("mp32 視為 mp3", rec_of()["ext"] == "mp3")
check("毫秒轉秒", rec_of(duration=183500)["duration"] == 184)
check("授權名稱", cb.license_label("by-nc-sa", "4.0") == "CC BY-NC-SA 4.0"
      and cb.license_label("cc0", "1.0") == "CC0 1.0")
check("SA 類資料夾有講明影片需同授權",
      "影片需同授權" in cb.LICENSE_CLASSES["by-sa"].folder)
check("Pixabay 類標為不可轉傳", cb.LICENSE_CLASSES["pixabay"].shareable is False)

# ---- 檔名 ----------------------------------------------------------------

name = cb.safe_name('a<b>:c/d\\e|f?g*h"')
check("去掉 Windows 不允許的字元", not any(ch in name for ch in '<>:"/\\|?*'), name)
check("Windows 保留名稱加底線", cb.safe_name("CON") == "_CON"
      and cb.safe_name("nul.txt") == "_nul.txt")
check("結尾的點與空白去掉", cb.safe_name("Song. . ") == "Song")
check("過長截斷", len(cb.safe_name("x" * 300)) == 80)

rec = cb.record_from_openverse(track(
    "42", "Evening: Tea?", tags=["relaxing", "calm", "romantic"],
    genres=["lounge"], creator="DJ Chill"), query_mood="放鬆療癒")
filename = cb.build_filename(rec)
check("檔名帶版權／情境／風格標籤",
      filename == "[需標註BY][放鬆療癒][浪漫甜蜜][LoFi輕音] Evening Tea - DJ Chill.mp3",
      filename)
check("預設資料夾：版權/情境/風格",
      cb.build_rel_dir(rec) == os.path.join(
          "2_可商用-需標註作者(CC-BY)", "放鬆療癒", "LoFi輕音"))
check("--layout mood/style 不分版權資料夾",
      cb.build_rel_dir(rec, cb.parse_layout("mood/style"))
      == os.path.join("放鬆療癒", "LoFi輕音"))
try:
    cb.parse_layout("license/genre")
    check("--layout 打錯要報錯", False)
except ValueError:
    check("--layout 打錯要報錯", True)
line = cb.attribution_line(rec)
check("標註文字含曲名、作者、來源、授權（TASL）",
      '"Evening: Tea?"' in line and "DJ Chill" in line
      and "jamendo.com/track/42" in line and "CC BY 3.0" in line
      and "creativecommons.org/licenses/by/3.0/" in line, line)
params = cb.search_params(["happy", "fun"], 2, OPTIONS)
check("搜尋參數：標籤、純音樂、授權、長度、分頁",
      params["tags"] == "happy fun" and params["category"] == "music"
      and "by-nd" not in params["license"] and params["length"] == "short,medium"
      and params["page"] == 2 and params["page_size"] == 20 and "source" not in params)

# ---- 整個收集流程 --------------------------------------------------------

happy_p1 = [
    track("h1", "Sunny Walk", tags=["happy", "instrumental"], genres=["pop"]),
    track("h2", "Bad License", license="by-nd", tags=["happy"]),
    track("h3", "Singer", tags=["happy", "vocal"]),
    track("h4", "Free Joy", license="cc0", version="1.0", tags=["happy"],
          genres=["electronic"]),
]
happy_p2 = [
    track("h5", "Too Long", tags=["happy"], duration=1200000),
    track("h6", "Party Time", license="by-nc", tags=["happy", "party"],
          genres=["dance"]),
    track("h7", "Extra", tags=["happy"]),
]
relax_p1 = [
    track("h1", "Sunny Walk", tags=["happy", "instrumental"], genres=["pop"]),
    track("r1", "Rain", license="by-sa", tags=["relaxing", "calm"],
          genres=["ambient"]),
]
http = FakeHttp({"happy": [happy_p1, happy_p2], "relaxing": [relax_p1]})

with tempfile.TemporaryDirectory() as tmp:
    root = os.path.join(tmp, "配樂庫")
    lib = cb.Library(root)
    client = cb.Openverse(http, delay=0, sleep=NO_SLEEP, log=QUIET)
    logs = []
    found, limited = cb.collect(lib, client, ["輕鬆愉快", "放鬆療癒"], OPTIONS,
                                log=logs.append)
    ids = [r["id"].split(":")[1] for r in found]
    check("每個情境收到 per_mood 首就停、略過不合格的", ids == ["h1", "h4", "h6", "r1"], ids)
    check("跨情境重複的歌只收一次", ids.count("h1") == 1)
    check("沒被額度擋", limited is False)
    check("輕鬆愉快翻到第 2 頁就夠了、放鬆療癒只有 1 頁",
          [c["page"] for c in http.calls] == [1, 2, 1], http.calls)
    check("略過原因有記錄", any("授權不能當配樂" in m and "有人聲" in m
                                 for m in logs), logs)

    ok, failed = cb.download_all(lib, found, http, delay=0, sleep=NO_SLEEP, log=QUIET)
    check("全部下載成功", (ok, failed) == (4, 0), (ok, failed))
    paths = sorted(r["path"] for r in lib.records.values())
    expected = [
        "1_可商用-免標註(CC0-公眾領域)/輕鬆愉快/電子/[免標註CC0][輕鬆愉快][電子] Free Joy - Artist.mp3",
        "2_可商用-需標註作者(CC-BY)/輕鬆愉快/流行/[需標註BY][輕鬆愉快][流行] Sunny Walk - Artist.mp3",
        "3_可商用-需標註-影片需同授權(CC-BY-SA)/放鬆療癒/氛圍/[需標註BY-SA][放鬆療癒][氛圍] Rain - Artist.mp3",
        "4_非商用-需標註作者(CC-BY-NC)/輕鬆愉快/電子/[非商用BY-NC][輕鬆愉快][節慶派對][電子] Party Time - Artist.mp3",
    ]
    check("依版權/情境/風格放好，檔名帶標籤", paths == expected, paths)
    check("檔案真的在磁碟上",
          all(os.path.exists(os.path.join(root, *p.split("/"))) for p in paths))

    with open(os.path.join(root, cb.CATALOG_CSV), "rb") as handle:
        raw = handle.read()
    check("CSV 有 UTF-8 BOM（Excel 直接開不亂碼）", raw.startswith(b"\xef\xbb\xbf"))
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    check("CSV 表頭與筆數", rows[0][0] == "檔案" and len(rows) == 5, len(rows))
    header = rows[0]
    party = next(r for r in rows[1:] if r[header.index("曲名")] == "Party Time")
    check("CSV 標明非商用、需標註",
          party[header.index("可商用")] == "否" and party[header.index("需標註作者")] == "是"
          and party[header.index("情境")] == "輕鬆愉快、節慶派對")
    free = next(r for r in rows[1:] if r[header.index("曲名")] == "Free Joy")
    check("CC0 不需要標註文字", free[header.index("標註文字（貼到影片說明欄）")] == "")

    credits = open(os.path.join(root, cb.CREDITS_TXT), encoding="utf-8").read()
    check("標註檔有需標註的歌", 'Music: "Sunny Walk" by Artist' in credits)
    check("需標註的排前面、CC0 排最後",
          credits.index("2_可商用") < credits.index("1_可商用"))
    readme = open(os.path.join(root, cb.README_TXT), encoding="utf-8").read()
    check("說明檔有各類數量與注意事項",
          "2_可商用-需標註作者(CC-BY)（1 首）" in readme and "Content ID" in readme
          and "9_僅限自用" in readme)

    # 重跑：配樂庫已經夠了就不再查 API
    before = len(http.calls)
    lib2 = cb.Library(root)
    check("清單能讀回來", len(lib2.records) == 4)
    found2, _ = cb.collect(lib2, client, ["輕鬆愉快"], OPTIONS, log=QUIET)
    check("已收滿的情境重跑不再查 API", not found2 and len(http.calls) == before)
    found3, _ = cb.collect(lib2, client, ["輕鬆愉快"], dict(OPTIONS, per_mood=4),
                           log=QUIET)
    check("調高數量會補收、已有的不重複",
          [r["id"] for r in found3] == ["openverse:h7"], [r["id"] for r in found3])

# ---- 額度用完、暫時性錯誤 ------------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    lib = cb.Library(tmp)
    sleeps = []
    http = FakeHttp({"happy": [happy_p1]}, errors=[http_error(429, 5)])
    client = cb.Openverse(http, delay=0, sleep=sleeps.append, log=QUIET)
    found, limited = cb.collect(lib, client, ["輕鬆愉快"], OPTIONS, log=QUIET)
    check("429 且只要等一下：照 Retry-After 等完再查", 5 in sleeps and len(found) == 2
          and not limited, (sleeps, len(found)))

    http = FakeHttp({"happy": [happy_p1]}, errors=[http_error(429, 3600)])
    client = cb.Openverse(http, delay=0, sleep=NO_SLEEP, log=QUIET)
    logs = []
    found, limited = cb.collect(cb.Library(tmp), client, ["輕鬆愉快"], OPTIONS,
                                log=logs.append)
    check("要等很久：停下來回報額度用完", limited is True and found == [])
    check("告訴使用者晚點重跑會接續", any("接續" in m for m in logs), logs)

    http = FakeHttp({"happy": [happy_p1, happy_p2]}, errors=[])
    http.errors = []
    real_get = http.get_json
    def get_json_400_on_page_2(url, params=None):
        if params["page"] == 2:
            raise http_error(400)
        return real_get(url, params)
    http.get_json = get_json_400_on_page_2
    client = cb.Openverse(http, delay=0, sleep=NO_SLEEP, log=QUIET)
    found, _ = cb.collect(cb.Library(tmp), client, ["輕鬆愉快"],
                          dict(OPTIONS, per_mood=10), log=QUIET)
    check("翻到頁數上限（400）就換下一個情境", len(found) == 2, len(found))

# ---- 預覽後下載、下載失敗補抓 --------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    lib = cb.Library(tmp)
    recs = [cb.record_from_openverse(t, "輕鬆愉快") for t in happy_p1[:1]]
    recs.append(cb.record_from_openverse(happy_p1[3], "輕鬆愉快"))
    for r in recs:      # 等同 fetch --dry-run
        lib.add(r)
        lib.assign_path(r)
    lib.save()
    check("預覽不下載任何音檔",
          not any(f.endswith(".mp3") for _, _, fs in os.walk(tmp) for f in fs))
    lib = cb.Library(tmp)
    pending = cb.pending_records(lib)
    check("預覽的歌列為待下載", len(pending) == 2)
    bad_url = pending[0]["audio_url"]
    http = FakeHttp({}, fail_urls=[bad_url])
    ok, failed = cb.download_all(lib, pending, http, delay=0, sleep=NO_SLEEP, log=QUIET)
    check("失敗會重試三次後標記失敗", (ok, failed) == (1, 1)
          and http.downloads.count(bad_url) == 3)
    check("失敗的歌之後還在待下載清單",
          [r["audio_url"] for r in cb.pending_records(cb.Library(tmp))] == [bad_url])
    check("沒有留下 .part 暫存檔",
          not any(f.endswith(".part") for _, _, fs in os.walk(tmp) for f in fs))

# ---- 撞名 ----------------------------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    lib = cb.Library(tmp)
    a = cb.record_from_openverse(track("aaa111", "Same", tags=["happy"]), "輕鬆愉快")
    b = cb.record_from_openverse(track("bbb222", "Same", tags=["happy"]), "輕鬆愉快")
    for r in (a, b):
        lib.add(r)
        lib.assign_path(r)
    check("同名歌第二首加來源 ID", a["path"] != b["path"]
          and b["path"].endswith(" #bbb222.mp3"), b["path"])

# ---- 匯入手動下載的 Pixabay 檔案 -----------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    downloads = os.path.join(tmp, "下載")
    os.makedirs(downloads)
    src = os.path.join(downloads, "lesfm-lofi-study-112191.mp3")
    with open(src, "wb") as handle:
        handle.write(b"ID3" + b"\x00" * 5000)
    open(os.path.join(downloads, "notes.txt"), "w").close()
    root = os.path.join(tmp, "配樂庫")
    files = cb.expand_inputs([downloads])
    check("資料夾展開只挑音檔", files == [src], files)
    check("萬用字元自己展開（Windows 命令列不會）",
          cb.expand_inputs([os.path.join(downloads, "*.mp3")]) == [src])
    check("Pixabay 檔名去掉尾巴 ID",
          cb.title_from_filename(src) == "lesfm lofi study")
    lib = cb.Library(root)
    done = cb.import_files(lib, files, "pixabay", log=QUIET)
    rec = next(iter(lib.records.values()))
    check("匯入一首", done == 1)
    check("Pixabay 放進僅限自用資料夾、檔名標自用",
          rec["path"].startswith("9_僅限自用-勿轉傳(Pixabay等平台授權)/")
          and "[自用Pixabay]" in rec["path"], rec["path"])
    check("從檔名猜到風格", rec["style"] == "LoFi輕音", rec["style"])
    check("原檔保留（預設複製）", os.path.exists(src))
    again = cb.import_files(cb.Library(root), files, "pixabay", log=QUIET)
    check("同一個檔案不會重複匯入", again == 0)
    rows = list(csv.reader(open(os.path.join(root, cb.CATALOG_CSV),
                                encoding="utf-8-sig")))
    check("CSV 標明不可轉傳", rows[1][rows[0].index("可轉傳給朋友")] == "否")
    other = os.path.join(downloads, "track01.wav")
    with open(other, "wb") as handle:
        handle.write(b"RIFF" + b"\x01" * 5000)
    lib = cb.Library(root)
    cb.import_files(lib, [other], "by", mood="史詩壯闊", style="電影配樂",
                    title="Hero", creator="Someone",
                    url="https://ccmixter.org/files/x/1", log=QUIET)
    rec = next(r for r in lib.records.values() if r["title"] == "Hero")
    check("指定授權／情境／風格匯入",
          rec["path"] == "2_可商用-需標註作者(CC-BY)/史詩壯闊/電影配樂/"
                         "[需標註BY][史詩壯闊][電影配樂] Hero - Someone.wav", rec["path"])
    credits = open(os.path.join(root, cb.CREDITS_TXT), encoding="utf-8").read()
    check("匯入的 CC 歌也有標註文字",
          'Music: "Hero" by Someone (https://ccmixter.org/files/x/1) | License: CC BY'
          in credits)

# ---- 命令列＋真的 urllib：本機假 Openverse 伺服器 -------------------------

import http.server  # noqa: E402
import threading  # noqa: E402
import urllib.parse  # noqa: E402

SERVED = {"happy": [track("s1", "Server Song", tags=["happy", "instrumental"],
                          genres=["jazz"]),
                    track("s2", "Html Error Page", tags=["happy"]),
                    track("s3", "Second Song", license="cc0", tags=["happy"])]}
state = {"throttled": False, "auth": []}


class FakeOpenverse(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        query = dict(urllib.parse.parse_qsl(url.query))
        state["auth"].append(self.headers.get("Authorization"))
        if url.path == "/v1/audio/":
            if not state["throttled"]:      # 第一次先回 429，測 Retry-After
                state["throttled"] = True
                self.send_response(429)
                self.send_header("Retry-After", "1")
                self.end_headers()
                return
            results = []
            for item in SERVED.get(query["tags"].split()[0], []):
                item = dict(item, url=f"http://127.0.0.1:{port}/file/{item['id']}")
                results.append(item)
            body = json.dumps({"result_count": len(results), "page_count": 1,
                               "page": 1, "page_size": 20, "results": results})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())
        elif url.path == "/file/s2":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html>blocked</html>")
        elif url.path.startswith("/file/"):
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.end_headers()
            self.wfile.write(b"\xff\xfb" * 30000)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        if self.path == "/v1/auth_tokens/register/":
            data = json.loads(body)
            ok = set(data) == {"name", "email", "description"}
            self.send_response(201 if ok else 400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"client_id": "cid", "client_secret": "csec",
                                         "name": data.get("name"), "msg": ""}).encode())
            return
        form = dict(urllib.parse.parse_qsl(body))
        ok = (self.path == "/v1/auth_tokens/token/"
              and form.get("grant_type") == "client_credentials"
              and form.get("client_secret") == "sec")
        self.send_response(200 if ok else 401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"access_token": "tok"} if ok else {}).encode())


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenverse)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
cb.API_BASE = f"http://127.0.0.1:{port}/v1"
try:
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "lib")
        common_args = ["--out", out, "--download-delay", "0"]
        code = cb.main(["fetch", "--dry-run", "--moods", "輕鬆愉快", "--per-mood", "5",
                        "--delay", "0", "--client-id", "id", "--client-secret", "sec"]
                       + common_args)
        check("命令列 fetch --dry-run 成功（含一次 429 等待）", code == 0, code)
        check("有金鑰時帶 Bearer token", "Bearer tok" in state["auth"], state["auth"])
        lib = cb.Library(out)
        check("預覽清單三首、都還沒下載",
              len(lib.records) == 3 and all(r["status"] == cb.STATUS_PLANNED
                                            for r in lib.records.values()))
        code = cb.main(["download"] + common_args)
        lib = cb.Library(out)
        status = {r["title"]: r["status"] for r in lib.records.values()}
        check("download：正常的抓下來", status["Server Song"] == cb.STATUS_DONE
              and status["Second Song"] == cb.STATUS_DONE, status)
        check("download：拿到網頁而不是音檔要算失敗",
              status["Html Error Page"] == cb.STATUS_FAILED and code == 1, (status, code))
        song = next(r for r in lib.records.values() if r["title"] == "Server Song")
        check("真的寫出音檔",
              os.path.getsize(lib.abspath(song)) == 60000
              and "[需標註BY][輕鬆愉快][爵士藍調]" in song["path"], song["path"])
        check("命令列 import 找不到檔案回傳 1",
              cb.main(["import", os.path.join(tmp, "nothing", "*.mp3")] + common_args) == 1)
        check("register 送出名稱、信箱、用途",
              cb.main(["register", "--name", "n", "--email", "a@b.c"]) == 0)

        # Windows 上 Excel 開著 CSV 時 os.replace 會 PermissionError
        real_replace = cb.os.replace
        def locked_csv(src, dst):
            if dst.endswith(cb.CATALOG_CSV):
                raise PermissionError(13, "locked")
            return real_replace(src, dst)
        cb.os.replace = locked_csv
        try:
            cb.Library(out).save()
            check("CSV 被 Excel 鎖住時照樣存清單、不留暫存檔",
                  not os.path.exists(os.path.join(out, cb.CATALOG_CSV + ".tmp")))
        except PermissionError:
            check("CSV 被 Excel 鎖住時照樣存清單、不留暫存檔", False)
        finally:
            cb.os.replace = real_replace
finally:
    server.shutdown()

print()
if failures:
    print(f"{len(failures)} 項失敗")
    sys.exit(1)
print("全部通過")
