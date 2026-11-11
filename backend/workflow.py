import asyncio
import hashlib
import json
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException

from .domain import ActionInput, now, redact
from .seed import agent_tasks
from .store import Store


def identifier(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8].upper()}"


def find(state: dict, collection: str, record_id: str) -> dict:
    record = next((item for item in state[collection] if item["id"] == record_id), None)
    if record is None:
        raise HTTPException(404, f"{collection.title()} record not found.")
    return record


def require(user: dict, permission: str, environment: str | None = None) -> None:
    if permission not in user["permissions"]:
        raise HTTPException(403, f"Your {user['role']} role does not have {permission} permission.")
    if environment and environment not in user["environments"]:
        raise HTTPException(403, f"Your role is not authorized to change {environment} resources.")


def audit(state: dict, user: dict, action: str, resource: str, incident: dict | None = None, previous: str = "", next_state: str = "", evidence: str = "", outcome: str = "Recorded") -> None:
    state["audit"].append({"id": identifier("AUD"), "timestamp": now(), "actor": user["name"], "actorId": user.get("id", user["name"]), "role": user["role"], "action": action, "resource": resource,
        "previous": previous, "next": next_state, "outcome": outcome, "correlationId": incident["id"] if incident else resource,
        "environment": incident["environment"] if incident else "Workspace", "evidence": evidence, "synthetic": state["mode"] == "demo"})


def change_gates(state: dict, change: dict) -> list[dict]:
    tests = [record for record in state["tests"] if record["incidentId"] == change["incidentId"] and record["commit"] == change["commit"] and record["timestamp"] >= change.get("proposedAt", "")]
    latest = max(tests, key=lambda record: record["timestamp"], default=None)
    total = latest["passed"] + latest["failed"] if latest else 0
    pass_rate = latest["passed"] / total * 100 if total else 0
    required_rate = state["policy"]["minimumPassRate"]
    test_pass = latest is not None and latest["status"] == "Passed" and latest["failed"] == 0 and pass_rate >= required_rate
    critical = [record for record in state["security"] if record["incidentId"] == change["incidentId"] and record["severity"] == "Critical" and record["status"] != "Resolved"]
    return [
        {"name": "Build & regression", "passed": test_pass, "required": True, "detail": f"{latest['passed']}/{total} checks passed for {change['commit']}" if latest else "Validation evidence for this exact proposed commit is missing"},
        {"name": "Security assessment", "passed": test_pass and not critical, "required": True, "detail": f"{len(critical)} unresolved critical findings" if critical else "Synthetic security review recorded; no scanner connected" if test_pass and state["mode"] == "demo" else "Security validation evidence is required"},
        {"name": "Rollback readiness", "passed": len(change["rollback"]) >= 30, "required": True, "detail": "Rollback plan and recovery thresholds documented"},
        {"name": "Evidence provenance", "passed": any(record["incidentId"] == change["incidentId"] for record in state["evidence"]), "required": True, "detail": "Linked incident evidence is available for human review"},
    ]


def ready(state: dict, change: dict) -> None:
    failed = [gate["name"] for gate in change_gates(state, change) if gate["required"] and not gate["passed"]]
    if failed:
        raise HTTPException(409, "Mandatory gates blocked: " + ", ".join(failed))


def incident_change(state: dict, incident: dict) -> dict:
    change = next((record for record in state["changes"] if record["incidentId"] == incident["id"]), None)
    if change is None:
        raise HTTPException(409, "No remediation proposal is available for this incident.")
    return change


def is_payment_sandbox(incident: dict) -> bool:
    return incident.get("service") == "payment-api" and incident.get("environment") == "Sandbox"


def payment_action_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def queue_payment_sandbox_operation(state: dict, incident: dict, change: dict, action: str, payload: dict, user: dict) -> str:
    operation_id = identifier("SOP")
    state.setdefault("sandboxOperations", []).append({
        "id": operation_id,
        "incidentId": incident["id"],
        "changeId": change["id"],
        "action": action,
        "requested": payload,
        "requestedById": user["id"],
        "requestedAt": now(),
        "status": "PENDING",
    })
    return operation_id


