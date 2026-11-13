"""Live smoke test for a deployed instance: run one real mission end to end on the running app.

Runs INSIDE the container against the app on loopback (so no browser sign-in is needed):

    az containerapp exec -g <group> -n behave-kyndryl --command "python -m backend.cloud_smoke INC-1043"

It approves every gate (the fix by a second persona, as separation of duties requires), follows the
outcome review's recommendation, prints where every finding came from and how many read-only tool
calls each agent made, and saves the PDF report next to the database. It makes real AI calls.
"""

import sys
import time

import httpx

BASE = "http://127.0.0.1:8000/api/v1"


def main(incident: str = "INC-1043") -> int:
    client = httpx.Client(timeout=120)

    def login(role: str) -> None:
        response = client.post(f"{BASE}/auth/demo", json={"role": role})
        response.raise_for_status()
        client.headers["X-CSRF-Token"] = response.json()["csrf"]
        # The session cookie is marked Secure in the cloud; send it explicitly over loopback http.
        client.headers["Cookie"] = "agentica_session=" + (response.cookies.get("agentica_session") or "")

    def mission(mission_id: str) -> dict:
        return next(m for m in client.get(f"{BASE}/workspace").json()["missions"] if m["id"] == mission_id)

    login("Incident Manager")
    for open_mission in client.get(f"{BASE}/workspace").json()["missions"]:
        if open_mission["incidentId"] == incident and open_mission["status"] not in {"Resolved", "Escalated", "Cancelled"}:
            client.post(f"{BASE}/missions/{open_mission['id']}/cancel")
    started = client.post(f"{BASE}/incidents/{incident}/missions")
    if started.status_code != 201:
        print("Could not start the mission:", started.status_code, started.text[:200])
        return 1
    mission_id = started.json()["missionId"]
    print("Mission", mission_id, "on", incident)

    def wait() -> dict:
        for _ in range(180):
            record = mission(mission_id)
            if record["pendingGate"] or record["status"] in {"Resolved", "Escalated", "Cancelled", "Paused"}:
                return record
            time.sleep(2)
        return mission(mission_id)

    def decide(decision: str, **extra) -> None:
        gate = mission(mission_id)["pendingGate"]
        response = client.post(f"{BASE}/missions/{mission_id}/decision", json={"gateId": gate["id"], "decision": decision, **extra})
        response.raise_for_status()

    while True:
        record = wait()
        gate = record["pendingGate"]
        print(" gate:", record["status"], gate and gate["type"])
        if not gate:
            break
        if gate["type"] == "fix":
            login("Change Approver")
            decide("approve")
            login("Incident Manager")
        elif gate["type"] == "resolution":
            outcome = record["iterations"][-1]["outcome"]
            print("   outcome:", outcome["detail"][:200])
            decide({"resolve": "resolve", "iterate": "iterate"}.get(outcome["recommendation"], "escalate"), note="Reviewed by the cloud smoke test")
        else:
            decide("approve")

    record = mission(mission_id)
    print("RESULT", record["status"], "after", len(record["iterations"]), "iteration(s)")
    for iteration in record["iterations"]:
        for member in iteration["team"]:
            finding = member.get("findings") or {}
            print(f"  it{iteration['number']} {member['role']:13} {finding.get('source', '')[:60]:60} tools={len(finding.get('toolCalls') or [])}")
        change = iteration.get("sandboxChange") or {}
        if change:
            print("  sandbox change:", change.get("status"), change.get("active"))
    fallbacks = [event["message"][:120] for event in record["events"] if event["type"] == "ai-fallback"]
    print("FALLBACKS", fallbacks or "none")
    report = client.get(f"{BASE}/incidents/{incident}/resolution-report/pdf")
    path = "/mnt/data/smoke-report.pdf"
    try:
        with open(path, "wb") as handle:
            handle.write(report.content)
    except OSError:
        path = "(not saved)"
    print("PDF", report.status_code, len(report.content), "bytes", path)
    return 0 if record["status"] == "Resolved" and not fallbacks else 2


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
