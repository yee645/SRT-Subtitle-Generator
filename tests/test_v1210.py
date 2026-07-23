# -*- coding: utf-8 -*-
"""v1.21.0 新功能測試：全片停頓自動跳剪（Jump Cut）＋字幕同步對齊。"""
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

from subtitle import jumpcut as jc


def cue(start, end, text):
    return {"start": start, "end": end, "text": text}


# ===== 1. 設定解析與夾限 =====
s = jc.resolve_jumpcut_settings(None)
check("預設值", s == jc.DEFAULT_JUMPCUT, str(s))
s2 = jc.resolve_jumpcut_settings({"jumpcut": {
    "min_gap": 0.1, "pad": 99, "max_cut_ratio": 0.95}})
check("min_gap 夾下限", s2["min_gap"] == 0.5)
check("pad 夾上限", s2["pad"] == 1.0)
check("max_cut_ratio 夾上限", s2["max_cut_ratio"] == 0.9)
s3 = jc.resolve_jumpcut_settings({"jumpcut": {"min_gap": "bad"}})
check("非數值回預設", s3["min_gap"] == jc.DEFAULT_JUMPCUT["min_gap"])

# ===== 2. find_cut_gaps：找出句間過長停頓 =====
cues = [cue(0.0, 2.0, "a"), cue(3.5, 5.0, "b"),   # 1.5s 停頓
       cue(5.3, 7.0, "c"),                        # 0.3s 太短不算
       cue(10.0, 12.0, "d")]                      # 3.0s 停頓
gaps = jc.find_cut_gaps(cues, 1.2)
check("找出正確的停頓區間", gaps == [(2.0, 3.5), (7.0, 10.0)], str(gaps))
check("不足門檻不列入", (5.0, 5.3) not in gaps)
check("少於 2 句不炸", jc.find_cut_gaps([cue(0, 1, "x")], 1.0) == [])
check("空清單不炸", jc.find_cut_gaps([], 1.0) == [])

# 未排序輸入也要能正確找出（依 start 排序後處理）。
unsorted_cues = [cue(10.0, 12.0, "d"), cue(0.0, 2.0, "a"), cue(3.5, 5.0, "b")]
gaps_unsorted = jc.find_cut_gaps(unsorted_cues, 1.2)
check("未排序輸入照樣正確", gaps_unsorted == [(2.0, 3.5), (5.0, 10.0)],
      str(gaps_unsorted))

# ===== 3. compute_keep_segments：轉成保留片段＋緩衝 =====
keep, cut_count = jc.compute_keep_segments(12.0, [(2.0, 3.5), (7.0, 10.0)], 0.15)
check("保留片段正確（含緩衝）",
      keep == [(0.0, 2.15), (3.35, 7.15), (9.85, 12.0)], str(keep))
check("跳剪次數正確", cut_count == 2)

# 緩衝後無可剪空間時視為不夠格（例如停頓恰好等於 2*pad）。
keep2, cut2 = jc.compute_keep_segments(10.0, [(2.0, 2.3)], 0.15)
check("緩衝後無空間時不剪", cut2 == 0 and keep2 == [(0.0, 10.0)], str(keep2))

# ===== 4. remap_cues：時間軸重新對映 =====
new_cues = jc.remap_cues(cues, keep)
check("cue a 不變（第一段）",
      new_cues[0]["start"] == 0.0 and new_cues[0]["end"] == 2.0)
check("cue b 正確位移",
      new_cues[1]["start"] == 2.3 and new_cues[1]["end"] == 3.8, str(new_cues[1]))
check("cue c 與 b 同段位移",
      new_cues[2]["start"] == 4.1 and new_cues[2]["end"] == 5.8, str(new_cues[2]))
check("cue d 落在第三段並正確位移",
      new_cues[3]["start"] == 6.1 and new_cues[3]["end"] == 8.1, str(new_cues[3]))
check("文字內容不變",
      [c["text"] for c in new_cues] == ["a", "b", "c", "d"])
check("cue 數量不變（無跨界需丟棄）", len(new_cues) == len(cues))

# ===== 5. _build_filter_complex：video+audio／純音訊／純影像 =====
fc, maps = jc._build_filter_complex([(0.0, 2.0), (3.0, 5.0)], True, True)
check("雙串流 concat 參數正確", "concat=n=2:v=1:a=1[vout][aout]" in fc, fc)
check("雙串流 map 正確", maps == ["-map", "[vout]", "-map", "[aout]"])
fc_v, maps_v = jc._build_filter_complex([(0.0, 2.0)], True, False)
check("純影像 concat 參數正確", "v=1:a=0[vout]" in fc_v, fc_v)
check("純影像 map 正確", maps_v == ["-map", "[vout]"])
check("純影像不含 atrim", "atrim" not in fc_v)
fc_a, maps_a = jc._build_filter_complex([(0.0, 2.0)], False, True)
check("純音訊 concat 參數正確", "v=0:a=1[aout]" in fc_a, fc_a)
check("純音訊 map 正確", maps_a == ["-map", "[aout]"])
check("純音訊不含 trim(影像)", "[0:v]trim" not in fc_a)

# ===== 6. suggest_output_path =====
check("輸出檔名加後綴", jc.suggest_output_path("影片.mp4") == "影片_跳剪.mp4")
check("無副檔名補 .mp4", jc.suggest_output_path("影片") == "影片_跳剪.mp4")

# ===== 7. apply_jumpcut：安全防呆（無需真的跑 ffmpeg 的錯誤路徑） =====
try:
    jc.apply_jumpcut("不存在.mp4", cues, "out.mp4")
    check("找不到檔案時報錯", False)
except FileNotFoundError:
    check("找不到檔案時報錯", True)

