"""Token Bucket 限流。

對應職缺：高效能 RESTful API 的開發與維護
規格測試：tests/spec/test_rate_limiter.py

概念：桶子最多放 capacity 個代幣，每秒補 refill_per_sec 個；
每個請求拿走一個，拿不到就拒絕（API 回 429）。
"""
import time
from collections.abc import Callable


class TokenBucket:
    def __init__(self, capacity: int, refill_per_sec: float, now: Callable[[], float] = time.monotonic):
        """TODO：一開始桶子是滿的。now 可注入，測試時不用真的等待。"""
        raise NotImplementedError("core.rate_limiter.TokenBucket.__init__ 尚未實作")

    def allow(self) -> bool:
        """TODO：先依經過的時間補代幣（不超過 capacity），有代幣就扣一個回 True，否則回 False。"""
        raise NotImplementedError("core.rate_limiter.TokenBucket.allow 尚未實作")
