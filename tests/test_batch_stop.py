# -*- coding: utf-8 -*-
"""
3.0 第 11 項第二十二階段：`pipeline.run_batch` 的 should_stop（批次中途停止）。

whisper 與燒錄換成替身（同 test_pipeline.py）。驗：
1. 沒給 should_stop：行為跟以前一樣（每支都跑、一支失敗不中斷）。
2. 每支開始之前問一次；回 True 之後不再開始下一支，正在跑的那支照樣跑完；沒處理的各回一筆
   （ok False、skipped True、照原本的順序），進度回報講還有幾支沒處理。
3. 一開始就停：一支都不跑，全部 skipped。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import load_config  # noqa: E402
from subtitle import pipeline  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)


WORDS = [{"word": "你好", "start": 0.0, "end": 0.5}, {"word": "世界", "start": 0.5, "end": 1.0}]
ran = []


def fake_transcribe(path, config, status_cb=None, initial_prompt=""):
    ran.append(os.path.basename(path))
    return list(WORDS)


pipeline.transcribe = fake_transcribe

with tempfile.TemporaryDirectory() as tmp:
    paths = []
    for name in ("一.mp4", "二.mp4", "三.mp4", "四.mp4"):
        path = os.path.join(tmp, name)
        open(path, "wb").write(b"x")
        paths.append(path)
    cfg = load_config()
    cfg["automation"] = {"export_srt": True, "export_vtt": False, "export_ass": False, "export_txt": False,
                         "burn_video": False, "output_dir": ""}

    # ----- 1. 沒給 should_stop -----
    results = pipeline.run_batch(paths[:2] + [os.path.join(tmp, "缺.mp4")], cfg)
    check("沒給 should_stop：每支都跑、失敗不中斷、沒有 skipped", [r["ok"] for r in results] == [True, True, False]
          and not any(r.get("skipped") for r in results) and ran == ["一.mp4", "二.mp4"], str(results))

    # ----- 2. 跑完第二支時按停止 -----
    ran.clear()
    asked = []
    messages = []

    def stop_after_two():
        asked.append(len(ran))
        return len(ran) >= 2
    results = pipeline.run_batch(paths, cfg, should_stop=stop_after_two,
                                 report=lambda m, r=None: messages.append((m, r)))
    check("每支開始之前問一次（第三支之前停）", asked == [0, 1, 2], str(asked))
    check("前兩支照樣跑完、成功", ran == ["一.mp4", "二.mp4"] and [r["ok"] for r in results[:2]] == [True, True])
    check("沒處理的兩支各回一筆、照原本的順序", [r["path"] for r in results] == paths
          and [r.get("skipped", False) for r in results] == [False, False, True, True]
          and all(not r["ok"] and r["result"] is None and r["error"] == "已停止，沒有處理" for r in results[2:]))
    check("進度回報講還有幾支沒處理", ("已停止：還有 2 個檔案沒有處理。", None) in messages, str(messages[-3:]))
    check("沒處理的沒有輸出檔", not os.path.exists(os.path.join(tmp, "三.srt"))
          and os.path.exists(os.path.join(tmp, "二.srt")))

    # ----- 3. 一開始就停 -----
    ran.clear()
    results = pipeline.run_batch(paths, cfg, should_stop=lambda: True)
    check("一開始就停：一支都不跑、全部 skipped", ran == [] and len(results) == 4
          and all(r.get("skipped") and not r["ok"] for r in results))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("批次停止（run_batch should_stop）測試全數通過。")
