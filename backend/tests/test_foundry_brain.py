"""Foundry brain tests with a fake Azure client: no network, no cost."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend import foundry_brain
from backend.app import create_app
from backend.domain import Settings
from backend.foundry_brain import FoundryBrain, Outcome, StepFindings, TeamPlan
from backend.mission import SPECIALISTS, _context
from backend.store import Store


def settings(**extra):
    values = {
        "AGENTICA_MODE": "demo",
        "AGENTICA_DEMO_STEP_SECONDS": 0,
        "AGENTICA_AI_ALLOWED_CLASSIFICATIONS": ["Internal"],
        "azure_ai_model_deployment": "gpt-test-mini",
        "azure_openai_endpoint": "https://example.openai.azure.com/openai/v1",
        "azure_openai_api_key": SecretStr("test-only-key"),
        "AGENTICA_AI_DAILY_CALL_LIMIT": 40,
    }
    values.update(extra)
    return Settings(**values)


class FakeAzure:
    """Answers each structured request from a canned response and counts calls."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def parse(self, *, model, instructions, input, text_format, max_output_tokens, store):
        self.calls.append(text_format.__name__)
        assert store is False and max_output_tokens <= 4000
        answer = self.answers[text_format.__name__]
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(status="completed", output_parsed=text_format.model_validate(answer), usage=SimpleNamespace(input_tokens=1200, output_tokens=300))


@pytest.fixture
def fake(monkeypatch):
    holder = {}

    def install(answers):
        azure = FakeAzure(answers)

        @contextmanager
        def client(_settings):
            yield SimpleNamespace(responses=azure)

        monkeypatch.setattr(foundry_brain, "openai_client", client)
        holder["azure"] = azure
        return azure

    return install


PLAN = {
    "analysis": "Checkout errors after a release with pool saturation evidence.",
    "selected": [
        {"role": "logs", "reason": "EVD-301 shows timeouts", "task": "Group timeouts"},
        {"role": "logs", "reason": "duplicate", "task": "dup"},
        {"role": "root-cause", "reason": "Weigh hypotheses", "task": "Name the cause"},
        {"role": "remediation", "reason": "Propose a fix", "task": "Draft fix"},
    ],
    "skipped": [{"role": "security", "reason": "No security signal"}],
}
WORK = {"findings": [
    {"role": "logs", "summary": "Timeouts in checkout logs.", "evidence_ids": ["EVD-301", "EVD-999"], "confidence": 1.7},
]}
OUTCOME = {"resolved": False, "detail": "No validation plan yet.", "recommendation": "iterate", "missing": ["validation", "logs"],
           "validation": {"technical_correctness": True, "completeness": False, "cross_agent_consistency": True, "security_and_risk_acceptable": True, "human_approval_satisfied": True, "summary": "Validation missing."}}


def brain_and_context(store_settings):
    store = Store("sqlite:///:memory:")
    application = create_app(store_settings, store)
    brain = application.state.mission_brain
    assert isinstance(brain, FoundryBrain)
    return brain, _context(store.read(), "INC-1042"), store


def test_plan_is_validated_and_completed(fake):
    fake({"TeamPlan": PLAN})
    brain, context, _ = brain_and_context(settings())
    plan = brain.plan(context, 1, [], [])
    assert plan["source"].startswith("AI-GENERATED /")
    assert [item["role"] for item in plan["selected"]] == ["logs", "root-cause", "remediation"]
    assert {item["role"] for item in plan["selected"]} | {item["role"] for item in plan["skipped"]} == set(SPECIALISTS)
    assert next(item for item in plan["skipped"] if item["role"] == "security")["reason"] == "No security signal"


def test_work_filters_unknown_evidence_and_fills_missing_members(fake):
    fake({"StepFindings": WORK})
    brain, context, _ = brain_and_context(settings())
    members = [{"role": "logs", "name": "Log analysis", "task": "t"}, {"role": "observability", "name": "Observability", "task": "t"}]
    findings = brain.work(context, "investigate", members, [])
    assert findings["logs"]["evidenceIds"] == ["EVD-301"]
    assert findings["logs"]["confidence"] == 1.0
    assert findings["observability"]["source"].startswith("SIMULATED fallback")


