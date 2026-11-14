"""The fix as checked code edits and a pull request (all offline; GitHub is faked)."""

import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import connectors
from backend.app import create_app
from backend.connectors import GitHubCode, Projects
from backend.domain import Settings
from backend.fix_delivery import build_patch, open_pull_request, replace_lines
from backend.mission import MissionTools, SimulatedBrain
from backend.store import Store
from backend.tests.test_connectors import archive
from backend.tests.test_missions import decide, login, mission, start

VIEWS = "def register(request):\n    return 'first'\n\n\ndef register(request):\n    return 'second'\n"
REPO = {"app/views.py": VIEWS, "app/crlf.py": "a = 1\r\nb = 2\r\n", ".github/workflows/ci.yml": "on: push\n", "app/.env": "KEY=1\n"}
EDIT = {"path": "app/views.py", "find": "\n\ndef register(request):\n    return 'second'  \n", "replace": ""}


class FakeGitHub:
    """Just enough of the GitHub API to read a repository and open a pull request."""

    def __init__(self, files=None, write_status=201):
        self.files = dict(files or REPO)
        self.calls: list[tuple[str, str]] = []
        self.branches: dict[str, dict[str, str]] = {}
        self.write_status = write_status
        self.pulls: list[dict] = []

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handle), follow_redirects=True)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.calls.append((method, path))
        body = json.loads(request.content) if request.content else {}
        if method == "GET" and "/tarball" in path:
            return httpx.Response(200, content=archive(self.files))
        if method == "GET" and "/commits" in path:
            return httpx.Response(200, json=[])
        if method == "GET" and path.endswith("/repos/o/r"):
            return httpx.Response(200, json={"default_branch": "main"})
        if method == "GET" and path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "base-sha"}})
        if method == "POST" and path.endswith("/git/refs"):
            name = body["ref"].removeprefix("refs/heads/")
            if name in self.branches:
                return httpx.Response(422, json={"message": "Reference already exists"})
            self.branches[name] = {}
            return httpx.Response(201, json={})
        if method == "DELETE" and "/git/refs/heads/" in path:
            self.branches.pop(path.split("/git/refs/heads/")[1], None)
            return httpx.Response(204)
        if "/contents/" in path:
            name = path.split("/contents/")[1]
            if method == "GET":
                return httpx.Response(200, json={"sha": f"sha-{name}", "content": base64.b64encode(self.files[name].encode()).decode()})
            if self.write_status != 201:
                return httpx.Response(self.write_status, json={"message": "no"})
            self.branches[body["branch"]][name] = base64.b64decode(body["content"]).decode()
            return httpx.Response(200, json={})
        if method == "POST" and path.endswith("/pulls"):
            self.pulls.append(body)
            return httpx.Response(201, json={"html_url": "https://github.com/o/r/pull/7", "number": 7})
        return httpx.Response(404)


@pytest.fixture(autouse=True)
def fresh_snapshots():
    connectors.forget_snapshots()
    yield
    connectors.forget_snapshots()


def code(github: FakeGitHub, pull_requests=True, token="t0ken") -> GitHubCode:
    return GitHubCode("o/r", token=token, client=github.client, pull_requests=pull_requests)


def test_lines_are_replaced_only_when_found_exactly_once():
    after, problem = replace_lines(VIEWS, "    return 'second'", "    return redirect('employee_list')")
    assert not problem and after.endswith("    return redirect('employee_list')\n") and "'first'" in after
    assert "appear 2 times" in replace_lines(VIEWS, "def register(request):", "x")[1]
    assert "not in the file" in replace_lines(VIEWS, "def login(request):", "x")[1]
    assert "changes nothing" in replace_lines(VIEWS, "    return 'second'", "    return 'second'")[1]
    assert "empty" in replace_lines(VIEWS, "\n\n", "x")[1]
    crlf, problem = replace_lines("a = 1\r\nb = 2\r\n", "b = 2", "b = 3")  # line endings of the file are kept
    assert not problem and crlf == "a = 1\r\nb = 3\r\n"


def test_patch_is_checked_against_the_real_files():
    github = FakeGitHub()
    patch = build_patch(code(github), [EDIT])
    assert patch["valid"] and patch["deliverable"] and patch["problems"] == []
    assert patch["files"][0]["path"] == "app/views.py" and patch["files"][0]["deletions"] >= 2 and "-    return 'second'" in patch["files"][0]["diff"]
    # Hidden files, pipelines and secrets are never editable; unknown lines are refused; nothing is deliverable then.
    bad = build_patch(code(github), [{"path": ".github/workflows/ci.yml", "find": "on: push", "replace": "on: pull_request_target"},
                                     {"path": "app/.env", "find": "KEY=1", "replace": "KEY=2"},
                                     {"path": "../../etc/passwd", "find": "root", "replace": "x"},
                                     {"path": "app/views.py", "find": "def nothing():", "replace": "x"}])
    assert not bad["valid"] and not bad["deliverable"] and len(bad["problems"]) == 4 and bad["files"] == []
    assert build_patch(code(github, pull_requests=False), [EDIT])["deliverable"] is False  # opt-in per project
    assert build_patch(code(github), [])["valid"] is False


