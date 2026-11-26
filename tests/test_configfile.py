# -*- coding: utf-8 -*-
"""
3.0 之後 A-5：config.json 的讀寫，以及跑測試時不准動到使用者的設定檔。

config.json 存著 API 金鑰、習慣設定、自動修正詞庫；一般版與新介面共用同一份，而且可以同時開著。這裡守：

1. 存檔一次換上：存到一半失敗（設定裡放了 JSON 存不了的東西、寫到一半磁碟滿），磁碟上原本那份原封不動，
   資料夾裡也不留暫存檔；兩個程式同時存檔、同時去讀，讀到的永遠是完整的一份；Windows 上換檔被正在讀的
   另一邊擋住時等一下再試，一直換不上才丟出去。
2. 讀不懂的設定檔不會被默默蓋掉：改名成 config.json.broken 留著（已經有一份就 .broken-2…）、寫進記錄檔，
   照舊用預設值開；讀不到（權限、被鎖住）的檔案本身沒壞，不動它。給了 fallback（新介面存檔時給的是開啟時
   讀到的那份）就用它代替，不拿預設值蓋掉記憶體裡的設定。
3. 刪掉的習慣設定「預設」重開後不會又出現；存的那份裡有「預設」時，照舊用預設值補上舊版沒有的欄位。
4. load_config 回傳的設定跟模組的預設值（DEFAULT_CONFIG）不共用任何內層物件：改了不會改到預設值。
5. tests/run_all.py：測試動到個人資料檔（config.json、生字本）會被換回原樣並算失敗；每個測試拿到固定字型的設定。
6. .github/workflows/tests.yml：每個 PR 在 Linux＋Xvfb 跑全套。
"""
import copy
import errno
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


PRISTINE = copy.deepcopy(config.DEFAULT_CONFIG)  # 第 4 段比對用：測試開始時的預設值
WORK = tempfile.mkdtemp()


def fresh(name):
    """換一個空資料夾當設定檔所在的地方，回傳那個資料夾。"""
    folder = os.path.join(WORK, name)
    os.makedirs(folder)
    config.CONFIG_PATH = os.path.join(folder, "config.json")
    return folder


def write_text(text, path=None):
    with open(path or config.CONFIG_PATH, "w", encoding="utf-8") as fh:
        fh.write(text)


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def peek(path):
    """檔案內容；不存在或讀不懂回傳 None（檢查用：舊版沒有這個檔時要回報 FAIL，不是整個當掉）。"""
    try:
        return read_text(path)
    except (OSError, ValueError):
        return None


