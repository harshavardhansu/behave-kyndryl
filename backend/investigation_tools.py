"""Read-only investigation tools that Foundry agents call to inspect the incident.

The agents no longer only read a JSON summary: they look things up on demand,
exactly like an engineer would. Every tool is **read-only** and limited to
what the person attached to this one incident:

- the ticket and every evidence record (including the full text of attached files),
- the service's log files (search, then read a window of lines), the live Payment API sandbox log and log evidence,
- metrics found in the evidence and the service status,
- the changes and deployments recorded for the service,
- the service's repository and recent commits, through whichever connector the project uses
  (a local folder or any GitHub repository: see ``connectors.py``),
- approved runbooks in the knowledge base.

Nothing here can change, run, deploy or delete anything. Results are size-capped
and redacted, and each call is recorded in ``trail`` so people (and the PDF
report) can see exactly what every agent looked at.
"""

import json
import re
from pathlib import Path
from typing import Any, Callable

from .connectors import Projects
from .domain import redact

ARGUMENTS = {"id", "query", "path", "file", "start_line", "lines", "level"}
MAX_LOG_LINES = 40
MAX_LISTED_FILES = 80
FILE_WINDOW_CHARS = 3000
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
    {"name": "list_changes", "description": "List changes and deployments recorded for the affected service (release, config change, risk, status) and the latest commits of its repository (id, message, time, files touched).", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "list_repo_files", "description": "List the source and configuration files of the affected service's repository. For a large repository give a folder in 'path' to list only that folder.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Optional folder, e.g. 'src/api'"}}, "additionalProperties": False}},
    {"name": "read_repo_file", "description": "Read one file of the affected service's repository (read-only), e.g. a config file with connection pool settings. A long file is returned in parts: continue with start_line.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Path exactly as shown by list_repo_files"}, "start_line": {"type": "integer", "description": "Optional 1-based line to start at"}, "lines": {"type": "integer", "description": "Optional number of lines to return"}}, "required": ["path"], "additionalProperties": False}},
    {"name": "search_repo", "description": "Search all repository files for a word or phrase; returns file:line matches.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False}},
    {"name": "search_knowledge", "description": "Search approved runbooks and past resolutions for a word or phrase.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False}},
]
TOOL_NAMES = {spec["name"] for spec in TOOL_SPECS}


class InvestigationTools:
    """The tools for ONE incident. ``trail`` records every call that was made."""

    def __init__(self, state: dict, incident: dict, sandbox: Any = None, projects: Projects | None = None):
        self.state = state
        self.incident = incident
        self.sandbox = sandbox
        self.project = (projects or Projects.load()).resolve(incident, sandbox)  # the connectors for this service
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

    def _log_names(self) -> list[str]:
        """Log files the agent may read for this incident's service."""
        return self.project.logs.names()

    def _lines(self, name: str) -> list[str]:
        return self.project.logs.lines(name) or []

    @staticmethod
    def _time(line: str) -> str:
        match = re.match(r"\s*\{?.*?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line[:80])
        return match.group(1) if match else ""

    def list_log_files(self) -> dict:
        logs = []
        for name in self._log_names():
            lines = self._lines(name)
            logs.append({"file": name, "lines": len(lines), "from": self._time(lines[0]) if lines else "", "to": self._time(lines[-1]) if lines else ""})
        if not logs:
            return {"logs": [], "note": "No log files are connected for this service; use search_logs on the attached evidence."}
        return {"logs": logs}

    def read_log(self, file: str = "", start_line: Any = None, lines: Any = 60) -> dict:
        names = self._log_names()
        name = file if file in names else next((n for n in names if n.split(" ")[0] == Path(str(file)).name), None)
        if name is None:
            return {"error": f"Log file {file!r} is not available. Use list_log_files."}
        content = self._lines(name)
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
        for name in self._log_names():
            for number, line in enumerate(self._lines(name), start=1):
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
        rows = rows[:10]
        for commit in self.project.code.commits()[:8]:
            row = {"kind": "commit", **{k: _clip(commit[k], 160) for k in ("id", "title", "author", "timestamp") if commit.get(k)}}
            if commit.get("files"):
                row["files"] = [_clip(name, 100) for name in commit["files"][:12]]
            rows.append(row)
        return {"changes": rows}

    # -- repository ----------------------------------------------------

    def _no_repo(self) -> str:
        return self.project.code.problem or "No source repository is connected for this service."

    def list_repo_files(self, path: str = "") -> dict:
        code = self.project.code
        files = code.paths()
        if not files:
            return {"files": [], "note": self._no_repo()}
        folder = str(path or "").strip().strip("./")
        shown = [name for name in files if name.startswith(folder + "/") or name == folder] if folder else files
        if folder and not shown:
            tops = sorted({name.split("/")[0] for name in files})
            return {"source": code.label, "total": len(files), "files": files[:MAX_LISTED_FILES], "note": f"There is no folder {folder!r} in this repository, so all files are listed. Top level: {', '.join(tops[:20])}"}
        result: dict[str, Any] = {"source": code.label, "total": len(shown), "files": shown[:MAX_LISTED_FILES]}
        if len(shown) > MAX_LISTED_FILES:
            folders = sorted({name[len(folder) + 1 if folder else 0:].split("/")[0] for name in shown if "/" in name[len(folder) + 1 if folder else 0:]})
            result["note"] = f"Showing {MAX_LISTED_FILES} of {len(shown)} files. List one folder with 'path', or use search_repo. Folders: {', '.join(folders[:30])}"
        return result

    def read_repo_file(self, path: str = "", start_line: Any = None, lines: Any = None) -> dict:
        code = self.project.code
        files = code.paths()
        wanted = str(path).strip().lstrip("./")
        name = wanted if wanted in files else next((item for item in files if item.rsplit("/", 1)[-1] == wanted), None)
        text = code.read(name) if name else None
        if text is None:
            return {"error": f"File {path!r} is not available. Use list_repo_files." if files else self._no_repo()}
        if len(text) <= FILE_WINDOW_CHARS:
            # A file that fits is always returned whole, whatever window was asked for: an agent that
            # reads only the first lines draws wrong conclusions (e.g. misses a second definition further down).
            return {"path": name, "totalLines": len(text.splitlines()), "complete": True, "text": text}
        content = text.splitlines()
        start = min(max(1, int(start_line or 1)), max(1, len(content)))
        limit = max(1, int(lines)) if lines not in (None, "") else len(content)
        window, used = [], 0
        for line in content[start - 1:start - 1 + limit]:
            if window and used + len(line) + 1 > FILE_WINDOW_CHARS:
                break
            window.append(_clip(line, FILE_WINDOW_CHARS))
            used += len(line) + 1
        last = start + len(window) - 1
        result = {"path": name, "from": start, "to": last, "totalLines": len(content), "complete": start == 1 and last >= len(content), "text": "\n".join(window)}
        if last < len(content):
            result["note"] = f"INCOMPLETE: you have seen lines {start}-{last} of {len(content)}. Call read_repo_file again with start_line={last + 1} before concluding anything about this file."
        return result

    def search_repo(self, query: str = "") -> dict:
        needle = str(query).strip().lower()
        if len(needle) < 2:
            return {"error": "Give a search word of at least 2 characters."}
        code = self.project.code
        matches = []
        for name in code.paths():
            for number, line in enumerate((code.read(name) or "").splitlines(), start=1):
                if needle in line.lower():
                    matches.append({"file": f"{name}:{number}", "line": _clip(line.strip(), 200)})
        result: dict[str, Any] = {"query": query, "total": len(matches), "matches": matches[:15]}
        if not matches and not code.paths():
            result["note"] = self._no_repo()
        return result

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
