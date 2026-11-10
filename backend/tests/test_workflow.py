import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import get_args
from unittest.mock import Mock
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend.app import create_app
from backend.domain import ActionInput, Settings
from backend.seed import AGENT_ROLES
from backend.store import Store
from backend.workflow import ACTION_PERMISSIONS


@pytest.fixture
def client():
    store = Store("sqlite:///:memory:")
    application = create_app(Settings(AGENTICA_MODE="demo", AGENTICA_DEMO_STEP_SECONDS=0), store)
    with TestClient(application) as test_client:
        yield test_client


def login(client, role="Incident Manager"):
    response = client.post("/api/v1/auth/demo", json={"role": role})
    assert response.status_code == 200
    client.headers["X-CSRF-Token"] = response.json()["csrf"]


def action(client, name, incident="INC-1042", **extra):
    return client.post(f"/api/v1/incidents/{incident}/actions", json={"action": name, **extra}, headers={"Idempotency-Key": uuid4().hex})


def prepare_approval(client):
    assert action(client, "start-investigation").status_code == 200
    assert action(client, "run-validation").status_code == 200
    assert action(client, "request-approval").status_code == 200


def test_anonymous_and_viewer_writes_rejected(client):
    assert client.get("/api/v1/workspace").status_code == 401
    login(client, "Viewer")
    assert client.get("/api/v1/workspace").status_code == 200
    assert action(client, "start-investigation").status_code == 403


def test_csrf_and_cross_origin_enforced(client):
    login(client)
    client.headers.pop("X-CSRF-Token")
    assert action(client, "start-investigation").status_code == 403
    response = client.post("/api/v1/auth/demo", json={"role": "Administrator"}, headers={"Origin": "https://untrusted.example"})
    assert response.status_code == 403


def test_environment_permissions_are_not_ui_only(client):
    login(client, "Developer")
    assert action(client, "start-investigation").status_code == 403


def test_validation_and_approval_are_required(client):
    login(client)
    assert action(client, "request-approval").status_code == 409
    assert action(client, "deploy", confirmation="Production").status_code == 409
    assert action(client, "close", reason="The incident appears resolved.").status_code == 409


def test_full_governed_checkout_workflow(client):
    login(client)
    prepare_approval(client)
    assert action(client, "approve", confirmation="APPROVE").status_code == 403
    login(client, "Change Approver")
    assert action(client, "approve", confirmation="APPROVE").status_code == 200
    assert action(client, "deploy", confirmation="Production").status_code == 403
    login(client)
    assert action(client, "deploy", confirmation="Staging").status_code == 422
    assert action(client, "deploy", confirmation="Production").status_code == 200
    assert action(client, "close", reason="Checkout recovery verified.").status_code == 409
    assert action(client, "verify").status_code == 200
    assert action(client, "close", reason="Synthetic recovery verified against the defined error and latency budgets.").status_code == 200
    state = client.get("/api/v1/workspace").json()
    incident = next(record for record in state["incidents"] if record["id"] == "INC-1042")
    assert incident["status"] == "Closed"
    assert incident["recovery"]["synthetic"] is True
    assert any(record["action"] == "close" for record in state["audit"])
    assert any(record["type"] == "Incident report" and not record["approved"] for record in state["knowledge"])


def test_no_self_approval_even_for_admin(client):
    login(client, "Administrator")
    prepare_approval(client)
    assert action(client, "approve", confirmation="APPROVE").status_code == 403


def test_display_name_changes_do_not_bypass_separation_of_duties(client):
    login(client, "Administrator")
    prepare_approval(client)

    def rename_display_only(state):
        approval = next(record for record in state["approvals"] if record["incidentId"] == "INC-1042")
        assert approval["requestedById"] == "taylor-chen"
        approval["requestedBy"] = "Previous display name"

    client.app.state.store.mutate(rename_display_only)
    assert action(client, "approve", confirmation="APPROVE").status_code == 403


