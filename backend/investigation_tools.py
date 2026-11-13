"""Read-only investigation tools that Foundry agents call to inspect the incident.

The agents no longer only read a JSON summary: they look things up on demand,
exactly like an engineer would. Every tool is **read-only** and limited to
what the person attached to this one incident:

- the ticket and every evidence record (including the full text of attached files),
- the service's log files (search, then read a window of lines), the live Payment API sandbox log and log evidence,
- metrics found in the evidence and the service status,
- the changes and deployments recorded for the service,
- the service's repository: ``payment_api/`` for the sandbox, ``sample_services/<service>/repo`` for the demo services,
- approved runbooks in the knowledge base.

Nothing here can change, run, deploy or delete anything. Results are size-capped
and redacted, and each call is recorded in ``trail`` so people (and the PDF
report) can see exactly what every agent looked at.
"""

import json
import re
from pathlib import Path
from typing import Any, Callable

from .domain import redact

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PROJECT_ROOT / "payment_api"            # the live Payment API sandbox source
SAMPLE_ROOT = PROJECT_ROOT / "sample_services"      # demo repos and logs: scripts/generate_sample_services.py
READABLE_SUFFIXES = {".py", ".txt", ".md", ".example", ".yml", ".yaml", ".java", ".kt", ".properties", ".options", ".json", ".toml", ".sql"}
ARGUMENTS = {"id", "query", "path", "file", "start_line", "lines", "level"}
MAX_LOG_LINES = 40
LOG_WINDOW_CHARS = 5000
MAX_CALLS = 10          # per agent run
MAX_RESULT_CHARS = 6000  # per tool result sent back to the agent


def _clip(value: Any, limit: int) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _is_payment_sandbox(incident: dict) -> bool:
    return incident.get("service") == "payment-api" and incident.get("environment") == "Sandbox"


