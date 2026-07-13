# -*- coding: utf-8 -*-
"""
一鍵執行全部功能測試。

    python tests/run_all.py

各測試檔皆以替身（stub）隔離 whisper／ffmpeg 相依，無須安裝任何
外部程式即可執行；每檔獨立子程序跑完並回報結果，全部通過才回傳 0。
"""

import os
import subprocess
import sys

TESTS = ["test_pipeline.py", "test_review.py", "test_v140.py", "test_v150.py",
         "test_v160.py", "test_v170.py", "test_v180.py", "test_v190.py",
         "test_v1100.py", "test_v1110.py"]


def main() -> int:
    base = os.path.dirname(os.path.abspath(__file__))
    failed = []
    for name in TESTS:
        print(f"===== {name} =====", flush=True)
        result = subprocess.run([sys.executable, os.path.join(base, name)])
        if result.returncode != 0:
            failed.append(name)
    print()
    if failed:
        print(f"測試失敗：{', '.join(failed)}")
        return 1
    print(f"全部 {len(TESTS)} 個測試檔通過。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
