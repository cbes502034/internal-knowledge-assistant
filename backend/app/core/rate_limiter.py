"""Token Bucket 限流。

對應職缺：高效能 RESTful API 的開發與維護
規格測試：tests/spec/test_algorithms.py

概念：桶子最多放 capacity 個代幣，每秒補 refill_per_sec 個；每個請求拿走一個，拿不到就拒絕（API 回 429）。
好處：允許短時間內的少量爆發（桶子是滿的），長期平均速率又被限制住。

限制：桶子存在這個行程的記憶體中。多個 worker 或多台主機時，每個行程各算各的，
正式環境要改放在 Redis 這類共用的地方。
"""
import threading
import time
from collections.abc import Callable


class TokenBucket:
    def __init__(self, capacity: int, refill_per_sec: float, now: Callable[[], float] = time.monotonic):
        if capacity <= 0 or refill_per_sec <= 0:
            raise ValueError("capacity 與 refill_per_sec 必須大於 0")
        self.capacity = capacity
        self.refill_per_sec = refill_per_sec
        self._now = now                     # 可注入，測試時不用真的等待
        self._tokens = float(capacity)      # 一開始桶子是滿的
        self._last = now()

    def _refill(self) -> None:
        current = self._now()
        elapsed = max(0.0, current - self._last)
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_sec)
        self._last = current

    def allow(self) -> bool:
        """先依經過的時間補代幣，有代幣就扣一個回 True，否則回 False。"""
        self._refill()
        if self._tokens >= 1:
            self._tokens -= 1
            return True
        return False

    def retry_after(self) -> float:
        """還要等幾秒才會有下一個代幣（給 429 的 Retry-After 使用）。"""
        self._refill()
        return max(0.0, (1 - self._tokens) / self.refill_per_sec)


class KeyedRateLimiter:
    """每個 key（例如使用者編號）一個桶子。FastAPI 的同步端點在執行緒池中執行，所以要加鎖。"""

    def __init__(self, capacity: int, refill_per_sec: float, now: Callable[[], float] = time.monotonic):
        self._capacity = capacity
        self._refill = refill_per_sec
        self._now = now
        self._buckets: dict[object, TokenBucket] = {}
        self._lock = threading.Lock()

    def check(self, key) -> tuple[bool, float]:
        """回傳 (是否允許, 還要等幾秒)。"""
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = self._buckets[key] = TokenBucket(self._capacity, self._refill, self._now)
            if bucket.allow():
                return True, 0.0
            return False, bucket.retry_after()
