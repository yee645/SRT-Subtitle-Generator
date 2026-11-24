# -*- coding: utf-8 -*-
"""
3.0 第 12 項 12-5：一般版的「3.0 新介面」提示（gui/qtbridge_dialog.py＋gui/app.py 的接線），在 Xvfb 下真的點。

1. 提示：說明（版本、裝在哪、一般版留著）、會送什麼；〔下載並安裝新介面〕〔以後再說〕；「不再提醒」預設沒勾。
2. 按〔下載並安裝新介面〕：背景跑安裝（傳進去的是 offer、exe 資料夾、設定檔資料夾）；進度條與那一行跟著動；
   只剩〔取消下載〕；解壓時〔取消下載〕變灰；裝好換成〔開啟新介面〕〔關閉〕與裝好的說明。
3. 〔開啟新介面〕：用 launch_args 的命令列與工作目錄開、關掉視窗、回報一次（沒勾＝False）；開不起來講原因、視窗留著。
4. 取消：按〔取消下載〕→ 安裝收到取消 → 講已取消、〔再試一次〕；再試一次會再跑。壞掉：講原因、〔再試一次〕〔關閉〕。
   下載中直接關視窗也會叫安裝停下來。
5. 勾「不再提醒」按〔以後再說〕：回報 True、只回報一次。
6. 主視窗的接線：有新的一般版時只提示更新、不查新介面；沒有時，打包好的 Windows 一般版、沒勾過不再提醒才去查，
   查到了經過佇列跳提示；從原始碼跑、勾過不再提醒都不查。提示裡勾「不再提醒」→ 存進 config.json 的 qt_bridge。
7. 截圖（深淺兩色）存到 QTBRIDGE_SHOTS 指定的資料夾（有設才存）。
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


try:
    import tkinter as tk
    root = tk.Tk()
except Exception as exc:  # noqa: BLE001
    print(f"SKIP 沒有顯示器或 tkinter：{exc}")
    sys.exit(0)

from subtitle import onedirupdate as odu  # noqa: E402
from subtitle import qtbridge as qb  # noqa: E402
from gui import qtbridge_dialog as qd  # noqa: E402

root.geometry("160x60+900+700")  # 提示視窗是它的 transient：主視窗藏起來的話提示也不會出現


def pump(seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def wait_for(cond, seconds=5):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        if cond():
            return True
        time.sleep(0.01)
    return False


def shown(dlg):
    return [b.cget("text") for b in dlg._row.pack_slaves()]


tmp = tempfile.mkdtemp()
exe_dir = os.path.join(tmp, "字幕工具")
cfg_dir = os.path.join(tmp, "設定")
os.makedirs(exe_dir)
os.makedirs(cfg_dir)
info = {"version": "v3.0.0", "asset": {"name": "SRT-Subtitle-Generator-Qt-v3.0.0-win64.zip",
                                       "url": odu.DOWNLOAD_PREFIX + "v3.0.0/x-win64.zip", "size": 150_000_000},
        "page": "https://github.com/yee645/SRT-Subtitle-Generator/releases/tag/v3.0.0"}
QT_EXE = os.path.join(qb.qt_dir(exe_dir), odu.EXE_NAME)


class FakeInstall:
    """換掉 qtbridge.install：每一步等測試放行。"""

    def __init__(self, result=QT_EXE):
        self.result = result
        self.calls = []
        self.go_prepare = threading.Event()
        self.go_finish = threading.Event()
        self.saw_cancel = None

    def __call__(self, offer, exe, cfg, progress=None, cancelled=None, preparing=None):
        self.calls.append((offer, exe, cfg))
        for i in range(1, 4):
            progress(i * 50_000_000, 150_000_000)
        while not self.go_prepare.wait(0.02):
            if cancelled():
                self.saw_cancel = True
                raise odu.UpdateError(odu.CANCELLED)
        preparing()
        self.go_finish.wait(5)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


shots = os.environ.get("QTBRIDGE_SHOTS")


def shoot(dlg, name):
    if not shots:
        return
    os.makedirs(shots, exist_ok=True)
    dlg.update()
    pump(0.3)
    geo = f"{dlg.winfo_width()}x{dlg.winfo_height()}+{dlg.winfo_rootx()}+{dlg.winfo_rooty()}"
    subprocess.run(["import", "-window", "root", "-crop", geo, "+repage", os.path.join(shots, name)],
                   check=False, timeout=20)


def set_theme(theme):
    try:
        import sv_ttk
        sv_ttk.set_theme(theme)
    except Exception:  # noqa: BLE001
        pass


# ----- 1 -----
remembered = []
launched = []
inst = FakeInstall()
set_theme("light")
dlg = qd.QtBridgeDialog(root, info, exe_dir, cfg_dir, on_remember=remembered.append, install_fn=inst,
                        launch_fn=lambda args, cwd: launched.append((args, cwd)))
pump()
text = dlg.text_var.get()
check("提示：版本、裝在哪、一般版留著", "v3.0.0" in text and qb.qt_dir(exe_dir) in text and "一般版不會被刪掉" in text
      and dlg.title() == qd.TITLE, text)
check("提示：寫明會送什麼", dlg.sends_label.cget("text") == qb.SENDS)
check("按鈕：〔下載並安裝新介面〕〔以後再說〕", shown(dlg) == [qd.INSTALL_LABEL, qd.LATER_LABEL], str(shown(dlg)))
check("「不再提醒」預設沒勾、進度條還沒出現", dlg.never_var.get() is False and not dlg.progress.winfo_ismapped()
      and dlg.never_check.winfo_ismapped() and dlg.sends_label.winfo_ismapped())
shoot(dlg, "qtbridge_offer_light.png")

# ----- 2 -----
dlg.install_btn.invoke()
check("按下去：背景安裝拿到 offer、exe 資料夾、設定檔資料夾", wait_for(lambda: inst.calls)
      and inst.calls[0] == (info, exe_dir, cfg_dir), str(inst.calls))
check("進度條與那一行跟著動", wait_for(lambda: dlg.progress_var.get() >= 99.9) and "100%" in dlg.status_var.get()
      and dlg.progress.winfo_ismapped(), f"{dlg.progress_var.get()} {dlg.status_var.get()}")
check("下載中只剩〔取消下載〕、點得到", shown(dlg) == [qd.CANCEL_LABEL] and str(dlg.cancel_btn.cget("state")) == "normal")
shoot(dlg, "qtbridge_downloading_light.png")
inst.go_prepare.set()
check("解壓時〔取消下載〕變灰", wait_for(lambda: dlg.state == "preparing")
      and str(dlg.cancel_btn.cget("state")) == "disabled" and "解壓" in dlg.status_var.get())
inst.go_finish.set()
check("裝好：〔開啟新介面〕〔關閉〕與裝好的說明", wait_for(lambda: dlg.state == "done")
      and shown(dlg) == [qd.OPEN_LABEL, qd.CLOSE_LABEL] and dlg.text_var.get() == qb.done_text(QT_EXE)
      and not dlg.progress.winfo_ismapped(), str(shown(dlg)))
check("裝好之後不再講會送什麼、不再問要不要提醒", not dlg.sends_label.winfo_ismapped()
      and not dlg.never_check.winfo_ismapped() and dlg.text_label.winfo_ismapped())
shoot(dlg, "qtbridge_done_light.png")

# ----- 3 -----
dlg.open_btn.invoke()
pump(0.1)
check("〔開啟新介面〕：用 launch_args 開、關掉視窗、回報一次（沒勾＝False）",
      launched == [qb.launch_args(QT_EXE)] and not dlg.winfo_exists() and remembered == [False],
      f"{launched} {remembered}")


def failing_launch(args, cwd):
    raise OSError("被防毒擋了")


inst = FakeInstall()
inst.go_prepare.set()
inst.go_finish.set()
remembered.clear()
dlg = qd.QtBridgeDialog(root, info, exe_dir, cfg_dir, on_remember=remembered.append, install_fn=inst,
                        launch_fn=failing_launch)
dlg.install_btn.invoke()
wait_for(lambda: dlg.state == "done")
dlg.open_btn.invoke()
pump(0.1)
check("開不起來：講原因與怎麼自己開、視窗留著", dlg.winfo_exists() and "被防毒擋了" in dlg.status_var.get()
      and dlg.status_label.winfo_ismapped()
      and odu.EXE_NAME in dlg.status_var.get() and remembered == [], dlg.status_var.get())
dlg.close()

# ----- 4 -----
inst = FakeInstall()
remembered.clear()
set_theme("dark")
dlg = qd.QtBridgeDialog(root, info, exe_dir, cfg_dir, on_remember=remembered.append, install_fn=inst,
                        launch_fn=lambda a, c: None)
shoot(dlg, "qtbridge_offer_dark.png")
dlg.install_btn.invoke()
wait_for(lambda: dlg.progress_var.get() >= 99.9)
shoot(dlg, "qtbridge_downloading_dark.png")
dlg.cancel_btn.invoke()
check("取消：安裝收到取消、講已取消、〔再試一次〕〔關閉〕", wait_for(lambda: dlg.state == "error")
      and inst.saw_cancel and dlg.status_var.get() == odu.CANCELLED
      and shown(dlg) == [qd.RETRY_LABEL, qd.CLOSE_LABEL], str(shown(dlg)))
shoot(dlg, "qtbridge_error_dark.png")
inst.go_prepare.set()
inst.result = odu.UpdateError("zip 裡找不到 SRT-Subtitle-Generator-Qt.exe。")
inst.go_finish.set()
dlg.install_btn.invoke()
check("〔再試一次〕會再跑；壞掉講原因", wait_for(lambda: dlg.state == "error" and len(inst.calls) == 2)
      and "找不到" in dlg.status_var.get(), dlg.status_var.get())
inst.result = RuntimeError("沒想到的錯")
dlg.install_btn.invoke()
check("不認得的錯也講出來、不會卡在下載中", wait_for(lambda: dlg.state == "error" and len(inst.calls) == 3)
      and "沒想到的錯" in dlg.status_var.get(), dlg.status_var.get())
dlg.close()

inst = FakeInstall()
dlg = qd.QtBridgeDialog(root, info, exe_dir, cfg_dir, install_fn=inst, launch_fn=lambda a, c: None)
dlg.install_btn.invoke()
wait_for(lambda: inst.calls)
dlg.close()
deadline = time.time() + 3
while inst.saw_cancel is None and time.time() < deadline:
    time.sleep(0.02)
check("下載中直接關視窗：安裝也停下來", inst.saw_cancel is True)
set_theme("light")

# ----- 5 -----
remembered.clear()
dlg = qd.QtBridgeDialog(root, info, exe_dir, cfg_dir, on_remember=remembered.append, install_fn=FakeInstall(),
                        launch_fn=lambda a, c: None)
dlg.never_check.invoke()
dlg.close_btn.invoke()
pump(0.1)
gone = not dlg.winfo_exists()
dlg.close()  # 已經關了再 close()：不會多回報一次
check("勾「不再提醒」按〔以後再說〕：回報 True、只一次", remembered == [True] and gone, str(remembered))

# ----- 6 -----
root.destroy()
import config as app_config  # noqa: E402
cfg_path = os.path.join(tmp, "config.json")
with open(cfg_path, "w", encoding="utf-8") as fp:
    json.dump({"whatsnew_seen": "never"}, fp)
app_config.CONFIG_PATH = cfg_path
import gui.app as gapp  # noqa: E402

checks_made = []
gapp.check_for_update = lambda: checks_made.append("check") or None  # 啟動時排的那一次也不連網
app = gapp.SrtApp()
for _ in range(30):
    app.update()

real = {name: getattr(qb, name) for name in ("bridge_dir", "fetch_offer")}
fetches = []
offer = dict(info)


def drain():
    items = []
    while not app.result_queue.empty():
        items.append(app.result_queue.get_nowait())
    return items


def fake_fetch(*a, **k):
    fetches.append(1)
    return offer


try:
    qb.fetch_offer = fake_fetch
    gapp.check_for_update = lambda: {"version": "v3.0.1", "url": "x", "notes": ""}
    qb.bridge_dir = lambda *a: exe_dir
    drain()
    app._update_check_worker()
    items = drain()
    check("有新的一般版：只提示更新、不查新介面", [k for k, _ in items] == ["update"] and fetches == [], str(items))

    gapp.check_for_update = lambda: None
    app._update_check_worker()
    items = drain()
    check("沒有新的一般版、打包好的 Windows 一般版：查到了就排提示", fetches == [1]
          and items == [("qt_bridge", (offer, exe_dir))], str(items))

    fetches.clear()
    qb.bridge_dir = real["bridge_dir"]
    app._update_check_worker()
    check("從原始碼跑：不查", fetches == [] and drain() == [])

    qb.bridge_dir = lambda *a: exe_dir
    app.config_data[qb.CONFIG_KEY] = qb.NEVER
    app._update_check_worker()
    check("勾過不再提醒：不查", fetches == [] and drain() == [])
    app.config_data.pop(qb.CONFIG_KEY)

    qb.fetch_offer = lambda *a, **k: fetches.append(1) or None
    app._update_check_worker()
    check("查不到能裝的：不排提示", fetches == [1] and drain() == [])
finally:
    for name, fn in real.items():
        setattr(qb, name, fn)

app.result_queue.put(("qt_bridge", (offer, exe_dir)))
check("經過佇列跳出提示（設定檔資料夾＝目前的工作目錄）", wait_for(
    lambda: getattr(app, "_qt_bridge_dialog", None) is not None and app._qt_bridge_dialog.winfo_exists(), 3)
    and app._qt_bridge_dialog.config_dir == os.getcwd() and app._qt_bridge_dialog.exe_dir == exe_dir)
dlg = app._qt_bridge_dialog
dlg.never_check.invoke()
dlg.close_btn.invoke()
for _ in range(10):
    app.update()
with open(cfg_path, encoding="utf-8") as fp:
    saved = json.load(fp)
check("勾「不再提醒」：存進 config.json 的 qt_bridge、讀回來還在", saved.get(qb.CONFIG_KEY) == qb.NEVER
      and app_config.load_config().get(qb.CONFIG_KEY) == qb.NEVER, str(saved)[:200])

app.config_data.pop(qb.CONFIG_KEY)  # 回到沒勾過的狀態，才看得出「沒勾就關」有沒有寫 never
app._save_config_silently()
app.result_queue.put(("qt_bridge", (offer, exe_dir)))
wait_for(lambda: app._qt_bridge_dialog is not dlg and app._qt_bridge_dialog.winfo_exists(), 3)
before = open(cfg_path, encoding="utf-8").read()
app._qt_bridge_dialog.close_btn.invoke()
for _ in range(10):
    app.update()
check("沒勾就關：不寫設定檔、也沒記 never", open(cfg_path, encoding="utf-8").read() == before
      and qb.CONFIG_KEY not in before and qb.CONFIG_KEY not in app.config_data)
app.destroy()

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("3.0 一般版到新介面的橋（介面）測試全數通過。")
