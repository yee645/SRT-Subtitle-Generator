# -*- coding: utf-8 -*-
"""
`subtitle/speech.py` 測試：朗讀（文字轉語音）。

ROADMAP 第 9 項第一階段第 5 項（介面）的前置：「朗讀」按鈕底下要有東西。

**真的發出聲音那一段在開發環境驗不到**——這台機器沒有 Windows、沒有
macOS，Linux 上也一個語音引擎都沒裝。所以測試分成：

* 純函式（設定、文字整理、命令組裝、PowerShell 編碼）離線測完；
* **行程管理是真的在跑**：注入的 `popen` 會把命令換成一個真的
  Python 子行程，起停、換句、退路重跑全部是真的 subprocess；
* **「這台機器沒有引擎」那條路不是模擬**——那就是這台機器的真實狀態。

守住五件事：

  1. **要念的文字絕不出現在任何語法位置。** 使用者從任意畫面框來的文字
     裡什麼都可能有；PowerShell 腳本裡只能看到 base64。
  2. **第二句要把第一句停掉**，不能疊著念。
  3. **「沒有引擎」和「念失敗」是兩種例外、兩種說法**，前者要講得出去
     哪裡裝。
  4. **截掉的字數要回報**，不能默默念一半。
  5. **指定語音被拒時退回預設語音再念一次**，而且只在真的指定過語音時
     才退——否則只是把同一個失敗再做一遍。
"""
import base64
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import speech as sp

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def guarded(name, fn):
    """
    跑一段會起真行程的測試；裡面丟出例外就記成失敗、繼續往下跑。

    沒有這層的話，一個意外例外會讓整個檔案在那裡中止，後面的斷言一條
    都不會跑，而輸出看起來只是「少了幾行」（test_screencap.py 踩過）。
    """
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - 就是要全部接住
        check(name + "（區塊內丟出例外）", False, f"{type(exc).__name__}: {exc}")


# ===== 1. 設定 ==========================================================
base = sp.resolve_speech_settings(None)
check("預設語速是正常速度", base["rate"] == 0)
check("預設有上限字數", base["max_chars"] == 1000)
wild = sp.resolve_speech_settings(
    {"speech": {"rate": 99, "volume": -5, "max_chars": 3, "bogus": 1}})
check("語速夾到 10", wild["rate"] == 10)
check("音量夾到 0", wild["volume"] == 0)
check("字數上限夾到下限 50", wild["max_chars"] == 50)
check("不認得的鍵被丟掉", "bogus" not in wild)

# ===== 2. 要念的文字 =====================================================
body, dropped = sp.prepare_text("Hello\x00\x07 world\n\n  again", base)
check("控制字元與多餘空白清掉", body == "Hello world again", repr(body))
check("短文字不截", dropped == 0)

small = sp.resolve_speech_settings({"speech": {"max_chars": 50}})
long_text = "第一句話在這裡。" * 20          # 160 字
body, dropped = sp.prepare_text(long_text, small)
check("長文字截到上限以內", len(body) <= 50, len(body))
check("截在句子邊界", body.endswith("。"), body[-3:])
check("回報截掉的字數且兩者加起來是原長",
      dropped > 0 and len(body) + dropped == len(long_text),
      (len(body), dropped))

no_boundary = "a" * 200
body, dropped = sp.prepare_text(no_boundary, small)
check("找不到句界就照上限截，不會少念一大截",
      len(body) == 50 and dropped == 150, (len(body), dropped))

check("純標點沒東西可念", not sp.has_speakable_text(" ，。!? \n"))
check("中文字算可念", sp.has_speakable_text("。好。"))

# ===== 3. 引擎偵測 =======================================================
real = sp.find_engine()
if sys.platform.startswith("linux"):
    check("這台機器真的沒有引擎（真實狀態，不是模擬）", real is None, real)
    msg = sp.describe_engine(real)
    check("沒有引擎時狀態列講得出安裝指令",
          "無法使用" in msg and "espeak-ng" in msg, msg)

every = lambda exe: "/usr/bin/" + exe
eng = sp.find_engine("linux", which=every)
check("Linux 優先 spd-say", eng and eng["exe"] == "spd-say", eng)
only_espeak = lambda exe: "/usr/bin/espeak" if exe == "espeak" else None
eng = sp.find_engine("linux", which=only_espeak)
check("只有舊版 espeak 也找得到", eng and eng["kind"] == "espeak"
      and eng["path"] == "/usr/bin/espeak", eng)
