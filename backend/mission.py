"""Orchestrated agent missions with human-in-the-loop gates.

A mission is the Orchestrator's attempt to resolve one incident:

1. The Orchestrator analyses the ticket and proposes a team (only the
   specialists it needs, with reasons, plus reasons for leaving the others out).
2. A human approves, edits or rejects the team.
3. The team works step by step (Investigate -> Diagnose -> Remediate &
   validate -> Govern & release). Important decisions stop at human gates:
   the root cause, and the fix (which a *different* person must approve).
4. The Orchestrator evaluates the outcome and a human confirms it is
   resolved, starts another iteration (carrying the learnings forward and
   adding agents if needed), or escalates.

The "brain" that plans, works and evaluates is pluggable. ``SimulatedBrain``
is a deterministic, rule-based planner that costs nothing and is always
labelled SIMULATED; a Foundry-backed brain can implement the same protocol.

This module never changes the incident lifecycle owned by ``workflow.py``;
it records proposals, findings, decisions and learnings for human review.
"""

import asyncio
from typing import Literal, Protocol

from fastapi import HTTPException
from pydantic import Field

from .domain import StrictModel, now, redact
from .seed import AGENT_ROLES
from .store import Store
from .workflow import audit, find, identifier, is_payment_sandbox, require

ROLE_INFO = {role: {"name": name, "purpose": purpose} for role, name, purpose, _ in AGENT_ROLES}
SPECIALISTS = [role for role, *_ in AGENT_ROLES if role != "orchestrator"]

STEPS: list[tuple[str, str, list[str]]] = [
    ("investigate", "Investigate", ["intake", "logs", "observability", "repository"]),
    ("diagnose", "Diagnose", ["knowledge", "root-cause"]),
    ("remediate", "Remediate & validate", ["remediation", "testing", "security", "validation"]),
    ("govern", "Govern & release", ["risk", "release", "summary"]),
]
STEP_OF = {role: step for step, _, roles in STEPS for role in roles}

MAX_ITERATIONS = 3
RUNNING_STATUSES = {"Analysing", "Working"}
OPEN_STATUSES = RUNNING_STATUSES | {"Awaiting team approval", "Awaiting decision", "Awaiting resolution review", "Paused"}
SIMULATED_MODE = "SIMULATED / rule-based planner"

GateType = Literal["team", "root-cause", "fix", "resolution"]


class DecisionInput(StrictModel):
    gateId: str = Field(min_length=3, max_length=60)
    decision: Literal["approve", "reject", "resolve", "iterate", "escalate"]
    addRoles: list[str] = Field(default_factory=list, max_length=13)
    removeRoles: list[str] = Field(default_factory=list, max_length=13)
    note: str = Field("", max_length=600)


# --------------------------------------------------------------------------
# Brains
# --------------------------------------------------------------------------


class MissionBrain(Protocol):
    mode: str

    def plan(self, context: dict, iteration: int, learnings: list[str], previous_roles: list[str]) -> dict: ...

    def work(self, context: dict, step: str, members: list[dict], prior: list[dict]) -> dict[str, dict]: ...

    def evaluate(self, context: dict, team_roles: list[str], iteration: int) -> dict: ...


KEYWORDS = {
    "logs": ("error", "exception", "fail", "timeout", "5xx", "500", "503", "crash"),
    "observability": ("latency", "slow", "p95", "timeout", "saturation", "pool", "connection", "error rate", "cpu", "memory", "throughput"),
    "repository": ("release", "deploy", "version", "v2.", "v3.", "config", "change", "regression", "commit", "rollout"),
    "security": ("security", "auth", "token", "vulnerab", "cve", "leak", "permission", "unauthori", "credential", "certificate"),
    "testing": ("regression", "test", "release", "deploy"),
    "risk": ("release", "deploy", "production", "rollback", "config", "change"),
    "release": ("release", "deploy", "rollback", "config", "change"),
}

# Roles held back in a first pass to keep the team small; added in a later
# iteration if the first fix does not resolve the issue.
SECOND_WAVE = {"repository", "knowledge", "security", "risk", "testing"}