with tempfile.TemporaryDirectory() as tmp:
    fake_src = os.path.join(tmp, "fake.mp4")
    open(fake_src, "wb").write(b"x")
    tight_cues = [cue(0.0, 2.0, "a"), cue(2.1, 4.0, "b")]  # 無達門檻停頓
    try:
        jc.apply_jumpcut(fake_src, tight_cues, os.path.join(tmp, "o.mp4"))
        check("無可跳剪停頓時報錯", False)
    except ValueError as exc:
        check("無可跳剪停頓時報錯", "未偵測到" in str(exc), str(exc))

    huge_gap_cues = [cue(0.0, 1.0, "a"), cue(11.0, 12.0, "b")]
    orig_probe = jc.probe_duration
    jc.probe_duration = lambda p: 12.0
    try:
        jc.apply_jumpcut(fake_src, huge_gap_cues, os.path.join(tmp, "o2.mp4"),
                         settings={"min_gap": 1.2, "pad": 0.15,
                                   "max_cut_ratio": 0.3})
        check("跳剪比例超標時報錯", False)
    except ValueError as exc:
        check("跳剪比例超標時報錯", "超過影片長度" in str(exc), str(exc))
    finally:
        jc.probe_duration = orig_probe

# ===== 8. format_jumpcut_report =====
report_text = jc.format_jumpcut_report({
    "cut_count": 2, "removed_seconds": 4.4,
    "original_seconds": 12.0, "kept_seconds": 7.6})
check("報告含跳剪次數與秒數", "共跳剪 2 處停頓" in report_text
      and "7.6 秒" in report_text, report_text)

# ===== 9. config／CLI／GUI 靜態掃描 =====
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from config import DEFAULT_CONFIG
check("config 預設含 jumpcut 區",
      DEFAULT_CONFIG["jumpcut"] == jc.DEFAULT_JUMPCUT,
      str(DEFAULT_CONFIG.get("jumpcut")))

with open(os.path.join(root, "cli.py"), encoding="utf-8") as fp:
    cli_src = fp.read()
check("cli.py 有 --jumpcut 旗標", "--jumpcut" in cli_src)

with open(os.path.join(root, "gui", "jumpcut_dialog.py"),
          encoding="utf-8") as fp:
    dialog_src = fp.read()
check("對話框無 classic tk.Checkbutton/Radiobutton 殘留",
      "tk.Checkbutton(" not in dialog_src.replace("ttk.Checkbutton(", "")
      and "tk.Radiobutton(" not in dialog_src.replace("ttk.Radiobutton(", ""))

with open(os.path.join(root, "gui", "app.py"), encoding="utf-8") as fp:
    app_src = fp.read()
check("app.py 有自動跳剪按鈕與 handler",
      "自動跳剪停頓" in app_src and "_open_jumpcut_dialog" in app_src)

# ===== 10. media.py 共用 has_video_stream／has_audio_stream =====
from subtitle import media, audiofix
check("audiofix 重用 media.has_video_stream（同一函式物件）",
      audiofix.has_video_stream is media.has_video_stream)

# ===== 11. 真實 CLI 端到端（合成測試媒體＋跳剪＋字幕同步對齊） =====
import shutil
if shutil.which("ffmpeg"):
    with tempfile.TemporaryDirectory() as tmp:
        clip = os.path.join(tmp, "clip.mp4")
        srt = os.path.join(tmp, "clip.srt")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=12:r=25",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
             "-shortest", "-c:v", "libx264", "-c:a", "aac", clip],
            capture_output=True, timeout=60)
        with open(srt, "w", encoding="utf-8") as fp:
            fp.write(
                "1\n00:00:00,000 --> 00:00:02,000\n第一句話\n\n"
                "2\n00:00:04,000 --> 00:00:06,000\n第二句話\n\n"
                "3\n00:00:09,000 --> 00:00:11,500\n第三句話\n\n"
            )
        env_main = os.path.join(root, "main.py")
        proc = subprocess.run(
            [sys.executable, env_main, "--subs", srt, "--jumpcut",
             "--formats", "srt", clip],
            cwd=tmp, capture_output=True, text=True, timeout=120)
        check("實測：CLI --subs --jumpcut 執行成功",
              proc.returncode == 0, proc.stdout + proc.stderr)
        video_out = os.path.join(tmp, "clip_跳剪.mp4")
        srt_out = os.path.join(tmp, "clip_跳剪.srt")
        check("實測：跳剪影片已產生", os.path.exists(video_out))
        check("實測：對齊後字幕已產生", os.path.exists(srt_out))
        if os.path.exists(video_out):
            dur_proc = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "format=duration", "-of",
                 "default=noprint_wrappers=1:nokey=1", video_out],
                capture_output=True, text=True, timeout=30)
            try:
                out_dur = float(dur_proc.stdout.strip())
            except ValueError:
                out_dur = 0.0
            # 原 12 秒，跳剪掉兩段停頓（各含緩衝共約 4.4 秒）後應明顯變短。
            check("實測：跳剪後長度明顯縮短",
                  0.0 < out_dur < 10.0, f"out_dur={out_dur}")
        if os.path.exists(srt_out):
            srt_text = open(srt_out, encoding="utf-8").read()
            check("實測：字幕內容仍完整保留三句",
                  all(word in srt_text for word in ["第一句話", "第二句話", "第三句話"]),
                  srt_text)
            # 對齊後第二句開始時間應明顯早於原本的 00:00:04（因為前面的停頓被剪掉）。
            check("實測：字幕時間軸確實被重新對齊（提前）",
                  "00:00:04,000" not in srt_text, srt_text)
else:
    print("SKIP 實測（無 ffmpeg）")

print()
if failures:
    print(f"共 {len(failures)} 項失敗：{failures}")
    sys.exit(1)
print("test_v1210 全部通過")
