# -*- coding: utf-8 -*-
"""
3.0 之後 A-1：新介面的發版打包改用 Python 3.12，自檢量「None 的參照數有沒有被多減」。

v3.0.0 的發版流程（release.yml 的 qt-preview 工作）用 Python 3.11.9＋PySide6 6.12.0 打新介面的 zip——
第 10 項第二階段記過，這個組合每呼叫一次沒有回傳值的 Qt 方法就把 None 的參照數多減一，用久了整個程式
崩潰（`none_dealloc`）。#179 只改了 PR 上跑的 qt-preview.yml，發版那一份漏了。2026-11-25 在容器裡重現：
3.11.18＋6.12.0 呼叫 1000 次 setText 少 1000、結束時 `Fatal Python error: none_dealloc`；3.12.3＋6.12.0 是 0。

1. 兩份工作流程打新介面的 Python 版本一樣，而且是 3.12 以上（不會再一份改了一份漏了）。
2. 自檢結果帶 Python 版本與 None 參照數的變化；正常（這台 3.12）是 0、自檢通過。
3. 參照數被多減時（把 `sys.getrefcount` 換成每次少 1000 的假的）：自檢不通過、結束碼 1——
   就算影片播得出來也一樣，打包流程因此不會打 zip。
4. 門檻：少一半以上才算錯，正常的雜訊不會誤判。
"""
import json
import os
import re
import subprocess as sp
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fp:
        return fp.read()


# ----- 1. 工作流程 -----
def qt_python(text):
    """工作流程裡打新介面那個工作的 python-version。"""
    if "\n  qt-preview:\n" in text:  # release.yml：頂層 jobs 底下的 qt-preview 工作
        text = text.split("\n  qt-preview:\n")[1]
        nxt = re.search(r"\n  [A-Za-z0-9_-]+:\n", text)
        text = text[:nxt.start()] if nxt else text
    found = re.findall(r'python-version:\s*"([\d.]+)"', text)
    return found


rel_py = qt_python(read(".github/workflows/release.yml"))
pre_py = qt_python(read(".github/workflows/qt-preview.yml"))
check("兩份工作流程打新介面用同一個 Python 版本", len(rel_py) == 1 and rel_py == pre_py, f"{rel_py} {pre_py}")
check("那個版本是 3.12 以上（3.11＋PySide6 6.12 會把 None 的參照數多減）",
      bool(rel_py) and tuple(int(x) for x in rel_py[0].split(".")[:2]) >= (3, 12), str(rel_py))

# ----- 4. 門檻 -----
try:
    from gui_qt import selftest as st
except ImportError as exc:
    print(f"SKIP 自檢（{exc}）")
    st = None
if st is not None:
    check("門檻：0、個位數的雜訊算正常", st.none_refcount_ok(0) and st.none_refcount_ok(-7) and st.none_refcount_ok(12))
    check("門檻：少一半以上算錯", not st.none_refcount_ok(-500) and not st.none_refcount_ok(-1000)
          and st.none_refcount_ok(-499))

    # 量測真的呼叫了那麼多次「沒有回傳值的 Qt 方法」——3.12 上數字本來就是 0，迴圈空轉也看不出來。
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    calls = []
    real_label = QtWidgets.QLabel

    class CountingLabel(real_label):
        def setText(self, text):
            calls.append(text)
            return super().setText(text)

    QtWidgets.QLabel = CountingLabel
    try:
        st.none_refcount_drift(50)
    finally:
        QtWidgets.QLabel = real_label
    check("量測真的呼叫 Qt 的 setText 那麼多次（迴圈空轉在 3.12 上看不出來）", len(calls) == 50, str(len(calls)))

    # ----- 2、3. 真的跑自檢 -----
    clip = os.path.join(ROOT, "research", "qt_probe", "probe_clip.mp4")
    tmp = tempfile.mkdtemp(prefix="qt_none_")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    RUN = r'''
import runpy, sys
if sys.argv[1] == "leak":
    real = sys.getrefcount
    state = {"n": 0}
    def fake(obj):
        if obj is None:
            state["n"] += 1
            return 10_000 - 1000 * state["n"]
        return real(obj)
    sys.getrefcount = fake
sys.argv = ["main.py", "--qt", "--selftest", sys.argv[2], sys.argv[3]]
runpy.run_path("main.py", run_name="__main__")
'''
    for mode in ("real", "leak"):
        out = os.path.join(tmp, f"{mode}.json")
        proc = sp.run([sys.executable, "-B", "-c", RUN, mode, out, clip], cwd=ROOT, env=env,
                      capture_output=True, timeout=120)
        res = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else {}
        if mode == "real":
            check("自檢結果帶 Python 版本與 None 參照數的變化",
                  res.get("python") == sys.version.split()[0] and "none_refcount_drift" in res, str(res))
            check(f"這台（Python {sys.version.split()[0]}）參照數沒被多減、自檢通過",
                  proc.returncode == 0 and res.get("ok") is True and st.none_refcount_ok(res.get("none_refcount_drift")),
                  f"rc={proc.returncode} {res}")
        else:
            check("參照數被多減：影片照樣播得出來，但自檢不通過、結束碼 1",
                  proc.returncode == 1 and res.get("ok") is False and res.get("frames_decoded", 0) > 0
                  and res.get("none_refcount_drift") == -1000, f"rc={proc.returncode} {res}")

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("新介面打包的 Python 版本與 None 參照數自檢測試全數通過。")