def test_pull_request_goes_to_a_new_branch_and_never_to_the_base_branch():
    github = FakeGitHub()
    result = open_pull_request(code(github), [EDIT], "INC-1", "MSN-AB", "Fix INC-1: sign-up", "body")
    assert result["status"] == "OPENED" and result["number"] == 7 and result["branch"] == "behave/inc-1-msn-ab" and result["base"] == "main"
    assert github.branches["behave/inc-1-msn-ab"]["app/views.py"] == "def register(request):\n    return 'first'\n"
    assert github.pulls == [{"title": "Fix INC-1: sign-up", "head": "behave/inc-1-msn-ab", "base": "main", "body": "body"}]
    writes = [(method, path) for method, path in github.calls if method in {"PUT", "POST", "DELETE", "PATCH"}]
    assert writes == [("POST", "/repos/o/r/git/refs"), ("PUT", "/repos/o/r/contents/app/views.py"), ("POST", "/repos/o/r/pulls")]  # no merge, no push to main
    again = open_pull_request(code(github), [EDIT], "INC-1", "MSN-AB", "Fix INC-1: sign-up", "body")
    assert again["branch"] == "behave/inc-1-msn-ab-2"  # an existing branch is never overwritten


def test_pull_request_is_refused_safely():
    github = FakeGitHub()
    assert open_pull_request(code(github, pull_requests=False), [EDIT], "INC-1", "M", "t", "b")["status"] == "SKIPPED"
    assert "token" in open_pull_request(code(github, token=""), [EDIT], "INC-1", "M", "t", "b")["error"]
    assert not github.branches and not github.pulls
    # The file changed after approval: nothing is written at all.
    moved = FakeGitHub()
    target = code(moved)
    target.paths()
    moved.files["app/views.py"] = "def register(request):\n    return 'rewritten'\n"
    result = open_pull_request(target, [EDIT], "INC-1", "M", "t", "b")
    assert result["status"] == "FAILED" and "no longer applies" in result["error"] and not moved.branches
    # A refused write removes the half-made branch.
    denied = FakeGitHub(write_status=403)
    result = open_pull_request(code(denied), [EDIT], "INC-1", "M", "t", "b")
    assert result["status"] == "FAILED" and "may not write" in result["error"] and not denied.branches and not denied.pulls


class PatchingBrain(SimulatedBrain):
    """The simulated team, plus a remediation finding that carries a checked patch (as the AI brain produces)."""

    def __init__(self, source):
        self.source = source

    def work(self, context, step, members, prior):
        findings = super().work(context, step, members, prior)
        if "remediation" in findings:
            findings["remediation"]["patch"] = build_patch(self.source, [EDIT])
        return findings


def run_to_pull_request(github: FakeGitHub, pull_requests=True):
    store = Store("sqlite:///:memory:")
    application = create_app(Settings(AGENTICA_MODE="demo", AGENTICA_DEMO_STEP_SECONDS=0), store)
    projects = Projects([{"service": "checkout-svc", "code": {"type": "github", "repo": "o/r", "pull_requests": pull_requests}}], token="t0ken")
    source = code(github, pull_requests=pull_requests)
    projects._code = lambda settings: source
    application.state.mission_brain = PatchingBrain(source)
    application.state.mission_tools = MissionTools(None, projects)
    return application


def test_mission_opens_the_pull_request_only_after_the_fix_is_approved():
    github = FakeGitHub()
    with TestClient(run_to_pull_request(github)) as client:
        login(client)
        mission_id = start(client)
        assert decide(client, mission_id, "approve").status_code == 200  # team
        assert decide(client, mission_id, "approve").status_code == 200  # root cause
        gate = mission(client, mission_id)["pendingGate"]
        assert gate["type"] == "fix" and gate["patch"]["valid"] and gate["patch"]["deliverable"]
        assert "pull request on a new branch" in gate["recommendation"] and "-    return 'second'" in gate["patch"]["files"][0]["diff"]
        assert not github.pulls and not github.branches  # nothing is written before a human approves
        assert decide(client, mission_id, "approve").status_code == 403  # the starter may not approve their own fix
        assert not github.pulls
        login(client, "Change Approver")
        assert decide(client, mission_id, "approve").status_code == 200
        record = mission(client, mission_id)
        pull = record["iterations"][0]["pullRequest"]
        assert pull["status"] == "OPENED" and pull["url"] == "https://github.com/o/r/pull/7"
        assert len(github.pulls) == 1 and "### Root cause" in github.pulls[0]["body"] and "fix: approved by Sam Rivera" in github.pulls[0]["body"]
        assert any(event["type"] == "pull-request" for event in record["events"])
        report = client.get("/api/v1/incidents/INC-1042/resolution-report/pdf")
        assert report.status_code == 200 and report.content.startswith(b"%PDF")


def test_rejected_fix_and_projects_without_pull_requests_write_nothing():
    github = FakeGitHub()
    with TestClient(run_to_pull_request(github)) as client:
        login(client)
        mission_id = start(client)
        decide(client, mission_id, "approve")
        decide(client, mission_id, "approve")
        login(client, "Change Approver")
        assert decide(client, mission_id, "reject", note="Not convinced").status_code == 200
        assert not github.pulls and not github.branches
    quiet = FakeGitHub()
    with TestClient(run_to_pull_request(quiet, pull_requests=False)) as client:
        login(client)
        mission_id = start(client)
        decide(client, mission_id, "approve")
        decide(client, mission_id, "approve")
        gate = mission(client, mission_id)["pendingGate"]
        assert gate["patch"]["valid"] and not gate["patch"]["deliverable"] and "owning team applies it" in gate["recommendation"]
        login(client, "Change Approver")
        assert decide(client, mission_id, "approve").status_code == 200
        assert "pullRequest" not in mission(client, mission_id)["iterations"][0]
        assert not quiet.pulls and not quiet.branches
