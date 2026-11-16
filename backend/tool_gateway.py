"""Tool Gateway: the single, governed door between the AI agents and anything outside the workspace.

Agents never act on a system themselves. Every action that changes or runs something outside the
workspace goes through ``ToolGateway.execute``:

1. **Allow-list.** Only the actions registered in ``ACTIONS`` exist, each with a risk level, the targets
   it may touch and whether it needs a human-approved fix.
2. **Independent approval check.** The gateway re-reads the mission from the database (it does not trust
   the caller) and checks that a human approved the fix in the current iteration, that the approver is
   not the person who started the mission, and that the change about to run is byte-for-byte the change
   that was approved (a hash recorded with the approval).
3. **Target policy.** Sandbox actions only reach the isolated Payment API sandbox; pull requests only go
   to repositories an administrator opted in, on a new branch, never the base branch.
4. **Once per approval.** An approved action runs once; a repeat request is refused.
5. **Auditability.** Every request, allowed or denied, is written to the gateway log and the audit trail
   and traced to Application Insights.

Read-only investigation tools are governed here too: each agent role gets only the tools it needs
(least privilege), see ``ROLE_TOOLS``.
"""

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable

from . import telemetry
from .domain import now, redact
from .store import Store
from .workflow import audit, identifier, is_payment_sandbox


@dataclass(frozen=True)
class GatewayAction:
    name: str
    kind: str          # "write" changes a system; "execute" runs something against it
    risk: str          # Low / Medium / High
    approval: bool     # needs a human-approved fix in this iteration, by someone other than the mission starter
    target: str
    description: str


ACTIONS: dict[str, GatewayAction] = {action.name: action for action in (
    GatewayAction("sandbox.apply_configuration", "write", "Medium", True, "The isolated Payment API sandbox only",
                  "Set the sandbox's release and connection-pool size exactly as approved, then read back the active configuration."),
    GatewayAction("sandbox.run_workload", "execute", "Low", False, "The isolated Payment API sandbox only",
                  "Send a calibrated 50-request workload and measure errors and latency."),
    GatewayAction("github.open_pull_request", "write", "Medium", True,
                  "Repositories an administrator connected with pull requests on; a new branch only",
                  "Push the approved edits to a new branch and open a pull request. Never merges and never writes the base branch."),
)}

# Least privilege for the read-only investigation tools: each agent gets what its job needs.
_COMMON = {"get_ticket", "list_evidence", "read_evidence", "search_knowledge"}
_CODE = {"list_changes", "list_repo_files", "read_repo_file", "search_repo"}
_LOGS = {"get_error_groups", "list_log_files", "read_log", "search_logs"}
ROLE_TOOLS: dict[str, frozenset[str]] = {role: frozenset(_COMMON | extra) for role, extra in {
    "intake": {"get_error_groups", "get_service_status"},
    "logs": _LOGS,
    "observability": _LOGS | {"get_service_status"},
    "repository": _CODE | {"get_error_groups"},
    "knowledge": set(),
    "root-cause": _CODE | _LOGS | {"get_service_status"},
    "remediation": _CODE | {"get_error_groups", "get_service_status", "search_logs"},
    "testing": _CODE | {"get_service_status"},
    "security": _CODE | {"search_logs", "get_error_groups"},
    "validation": {"get_service_status", "search_logs", "get_error_groups", "list_changes"},
    "risk": _CODE | {"get_service_status"},
    "release": {"list_changes", "get_service_status"},
    "summary": {"list_changes", "get_error_groups"},
}.items()}


def allowed_tools(role: str | None) -> frozenset[str] | None:
    """The read-only tools an agent role may call; None means "no restriction" (no role given)."""
    if role is None:
        return None
    return ROLE_TOOLS.get(role, frozenset(_COMMON))


