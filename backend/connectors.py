"""Connectors: how the agents reach a project's code and logs, whatever the project is.

The investigation tools never touch a specific system. They ask a ``Project`` for two things:

- a **code source** (list files, read a file, recent commits), and
- a **log source** (list log files, read their lines).

A connector translates those calls to where the project really lives. Today:

- ``LocalCode`` / ``LocalLogs``: folders on this machine (the Payment API sandbox and the sample services),
- ``GitHubCode``: any GitHub repository, in any language, read over the GitHub API (read-only).

A project is connected with configuration only, never code: one entry in ``projects.json``
(see ``projects.example.json``). Nothing in the project itself has to change.

Everything here is **read-only**. Text that comes from a repository or a log is data for the
agents to read, never instructions.
"""

import io
import json
import logging
import os
import subprocess
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Callable

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PAYMENT_REPO = PROJECT_ROOT / "payment_api"       # the live Payment API sandbox source
SAMPLE_ROOT = PROJECT_ROOT / "sample_services"    # demo repos and logs: scripts/generate_sample_services.py

READABLE_SUFFIXES = {
    ".py", ".txt", ".md", ".example", ".yml", ".yaml", ".java", ".kt", ".properties", ".options", ".json", ".toml", ".sql",
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".html", ".ejs", ".css", ".scss", ".vue", ".go", ".rb", ".php", ".cs",
    ".c", ".h", ".cpp", ".hpp", ".rs", ".swift", ".scala", ".sh", ".xml", ".gradle", ".ini", ".cfg", ".conf", ".tf", ".bicep",
}
READABLE_NAMES = {"Dockerfile", "Containerfile", "Makefile", "Procfile", "Jenkinsfile"}
SKIPPED_FOLDERS = {"node_modules", "vendor", "dist", "build", "target", "venv", "env", "site-packages", "coverage"}
SKIPPED_ENDINGS = ("-lock.json", ".lock", ".min.js", ".min.css", ".map")
MAX_FILE_BYTES = 200_000       # one source file
MAX_FILES = 400                # per repository snapshot
MAX_DOWNLOAD_BYTES = 15_000_000
SNAPSHOT_SECONDS = 600         # how long a GitHub snapshot is reused before it is fetched again

log = logging.getLogger("behave.connectors")


_cli_token: list[str] = []


def github_token() -> str:
    """The GitHub token: AGENTICA_GITHUB_TOKEN, or (local development only, when AGENTICA_GITHUB_USE_CLI
    is on) the token of the GitHub CLI signed in on this machine. It is kept in memory only."""
    from .domain import Settings

    settings = Settings()
    token = settings.github_token.get_secret_value()
    if token or not settings.github_use_cli:
        return token
    if not _cli_token:
        try:
            result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10, check=False)
            _cli_token.append(result.stdout.strip() if result.returncode == 0 else "")
        except (OSError, subprocess.SubprocessError):
            _cli_token.append("")
    return _cli_token[0]


def readable(path: str) -> bool:
    """True for source and configuration files an agent may read (no hidden, binary, vendored or lock files)."""
    parts = path.split("/")
    name = parts[-1]
    if any(part.startswith((".", "__")) or part in SKIPPED_FOLDERS for part in parts):
        return False
    if name.endswith(SKIPPED_ENDINGS):
        return False
    return name in READABLE_NAMES or Path(name).suffix.lower() in READABLE_SUFFIXES


# -- code sources ---------------------------------------------------------


class NoCode:
    """No repository is connected for this service."""

    label = ""
    problem = ""
    pull_requests = False

    def paths(self) -> list[str]:
        return []

    def read(self, path: str) -> str | None:
        return None

    def commits(self) -> list[dict]:
        return []


class LocalCode(NoCode):
    """A folder on this machine."""

    def __init__(self, root: Path, label: str = ""):
        self.root = root
        self.label = label or f"local folder {root.name}"

    def _files(self) -> dict[str, Path]:
        if not self.root.is_dir():
            return {}
        files: dict[str, Path] = {}
        for path in sorted(self.root.rglob("*")):
            relative = path.relative_to(self.root).as_posix()
            if path.is_file() and readable(relative):
                files[relative] = path
        return files

    def paths(self) -> list[str]:
        return list(self._files())

    def read(self, path: str) -> str | None:
        match = self._files().get(path)  # only a listed file can be read: no path can escape the folder
        return match.read_text(encoding="utf-8", errors="replace") if match else None


_snapshots: dict[tuple, tuple[float, dict]] = {}
_snapshot_lock = Lock()


