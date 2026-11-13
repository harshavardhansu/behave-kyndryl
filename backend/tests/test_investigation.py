"""Read-only investigation tools, the Foundry tool-call loop and the mission PDF report (all offline)."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

from backend import foundry_runtime
from backend.foundry_runtime import FoundryAgentService
from backend.investigation_tools import MAX_CALLS, TOOL_NAMES, InvestigationTools
from backend.mission_report import generate_mission_report_pdf, pick_mission
from backend.seed import seed_workspace
from backend.store import Store
from backend.tests.test_foundry_runtime import settings


def sandbox_state():
    state = seed_workspace(True)
    incident = next(i for i in state["incidents"] if i["service"] == "payment-api" and i["environment"] == "Sandbox")
    return state, incident


def test_tools_read_only_what_belongs_to_the_incident():
    state, incident = sandbox_state()
    tools = InvestigationTools(state, incident)
    listing = tools.call("list_evidence", {})
    assert listing["evidence"] and all(row["id"] for row in listing["evidence"])
    first = listing["evidence"][0]["id"]
    assert tools.call("read_evidence", {"id": first})["text"]
    other = next(e["id"] for e in state["evidence"] if e["incidentId"] != incident["id"])
    assert "error" in tools.call("read_evidence", {"id": other})  # another incident's evidence is off limits
    assert tools.call("get_ticket", {})["title"] == incident["title"]
    assert "error" not in tools.call("get_ticket", {})  # the ticket's own "error" field is not a tool failure
    assert tools.call("search_logs", {"query": "pool"})["matches"] is not None
    assert tools.call("search_knowledge", {"query": "connection pool sizing"})["articles"]
    assert [c["tool"] for c in tools.trail][:2] == ["list_evidence", "read_evidence"]


def test_repo_reading_is_confined_and_unknown_tools_fail_safely():
    state, incident = sandbox_state()
    tools = InvestigationTools(state, incident)
    assert "app.py" in tools.call("list_repo_files", {})["files"]
    assert "pool" in tools.call("read_repo_file", {"path": "app.py"})["text"].lower()
    for bad in ("../backend/domain.py", "/etc/passwd", "..\\..\\.env", ".env"):
        assert "error" in tools.call("read_repo_file", {"path": bad})
    assert "error" in tools.call("delete_everything", {})
    assert "error" in tools.call("read_evidence", "not-a-dict")  # malformed arguments never raise
    # A ticket that is not about the sandbox has no repository connected.
    other = next(i for i in state["incidents"] if i["service"] == "redis-cache")
    assert InvestigationTools(state, other).call("list_repo_files", {})["files"] == []
    assert InvestigationTools(state, other).call("list_log_files", {})["logs"] == []
    assert TOOL_NAMES >= {"read_evidence", "search_logs", "read_repo_file"}


def test_tool_budget_and_secret_redaction():
    state, incident = sandbox_state()
    state["evidence"].append({"id": "EVD-SECRET", "incidentId": incident["id"], "title": "t", "type": "Log", "excerpt": "password=Hunter2Hunter2 api_key=sk-abcdefghijklmnop0123456789", "classification": "Observed"})
    tools = InvestigationTools(state, incident)
    text = json.dumps(tools.call("read_evidence", {"id": "EVD-SECRET"}))
    assert "Hunter2Hunter2" not in text and "sk-abcdefghijklmnop0123456789" not in text
    for _ in range(MAX_CALLS + 2):
        result = tools.call("get_ticket", {})
    assert "budget" in result["error"]


def test_foundry_tool_loop_executes_calls_and_returns_the_final_answer(monkeypatch):
    state, incident = sandbox_state()
    store = Store("sqlite:///:memory:")
    store.initialize(seed_workspace(True))
    store.mutate(lambda s: s.setdefault("foundryAgents", {}).__setitem__("logs", {"name": "behave-logs", "version": "1", "model": "gpt-test"}))
    sent = []

    class Responses:
        def create(self, input, extra_body, previous_response_id=None):
            sent.append((input, previous_response_id))
            if previous_response_id is None:
                call = SimpleNamespace(type="function_call", name="list_evidence", arguments="{}", call_id="c1")
                return SimpleNamespace(id="r1", status="completed", output=[call], output_text="", usage=SimpleNamespace(input_tokens=10, output_tokens=5))
            return SimpleNamespace(id="r2", status="completed", output=[], output_text='{"summary":"ok"}', usage=SimpleNamespace(input_tokens=20, output_tokens=7))

    class OpenAI:
        responses = Responses()
        def with_options(self, **_): return self
        def __enter__(self): return self
        def __exit__(self, *_): return False

    @contextmanager
    def client(_settings):
        yield SimpleNamespace(get_openai_client=lambda: OpenAI())

    monkeypatch.setattr(foundry_runtime, "project_client", client)
    tools = InvestigationTools(state, incident)
    text, tokens_in, tokens_out = FoundryAgentService(settings(), store).run("logs", {"x": 1}, {}, tools)
    assert json.loads(text) == {"summary": "ok"} and (tokens_in, tokens_out) == (30, 12)
    assert sent[1][1] == "r1" and sent[1][0][0]["type"] == "function_call_output" and sent[1][0][0]["call_id"] == "c1"
    assert [c["tool"] for c in tools.trail] == ["list_evidence"]


def test_mission_report_pdf_is_built_from_what_happened():
    state, incident = sandbox_state()
    finding = {"summary": "Pool of 5 exhausted under 50 requests.", "evidenceIds": ["EVD-421"], "confidence": 0.95, "source": "AI-GENERATED / Foundry agent behave-logs v4",
               "toolCalls": [{"tool": "read_evidence", "arguments": {"id": "EVD-421"}, "ok": True, "found": "release configuration"}]}
    mission = {
        "id": "MSN-TEST", "incidentId": incident["id"], "status": "Resolved", "maxIterations": 3, "requestedBy": "Alex Morgan", "createdAt": "2026-01-01T00:00:00+00:00",
        "resolution": {"by": "Alex Morgan"}, "learnings": ["Iteration 1: fix needed"], "events": [{"timestamp": "2026-01-01T00:00:01+00:00", "actor": "Orchestrator", "message": "Proposed a team."}],
        "iterations": [{"number": 1, "plan": {"analysis": "Start with logs.", "source": "AI-GENERATED / Foundry agent behave-orchestrator v4"}, "skipped": [{"role": "release", "name": "Release", "reason": "too early"}],
                        "team": [{"role": "logs", "name": "Log analysis", "reason": "Errors in logs", "findings": finding}, {"role": "root-cause", "name": "Root cause", "reason": "Explain", "findings": finding}],
                        "decisions": [{"type": "team", "decision": "approve", "by": "Alex Morgan", "note": "", "at": "2026-01-01T00:00:02+00:00"}],
                        "sandboxChange": {"requested": {"release": "3.8.1", "pool_size": 20}, "status": "SUCCEEDED", "active": {"release": "3.8.1", "pool_size": 20}},
                        "outcome": {"resolved": True, "detail": "MEASURED: 0 of 50 failed.", "source": "MEASURED"}}],
    }
    assert pick_mission({"missions": [mission]}, incident["id"]) is mission and pick_mission({"missions": [mission]}, "INC-NONE") is None
    pdf = generate_mission_report_pdf(incident, mission, state)
    assert pdf.startswith(b"%PDF") and len(pdf) > 4000
    mission["iterations"][0].pop("sandboxChange")  # also renders when nothing was applied and nothing finished
    mission.update(status="Awaiting team approval", resolution=None)
    mission["iterations"][0].pop("outcome")
    assert generate_mission_report_pdf(incident, mission, state).startswith(b"%PDF")


def test_demo_services_have_repositories_and_logs_to_investigate():
    state = seed_workspace(True)
    incident = next(i for i in state["incidents"] if i["service"] == "checkout-svc")
    tools = InvestigationTools(state, incident)
    files = tools.call("list_repo_files", {})["files"]
    assert "src/main/resources/application.yml" in files
    assert "maximum-pool-size: 10" in tools.call("read_repo_file", {"path": "src/main/resources/application.yml"})["text"]
    assert tools.call("read_repo_file", {"path": "application.yml"})["path"] == "src/main/resources/application.yml"  # bare file name works
    assert any("CHANGELOG" in m["file"] for m in tools.call("search_repo", {"query": "c7f4e21"})["matches"])
    for bad in ("../../backend/domain.py", "../logs/checkout-svc.log", "/etc/hosts"):
        assert "error" in tools.call("read_repo_file", {"path": bad})

    tools = InvestigationTools(state, incident)  # fresh call budget for the log checks
    logs = tools.call("list_log_files", {})["logs"]
    assert {log["file"] for log in logs} >= {"checkout-svc.log"} and all(log["lines"] > 0 for log in logs)
    errors = tools.call("search_logs", {"query": "HikariPool", "level": "ERROR"})
    assert errors["total"] > 50 and errors["firstSeen"].startswith("2026-10-30T09:42")
    assert errors["matches"][0]["source"] == "EVD-301"  # attached log evidence is searched too
    first = int(next(m for m in errors["matches"] if m["source"].startswith("checkout-svc.log:"))["source"].split(":")[1])
    window = tools.call("read_log", {"file": "checkout-svc.log", "start_line": first - 5, "lines": 10})
    assert len(window["lines"]) == 10 and window["from"] == first - 5
    capped = tools.call("read_log", {"file": "checkout-svc.log", "lines": 500})
    assert 10 <= len(capped["lines"]) <= 40 and capped["to"] - capped["from"] + 1 == len(capped["lines"])  # capped, range stays accurate
    assert "error" in tools.call("read_log", {"file": "../../.env"})
    assert tools.trail[-1]["ok"] is False