def record_payment_sandbox_result(state: dict, operation_id: str, execution: dict, user: dict, cache_key: str) -> dict:
    operation = find(state, "sandboxOperations", operation_id)
    if operation["status"] != "PENDING":
        return operation
    operation.update(status=execution["status"], completedAt=now(), result=redact(execution))
    incident = find(state, "incidents", operation["incidentId"])
    change = incident_change(state, incident)
    active = execution.get("active_config") or {}
    if operation["status"] == "SUCCEEDED":
        deployment_id = identifier("DEP")
        state["deployments"].append({
            "id": deployment_id,
            "changeId": change["id"],
            "service": "payment-api",
            "version": active["release"],
            "environment": "Sandbox",
            "timestamp": now(),
            "status": "Succeeded and active configuration verified",
        })
        if operation["action"] == "deploy":
            change["status"] = "Post-Deployment Verification"
            incident["status"] = "Monitoring"
        else:
            if change.get("approvalId"):
                find(state, "approvals", change["approvalId"]).update(
                    status="Rejected", reason="Superseded by an authorized sandbox rollback"
                )
            change.update(status="Rolled Back", approvalId=None, proposedAt=now())
            incident.update(status="Reopened", workflowStatus="Idle", recovery=None, workflowGeneration=incident["workflowGeneration"] + 1)
    else:
        change["status"] = "Manual Intervention Required"
    audit(
        state,
        user,
        f"Payment sandbox {operation['action']}",
        operation_id,
        incident,
        previous="PENDING",
        next_state=operation["status"],
        evidence=operation_id,
        outcome=operation["status"],
    )
    result = {
        "message": execution.get("error") or "Payment API sandbox operation completed and active configuration was verified.",
        "incidentId": incident["id"],
        "status": incident["status"],
        "launch": False,
        "generation": incident["workflowGeneration"],
        "sandboxOperationId": operation_id,
        "sandboxOperationStatus": operation["status"],
    }
    if cache_key in state.get("idempotency", {}):
        state["idempotency"][cache_key]["result"] = result
    return result


ACTION_PERMISSIONS = {
    "start-investigation": "workflow:run", "pause": "workflow:run", "resume": "workflow:run", "cancel": "workflow:run", "retry": "workflow:run", "generate-fix": "workflow:run",
    "run-validation": "validation:run", "request-approval": "approval:request", "approve": "approval:decide", "reject": "approval:decide",
    "deploy": "change:deploy", "rollback": "change:deploy", "verify": "recovery:record", "close": "incident:close", "reopen": "incident:update", "assign": "incident:update", "escalate": "incident:update",
}