def test_rejection_has_visible_consequences(client):
    login(client)
    prepare_approval(client)
    login(client, "Change Approver")
    assert action(client, "reject", reason="Need a longer performance validation window.").status_code == 200
    state = client.get("/api/v1/workspace").json()
    assert next(item for item in state["incidents"] if item["id"] == "INC-1042")["status"] == "Fix Proposed"
    assert any(item["status"] == "Rejected" and item["incidentId"] == "INC-1042" for item in state["approvals"])


def test_idempotency_deduplicates_writes(client):
    login(client)
    headers = {"Idempotency-Key": uuid4().hex}
    payload = {"action": "assign", "owner": "James Wilson"}
    first = client.post("/api/v1/incidents/INC-1042/actions", json=payload, headers=headers)
    second = client.post("/api/v1/incidents/INC-1042/actions", json=payload, headers=headers)
    assert first.json() == second.json()
    state = client.get("/api/v1/workspace").json()
    assert len([item for item in state["audit"] if item["action"] == "assign"]) == 1
    payload["owner"] = "Alex Morgan"
    assert client.post("/api/v1/incidents/INC-1042/actions", json=payload, headers=headers).status_code == 409


def test_upload_validation_redaction_and_timestamp_preservation(client):
    login(client)
    endpoint = "/api/v1/incidents/INC-1042/evidence/upload"
    assert client.post(endpoint, files={"file": ("../escape.txt", b"anything")}).status_code == 422
    assert client.post(endpoint, files={"file": ("project.zip", b"PK00")}).status_code == 415
    assert client.post(endpoint, files={"file": ("bad.json", b"{invalid")}).status_code == 422
    response = client.post(endpoint, files={"file": ("observed.json", b'{"timestamp":"2026-01-02T03:04:05+05:30","message":"password=never-show-this","level":"ERROR"}')})
    assert response.status_code == 201
    assert "never-show-this" not in response.text
    state = client.get("/api/v1/workspace").json()
    imported = next(item for item in state["logs"] if item["source"] == "upload:observed.json")
    assert imported["timestamp"] == "2026-01-02T03:04:05+05:30"


def test_failed_manual_validation_blocks_promotion(client):
    login(client)
    assert action(client, "start-investigation").status_code == 200
    state = client.get("/api/v1/workspace").json()
    change = next(item for item in state["changes"] if item["incidentId"] == "INC-1042")
    response = client.post("/api/v1/incidents/INC-1042/tests", json={"suite": "Recorded regression", "commit": change["commit"], "passed": 10, "failed": 1, "duration": 4, "source": "Local test report ref TEST-1"})
    assert response.status_code == 201
    assert action(client, "request-approval").status_code == 409


def test_critical_security_gate_cannot_be_bypassed(client):
    login(client)
    assert action(client, "start-investigation").status_code == 200
    assert action(client, "run-validation").status_code == 200
    client.app.state.store.mutate(lambda state: state["security"].append({"id": "SEC-BLOCK", "incidentId": "INC-1042", "severity": "Critical", "status": "Open"}))
    assert action(client, "request-approval").status_code == 409


def test_live_mode_cannot_open_demo_database(client):
    with pytest.raises(RuntimeError):
        create_app(Settings(AGENTICA_MODE="production", azure_tenant_id="tenant", AGENTICA_AUTH_AUDIENCE="audience"), client.app.state.store)


def test_database_readiness_reports_failure_and_recovery(client, monkeypatch):
    assert client.get("/api/v1/health").status_code == 200
    with monkeypatch.context() as patch:
        def unavailable(*args, **kwargs):
            raise OperationalError("SELECT", {}, Exception("private database connection detail"))

        patch.setattr(client.app.state.store.engine, "connect", unavailable)
        response = client.get("/api/v1/health")
        assert response.status_code == 503
        assert response.json()["database"] == "UNAVAILABLE"
        assert "private database connection detail" not in response.text
    assert client.get("/api/v1/health").json()["database"] == "AVAILABLE"


def test_production_sqlite_is_rejected_before_initialization(monkeypatch):
    store = Store("sqlite:///:memory:")
    initialized = []
    monkeypatch.setattr(store, "initialize", lambda state: initialized.append(state))
    settings = Settings(AGENTICA_MODE="production", database_url="sqlite:///:memory:", azure_tenant_id="tenant", AGENTICA_AUTH_AUDIENCE="audience")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        create_app(settings, store)
    assert initialized == []