class SimulatedBrain:
    """Deterministic planner. No model calls, no cost, clearly labelled."""

    mode = SIMULATED_MODE

    def _text(self, context: dict) -> str:
        incident = context["incident"]
        fields = ("title", "description", "error", "actual", "impact", "service")
        return " ".join(str(incident.get(field, "")) for field in fields).lower()

    def relevant_roles(self, context: dict) -> list[str]:
        text = self._text(context)
        types = {record["type"].lower() for record in context["evidence"]}
        roles = {"intake", "root-cause", "remediation", "validation", "summary", "knowledge"}
        if "log" in types:
            roles.add("logs")
        if types & {"metric", "trace"}:
            roles.add("observability")
        for role, words in KEYWORDS.items():
            if any(word in text for word in words):
                roles.add(role)
        return [role for role in SPECIALISTS if role in roles]

    def _reason(self, role: str, context: dict) -> str:
        incident = context["incident"]
        evidence = context["evidence"]
        by_type = lambda kind: [record["id"] for record in evidence if record["type"].lower() == kind]
        reasons = {
            "intake": f"Classify the {incident['severity']} ticket and confirm scope on {incident['service']}.",
            "logs": f"Log evidence is attached ({', '.join(by_type('log')[:3]) or 'log records'}); group the failing requests.",
            "observability": f"Metric or trace evidence is attached ({', '.join((by_type('metric') + by_type('trace'))[:3]) or 'telemetry'}); correlate saturation and latency.",
            "repository": "The ticket points to a recent release or configuration change; inspect what changed.",
            "knowledge": "Look for an approved runbook or a prior resolution for this service.",
            "root-cause": "Weigh the competing explanations and name the most likely cause.",
            "remediation": "Prepare a reviewable fix proposal (no code is executed).",
            "testing": "The change touches a release path; define regression checks for the fix.",
            "security": "The ticket mentions authentication, credentials or access; review security impact.",
            "validation": "Check the fix against the quality gates and acceptance thresholds.",
            "risk": "A production change is involved; assess blast radius and rollback readiness.",
            "release": "Coordinate the human-approved (simulated) release of the fix.",
            "summary": "Record the outcome and the evidence references for the incident report.",
        }
        return reasons[role]

    def _task(self, role: str) -> str:
        return ROLE_INFO[role]["purpose"]

    def plan(self, context: dict, iteration: int, learnings: list[str], previous_roles: list[str]) -> dict:
        incident = context["incident"]
        relevant = self.relevant_roles(context)
        if iteration == 1:
            chosen = [role for role in relevant if role not in SECOND_WAVE]
        else:
            chosen = list(dict.fromkeys(previous_roles + relevant))
        selected = []
        for role in chosen:
            reason = self._reason(role, context)
            if iteration > 1 and role not in previous_roles:
                reason = f"Added in iteration {iteration}: {reason}"
            elif iteration > 1:
                reason = f"Continuing from iteration {iteration - 1}. {reason}"
            selected.append({"role": role, "reason": reason, "task": self._task(role)})
        skipped = []
        for role in SPECIALISTS:
            if role in chosen:
                continue
            if role in relevant:
                reason = "Held back in the first pass to keep the team small; added if the first fix does not resolve the issue."
            else:
                reason = "No signal for this specialist in the ticket or its evidence."
            skipped.append({"role": role, "reason": reason})
        analysis = (
            f"{incident['severity']} incident on {incident['service']} ({incident['environment']}). "
            f"{len(context['evidence'])} evidence record(s) available. "
            f"Proposing {len(selected)} of {len(SPECIALISTS)} specialists for iteration {iteration}."
        )
        if learnings:
            analysis += f" Building on {len(learnings)} learning(s) from earlier iterations."
        return {"analysis": analysis, "selected": selected, "skipped": skipped}

    def work(self, context: dict, step: str, members: list[dict], prior: list[dict]) -> dict[str, dict]:
        incident = context["incident"]
        evidence = context["evidence"]
        hypotheses = sorted(context["hypotheses"], key=lambda item: item["confidence"], reverse=True)
        change = context.get("change")
        ids_of = lambda *kinds: [record["id"] for record in evidence if record["type"].lower() in kinds]
        top = hypotheses[0] if hypotheses else None
        findings: dict[str, dict] = {}
        for member in members:
            role = member["role"]
            if role == "intake":
                summary = f"Classified as {incident['severity']} on {incident['service']} in {incident['environment']}. Impact: {incident['impact'][:140]}"
                refs, confidence = [record["id"] for record in evidence[:2]], 0.9
            elif role == "logs":
                refs = ids_of("log")
                summary = f"Reviewed {len(refs) or 'no'} log record(s). " + (next((r['title'] for r in evidence if r['id'] in refs), 'No log signal attached.'))
                confidence = 0.8 if refs else 0.3
            elif role == "observability":
                refs = ids_of("metric", "trace")
                summary = "Correlated telemetry: " + ("; ".join(r["title"] for r in evidence if r["id"] in refs)[:220] or "no metrics or traces attached.")
                confidence = 0.8 if refs else 0.3
            elif role == "repository":
                refs = ids_of("change", "deployment", "diff", "log")[:2]
                summary = f"The most recent change on {incident['service']} lines up with the start of the errors; it is the leading trigger."
                confidence = 0.7
            elif role == "knowledge":
                refs = []
                summary = f"Found guidance for {incident['service']}: verify connection and resource limits after each release before rolling back."
                confidence = 0.6
            elif role == "root-cause":
                refs = (top or {}).get("supports", [])[:3] or [record["id"] for record in evidence[:2]]
                title = top["title"] if top else f"Resource exhaustion on {incident['service']} after the latest change"
                summary = f"Most likely cause: {title}."
                confidence = round(top["confidence"], 2) if top else 0.6
            elif role == "remediation":
                refs = []
                title = change["title"] if change else f"Revert the most recent change on {incident['service']}"
                summary = f"Proposed fix: {title}. Rollback plan prepared."
                confidence = 0.7
            elif role == "testing":
                refs = []
                summary = "Defined regression checks for the fix: concurrency, latency budget and error rate."
                confidence = 0.7
            elif role == "security":
                refs = []
                summary = "No new security exposure introduced by the proposed fix."
                confidence = 0.7
            elif role == "validation":
                refs = []
                summary = "Quality gates reviewed for the proposal; acceptance threshold: error rate under 1% and p95 under 500 ms."
                confidence = 0.7
            elif role == "risk":
                refs = []
                summary = "Blast radius limited to the affected service; rollback ready."
                confidence = 0.7
            elif role == "release":
                refs = []
                summary = "Simulated release of the human-approved fix recorded. No production system was changed."
                confidence = 0.9
            else:
                refs = [record["id"] for record in evidence[:3]]
                summary = f"Summary drafted for {incident['id']} with {len(prior)} prior finding(s) and evidence references."
                confidence = 0.9
            findings[role] = {"summary": summary, "evidenceIds": refs, "confidence": confidence}
        return findings

    def evaluate(self, context: dict, team_roles: list[str], iteration: int) -> dict:
        relevant = set(self.relevant_roles(context))
        missing = [role for role in SPECIALISTS if role in relevant and role not in team_roles]
        if not missing:
            return {
                "resolved": True,
                "detail": "Simulated verification: error rate back under 1% and p95 latency under 500 ms after the fix.",
                "recommendation": "resolve",
                "missing": [],
            }
        names = ", ".join(ROLE_INFO[role]["name"] for role in missing)
        return {
            "resolved": False,
            "detail": f"Simulated verification: errors dropped but stayed above the 1% threshold. Areas not yet covered: {names}.",
            "recommendation": "iterate" if iteration < MAX_ITERATIONS else "escalate",
            "missing": missing,
        }


