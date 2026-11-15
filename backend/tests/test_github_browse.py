"""Picking a repository, branch, commit and folder on GitHub (all offline; GitHub is faked)."""

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import github_browse
from backend.app import create_app
from backend.connectors import Projects
from backend.domain import Settings
from backend.github_browse import GitHubBrowser, GitHubLookupError
from backend.store import Store
from backend.tests.test_missions import login


class FakeAPI:
    def __init__(self, limited: bool = False):
        self.calls: list[tuple[str, str]] = []
        self.limited = limited

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((path, request.headers.get("authorization", "")))
        if self.limited:
            return httpx.Response(403, headers={"x-ratelimit-remaining": "0"}, json={"message": "rate limit"})
        if path == "/users/acme/repos":
            return httpx.Response(200, json=[
                {"full_name": "acme/shop", "description": "Shop API", "language": "Python", "private": False, "default_branch": "main", "pushed_at": "2026-11-01T00:00:00Z"},
                {"full_name": "acme/fork-of-x", "fork": True},
                {"full_name": "acme/internal", "private": False, "default_branch": "trunk"},
            ])
        if path in ("/repos/acme/shop", "/repos/acme/internal"):
            return httpx.Response(200, json={"full_name": path[7:], "default_branch": "trunk" if "internal" in path else "main", "private": "internal" in path})
        if path.endswith("/branches"):
            return httpx.Response(200, json=[{"name": "feature/x"}, {"name": "main"}, {"name": "Develop"}])
        if path.endswith("/commits"):
            return httpx.Response(200, json=[{"sha": "abcdef1234567890", "commit": {"message": "Fix login\n\nbody", "author": {"name": "Dev", "date": "2026-11-10T00:00:00Z"}}}])
        if "/git/trees/" in path:
            return httpx.Response(200, json={"truncated": False, "tree": [
                {"path": "package.json", "type": "blob"}, {"path": "services/api/requirements.txt", "type": "blob"}, {"path": "services/api/manage.py", "type": "blob"},
                {"path": "web/node_modules/x/package.json", "type": "blob"}, {"path": "docs/readme.md", "type": "blob"},
            ]})
        return httpx.Response(404, json={"message": "Not Found"})


@pytest.fixture(autouse=True)
def fresh_cache():
    github_browse.forget()
    yield
    github_browse.forget()


def browser(api: FakeAPI) -> GitHubBrowser:
    projects = Projects([{"service": "internal-svc", "name": "Internal", "code": {"type": "github", "repo": "acme/internal", "ref": "trunk", "pull_requests": True}}], token="server-token")
    return GitHubBrowser(projects, client=api.client)


def test_connected_repositories_come_first_and_public_ones_are_found_by_owner():
    api = FakeAPI()
    rows = browser(api).repositories("acme")["repositories"]
    assert [row["repo"] for row in rows] == ["acme/internal", "acme/shop"]  # connected first; forks of an owner are left out; no duplicates
    assert rows[0]["connected"] and rows[0]["pullRequests"] and rows[0]["ref"] == "trunk"
    assert rows[1] == {"repo": "acme/shop", "name": "shop", "description": "Shop API", "language": "Python", "private": False, "defaultBranch": "main",
                       "updatedAt": "2026-11-01T00:00:00Z", "connected": False, "pullRequests": False}
    assert api.calls == [("/users/acme/repos", "")]  # an owner listing never sends the server's token
    assert [row["repo"] for row in browser(FakeAPI()).repositories("https://github.com/acme/shop.git")["repositories"]] == ["acme/internal", "acme/shop"]
    assert [row["repo"] for row in browser(FakeAPI()).repositories("")["repositories"]] == ["acme/internal"]


def test_the_token_is_used_only_for_connected_repositories():
    api = FakeAPI()
    lookups = browser(api)
    assert lookups.branches("acme/internal")["private"] is True
    assert lookups.branches("acme/shop")["branches"] == ["main", "Develop", "feature/x"]  # default branch first
    assert {auth for path, auth in api.calls if "internal" in path} == {"Bearer server-token"}
    assert {auth for path, auth in api.calls if "shop" in path} == {""}


