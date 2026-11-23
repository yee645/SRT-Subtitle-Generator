# -*- coding: utf-8 -*-
"""
背景查新版本（3.0 第 11 項第三十階段），以及資料夾版的背景下載與準備（第 12 項 12-3，核心在 `subtitle/onedirupdate.py`）。
查法與提示文字在 `subtitle/updatecheck.py`；提示列在 `gui_qt/app.py`。

會送出去的：向 GitHub API 查最新 Release 的一般連線請求，不含任何檔案、字幕、設定或帳號資訊（`updatecheck.SENDS`）。
"""
import threading

from PySide6.QtCore import QObject, Signal

from subtitle import updatecheck


class UpdateWorker(QObject):
    """背景執行緒跑 `updatecheck.fetch_latest`；查到比目前新的版本發 `finished(info)`，否則發 `finished(None)`。"""

    finished = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False

    def start(self, current):
        if self.busy:
            return False
        self.busy = True
        threading.Thread(target=self._run, args=(current,), daemon=True).start()
        return True

    def _run(self, current):
        info = updatecheck.fetch_latest(current)
        self.busy = False
        self.finished.emit(info)


class InstallWorker(QObject):
    """
    背景下載並準備新版（第 12 項 12-3）：下載 zip → 安全解壓到程式資料夾旁邊 → 帶上設定、生字本、tools → 寫好切換腳本。

    progress(已下載, 總共)；preparing()＝下載完、開始解壓；finished(結果)：成功是 {"new_dir", "script", "copied"}，
    失敗或取消是 {"error": 給使用者看的訊息}。切換本身要等程式關掉（`gui_qt/app.py` 的 closeEvent）。
    會送出去的：只有向 GitHub 下載 zip 的連線請求（`onedirupdate.SENDS`）。
    """

    progress = Signal(int, int)
    preparing = Signal()
    finished = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        self._cancel = False

    def start(self, asset, version, app_dir, config_dir, pid):
        if self.busy:
            return False
        self.busy = True
        self._cancel = False
        threading.Thread(target=self._run, args=(asset, version, app_dir, config_dir, pid), daemon=True).start()
        return True

    def cancel(self):
        self._cancel = True

    def _run(self, asset, version, app_dir, config_dir, pid):
        import os
        import tempfile

        from subtitle import onedirupdate as odu

        zip_path = None
        try:
            parent = os.path.dirname(os.path.abspath(app_dir))
            zip_path = odu.download(asset, parent, progress=lambda d, t: self.progress.emit(d, t),
                                    cancelled=lambda: self._cancel)
            self.preparing.emit()
            new_dir = odu.extract(zip_path, app_dir, version)
            copied = odu.carry_over(app_dir, config_dir, new_dir)
            text = odu.switch_script(pid, app_dir, new_dir, odu.work_dir(app_dir, config_dir))
            script = odu.write_script(text, tempfile.mkdtemp(prefix="srt-update-"))  # 不放在要被改名的資料夾裡
            result = {"new_dir": new_dir, "script": script, "copied": copied}
        except odu.UpdateError as exc:
            result = {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001 —— 磁碟滿、沒權限：講原因，不讓背景執行緒默默死掉
            result = {"error": f"準備新版失敗：{exc}"}
        finally:
            if zip_path:
                try:
                    os.remove(zip_path)
                except OSError:
                    pass
        self.busy = False
        self.finished.emit(result)