# --------------------------------------------------------------------------
# State helpers
# --------------------------------------------------------------------------


def _event(mission: dict, kind: str, message: str, actor: str = "Orchestrator", role: str | None = None) -> None:
    mission["events"].append({
        "id": identifier("EVT"), "timestamp": now(), "iteration": mission["iteration"],
        "type": kind, "actor": actor, "role": role, "message": redact(message),
    })
    mission["events"] = mission["events"][-250:]
    mission["updatedAt"] = now()


def _context(state: dict, incident_id: str) -> dict:
    incident = find(state, "incidents", incident_id)
    return {
        "incident": incident,
        "evidence": [record for record in state["evidence"] if record["incidentId"] == incident_id][:12],
        "hypotheses": [record for record in state["hypotheses"] if record["incidentId"] == incident_id],
        "change": next((record for record in state["changes"] if record["incidentId"] == incident_id), None),
    }


def _current(mission: dict) -> dict:
    return mission["iterations"][-1]


def _member(mission: dict, role: str, reason: str, task: str, added_by: str | None = None) -> dict:
    return {
        "id": f"{mission['id']}-{mission['iteration']}-{role}", "role": role, "name": ROLE_INFO[role]["name"],
        "purpose": ROLE_INFO[role]["purpose"], "reason": reason, "task": task, "step": STEP_OF[role],
        "status": "Queued", "findings": None, "startedAt": None, "completedAt": None, "addedBy": added_by,
    }


def _gate(mission: dict, kind: GateType, title: str, detail: str, recommendation: str, requires: str = "workflow:run") -> None:
    mission["pendingGate"] = {
        "id": identifier("GATE"), "type": kind, "title": title, "detail": redact(detail),
        "recommendation": recommendation, "requires": requires, "createdAt": now(), "iteration": mission["iteration"],
    }


def find_mission(state: dict, mission_id: str) -> dict:
    mission = next((item for item in state.get("missions", []) if item["id"] == mission_id), None)
    if mission is None:
        raise HTTPException(404, "Mission not found.")
    return mission


def _new_iteration(mission: dict, number: int) -> None:
    mission["iteration"] = number
    mission["iterations"].append({
        "number": number, "plan": None, "team": [], "skipped": [], "decisions": [],
        "outcome": None, "learnings": [], "startedAt": now(), "completedAt": None,
    })
    mission["status"] = "Analysing"
    mission["cursor"] = {"step": 0, "phase": "start"}
    mission["pendingGate"] = None
    mission["runToken"] += 1
    _event(mission, "analysing", f"Iteration {number}: the Orchestrator is analysing the ticket" + (" with the learnings so far." if mission["learnings"] else "."))


# --------------------------------------------------------------------------
# Keep the incident, change, approval and deployment records in step with
# the mission, so every page (Incidents, Changes, Command centre, Reports)
# tells the same story. The mission is the engine; these are its effects.
# --------------------------------------------------------------------------


def _mission_change(state: dict, mission: dict, incident: dict, summary: str) -> dict:
    change = next((record for record in state["changes"] if record["id"] == mission.get("changeId")), None)
    change = change or next((record for record in state["changes"] if record["incidentId"] == incident["id"] and record["status"] not in {"Completed", "Rolled Back"}), None)
    if change is None:
        change = {
            "id": identifier("CHG"), "incidentId": incident["id"], "title": ("Agent mission fix: " + summary)[:120], "status": "Draft", "risk": "Medium",
            "owner": mission["requestedBy"], "environment": incident["environment"], "branch": f"mission/{mission['id'].lower()}", "commit": f"mission-{mission['id'].lower()}",
            "files": ["Proposed by the Remediation agent (see mission findings)"], "diff": redact(summary)[:2000],
            "rollback": "Revert to the last known-good configuration and re-verify error rate and latency.",
            "plan": ["Review the agent findings and evidence", "Obtain separate human approval", "Apply the change", "Verify recovery"],
            "justification": "Proposed by the agent mission after a human-approved root cause.", "approvalId": None, "gates": [],
        }
        state["changes"].append(change)
    mission["changeId"] = change["id"]
    return change


