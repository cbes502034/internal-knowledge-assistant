"""規格：app/core/llm_service.py 的重試、app/services/eval.py 的 compute_metrics"""
import pytest

from app.core.llm_service import LLMService, LLMUnavailableError
from app.services.eval import compute_metrics


# ---------- 重試 ----------
class Flaky:
    """前 fail_times 次丟出連線錯誤，之後成功。"""

    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ConnectionError("模型連不上")
        return "ok"


def test_retry_succeeds_after_transient_errors_with_backoff():
    waits: list[float] = []
    func = Flaky(fail_times=2)
    assert LLMService(sleep=waits.append)._call_with_retry(func) == "ok"
    assert func.calls == 3
    assert waits == [1.0, 2.0]


def test_retry_gives_up_and_hides_internal_error():
    waits: list[float] = []
    func = Flaky(fail_times=99)
    with pytest.raises(LLMUnavailableError) as exc:
        LLMService(sleep=waits.append)._call_with_retry(func)
    assert func.calls == 4                      # 第 1 次 + 重試 3 次
    assert waits == [1.0, 2.0, 4.0]
    assert "模型連不上" not in str(exc.value)    # 不洩漏內部細節


def test_non_transient_error_is_not_retried():
    def bad():
        raise ValueError("請求本身有問題")

    waits: list[float] = []
    with pytest.raises(LLMUnavailableError):
        LLMService(sleep=waits.append)._call_with_retry(bad)
    assert waits == []


# ---------- 評測指標 ----------
def case(hit_rank, should_refuse=False, refused=False, latency_ms=100):
    return {"hit_rank": hit_rank, "should_refuse": should_refuse, "refused": refused, "latency_ms": latency_ms}


def test_hit_rate_and_mrr_only_count_answerable_cases():
    m = compute_metrics([case(1), case(3), case(None), case(5), case(None, should_refuse=True, refused=True)])
    assert m["hit_at_1"] == pytest.approx(1 / 4)
    assert m["hit_at_3"] == pytest.approx(2 / 4)
    assert m["mrr"] == pytest.approx((1 + 1 / 3 + 0 + 1 / 5) / 4)


def test_refuse_accuracy():
    m = compute_metrics([case(None, True, True), case(None, True, False), case(1)])
    assert m["refuse_accuracy"] == pytest.approx(0.5)


def test_latency_percentiles():
    m = compute_metrics([case(1, latency_ms=ms) for ms in range(100, 2100, 100)])   # 100…2000 共 20 筆
    assert m["p50_ms"] == 1000
    assert m["p95_ms"] == 1900


def test_empty_categories_do_not_divide_by_zero():
    m = compute_metrics([])
    assert m["hit_at_1"] == 0.0 and m["refuse_accuracy"] == 0.0
