# -*- coding: utf-8 -*-
"""
友善錯誤模組：把技術性例外翻譯成「原因＋解決方法」。

使用者回饋（Issue #24）：錯誤視窗只丟出一行技術訊息（甚至是 ffmpeg 的
英文 stderr），看不出哪裡出問題、更不知道該怎麼修。本模組集中維護
「常見失敗 → 白話原因 → 具體解法」的對照表，GUI 錯誤對話框與 CLI
輸出共用同一份翻譯，之後新增功能只要 raise 既有格式的訊息就自動受惠。

純文字規則、零 GUI 依賴，可完整單元測試。
"""

from __future__ import annotations

from typing import Union

# 錯誤類別（kind）：GUI 依此決定是否顯示對應的修復按鈕（如自動安裝 ffmpeg）。
KIND_GENERIC = "generic"
KIND_FFMPEG_MISSING = "ffmpeg_missing"
KIND_WHISPER_MISSING = "whisper_missing"
KIND_API_KEY = "api_key"
KIND_FILE_MISSING = "file_missing"
KIND_NO_SPEECH = "no_speech"
KIND_FFMPEG_FAILED = "ffmpeg_failed"
KIND_DISK = "disk"
KIND_NETWORK = "network"


class FriendlyError(RuntimeError):
    """帶「原因」與「解決方法」的錯誤，訊息本體仍是一句話摘要。"""

    def __init__(self, message: str, cause: str = "", solution: str = "",
                 details: str = "", kind: str = KIND_GENERIC):
        super().__init__(message)
        self.cause = cause          # 為什麼會發生（白話）
        self.solution = solution    # 具體要做什麼才能解決
        self.details = details      # 原始技術訊息（供回報或進階排查）
        self.kind = kind


_FFMPEG_MANUAL_URL = "https://www.gyan.dev/ffmpeg/builds/"
_ISSUE_URL = "https://github.com/yee645/SRT-Subtitle-Generator/issues"

# ffmpeg 執行中失敗的訊息開頭（各模組 raise 時帶原始 stderr 尾段）。
_FFMPEG_RUN_FAILURES = (
    "ffmpeg 燒錄失敗", "ffmpeg 粗剪失敗", "響度正規化失敗", "背景音樂混音失敗",
    "短片輸出失敗", "畫面擷取失敗", "無法啟動 ffmpeg",
)