TOOL_SPECS: list[dict] = [
    {"name": "get_ticket", "description": "Read the incident ticket: title, severity, service, environment, description, impact and error.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "list_evidence", "description": "List every evidence record attached to this incident (id, type, title, classification, source).", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "read_evidence", "description": "Read the full text of one evidence record by id, for example an attached log file.", "parameters": {"type": "object", "properties": {"id": {"type": "string", "description": "Evidence id such as EVD-301"}}, "required": ["id"], "additionalProperties": False}},
    {"name": "search_logs", "description": "Search the service's log files, the live sandbox log and log evidence for a word or phrase (case-insensitive). Returns the total count, first and last time it appears, and matching lines with file:line. Optionally filter by level (ERROR, WARN, INFO).", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Word or phrase, e.g. 'timeout' or 'HikariPool'"}, "level": {"type": "string", "description": "Optional: ERROR, WARN or INFO"}}, "required": ["query"], "additionalProperties": False}},
    {"name": "list_log_files", "description": "List the log files available for the affected service, with line counts and the time range they cover.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "read_log", "description": "Read a window of lines from one log file (up to 40 lines). Without start_line it returns the last lines. Use search_logs first to find the line numbers that matter.", "parameters": {"type": "object", "properties": {"file": {"type": "string", "description": "Name from list_log_files"}, "start_line": {"type": "integer", "description": "1-based line number to start at"}, "lines": {"type": "integer", "description": "How many lines (max 40)"}}, "required": ["file"], "additionalProperties": False}},
    {"name": "get_service_status", "description": "Read the current state of the affected service: recorded health, metric evidence and, for the Payment API sandbox, the live active configuration.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "list_changes", "description": "List changes and deployments recorded for the affected service (release, config change, risk, status).", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "list_repo_files", "description": "List the source and configuration files of the affected service's repository.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "read_repo_file", "description": "Read one file of the affected service's repository (read-only), e.g. a config file with connection pool settings.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Path exactly as shown by list_repo_files"}}, "required": ["path"], "additionalProperties": False}},
    {"name": "search_repo", "description": "Search all repository files for a word or phrase; returns file:line matches.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False}},
    {"name": "search_knowledge", "description": "Search approved runbooks and past resolutions for a word or phrase.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False}},
]
TOOL_NAMES = {spec["name"] for spec in TOOL_SPECS}


class InvestigationTools:
    """The tools for ONE incident. ``trail`` records every call that was made."""

    def __init__(self, state: dict, incident: dict, sandbox: Any = None):
        self.state = state
        self.incident = incident
        self.sandbox = sandbox
        self.trail: list[dict] = []
        self._handlers: dict[str, Callable[..., Any]] = {
            "get_ticket": self.get_ticket, "list_evidence": self.list_evidence, "read_evidence": self.read_evidence,
            "search_logs": self.search_logs, "get_service_status": self.get_service_status, "list_changes": self.list_changes,
            "list_repo_files": self.list_repo_files, "read_repo_file": self.read_repo_file, "search_repo": self.search_repo,
            "list_log_files": self.list_log_files, "read_log": self.read_log, "search_knowledge": self.search_knowledge,
        }

    # -- dispatch --------------------------------------------------------

    def call(self, name: str, arguments: dict | None) -> dict:
        """Run one tool. Never raises: a problem is returned to the agent as ``{"error": ...}``."""
        arguments = arguments if isinstance(arguments, dict) else {}
        if len(self.trail) >= MAX_CALLS:
            result: dict = {"error": f"Tool budget of {MAX_CALLS} calls used. Answer now with what you have."}
        elif name not in self._handlers:
            result = {"error": f"Unknown tool {name}. Available: {', '.join(sorted(TOOL_NAMES))}."}
        else:
            try:
                result = self._handlers[name](**{key: value for key, value in arguments.items() if key in ARGUMENTS})
            except TypeError:
                result = {"error": f"Bad arguments for {name}."}
            except Exception as error:  # noqa: BLE001 - reported to the agent, never raised
                result = {"error": f"{type(error).__name__} while running {name}."}
        result = json.loads(redact(json.dumps(result, default=str)))
        result = self._fit(result)
        self.trail.append({
            "tool": name,
            "arguments": {key: _clip(value, 80) for key, value in arguments.items() if key in ARGUMENTS},
            "ok": "error" not in result,
            "found": _clip(self._headline(name, result), 140),
        })
        return result

    @staticmethod
    def _fit(result: dict) -> dict:
        """Keep a result under MAX_RESULT_CHARS: drop list items first so the structure survives."""
        lists = [key for key, value in result.items() if isinstance(value, list)]
        while len(json.dumps(result)) > MAX_RESULT_CHARS and any(len(result[key]) > 1 for key in lists):
            key = max(lists, key=lambda name: len(json.dumps(result[name])))
            result[key] = result[key][:-1]
            result["truncated"] = True
        if len(json.dumps(result)) > MAX_RESULT_CHARS:
            result = {"truncated": True, "text": _clip(json.dumps(result), MAX_RESULT_CHARS)}
        return result

    @staticmethod
    def _headline(name: str, result: dict) -> str:
        if "error" in result:
            return result["error"]
        if name == "search_logs" and "total" in result:
            return f"{result['total']} matching lines" + (f" ({result['firstSeen']} to {result['lastSeen']})" if result.get("firstSeen") else "")
        if name == "read_log" and "file" in result:
            return f"{result['file']} lines {result.get('from')}-{result.get('to')} of {result.get('totalLines')}"
        for key in ("matches", "evidence", "changes", "files", "articles", "logs"):
            if isinstance(result.get(key), list):
                return f"{len(result[key])} {key}"
        return {"get_ticket": "ticket read", "read_evidence": result.get("title", "evidence read"), "read_repo_file": f"{result.get('path', 'file')} read", "get_service_status": "status read"}.get(name, "ok")

    # -- the tools -------------------------------------------------------

    def _evidence(self) -> list[dict]:
        return [record for record in self.state.get("evidence", []) if record.get("incidentId") == self.incident["id"]]

    def get_ticket(self) -> dict:
        keys = ("id", "title", "severity", "status", "service", "environment", "description", "impact", "error", "expected", "actual", "detectedAt")
        return {("errorMessage" if key == "error" else key): _clip(self.incident[key], 1200) for key in keys if self.incident.get(key)}

    def list_evidence(self) -> dict:
        return {"evidence": [
            {"id": r["id"], "type": r.get("type"), "title": _clip(r.get("title", ""), 120), "classification": r.get("classification"), "source": _clip(r.get("source", ""), 80), "length": len(r.get("excerpt", ""))}
            for r in self._evidence()
        ]}

    def read_evidence(self, id: str = "") -> dict:
        record = next((r for r in self._evidence() if r["id"] == id), None)
        if record is None:
            return {"error": f"No evidence {id!r} on this incident. Use list_evidence."}
        return {"id": record["id"], "type": record.get("type"), "title": record.get("title"), "source": record.get("source"), "classification": record.get("classification"), "text": _clip(record.get("excerpt", ""), 3000)}

    # -- logs ----------------------------------------------------------

    def _log_files(self) -> dict[str, Path]:
        """Log files the agent may read for this incident's service (name -> path)."""
        files: dict[str, Path] = {}
        if _is_payment_sandbox(self.incident):
            log_path = getattr(self.sandbox, "log_path", None)
            if log_path is not None and Path(log_path).is_file():
                files["payment-sandbox.log (live)"] = Path(log_path)
        folder = SAMPLE_ROOT / str(self.incident.get("service", "")) / "logs"
        if folder.is_dir() and folder.resolve().is_relative_to(SAMPLE_ROOT.resolve()):
            files.update({p.name: p for p in sorted(folder.glob("*.log")) if p.is_file()})
        return files

    @staticmethod
    def _lines(path: Path) -> list[str]:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-20000:]

    @staticmethod
    def _time(line: str) -> str:
        match = re.match(r"\s*\{?.*?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line[:80])
        return match.group(1) if match else ""

    def list_log_files(self) -> dict:
        logs = []
        for name, path in self._log_files().items():
            lines = self._lines(path)
            logs.append({"file": name, "lines": len(lines), "from": self._time(lines[0]) if lines else "", "to": self._time(lines[-1]) if lines else ""})
        if not logs:
            return {"logs": [], "note": "No log files are connected for this service; use search_logs on the attached evidence."}
        return {"logs": logs}

    def read_log(self, file: str = "", start_line: Any = None, lines: Any = 60) -> dict:
        files = self._log_files()
        path = files.get(file) or next((p for name, p in files.items() if name.split(" ")[0] == Path(str(file)).name), None)
        if path is None:
            return {"error": f"Log file {file!r} is not available. Use list_log_files."}
        content = self._lines(path)
        count = max(1, min(int(lines or 60), MAX_LOG_LINES))
        start = int(start_line) if start_line not in (None, "") else max(1, len(content) - count + 1)
        start = min(max(1, start), max(1, len(content)))
        window, used = [], 0
        for n, line in enumerate(content[start - 1 : start - 1 + count]):
            entry = f"{start + n}: {_clip(line, 260)}"
            if window and used + len(entry) > LOG_WINDOW_CHARS:
                break
            window.append(entry)
            used += len(entry)
        return {"file": file, "from": start, "to": start + len(window) - 1, "totalLines": len(content), "lines": window}

    def search_logs(self, query: str = "", level: str = "") -> dict:
        needle = str(query).strip().lower()
        if len(needle) < 2:
            return {"error": "Give a search word of at least 2 characters."}
        level = str(level or "").strip().upper()
        matches: list[dict] = []
        for record in self._evidence():
            if record.get("type") != "Log":
                continue
            for line in str(record.get("excerpt", "")).splitlines():
                if needle in line.lower() and (not level or level in line.upper()):
                    matches.append({"source": record["id"], "time": self._time(line), "line": _clip(line.strip(), 240)})
        for name, path in self._log_files().items():
            for number, line in enumerate(self._lines(path), start=1):
                if needle in line.lower() and (not level or level in line[:60].upper() or f'"severity": "{level}"' in line):
                    matches.append({"source": f"{name.split(' ')[0]}:{number}", "time": self._time(line), "line": _clip(line.strip(), 240)})
        times = sorted(m["time"] for m in matches if m["time"])
        sample = matches[:5] + matches[-5:] if len(matches) > 10 else matches
        return {"query": query, "level": level or "any", "total": len(matches), "firstSeen": times[0] if times else "", "lastSeen": times[-1] if times else "", "matches": sample}

    def get_service_status(self) -> dict:
        service = self.incident.get("service")
        record = next((s for s in self.state.get("services", []) if s.get("id") == service or s.get("name") == service), None)
        result: dict[str, Any] = {"service": service}
        if record:
            result["recorded"] = {key: record[key] for key in ("health", "status", "tier", "owner", "slo") if key in record}
        result["metricEvidence"] = [{"id": r["id"], "title": _clip(r.get("title", ""), 100), "text": _clip(r.get("excerpt", ""), 300)} for r in self._evidence() if r.get("type") in {"Metric", "Trace"}][:6]
        if self.sandbox is not None and _is_payment_sandbox(self.incident):
            try:
                status = self.sandbox.status()
                result["liveSandbox"] = {"running": status.get("running"), "activeConfig": status.get("activeConfig")}
            except Exception:  # noqa: BLE001
                result["liveSandbox"] = {"error": "sandbox status unavailable"}
        return result

    def list_changes(self) -> dict:
        service = self.incident.get("service")
        changes = [c for c in self.state.get("changes", []) if c.get("incidentId") == self.incident["id"] or c.get("service") == service]
        deployments = [d for d in self.state.get("deployments", []) if d.get("service") == service]
        rows = [{"kind": "change", **{k: _clip(c[k], 160) for k in ("id", "title", "risk", "status") if k in c}} for c in changes]
        rows += [{"kind": "deployment", **{k: _clip(d[k], 160) for k in ("id", "release", "version", "status", "timestamp") if k in d}} for d in deployments]
        return {"changes": rows[:10]}

    # -- repository ----------------------------------------------------

    def _repo_root(self) -> Path | None:
        if _is_payment_sandbox(self.incident):
            return REPO_ROOT if REPO_ROOT.is_dir() else None
        root = SAMPLE_ROOT / str(self.incident.get("service", "")) / "repo"
        if root.is_dir() and root.resolve().is_relative_to(SAMPLE_ROOT.resolve()):
            return root
        return None

    def _repo_files(self) -> dict[str, Path]:
        root = self._repo_root()
        if root is None:
            return {}
        files = {}
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if path.is_file() and path.suffix in READABLE_SUFFIXES and not any(part.startswith((".", "__")) for part in relative.parts):
                files[relative.as_posix()] = path
        return files

    def list_repo_files(self) -> dict:
        files = self._repo_files()
        if not files:
            return {"files": [], "note": "No source repository is connected for this service."}
        return {"files": list(files)[:60]}

    def read_repo_file(self, path: str = "") -> dict:
        files = self._repo_files()
        wanted = str(path).strip().lstrip("./")
        match = files.get(wanted) or next((p for name, p in files.items() if name.rsplit("/", 1)[-1] == wanted), None)
        if match is None:
            return {"error": f"File {path!r} is not available. Use list_repo_files."}
        name = next(name for name, p in files.items() if p == match)
        return {"path": name, "text": _clip(match.read_text(encoding="utf-8", errors="replace"), 3000)}

    def search_repo(self, query: str = "") -> dict:
        needle = str(query).strip().lower()
        if len(needle) < 2:
            return {"error": "Give a search word of at least 2 characters."}
        matches = []
        for name, path in self._repo_files().items():
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
                if needle in line.lower():
                    matches.append({"file": f"{name}:{number}", "line": _clip(line.strip(), 200)})
        return {"query": query, "matches": matches[:15]}

    def search_knowledge(self, query: str = "") -> dict:
        words = [w for w in re.split(r"\W+", query.lower()) if len(w) > 2]
        if not words:
            return {"error": "Give at least one search word."}
        service = self.incident.get("service")
        hits = []
        for article in self.state.get("knowledge", []):
            if not article.get("approved"):
                continue
            haystack = f"{article.get('title', '')} {article.get('body', '')}".lower()
            score = sum(w in haystack for w in words) + (1 if service in article.get("services", []) else 0)
            if score > 1 or (score and service in article.get("services", [])):
                hits.append((score, article))
        hits.sort(key=lambda pair: -pair[0])
        return {"articles": [{"id": a["id"], "title": a.get("title"), "type": a.get("type"), "text": _clip(a.get("body", ""), 700)} for _, a in hits[:3]]}
