"""Error intelligence: turn raw logs into grouped, trackable error issues.

Everything here works on what was really uploaded. Nothing is guessed: a field that is not in the
log (a timestamp, a line number, a request ID) stays empty.

- ``parse_errors`` reads plain-text logs, JSON-lines logs and Python, Java and JavaScript stack
  traces, and returns one event per error with its type, message, stack frames and IDs.
- ``fingerprint`` gives the same value to the same error seen again (numbers, IDs and quoted values
  are ignored), so recurring errors are grouped into one issue with a count.
- ``record_errors`` stores the issues in the workspace (``errors`` collection).
- ``correlate`` links an issue's stack frames to files in the connected source code and returns
  the surrounding lines, or says plainly that the location could not be established.
"""

import hashlib
import json
import re
from typing import Any

from .domain import redact

MAX_EVENTS = 2000          # per parsed text
MAX_STACK_LINES = 30
MAX_FRAMES = 12
ERROR_LEVELS = {"ERROR", "FATAL", "CRITICAL", "SEVERE", "EMERGENCY", "ALERT"}

TIMESTAMP = re.compile(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)")
LEVEL = re.compile(r"\b(FATAL|CRITICAL|SEVERE|EMERGENCY|ALERT|ERROR|WARN(?:ING)?|INFO|DEBUG|TRACE)\b")
EXCEPTION = re.compile(r"((?:[A-Za-z_][\w$]*\.)*[A-Z][\w$]*(?:Error|Exception|Failure|Fault|Timeout|Exit|Interrupt|Violation))\b(?::\s*(.*))?")
PY_FRAME = re.compile(r'^\s*File "(.+?)", line (\d+)(?:, in (.+))?')
JAVA_FRAME = re.compile(r"^\s*at ([\w$.<>]+)\(([\w$.-]+)(?::(\d+))?\)")
JS_FRAME = re.compile(r"^\s*at (?:(.+?) \()?((?:file://)?[^()\s]+?):(\d+):\d+\)?\s*$")
REQUEST_ID = re.compile(r"\b(?:request|req)[_-]?id[\"'=:\s]+([\w-]{4,80})", re.IGNORECASE)
CORRELATION_ID = re.compile(r"\b(?:correlation[_-]?id|trace[_-]?id)[\"'=:\s]+([\w-]{4,80})", re.IGNORECASE)

CATEGORIES = [
    ("Memory or resource", r"outofmemory|memoryerror|heap space|\boom\b|too many open files|resource exhausted|no space left"),
    ("Database", r"\bsql|jdbc|hikari|psycopg|mongo|deadlock|connection pool|database|\bdb\b|postgres|mysql|redis"),
    ("Authentication", r"\b401\b|\b403\b|unauthori[sz]ed|forbidden|authentication|invalid credentials|token expired|permission denied"),
    ("Timeout", r"timed? ?out|timeout|deadline exceeded"),
    ("Dependency", r"modulenotfound|importerror|noclassdeffound|classnotfound|cannot find module|econnrefused|connection refused|unknownhost|enotfound"),
    ("Configuration", r"improperlyconfigured|missing (?:configuration|setting|environment)|not configured|invalid configuration|keyerror: '[A-Z_]+'"),
    ("Deployment", r"crashloopbackoff|image ?pull|rollout|readiness probe|migration failed|startup failed"),
    ("API", r"\b5\d\d\b|status[=: ]+5\d\d|bad gateway|service unavailable|upstream|http error"),
]


def _category(text: str) -> str:
    lowered = text.lower()
    return next((name for name, pattern in CATEGORIES if re.search(pattern, lowered)), "Runtime")


def _severity(level: str, exception: str, text: str) -> str:
    if level in {"FATAL", "CRITICAL", "EMERGENCY", "ALERT"} or re.search(r"outofmemory|memoryerror|segmentation fault|panic", text.lower()):
        return "Critical"
    if exception or level in {"ERROR", "SEVERE"}:
        return "High" if exception else "Medium"
    return "Low"


