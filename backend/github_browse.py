"""Browse GitHub to pick what a task should read: a repository, a branch, a commit and a project folder.

Rules (the same as for reading code):

- A repository an administrator connected in ``projects.json`` is looked up with the server's token,
  so it can be private. It is listed first and marked ``connected``.
- Any other repository is looked up **without** a token: only public repositories are visible, and
  GitHub allows about 60 such requests an hour per server, so answers are cached briefly.
- Everything is read-only. Nothing returned here is ever executed.
"""

import re
import time
from threading import Lock
from typing import Any, Callable

import httpx

from .connectors import Projects

API = "https://api.github.com"
REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")
OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
CACHE_SECONDS = 90
MANIFESTS = ("package.json", "requirements.txt", "pyproject.toml", "pom.xml", "build.gradle", "build.gradle.kts", "go.mod",
             "Cargo.toml", "composer.json", "Gemfile", "manage.py", "Dockerfile", "Containerfile", "setup.py", "Pipfile")

_cache: dict[tuple, tuple[float, Any]] = {}
_lock = Lock()


class GitHubLookupError(Exception):
    """A lookup failed. The message is safe to show to the person."""


def forget() -> None:
    with _lock:
        _cache.clear()


class GitHubBrowser:
    def __init__(self, projects: Projects | None = None, client: Callable[[], httpx.Client] | None = None, api: str = API):
        self.projects = projects or Projects.load()
        self.api = api.rstrip("/")
        self._client = client or (lambda: httpx.Client(timeout=15, follow_redirects=True))

    # -- which repositories may use the server's token ---------------------

    def connected(self) -> list[dict]:
        rows = []
        for service, entry in self.projects.entries.items():
            code = entry.get("code") or {}
            if code.get("type") == "github" and REPO.match(str(code.get("repo", ""))):
                rows.append({"repo": code["repo"], "service": service, "name": entry.get("name") or service, "ref": code.get("ref") or "",
                             "path": code.get("path") or "", "connected": True, "pullRequests": code.get("pull_requests") is True})
        return rows

    def _token_for(self, repo: str) -> str:
        return self.projects.token if any(row["repo"].lower() == repo.lower() for row in self.connected()) else ""

    def _get(self, path: str, repo: str = "", params: dict | None = None) -> Any:
        token = self._token_for(repo) if repo else ""
        key = (self.api, path, tuple(sorted((params or {}).items())), bool(token))
        with _lock:
            cached = _cache.get(key)
            if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
                return cached[1]
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "incident-investigator"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            with self._client() as client:
                response = client.get(f"{self.api}{path}", headers=headers, params=params)
        except httpx.HTTPError as error:
            raise GitHubLookupError(f"GitHub could not be reached ({type(error).__name__}).") from None
        if response.status_code == 404:
            raise GitHubLookupError("Not found. A private repository must be connected by an administrator before it can be read.")
        if response.status_code in (403, 429):
            limited = response.headers.get("x-ratelimit-remaining") == "0"
            raise GitHubLookupError("GitHub's limit for lookups without a token is used up; try again later, or ask an administrator to connect the repository."
                              if limited else "GitHub refused the request.")
        if response.status_code >= 400:
            raise GitHubLookupError(f"GitHub answered {response.status_code}.")
        value = response.json()
        with _lock:
            _cache[key] = (time.monotonic(), value)
        return value

    # -- lookups --------------------------------------------------------------

    def repositories(self, query: str = "") -> dict:
        """Connected repositories, plus the public repositories of an owner (``acme``) or one exact repository (``acme/shop``)."""
        query = query.strip().strip("/").removeprefix("https://github.com/").removesuffix(".git")
        rows = self.connected()
        found: list[dict] = []
        if REPO.match(query):
            item = self._get(f"/repos/{query}", query)
            found = [item]
        elif OWNER.match(query):
            found = self._get(f"/users/{query}/repos", params={"type": "owner", "sort": "updated", "per_page": 30})
        elif query:
            raise GitHubLookupError("Type an owner (for example acme) or a repository (acme/shop-api).")
        known = {row["repo"].lower() for row in rows}
        for item in found if isinstance(found, list) else []:
            name = str(item.get("full_name", ""))
            if not REPO.match(name) or name.lower() in known or item.get("fork") and query and "/" not in query:
                continue
            rows.append({"repo": name, "name": name.split("/", 1)[1], "description": str(item.get("description") or "")[:160],
                         "language": item.get("language") or "", "private": bool(item.get("private")), "defaultBranch": item.get("default_branch") or "",
                         "updatedAt": item.get("pushed_at") or item.get("updated_at") or "", "connected": False, "pullRequests": False})
        return {"repositories": rows[:40]}

    def branches(self, repo: str) -> dict:
        self._check(repo)
        info = self._get(f"/repos/{repo}", repo)
        items = self._get(f"/repos/{repo}/branches", repo, {"per_page": 100})
        default = info.get("default_branch") or ""
        names = [str(item.get("name")) for item in items if item.get("name")]
        names.sort(key=lambda name: (name != default, name.lower()))
        return {"repo": repo, "defaultBranch": default, "private": bool(info.get("private")), "branches": names[:100]}

    def commits(self, repo: str, ref: str = "") -> dict:
        self._check(repo)
        params: dict[str, Any] = {"per_page": 15}
        if ref:
            params["sha"] = self._ref(ref)
        rows = []
        for item in self._get(f"/repos/{repo}/commits", repo, params):
            commit = item.get("commit") or {}
            rows.append({"sha": str(item.get("sha", "")), "short": str(item.get("sha", ""))[:7], "title": str(commit.get("message", "")).split("\n", 1)[0][:140],
                         "author": str((commit.get("author") or {}).get("name", ""))[:60], "date": (commit.get("author") or {}).get("date", "")})
        return {"repo": repo, "ref": ref, "commits": rows}

    def folders(self, repo: str, ref: str = "") -> dict:
        """Folders that look like a project of their own (they hold a manifest such as package.json), for monorepos."""
        self._check(repo)
        target = self._ref(ref) if ref else self.branches(repo)["defaultBranch"]
        tree = self._get(f"/repos/{repo}/git/trees/{target}", repo, {"recursive": "1"})
        projects: dict[str, list[str]] = {}
        for item in tree.get("tree", []):
            path = str(item.get("path", ""))
            name = path.rsplit("/", 1)[-1]
            if item.get("type") == "blob" and name in MANIFESTS and "node_modules/" not in path and path.count("/") <= 4:
                folder = path.rsplit("/", 1)[0] if "/" in path else ""
                projects.setdefault(folder, []).append(name)
        rows = [{"path": folder, "markers": sorted(set(names))[:4]} for folder, names in sorted(projects.items())]
        return {"repo": repo, "ref": target, "folders": rows[:60], "truncated": bool(tree.get("truncated"))}

    @staticmethod
    def _check(repo: str) -> None:
        if not REPO.match(repo):
            raise GitHubLookupError("Give the repository as owner/name.")

    @staticmethod
    def _ref(ref: str) -> str:
        if not re.match(r"^[A-Za-z0-9._/-]{1,200}$", ref) or ".." in ref:
            raise GitHubLookupError("That branch or commit name is not valid.")
        return ref
