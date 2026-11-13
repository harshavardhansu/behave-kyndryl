import argparse
import json
import math
import statistics
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get_json(url: str, timeout: float = 5.0) -> dict[str, Any]:
    with _NO_PROXY_OPENER.open(url, timeout=timeout) as response:
        return json.loads(response.read())


def request_summary(url: str, barrier: threading.Barrier, timeout: float) -> dict[str, Any]:
    barrier.wait(timeout=timeout)
    started = time.perf_counter()
    try:
        with _NO_PROXY_OPENER.open(url, timeout=timeout) as response:
            response.read()
            return {"status": response.status, "latency_ms": (time.perf_counter() - started) * 1000}
    except urllib.error.HTTPError as error:
        error.read()
        return {"status": error.code, "latency_ms": (time.perf_counter() - started) * 1000}
    except (TimeoutError, urllib.error.URLError) as error:
        return {
            "status": 0,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "transport_error": type(error).__name__,
        }


def run_workload(base_url: str, concurrency: int = 50, request_timeout: float = 30.0) -> dict[str, Any]:
    if not 15 <= concurrency <= 200:
        raise ValueError("Concurrency must be between 15 and 200, at least three times the pool size of five.")
    if request_timeout <= 2:
        raise ValueError("Request timeout must exceed the configured two-second database pool timeout.")

    config = get_json(f"{base_url.rstrip('/')}/control/config")
    if config.get("pool_size") != 5 and config.get("pool_size") != 20:
        raise ValueError("Workload is restricted to the calibrated pool sizes 5 and 20.")
    if config.get("max_overflow") != 0 or config.get("pool_timeout") != 2 or config.get("hold_seconds") != 0.3:
        raise ValueError("Active configuration differs from the calibrated workload parameters.")

    metrics_before = get_json(f"{base_url.rstrip('/')}/metrics")
    barrier = threading.Barrier(concurrency)
    started_at = datetime.now(timezone.utc).isoformat()
    run_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        results = list(
            executor.map(
                lambda _: request_summary(
                    f"{base_url.rstrip('/')}/payments/summary", barrier, request_timeout
                ),
                range(concurrency),
            )
        )
    elapsed_ms = (time.perf_counter() - run_started) * 1000
    ended_at = datetime.now(timezone.utc).isoformat()
    metrics_after = get_json(f"{base_url.rstrip('/')}/metrics")
    latencies = sorted(result["latency_ms"] for result in results)
    status_counts: dict[str, int] = {}
    for result in results:
        key = str(result["status"])
        status_counts[key] = status_counts.get(key, 0) + 1
    error_count = sum(result["status"] != 200 for result in results)
    return {
        "measurement_status": "MEASURED",
        "started_at": started_at,
        "ended_at": ended_at,
        "release": config["release"],
        "pool_size": config["pool_size"],
        "max_overflow": config["max_overflow"],
        "pool_timeout": config["pool_timeout"],
        "hold_seconds": config["hold_seconds"],
        "concurrency": concurrency,
        "request_count": len(results),
        "status_counts": status_counts,
        "error_count": error_count,
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 3) if latencies else 0,
            "p95": round(latencies[max(0, math.ceil(len(latencies) * 0.95) - 1)], 3) if latencies else 0,
            "max": round(latencies[-1], 3) if latencies else 0,
            "elapsed": round(elapsed_ms, 3),
        },
        "service_metrics_before": metrics_before,
        "service_metrics_after": metrics_after,
        "responses": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the calibrated Payment API sandbox workload.")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--request-timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expect-errors", action="store_true")
    parser.add_argument("--expect-zero-errors", action="store_true")
    arguments = parser.parse_args()
    if arguments.expect_errors and arguments.expect_zero_errors:
        parser.error("Choose only one expected error condition.")
    result = run_workload(arguments.base_url, arguments.concurrency, arguments.request_timeout)
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if arguments.expect_errors and result["error_count"] == 0:
        return 1
    if arguments.expect_zero_errors and result["error_count"] != 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())