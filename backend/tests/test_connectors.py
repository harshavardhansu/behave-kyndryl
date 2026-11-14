"""Connectors: any project is connected with configuration only (all offline; GitHub is faked)."""

import io
import json
import tarfile

import httpx
import pytest

from backend import connectors
from backend.connectors import GitHubCode, Projects, ensure_services, readable
from backend.investigation_tools import InvestigationTools
from backend.seed import seed_workspace

VIEWS = "def register(request):\n    return 'first'\n\n\ndef register(request):\n    return 'second'\n"
FILES = {
    "manage.py": "print('manage')\n",
    "app/employees/views.py": VIEWS,
    "app/employees/big.py": "\n".join(f"line_{n} = {n}" for n in range(1, 801)),
    "app/static/logo.png": "binary",
    "app/node_modules/x/index.js": "ignored()",
    "app/.env": "SECRET=1",
    "package-lock.json": "{}",
    "web/server.js": "const express = require('express')\n",
}


def archive(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"owner-repo-abc123/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("owner-repo-abc123/app/link.py")  # a symlink must never be followed
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        tar.addfile(link)
    return buffer.getvalue()


def fake_github(calls: list, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, request.headers.get("authorization", "")))
        if status != 200:
            return httpx.Response(status, json={"message": "nope"})
        if request.url.path.endswith("/tarball/main"):
            return httpx.Response(200, content=archive(FILES))
        if request.url.path.endswith("/commits"):
            return httpx.Response(200, json=[{"sha": "abcdef1234567", "commit": {"message": "Add second register view\n\ndetails", "author": {"name": "Dev", "date": "2026-11-10T08:00:00Z"}}}])
        if "/commits/" in request.url.path:
            return httpx.Response(200, json={"files": [{"filename": "app/employees/views.py"}]})
        return httpx.Response(404)

    return lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


@pytest.fixture(autouse=True)
def fresh_snapshots():
    connectors.forget_snapshots()
    yield
    connectors.forget_snapshots()


def test_only_source_files_are_readable():
    assert readable("src/api/Handler.java") and readable("web/server.js") and readable("Dockerfile")
    for path in (".env", "app/.git/config", "node_modules/x/index.js", "package-lock.json", "logo.png", "app/__pycache__/x.py", "dist/app.min.js"):
        assert not readable(path)


def test_github_repository_is_read_in_one_download_and_reused():
    calls: list = []
    code = GitHubCode("owner/repo", "main", token="t0ken", client=fake_github(calls))
    assert code.paths() == ["app/employees/big.py", "app/employees/views.py", "manage.py", "web/server.js"]
    assert code.read("app/employees/views.py") == VIEWS
    assert code.read("app/.env") is None and code.read("app/link.py") is None and code.read("../x") is None
    assert code.commits()[0] == {"id": "abcdef1", "title": "Add second register view", "author": "Dev", "timestamp": "2026-11-10T08:00:00Z", "files": ["app/employees/views.py"]}
    assert len(calls) == 3 and all(auth == "Bearer t0ken" for _, auth in calls)  # archive + commits + 1 commit detail
    GitHubCode("owner/repo", "main", client=fake_github(calls)).paths()
    assert len(calls) == 3  # the snapshot is reused


def test_github_subfolder_and_failures_are_reported_not_raised():
    code = GitHubCode("owner/repo", "main", path="app", client=fake_github([]))
    assert code.paths() == ["employees/big.py", "employees/views.py"]
    connectors.forget_snapshots()
    broken = GitHubCode("owner/private", "main", client=fake_github([], status=404))
    assert broken.paths() == [] and "not found" in broken.problem


def connected(monkeypatch) -> tuple[dict, dict, Projects]:
    projects = Projects([{"service": "employee-portal", "name": "Employee portal", "code": {"type": "github", "repo": "owner/repo", "ref": "main"}}])
    monkeypatch.setattr(connectors.GitHubCode, "__init__", _patched_init(connectors.GitHubCode.__init__))
    state = seed_workspace(True)
    assert ensure_services(state, projects, "2026-11-14T00:00:00Z") == ["employee-portal"]
    assert ensure_services(state, projects, "2026-11-14T00:00:00Z") == []  # only once
    incident = {"id": "INC-9001", "title": "Sign-up broken", "service": "employee-portal", "environment": "Production"}
    return state, incident, projects