def sync_records(state: dict, mission: dict) -> None:
    incident = find(state, "incidents", mission["incidentId"])
    if not mission["iterations"]:
        return
    current = _current(mission)
    system = {"name": "Agent mission", "role": "Orchestrator", "id": "agent-mission"}
    approved = {decision["type"] for decision in current["decisions"] if decision["decision"] == "approve"}
    gate = mission.get("pendingGate")
    change = next((record for record in state["changes"] if record["id"] == mission.get("changeId")), None)

    # Fix awaiting a human: make it a real change + approval on the Changes page.
    if gate and gate["type"] == "fix":
        remediation = next((member for member in current["team"] if member["role"] == "remediation" and member.get("findings")), None)
        change = _mission_change(state, mission, incident, (remediation or {}).get("findings", {}).get("summary", gate["detail"]))
        approval = next((item for item in state["approvals"] if item.get("missionGateId") == gate["id"]), None)
        if approval is None:
            approval = {"id": identifier("APR"), "changeId": change["id"], "incidentId": incident["id"], "title": change["title"], "requestedBy": mission["requestedBy"],
                        "requestedById": mission["requestedById"], "requestedAt": now(), "status": "Pending", "reviewedBy": None, "decidedAt": None, "reason": "",
                        "missionId": mission["id"], "missionGateId": gate["id"]}
            state["approvals"].append(approval)
        change.update(status="Approval", approvalId=approval["id"])
        gate["changeId"], gate["approvalId"] = change["id"], approval["id"]

    # Record the human decision on the approval (any iteration: a rejected fix starts a new one).
    for decision in (item for iteration in mission["iterations"] for item in iteration["decisions"]):
        if decision["type"] != "fix":
            continue
        approval = next((item for item in state["approvals"] if item.get("missionGateId") == decision["gateId"]), None)
        if approval and approval["status"] == "Pending":
            approval.update(status="Approved" if decision["decision"] == "approve" else "Rejected", reviewedBy=decision["by"], reviewedById=decision["byId"],
                            decidedAt=decision["at"], reason=decision["note"] or ("Approved in the agent mission." if decision["decision"] == "approve" else "Rejected in the agent mission."))
            target = next((record for record in state["changes"] if record["id"] == approval["changeId"]), None)
            if target:
                target["status"] = "Scheduled" if decision["decision"] == "approve" else "Draft"

    deployed = (current.get("sandboxChange") or {}).get("status") == "SUCCEEDED" or ("fix" in approved and mission["status"] in {"Awaiting resolution review", "Resolved"})
    if deployed and change and not current.get("deploymentId"):
        sandbox = current.get("sandboxChange") or {}
        deployment_id = identifier("DEP")
        state["deployments"].append({
            "id": deployment_id, "changeId": change["id"], "service": incident["service"],
            "version": (sandbox.get("active") or {}).get("release", "mission fix"), "environment": incident["environment"], "timestamp": now(),
            "status": "Succeeded and active configuration verified" if sandbox.get("status") == "SUCCEEDED" else "Simulated release after human approval",
        })
        current["deploymentId"] = deployment_id
        change["status"] = "Post-Deployment Verification"

    # Incident lifecycle status, derived from where the mission is.
    if mission["status"] == "Cancelled":
        # Withdraw anything the mission left half-way, so a new mission can start cleanly.
        for approval in state["approvals"]:
            if approval.get("missionId") == mission["id"] and approval["status"] == "Pending":
                approval.update(status="Rejected", reason="Withdrawn: the agent mission was cancelled.", decidedAt=now())
                target_change = next((record for record in state["changes"] if record["id"] == approval["changeId"]), None)
                if target_change and target_change["status"] == "Approval":
                    target_change.update(status="Draft", approvalId=None)
        if incident["status"] in {"Triaged", "Root Cause Identified", "Fix Proposed", "Awaiting Approval", "Approved"}:
            previous = incident["status"]
            incident["status"] = "Investigating"
            audit(state, system, "Incident status updated by agent mission", incident["id"], incident, previous=previous, next_state="Investigating", evidence=mission["id"])
        incident["workflowStatus"] = "Idle"
        return
    if mission["status"] == "Escalated":
        incident["workflowStatus"] = "Idle"
        return
    if mission["status"] == "Resolved":
        target = "Resolved"
    elif deployed:
        target = "Monitoring"
    elif "fix" in approved:
        target = "Approved"
    elif gate and gate["type"] == "fix":
        target = "Awaiting Approval"
    elif "root-cause" in approved:
        target = "Root Cause Identified"
    elif current["team"] or mission["iteration"] > 1:
        target = "Investigating"
    else:
        target = "Triaged" if incident["status"] in {"New", "Reopened"} else incident["status"]
    if incident["status"] != target:
        previous = incident["status"]
        incident["status"] = target
        audit(state, system, "Incident status updated by agent mission", incident["id"], incident, previous=previous, next_state=target, evidence=mission["id"])
    incident["workflowStatus"] = "Running" if mission["status"] in RUNNING_STATUSES else "Completed" if mission["status"] == "Resolved" else "Idle"

    if mission["status"] == "Resolved":
        if change and change["status"] != "Completed":
            change["status"] = "Completed"
        if not incident.get("recovery"):
            outcome = current.get("outcome") or {}
            measurement = outcome.get("measurement")
            resolution = mission.get("resolution") or {}
            incident["recovery"] = {
                "timestamp": now(), "actor": resolution.get("by", mission["requestedBy"]),
                "errorRate": measurement["errorRate"] if measurement else None, "latency": measurement["p95Ms"] if measurement else None,
                "synthetic": not measurement, "evidence": (outcome.get("evidenceIds") or [""])[0],
                "basis": "MEASURED" if measurement else "Human-confirmed after agent mission (not measured)",
            }
            incident["outcome"] = redact(resolution.get("note") or outcome.get("detail", ""))[:1000]


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def start_mission(state: dict, incident_id: str, user: dict, brain: MissionBrain) -> dict:
    incident = find(state, "incidents", incident_id)
    require(user, "workflow:run", incident["environment"])
    missions = state.setdefault("missions", [])
    if any(item["incidentId"] == incident_id and item["status"] in OPEN_STATUSES for item in missions):
        raise HTTPException(409, "This incident already has an open mission. Finish, escalate or cancel it first.")
    if not any(record["incidentId"] == incident_id for record in state["evidence"]):
        raise HTTPException(409, "Attach at least one evidence record before starting a mission.")
    mission = {
        "id": identifier("MSN"), "incidentId": incident_id, "status": "Analysing", "mode": brain.mode,
        "iteration": 0, "maxIterations": MAX_ITERATIONS, "requestedBy": user["name"], "requestedById": user.get("id", user["name"]),
        "createdAt": now(), "updatedAt": now(), "runToken": 0, "cursor": {"step": 0, "phase": "start"},
        "pendingGate": None, "iterations": [], "events": [], "learnings": [], "resolution": None, "pausedFrom": None,
    }
    _event(mission, "started", f"Mission started by {user['name']} for {incident_id}: {incident['title']}", actor=user["name"])
    _new_iteration(mission, 1)
    missions.append(mission)
    audit(state, user, "Agent mission started", mission["id"], incident, next_state="Orchestrator analysing")
    sync_records(state, mission)
    return {"missionId": mission["id"], "runToken": mission["runToken"], "launch": True}


