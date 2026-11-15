"""Engineering inputs (logs, source files, project ZIPs, repositories) and error intelligence. All offline."""

import io
import stat
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend import connectors
from backend.app import create_app
from backend.connectors import Projects
from backend.domain import Settings
from backend.error_intel import correlate, fingerprint, parse_errors
from backend.investigation_tools import InvestigationTools
from backend.store import Store
from backend.task_inputs import UnsafeArchive, inspect_zip
from backend.tests.test_fix_delivery import FakeGitHub
from backend.tests.test_missions import login

VIEWS = "from .models import Employee\n\n\ndef employee_list(request):\n    employees = Employee.objects.all()\n    return render(request, 'list.html', {'employees': employees})\n"
PY_LOG = """2026-11-14T09:12:01Z INFO request started
2026-11-14T09:12:02Z ERROR Internal Server Error: /employees/ request_id=abc-1234
Traceback (most recent call last):
  File "/app/portal/employees/views.py", line 5, in employee_list
    employees = Employee.objects.all()
  File "/usr/lib/python3.12/site-packages/django/db/backends/utils.py", line 89, in _execute
    return self.cursor.execute(sql, params)
django.db.utils.OperationalError: no such table: employees_employee
2026-11-14T09:13:02Z ERROR Internal Server Error: /employees/ request_id=abc-9999
Traceback (most recent call last):
  File "/app/portal/employees/views.py", line 5, in employee_list
    employees = Employee.objects.all()
django.db.utils.OperationalError: no such table: employees_employee
2026-11-14T09:14:00Z WARN slow response 900ms
"""
JAVA_LOG = """2026-11-14 10:00:01,123 ERROR [exec-3] c.a.checkout.OrderService - Failed to place order 4411
java.sql.SQLTransientConnectionException: HikariPool-1 - Connection is not available, request timed out after 30000ms.
\tat com.zaxxer.hikari.pool.HikariPool.createTimeoutException(HikariPool.java:696)
\tat com.acme.checkout.OrderService.placeOrder(OrderService.java:88)
Caused by: java.net.SocketTimeoutException: connect timed out
"""
JS_LOG = """TypeError: Cannot read properties of null (reading 'title')
    at /srv/blog/app.js:52:25
    at Layer.handle [as handle_request] (/srv/blog/node_modules/express/lib/router/layer.js:95:5)
{"timestamp":"2026-11-14T11:00:00Z","level":"error","message":"payment declined for order 77","requestId":"r-778899"}
{"timestamp":"2026-11-14T11:00:01Z","level":"info","message":"fine"}
"""


def make_zip(files: dict[str, str | bytes], links: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
        for name, target in (links or {}).items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, target)
    return buffer.getvalue()


PROJECT = {
    "portal/manage.py": "import django\n",
    "portal/requirements.txt": "Django==5.1\npytest\n",
    "portal/employees/views.py": VIEWS,
    "portal/employees/tests/test_views.py": "def test_list():\n    assert True\n",
    "portal/logs/app.log": PY_LOG,
    "portal/.env": "SECRET_KEY=never-read\n",
    "portal/node_modules/x/index.js": "ignored()",
    "portal/static/logo.png": b"\x89PNG\x00\x00binary",
}


@pytest.fixture
def client():
    with TestClient(create_app(Settings(AGENTICA_MODE="demo", AGENTICA_DEMO_STEP_SECONDS=0), Store("sqlite:///:memory:"))) as test_client:
        login(test_client)
        yield test_client


