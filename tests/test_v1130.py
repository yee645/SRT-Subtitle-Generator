# -*- coding: utf-8 -*-
"""v1.13.0 新功能測試：音訊一鍵修復、mid-roll 廣告插入點建議。"""
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import adbreaks, audiofix, errors, media
from subtitle.publisher import build_publish_pack

# =====================================================================
# mid-roll 廣告插入點（adbreaks.py）
# =====================================================================

# ===== 1. 設定夾限與預設 =====
a = adbreaks.resolve_adbreak_settings(None)
check("廣告點預設值", a == adbreaks.DEFAULT_ADBREAKS, str(a))
a2 = adbreaks.resolve_adbreak_settings({"adbreaks": {
    "min_spacing_minutes": 0.1, "max_breaks": 99, "min_pause": "bad",
    "skip_head_minutes": -5, "skip_tail_minutes": 99}})
check("間隔夾限下界", a2["min_spacing_minutes"] == 2.0)
check("數量夾限上界", a2["max_breaks"] == 20)
check("停頓非數值回預設", a2["min_pause"] == 1.2)
check("頭部保留夾限下界", a2["skip_head_minutes"] == 0.0)
check("尾部保留夾限上界", a2["skip_tail_minutes"] == 10.0)

# ===== 2. 停頓候選 =====
def seg(start, end, text="講話內容測試", kind="speech"):
    return {"kind": kind, "start": start, "end": end, "text": text,
            "tags": [], "keep": True, "score": 0.0}

items = [
    seg(0, 100, "開場"),
    # 100→103：3 秒停頓
    seg(103, 240, "第一段主題"),
    # 240→241：1 秒（低於預設 1.2 不算）
    seg(241, 400, "第二段"),
    # 400→406：6 秒大停頓
    seg(406, 550, "第三段"),
    {"kind": "silence", "start": 550, "end": 555, "text": "（冷場）",
     "tags": [], "keep": False, "score": 0.0},
    seg(555, 700, "尾段收尾"),
]
cands = adbreaks.find_pause_candidates(items, min_pause=1.2)
check("候選數量（含 silence 段間隙）", len(cands) == 3, str(cands))
check("候選依時間排序",
      [round(c["time"], 1) for c in cands] == [101.5, 403.0, 552.5],
      str([c["time"] for c in cands]))
check("候選帶前後句摘要", cands[0]["before"].endswith("開場")
      and cands[0]["after"].startswith("第一段"), str(cands[0]))
check("停頓長度正確", abs(cands[1]["gap"] - 6.0) < 0.01)

# ===== 3. 建議挑選 =====
cfg = {"min_spacing_minutes": 4.0, "max_breaks": 6, "min_pause": 1.2,
       "skip_head_minutes": 1.0, "skip_tail_minutes": 1.0}
picked = adbreaks.suggest_ad_breaks(items, 700.0, cfg)
check("停頓最久者優先且守住間隔",
      [round(p["time"], 1) for p in picked] == [101.5, 403.0, 552.5]
      or len(picked) >= 2, str(picked))
# 間隔 4 分鐘（240 秒）：101.5 與 403 相距 301 秒 OK；552.5 與 403 相距
# 149.5 秒 < 240 → 只留 6 秒大停頓與 3 秒停頓兩個。
check("間隔限制生效", [round(p["time"], 1) for p in picked]
      == [101.5, 403.0], str(picked))

short = adbreaks.suggest_ad_breaks(items, 400.0, cfg)
check("不足 8 分鐘回空清單", short == [])

head_cfg = dict(cfg, skip_head_minutes=2.0, skip_tail_minutes=3.0)
picked2 = adbreaks.suggest_ad_breaks(items, 700.0, head_cfg)
check("頭尾保留區生效",
      all(120.0 <= p["time"] <= 520.0 for p in picked2), str(picked2))

cap_cfg = dict(cfg, max_breaks=1)
picked3 = adbreaks.suggest_ad_breaks(items, 700.0, cap_cfg)
check("數量上限生效且取最大停頓", len(picked3) == 1
      and abs(picked3[0]["time"] - 403.0) < 0.1, str(picked3))

# ===== 4. 文字排版 =====
text = adbreaks.format_ad_breaks(picked)
check("排版含時間戳", "01:41" in text and "06:43" in text, text)
check("排版含停頓秒數", "6.0 秒" in text, text)
check("排版含前後句", "｜" in text, text)
check("空清單回空字串", adbreaks.format_ad_breaks([]) == "")
long_break = adbreaks.format_ad_breaks(
    [{"time": 3700.0, "gap": 2.0, "before": "", "after": ""}])
check("超過一小時帶時分秒", "1:01:40" in long_break, long_break)

