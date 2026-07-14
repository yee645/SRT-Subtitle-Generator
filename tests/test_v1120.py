# -*- coding: utf-8 -*-
"""v1.12.0 新功能測試：友善錯誤翻譯、ffmpeg 自動安裝。"""
import io
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import errors, ffmpeg_setup

# =====================================================================
# 友善錯誤翻譯（errors.py）
# =====================================================================

# ===== 1. 各已知情境的分類 =====
e = errors.describe_exception(
    RuntimeError("找不到 ffmpeg，請先安裝並加入系統 PATH。"))
check("ffmpeg 缺失歸類", e.kind == errors.KIND_FFMPEG_MISSING)
check("ffmpeg 缺失有原因", "尚未安裝 ffmpeg" in e.cause, e.cause)
check("ffmpeg 缺失有解法", "自動安裝 ffmpeg" in e.solution, e.solution)
check("is_ffmpeg_missing 判定", errors.is_ffmpeg_missing(
    "找不到 ffmpeg，請先安裝並加入系統 PATH。"))

e = errors.describe_exception(RuntimeError(
    "找不到可用的本地 Whisper。請先安裝 Python 並執行 pip install..."))
check("whisper 缺失歸類", e.kind == errors.KIND_WHISPER_MISSING)
check("whisper 解法含三條路", "API" in e.solution and "模式二" in e.solution,
      e.solution)

e = errors.describe_exception(RuntimeError("載入 Whisper 模型失敗：OOM"))
check("模型載入失敗有解法", "較小的模型" in e.solution, e.solution)
check("模型載入失敗保留原文", "OOM" in e.details, e.details)

e = errors.describe_exception(
    RuntimeError("已啟用 API 模式，但尚未填入 OpenAI API 金鑰。"))
check("API 金鑰歸類", e.kind == errors.KIND_API_KEY)

e = errors.describe_exception(RuntimeError("呼叫 OpenAI API 失敗：timeout"))
check("API 失敗歸類網路", e.kind == errors.KIND_NETWORK)

e = errors.describe_exception(RuntimeError("未能從音訊辨識到任何人聲。"))
check("無人聲歸類", e.kind == errors.KIND_NO_SPEECH)
check("無人聲有解法", "播放器" in e.solution, e.solution)

e = errors.describe_exception(PermissionError(13, "Permission denied"))
check("權限錯誤有解法", "輸出資料夾" in e.solution, e.solution)

e = errors.describe_exception(OSError("No space left on device"))
check("磁碟不足歸類", e.kind == errors.KIND_DISK)

e = errors.describe_exception(FileNotFoundError("找不到檔案：a.mp4"))
check("檔案不存在歸類", e.kind == errors.KIND_FILE_MISSING)

e = errors.describe_exception(RuntimeError(
    "ffmpeg 燒錄失敗：[libx264] ... Conversion failed!"))
check("ffmpeg 執行失敗歸類", e.kind == errors.KIND_FFMPEG_FAILED)
check("ffmpeg 執行失敗保留 stderr", "Conversion failed" in e.details,
      e.details)
for prefix in ("ffmpeg 粗剪失敗：x", "響度正規化失敗：x", "背景音樂混音失敗：x",
               "短片輸出失敗：x", "畫面擷取失敗：x", "無法啟動 ffmpeg：x"):
    e = errors.describe_exception(RuntimeError(prefix))
    check(f"「{prefix[:9]}」歸類 ffmpeg 失敗",
          e.kind == errors.KIND_FFMPEG_FAILED, e.kind)

e = errors.describe_exception(ValueError("某個很怪的內部錯誤 xyz"))
check("未知錯誤退回 generic", e.kind == errors.KIND_GENERIC)
check("未知錯誤引導回報", "app.log" in e.solution and "issues" in e.solution,
      e.solution)
check("未知錯誤保留原文", "xyz" in e.details, e.details)

# FriendlyError 原樣通過（不重複包裝）。
original = errors.FriendlyError("自訂", cause="c", solution="s",
                                kind=errors.KIND_NETWORK)
check("FriendlyError 原樣回傳",
      errors.describe_exception(original) is original)

# 也接受純字串輸入（GUI queue 傳字串的舊路徑相容）。
e = errors.describe_exception("找不到 ffmpeg，請先安裝並加入系統 PATH。")
check("字串輸入可翻譯", e.kind == errors.KIND_FFMPEG_MISSING)

# ===== 2. CLI 文字排版 =====
text = errors.format_error_text(RuntimeError("未能從音訊辨識到任何人聲。"))
check("CLI 文字含三段", text.count("\n") == 2 and "原因：" in text
      and "解法：" in text, text)

# =====================================================================
# ffmpeg 自動安裝（ffmpeg_setup.py）
# =====================================================================

# ===== 3. 安裝目錄搜尋與 PATH 生效 =====
candidates = ffmpeg_setup.install_candidates()
check("安裝候選：程式資料夾優先",
      candidates[0].startswith(ffmpeg_setup.app_root()), str(candidates))
check("安裝候選：有使用者資料夾退路", len(candidates) == 2, str(candidates))

