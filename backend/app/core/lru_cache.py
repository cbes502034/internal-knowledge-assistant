"""LRU 快取：容量滿時淘汰最久沒用的項目。

對應職缺：高效能 API；資料結構（雜湊表＋雙向鏈結串列）
規格測試：tests/spec/test_algorithms.py

用途：同一個問題重複出現時，不重新計算向量。

為什麼是這兩個結構：
  雜湊表：用 key 在 O(1) 找到節點
  雙向鏈結串列：把節點移到最前面、從最後面移除都是 O(1)（只改前後指標）
  串列最前面＝最近使用，最後面＝最久沒用。頭尾各放一個哨兵節點，就不必處理空串列的特例。
"""
from typing import Any


class _Node:
    __slots__ = ("key", "value", "prev", "next")

    def __init__(self, key: Any = None, value: Any = None):
        self.key = key
        self.value = value
        self.prev: "_Node | None" = None
        self.next: "_Node | None" = None


class LRUCache:
    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("capacity 必須大於 0")
        self.capacity = capacity
        self._map: dict[Any, _Node] = {}
        self._head = _Node()        # 哨兵：head.next 是最近使用的
        self._tail = _Node()        # 哨兵：tail.prev 是最久沒用的
        self._head.next = self._tail
        self._tail.prev = self._head

    def _unlink(self, node: _Node) -> None:
        node.prev.next = node.next
        node.next.prev = node.prev

    def _push_front(self, node: _Node) -> None:
        node.prev = self._head
        node.next = self._head.next
        self._head.next.prev = node
        self._head.next = node

    def get(self, key):
        """找到回傳值並標記為最近使用；找不到回 None。"""
        node = self._map.get(key)
        if node is None:
            return None
        self._unlink(node)
        self._push_front(node)
        return node.value

    def put(self, key, value) -> None:
        """寫入或更新（更新也算使用）；超過容量時淘汰最久沒用的那一筆。"""
        node = self._map.get(key)
        if node is not None:
            node.value = value
            self._unlink(node)
            self._push_front(node)
            return
        if len(self._map) >= self.capacity:
            oldest = self._tail.prev
            self._unlink(oldest)
            del self._map[oldest.key]
        node = _Node(key, value)
        self._map[key] = node
        self._push_front(node)

    def __len__(self) -> int:
        return len(self._map)
