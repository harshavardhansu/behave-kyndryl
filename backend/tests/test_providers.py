from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import create_app
from backend.domain import Settings
from backend.providers import Assessment, Candidate, FoundryProvider, ProviderError, validate_references
from backend.store import Store


def candidate(reference="EVD-301"):
    return Candidate(title="Pool saturation hypothesis", status="Suspected", confidence=.8, supporting_evidence=[reference], contradicting_evidence=[], missing_evidence=["Equivalent-load comparison"], next_experiment="Compare connection acquisition under an isolated bounded workload.")


def test_unknown_evidence_and_unbounded_confidence_are_rejected():
    output = Assessment(summary="Provisional assessment", hypotheses=[candidate("UNKNOWN")], limitations=["No controlled validation"])
    with pytest.raises(ProviderError):
        validate_references(output, [{"id": "EVD-301"}])
    with pytest.raises(ValidationError):
        Candidate(**{**candidate().model_dump(), "confidence": 1.4})


def test_model_cannot_return_execution_authorization_fields():
    with pytest.raises(ValidationError):
        Assessment(summary="Not allowed", hypotheses=[candidate()], limitations=[], approved=True, shell="arbitrary command")


def test_provider_endpoint_is_allowlisted():
    with pytest.raises(ProviderError):
        FoundryProvider(Settings(azure_ai_project_endpoint="http://127.0.0.1:8000/private", azure_ai_model_deployment="configured-model"))


def test_unconfigured_model_fails_explicitly_without_workflow_changes():
    application = create_app(Settings(AGENTICA_MODE="demo", AGENTICA_AI_ALLOWED_CLASSIFICATIONS=["Internal"], azure_ai_project_endpoint="", azure_ai_model_deployment=""), Store("sqlite:///:memory:"))
    with TestClient(application) as client:
        session = client.post("/api/v1/auth/demo", json={"role": "Incident Manager"}).json()
        client.headers["X-CSRF-Token"] = session["csrf"]
        before = client.get("/api/v1/workspace").json()
        response = client.post("/api/v1/incidents/INC-1042/assessment", json={"confirmed": True}, headers={"Idempotency-Key": uuid4().hex})
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"]
        after = client.get("/api/v1/workspace").json()
        assert after["hypotheses"] == before["hypotheses"]
        assert after["incidents"] == before["incidents"]
        assert any(record["action"] == "Model assessment failed" for record in after["audit"])


def test_structured_assessment_adds_findings_but_not_approval():
    class TestProvider:
        def assess(self, incident, evidence):
            return Assessment(summary="Provisional assessment", hypotheses=[candidate()], limitations=["Human review required"])

    application = create_app(Settings(AGENTICA_MODE="demo", AGENTICA_AI_ALLOWED_CLASSIFICATIONS=["Internal"]), Store("sqlite:///:memory:"))
    application.state.provider = TestProvider()
    with TestClient(application) as client:
        session = client.post("/api/v1/auth/demo", json={"role": "Incident Manager"}).json()
        client.headers["X-CSRF-Token"] = session["csrf"]
        before = client.get("/api/v1/workspace").json()
        key = uuid4().hex
        response = client.post("/api/v1/incidents/INC-1042/assessment", json={"confirmed": True}, headers={"Idempotency-Key": key})
        assert response.status_code == 200
        after = client.get("/api/v1/workspace").json()
        assert len(after["hypotheses"]) == len(before["hypotheses"]) + 1
        assert after["approvals"] == before["approvals"]
        assert after["incidents"] == before["incidents"]
        assert client.post("/api/v1/incidents/INC-1042/assessment", json={"confirmed": True}, headers={"Idempotency-Key": key}).status_code == 409


@pytest.mark.parametrize("classification,permitted", [("Internal", []), ("Confidential", ["Internal"]), ("Restricted", ["Public", "Internal", "Confidential"]), ("Unknown", ["Internal"])])
def test_classification_policy_blocks_provider_dispatch(classification, permitted):
    calls = []

    class RecordingProvider:
        def assess(self, incident, evidence):
            calls.append(incident["id"])
            return Assessment(summary="Provisional assessment", hypotheses=[candidate()], limitations=[])

    application = create_app(Settings(AGENTICA_MODE="demo", AGENTICA_AI_ALLOWED_CLASSIFICATIONS=permitted), Store("sqlite:///:memory:"))
    application.state.provider = RecordingProvider()
    with TestClient(application) as client:
        session = client.post("/api/v1/auth/demo", json={"role": "Incident Manager"}).json()
        client.headers["X-CSRF-Token"] = session["csrf"]
        application.state.store.mutate(lambda state: state["evidence"][0].update(dataClassification=classification))
        before = client.get("/api/v1/workspace").json()
        response = client.post("/api/v1/incidents/INC-1042/assessment", json={"confirmed": True}, headers={"Idempotency-Key": uuid4().hex})
        assert response.status_code == 403
        assert calls == []
        after = client.get("/api/v1/workspace").json()
        assert after["hypotheses"] == before["hypotheses"]
        assert after["incidents"] == before["incidents"]
        assert any(event["action"] == "AI data access denied" for event in after["audit"])


