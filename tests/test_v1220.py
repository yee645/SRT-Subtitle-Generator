# -*- coding: utf-8 -*-
"""v1.22.0 新功能測試：重複片段（NG 重錄）偵測與一鍵剪除。"""
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

from subtitle import retakes as rt


def cue(start, end, text):
    return {"start": start, "end": end, "text": text}


# ===== 1. 設定解析與夾限 =====
s = rt.resolve_retake_settings(None)
check("預設值", s == rt.DEFAULT_RETAKES, str(s))
s2 = rt.resolve_retake_settings({"retakes": {
    "similarity_threshold": 0.1, "max_gap_seconds": 999, "pad": 99}})
check("similarity_threshold 夾下限", s2["similarity_threshold"] == 0.5)
check("max_gap_seconds 夾上限", s2["max_gap_seconds"] == 120.0)
check("pad 夾上限", s2["pad"] == 1.0)
s3 = rt.resolve_retake_settings({"retakes": {"similarity_threshold": "bad"}})
check("非數值回預設",
      s3["similarity_threshold"] == rt.DEFAULT_RETAKES["similarity_threshold"])

# ===== 2. _normalize／_similarity =====
check("正規化去除換行與空白",
      rt._normalize("你好\n世界  測試") == "你好世界測試")
check("完全相同相似度為 1", rt._similarity("abc", "abc") == 1.0)
check("完全不同相似度低", rt._similarity("abc", "xyz") < 0.5)
check("空字串相似度為 0", rt._similarity("", "abc") == 0.0)

# ===== 3. find_retakes：找出候選重複片段 =====
settings = rt.resolve_retake_settings(None)

# 完全重複（同一句話講兩次）。
exact = [cue(0.0, 2.0, "大家好"), cue(2.5, 4.0, "今天來聊聊這個"),
        cue(5.0, 6.6, "今天來聊聊這個"), cue(8.0, 10.0, "開始吧")]
found = rt.find_retakes(exact, settings)
check("找出完全重複的候選", len(found) == 1 and found[0]["index"] == 1,
      str(found))
check("保留最後一次（matched_index 指向較晚的句子）",
      found[0]["matched_index"] == 2 if found else False)
check("相似度接近 1", found[0]["similarity"] > 0.95 if found else False)

# 略有不同但高度相似（重講時措辭微調）。
near = [cue(0.0, 2.0, "這個超讚的東西"), cue(3.0, 4.5, "這個超級讚的東西")]
found_near = rt.find_retakes(near, settings)
check("高相似度也視為重複", len(found_near) == 1, str(found_near))

# 相似度不足，不算重複。
low = [cue(0.0, 2.0, "今天天氣真好"), cue(3.0, 4.5, "我昨天吃了牛肉麵")]
found_low = rt.find_retakes(low, settings)
check("相似度不足不列入", found_low == [], str(found_low))

# 間隔太遠，不算重複（即使文字完全一樣）。
far = [cue(0.0, 2.0, "那我們開始吧"), cue(60.0, 62.0, "那我們開始吧")]
found_far = rt.find_retakes(far, settings)
check("超過時間窗不列入", found_far == [], str(found_far))

# 連續三次重講：前兩次都應標記為候選，只保留最後一次。
triple = [cue(0.0, 2.0, "測試一下麥克風"), cue(3.0, 5.0, "測試一下麥克風"),
         cue(6.0, 8.0, "測試一下麥克風")]
found_triple = rt.find_retakes(triple, settings)
check("連續三次重講標記前兩次",
      sorted(r["index"] for r in found_triple) == [0, 1], str(found_triple))

# 空清單／單句不炸。
check("空清單不炸", rt.find_retakes([], settings) == [])
check("單句不炸", rt.find_retakes([cue(0, 1, "x")], settings) == [])

# 未排序輸入也要能正確處理。
unsorted_cues = [cue(5.0, 6.6, "今天來聊聊這個"), cue(0.0, 2.0, "大家好"),
                cue(2.5, 4.0, "今天來聊聊這個")]
found_unsorted = rt.find_retakes(unsorted_cues, settings)
check("未排序輸入照樣正確找出",
      len(found_unsorted) == 1 and found_unsorted[0]["text"] == "今天來聊聊這個",
      str(found_unsorted))

# ===== 4. format_retakes_report =====
report_text = rt.format_retakes_report(found)
check("報告含偵測數量", "共偵測到 1 處" in report_text, report_text)
check("空清單回無候選訊息",
      rt.format_retakes_report([]) == "未偵測到疑似重複片段。")

# ===== 5. suggest_output_path =====
check("輸出檔名加後綴", rt.suggest_output_path("影片.mp4") == "影片_去重複.mp4")
check("無副檔名補 .mp4", rt.suggest_output_path("影片") == "影片_去重複.mp4")

# ===== 6. apply_retake_removal：安全防呆 =====
try:
    rt.apply_retake_removal("不存在.mp4", exact, found, "out.mp4")
    check("找不到檔案時報錯", False)
except FileNotFoundError:
    check("找不到檔案時報錯", True)