def _end_iteration(mission: dict, learning: str, outcome: dict) -> None:
    current = _current(mission)
    for member in current["team"]:
        if member["status"] in {"Queued", "Running"}:
            member["status"] = "Not reached"
    current["outcome"] = outcome
    current["learnings"].append(learning)
    current["completedAt"] = now()
    mission["learnings"].append(f"Iteration {current['number']}: {learning}")


def _next_iteration_or_escalate(mission: dict, user: dict) -> bool:
    if mission["iteration"] >= mission["maxIterations"]:
        mission["status"] = "Escalated"
        mission["pendingGate"] = None
        _event(mission, "escalated", f"Iteration limit ({mission['maxIterations']}) reached. Escalated to the incident commander.", actor=user["name"])
        return False
    _new_iteration(mission, mission["iteration"] + 1)
    return True


def decide(state: dict, mission_id: str, payload: DecisionInput, user: dict) -> dict:
    mission = find_mission(state, mission_id)
    incident = find(state, "incidents", mission["incidentId"])
    gate = mission.get("pendingGate")
    if not gate or gate["id"] != payload.gateId:
        raise HTTPException(409, "This decision is no longer pending. Refresh to see the current mission state.")
    require(user, gate["requires"], incident["environment"])
    user_id = user.get("id", user["name"])
    note = redact(payload.note.strip())
    current = _current(mission)
    record = {"gateId": gate["id"], "type": gate["type"], "decision": payload.decision, "by": user["name"], "byId": user_id, "note": note, "at": now()}
    launch = False

    def needs_note(minimum: int = 5) -> None:
        if len(note) < minimum:
            raise HTTPException(422, f"Record a reason of at least {minimum} characters.")

    if gate["type"] == "team":
        if payload.decision == "approve":
            plan = current["plan"]
            unknown = [role for role in payload.addRoles + payload.removeRoles if role not in SPECIALISTS]
            if unknown:
                raise HTTPException(422, f"Unknown specialist role: {', '.join(unknown)}.")
            chosen = [item for item in plan["selected"] if item["role"] not in payload.removeRoles]
            chosen_roles = {item["role"] for item in chosen}
            for role in payload.addRoles:
                if role not in chosen_roles:
                    chosen.append({"role": role, "reason": f"Added by {user['name']}" + (f": {note}" if note else "."), "task": ROLE_INFO[role]["purpose"], "addedBy": user["name"]})
                    chosen_roles.add(role)
            if not chosen:
                raise HTTPException(422, "The team needs at least one specialist.")
            order = {role: index for index, role in enumerate(SPECIALISTS)}
            chosen.sort(key=lambda item: order[item["role"]])
            current["team"] = [_member(mission, item["role"], item["reason"], item["task"], item.get("addedBy")) for item in chosen]
            current["skipped"] = [
                {**item, "reason": f"Removed by {user['name']}" + (f": {note}" if note else ".")} if item["role"] in payload.removeRoles else item
                for item in plan["skipped"] if item["role"] not in chosen_roles
            ] + [
                {"role": item["role"], "reason": f"Removed by {user['name']}" + (f": {note}" if note else ".")}
                for item in plan["selected"] if item["role"] in payload.removeRoles
            ]
            mission["status"] = "Working"
            mission["cursor"] = {"step": 0, "phase": "start"}
            mission["runToken"] += 1
            edits = []
            if payload.addRoles:
                edits.append("added " + ", ".join(ROLE_INFO[role]["name"] for role in payload.addRoles))
            if payload.removeRoles:
                edits.append("removed " + ", ".join(ROLE_INFO[role]["name"] for role in payload.removeRoles))
            _event(mission, "team-approved", f"{user['name']} approved a team of {len(current['team'])}" + (f" ({'; '.join(edits)})" if edits else "") + ".", actor=user["name"])
            launch = True
        elif payload.decision == "reject":
            needs_note()
            mission["learnings"].append(f"Iteration {current['number']}: team rejected by {user['name']}: {note}")
            current["plan"] = None
            mission["status"] = "Analysing"
            mission["runToken"] += 1
            _event(mission, "team-rejected", f"{user['name']} rejected the proposed team: {note}. The Orchestrator is re-planning.", actor=user["name"])
            launch = True
        else:
            raise HTTPException(422, "Approve or reject the proposed team.")

    elif gate["type"] in {"root-cause", "fix"}:
        if gate["type"] == "fix" and user_id == mission["requestedById"]:
            raise HTTPException(403, "Separation of duties: the person who started the mission cannot approve its fix.")
        if payload.decision == "approve":
            mission["status"] = "Working"
            mission["runToken"] += 1
            _event(mission, "decision-approved", f"{user['name']} approved: {gate['title']}.", actor=user["name"])
            launch = True
        elif payload.decision == "reject":
            needs_note()
            label = "Root cause" if gate["type"] == "root-cause" else "Fix"
            _end_iteration(mission, f"{label} rejected by {user['name']}: {note}", {"resolved": False, "detail": f"{label} rejected by a human reviewer.", "recommendation": "iterate"})
            _event(mission, "decision-rejected", f"{user['name']} rejected: {gate['title']}. Reason: {note}", actor=user["name"])
            mission["pendingGate"] = None
            launch = _next_iteration_or_escalate(mission, user)
        else:
            raise HTTPException(422, "Approve or reject this decision.")

    elif gate["type"] == "resolution":
        outcome = current.get("outcome") or {}
        if payload.decision == "resolve":
            mission["status"] = "Resolved"
            mission["resolution"] = {"by": user["name"], "at": now(), "note": note, "iteration": mission["iteration"]}
            current["completedAt"] = now()
            _event(mission, "resolved", f"{user['name']} confirmed the issue is resolved." + (f" {note}" if note else ""), actor=user["name"])
        elif payload.decision == "iterate":
            learning = outcome.get("detail", "Not resolved.") + (f" Reviewer note: {note}" if note else "")
            current["learnings"].append(learning)
            current["completedAt"] = now()
            mission["learnings"].append(f"Iteration {current['number']}: {learning}")
            _event(mission, "iterate", f"{user['name']} started another iteration.", actor=user["name"])
            launch = _next_iteration_or_escalate(mission, user)
        elif payload.decision == "escalate":
            mission["status"] = "Escalated"
            _event(mission, "escalated", f"{user['name']} escalated the incident." + (f" {note}" if note else ""), actor=user["name"])
        else:
            raise HTTPException(422, "Choose resolve, iterate or escalate.")
        if mission["status"] in {"Resolved", "Escalated"}:
            mission["pendingGate"] = None

    current["decisions"].append(record)
    if mission.get("pendingGate") and mission["pendingGate"]["id"] == gate["id"]:
        mission["pendingGate"] = None
    audit(state, user, f"Mission decision: {gate['title']}", mission["id"], incident, next_state=f"{payload.decision} / {mission['status']}", outcome=payload.decision)
    sync_records(state, mission)
    return {"missionId": mission["id"], "status": mission["status"], "runToken": mission["runToken"], "launch": launch}


