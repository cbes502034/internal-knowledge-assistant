"""規格：app/core/rrf.py、lru_cache.py、rate_limiter.py"""
import pytest

from app.core.lru_cache import LRUCache
from app.core.rate_limiter import TokenBucket
from app.core.rrf import rrf_fuse


# ---------- RRF ----------
def test_rrf_item_in_both_rankings_wins():
    fused = rrf_fuse([[3, 1, 2], [1, 4]])
    assert fused[0][0] == 1
    assert {i for i, _ in fused} == {1, 2, 3, 4}


def test_rrf_score_formula():
    fused = dict(rrf_fuse([[3, 1], [1]], k=60))
    assert fused[1] == pytest.approx(1 / 62 + 1 / 61)
    assert fused[3] == pytest.approx(1 / 61)


def test_rrf_ties_break_by_smaller_id_and_empty_input():
    assert [i for i, _ in rrf_fuse([[5], [2]])] == [2, 5]
    assert rrf_fuse([]) == []


# ---------- LRU ----------
def test_lru_get_put():
    cache = LRUCache(2)
    cache.put("a", 1)
    assert cache.get("a") == 1
    assert cache.get("missing") is None
    assert len(cache) == 1


def test_lru_evicts_least_recently_used():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")              # a 變成最近使用
    cache.put("c", 3)           # 淘汰 b
    assert cache.get("b") is None
    assert cache.get("a") == 1 and cache.get("c") == 3


def test_lru_update_existing_key_refreshes_it():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("a", 10)          # 更新也算使用
    cache.put("c", 3)           # 淘汰 b
    assert cache.get("a") == 10 and cache.get("b") is None
    assert len(cache) == 2


def test_lru_rejects_non_positive_capacity():
    with pytest.raises(ValueError):
        LRUCache(0)


# ---------- Token Bucket ----------
class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_bucket_starts_full_then_rejects():
    bucket = TokenBucket(capacity=3, refill_per_sec=1, now=FakeClock())
    assert [bucket.allow() for _ in range(4)] == [True, True, True, False]


def test_bucket_refills_over_time_but_not_beyond_capacity():
    clock = FakeClock()
    bucket = TokenBucket(capacity=2, refill_per_sec=1, now=clock)
    bucket.allow(), bucket.allow()
    assert bucket.allow() is False
    clock.t = 1.0                       # 過 1 秒，補 1 個
    assert bucket.allow() is True
    assert bucket.allow() is False
    clock.t = 100.0                     # 過很久也只補到滿（2 個）
    assert [bucket.allow() for _ in range(3)] == [True, True, False]
