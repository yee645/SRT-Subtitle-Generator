# -*- coding: utf-8 -*-
"""
「新版介面速覽」對照表（v1.52.1 第二輪）。

v1.52 把主視窗從「11 顆工具列按鈕 + 一整頁欄位」改成四個階段頁籤，
`docs/UI_ARCHITECTURE_2.0.md` D 節點名的風險就是老用戶的肌肉記憶會落
空——按鈕沒有消失，只是搬家了，但使用者第一眼看到的是「不見了」。

所以這裡不做那種「歡迎使用新版！」的行銷頁，而是一張**舊位置 → 新位置**
的對照表：使用者心裡想的是「我的某某功能呢」，這張表就照那個問法回答。
兩顆被改名的按鈕也列進來（D-1），因為改名比搬家更難靠找的找到。

首次啟動時由 `gui/app.py` 呼叫；勾「不再顯示」後寫入 config 的
`whatsnew_seen`，之後任何版本都不再跳（見 `NEVER_SHOW`）。
"""

import tkinter as tk
from tkinter import ttk

# 使用者勾了「不再顯示」時寫進 config["whatsnew_seen"] 的值。用哨符字串
# 而不是布林，是為了和「看過 1.52.1 這一版」區分開來：前者是永久關閉，
# 後者只代表這一版看過了，日後又一次大改介面仍可再導覽一次。
NEVER_SHOW = "never"

# (舊位置, 新位置) 對照。順序照使用者最可能先找哪一個排，不是照程式碼順序。
MOVED = [
    ("工具列〔審片助手（找片段）〕", "① 素材與剪輯"),
    ("工具列〔字幕健檢〕〔章節健檢〕〔發佈健檢〕〔封面健檢〕等健檢類",
     "③ 健檢中心（一個窗看完，不必逐項開）"),
    ("工具列〔配樂助手〕〔品牌套版〕", "④ 輸出與發佈 → 成品加工"),
    ("清單編輯列〔匯入字幕〕", "① 素材與剪輯（匯入是來源，不是清單操作）"),
    ("「匯出與燒錄」區", "④ 輸出與發佈 →「輸出」框下半"),
    ("「自動化輸出（一鍵完成用）」區", "④ 輸出與發佈 →「輸出」框中段，已改名「輸出設定」"),
]

# (舊名, 新名, 為什麼改) 對照。
RENAMED = [
    ("自動跳剪停頓", "剪停頓（依字幕）", "原名看不出它吃的是字幕還是影片"),
    ("重複片段偵測", "剪重複片段", "原名只說偵測，其實會剪"),
]

# 拆掉的按鈕要單獨講，因為它不是搬家也不是改名，是行為變了。
SPLIT_TEXT = (
    "〔一鍵完成（生成＋匯出＋燒錄）〕拆成並排的兩顆："
    "〔開始生成字幕〕與〔完成輸出（依輸出設定）〕。\n"
    "舊按鈕會一路衝到底，等於沒有校對的機會就把錯字燒進影片；"
    "拆開後中間那段空白就是校對、健檢、翻譯的位置。"
    "不需要校對的話，連按兩顆，結果和以前完全一樣。\n"
    "一次處理多個檔案時，動作列會自動多出〔批次一鍵完成〕，"
    "行為與舊按鈕一致（批次本來就不會逐支校對）。"
)


class WhatsNewDialog(tk.Toplevel):
    """新版介面速覽；關閉時把「不再顯示」的選擇回報給 on_close。"""

    def __init__(self, master, version, on_close=None):
        super().__init__(master)
        self.title("新版介面速覽")
        self.transient(master)
        self.resizable(True, True)
        self.geometry("720x620")
        self.minsize(600, 480)
        self._on_close = on_close

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body, justify="left", wraplength=660,
            text=f"這一版（{version}）把主視窗改成四個階段頁籤：\n"
                 "① 素材與剪輯 → ② 字幕 → ③ 健檢中心 → ④ 輸出與發佈。\n"
                 "頁籤的順序就是做一支影片的順序，原本的功能一個都沒有拿掉，"
                 "只是搬到它該在的階段。以下是搬家對照表。",
        ).pack(anchor="w", pady=(0, 10))

        canvas_holder = ttk.Frame(body)
        canvas_holder.pack(fill="both", expand=True)
        # 捲軸先 pack（side="right"）再 pack 內容區，順序反了會讓捲軸被
        # 擠成 1px——v1.48.0 出過這個包，見 docs/ROADMAP_2.0.md 紀律節。
        scrollbar = ttk.Scrollbar(canvas_holder, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        text = tk.Text(
            canvas_holder, wrap="word", height=10, relief="flat",
            yscrollcommand=scrollbar.set, padx=8, pady=6,
        )
        text.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=text.yview)
        text.insert("end", self._build_body())
        text.configure(state="disabled")

        self.never_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            body, text="不再顯示這個速覽", variable=self.never_var,
        ).pack(anchor="w", pady=(10, 0))

        ttk.Button(body, text="開始使用", width=12, command=self._close).pack(
            anchor="e", pady=(8, 0))
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build_body(self):
        """組出對照表全文。純字串，方便測試直接驗內容。"""
        lines = ["【功能搬到哪裡了】", ""]
        for old, new in MOVED:
            lines.append(f"　{old}\n　　→ {new}")
        lines += ["", "【改名的按鈕】", ""]
        for old, new, why in RENAMED:
            lines.append(f"　{old} → 「{new}」（{why}）")
        lines += ["", "【「一鍵完成」拆成兩顆】", "", SPLIT_TEXT]
        return "\n".join(lines)

    def _close(self):
        if self._on_close:
            self._on_close(bool(self.never_var.get()))
        self.destroy()


def should_show(config, version):
    """
    是否該在啟動時跳出速覽。

    看過這一版、或勾過「不再顯示」就不跳。抽成函式讓 GUI 那端只剩一行
    判斷，也讓這個規則可以不開視窗就測。
    """
    seen = (config.get("whatsnew_seen") or "").strip()
    return seen != NEVER_SHOW and seen != version
