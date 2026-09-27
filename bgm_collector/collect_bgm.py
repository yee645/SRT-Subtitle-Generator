# -*- coding: utf-8 -*-
"""
配樂庫收集器：搜尋開放授權的剪輯配樂，依「版權／情境／風格」分資料夾存放，
檔名直接帶分類標籤，例如：

    配樂庫/2_可商用-需標註作者(CC-BY)/放鬆療癒/LoFi輕音/
        [需標註BY][放鬆療癒][LoFi輕音] Morning Coffee - Some Artist.mp3

資料來源是 Openverse（WordPress 基金會維運的開放授權媒體搜尋引擎）的音訊
API，音樂實際來自 Jamendo。選它而不是直接爬 Pixabay 的原因：

- Pixabay 服務條款明文禁止爬蟲與大量下載，也禁止把音檔原封不動轉給別人
  （"Standalone" 散布）——而收集這批音樂的目的正是分享給朋友。
- Openverse 每首歌都帶機器可讀的授權（CC0／CC BY／CC BY-SA…）、曲風
  （genres）與情緒標籤（Jamendo 的 mood tags），分類不必靠猜。
- CC 授權本身就允許轉傳，只要標註資訊跟著檔案走（本工具會一併產生
  標註文字與授權說明）。

在 Pixabay、YouTube 音效庫手動下載的曲子，可以用 `import` 指令歸進同一套
分類，但會放進「9_僅限自用-勿轉傳」資料夾，提醒不要一起分享出去。

用法（只用 Python 標準函式庫，不需另外安裝套件）：

    python bgm_collector/collect_bgm.py fetch --dry-run   # 先預覽會抓到哪些歌
    python bgm_collector/collect_bgm.py fetch             # 搜尋並下載
    python bgm_collector/collect_bgm.py download          # 下載預覽清單／補抓失敗的
    python bgm_collector/collect_bgm.py import 下載/*.mp3 --license pixabay
    python bgm_collector/collect_bgm.py tags              # 列出可用的情境與風格
    python bgm_collector/collect_bgm.py register --name 名稱 --email 信箱  # 申請金鑰
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import os
import re
import shutil
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, namedtuple

API_BASE = "https://api.openverse.org/v1"
USER_AGENT = ("SRT-Subtitle-Generator-BGMCollector/1.0 "
              "(+https://github.com/yee645/SRT-Subtitle-Generator)")

# Openverse 對匿名與一般金鑰都只給前 240 筆（12 頁 × 20 筆），再往後翻會 400。
PAGE_SIZE = 20
MAX_PAGES = 12
# 伺服器要求等待超過這個秒數就不等了，存檔後請使用者之後再跑。
MAX_RETRY_AFTER = 120

CATALOG_JSON = "配樂清單.json"
CATALOG_CSV = "配樂清單.csv"
CREDITS_TXT = "CREDITS_標註文字.txt"
README_TXT = "README_授權說明.txt"

STATUS_DONE = "已下載"
STATUS_PLANNED = "未下載（預覽）"
STATUS_FAILED = "下載失敗"

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
IMPORT_LICENSES = ["pixabay", "ytal"] + ALL_USABLE_LICENSES


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


# ---------------------------------------------------------------------------
# 檔名與路徑
# ---------------------------------------------------------------------------

_WINDOWS_RESERVED = ({"CON", "PRN", "AUX", "NUL"}
                     | {f"COM{i}" for i in range(1, 10)}
                     | {f"LPT{i}" for i in range(1, 10)})


def safe_name(text, max_len=80):
    """轉成 Windows／macOS 都能用的檔名片段。"""
    text = unicodedata.normalize("NFC", str(text or ""))
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        text = "untitled"
    if text.split(".")[0].upper() in _WINDOWS_RESERVED:
        text = "_" + text
    if len(text) > max_len:
        text = text[:max_len].rstrip(" .")
    return text


def tag_prefix(rec):
    lic = LICENSE_CLASSES[rec["license"]]
    tags = [lic.tag] + list(rec["moods"]) + [rec["style"]]
    if rec.get("vocal"):
        tags.append("含人聲")
    return "".join(f"[{tag}]" for tag in tags)


def build_filename(rec, suffix=""):
    """[版權][情境][風格] 曲名 - 作者.副檔名；整個檔名控制在 150 字內。"""
    name = f"{tag_prefix(rec)} {safe_name(rec['title'], 70)}"
    if rec.get("creator"):
        name += f" - {safe_name(rec['creator'], 40)}"
    return f"{name}{suffix}.{rec['ext']}"


LAYOUT_PARTS = ("license", "mood", "style")


def build_rel_dir(rec, layout=LAYOUT_PARTS):
    folders = {"license": LICENSE_CLASSES[rec["license"]].folder,
               "mood": rec["moods"][0], "style": rec["style"]}
    return os.path.join(*[folders[part] for part in layout]) if layout else ""


def parse_layout(text):
    parts = tuple(p.strip() for p in (text or "").split("/") if p.strip())
    for part in parts:
        if part not in LAYOUT_PARTS:
            raise ValueError(f"--layout 只能用 license、mood、style，收到：{part}")
    return parts


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
# Openverse
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
    """Openverse 的一筆搜尋結果轉成配樂清單的一筆紀錄。"""
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
        "path": "",
        "status": STATUS_PLANNED,
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


class RateLimited(Exception):
    """API 額度用完，要等很久才能再查。"""


class NotAudioError(IOError):
    """拿到的不是音檔（例如錯誤網頁）；重試也沒用，直接算失敗。"""


class Http:
    """很薄的一層 urllib 包裝，測試時整個換成替身。"""

    def __init__(self, token=None, timeout=30):
        self.token = token
        self.timeout = timeout

    def _headers(self):
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
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
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def download(self, url, dest):
        """下載到 dest；先寫 .part 再改名，中斷不會留下半個檔。回傳位元組數。"""
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
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


def post_json(url, payload, timeout=30):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_token(http, client_id, client_secret):
    """用 Openverse 的 client credentials 換 access token（有效 12 小時）。"""
    data = http.post_form(f"{API_BASE}/auth_tokens/token/", {
        "grant_type": "client_credentials",
        "client_id": client_id, "client_secret": client_secret})
    return data["access_token"]


class Openverse:
    def __init__(self, http, delay=1.5, sleep=time.sleep, log=print):
        self.http = http
        self.delay = delay
        self.sleep = sleep
        self.log = log
        self._last_call = None

    def search(self, params):
        """查一頁；429 時照 Retry-After 等一下再試，等太久就丟 RateLimited。"""
        for attempt in range(4):
            if self._last_call is not None and self.delay:
                self.sleep(self.delay)
            self._last_call = True
            try:
                return self.http.get_json(f"{API_BASE}/audio/", params)
            except urllib.error.HTTPError as error:
                if error.code == 429:
                    wait = _retry_after_seconds(error)
                    if wait > MAX_RETRY_AFTER or attempt == 3:
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


# ---------------------------------------------------------------------------
# 配樂庫（清單、標註、說明檔）
# ---------------------------------------------------------------------------

class Library:
    def __init__(self, root, layout=LAYOUT_PARTS):
        self.root = root
        self.layout = layout
        self.records = {}
        path = os.path.join(root, CATALOG_JSON)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                for rec in json.load(handle):
                    self.records[rec["id"]] = rec

    def has_file(self, rec_id):
        rec = self.records.get(rec_id)
        return bool(rec and rec["status"] == STATUS_DONE and rec["path"]
                    and os.path.exists(self.abspath(rec)))

    def abspath(self, rec):
        return os.path.join(self.root, *rec["path"].split("/"))

    def assign_path(self, rec):
        """決定這首歌放哪裡；撞名時在檔名後面加來源 ID。"""
        rel_dir = build_rel_dir(rec, self.layout)
        taken = {r["path"] for r in self.records.values() if r["id"] != rec["id"]}
        for suffix in ("", f" #{_short_id(rec['id'])}"):
            rel = os.path.join(rel_dir, build_filename(rec, suffix))
            rel = rel.replace(os.sep, "/")
            if rel not in taken and (rel == rec.get("path")
                                     or not os.path.exists(
                                         os.path.join(self.root, rel))):
                rec["path"] = rel
                return rel
        raise FileExistsError(f"找不到可用的檔名：{rel}")

    def add(self, rec):
        self.records[rec["id"]] = rec

    def sorted_records(self):
        return sorted(self.records.values(), key=lambda r: r["path"] or r["id"])

    def save(self):
        os.makedirs(self.root, exist_ok=True)
        records = self.sorted_records()
        _atomic_write(os.path.join(self.root, CATALOG_JSON),
                      json.dumps(records, ensure_ascii=False, indent=1))
        self._write_csv(records)
        self._write_credits(records)
        self._write_readme(records)

    def _write_csv(self, records):
        header = ["檔案", "版權分類", "授權", "可商用", "需標註作者", "影片需同授權",
                  "可轉傳給朋友", "情境", "風格", "節奏", "人聲", "長度", "曲名", "作者",
                  "來源平台", "原始頁面", "授權條款", "標註文字（貼到影片說明欄）", "狀態"]
        yes_no = {True: "是", False: "否", None: "不明"}
        path = os.path.join(self.root, CATALOG_CSV)
        # utf-8-sig：Excel 直接點開才不會亂碼。
        with open(path + ".tmp", "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            for rec in records:
                lic = LICENSE_CLASSES[rec["license"]]
                writer.writerow([
                    rec["path"].replace("/", os.sep), lic.folder,
                    license_label(rec["license"], rec.get("license_version")),
                    yes_no[lic.commercial], yes_no[lic.attribution],
                    yes_no[lic.share_alike], yes_no[lic.shareable],
                    "、".join(rec["moods"]), rec["style"], rec.get("speed", ""),
                    yes_no[rec.get("vocal")], format_duration(rec.get("duration")),
                    rec["title"], rec.get("creator", ""), rec.get("source", ""),
                    rec.get("landing_url", ""), rec.get("license_url", ""),
                    attribution_line(rec) if lic.attribution else "",
                    rec["status"]])
        try:
            os.replace(path + ".tmp", path)
        except PermissionError:
            # Windows 上 Excel 開著這個檔會鎖住它；清單本體（JSON）照樣有存。
            os.remove(path + ".tmp")
            print(f"（{CATALOG_CSV} 正被 Excel 開著，這次沒更新；"
                  "關掉後執行 download 指令就會重寫）")

    def _write_credits(self, records):
        lines = ["配樂標註文字（CREDITS）", "",
                 "用到哪一首，就把它底下那一行貼到影片說明欄。",
                 "不需標註的（CC0、公眾領域、Pixabay）列在最後備查；標了也無妨。", ""]
        groups = {}
        for rec in records:
            if rec["status"] == STATUS_DONE:
                groups.setdefault(LICENSE_CLASSES[rec["license"]].folder, []).append(rec)
        needs_credit = {lic.folder: lic.attribution for lic in LICENSE_CLASSES.values()}
        for folder in sorted(groups, key=lambda f: (not needs_credit[f], f)):
            lines += [f"== {folder} ==", ""]
            for rec in groups[folder]:
                lines += [os.path.basename(rec["path"]), attribution_line(rec), ""]
        _atomic_write(os.path.join(self.root, CREDITS_TXT), "\n".join(lines))

    def _write_readme(self, records):
        counts = Counter(LICENSE_CLASSES[r["license"]].folder
                         for r in records if r["status"] == STATUS_DONE)
        notes = {}
        for lic in LICENSE_CLASSES.values():
            notes.setdefault(lic.folder, [])
            if lic.note not in notes[lic.folder]:
                notes[lic.folder].append(lic.note)
        lines = [
            "這個配樂庫怎麼用（給拿到這個資料夾的人）",
            "",
            "資料夾分三層：版權分類 / 情境 / 風格。檔名開頭的 [..] 是同樣的分類，",
            "檔案被搬出資料夾也看得出來它能怎麼用。",
            "",
            f"完整清單在「{CATALOG_CSV}」（Excel 可直接開），",
            f"要貼到影片說明欄的標註文字在「{CREDITS_TXT}」。",
            "",
            "== 版權分類 ==",
            "",
        ]
        for folder in sorted(notes):
            lines += [f"{folder}（{counts.get(folder, 0)} 首）"]
            lines += [f"  {note}" for note in notes[folder]] + [""]
        lines += [
            "== 其他注意 ==",
            "",
            "- 所有歌曲的原始頁面都記在清單裡。上傳 YouTube 若被 Content ID 聲明，",
            "  拿原始頁面與授權條款去申訴即可（CC 授權的歌偶爾會被發行商誤登記）。",
            "- 「禁止改作（ND）」的歌沒有收：音樂配進影片在 CC 條款裡算改作。",
            f"- 「{_PERSONAL_FOLDER}」裡的歌是手動從 Pixabay 等平台下載的，",
            "  那些平台禁止把音檔原封不動轉給別人；分享配樂庫時請排除這個資料夾，",
            "  朋友要用就照清單上的原始頁面自己下載。",
            "",
        ]
        _atomic_write(os.path.join(self.root, README_TXT), "\n".join(lines))


def _atomic_write(path, text):
    with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(path + ".tmp", path)


def _short_id(rec_id):
    return re.sub(r"[^0-9A-Za-z]", "", rec_id.split(":", 1)[-1])[:8] or "x"


# ---------------------------------------------------------------------------
# 收集流程
# ---------------------------------------------------------------------------

def search_params(tags, page, options):
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


def collect(library, client, moods, options, log=print):
    """每個情境搜到 per_mood 首為止（已經在配樂庫裡的也算數，重跑會接續）。

    回傳這次新找到的紀錄。額度用完時提早結束，已找到的照樣回傳。
    """
    found = []
    seen = set(library.records)
    skipped = Counter()
    mood_table = {name: search for name, search, _ in MOODS}
    for mood in moods:
        have = sum(1 for r in library.records.values() if r.get("query_mood") == mood)
        need = options["per_mood"] - have
        if need <= 0:
            log(f"【{mood}】配樂庫已有 {have} 首，跳過")
            continue
        got = 0
        for page in range(1, MAX_PAGES + 1):
            try:
                data = client.search(search_params(mood_table[mood], page, options))
            except RateLimited as error:
                log(f"\nOpenverse 查詢額度暫時用完（要等 {error.args[0]} 秒以上）。"
                    "已找到的都會存好，晚點再執行同一個指令就會接續。")
                _log_skips(skipped, log)
                return found, True
            except urllib.error.HTTPError as error:
                if error.code == 400 and page > 1:
                    break   # 翻到頁數上限
                raise
            results = data.get("results") or []
            for item in results:
                rec = record_from_openverse(item, query_mood=mood)
                if rec["id"] in seen:
                    continue
                seen.add(rec["id"])
                reason = skip_reason(rec, options)
                if reason:
                    skipped[reason] += 1
                    continue
                found.append(rec)
                got += 1
                if got >= need:
                    break
            if got >= need or not results or page >= (data.get("page_count") or 0):
                break
        log(f"【{mood}】新找到 {got} 首" + ("" if got >= need else "（搜尋結果只有這些）"))
    _log_skips(skipped, log)
    return found, False


def _log_skips(skipped, log):
    if skipped:
        detail = "、".join(f"{reason} {count} 首" for reason, count in skipped.most_common())
        log(f"略過：{detail}")


def download_all(library, records, http, delay=0.5, sleep=time.sleep, log=print):
    ok = failed = 0
    try:
        for index, rec in enumerate(records, 1):
            library.add(rec)
            library.assign_path(rec)
            dest = library.abspath(rec)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            log(f"[{index}/{len(records)}] {rec['path']}")
            for attempt in range(3):
                try:
                    http.download(rec["audio_url"], dest)
                    rec["status"] = STATUS_DONE
                    ok += 1
                    break
                except OSError as error:   # 含 URLError、HTTPError、逾時
                    if attempt < 2 and not isinstance(error, NotAudioError):
                        sleep(2 ** (attempt + 1))
                        continue
                    rec["status"] = STATUS_FAILED
                    failed += 1
                    log(f"  下載失敗：{error}")
                    break
            if index % 10 == 0:
                library.save()
            if delay:
                sleep(delay)
    finally:
        library.save()   # 中途按 Ctrl+C 也不會整批白抓
    return ok, failed


def pending_records(library):
    return [r for r in library.sorted_records()
            if r.get("origin") == "openverse" and not library.has_file(r["id"])]


# ---------------------------------------------------------------------------
# 匯入手動下載的檔案（Pixabay、YouTube 音效庫…）
# ---------------------------------------------------------------------------

def expand_inputs(patterns):
    """Windows 的命令列不會幫忙展開 *.mp3，這裡自己展開；資料夾就整個掃。"""
    files = []
    for pattern in patterns:
        matches = glob.glob(pattern) or ([pattern] if os.path.exists(pattern) else [])
        for match in matches:
            if os.path.isdir(match):
                for base, _, names in os.walk(match):
                    files += [os.path.join(base, n) for n in sorted(names)]
            else:
                files.append(match)
    return [f for f in files
            if os.path.splitext(f)[1].lower().lstrip(".") in AUDIO_EXTS]


def title_from_filename(path):
    """Pixabay 的檔名像 lesfm-lofi-study-112191.mp3：去掉尾巴的數字 ID，連字號換空白。"""
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = re.sub(r"[-_ ]\d{4,}$", "", stem)
    return re.sub(r"[-_]+", " ", stem).strip() or stem


def file_id(path):
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        digest.update(handle.read(1 << 20))
    digest.update(str(os.path.getsize(path)).encode())
    return f"local:{digest.hexdigest()[:16]}"


def import_files(library, paths, license_key, mood=None, style=None, move=False,
                 title=None, creator="", url="", log=print):
    done = 0
    for path in paths:
        rec_id = file_id(path)
        if library.has_file(rec_id):
            log(f"已在配樂庫裡，略過：{path}")
            continue
        name = title or title_from_filename(path)
        rec = {
            "id": rec_id, "origin": "import", "source": license_key,
            "title": name, "creator": creator, "creator_url": "",
            "landing_url": url, "audio_url": "",
            "ext": os.path.splitext(path)[1].lower().lstrip("."),
            "license": license_key, "license_version": "",
            "license_url": "https://pixabay.com/service/license-summary/"
            if license_key == "pixabay" else "",
            "tags": [], "genres": [],
            "moods": [mood] if mood else classify_moods(title=name),
            "style": style or classify_style(title=name),
            "vocal": None, "speed": "", "duration": None,
            "query_mood": "", "path": "", "status": STATUS_PLANNED,
        }
        library.add(rec)
        library.assign_path(rec)
        dest = library.abspath(rec)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        (shutil.move if move else shutil.copy2)(path, dest)
        rec["status"] = STATUS_DONE
        done += 1
        log(f"{path} → {rec['path']}")
    library.save()
    return done


# ---------------------------------------------------------------------------
# 命令列
# ---------------------------------------------------------------------------

def _options_from_args(args):
    licenses = COMMERCIAL_LICENSES if args.commercial_only else ALL_USABLE_LICENSES
    return {
        "licenses": licenses,
        "per_mood": args.per_mood,
        "min_sec": args.min_sec,
        "max_sec": args.max_sec,
        "allow_vocal": args.allow_vocal,
        "allow_ogg": args.allow_ogg,
        "sources": [s for s in (args.sources or "").split(",") if s],
    }


def _select_moods(text):
    if not text:
        return list(MOOD_NAMES)
    moods = [m.strip() for m in re.split(r"[,，、]", text) if m.strip()]
    unknown = [m for m in moods if m not in MOOD_NAMES]
    if unknown:
        raise SystemExit(f"不認得的情境：{'、'.join(unknown)}。可用：{'、'.join(MOOD_NAMES)}")
    return moods


def _make_http(args):
    http = Http()
    client_id = args.client_id or os.environ.get("OPENVERSE_CLIENT_ID")
    secret = args.client_secret or os.environ.get("OPENVERSE_CLIENT_SECRET")
    if client_id and secret:
        http.token = fetch_token(http, client_id, secret)
        print("已使用 Openverse 金鑰（額度較高）")
    return http


def cmd_fetch(args):
    library = Library(args.out, parse_layout(args.layout))
    options = _options_from_args(args)
    http = _make_http(args)
    client = Openverse(http, delay=args.delay)
    found, limited = collect(library, client, _select_moods(args.moods), options)
    if args.dry_run:
        for rec in found:
            library.add(rec)
            library.assign_path(rec)
        library.save()
        print(f"\n預覽完成：新找到 {len(found)} 首，還沒下載。"
              f"清單在 {os.path.join(args.out, CATALOG_CSV)}；"
              f"確認後執行 download 指令下載。")
        return 0
    ok, failed = download_all(library, found, http, delay=args.download_delay)
    print(f"\n完成：下載 {ok} 首" + (f"、失敗 {failed} 首（再跑 download 可補抓）"
                                   if failed else "") + f"，存在 {args.out}")
    return 2 if limited else 0


def cmd_download(args):
    library = Library(args.out, parse_layout(args.layout))
    records = pending_records(library)
    if not records:
        print("沒有待下載的歌曲。")
        return 0
    ok, failed = download_all(library, records, Http(), delay=args.download_delay)
    print(f"\n完成：下載 {ok} 首" + (f"、失敗 {failed} 首" if failed else ""))
    return 1 if failed else 0


def cmd_import(args):
    paths = expand_inputs(args.files)
    if not paths:
        print("找不到音檔。")
        return 1
    library = Library(args.out, parse_layout(args.layout))
    done = import_files(library, paths, args.license, mood=args.mood,
                        style=args.style, move=args.move, title=args.title,
                        creator=args.artist or "", url=args.url or "")
    print(f"\n完成：匯入 {done} 首")
    return 0


def cmd_register(args):
    data = post_json(f"{API_BASE}/auth_tokens/register/", {
        "name": args.name, "email": args.email,
        "description": args.description})
    print(f"""註冊成功。下面兩串只會顯示這一次，請自己記下來（不要放進配樂庫資料夾，
