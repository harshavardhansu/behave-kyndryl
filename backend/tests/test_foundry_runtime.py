"""Foundry agents: provisioning, invocation and mission wiring, with a fake Azure project (no network, no cost)."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend import foundry_runtime
from backend.app import create_app
from backend.domain import Settings
from backend.foundry_agents import get_all_agents
from backend.foundry_brain import FoundryBrain
from backend.foundry_runtime import FoundryAgentService, agent_name, foundry_agent_status
from backend.mission import _context
from backend.store import Store

PROJECT = "https://demo.services.ai.azure.com/api/projects/demo-project"


def settings(**extra):
    values = {"AGENTICA_MODE": "demo", "AGENTICA_DEMO_STEP_SECONDS": 0, "AGENTICA_AI_ALLOWED_CLASSIFICATIONS": ["Internal"],
              "azure_ai_project_endpoint": PROJECT, "azure_ai_model_deployment": "gpt-test", "AGENTICA_AI_DAILY_CALL_LIMIT": 100}
    values.update(extra)
    return Settings(**values)


class FakeProject:
    """Stands in for AIProjectClient: records created agents and answers agent calls."""

    def __init__(self, answers=None, fail_create=None):
        self.created, self.gets, self.calls = [], [], []
        self.answers = answers or {}
        self.fail_create = fail_create
        self.deleted: set[str] = set()
        owner = self

        class Agents:
            def create_version(self, agent_name, definition, description=None, metadata=None):
                if owner.fail_create:
                    raise owner.fail_create
                owner.created.append((agent_name, definition.instructions, metadata))
                return SimpleNamespace(version=str(sum(1 for item in owner.created if item[0] == agent_name)), id=f"{agent_name}:v")

            def get(self, name):
                owner.gets.append(name)
                if name in owner.deleted:
                    raise RuntimeError("404 not found")
                return SimpleNamespace(name=name)

        class Responses:
            def create(self, input, extra_body):
                name = extra_body["agent_reference"]["name"]
                owner.calls.append((name, input))
                answer = owner.answers.get(name)
                if isinstance(answer, Exception):
                    raise answer
                return SimpleNamespace(status="completed", output_text="Here you go: " + json.dumps(answer), usage=SimpleNamespace(input_tokens=500, output_tokens=120))

        class OpenAI:
            responses = Responses()

            def with_options(self, **_):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        self.agents = Agents()
        self.get_openai_client = lambda: OpenAI()


@pytest.fixture
def fake_azure(monkeypatch):
    def install(project):
        @contextmanager
        def client(_settings):
            yield project

        monkeypatch.setattr(foundry_runtime, "project_client", client)
        return project

    return install


def service():
    store = Store("sqlite:///:memory:")
    from backend.seed import seed_workspace

    store.initialize(seed_workspace(True))
    return FoundryAgentService(settings(), store), store


def test_provisioning_creates_14_agents_and_is_idempotent(fake_azure):
    project = fake_azure(FakeProject())
    agents, store = service()
    results = agents.provision()
    assert len(results) == 14 and all(item["action"] == "created" for item in results)
    assert {name for name, _, _ in project.created} == {agent_name(agent.role) for agent in get_all_agents()}
    assert all("no tools" in instructions for _, instructions, _ in project.created)
    again = agents.provision()
    assert all(item["action"] == "unchanged" for item in again) and len(project.created) == 14
    project.deleted.add("behave-logs")
    assert next(item for item in agents.provision() if item["role"] == "logs")["action"] == "recreated"
    status = foundry_agent_status(settings(), store)
    assert status["provisioned"] == 14 and status["mode"] == "foundry"


def test_status_is_honest_before_provisioning():
    _, store = service()
    assert foundry_agent_status(settings(), store)["mode"] == "model"
    assert foundry_agent_status(settings(azure_ai_project_endpoint="", azure_ai_model_deployment=""), store)["mode"] == "simulated"
    assert foundry_agent_status(settings(AGENTICA_AGENT_MODE="model"), store)["mode"] == "model"


def test_provisioning_errors_are_friendly(fake_azure):
    fake_azure(FakeProject(fail_create=RuntimeError("403 Forbidden")))
    agents, _ = service()
    with pytest.raises(Exception, match="Azure AI User"):
        agents.provision(["logs"])


def brain_with_agents(fake_azure, answers):
    project = fake_azure(FakeProject(answers))
    store = Store("sqlite:///:memory:")
    application = create_app(settings(), store)
    brain = application.state.mission_brain
    assert isinstance(brain, FoundryBrain)
    brain.agents.provision(["orchestrator", "logs", "observability"])
    return brain, project, _context(store.read(), "INC-1042"), store


def test_work_runs_foundry_agents_in_parallel_and_validates(fake_azure):
    finding = {"summary": "Pool exhausted in checkout logs.", "evidence_ids": ["EVD-301", "EVD-999"], "confidence": 2}
    brain, project, context, store = brain_with_agents(fake_azure, {"behave-logs": finding, "behave-observability": {**finding, "summary": "Saturation in metrics."}})
    members = [{"role": "logs", "name": "Log analysis", "task": "t"}, {"role": "observability", "name": "Observability", "task": "t"}, {"role": "knowledge", "name": "Knowledge", "task": "t"}]
    findings = brain.work(context, "investigate", members, [])
    assert findings["logs"]["evidenceIds"] == ["EVD-301"] and findings["logs"]["confidence"] == 1.0
    assert "Foundry agent behave-logs v1" in findings["logs"]["source"]
    assert findings["observability"]["summary"] == "Saturation in metrics."
    assert findings["knowledge"]["source"].startswith("SIMULATED fallback")  # not provisioned, model unavailable in the fake
    assert {name for name, _ in project.calls} == {"behave-logs", "behave-observability"}
    usage = store.read()["aiUsage"]
    assert usage["calls"] >= 2 and store.read()["foundryAgents"]["logs"]["runs"] == 1
    assert brain.mode.endswith("+ 3 Foundry agents")


def test_agent_failure_or_bad_output_falls_back_with_a_reason(fake_azure):
    brain, _, context, _ = brain_with_agents(fake_azure, {"behave-logs": RuntimeError("401 Unauthorized"), "behave-observability": {"wrong": "shape"}})
    members = [{"role": "logs", "name": "Log analysis", "task": "t"}, {"role": "observability", "name": "Observability", "task": "t"}]
    findings = brain.work(context, "investigate", members, [])
    assert "az login" in findings["logs"]["source"] and findings["logs"]["source"].startswith("SIMULATED fallback")
    assert "wrong format" in findings["observability"]["source"]


def test_orchestrator_agent_plans_and_validates(fake_azure):
    plan = {"analysis": "Pool saturation after the release.", "selected": [{"role": "logs", "reason": "EVD-301", "task": "group timeouts"}, {"role": "logs", "reason": "dup", "task": "dup"}], "skipped": [{"role": "security", "reason": "no signal"}]}
    outcome = {"resolved": False, "detail": "No validation yet.", "recommendation": "resolve", "missing": ["validation", "logs"],
               "validation": {"technical_correctness": True, "completeness": False, "cross_agent_consistency": True, "security_and_risk_acceptable": True, "human_approval_satisfied": True, "summary": "Needs validation."}}
    brain, project, context, _ = brain_with_agents(fake_azure, {"behave-orchestrator": plan})
    result = brain.plan(context, 1, [], [])
    assert result["source"] == "AI-GENERATED / Foundry agent behave-orchestrator v1"
    assert [item["role"] for item in result["selected"]] == ["logs"]
    project.answers["behave-orchestrator"] = outcome
    context["findings"], context["decisions"] = [], []
    evaluated = brain.evaluate(context, ["logs"], 3)
    assert evaluated["recommendation"] == "escalate" and evaluated["missing"] == ["validation"]
    assert "Completeness FAIL" in evaluated["detail"] and evaluated["validationReport"]["completeness"] is False


def test_model_mode_never_uses_agents(fake_azure):
    project = fake_azure(FakeProject())
    store = Store("sqlite:///:memory:")
    application = create_app(settings(AGENTICA_AGENT_MODE="model"), store)
    application.state.mission_brain.agents.provision(["logs"])
    assert application.state.mission_brain.agents.available("logs") is False
    assert project.calls == []


def test_sync_endpoint_requires_admin_and_reports_results(fake_azure):
    fake_azure(FakeProject())
    application = create_app(settings(), Store("sqlite:///:memory:"))
    with TestClient(application) as client:
        client.headers["X-CSRF-Token"] = client.post("/api/v1/auth/demo", json={"role": "Incident Manager"}).json()["csrf"]
        assert client.post("/api/v1/foundry/agents/sync", json={}).status_code == 403
        client.headers["X-CSRF-Token"] = client.post("/api/v1/auth/demo", json={"role": "Administrator"}).json()["csrf"]
        response = client.post("/api/v1/foundry/agents/sync", json={"roles": ["logs"]})
        assert response.status_code == 200 and response.json()["results"][0]["action"] == "created"
        assert client.get("/api/v1/workspace").json()["aiMode"].endswith("+ 1 Foundry agents")


def test_service_principal_credential_is_used_when_configured(monkeypatch):
    from azure.identity import ClientSecretCredential

    from backend.ai_client import entra_credential

    credential = entra_credential(settings(AZURE_TENANT_ID="t", AZURE_CLIENT_ID="c", AZURE_CLIENT_SECRET=SecretStr("not-a-real-secret")))
    assert isinstance(credential, ClientSecretCredential)
    assert not isinstance(entra_credential(settings()), ClientSecretCredential)
