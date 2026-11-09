# -*- coding: utf-8 -*-
"""
轉接檔：健檢中心的檢查與修復邏輯搬到 `subtitle/healthcheck.py` 了（3.0 第 11 項
第八階段，一般版與 3.0 共用）。

舊的 `from gui import health_aggregator` 照樣能用，拿到的就是同一個模組物件
（不是複本：改它的屬性、測試替換函式，兩個名字看到的都一樣）。
"""
import sys

from subtitle import healthcheck as _healthcheck

sys.modules[__name__] = _healthcheck