def test_commits_and_project_folders():
    lookups = browser(FakeAPI())
    commit = lookups.commits("acme/shop", "main")["commits"][0]
    assert commit == {"sha": "abcdef1234567890", "short": "abcdef1", "title": "Fix login", "author": "Dev", "date": "2026-11-10T00:00:00Z"}
    folders = lookups.folders("acme/shop", "main")
    assert folders["folders"] == [{"path": "", "markers": ["package.json"]}, {"path": "services/api", "markers": ["manage.py", "requirements.txt"]}]  # vendored code ignored


def test_bad_input_and_github_limits_give_plain_messages():
    lookups = browser(FakeAPI())
    for bad in ("not a repo", "../etc"):
        with pytest.raises(GitHubLookupError):
            lookups.repositories(bad)
    with pytest.raises(GitHubLookupError, match="owner/name"):
        lookups.branches("nope")
    with pytest.raises(GitHubLookupError, match="not valid"):
        lookups.commits("acme/shop", "../../x")
    with pytest.raises(GitHubLookupError, match="administrator"):
        lookups.branches("acme/missing")
    with pytest.raises(GitHubLookupError, match="limit"):
        browser(FakeAPI(limited=True)).repositories("acme")


def test_lookup_endpoints_need_permission_to_create_tasks(monkeypatch):
    api = FakeAPI()
    monkeypatch.setattr(Projects, "load", classmethod(lambda cls, path=None: Projects([], token="server-token")))
    monkeypatch.setattr(github_browse.GitHubBrowser, "__init__", _with_client(github_browse.GitHubBrowser.__init__, api))
    with TestClient(create_app(Settings(AGENTICA_MODE="demo"), Store("sqlite:///:memory:"))) as client:
        login(client)
        assert [row["repo"] for row in client.get("/api/v1/github/repositories", params={"q": "acme"}).json()["repositories"]] == ["acme/shop", "acme/internal"]
        assert client.get("/api/v1/github/repositories/acme/shop/branches").json()["defaultBranch"] == "main"
        assert client.get("/api/v1/github/repositories/acme/shop/commits", params={"ref": "main"}).json()["commits"][0]["short"] == "abcdef1"
        assert client.get("/api/v1/github/repositories/acme/shop/folders", params={"ref": "main"}).status_code == 200
        problem = client.get("/api/v1/github/repositories/acme/missing/branches")
        assert problem.status_code == 422 and "administrator" in problem.json()["detail"]
        login(client, "Viewer")
        assert client.get("/api/v1/github/repositories", params={"q": "acme"}).status_code == 403


def _with_client(original, api):
    def init(self, projects=None, client=None, api_url=github_browse.API):
        original(self, projects, api.client)
    return init


def test_repository_scan_reports_real_problems_only():
    from backend.repo_analyzer import scan_repository

    class Code:
        label = "test repository"
        files = {
            "app/settings.py": "SECRET_KEY = 'django-insecure-abcdefghijklmnop'\nDEBUG = True\nALLOWED_HOSTS = ['*']\n",
            "app/views.py": "def index(request):\n    return render(request, 'index.html')\n",
            "README.md": "hello\n",
        }

        def paths(self):
            return list(self.files)

        def read(self, path):
            return self.files.get(path)

    findings, scanned = scan_repository(Code(), ["Security", "Configuration", "Code paths"])
    assert scanned == 3
    assert [(f["file"], f["line"], f["title"]) for f in findings] == [
        ("app/settings.py", 1, "Hardcoded credential or token detected"),
        ("app/settings.py", 2, "Debug mode switched on in settings"),
        ("app/settings.py", 3, "Any host name accepted (ALLOWED_HOSTS = ['*'])"),
    ]  # clean files produce nothing: "looks fine" notes are not findings
    assert "abcdefghijklmnop" not in str(findings) and findings[0]["evidence"][0].endswith("SECRET_KEY = '***'")