def _frame(line: str) -> dict | None:
    """One stack frame from a Python, Java or JavaScript trace line, or None."""
    match = PY_FRAME.match(line)
    if match:
        return {"file": match.group(1), "line": int(match.group(2)), "function": (match.group(3) or "").strip()}
    match = JAVA_FRAME.match(line)
    if match:
        qualified = match.group(1)
        owner, _, method = qualified.rpartition(".")
        package_path = owner.split("$")[0].replace(".", "/")
        file = f"{package_path.rsplit('/', 1)[0]}/{match.group(2)}" if "/" in package_path and match.group(2).endswith((".java", ".kt", ".scala", ".groovy")) else match.group(2)
        return {"file": file, "line": int(match.group(3)) if match.group(3) else None, "function": method}
    match = JS_FRAME.match(line)
    if match:
        return {"file": match.group(2).removeprefix("file://"), "line": int(match.group(3)), "function": (match.group(1) or "").strip()}
    return None


def _is_stack_line(line: str) -> bool:
    stripped = line.strip()
    return bool(_frame(line)) or stripped.startswith(("Caused by:", "Traceback (most recent call last)", "...", "During handling of", "The above exception")) or (line.startswith(("    ", "\t")) and bool(stripped))


def _new_event(raw: str, timestamp: str = "", level: str = "", message: str = "") -> dict:
    return {"timestamp": timestamp, "level": level, "message": message or raw.strip(), "type": "", "stack": [], "frames": [], "requestId": "", "correlationId": "", "raw": raw.strip()}


def _finish(event: dict) -> dict | None:
    """Fill in the exception type and IDs; drop lines that are not errors."""
    text = "\n".join([event["message"], *event["stack"]])
    # The last "Type: message" line of a trace is the error that was raised (Python), the first one otherwise.
    typed = [match for match in (EXCEPTION.search(line) for line in [event["message"], *event["stack"]]) if match]
    if typed:
        chosen = typed[-1] if any(line.lstrip().startswith("Traceback") for line in [event["message"], *event["stack"]]) else typed[0]
        event["type"] = chosen.group(1)
        event["detail"] = (chosen.group(2) or "").strip()  # the exception's own message: what recurring errors share
        if chosen.group(2) and (event["message"].lstrip().startswith("Traceback") or not event["message"].strip()):
            event["message"] = f"{chosen.group(1)}: {chosen.group(2)}".strip()
    if not event["type"] and event["level"] not in ERROR_LEVELS:
        return None
    for key, pattern in (("requestId", REQUEST_ID), ("correlationId", CORRELATION_ID)):
        if not event[key]:
            found = pattern.search(text)
            event[key] = found.group(1) if found else ""
    event["frames"] = [frame for frame in (_frame(line) for line in event["stack"]) if frame][:MAX_FRAMES]
    event["stack"] = event["stack"][:MAX_STACK_LINES]
    event["category"] = _category(text)
    event["severity"] = _severity(event["level"], event["type"], text)
    event["message"] = event["message"][:600]
    return event


def _json_event(record: dict) -> dict | None:
    def pick(*names: str) -> str:
        for name in names:
            value = record.get(name)
            if value not in (None, ""):
                return value if isinstance(value, str) else json.dumps(value)
        return ""

    level = pick("level", "severity", "levelname", "log.level").upper()
    level = "WARN" if level == "WARNING" else level
    stack = pick("stack", "stack_trace", "stacktrace", "exception", "exc_info", "error.stack_trace", "traceback")
    message = pick("message", "msg", "error", "event") or (stack.splitlines()[0] if stack else "")
    if not message:
        return None
    event = _new_event(message, pick("timestamp", "time", "@timestamp", "ts"), level, message)
    event["stack"] = [line for line in stack.splitlines() if line.strip()] if stack else []
    event["requestId"] = pick("requestId", "request_id", "req_id")
    event["correlationId"] = pick("correlationId", "correlation_id", "traceId", "trace_id")
    return event


def parse_errors(text: str) -> list[dict]:
    """Every error in a log text, in order. Lines that are not errors are ignored."""
    events: list[dict] = []
    current: dict | None = None

    def close() -> None:
        nonlocal current
        if current is not None:
            finished = _finish(current)
            if finished and len(events) < MAX_EVENTS:
                events.append(finished)
        current = None

    for raw in text.splitlines():
        if not raw.strip():
            continue
        if raw.lstrip().startswith("{") and raw.rstrip().endswith("}"):
            close()
            try:
                record = json.loads(raw)
            except ValueError:
                record = None
            if isinstance(record, dict):
                current = _json_event(record)
                close()
                continue
        time = TIMESTAMP.search(raw[:60])
        level = LEVEL.search(raw[:120])
        starts_trace = raw.lstrip().startswith("Traceback (most recent call last)")
        if current is not None and not time and (_is_stack_line(raw) or EXCEPTION.match(raw.strip())):
            current["stack"].append(raw.rstrip())  # a continuation of the current error
            continue
        if time or level or starts_trace or EXCEPTION.match(raw.strip()):
            close()
            name = level.group(1) if level else ""
            name = "WARN" if name == "WARNING" else name
            message = raw[level.end():].lstrip(" :-]|") if level else raw[time.end():].lstrip(" :-]|") if time else raw
            current = _new_event(raw, time.group(1) if time else "", name, message)
            if starts_trace:
                current["stack"].append(raw.rstrip())
            continue
        close()
    close()
    return events