def test_direct_foundry_boundary_rejects_restricted_data_without_network_access():
    provider = FoundryProvider(Settings(azure_ai_project_endpoint="https://example.services.ai.azure.com/api/projects/example", azure_ai_model_deployment="test-only", AGENTICA_AI_ALLOWED_CLASSIFICATIONS=["Internal"]))
    with pytest.raises(ProviderError, match="Restricted"):
        provider.assess({"dataClassification": "Restricted"}, [])


def test_restricted_provider_allowlist_cannot_be_enabled_without_controls():
    with pytest.raises(ValidationError):
        Settings(AGENTICA_AI_ALLOWED_CLASSIFICATIONS=["Restricted"])


@pytest.mark.parametrize("invalid_output", [False, True])
def test_provider_failure_is_persisted_and_never_adds_findings(invalid_output):
    class FailingProvider:
        def assess(self, incident, evidence):
            if invalid_output:
                return {"approved": True, "summary": "private output detail"}
            raise RuntimeError("private provider connection detail")

    application = create_app(Settings(AGENTICA_MODE="demo", AGENTICA_AI_ALLOWED_CLASSIFICATIONS=["Internal"]), Store("sqlite:///:memory:"))
    application.state.provider = FailingProvider()
    with TestClient(application) as client:
        session = client.post("/api/v1/auth/demo", json={"role": "Incident Manager"}).json()
        client.headers["X-CSRF-Token"] = session["csrf"]
        before = application.state.store.read()
        response = client.post("/api/v1/incidents/INC-1042/assessment", json={"confirmed": True}, headers={"Idempotency-Key": uuid4().hex})
        assert response.status_code == 503
        assert "private" not in response.text
        after = application.state.store.read()
        execution = next(iter(after["modelRequests"].values()))
        assert execution["status"] == "Failed"
        assert execution["executionId"].startswith("EXE-")
        assert execution["failureId"].startswith("FAIL-")
        assert execution["errorCategory"] == ("INVALID_OUTPUT" if invalid_output else "PROVIDER_FAILURE")
        assert after["hypotheses"] == before["hypotheses"]
        assert after["approvals"] == before["approvals"]


def test_interrupted_model_request_requires_review_without_reexecution():
    application = create_app(Settings(AGENTICA_MODE="demo"), Store("sqlite:///:memory:"))
    application.state.store.mutate(lambda state: state.update(modelRequests={"original-key": {"executionId": "EXE-ORIGINAL", "status": "Running", "incidentId": "INC-1042"}}))
    with TestClient(application):
        execution = application.state.store.read()["modelRequests"]["original-key"]
        assert execution["executionId"] == "EXE-ORIGINAL"
        assert execution["status"] == "MANUAL_INTERVENTION_REQUIRED"
        assert execution["errorCategory"] == "INTERRUPTED_PROVIDER_REQUEST"


def test_configured_provider_without_data_policy_is_not_advertised_as_ready():
    settings = Settings(AGENTICA_MODE="demo", azure_ai_project_endpoint="https://example.services.ai.azure.com/api/projects/example", azure_ai_model_deployment="test-only", AGENTICA_AI_ALLOWED_CLASSIFICATIONS=[])
    application = create_app(settings, Store("sqlite:///:memory:"))
    with TestClient(application) as client:
        client.post("/api/v1/auth/demo", json={"role": "Incident Manager"})
        integration = next(record for record in client.get("/api/v1/workspace").json()["integrations"] if record["id"] == "foundry")
        assert integration["status"] == "Blocked by data policy"
        assert integration["dataPolicy"]["restrictedDataAllowed"] is False
        assert "AGENTICA_AI_ALLOWED_CLASSIFICATIONS" in integration["required"]