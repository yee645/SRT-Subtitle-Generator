# -*- coding: utf-8 -*-
"""
某一個時間點該顯示哪一句字幕（3.0 第 2 項：播放器的字幕疊加層）。

零 GUI 依賴：Qt 版的播放器每一格都會問一次，之後的時間軸（第 4 項）拖曳
播放頭時也要問；放在核心層，兩邊才不會各寫一份、各有各的邊界規則。

邊界規則（與燒錄一致：ffmpeg 的 subtitles 濾鏡在 start ≤ t < end 顯示）：

* 包含開始、不包含結束——剛好在結束那一刻已經換下一句或消失，不會兩句
  同時出現在接縫上。
* 字幕重疊時（上一句還沒結束、下一句已經開始），顯示**開始得最晚**的那
  一句：使用者在清單裡剛打的那句一定看得到。
"""
import bisect


class CueIndex:
    """
    預先排好序的查詢索引。播放時每一格都查，所以建一次、查很多次；字幕
    清單一改就重建（建一次是 O(n log n)，幾千句也在毫秒內）。
    """

    def __init__(self, cues):
        # 依開始時間排序；同一個開始時間保留原本順序（sorted 是穩定的）。
        self._cues = sorted(
            (c for c in cues if float(c.get("end", 0)) > float(c.get("start", 0))),
            key=lambda c: float(c["start"]))
        self._starts = [float(c["start"]) for c in self._cues]
        # _reach[i]：前 i+1 句裡最晚的結束時間。往回找的時候，一旦這個值
        # 已經 ≤ 查詢時間，更前面的句子不可能還在顯示，可以停了——空檔時
        # 不必一路掃回開頭。
        self._reach = []
        latest = float("-inf")
        for cue in self._cues:
            latest = max(latest, float(cue["end"]))
            self._reach.append(latest)

    def __len__(self):
        return len(self._cues)

    def at(self, seconds):
        """回傳 seconds 這一刻該顯示的那句（cue dict），沒有就回傳 None。"""
        # 開始時間 ≤ seconds 的最後一句的位置。
        i = bisect.bisect_right(self._starts, seconds) - 1
        # 往前找第一句還沒結束的：沒有重疊時第一句就是。一句長字幕可能蓋
        # 住後面好幾句短的，所以不能看一句就放棄，但 _reach 會讓它在確定
        # 前面都已結束時停下。
        while i >= 0 and self._reach[i] > seconds:
            cue = self._cues[i]
            if seconds < float(cue["end"]):
                return cue
            i -= 1
        return None


def cue_at(cues, seconds):
    """只查一次的便利函式；要查很多次請建 CueIndex。"""
    return CueIndex(cues).at(seconds)