def cancel_mission(state: dict, mission_id: str, user: dict) -> dict:
    mission = find_mission(state, mission_id)
    incident = find(state, "incidents", mission["incidentId"])
    require(user, "workflow:run", incident["environment"])
    if mission["status"] not in OPEN_STATUSES:
        raise HTTPException(409, "Only an open mission can be cancelled.")
    mission["status"] = "Cancelled"
    mission["pendingGate"] = None
    mission["runToken"] += 1
    for member in _current(mission)["team"]:
        if member["status"] in {"Queued", "Running"}:
            member["status"] = "Cancelled"
    _event(mission, "cancelled", f"{user['name']} cancelled the mission.", actor=user["name"])
    audit(state, user, "Agent mission cancelled", mission["id"], incident, next_state="Cancelled")
    sync_records(state, mission)
    return {"missionId": mission["id"], "status": mission["status"], "launch": False}


def resume_mission(state: dict, mission_id: str, user: dict) -> dict:
    mission = find_mission(state, mission_id)
    incident = find(state, "incidents", mission["incidentId"])
    require(user, "workflow:run", incident["environment"])
    if mission["status"] != "Paused" or not mission.get("pausedFrom"):
        raise HTTPException(409, "Only a paused mission can be resumed.")
    mission["status"] = mission["pausedFrom"]
    mission["pausedFrom"] = None
    mission["runToken"] += 1
    _event(mission, "resumed", f"{user['name']} resumed the mission.", actor=user["name"])
    return {"missionId": mission["id"], "status": mission["status"], "runToken": mission["runToken"], "launch": True}


def pause_interrupted(state: dict) -> None:
    """On restart, background work is gone: pause running missions for a human to resume."""
    for mission in state.get("missions", []):
        if mission["status"] in RUNNING_STATUSES:
            mission["pausedFrom"] = mission["status"]
            mission["status"] = "Paused"
            for member in _current(mission)["team"]:
                if member["status"] == "Running":
                    member["status"] = "Queued"
            _event(mission, "paused", "The service restarted during this mission. Resume it to continue.", actor="System")


# --------------------------------------------------------------------------
# Background runner: one small transition per tick so the UI can follow it
# --------------------------------------------------------------------------


class NeedBrain(Exception):
    """Raised inside a store transaction when a remote (AI) brain must be called.

    The transaction rolls back, the runner makes the slow call outside the
    database lock, stashes the answer on the mission and retries the step.
    """

    def __init__(self, key: str, method: str, args: tuple, target: str = "brain"):
        super().__init__(key)
        self.key = key
        self.method = method
        self.args = args
        self.target = target


def _ask(brain: MissionBrain, mission: dict, key: str, method: str, *args):
    if not getattr(brain, "remote", False):
        return getattr(brain, method)(*args)
    cache = mission.setdefault("brainCache", {})
    if key in cache:
        return cache.pop(key)
    raise NeedBrain(key, method, args)


def _ask_tool(mission: dict, key: str, method: str, *args):
    """Like ``_ask`` but for slow real-world actions (sandbox changes, workloads)."""
    cache = mission.setdefault("brainCache", {})
    if key in cache:
        return cache.pop(key)
    raise NeedBrain(key, method, args, target="tools")