def new_task(client, **extra) -> str:
    body = {"title": "Employee list page fails with a server error", "description": "Opening the employee list returns a 500 error since this morning for every user.",
            "severity": "High", "environment": "Production", "service": "hr-portal", "impact": "Nobody in HR can see the employee list.",
            "detectedAt": "2026-11-14T09:15:00+00:00", **extra}
    response = client.post("/api/v1/incidents", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload(client, incident_id: str, name: str, content: bytes):
    return client.post(f"/api/v1/incidents/{incident_id}/evidence/upload", files={"file": (name, content)})


# -- logs ----------------------------------------------------------------------


def test_errors_are_parsed_from_python_java_javascript_and_json_logs():
    python = parse_errors(PY_LOG)
    assert [event["type"] for event in python] == ["django.db.utils.OperationalError"] * 2  # INFO and WARN lines are not errors
    assert python[0]["timestamp"] == "2026-11-14T09:12:02Z" and python[0]["requestId"] == "abc-1234" and python[0]["category"] == "Database"
    assert python[0]["frames"][0] == {"file": "/app/portal/employees/views.py", "line": 5, "function": "employee_list"}
    assert fingerprint(python[0]) == fingerprint(python[1])  # same error, different request: one issue
    java = parse_errors(JAVA_LOG)
    assert len(java) == 1 and java[0]["type"] == "java.sql.SQLTransientConnectionException" and java[0]["message"].endswith("Failed to place order 4411")
    assert java[0]["frames"][1] == {"file": "com/acme/checkout/OrderService.java", "line": 88, "function": "placeOrder"}
    script = parse_errors(JS_LOG)
    assert [event["type"] for event in script] == ["TypeError", ""] and script[0]["frames"][0]["file"] == "/srv/blog/app.js"
    assert script[1]["requestId"] == "r-778899" and script[1]["timestamp"] == "2026-11-14T11:00:00Z" and script[1]["severity"] == "Medium"
    assert parse_errors("all good\n2026-11-14T09:12:01Z INFO started\n") == []
    assert fingerprint(java[0]) != fingerprint(python[0])


def test_missing_information_is_left_empty_not_invented():
    event = parse_errors("ValueError: bad input\n")[0]
    assert event["timestamp"] == "" and event["frames"] == [] and event["requestId"] == ""


# -- archives ------------------------------------------------------------------


def test_zip_is_read_without_unpacking_and_only_source_and_logs_are_kept():
    report = inspect_zip(make_zip(PROJECT, links={"portal/link.py": "/etc/passwd"}))
    assert sorted(report["sources"]) == ["employees/tests/test_views.py", "employees/views.py", "manage.py", "requirements.txt"]  # wrapping folder removed
    assert list(report["logs"]) == ["logs/app.log"] and report["skipped"] >= 3  # .env, node_modules and the image are never read


@pytest.mark.parametrize("name", ["../../etc/passwd", "/etc/passwd", "a/../../b.py", "C:\\Windows\\x.py"])
def test_archives_with_paths_that_escape_are_refused(name):
    with pytest.raises(UnsafeArchive):
        inspect_zip(make_zip({name: "x = 1\n"}))


def test_bombs_and_non_archives_are_refused():
    with pytest.raises(UnsafeArchive, match="suspiciously compressed"):
        inspect_zip(make_zip({"big.py": "a" * 30_000_000}))
    with pytest.raises(UnsafeArchive, match="not a valid ZIP"):
        inspect_zip(b"PK00 not really")


# -- the whole path: upload, understand, track, locate ---------------------------


def test_project_zip_becomes_readable_source_tracked_errors_and_a_located_stack_trace(client):
    task = new_task(client)
    before = client.get(f"/api/v1/incidents/{task}/readiness").json()
    assert before["hasSource"] is False and "Attach an error log" in before["message"]

    response = upload(client, task, "portal.zip", make_zip(PROJECT))
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["sourceFiles"] == 4 and record["logFiles"] == 1 and len(record["errorGroups"]) == 1 and "never-read" not in response.text

    state = client.get("/api/v1/workspace").json()
    incident = next(item for item in state["incidents"] if item["id"] == task)
    assert incident["project"]["frameworks"] == ["Django"] and incident["project"]["languages"][0]["name"] == "Python"
    assert incident["project"]["entryPoints"] == ["manage.py"] and incident["project"]["tests"] == {"frameworks": ["pytest"], "files": 1}
    issue = next(item for item in state["errors"] if task in item["incidentIds"])
    assert issue["count"] == 2 and issue["type"] == "django.db.utils.OperationalError" and issue["severity"] == "High" and issue["status"] == "Open"
    assert issue["firstSeen"] == "2026-11-14T09:12:02Z" and issue["lastSeen"] == "2026-11-14T09:13:02Z" and issue["service"] == "hr-portal"
    assert any(service["id"] == "hr-portal" for service in state["services"])  # a new application is added to the catalog

    ready = client.get(f"/api/v1/incidents/{task}/readiness").json()
    assert ready["hasSource"] and ready["sourceFiles"] == 4 and ready["errorGroups"] == 1 and ready["missing"] == [] and ready["canOpenPullRequest"] is False

    located = client.get(f"/api/v1/errors/{issue['id']}/source").json()
    assert located["matches"][0]["path"] == "employees/views.py" and located["matches"][0]["line"] == 5
    assert next(row for row in located["matches"][0]["snippet"] if row["hit"])["text"].strip() == "employees = Employee.objects.all()"
    assert all("site-packages" not in match["path"] for match in located["matches"])  # library frames are not in the project

    # The agents see the same thing through their read-only tools.
    tools = InvestigationTools(client.app.state.store.read(), incident)
    assert "employees/views.py" in tools.call("list_repo_files", {})["files"] and tools.call("get_ticket", {})["project"]["frameworks"] == ["Django"]
    groups = tools.call("get_error_groups", {})
    assert groups["errors"][0]["occurrences"] == 2 and groups["errors"][0]["inSource"][0]["path"] == "employees/views.py" and "5>" in groups["errors"][0]["inSource"][0]["code"]

    # The same log again raises the count, not the number of issues.
    assert upload(client, task, "again.log", PY_LOG.encode()).status_code == 201
    errors = [item for item in client.get("/api/v1/workspace").json()["errors"] if task in item["incidentIds"]]
    assert len(errors) == 1 and errors[0]["count"] == 4


def test_logs_alone_ask_for_the_source_and_never_claim_a_location(client):
    task = new_task(client)
    assert upload(client, task, "server.log", JAVA_LOG.encode()).status_code == 201
    readiness = client.get(f"/api/v1/incidents/{task}/readiness").json()
    assert readiness["hasSource"] is False and readiness["errorGroups"] == 1
    assert "1 error group found" in readiness["message"] and "source code is not included" in readiness["message"]
    issue = next(item for item in client.get("/api/v1/workspace").json()["errors"] if task in item["incidentIds"])
    assert "No source code is connected" in client.get(f"/api/v1/errors/{issue['id']}/source").json()["note"]
    started = client.post(f"/api/v1/incidents/{task}/missions")
    assert started.status_code == 201
    mission = next(item for item in client.get("/api/v1/workspace").json()["missions"] if item["id"] == started.json()["missionId"])
    assert any(event["type"] == "no-source" for event in mission["events"])


def test_single_source_file_and_pasted_stack_trace(client):
    task = new_task(client, error=JS_LOG.splitlines()[0] + "\n" + JS_LOG.splitlines()[1])
    issue = next(item for item in client.get("/api/v1/workspace").json()["errors"] if task in item["incidentIds"])
    assert issue["type"] == "TypeError" and issue["count"] == 1
    source = "\n".join(f"// line {number}" for number in range(1, 60)).encode()
    assert upload(client, task, "app.js", source).status_code == 201
    incident = next(item for item in client.get("/api/v1/workspace").json()["incidents"] if item["id"] == task)
    assert incident["sourceUploads"][0]["kind"] == "file" and incident["project"]["languages"] == [{"name": "JavaScript", "files": 1}]
    located = client.get(f"/api/v1/errors/{issue['id']}/source").json()
    assert located["matches"][0]["path"] == "app.js" and located["matches"][0]["line"] == 52


def test_error_status_and_upload_rules(client):
    task = new_task(client)
    upload(client, task, "server.log", JAVA_LOG.encode())
    issue = next(item for item in client.get("/api/v1/workspace").json()["errors"] if task in item["incidentIds"])
    done = client.patch(f"/api/v1/errors/{issue['id']}", json={"status": "Resolved", "note": "pool resized"})
    assert done.status_code == 200 and done.json()["status"] == "Resolved" and done.json()["statusBy"] == "Alex Morgan"
    upload(client, task, "later.log", JAVA_LOG.encode())  # it happens again: reopened
    assert next(item for item in client.get("/api/v1/workspace").json()["errors"] if item["id"] == issue["id"])["status"] == "Open"
    login(client, "Viewer")
    assert client.patch(f"/api/v1/errors/{issue['id']}", json={"status": "Ignored"}).status_code == 403
    assert upload(client, task, "x.log", b"ERROR nope").status_code == 403
    login(client)
    assert upload(client, task, "evil.zip", make_zip({"../../escape.py": "x"})).status_code == 422
    assert upload(client, task, "empty.zip", make_zip({"logo.png": b"\x89PNG\x00"})).status_code == 422
    assert client.post("/api/v1/incidents", json={"title": "A valid title here", "description": "A long enough description of it.", "severity": "Low", "environment": "Production",
                                                  "service": "../etc", "impact": "Some impact.", "detectedAt": "2026-11-14T09:15:00+00:00"}).status_code == 422


def test_a_repository_named_on_a_task_is_read_without_the_server_token(client, monkeypatch):
    github = FakeGitHub({"src/app.py": "print('hi')\n", "requirements.txt": "flask\n"})
    seen: list[str] = []

    def fake_init(self, repo, ref="", path="", api="https://api.github.com", token="", client=None, pull_requests=False):
        seen.append(token)
        original(self, repo, ref, path, api, token=token, client=github.client, pull_requests=pull_requests)

    original = connectors.GitHubCode.__init__
    monkeypatch.setattr(connectors.GitHubCode, "__init__", fake_init)
    monkeypatch.setattr(Projects, "load", classmethod(lambda cls, path=None: Projects([], token="server-secret", storage=None)))
    task = new_task(client, repository={"repo": "o/r", "ref": "main"})
    incident = next(item for item in client.get("/api/v1/workspace").json()["incidents"] if item["id"] == task)
    assert incident["repository"] == {"repo": "o/r", "ref": "main", "path": ""} and incident["project"]["frameworks"] == ["Flask"]
    assert seen and set(seen) == {""}  # the server's token is never used for a repository a user typed in
    code = Projects([], token="server-secret").resolve(incident).code
    assert code.pull_requests is False
    bad = client.post("/api/v1/incidents", json={"title": "A valid title here", "description": "A long enough description of it.", "severity": "Low", "environment": "Production",
                                                 "service": "x", "impact": "Some impact.", "detectedAt": "2026-11-14T09:15:00+00:00", "repository": {"repo": "not a repo"}})
    assert bad.status_code == 422


def test_correlate_refuses_ambiguous_file_names():
    class Code:
        label = "test"

        def paths(self):
            return ["a/views.py", "b/views.py"]

        def read(self, path):
            return "x = 1\n"

    result = correlate({"frames": [{"file": "views.py", "line": 1, "function": "f"}]}, Code())
    assert result["matches"] == [] and "None of the files" in result["note"]