class GitHubCode(NoCode):
    """A GitHub repository, read through the GitHub API. Works for any language: files are read as text.

    One download (the repository archive) gives the file list and every file's text, so searching
    costs no extra requests; the snapshot is reused for a few minutes. A token is optional for public
    repositories and is read from the environment only (``AGENTICA_GITHUB_TOKEN``), never from a file.
    """

    def __init__(self, repo: str, ref: str = "", path: str = "", api: str = "https://api.github.com",
                 token: str = "", client: Callable[[], httpx.Client] | None = None, pull_requests: bool = False):
        self.repo = repo.strip().strip("/")
        self.ref = ref.strip()
        self.subfolder = path.strip().strip("/")
        self.api = api.rstrip("/")
        self.token = token
        self.pull_requests = pull_requests  # may an approved fix be delivered as a pull request? (opt-in per project)
        self._client = client or (lambda: httpx.Client(timeout=20, follow_redirects=True))
        self.label = f"GitHub {self.repo}" + (f"@{self.ref}" if self.ref else "") + (f" /{self.subfolder}" if self.subfolder else "")
        self.problem = ""

    def _headers(self) -> dict:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "incident-investigator"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _inside(self, path: str) -> str | None:
        """The path relative to the configured subfolder, or None when it lies outside it."""
        if not self.subfolder:
            return path
        return path[len(self.subfolder) + 1:] if path.startswith(self.subfolder + "/") else None

    def _download(self) -> dict:
        files: dict[str, str] = {}
        with self._client() as client:
            url = f"{self.api}/repos/{self.repo}/tarball" + (f"/{self.ref}" if self.ref else "")
            with client.stream("GET", url, headers=self._headers()) as response:
                response.raise_for_status()
                buffer = io.BytesIO()
                for chunk in response.iter_bytes():
                    buffer.write(chunk)
                    if buffer.tell() > MAX_DOWNLOAD_BYTES:
                        raise ValueError("the repository archive is larger than the 15 MB limit")
            buffer.seek(0)
            # Read members straight from memory; nothing is ever unpacked to disk.
            with tarfile.open(fileobj=buffer, mode="r:gz") as archive:
                for member in archive:
                    relative = self._inside(member.name.split("/", 1)[1]) if "/" in member.name else None
                    if not member.isfile() or relative is None or not readable(relative) or member.size > MAX_FILE_BYTES:
                        continue
                    handle = archive.extractfile(member)
                    if handle is not None:
                        files[relative] = handle.read().decode("utf-8", errors="replace")
                    if len(files) >= MAX_FILES:
                        break
            commits = self._recent_commits(client)
        return {"files": dict(sorted(files.items())), "commits": commits}

    def _recent_commits(self, client: httpx.Client) -> list[dict]:
        params: dict[str, Any] = {"per_page": 8}
        if self.ref:
            params["sha"] = self.ref
        if self.subfolder:
            params["path"] = self.subfolder
        try:
            response = client.get(f"{self.api}/repos/{self.repo}/commits", headers=self._headers(), params=params)
            response.raise_for_status()
            rows = []
            for index, item in enumerate(response.json()[:8]):
                commit = item.get("commit", {})
                row = {"id": str(item.get("sha", ""))[:7], "title": str(commit.get("message", "")).splitlines()[0][:160] if commit.get("message") else "",
                       "author": str(commit.get("author", {}).get("name", ""))[:60], "timestamp": commit.get("author", {}).get("date", "")}
                if index < 3:  # which files the latest commits touched (one small request each)
                    detail = client.get(f"{self.api}/repos/{self.repo}/commits/{item.get('sha')}", headers=self._headers())
                    if detail.status_code == 200:
                        row["files"] = [str(f.get("filename", "")) for f in detail.json().get("files", [])][:12]
                rows.append(row)
            return rows
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return []  # the code is still readable without the history

    def _snapshot(self) -> dict:
        key = (self.api, self.repo, self.ref, self.subfolder)
        with _snapshot_lock:
            cached = _snapshots.get(key)
            if cached and time.monotonic() - cached[0] < SNAPSHOT_SECONDS:
                return cached[1]
            try:
                snapshot = self._download()
                self.problem = ""
            except httpx.HTTPStatusError as error:
                code = error.response.status_code
                reason = {401: "the token was rejected", 403: "access was refused or the request limit was reached", 404: "the repository or branch was not found (a private repository needs a token)"}.get(code, f"GitHub answered {code}")
                self.problem = f"Could not read {self.label}: {reason}."
                snapshot = {"files": {}, "commits": [], "problem": self.problem}
            except (httpx.HTTPError, tarfile.TarError, ValueError, OSError) as error:
                self.problem = f"Could not read {self.label}: {type(error).__name__}."
                snapshot = {"files": {}, "commits": [], "problem": self.problem}
            if self.problem:
                log.warning(self.problem)
            _snapshots[key] = (time.monotonic(), snapshot)  # failures are cached too, so a broken link is not hammered
            return snapshot

    def paths(self) -> list[str]:
        snapshot = self._snapshot()
        self.problem = snapshot.get("problem", "")
        return list(snapshot["files"])

    def read(self, path: str) -> str | None:
        return self._snapshot()["files"].get(path)

    def commits(self) -> list[dict]:
        return self._snapshot()["commits"]


def forget_snapshots() -> None:
    """Drop every cached GitHub snapshot (used by tests and after a project is reconnected)."""
    with _snapshot_lock:
        _snapshots.clear()


# -- log sources ----------------------------------------------------------