def describe_exception(exc: Union[BaseException, str]) -> FriendlyError:
    """
    把任意例外（或錯誤字串）翻譯成 FriendlyError。

    已是 FriendlyError 者原樣回傳；能對照到已知情境的補上原因與解法；
    無法歸類的保留原文並引導附細節回報。
    """
    if isinstance(exc, FriendlyError):
        return exc
    text = str(exc)

    if "找不到 ffmpeg" in text or "找不到 ffprobe" in text:
        return FriendlyError(
            "找不到 ffmpeg（影音處理引擎）",
            cause="這部電腦尚未安裝 ffmpeg，或安裝後未加入系統 PATH。"
                  "本程式的轉錄、燒錄、剪輯、健檢等所有影音處理都依賴它。",
            solution="按「自動安裝 ffmpeg」讓程式自動下載安裝（免管理員權限、"
                     "不需設定 PATH）；或手動至 " + _FFMPEG_MANUAL_URL +
                     " 下載 release-essentials 壓縮檔，解壓後把 bin 資料夾"
                     "加入系統 PATH 再重啟本程式。",
            details=text, kind=KIND_FFMPEG_MISSING)

    if "找不到可用的本地 Whisper" in text or "無法啟動外部 Python" in text:
        return FriendlyError(
            "找不到可用的語音辨識引擎（Whisper）",
            cause="本程式打包版不內含 Whisper 語音辨識引擎，需要外部 Python "
                  "環境或改用雲端 API。",
            solution="三選一：(1) 安裝 Python 後執行 pip install openai-whisper，"
                     "並於「轉寫設定」的「本地 Python」欄位填入該 Python 路徑；"
                     "(2) 於「轉寫設定」啟用 OpenAI API 模式並填入金鑰"
                     "（免安裝、按用量計費）；(3) 已有逐字稿時改用"
                     "「模式二：文字稿對齊」。",
            details=text, kind=KIND_WHISPER_MISSING)

    if "載入 Whisper 模型失敗" in text or "外部 Whisper 辨識失敗" in text:
        return FriendlyError(
            "Whisper 語音辨識執行失敗",
            cause="常見原因：首次使用該模型時下載中斷（模型需連網下載）、"
                  "記憶體不足（large/medium 模型較吃資源）、或外部 Python "
                  "環境的 whisper 安裝不完整。",
            solution="先改選較小的模型（如 base）重試；確認網路暢通後再試一次"
                     "（模型只需下載一次）；若持續失敗，於該 Python 環境重跑 "
                     "pip install --upgrade openai-whisper。",
            details=text)

    if "尚未填入 OpenAI API 金鑰" in text:
        return FriendlyError(
            "API 模式缺少金鑰",
            cause="「轉寫設定」啟用了 OpenAI API 模式，但金鑰欄位是空的。",
            solution="至 platform.openai.com 建立 API 金鑰並填入「轉寫設定」"
                     "的金鑰欄位；或取消勾選 API 模式改用本地 Whisper。",
            details=text, kind=KIND_API_KEY)

    if "未安裝 openai 函式庫" in text:
        return FriendlyError(
            "缺少 openai 函式庫",
            cause="啟用了 API 模式，但目前環境沒有安裝 openai 套件。",
            solution="於命令列執行 pip install openai；或取消 API 模式"
                     "改用本地 Whisper。",
            details=text)

    if "呼叫 OpenAI API 失敗" in text:
        return FriendlyError(
            "OpenAI API 呼叫失敗",
            cause="常見原因：網路無法連線、API 金鑰無效或過期、帳戶額度用盡。",
            solution="確認網路可連上 api.openai.com；至 platform.openai.com "
                     "檢查金鑰狀態與剩餘額度；問題持續時重新產生一組金鑰。",
            details=text, kind=KIND_NETWORK)

    if ("未能從音訊辨識到任何人聲" in text
            or "辨識完成但未取得任何文字內容" in text):
        return FriendlyError(
            "沒有辨識到任何人聲",
            cause="來源檔可能沒有聲音軌、整段是音樂／環境音、或講話音量太小。",
            solution="先用播放器確認該檔案聽得到清楚人聲；若人聲很小聲，"
                     "可先做響度正規化再轉錄；確認選到的是正確的檔案。",
            details=text, kind=KIND_NO_SPEECH)

    if isinstance(exc, PermissionError) or "Permission denied" in text \
            or "拒絕存取" in text:
        return FriendlyError(
            "檔案無法寫入（權限不足或被占用）",
            cause="輸出位置沒有寫入權限（如 Program Files），"
                  "或檔案正被其他程式（播放器、剪輯軟體）開啟中。",
            solution="關閉正在使用該檔案的程式；或到「自動化輸出」把輸出資料夾"
                     "改到自己的文件／桌面等可寫入的位置。",
            details=text)

    if "No space left" in text or "空間不足" in text:
        return FriendlyError(
            "磁碟空間不足",
            cause="輸出磁碟的剩餘空間不夠寫入影片／音訊檔。",
            solution="清理磁碟空間，或把輸出資料夾改到其他磁碟後重試。",
            details=text, kind=KIND_DISK)

    if isinstance(exc, FileNotFoundError) or "找不到檔案" in text \
            or "找不到來源影片" in text or "找不到背景音樂檔" in text \
            or "找不到指定的音訊" in text:
        return FriendlyError(
            "找不到來源檔案",
            cause="檔案在選取之後被移動、改名或刪除了。",
            solution="重新瀏覽選擇檔案；若檔案在外接硬碟或網路磁碟，"
                     "確認其仍然連接中。",
            details=text, kind=KIND_FILE_MISSING)

    if any(text.startswith(prefix) or prefix in text
           for prefix in _FFMPEG_RUN_FAILURES):
        return FriendlyError(
            "影音處理（ffmpeg）執行失敗",
            cause="ffmpeg 處理這個檔案時中斷。常見原因：來源檔損壞或格式"
                  "特殊、磁碟空間不足、輸出位置無法寫入。",
            solution="先用播放器確認來源檔可以正常播放；確認磁碟剩餘空間；"
                     "把輸出資料夾換到可寫入的位置再試一次。問題持續時，"
                     "請複製下方技術細節回報。",
            details=text, kind=KIND_FFMPEG_FAILED)

    return FriendlyError(
        "發生未預期的錯誤",
        cause="這不是一個已知的常見問題，可能與特定檔案或環境有關。",
        solution="再試一次；若持續發生，請複製下方技術細節（並附上程式資料夾"
                 "的 app.log），到 " + _ISSUE_URL + " 回報。",
        details=text or repr(exc))


def format_error_text(exc: Union[BaseException, str]) -> str:
    """CLI／純文字情境用：翻譯後排成多行文字。"""
    err = describe_exception(exc)
    lines = [f"錯誤：{err}"]
    if err.cause:
        lines.append(f"原因：{err.cause}")
    if err.solution:
        lines.append(f"解法：{err.solution}")
    return "\n".join(lines)


def is_ffmpeg_missing(exc: Union[BaseException, str]) -> bool:
    """供 GUI 判斷是否顯示「自動安裝 ffmpeg」按鈕。"""
    return describe_exception(exc).kind == KIND_FFMPEG_MISSING
