import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.domain import Settings
from backend.mission import MAX_ITERATIONS, SPECIALISTS, SimulatedBrain, _context
from backend.store import Store


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


def mission(client, mission_id):
    return next(item for item in client.get("/api/v1/workspace").json()["missions"] if item["id"] == mission_id)


def start(client, incident="INC-1042"):
    response = client.post(f"/api/v1/incidents/{incident}/missions")
    assert response.status_code == 201, response.text
    return response.json()["missionId"]


def decide(client, mission_id, decision, **extra):
    gate = mission(client, mission_id)["pendingGate"]
    assert gate is not None
    return client.post(f"/api/v1/missions/{mission_id}/decision", json={"gateId": gate["id"], "decision": decision, **extra})


def test_orchestrator_proposes_a_team_not_all_specialists(client):
    login(client)
    mission_id = start(client)
    record = mission(client, mission_id)
    assert record["status"] == "Awaiting team approval"
    assert record["mode"].startswith("SIMULATED")
    plan = record["iterations"][0]["plan"]
    selected = {item["role"] for item in plan["selected"]}
    skipped = {item["role"] for item in plan["skipped"]}
    assert 0 < len(selected) < len(SPECIALISTS)
    assert selected | skipped == set(SPECIALISTS)
    assert all(item["reason"] for item in plan["selected"] + plan["skipped"])
    assert record["pendingGate"]["type"] == "team"
    assert any(event["type"] == "team-proposed" for event in record["events"])


def test_team_selection_depends_on_the_ticket(client):
    login(client)
    state = client.get("/api/v1/workspace").json()
    brain = SimulatedBrain()
    teams = {frozenset(brain.relevant_roles(_context(state, incident["id"]))) for incident in state["incidents"] if any(e["incidentId"] == incident["id"] for e in state["evidence"])}
    assert len(teams) > 1


def test_only_one_open_mission_per_incident(client):
    login(client)
    start(client)
    assert client.post("/api/v1/incidents/INC-1042/missions").status_code == 409


def test_human_can_edit_the_team_and_work_stops_at_root_cause_gate(client):
    login(client)
    mission_id = start(client)
    plan = mission(client, mission_id)["iterations"][0]["plan"]
    removed = next(item["role"] for item in plan["selected"] if item["role"] == "logs")
    added = next(item["role"] for item in plan["skipped"])
    response = decide(client, mission_id, "approve", addRoles=[added], removeRoles=[removed], note="Adjusted by the commander")
    assert response.status_code == 200, response.text
    record = mission(client, mission_id)
    team = {member["role"]: member for member in record["iterations"][0]["team"]}
    assert added in team and team[added]["addedBy"] == "Alex Morgan"
    assert removed not in team
    assert any(item["role"] == removed and "Removed by" in item["reason"] for item in record["iterations"][0]["skipped"])
    assert record["status"] == "Awaiting decision"
    assert record["pendingGate"]["type"] == "root-cause"
    finished = [member for member in team.values() if member["status"] == "Completed"]
    assert finished and all(member["findings"]["summary"] for member in finished)


def test_rejecting_the_team_requires_a_reason_and_replans(client):
    login(client)
    mission_id = start(client)
    assert decide(client, mission_id, "reject", note="").status_code == 422
    assert decide(client, mission_id, "reject", note="Too small a team for a P1").status_code == 200
    record = mission(client, mission_id)
    assert record["status"] == "Awaiting team approval"
    assert any("team rejected" in learning for learning in record["learnings"])


def run_to_fix_gate(client):
    mission_id = start(client)
    assert decide(client, mission_id, "approve").status_code == 200
    assert decide(client, mission_id, "approve").status_code == 200
    assert mission(client, mission_id)["pendingGate"]["type"] == "fix"
    return mission_id


def test_fix_needs_a_different_approver_with_approval_rights(client):
    login(client)
    mission_id = run_to_fix_gate(client)
    assert decide(client, mission_id, "approve").status_code == 403
    login(client, "Administrator")
    record = mission(client, mission_id)
    response = client.post(f"/api/v1/missions/{mission_id}/decision", json={"gateId": record["pendingGate"]["id"], "decision": "approve"})
    assert response.status_code == 200, response.text
    record = mission(client, mission_id)
    assert record["status"] == "Awaiting resolution review"
    assert record["iterations"][0]["outcome"]["resolved"] is False


