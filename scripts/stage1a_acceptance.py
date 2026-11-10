import argparse
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.payment_sandbox import PaymentSandboxControlAdapter
from payment_api.workload import run_workload


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def compose(adapter: PaymentSandboxControlAdapter, *arguments: str, profile: str | None = None) -> Any:
    if profile:
        return adapter._compose("--profile", profile, *arguments)
    return adapter._compose(*arguments)


def get_json(url: str, timeout: float = 5.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read())


def response_status(url: str) -> tuple[int, dict[str, Any] | None]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            body = json.loads(response.read())
            return response.status, body
    except urllib.error.HTTPError as error:
        error.read()
        return error.code, None


def wait_for_health(base_url: str, timeout_seconds: int = 90) -> dict[str, Any]:
    import time

    deadline = time.monotonic() + timeout_seconds
    last_error = "service did not respond"
    while time.monotonic() < deadline:
        try:
            return get_json(f"{base_url}/health", timeout=3)
        except Exception as error:
            last_error = type(error).__name__
            time.sleep(0.5)
    raise RuntimeError(f"Payment API health check timed out ({last_error}).")


def read_audit(adapter: PaymentSandboxControlAdapter) -> list[dict[str, Any]]:
    if not adapter.audit_path.exists():
        return []
    return [json.loads(line) for line in adapter.audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_cycle(adapter: PaymentSandboxControlAdapter, run_number: int, concurrency: int) -> dict[str, Any]:
    environment = adapter._environment()
    base_url = f"http://127.0.0.1:{environment['PAYMENT_API_PORT']}"
    previous_url = f"http://127.0.0.1:{environment['PAYMENT_PREVIOUS_API_PORT']}"
    record: dict[str, Any] = {
        "run": run_number,
        "started_at": timestamp(),
        "status": "RUNNING",
        "workload": {"concurrency": concurrency, "request_timeout_seconds": 30, "operation_seconds": 0.3},
    }
    prepared = adapter.prepare_sandbox(actor_id="stage1a-acceptance")
    record["prepare"] = prepared
    if prepared["status"] != "SUCCEEDED":
        raise RuntimeError(prepared["error"] or "Initial sandbox state was not verified.")

    postgres = compose(
        adapter,
        "exec",
        "--no-T",
        "payment-db",
        "pg_isready",
        "-U",
        environment["PAYMENT_DB_USER"],
        "-d",
        environment["PAYMENT_DB_NAME"],
    )
    record["postgres_health"] = postgres.stdout.strip()
    if "accepting connections" not in postgres.stdout.lower():
        raise RuntimeError("PostgreSQL did not report accepting connections.")

    initial_config = adapter.get_active_config(actor_id="stage1a-acceptance")
    if initial_config["status"] != "REAL":
        raise RuntimeError(initial_config["error"])
    record["initial_config"] = initial_config["active_config"]
    if not adapter._matches(initial_config["active_config"], "3.8.1", 5):
        raise RuntimeError("The initial v3.8.1 / pool size 5 state was not verified.")
    record["initial_health"] = wait_for_health(base_url)
    feature_status, feature_summary = response_status(f"{base_url}/payments/summary")
    if feature_status != 200 or not feature_summary or feature_summary.get("payment_count", 0) <= 0:
        raise RuntimeError("Feature X did not return a meaningful Payment API summary.")
    record["initial_feature"] = {"http_status": feature_status, "summary": feature_summary}

    previous_started = False
    try:
        compose(adapter, "up", "--detach", "payment-api-previous", profile="release-build")
        previous_started = True
        record["previous_health"] = wait_for_health(previous_url)
        previous_config = get_json(f"{previous_url}/control/config")
        previous_feature_status, _ = response_status(f"{previous_url}/payments/summary")
        record["previous_release_check"] = {
            "config": previous_config,
            "feature_x_http_status": previous_feature_status,
        }
        if previous_config.get("release") != "previous" or previous_config.get("pool_size") != 20:
            raise RuntimeError("The previous release is not running with pool size 20.")
        if previous_feature_status != 404:
            raise RuntimeError("Feature X must not be exposed by the previous release.")
    finally:
        if previous_started:
            compose(adapter, "stop", "payment-api-previous", profile="release-build")

    failed_load = run_workload(base_url, concurrency=concurrency)
    record["pool_5_workload"] = failed_load
    if failed_load["error_count"] <= 0 or int(failed_load["status_counts"].get("500", 0)) <= 0:
        raise RuntimeError("The controlled pool size 5 workload did not produce actual HTTP 500 responses.")

    logs = compose(adapter, "logs", "--no-color", "payment-api").stdout
    timeout_lines = [line for line in logs.splitlines() if "TimeoutError" in line]
    record["timeout_log_lines"] = timeout_lines[-20:]
    if not timeout_lines:
        raise RuntimeError("The service logs did not identify the SQLAlchemy connection acquisition TimeoutError.")

    recovered = adapter.apply_configuration("3.8.1", 20, actor_id="stage1a-acceptance")
    record["recovery_control"] = recovered
    if recovered["status"] != "SUCCEEDED":
        raise RuntimeError(recovered["error"] or "Pool size 20 was not applied and verified.")
    record["recovery_health"] = wait_for_health(base_url)
    recovery_config = adapter.get_active_config(actor_id="stage1a-acceptance")
    record["recovery_config"] = recovery_config["active_config"]
    if recovery_config["status"] != "REAL" or not adapter._matches(recovery_config["active_config"], "3.8.1", 20):
        raise RuntimeError("The active v3.8.1 / pool size 20 state was not verified.")

    recovered_load = run_workload(base_url, concurrency=concurrency)
    record["pool_20_workload"] = recovered_load
    if recovered_load["error_count"] != 0:
        raise RuntimeError("The same workload still produced errors after pool restoration.")
    recovered_feature_status, recovered_summary = response_status(f"{base_url}/payments/summary")
    record["recovered_feature"] = {"http_status": recovered_feature_status, "summary": recovered_summary}
    if recovered_feature_status != 200 or not recovered_summary:
        raise RuntimeError("Feature X did not remain available after pool restoration.")

    audit_records = read_audit(adapter)
    for result in (prepared, recovered):
        statuses = {
            item.get("status")
            for item in audit_records
            if item.get("operation_id") == result["operation_id"]
        }
        if not {"PENDING", "SUCCEEDED"} <= statuses:
            raise RuntimeError(f"Sandbox control operation {result['operation_id']} is not fully audited.")
    record["audited_operation_ids"] = [prepared["operation_id"], recovered["operation_id"]]
    record["finished_at"] = timestamp()
    record["status"] = "PASS"
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Run three complete Stage 1A Payment API acceptance cycles.")
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--output-root", type=Path, default=Path("test-results/stage1a"))
    arguments = parser.parse_args()
    if arguments.concurrency < 15:
        parser.error("Concurrency must be at least 15 (three times the configured pool size of five).")

    adapter = PaymentSandboxControlAdapter()
    sequence = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = arguments.output_root / sequence
    output_dir.mkdir(parents=True, exist_ok=False)
    summary: dict[str, Any] = {
        "sequence": sequence,
        "truth_label": "MEASURED",
        "required_runs": 3,
        "concurrency": arguments.concurrency,
        "runs": [],
    }
    failed = False
    for run_number in range(1, 4):
        try:
            record = run_cycle(adapter, run_number, arguments.concurrency)
        except Exception as error:
            record = {
                "run": run_number,
                "started_at": timestamp(),
                "finished_at": timestamp(),
                "status": "FAIL",
                "error": f"{type(error).__name__}: {error}",
            }
            failed = True
        (output_dir / f"run-{run_number}.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        summary["runs"].append(record)
        print(f"Run {run_number}: {record['status']}")
        if failed:
            for skipped in range(run_number + 1, 4):
                not_run = {"run": skipped, "status": "NOT RUN", "reason": "A prior run failed; correct the cause and restart the three-run sequence."}
                (output_dir / f"run-{skipped}.json").write_text(json.dumps(not_run, indent=2) + "\n", encoding="utf-8")
                summary["runs"].append(not_run)
            break
    summary["status"] = "PASS" if len(summary["runs"]) == 3 and all(item["status"] == "PASS" for item in summary["runs"]) else "FAIL"
    summary["owner_verification"] = "NOT RUN"
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Acceptance sequence: {summary['status']}")
    print(f"Results: {summary_path}")
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
