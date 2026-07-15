# -*- coding: utf-8 -*-
"""
v1.13.1 修復驗證（Issue #28）：

1. 勾選框顯示 bug——sv_ttk 深色/淺色主題套用時，classic tk.Checkbutton
   的勾選指示器不跟主題調色盤走，導致按下短暫可見、放開又「看起來」
   變回空白；修法是全面改用 ttk.Checkbutton。本測試靜態掃描 gui/*.py
   確認沒有殘留的 tk.Checkbutton。
2. 外部 Whisper 輸出解析失敗——worker 子程序若在 stdout 混入雜訊
   （下載進度、套件警告等），會讓本程式讀不出 JSON。修法是用
   os.dup2 把 stdout 檔案描述元暫時導到 devnull，涵蓋 Python 與
   C 層級輸出。本測試以假 whisper 模組實際跑一次 _WORKER_SCRIPT，
   驗證雜訊確實被擋下、JSON 仍完整可解析。
"""
import glob
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import errors, transcriber

# ===== 1. 勾選框：gui/*.py 不應殘留 classic tk.Checkbutton =====
gui_dir = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "gui")
offenders = []
for path in glob.glob(os.path.join(gui_dir, "*.py")):
    text = open(path, encoding="utf-8").read()
    # "ttk.Checkbutton(" 本身含有子字串 "tk.Checkbutton("，先挖掉
    # 合法的 ttk 用法，剩下的才是需要抓的 classic tk.Checkbutton。
    if "tk.Checkbutton(" in text.replace("ttk.Checkbutton(", ""):
        offenders.append(os.path.basename(path))
check("gui/*.py 無殘留 tk.Checkbutton", not offenders, str(offenders))
# 抽查曾經回報壞掉的檔案，確認確實已改用 ttk.Checkbutton。
for name in ("audiocheck_dialog.py", "review_window.py", "app.py",
             "style_panel.py"):
    text = open(os.path.join(gui_dir, name), encoding="utf-8").read()
    check(f"{name} 使用 ttk.Checkbutton", "ttk.Checkbutton(" in text)

# ===== 2. 友善錯誤：外部 Whisper 輸出解析失敗 =====
e = errors.describe_exception(
    RuntimeError("無法解析外部 Whisper 的輸出結果。"))
check("解析失敗有明確原因", "不是預期的乾淨 JSON" in e.cause, e.cause)
check("解析失敗有具體解法",
      "openai-whisper" in e.solution and "API" in e.solution, e.solution)
check("不再落入未知錯誤分類", "已知的常見問題" not in e.cause, e.cause)

# ===== 3. 外部 Whisper worker：stdout 雜訊隔離（假 whisper 模組端到端）=====
FAKE_WHISPER = '''# -*- coding: utf-8 -*-
def load_model(name):
    print("正在下載模型... 100%")           # 模擬下載進度雜訊
    import sys
    sys.stderr.write("(stderr 雜訊不影響，僅供對照)\\n")
    return _FakeModel()


class _FakeModel:
    def transcribe(self, audio_path, **kwargs):
        print("UserWarning: FP16 is not supported on CPU")  # 模擬套件警告
        return {"segments": [{
            "start": 0.0, "end": 1.2,
            "text": "測試",
            "words": [{"word": "測試", "start": 0.0, "end": 1.2}],
        }]}
'''

with tempfile.TemporaryDirectory() as tmp:
    worker_path = os.path.join(tmp, "worker.py")
    with open(worker_path, "w", encoding="utf-8") as fp:
        fp.write(transcriber._WORKER_SCRIPT)
    # 假 whisper 模組與 worker 腳本同目錄，Python 會優先從腳本所在
    # 目錄（sys.path[0]）找到它，不需要安裝真正的 openai-whisper。
    with open(os.path.join(tmp, "whisper.py"), "w", encoding="utf-8") as fp:
        fp.write(FAKE_WHISPER)
    audio_path = os.path.join(tmp, "a.wav")
    open(audio_path, "wb").write(b"x")

    completed = subprocess.run(
        [sys.executable, worker_path, audio_path, "base", "auto", ""],
        capture_output=True, timeout=30)

    check("worker 子程序正常結束", completed.returncode == 0,
          completed.stderr.decode("utf-8", "ignore"))
    stdout_text = completed.stdout.decode("utf-8", "ignore")
    check("雜訊未混入 stdout", "下載模型" not in stdout_text
          and "UserWarning" not in stdout_text, stdout_text)
    try:
        words = json.loads(stdout_text)
        parsed_ok = True
    except json.JSONDecodeError:
        words, parsed_ok = None, False
    check("stdout 仍是可解析的乾淨 JSON", parsed_ok, stdout_text)
    if parsed_ok:
        check("轉寫結果正確帶出", words == [
            {"word": "測試", "start": 0.0, "end": 1.2}], str(words))

print("\n" + ("ALL PASS" if not failures else f"FAILURES: {failures}"))
sys.exit(1 if failures else 0)
