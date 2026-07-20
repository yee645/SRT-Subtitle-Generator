# -*- coding: utf-8 -*-
"""v1.19.0 新功能測試：匯入既有字幕檔（SRT/VTT）。"""
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


from subtitle import importer
from subtitle.errors import (KIND_FILE_MISSING, describe_exception)
from subtitle.exporter import cues_to_srt

# =====================================================================
# SRT 解析
# =====================================================================

# ===== 1. 標準 3 段字幕 =====
srt_normal = """1
00:00:01,000 --> 00:00:03,000
第一句字幕

2
00:00:03,500 --> 00:00:05,000
第二句字幕

3
00:00:05,500 --> 00:00:07,000
第三句字幕
"""
cues, skipped = importer.parse_srt(srt_normal)
check("SRT 標準 3 句解析數量", len(cues) == 3, str(cues))
check("SRT 標準無略過", skipped == 0)
check("SRT 標準時間正確",
      cues[0]["start"] == 1.0 and cues[0]["end"] == 3.0, str(cues[0]))
check("SRT 標準文字正確", cues[0]["text"] == "第一句字幕")
check("SRT cue 不含 words 鍵", "words" not in cues[0])

# ===== 2. 毫秒用點的變體 =====
srt_dot = """1
00:00:01.000 --> 00:00:03.000
點號毫秒測試
"""
cues_dot, skipped_dot = importer.parse_srt(srt_dot)
check("SRT 點號毫秒可解析", len(cues_dot) == 1 and skipped_dot == 0, str(cues_dot))
check("SRT 點號毫秒時間正確",
      cues_dot[0]["start"] == 1.0 and cues_dot[0]["end"] == 3.0)

# ===== 3. 缺索引行 =====
srt_no_index = """00:00:01,000 --> 00:00:03,000
沒有索引行的字幕

00:00:04,000 --> 00:00:06,000
第二句也沒有索引行
"""
cues_ni, skipped_ni = importer.parse_srt(srt_no_index)
check("SRT 缺索引行仍可解析", len(cues_ni) == 2 and skipped_ni == 0, str(cues_ni))
check("SRT 缺索引行文字正確", cues_ni[0]["text"] == "沒有索引行的字幕")

# ===== 4. 多行文字保留 =====
srt_multiline = """1
00:00:01,000 --> 00:00:03,000
第一行
第二行
"""
cues_ml, _ = importer.parse_srt(srt_multiline)
check("SRT 多行文字保留換行",
      cues_ml[0]["text"] == "第一行\n第二行", repr(cues_ml[0]["text"]))

# ===== 5. 中間區塊格式錯誤，僅該區塊略過 =====
srt_malformed_middle = """1
00:00:01,000 --> 00:00:03,000
正常第一句

2
這是一個沒有時間軸的壞區塊
完全無法辨識

3
00:00:05,000 --> 00:00:07,000
正常第三句
"""
cues_mm, skipped_mm = importer.parse_srt(srt_malformed_middle)
check("SRT 中間壞區塊：略過數量 1", skipped_mm == 1, str(skipped_mm))
check("SRT 中間壞區塊：其餘正常解析",
      len(cues_mm) == 2 and cues_mm[0]["text"] == "正常第一句"
      and cues_mm[1]["text"] == "正常第三句", str(cues_mm))

# ===== 6. <i>/<font> 等行內標記剝除 =====
srt_markup = """1
00:00:01,000 --> 00:00:03,000
<i>斜體文字</i>與<font color="#FF0000">彩色文字</font>
"""
cues_markup, _ = importer.parse_srt(srt_markup)
check("SRT 行內標記剝除",
      cues_markup[0]["text"] == "斜體文字與彩色文字", repr(cues_markup[0]["text"]))

# ===== 7. {\an8} 等 ASS 覆寫碼剝除 =====
srt_ass_override = """1
00:00:01,000 --> 00:00:03,000
{\\an8}置頂字幕
"""
cues_ov, _ = importer.parse_srt(srt_ass_override)
check("SRT ASS 覆寫碼剝除",
      cues_ov[0]["text"] == "置頂字幕", repr(cues_ov[0]["text"]))

# ===== 8. CRLF 檔案 =====
srt_crlf = srt_normal.replace("\n", "\r\n")
cues_crlf, skipped_crlf = importer.parse_srt(srt_crlf)
check("SRT CRLF 可正確解析",
      len(cues_crlf) == 3 and skipped_crlf == 0, str(cues_crlf))