eng = sp.find_engine("win32", which=lambda e: "C:/ps.exe" if e == "powershell" else None)
check("Windows 找 powershell", eng and eng["kind"] == "sapi", eng)
check("Windows 沒有 powershell 時訊息講的是 PowerShell",
      "PowerShell" in sp.unavailable_message("win32"))

# ===== 4. 命令組裝（不經 shell、文字在 -- 之後） =========================
hostile = "-rf `whoami` $(id) '\"; Remove-Item C:\\ -Recurse #\n第二行"
espeak = {"kind": "espeak", "exe": "espeak-ng", "path": "/usr/bin/espeak-ng"}
cmd = sp.build_command(espeak, hostile, "zh-TW", base)
check("回傳陣列", isinstance(cmd, list))
check("文字原封不動當最後一個參數", cmd[-1] == hostile)
check("文字前面有 --，開頭是 - 也不會被當成選項", cmd[-2] == "--")
check("中文用 espeak-ng 的 cmn", cmd[cmd.index("-v") + 1] == "cmn", cmd)
cmd = sp.build_command(espeak, "hi", "xx-YY", base)
check("查不到的語言不指定語音（不硬猜代碼）", "-v" not in cmd, cmd)
cmd = sp.build_command(espeak, "hi", "zh-TW", base, with_voice=False)
check("with_voice=False 真的拿掉語音", "-v" not in cmd, cmd)
cmd = sp.build_command({"kind": "spd", "exe": "spd-say"}, "hi", "ja", base)
check("spd-say 帶 -w（行程結束＝念完）", "-w" in cmd, cmd)
say = sp.build_command({"kind": "say", "exe": "say"}, "hi", "zh-TW", base)
check("macOS 不硬塞猜來的語音名稱", "-v" not in say, say)
for kind in ("spd", "say", "espeak"):
    c = sp.build_command({"kind": kind, "exe": kind}, hostile, "ja", base)
    check(f"{kind}：文字是最後一個參數且前面是 --",
          c[-1] == hostile and c[-2] == "--", c[-3:])

fast = sp.resolve_speech_settings({"speech": {"rate": 10}})
slow = sp.resolve_speech_settings({"speech": {"rate": -10}})
f = sp.build_command(espeak, "hi", None, fast)
s = sp.build_command(espeak, "hi", None, slow)
check("語速真的有傳到命令裡（快 > 慢）",
      int(f[f.index("-s") + 1]) > int(s[s.index("-s") + 1]), (f, s))

# ===== 5. PowerShell：文字只以 base64 出現 ===============================
sapi = {"kind": "sapi", "exe": "powershell", "path": "C:/ps.exe"}
cmd = sp.build_command(sapi, hostile, "ja", base)
check("用 -EncodedCommand 送腳本", "-EncodedCommand" in cmd, cmd)
check("命令列上完全看不到原文",
      not any("whoami" in part or "Remove-Item" in part for part in cmd))
script = base64.b64decode(cmd[-1]).decode("utf-16-le")
check("解回來的腳本裡也看不到原文",
      "whoami" not in script and "Remove-Item" not in script)
b64 = script.split("FromBase64String('")[1].split("'")[0]
check("腳本裡那段 base64 解回來和原文一字不差",
      base64.b64decode(b64).decode("utf-8") == hostile)
check("日文挑 ja 開頭的語音", "StartsWith('ja')" in script, script)
check("挑不到語音也照念（if 包住 SelectVoice）",
      "if($v){$s.SelectVoice" in script)
nov = base64.b64decode(sp.build_command(sapi, "hi", "ja", base,
                                        with_voice=False)[-1]).decode("utf-16-le")
check("with_voice=False 時腳本不挑語音", "GetInstalledVoices" not in nov)

worst = "語" * base["max_chars"]
cmd = sp.build_command(sapi, worst, "zh-TW", base)
total = sum(len(p) + 1 for p in cmd)
check("上限字數的中文仍在 Windows 命令列長度限制內（32767）",
      total < 32767, total)

# ===== 6. 行程管理（真的子行程） =========================================
launched = []


def real_popen(behaviour):
    """把引擎命令換成真的 Python 子行程；behaviour(cmd) 決定它做什麼。"""
    def _popen(cmd, **kw):
        launched.append((cmd, kw))
        code = behaviour(cmd)
        return subprocess.Popen([sys.executable, "-c", code], **kw)
    return _popen


long_sleep = lambda cmd: "import time; time.sleep(30)"


