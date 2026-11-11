"""Local Payment API sandbox: real process integration, API endpoints and mission integration."""

import socket
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.domain import Settings
from backend.payment_local import LocalPaymentSandbox, SandboxError
from backend.store import Store


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def real_sandbox(tmp_path: Path):
    sandbox = LocalPaymentSandbox(port=free_port(), data_dir=tmp_path)
    yield sandbox
    sandbox.stop()


def test_real_sandbox_fails_at_pool_5_and_recovers_at_pool_20(real_sandbox):
    started = real_sandbox.start()
    assert started["running"] and started["activeConfig"]["pool_size"] == 5
    broken = real_sandbox.run_workload(50)
    assert broken["errors"] > 0 and broken["featureX"]
    fixed = real_sandbox.apply_configuration("3.8.1", 20)
    assert fixed["status"] == "SUCCEEDED" and fixed["active_config"]["pool_size"] == 20
    healthy = real_sandbox.run_workload(50)
    assert healthy["errors"] == 0 and healthy["succeeded"] == 50 and healthy["featureX"]
    rolled_back = real_sandbox.apply_configuration("previous", 20)
    assert rolled_back["status"] == "SUCCEEDED"
    previous = real_sandbox.run_workload(50)
    assert previous["errors"] == 0 and previous["notFound"] == 50 and not previous["featureX"]


def test_only_approved_configurations(real_sandbox):
    for release, pool in [("3.8.1", 50), ("previous", 5), ("9.9.9", 20)]:
        with pytest.raises(ValueError):
            real_sandbox.apply_configuration(release, pool)


def test_workload_requires_a_running_sandbox(real_sandbox):
    with pytest.raises(SandboxError):
        real_sandbox.run_workload(50)


class FakeSandbox(LocalPaymentSandbox):
    """No process: pool 5 fails 9/50, pool 20 succeeds. Exercises the API and mission wiring."""

    def __init__(self):
        super().__init__(port=1, data_dir=Path("/nonexistent"))
        self.config = None
        self.calls = []

    def status(self):
        return {"mode": "local", "running": self.config is not None, "url": "http://fake", "activeConfig": self.config, "featureX": True}

    def start(self, actor_id="system"):
        self.config = {"service": "payment-api", "release": "3.8.1", "pool_size": 5, "max_overflow": 0}
        return self.status()

    def stop(self):
        self.config = None

    def apply_configuration(self, release, pool_size, actor_id="system"):
        self.calls.append((release, pool_size, actor_id))
        self.config = {"service": "payment-api", "release": release, "pool_size": pool_size, "max_overflow": 0}
        return {"status": "SUCCEEDED", "active_config": self.config, "error": ""}

    def run_workload(self, concurrency=50):
        if self.config is None:
            raise SandboxError("Start the Payment API sandbox first.")
        errors = 9 if self.config["pool_size"] == 5 else 0
        return {"measuredAt": "2026-11-11T00:00:00+00:00", "release": self.config["release"], "poolSize": self.config["pool_size"], "concurrency": 50,
                "requests": 50, "succeeded": 50 - errors, "errors": errors, "notFound": 0, "errorRate": errors * 2.0, "p95Ms": 2400 if errors else 900, "maxMs": 2700, "featureX": True}


@pytest.fixture
def app_and_sandbox():
    sandbox = FakeSandbox()
    application = create_app(Settings(AGENTICA_MODE="demo", AGENTICA_DEMO_STEP_SECONDS=0), Store("sqlite:///:memory:"), sandbox_control=sandbox)
    with TestClient(application) as client:
        yield client, sandbox


def login(client, role="Incident Manager"):
    response = client.post("/api/v1/auth/demo", json={"role": role})
    client.headers["X-CSRF-Token"] = response.json()["csrf"]


def test_sandbox_endpoints_record_measured_evidence(app_and_sandbox):
    client, _ = app_and_sandbox
    login(client)
    assert client.post("/api/v1/sandbox/payment/workload", json={"incidentId": "INC-1043"}).status_code == 409
    assert client.post("/api/v1/sandbox/payment/start").json()["running"] is True
    result = client.post("/api/v1/sandbox/payment/workload", json={"incidentId": "INC-1043"}).json()
    assert result["measurement"]["errors"] == 9 and result["evidenceIds"]
    snapshot = client.get("/api/v1/workspace").json()
    evidence = next(item for item in snapshot["evidence"] if item["id"] == result["evidenceIds"][0])
    assert evidence["synthetic"] is False and "9/50" in evidence["title"]
    assert snapshot["paymentSandbox"]["running"] is True
    assert client.post("/api/v1/sandbox/payment/workload", json={"incidentId": "INC-1042"}).status_code == 422
    login(client, "Viewer")
    assert client.post("/api/v1/sandbox/payment/start").status_code == 403


def mission_state(client, mission_id):
    return next(item for item in client.get("/api/v1/workspace").json()["missions"] if item["id"] == mission_id)


def decide(client, mission_id, decision="approve"):
    gate = mission_state(client, mission_id)["pendingGate"]
    response = client.post(f"/api/v1/missions/{mission_id}/decision", json={"gateId": gate["id"], "decision": decision})
    assert response.status_code == 200, response.text


def test_mission_applies_approved_fix_and_measures_recovery(app_and_sandbox):
    client, sandbox = app_and_sandbox
    login(client)
    client.post("/api/v1/sandbox/payment/start")
    mission_id = client.post("/api/v1/incidents/INC-1043/missions").json()["missionId"]
    decide(client, mission_id)
    decide(client, mission_id)
    gate = mission_state(client, mission_id)["pendingGate"]
    assert gate["type"] == "fix" and "pool size 20" in gate["detail"]
    assert sandbox.calls == []
    login(client, "Change Approver")
    decide(client, mission_id)
    mission = mission_state(client, mission_id)
    assert sandbox.calls and sandbox.calls[-1][:2] == ("3.8.1", 20)
    outcome = mission["iterations"][-1]["outcome"]
    assert outcome["source"] == "MEASURED" and outcome["resolved"] is True and outcome["measurement"]["errors"] == 0
    assert mission["pendingGate"]["title"] == "Confirm the measured outcome"
    assert any(event["type"] == "sandbox-applied" for event in mission["events"])


def test_demo_reset_restores_stories(app_and_sandbox):
    client, _ = app_and_sandbox
    login(client, "Administrator")
    client.post("/api/v1/incidents/INC-1043/missions")
    assert client.get("/api/v1/workspace").json()["missions"]
    response = client.post("/api/v1/admin/demo-reset")
    assert response.status_code == 200, response.text
    snapshot = client.get("/api/v1/workspace").json()
    assert snapshot["missions"] == [] and len(snapshot["incidents"]) == 13
    login(client, "Incident Manager")
    assert client.post("/api/v1/admin/demo-reset").status_code == 403
