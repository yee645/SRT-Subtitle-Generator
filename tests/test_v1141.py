# -*- coding: utf-8 -*-
"""
v1.14.1 修復驗證：

1. 英文（拉丁字）字幕黏字：subtitle/segmenter.py 的 join_words()——
   純拉丁文補空白、純中文不補空白、中英混排只在拉丁-拉丁邊界補空白、
   標點前不產生孤立空白；review.py 改為直接重用 segmenter 的實作
   （不再各自維護一份）。
2. 深色主題主視窗：gui/app.py 的可設定元件應已改為 ttk 版本
   （靜態掃描 classic tk.Frame/Label/Entry/Button/Radiobutton 不應殘留）；
   gui/scrollable.py 的 ScrollableFrame 需支援依主題設定 Canvas 背景色
   並提供 refresh_theme() 供主題切換時同步。
3. 視窗預設寬度：gui/app.py 預設幾何應為 1400x800（1180 會裁切樣式面板
   的「選擇顏色」按鈕，已由真實螢幕截圖驗證）。
4. 對齊模式字幕重疊：subtitle/segmenter.py 的 _post_process() 應保證
   輸出嚴格不重疊、時間單調遞增——不重疊優先於最短秒數。

另包含真實 CLI 端到端驗證（若本機有 ffmpeg，以 lavfi 合成極短測試音訊，
並以假 external-python whisper 替身跑完整「模式一」流程，
確認實際輸出的 .srt 內容確實修好黏字問題）。
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
def check(name, cond, extra=""):
    print(("PASS" if cond else f"FAIL {extra}"), name)
    if not cond:
        failures.append(name)

from subtitle import review, segmenter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def words_of(*tokens):
    """把 (文字, start, end) tuple 清單轉成逐字時間軸 dict 清單。"""
    return [{"word": text, "start": start, "end": end}
            for text, start, end in tokens]


# ===== 1. join_words()：拉丁字補空白、中文不補空白、混排、標點 =====

pure_latin = words_of(
    ("This", 0.0, 0.2), ("is", 0.2, 0.4), ("a", 0.4, 0.5), ("test", 0.5, 0.8))
check("純拉丁文加空白", segmenter.join_words(pure_latin) == "This is a test",
      segmenter.join_words(pure_latin))

pure_cjk = words_of(("這", 0.0, 0.1), ("是", 0.1, 0.2), ("測", 0.2, 0.3),
                    ("試", 0.3, 0.4))
check("純中文不加空白", segmenter.join_words(pure_cjk) == "這是測試",
      segmenter.join_words(pure_cjk))

mixed = words_of(("我", 0.0, 0.1), ("們", 0.1, 0.2), ("用", 0.2, 0.3),
                 ("OBS", 0.3, 0.6), ("Studio", 0.6, 1.0),
                 ("錄", 1.0, 1.1), ("影", 1.1, 1.2))
check("中英混排只在拉丁-拉丁邊界補空白",
      segmenter.join_words(mixed) == "我們用OBS Studio錄影",
      segmenter.join_words(mixed))

punct = words_of(("today", 0.0, 0.3), (".", 0.3, 0.35))
check("標點前不產生孤立空白", segmenter.join_words(punct) == "today.",
      repr(segmenter.join_words(punct)))

punct_comma = words_of(("Well", 0.0, 0.2), (",", 0.2, 0.22),
                       ("hello", 0.3, 0.6), ("!", 0.6, 0.62))
check("逗號與驚嘆號前不產生孤立空白",
      segmenter.join_words(punct_comma) == "Well, hello!",
      repr(segmenter.join_words(punct_comma)))

empty_ignored = words_of(("Hi", 0.0, 0.1), ("", 0.1, 0.1), ("there", 0.2, 0.4))
check("空字串 token 不影響拼接",
      segmenter.join_words(empty_ignored) == "Hi there",
      repr(segmenter.join_words(empty_ignored)))

# review.py 應直接重用 segmenter.join_words，不再各自維護一份實作。
check("review._join_words 與 segmenter.join_words 是同一個函式",
      review._join_words is segmenter.join_words)

# build_cues_from_words 端到端：確認實際生成流程也修好了黏字問題。
seg_cfg = {"max_chars_cjk": 18, "max_chars_latin": 45, "min_duration": 0.1,
          "max_duration": 30.0, "pause_gap": 5.0}
latin_words = words_of(
    ("This", 0.0, 0.25), ("is", 0.25, 0.45), ("a", 0.45, 0.55),
    ("test", 0.55, 0.85), ("of", 0.85, 1.00), ("latin", 1.00, 1.35),
    ("segmentation", 1.35, 1.95), ("logic", 1.95, 2.25),
    ("here", 2.25, 2.50), ("today", 2.50, 2.85), (".", 2.85, 2.90))
cues = segmenter.build_cues_from_words(latin_words, seg_cfg)
full_text = " ".join(c["text"] for c in cues).replace(" .", ".")
check("build_cues_from_words 產生的字幕不再黏字",
      "This is a test of" in full_text and "Thisisatestof" not in full_text,
      full_text)

# ===== 2. 深色主題：主視窗改用 ttk 元件、ScrollableFrame 支援主題背景 =====

app_path = os.path.join(REPO_ROOT, "gui", "app.py")
check("gui/app.py 存在", os.path.exists(app_path))
if os.path.exists(app_path):
    app_src = open(app_path, encoding="utf-8").read()
    # 排除字串當中出現 "ttk.Xxx(" 造成的假陽性：只找真正的 classic 呼叫。
    import re
    for widget in ("Frame", "Label", "Entry", "Button", "Radiobutton"):
        pattern = re.compile(r"(?<!t)tk\." + widget + r"\(")
        hits = pattern.findall(app_src)
        check(f"gui/app.py 無殘留 classic tk.{widget}(", not hits,
              f"殘留 {len(hits)} 處")
    check("gui/app.py 主題切換會同步捲動畫布背景",
          "scroll_frame.refresh_theme" in app_src)
    check("gui/app.py 預設幾何為 1400x800",
          'self.geometry("1400x800")' in app_src)

scrollable_path = os.path.join(REPO_ROOT, "gui", "scrollable.py")
check("gui/scrollable.py 存在", os.path.exists(scrollable_path))
if os.path.exists(scrollable_path):
    scrollable_src = open(scrollable_path, encoding="utf-8").read()
    check("ScrollableFrame 支援 theme 參數", "def __init__(self, master, theme=" in scrollable_src)
    check("ScrollableFrame 提供 refresh_theme()", "def refresh_theme(self" in scrollable_src)

# 靜態掃描 ScrollableFrame 的主題色對照表（不 import tkinter，
# 與本專案既有慣例一致：一般測試套件不依賴 tkinter/DISPLAY 才能執行；
# 實際的 Tk 視窗渲染改由 GUI screenshot 驗證，見發版說明）。
if os.path.exists(scrollable_path):
    check("淺色主題背景色對照表含 #fafafa（sv-ttk light 的 colors(-bg)）",
          '"light": "#fafafa"' in scrollable_src)
    check("深色主題背景色對照表含 #1c1c1c（sv-ttk dark 的 colors(-bg)）",
          '"dark": "#1c1c1c"' in scrollable_src)


# ===== 3. 對齊模式字幕重疊：_post_process 保證不重疊、時間單調遞增 =====

def has_overlap(cues):
    return any(cues[i]["end"] > cues[i + 1]["start"]
              for i in range(len(cues) - 1))


def is_monotonic(cues):
    return all(cues[i]["start"] <= cues[i + 1]["start"]
              for i in range(len(cues) - 1))


overlap_seg_cfg = {"min_duration": 1.0, "max_duration": 7.0,
                   "max_chars_cjk": 18, "max_chars_latin": 45}

# 案例 1：原始回報的確切重現（近乎相同起始時間，前一句過短觸發最短秒數延伸）。
repro_cues = [
    {"start": 4.733, "end": 4.833, "text": "這是一段測試字幕內容"},
    {"start": 4.733, "end": 5.733, "text": "希望接下來一切順利進行"},
]
out1 = segmenter._post_process(list(repro_cues), overlap_seg_cfg)
check("案例1（原始回報重現）輸出不重疊", not has_overlap(out1),
      [(c["start"], c["end"]) for c in out1])
check("案例1 時間單調遞增", is_monotonic(out1),
      [(c["start"], c["end"]) for c in out1])
check("案例1 保留兩句字幕", len(out1) == 2, len(out1))
if len(out1) == 2:
    check("案例1 下一句長度維持原本 1.0 秒（不重疊優先於最短秒數）",
          abs((out1[1]["end"] - out1[1]["start"]) - 1.0) < 1e-6,
          out1[1]["end"] - out1[1]["start"])

# 案例 2：起始時間完全相同。
identical_start_cues = [
    {"start": 10.0, "end": 10.2, "text": "第一句測試內容文字"},
    {"start": 10.0, "end": 11.0, "text": "第二句測試內容文字"},
]
out2 = segmenter._post_process(list(identical_start_cues), overlap_seg_cfg)
check("案例2（起始時間相同）輸出不重疊", not has_overlap(out2),
      [(c["start"], c["end"]) for c in out2])
check("案例2 時間單調遞增", is_monotonic(out2),
      [(c["start"], c["end"]) for c in out2])

# 案例 3：正常不衝突的情況，時長不應被這次修改影響。
normal_cues = [
    {"start": 0.0, "end": 2.0, "text": "第一句正常字幕內容測試"},
    {"start": 2.5, "end": 4.5, "text": "第二句正常字幕內容測試"},
]
out3 = segmenter._post_process(list(normal_cues), overlap_seg_cfg)
check("案例3（正常情況）輸出不重疊", not has_overlap(out3))
check("案例3 第一句時長不變（2.0 秒）",
      len(out3) >= 1 and abs((out3[0]["end"] - out3[0]["start"]) - 2.0) < 1e-6,
      [(c["start"], c["end"]) for c in out3])
if len(out3) >= 2:
    check("案例3 第二句時長不變（2.0 秒）",
          abs((out3[1]["end"] - out3[1]["start"]) - 2.0) < 1e-6,
          [(c["start"], c["end"]) for c in out3])
    check("案例3 起始時間不變", out3[1]["start"] == 2.5, out3[1]["start"])


# ===== 4. 真實 CLI 端到端驗證（若本機有 ffmpeg 才執行） =====

HAVE_FFMPEG = shutil.which("ffmpeg") is not None
if not HAVE_FFMPEG:
    print("\n(找不到 ffmpeg，略過真實 CLI 端到端驗證——僅單元測試通過與否有效)")
else:
    STUB_WHISPER_TEMPLATE = '''# -*- coding: utf-8 -*-
class _FakeModel:
    def transcribe(self, audio_path, **kwargs):
        words = {words!r}
        return {{"segments": [{{"words": [
            {{"word": w, "start": s, "end": e}} for w, s, e in words
        ]}}]}}


def load_model(name):
    return _FakeModel()
'''

    def make_stub_python(tmp_dir, name, words):
        """建立一個「假 external whisper」的 python 包裝腳本，回傳其路徑。

        機制與真實 python_path 設定一致：wrapper 內把 PYTHONPATH 指到
        只含假 whisper.py 的資料夾，再交給真正的 python 執行；主流程本身
        （驅動 main.py 的行程）不會拿到這個 PYTHONPATH，因此程式內
        `import whisper` 仍會失敗，確保真的是走 python_path 外部子程序機制。
        """
        stub_dir = os.path.join(tmp_dir, f"stub_{name}")
        os.makedirs(stub_dir, exist_ok=True)
        with open(os.path.join(stub_dir, "whisper.py"), "w",
                  encoding="utf-8") as fp:
            fp.write(STUB_WHISPER_TEMPLATE.format(words=words))
        wrapper_path = os.path.join(tmp_dir, f"stub_python_{name}.sh")
        with open(wrapper_path, "w", encoding="utf-8") as fp:
            fp.write("#!/bin/sh\n")
            fp.write(f'export PYTHONPATH="{stub_dir}"\n')
            fp.write(f'exec "{sys.executable}" "$@"\n')
        st = os.stat(wrapper_path)
        os.chmod(wrapper_path, st.st_mode | stat.S_IEXEC)
        return wrapper_path

    def run_cli(work_dir, config):
        with open(os.path.join(work_dir, "config.json"), "w",
                  encoding="utf-8") as fp:
            json.dump(config, fp, ensure_ascii=False)
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "main.py"), "clip.wav"],
            cwd=work_dir, env=env, capture_output=True, text=True, timeout=60)
        return result

    with tempfile.TemporaryDirectory() as tmp:
        clip_path = os.path.join(tmp, "clip.wav")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=3", clip_path],
            check=True)

        # --- 純英文：確認不再黏字，標點前也不會有孤立空白 ---
        en_words = [
            ("This", 0.00, 0.25), (" is", 0.25, 0.45), (" a", 0.45, 0.55),
            (" test", 0.55, 0.85), (" of", 0.85, 1.00), (" latin", 1.00, 1.35),
            (" segmentation", 1.35, 1.95), (" logic", 1.95, 2.25),
            (" here", 2.25, 2.50), (" today", 2.50, 2.85), (".", 2.85, 2.90),
        ]
        en_work = os.path.join(tmp, "en")
        os.makedirs(en_work)
        shutil.copy(clip_path, os.path.join(en_work, "clip.wav"))
        stub_python = make_stub_python(tmp, "en", en_words)
        config = {
            "transcription": {"model": "base", "language": "en",
                              "use_api": False, "api_key": "",
                              "python_path": stub_python, "prompt": "",
                              "use_cache": False},
            "automation": {"export_srt": True, "export_vtt": False,
                          "export_ass": False, "export_txt": False,
                          "burn_video": False, "output_dir": ""},
        }
        result = run_cli(en_work, config)
        check("純英文 CLI 流程正常結束", result.returncode == 0,
              result.stdout + result.stderr)
        srt_path = os.path.join(en_work, "clip.srt")
        check("純英文 CLI 產生 .srt 檔", os.path.exists(srt_path))
        if os.path.exists(srt_path):
            srt_text = open(srt_path, encoding="utf-8").read()
            joined = srt_text.replace("\n", " ")
            check("CLI 產生的 .srt 含正確斷詞的英文（This is a test of）",
                  "This is a test of" in joined, srt_text)
            check("CLI 產生的 .srt 無黏字（Thisisatestof 不應出現）",
                  "Thisisatestof" not in joined, srt_text)
            check("CLI 產生的 .srt 標點前無孤立空白（today.）",
                  "today ." not in srt_text, srt_text)

        # --- 中英混排：確認只在拉丁-拉丁邊界補空白 ---
        mixed_words = [
            ("我", 0.00, 0.15), ("們", 0.15, 0.30), ("用", 0.30, 0.45),
            (" OBS", 0.45, 0.75), (" Studio", 0.75, 1.15),
            ("錄", 1.15, 1.30), ("影", 1.30, 1.45),
        ]
        mixed_work = os.path.join(tmp, "mixed")
        os.makedirs(mixed_work)
        shutil.copy(clip_path, os.path.join(mixed_work, "clip.wav"))
        stub_python_mixed = make_stub_python(tmp, "mixed", mixed_words)
        config_mixed = {
            "transcription": {"model": "base", "language": "zh",
                              "use_api": False, "api_key": "",
                              "python_path": stub_python_mixed, "prompt": "",
                              "use_cache": False},
            "automation": {"export_srt": True, "export_vtt": False,
                          "export_ass": False, "export_txt": False,
                          "burn_video": False, "output_dir": ""},
        }
        result_mixed = run_cli(mixed_work, config_mixed)
        check("中英混排 CLI 流程正常結束", result_mixed.returncode == 0,
              result_mixed.stdout + result_mixed.stderr)
        srt_mixed_path = os.path.join(mixed_work, "clip.srt")
        check("中英混排 CLI 產生 .srt 檔", os.path.exists(srt_mixed_path))
        if os.path.exists(srt_mixed_path):
            srt_mixed_text = open(srt_mixed_path, encoding="utf-8").read()
            check("中英混排只在 OBS/Studio 之間補空白",
                  "我們用OBS Studio錄影" in srt_mixed_text, srt_mixed_text)


print("\n" + ("ALL PASS" if not failures else f"FAILURES: {failures}"))
sys.exit(1 if failures else 0)
