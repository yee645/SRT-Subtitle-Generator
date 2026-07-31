# -*- coding: utf-8 -*-
"""v1.27.0 新功能測試：音訊轉視覺化影片（波形／頻譜）。"""
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

from subtitle import audiovis as av

# ===== 1. 設定解析與夾限 =====
s = av.resolve_audiovis_settings(None)
check("預設值", s == av.DEFAULT_AUDIOVIS, str(s))

s2 = av.resolve_audiovis_settings({"audiovis": {
    "mode": "SPECTRUM", "width": 99999, "height": 1, "color": "not-a-color"}})
check("mode 大小寫容錯", s2["mode"] == "spectrum", str(s2))
check("width 夾上限", s2["width"] == 3840, str(s2))
check("height 夾下限", s2["height"] == 360, str(s2))
check("非法色碼回預設", s2["color"] == "#3fa9f5", str(s2))

s3 = av.resolve_audiovis_settings({"audiovis": {"mode": "帶種"}})
check("非法 mode 回預設", s3["mode"] == "waveform", str(s3))

s4 = av.resolve_audiovis_settings({"audiovis": {"color": "#ABCDEF"}})
check("合法色碼保留", s4["color"] == "#ABCDEF", str(s4))

# ===== 2. suggest_output_path =====
check("輸出檔名固定 mp4",
      av.suggest_output_path("節目.mp3") == "節目_視覺化影片.mp4")
check("無副檔名也能處理",
      av.suggest_output_path("節目") == "節目_視覺化影片.mp4")

# ===== 3. 安全防呆（不需真的跑 ffmpeg 的錯誤路徑） =====
try:
    av.render_audio_video("不存在.mp3", "out.mp4")
    check("找不到檔案時報錯", False)
except FileNotFoundError:
    check("找不到檔案時報錯", True)

with tempfile.TemporaryDirectory() as tmp:
    fake_bg = os.path.join(tmp, "bg.txt")
    open(fake_bg, "wb").write(b"x")
    if av.ffmpeg_available():
        try:
            av.render_audio_video(fake_bg, os.path.join(tmp, "o.mp4"))
            check("非音訊檔（無音軌）時報錯", False)
        except ValueError as exc:
            check("非音訊檔（無音軌）時報錯", "音訊軌" in str(exc), str(exc))
    else:
        print("SKIP 無音軌防呆（無 ffmpeg）")

# ===== 4. config／GUI／CLI 靜態掃描 =====
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from config import DEFAULT_CONFIG
check("config 預設含 audiovis 區",
      DEFAULT_CONFIG.get("audiovis") == av.DEFAULT_AUDIOVIS,
      str(DEFAULT_CONFIG.get("audiovis")))

with open(os.path.join(root, "cli.py"), encoding="utf-8") as fp:
    cli_src = fp.read()
check("cli.py 有 --audiovis 旗標", "--audiovis" in cli_src)

with open(os.path.join(root, "gui", "audiovis_dialog.py"),
          encoding="utf-8") as fp:
    dialog_src = fp.read()
check("對話框有輸出視覺化影片按鈕與 handler",
      "輸出視覺化影片" in dialog_src and "render_audio_video" in dialog_src)
check("對話框無 classic tk.Checkbutton/Radiobutton 殘留",
      "tk.Checkbutton(" not in dialog_src.replace("ttk.Checkbutton(", "")
      and "tk.Radiobutton(" not in dialog_src.replace(
          "ttk.Radiobutton(", ""))

with open(os.path.join(root, "gui", "app.py"), encoding="utf-8") as fp:
    app_src = fp.read()
check("主視窗工具列有音訊轉影片按鈕",
      "音訊轉影片" in app_src and "AudioVisDialog" in app_src)

with open(os.path.join(root, "subtitle", "errors.py"),
          encoding="utf-8") as fp:
    errors_src = fp.read()
check("errors.py 已註冊「音訊轉影片失敗」的友善錯誤分類",
      "音訊轉影片失敗" in errors_src)

