# -*- coding: utf-8 -*-
"""v1.44.0 新功能測試：音樂節拍分析與剪點對齊。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import beatsync as bs

S = bs.resolve_beatsync_settings(None)

# ===== 1. 設定解析與夾限 =====
check("預設搜尋 60~200 BPM",
      S["min_bpm"] == 60.0 and S["max_bpm"] == 200.0, str(S))
check("預設最多挪 0.25 秒", S["max_shift"] == 0.25)
check("預設信心門檻 2.0（實測校準）", S["min_confidence"] == 2.0)
over = bs.resolve_beatsync_settings(
    {"beatsync": {"min_bpm": 999, "max_bpm": 999, "max_shift": 99,
                  "octave_tolerance": 99, "min_confidence": 99}})
check("BPM 夾限上界", over["max_bpm"] == bs._BPM_RANGE[1], str(over))
check("位移夾限上界", over["max_shift"] == bs._SHIFT_RANGE[1])
check("容忍度夾限到 1.0", over["octave_tolerance"] == 1.0)
check("信心夾限上界", over["min_confidence"] == bs._CONFIDENCE_RANGE[1])
under = bs.resolve_beatsync_settings(
    {"beatsync": {"max_shift": -5, "octave_tolerance": 0, "min_confidence": 0}})
check("位移夾限下界", under["max_shift"] == 0.0)
check("容忍度夾限下界", under["octave_tolerance"] == bs._TOLERANCE_RANGE[0])
check("信心夾限下界", under["min_confidence"] == bs._CONFIDENCE_RANGE[0])
check("無法轉數字時退回預設",
      bs.resolve_beatsync_settings(
          {"beatsync": {"max_shift": "快"}})["max_shift"] == 0.25)
check("None 不覆蓋預設值",
      bs.resolve_beatsync_settings(
          {"beatsync": {"min_bpm": None}})["min_bpm"] == 60.0)
check("空設定等同預設", bs.resolve_beatsync_settings({}) == S)
# 最慢被設得比最快還大時要對調，否則一個候選都掃不到。
swapped = bs.resolve_beatsync_settings(
    {"beatsync": {"min_bpm": 180, "max_bpm": 90}})
check("最慢大於最快時自動對調",
      swapped["min_bpm"] == 90.0 and swapped["max_bpm"] == 180.0,
      str(swapped))

# ===== 2. 能量包絡與起音強度 =====
env = bs.energy_envelope([0] * (bs.HOP * 4))
check("全靜音的包絡為 0", all(v == 0 for v in env), str(env[:3]))
check("包絡長度約等於樣本數／HOP", len(env) == 3, str(len(env)))
flux = bs.onset_strength([0.0, 5.0, 3.0, 8.0])
# 半波整流：只保留「變大聲」的部分，變小聲一律當 0。
check("只保留上升沿", flux == [0.0, 5.0, 0.0, 5.0], str(flux))
check("空包絡不會炸", bs.onset_strength([]) == [0.0])

# ===== 3. 速度偵測（用合成的脈衝序列，不碰 ffmpeg）=====
def pulse_flux(bpm, seconds=30.0, amplitude=100.0):
    """依指定 BPM 造出脈衝式的起音強度序列。"""
    n = int(seconds * bs.FRAMES_PER_SECOND)
    out = [0.0] * n
    period = bs.FRAMES_PER_SECOND * 60.0 / bpm
    k = 0
    while True:
        i = int(round(k * period))
        if i >= n:
            break
        out[i] = amplitude
        k += 1
    return out

for expect in (90.0, 120.0, 140.0):
    got = bs.detect_tempo(pulse_flux(expect), S)
    check(f"還原 {expect:.0f} BPM", abs(got["bpm"] - expect) <= 1.0,
          f"得到 {got['bpm']}")

# 這是本版最容易寫錯的地方：慢一倍的速度落在真拍點的子集上，平均分數
# 必然與正確速度相當，單靠分數會挑到慢的那個（實測 120 被判成 60）。
half = bs.detect_tempo(pulse_flux(120.0), S)
check("八度校正：120 BPM 不會被判成 60", half["bpm"] == 120.0,
      str(half["bpm"]))
no_octave = bs.resolve_beatsync_settings(
    {"beatsync": {"octave_tolerance": 1.0}})
check("容忍度設到 1.0 時仍能運作",
      bs.detect_tempo(pulse_flux(120.0), no_octave)["bpm"] > 0)

check("空 flux 回 bpm=0", bs.detect_tempo([], S)["bpm"] == 0.0)
check("空 flux 也回信心 0", bs.detect_tempo([], S)["confidence"] == 0.0)

# ===== 4. 信心判定（沒有節拍就不要自信地講一個數字）=====
flat = [10.0] * int(30 * bs.FRAMES_PER_SECOND)
flat_result = bs.detect_tempo(flat, S)
check("完全平坦的訊號判為沒有節拍", flat_result["bpm"] == 0.0,
      str(flat_result))
zeros = bs.detect_tempo([0.0] * 500, S)
check("全零訊號判為沒有節拍", zeros["bpm"] == 0.0, str(zeros))
check("真有節拍時信心明顯高於門檻",
      bs.detect_tempo(pulse_flux(120.0), S)["confidence"] > S["min_confidence"],
      str(bs.detect_tempo(pulse_flux(120.0), S)["confidence"]))
# 門檻可調：調到很高時連真節拍也會被判為不夠有信心。
strict = bs.resolve_beatsync_settings({"beatsync": {"min_confidence": 10.0}})
check("調高信心門檻後連真節拍也會被擋",
      bs.detect_tempo(pulse_flux(120.0), strict)["bpm"] == 0.0)

# ===== 5. 拍點清單 =====
beats = bs.beat_times(120.0, 0.0, 3.0)
check("120 BPM 每 0.5 秒一拍", beats == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5],
      str(beats))
check("相位會平移整個拍點格",
      bs.beat_times(120.0, 0.25, 1.0) == [0.25, 0.75])
check("bpm 為 0 時回空清單", bs.beat_times(0, 0, 10) == [])
check("長度為 0 時回空清單", bs.beat_times(120, 0, 0) == [])
check("負相位的拍點不會是負數",
      all(b >= 0 for b in bs.beat_times(120, -0.3, 1.2)))

# ===== 6. 剪點對齊 =====
grid = bs.beat_times(120.0, 0.0, 20.0)
rows = bs.snap_times([1.02, 3.31, 7.9], grid, 0.25)
check("對齊到最近的拍子", rows[0]["snapped"] == 1.0, str(rows[0]))
check("記錄要挪多少", abs(rows[0]["shift"] + 0.02) < 1e-6, str(rows[0]))
check("可對齊的標記為 aligned", all(r["aligned"] for r in rows))
check("往後挪也算得對", rows[1]["snapped"] == 3.5, str(rows[1]))

# 離拍子太遠就不硬挪——那會讓畫面與內容對不上。
far = bs.snap_times([5.0], [0.0, 10.0], 0.25)
check("超過上限不對齊", far[0]["aligned"] is False)
check("超過上限時維持原位", far[0]["snapped"] == 5.0)
check("超過上限仍回報差距", abs(far[0]["shift"]) == 5.0)
loose = bs.snap_times([5.0], [0.0, 10.0], 6.0)
check("放寬上限後就會對齊", loose[0]["aligned"] is True)

check("沒有拍點時不對齊",
      bs.snap_times([1.0], [], 0.25)[0]["aligned"] is False)
check("空剪點清單不會炸", bs.snap_times([], grid, 0.25) == [])
check("None 不會炸", bs.snap_times(None, grid, 0.25) == [])

# ===== 7. 時間顯示 =====
check("秒數排成 M:SS.s", bs.format_timestamp(65.4) == "1:05.4")
check("小於一分鐘補零", bs.format_timestamp(4.0) == "0:04.0")
check("負數不會變成怪字串", bs.format_timestamp(-5) == "0:00.0")

# ===== 8. 報告排版 =====
result = {"bpm": 120.0, "phase": 0.5, "beats": grid, "duration": 20.0,
          "confidence": 5.3}
text = bs.format_beat_report(result, rows, S)
check("報告有標題", "音樂節拍分析" in text)
check("報告列出 BPM", "120.0 BPM" in text)
check("報告列出每拍秒數", "0.500 秒" in text)
check("報告列出第一拍與總拍數", "第一拍" in text and "共" in text)
check("報告列出剪點對齊建議", "剪點對齊建議" in text)
check("報告標示每個剪點要挪多少", "挪 " in text)
check("報告總結可對齊比例", "3/3 個剪點可對齊" in text)
far_text = bs.format_beat_report(result, bs.snap_times([50.0], grid, 0.25), S)
check("超過上限的剪點在報告中說明原因", "維持原位" in far_text)
check("報告說明為什麼不硬挪", "不是對齊而是破壞" in far_text)

none_text = bs.format_beat_report({"bpm": 0.0})
check("沒有節拍時據實說明", "沒有偵測到穩定的節拍" in none_text)
check("沒有節拍時說明哪種素材會這樣",
      "純人聲" in none_text and "環境音" in none_text)
check("沒有節拍時不列出 BPM 數字", "BPM" not in none_text)
check("報告不使用 Markdown（tk.Text 會原樣顯示星號）",
      "**" not in text and "**" not in none_text)
check("不給 snapped 也能排版",
      isinstance(bs.format_beat_report(result), str))

# ===== 9. 設定檔預設值 =====
from config import DEFAULT_CONFIG

check("config 有 beatsync 區段", "beatsync" in DEFAULT_CONFIG)
check("config 預設值與模組一致",
      DEFAULT_CONFIG["beatsync"] == bs.DEFAULT_BEATSYNC,
      str(DEFAULT_CONFIG["beatsync"]))

# ===== 10. CLI 介面 =====
import cli
import inspect

parser = cli.build_parser()
args = parser.parse_args(["--beatcheck", "v.mp4"])
check("CLI 有 --beatcheck", args.beatcheck is True)
check("--music 預設為 None", args.music is None)
check("--music 可指定",
      parser.parse_args(["--beatcheck", "--music", "m.mp3",
                         "v.mp4"]).music == "m.mp3")

# 節拍分析不需要逐字稿，必須走免轉錄的輕量工具分支，否則會白跑一次
# 語音辨識（沒有 Whisper 的環境甚至會直接失敗）。
main_src = inspect.getsource(cli.main) if hasattr(cli, "main") else ""
run_src = inspect.getsource(cli)
check("beatcheck 列在免轉錄的工具分支",
      "or args.pacecheck or args.beatcheck" in run_src
      or "args.beatcheck)" in run_src, "未接上免轉錄分支")

src = inspect.getsource(cli._export_beatcheck)
check("沒指定配樂時分析素材本身", "music_path or media_path" in src)
check("只有指定配樂且素材有影像時才掃剪點",
      "has_video_stream" in src and "music_path" in src)
check("剪點重用既有的 detect_scene_changes",
      "detect_scene_changes" in src)
check("對齊重用 beatsync.snap_times", "snap_times" in src)

# ===== 11. 回歸：零第三方依賴、零 GUI 依賴 =====
mod_src = inspect.getsource(bs)
check("beatsync 沒有引入 numpy 等第三方套件",
      "numpy" not in mod_src and "librosa" not in mod_src
      and "scipy" not in mod_src)
check("beatsync 零 GUI 依賴",
      "tkinter" not in mod_src and "import gui" not in mod_src)
check("只有一個入口會碰 ffmpeg",
      mod_src.count('"ffmpeg"') == 1, str(mod_src.count('"ffmpeg"')))

print()
if failures:
    print(f"失敗 {len(failures)} 項：{', '.join(failures)}")
    sys.exit(1)
print("v1.44.0 測試全數通過。")