def fingerprint(value: Any) -> str:
    """A stable hash of exactly what was approved (dict keys sorted)."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class GatewayDenied(Exception):
    """The gateway refused the action. The message is safe to show and is recorded."""


def _summary(result: dict) -> dict:
    keep = ("status", "url", "number", "branch", "error", "requests", "errors", "p95Ms", "errorRate", "release", "pool_size")
    summary = {key: result[key] for key in keep if key in result and result[key] not in (None, "")}
    active = result.get("active_config")
    if isinstance(active, dict):
        summary["active"] = {key: active.get(key) for key in ("release", "pool_size")}
    measurement = result.get("measurement")
    if isinstance(measurement, dict):
        summary.update({key: measurement.get(key) for key in ("requests", "errors", "p95Ms", "errorRate") if key in measurement})
    return redact(summary)


class ToolGateway:
    def __init__(self, store: Store):
        self.store = store

    @staticmethod
    def catalog() -> dict:
        return {"actions": [asdict(action) for action in ACTIONS.values()],
                "readTools": {role: sorted(tools) for role, tools in ROLE_TOOLS.items()}}

    # -- the checks ---------------------------------------------------------------

    @staticmethod
    def _admit(state: dict, action: GatewayAction, mission_id: str, approved_hash: str, check_target: Callable[[dict], str] | None) -> dict:
        mission = next((item for item in state.get("missions", []) if item["id"] == mission_id), None)
        if mission is None:
            raise GatewayDenied(f"Mission {mission_id or '(none)'} does not exist.")
        if mission["status"] != "Working":
            raise GatewayDenied(f"Mission {mission_id} is {mission['status']}, not working: nothing may run for it now.")
        incident = next((item for item in state["incidents"] if item["id"] == mission["incidentId"]), None)
        if incident is None:
            raise GatewayDenied("The mission's incident no longer exists.")
        current = mission["iterations"][-1]
        approval = None
        if action.approval:
            approvals = [item for item in current["decisions"] if item["type"] == "fix" and item["decision"] == "approve"]
            if not approvals:
                raise GatewayDenied("No human approved a fix in this iteration.")
            approval = approvals[-1]
            if approval.get("byId") == mission.get("requestedById") or approval.get("by") == mission.get("requestedBy"):
                raise GatewayDenied("Separation of duties: the fix was approved by the person who started the mission.")
            if not approval.get("approvedHash"):
                raise GatewayDenied("The approval does not record exactly what was approved, so nothing may run on it.")
            if approval["approvedHash"] != approved_hash:
                raise GatewayDenied("The change to run differs from the change the human approved.")
        if action.name.startswith("sandbox.") and not is_payment_sandbox(incident):
            raise GatewayDenied("Sandbox actions may only target the isolated Payment API sandbox incident.")
        problem = check_target(incident) if check_target else ""
        if problem:
            raise GatewayDenied(problem)
        if action.approval and any(entry["missionId"] == mission_id and entry["iteration"] == mission["iteration"] and entry["action"] == action.name
                                   and entry["status"] in {"RUNNING", "SUCCEEDED"} for entry in state.get("gateway", [])):
            raise GatewayDenied("This approved action already ran once for this approval.")
        return {"mission": mission, "incident": incident, "approval": approval}

    def _record(self, state: dict, entry: dict, incident: dict | None) -> None:
        state.setdefault("gateway", []).append(entry)
        audit(state, {"name": "Tool Gateway", "role": "Governance", "id": "tool-gateway"},
              f"Tool Gateway {entry['status'].lower()}: {entry['action']}", entry["id"], incident,
              next_state=entry["status"], evidence=entry.get("missionId", ""))

    # -- the door ---------------------------------------------------------------------

    def execute(self, action_name: str, mission_id: str, approved_value: Any, run: Callable[[], dict],
                check_target: Callable[[dict], str] | None = None, requested_by: str = "Agent mission") -> dict:
        """Run one action if every check passes. Never raises: a refusal or failure comes back as a result."""
        action = ACTIONS.get(action_name)
        approved_hash = fingerprint(approved_value)
        started, stamp = time.monotonic(), now()
        entry = {"id": identifier("GW"), "action": action_name, "kind": action.kind if action else "unknown", "risk": action.risk if action else "High",
                 "missionId": mission_id, "incidentId": "", "iteration": 0, "requestedBy": requested_by, "approvedBy": None,
                 "approvalGateId": None, "paramsHash": approved_hash[:16], "status": "RUNNING", "reason": "", "startedAt": stamp,
                 "finishedAt": None, "durationMs": None, "result": {}}
        with telemetry.span(f"tool_gateway {action_name}", **{"behave.gateway.action": action_name, "behave.mission.id": mission_id,
                                                             "behave.gateway.risk": entry["risk"]}) as span:
            def admit(state: dict) -> dict:
                if action is None:
                    raise GatewayDenied(f"'{action_name}' is not a registered gateway action.")
                admitted = self._admit(state, action, mission_id, approved_hash, check_target)
                approval = admitted["approval"] or {}
                entry.update(incidentId=admitted["incident"]["id"], iteration=admitted["mission"]["iteration"],
                             approvedBy=approval.get("by"), approvalGateId=approval.get("gateId"))
                self._record(state, dict(entry), admitted["incident"])
                return admitted

            try:
                self.store.mutate(admit)
            except GatewayDenied as denied:
                entry.update(status="DENIED", reason=str(denied), finishedAt=now(), durationMs=0)

                def deny(state: dict) -> None:
                    incident = next((item for item in state["incidents"] if item["id"] == entry["incidentId"]), None)
                    self._record(state, dict(entry), incident)

                self.store.mutate(deny)
                span.set_attribute("behave.gateway.decision", "denied")
                return {"status": "DENIED", "error": f"Tool Gateway refused: {denied}", "gatewayId": entry["id"]}

            span.set_attribute("behave.gateway.decision", "allowed")
            try:
                result = run()
            except Exception as error:  # noqa: BLE001 - reported as a failed action, never raised
                result = {"status": "FAILED", "error": f"{type(error).__name__}: {error}"[:300]}
            ok = result.get("status") in {"SUCCEEDED", "OPENED"} or (action_name == "sandbox.run_workload" and "measurement" in result)
            final = "SUCCEEDED" if ok else "FAILED"
            span.set_attribute("behave.gateway.status", final)

            def finish(state: dict) -> None:
                record = next((item for item in state.get("gateway", []) if item["id"] == entry["id"]), None)
                if record is not None:
                    record.update(status=final, finishedAt=now(), durationMs=int((time.monotonic() - started) * 1000), result=_summary(result),
                                  reason="" if ok else str(result.get("error") or "The action did not succeed.")[:300])

            self.store.mutate(finish)
            return {**result, "gatewayId": entry["id"]}
