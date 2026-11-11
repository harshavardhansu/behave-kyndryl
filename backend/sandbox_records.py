"""Turn live Payment API sandbox measurements into BEHAVE evidence.

A measurement is real: it is the outcome of firing the calibrated concurrent
workload at the running sandbox. It is stored as MEASURED evidence on the
sandbox incident (plus the latest real error lines from the service log), so
agents, the AI and humans all reason over the same observed numbers.
"""

import json

from .domain import now, redact
from .workflow import audit, identifier


def describe(measurement: dict) -> str:
    feature = "available" if measurement.get("featureX") else "not available (previous release)"
    return (
        f"{measurement['errors']}/{measurement['requests']} requests failed with HTTP 5xx "
        f"({measurement['errorRate']}% error rate) at {measurement['concurrency']} concurrent requests; "
        f"p95 {measurement['p95Ms']} ms, max {measurement['maxMs']} ms; release {measurement['release']}, "
        f"pool size {measurement['poolSize']}; Feature X (GET /payments/summary) {feature}."
    )


def record_measurement(state: dict, incident: dict | None, measurement: dict, log_lines: list[str], actor: dict, purpose: str) -> list[str]:
    """Store a measurement and, when an incident is given, attach it as evidence. Returns evidence IDs."""
    entry = {"id": identifier("MSR"), "incidentId": incident["id"] if incident else None, "purpose": purpose, "recordedBy": actor["name"], **measurement}
    state.setdefault("sandboxMeasurements", []).append(entry)
    state["sandboxMeasurements"] = state["sandboxMeasurements"][-30:]
    if incident is None:
        return []
    ids = []
    metric_id = identifier("EVD")
    state["evidence"].append({
        "id": metric_id, "incidentId": incident["id"],
        "title": f"Measured workload: {measurement['errors']}/{measurement['requests']} requests failed (pool {measurement['poolSize']})",
        "type": "Metric", "source": f"payment-api sandbox / calibrated workload ({purpose})", "timestamp": measurement["measuredAt"],
        "service": "payment-api", "environment": "Sandbox", "classification": "Observed",
        "excerpt": describe(measurement), "reason": "MEASURED against the running Payment API sandbox; not simulated.",
        "traceId": "", "synthetic": False,
    })
    ids.append(metric_id)
    if measurement["errors"] and log_lines:
        excerpts = []
        for line in log_lines:
            try:
                record = json.loads(line)
                excerpts.append(f"{record.get('timestamp', '')} {record.get('severity')} {record.get('method')} {record.get('path')} -> {record.get('status_code')} {record.get('exception_type')}: {str(record.get('error', ''))[:220]}")
            except ValueError:
                excerpts.append(line[:300])
        log_id = identifier("EVD")
        state["evidence"].append({
            "id": log_id, "incidentId": incident["id"], "title": "Payment API error log: connection pool timeout",
            "type": "Log", "source": "payment-api sandbox / service log", "timestamp": now(),
            "service": "payment-api", "environment": "Sandbox", "classification": "Observed",
            "excerpt": redact("\n".join(excerpts))[:2000], "reason": "Real structured error lines written by the sandbox service during the measured workload.",
            "traceId": "", "synthetic": False,
        })
        ids.append(log_id)
    audit(state, actor, f"Sandbox workload measured ({purpose})", entry["id"], incident, next_state=f"{measurement['errors']} errors / {measurement['requests']}", evidence=",".join(ids))
    return ids
