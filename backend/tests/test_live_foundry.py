"""LIVE test: runs one real mission against your real Azure AI Foundry agents.

Skipped unless you ask for it (it makes real, billable calls: roughly 20 calls, a few cents):

    RUN_LIVE_FOUNDRY=1 .venv/bin/python -m pytest backend/tests/test_live_foundry.py -s

Needs: the 14 agents created (python -m backend.foundry_provision) and a Microsoft Entra sign-in
(python -m backend.azure_login). It uses an in-memory database, so it never touches your data, and it
fails loudly if any agent silently fell back to the model or the simulated planner.
"""

import os

import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.domain import Settings
from backend.store import Store
from backend.tests.test_missions import decide, login, mission, start

pytestmark = pytest.mark.skipif(os.getenv("RUN_LIVE_FOUNDRY") != "1", reason="live Azure test: set RUN_LIVE_FOUNDRY=1 to run it")


def live_settings() -> Settings:
    env = dotenv_values(".env")
    return Settings(
        AGENTICA_MODE="demo", AGENTICA_DEMO_STEP_SECONDS=0, AGENTICA_AI_ALLOWED_CLASSIFICATIONS=["Internal"], AGENTICA_AI_DAILY_CALL_LIMIT=80,
        azure_ai_project_endpoint=env.get("AZURE_AI_PROJECT_ENDPOINT", ""), azure_ai_model_deployment=env.get("AZURE_AI_MODEL_DEPLOYMENT", ""),
        azure_tenant_id=env.get("AZURE_TENANT_ID", ""),
    )


@pytest.fixture
def live_client():
    config = live_settings()
    assert config.azure_ai_project_endpoint, "AZURE_AI_PROJECT_ENDPOINT is not set in .env"
    registry = Store(Settings().database_url).read().get("foundryAgents") or {}
    assert len(registry) == 14, "Provision the 14 agents first: python -m backend.foundry_provision"
    store = Store("sqlite:///:memory:")
    application = create_app(config, store)
    store.mutate(lambda state: state.__setitem__("foundryAgents", registry))
    with TestClient(application) as client:
        yield client


def test_one_real_mission_runs_on_foundry_agents_with_tools_and_a_report(live_client):
    client = live_client
    login(client)
    mission_id = start(client, "INC-1042")
    plan = mission(client, mission_id)["iterations"][0]["plan"]
    assert plan["source"].startswith("AI-GENERATED / Foundry agent behave-orchestrator"), plan["source"]

    assert decide(client, mission_id, "approve").status_code == 200  # team
    record = mission(client, mission_id)
    assert record["pendingGate"]["type"] == "root-cause", record["status"]
    assert decide(client, mission_id, "approve").status_code == 200  # root cause
    assert mission(client, mission_id)["pendingGate"]["type"] == "fix"
    login(client, "Change Approver")  # a different person approves the fix
    assert decide(client, mission_id, "approve").status_code == 200
    login(client)

    record = mission(client, mission_id)
    assert record["status"] == "Awaiting resolution review"
    members = [m for it in record["iterations"] for m in it["team"] if m.get("findings")]
    assert members, "no agent produced a finding"
    for member in members:
        finding = member["findings"]
        assert finding["source"].startswith("AI-GENERATED / Foundry agent"), f"{member['role']} did not run as a Foundry agent: {finding['source']}"
        assert finding.get("toolCalls"), f"{member['role']} did not use any read-only tool"
        assert finding["summary"] and 0 <= finding["confidence"] <= 1
    assert not [e for e in record["events"] if e["type"] == "ai-fallback"], "an AI step silently fell back to the simulated planner"
    outcome = record["iterations"][-1]["outcome"]
    assert outcome["source"].startswith("AI-GENERATED / Foundry agent behave-orchestrator") and outcome.get("validationReport")

    pdf = client.get("/api/v1/incidents/INC-1042/resolution-report/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and len(pdf.content) > 6000
