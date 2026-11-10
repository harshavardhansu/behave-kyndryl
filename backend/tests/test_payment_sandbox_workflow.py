from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.domain import Settings
from backend.store import Store


class SandboxControl:
    def __init__(self):
        self.calls = []
        self.result_status = "SUCCEEDED"

    def apply_configuration(self, release, pool_size, actor_id="system"):
        self.calls.append((release, pool_size, actor_id))
        return {
            "status": self.result_status,
            "active_config": {"service": "payment-api", "release": release, "pool_size": pool_size},
            "error": "Sandbox state requires manual inspection." if self.result_status != "SUCCEEDED" else "",
        }


@pytest.fixture

def payment_client():
    control = SandboxControl()
    store = Store("sqlite:///:memory:")
    application = create_app(
        Settings(mode="demo", demo_step_seconds=0, max_upload_bytes=2_097_152, allowed_origins="http://127.0.0.1:5173,http://localhost:5173", auth_audience=""),
        store,
        control,
    )
    with TestClient(application) as client:
        login = client.post("/api/v1/auth/demo", json={"role": "Incident Manager"}).json()
        client.headers["X-CSRF-Token"] = login["csrf"]
        yield client, control


def action(client, incident_id, name, **details):
    return client.post(
        f"/api/v1/incidents/{incident_id}/actions",
        json={"action": name, **details},
        headers={"Idempotency-Key": uuid4().hex},
    )


def prepare_payment_approval(client):
    created = client.post(
        "/api/v1/incidents",
        json={
            "title": "Synthetic Payment API sandbox incident fixture",
            "description": "Test fixture representing a Payment API summary timeout under concurrent sandbox workload.",
            "severity": "High",
            "environment": "Sandbox",
            "service": "payment-api",
            "impact": "Synthetic workflow-test evidence only; no live workload is executed.",
            "detectedAt": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert created.status_code == 201
    incident_id = created.json()["id"]
    evidence = client.post(
        f"/api/v1/incidents/{incident_id}/evidence",
        json={
            "title": "Synthetic pool exhaustion evidence fixture",
            "excerpt": "TEST FIXTURE: represents database acquisition timeouts; no live workload was executed.",
            "source": "sandbox workflow integration test fixture",
            "type": "Metric",
            "classification": "Observed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert evidence.status_code == 201

    def prepare(state):
        incident = next(item for item in state["incidents"] if item["id"] == incident_id)
        incident["status"] = "Testing"
        change = next(item for item in state["changes"] if item["incidentId"] == incident_id)
        state["tests"].append({
            "id": f"TEST-{uuid4().hex[:8]}",
            "incidentId": incident_id,
            "status": "Passed",
            "passed": 1,
            "failed": 0,
            "commit": change["commit"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "synthetic": True,
            "source": "TEST FIXTURE: no workload was executed",
        })

    client.app.state.store.mutate(prepare)
    requested = action(client, incident_id, "request-approval")
    assert requested.status_code == 200
    approver = client.post("/api/v1/auth/demo", json={"role": "Change Approver"}).json()
    client.headers["X-CSRF-Token"] = approver["csrf"]
    approved = action(client, incident_id, "approve", confirmation="APPROVE")
    assert approved.status_code == 200
    operator = client.post("/api/v1/auth/demo", json={"role": "Incident Manager"}).json()
    client.headers["X-CSRF-Token"] = operator["csrf"]
    return incident_id


def test_sandbox_deploy_and_rollback_call_adapter_and_record_verified_results(payment_client):
    client, control = payment_client
    incident_id = prepare_payment_approval(client)

    deployed = action(client, incident_id, "deploy", confirmation="Sandbox")

    assert deployed.status_code == 200
    assert control.calls == [("3.8.1", 20, "alex-morgan")]
    state = client.get("/api/v1/workspace").json()
    operation = next(item for item in state["sandboxOperations"] if item["incidentId"] == incident_id)
    assert operation["status"] == "SUCCEEDED"
    assert next(item for item in state["incidents"] if item["id"] == incident_id)["status"] == "Monitoring"
    assert any(item["action"] == "Payment sandbox deploy" and item["outcome"] == "SUCCEEDED" for item in state["audit"])

    rolled_back = action(client, incident_id, "rollback", confirmation="Sandbox", reason="Restore the previous release for comparison.")

    assert rolled_back.status_code == 200
    assert control.calls[-1] == ("previous", 20, "alex-morgan")
    assert next(item for item in client.get("/api/v1/workspace").json()["incidents"] if item["id"] == incident_id)["status"] == "Reopened"


def test_changed_sandbox_payload_cannot_use_existing_approval(payment_client):
    client, control = payment_client
    incident_id = prepare_payment_approval(client)
    client.app.state.store.mutate(
        lambda state: next(item for item in state["changes"] if item["incidentId"] == incident_id)["sandboxAction"].update(pool_size=5)
    )

    response = action(client, incident_id, "deploy", confirmation="Sandbox")

    assert response.status_code == 409
    assert control.calls == []


def test_unverified_sandbox_operation_does_not_claim_success(payment_client):
    client, control = payment_client
    control.result_status = "MANUAL_INTERVENTION_REQUIRED"
    incident_id = prepare_payment_approval(client)

    response = action(client, incident_id, "deploy", confirmation="Sandbox")

    assert response.status_code == 503
    state = client.get("/api/v1/workspace").json()
    operation = next(item for item in state["sandboxOperations"] if item["incidentId"] == incident_id)
    assert operation["status"] == "MANUAL_INTERVENTION_REQUIRED"
    assert next(item for item in state["incidents"] if item["id"] == incident_id)["status"] == "Deploying"


def test_payment_api_service_is_restricted_to_sandbox_environment(payment_client):
    client, _ = payment_client
    payload = {
        "title": "Payment incident outside sandbox",
        "description": "This request must not target the real Payment API service by mistake.",
        "severity": "High",
        "environment": "Production",
        "service": "payment-api",
        "impact": "No production service may be changed by this sandbox workflow.",
        "detectedAt": datetime.now(timezone.utc).isoformat(),
    }

    assert client.post("/api/v1/incidents", json=payload).status_code == 422
    payload["environment"] = "Sandbox"
    payload["service"] = "checkout-svc"
    assert client.post("/api/v1/incidents", json=payload).status_code == 422