class LocalLogs:
    """Log files in a folder on this machine, plus any single files added by name (e.g. the live sandbox log)."""

    def __init__(self, folder: Path | None = None, extra: dict[str, Path] | None = None, label: str = ""):
        self.folder = folder
        self.extra = extra or {}
        self.label = label or (f"log folder {folder.name}" if folder else "")

    def _files(self) -> dict[str, Path]:
        files = {name: path for name, path in self.extra.items() if Path(path).is_file()}
        if self.folder is not None and self.folder.is_dir():
            files.update({p.name: p for p in sorted(self.folder.glob("*.log")) if p.is_file()})
        return files

    def names(self) -> list[str]:
        return list(self._files())

    def lines(self, name: str) -> list[str] | None:
        path = self._files().get(name)
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-20000:] if path else None


# -- projects -------------------------------------------------------------


@dataclass
class Project:
    """What is connected for one service."""

    service: str
    name: str = ""
    code: Any = field(default_factory=NoCode)
    logs: Any = field(default_factory=LocalLogs)


def _under(base: Path, folder: Path) -> bool:
    return folder.is_dir() and folder.resolve().is_relative_to(base.resolve())


class Projects:
    """The connected projects: ``projects.json`` first, then the built-in demo services."""

    def __init__(self, entries: list[dict] | None = None, token: str = ""):
        self.entries = {str(entry["service"]): entry for entry in (entries or []) if isinstance(entry, dict) and entry.get("service")}
        self.token = token

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "Projects":
        from .domain import Settings

        chosen = path or Settings().projects_file or "projects.json"
        file = Path(chosen) if Path(chosen).is_absolute() else PROJECT_ROOT / chosen
        entries: list[dict] = []
        if file.is_file():
            try:
                loaded = json.loads(file.read_text(encoding="utf-8"))
                entries = loaded.get("projects", []) if isinstance(loaded, dict) else []
            except (OSError, ValueError) as error:
                log.warning("Ignoring %s: %s", file.name, error)
        return cls(entries, token=github_token())

    def services(self) -> list[dict]:
        """The configured projects as (service id, display name, type) for the service catalog."""
        return [{"id": service, "name": str(entry.get("name") or service), "type": str(entry.get("type") or "Service"),
                 "environment": str(entry.get("environment") or "Production")} for service, entry in self.entries.items()]

    def _code(self, settings: dict | None) -> Any:
        settings = settings or {}
        kind = settings.get("type")
        if kind == "github" and settings.get("repo"):
            return GitHubCode(str(settings["repo"]), str(settings.get("ref") or ""), str(settings.get("path") or ""),
                              str(settings.get("api") or "https://api.github.com"), token=self.token,
                              pull_requests=settings.get("pull_requests") is True)
        if kind == "folder" and settings.get("path"):
            folder = (PROJECT_ROOT / str(settings["path"])).resolve()
            return LocalCode(folder) if _under(PROJECT_ROOT, folder) else NoCode()
        return NoCode()

    def _logs(self, settings: dict | None) -> Any:
        settings = settings or {}
        if settings.get("type") == "folder" and settings.get("path"):
            folder = (PROJECT_ROOT / str(settings["path"])).resolve()
            return LocalLogs(folder) if _under(PROJECT_ROOT, folder) else LocalLogs()
        return LocalLogs()

    def resolve(self, incident: dict, sandbox: Any = None) -> Project:
        service = str(incident.get("service", ""))
        entry = self.entries.get(service)
        if entry:
            return Project(service, str(entry.get("name") or service), self._code(entry.get("code")), self._logs(entry.get("logs")))
        if service == "payment-api" and incident.get("environment") == "Sandbox":
            live = getattr(sandbox, "log_path", None)
            extra = {"payment-sandbox.log (live)": Path(live)} if live is not None else {}
            sample = SAMPLE_ROOT / service / "logs"
            return Project(service, "Payment API sandbox", LocalCode(PAYMENT_REPO, "the Payment API sandbox source"),
                           LocalLogs(sample if _under(SAMPLE_ROOT, sample) else None, extra))
        repo, logs = SAMPLE_ROOT / service / "repo", SAMPLE_ROOT / service / "logs"
        return Project(service, service, LocalCode(repo, f"sample repository {service}") if _under(SAMPLE_ROOT, repo) else NoCode(),
                       LocalLogs(logs if _under(SAMPLE_ROOT, logs) else None))


def ensure_services(state: dict, projects: Projects, stamp: str) -> list[str]:
    """Add a catalog entry for every configured project that has none yet, so incidents can be raised on it."""
    known = {service.get("id") for service in state.get("services", [])}
    added = []
    for index, item in enumerate(projects.services()):
        if item["id"] in known:
            continue
        state["services"].append({
            "id": item["id"], "name": item["name"], "type": item["type"], "health": "Healthy", "environment": item["environment"],
            "latency": 0, "errorRate": 0, "rps": 0, "observedAt": stamp, "evidence": [], "changes": [], "incidents": [],
            "position": {"x": 700 + 175 * (index % 2), "y": 115 + 150 * (index // 2)}, "connected": True,
        })
        added.append(item["id"])
    return added