# ===== 5. 發佈包整合 =====
pack = build_publish_pack(items, ad_breaks=picked)
check("發佈包含廣告插入點區塊", "mid-roll 廣告插入點" in pack, pack[-200:])
pack_none = build_publish_pack(items, ad_breaks=[])
check("無插入點時區塊略去", "mid-roll" not in pack_none)

# =====================================================================
# 音訊一鍵修復（audiofix.py）
# =====================================================================

# ===== 6. 設定夾限與預設 =====
f = audiofix.resolve_audiofix_settings(None)
check("修復預設值", f == audiofix.DEFAULT_AUDIOFIX, str(f))
f2 = audiofix.resolve_audiofix_settings({"audiofix": {
    "denoise_strength": 99, "highpass_hz": 10, "loudnorm": 1,
    "denoise": 0}})
check("降噪強度夾限上界", f2["denoise_strength"] == 40.0)
check("高通頻率夾限下界", f2["highpass_hz"] == 40.0)
check("布林欄位轉型", f2["loudnorm"] is True and f2["denoise"] is False)

# ===== 7. 濾鏡鏈組裝 =====
chain = audiofix.build_audiofix_filter(
    {"denoise": True, "denoise_strength": 12.0,
     "highpass": True, "highpass_hz": 80.0, "loudnorm": False})
check("預設鏈：高通在前、降噪在後",
      chain == "highpass=f=80,afftdn=nr=12", chain)
only_denoise = audiofix.build_audiofix_filter(
    {"denoise": True, "denoise_strength": 20.0,
     "highpass": False, "highpass_hz": 80.0, "loudnorm": False})
check("僅降噪", only_denoise == "afftdn=nr=20", only_denoise)
with_loud = audiofix.build_audiofix_filter(
    {"denoise": True, "denoise_strength": 12.0,
     "highpass": True, "highpass_hz": 80.0, "loudnorm": True},
    measured={"input_i": "-20.1", "input_tp": "-5.0",
              "input_lra": "9.0", "input_thresh": "-30.5",
              "target_offset": "0.3"})
check("響度殿後且用兩階段線性模式",
      with_loud.endswith("linear=true")
      and "loudnorm=I=-14" in with_loud
      and with_loud.startswith("highpass"), with_loud)
empty = audiofix.build_audiofix_filter(
    {"denoise": False, "highpass": False, "loudnorm": False,
     "denoise_strength": 12.0, "highpass_hz": 80.0})
check("全關回空字串", empty == "")

# ===== 8. 影像串流偵測與輸出命名 =====
# has_video_stream 現在共用 media.py 的實作（與 has_audio_stream 同一處），
# 內部呼叫的 ffprobe_available／subprocess.run 要對 media 模組本身替身，
# 對 audiofix.ffprobe_available 替身不會生效（僅改到 audiofix 自己的名稱綁定）。
orig_run = audiofix.subprocess.run
orig_probe_avail = media.ffprobe_available
media.ffprobe_available = lambda: True
audiofix.subprocess.run = lambda cmd, **k: types.SimpleNamespace(
    returncode=0, stdout=b"video\n", stderr=b"")
check("有影像串流判定", audiofix.has_video_stream("v.mp4") is True)
audiofix.subprocess.run = lambda cmd, **k: types.SimpleNamespace(
    returncode=0, stdout=b"", stderr=b"")
check("純音訊判定", audiofix.has_video_stream("a.mp3") is False)
check("純音訊輸出改 m4a",
      audiofix.suggest_output_path("錄音.mp3") == "錄音_修復.m4a")
audiofix.subprocess.run = lambda cmd, **k: types.SimpleNamespace(
    returncode=0, stdout=b"video\n", stderr=b"")
check("影片輸出保留副檔名",
      audiofix.suggest_output_path("影片.mkv") == "影片_修復.mkv")
media.ffprobe_available = lambda: False
check("無 ffprobe 保守視為有影像",
      audiofix.has_video_stream("x.mp4") is True)
audiofix.subprocess.run = orig_run
media.ffprobe_available = orig_probe_avail

# ===== 9. 命令組裝 =====
cmd = audiofix._fix_command("in.mp4", "out.mp4", "afftdn=nr=12", True)
check("影片模式原樣複製影像", "-c:v" in cmd
      and cmd[cmd.index("-c:v") + 1] == "copy"
      and cmd[cmd.index("-map") + 1] == "0:v?", str(cmd))
check("音訊重編碼 aac", cmd[cmd.index("-c:a") + 1] == "aac")
check("濾鏡帶入", cmd[cmd.index("-af") + 1] == "afftdn=nr=12")
cmd_a = audiofix._fix_command("in.mp3", "out.m4a", "afftdn=nr=12", False)
check("純音訊模式去影像", "-vn" in cmd_a and "-c:v" not in cmd_a, str(cmd_a))

# ===== 10. fix_audio：成功與錯誤路徑 =====
orig_avail = audiofix.ffmpeg_available
audiofix.ffmpeg_available = lambda: False
try:
    audiofix.fix_audio("x.mp4", "y.mp4")
    check("修復 ffmpeg 不可用時報錯", False)
