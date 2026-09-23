# -*- coding: utf-8 -*-
"""
朗讀（文字轉語音）：把原文或譯文念出來。

使用者要的「支援朗讀」是學習用途——看得懂還不夠，外語要聽得出來才學得
起來。這一層只做「把一段文字念出來」，不碰介面。

**全程在本機，不連網。** 三個平台用的都是作業系統自己就有的語音合成，
不打 API、不上傳文字。這點很重要：朗讀的對象常常是剛從畫面上 OCR 下來
的內容，那些內容已經在 `subtitle/screencap.py` 的隱私規則底下了，不該
為了念一句話又把它送出去一次。

**三個平台各用各的辦法，但介面一樣**：

| 平台 | 作法 | 要不要另外安裝 | 開發時能不能驗 |
|---|---|---|---|
| Windows | `powershell` ＋ `System.Speech`（SAPI） | 不用，系統內建 | **不行**（沒有 Windows） |
| macOS | 內建的 `say`（**不指定語音**，理由見 `build_command`） | 不用 | 不行（沒有 macOS） |
| Linux | `spd-say` → `espeak-ng` → `espeak`（依序找） | 要，多數桌面發行版預裝 | **這台機器上一個都沒有** |

所以這個模組刻意拆成**驗得到的那一半**與**驗不到的那一半**，作法沿用
`subtitle/tesseract_setup.py` 的教訓：

* **驗得到**：引擎偵測、命令組裝、語速／音量換算、文字長度處理、行程的
  起停與換句（拿一個「假引擎」跑真的 subprocess，行程管理那一段是真的
  在跑）、**以及「這台機器上根本沒有引擎」這條路**——那不是模擬，這台
  機器的真實狀態就是沒有。
* **驗不到**：SAPI 與 `say` 真的發出聲音。這兩段照實標記，不要在 PR 裡
  寫成已驗證。

**不用 shell、不做字串拼接。** 要念的文字是使用者從任意畫面上框來的，
裡面有什麼字元都不奇怪。外部命令一律用參數陣列；PowerShell 那條更進一
步——文字先 base64 編碼再在腳本裡解回來，腳本本身用 `-EncodedCommand`
送出去，所以文字**從頭到尾沒有出現在任何一層的語法位置**，引號、換行、
反引號都傷不到它，順便也不必動到執行原則（ExecutionPolicy）。

零 GUI 依賴，供查譯面板與 CLI 共用。
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import sys
from typing import Callable, Optional

# 使用者可調參數（config["speech"]）。
DEFAULT_SPEECH = {
    "enabled": True,
    # 語速。-10（慢）~ 10（快），0 是各引擎自己的正常速度。學外語的人
    # 常常要調慢，所以這個值一定要露出來給使用者調。
    "rate": 0,
    "volume": 100,     # 0~100
    # 單次朗讀的字數上限。理由和 quicktranslate 的 max_chars 同一個——
    # 使用者可能一失手選到整份逐字稿，念下去要好幾分鐘而且停不下來。
    # 超過就截到這個長度並回報截掉幾個字，不要默默念一半。
    "max_chars": 1000,
}

_RATE_RANGE = (-10, 10)
_VOLUME_RANGE = (0, 100)
_MAX_CHARS_RANGE = (50, 20000)

# 起停用的逾時；正常情形下這兩個動作都是瞬間的。
_TERM_TIMEOUT = 3


class SpeechError(RuntimeError):
    """朗讀失敗。訊息一律要講得出下一步。"""


class SpeechUnavailable(SpeechError):
    """這台機器上找不到任何語音引擎。

    和 `SpeechError` 分開是有理由的，這是 `subtitle/hotkey.py` 學到的同
    一課：「失敗」與「這個環境沒有這個東西」的**下一步完全不一樣**。前
    者叫使用者再試一次，後者叫他去裝一個——把兩者寫成同一句話，使用者
    就會一直重試一件永遠不會成功的事。
    """


def _clamp(value, low, high):
    return max(low, min(high, value))


def resolve_speech_settings(config: Optional[dict] = None) -> dict:
    """取出本模組的設定，缺漏補預設值並夾到合理範圍。"""
    raw = dict(DEFAULT_SPEECH)
    if config:
        raw.update({k: v for k, v in (config.get("speech") or {}).items()
                    if k in DEFAULT_SPEECH})
    return {
        "enabled": bool(raw["enabled"]),
        "rate": int(_clamp(int(raw["rate"]), *_RATE_RANGE)),
        "volume": int(_clamp(int(raw["volume"]), *_VOLUME_RANGE)),
        "max_chars": int(_clamp(int(raw["max_chars"]), *_MAX_CHARS_RANGE)),
    }


# ----------------------------------------------------------------------
# 要念的文字
# ----------------------------------------------------------------------
# 控制字元（含 OCR 偶爾吐出來的雜訊）在各家引擎手上行為不一，先清掉。
# 換行保留成空白——句子之間該有停頓，但不該念出「反斜線 n」。
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS_RE = re.compile(r"\s+")


def prepare_text(text: str, settings: Optional[dict] = None) -> tuple:
    """
    把一段文字整理成可以送進引擎的樣子。

    回傳 `(text, dropped)`；`dropped` 是被截掉的字數，**大於 0 時介面要
    講出來**——念到一半自己停掉而沒有交代，使用者只會以為朗讀壞了。
    """
    settings = settings or resolve_speech_settings()
    cleaned = _WS_RE.sub(" ", _CTRL_RE.sub(" ", text or "")).strip()
    limit = settings["max_chars"]
    if len(cleaned) <= limit:
        return cleaned, 0
    head = cleaned[:limit]
    # 盡量斷在句子邊界，斷在詞中間念起來很怪。只往回找一小段，找不到就
    # 照原樣截——寧可斷得不漂亮，也不要為了漂亮少念一大截。
    window = head[-80:]
    cut = max(window.rfind(ch) for ch in "。！？.!?；;\n")
    if cut >= 0:
        head = head[:len(head) - len(window) + cut + 1]
    return head.strip(), len(cleaned) - len(head.strip())


def has_speakable_text(text: str) -> bool:
    """有沒有值得念的東西（避免對著空白或純標點按下去沒反應）。"""
    cleaned = _WS_RE.sub("", _CTRL_RE.sub("", text or ""))
    return any(ch.isalnum() for ch in cleaned)


# ----------------------------------------------------------------------
# 引擎偵測
# ----------------------------------------------------------------------
# 每個平台照偏好順序列候選。kind 決定命令怎麼組，exe 是要找的執行檔。
_CANDIDATES = {
    "win32": [
        {"kind": "sapi", "exe": "powershell", "display": "Windows 內建語音（SAPI）"},
        {"kind": "sapi", "exe": "pwsh", "display": "Windows 內建語音（SAPI）"},
    ],
    "darwin": [
        {"kind": "say", "exe": "say", "display": "macOS 內建語音（say）"},
    ],
    "linux": [
        {"kind": "spd", "exe": "spd-say", "display": "speech-dispatcher（spd-say）"},
        {"kind": "espeak", "exe": "espeak-ng", "display": "eSpeak NG"},
        {"kind": "espeak", "exe": "espeak", "display": "eSpeak"},
    ],
}

# 這台機器上找不到引擎時要說的話。Linux 那句要講得出安裝指令，不然使用
# 者知道「沒有引擎」也沒有用。
_NO_ENGINE_HINT = {
    "win32": "這台電腦的 PowerShell 找不到，朗讀用的是 Windows 內建語音，"
             "需要它才能啟動。",
    "darwin": "找不到 macOS 內建的 say 指令，朗讀功能無法使用。",
    "linux": "這台電腦沒有裝語音引擎，所以念不出來。可以安裝其中一個："
             "`sudo apt install espeak-ng`（或 speech-dispatcher），裝好後"
             "重開本程式即可。",
}


def _platform_key(platform_name: Optional[str] = None) -> str:
    name = platform_name or sys.platform
    if name.startswith("win"):
        return "win32"
    if name == "darwin":
        return "darwin"
    return "linux"


def find_engine(platform_name: Optional[str] = None,
                which: Optional[Callable] = None) -> Optional[dict]:
    """
    找出這台機器上可用的語音引擎，找不到回 `None`。

    `which` 可注入，測試才驗得到「有／沒有」兩條路——這台機器的真實狀態
    是一個都沒有，所以「有」那條路只能用注入的方式驗。
    """
    which = which or shutil.which
    key = _platform_key(platform_name)
    for spec in _CANDIDATES.get(key, []):
        path = which(spec["exe"])
        if path:
            found = dict(spec)
            found["path"] = path
            found["platform"] = key
            return found
    return None


def unavailable_message(platform_name: Optional[str] = None) -> str:
    """找不到引擎時要顯示的那句話（含下一步）。"""
    return _NO_ENGINE_HINT[_platform_key(platform_name)]


def describe_engine(engine: Optional[dict],
                    platform_name: Optional[str] = None) -> str:
    """給介面顯示的一行狀態。"""
    if not engine:
        return "朗讀：無法使用（" + unavailable_message(platform_name) + "）"
    return "朗讀：" + engine["display"]


# ----------------------------------------------------------------------
# 語言 → 各家引擎的說法
# ----------------------------------------------------------------------
# 本專案的語言代碼 → 各引擎認得的講法。查不到的語言一律「不指定語音」，
# 讓引擎用自己的預設值，不要硬猜一個代碼送進去。
_VOICE_MAP = {
    #                 SAPI culture   espeak-ng   spd-say
    "zh-TW": ("zh-TW", "cmn", "zh"),
    "zh-CN": ("zh-CN", "cmn", "zh"),
    "en":    ("en",    "en",  "en"),
    "en-US": ("en-US", "en-us", "en"),
    "ja":    ("ja",    "ja",  "ja"),
    "ko":    ("ko",    "ko",  "ko"),
    "es":    ("es",    "es",  "es"),
    "fr":    ("fr",    "fr",  "fr"),
    "de":    ("de",    "de",  "de"),
    "it":    ("it",    "it",  "it"),
    "pt":    ("pt",    "pt",  "pt"),
    "ru":    ("ru",    "ru",  "ru"),
}


def voice_for(lang: Optional[str], kind: str) -> Optional[str]:
    """查某個語言在某一家引擎裡的講法；查不到回 `None`（＝不指定）。"""
    if not lang:
        return None
    row = _VOICE_MAP.get(lang) or _VOICE_MAP.get(lang.split("-")[0])
    if not row:
        return None
    return {"sapi": row[0], "espeak": row[1], "spd": row[2]}.get(kind)


def _espeak_wpm(rate: int) -> int:
    """-10~10 換成 espeak 的每分鐘字數（預設 175，夾在 80~400）。"""
    return int(_clamp(175 + rate * 12, 80, 400))


def _say_wpm(rate: int) -> int:
    """-10~10 換成 macOS say 的每分鐘字數（預設 175）。"""
    return int(_clamp(175 + rate * 12, 90, 400))


def _spd_rate(rate: int) -> int:
    """-10~10 換成 spd-say 的 -100~100。"""
    return int(_clamp(rate * 10, -100, 100))


# ----------------------------------------------------------------------
# PowerShell（SAPI）
# ----------------------------------------------------------------------
_PS_TEMPLATE = """\
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Speech
$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64}'))
$s=New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Rate={rate}
$s.Volume={volume}
{voice}$s.Speak($t)
"""

# 挑語音：挑「語系前綴對得上、而且是啟用中」的第一個。挑不到就不換，用
# 系統預設——**不要因為挑不到就不念**，念錯口音也好過完全沒有聲音。
_PS_VOICE = """\
$v=$s.GetInstalledVoices()|Where-Object {{$_.Enabled -and \
$_.VoiceInfo.Culture.Name.StartsWith('{culture}')}}|Select-Object -First 1
if($v){{$s.SelectVoice($v.VoiceInfo.Name)}}
"""


def build_powershell_script(text: str, lang: Optional[str],
                            settings: dict, with_voice: bool = True) -> str:
    """組出要交給 PowerShell 的腳本原文（可離線檢查）。"""
    b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    culture = voice_for(lang, "sapi") if with_voice else None
    voice = _PS_VOICE.format(culture=culture) if culture else ""
    return _PS_TEMPLATE.format(
        b64=b64, rate=int(settings["rate"]),
        volume=int(settings["volume"]), voice=voice)


def encode_powershell(script: str) -> str:
    """PowerShell `-EncodedCommand` 要的是 UTF-16LE 再 base64。"""
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def build_command(engine: dict, text: str, lang: Optional[str],
                  settings: dict, with_voice: bool = True) -> list:
    """
    組出要執行的命令陣列。

    `with_voice=False` 是給「指定語音被引擎拒絕」時的第二次嘗試用的——
    有些 espeak 建置不認得某些語言代碼，整句念不出來遠比口音不對嚴重。
    一律回陣列、絕不經過 shell（理由見檔頭）。
    """
    kind = engine["kind"]
    exe = engine.get("path") or engine["exe"]
    if kind == "sapi":
        script = build_powershell_script(text, lang, settings, with_voice)
        return [exe, "-NoProfile", "-NonInteractive",
                "-EncodedCommand", encode_powershell(script)]
    if kind == "say":
        # say 的 -v 吃的是「語音名稱」（例如某個具名的聲音），不是語系代
        # 碼；名稱清單要在使用者那台 Mac 上問 `say -v ?` 才知道，這裡沒有
        # macOS 可以驗。與其硬塞一個猜的名稱，不如不指定，讓系統用預設
        # 語音——這是已知的缺口，寫在檔頭的表裡。
        return [exe, "-r", str(_say_wpm(settings["rate"])), "--", text]
    if kind == "spd":
        cmd = [exe, "-r", str(_spd_rate(settings["rate"])),
               "-w"]  # -w：念完才結束，行程結束＝念完
        voice = voice_for(lang, "spd") if with_voice else None
        if voice:
            cmd += ["-l", voice]
        cmd += ["--", text]
        return cmd
    if kind == "espeak":
        cmd = [exe, "-s", str(_espeak_wpm(settings["rate"])),
               "-a", str(int(_clamp(settings["volume"] * 2, 0, 200)))]
        voice = voice_for(lang, "espeak") if with_voice else None
        if voice:
            cmd += ["-v", voice]
        cmd += ["--", text]
        return cmd
    raise SpeechError("不認得的語音引擎：%s" % kind)


# ----------------------------------------------------------------------
# 行程管理
# ----------------------------------------------------------------------
class Speaker:
    """
    一次只念一句。

    按第二次朗讀時**先把前一句停掉**，不要兩句疊在一起——這是實際用起來
    才會在意的事：使用者按了「念原文」再按「念譯文」，疊著念等於兩句都
    聽不清楚。
    """

    def __init__(self, engine: Optional[dict] = None,
                 settings: Optional[dict] = None,
                 popen: Optional[Callable] = None):
        self.engine = engine if engine is not None else find_engine()
        self.settings = settings or resolve_speech_settings()
        self._popen = popen or subprocess.Popen
        self._proc = None
        self.last_command = None
        self.last_error = ""
        self._retry_pending = False
        self._body = ""
        self._lang = None

    # -- 狀態 --------------------------------------------------------
    def available(self) -> bool:
        return self.engine is not None

    def is_speaking(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # -- 動作 --------------------------------------------------------
    def speak(self, text: str, lang: Optional[str] = None) -> int:
        """
        念一段文字，回傳被截掉的字數（0 代表整段都念）。

        不等它念完——朗讀要是把介面卡住，使用者連「停止」都按不到。
        """
        if not self.engine:
            raise SpeechUnavailable(unavailable_message())
        if not has_speakable_text(text):
            raise SpeechError("這段內容沒有可以念的文字。")
        body, dropped = prepare_text(text, self.settings)
        self.stop()
        self._body = body
        self._lang = lang
        self._launch(body, lang, with_voice=True)
        return dropped

    def _launch(self, body: str, lang: Optional[str], with_voice: bool):
        cmd = build_command(self.engine, body, lang, self.settings, with_voice)
        self.last_command = cmd
        # 只有「這次真的指定了語音」才有退路可退；沒指定過就重跑一次只是
        # 把同一個失敗再做一遍。
        self._retry_pending = with_voice and bool(
            voice_for(lang, self.engine["kind"]))
        try:
            self._proc = self._popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL, **_no_window())
        except OSError as exc:
            self._proc = None
            self._retry_pending = False
            raise SpeechError("朗讀啟動失敗：%s" % exc) from exc

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        """
        等它念完，回傳結束碼；還在念（逾時）回 `None`。

        若引擎是因為**不認得指定的語音**而失敗，這裡會自動改成不指定語
        音再念一次。有些 espeak 建置不收某些語言代碼，而「口音不對」遠
        比「整段沒聲音」輕微——退到預設語音是划算的。這條退路失敗得很
        快，使用者察覺不到中間換過一次。
        """
        if self._proc is None:
            return None
        try:
            code = self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
        if code == 0 or not self._retry_pending:
            self._retry_pending = False
            return code
        self._retry_pending = False
        self.last_error = self._read_stderr()
        self._launch(self._body, self._lang, with_voice=False)
        return self.wait(timeout=timeout)

    def _read_stderr(self) -> str:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return ""
        try:
            return (proc.stderr.read() or b"").decode("utf-8", "replace").strip()
        except (OSError, ValueError):
            return ""

    def stop(self) -> None:
        """停止目前這一句；沒有在念就什麼都不做。"""
        proc = self._proc
        self._proc = None
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=_TERM_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
        except OSError:
            pass


def _no_window() -> dict:
    """Windows 上不要為了念一句話閃一個黑色主控台視窗出來。"""
    if sys.platform.startswith("win"):  # pragma: no cover - 非 Windows 驗不到
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if flags:
            return {"creationflags": flags}
    return {}