def act(state: dict, incident_id: str, command: ActionInput, user: dict, key: str) -> dict:
    incident = find(state, "incidents", incident_id)
    require(user, ACTION_PERMISSIONS[command.action], incident["environment"])
    fingerprint = hashlib.sha256(json.dumps(command.model_dump(), sort_keys=True).encode()).hexdigest()
    cache_key = f"{user['id']}:{incident_id}:{key}"
    cache = state.setdefault("idempotency", {})
    if cache_key in cache:
        if cache[cache_key]["fingerprint"] != fingerprint:
            raise HTTPException(409, "This idempotency key was already used with a different request.")
        return {**cache[cache_key]["result"], "launch": False}
    action = command.action
    sandbox_target = is_payment_sandbox(incident)
    if state["mode"] != "demo" and action in {"start-investigation", "resume", "retry", "generate-fix", "run-validation", "deploy", "rollback", "verify"} and not (sandbox_target and action in {"deploy", "rollback"}):
        raise HTTPException(503, "An authorized execution adapter is not configured. No operation was performed.")
    previous = incident["status"]
    tasks = [task for task in state["agents"] if task["incidentId"] == incident_id]
    message = "Action recorded."
    launch = False
    sandbox_operation_id = None
    if action == "start-investigation":
        if incident["workflowStatus"] == "Running" or incident["status"] in {"Awaiting Approval", "Approved", "Deploying", "Monitoring", "Resolved", "Closed"}:
            raise HTTPException(409, "An investigation cannot be started from the current workflow stage.")
        if not any(record["incidentId"] == incident_id for record in state["evidence"]):
            raise HTTPException(409, "Attach at least one evidence record before starting an investigation.")
        fresh = agent_tasks(incident_id)
        if tasks:
            for task in tasks:
                replacement = next(item for item in fresh if item["id"] == task["id"])
                task.update(replacement)
        else:
            state["agents"].extend(fresh)
            tasks = fresh
        for task in tasks:
            task.update(status="Queued", startedAt=now(), lastActivity=now())
        incident.update(status="Investigating", workflowStatus="Running", workflowGeneration=incident["workflowGeneration"] + 1)
        message, launch = "Synthetic investigation started. No external tools are executing.", True
    elif action == "pause":
        if incident["workflowStatus"] != "Running":
            raise HTTPException(409, "Only a running workflow can be paused.")
        incident["workflowStatus"] = "Paused"
        for task in tasks:
            if task["status"] == "Running":
                task["status"] = "Paused"
        message = "Workflow paused. Completed evidence is preserved."
    elif action in {"resume", "retry"}:
        valid = {"Paused"} if action == "resume" else {"Failed", "Cancelled"}
        if incident["workflowStatus"] not in valid:
            raise HTTPException(409, "The workflow is not in a resumable state.")
        if action == "retry" and any(task["retries"] >= state["policy"]["maxRetries"] for task in tasks):
            raise HTTPException(409, "The configured retry budget is exhausted.")
        for task in tasks:
            if task["status"] in {"Failed", "Cancelled", "Paused"}:
                task["status"] = "Queued"
                task["retries"] += int(action == "retry")
        incident.update(workflowStatus="Running", workflowGeneration=incident["workflowGeneration"] + 1)
        message, launch = "Synthetic workflow resumed from its persisted state.", True
    elif action == "cancel":
        if incident["workflowStatus"] not in {"Running", "Paused"}:
            raise HTTPException(409, "Only an active workflow can be cancelled.")
        incident.update(workflowStatus="Cancelled", workflowGeneration=incident["workflowGeneration"] + 1)
        for task in tasks:
            if task["status"] in {"Queued", "Running", "Paused"}:
                task["status"] = "Cancelled"
        message = "Workflow cancelled. Evidence and execution history were retained."
    elif action == "generate-fix":
        if incident["status"] not in {"Root Cause Identified", "Fix Proposed"}:
            raise HTTPException(409, "Complete the evidence-based investigation before preparing a proposal.")
        change = incident_change(state, incident)
        change.update(status="Validation", proposedAt=now(), commit=f"demo-fix-{uuid4().hex[:7]}", approvalId=None)
        incident["status"] = "Fix Proposed"
        message = "Synthetic configuration proposal prepared for review. No repository was modified."
    elif action == "run-validation":
        if incident["status"] not in {"Fix Proposed", "Testing", "Root Cause Identified"}:
            raise HTTPException(409, "A proposed remediation is required before validation.")
        change = incident_change(state, incident)
        if incident["service"] != "checkout-svc" or not incident["synthetic"]:
            raise HTTPException(503, "No validation replay fixture is available for this incident. Configure a runner or record test evidence.")
        run_id = identifier("TEST")
        state["tests"].append({"id": run_id, "incidentId": incident_id, "suite": "Checkout remediation validation", "category": "Regression", "status": "Passed", "passed": 48, "failed": 0, "skipped": 0, "flaky": 0, "duration": 41.8, "coverage": None, "commit": change["commit"], "environment": "Staging", "timestamp": now(), "synthetic": True, "source": "Explicit synthetic validation replay; no code was executed", "cases": [
            {"name": "checkout_concurrent_orders", "status": "Passed", "expected": ">=99% success at 50 concurrent clients", "actual": "Synthetic fixture: 99.8% success", "duration": 12.1, "error": ""},
            {"name": "connection_acquisition_budget", "status": "Passed", "expected": "Acquisition < 250 ms; total connections <= 200", "actual": "Synthetic fixture: 42 ms; 150 connections", "duration": 8.2, "error": ""},
            {"name": "checkout_latency_budget", "status": "Passed", "expected": "p95 < 500 ms", "actual": "Synthetic fixture: 238 ms", "duration": 10.1, "error": ""},
            {"name": "security_policy_fixture", "status": "Passed", "expected": "No unresolved critical findings in the fixture", "actual": "Synthetic fixture review passed; no scanner connected", "duration": 1.1, "error": ""},
        ]})
        evidence_id = identifier("EVD")
        state["evidence"].append({"id": evidence_id, "incidentId": incident_id, "title": "Synthetic remediation validation replay", "type": "Test", "source": f"demo-fixture / {run_id}", "timestamp": now(), "service": incident["service"], "environment": "Staging", "classification": "Validated", "excerpt": "Pre-recorded synthetic outcome: 48 checks passed; error rate 0.2%; p95 238ms; aggregate connection budget 150/200. No tests were executed against a real repository.", "reason": "Supports the demo approval gate only. It is not production validation evidence.", "traceId": "", "synthetic": True})
        for task in tasks:
            if task["phase"] in {4, 5}:
                task.update(status="Completed", lastActivity=now(), outputs=[run_id, evidence_id], task="Synthetic validation fixture reviewed")
        change["status"] = "Validation"
        incident["status"] = "Testing"
        message = "Synthetic validation replay recorded: 48 passed. No real tests or scans were executed."
    elif action == "request-approval":
        change = incident_change(state, incident)
        if incident["status"] not in {"Testing", "Fix Proposed", "Root Cause Identified"}:
            raise HTTPException(409, "The incident is not ready to request approval.")
        ready(state, change)
        approval_id = identifier("APR")
        approval = {"id": approval_id, "changeId": change["id"], "incidentId": incident_id, "title": change["title"], "requestedBy": user["name"], "requestedById": user["id"], "requestedAt": now(), "status": "Pending", "reviewedBy": None, "reviewedById": None, "decidedAt": None, "reason": ""}
        if is_payment_sandbox(incident):
            approval["actionPayloadHash"] = payment_action_hash(change["sandboxAction"])
        state["approvals"].append(approval)
        change.update(approvalId=approval_id, status="Approval")
        incident["status"] = "Awaiting Approval"
        for task in tasks:
            if task["role"] == "release":
                task.update(status="Waiting for Human Approval", task="Separate human decision required")
        message = "Approval requested. A different authorized human must review the change."
    elif action in {"approve", "reject"}:
        change = incident_change(state, incident)
        if not change["approvalId"] or incident["status"] != "Awaiting Approval":
            raise HTTPException(409, "There is no pending approval for this incident.")
        approval = find(state, "approvals", change["approvalId"])
        if approval["status"] != "Pending":
            raise HTTPException(409, "This approval was already decided.")
        if approval.get("missionId"):
            raise HTTPException(409, f"This approval belongs to agent mission {approval['missionId']}. Decide it in the AI War Room so the mission continues.")
        if is_payment_sandbox(incident) and approval.get("actionPayloadHash") != payment_action_hash(change["sandboxAction"]):
            raise HTTPException(409, "The Payment API sandbox action changed after approval was requested.")
        if approval.get("requestedById") == user["id"] or approval["requestedBy"] == user["name"]:
            raise HTTPException(403, "Separation of duties: you cannot approve or reject your own request.")
        if action == "approve":
            ready(state, change)
            if command.confirmation != "APPROVE":
                raise HTTPException(422, "Explicit approval confirmation is required.")
        elif len(command.reason) < 10:
            raise HTTPException(422, "Record a rejection reason of at least 10 characters.")
        approval.update(status="Approved" if action == "approve" else "Rejected", reviewedBy=user["name"], reviewedById=user["id"], decidedAt=now(), reason=redact(command.reason or "Evidence, mandatory gates and rollback plan reviewed."))
        change["status"] = "Scheduled" if action == "approve" else "Draft"
        incident["status"] = "Approved" if action == "approve" else "Fix Proposed"
        message = "Human approval recorded." if action == "approve" else "Change rejected and returned for revision."
    elif action == "deploy":
        change = incident_change(state, incident)
        ready(state, change)
        if incident["status"] != "Approved" or not change["approvalId"]:
            raise HTTPException(409, "A current human approval is required before deployment.")
        approval = find(state, "approvals", change["approvalId"])
        if approval["status"] != "Approved" or not approval["reviewedBy"] or approval["reviewedBy"] == approval["requestedBy"]:
            raise HTTPException(409, "A separate authorized approval is required.")
        if approval.get("requestedById") and approval.get("reviewedById") == approval["requestedById"]:
            raise HTTPException(409, "A separate authorized identity is required.")
        if command.confirmation != incident["environment"]:
            raise HTTPException(422, f"Type {incident['environment']} to confirm the target environment.")
        if sandbox_target:
            if approval.get("actionPayloadHash") != payment_action_hash(change["sandboxAction"]):
                raise HTTPException(409, "The Payment API sandbox action changed after approval was granted.")
            sandbox_operation_id = queue_payment_sandbox_operation(state, incident, change, "deploy", change["sandboxAction"], user)
            change["status"], incident["status"] = "Applying", "Deploying"
            message = "Payment API sandbox deployment started; active configuration verification is pending."
        else:
            deployment_id = identifier("DEP")
            state["deployments"].append({"id": deployment_id, "changeId": change["id"], "service": incident["service"], "version": change["commit"], "environment": incident["environment"], "timestamp": now(), "status": "Simulated - awaiting verification"})
            change["status"], incident["status"] = "Post-Deployment Verification", "Monitoring"
            for task in tasks:
                if task["role"] == "release":
                    task.update(status="Completed", lastActivity=now(), outputs=[deployment_id], task="Authorized deployment simulated; no infrastructure writes")
            message = "Deployment simulated. No production system was contacted or changed. Recovery verification is required."
    elif action == "rollback":
        if incident["status"] not in {"Monitoring", "Resolved"}:
            raise HTTPException(409, "Only a deployed change awaiting closure can be rolled back.")
        if command.confirmation != incident["environment"] or len(command.reason) < 10:
            raise HTTPException(422, "Confirm the target environment and record a rollback reason.")
        change = incident_change(state, incident)
        if change["status"] not in {"Post-Deployment Verification", "Completed"}:
            raise HTTPException(409, "No deployed change is available to roll back.")
        if sandbox_target:
            sandbox_operation_id = queue_payment_sandbox_operation(state, incident, change, "rollback", change["sandboxRollbackAction"], user)
            change["status"] = "Applying Rollback"
            message = "Payment API sandbox rollback started; active configuration verification is pending."
        else:
            if change["approvalId"]:
                find(state, "approvals", change["approvalId"]).update(status="Rejected", reason="Superseded by an authorized simulated rollback")
            change.update(status="Rolled Back", approvalId=None, proposedAt=now())
            incident.update(status="Reopened", workflowStatus="Idle", recovery=None, workflowGeneration=incident["workflowGeneration"] + 1)
            state["deployments"].append({"id": identifier("DEP"), "changeId": change["id"], "service": incident["service"], "version": "previous approved artifact", "environment": incident["environment"], "timestamp": now(), "status": "Simulated rollback"})
            message = "Rollback simulated. No infrastructure was changed; previous approval readiness is invalidated."
    elif action == "verify":
        if incident["status"] != "Monitoring":
            raise HTTPException(409, "Verification requires a deployed change in Monitoring state.")
        change = incident_change(state, incident)
        evidence_id = identifier("EVD")
        state["evidence"].append({"id": evidence_id, "incidentId": incident_id, "title": "Synthetic recovery verification", "type": "Metric", "source": "demo-fixture / recovery-window-15m", "timestamp": now(), "service": incident["service"], "environment": incident["environment"], "classification": "Validated", "excerpt": "Synthetic 15-minute verification window: error rate 0.2% < 1%; p95 238ms < 500ms; no new critical alerts. This is not live telemetry.", "reason": "Records recovery criteria for the controlled demo workflow.", "traceId": "", "synthetic": True})
        incident.update(status="Resolved", recovery={"timestamp": now(), "errorRate": .2, "latency": 238, "actor": user["name"], "synthetic": True, "evidence": evidence_id})
        change["status"] = "Completed"
        message = "Synthetic recovery evidence recorded. Human closure and an outcome summary are still required."
    elif action == "close":
        if incident["status"] != "Resolved" or not incident["recovery"]:
            raise HTTPException(409, "Recovery verification is required before closure.")
        if len(command.reason) < 12:
            raise HTTPException(422, "Provide a closure outcome of at least 12 characters.")
        incident.update(status="Closed", workflowStatus="Completed", outcome=redact(command.reason))
        for task in tasks:
            if task["role"] in {"orchestrator", "summary"}:
                task.update(status="Completed", lastActivity=now(), task="Human-reviewed outcome recorded", outputs=[incident_id])
        state["knowledge"].append({"id": identifier("KB"), "title": f"Resolution draft: {incident['title']}", "type": "Incident report", "owner": user["name"], "ownerId": user["id"], "version": "0.1", "reviewedAt": now(), "approved": False, "source": "Human closure; pending knowledge review", "services": [incident["service"]], "incidents": [incident_id], "body": f"Recorded outcome\n{redact(command.reason)}\n\nVerification evidence\n{incident['recovery']['evidence']}\n\nThis draft requires separate knowledge approval. Synthetic verification does not establish a real production resolution."})
        message = "Incident closed with a recorded outcome. A knowledge draft is available for review."
    elif action == "reopen":
        if incident["status"] not in {"Closed", "Resolved"}:
            raise HTTPException(409, "Only a resolved or closed incident can be reopened.")
        if len(command.reason) < 10:
            raise HTTPException(422, "Record why the incident is being reopened.")
        incident.update(status="Reopened", workflowStatus="Idle", recovery=None, workflowGeneration=incident["workflowGeneration"] + 1)
        for change in state["changes"]:
            if change["incidentId"] == incident_id:
                if change["approvalId"]:
                    find(state, "approvals", change["approvalId"]).update(status="Rejected", reason="Superseded by incident reopening")
                change.update(approvalId=None, status="Draft", proposedAt=now())
        message = "Incident reopened. Previous approvals and validation readiness have been invalidated."
    elif action == "assign":
        if len(command.owner) < 3:
            raise HTTPException(422, "Select an incident commander.")
        incident.update(owner=redact(command.owner), commander=redact(command.owner))
        message = "Incident ownership updated."
    elif action == "escalate":
        if len(command.reason) < 10:
            raise HTTPException(422, "Record an escalation reason.")
        incident["severity"] = "Critical"
        message = "Severity escalated to Critical. No external notification integration is connected."
    audit(state, user, action, incident_id, incident, previous, incident["status"])
    result = {"message": message, "incidentId": incident_id, "status": incident["status"], "launch": launch, "generation": incident["workflowGeneration"]}
    if sandbox_operation_id:
        result["sandboxOperationId"] = sandbox_operation_id
    cache[cache_key] = {"fingerprint": fingerprint, "result": result}
    if len(cache) > 2000:
        del cache[next(iter(cache))]
    return result


