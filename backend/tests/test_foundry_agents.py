"""Comprehensive test suite for the 14-Agent Azure AI Foundry & OpenAI Architecture."""

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.domain import Settings
from backend.foundry_agents import (
    AGENTS_CATALOG,
    export_agent_manifests,
    get_agent,
    get_all_agents,
)
from backend.foundry_brain import FoundryBrain
from backend.orchestrator_brain import OrchestratorBrain
from backend.store import Store


@pytest.fixture
def test_app():
    store = Store("sqlite:///:memory:")
    settings = Settings(
        AGENTICA_MODE="demo",
        AGENTICA_DEMO_STEP_SECONDS=0,
        AGENTICA_AI_ALLOWED_CLASSIFICATIONS=["Internal", "Public"],
        azure_ai_model_deployment="gpt-4.1-mini",
        azure_ai_project_endpoint="https://odl-user-2443936-1468-resource.services.ai.azure.com/api/projects/odl-user-2443936-1468",
    )
    return create_app(settings, store), store


def test_all_14_agents_defined_and_configured():
    """Verify all 14 specialized agents are defined with complete specifications."""
    agents = get_all_agents()
    assert len(agents) == 14

    expected_roles = [
        "orchestrator", "intake", "logs", "observability", "repository",
        "knowledge", "root-cause", "remediation", "testing", "security",
        "validation", "risk", "release", "summary",
    ]
    assert [a.role for a in agents] == expected_roles

    for agent in agents:
        assert agent.name, f"Agent {agent.role} missing name"
        assert agent.description, f"Agent {agent.role} missing description"
        assert agent.objective, f"Agent {agent.role} missing objective"
        assert agent.system_prompt, f"Agent {agent.role} missing system prompt"
        assert len(agent.system_prompt) > 100, f"System prompt for {agent.role} is too brief"
        assert agent.execution_boundaries, f"Agent {agent.role} missing boundaries"
        assert len(agent.tools) > 0, f"Agent {agent.role} missing tools"
        assert agent.foundry_agent_id.startswith("asst_foundry_")


def test_human_approval_gate_requirements():
    """Verify that sensitive actions require human approval flags."""
    root_cause = get_agent("root-cause")
    remediation = get_agent("remediation")
    release = get_agent("release")
    orchestrator = get_agent("orchestrator")

    assert root_cause.human_approval_required is True
    assert remediation.human_approval_required is True
    assert release.human_approval_required is True
    assert orchestrator.human_approval_required is True

    # Read-only investigative agents should not require human approval
    logs = get_agent("logs")
    observability = get_agent("observability")
    assert logs.human_approval_required is False
    assert observability.human_approval_required is False


def test_export_agent_manifests():
    """Verify agent manifests export properly for Azure AI Foundry Project registration."""
    manifests = export_agent_manifests()
    assert len(manifests) == 14
    for item in manifests:
        assert "id" in item
        assert "role" in item
        assert "system_prompt" in item
        assert "tools" in item


def test_foundry_agents_api_endpoint(test_app):
    """Test the GET /api/v1/foundry/agents endpoint returns all 14 agents."""
    app, _ = test_app
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/demo", json={"role": "Incident Manager"})
        client.headers["X-CSRF-Token"] = login.json()["csrf"]

        res = client.get("/api/v1/foundry/agents")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 14
        assert len(data["agents"]) == 14
        assert data["centralBrain"] == "OpenAI Central Intelligence"
        assert "projectEndpoint" in data


def test_orchestrator_brain_fallback_and_structure(test_app):
    """Test that OrchestratorBrain handles plan, work, and evaluate cleanly."""
    _, store = test_app
    settings = Settings(
        AGENTICA_MODE="demo",
        AGENTICA_AI_ALLOWED_CLASSIFICATIONS=["Internal"],
    )
    brain = OrchestratorBrain(settings, store)
    context = {
        "incident": {
            "id": "INC-1042",
            "title": "Checkout failure",
            "severity": "Critical",
            "service": "checkout-svc",
            "environment": "Production",
            "description": "DB connection timeout",
            "impact": "Customer checkouts failing",
            "error": "HikariPool timeout",
        },
        "evidence": [
            {"id": "EVD-301", "type": "Log", "title": "Timeout", "excerpt": "Timeout error"},
            {"id": "EVD-302", "type": "Metric", "title": "Saturation", "excerpt": "Pool full"},
        ],
        "hypotheses": [],
        "findings": [],
        "decisions": [],
    }

    # Test Plan
    plan = brain.plan(context, 1, [], [])
    assert "selected" in plan
    assert "skipped" in plan
    assert len(plan["selected"]) > 0

    # Test Work
    members = [{"role": "logs", "name": "Log analysis", "task": "Analyze logs", "findings": None}]
    findings = brain.work(context, "investigate", members, [])
    assert "logs" in findings
    assert "summary" in findings["logs"]

    # Test Evaluate (Central OpenAI Final Validation)
    outcome = brain.evaluate(context, ["logs", "root-cause", "remediation", "validation"], 1)
    assert "resolved" in outcome
    assert "recommendation" in outcome
    assert outcome["recommendation"] in {"resolve", "iterate", "escalate"}