except RuntimeError as exc:
    check("修復 ffmpeg 不可用時報錯", "ffmpeg" in str(exc))
audiofix.ffmpeg_available = lambda: True

try:
    audiofix.fix_audio("不存在.mp4", "y.mp4")
    check("找不到檔案時報錯", False)
except FileNotFoundError:
    check("找不到檔案時報錯", True)

with tempfile.TemporaryDirectory() as tmp:
    src = os.path.join(tmp, "v.mp4")
    open(src, "wb").write(b"x")
    out = os.path.join(tmp, "v_修復.mp4")

    try:
        audiofix.fix_audio(src, out, settings={
            "denoise": False, "highpass": False, "loudnorm": False,
            "denoise_strength": 12.0, "highpass_hz": 80.0})
        check("全關時擋下", False)
    except ValueError as exc:
        check("全關時擋下", "至少勾選" in str(exc))

    captured = {}
    class FakeProc:
        stdout = None
        stderr = None
        def wait(self):
            return 0
    orig_popen = audiofix.subprocess.Popen
    orig_dur = audiofix.probe_duration
    orig_hv = audiofix.has_video_stream
    orig_ha = audiofix.has_audio_stream
    orig_measure = audiofix.measure_loudness
    audiofix.subprocess.Popen = (
        lambda cmd, **k: captured.update(cmd=cmd) or FakeProc())
    audiofix.probe_duration = lambda p: 30.0
    audiofix.has_video_stream = lambda p: True
    audiofix.has_audio_stream = lambda p: True
    audiofix.measure_loudness = lambda p, **k: {
        "input_i": "-20.0", "input_tp": "-4.0", "input_lra": "8.0",
        "input_thresh": "-30.0", "target_offset": "0.1"}

    events = []
    result = audiofix.fix_audio(
        src, out,
        settings={"denoise": True, "denoise_strength": 15.0,
                  "highpass": True, "highpass_hz": 100.0, "loudnorm": True},
        progress_cb=lambda ratio, msg: events.append((ratio, msg)))
    check("回傳輸出路徑", result == out)
    af = captured["cmd"][captured["cmd"].index("-af") + 1]
    check("命令帶完整修復鏈", af.startswith("highpass=f=100")
          and "afftdn=nr=15" in af and "linear=true" in af, af)
    check("修復進度回報到完成", events and events[-1][0] == 1.0, str(events))

    audiofix.subprocess.Popen = orig_popen
    audiofix.probe_duration = orig_dur
    audiofix.has_video_stream = orig_hv
    audiofix.has_audio_stream = orig_ha
    audiofix.measure_loudness = orig_measure
audiofix.ffmpeg_available = orig_avail

# ===== 11. 友善錯誤涵蓋修復失敗 =====
e = errors.describe_exception(RuntimeError("音訊修復失敗：afftdn error"))
check("修復失敗歸類 ffmpeg 失敗", e.kind == errors.KIND_FFMPEG_FAILED)

# ===== 12. config 預設值 =====
from config import DEFAULT_CONFIG
check("config 含 audiofix 區塊",
      DEFAULT_CONFIG["audiofix"] == audiofix.DEFAULT_AUDIOFIX,
      str(DEFAULT_CONFIG.get("audiofix")))
check("config 含 adbreaks 區塊",
      DEFAULT_CONFIG["adbreaks"] == adbreaks.DEFAULT_ADBREAKS,
      str(DEFAULT_CONFIG.get("adbreaks")))

# ===== 13. CLI 整合 =====
import cli
args = cli.build_parser().parse_args(["--audiofix", "a.mp4"])
check("CLI 旗標解析", args.audiofix)

orig_fix = cli.fix_audio
orig_suggest = cli.suggest_output_path
def fake_fix(path, out, settings=None, **kwargs):
    open(out, "wb").write(b"fixed")
    return out
cli.fix_audio = fake_fix
with tempfile.TemporaryDirectory() as tmp:
    media = os.path.join(tmp, "素材.mp4")
    open(media, "wb").write(b"x")
    cli.suggest_output_path = lambda p: os.path.join(
        tmp, os.path.splitext(os.path.basename(p))[0] + "_修復.mp4")
    results = cli._run_tools_batch(
        [media], {"automation": {"output_dir": ""}},
        lambda msg, ratio=None: None, do_audiofix=True)
    exports = results[0]["result"]["exports"]
    check("CLI 修復輸出", results[0]["ok"]
          and any("修復" in p for p in exports)
          and all(os.path.exists(p) for p in exports), str(results))
cli.fix_audio = orig_fix
cli.suggest_output_path = orig_suggest

print("\n" + ("ALL PASS" if not failures else f"FAILURES: {failures}"))
sys.exit(1 if failures else 0)
