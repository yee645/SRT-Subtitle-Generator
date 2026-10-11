# -*- coding: utf-8 -*-
"""
3.0 第 13 項：線上配樂庫的核心（subtitle/musiclib.py）與音樂軌讀網址（subtitle/assemble.py）。

不連外網：Openverse 換成替身（回傳的欄位照 Openverse 原始碼與 Jamendo 來源的真實資料），
網址播放用本機的 HTTP 伺服器。

1. 查詢參數：只選情境用標籤查；有關鍵字或風格改用 q（Openverse 的 q 不能跟 tags 並用），
   情境變成 q 裡的「任一個字」；預設只查可商用的授權；條件不夠、不認得的情境風格說清楚。
   風格拿去搜尋的字都是那個風格判斷用的關鍵字（搜到的歌分得回那個風格）。
2. 搜尋結果：篩掉授權不對、有人聲、太短（音效）的；重複的只留一首；分到所選風格與情境的
   排前面；翻頁到 Openverse 的上限為止，翻過頭的 400 當成沒有更多。
3. 用戶端：沒設金鑰匿名查；有金鑰先換 token，換不到退回匿名（不讓整個配樂庫不能用）；
   有人在等，伺服器要求等太久就直接說額度用完。
4. 授權提醒、放進音樂軌時記下的欄位、標註文字（同一首只列一次、NC／SA 另外提醒、沒有
   線上配樂不寫檔）。
5. 音樂軌讀網址（assemble）：只有音樂軌收網址；網址輸入帶斷線重連與逾時；顯示名稱用曲名；
   真的輸出（ffmpeg 從本機 HTTP 伺服器讀）音樂在對的那幾秒、循環到片尾；網址失效時說清楚是
   哪一首、不留檔；check_stream 讀得到長度、讀不到時說原因（不帶又長又看不懂的網址）。
"""
import email.message
import functools
import http.server
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import assemble  # noqa: E402
from subtitle import musiclib as ml  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def track(ident, title, license="by", tags=(), genres=(), duration=180000,
          filetype="mp32", creator="Artist", version="4.0"):
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
        "tags": [{"name": t, "accuracy": None, "unstable__provider": "jamendo"} for t in tags],
        "duration": duration, "mature": False,
    }


def http_error(code, retry_after=None):
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError("https://api.openverse.org/v1/audio/", code, "err", headers,
                                  io.BytesIO(b"{}"))


class FakeClient:
    """Openverse 用戶端的替身：照頁數回結果，記下每次的參數。"""

    def __init__(self, pages, page_count=None, error=None):
        self.pages = pages
        self.page_count = len(pages) if page_count is None else page_count
        self.calls = []
        self.error = error

    def search(self, params):
        self.calls.append(dict(params))
        if self.error:
            raise self.error
        page = params["page"]
        results = self.pages[page - 1] if page <= len(self.pages) else []
        return {"result_count": 999, "page_count": self.page_count, "page_size": 20, "page": page,
                "results": results}


