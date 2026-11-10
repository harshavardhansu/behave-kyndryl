import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from uuid import uuid4


RELEASE_IMAGES = {
    "previous": "behave-payment-api:previous",
    "3.8.1": "behave-payment-api:3.8.1",
}
APPROVED_POOL_SIZES = {5, 20}


class PaymentSandboxControl(Protocol):
    def apply_configuration(self, release: str, pool_size: int, actor_id: str = "system") -> dict[str, Any]: ...


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class PaymentSandboxControlAdapter:
    project_name = "behave-payment-sandbox"
    service_name = "payment-api"

    def __init__(
        self,
        root: Path | None = None,
        runner: Callable[..., Any] = subprocess.run,
        active_config_reader: Callable[[dict[str, str]], dict[str, Any]] | None = None,
        audit_path: Path | None = None,
        compose_provider: str | None = None,
    ) -> None:
        self.root = root or Path(__file__).resolve().parents[1]
        self.compose_file = self.root / "compose.yaml"
        self.sample_env_file = self.root / "payment_api" / "sandbox.env.example"
        self.env_file = self.root / "payment_api" / ".env.sandbox"
        self.audit_path = audit_path or self.root / "data" / "payment-sandbox-audit.jsonl"
        self.runner = runner
        self.active_config_reader = active_config_reader or self._read_live_config
        self.compose_provider = compose_provider
        self._lock = threading.RLock()

    def _environment(self) -> dict[str, str]:
        source = self.env_file if self.env_file.exists() else self.sample_env_file
        values: dict[str, str] = {}
        for line in source.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator or key in values:
                raise ValueError("Sandbox configuration contains an invalid or duplicate setting.")
            values[key] = value
        self._validate_environment(values)
        return values

    def _validate_environment(self, values: dict[str, str]) -> None:
        if values.get("PAYMENT_COMPOSE_PROJECT") != self.project_name:
            raise ValueError("Sandbox control is restricted to the approved Compose project.")
        if values.get("PAYMENT_API_BIND_ADDRESS") not in {"127.0.0.1", "localhost"}:
            raise ValueError("The Payment API sandbox must be bound to loopback only.")
        release = values.get("PAYMENT_API_VERSION")
        if release not in RELEASE_IMAGES or values.get("PAYMENT_API_IMAGE") != RELEASE_IMAGES[release]:
            raise ValueError("Sandbox release configuration is not allowlisted.")
        try:
            pool_size = int(values["PAYMENT_DB_POOL_SIZE"])
            api_port = int(values["PAYMENT_API_PORT"])
            db_port = int(values["PAYMENT_DB_PORT"])
        except (KeyError, ValueError):
            raise ValueError("Sandbox ports or connection-pool settings are invalid.") from None
        if pool_size not in APPROVED_POOL_SIZES:
            raise ValueError("Only the calibrated sandbox pool sizes 5 and 20 are allowed.")
        if release == "previous" and pool_size != 20:
            raise ValueError("The previous Payment API release must use pool size 20.")
        if values.get("PAYMENT_DB_MAX_OVERFLOW") != "0" or values.get("PAYMENT_DB_POOL_TIMEOUT") != "2":
            raise ValueError("Sandbox overflow and timeout settings must match the calibrated scenario.")
        if values.get("PAYMENT_DB_HOLD_SECONDS") != "0.3":
            raise ValueError("Sandbox operation timing must match the calibrated scenario.")
        if not 1 <= api_port <= 65535 or not 1 <= db_port <= 65535:
            raise ValueError("Sandbox ports are outside the valid range.")

    def _write_environment(self, values: dict[str, str]) -> None:
        self._validate_environment(values)
        self.env_file.parent.mkdir(parents=True, exist_ok=True)
        content = "".join(f"{key}={value}\n" for key, value in sorted(values.items()))
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.env_file.parent, delete=False
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = temporary.name
            os.replace(temporary_path, self.env_file)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def _compose(self, *arguments: str) -> Any:
        if not self.compose_file.is_file():
            raise FileNotFoundError("The approved sandbox Compose file is unavailable.")
        self._environment()
        provider = self.compose_provider or shutil.which("podman-compose")
        if provider is None:
            executable = "podman-compose.exe" if os.name == "nt" else "podman-compose"
            candidate = Path(sys.executable).parent / executable
            if candidate.is_file():
                provider = str(candidate)
        if provider is None:
            raise FileNotFoundError("Install the native podman-compose provider from requirements-podman.txt.")
        command = [
            "podman",
            "compose",
            "--project-name",
            self.project_name,
            "--env-file",
            str(self.env_file),
            "--file",
            str(self.compose_file),
            *arguments,
        ]
        return self.runner(
            command,
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ, "PODMAN_COMPOSE_PROVIDER": provider},
        )

    def _read_live_config(self, values: dict[str, str]) -> dict[str, Any]:
        address = values["PAYMENT_API_BIND_ADDRESS"]
        if address == "localhost":
            address = "127.0.0.1"
        url = f"http://{address}:{values['PAYMENT_API_PORT']}/control/config"
        with urllib.request.urlopen(url, timeout=3) as response:
            active = json.loads(response.read())
        if active.get("service") != self.service_name:
            raise ValueError("The responding service is not the approved Payment API sandbox.")
        return {"truth_label": "REAL", **active}

    def _append_audit(self, record: dict[str, Any]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as audit_file:
            audit_file.write(json.dumps(record, sort_keys=True) + "\n")
            audit_file.flush()
            os.fsync(audit_file.fileno())

    def _read_result(self, values: dict[str, str]) -> dict[str, Any]:
        try:
            active = self.active_config_reader(values)
            return {"status": "REAL", "active_config": active, "error": ""}
        except Exception as error:
            return {
                "status": "NOT CONFIGURED",
                "active_config": None,
                "error": f"Payment API sandbox configuration could not be verified ({type(error).__name__}).",
            }

    def _wait_for_active_config(self, values: dict[str, str]) -> dict[str, Any]:
        deadline = time.monotonic() + 60
        result = self._read_result(values)
        while result["status"] != "REAL" and time.monotonic() < deadline:
            time.sleep(0.5)
            result = self._read_result(values)
        return result

    def prepare_sandbox(self, actor_id: str = "system") -> dict[str, Any]:
        operation_id = f"SOP-{uuid4().hex[:12].upper()}"
        started_at = timestamp()
        with self._lock:
            values = self._environment()
            values.update(
                PAYMENT_API_VERSION="3.8.1",
                PAYMENT_API_IMAGE=RELEASE_IMAGES["3.8.1"],
                PAYMENT_DB_POOL_SIZE="5",
            )
            pending = {
                "operation_id": operation_id,
                "operation": "prepare_sandbox",
                "actor_id": actor_id,
                "requested": {"release": "3.8.1", "pool_size": 5, "build_releases": ["previous", "3.8.1"]},
                "started_at": started_at,
                "status": "PENDING",
            }
            self._append_audit(pending)
            self._write_environment(values)
            try:
                self._compose("--profile", "release-build", "build", self.service_name, "payment-api-previous")
                self._compose("up", "--detach", "--force-recreate", self.service_name)
            except subprocess.CalledProcessError as error:
                status = "MANUAL_INTERVENTION_REQUIRED"
                reason = f"Compose operation failed with exit code {error.returncode}; active state must be inspected."
                active = None
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as error:
                status = "MANUAL_INTERVENTION_REQUIRED"
                reason = f"Sandbox preparation could not be confirmed ({type(error).__name__})."
                active = None
            else:
                verified = self._wait_for_active_config(values)
                active = verified["active_config"]
                if verified["status"] != "REAL":
                    status, reason = "MANUAL_INTERVENTION_REQUIRED", verified["error"]
                elif not self._matches(active, "3.8.1", 5):
                    status, reason = "MANUAL_INTERVENTION_REQUIRED", "The initial live sandbox configuration does not match v3.8.1 with pool size 5."
                else:
                    status, reason = "SUCCEEDED", ""
            result = {**pending, "status": status, "completed_at": timestamp(), "active_config": active, "error": reason}
            self._append_audit(result)
            return result

    @staticmethod
    def _matches(active: dict[str, Any], release: str, pool_size: int) -> bool:
        return (
            active.get("service") == "payment-api"
            and active.get("release") == release
            and active.get("pool_size") == pool_size
            and active.get("max_overflow") == 0
            and active.get("pool_timeout") == 2
            and active.get("hold_seconds") == 0.3
        )

    def get_active_config(self, actor_id: str = "system") -> dict[str, Any]:
        with self._lock:
            values = self._environment()
            result = self._read_result(values)
            operation = {
                "operation_id": f"SOP-{uuid4().hex[:12].upper()}",
                "operation": "get_active_config",
                "actor_id": actor_id,
                "timestamp": timestamp(),
                **result,
            }
            self._append_audit(operation)
            return operation

    def _apply(self, release: str, pool_size: int, operation: str, actor_id: str) -> dict[str, Any]:
        operation_id = f"SOP-{uuid4().hex[:12].upper()}"
        started_at = timestamp()
        with self._lock:
            current = self._environment()
            requested = {"release": release, "pool_size": pool_size}
            pending = {
                "operation_id": operation_id,
                "operation": operation,
                "actor_id": actor_id,
                "requested": requested,
                "started_at": started_at,
                "status": "PENDING",
            }
            self._append_audit(pending)
            previous_release = current["PAYMENT_API_VERSION"]
            current["PAYMENT_API_VERSION"] = release
            current["PAYMENT_API_IMAGE"] = RELEASE_IMAGES[release]
            current["PAYMENT_DB_POOL_SIZE"] = str(pool_size)
            self._write_environment(current)
            try:
                if release != previous_release:
                    self._compose("build", self.service_name)
                self._compose("up", "--detach", "--force-recreate", self.service_name)
            except subprocess.CalledProcessError as error:
                status = "MANUAL_INTERVENTION_REQUIRED"
                reason = f"Compose operation failed with exit code {error.returncode}; active state must be inspected."
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as error:
                status = "MANUAL_INTERVENTION_REQUIRED"
                reason = f"Sandbox control could not be confirmed ({type(error).__name__}); active state must be inspected."
            else:
                verified = self._wait_for_active_config(current)
                active = verified["active_config"]
                if verified["status"] != "REAL":
                    status = "MANUAL_INTERVENTION_REQUIRED"
                    reason = verified["error"]
                elif not self._matches(active, release, pool_size):
                    status = "MANUAL_INTERVENTION_REQUIRED"
                    reason = "The live sandbox configuration does not match the requested configuration."
                else:
                    status = "SUCCEEDED"
                    reason = ""
            result = {
                **pending,
                "status": status,
                "completed_at": timestamp(),
                "active_config": active if "active" in locals() else None,
                "error": reason,
            }
            self._append_audit(result)
            return result

    def set_release(self, version: str, actor_id: str = "system") -> dict[str, Any]:
        if version not in RELEASE_IMAGES:
            raise ValueError("Only the previous release and v3.8.1 are approved for this sandbox.")
        values = self._environment()
        pool_size = 20 if version == "previous" else int(values["PAYMENT_DB_POOL_SIZE"])
        return self._apply(version, pool_size, "set_release", actor_id)

    def apply_configuration(self, release: str, pool_size: int, actor_id: str = "system") -> dict[str, Any]:
        if release not in RELEASE_IMAGES:
            raise ValueError("Only the previous release and v3.8.1 are approved for this sandbox.")
        if pool_size not in APPROVED_POOL_SIZES:
            raise ValueError("Only the calibrated sandbox pool sizes 5 and 20 are allowed.")
        if release == "previous" and pool_size != 20:
            raise ValueError("The previous Payment API release must use pool size 20.")
        return self._apply(release, pool_size, "apply_configuration", actor_id)

    def set_pool_size(self, size: int, actor_id: str = "system") -> dict[str, Any]:
        if size not in APPROVED_POOL_SIZES:
            raise ValueError("Only the calibrated sandbox pool sizes 5 and 20 are allowed.")
        values = self._environment()
        if values["PAYMENT_API_VERSION"] == "previous" and size != 20:
            raise ValueError("The previous Payment API release must use pool size 20.")
        return self._apply(values["PAYMENT_API_VERSION"], size, "set_pool_size", actor_id)

    def restart(self, actor_id: str = "system") -> dict[str, Any]:
        operation_id = f"SOP-{uuid4().hex[:12].upper()}"
        started_at = timestamp()
        with self._lock:
            values = self._environment()
            pending = {
                "operation_id": operation_id,
                "operation": "restart",
                "actor_id": actor_id,
                "started_at": started_at,
                "status": "PENDING",
            }
            self._append_audit(pending)
            try:
                self._compose("up", "--detach", "--force-recreate", self.service_name)
                verified = self._wait_for_active_config(values)
                active = verified["active_config"]
                if verified["status"] != "REAL":
                    status, reason = "MANUAL_INTERVENTION_REQUIRED", verified["error"]
                elif not self._matches(active, values["PAYMENT_API_VERSION"], int(values["PAYMENT_DB_POOL_SIZE"])):
                    status, reason = "MANUAL_INTERVENTION_REQUIRED", "The live sandbox configuration differs from the requested state."
                else:
                    status, reason = "SUCCEEDED", ""
            except subprocess.CalledProcessError as error:
                status, reason, active = "MANUAL_INTERVENTION_REQUIRED", f"Compose operation failed with exit code {error.returncode}; active state must be inspected.", None
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as error:
                status, reason, active = "MANUAL_INTERVENTION_REQUIRED", f"Sandbox restart could not be confirmed ({type(error).__name__}).", None
            result = {**pending, "status": status, "completed_at": timestamp(), "active_config": active, "error": reason}
            self._append_audit(result)
            return result