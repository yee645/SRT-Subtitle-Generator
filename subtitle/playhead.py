# -*- coding: utf-8 -*-
"""
播放頭的規則（剪輯器版面 E-6a）：時間碼的寫法、逐格的步距、J／K／L 的速度。

只放純計算（零 GUI 依賴、不 import config）；按鍵與按鈕在 `gui_qt/editor.py`。
"""
DEFAULT_FPS = 30.0
MIN_FPS, MAX_FPS = 1.0, 240.0
JKL_RATES = (1.0, 2.0, 4.0)   # L 每按一次快一級，到 4 倍為止
J_STEP_MS = 1000              # J：倒退 1 秒（按住會連續倒退）


def clean_fps(fps):
    """量到的影格率不合理（None、0、負的、超過 240、不是數字）就用 30。"""
    try:
        fps = float(fps)
    except (TypeError, ValueError):
        return DEFAULT_FPS
    if fps != fps or not MIN_FPS <= fps <= MAX_FPS:
        return DEFAULT_FPS
    return fps


def format_timecode(ms):
    """毫秒 → 「時:分:秒.百分之一秒」（00:01:02.45）；負的當 0。百分之一秒無條件捨去，不會進位成下一秒。"""
    ms = max(0, int(ms))
    hours, rest = divmod(ms, 3600000)
    minutes, rest = divmod(rest, 60000)
    seconds, rest = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{rest // 10:02d}"


def frame_index(ms, fps):
    """第幾格（從 0 起）：落在那一格裡面都算那一格。"""
    fps = clean_fps(fps)
    return int(max(0, int(ms)) * fps / 1000.0 + 1e-6)


def frame_start_ms(index, fps):
    """第 index 格從幾毫秒開始（往上取整：保證落在那一格裡面，不會因為捨去掉回前一格）。"""
    fps = clean_fps(fps)
    exact = max(0, int(index)) * 1000.0 / fps
    ms = int(exact)
    return ms if ms >= exact - 1e-6 else ms + 1


def step_frames(ms, frames, fps, duration_ms=None):
    """
    從 ms 往前（負）或往後（正）走幾格，回傳新的毫秒（對齊到那一格的開頭）。夾在 0～片尾；
    片尾那一格以後不再走。
    """
    target = frame_index(ms, fps) + int(frames)
    out = frame_start_ms(max(0, target), fps)
    if duration_ms is not None and duration_ms > 0:
        last = frame_start_ms(frame_index(max(0, int(duration_ms) - 1), fps), fps)
        out = min(out, last)
    return max(0, out)


def next_rate(rate, playing):
    """L：沒在播就用 1 倍速播；在播就快一級（1→2→4，到頂不變）。"""
    if not playing:
        return JKL_RATES[0]
    faster = [r for r in JKL_RATES if r > float(rate) + 1e-9]
    return faster[0] if faster else JKL_RATES[-1]


def rewind(ms, step_ms=J_STEP_MS):
    """J：倒退 step_ms，不出片頭。"""
    return max(0, int(ms) - int(step_ms))
