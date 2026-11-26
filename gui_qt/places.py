# -*- coding: utf-8 -*-
"""
面板的說明文字指路用哪一套說法（剪輯器版面 E-7a）。

同一個面板可能放在四頁籤或剪輯器版面裡。顯示帶「②字幕頁」「④」這類頁籤編號的文字時都經過 `here(元件, 文字)`：
元件（或它往上任何一層父元件）所在的視窗標了剪輯器版面，就照 `subtitle/placenames.py` 換成剪輯器的說法，
否則原樣（四頁籤一字不差）。看的是元件當下的位置，不是全域開關：同一個程式裡兩種視窗可以並存。

剪輯器版面建好之後另外用 `relabel_tree` 把已經顯示出來的字（標籤、按鈕、提示、佔位字、群組標題、頁籤）換一輪：
面板是四頁籤先建好再搬過去的，建的當下還不知道會放在哪。
"""
from PySide6.QtWidgets import (
    QAbstractButton, QGroupBox, QLabel, QLineEdit, QPlainTextEdit, QTabWidget, QTextEdit, QWidget,
)

from subtitle.placenames import for_editor, has_tab_place

LAYOUT_PROPERTY = "srtLayout"
EDITOR = "editor"


def layout_of(widget):
    """元件所在的版面："editor" 或 "tabs"（往上找父元件，對話框也算它的父視窗）。"""
    w = widget
    while w is not None:
        value = w.property(LAYOUT_PROPERTY)
        if value:
            return value
        w = w.parentWidget()
    return "tabs"


def here(widget, text):
    """這段說明文字在 widget 所在的版面該怎麼講。"""
    if not has_tab_place(text):
        return text
    return for_editor(text) if layout_of(widget) == EDITOR else text


def relabel_tree(root, skip=()):
    """把 root 底下已經顯示的字換成剪輯器的說法；回傳換了幾處。skip 裡的元件（與它底下）不動。"""
    skip = tuple(skip)
    changed = 0
    for w in [root] + root.findChildren(QWidget):
        if any(w is s or s.isAncestorOf(w) for s in skip):
            continue
        for get, put in _accessors(w):
            text = get()
            if has_tab_place(text):
                put(for_editor(text))
                changed += 1
    return changed


def _accessors(w):
    pairs = [(w.toolTip, w.setToolTip)]
    if isinstance(w, (QLabel, QAbstractButton)):
        pairs.append((w.text, w.setText))
    if isinstance(w, (QLineEdit, QPlainTextEdit, QTextEdit)):
        pairs.append((w.placeholderText, w.setPlaceholderText))
    if isinstance(w, QGroupBox):
        pairs.append((w.title, w.setTitle))
    if isinstance(w, QTabWidget):
        for i in range(w.count()):
            pairs.append((lambda i=i: w.tabText(i), lambda t, i=i: w.setTabText(i, t)))
            pairs.append((lambda i=i: w.tabToolTip(i), lambda t, i=i: w.setTabToolTip(i, t)))
    return pairs
