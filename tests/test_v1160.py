# -*- coding: utf-8 -*-
"""v1.16.0 既有功能精修測試：對話框深色主題全面化、封面候選短片自適應、
孤字合併時間防護。"""
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

from subtitle import segmenter, thumbnails

# ===== 1. 孤字合併：時間防護與 CJK 感知接回 =====
def cue(start, end, text):
    return {"start": start, "end": end, "text": text}

# 間隔小 → 照舊併回
close = segmenter._merge_orphan_cues(
    [cue(0.0, 2.0, "今天天氣很好"), cue(2.3, 2.8, "喔")])
check("近距離孤字仍併回", len(close) == 1 and close[0]["text"].endswith("喔")
      and close[0]["end"] == 2.8, str(close))

# 間隔大（停頓後的反應詞）→ 不併，前一句不被拉長
far = segmenter._merge_orphan_cues(
    [cue(0.0, 2.0, "今天天氣很好"), cue(5.5, 6.0, "嗯")])
check("停頓後孤字不併回", len(far) == 2 and far[0]["end"] == 2.0, str(far))

# 英文孤字接回要補空白
latin = segmenter._merge_orphan_cues(
    [cue(0.0, 2.0, "let's go"), cue(2.2, 2.6, "ok")])
check("英文孤字接回補空白", len(latin) == 1
      and latin[0]["text"] == "let's go ok", str(latin))

# 中文孤字接回不補空白
cjk = segmenter._merge_orphan_cues(
    [cue(0.0, 2.0, "我們走吧"), cue(2.2, 2.6, "好")])
check("中文孤字接回不補空白", len(cjk) == 1
      and cjk[0]["text"] == "我們走吧好", str(cjk))

# ===== 2. 封面候選：短素材自適應間隔 =====
check("長素材間隔不變",
      thumbnails.effective_spacing(600.0, 6, 8.0) == 8.0)
val = thumbnails.effective_spacing(20.0, 6, 8.0)
check("短素材間隔自動縮小",
      abs(val - 20.0 / 7) < 1e-9, str(val))
check("極短素材保留 0.5 秒下限",
      thumbnails.effective_spacing(2.0, 10, 8.0) == 0.5)
check("零長度素材回傳原值",
      thumbnails.effective_spacing(0.0, 6, 8.0) == 8.0)

# 均勻取樣在 20 秒素材上湊滿 6 個窗口（舊版只有 2 個）
settings = thumbnails.resolve_thumbnail_settings(None)
windows = thumbnails.sample_windows(None, 20.0, settings)
check("20 秒素材湊滿 6 個窗口", len(windows) == 6, str(len(windows)))

# ===== 3. 對話框深色主題：無 classic 元件殘留（固定色橫幅除外） =====
import re
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for name in ("review_window", "audiocheck_dialog", "branding_dialog",
             "replace_dialog", "error_dialog", "ffmpeg_dialog",
             "music_dialog"):
    src = open(os.path.join(root, "gui", f"{name}.py"),
               encoding="utf-8").read()
    bad = []
    for m in re.finditer(r"\btk\.(Label|Frame|Entry|Button)\(", src):
        depth, j = 0, m.end() - 1
        while j < len(src):
            if src[j] == "(":
                depth += 1
            elif src[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        call = src[m.start():j + 1]
        if "bg=" not in call:  # 固定色橫幅（帶 bg=）是刻意保留的
            bad.append(call[:60])
    check(f"{name} 無未主題化 classic 元件", not bad, str(bad))

# ===== 4. 真實 ffmpeg：短素材封面候選實際輸出 6 張 =====
if thumbnails.ffmpeg_available():
    with tempfile.TemporaryDirectory() as tmp:
        clip = os.path.join(tmp, "short.mp4")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=20",
             "-c:v", "libx264", clip], capture_output=True, timeout=120)
        results = thumbnails.generate_thumbnails(
            clip, None, 20.0,
            output_paths=lambda rank: os.path.join(tmp, f"t{rank:02d}.png"),
            settings=settings)
        check("實測：20 秒素材輸出滿 6 張候選",
              len(results) == 6, str(len(results)))
        check("實測：候選檔案皆存在且非空",
              all(os.path.getsize(item["path"]) > 0 for item in results))
        times = sorted(item["time"] for item in results)
        min_gap = min(b - a for a, b in zip(times, times[1:]))
        check("實測：候選彼此仍保持間隔",
              min_gap >= 0.5, str(min_gap))
else:
    print("SKIP 實測（無 ffmpeg）")

print()
if failures:
    print(f"共 {len(failures)} 項失敗：{failures}")
    sys.exit(1)
print("test_v1160 全部通過")