def test_rollback_requires_deployed_change_and_invalidates_approval(client):
    login(client)
    assert action(client, "rollback", confirmation="Production", reason="The rollout did not meet recovery criteria.").status_code == 409
    prepare_approval(client)
    login(client, "Change Approver")
    assert action(client, "approve", confirmation="APPROVE").status_code == 200
    login(client)
    assert action(client, "deploy", confirmation="Production").status_code == 200
    assert action(client, "rollback", confirmation="Staging", reason="The rollout did not meet recovery criteria.").status_code == 422
    assert action(client, "rollback", confirmation="Production", reason="The rollout did not meet recovery criteria.").status_code == 200
    state = client.get("/api/v1/workspace").json()
    assert next(item for item in state["changes"] if item["id"] == "CHG-2084")["approvalId"] is None
    assert next(item for item in state["incidents"] if item["id"] == "INC-1042")["status"] == "Reopened"


def test_repository_replay_is_explicit_and_never_fetches_urls(client):
    login(client)
    payload = {"source": "repository", "url": "https://example.invalid/private/repo", "scope": ["Configuration", "Tests"], "permissionConfirmed": True}
    assert client.post("/api/v1/repositories/analyses", json=payload).status_code == 503
    payload["source"] = "fixture"
    response = client.post("/api/v1/repositories/analyses", json=payload)
    assert response.status_code == 201
    assert len(response.json()["findings"]) == 2
    assert "No repository URL was accessed" in response.json()["limitations"]
    payload["permissionConfirmed"] = False
    assert client.post("/api/v1/repositories/analyses", json=payload).status_code == 422


def test_knowledge_requires_independent_review_and_verified_resolution(client):
    login(client)
    response = client.post("/api/v1/knowledge", json={"title": "Connection pool operating guide", "type": "Runbook", "body": "Review the aggregate connection budget across replicas before changing the pool configuration.", "services": ["checkout-svc"], "incidents": ["INC-1042"]})
    assert response.status_code == 201
    assert response.json()["approved"] is False
    record_id = response.json()["id"]
    assert client.post(f"/api/v1/knowledge/{record_id}/review", json={"decision": "approve", "reason": "Reviewed against the operating policy."}).status_code == 403
    login(client, "Administrator")
    assert client.post(f"/api/v1/knowledge/{record_id}/review", json={"decision": "approve", "reason": "Reviewed against the operating policy."}).status_code == 200
    assert client.get("/api/v1/admin/access").status_code == 200
    login(client, "Viewer")
    assert client.get("/api/v1/admin/access").status_code == 403


def test_evidence_sensitivity_and_provenance_are_preserved(client):
    login(client)
    content = b'{"message":"password=do-not-retain"}'
    response = client.post("/api/v1/incidents/INC-1042/evidence/upload", data={"dataClassification": "Restricted"}, files={"file": ("evidence.json", content, "application/json")})
    assert response.status_code == 201
    record = response.json()
    assert record["dataClassification"] == "Restricted"
    assert record["classification"] == "Unverified"
    assert record["sizeBytes"] == len(content)
    assert record["sha256"] == hashlib.sha256(content).hexdigest()
    assert record["derivativeSha256"] == hashlib.sha256(record["excerpt"].encode()).hexdigest()
    assert record["collectedById"] == "alex-morgan"
    assert record["originalRetained"] is False
    assert record["malwareScanStatus"] == "NOT CONFIGURED"
    assert "do-not-retain" not in response.text
    assert "do-not-retain" not in client.get("/api/v1/workspace").text


def test_manual_evidence_cannot_downgrade_incident_sensitivity(client):
    login(client)
    client.app.state.store.mutate(lambda state: next(record for record in state["incidents"] if record["id"] == "INC-1042").update(dataClassification="Confidential"))
    response = client.post("/api/v1/incidents/INC-1042/evidence", json={"title": "Manual diagnostic observation", "excerpt": "Connection acquisition exceeded the configured budget.", "source": "Operator observation", "classification": "Observed", "dataClassification": "Public", "timestamp": "2026-01-02T03:04:05Z"})
    assert response.status_code == 201
    assert response.json()["dataClassification"] == "Confidential"
    assert response.json()["hashScope"] == "validated-input-record"


