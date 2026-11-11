import pytest
from pydantic import ValidationError

from backend.domain import IncidentInput, PolicyInput, persona, redact
from backend.seed import seed_workspace
from backend.store import Store


def test_fixture_references_and_topology():
    state = seed_workspace()
    incidents = {record["id"] for record in state["incidents"]}
    services = {record["id"] for record in state["services"]}
    evidence = {record["id"] for record in state["evidence"]}
    assert len(services) == 16  # 15 production services + the local Payment API sandbox
    assert all(any(item["incidentId"] == incident for item in state["evidence"]) for incident in incidents), "every demo incident needs evidence"
    for hypothesis in state["hypotheses"]:
        assert set(hypothesis["supports"]) | set(hypothesis["contradicts"]) <= evidence
    assert len(evidence) == len(state["evidence"]), "evidence IDs must be unique"
    for edge in state["dependencies"]:
        assert edge["source"] in services and edge["target"] in services
        assert 0 <= edge["strength"] <= 1
        assert set(edge["evidence"]) <= evidence
    for collection in ("evidence", "hypotheses", "agents", "tests", "changes", "approvals"):
        assert all(record["incidentId"] in incidents for record in state[collection])


def test_persistence_and_atomic_rollback():
    store = Store("sqlite:///:memory:")
    store.initialize(seed_workspace())
    store.mutate(lambda state: state["incidents"][0].update(owner="Test owner"))
    assert store.read()["incidents"][0]["owner"] == "Test owner"

    def invalid_update(state):
        state["incidents"][0]["owner"] = "Must not persist"
        raise ValueError("Rejected")

    with pytest.raises(ValueError):
        store.mutate(invalid_update)
    assert store.read()["incidents"][0]["owner"] == "Test owner"


def test_secrets_are_redacted_recursively():
    original = {"access_token": "secret-value", "items": ["password=never-show-this", "Authorization: Bearer abc.xyz.123"], "url": "https://user:pass@example.com"}
    result = str(redact(original))
    assert "secret-value" not in result and "never-show-this" not in result
    assert "abc.xyz.123" not in result and "user:pass" not in result


def test_mandatory_approval_policy_cannot_be_disabled():
    with pytest.raises(ValidationError):
        PolicyInput(productionApprovalRequired=False)
    assert "approval:decide" not in persona("Incident Manager")["permissions"]
    assert "Production" not in persona("Developer")["environments"]


def test_incident_rejects_missing_timezone_and_unknown_fields():
    record = {"title": "Checkout failure", "description": "A sufficiently detailed issue report.", "impact": "Orders are blocked", "severity": "Critical", "environment": "Production", "service": "checkout-svc", "detectedAt": "2026-01-01T10:00:00"}
    with pytest.raises(ValidationError):
        IncidentInput(**record)
    record["detectedAt"] += "Z"
    assert IncidentInput(**record).service == "checkout-svc"
    with pytest.raises(ValidationError):
        IncidentInput(**record, unrestrictedShell=True)