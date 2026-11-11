"""Local Payment API sandbox: the real Payment API, run as a local process.

This is the no-Docker way to demo a real, measurable incident:

* The Payment API (``payment_api/app.py``) runs on 127.0.0.1 with its own SQLite
  file and the same bounded connection pool as the container deployment
  (pool size N, no overflow, 2 s acquisition timeout, 0.3 s hold per request).
* Release v3.8.1 ships with pool size 5. Fifty concurrent requests to the new
  ``GET /payments/summary`` endpoint exhaust the pool and some requests fail with
  real HTTP 500 errors.
* The approved fix sets pool size 20 (keeping v3.8.1); the approved rollback
  goes back to the previous release (pool 20, no summary endpoint).

Only those calibrated configurations are accepted, only for this one local
service, and every change is verified against the live ``/control/config``.
It exposes the same ``apply_configuration`` contract as the container adapter
in ``payment_sandbox.py``, so ``workflow.py`` uses either without changes.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

APPROVED = {("3.8.1", 5), ("3.8.1", 20), ("previous", 20)}
INITIAL = ("3.8.1", 5)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SandboxError(Exception):
    """A safe, user-facing sandbox problem."""


class LocalPaymentSandbox:
    mode = "local"

    def __init__(self, root: Path | None = None, port: int | None = None, data_dir: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parents[1]
        self.port = port or int(os.getenv("PAYMENT_LOCAL_PORT", "18080"))
        self.data_dir = data_dir or self.root / "data"
        self.database = self.data_dir / "payment-sandbox.db"
        self.log_path = self.data_dir / "payment-sandbox.log"
        self.pid_path = self.data_dir / "payment-sandbox.pid"
        self.audit_path = self.data_dir / "payment-sandbox-audit.jsonl"
        self.process: subprocess.Popen | None = None
        self._lock = threading.RLock()

    # -- helpers -----------------------------------------------------------

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _get(self, path: str, timeout: float = 2.0) -> dict[str, Any] | None:
        try:
            with urllib.request.urlopen(self.url + path, timeout=timeout) as response:
                return json.loads(response.read().decode())
        except Exception:
            return None

    def _port_busy(self) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.3)
            return probe.connect_ex(("127.0.0.1", self.port)) == 0

    def _audit(self, record: dict[str, Any]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def _kill_stale(self) -> None:
        """Stop a sandbox left over from an earlier backend run (tracked by pid file)."""
        if not self.pid_path.exists():
            return
        try:
            pid = int(self.pid_path.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            for _ in range(30):
                time.sleep(0.1)
                os.kill(pid, 0)
        except (ValueError, ProcessLookupError, PermissionError, OSError):
            pass
        finally:
            self.pid_path.unlink(missing_ok=True)

    def _stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
        self._kill_stale()

    def _start(self, release: str, pool_size: int) -> dict[str, Any]:
        self._stop()
        if self._port_busy():
            raise SandboxError(f"Port {self.port} is already used by another program. Stop it or set PAYMENT_LOCAL_PORT.")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        environment = {
            **os.environ,
            "PAYMENT_LOCAL_MODE": "1",
            "PAYMENT_DATABASE_URL": f"sqlite:///{self.database}",
            "PAYMENT_API_VERSION": release,
            "PAYMENT_DB_POOL_SIZE": str(pool_size),
            "PAYMENT_DB_MAX_OVERFLOW": "0",
            "PAYMENT_DB_POOL_TIMEOUT": "2",
            "PAYMENT_DB_HOLD_SECONDS": "0.3",
        }
        log = self.log_path.open("ab")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "payment_api.app:create_app", "--factory", "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "warning"],
            cwd=self.root, env=environment, stdout=log, stderr=log,
            start_new_session=True,
        )
        self.pid_path.write_text(str(self.process.pid))
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise SandboxError("The Payment API process exited during start-up. See data/payment-sandbox.log.")
            active = self._get("/control/config")
            if active:
                return active
            time.sleep(0.2)
        self._stop()
        raise SandboxError("The Payment API did not become healthy within 20 seconds.")

    # -- public API --------------------------------------------------------

    def status(self) -> dict[str, Any]:
        with self._lock:
            running = bool(self.process and self.process.poll() is None)
            active = self._get("/control/config", timeout=1.0) if running else None
            return {
                "mode": self.mode,
                "running": running and active is not None,
                "url": self.url,
                "activeConfig": active,
                "featureX": bool(active and active.get("release") == "3.8.1"),
                "approvedConfigurations": [{"release": release, "pool_size": pool} for release, pool in sorted(APPROVED)],
            }

    def start(self, actor_id: str = "system") -> dict[str, Any]:
        with self._lock:
            if self.process and self.process.poll() is None and self._get("/control/config"):
                return self.status()
        result = self.apply_configuration(*INITIAL, actor_id=actor_id)
        if result["status"] != "SUCCEEDED":
            raise SandboxError(result["error"] or "The Payment API sandbox could not be started.")
        return self.status()

    def stop(self) -> None:
        with self._lock:
            self._stop()

    def apply_configuration(self, release: str, pool_size: int, actor_id: str = "system") -> dict[str, Any]:
        if (release, pool_size) not in APPROVED:
            raise ValueError("Only the approved sandbox configurations are allowed: v3.8.1 with pool 5 or 20, or the previous release with pool 20.")
        operation = {
            "operation_id": f"SOP-{uuid4().hex[:12].upper()}", "operation": "apply_configuration", "mode": self.mode,
            "actor_id": actor_id, "requested": {"release": release, "pool_size": pool_size}, "started_at": _now(), "status": "PENDING",
        }
        self._audit(operation)
        with self._lock:
            try:
                active = self._start(release, pool_size)
            except SandboxError as error:
                result = {**operation, "status": "MANUAL_INTERVENTION_REQUIRED", "completed_at": _now(), "active_config": None, "error": str(error)}
                self._audit(result)
                return result
        matches = active.get("release") == release and active.get("pool_size") == pool_size and active.get("max_overflow") == 0
        result = {
            **operation,
            "status": "SUCCEEDED" if matches else "MANUAL_INTERVENTION_REQUIRED",
            "completed_at": _now(),
            "active_config": active,
            "error": "" if matches else "The live sandbox configuration does not match the requested configuration.",
        }
        self._audit(result)
        return result

    def run_workload(self, concurrency: int = 50) -> dict[str, Any]:
        from payment_api.workload import run_workload

        with self._lock:
            if not (self.process and self.process.poll() is None):
                raise SandboxError("Start the Payment API sandbox first.")
            active = self._get("/control/config")
        result = run_workload(self.url, concurrency)
        counts = {int(code): count for code, count in result.get("status_counts", {}).items()}
        errors = sum(count for code, count in counts.items() if code >= 500)
        not_found = counts.get(404, 0)
        return {
            "measuredAt": _now(),
            "release": (active or {}).get("release"),
            "poolSize": (active or {}).get("pool_size"),
            "concurrency": concurrency,
            "requests": result.get("request_count", concurrency),
            "succeeded": counts.get(200, 0),
            "errors": errors,
            "notFound": not_found,
            "errorRate": round(errors / max(result.get("request_count", concurrency), 1) * 100, 1),
            "p95Ms": round(result.get("latency_ms", {}).get("p95", 0)),
            "maxMs": round(result.get("latency_ms", {}).get("max", 0)),
            "featureX": not_found == 0,
        }


def read_recent_errors(sandbox: "LocalPaymentSandbox", limit: int = 3) -> list[str]:
    """Return the most recent structured ERROR lines from the sandbox service log."""
    if not sandbox.log_path.exists():
        return []
    lines = sandbox.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
    errors = [line for line in lines if '"severity": "ERROR"' in line]
    return errors[-limit:]