with tempfile.TemporaryDirectory() as tmp:
    fake_src = os.path.join(tmp, "fake.mp4")
    open(fake_src, "wb").write(b"x")
    try:
        rt.apply_retake_removal(fake_src, exact, [],
                                os.path.join(tmp, "o.mp4"))
        check("未勾選任何項目時報錯", False)
    except ValueError as exc:
        check("未勾選任何項目時報錯", "沒有勾選" in str(exc), str(exc))

# ===== 7. format_retake_removal_report =====
removal_report = rt.format_retake_removal_report({
    "cut_count": 1, "removed_seconds": 1.9,
    "original_seconds": 12.0, "kept_seconds": 10.1})
check("剪除報告含次數與秒數",
      "共剪掉 1 處重複片段" in removal_report and "10.1 秒" in removal_report,
      removal_report)

# ===== 8. config／CLI／GUI 靜態掃描 =====
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from config import DEFAULT_CONFIG
check("config 預設含 retakes 區",
      DEFAULT_CONFIG["retakes"] == rt.DEFAULT_RETAKES,
      str(DEFAULT_CONFIG.get("retakes")))

with open(os.path.join(root, "cli.py"), encoding="utf-8") as fp:
    cli_src = fp.read()
check("cli.py 有 --retakes 旗標", "--retakes" in cli_src)
check("cli.py 有 --retakes-cut 旗標", "--retakes-cut" in cli_src)

with open(os.path.join(root, "gui", "retakes_dialog.py"),
          encoding="utf-8") as fp:
    dialog_src = fp.read()
check("對話框無 classic tk.Radiobutton 殘留",
      "tk.Radiobutton(" not in dialog_src.replace("ttk.Radiobutton(", ""))
check("對話框的勾選候選項目使用 ttk.Checkbutton",
      "ttk.Checkbutton(" in dialog_src and "tk.Checkbutton(" not in
      dialog_src.replace("ttk.Checkbutton(", ""))

with open(os.path.join(root, "gui", "app.py"), encoding="utf-8") as fp:
    app_src = fp.read()
check("app.py 有重複片段偵測按鈕與 handler",
      "重複片段偵測" in app_src and "_open_retakes_dialog" in app_src)

# ===== 9. 真實 CLI 端到端（合成測試媒體＋重複片段偵測與剪除＋字幕同步對齊） =====
import shutil
if shutil.which("ffmpeg"):
    with tempfile.TemporaryDirectory() as tmp:
        clip = os.path.join(tmp, "clip.mp4")
        srt = os.path.join(tmp, "clip.srt")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=green:s=320x240:d=12:r=25",
             "-f", "lavfi", "-i", "sine=frequency=330:duration=12",
             "-shortest", "-c:v", "libx264", "-c:a", "aac", clip],
            capture_output=True, timeout=60)
        with open(srt, "w", encoding="utf-8") as fp:
            fp.write(
                "1\n00:00:00,000 --> 00:00:02,000\n大家好歡迎回到我的頻道\n\n"
                "2\n00:00:02,500 --> 00:00:04,000\n"
                "今天要跟大家分享一個超讚的東西\n\n"
                "3\n00:00:05,000 --> 00:00:06,600\n"
                "今天要跟大家分享一個超級讚的東西\n\n"
                "4\n00:00:08,000 --> 00:00:10,000\n那我們開始吧\n\n"
            )
        env_main = os.path.join(root, "main.py")
        proc = subprocess.run(
            [sys.executable, env_main, "--subs", srt, "--retakes",
             "--retakes-cut", "--formats", "srt", clip],
            cwd=tmp, capture_output=True, text=True, timeout=120)
        check("實測：CLI --subs --retakes --retakes-cut 執行成功",
              proc.returncode == 0, proc.stdout + proc.stderr)
        report_path = os.path.join(tmp, "clip_重複片段.txt")
        check("實測：候選清單報告已產生", os.path.exists(report_path))
        if os.path.exists(report_path):
            report_content = open(report_path, encoding="utf-8").read()
            check("實測：報告標出候選重複片段",
                  "共偵測到" in report_content, report_content)
        video_out = os.path.join(tmp, "clip_去重複.mp4")
        srt_out = os.path.join(tmp, "clip_去重複.srt")
        check("實測：去重複影片已產生", os.path.exists(video_out))
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
            check("實測：去重複後長度確實縮短",
                  0.0 < out_dur < 12.0, f"out_dur={out_dur}")
        if os.path.exists(srt_out):
            srt_text = open(srt_out, encoding="utf-8").read()
            check("實測：僅保留最後一次講的版本（超級讚）",
                  "超級讚的東西" in srt_text, srt_text)
            check("實測：較早的失敗版本已被剪掉（超讚的東西，非超級讚）",
                  "今天要跟大家分享一個超讚的東西\n" not in srt_text, srt_text)
            check("實測：其餘句子仍保留",
                  "大家好歡迎回到我的頻道" in srt_text
                  and "那我們開始吧" in srt_text, srt_text)
else:
    print("SKIP 實測（無 ffmpeg）")

print()
if failures:
    print(f"共 {len(failures)} 項失敗：{failures}")
    sys.exit(1)
print("test_v1220 全部通過")