# ===== 9. end<=start 略過 =====
srt_bad_time = """1
00:00:05,000 --> 00:00:03,000
結束早於開始，應略過

2
00:00:06,000 --> 00:00:08,000
正常字幕
"""
cues_bt, skipped_bt = importer.parse_srt(srt_bad_time)
check("SRT end<=start 略過", skipped_bt == 1 and len(cues_bt) == 1, str(cues_bt))

# =====================================================================
# VTT 解析
# =====================================================================

# ===== 10. header + NOTE + STYLE 略過 =====
vtt_full = """WEBVTT

NOTE
這是一段註解，應整段略過

STYLE
::cue { color: yellow; }

1
00:00:01.000 --> 00:00:03.000
第一句 VTT 字幕

00:00:04.000 --> 00:00:06.000
沒有 cue identifier 的第二句
"""
cues_vtt, skipped_vtt = importer.parse_vtt(vtt_full)
check("VTT header/NOTE/STYLE 略過後解析數量", len(cues_vtt) == 2, str(cues_vtt))
check("VTT 無略過（NOTE/STYLE 非壞區塊）", skipped_vtt == 0, str(skipped_vtt))
check("VTT cue identifier 正確解析", cues_vtt[0]["text"] == "第一句 VTT 字幕")
check("VTT 缺 identifier 正確解析",
      cues_vtt[1]["text"] == "沒有 cue identifier 的第二句")

# ===== 11. MM:SS.mmm 短時間戳 =====
vtt_short_time = """WEBVTT

00:01.500 --> 00:03.000
短時間戳測試
"""
cues_short, skipped_short = importer.parse_vtt(vtt_short_time)
check("VTT 短時間戳可解析", len(cues_short) == 1 and skipped_short == 0,
      str(cues_short))
check("VTT 短時間戳數值正確",
      abs(cues_short[0]["start"] - 1.5) < 0.001
      and abs(cues_short[0]["end"] - 3.0) < 0.001, str(cues_short[0]))

# ===== 12. cue settings 剝除 =====
vtt_settings = """WEBVTT

00:00:01.000 --> 00:00:03.000 position:10%,line-left align:center
帶 cue settings 的字幕
"""
cues_settings, _ = importer.parse_vtt(vtt_settings)
check("VTT cue settings 不混入文字",
      cues_settings[0]["text"] == "帶 cue settings 的字幕",
      repr(cues_settings[0]["text"]))

# ===== 13. YouTube 風格逐字時間標記 + <c> 剝除 =====
vtt_youtube = """WEBVTT

00:00:01.000 --> 00:00:05.000
<00:00:01.500><c> 你好</c><00:00:02.000><c> 世界</c>
"""
cues_yt, _ = importer.parse_vtt(vtt_youtube)
check("VTT YouTube 逐字標記與 <c> 剝除",
      cues_yt[0]["text"] == "你好 世界", repr(cues_yt[0]["text"]))

# ===== 14. <v Speaker> 剝除 =====
vtt_voice = """WEBVTT

00:00:01.000 --> 00:00:03.000
<v Alice>大家好，我是 Alice</v>
"""
cues_voice, _ = importer.parse_vtt(vtt_voice)
check("VTT <v Speaker> 剝除",
      cues_voice[0]["text"] == "大家好，我是 Alice", repr(cues_voice[0]["text"]))

# ===== 15. 無 WEBVTT 標頭也不崩潰（當類 SRT 嘗試解析） =====
vtt_no_header = """00:00:01.000 --> 00:00:03.000
沒有 WEBVTT 標頭
"""
cues_nh, skipped_nh = importer.parse_vtt(vtt_no_header)
check("VTT 缺標頭不崩潰仍可解析",
      len(cues_nh) == 1 and cues_nh[0]["text"] == "沒有 WEBVTT 標頭", str(cues_nh))

# =====================================================================
# 編碼偵測
# =====================================================================

