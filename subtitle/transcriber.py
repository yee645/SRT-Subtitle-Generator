# -*- coding: utf-8 -*-
"""
語音轉寫模組（模式一：音訊轉錄）。

支援三種執行途徑：
1. 程式內本地 Whisper：以原始碼執行且環境已安裝 openai-whisper 時直接使用。
2. 外部 Python 子程序：當程式內無 whisper（例如打包成 exe 後）時，
   改以使用者自備、已安裝 whisper 的 Python 直譯器執行轉寫。
3. OpenAI 雲端 API：於設定中啟用 use_api 並填入 api_key。

三者皆回傳統一格式的逐字時間軸：
    list[dict]，每筆為 {"word": str, "start": float, "end": float}

initial_prompt 參數可提供一段提示文字（例如使用者的文字稿），
讓 Whisper 的辨識用詞、標點與字體（繁/簡）更貼近該文字，
模式二的文字稿對齊會用到。
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time

from .media import probe_duration

# 各 Whisper 模型在 CPU 上對「實時音訊長度」的處理時間倍數估算值，
# 用於時間軸式假進度條（無法直接取得 whisper 內部進度）。
_MODEL_TIME_FACTOR = {
    "tiny": 0.4, "base": 0.6, "small": 1.5, "medium": 3.0, "large": 6.0,
}

# 外部 Python 子程序所執行的 whisper 轉寫工作腳本內容。
# 以子程序方式執行，可讓打包後的 exe 使用使用者自行安裝的 whisper。
_WORKER_SCRIPT = '''# -*- coding: utf-8 -*-
import sys, json
import whisper

audio_path, model_name, language = sys.argv[1], sys.argv[2], sys.argv[3]
initial_prompt = sys.argv[4] if len(sys.argv) > 4 else ""

model = whisper.load_model(model_name)
kwargs = {"word_timestamps": True, "verbose": False}
if language and language != "auto":
    kwargs["language"] = language
if initial_prompt:
    kwargs["initial_prompt"] = initial_prompt
result = model.transcribe(audio_path, **kwargs)

words = []
for segment in result.get("segments", []):
    for word in segment.get("words", []):
        text = (word.get("word") or "").strip()
        if not text:
            continue
        words.append({"word": text,
                      "start": float(word.get("start", 0.0)),
                      "end": float(word.get("end", 0.0))})
if not words:
    for segment in result.get("segments", []):
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        words.append({"word": text,
                      "start": float(segment.get("start", 0.0)),
                      "end": float(segment.get("end", 0.0))})

sys.stdout.buffer.write(json.dumps(words, ensure_ascii=False).encode("utf-8"))
'''


# zh-TW 為本程式的特別語言標記。Whisper 本身只認 "zh"、且常輸出簡體，
# 故選用 zh-TW 時：以 zh 辨識、加繁體提示詞偏導，再把結果轉為台灣繁體中文。
_TRADITIONAL_MARK = "zh-TW"
_TRADITIONAL_PROMPT = "以下是繁體中文的內容。"


def transcribe(audio_path, config, status_cb=None, initial_prompt=""):
    """
    依設定選擇 API 或本地模式進行語音轉寫。

    參數：
        audio_path: 影片或音訊檔路徑。
        config: 完整設定 dict。
        status_cb: 可選的狀態回呼函式，接受一個字串訊息。
        initial_prompt: 可選的提示文字，引導辨識用詞與字體。
    回傳：逐字時間軸 list。
    """
    if not audio_path or not os.path.exists(audio_path):
        raise FileNotFoundError("找不到指定的音訊或影片檔案。")

    # 複製一份設定以便在 zh-TW 模式下調整語言代碼，不影響原設定。
    transcription_cfg = dict(config.get("transcription", {}))

    # 若呼叫端未傳入提示，改用使用者於設定中填寫的提示詞（導正專有名詞、常見錯字）。
    user_prompt = (transcription_cfg.get("prompt") or "").strip()
    if not initial_prompt and user_prompt:
        initial_prompt = user_prompt

    want_traditional = (transcription_cfg.get("language") == _TRADITIONAL_MARK)
    if want_traditional:
        transcription_cfg["language"] = "zh"
        if not initial_prompt:
            initial_prompt = _TRADITIONAL_PROMPT
        elif _TRADITIONAL_PROMPT not in initial_prompt:
            # 已有自訂提示詞時，附加繁體偏導詞以兼顧字體與用詞導正。
            initial_prompt = f"{_TRADITIONAL_PROMPT}{initial_prompt}"

    if transcription_cfg.get("use_api"):
        words = _transcribe_with_api(
            audio_path, transcription_cfg, status_cb, initial_prompt)
    else:
        words = _transcribe_with_local(
            audio_path, transcription_cfg, status_cb, initial_prompt)

    if want_traditional:
        words = _to_traditional(words)
    return words


def _to_traditional(words):
    """把逐字結果轉為台灣繁體中文；未安裝 zhconv 時略過不中斷程式。"""
    try:
        from zhconv import convert
    except ImportError:
        return words
    return [{
        "word": convert(word.get("word", ""), "zh-tw"),
        "start": word.get("start", 0.0),
        "end": word.get("end", 0.0),
    } for word in words]


def _notify(status_cb, message, ratio=None):
    """
    安全地呼叫狀態回呼。

    為相容舊版簽名（status_cb(message)），會先嘗試以 (message, ratio) 呼叫，
    若失敗再退回以 (message) 呼叫，確保新舊兩種簽名皆可運作。
    """
    if not callable(status_cb):
        return
    try:
        status_cb(message, ratio)
    except TypeError:
        status_cb(message)


# ---------------------------------------------------------------------------
# 本地模式：優先程式內 whisper，否則改用外部 Python 子程序
# ---------------------------------------------------------------------------

def _transcribe_with_local(audio_path, transcription_cfg, status_cb, initial_prompt):
    """本地轉寫：能在程式內 import whisper 就直接用，否則改走外部 Python。"""
    try:
        import whisper  # noqa: F401
    except ImportError:
        return _transcribe_via_external_python(
            audio_path, transcription_cfg, status_cb, initial_prompt)
    return _transcribe_in_process(
        audio_path, transcription_cfg, status_cb, initial_prompt)


def _transcribe_in_process(audio_path, transcription_cfg, status_cb, initial_prompt):
    """直接在目前程式內使用本地 Whisper 函式庫轉寫。"""
    import whisper

    model_name = transcription_cfg.get("model", "base")
    language = transcription_cfg.get("language", "auto")

    _notify(status_cb, f"正在載入 Whisper 模型（{model_name}），首次使用需下載，請稍候...",
            ratio=0.02)
    try:
        model = whisper.load_model(model_name)
    except Exception as exc:
        raise RuntimeError(f"載入 Whisper 模型失敗：{exc}") from exc

    _notify(status_cb, "正在進行語音辨識，較長的影片需要數分鐘...", ratio=0.08)
    transcribe_kwargs = {"word_timestamps": True, "verbose": False}
    if language and language != "auto":
        transcribe_kwargs["language"] = language
    if initial_prompt:
        transcribe_kwargs["initial_prompt"] = initial_prompt

    # 啟動背景假進度執行緒：依音訊時長與模型速度估算進度推進。
    # Whisper 沒有公開的進度回呼，僅能以時間軸式估算給使用者一個視覺參考。
    duration = probe_duration(audio_path)
    factor = _MODEL_TIME_FACTOR.get(model_name, 1.0)
    expected = max(duration * factor, 5.0)
    stop_event = threading.Event()
    progress_thread = threading.Thread(
        target=_simulate_progress,
        args=(status_cb, expected, stop_event, 0.10, 0.92,
              "正在語音辨識，請耐心等候..."),
        daemon=True,
    )
    progress_thread.start()
    try:
        result = model.transcribe(audio_path, **transcribe_kwargs)
    except Exception as exc:
        raise RuntimeError(f"語音辨識過程發生錯誤：{exc}") from exc
    finally:
        stop_event.set()
        progress_thread.join(timeout=1.0)

    _notify(status_cb, "語音辨識完成，整理結果中...", ratio=0.96)
    return _extract_words_from_whisper_result(result)


def _simulate_progress(status_cb, expected_seconds, stop_event,
                       start_ratio, end_ratio, message):
    """
    背景時間軸式假進度。

    在 expected_seconds 內把比例由 start_ratio 推進到 end_ratio；
    結束前不抵達 100%，等待主流程完成後再補到 1.0。
    """
    if not callable(status_cb):
        return
    started = time.time()
    span = max(end_ratio - start_ratio, 0.01)
    while not stop_event.is_set():
        elapsed = time.time() - started
        ratio = start_ratio + span * min(elapsed / expected_seconds, 1.0)
        # 模擬曲線：愈接近末端時推進愈慢，避免使用者誤以為已完成卻久候。
        if ratio > end_ratio - 0.02:
            ratio = end_ratio - 0.02
        try:
            status_cb(message, ratio)
        except TypeError:
            status_cb(message)
        if stop_event.wait(timeout=1.5):
            break


def _extract_words_from_whisper_result(result):
    """從 Whisper 結果 dict 中萃取逐字時間軸。"""
    words = []
    for segment in result.get("segments", []):
        for word in segment.get("words", []):
            text = (word.get("word") or "").strip()
            if not text:
                continue
            words.append({
                "word": text,
                "start": float(word.get("start", 0.0)),
                "end": float(word.get("end", 0.0)),
            })
    if not words:
        for segment in result.get("segments", []):
            text = (segment.get("text") or "").strip()
            if not text:
                continue
            words.append({
                "word": text,
                "start": float(segment.get("start", 0.0)),
                "end": float(segment.get("end", 0.0)),
            })
    if not words:
        raise RuntimeError("辨識完成但未取得任何文字內容，請確認音訊是否含人聲。")
    return words


def _transcribe_via_external_python(audio_path, transcription_cfg, status_cb,
                                    initial_prompt):
    """以使用者自備、已安裝 whisper 的外部 Python 直譯器執行轉寫。"""
    configured = transcription_cfg.get("python_path", "")
    _notify(status_cb, "正在尋找已安裝 Whisper 的 Python 直譯器...")
    python_exe = _find_external_python(configured)
    if not python_exe:
        raise RuntimeError(
            "找不到可用的本地 Whisper。請先安裝 Python 並執行 "
            "pip install openai-whisper，再於「轉寫設定」的「本地 Python」"
            "欄位指向該 python.exe；或改用 OpenAI API 模式。"
        )

    model_name = transcription_cfg.get("model", "base")
    language = transcription_cfg.get("language", "auto")

    # 把工作腳本寫到暫存檔，交給外部 Python 執行。
    worker_path = None
    try:
        with tempfile.NamedTemporaryFile(
                "w", suffix=".py", delete=False, encoding="utf-8") as fp:
            fp.write(_WORKER_SCRIPT)
            worker_path = fp.name

        _notify(status_cb, "正在以外部 Python 進行語音辨識，較長的影片需要數分鐘...")
        command = [python_exe, worker_path, audio_path, model_name, language,
                   initial_prompt or ""]
        try:
            completed = subprocess.run(command, capture_output=True)
        except OSError as exc:
            raise RuntimeError(f"無法啟動外部 Python：{exc}") from exc

        if completed.returncode != 0:
            stderr = (completed.stderr or b"").decode("utf-8", errors="ignore")
            raise RuntimeError(f"外部 Whisper 辨識失敗：{stderr[-400:]}")

        try:
            words = json.loads((completed.stdout or b"").decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError("無法解析外部 Whisper 的輸出結果。") from exc
    finally:
        if worker_path and os.path.exists(worker_path):
            try:
                os.unlink(worker_path)
            except OSError:
                pass

    if not words:
        raise RuntimeError("辨識完成但未取得任何文字內容，請確認音訊是否含人聲。")
    return words


def _find_external_python(configured_path):
    """尋找一個已安裝 whisper 的 Python 直譯器，找不到時回傳 None。"""
    if configured_path and configured_path.strip():
        # 使用者明確指定路徑時，僅檢查該直譯器。
        candidates = [configured_path.strip()]
    else:
        # 未指定時，嘗試 PATH 上常見的 Python 指令。
        candidates = ["python", "py", "python3"]
    for candidate in candidates:
        if _python_has_whisper(candidate):
            return candidate
    return None


def _python_has_whisper(python_exe):
    """檢查指定的 Python 直譯器是否可成功 import whisper。"""
    try:
        result = subprocess.run(
            [python_exe, "-c", "import whisper"],
            capture_output=True, timeout=90,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# ---------------------------------------------------------------------------
# API 模式
# ---------------------------------------------------------------------------

def _transcribe_with_api(audio_path, transcription_cfg, status_cb, initial_prompt):
    """使用 OpenAI 雲端 API 轉寫。"""
    api_key = transcription_cfg.get("api_key", "").strip()
    if not api_key:
        raise RuntimeError("已啟用 API 模式，但尚未填入 OpenAI API 金鑰。")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "未安裝 openai 函式庫。請執行：pip install openai"
        ) from exc

    _notify(status_cb, "正在透過 OpenAI API 進行語音辨識...")
    language = transcription_cfg.get("language", "auto")
    client = OpenAI(api_key=api_key)

    api_kwargs = {
        "model": "whisper-1",
        "response_format": "verbose_json",
        "timestamp_granularities": ["word"],
    }
    if language and language != "auto":
        api_kwargs["language"] = language
    if initial_prompt:
        api_kwargs["prompt"] = initial_prompt

    try:
        with open(audio_path, "rb") as audio_file:
            response = client.audio.transcriptions.create(file=audio_file, **api_kwargs)
    except Exception as exc:
        raise RuntimeError(f"呼叫 OpenAI API 失敗：{exc}") from exc

    return _extract_words_from_api(response)


def _extract_words_from_api(response):
    """從 OpenAI API 回應中萃取逐字時間軸。"""
    words = []
    api_words = getattr(response, "words", None) or []
    for word in api_words:
        # API 回傳的可能是物件或 dict，兩種情況都相容處理。
        if isinstance(word, dict):
            text = (word.get("word") or "").strip()
            start = word.get("start", 0.0)
            end = word.get("end", 0.0)
        else:
            text = (getattr(word, "word", "") or "").strip()
            start = getattr(word, "start", 0.0)
            end = getattr(word, "end", 0.0)
        if not text:
            continue
        words.append({
            "word": text,
            "start": float(start or 0.0),
            "end": float(end or 0.0),
        })

    if not words:
        # 沒有逐字資料時退回整段文字（時間軸由後續流程估算）。
        text = (getattr(response, "text", "") or "").strip()
        if not text:
            raise RuntimeError("API 辨識完成但未取得任何文字內容。")
        words.append({"word": text, "start": 0.0, "end": 0.0})
    return words