def test_iteration_adds_agents_and_resolves(client):
    login(client)
    mission_id = run_to_fix_gate(client)
    login(client, "Change Approver")
    assert decide(client, mission_id, "approve").status_code == 200
    login(client)
    first_team = {member["role"] for member in mission(client, mission_id)["iterations"][0]["team"]}
    assert decide(client, mission_id, "iterate", note="Errors still above threshold").status_code == 200
    record = mission(client, mission_id)
    assert record["iteration"] == 2 and record["pendingGate"]["type"] == "team"
    second_plan = {item["role"] for item in record["iterations"][1]["plan"]["selected"]}
    assert first_team < second_plan
    assert record["learnings"]
    assert decide(client, mission_id, "approve").status_code == 200
    assert decide(client, mission_id, "approve").status_code == 200
    login(client, "Change Approver")
    assert decide(client, mission_id, "approve").status_code == 200
    login(client)
    record = mission(client, mission_id)
    assert record["iterations"][1]["outcome"]["resolved"] is True
    assert decide(client, mission_id, "resolve").status_code == 200
    assert mission(client, mission_id)["status"] == "Resolved"


def test_iteration_limit_escalates(client):
    login(client)
    mission_id = start(client)
    for _ in range(MAX_ITERATIONS):
        assert decide(client, mission_id, "approve").status_code == 200
        assert decide(client, mission_id, "reject", note="Root cause not convincing").status_code == 200
    assert mission(client, mission_id)["status"] == "Escalated"


def test_viewer_cannot_start_or_decide(client):
    login(client)
    mission_id = start(client)
    login(client, "Viewer")
    assert client.post("/api/v1/incidents/INC-1041/missions").status_code == 403
    assert decide(client, mission_id, "approve").status_code == 403


def test_cancel_and_stale_gate(client):
    login(client)
    mission_id = start(client)
    gate_id = mission(client, mission_id)["pendingGate"]["id"]
    assert client.post(f"/api/v1/missions/{mission_id}/cancel").status_code == 200
    response = client.post(f"/api/v1/missions/{mission_id}/decision", json={"gateId": gate_id, "decision": "approve"})
    assert response.status_code == 409
    assert mission(client, mission_id)["status"] == "Cancelled"


def test_workspace_publishes_the_mission_squads_in_order(client):
    login(client)
    steps = client.get("/api/v1/workspace").json()["missionSteps"]
    assert [step["id"] for step in steps] == ["investigate", "diagnose", "remediate", "govern"]
    assert sorted(role for step in steps for role in step["roles"]) == sorted(SPECIALISTS)  # every specialist belongs to one squad


def test_an_approved_solution_can_be_handed_over(client):
    """A fix this system cannot apply ends as "Solution ready": not falsely resolved, not escalated."""
    login(client)
    mission_id = run_to_fix_gate(client)
    login(client, "Change Approver")
    assert decide(client, mission_id, "approve").status_code == 200
    login(client)
    assert mission(client, mission_id)["pendingGate"]["type"] == "resolution"
    assert decide(client, mission_id, "handoff", note="Owning team will implement").status_code == 200
    record = mission(client, mission_id)
    assert record["status"] == "Solution ready" and record["pendingGate"] is None
    assert record["handoff"]["note"] == "Owning team will implement" and not record.get("resolution")
    workspace = client.get("/api/v1/workspace").json()
    incident = next(item for item in workspace["incidents"] if item["id"] == "INC-1042")
    assert incident["status"] != "Resolved" and incident["workflowStatus"] == "Completed"
    report = client.get("/api/v1/incidents/INC-1042/resolution-report/pdf")
    assert report.status_code == 200 and report.content.startswith(b"%PDF")
    assert start(client)  # a new mission can be started afterwards


def test_a_low_confidence_root_cause_is_flagged_for_rejection(client):
    """The gate must not present a guess as a diagnosis."""
    class UnsureBrain(SimulatedBrain):
        def work(self, context, step, members, prior):
            findings = super().work(context, step, members, prior)
            if "root-cause" in findings:
                findings["root-cause"].update(summary="The cause could not be identified.", confidence=0.2)
            return findings

    client.app.state.mission_brain = UnsureBrain()
    login(client)
    mission_id = start(client)
    assert decide(client, mission_id, "approve").status_code == 200
    gate = mission(client, mission_id)["pendingGate"]
    assert gate["type"] == "root-cause" and gate["title"].startswith("Root cause not established")
    assert gate["detail"].startswith("LOW CONFIDENCE (0.20)") and gate["recommendation"].startswith("Reject")