免得跟著分享出去）：

  client_id     = {data['client_id']}
  client_secret = {data['client_secret']}

1. 到 {args.email} 收信，點驗證連結；沒驗證前額度跟匿名一樣。
2. Windows 設成環境變數（設完要開新的命令列視窗）：
     setx OPENVERSE_CLIENT_ID {data['client_id']}
     setx OPENVERSE_CLIENT_SECRET {data['client_secret']}
   macOS／Linux 把 export OPENVERSE_CLIENT_ID=… 寫進 ~/.zshrc 或 ~/.bashrc。
之後 fetch 就會自動使用金鑰。""")
    return 0


def cmd_tags(_args):
    print("情境（--moods、--mood 可用）：")
    for name, search, _ in MOODS:
        print(f"  {name}：{', '.join(search)}")
    print("\n風格（--style 可用）：")
    for name, words in STYLES:
        print(f"  {name}：{', '.join(words[:8])}…")
    print("\n版權分類：")
    for key, lic in LICENSE_CLASSES.items():
        print(f"  {key:9} {lic.folder}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="搜尋開放授權的剪輯配樂，依版權／情境／風格分類存放。")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--out", default="配樂庫", help="配樂庫資料夾（預設：配樂庫）")
        p.add_argument("--layout", default="license/mood/style",
                       help="資料夾層次，預設 license/mood/style（版權/情境/風格）")
        p.add_argument("--download-delay", type=float, default=0.5,
                       help="每首下載之間暫停幾秒（預設 0.5）")

    p = sub.add_parser("fetch", help="搜尋並下載")
    common(p)
    p.add_argument("--moods", help="只抓這些情境，逗號分隔，例如 放鬆療癒,輕鬆愉快")
    p.add_argument("--per-mood", type=int, default=10,
                   help="每個情境收幾首（預設 10；重跑會補到這個數字）")
    p.add_argument("--commercial-only", action="store_true",
                   help="只收可商用的（CC0、公眾領域、CC BY、CC BY-SA）")
    p.add_argument("--allow-vocal", action="store_true",
                   help="也收有人聲的歌（預設只收純音樂，免得蓋過旁白）")
    p.add_argument("--allow-ogg", action="store_true",
                   help="也收 ogg／opus 格式（部分剪輯軟體不支援）")
    p.add_argument("--min-sec", type=int, default=30, help="最短秒數（預設 30）")
    p.add_argument("--max-sec", type=int, default=600, help="最長秒數（預設 600）")
    p.add_argument("--sources", help="限定來源，例如 jamendo（預設不限）")
    p.add_argument("--dry-run", action="store_true", help="只產生清單，不下載")
    p.add_argument("--delay", type=float, default=1.5, help="API 查詢間隔秒數")
    p.add_argument("--client-id", help="Openverse 金鑰（或設環境變數 OPENVERSE_CLIENT_ID）")
    p.add_argument("--client-secret", help="或設環境變數 OPENVERSE_CLIENT_SECRET")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("download", help="下載清單裡還沒下載或失敗的歌")
    common(p)
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("import", help="把手動下載的音檔歸進同一套分類")
    common(p)
    p.add_argument("files", nargs="+", help="音檔或資料夾，可用 *.mp3")
    p.add_argument("--license", choices=IMPORT_LICENSES, default="pixabay",
                   help="這批檔案的授權（預設 pixabay；ytal＝YouTube 音效庫）")
    p.add_argument("--mood", help="指定情境（不指定就從檔名猜）")
    p.add_argument("--style", help="指定風格（不指定就從檔名猜）")
    p.add_argument("--title", help="指定曲名（單一檔案時用）")
    p.add_argument("--artist", help="作者（CC 授權需要標註時請填）")
    p.add_argument("--url", help="原始頁面網址（CC 授權需要標註時請填）")
    p.add_argument("--move", action="store_true", help="用搬移代替複製")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("register", help="申請免費的 Openverse 金鑰（額度較高）")
    p.add_argument("--name", required=True,
                   help="應用程式名稱，全站不可重複，例如 bgm-collector-你的名字")
    p.add_argument("--email", required=True, help="收驗證信的信箱")
    p.add_argument("--description", default=(
        "Personal tool that builds a categorized library of openly licensed "
        "background music for video editing."), help="用途說明")
    p.set_defaults(func=cmd_register)

    p = sub.add_parser("tags", help="列出可用的情境、風格與版權分類")
    p.set_defaults(func=cmd_tags)
    return parser


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ValueError as error:
        print(error)
        return 1
    except urllib.error.HTTPError as error:
        detail = error.read(500).decode("utf-8", "replace") if error.fp else ""
        print(f"API 回應錯誤 {error.code}：{error.reason} {detail}".rstrip())
        return 1
    except urllib.error.URLError as error:
        print(f"連不上網路：{error.reason}")
        return 1
    except KeyboardInterrupt:
        print("\n已中斷。已下載的都記在清單裡，再跑一次會接續。")
        return 130


if __name__ == "__main__":
    sys.exit(main())
