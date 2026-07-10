# -*- coding: utf-8 -*-
"""pipeline 模組的無 GUI 功能測試：以替身取代 whisper/ffmpeg 相依。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle import pipeline
from config import load_config

FAKE_WORDS = [
    {"word": "你好", "start": 0.0, "end": 0.5},
    {"word": "世界", "start": 0.5, "end": 1.0},
    {"word": "這是", "start": 2.0, "end": 2.4},
    {"word": "測試", "start": 2.4, "end": 3.0},
]

def fake_transcribe(path, config, status_cb=None, initial_prompt=""):
    if status_cb:
        status_cb("辨識中", 0.5)
    return list(FAKE_WORDS)

def fake_burn(video_path, cues, output_path, style=None, progress_cb=None, use_ass=True, **kwargs):
    if progress_cb:
        progress_cb(0.5, "燒錄中")
    with open(output_path, "wb") as fp:
        fp.write(b"FAKE_MP4")
    return output_path

pipeline.transcribe = fake_transcribe
pipeline.burn_subtitles = fake_burn
from subtitle import aligner
aligner.transcribe = fake_transcribe

failures = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        failures.append(name)

with tempfile.TemporaryDirectory() as tmp:
    media1 = os.path.join(tmp, "影片A.mp4")
    media2 = os.path.join(tmp, "影片B.mp4")
    for p in (media1, media2):
        open(p, "wb").write(b"x")

    cfg = load_config()
    cfg["automation"] = {
        "export_srt": True, "export_vtt": True, "export_ass": False,
        "export_txt": False, "burn_video": True, "output_dir": "",
    }

    # unique_path
    check("unique_path 不存在時原樣", pipeline.unique_path(os.path.join(tmp, "x.srt")).endswith("x.srt"))
    open(os.path.join(tmp, "dup.srt"), "w").close()
    check("unique_path 衝突時加 (1)", pipeline.unique_path(os.path.join(tmp, "dup.srt")).endswith("dup (1).srt"))

    # 單檔 pipeline
    msgs = []
    result = pipeline.run_pipeline(media1, cfg, mode="transcribe",
                                   report=lambda m, r=None: msgs.append((m, r)))
    check("產生 cues", len(result["cues"]) >= 1)
    check("匯出 srt+vtt 兩檔", len(result["exports"]) == 2)
    check("匯出到來源資料夾", all(os.path.dirname(p) == tmp for p in result["exports"]))
    check("匯出檔以來源命名", os.path.basename(result["exports"][0]) == "影片A.srt")
    check("燒錄輸出存在", result["burned"] and os.path.exists(result["burned"]))
    check("燒錄檔名 _subtitled", result["burned"].endswith("影片A_subtitled.mp4"))
    ratios = [r for _, r in msgs if r is not None]
    check("進度單調遞增", ratios == sorted(ratios) and ratios[-1] == 1.0)

    # 再跑一次：不得覆蓋，應產生 (1)
    result2 = pipeline.run_pipeline(media1, cfg, mode="transcribe")
    check("重跑不覆蓋 (1)", result2["exports"][0].endswith("影片A (1).srt"))

    # 指定輸出資料夾
    outdir = os.path.join(tmp, "out")
    cfg["automation"]["output_dir"] = outdir
    r3 = pipeline.run_pipeline(media1, cfg)
    check("輸出到指定資料夾", all(os.path.dirname(p) == outdir for p in r3["exports"]))
    cfg["automation"]["output_dir"] = ""

    # 批次：一檔成功、一檔不存在 → 不中斷
    batch = pipeline.run_batch([media2, os.path.join(tmp, "缺.mp4")], cfg)
    check("批次共 2 筆結果", len(batch) == 2)
    check("第一檔成功", batch[0]["ok"])
    check("第二檔失敗但有錯誤訊息", not batch[1]["ok"] and batch[1]["error"])

    # align 模式：sidecar txt
    with open(os.path.join(tmp, "影片B.txt"), "w", encoding="utf-8") as fp:
        fp.write("你好世界\n這是測試")
    r4 = pipeline.run_pipeline(media2, cfg, mode="align", transcript="")
    check("align sidecar 產生 cues", len(r4["cues"]) >= 1)

    # align 無文字稿也無 sidecar → 明確錯誤
    try:
        pipeline.run_pipeline(media1, cfg, mode="align", transcript="")
        check("align 缺文字稿應報錯", False)
    except ValueError as exc:
        check("align 缺文字稿應報錯", "文字稿" in str(exc))

    # 未勾任何輸出 → 明確錯誤
    cfg["automation"] = {k: False for k in cfg["automation"]}
    cfg["automation"]["output_dir"] = ""
    try:
        pipeline.run_pipeline(media1, cfg)
        check("未勾輸出應報錯", False)
    except ValueError:
        check("未勾輸出應報錯", True)

print("\n" + ("ALL PASS" if not failures else f"FAILURES: {failures}"))
sys.exit(1 if failures else 0)