def _normalise(message: str) -> str:
    text = message.lower()
    text = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<id>", text)
    text = re.sub(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b", "<email>", text)
    text = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b", "<ip>", text)
    text = re.sub(r"\b0x[0-9a-f]+\b|\b[0-9a-f]{12,}\b", "<hex>", text)
    text = re.sub(r"\b\w*(?:id|key|token|session)\b\s*[=:]\s*\S+", "<id>", text)
    text = re.sub(r"'[^']*'|\"[^\"]*\"", "<value>", text)
    text = re.sub(r"\d+", "<n>", text)
    return re.sub(r"\s+", " ", text).strip()[:160]


LIBRARY_PATH = re.compile(r"site-packages|dist-packages|node_modules|/usr/lib|/lib/python|^java[./]|^javax[./]|^jdk[./]|^sun[./]|^org/springframework|^com/zaxxer|<frozen|internal/")


def raising_frame(event: dict) -> dict | None:
    """The frame in the application's own code closest to the error (library frames are skipped when possible)."""
    frames = event.get("frames") or []
    if not frames:
        return None
    python = any(str(line).lstrip().startswith("Traceback") for line in event.get("stack", []))
    ordered = list(reversed(frames)) if python else frames  # Python lists the raising frame last, Java and JavaScript first
    return next((frame for frame in ordered if not LIBRARY_PATH.search(str(frame["file"]).replace(chr(92), "/"))), ordered[0])


def fingerprint(event: dict) -> str:
    """Stable identity of an error: its type, its message without the changing parts, and where it was raised."""
    frame = raising_frame(event)
    where = f"{str(frame['file']).replace(chr(92), '/').rsplit('/', 1)[-1]}:{frame['function']}" if frame else ""
    what = event.get("detail") if event.get("type") else event["message"]
    return hashlib.sha1(f"{event['type']}|{_normalise(what or '')}|{where}".encode()).hexdigest()[:12]


def record_errors(state: dict, incident: dict, text: str, evidence_id: str, observed_at: str, new_id) -> list[dict]:
    """Parse ``text`` and add its errors to the workspace, grouped by fingerprint. Returns the issues touched."""
    issues = state.setdefault("errors", [])
    touched: dict[str, dict] = {}
    for event in parse_errors(text):
        print_ = fingerprint(event)
        issue = next((item for item in issues if item["fingerprint"] == print_ and item["service"] == incident["service"] and item["environment"] == incident["environment"]), None)
        seen = event["timestamp"] or observed_at
        if issue is None:
            short = event["type"].rsplit(".", 1)[-1] if event["type"] else ""
            # Name the issue after the exception itself when there is one; the log line stays in "message".
            title = f"{short}: {event['detail']}" if short and event.get("detail") else (f"{short}: " if short and short not in event["message"] else "") + event["message"]
            issue = {
                "id": new_id("ERR"), "fingerprint": print_, "title": redact(title)[:160], "type": event["type"] or "Logged error", "category": event["category"],
                "message": redact(event["message"]), "service": incident["service"], "environment": incident["environment"], "application": incident["service"],
                "firstSeen": seen, "lastSeen": seen, "count": 0, "severity": event["severity"], "status": "Open", "incidentIds": [], "evidenceIds": [],
                "frames": event["frames"], "sourceFiles": list(dict.fromkeys(str(frame["file"]) for frame in event["frames"]))[:8],
                "sample": {"message": redact(event["message"]), "stack": redact(event["stack"]), "requestId": event["requestId"], "correlationId": event["correlationId"], "timestampKnown": bool(event["timestamp"])},
                "createdAt": observed_at, "synthetic": False,
            }
            issues.append(issue)
        issue["count"] += 1
        issue["firstSeen"], issue["lastSeen"] = min(issue["firstSeen"], seen), max(issue["lastSeen"], seen)
        if {"Critical": 3, "High": 2, "Medium": 1, "Low": 0}[event["severity"]] > {"Critical": 3, "High": 2, "Medium": 1, "Low": 0}[issue["severity"]]:
            issue["severity"] = event["severity"]
        if issue["status"] == "Resolved":
            issue["status"] = "Open"  # it came back
            issue["reopenedAt"] = observed_at
        for key, value in (("incidentIds", incident["id"]), ("evidenceIds", evidence_id)):
            if value and value not in issue[key]:
                issue[key].append(value)
        touched[issue["id"]] = issue
    return list(touched.values())


def correlate(issue: dict, code: Any, context: int = 4) -> dict:
    """Find the issue's stack frames in the connected source code. Never guesses a location."""
    paths = code.paths()
    if not paths:
        return {"matches": [], "note": getattr(code, "problem", "") or "No source code is connected, so the error cannot be located in code."}
    if not issue.get("frames"):
        return {"matches": [], "note": "The log has no stack trace or file reference for this error, so its exact place in the code cannot be established."}
    matches: list[dict] = []
    for frame in issue["frames"]:
        parts = [part for part in str(frame["file"]).replace("\\", "/").split("/") if part and part != "."]
        found = None
        for size in range(len(parts), 0, -1):  # the longest path ending that exists exactly once wins
            suffix = "/".join(parts[-size:])
            candidates = [path for path in paths if path == suffix or path.endswith("/" + suffix)]
            if len(candidates) == 1:
                found = candidates[0]
                break
            if len(candidates) > 1 and size == 1:
                break  # an ambiguous file name is not a match
        if not found or any(item["path"] == found and item["line"] == frame["line"] for item in matches):
            continue
        lines = (code.read(found) or "").splitlines()
        line = frame["line"] if isinstance(frame["line"], int) and 1 <= frame["line"] <= len(lines) else None
        start = max(1, (line or 1) - context)
        matches.append({
            "path": found, "line": line, "function": frame["function"],
            "snippet": [{"number": number, "text": lines[number - 1][:240], "hit": number == line} for number in range(start, min(len(lines), (line or 1) + context) + 1)] if line else [],
            "note": "" if line else "The file was found but the line number from the log is not in the current version of the file.",
        })
        if len(matches) >= 4:
            break
    note = "" if matches else "None of the files named in the stack trace are part of the connected source code (they may belong to a library or another service)."
    return redact({"matches": matches, "note": note, "source": getattr(code, "label", "")})


MAX_LOG_RECORDS = 1000  # per uploaded file


def parse_log_lines(text: str) -> list[dict]:
    """Every log line that has a timestamp or a level, with its stack-trace lines folded into the message.

    Used to fill the Observability log view from what was really uploaded. A line keeps an empty timestamp
    when the log has none; it is never invented.
    """
    records: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        if not raw.strip():
            continue
        if raw.lstrip().startswith("{") and raw.rstrip().endswith("}"):
            try:
                item = json.loads(raw)
            except ValueError:
                item = None
            if isinstance(item, dict):
                event = _json_event(item)
                level = str(item.get("level") or item.get("severity") or item.get("levelname") or "").upper()
                message = str(item.get("message") or item.get("msg") or item.get("error") or item.get("event") or "")
                if message:
                    current = {"timestamp": (event or {}).get("timestamp", "") or str(item.get("timestamp") or item.get("time") or ""), "level": level,
                               "message": message, "requestId": (event or {}).get("requestId", "")}
                    records.append(current)
                continue
        time = TIMESTAMP.search(raw[:60])
        level = LEVEL.search(raw[:120])
        if current is not None and not time and (_is_stack_line(raw) or EXCEPTION.match(raw.strip())):
            if len(current["message"]) < 4000:
                current["message"] += "\n" + raw.rstrip()
            continue
        if time or level:
            name = level.group(1) if level else ""
            message = raw[level.end():].lstrip(" :-]|") if level else raw[time.end():].lstrip(" :-]|")
            found = REQUEST_ID.search(raw) or CORRELATION_ID.search(raw)
            current = {"timestamp": time.group(1) if time else "", "level": name, "message": message or raw.strip(), "requestId": found.group(1) if found else ""}
            records.append(current)
            if len(records) >= MAX_LOG_RECORDS:
                break
        else:
            current = None
    for record in records:
        level = record["level"].upper()
        record["level"] = ("ERROR" if level in ERROR_LEVELS or level == "ERR" else "WARN" if level.startswith("WARN")
                           else "DEBUG" if level in {"DEBUG", "TRACE"} else "INFO")
    return records
