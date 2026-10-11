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
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# 授權、情境、風格的分類規則與 Openverse 連線，跟剪輯器的線上配樂庫共用
# （subtitle/musiclib.py）：同一首歌在兩邊分到的類別一樣。
from subtitle import musiclib  # noqa: E402
from subtitle.musiclib import (  # noqa: E402
    ALL_USABLE_LICENSES, AUDIO_EXTS, COMMERCIAL_LICENSES, LICENSE_CLASSES, MAX_PAGES,
    MOOD_NAMES, MOODS, STYLES, Http, NotAudioError, Openverse, RateLimited,
    attribution_line, classify_moods, classify_style, format_duration, license_label,
    post_json, search_params, skip_reason)

API_BASE = "https://api.openverse.org/v1"
USER_AGENT = ("SRT-Subtitle-Generator-BGMCollector/1.0 "
              "(+https://github.com/yee645/SRT-Subtitle-Generator)")

CATALOG_JSON = "配樂清單.json"
CATALOG_CSV = "配樂清單.csv"
CREDITS_TXT = "CREDITS_標註文字.txt"
README_TXT = "README_授權說明.txt"

STATUS_DONE = "已下載"
STATUS_PLANNED = "未下載（預覽）"
STATUS_FAILED = "下載失敗"

IMPORT_LICENSES = ["pixabay", "ytal"] + ALL_USABLE_LICENSES


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


# ---------------------------------------------------------------------------
# Openverse
# ---------------------------------------------------------------------------

def record_from_openverse(item, query_mood=None):
    """musiclib 的配樂紀錄，再加上收集器自己的欄位：存放路徑與下載狀態。"""
    return dict(musiclib.record_from_openverse(item, query_mood),
                path="", status=STATUS_PLANNED)


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
            f"- 「{LICENSE_CLASSES['pixabay'].folder}」裡的歌是手動從 Pixabay 等平台下載的，",
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
    http = Http(user_agent=USER_AGENT)
    client_id = args.client_id or os.environ.get("OPENVERSE_CLIENT_ID")
    secret = args.client_secret or os.environ.get("OPENVERSE_CLIENT_SECRET")
    if client_id and secret:
        http.token = musiclib.fetch_token(http, client_id, secret, api_base=API_BASE)
        print("已使用 Openverse 金鑰（額度較高）")
    return http


def cmd_fetch(args):
    library = Library(args.out, parse_layout(args.layout))
    options = _options_from_args(args)
    http = _make_http(args)
    client = Openverse(http, delay=args.delay, api_base=API_BASE)
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
    ok, failed = download_all(library, records, Http(user_agent=USER_AGENT),
                              delay=args.download_delay)
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
        "description": args.description}, user_agent=USER_AGENT)
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