def test_evidence_mime_mismatch_is_rejected(client):
    login(client)
    response = client.post("/api/v1/incidents/INC-1042/evidence/upload", files={"file": ("evidence.txt", b"A valid text observation", "text/html")})
    assert response.status_code == 415


def test_linked_incident_environment_cannot_be_bypassed(client):
    login(client)
    assert action(client, "start-investigation").status_code == 200
    login(client, "QA Engineer")
    response = client.post("/api/v1/incidents/INC-1042/tests", json={"suite": "Recorded regression", "commit": "test-commit", "passed": 10, "failed": 0, "duration": 4, "source": "Local test report ref TEST-1"})
    assert response.status_code == 403
    login(client, "Developer")
    response = client.post("/api/v1/repositories/analyses", json={"source": "fixture", "environment": "Staging", "scope": ["Configuration"], "permissionConfirmed": True, "incidentId": "INC-1042"})
    assert response.status_code == 403
    login(client)
    response = client.post("/api/v1/repositories/analyses", json={"source": "fixture", "scope": ["Configuration"], "permissionConfirmed": True, "incidentId": "INC-1041"})
    assert response.status_code == 409


def test_failed_database_write_rolls_back_without_success(client, monkeypatch):
    login(client)
    store = client.app.state.store
    before = store.read()
    original_write = store._write
    with monkeypatch.context() as patch:
        def fail_write(session, state):
            original_write(session, state)
            session.flush()
            raise OperationalError("UPDATE", {}, Exception("private database detail"))

        patch.setattr(store, "_write", fail_write)
        response = action(client, "assign", owner="New test commander")
        assert response.status_code == 503
        assert "private database detail" not in response.text
    after = store.read()
    assert after["incidents"] == before["incidents"]
    assert after["audit"] == before["audit"]


@pytest.mark.parametrize("roles,tenant,expected", [([], "test-tenant", 403), (["UnassignedRole"], "test-tenant", 403), (["Viewer"], "other-tenant", 401), (["Viewer"], "test-tenant", 200)])
def test_entra_requires_assigned_role_and_matching_tenant(monkeypatch, roles, tenant, expected):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_client = Mock()
    key_client.get_signing_key_from_jwt.return_value = SimpleNamespace(key=private_key.public_key())
    monkeypatch.setattr(jwt, "PyJWKClient", lambda *args, **kwargs: key_client)
    store = Mock()
    store.engine.dialect.name = "postgresql"
    store.read.return_value = {"mode": "production"}
    settings = Settings(AGENTICA_MODE="production", database_url="postgresql+psycopg://test.invalid/not-connected", azure_tenant_id="test-tenant", AGENTICA_AUTH_AUDIENCE="test-audience", azure_ai_project_endpoint="", azure_ai_model_deployment="")
    application = create_app(settings, store)
    timestamp = datetime.now(timezone.utc)
    token = jwt.encode({"exp": timestamp + timedelta(minutes=5), "iat": timestamp, "aud": "test-audience", "iss": "https://login.microsoftonline.com/test-tenant/v2.0", "oid": "test-object", "tid": tenant, "roles": roles}, private_key, algorithm="RS256")
    with TestClient(application) as production_client:
        response = production_client.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == expected
        if expected == 200:
            assert response.json()["user"]["role"] == "Viewer"


def test_original_agent_and_action_contracts_are_preserved():
    assert {role[0] for role in AGENT_ROLES} == {"orchestrator", "intake", "logs", "observability", "repository", "knowledge", "root-cause", "remediation", "testing", "security", "validation", "risk", "release", "summary"}
    assert len(AGENT_ROLES) == 14
    actions = {"start-investigation", "pause", "resume", "cancel", "retry", "generate-fix", "run-validation", "request-approval", "approve", "reject", "deploy", "rollback", "verify", "close", "reopen", "assign", "escalate"}
    assert set(get_args(ActionInput.model_fields["action"].annotation)) == actions
    assert set(ACTION_PERMISSIONS) == actions