def error_of(fn, *args, exc=ValueError, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc as error:
        return str(error)
    return None


# ----- 1. 查詢參數 -----
mood_only = ml.search_request(mood="放鬆療癒")
check("只選情境：用標籤查（Jamendo 的情緒標籤最準），不帶 q",
      "q" not in mood_only and mood_only["tags"].split()[:2] == ["relaxing", "calm"], mood_only)
check("查詢都限定音樂、可商用的授權、30 秒～10 分鐘、一頁 20 首、第 1 頁",
      mood_only["category"] == "music" and mood_only["license"] == "cc0,pdm,by,by-sa"
      and mood_only["length"] == "short,medium" and mood_only["page_size"] == 20
      and mood_only["page"] == 1, mood_only)
check("勾了也列非商用：授權多 by-nc、by-nc-sa（ND 永遠不查）",
      ml.search_request(mood="放鬆療癒", commercial_only=False)["license"]
      == "cc0,pdm,by,by-sa,by-nc,by-nc-sa")
both = ml.search_request(keyword="  summer  morning ", mood="輕鬆愉快", style="LoFi輕音", page=3)
check("關鍵字＋風格＋情境：q 裡每一組都要中、組內任一個字即可；不帶 tags",
      "tags" not in both and both["q"] == "(summer morning) + (lofi | chillhop | downtempo)"
      " + (happy | cheerful | joyful | fun)" and both["page"] == 3, both)
check("只有一個字的關鍵字不加括號、只有一個字的風格也不加",
      ml.search_request(keyword="piano", style="流行")["q"] == "piano + pop")
check("關鍵字裡的查詢語法符號當成空白（不會弄亂分組）",
      ml.search_request(keyword='lo-fi "chill" (beats)|x', style="流行")["q"] == "(lo fi chill beats x) + pop"
      and error_of(ml.search_request, keyword="+-|") == "輸入關鍵字，或選一個情境、風格",
      ml.search_request(keyword='lo-fi "chill" (beats)|x', style="流行")["q"])
check("只選風格：q 是那個風格的搜尋字",
      ml.search_request(style="爵士藍調")["q"] == "(jazz | blues)")
check("什麼都沒選：說清楚要怎麼做",
      error_of(ml.search_request) == "輸入關鍵字，或選一個情境、風格"
      and error_of(ml.search_request, keyword="   ") == "輸入關鍵字，或選一個情境、風格")
check("不認得的情境、風格：說是哪一個",
      "不認得的情境：開心" == error_of(ml.search_request, mood="開心")
      and "不認得的風格：重金屬" == error_of(ml.search_request, style="重金屬"))
check("每個風格都有搜尋字",
      set(ml.STYLE_SEARCH) == set(ml.STYLE_NAMES) and all(ml.STYLE_SEARCH.values()))
keywords = dict(ml._STYLE_KEYWORDS)
stray = {style: [w for w in words if ml.norm(w) not in keywords[style]]
         for style, words in ml.STYLE_SEARCH.items()}
check("風格的搜尋字都是那個風格的判斷關鍵字（搜到的歌分得回那個風格）",
      not any(stray.values()), stray)
check("風格的搜尋字當成歌的曲風時，分到的就是那個風格",
      all(ml.classify_style([], [w], "") == style
          for style, words in ml.STYLE_SEARCH.items() for w in words),
      [(s, w, ml.classify_style([], [w], "")) for s, ws in ml.STYLE_SEARCH.items() for w in ws
       if ml.classify_style([], [w], "") != s])

# ----- 2. 搜尋結果 -----
page1 = [
    track("a1", "Happy Jazz", tags=["happy", "instrumental"], genres=["jazz"]),
    track("a2", "Chill Beat", tags=["happy", "instrumental"], genres=["lofi"]),
    track("a3", "Sung Song", tags=["happy", "vocal"], genres=["lofi"]),
    track("a4", "Sad Lofi", tags=["sad", "instrumental"], genres=["lofi"]),
    track("a5", "Tiny Jingle", tags=["happy"], genres=["lofi"], duration=8000),
    track("a6", "No Derivs", license="by-nd", tags=["happy"], genres=["lofi"]),
    track("a2", "Chill Beat", tags=["happy", "instrumental"], genres=["lofi"]),
    track("a7", "Ogg Lofi", tags=["happy", "instrumental"], genres=["lofi"], filetype="ogg"),
    track("a8", "NC Lofi", license="by-nc", tags=["happy", "instrumental"], genres=["lofi"]),
]
client = FakeClient([page1, [track("b1", "Second Page", tags=["happy"], genres=["lofi"])]], page_count=40)
result = ml.search(client, keyword="beat", mood="輕鬆愉快", style="LoFi輕音")
titles = [r["title"] for r in result["tracks"]]
check("篩掉有人聲、太短（音效）、ND、預設不收的 NC；重複的只留一首；ogg 剪輯器自己讀得了",
      sorted(titles) == ["Chill Beat", "Happy Jazz", "Ogg Lofi", "Sad Lofi"], titles)
check("分到所選風格與情境的排前面（其餘照 Openverse 的順序）",
      titles == ["Chill Beat", "Ogg Lofi", "Happy Jazz", "Sad Lofi"], titles)
check("略過的原因與首數",
      result["skipped"] == {"有人聲": 1, "長度不在範圍內": 1, "授權不能當配樂": 1, "授權不在這次的範圍": 1},
      result["skipped"])
check("查詢參數照 search_request，第 1 頁；還有更多（頁數上限 12，不是 Openverse 說的 40）",
      client.calls[0] == ml.search_request("beat", "輕鬆愉快", "LoFi輕音")
      and result["page"] == 1 and result["has_more"] is True and result["total"] == 999)
rec = result["tracks"][0]
check("每首帶曲名、作者、網址、授權、情境、風格（同收集器的配樂紀錄）",
      rec["audio_url"].startswith("https://prod-1.storage.jamendo.com/") and rec["license"] == "by"
      and rec["moods"][0] == "輕鬆愉快" and rec["style"] == "LoFi輕音" and rec["creator"] == "Artist"
      and rec["landing_url"] == "https://www.jamendo.com/track/a2" and "path" not in rec, rec)
nc = ml.search(FakeClient([page1]), mood="輕鬆愉快", commercial_only=False, allow_vocal=True)
check("勾了非商用與有人聲：NC 與有人聲的也列（ND、太短的照樣不列）",
      sorted(r["title"] for r in nc["tracks"]) == ["Chill Beat", "Happy Jazz", "NC Lofi", "Ogg Lofi",
                                                    "Sad Lofi", "Sung Song"]
      and nc["has_more"] is False, [r["title"] for r in nc["tracks"]])
last = ml.search(FakeClient([page1] * 12, page_count=40), keyword="x", page=12)
check("第 12 頁就是最後一頁（Openverse 只給前 240 筆）", last["has_more"] is False)
over = ml.search(FakeClient([], error=http_error(400)), keyword="x", page=13)
check("翻過頭的 400：當成沒有更多，不是錯誤",
      over == {"tracks": [], "page": 13, "has_more": False, "total": 0, "skipped": {}}, over)
check("第 1 頁就 400：照樣丟出來（查詢本身有問題）",
      error_of(ml.search, FakeClient([], error=http_error(400)), keyword="x",
               exc=urllib.error.HTTPError) is not None)

# ----- 3. 用戶端 -----


class FakeHttp:
    def __init__(self, token_error=None, errors=()):
        self.token = None
        self.posts = []
        self.gets = []
        self.token_error = token_error
        self.errors = list(errors)

    def post_form(self, url, fields):
        self.posts.append((url, dict(fields)))
        if self.token_error:
            raise self.token_error
        return {"access_token": "tok123"}

    def get_json(self, url, params=None):
        self.gets.append(url)
        if self.errors:
            raise self.errors.pop(0)
        return {"results": [], "page_count": 0}


anon_http = FakeHttp()
anon = ml.client_from_env(environ={}, http=anon_http)
check("沒設金鑰：匿名查，不連網換 token", anon_http.posts == [] and anon_http.token is None)
check("剪輯器的用戶端：不等前一次（delay 0）、伺服器要求等超過 5 秒就不等",
      anon.delay == 0 and anon.max_retry_after == ml.INTERACTIVE_MAX_WAIT == 5)
key_http = FakeHttp()
env = {"OPENVERSE_CLIENT_ID": "id1", "OPENVERSE_CLIENT_SECRET": "sec1"}
ml.client_from_env(environ=env, http=key_http, api_base="http://127.0.0.1:9/v1")
check("有金鑰：先換 token（用指定的 API 位址）",
      key_http.token == "tok123" and key_http.posts[0][0] == "http://127.0.0.1:9/v1/auth_tokens/token/"
      and key_http.posts[0][1]["client_id"] == "id1", key_http.posts)
bad_http = FakeHttp(token_error=urllib.error.URLError("down"))
ml.client_from_env(environ=env, http=bad_http)
check("換不到 token：退回匿名，配樂庫照樣能用", bad_http.token is None and len(bad_http.posts) == 1)
sleeps = []
waiting = ml.client_from_env(environ={}, http=FakeHttp(errors=[http_error(429, 3)]))
waiting.sleep = sleeps.append
waiting.search({"q": "x"})
check("伺服器要求等 3 秒：等完再查一次", sleeps == [3], sleeps)
limited = ml.client_from_env(environ={}, http=FakeHttp(errors=[http_error(429, 60)]))
limited.sleep = sleeps.append
check("要求等 60 秒：不等，丟 RateLimited（介面說額度用完）",
      error_of(limited.search, {"q": "x"}, exc=ml.RateLimited) == "60" and sleeps == [3])
plain_http = FakeHttp()
ml.client_from_env(environ={}, http=plain_http).search({"q": "x"})
check("沒指定 API 位址：查 Openverse 的正式位址", plain_http.gets == ["https://api.openverse.org/v1/audio/"],
      plain_http.gets)

# ----- 4. 授權提醒、音樂軌欄位、標註文字 -----
recs = {lic: ml.record_from_openverse(track(lic, f"Song {lic}", license=lic, version="4.0"))
        for lic in ("cc0", "by", "by-sa", "by-nc", "by-nc-sa")}
check("授權標籤（結果清單那一格）",
      [ml.license_tag(recs[k]) for k in ("cc0", "by", "by-nc")] == ["免標註CC0", "需標註BY", "非商用BY-NC"],
      [ml.license_tag(recs[k]) for k in ("cc0", "by", "by-nc")])
check("CC0、BY 不用特別提醒", ml.license_warning(recs["cc0"]) == "" == ml.license_warning(recs["by"]))
check("NC 提醒不能營利、SA 提醒整支影片要同授權、NC-SA 兩個都提",
      "非商用" in ml.license_warning(recs["by-nc"]) and "CC BY-SA" in ml.license_warning(recs["by-sa"])
      and ml.license_warning(recs["by-nc-sa"]).count("；") == 1, ml.license_warning(recs["by-nc-sa"]))
meta = ml.track_meta(recs["by"])
check("放進音樂軌時記下曲名、作者、授權、來源頁與標註文字（TASL）",
      set(meta) == set(ml.TRACK_META_KEYS) and meta["title"] == "Song by"
      and meta["credit"] == ml.attribution_line(recs["by"])
      and meta["credit"].startswith('Music: "Song by" by Artist (https://www.jamendo.com/track/by)')
      and "License: CC BY 4.0" in meta["credit"], meta)
items = [dict(path="https://x/1", **ml.track_meta(recs["by"])), {"path": "/local/song.mp3"},
         dict(path="https://x/1", **ml.track_meta(recs["by"])), dict(path="https://x/2", **ml.track_meta(recs["by-nc"])),
         dict(path="https://x/3", **ml.track_meta(recs["cc0"]))]
text = ml.credits_text(items, "成品.mp4")
lines = text.splitlines()
check("標註文字：寫是哪支影片、同一首只列一次、本機的歌不列",
      lines[0] == "這支影片（成品.mp4）用到的線上配樂" and text.count('Music: "Song by"') == 1
      and 'Music: "Song by-nc"' in text and 'Music: "Song cc0"' in text and "song.mp3" not in text, text)
check("標註文字：NC 另外一段提醒", "注意：" in lines and any(l.startswith("- 「Song by-nc」：非商用") for l in lines), text)
check("沒有線上配樂：空字串", ml.credits_text([{"path": "/a.mp3"}]) == "" == ml.credits_text([]))
tmp = tempfile.mkdtemp()
video = os.path.join(tmp, "成品.mp4")
written = ml.write_credits(items, video)
check("寫在影片旁邊：<檔名>_配樂標註.txt（UTF-8 帶 BOM，記事本開不會亂碼）",
      written == os.path.join(tmp, "成品_配樂標註.txt") == ml.credits_path(video)
      and open(written, "rb").read().startswith(b"\xef\xbb\xbf")
      and open(written, encoding="utf-8-sig").read() == text, written)
check("沒有線上配樂：不寫檔、回 None",
      ml.write_credits([{"path": "/a.mp3"}], os.path.join(tmp, "b.mp4")) is None
      and not os.path.exists(os.path.join(tmp, "b_配樂標註.txt")))

# ----- 5. 音樂軌讀網址（assemble） -----
url = "https://prod-1.storage.jamendo.com/?trackid=42&format=mp32"
check("is_url：http／https 才算", assemble.is_url(url)
      and assemble.is_url("HTTP://a/b.mp3") and not assemble.is_url("C:/music/a.mp3")
      and not assemble.is_url("ftp://a/b.mp3"))
check("顯示名稱：有曲名用曲名；網址用路徑最後一段（解碼），沒有就用網域；本機檔用檔名",
      assemble.item_label({"path": url, "title": "Sunny"}) == "Sunny"
      and assemble.item_label({"path": "https://a.org/x/My%20Song.mp3?x=1"}) == "My Song.mp3"
      and assemble.item_label({"path": url}) == "prod-1.storage.jamendo.com"
      and assemble.item_label({"path": os.path.join("dir", "a.mp3")}) == "a.mp3")
base = {"main": [{"path": "a.mp4", "out": 10}]}
check("主軌、疊加軌不收網址（要逐格對畫面，串流太慢）",
      "只有音樂軌" in (error_of(assemble.normalize, {"main": [{"path": url, "out": 3}]},
                                                     exc=assemble.AssembleError) or "")
      and "疊加軌第 1 段是網址" in (error_of(assemble.normalize, dict(base, overlays=[{"path": url, "out": 2}]),
                                             exc=assemble.AssembleError) or ""))
song = dict(assemble.new_music(url, 2.0, 10.0, 4.0), **ml.track_meta(recs["by"]))
tl = assemble.normalize(dict(base, music=[song]))
check("音樂軌收網址；曲名、授權那些欄位 normalize 不看（輸出不受影響）",
      tl["music"][0]["path"] == url and set(tl["music"][0]) == {"path", "at", "in", "out", "volume", "loop", "duck"})
media = {"a.mp4": {"video": True, "audio": True}, url: {"video": False, "audio": True}}
cmd = assemble.build_command(tl, "out.mp4", media, (640, 360, 30))
i = cmd.index(url)
check("網址的輸入帶斷線重連與逾時（-i 前面），本機檔不帶",
      cmd[i - 1] == "-i" and cmd[i - 1 - len(assemble.URL_INPUT_OPTIONS):i - 1] == assemble.URL_INPUT_OPTIONS
      and cmd.count("-reconnect") == 1, cmd)
looped = assemble.normalize(dict(base, music=[dict(song, loop=True)]))
cmd = assemble.build_command(looped, "out.mp4", media, (640, 360, 30))
i = cmd.index(url)
opts = len(assemble.URL_INPUT_OPTIONS)
check("循環的網址：重連參數、-stream_loop -1、-i 網址",
      cmd[i - 3 - opts:i] == assemble.URL_INPUT_OPTIONS + ["-stream_loop", "-1", "-i"], cmd[i - 3 - opts:i + 1])
check("時間軸不是 dict：照樣說「時間軸要是 dict」（記曲名那一步不先當掉）",
      error_of(assemble.render, ["x"], "o.mp4", exc=assemble.AssembleError) == "時間軸要是 dict")
check("音樂軌沒聲音的錯誤寫曲名，不寫看不懂的網址",
      "音樂軌第 1 段沒有聲音：" in (error_of(assemble.build_command, assemble.normalize(dict(base, music=[song])), "o.mp4",
                                             dict(media, **{url: {"video": False, "audio": False}}),
                                             exc=assemble.AssembleError) or ""))

if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
    print("SKIP 這個環境沒有 ffmpeg：略過真的從網址讀")
else:
    def run(*args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)

    def p(name):
        return os.path.join(tmp, name)

    served = os.path.join(tmp, "srv")
    os.makedirs(served)
    run("-f", "lavfi", "-i", "color=c=gray:size=320x240:rate=25", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-t", "10", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        p("main.mp4"))
    run("-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000", "-t", "4", os.path.join(served, "song.wav"))

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=served))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    song_url = f"http://127.0.0.1:{port}/song.wav?trackid=7&format=mp32"

    probe = ml.check_stream(song_url, timeout=10)
    check("check_stream：讀得到聲音、量得到長度", probe["ok"] and abs(probe["seconds"] - 4.0) < 0.05, probe)
    missing = ml.check_stream(f"http://127.0.0.1:{port}/gone.mp3", timeout=10)
    check("check_stream：404 說讀不到與原因，不帶網址",
          not missing["ok"] and missing["reason"].startswith("讀不到聲音（網路斷了，或原網址已失效）")
          and "404" in missing["reason"] and "127.0.0.1" not in missing["reason"], missing)
    dead_port = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    dead_url = f"http://127.0.0.1:{dead_port.server_address[1]}/song.wav"
    dead_port.server_close()
    refused = ml.check_stream(dead_url, timeout=5)
    check("check_stream：連不上的網址", not refused["ok"] and refused["seconds"] is None, refused)
    real_which = shutil.which
    shutil.which = lambda name: None
    try:
        no_probe = ml.check_stream(song_url)
    finally:
        shutil.which = real_which
    check("check_stream：沒有 ffprobe 說清楚", not no_probe["ok"] and "ffprobe" in no_probe["reason"], no_probe)

    def tone(path, start, end):
        out = subprocess.run(["ffmpeg", "-v", "info", "-ss", str(start), "-t", str(end - start), "-i", path, "-af",
                              "bandpass=f=880:width_type=h:w=100,volumedetect", "-f", "null", "-"],
                             capture_output=True, text=True).stderr
        return float([l.split("mean_volume:")[1].split()[0] for l in out.splitlines() if "mean_volume" in l][0])

    item = dict(assemble.new_music(song_url, 2.0, 10.0, probe["seconds"]), volume=1.0, duck=False,
                **ml.track_meta(recs["by"]))
    out = p("once.mp4")
    done = assemble.render({"main": [{"path": p("main.mp4"), "out": 10}], "music": [item]}, out)
    loud = [tone(out, 2.2, 5.8), tone(out, 0.2, 1.8), tone(out, 6.2, 9.8)]
    check("真的輸出：音樂從網址讀，只在 2～6 秒（整首 4 秒）",
          done["duration"] == 10.0 and loud[0] > -35 and loud[1] < -45 and loud[2] < -45, loud)
    out = p("loop.mp4")
    assemble.render({"main": [{"path": p("main.mp4"), "out": 10}], "music": [dict(item, loop=True)]}, out)
    loud = [tone(out, 2.2, 5.8), tone(out, 6.2, 9.8), tone(out, 0.2, 1.8)]
    check("真的輸出：循環的網址一路放到片尾", loud[0] > -35 and loud[1] > -35 and loud[2] < -45, loud)
    gone = dict(item, path=f"http://127.0.0.1:{port}/gone.mp3", title="消失的歌")
    message = error_of(assemble.render, {"main": [{"path": p("main.mp4"), "out": 10}], "music": [gone]},
                       p("gone.mp4"), exc=assemble.AssembleError)
    check("網址失效：說是哪一首（曲名），不留下檔案",
          message == "線上配樂讀不到（網路斷了，或原網址已失效）：消失的歌"
          and not [f for f in os.listdir(tmp) if f.startswith("gone")], message)
    server.shutdown()
    server.server_close()
shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 線上配樂庫核心測試全數通過。")