orig_candidates = ffmpeg_setup.install_candidates
orig_path = os.environ.get("PATH", "")
with tempfile.TemporaryDirectory() as tmp:
    bin_dir = os.path.join(tmp, "bin")
    os.makedirs(bin_dir)
    ffmpeg_setup.install_candidates = lambda: [bin_dir]

    check("未安裝時 installed_dir 為 None",
          ffmpeg_setup.installed_dir() is None)
    check("未安裝時 ensure 不動 PATH",
          ffmpeg_setup.ensure_ffmpeg_on_path() is None
          and os.environ["PATH"] == orig_path)

    for name in ffmpeg_setup.BINARY_NAMES:
        open(os.path.join(bin_dir, name), "wb").write(b"bin")
    check("安裝後 installed_dir 找到", ffmpeg_setup.installed_dir() == bin_dir)
    check("ensure 把目錄加進 PATH",
          ffmpeg_setup.ensure_ffmpeg_on_path() == bin_dir
          and os.environ["PATH"].split(os.pathsep)[0] == bin_dir)
    before = os.environ["PATH"]
    ffmpeg_setup.ensure_ffmpeg_on_path()
    check("ensure 冪等不重複加", os.environ["PATH"] == before)
os.environ["PATH"] = orig_path
ffmpeg_setup.install_candidates = orig_candidates

# ===== 4. install_ffmpeg：假下載端到端 =====
def build_fake_zip(names):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(f"ffmpeg-build/bin/{name}", b"FAKEBIN-" + name.encode())
            # 干擾項：非 bin 目錄下的同名檔與其他檔案。
            archive.writestr(f"ffmpeg-build/doc/{name}", b"DOC")
        archive.writestr("ffmpeg-build/LICENSE.txt", b"GPL")
    return buffer.getvalue()

class FakeResponse:
    def __init__(self, payload):
        self._fp = io.BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))}
    def read(self, size=-1):
        return self._fp.read(size)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False

payload = build_fake_zip(ffmpeg_setup.BINARY_NAMES)
orig_urlopen = ffmpeg_setup.urllib.request.urlopen
orig_path = os.environ.get("PATH", "")
with tempfile.TemporaryDirectory() as tmp:
    target = os.path.join(tmp, "tools", "ffmpeg", "bin")
    ffmpeg_setup.install_candidates = lambda: [target]
    ffmpeg_setup.urllib.request.urlopen = (
        lambda request, timeout=0: FakeResponse(payload))

    events = []
    result = ffmpeg_setup.install_ffmpeg(
        progress_cb=lambda ratio, msg: events.append((ratio, msg)))
    check("安裝回傳目標目錄", result == target, result)
    installed = sorted(os.listdir(target))
    check("兩個執行檔都就位",
          installed == sorted(ffmpeg_setup.BINARY_NAMES), str(installed))
    content = open(os.path.join(target, ffmpeg_setup.BINARY_NAMES[0]),
                   "rb").read()
    check("取的是 bin/ 目錄版本", content.startswith(b"FAKEBIN-"), content)
    check("安裝後 PATH 生效",
          os.environ["PATH"].split(os.pathsep)[0] == target)
    check("進度回報到完成", events and events[-1][0] == 1.0
          and "完成" in events[-1][1], str(events[-3:]))

    # 失敗情境一：離線／被防火牆擋 → FriendlyError（網路類）。
    def fail_urlopen(request, timeout=0):
        raise OSError("connection refused")
    ffmpeg_setup.urllib.request.urlopen = fail_urlopen
    try:
        ffmpeg_setup.install_ffmpeg()
        check("下載失敗要報錯", False)
    except errors.FriendlyError as exc:
        check("下載失敗為 FriendlyError", exc.kind == errors.KIND_NETWORK)
        check("下載失敗附手動解法", "tools" in exc.solution, exc.solution)

    # 失敗情境二：壓縮檔缺執行檔 → 明確訊息。
    bad_payload = build_fake_zip(ffmpeg_setup.BINARY_NAMES[:1])
    ffmpeg_setup.urllib.request.urlopen = (
        lambda request, timeout=0: FakeResponse(bad_payload))
    try:
        ffmpeg_setup.install_ffmpeg()
        check("壓縮檔缺檔要報錯", False)
    except RuntimeError as exc:
        check("壓縮檔缺檔訊息明確", "找不到" in str(exc), str(exc))

os.environ["PATH"] = orig_path
ffmpeg_setup.install_candidates = orig_candidates
ffmpeg_setup.urllib.request.urlopen = orig_urlopen

# ===== 5. CLI 整合：失敗摘要翻譯成原因＋解法 =====
import cli
orig_run_batch = cli.run_batch
cli.run_batch = lambda files, config, mode=None, report=None: [
    {"path": files[0], "ok": False, "result": None,
     "error": "找不到 ffmpeg，請先安裝並加入系統 PATH。"}]
try:
    code = cli.main(["x.mp4"])
    check("CLI 失敗回傳碼", code == 1)
finally:
    cli.run_batch = orig_run_batch

print("\n" + ("ALL PASS" if not failures else f"FAILURES: {failures}"))
sys.exit(1 if failures else 0)
