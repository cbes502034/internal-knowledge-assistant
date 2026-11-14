"""LRU 快取：容量滿時淘汰最久沒用的項目。

對應職缺：高效能 API；資料結構（雜湊表＋雙向鏈結串列）
規格測試：tests/spec/test_lru_cache.py

用途：同一個問題重複出現時，不重新計算向量。
要求：get、put 都是 O(1)。請自己實作雙向鏈結串列，不要用 OrderedDict 或 functools。
"""


class LRUCache:
    def __init__(self, capacity: int):
        """TODO：capacity <= 0 → raise ValueError。"""
        raise NotImplementedError("core.lru_cache.LRUCache.__init__ 尚未實作")

    def get(self, key):
        """TODO：找到回傳值並標記為「最近使用」；找不到回 None。"""
        raise NotImplementedError("core.lru_cache.LRUCache.get 尚未實作")

    def put(self, key, value) -> None:
        """TODO：寫入或更新；超過容量時淘汰最久沒用的那一筆。"""
        raise NotImplementedError("core.lru_cache.LRUCache.put 尚未實作")

    def __len__(self) -> int:
        raise NotImplementedError("core.lru_cache.LRUCache.__len__ 尚未實作")
