import threading

import pytest

from payment_api import workload


def test_workload_rejects_concurrency_below_three_times_the_failure_pool(monkeypatch):
    monkeypatch.setattr(workload, "get_json", lambda *_: pytest.fail("No network call expected"))

    with pytest.raises(ValueError, match="at least three times"):
        workload.run_workload("http://127.0.0.1:18080", concurrency=14)


def test_workload_summarizes_http_statuses_and_latency(monkeypatch):
    config = {
        "release": "3.8.1",
        "pool_size": 5,
        "max_overflow": 0,
        "pool_timeout": 2,
        "hold_seconds": 0.3,
    }
    monkeypatch.setattr(
        workload,
        "get_json",
        lambda url: config if url.endswith("/control/config") else {"request_count": 0},
    )
    statuses = iter([500, *([200] * 14)])
    status_lock = threading.Lock()

    def request_summary(url, barrier, timeout):
        assert url.endswith("/payments/summary")
        assert timeout > 2
        barrier.wait(timeout=timeout)
        with status_lock:
            status = next(statuses)
        return {"status": status, "latency_ms": float(status)}

    monkeypatch.setattr(workload, "request_summary", request_summary)

    result = workload.run_workload("http://127.0.0.1:18080", concurrency=15)

    assert result["request_count"] == 15
    assert result["status_counts"] == {"200": 14, "500": 1}
    assert result["error_count"] == 1
    assert result["latency_ms"]["p95"] == 500.0