# ===== 16. utf-8-sig（BOM）=====
with tempfile.TemporaryDirectory() as tmp:
    bom_path = os.path.join(tmp, "bom.srt")
    content = "1\n00:00:01,000 --> 00:00:03,000\n編碼測試中文字幕\n"
    with open(bom_path, "wb") as fp:
        fp.write(content.encode("utf-8-sig"))
    loaded_bom = importer.load_subtitle_file(bom_path)
    check("utf-8-sig 編碼判斷正確",
          loaded_bom["encoding"] == "utf-8-sig", loaded_bom["encoding"])
    check("utf-8-sig 內容解析正確",
          loaded_bom["cues"][0]["text"] == "編碼測試中文字幕")

    # ===== 17. cp950（繁體 Big5 系列）=====
    cp950_path = os.path.join(tmp, "cp950.srt")
    content_cp950 = "1\n00:00:01,000 --> 00:00:03,000\n你好世界測試\n"
    with open(cp950_path, "wb") as fp:
        fp.write(content_cp950.encode("cp950"))
    loaded_cp950 = importer.load_subtitle_file(cp950_path)
    check("cp950 編碼判斷正確",
          loaded_cp950["encoding"] == "cp950", loaded_cp950["encoding"])
    check("cp950 內容解析正確",
          loaded_cp950["cues"][0]["text"] == "你好世界測試")

    # ===== 18. 錯誤：missing file =====
    try:
        importer.load_subtitle_file(os.path.join(tmp, "不存在.srt"))
        check("找不到檔案應拋例外", False, "未拋出例外")
    except FileNotFoundError as exc:
        check("找不到檔案訊息格式正確", "找不到檔案" in str(exc), str(exc))
        err = describe_exception(exc)
        check("找不到檔案歸類正確", err.kind == KIND_FILE_MISSING, err.kind)

    # ===== 19. 錯誤：不支援副檔名 =====
    ass_path = os.path.join(tmp, "字幕.ass")
    with open(ass_path, "w", encoding="utf-8") as fp:
        fp.write("dummy")
    try:
        importer.load_subtitle_file(ass_path)
        check("不支援副檔名應拋例外", False, "未拋出例外")
    except ValueError as exc:
        check("不支援副檔名訊息正確", "不支援的字幕檔格式" in str(exc), str(exc))
        # 沿用 exporter.py「不支援的輸出格式」的既有慣例：不另立專屬規則，
        # 走 errors.py 一般化 fallback 即可（技術細節仍會完整附上原文）。
        err_ext = describe_exception(exc)
        check("不支援副檔名走一般化 fallback（與 exporter 慣例一致）",
              "不支援的字幕檔格式" in err_ext.details, err_ext.details)

    # ===== 20. 錯誤：整份檔案解析不出任何字幕 =====
    garbage_path = os.path.join(tmp, "garbage.srt")
    with open(garbage_path, "w", encoding="utf-8") as fp:
        fp.write("這只是一段完全沒有時間軸的亂寫文字\n第二行也是\n")
    try:
        importer.load_subtitle_file(garbage_path)
        check("無法解析應拋例外", False, "未拋出例外")
    except RuntimeError as exc:
        check("無法解析訊息正確", "無法解析字幕檔" in str(exc), str(exc))
        err_parse = describe_exception(exc)
        check("無法解析歸類為友善標題",
              str(err_parse) == "無法解析匯入的字幕檔", str(err_parse))
        check("無法解析附帶解法", bool(err_parse.solution))

# =====================================================================
# 21. 圓角測試：cues -> cues_to_srt -> parse_srt
# =====================================================================
roundtrip_cues = [
    {"start": 0.0, "end": 1.234, "text": "第一句"},
    {"start": 1.5, "end": 3.999, "text": "第二句\n第二行"},
    {"start": 4.0, "end": 6.001, "text": "第三句"},
]
srt_text = cues_to_srt(roundtrip_cues)
rt_cues, rt_skipped = importer.parse_srt(srt_text)
check("圓角：句數相符", len(rt_cues) == 3 and rt_skipped == 0, str(rt_cues))
for original, parsed in zip(roundtrip_cues, rt_cues):
    check(f"圓角：開始時間 {original['start']} 誤差 <1ms",
          abs(original["start"] - parsed["start"]) < 0.001,
          f"{original['start']} vs {parsed['start']}")
    check(f"圓角：結束時間 {original['end']} 誤差 <1ms",
          abs(original["end"] - parsed["end"]) < 0.001,
          f"{original['end']} vs {parsed['end']}")
    check(f"圓角：文字相符 {original['text']!r}",
          original["text"] == parsed["text"])

# =====================================================================
# 22. 靜態掃描
# =====================================================================
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app_src = open(os.path.join(root, "gui", "app.py"), encoding="utf-8").read()
check("app.py 已接上匯入字幕按鈕",
      "匯入字幕" in app_src and "_import_subtitles" in app_src)
check("app.py 匯入字幕呼叫 load_subtitle_file",
      "load_subtitle_file" in app_src)
check("app.py 無 classic tk.Button 殘留（沿用 ttk）",
      "tk.Button(" not in app_src.replace("ttk.Button(", ""))