def test_outcome_normalises_recommendation_and_missing(fake):
    fake({"Outcome": OUTCOME})
    brain, context, _ = brain_and_context(settings())
    context["findings"] = []
    outcome = brain.evaluate(context, ["logs"], 3)
    assert outcome["recommendation"] == "escalate"
    assert outcome["missing"] == ["validation"]


def test_identical_requests_are_cached_and_counted(fake):
    azure = fake({"TeamPlan": PLAN})
    brain, context, store = brain_and_context(settings())
    brain.plan(context, 1, [], [])
    brain.plan(context, 1, [], [])
    assert azure.calls == ["TeamPlan"]
    usage = store.read()["aiUsage"]
    assert usage["calls"] == 1 and usage["cacheHits"] == 1
    assert usage["inputTokens"] == 1200 and usage["outputTokens"] == 300


def test_daily_limit_falls_back_to_simulated(fake):
    azure = fake({"TeamPlan": PLAN})
    brain, context, _ = brain_and_context(settings(AGENTICA_AI_DAILY_CALL_LIMIT=0))
    plan = brain.plan(context, 1, [], [])
    assert plan["source"].startswith("SIMULATED fallback: Daily AI call limit")
    assert azure.calls == []


def test_data_policy_blocks_ai_calls(fake):
    azure = fake({"TeamPlan": PLAN})
    brain, context, _ = brain_and_context(settings(AGENTICA_AI_ALLOWED_CLASSIFICATIONS=["Public"]))
    plan = brain.plan(context, 1, [], [])
    assert plan["source"].startswith("SIMULATED fallback")
    assert azure.calls == []


def test_azure_failure_falls_back(fake):
    fake({"TeamPlan": RuntimeError("network down")})
    brain, context, _ = brain_and_context(settings())
    assert brain.plan(context, 1, [], [])["source"] == "SIMULATED fallback: Azure OpenAI request failed (RuntimeError)."


def test_mission_runs_end_to_end_with_ai_brain(fake):
    azure = fake({"TeamPlan": PLAN, "StepFindings": WORK, "Outcome": OUTCOME})
    application = create_app(settings(), Store("sqlite:///:memory:"))
    with TestClient(application) as client:
        login = client.post("/api/v1/auth/demo", json={"role": "Incident Manager"})
        client.headers["X-CSRF-Token"] = login.json()["csrf"]
        mission_id = client.post("/api/v1/incidents/INC-1042/missions").json()["missionId"]
        snapshot = client.get("/api/v1/workspace").json()
        assert "aiCache" not in snapshot and snapshot["aiMode"].startswith("AI-GENERATED")
        mission = next(item for item in snapshot["missions"] if item["id"] == mission_id)
        assert mission["mode"].startswith("AI-GENERATED") and mission["iterations"][0]["plan"]["source"].startswith("AI-GENERATED")
        assert "brainCache" not in mission
        gate = mission["pendingGate"]
        assert client.post(f"/api/v1/missions/{mission_id}/decision", json={"gateId": gate["id"], "decision": "approve"}).status_code == 200
        mission = next(item for item in client.get("/api/v1/workspace").json()["missions"] if item["id"] == mission_id)
        assert mission["pendingGate"]["type"] == "root-cause"
        assert azure.calls == ["TeamPlan", "StepFindings", "StepFindings"]
        assert snapshot["aiUsage"]["calls"] == 1


def test_outcome_tolerates_invented_missing_roles():
    from backend.foundry_brain import Outcome

    report = {"technical_correctness": True, "completeness": False, "cross_agent_consistency": True, "security_and_risk_acceptable": True, "human_approval_satisfied": False, "summary": "s"}
    outcome = Outcome.model_validate({"resolved": False, "detail": "d", "recommendation": "iterate", "missing": ["testing", "human_approval"], "validation": report})
    assert outcome.missing == ["testing", "human_approval"]