def _block_start_stop():
    spk = sp.Speaker(engine=espeak, settings=base, popen=real_popen(long_sleep))
    check("有引擎時 available", spk.available())
    spk.speak("first sentence", "en")
    first = spk._proc
    check("開始念之後 is_speaking", spk.is_speaking())
    check("不經 shell", "shell" not in launched[-1][1])
    check("stdin 關掉（引擎不會卡在等輸入）",
          launched[-1][1].get("stdin") is subprocess.DEVNULL)
    spk.speak("second sentence", "en")
    time.sleep(0.2)
    check("第二句把第一句停掉", first.poll() is not None, first.poll())
    check("第二句在念", spk.is_speaking())
    spk.stop()
    check("stop 之後不再念", not spk.is_speaking())
    spk.stop()
    check("重複 stop 不會出事", True)


guarded("起停與換句", _block_start_stop)


def _block_retry():
    # 退路：指定語音就失敗、不指定就成功
    del launched[:]
    picky = lambda cmd: ("import sys; sys.stderr.write('unknown voice'); sys.exit(1)"
                         if "-v" in cmd else "pass")
    spk = sp.Speaker(engine=espeak, settings=base, popen=real_popen(picky))
    spk.speak("hello", "zh-TW")
    code = spk.wait(timeout=10)
    check("語音被拒後自動退回預設語音而成功", code == 0, code)
    check("前後剛好啟動兩次", len(launched) == 2, len(launched))
    check("第二次真的沒帶語音", "-v" not in launched[1][0], launched[1][0])
    check("第一次的錯誤訊息留下來了", "unknown voice" in spk.last_error,
          spk.last_error)


guarded("語音被拒的退路", _block_retry)


def _block_no_retry():
    # 沒指定語音就失敗：不要重跑同一個失敗
    del launched[:]
    always_fail = lambda cmd: "import sys; sys.exit(3)"
    spk = sp.Speaker(engine=espeak, settings=base, popen=real_popen(always_fail))
    spk.speak("hello", "xx-YY")          # 查不到的語言 → 本來就沒指定語音
    code = spk.wait(timeout=10)
    check("沒指定語音時失敗就是失敗，回傳真實結束碼", code == 3, code)
    check("而且只啟動一次", len(launched) == 1, len(launched))


guarded("沒指定語音不重跑", _block_no_retry)


# ===== 7. 兩種例外、兩種說法 ============================================
nobody = sp.Speaker(engine=None, settings=base)
check("沒有引擎時 not available", not nobody.available())
try:
    nobody.speak("hello")
    check("沒有引擎時要丟例外", False)
except sp.SpeechUnavailable as exc:
    check("沒有引擎丟 SpeechUnavailable", True)
    check("SpeechUnavailable 也是 SpeechError（呼叫端可以一起接）",
          isinstance(exc, sp.SpeechError))
except sp.SpeechError as exc:
    check("沒有引擎丟 SpeechUnavailable（不是一般 SpeechError——兩者的下一步不同）",
          False, str(exc))

spk = sp.Speaker(engine=espeak, settings=base, popen=real_popen(long_sleep))
try:
    spk.speak("  。，  ")
    check("空內容要丟例外", False)
except sp.SpeechUnavailable:
    check("空內容不能說成「沒有引擎」", False)
except sp.SpeechError as exc:
    check("空內容丟一般 SpeechError 並說明", "沒有可以念" in str(exc))
check("空內容不會啟動任何行程", spk._proc is None)

small_spk = sp.Speaker(engine=espeak, settings=small, popen=real_popen(long_sleep))
dropped = small_spk.speak(long_text, "zh-TW")
small_spk.stop()
check("speak 回報截掉的字數", dropped > 0, dropped)


def broken_popen(cmd, **kw):
    raise FileNotFoundError("espeak-ng")


spk = sp.Speaker(engine=espeak, settings=base, popen=broken_popen)
try:
    spk.speak("hello")
    check("引擎被移除時要丟例外", False)
except sp.SpeechError as exc:
    check("啟動失敗轉成 SpeechError（不是裸 OSError）",
          "啟動失敗" in str(exc))
except OSError as exc:
    check("啟動失敗轉成 SpeechError（不是裸 OSError）", False, repr(exc))
check("啟動失敗後不殘留半個狀態", not spk.is_speaking())

print()
if failures:
    print(f"{len(failures)} 項失敗")
    sys.exit(1)
print("全部通過")