check("app.py 無 classic tk.Checkbutton 殘留",
      "tk.Checkbutton(" not in app_src.replace("ttk.Checkbutton(", ""))
check("app.py 無 classic tk.Radiobutton 殘留",
      "tk.Radiobutton(" not in app_src.replace("ttk.Radiobutton(", ""))
check("app.py 無 classic tk.Entry 殘留",
      "tk.Entry(" not in app_src.replace("ttk.Entry(", ""))

importer_src = open(os.path.join(root, "subtitle", "importer.py"),
                    encoding="utf-8").read()
check("importer.py 零 GUI 依賴", "tkinter" not in importer_src)

# =====================================================================
# 23. CLI --subs 整合（單元）
# =====================================================================
import cli
args = cli.build_parser().parse_args(["--subs", "字幕.srt", "影片.mp4"])
check("CLI --subs 旗標解析", args.subs == "字幕.srt")

with tempfile.TemporaryDirectory() as tmp:
    media = os.path.join(tmp, "影片.mp4")
    open(media, "wb").write(b"x")
    try:
        cli.main(["--subs", "字幕.srt", media, os.path.join(tmp, "other.mp4")])
        check("CLI --subs 多檔應報錯", False, "未拋出例外")
    except SystemExit as exc:
        check("CLI --subs 多檔報錯訊息正確",
              "剛好一個" in str(exc.code) or "個" in str(exc.code), str(exc.code))

# =====================================================================
# 24. 真實 ffmpeg 端到端：--subs 匯入字幕直接匯出＋燒錄
# =====================================================================
from subtitle.burner import ffmpeg_available

if not ffmpeg_available():
    print("嘗試安裝 ffmpeg（apt-get install -y ffmpeg）...")
    subprocess.run(["apt-get", "update"], capture_output=True)
    subprocess.run(["apt-get", "install", "-y", "ffmpeg"], capture_output=True)

if ffmpeg_available():
    with tempfile.TemporaryDirectory() as tmp:
        clip = os.path.join(tmp, "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=5",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
             "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
             "-t", "5", clip], capture_output=True, timeout=120)
        check("e2e 測試素材產生成功", os.path.exists(clip) and os.path.getsize(clip) > 0)

        subs_path = os.path.join(tmp, "subs.srt")
        with open(subs_path, "w", encoding="utf-8") as fp:
            fp.write(
                "1\n00:00:00,500 --> 00:00:04,500\n"
                "真實端到端測試字幕\n")

        main_py = os.path.join(root, "main.py")
        proc = subprocess.run(
            [sys.executable, main_py, "--subs", "subs.srt", "--burn",
             "--formats", "srt,vtt", "clip.mp4"],
            cwd=tmp, capture_output=True, text=True, timeout=180)
        check("e2e CLI --subs 執行成功",
              proc.returncode == 0,
              f"returncode={proc.returncode}\n{proc.stdout}\n{proc.stderr}")

        burned_path = os.path.join(tmp, "clip_subtitled.mp4")
        exported_srt = os.path.join(tmp, "clip.srt")
        exported_vtt = os.path.join(tmp, "clip.vtt")
        check("e2e 燒錄輸出存在",
              os.path.exists(burned_path) and os.path.getsize(burned_path) > 0)
        check("e2e SRT 匯出存在", os.path.exists(exported_srt))
        check("e2e VTT 匯出存在", os.path.exists(exported_vtt))

        if os.path.exists(burned_path):
            from subtitle.media import probe_duration
            out_dur = probe_duration(burned_path)
            check("e2e 燒錄輸出時長接近原片（5 秒）",
                  4.5 < out_dur < 5.5, str(out_dur))

            frame_path = os.path.join(tmp, "frame.png")
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-ss", "2", "-i", burned_path, "-frames:v", "1", frame_path],
                capture_output=True, timeout=60)
            check("e2e 擷取畫面成功（供人工確認字幕已燒錄）",
                  os.path.exists(frame_path) and os.path.getsize(frame_path) > 0)

        if os.path.exists(exported_srt):
            with open(exported_srt, encoding="utf-8") as fp:
                srt_content = fp.read()
            check("e2e 匯出 SRT 內容含匯入的字幕文字",
                  "真實端到端測試字幕" in srt_content, srt_content)
else:
    print("SKIP 真實端到端測試（無 ffmpeg，且自動安裝失敗）")

print()
if failures:
    print(f"共 {len(failures)} 項失敗：{failures}")
    sys.exit(1)
print("test_v1190 全部通過")