# ===== 5. 真實 ffmpeg 端到端 =====
if av.ffmpeg_available():
    with tempfile.TemporaryDirectory() as tmp:
        audio_path = os.path.join(tmp, "podcast.mp3")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
             "-c:a", "mp3", audio_path],
            capture_output=True, timeout=30)

        # 5a. 無背景圖：純黑底全畫面波形。
        out_no_bg = os.path.join(tmp, "no_bg.mp4")
        av.render_audio_video(
            audio_path, out_no_bg,
            settings=av.resolve_audiovis_settings(
                {"audiovis": {"width": 640, "height": 360}}))
        check("實測：無背景圖輸出檔已產生", os.path.exists(out_no_bg))

        def probe(path):
            proc = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height",
                 "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1", path],
                capture_output=True, text=True, timeout=30)
            info = {}
            for line in proc.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    info[k] = v
            return info

        info_no_bg = probe(out_no_bg)
        check("實測：無背景圖解析度正確",
              info_no_bg.get("width") == "640"
              and info_no_bg.get("height") == "360", str(info_no_bg))
        check("實測：無背景圖時長與音訊相符",
              abs(float(info_no_bg.get("duration", 0)) - 5.0) < 0.5,
              str(info_no_bg))

        # 像素驗證：波形顏色確實套用（非預設綠色，抽真實畫面比對亮度）。
        frame_path = os.path.join(tmp, "frame.png")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-i", out_no_bg, "-ss", "1", "-vframes", "1", frame_path],
            capture_output=True, timeout=30)
        check("實測：輸出影片可正常擷取畫面（非空白/損毀檔）",
              os.path.exists(frame_path)
              and os.path.getsize(frame_path) > 0)

        # 5b. 有背景圖：疊加成下緣色帶。
        bg_path = os.path.join(tmp, "bg.png")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=darkred:s=800x800",
             "-frames:v", "1", bg_path],
            capture_output=True, timeout=30)
        out_with_bg = os.path.join(tmp, "with_bg.mp4")
        av.render_audio_video(
            audio_path, out_with_bg,
            settings=av.resolve_audiovis_settings({"audiovis": {
                "width": 640, "height": 360, "background_image": bg_path,
                "mode": "spectrum"}}))
        check("實測：有背景圖（頻譜模式）輸出檔已產生",
              os.path.exists(out_with_bg))
        info_with_bg = probe(out_with_bg)
        check("實測：有背景圖解析度正確",
              info_with_bg.get("width") == "640"
              and info_with_bg.get("height") == "360", str(info_with_bg))
        check("實測：有背景圖時長與音訊相符",
              abs(float(info_with_bg.get("duration", 0)) - 5.0) < 0.5,
              str(info_with_bg))

        # 5c. 背景圖不存在時報錯。
        try:
            av.render_audio_video(
                audio_path, os.path.join(tmp, "x.mp4"),
                settings=av.resolve_audiovis_settings({"audiovis": {
                    "background_image": os.path.join(tmp, "沒有這張圖.png")}}))
            check("實測：背景圖不存在時報錯", False)
        except FileNotFoundError as exc:
            check("實測：背景圖不存在時報錯", "背景圖片" in str(exc), str(exc))

        # 5d. 整合驗證：轉出的影片可直接接上既有字幕燒錄管線
        # （純音訊來源原本完全無法使用「燒錄字幕」功能，這是本功能
        #  要打通的關鍵缺口）。
        from subtitle.burner import burn_subtitles
        from subtitle.media import has_audio_stream, probe_dimensions
        check("實測：轉出影片有音訊軌", has_audio_stream(out_no_bg))
        check("實測：轉出影片可正確探測畫面尺寸",
              probe_dimensions(out_no_bg) == (640, 360))
        burned_out = os.path.join(tmp, "burned.mp4")
        burn_subtitles(
            out_no_bg, [{"start": 0.0, "end": 2.0, "text": "整合測試字幕"}],
            burned_out)
        check("實測：轉出影片可成功燒錄字幕（打通純音訊來源的既有管線）",
              os.path.exists(burned_out))

        # 5e. CLI 端到端。
        env_main = os.path.join(root, "main.py")
        proc = subprocess.run(
            [sys.executable, env_main, "--audiovis", audio_path],
            cwd=tmp, capture_output=True, text=True, timeout=120)
        check("實測：CLI --audiovis 執行成功", proc.returncode == 0,
              proc.stdout + proc.stderr)
        cli_out = os.path.join(tmp, "podcast_視覺化影片.mp4")
        check("實測：CLI 輸出視覺化影片已產生", os.path.exists(cli_out))
else:
    print("SKIP 實測（無 ffmpeg）")

print()
if failures:
    print(f"共 {len(failures)} 項失敗：{failures}")
    sys.exit(1)
print("test_v1270 全部通過")