class MissionTools:
    """Real actions a mission may take on the local Payment API sandbox, only after human approval."""

    def __init__(self, sandbox):
        self.sandbox = sandbox

    def apply_fix(self, action: dict) -> dict:
        try:
            return self.sandbox.apply_configuration(action["release"], int(action["pool_size"]), actor_id="agent-mission")
        except Exception as error:  # noqa: BLE001 - reported to humans, never hidden
            return {"status": "MANUAL_INTERVENTION_REQUIRED", "error": f"{type(error).__name__}: {error}", "active_config": None}

    def measure(self) -> dict:
        from .payment_local import read_recent_errors

        try:
            measurement = self.sandbox.run_workload(50)
        except Exception as error:  # noqa: BLE001
            return {"error": f"{type(error).__name__}: {error}"}
        return {"measurement": measurement, "logLines": read_recent_errors(self.sandbox)}


SANDBOX_FIX = {"release": "3.8.1", "pool_size": 20}


def _sandbox_action(state: dict, incident: dict) -> dict:
    change = next((record for record in state["changes"] if record["incidentId"] == incident["id"]), None)
    return dict((change or {}).get("sandboxAction") or SANDBOX_FIX)


def _stash(state: dict, mission_id: str, token: int, key: str, result) -> bool:
    mission = find_mission(state, mission_id)
    if mission["runToken"] != token or mission["status"] not in RUNNING_STATUSES:
        return False
    mission.setdefault("brainCache", {})[key] = result
    return True


def _note_fallback(mission: dict, source: str | None, what: str) -> None:
    if source and source.startswith("SIMULATED fallback"):
        _event(mission, "ai-fallback", f"AI unavailable for {what}; used the simulated planner. {source.removeprefix('SIMULATED fallback: ')}", actor="System")


def _advance(state: dict, mission_id: str, token: int, brain: MissionBrain, tools: "MissionTools | None" = None) -> bool:
    keep_going = _advance_step(state, mission_id, token, brain, tools)
    mission = find_mission(state, mission_id)
    if mission["runToken"] == token:
        sync_records(state, mission)
    return keep_going