def disk_key():
    """磁碟上那份的 API 金鑰；讀不懂（半份）回傳 None。"""
    try:
        with open(config.CONFIG_PATH, encoding="utf-8") as fh:
            return json.load(fh)["transcription"]["api_key"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


class Records(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append((record.levelno, record.getMessage()))


records = Records()
logging.getLogger("config").addHandler(records)


# ===== 1. 存檔一次換上 =====================================================

folder = fresh("atomic")
good = copy.deepcopy(config.load_config())
good["transcription"]["api_key"] = "sk-KEEP"
config.save_config(good)
check("正常存檔讀得回來", disk_key() == "sk-KEEP")

bad = copy.deepcopy(good)
bad["review"]["存不了"] = {1, 2, 3}  # set：JSON 存不了，json 寫到一半才發現
raised = None
try:
    config.save_config(bad)
except TypeError as exc:
    raised = exc
check("存不了的設定照樣丟 TypeError（呼叫端看得到）", raised is not None)
check("存到一半失敗：磁碟上原本那份原封不動（讀得懂、金鑰還在）", disk_key() == "sk-KEEP", repr(disk_key()))
check("存到一半失敗：資料夾裡沒有留下暫存檔", os.listdir(folder) == ["config.json"], str(os.listdir(folder)))

changed = copy.deepcopy(good)
changed["transcription"]["api_key"] = "sk-NEW"
real_fsync = os.fsync


def full_disk(fd):
    raise OSError(errno.ENOSPC, "No space left on device")


raised = None
os.fsync = full_disk
try:
    config.save_config(changed)
except OSError as exc:
    raised = exc
finally:
    os.fsync = real_fsync
check("寫到一半磁碟滿：丟 OSError（介面照舊顯示「設定儲存失敗」）", isinstance(raised, OSError), repr(raised))
check("寫到一半磁碟滿：磁碟上還是上一份完整的設定", disk_key() == "sk-KEEP", repr(disk_key()))
check("寫到一半磁碟滿：暫存檔清掉了", os.listdir(folder) == ["config.json"], str(os.listdir(folder)))

# Windows：另一個介面正好開著 config.json 在讀，換檔被拒絕（PermissionError）——讀完就放開了，等一下再試。
real_replace = os.replace
tries = []


def busy_twice(source, target):
    tries.append(target)
    if len(tries) <= 2:
        raise PermissionError(13, "另一個程式正在使用此檔案")
    real_replace(source, target)


def busy_forever(source, target):
    tries.append(target)
    raise PermissionError(13, "另一個程式正在使用此檔案")


raised = None
os.replace = busy_twice
try:
    config.save_config(changed)
except OSError as exc:
    raised = exc
finally:
    os.replace = real_replace
check("換檔被擋兩次（Windows 另一邊正在讀）：等一下再試、存進去",
      raised is None and disk_key() == "sk-NEW" and len(tries) == 3, f"{raised!r} tries={len(tries)}")

tries.clear()
raised = None
started = time.time()
os.replace = busy_forever
try:
    config.save_config(good)
except OSError as exc:
    raised = exc
finally:
    os.replace = real_replace
waited = time.time() - started
check("一直換不上：試幾次、等不到一秒就放棄，丟 PermissionError（介面照舊顯示存檔失敗）",
      isinstance(raised, PermissionError) and 3 <= len(tries) <= 20 and waited < 1.0,
      f"{raised!r} tries={len(tries)} waited={waited:.2f}")
check("一直換不上：磁碟上還是上一份、暫存檔清掉了",
      disk_key() == "sk-NEW" and os.listdir(folder) == ["config.json"], str(os.listdir(folder)))

# 兩個程式（一般版與新介面）同時存檔，另一邊同時在讀：讀到的永遠是完整的一份。
WRITER = r'''
import sys, time
sys.path.insert(0, sys.argv[1])
import config
config.CONFIG_PATH = sys.argv[2]
tag = sys.argv[3]
payload = {"writer": tag,
           "corrections": [{"find": f"{tag}{i}", "replace": "字" * 40, "case": False} for i in range(400)]}
deadline = time.time() + float(sys.argv[4])
errors = 0
while time.time() < deadline:
    try:
        config.save_config(payload)
    except OSError:
        errors += 1
print(errors)
'''
folder = fresh("concurrent")
config.save_config({"writer": "init"})
writers = [subprocess.Popen([sys.executable, "-c", WRITER, ROOT, config.CONFIG_PATH, tag, "1.5"],
                            stdout=subprocess.PIPE, text=True) for tag in ("tk", "qt")]
reads = torn = 0
while any(p.poll() is None for p in writers):
    reads += 1
    try:
        text = read_text(config.CONFIG_PATH)
    except FileNotFoundError:
        torn += 1
        continue
    except ValueError:  # 讀到半個中文字（UnicodeDecodeError）：一樣是半份
        torn += 1
        continue
    try:
        if json.loads(text).get("writer") not in ("init", "tk", "qt"):
            torn += 1
    except ValueError:
        torn += 1
outputs = [p.communicate()[0].strip() for p in writers]
check(f"兩個程式同時存檔、同時去讀：讀了 {reads} 次，沒有一次讀到半份或讀不到",
      reads >= 50 and torn == 0, f"torn={torn}")
check("同時存檔的兩邊都沒有存檔失敗", outputs == ["0", "0"], str(outputs))
check("同時存檔之後資料夾裡只剩 config.json", os.listdir(folder) == ["config.json"], str(os.listdir(folder)))


# ===== 2. 讀不懂的設定檔不會被默默蓋掉 =====================================

folder = fresh("broken")
HALF = '{"transcription": {"api_key": "sk-HALF'  # 寫到一半的樣子
write_text(HALF)
records.messages.clear()
loaded = config.load_config()
check("讀不懂的設定檔：照舊用預設值開（不當掉）",
      loaded["transcription"]["api_key"] == "" and loaded["active_preset"] == "預設")
broken1 = config.CONFIG_PATH + ".broken"
check("讀不懂的設定檔：原檔改名成 config.json.broken 留著，內容一字不差",
      peek(broken1) == HALF, str(os.listdir(folder)))
check("讀不懂的設定檔：config.json 讓出來了（下次存檔不會蓋掉備份）", not os.path.exists(config.CONFIG_PATH))
check("讀不懂的設定檔：記錄檔寫了一筆警告，講備份在哪",
      any(level == logging.WARNING and "config.json.broken" in msg for level, msg in records.messages),
      str(records.messages))

write_text("[1, 2, 3]")  # 讀得懂但不是設定（不是 dict）
config.load_config()
broken2 = config.CONFIG_PATH + ".broken-2"
check("又壞一次：第一份備份不被蓋掉，新的叫 config.json.broken-2",
      peek(broken1) == HALF and peek(broken2) == "[1, 2, 3]", str(sorted(os.listdir(folder))))

with open(config.CONFIG_PATH, "wb") as fh:
    fh.write(b"\xff\xfe\x00bad")  # 不是 UTF-8
config.load_config()
check("不是 UTF-8 的設定檔也一樣改名留著", os.path.exists(config.CONFIG_PATH + ".broken-3"),
      str(sorted(os.listdir(folder))))

# 給了 fallback：讀不懂時用它代替（新介面存檔時給開啟時讀到的那份）。
folder = fresh("fallback")
mine = copy.deepcopy(config.load_config())
mine["transcription"]["api_key"] = "sk-IN-MEMORY"
mine["presets"]["我的樣式"] = config.make_profile(mine["subtitle_style"], mine["segmentation"])
write_text(HALF)
got = None
try:
    got = config.load_config(fallback=mine)
except TypeError as exc:  # 舊版沒有這個參數
    print(f"（load_config 不收 fallback：{exc}）")
check("給了 fallback：讀不懂時用它，不拿預設值蓋掉記憶體裡的設定",
      got is not None and got["transcription"]["api_key"] == "sk-IN-MEMORY" and "我的樣式" in got["presets"])
check("用 fallback 時壞掉的檔照樣改名留著", os.path.exists(config.CONFIG_PATH + ".broken"))
if got is not None:
    got["transcription"]["api_key"] = "改掉"
check("fallback 回傳的是複本：改了不會動到呼叫端那份", mine["transcription"]["api_key"] == "sk-IN-MEMORY")
got = None
try:
    got = config.load_config(fallback=mine)  # 設定檔已經不在了（改名了）
except TypeError:
    pass
check("設定檔不存在時不用 fallback：照舊是預設值（刪掉設定檔＝回到預設）",
      got is not None and got["transcription"]["api_key"] == "")

# 讀不到（權限、被鎖住）：檔案本身沒壞，不動它。
folder = fresh("unreadable")
config.save_config(good)


def locked_open(path, *args, **kwargs):
    raise PermissionError(errno.EACCES, "Permission denied", path)


config.open = locked_open  # 模組層的名字蓋過內建的 open：只有 config 讀檔時會拿到
try:
    got = config.load_config()
    got_fb = None
    try:
        got_fb = config.load_config(fallback=mine)
    except TypeError:
        pass
finally:
    del config.open
check("讀不到的設定檔：照舊用預設值開", got["transcription"]["api_key"] == "")
check("讀不到的設定檔：不改名、原檔還在原處", os.listdir(folder) == ["config.json"] and disk_key() == "sk-KEEP",
      str(os.listdir(folder)))
check("讀不到又給了 fallback：用 fallback", got_fb is not None and got_fb["transcription"]["api_key"] == "sk-IN-MEMORY")


# ===== 3. 習慣設定「預設」刪掉就是刪掉 =======================================

folder = fresh("presets")
cfg = copy.deepcopy(config.load_config())
cfg["presets"]["我的樣式"] = config.make_profile(cfg["subtitle_style"], cfg["segmentation"])
del cfg["presets"]["預設"]  # 兩個介面在 >=2 組時都允許刪「預設」
cfg["active_preset"] = "我的樣式"
config.save_config(cfg)
again = config.load_config()
check("刪掉的「預設」重開後不會又出現", sorted(again["presets"]) == ["我的樣式"], str(sorted(again["presets"])))
check("選取中的習慣設定照舊", again["active_preset"] == "我的樣式", again["active_preset"])

write_text(json.dumps({"presets": {"預設": {"subtitle_style": {"font_size": 40}, "segmentation": {}}},
                       "active_preset": "預設"}, ensure_ascii=False))
again = config.load_config()
style = again["presets"]["預設"]["subtitle_style"]
check("存的「預設」少了後來才加的欄位：用預設值補上，存的值照舊",
      style["font_size"] == 40 and style["dynamic_mode"] == "off"
      and again["presets"]["預設"]["segmentation"]["max_chars_cjk"] == 18, str(style))

only = {"甲": {"subtitle_style": {"font_size": 30}, "segmentation": {}}}
write_text(json.dumps({"presets": only, "active_preset": "甲"}, ensure_ascii=False))
again = config.load_config()
check("其他名字的習慣設定照存的原樣", again["presets"] == only and again["active_preset"] == "甲",
      str(again["presets"]))

write_text(json.dumps({"presets": {}, "active_preset": "不存在"}))
again = config.load_config()
check("存的習慣設定是空的：至少留一組「預設」並選它",
      list(again["presets"]) == ["預設"] and again["active_preset"] == "預設", str(again["presets"].keys()))

write_text(json.dumps({"theme": "dark"}))
again = config.load_config()
check("舊版設定檔沒有 presets：照舊用目前的樣式建一組「預設」",
      list(again["presets"]) == ["預設"] and again["active_preset"] == "預設")


# ===== 4. 載入的設定跟預設值不共用內層物件 ===================================

folder = fresh("alias")
fresh_cfg = config.load_config()  # 沒有設定檔
fresh_cfg["transcription"]["api_key"] = "sk-LEAK"
fresh_cfg["presets"]["預設"]["subtitle_style"]["font_size"] = 99
fresh_cfg["corrections"].append({"find": "a", "replace": "b", "case": False})
write_text(json.dumps({"theme": "dark"}))  # 舊版的設定檔：少了很多區塊
partial = config.load_config()
partial["review"]["silence_gap"] = 9.9
partial["clipwatch"]["enabled"] = True
check("改了載入的設定，模組的預設值（DEFAULT_CONFIG）不跟著變", config.DEFAULT_CONFIG == PRISTINE)
os.remove(config.CONFIG_PATH)
check("再載一次拿到的是乾淨的預設值", config.load_config() == config.load_config()
      and config.load_config()["transcription"]["api_key"] == ""
      and config.load_config()["corrections"] == [])
config.DEFAULT_CONFIG.clear()
config.DEFAULT_CONFIG.update(copy.deepcopy(PRISTINE))  # 舊版會被改到：還原，免得影響下面


# ===== 5. tests/run_all.py：個人資料檔保護與固定字型 ==========================

spec = importlib.util.spec_from_file_location("run_all_under_test", os.path.join(ROOT, "tests", "run_all.py"))
run_all = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_all)

home = os.path.join(WORK, "home")  # 假裝是從原始碼跑程式的人的專案根目錄
os.makedirs(home)
own = '{"transcription": {"api_key": "sk-DEVELOPER"}}'
write_text(own, os.path.join(home, "config.json"))
bad_test = os.path.join(WORK, "test_touches_config.py")
write_text(
    "import json, os\n"
    "home = os.environ['FAKE_HOME']\n"
    "with open(os.path.join(home, 'config.json'), 'w', encoding='utf-8') as fh:\n"
    "    json.dump({'preflight': {}, 'healthcenter': {}}, fh)\n"
    "with open(os.path.join(home, 'quicktranslate_vocab.json'), 'w', encoding='utf-8') as fh:\n"
    "    fh.write('[]')\n", bad_test)
env = run_all.test_env(dict(os.environ, FAKE_HOME=home))
code, touched = run_all.run_one(bad_test, [home], env)
check("測試把 config.json 換成兩個區塊：被抓出來",
      os.path.join(home, "config.json") in touched, str(touched))
check("被動到的 config.json 換回原樣（金鑰還在）", peek(os.path.join(home, "config.json")) == own)
check("測試建出來的生字本刪掉了（原本沒有）", not os.path.exists(os.path.join(home, "quicktranslate_vocab.json"))
      and os.path.join(home, "quicktranslate_vocab.json") in touched)
check("測試本身的結束碼照實回傳", code == 0)

quiet_test = os.path.join(WORK, "test_quiet.py")
write_text("print('PASS 什麼都沒動')\n", quiet_test)
code, touched = run_all.run_one(quiet_test, [home], env)
check("沒動到的測試：不算動到", code == 0 and touched == [])
check("run_all 守的是目前的資料夾與專案根目錄", "os.getcwd()" in read_text(os.path.join(ROOT, "tests", "run_all.py"))
      and "realpath(ROOT)" in read_text(os.path.join(ROOT, "tests", "run_all.py")))

fonts_conf = os.path.join(ROOT, "tests", "fonts.conf")
check("每個測試拿到固定字型的設定（tests/fonts.conf）",
      run_all.test_env({})["FONTCONFIG_FILE"] == fonts_conf and os.path.exists(fonts_conf))
check("已經有設 FONTCONFIG_FILE 的照用", run_all.test_env({"FONTCONFIG_FILE": "/x.conf"})["FONTCONFIG_FILE"] == "/x.conf")
for name in ("test_v220.py", "test_screentranslate_gui.py", "test_qt_player.py"):
    check(f"{name} 單獨跑也套上固定字型", "FONTCONFIG_FILE" in read_text(os.path.join(ROOT, "tests", name)))

if shutil.which("fc-match") and shutil.which("fc-list"):
    plain = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True,
                           env={k: v for k, v in os.environ.items() if k != "FONTCONFIG_FILE"}).stdout
    pinned = subprocess.run(["fc-match", "-f", "%{family}", "Microsoft JhengHei"], capture_output=True, text=True,
                            env=dict(os.environ, FONTCONFIG_FILE=fonts_conf))
    check("固定字型的設定讀得懂（fc-match 正常結束）", pinned.returncode == 0, pinned.stderr[-200:])
    if "Inter" in plain:
        check("這台有 Inter：固定之後 Microsoft JhengHei 不會退到 Inter",
              "Inter" not in pinned.stdout, pinned.stdout)
    else:
        print("SKIP 這台沒有 Inter：略過「不會退到 Inter」")
else:
    print("SKIP 沒有 fontconfig 工具：略過字型設定的實測")


# ===== 6. 每個 PR 都跑全套 =================================================

workflow_path = os.path.join(ROOT, ".github", "workflows", "tests.yml")
workflow = read_text(workflow_path) if os.path.exists(workflow_path) else ""
check(".github/workflows/tests.yml 存在、PR 觸發", "pull_request" in workflow)
check("CI 在 Xvfb 下跑 tests/run_all.py", "xvfb-run" in workflow and "tests/run_all.py" in workflow)
check("CI 裝了 Tk、PySide6、sv-ttk、ffmpeg、tesseract、x11-utils 與兩套字型",
      all(word in workflow for word in ("python3-tk", "PySide6", "sv-ttk", "ffmpeg", "tesseract-ocr-chi-tra",
                                        "x11-utils", "fonts-dejavu-core", "fonts-wqy-zenhei")))
check("CI 用 Ubuntu 24.04 的 Python 3.12（跟新介面打包同一版）", "ubuntu-24.04" in workflow
      and "/usr/bin/python3 -m venv" in workflow)


shutil.rmtree(WORK, ignore_errors=True)
print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("設定檔讀寫測試全數通過。")
