"""Numbers for a real workspace, computed from its records instead of stored demonstration values.

- ``trends``: incidents opened per day by severity, and incidents resolved per day, for the last 7 days,
  counted from the incidents and the audit trail.
- ``services``: each service's health from its open incidents and open errors. Latency, error rate and
  request rate are left empty (no monitoring connector is connected), except for the Payment API
  sandbox, whose numbers come from its latest measured workload.
"""

from datetime import datetime, timedelta, timezone

CLOSED = {"Resolved", "Closed"}


def _day(value: str) -> str:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%b %d")
    except ValueError:
        return ""


def trends(state: dict, days: int = 7) -> list[dict]:
    today = datetime.now(timezone.utc)
    labels = [(today - timedelta(days=offset)).strftime("%b %d") for offset in range(days - 1, -1, -1)]
    rows = {label: {"date": label, "critical": 0, "high": 0, "other": 0, "resolved": 0} for label in labels}
    for incident in state.get("incidents", []):
        label = _day(incident.get("detectedAt", ""))
        if label in rows:
            key = {"Critical": "critical", "High": "high"}.get(incident.get("severity"), "other")
            rows[label][key] += 1
    resolved_seen: set[str] = set()
    for event in sorted(state.get("audit", []), key=lambda item: item.get("timestamp", "")):
        if event.get("next") in CLOSED and event.get("correlationId") not in resolved_seen and str(event.get("correlationId", "")).startswith("INC-"):
            label = _day(event.get("timestamp", ""))
            if label in rows:
                rows[label]["resolved"] += 1
                resolved_seen.add(event["correlationId"])
    return [rows[label] for label in labels]


def services(state: dict) -> list[dict]:
    open_incidents: dict[str, list[dict]] = {}
    for incident in state.get("incidents", []):
        if incident.get("status") not in CLOSED:
            open_incidents.setdefault(incident["service"], []).append(incident)
    open_errors: dict[str, list[dict]] = {}
    for issue in state.get("errors", []):
        if issue.get("status") == "Open":
            open_errors.setdefault(issue["service"], []).append(issue)
    rows = []
    for index, service in enumerate(state.get("services", [])):
        incidents, errors = open_incidents.get(service["id"], []), open_errors.get(service["id"], [])
        critical = any(item.get("severity") == "Critical" for item in incidents + errors)
        rows.append({
            **service, "position": {"x": 190 * (index % 4), "y": 130 * (index // 4)},  # a plain grid: no dependency map is connected
            "health": "Critical" if critical else "Degraded" if incidents or errors else "Healthy",
            "latency": None, "errorRate": None, "rps": None,
            "healthBasis": f"{len(incidents)} open incident(s), {len(errors)} open error group(s) in this workspace; no live monitoring is connected",
            "incidents": [item["id"] for item in incidents],
        })
    measured = [item for item in state.get("sandboxMeasurements", []) if item.get("requests")]
    if measured:
        latest = measured[-1]
        seconds = max(float(latest.get("durationMs") or 0) / 1000, 0.001)
        rows.append({
            "id": "payment-api", "name": "Payment API sandbox", "type": "API", "environment": "Sandbox",
            "health": "Critical" if latest["errorRate"] >= 5 else "Degraded" if latest["errorRate"] > 0 else "Healthy",
            "latency": latest["p95Ms"], "errorRate": latest["errorRate"], "rps": round(latest["requests"] / seconds, 1) if latest.get("durationMs") else None,
            "observedAt": latest["measuredAt"], "evidence": [], "changes": [], "incidents": [item["id"] for item in open_incidents.get("payment-api", [])],
            "position": {"x": 0, "y": 0}, "connected": True, "healthBasis": f"Measured workload at {latest['measuredAt']}: {latest['errors']}/{latest['requests']} errors, p95 {latest['p95Ms']} ms",
        })
    return rows


def _time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def metrics(state: dict) -> dict:
    """Response-time numbers computed from the records. A value is None when there is nothing to measure yet."""
    reported = {event["resource"]: _time(event["timestamp"]) for event in state.get("audit", []) if event.get("action") == "Incident created"}
    first_mission: dict[str, datetime] = {}
    finished: set[str] = set()
    for mission in state.get("missions", []):
        started = _time(mission.get("createdAt", ""))
        if started and (mission["incidentId"] not in first_mission or started < first_mission[mission["incidentId"]]):
            first_mission[mission["incidentId"]] = started
        if mission.get("status") in {"Resolved", "Solution ready"}:
            finished.add(mission["incidentId"])
    to_start = [(first_mission[key] - reported[key]).total_seconds() / 60 for key in first_mission if reported.get(key) and first_mission[key] >= reported[key]]
    resolved = [incident for incident in state.get("incidents", []) if incident.get("status") in CLOSED and (incident.get("recovery") or {}).get("timestamp")]
    to_resolve = []
    for incident in resolved:
        end, begin = _time(incident["recovery"]["timestamp"]), reported.get(incident["id"])
        if end and begin and end >= begin:
            to_resolve.append((end - begin).total_seconds() / 60)
    mean = lambda values: round(sum(values) / len(values), 1) if values else None  # noqa: E731
    return {
        "minutesToInvestigation": mean(to_start), "investigatedIncidents": len(to_start),
        "minutesToResolution": mean(to_resolve), "resolvedIncidents": len(resolved),
        "resolvedWithAgents": sum(1 for incident in resolved if incident["id"] in finished),
        "measuredResolutions": sum(1 for incident in resolved if (incident.get("recovery") or {}).get("basis") == "MEASURED"),
        "basis": "Computed from this workspace's records: report time to first agent mission, and report time to recorded recovery.",
    }