async def run_demo_workflow(store: Store, incident_id: str, generation: int, step_seconds: float) -> None:
    agent_user = {"name": "Demo orchestrator", "role": "Bounded synthetic worker"}
    started = monotonic()
    try:
        for phase in range(4):
            def start_phase(state: dict) -> bool:
                incident = find(state, "incidents", incident_id)
                if incident["workflowStatus"] != "Running" or incident["workflowGeneration"] != generation:
                    return False
                if monotonic() - started > state["policy"]["maxTaskSeconds"]:
                    raise TimeoutError("Workflow time budget exceeded")
                for task in state["agents"]:
                    if task["incidentId"] == incident_id and task["phase"] in {phase, -1} and task["status"] != "Completed":
                        task.update(status="Running", task=f"Evaluating synthetic phase {phase + 1}", lastActivity=now())
                return True

            if not store.mutate(start_phase):
                return
            await asyncio.sleep(step_seconds)

            def finish_phase(state: dict) -> bool:
                incident = find(state, "incidents", incident_id)
                if incident["workflowStatus"] != "Running" or incident["workflowGeneration"] != generation:
                    return False
                evidence = [record["id"] for record in state["evidence"] if record["incidentId"] == incident_id]
                for task in state["agents"]:
                    if task["incidentId"] == incident_id and task["phase"] == phase:
                        task.update(status="Completed", task="Synthetic evidence replay completed", lastActivity=now(), inputs=evidence[:4], outputs=evidence[:2])
                audit(state, agent_user, f"Synthetic investigation phase {phase + 1}", incident_id, incident, evidence=evidence[0] if evidence else "")
                if phase == 1 and (incident["service"] != "checkout-svc" or not incident["synthetic"]):
                    incident["workflowStatus"] = "Completed"
                    for task in state["agents"]:
                        if task["incidentId"] == incident_id and task["phase"] >= 2:
                            task.update(status="Waiting for Evidence", task="No scenario fixture or configured diagnostic adapter; manual investigation required")
                    return False
                if phase == 2:
                    incident["status"] = "Root Cause Identified"
                if phase == 3:
                    change = incident_change(state, incident)
                    change.update(status="Validation", proposedAt=now(), commit=f"demo-fix-{generation}", approvalId=None)
                    incident.update(status="Fix Proposed", workflowStatus="Completed")
                    for task in state["agents"]:
                        if task["incidentId"] == incident_id and task["role"] == "orchestrator":
                            task.update(status="Waiting for Human Approval", task="Review the proposal and run the synthetic validation replay")
                return True

            if not store.mutate(finish_phase):
                return
    except Exception:
        def fail(state: dict) -> None:
            incident = find(state, "incidents", incident_id)
            if incident["workflowGeneration"] != generation:
                return
            incident["workflowStatus"] = "Failed"
            for task in state["agents"]:
                if task["incidentId"] == incident_id and task["status"] == "Running":
                    task.update(status="Failed", task="Workflow infrastructure failure; bounded retry available", lastActivity=now())
            audit(state, agent_user, "Workflow failed", incident_id, incident, outcome="Infrastructure failure")
        store.mutate(fail)