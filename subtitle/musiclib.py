# -*- coding: utf-8 -*-
"""
線上配樂庫的核心：搜尋開放授權的配樂、判斷授權能不能當配樂、分情境與風格、確認網址
播得出來、輸出時產生標註文字。零 GUI 依賴。

使用者 2026-10-11 要的是：剪輯器裡直接搜尋、試聽、放進音樂軌，**不必先下載到本機**、
也不必切視窗到各個平台找。做法：

* 搜尋走 Openverse（WordPress 基金會維運的開放授權搜尋引擎）的音訊 API，音樂實際來自
  Jamendo。不用金鑰就能查（匿名額度較低）；設了環境變數 `OPENVERSE_CLIENT_ID`／
  `OPENVERSE_CLIENT_SECRET` 就換成金鑰（額度較高）。Pixabay 沒有音樂的 API、條款又禁止
  爬取，YouTube 音效庫沒有 API，這兩個都接不了。
* 音樂軌記的是**網址**（`assemble` 的 path 可以是 http／https 網址）：試聽是串流，輸出時
  ffmpeg 直接讀網址，電腦裡不留檔。放進時間軸之前先用 ffprobe 讀一次網址
  （`check_stream`），讀不到就不放。
* 每首都帶授權。ND（禁止改作）不收——CC 條款把「音樂與影像同步」算改作；NC 只能用在非
  營利影片；SA 整支影片要用同一種授權。輸出時把用到的線上配樂寫成一份標註文字
  （`write_credits`，CC 建議的 TASL：曲名、作者、來源、授權），貼到影片說明欄。

授權、情境、風格的分類規則原本寫在 `bgm_collector/collect_bgm.py`（下載到本機、分資料
夾給朋友的收集器），搬到這裡兩邊共用：同一首歌在兩邊分到的類別一樣。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import namedtuple

API_BASE = "https://api.openverse.org/v1"
USER_AGENT = ("SRT-Subtitle-Generator-MusicLibrary/1.0 "
              "(+https://github.com/yee645/SRT-Subtitle-Generator)")

# Openverse 對匿名與一般金鑰都只給前 240 筆（12 頁 × 20 筆），再往後翻會 400。
PAGE_SIZE = 20
MAX_PAGES = 12
# 伺服器要求等待超過這個秒數就不等了（收集器存檔後請使用者之後再跑；剪輯器直接告訴使用者）。
MAX_RETRY_AFTER = 120

# ---------------------------------------------------------------------------
# 版權分類
# ---------------------------------------------------------------------------

LicenseClass = namedtuple(
    "LicenseClass",
    "folder tag commercial attribution share_alike shareable note")

_PD_FOLDER = "1_可商用-免標註(CC0-公眾領域)"
_PERSONAL_FOLDER = "9_僅限自用-勿轉傳(Pixabay等平台授權)"

LICENSE_CLASSES = {
    "cc0": LicenseClass(
        _PD_FOLDER, "免標註CC0", True, False, False, True,
        "作者已放棄權利，商用、改編都可以，不標註也可以。"),
    "pdm": LicenseClass(
        _PD_FOLDER, "公眾領域PD", True, False, False, True,
        "已進入公眾領域，商用、改編都可以，不標註也可以。"),
    "by": LicenseClass(
        "2_可商用-需標註作者(CC-BY)", "需標註BY", True, True, False, True,
        "可商用（含開營利、業配），但影片說明欄一定要標註曲名、作者、來源與授權。"),
    "by-sa": LicenseClass(
        "3_可商用-需標註-影片需同授權(CC-BY-SA)", "需標註BY-SA",
        True, True, True, True,
        "可商用且需標註；但音樂配進影片在 CC 條款裡算「改作」，"
        "整支影片也必須用 CC BY-SA 釋出。不想這樣就別用這一類。"),
    "by-nc": LicenseClass(
        "4_非商用-需標註作者(CC-BY-NC)", "非商用BY-NC", False, True, False, True,
        "只能用在非營利影片：開了營利的 YouTube、業配、接案都不行。需標註。"),
    "by-nc-sa": LicenseClass(
        "5_非商用-需標註-影片需同授權(CC-BY-NC-SA)", "非商用BY-NC-SA",
        False, True, True, True,
        "只能非營利使用、需標註，而且整支影片要用 CC BY-NC-SA 釋出。"),
    "pixabay": LicenseClass(
        _PERSONAL_FOLDER, "自用Pixabay", True, False, False, False,
        "Pixabay 授權：可商用、免標註，但禁止把音檔原封不動轉給別人。"
        "朋友要用請給他原始網址自己下載。"),
    "ytal": LicenseClass(
        _PERSONAL_FOLDER, "自用YT音效庫", True, False, False, False,
        "YouTube 音效庫：只能用在 YouTube 影片，部分曲目要求標註（以音效庫頁面為準），"
        "不可轉傳。"),
}

# 這些授權的音樂不能當配樂：CC 條款明定「把音樂與影像同步」屬於改作，
# ND（禁止改作）等於直接排除；sampling+ 系列已廢止且只允許取樣。
UNUSABLE_LICENSES = {
    "by-nd": "禁止改作（ND）——配進影片就算改作，不能當配樂",
    "by-nc-nd": "禁止改作（ND）——配進影片就算改作，不能當配樂",
    "sampling+": "已廢止的取樣授權，只允許取樣",
    "nc-sampling+": "已廢止的取樣授權，只允許取樣",
}

COMMERCIAL_LICENSES = ["cc0", "pdm", "by", "by-sa"]
ALL_USABLE_LICENSES = COMMERCIAL_LICENSES + ["by-nc", "by-nc-sa"]


def license_label(license_key, version=""):
    """授權代碼轉成人看得懂的名稱，例如 by-sa + 4.0 → CC BY-SA 4.0。"""
    key = (license_key or "").lower()
    names = {"cc0": "CC0", "pdm": "Public Domain Mark",
             "pixabay": "Pixabay Content License",
             "ytal": "YouTube Audio Library"}
    name = names.get(key) or ("CC " + key.upper())
    return f"{name} {version}".strip()


# ---------------------------------------------------------------------------
# 情境與風格
# ---------------------------------------------------------------------------

# 每個情境：(名稱, 拿去 Openverse 搜尋的標籤, 另外也算命中的同義詞)。
# 標籤用英文，因為 Jamendo 的 mood tags 是英文。排在前面的同分時優先。
MOODS = [
    ("輕鬆愉快",
     ["happy", "cheerful", "joyful", "fun", "playful", "positive", "bright", "sunny"],
     ["joy", "feelgood", "lighthearted", "bouncy", "carefree", "summer"]),
    ("放鬆療癒",
     ["relaxing", "calm", "peaceful", "chill", "soft", "dreamy", "mellow", "soothing"],
     ["relax", "relaxed", "relaxation", "meditation", "meditative", "gentle",
      "serene", "tranquil", "quiet", "sleep", "lullaby", "spa", "yoga"]),
    ("溫暖勵志",
     ["inspiring", "uplifting", "motivational", "hopeful", "inspirational", "warm"],
     ["motivation", "inspiration", "hope", "optimistic", "confident"]),
    ("熱血動感",
     ["energetic", "powerful", "action", "sport", "intense", "upbeat", "driving"],
     ["energy", "sports", "workout", "fast", "aggressive", "strong"]),
    ("史詩壯闊",
     ["epic", "cinematic", "dramatic", "heroic", "trailer", "majestic", "adventure"],
     ["orchestral", "grandiose", "battle", "triumphant", "glorious"]),
    ("感傷抒情",
     ["sad", "melancholic", "emotional", "sentimental", "lonely", "melancholy"],
     ["sorrow", "tragic", "grief", "heartbreak", "tears", "reflective",
      "introspective"]),
    ("浪漫甜蜜",
     ["romantic", "love", "tender", "sweet", "wedding", "romance"],
     ["passion", "sensual", "valentine"]),
    ("懸疑緊張",
     ["dark", "suspense", "mysterious", "tension", "scary", "horror", "thriller",
      "ominous"],
     ["mystery", "creepy", "eerie", "sinister", "spooky", "tense", "suspenseful",
      "haunting", "halloween"]),
    ("搞笑逗趣",
     ["funny", "comedy", "quirky", "silly", "whimsical", "cartoon", "comic", "humor"],
     ["humorous", "goofy", "kids", "children", "childish"]),
    ("科技未來",
     ["futuristic", "technology", "tech", "scifi", "space", "digital", "cyberpunk"],
     ["future", "robot", "cyber", "innovation"]),
    ("商務簡報",
     ["corporate", "business", "presentation", "commercial", "advertising"],
     ["advertisement", "promo", "promotion", "marketing", "company"]),
    ("復古懷舊",
     ["retro", "vintage", "nostalgic", "80s", "oldschool", "nostalgia"],
     ["70s", "90s", "60s", "oldies"]),
    ("節慶派對",
     ["party", "christmas", "holiday", "festive", "celebration", "xmas"],
     ["birthday", "newyear", "club"]),
]
UNSORTED_MOOD = "未分類情境"

STYLES = [
    ("LoFi輕音", ["lofi", "lofihiphop", "chillhop", "chillout", "chill", "downtempo",
                 "triphop", "lounge", "jazzhop", "easylistening"]),
    ("電子", ["electronic", "electronica", "electro", "edm", "house", "deephouse",
             "techno", "trance", "dubstep", "drumnbass", "dnb", "synthwave",
             "electropop", "idm", "breakbeat", "dance", "synthpop", "chiptune",
             "8bit", "futurebass", "glitch"]),
    ("流行", ["pop", "indiepop", "dancepop", "kpop", "jpop", "cpop"]),
    ("搖滾", ["rock", "alternative", "alternativerock", "indierock", "punk", "metal",
             "heavymetal", "grunge", "hardrock", "postrock", "poprock",
             "progressiverock"]),
    ("嘻哈", ["hiphop", "rap", "trap", "boombap", "beats", "beat",
             "instrumentalhiphop"]),
    ("爵士藍調", ["jazz", "blues", "swing", "bossanova", "smoothjazz", "bebop",
               "acidjazz"]),
    ("放克靈魂", ["funk", "soul", "rnb", "disco", "motown", "groove", "neosoul"]),
    ("電影配樂", ["soundtrack", "cinematic", "orchestral", "filmscore", "score",
               "trailer", "videogame", "gamemusic", "film", "movie", "epic"]),
    ("古典鋼琴", ["classical", "baroque", "chamber", "symphony", "symphonic", "opera",
               "piano", "neoclassical"]),
    ("原聲民謠", ["acoustic", "folk", "country", "singersongwriter", "americana",
               "bluegrass", "guitar", "acousticguitar"]),
    ("氛圍", ["ambient", "newage", "meditation", "drone", "atmospheric", "chillwave",
             "darkambient"]),
    ("世界音樂", ["world", "worldmusic", "latin", "reggae", "celtic", "african",
               "asian", "ethnic", "oriental", "flamenco", "chinese", "japanese",
               "indian", "arabic", "balkan", "tango", "salsa", "reggaeton", "ska"]),
]
OTHER_STYLE = "其他風格"

# 剪輯器裡選了某個風格時，拿去搜尋的字：每種挑最常見、真的會出現在曲名與標籤上的幾個
# （STYLES 的關鍵字是拿來「判斷」的，很多是正規化後的合字，例如 lofihiphop，拿去搜尋
# 反而找不到）。都必須是該風格的關鍵字，測試守著。
STYLE_SEARCH = {
    "LoFi輕音": ["lofi", "chillhop", "downtempo"],
    "電子": ["electronic", "edm", "house", "synthwave"],
    "流行": ["pop"],
    "搖滾": ["rock", "indierock", "metal"],
    "嘻哈": ["hiphop", "rap", "beats"],
    "爵士藍調": ["jazz", "blues"],
    "放克靈魂": ["funk", "soul", "disco"],
    "電影配樂": ["cinematic", "soundtrack", "orchestral"],
    "古典鋼琴": ["classical", "piano"],
    "原聲民謠": ["acoustic", "folk", "guitar"],
    "氛圍": ["ambient", "atmospheric"],
    "世界音樂": ["world", "latin", "reggae", "ethnic"],
}

MOOD_NAMES = [name for name, _, _ in MOODS]
STYLE_NAMES = [name for name, _ in STYLES]

SPEED_LABELS = {"speedlow": "慢", "speedmedium": "中", "speedhigh": "快"}
_VOCAL_TAGS = {"vocal", "vocals", "singing", "male", "female"}


def norm(text):
    """英文標籤正規化：小寫、只留英數字（hip-hop、Hip Hop 都變成 hiphop）。"""
    return re.sub(r"[^0-9a-z]+", "", (text or "").lower())


def title_tokens(text):
    """把標題拆成字，另外加上相鄰兩字的組合，讓 Lo Fi、Hip Hop 也能對上。"""
    words = re.findall(r"[0-9a-z]+", (text or "").lower())
    return set(words) | {a + b for a, b in zip(words, words[1:])}


_MOOD_KEYWORDS = [(name, {norm(k) for k in search + extra})
                  for name, search, extra in MOODS]
_STYLE_KEYWORDS = [(name, {norm(k) for k in words}) for name, words in STYLES]


def _rank(buckets, fields, bonus=None):
    """各分類在各欄位命中的關鍵字數 × 欄位權重，回傳 [(分數, 名稱)] 由高到低。"""
    ranked = []
    for index, (name, keywords) in enumerate(buckets):
        score = sum(len(tokens & keywords) * weight for tokens, weight in fields)
        if bonus and bonus == name:
            score += 1
        if score > 0:
            ranked.append((score, -index, name))
    ranked.sort(reverse=True)
    return [(score, name) for score, _, name in ranked]


def classify_moods(tags=(), genres=(), title="", hint=None, max_moods=2):
    """判斷情境，最多回傳兩個；第一個決定資料夾，全部都會寫進檔名。

    情緒標籤最可信（權重 2），曲風與標題次之（1）。`hint` 是當初拿哪個
    情境去搜尋到這首歌的，只加 1 分當沒有其他線索時的依據。第二個情境
    至少要有一個標籤命中（2 分）才列，避免只靠標題某個字就多掛一類。
    """
    fields = [({norm(t) for t in tags}, 2), ({norm(g) for g in genres}, 1),
              (title_tokens(title), 1)]
    ranked = _rank(_MOOD_KEYWORDS, fields, bonus=hint)
    if not ranked:
        return [UNSORTED_MOOD]
    moods = [ranked[0][1]]
    moods += [name for score, name in ranked[1:max_moods] if score >= 2]
    return moods


def classify_style(tags=(), genres=(), title=""):
    """判斷風格：曲風欄位最可信（權重 3），樂器等標籤與標題只當補充（1）。"""
    fields = [({norm(g) for g in genres}, 3), ({norm(t) for t in tags}, 1),
              (title_tokens(title), 1)]
    ranked = _rank(_STYLE_KEYWORDS, fields)
    return ranked[0][1] if ranked else OTHER_STYLE


def detect_vocal(tags):
    """True＝有人聲、False＝純音樂、None＝來源沒說。"""
    tokens = {norm(t) for t in tags}
    if "instrumental" in tokens:
        return False
    if tokens & _VOCAL_TAGS:
        return True
    return None


def detect_speed(tags):
    for tag in tags:
        label = SPEED_LABELS.get(norm(tag))
        if label:
            return label
    return ""


def attribution_line(rec):
    """貼到影片說明欄用的標註（TASL：曲名、作者、來源、授權）。"""
    text = f'Music: "{rec["title"]}"'
    if rec.get("creator"):
        text += f' by {rec["creator"]}'
    if rec.get("landing_url"):
        text += f' ({rec["landing_url"]})'
    text += f' | License: {license_label(rec["license"], rec.get("license_version"))}'
    if rec.get("license_url"):
        text += f' {rec["license_url"]}'
    return text


def format_duration(seconds):
    if not seconds:
        return ""
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


# ---------------------------------------------------------------------------
# Openverse 的搜尋結果
# ---------------------------------------------------------------------------

EXT_BY_FILETYPE = {"mp32": "mp3", "mp3": "mp3", "wav": "wav", "flac": "flac",
                   "m4a": "m4a", "aac": "aac", "aif": "aiff", "aiff": "aiff",
                   "ogg": "ogg", "oga": "ogg", "opus": "opus"}
# 剪輯軟體（Premiere、剪映、Final Cut…）都吃得下的格式；ogg／opus 有些吃不下。
EDITOR_FRIENDLY_EXTS = {"mp3", "wav", "flac", "m4a", "aac", "aiff"}
AUDIO_EXTS = set(EXT_BY_FILETYPE.values())


def guess_ext(filetype, url):
    ext = EXT_BY_FILETYPE.get((filetype or "").lower())
    if ext:
        return ext
    path_ext = os.path.splitext(urllib.parse.urlsplit(url or "").path)[1]
    return EXT_BY_FILETYPE.get(path_ext.lower().lstrip("."), "")


def record_from_openverse(item, query_mood=None):
    """Openverse 的一筆搜尋結果轉成一筆配樂紀錄（曲名、作者、網址、授權、情境、風格…）。"""
    tags = [t.get("name") for t in item.get("tags") or []
            if isinstance(t, dict) and t.get("name")]
    genres = [g for g in item.get("genres") or [] if isinstance(g, str)]
    title = (item.get("title") or "").strip() or "untitled"
    duration_ms = item.get("duration")
    return {
        "id": f"openverse:{item.get('id')}",
        "origin": "openverse",
        "source": item.get("source") or item.get("provider") or "",
        "title": title,
        "creator": (item.get("creator") or "").strip(),
        "creator_url": item.get("creator_url") or "",
        "landing_url": item.get("foreign_landing_url") or "",
        "audio_url": item.get("url") or "",
        "ext": guess_ext(item.get("filetype"), item.get("url")),
        "license": (item.get("license") or "").lower(),
        "license_version": item.get("license_version") or "",
        "license_url": item.get("license_url") or "",
        "tags": tags,
        "genres": genres,
        "moods": classify_moods(tags, genres, title, hint=query_mood),
        "style": classify_style(tags, genres, title),
        "vocal": detect_vocal(tags),
        "speed": detect_speed(tags),
        "duration": round(duration_ms / 1000) if duration_ms else None,
        "query_mood": query_mood or "",
    }


def skip_reason(rec, options):
    """不收這首的原因；回傳 None 表示可以收。"""
    if rec["license"] in UNUSABLE_LICENSES:
        return "授權不能當配樂"
    if rec["license"] not in LICENSE_CLASSES:
        return "授權不明"
    if rec["license"] not in options["licenses"]:
        return "授權不在這次的範圍"
    if not rec["audio_url"]:
        return "沒有音檔網址"
    if rec["ext"] not in EDITOR_FRIENDLY_EXTS and not (
            options.get("allow_ogg") and rec["ext"] in AUDIO_EXTS):
        return "音檔格式剪輯軟體不一定吃得下"
    if rec["vocal"] and not options.get("allow_vocal"):
        return "有人聲"
    duration = rec["duration"]
    if duration and not (options["min_sec"] <= duration <= options["max_sec"]):
        return "長度不在範圍內"
    return None


# ---------------------------------------------------------------------------
# 連線
# ---------------------------------------------------------------------------

class RateLimited(Exception):
    """API 額度用完，要等很久才能再查（args[0]＝伺服器要求等幾秒）。"""


class NotAudioError(IOError):
    """拿到的不是音檔（例如錯誤網頁）；重試也沒用，直接算失敗。"""


class Http:
    """很薄的一層 urllib 包裝，測試時整個換成替身。"""

    def __init__(self, token=None, timeout=30, user_agent=USER_AGENT):
        self.token = token
        self.timeout = timeout
        self.user_agent = user_agent

    def _headers(self):
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def get_json(self, url, params=None):
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers=self._headers())
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_form(self, url, fields):
        data = urllib.parse.urlencode(fields).encode("ascii")
        request = urllib.request.Request(url, data=data, headers={
            "User-Agent": self.user_agent,
            "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def download(self, url, dest):
        """下載到 dest；先寫 .part 再改名，中斷不會留下半個檔。回傳位元組數。"""
        import shutil
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        part = dest + ".part"
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                content_type = response.headers.get("Content-Type", "")
                if content_type.startswith(("text/", "application/json")):
                    raise NotAudioError(f"伺服器回傳的不是音檔（{content_type}）")
                with open(part, "wb") as handle:
                    shutil.copyfileobj(response, handle, 1 << 16)
            size = os.path.getsize(part)
            if size < 20 * 1024:
                raise NotAudioError(f"檔案太小（{size} bytes），大概不是完整的音檔")
            os.replace(part, dest)
            return size
        finally:
            if os.path.exists(part):
                os.remove(part)


def post_json(url, payload, timeout=30, user_agent=USER_AGENT):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"User-Agent": user_agent, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_token(http, client_id, client_secret, api_base=None):
    """用 Openverse 的 client credentials 換 access token（有效 12 小時）。"""
    data = http.post_form(f"{api_base or API_BASE}/auth_tokens/token/", {
        "grant_type": "client_credentials",
        "client_id": client_id, "client_secret": client_secret})
    return data["access_token"]


class Openverse:
    """
    Openverse 音訊搜尋。`api_base` 省略時用這個模組的 API_BASE（查的當下才讀，測試換掉
    模組變數就生效）。`max_retry_after`：伺服器要求等超過這麼多秒就不等、丟 RateLimited
    （收集器在背景跑，等兩分鐘無妨；剪輯器裡有人在等，等幾秒就好）。
    """

    def __init__(self, http, delay=1.5, sleep=time.sleep, log=print, api_base=None,
                 max_retry_after=MAX_RETRY_AFTER):
        self.http = http
        self.delay = delay
        self.sleep = sleep
        self.log = log
        self.api_base = api_base
        self.max_retry_after = max_retry_after
        self._last_call = None

    def search(self, params):
        """查一頁；429 時照 Retry-After 等一下再試，等太久就丟 RateLimited。"""
        for attempt in range(4):
            if self._last_call is not None and self.delay:
                self.sleep(self.delay)
            self._last_call = True
            try:
                return self.http.get_json(f"{self.api_base or API_BASE}/audio/", params)
            except urllib.error.HTTPError as error:
                if error.code == 429:
                    wait = _retry_after_seconds(error)
                    if wait > self.max_retry_after or attempt == 3:
                        raise RateLimited(wait) from error
                    self.log(f"  API 要求稍等 {wait} 秒…")
                    self.sleep(wait)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                if attempt == 3:
                    raise
                self.log(f"  連線失敗（{error}），重試中…")
                self.sleep(2 ** (attempt + 1))
        raise RuntimeError("unreachable")


def _retry_after_seconds(error):
    try:
        return max(1, int(float(error.headers.get("Retry-After", "60"))))
    except (TypeError, ValueError, AttributeError):
        return 60


def search_params(tags, page, options):
    """收集器用的查詢（一次一個情境，用標籤查）。"""
    params = {
        "tags": " ".join(tags),
        "category": "music",
        "license": ",".join(options["licenses"]),
        # short＝30 秒～2 分、medium＝2～10 分：剪輯配樂最常用的長度。
        "length": "short,medium",
        "page_size": PAGE_SIZE,
        "page": page,
    }
    if options.get("sources"):
        params["source"] = ",".join(options["sources"])
    return params


# ---------------------------------------------------------------------------
# 剪輯器裡的搜尋
# ---------------------------------------------------------------------------

# 剪輯器裡（有人在等）：伺服器要求等超過幾秒就不等，直接說額度用完。
INTERACTIVE_MAX_WAIT = 5
# 剪輯器裡收的長度：太短的是音效、不是配樂；上限放寬（循環用不到那麼長，但不擋）。
MIN_SECONDS = 15
MAX_SECONDS = 60 * 60


def client_from_env(environ=None, api_base=None, http=None):
    """
    剪輯器用的 Openverse 用戶端：不等前一次查詢（delay=0）、伺服器要求等太久就不等。
    環境變數 OPENVERSE_CLIENT_ID／OPENVERSE_CLIENT_SECRET 都有時先換金鑰（會連網，
    請在背景執行緒呼叫）；換不到就退回匿名，不讓整個配樂庫不能用。
    """
    environ = os.environ if environ is None else environ
    http = http or Http(timeout=20)
    client_id = environ.get("OPENVERSE_CLIENT_ID")
    secret = environ.get("OPENVERSE_CLIENT_SECRET")
    if client_id and secret and not http.token:
        try:
            http.token = fetch_token(http, client_id, secret, api_base=api_base)
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            http.token = None
    return Openverse(http, delay=0, log=lambda _m: None, api_base=api_base,
                     max_retry_after=INTERACTIVE_MAX_WAIT)


_QUERY_SYNTAX = re.compile(r'[+|\-"*()~\\]')


def _or_group(words):
    words = [w for w in words if w]
    if len(words) <= 1:
        return words[0] if words else ""
    return "(" + " | ".join(words) + ")"


def search_request(keyword="", mood=None, style=None, commercial_only=True, page=1):
    """
    剪輯器的一次查詢 → Openverse 的參數。至少要有關鍵字、情境、風格其中一個，否則
    ValueError。

    * 只選情境：用標籤查（`tags`，跟收集器一樣，Jamendo 的情緒標籤最準）。
    * 有關鍵字或風格：Openverse 的 `q` 不能跟 `tags` 一起用，情境改成 `q` 裡的一組
      「任一個字」：`lofi + (happy | cheerful | joyful | fun)`。
    * 關鍵字當成一般的字：Openverse 的查詢語法符號（+ | - " * ( ) ~）換成空白，不然使用者
      打的 lo-fi、a|b 會把上面的分組弄亂（lo-fi → lo fi，標題裡的 Lo-Fi 照樣對得上）。
    """
    keyword = " ".join(_QUERY_SYNTAX.sub(" ", keyword or "").split())
    if mood is not None and mood not in MOOD_NAMES:
        raise ValueError(f"不認得的情境：{mood}")
    if style is not None and style not in STYLE_SEARCH:
        raise ValueError(f"不認得的風格：{style}")
    if not (keyword or mood or style):
        raise ValueError("輸入關鍵字，或選一個情境、風格")
    licenses = COMMERCIAL_LICENSES if commercial_only else ALL_USABLE_LICENSES
    params = {"category": "music", "license": ",".join(licenses),
              "length": "short,medium", "page_size": PAGE_SIZE, "page": int(page)}
    mood_tags = dict((name, search) for name, search, _ in MOODS).get(mood, [])
    if keyword or style:
        groups = []
        if keyword:
            groups.append(f"({keyword})" if " " in keyword else keyword)
        if style:
            groups.append(_or_group(STYLE_SEARCH[style]))
        if mood:
            groups.append(_or_group(mood_tags[:4]))
        params["q"] = " + ".join(groups)
    else:
        params["tags"] = " ".join(mood_tags)
    return params


def search(client, keyword="", mood=None, style=None, commercial_only=True,
           allow_vocal=False, page=1):
    """
    剪輯器的一次搜尋：查一頁 Openverse，轉成配樂紀錄、照授權／人聲／長度篩掉不能用的，
    選了情境或風格時把分到那一類的排前面（其餘照樣列：搜尋本來就是照那些字查到的）。

    回傳 {"tracks", "page", "has_more", "total", "skipped"（原因 → 首數）}。
    額度用完丟 RateLimited；連不上丟 urllib.error.URLError／OSError。
    """
    params = search_request(keyword, mood, style, commercial_only, page)
    options = {"licenses": COMMERCIAL_LICENSES if commercial_only else ALL_USABLE_LICENSES,
               "allow_vocal": allow_vocal, "allow_ogg": True,  # 剪輯器自己用 ffmpeg 讀，ogg 也行
               "min_sec": MIN_SECONDS, "max_sec": MAX_SECONDS}
    try:
        data = client.search(params)
    except urllib.error.HTTPError as error:
        if error.code == 400 and page > 1:  # 翻過頁數上限
            return {"tracks": [], "page": page, "has_more": False, "total": 0, "skipped": {}}
        raise
    tracks, skipped, seen = [], {}, set()
    for item in data.get("results") or []:
        rec = record_from_openverse(item, query_mood=mood)
        if rec["id"] in seen:
            continue
        seen.add(rec["id"])
        reason = skip_reason(rec, options)
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        tracks.append(rec)

    def fit(rec):
        return ((style is not None and rec["style"] != style)
                + (mood is not None and mood not in rec["moods"]))
    tracks.sort(key=fit)  # sort 是穩定的：同一層照 Openverse 原本的順序
    pages = min(int(data.get("page_count") or 0), MAX_PAGES)
    return {"tracks": tracks, "page": page, "has_more": page < pages,
            "total": int(data.get("result_count") or 0), "skipped": skipped}


def license_tag(rec):
    """結果清單上那一格：例如「需標註BY」「非商用BY-NC」。"""
    lic = LICENSE_CLASSES.get(rec.get("license", ""))
    return lic.tag if lic else (rec.get("license") or "授權不明")


def license_warning(rec):
    """放進時間軸時要提醒的：NC 只能非營利、SA 整支影片要同授權；可以放心用就回空字串。"""
    lic = LICENSE_CLASSES.get(rec.get("license", ""))
    if not lic:
        return ""
    notes = []
    if not lic.commercial:
        notes.append("非商用：開了營利的影片、業配、接案都不能用")
    if lic.share_alike:
        notes.append(f"整支影片要用 {license_label(rec['license'])} 釋出")
    return "；".join(notes)


# 音樂軌上記著的線上配樂資料（normalize 不看，輸出不受影響；寫標註、顯示曲名用）
TRACK_META_KEYS = ("title", "creator", "license", "license_version", "license_url",
                   "landing_url", "source", "credit")


def track_meta(rec):
    """一筆配樂紀錄 → 放進音樂軌那一段時一起記下的資料（曲名、授權、標註文字…）。"""
    meta = {key: rec.get(key, "") for key in TRACK_META_KEYS if key != "credit"}
    meta["credit"] = attribution_line(rec)
    return meta


# ---------------------------------------------------------------------------
# 確認網址播得出來
# ---------------------------------------------------------------------------

def check_stream(url, timeout=25):
    """
    用 ffprobe 讀一次網址：有沒有聲音、多長。回傳 {"ok", "seconds", "reason"}。
    放進音樂軌之前先確認——網址失效、網路斷了、拿到的是錯誤網頁，都在這裡擋下來，
    不要等到輸出才失敗。
    """
    import shutil
    if not shutil.which("ffprobe"):
        return {"ok": False, "seconds": None, "reason": "找不到 ffprobe（ffmpeg 沒有裝好）"}
    command = ["ffprobe", "-v", "error", "-rw_timeout", str(int(timeout * 1_000_000)),
               "-select_streams", "a:0", "-show_entries", "stream=codec_type:format=duration",
               "-of", "json", url]
    try:
        done = subprocess.run(command, capture_output=True, timeout=timeout + 5)
    except (OSError, subprocess.SubprocessError):
        return {"ok": False, "seconds": None, "reason": "讀取逾時（網路太慢或連不上）"}
    try:
        info = json.loads((done.stdout or b"{}").decode("utf-8", errors="ignore") or "{}")
    except ValueError:
        info = {}
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams") or [])
    try:
        seconds = round(float((info.get("format") or {}).get("duration")), 3)
    except (TypeError, ValueError):
        seconds = None
    if done.returncode != 0 or not has_audio:
        lines = (done.stderr or b"").decode("utf-8", errors="ignore").strip().splitlines()
        # ffprobe 的錯誤是「網址: 原因」；網址很長又看不懂，只留原因
        detail = lines[-1].replace(url, "").strip(" :")[:120] if lines else ""
        reason = "讀不到聲音（網路斷了，或原網址已失效）"
        return {"ok": False, "seconds": None, "reason": reason + (f"：{detail}" if detail else "")}
    if not seconds or seconds <= 0:
        return {"ok": False, "seconds": None, "reason": "量不到這首有多長"}
    return {"ok": True, "seconds": seconds, "reason": ""}


# ---------------------------------------------------------------------------
# 標註文字
# ---------------------------------------------------------------------------

def credits_text(items, video_name=""):
    """
    音樂軌上用到的線上配樂 → 一份標註文字（貼到影片說明欄）。沒有線上配樂回傳空字串。
    同一首用兩次只列一次；NC、SA 另外寫一段提醒。
    """
    lines, warnings, seen = [], [], set()
    for item in items:
        credit = item.get("credit")
        if not credit or credit in seen:
            continue
        seen.add(credit)
        lines.append(credit)
        warning = license_warning(item)
        if warning:
            warnings.append(f"「{item.get('title') or '這首'}」：{warning}")
    if not lines:
        return ""
    head = f"這支影片（{video_name}）用到的線上配樂" if video_name else "這支影片用到的線上配樂"
    text = [head,
            "CC BY 系列（BY、BY-SA、BY-NC、BY-NC-SA）要求在影片說明欄附上下面的標註；"
            "CC0／公眾領域不必標註，附上也無妨。", ""]
    text += lines
    if warnings:
        text += ["", "注意："] + [f"- {w}" for w in warnings]
    return "\n".join(text) + "\n"


def credits_path(video_path):
    return os.path.splitext(video_path)[0] + "_配樂標註.txt"


def write_credits(items, video_path):
    """有線上配樂就在影片旁邊寫一份 `<檔名>_配樂標註.txt`，回傳路徑；沒有就回 None。"""
    text = credits_text(items, os.path.basename(video_path))
    if not text:
        return None
    path = credits_path(video_path)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8-sig") as handle:  # 換行照系統（Windows 是 CRLF）
        handle.write(text)
    os.replace(temp, path)
    return path