def _advance_step(state: dict, mission_id: str, token: int, brain: MissionBrain, tools: "MissionTools | None" = None) -> bool:
    mission = find_mission(state, mission_id)
    if mission["runToken"] != token or mission["status"] not in RUNNING_STATUSES:
        return False
    context = _context(state, mission["incidentId"])
    current = _current(mission)
    sandbox = tools is not None and is_payment_sandbox(context["incident"])

    # Real sandbox: once a human has approved the fix, apply exactly that change and verify it.
    fix_approved = any(item["type"] == "fix" and item["decision"] == "approve" for item in current["decisions"])
    if mission["status"] == "Working" and sandbox and fix_approved and "sandboxChange" not in current:
        action = _sandbox_action(state, context["incident"])
        result = _ask_tool(mission, f"apply:{mission['iteration']}", "apply_fix", action)
        current["sandboxChange"] = {"requested": action, "status": result.get("status"), "active": result.get("active_config"), "error": result.get("error", "")}
        if result.get("status") == "SUCCEEDED":
            active = result["active_config"]
            _event(mission, "sandbox-applied", f"Applied the human-approved fix to the live Payment API sandbox: release {active['release']}, pool size {active['pool_size']} (verified on the running service).", actor="Release coordination", role="release")
        else:
            _event(mission, "sandbox-failed", f"The sandbox change could not be verified: {result.get('error')}. A human must inspect it.", actor="System")
        audit(state, {"name": "Agent mission", "role": "Release coordination"}, "Payment sandbox change applied by mission", mission["id"], context["incident"], next_state=str(current["sandboxChange"]["status"]))
        return True

    if mission["status"] == "Analysing":
        previous = mission["iterations"][-2]["team"] if len(mission["iterations"]) > 1 else []
        plan_key = f"plan:{mission['iteration']}:{len(mission['learnings'])}"
        plan = _ask(brain, mission, plan_key, "plan", context, mission["iteration"], list(mission["learnings"]), [member["role"] for member in previous])
        current["plan"] = redact(plan)
        _note_fallback(mission, plan.get("source"), "team planning")
        mission["status"] = "Awaiting team approval"
        names = ", ".join(ROLE_INFO[item["role"]]["name"] for item in plan["selected"])
        _event(mission, "team-proposed", f"Proposed a team of {len(plan['selected'])}: {names}.")
        _gate(
            mission, "team", f"Approve the team for iteration {mission['iteration']}",
            plan["analysis"], f"Approve {len(plan['selected'])} specialists; {len(plan['skipped'])} left out with reasons.",
        )
        return False

    cursor = mission["cursor"]
    team_roles = [member["role"] for member in current["team"]]
    step_index = cursor["step"]
    while step_index < len(STEPS) and not any(STEP_OF[role] == STEPS[step_index][0] for role in team_roles):
        step_index += 1
    if step_index >= len(STEPS) and sandbox:
        # Real sandbox: the outcome is MEASURED by re-running the calibrated workload.
        measured = _ask_tool(mission, f"measure:{mission['iteration']}", "measure")
        if "measurement" in measured:
            from .sandbox_records import describe, record_measurement

            measurement = measured["measurement"]
            ids = record_measurement(state, context["incident"], measurement, measured.get("logLines", []), {"name": "Agent mission", "role": "Validation"}, f"mission {mission['id']} iteration {mission['iteration']}")
            applied = (current.get("sandboxChange") or {}).get("status") == "SUCCEEDED"
            resolved = applied and measurement["errors"] == 0 and measurement["requests"] > 0
            recommendation = "resolve" if resolved else "iterate" if mission["iteration"] < mission["maxIterations"] else "escalate"
            outcome = {
                "resolved": resolved,
                "detail": "MEASURED: " + describe(measurement) + ("" if applied else " No approved fix was applied in this iteration."),
                "recommendation": recommendation, "missing": [], "source": "MEASURED", "evidenceIds": ids, "measurement": measurement,
            }
            current["outcome"] = outcome
            mission["status"] = "Awaiting resolution review"
            _event(mission, "measured", ("Outcome: resolved. " if resolved else "Outcome: not resolved. ") + outcome["detail"], actor="Validation", role="validation")
            options = {"resolve": "Confirm resolved", "iterate": "Start another iteration", "escalate": "Escalate"}
            _gate(mission, "resolution", "Confirm the measured outcome", outcome["detail"], options[recommendation], "workflow:run")
            return False
        _event(mission, "sandbox-failed", f"Could not measure the sandbox ({measured.get('error')}); falling back to the planner's assessment.", actor="System")

    if step_index >= len(STEPS):
        context["findings"] = [{"role": member["role"], "summary": member["findings"]["summary"]} for member in current["team"] if member.get("findings")]
        context["decisions"] = [{"gate": decision["type"], "decision": decision["decision"], "by": decision["by"]} for decision in current["decisions"]]
        outcome = _ask(brain, mission, f"evaluate:{mission['iteration']}", "evaluate", context, team_roles, mission["iteration"])
        current["outcome"] = outcome
        _note_fallback(mission, outcome.get("source"), "the outcome review")
        mission["status"] = "Awaiting resolution review"
        _event(mission, "evaluated", ("Outcome: resolved. " if outcome["resolved"] else "Outcome: not resolved. ") + outcome["detail"])
        options = {"resolve": "Confirm resolved", "iterate": "Start another iteration", "escalate": "Escalate"}
        _gate(mission, "resolution", "Confirm the outcome", outcome["detail"], options[outcome["recommendation"]], "workflow:run")
        return False
    step_id, step_name, _ = STEPS[step_index]
    members = [member for member in current["team"] if member["step"] == step_id]

    if cursor["phase"] == "start":
        for member in members:
            member.update(status="Running", startedAt=now())
        _event(mission, "step-started", f"{step_name}: {', '.join(member['name'] for member in members)} started work.")
        mission["cursor"] = {"step": step_index, "phase": "finish"}
        return True

    prior = [member for member in current["team"] if member["findings"]]
    findings = _ask(brain, mission, f"work:{mission['iteration']}:{step_id}", "work", context, step_id, members, prior)
    _note_fallback(mission, next((value.get("source") for value in findings.values() if value.get("source", "").startswith("SIMULATED fallback")), None), step_name)
    for member in members:
        result = findings.get(member["role"]) or {"summary": "No finding returned.", "evidenceIds": [], "confidence": 0.0}
        member.update(status="Completed", completedAt=now(), findings=redact(result))
        calls = result.get("toolCalls") or []
        if calls:
            looked = "; ".join(f"{call['tool']}({', '.join(str(v) for v in call['arguments'].values())}) → {call['found']}" for call in calls[:6])
            _event(mission, "investigation", f"{member['name']} investigated with {len(calls)} read-only tool call{'s' if len(calls) != 1 else ''}: {looked}", actor=member["name"], role=member["role"])
        _event(mission, "finding", f"{member['name']}: {result['summary']}", actor=member["name"], role=member["role"])
    mission["cursor"] = {"step": step_index + 1, "phase": "start"}
    next_names = next((name for sid, name, _ in STEPS[step_index + 1:] if any(STEP_OF[role] == sid for role in team_roles)), None)
    if next_names:
        _event(mission, "handoff", f"Handing {step_name} findings to {next_names}.")

    by_role = {member["role"]: member for member in current["team"]}
    if step_id == "diagnose" and "root-cause" in by_role:
        finding = by_role["root-cause"]["findings"]
        mission["status"] = "Awaiting decision"
        _gate(mission, "root-cause", "Approve the root cause", f"{finding['summary']} Confidence {finding['confidence']:.2f}.", "Approve to move on to the fix, or reject to investigate further.")
        return False
    if step_id == "remediate" and "remediation" in by_role:
        finding = by_role["remediation"]["findings"]
        mission["status"] = "Awaiting decision"
        detail = finding["summary"]
        if sandbox:
            action = _sandbox_action(state, context["incident"])
            detail = f"Exact action on approval: set the live Payment API sandbox to release {action['release']} with pool size {action['pool_size']}, then re-measure. Proposal: {detail}"
        _gate(mission, "fix", "Approve the fix for release", detail, "A different person from the mission starter must approve.", "approval:decide")
        return False
    return True


async def run_mission(store: Store, mission_id: str, token: int, brain: MissionBrain, step_seconds: float, tools: MissionTools | None = None) -> None:
    try:
        while True:
            await asyncio.sleep(step_seconds)
            while True:
                try:
                    keep_going = store.mutate(lambda state: _advance(state, mission_id, token, brain, tools))
                    break
                except NeedBrain as need:
                    target = tools if need.target == "tools" else brain
                    result = await asyncio.to_thread(getattr(target, need.method), *need.args)
                    if not store.mutate(lambda state: _stash(state, mission_id, token, need.key, result)):
                        return
            if not keep_going:
                return
    except Exception:
        def fail(state: dict) -> None:
            mission = find_mission(state, mission_id)
            if mission["runToken"] != token:
                return
            mission["pausedFrom"] = mission["status"] if mission["status"] in RUNNING_STATUSES else None
            mission["status"] = "Paused"
            _event(mission, "error", "The mission hit an infrastructure error and was paused. Resume it to retry.", actor="System")
        store.mutate(fail)
