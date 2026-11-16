"""The parts that make the system real: Tool Gateway, organizational memory, Azure AI Search retrieval,
a workspace with no demonstration records, and records produced only by real activity. All offline."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import knowledge_search, platform_status
from backend.app import create_app
from backend.dependency_inventory import inventory
from backend.domain import Settings
from backend.investigation_tools import InvestigationTools
from backend.knowledge_search import KnowledgeIndex
from backend.mission import MissionTools, SimulatedBrain
from backend.sandbox_records import record_measurement
from backend.seed import real_workspace, seed_workspace
from backend.store import Store
from backend.tests.test_missions import decide, login, mission, start
from backend.tests.test_task_inputs import JAVA_LOG, PROJECT, PY_LOG, make_zip, new_task, upload
from backend.tool_gateway import ACTIONS, ROLE_TOOLS, ToolGateway, fingerprint

ACTION = {"release": "3.8.1", "pool_size": 20}


class ConfidentBrain(SimulatedBrain):
    """Stands in for the AI on real incidents: fixed, confident findings so the flow can be driven end to end."""

    def work(self, context, step, members, prior):
        text = {"root-cause": "The employee table is missing because migrations were not run after the release. This explains the OperationalError in views.py.",
                "remediation": "Run the pending migrations in the release pipeline. Rollback: restore the previous release. Verify: the employee list loads.",
                "validation": "Fixed when GET /employees/ returns 200 and no OperationalError is logged."}
        return {member["role"]: {"summary": text.get(member["role"], f"Checked by {member['role']}."), "evidenceIds": [], "confidence": 0.9} for member in members}

    def evaluate(self, context, team_roles, iteration):
        return {"resolved": False, "solutionReady": True, "recommendation": "handoff", "missing": [], "detail": "Root cause and fix approved by people; nothing was applied here."}


def real_app(**settings) -> TestClient:
    application = create_app(Settings(AGENTICA_MODE="demo", AGENTICA_WORKSPACE="real", AGENTICA_DEMO_STEP_SECONDS=0, **settings), Store("sqlite:///:memory:"))
    application.state.mission_brain = ConfidentBrain()
    return TestClient(application)


@pytest.fixture
def client():
    with real_app() as test_client:
        login(test_client)
        yield test_client


def run_to_handoff(client, task: str) -> str:
    started = client.post(f"/api/v1/incidents/{task}/missions")
    assert started.status_code == 201, started.text
    mission_id = started.json()["missionId"]
    assert decide(client, mission_id, "approve").status_code == 200          # team
    assert decide(client, mission_id, "approve").status_code == 200          # root cause
    login(client, "Change Approver")
    assert decide(client, mission_id, "approve").status_code == 200          # fix, by a second person
    login(client)
    assert mission(client, mission_id)["pendingGate"]["type"] == "resolution"
    assert decide(client, mission_id, "handoff", note="Owning team applies it").status_code == 200
    return mission_id


# -- Tool Gateway ------------------------------------------------------------------


def gateway_state(decisions=None, status="Working", service="payment-api", environment="Sandbox"):
    state = seed_workspace(True)
    state["incidents"].append({"id": "INC-GW", "title": "Sandbox incident", "service": service, "environment": environment, "status": "Investigating", "synthetic": False})
    state["missions"] = [{"id": "MSN-GW", "incidentId": "INC-GW", "status": status, "iteration": 1, "requestedBy": "Alex Morgan", "requestedById": "alex-morgan",
                          "iterations": [{"number": 1, "team": [], "decisions": decisions or []}]}]
    store = Store("sqlite:///:memory:")
    store.initialize(state)
    return store


def approval(by="Sam Rivera", by_id="sam-rivera", value=ACTION):
    return {"gateId": "GATE-1", "type": "fix", "decision": "approve", "by": by, "byId": by_id, "approvedHash": fingerprint(value)}


def test_gateway_runs_an_approved_action_once_and_logs_it():
    store = gateway_state([approval()])
    gateway, ran = ToolGateway(store), []
    result = gateway.execute("sandbox.apply_configuration", "MSN-GW", ACTION, lambda: ran.append(1) or {"status": "SUCCEEDED", "active_config": ACTION})
    assert result["status"] == "SUCCEEDED" and ran == [1]
    entry = store.read()["gateway"][0]
    assert entry["status"] == "SUCCEEDED" and entry["approvedBy"] == "Sam Rivera" and entry["approvalGateId"] == "GATE-1" and entry["result"]["active"] == ACTION
    assert entry["incidentId"] == "INC-GW" and entry["risk"] == "Medium" and entry["durationMs"] is not None
    again = gateway.execute("sandbox.apply_configuration", "MSN-GW", ACTION, lambda: ran.append(2) or {"status": "SUCCEEDED"})
    assert again["status"] == "DENIED" and "already ran once" in again["error"] and ran == [1]
    actions = [event["action"] for event in store.read()["audit"] if event["actor"] == "Tool Gateway"]
    assert "Tool Gateway running: sandbox.apply_configuration" in actions and "Tool Gateway denied: sandbox.apply_configuration" in actions


@pytest.mark.parametrize("decisions,value,status,expected", [
    ([], ACTION, "Working", "No human approved a fix"),
    ([approval(by="Alex Morgan", by_id="alex-morgan")], ACTION, "Working", "Separation of duties"),
    ([approval()], {"release": "3.8.1", "pool_size": 500}, "Working", "differs from the change the human approved"),
    ([{**approval(), "approvedHash": ""}], ACTION, "Working", "does not record exactly what was approved"),
    ([approval()], ACTION, "Cancelled", "not working"),
    ([{**approval(), "decision": "reject"}], ACTION, "Working", "No human approved a fix"),
])
def test_gateway_refuses_anything_a_human_did_not_approve(decisions, value, status, expected):
    store = gateway_state(decisions, status)
    ran = []
    result = ToolGateway(store).execute("sandbox.apply_configuration", "MSN-GW", value, lambda: ran.append(1) or {"status": "SUCCEEDED"})
    assert result["status"] == "DENIED" and expected in result["error"] and ran == []
    entry = store.read()["gateway"][0]
    assert entry["status"] == "DENIED" and expected in entry["reason"]


def test_gateway_checks_the_action_and_its_target():
    store = gateway_state([approval()], service="checkout-svc", environment="Production")
    gateway, ran = ToolGateway(store), []
    run = lambda: ran.append(1) or {"status": "SUCCEEDED"}  # noqa: E731
    assert "isolated Payment API sandbox" in gateway.execute("sandbox.apply_configuration", "MSN-GW", ACTION, run)["error"]
    assert "not a registered gateway action" in gateway.execute("shell.run", "MSN-GW", ACTION, run)["error"]
    assert "does not exist" in gateway.execute("sandbox.run_workload", "MSN-NOPE", {"workload": 50}, run)["error"]
    edits = [{"path": "a.py", "find": "x", "replace": "y"}]
    store = gateway_state([approval(value=edits)], service="checkout-svc", environment="Production")
    refused = ToolGateway(store).execute("github.open_pull_request", "MSN-GW", edits, run, lambda incident: "This repository is not opted in to pull requests.")
    assert refused["status"] == "DENIED" and "not opted in" in refused["error"] and ran == []
    # Without a gateway nothing outside may run at all.
    assert MissionTools(None, None, None).apply_fix(ACTION, "MSN-GW")["status"] == "DENIED"
    # A failing action is recorded as failed, never raised.
    store = gateway_state([approval()])
    failed = ToolGateway(store).execute("sandbox.apply_configuration", "MSN-GW", ACTION, lambda: 1 / 0)
    assert failed["status"] == "FAILED" and store.read()["gateway"][0]["status"] == "FAILED"


def test_each_agent_gets_only_the_tools_its_job_needs():
    state = seed_workspace(True)
    incident = next(item for item in state["incidents"] if item["service"] == "payment-api")
    knowledge = InvestigationTools(state, incident, role="knowledge")
    assert "least privilege" in knowledge.call("read_repo_file", {"path": "app.py"})["error"]
    assert "error" not in knowledge.call("get_ticket", {})
    assert "text" in InvestigationTools(state, incident, role="repository").call("read_repo_file", {"path": "app.py"})
    assert "read_repo_file" not in ROLE_TOOLS["knowledge"] and "read_log" not in ROLE_TOOLS["release"] and set(ACTIONS) == {
        "sandbox.apply_configuration", "sandbox.run_workload", "github.open_pull_request"}


# -- a workspace with no demonstration records ---------------------------------------


def test_real_workspace_starts_empty_and_reports_only_checked_statuses(client):
    state = client.get("/api/v1/workspace").json()
    assert state["workspaceKind"] == "real" and client.get("/api/v1/health").json()["workspace"] == "real"
    for name in ("incidents", "evidence", "logs", "tests", "security", "changes", "deployments", "knowledge", "hypotheses", "errors", "missions", "gateway"):
        assert state[name] == [], name
    assert [row["date"] for row in state["trends"]] and all(row["critical"] == row["high"] == row["other"] == row["resolved"] == 0 for row in state["trends"])
    by_id = {item["id"]: item for item in state["integrations"]}
    assert by_id["gateway"]["status"] == "Active" and by_id["search"]["status"] == "Not configured" and by_id["keyvault"]["status"] == "Not configured"
    assert by_id["tracing"]["status"] == "Not configured" and by_id["runner"]["status"] == "Not configured" and by_id["telemetry"]["status"] == "Not configured"
    assert "demo" not in json.dumps(state["integrations"]).lower() and "synthetic" not in json.dumps(state["integrations"]).lower()
    catalog = client.get("/api/v1/gateway").json()
    assert len(catalog["actions"]) == 3 and catalog["log"] == [] and "search_knowledge" in catalog["readTools"]["knowledge"]


def test_real_workspace_never_simulates_and_records_what_people_observed(client):
    task = new_task(client)
    assert upload(client, task, "portal.zip", make_zip(PROJECT)).status_code == 201
    headers = lambda: {"Idempotency-Key": __import__("uuid").uuid4().hex}  # noqa: E731
    for action in ("start-investigation", "generate-fix", "run-validation", "deploy", "rollback"):
        login(client, "Administrator")
        refused = client.post(f"/api/v1/incidents/{task}/actions", json={"action": action, "confirmation": "Production", "reason": "trying a simulated step"}, headers=headers())
        assert refused.status_code == 409, (action, refused.text)
    login(client)
    mission_id = run_to_handoff(client, task)
    assert mission(client, mission_id)["status"] == "Solution ready"
    state = client.get("/api/v1/workspace").json()
    assert state["deployments"] == [] and not any(record.get("synthetic") for name in ("evidence", "tests", "audit", "logs", "hypotheses") for record in state[name])
    incident = next(item for item in state["incidents"] if item["id"] == task)
    assert incident["status"] == "Approved" and incident["recovery"] is None  # nothing is claimed as recovered
    short = client.post(f"/api/v1/incidents/{task}/actions", json={"action": "verify", "reason": "ok"}, headers=headers())
    assert short.status_code == 422
    done = client.post(f"/api/v1/incidents/{task}/actions", json={"action": "verify", "reason": "Migrations ran in release 2.19; the employee list loads and no OperationalError was logged for 2 hours."}, headers=headers())
    assert done.status_code == 200, done.text
    state = client.get("/api/v1/workspace").json()
    incident = next(item for item in state["incidents"] if item["id"] == task)
    assert incident["status"] == "Resolved" and incident["recovery"]["errorRate"] is None and incident["recovery"]["synthetic"] is False
    assert "Recorded by a person" in incident["recovery"]["basis"]
    evidence = next(item for item in state["evidence"] if item["id"] == incident["recovery"]["evidence"])
    assert "Migrations ran" in evidence["excerpt"] and evidence["type"] == "Observation"
    assert next(item for item in state["knowledge"] if task in item["incidents"])["verified"] is True
    assert sum(row["resolved"] for row in state["trends"]) == 1 and sum(row["high"] for row in state["trends"]) == 1  # counted from real records


def test_without_ai_nothing_is_invented_for_a_real_incident():
    with real_app() as client:
        client.app.state.mission_brain = SimulatedBrain()
        login(client)
        task = new_task(client)
        upload(client, task, "server.log", JAVA_LOG.encode())
        mission_id = client.post(f"/api/v1/incidents/{task}/missions").json()["missionId"]
        assert decide(client, mission_id, "approve").status_code == 200
        gate = mission(client, mission_id)["pendingGate"]
        assert gate["type"] == "root-cause" and gate["recommendation"].startswith("Reject") and "LOW CONFIDENCE (0.00)" in gate["detail"]
        finding = next(member["findings"] for member in mission(client, mission_id)["iterations"][0]["team"] if member["role"] == "root-cause")
        assert finding["confidence"] == 0 and "Not performed: no AI model was available" in finding["summary"]


# -- records come from real activity ---------------------------------------------------


def test_uploads_scans_and_missions_fill_the_pages_with_real_records(client, monkeypatch):
    task = new_task(client)
    assert upload(client, task, "portal.zip", make_zip({**PROJECT, "portal/settings.py": "SECRET_KEY = 'abcdefghijklmnop1234'\nDEBUG = True\n"})).status_code == 201
    state = client.get("/api/v1/workspace").json()
    # Observability: every timestamped line of the uploaded log, not only the errors.
    logs = [record for record in state["logs"] if record["service"] == "hr-portal"]
    assert [record["level"] for record in logs] == ["INFO", "ERROR", "ERROR", "WARN"] and all(record["synthetic"] is False for record in logs)
    assert "Traceback" in logs[1]["message"] and logs[1]["traceId"] == "abc-1234" and logs[0]["timestamp"] == "2026-11-14T09:12:01Z"
    # Services: health from open incidents and errors; no invented metrics.
    service = next(item for item in state["services"] if item["id"] == "hr-portal")
    assert service["health"] == "Degraded" and service["latency"] is None and service["errorRate"] is None and "no live monitoring" in service["healthBasis"]
    # Dependencies declared in the uploaded project.
    deps = client.get(f"/api/v1/incidents/{task}/dependencies").json()
    assert {(row["name"], row["version"]) for row in deps["dependencies"]} == {("Django", "==5.1"), ("pytest", "not pinned")} and deps["unpinned"] == 1
    # Investigations and Changes: from the mission.
    mission_id = run_to_handoff(client, task)
    state = client.get("/api/v1/workspace").json()
    hypothesis = next(item for item in state["hypotheses"] if item["incidentId"] == task)
    assert hypothesis["status"] == "Confirmed by a person" and hypothesis["confidence"] == 0.9 and hypothesis["title"].startswith("The employee table is missing")
    change = next(item for item in state["changes"] if item["incidentId"] == task)
    assert "restore the previous release" in change["rollback"] and change["plan"][1] == "A different person approves this exact change"
    assert mission(client, mission_id)["knowledgeId"]


def test_repository_scan_findings_reach_the_security_page(client, monkeypatch):
    from backend import connectors
    from backend.tests.test_fix_delivery import FakeGitHub

    github = FakeGitHub({"app/settings.py": 'API_KEY = "abcdefghijklmnop1234"\nDEBUG = True\n', "Dockerfile": "FROM python:3.13\nCOPY . .\n"})
    original = connectors.GitHubCode.__init__
    monkeypatch.setattr(connectors.GitHubCode, "__init__", lambda self, repo, ref="", path="", api="", token="", client=None, pull_requests=False:
                        original(self, repo, ref, path, "https://api.github.com", token=token, client=github.client, pull_requests=pull_requests))
    body = {"source": "repository", "url": "acme/shop", "branch": "main", "commit": "c7f4e21", "scope": ["Security", "Configuration"], "incidentId": None, "permissionConfirmed": True}
    first = client.post("/api/v1/repositories/analyses", json=body)
    assert first.status_code == 201, first.text
    findings = client.get("/api/v1/workspace").json()["security"]
    assert {(item["title"], item["file"], item["line"], item["category"]) for item in findings} == {
        ("Hardcoded credential or token detected", "app/settings.py", 1, "Secret scanning"), ("Debug mode switched on in settings", "app/settings.py", 2, "Static analysis"),
        ("Container runs as root user", "Dockerfile", 1, "Container scanning")}
    assert all(item["status"] == "Open" and item["synthetic"] is False and item["service"] == "acme/shop" for item in findings) and "abcdefghijklmnop1234" not in json.dumps(findings)
    assert client.post("/api/v1/repositories/analyses", json=body).status_code == 201
    assert len(client.get("/api/v1/workspace").json()["security"]) == 3  # the same finding is not listed twice


def test_a_sandbox_measurement_is_an_executed_test_run():
    state = real_workspace()
    incident = {"id": "INC-1", "service": "payment-api", "environment": "Sandbox"}
    measurement = {"measuredAt": "2026-11-16T10:00:00+00:00", "release": "3.8.1", "poolSize": 5, "concurrency": 50, "requests": 50, "succeeded": 22, "errors": 28,
                   "notFound": 0, "errorRate": 56.0, "p95Ms": 2104, "maxMs": 2200, "featureX": True, "durationMs": 2300}
    record_measurement(state, incident, measurement, [], {"name": "Agent mission", "role": "Validation"}, "test")
    run = state["tests"][0]
    assert run["status"] == "Failed" and run["passed"] == 1 and run["failed"] == 1 and run["synthetic"] is False and run["duration"] == 2.3
    assert run["source"].startswith("Executed: 50 real requests") and [case["status"] for case in run["cases"]] == ["Failed", "Passed"]
    assert "28/50 failed (56.0%); p95 2104 ms" in run["cases"][0]["actual"]
    record_measurement(state, incident, {**measurement, "errors": 0, "errorRate": 0.0, "succeeded": 50, "p95Ms": 935}, [], {"name": "Agent mission", "role": "Validation"}, "after the fix")
    assert state["tests"][1]["status"] == "Passed" and state["tests"][1]["failed"] == 0  # slow but error-free: the mission's own criterion


def test_dependency_inventory_reads_real_manifests():
    class Code:
        label = "test"
        files = {
            "requirements.txt": "fastapi>=0.119,<1\nuvicorn[standard]>=0.38\n# comment\nrequests\n",
            "web/package.json": json.dumps({"dependencies": {"express": "^4.21.2"}, "devDependencies": {"jest": "29.7.0"}}),
            "svc/pom.xml": "<project><dependencies><dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId><version>3.3.5</version></dependency></dependencies></project>",
            "go.mod": "module x\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.10.0\n)\n",
            "web/node_modules/x/package.json": json.dumps({"dependencies": {"ignored": "1"}}),
        }

        def paths(self):
            return list(self.files)

        def read(self, path):
            return self.files[path]

    result = inventory(Code())
    found = {(row["ecosystem"], row["name"], row["version"], row["scope"]) for row in result["dependencies"]}
    assert found == {("PyPI", "fastapi", ">=0.119,<1", "runtime"), ("PyPI", "uvicorn", ">=0.38", "runtime"), ("PyPI", "requests", "not pinned", "runtime"),
                     ("npm", "express", "^4.21.2", "runtime"), ("npm", "jest", "29.7.0", "development"),
                     ("Maven", "org.springframework.boot:spring-boot-starter-web", "3.3.5", "compile"), ("Go", "github.com/gin-gonic/gin", "v1.10.0", "runtime")}
    assert result["total"] == 7 and len(result["manifests"]) == 4 and "not resolved" in result["note"]


# -- organizational memory -------------------------------------------------------------


def test_a_finished_mission_teaches_the_next_one(client):
    first = new_task(client)
    assert upload(client, first, "portal.zip", make_zip(PROJECT)).status_code == 201
    mission_id = run_to_handoff(client, first)
    record_id = mission(client, mission_id)["knowledgeId"]
    record = next(item for item in client.get("/api/v1/workspace").json()["knowledge"] if item["id"] == record_id)
    assert record["type"] == "Incident resolution" and record["approved"] is False and record["verified"] is False and record["incidents"] == [first]
    assert len(record["fingerprints"]) == 1 and "Root cause (confidence 0.90" in record["body"] and "migrations were not run" in record["body"]
    assert "Approved solution handed to the owning team (not applied by this system)" in record["body"]
    assert any(event["type"] == "memory" for event in mission(client, mission_id)["events"])

    # Not searchable until a different person approves it.
    state = client.app.state.store.read()
    incident = next(item for item in state["incidents"] if item["id"] == first)
    assert InvestigationTools(state, incident).call("search_knowledge", {"query": "employee table migrations"})["articles"] == []
    login(client, "Administrator")
    reviewed = client.post(f"/api/v1/knowledge/{record_id}/review", json={"decision": "approve", "reason": "Matches what the team found."})
    assert reviewed.status_code == 200 and reviewed.json()["approved"] is True
    login(client)

    # The same error on a later incident: the earlier resolution is found by fingerprint and by search.
    second = new_task(client, title="Employee list is failing again after the weekend release")
    assert upload(client, second, "again.log", PY_LOG.encode()).status_code == 201
    started = client.post(f"/api/v1/incidents/{second}/missions").json()["missionId"]
    memory = [event["message"] for event in mission(client, started)["events"] if event["type"] == "memory"]
    assert len(memory) == 1 and record_id in memory[0] and "not yet verified" in memory[0]
    state = client.app.state.store.read()
    later = next(item for item in state["incidents"] if item["id"] == second)
    found = InvestigationTools(state, later, role="knowledge").call("search_knowledge", {"query": "employee table missing migrations"})
    assert found["articles"][0]["id"] == record_id and found["retrieval"].startswith("local keyword search (Azure AI Search is not configured)")


def test_the_person_who_started_the_mission_cannot_approve_its_knowledge_record():
    with real_app() as client:
        login(client, "Administrator")
        task = new_task(client)
        upload(client, task, "server.log", JAVA_LOG.encode())
        started = client.post(f"/api/v1/incidents/{task}/missions").json()["missionId"]
        decide(client, started, "approve")
        decide(client, started, "approve")
        login(client, "Change Approver")
        decide(client, started, "approve")
        login(client, "Administrator")
        decide(client, started, "handoff")
        record_id = mission(client, started)["knowledgeId"]
        own = client.post(f"/api/v1/knowledge/{record_id}/review", json={"decision": "approve", "reason": "Approving my own mission."})
        assert own.status_code == 403


# -- Azure AI Search retrieval -----------------------------------------------------------


class FakeSearch:
    def __init__(self, fail: bool = False):
        self.docs: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []
        self.searches: list[dict] = []
        self.fail = fail

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        assert request.headers["authorization"] == "Bearer entra-token" and "api-key" not in request.headers
        if self.fail:
            return httpx.Response(403, json={"error": {"message": "Forbidden"}})
        body = json.loads(request.content) if request.content else {}
        if request.method == "PUT":
            assert body["name"] == "kb" and body["scoringProfiles"][0]["name"] == "service-boost"
            return httpx.Response(201, json={})
        if path.endswith("/docs/search.index"):
            for item in body["value"]:
                if item["@search.action"] == "delete":
                    self.docs.pop(item["id"], None)
                else:
                    self.docs[item["id"]] = item
            return httpx.Response(200, json={"value": []})
        self.searches.append(body)
        if body["search"] == "*":
            return httpx.Response(200, json={"value": [{"id": key} for key in self.docs]})
        hits = [doc for doc in self.docs.values() if doc["approved"] and any(word.lower() in (doc["title"] + doc["body"]).lower() for word in body["search"].split())]
        return httpx.Response(200, json={"value": [{**doc, "@search.score": 2.5} for doc in hits[: body["top"]]]})


class Token:
    token, expires_on = "entra-token", 4102444800


def index_for(fake: FakeSearch) -> KnowledgeIndex:
    return KnowledgeIndex("https://srch.example.net", "kb", lambda: type("Credential", (), {"get_token": lambda self, scope: Token()})(), client=fake.client)


KNOWLEDGE = [
    {"id": "KB-1", "title": "Pool saturation runbook", "body": "Raise the connection pool after password=hunter2hunter2 rotation.", "type": "Runbook", "approved": True, "services": ["checkout-svc"]},
    {"id": "KB-2", "title": "Draft about pool sizes", "body": "Unreviewed pool notes.", "type": "Incident resolution", "approved": False, "services": ["checkout-svc"]},
]


def test_knowledge_is_indexed_and_searched_in_azure_ai_search(monkeypatch):
    fake = FakeSearch()
    index = index_for(fake)
    fake.docs["KB-OLD"] = {"id": "KB-OLD", "title": "gone", "body": "", "approved": True}
    assert index.sync(KNOWLEDGE) == {"indexed": 2, "removed": 1} and set(fake.docs) == {"KB-1", "KB-2"}
    assert "hunter2hunter2" not in json.dumps(fake.docs)  # secrets are redacted before they leave the app
    monkeypatch.setitem(knowledge_search._index, "value", index)
    result = knowledge_search.search(KNOWLEDGE, "connection pool saturation", "checkout-svc")
    assert result["retrieval"].startswith("Azure AI Search") and [item["id"] for item in result["articles"]] == ["KB-1"] and result["articles"][0]["score"] == 2.5
    query = fake.searches[-1]
    assert query["filter"] == "approved eq true" and query["scoringProfile"] == "service-boost" and query["scoringParameters"] == ["service-checkout-svc"]
    assert sum(1 for method, _ in fake.calls if method == "PUT") == 1  # the index is created once


def test_search_falls_back_to_local_and_says_so(monkeypatch):
    monkeypatch.setitem(knowledge_search._index, "value", index_for(FakeSearch(fail=True)))
    result = knowledge_search.search(KNOWLEDGE, "connection pool saturation", "checkout-svc")
    assert result["retrieval"].startswith("local keyword search (Azure AI Search unavailable") and [item["id"] for item in result["articles"]] == ["KB-1"]
    monkeypatch.setitem(knowledge_search._index, "value", None)
    assert "not configured" in knowledge_search.search(KNOWLEDGE, "pool", "checkout-svc")["retrieval"]


def test_statuses_are_checked_not_declared(monkeypatch):
    platform_status.forget()
    settings = Settings(AGENTICA_MODE="demo")
    assert platform_status.key_vault(settings)["status"] == "Not configured" and platform_status.search_service(settings)["status"] == "Not configured"
    rows = {row["id"]: row for row in platform_status.statuses(settings, {"gateway": [{}, {}]}, agents_ready=0, ai_configured=False)}
    assert rows["foundry"]["status"] == "Not configured" and "2 requests logged" in rows["gateway"]["description"] and rows["entra"]["status"] == "Local personas"
