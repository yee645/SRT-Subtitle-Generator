# -*- coding: utf-8 -*-
"""
字幕尋找與取代對話框。

自動字幕的同一個錯字（人名、產品名、同音字）往往整集重複出現，
逐句雙擊修改效率極差。本對話框對字幕清單做批次尋找與取代：

- 「找下一個」在清單中循環跳到下一個命中的字幕列
- 「取代目前」只改目前選取的那一句，改完自動跳下一個
- 「全部取代」一次修正整份字幕，並回報取代次數

非強制回應（modeless）：對話框開著仍可操作主視窗清單。
比對為字面文字，可勾選是否區分大小寫（中文不受影響）。
"""

import tkinter as tk
from tkinter import messagebox, ttk

from config import save_config
from subtitle.textedit import (count_occurrences, find_in_cues,
                               normalize_correction_rules, replace_in_cues)


class ReplaceDialog(tk.Toplevel):
    """尋找與取代對話框：操作 app 的字幕清單（self.app.cues）。"""

    def __init__(self, app):
        super().__init__(app)
        self.title("尋找與取代")
        self.transient(app)
        self.resizable(False, False)
        self.app = app
        self._hits = []      # 目前搜尋字串命中的 cue 索引
        self._pos = -1       # 下一個要跳到的命中位置

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="尋找：").grid(row=0, column=0, sticky="w", pady=3)
        self.find_var = tk.StringVar()
        find_entry = ttk.Entry(body, textvariable=self.find_var, width=28)
        find_entry.grid(row=0, column=1, sticky="we", padx=(6, 0), pady=3)
        find_entry.focus_set()
        # 輸入時即時更新命中統計，按 Enter 直接找下一個。
        self.find_var.trace_add("write", lambda *_a: self._invalidate())
        find_entry.bind("<Return>", lambda _e: self._on_find_next())

        ttk.Label(body, text="取代為：").grid(row=1, column=0, sticky="w", pady=3)
        self.replace_var = tk.StringVar()
        ttk.Entry(body, textvariable=self.replace_var, width=28).grid(
            row=1, column=1, sticky="we", padx=(6, 0), pady=3)

        self.case_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            body, text="區分大小寫（英文）", variable=self.case_var,
            command=self._invalidate,
        ).grid(row=2, column=1, sticky="w", padx=(6, 0))

        self.status_var = tk.StringVar(value="輸入要尋找的文字。")
        ttk.Label(body, textvariable=self.status_var,
                  foreground="#666666").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(6, 2))

        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="we", pady=(4, 0))
        ttk.Button(buttons, text="找下一個", width=10,
                   command=self._on_find_next).pack(side="left", padx=2)
        ttk.Button(buttons, text="取代目前", width=10,
                   command=self._on_replace_current).pack(side="left", padx=2)
        ttk.Button(buttons, text="全部取代", width=10,
                   command=self._on_replace_all).pack(side="left", padx=2)
        ttk.Button(buttons, text="關閉", width=8,
                   command=self.destroy).pack(side="right", padx=2)

        # 自動修正詞庫：把目前的取代存成規則，之後每次生成字幕自動套用。
        rules_frame = ttk.LabelFrame(
            body, text="自動修正詞庫（每次生成字幕後自動套用）", padding=(8, 6))
        rules_frame.grid(row=5, column=0, columnspan=2, sticky="we",
                         pady=(10, 0))
        self.rules_list = tk.Listbox(rules_frame, height=5)
        self.rules_list.pack(fill="both", expand=True)
        rule_buttons = ttk.Frame(rules_frame)
        rule_buttons.pack(fill="x", pady=(4, 0))
        ttk.Button(
            rule_buttons, text="把目前取代存為規則", width=18,
            command=self._on_save_rule).pack(side="left", padx=2)
        ttk.Button(
            rule_buttons, text="刪除選取規則", width=12,
            command=self._on_delete_rule).pack(side="left", padx=2)
        self._refresh_rules()

        self.bind("<Escape>", lambda _e: self.destroy())

    # ------------------------------------------------------------------
    def _invalidate(self):
        """搜尋條件變動：重算命中清單並更新統計文字。"""
        term = self.find_var.get()
        self._hits = find_in_cues(self.app.cues, term, self.case_var.get())
        self._pos = -1
        if not term:
            self.status_var.set("輸入要尋找的文字。")
        elif not self._hits:
            self.status_var.set("沒有找到符合的字幕。")
        else:
            total = count_occurrences(self.app.cues, term, self.case_var.get())
            self.status_var.set(
                f"共 {len(self._hits)} 句字幕、{total} 處符合。")

    def _select_cue(self, index):
        """在主視窗清單中選取並捲動到指定 cue。"""
        children = self.app.cue_tree.get_children()
        if 0 <= index < len(children):
            item = children[index]
            self.app.cue_tree.selection_set(item)
            self.app.cue_tree.see(item)

    # ------------------------------------------------------------------
    def _on_find_next(self):
        # 清單可能在對話框開啟後被編輯過，每次都以最新內容重找。
        self._hits = find_in_cues(
            self.app.cues, self.find_var.get(), self.case_var.get())
        if not self._hits:
            self._invalidate()
            return
        self._pos = (self._pos + 1) % len(self._hits)
        self._select_cue(self._hits[self._pos])
        self.status_var.set(
            f"第 {self._pos + 1} / {len(self._hits)} 個符合的字幕。")

    def _on_replace_current(self):
        """只取代目前選取（或下一個命中）的那一句，改完跳到下一個。"""
        term = self.find_var.get()
        if not term:
            return
        if self._pos < 0 or self._pos >= len(self._hits):
            self._on_find_next()
            if self._pos < 0:
                return
        target = self._hits[self._pos]
        new_cues, count = replace_in_cues(
            self.app.cues, term, self.replace_var.get(),
            self.case_var.get(), only_indices=[target])
        if count:
            self.app.cues = new_cues
            self.app.apply_text_edits()
        # 目標句已修正，重找並停在下一個命中處。
        self._hits = find_in_cues(self.app.cues, term, self.case_var.get())
        self._pos = -1
        if self._hits:
            # 跳到原位置之後的第一個命中（沒有就繞回開頭）。
            later = [i for i, idx in enumerate(self._hits) if idx >= target]
            self._pos = (later[0] - 1) if later else -1
            self._on_find_next()
        else:
            self.status_var.set(f"已取代，沒有其他符合的字幕了。")

    def _on_replace_all(self):
        term = self.find_var.get()
        if not term:
            return
        new_cues, count = replace_in_cues(
            self.app.cues, term, self.replace_var.get(), self.case_var.get())
        if not count:
            messagebox.showinfo("全部取代", "沒有找到符合的文字。",
                                parent=self)
            return
        self.app.cues = new_cues
        self.app.apply_text_edits()
        self._invalidate()
        self.status_var.set(f"已取代 {count} 處。")

    # ------------------------------------------------------------------
    # 自動修正詞庫（規則記憶）
    # ------------------------------------------------------------------
    def _current_rules(self):
        return normalize_correction_rules(
            self.app.config_data.get("corrections"))

    def _save_rules(self, rules):
        self.app.config_data["corrections"] = rules
        try:
            save_config(self.app.config_data)
        except OSError:
            pass  # 存檔失敗不影響本次使用，下次關閉程式仍會再存。
        self._refresh_rules()

    def _refresh_rules(self):
        self.rules_list.delete(0, "end")
        for rule in self._current_rules():
            case = "（區分大小寫）" if rule["case"] else ""
            target = rule["replace"] if rule["replace"] else "（刪除）"
            self.rules_list.insert("end",
                                   f"{rule['find']} → {target}{case}")

    def _on_save_rule(self):
        find = self.find_var.get().strip()
        if not find:
            messagebox.showinfo("提示", "請先填入「尋找」欄位。", parent=self)
            return
        rules = [r for r in self._current_rules() if r["find"] != find]
        rules.append({"find": find,
                      "replace": self.replace_var.get(),
                      "case": bool(self.case_var.get())})
        self._save_rules(rules)
        self.status_var.set(
            f"已存為自動修正規則（共 {len(rules)} 條），之後每次生成字幕自動套用。")

    def _on_delete_rule(self):
        selection = self.rules_list.curselection()
        if not selection:
            messagebox.showinfo("提示", "請先在清單中選取要刪除的規則。",
                                parent=self)
            return
        rules = self._current_rules()
        del rules[selection[0]]
        self._save_rules(rules)
        self.status_var.set("已刪除選取的規則。")