def _patched_init(original):
    def init(self, *args, **kwargs):
        kwargs["client"] = fake_github([])
        original(self, *args, **kwargs)
    return init


def test_agents_investigate_a_github_project_through_the_same_tools(monkeypatch):
    state, incident, projects = connected(monkeypatch)
    tools = InvestigationTools(state, incident, projects=projects)
    listing = tools.call("list_repo_files", {})
    assert listing["source"] == "GitHub owner/repo@main" and "app/employees/views.py" in listing["files"]
    assert tools.call("list_repo_files", {"path": "web"})["files"] == ["web/server.js"]
    found = tools.call("search_repo", {"query": "def register"})
    assert found["total"] == 2 and found["matches"][0]["file"] == "app/employees/views.py:1"
    assert "second" in tools.call("read_repo_file", {"path": "views.py"})["text"]
    commit = next(row for row in tools.call("list_changes", {})["changes"] if row["kind"] == "commit")
    assert commit["title"] == "Add second register view" and commit["files"] == ["app/employees/views.py"]
    for bad in ("app/.env", "../../etc/passwd", "app/link.py"):
        assert "error" in tools.call("read_repo_file", {"path": bad})


def test_long_files_are_read_in_parts(monkeypatch):
    state, incident, projects = connected(monkeypatch)
    tools = InvestigationTools(state, incident, projects=projects)
    first = tools.call("read_repo_file", {"path": "app/employees/big.py"})
    assert first["from"] == 1 and first["totalLines"] == 800 and "start_line=" in first["note"]
    following = tools.call("read_repo_file", {"path": "app/employees/big.py", "start_line": first["to"] + 1})
    assert following["from"] == first["to"] + 1 and following["text"].startswith(f"line_{first['to'] + 1} ")
    assert len(json.dumps(following)) < 6000


def test_projects_file_is_configuration_only(tmp_path, monkeypatch):
    file = tmp_path / "projects.json"
    file.write_text(json.dumps({"projects": [
        {"service": "blog", "name": "Blog", "code": {"type": "github", "repo": "o/blog"}},
        {"service": "escape", "code": {"type": "folder", "path": "../../etc"}, "logs": {"type": "folder", "path": "/var/log"}},
        "not-a-project",
    ]}))
    monkeypatch.setenv("AGENTICA_GITHUB_TOKEN", "from-env")
    projects = Projects.load(file)
    assert [item["id"] for item in projects.services()] == ["blog", "escape"]
    blog = projects.resolve({"service": "blog"})
    assert isinstance(blog.code, GitHubCode) and blog.code.token == "from-env" and blog.logs.names() == []
    outside = projects.resolve({"service": "escape"})
    assert outside.code.paths() == [] and outside.logs.names() == []  # folders outside the project are refused
    (tmp_path / "broken.json").write_text("{not json")
    assert Projects.load(tmp_path / "broken.json").services() == []
    # Services without an entry keep the built-in demo sources.
    assert "app.py" in projects.resolve({"service": "payment-api", "environment": "Sandbox"}).code.paths()


def test_tools_forgive_common_agent_mistakes(monkeypatch):
    state, incident, projects = connected(monkeypatch)
    tools = InvestigationTools(state, incident, projects=projects)
    whole = tools.call("read_repo_file", {"path": "app/employees/views.py", "start_line": 1, "lines": 2})  # agents often ask for a few lines
    assert whole["complete"] is True and "'second'" in whole["text"]  # a file that fits is always returned whole
    part = tools.call("read_repo_file", {"path": "app/employees/big.py", "start_line": 5, "lines": 2})
    assert part["from"] == 5 and part["to"] == 6 and part["complete"] is False and "INCOMPLETE" in part["note"]
    missing = tools.call("list_repo_files", {"path": "src"})  # a folder that does not exist is not "no repository"
    assert "no folder 'src'" in missing["note"] and "app/employees/views.py" in missing["files"]
    assert all(call["ok"] for call in tools.trail)
