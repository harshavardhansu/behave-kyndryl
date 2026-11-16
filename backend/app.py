import csv
import logging
from pathlib import Path
import os
import hashlib
import io
import json
import re
import secrets
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from threading import Lock, Thread
from time import monotonic
from typing import Annotated, Literal

import jwt
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field, ValidationError
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from .data_governance import DataPolicyError, authorize_model_context, evidence_provenance, strongest_classification
from .domain import ActionInput, DataClassification, EvidenceInput, IncidentInput, PERSONAS, PolicyInput, ReviewInput, Settings, StrictModel, now, persona, redact
from .payment_sandbox import PaymentSandboxControl, PaymentSandboxControlAdapter
from .providers import Assessment, ProviderError, configured_provider, validate_references
from .seed import fresh_workspace, real_workspace, seed_workspace
from . import platform_status, real_views
from .dependency_inventory import inventory as dependency_inventory
from .ai_client import AIBudget, AIUnavailable, ai_configured, key_mode
from .foundry_agents import get_all_agents
from .foundry_runtime import FoundryAgentService, foundry_agent_status
from .foundry_brain import FoundryBrain
from .mission import STEPS, DecisionInput, MissionTools, SimulatedBrain, cancel_mission, decide, pause_interrupted, resume_mission, run_mission, start_mission
from .store import Store
from .connectors import Projects, configure as configure_connectors, ensure_services, forget_snapshots, storage_root
from .error_intel import correlate, parse_log_lines, record_errors
from .github_browse import GitHubBrowser, GitHubLookupError
from .tool_gateway import ToolGateway
from . import knowledge_search, telemetry
from .task_inputs import TaskStorage, UnsafeArchive, inspect_zip, profile_project
from .workflow import act, audit, change_gates, find, identifier, is_payment_sandbox, record_payment_sandbox_result, require, run_demo_workflow
from .payment_local import LocalPaymentSandbox, SandboxError, read_recent_errors
from .sandbox_records import record_measurement
from .repo_analyzer import analyze_github_file, scan_repository
from .resolution_report import generate_resolution_report
from .mission_report import generate_mission_report_pdf, pick_mission
from .pdf_generator import generate_incident_resolution_pdf, generate_repo_analysis_pdf


class LoginInput(StrictModel):
    role: str = "Incident Manager"


class AssessmentInput(StrictModel):
    confirmed: Literal[True]


class KnowledgeInput(StrictModel):
    title: str = Field(min_length=8, max_length=180)
    type: Literal["Runbook", "Troubleshooting guide", "Service documentation", "Architecture document", "Incident report", "Known error pattern", "Remediation procedure", "Release checklist", "Technical FAQ"]
    body: str = Field(min_length=30, max_length=30_000)
    services: list[str] = Field(default_factory=list, max_length=20)
    incidents: list[str] = Field(default_factory=list, max_length=20)


class KnowledgeReview(StrictModel):
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=10, max_length=2000)


class ErrorStatusInput(StrictModel):
    status: Literal["Open", "Resolved", "Ignored"]
    note: str = Field("", max_length=600)


class ExportInput(StrictModel):
    format: Literal["json", "csv"] = "json"
    incidentId: str = ""
    environment: str = "All environments"


class RecordedTestInput(StrictModel):
    suite: str = Field(min_length=5, max_length=160)
    commit: str = Field(min_length=3, max_length=100)
    passed: int = Field(ge=0, le=1_000_000)
    failed: int = Field(ge=0, le=1_000_000)
    skipped: int = Field(0, ge=0, le=1_000_000)
    source: str = Field(min_length=10, max_length=500)
    duration: float = Field(ge=0, le=86_400)


class RepositoryInput(StrictModel):
    source: Literal["fixture", "repository", "incident"]  # "incident": the source connected to the incident (ZIP, file or repository)
    url: str = Field("", max_length=500)
    branch: str = Field("main", min_length=1, max_length=120)
    commit: str = Field("c7f4e21", min_length=3, max_length=100)
    stack: str = Field("Java / Spring Boot", min_length=2, max_length=100)
    environment: Literal["Development", "Staging", "Production"] = "Staging"
    scope: list[Literal["Configuration", "Code paths", "Dependencies", "Tests", "Security"]] = Field(min_length=1, max_length=5)
    incidentId: str | None = Field(default="INC-1042", max_length=100)
    permissionConfirmed: Literal[True]


def _configure_logging() -> None:
    """Show the app's own messages (behave.*: Foundry sync, agent fallbacks) in the container logs."""
    logger = logging.getLogger("behave")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


def create_app(settings: Settings | None = None, store: Store | None = None, sandbox_control: PaymentSandboxControl | None = None) -> FastAPI:
    config = settings or Settings()
    _configure_logging()
    if config.mode == "production":
        if make_url(config.database_url).get_backend_name() != "postgresql" or (store is not None and store.engine.dialect.name != "postgresql"):
            raise RuntimeError("Production requires PostgreSQL. SQLite is limited to local demonstration and isolated testing.")
        if not config.azure_tenant_id or not config.auth_audience:
            raise RuntimeError("Production requires AZURE_TENANT_ID and AGENTICA_AUTH_AUDIENCE; demo authentication is disabled.")
    database = store or Store(config.database_url)
    database.initialize(real_workspace(config.mode) if config.workspace == "real" else seed_workspace(config.mode == "demo"))
    if database.read()["mode"] != config.mode:
        raise RuntimeError("Use a separate database for demo and production. Synthetic records must never be promoted as production data.")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        def recover(state: dict) -> None:
            for incident in state["incidents"]:
                if incident["workflowStatus"] == "Running":
                    incident["workflowStatus"] = "Paused"
                    incident["workflowGeneration"] += 1
                    for task in state["agents"]:
                        if task["incidentId"] == incident["id"] and task["status"] == "Running":
                            task["status"] = "Paused"
                    audit(state, {"name": "System", "role": "Recovery"}, "Interrupted workflow paused", incident["id"], incident)
            for execution in state.get("modelRequests", {}).values():
                if execution["status"] == "Running":
                    execution.update(status="MANUAL_INTERVENTION_REQUIRED", lastActivity=now(), errorCategory="INTERRUPTED_PROVIDER_REQUEST", error="The provider outcome is uncertain after restart. Review the original request before making another request.")
                    audit(state, {"name": "System", "role": "Recovery"}, "Interrupted model request requires review", execution.get("executionId", "legacy-model-request"), outcome="MANUAL_INTERVENTION_REQUIRED")
            for operation in state.get("sandboxOperations", []):
                if operation["status"] == "PENDING":
                    operation.update(status="MANUAL_INTERVENTION_REQUIRED", completedAt=now(), error="The sandbox operation outcome is uncertain after restart. Inspect active configuration before taking further action.")
                    audit(state, {"name": "System", "role": "Recovery"}, "Payment sandbox operation requires review", operation["id"], outcome="MANUAL_INTERVENTION_REQUIRED")
            pause_interrupted(state)
            ensure_services(state, Projects.load(), now())  # connected projects (projects.json) appear in the service catalog
        database.mutate(recover)
        if config.foundry_auto_sync and isinstance(application.state.mission_brain, FoundryBrain) and not database.read().get("foundryAgents"):
            def sync_agents() -> None:
                try:
                    results = application.state.mission_brain.agents.provision()
                    logging.getLogger("behave.foundry").warning("Foundry auto-sync: %d agents ready (%s).", len(results), ", ".join(sorted({item["action"] for item in results})))
                except Exception as error:  # noqa: BLE001 - reported in the logs and the Foundry agents tab
                    logging.getLogger("behave.foundry").warning("Foundry auto-sync failed: %s", error)

            Thread(target=sync_agents, name="foundry-auto-sync", daemon=True).start()
        knowledge_search.refresh(lambda: database.read()["knowledge"])  # make the search index match the knowledge base
        yield
        telemetry.shutdown()
        control = application.state.sandbox_control
        if isinstance(control, LocalPaymentSandbox):
            control.stop()

    application = FastAPI(
        title="Behave Kyndryl API",
        description="Behave Kyndryl: an Orchestrator forms a team of specialist agents per incident; humans approve every important decision.",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        swagger_ui_parameters={"syntaxHighlight.theme": "monokai", "tryItOutEnabled": True},
    )
    application.state.store = database
    configure_connectors(config)  # connectors and task storage follow this application's settings
    knowledge_search.configure(config)  # organizational memory in Azure AI Search (when configured)
    telemetry.configure(config.applicationinsights_connection_string.get_secret_value())
    task_storage = TaskStorage(storage_root(config))
    application.state.settings = config
    application.state.provider = configured_provider(config)
    application.state.mission_brain = FoundryBrain(config, database) if ai_configured(config) and config.ai_allowed_classifications else SimulatedBrain()
    # Local mode (default) runs the real Payment API as a local process: no Docker needed.
    application.state.sandbox_control = sandbox_control or (
        LocalPaymentSandbox() if os.getenv("PAYMENT_SANDBOX_MODE", "local") == "local" else PaymentSandboxControlAdapter()
    )
    application.state.tool_gateway = ToolGateway(database)  # every outside action by the agents passes through here
    application.state.mission_tools = MissionTools(application.state.sandbox_control if isinstance(application.state.sandbox_control, LocalPaymentSandbox) else None,
                                                   gateway=application.state.tool_gateway)
    if hasattr(application.state.mission_brain, "sandbox") and isinstance(application.state.sandbox_control, LocalPaymentSandbox):
        application.state.mission_brain.sandbox = application.state.sandbox_control
    sandbox_operation_lock = Lock()
    rate_buckets: dict[str, deque] = defaultdict(deque)
    jwks = jwt.PyJWKClient(f"https://login.microsoftonline.com/{config.azure_tenant_id}/discovery/v2.0/keys", cache_keys=True, timeout=5) if config.mode == "production" else None

    @application.middleware("http")
    async def guard(request: Request, call_next):
        host = request.url.hostname or ""
        if config.mode == "demo" and host not in {"localhost", "127.0.0.1", "::1", "testserver"}:
            extra_hosts = {item.strip().lower() for item in config.demo_hosts.split(",") if item.strip()}
            if host.lower() not in extra_hosts or not config.require_platform_auth:
                return JSONResponse(status_code=403, content={"detail": "Demo access is restricted to loopback hosts."})
            # Behind Azure Container Apps sign-in: every request except the health probe must carry the
            # signed-in user that the platform adds (and strips from client requests).
            if request.url.path != "/api/v1/health" and not request.headers.get("x-ms-client-principal-id"):
                return JSONResponse(status_code=401, content={"detail": "Sign in required."})
        origin = request.headers.get("origin", "")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            allowed = origin in config.allowed_origins.split(",") or (config.mode == "demo" and re.fullmatch(r"http://(?:localhost|127\.0\.0\.1):\d+", origin))
            if origin and not allowed:
                return JSONResponse(status_code=403, content={"detail": "Cross-origin write rejected."})
            length = request.headers.get("content-length", "0")
            if not length.isdecimal() or int(length) > config.max_upload_bytes + 65_536:
                return JSONResponse(status_code=413, content={"detail": "Request exceeds the configured upload limit."})
        client = request.client.host if request.client else "unknown"
        bucket = rate_buckets[client]
        timestamp = monotonic()
        while bucket and timestamp - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= 300:
            return JSONResponse(status_code=429, content={"detail": "Rate limit reached. Retry after one minute."}, headers={"Retry-After": "60"})
        bucket.append(timestamp)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError):
        messages = [f"{'.'.join(str(part) for part in item['loc'][1:])}: {item['msg']}" for item in error.errors()]
        return JSONResponse(status_code=422, content={"detail": "; ".join(messages)})

    @application.exception_handler(Exception)
    async def unexpected_error(_: Request, __: Exception):
        return JSONResponse(status_code=500, content={"detail": "The operation could not be completed. No successful outcome is implied. Check API health and retry safe operations."})

    @application.exception_handler(SQLAlchemyError)
    async def database_error(_: Request, __: SQLAlchemyError):
        return JSONResponse(status_code=503, content={"detail": "Durable storage is unavailable. No successful outcome is confirmed. Check authoritative state before retrying; reuse the original idempotency key where supported."})

    def authenticated(request: Request) -> dict:
        if config.mode == "production":
            authorization = request.headers.get("authorization", "")
            if not authorization.startswith("Bearer ") or jwks is None:
                raise HTTPException(401, "An Entra access token is required.")
            token = authorization.removeprefix("Bearer ")
            try:
                signing_key = jwks.get_signing_key_from_jwt(token)
                claims = jwt.decode(token, signing_key.key, algorithms=["RS256"], audience=config.auth_audience, issuer=f"https://login.microsoftonline.com/{config.azure_tenant_id}/v2.0", options={"require": ["exp", "iat", "aud", "iss", "oid", "tid"]})
                if claims["tid"] != config.azure_tenant_id or not isinstance(claims["oid"], str) or not claims["oid"].strip():
                    raise HTTPException(401, "Identity tenant or object identifier is invalid.")
                roles = claims.get("roles", [])
                if not isinstance(roles, list):
                    raise HTTPException(403, "An assigned application role is required.")
                role = next((item for item in roles if isinstance(item, str) and item in PERSONAS), None)
                if role is None:
                    raise HTTPException(403, "An assigned application role is required.")
                user = persona(role)
                user.update(id=claims["oid"], name=claims.get("name", "Entra user"), initials="EU", identityTenantId=claims["tid"])
                return {"user": user, "csrf": "", "mode": config.mode, "workspace": "Northstar Commerce"}
            except jwt.PyJWTError:
                raise HTTPException(401, "Invalid or expired identity token.") from None
        token = request.cookies.get("agentica_session", "")
        session = database.get_session(hashlib.sha256(token.encode()).hexdigest()) if token else None
        if not session or datetime.fromisoformat(session["expiresAt"]) < datetime.now(timezone.utc):
            raise HTTPException(401, "Your session has expired. Sign in again.")
        if request.method not in {"GET", "HEAD"} and not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), session["csrf"]):
            raise HTTPException(403, "The request could not be verified. Reload your session.")
        return {key: value for key, value in session.items() if key != "expiresAt"}

    Auth = Annotated[dict, Depends(authenticated)]

    @application.get("/api/v1/health")
    def health():
        result = {"status": "ok", "database": "AVAILABLE", "mode": config.mode,
                  "execution": "Tool Gateway: Payment API sandbox and opted-in pull requests only, after a separate human approval"}
        try:
            database.check_health()
            result["workspace"] = database.read().get("workspaceKind", "demo")
        except SQLAlchemyError:
            return JSONResponse(status_code=503, content={**result, "status": "unavailable", "database": "UNAVAILABLE"})
        return result

    @application.post("/api/v1/auth/demo")
    def login(payload: LoginInput, request: Request, response: Response):
        if config.mode != "demo":
            raise HTTPException(404, "Demo identities are unavailable.")
        if payload.role not in PERSONAS:
            raise HTTPException(422, "Unknown demo role.")
        old_token = request.cookies.get("agentica_session", "")
        if old_token:
            database.delete_session(hashlib.sha256(old_token.encode()).hexdigest())
        token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        result = {"user": persona(payload.role), "csrf": csrf, "mode": "demo", "workspace": "Northstar Commerce"}
        database.save_session(hashlib.sha256(token.encode()).hexdigest(), {**result, "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()})
        response.set_cookie("agentica_session", token, httponly=True, samesite="strict", max_age=28_800, path="/api", secure=config.secure_cookies)
        database.mutate(lambda state: audit(state, result["user"], "Role selected" if state.get("workspaceKind") == "real" else "Demo identity selected", payload.role))
        return result

    @application.get("/api/v1/auth/session")
    def session(auth: Auth):
        return auth

    @application.post("/api/v1/auth/logout")
    def logout(request: Request, response: Response, auth: Auth):
        database.delete_session(hashlib.sha256(request.cookies.get("agentica_session", "").encode()).hexdigest())
        response.delete_cookie("agentica_session", path="/api", secure=config.secure_cookies)
        database.mutate(lambda state: audit(state, auth["user"], "Signed out", auth["user"]["id"]))
        return {"message": "Signed out."}

    @application.get("/api/v1/workspace")
    def snapshot(auth: Auth):
        require(auth["user"], "read")
        state = database.read()
        state.pop("idempotency", None)
        state.pop("aiCache", None)
        for mission in state.get("missions", []):
            mission.pop("brainCache", None)
        state["aiMode"] = application.state.mission_brain.mode
        # The squads the mission engine runs, in order: the War Room draws exactly these (any number).
        state["missionSteps"] = [{"id": step, "name": name, "roles": list(roles)} for step, name, roles in STEPS]
        control = application.state.sandbox_control
        state["paymentSandbox"] = control.status() if hasattr(control, "status") else {"mode": "container", "running": False}
        AIBudget(database, config)._usage(state)
        for change in state["changes"]:
            change["gates"] = change_gates(state, change)
        for integration in state["integrations"]:
            if integration["id"] == "foundry":
                integration["dataPolicy"] = {"allowedClassifications": config.ai_allowed_classifications, "restrictedDataAllowed": False}
                if "AGENTICA_AI_ALLOWED_CLASSIFICATIONS" not in integration["required"]:
                    integration["required"].append("AGENTICA_AI_ALLOWED_CLASSIFICATIONS")
                if ai_configured(config):
                    integration["status"] = "Configured, not verified" if config.ai_allowed_classifications else "Blocked by data policy"
                    integration["authentication"] = "API key" if key_mode(config) else "Microsoft Entra ID"
            if integration["id"] == "entra" and config.mode == "production":
                integration["status"] = "Configured, not verified"
        if state.get("workspaceKind") == "real":
            # Real workspace: every status and number is checked or computed from real records, never stored demo values.
            state["integrations"] = platform_status.statuses(config, state, len(state.get("foundryAgents") or {}), ai_configured(config))
            state["trends"] = real_views.trends(state)
            state["services"] = real_views.services(state)
            state["metrics"] = real_views.metrics(state)
            state["snapshotAt"] = now()  # a real workspace is always "as of now"
        state["workspaceKind"] = state.get("workspaceKind", "demo")
        state["gateway"] = sorted(state.get("gateway", []), key=lambda entry: entry["startedAt"], reverse=True)[:50]
        state["audit"].sort(key=lambda event: event["timestamp"], reverse=True)
        state["incidents"].sort(key=lambda incident: incident["detectedAt"], reverse=True)
        return state

    @application.get("/api/v1/gateway")
    def gateway_catalog(auth: Auth):
        """The Tool Gateway's registered actions, per-agent read permissions and recent decisions."""
        require(auth["user"], "read")
        log = sorted(database.read().get("gateway", []), key=lambda entry: entry["startedAt"], reverse=True)[:100]
        return {**application.state.tool_gateway.catalog(), "log": log}

    @application.get("/api/v1/incidents/{incident_id}/source")
    def incident_source(incident_id: str, auth: Auth):
        """The source code connected to an incident: where it comes from, its files and what the project is."""
        require(auth["user"], "read")
        incident = find(database.read(), "incidents", incident_id)
        code = Projects.load().resolve(incident).code
        paths = code.paths()
        return {"label": code.label if paths else "", "files": paths[:2000], "total": len(paths), "project": profile_project(code) if paths else None,
                "pullRequests": bool(paths and getattr(code, "pull_requests", False) and getattr(code, "token", "")),
                "problem": "" if paths else (code.problem or "No source code is connected to this incident.")}

    @application.get("/api/v1/incidents/{incident_id}/source/file")
    def incident_source_file(incident_id: str, auth: Auth, path: str = ""):
        """One file of the incident's source, read-only, with secrets redacted. Only listed files can be read."""
        require(auth["user"], "read")
        incident = find(database.read(), "incidents", incident_id)
        code = Projects.load().resolve(incident).code
        if path not in code.paths():
            raise HTTPException(404, "That file is not part of this incident's source.")
        text = code.read(path) or ""
        return {"path": path, "lines": len(text.splitlines()), "truncated": len(text) > 200_000, "text": redact(text[:200_000])}

    @application.get("/api/v1/incidents/{incident_id}/dependencies")
    def incident_dependencies(incident_id: str, auth: Auth):
        """Dependencies declared in the manifests of the task's source code (uploaded or from GitHub)."""
        require(auth["user"], "read")
        incident = find(database.read(), "incidents", incident_id)
        code = Projects.load().resolve(incident).code
        if not code.paths():
            return {"source": "", "manifests": [], "dependencies": [], "total": 0, "unpinned": 0,
                    "note": code.problem or "No source code is connected to this incident, so there is nothing to inventory."}
        return dependency_inventory(code)

    @application.get("/api/v1/foundry/agents")
    def list_foundry_agents(auth: Auth):
        require(auth["user"], "read")
        return foundry_agent_status(config, database)

    class FoundrySyncInput(StrictModel):
        roles: list[str] = Field(default_factory=list, max_length=14)
        force: bool = False

    @application.post("/api/v1/foundry/agents/sync")
    def sync_foundry_agents(payload: FoundrySyncInput, auth: Auth):
        """Create or update the agents in the Azure AI Foundry project (needs Microsoft Entra sign-in)."""
        require(auth["user"], "admin:write")
        service = application.state.mission_brain.agents if hasattr(application.state.mission_brain, "agents") else FoundryAgentService(config, database)
        try:
            results = service.provision(payload.roles or None, payload.force)
        except AIUnavailable as error:
            raise HTTPException(503, str(error)) from None
        created = [item for item in results if item["action"] != "unchanged"]
        database.mutate(lambda state: audit(state, auth["user"], "Foundry agents synced", "foundry", next_state=f"{len(created)} created or updated, {len(results) - len(created)} unchanged"))
        return {**foundry_agent_status(config, database), "results": results}

    @application.post("/api/v1/incidents", status_code=201)
    def create_incident(payload: IncidentInput, auth: Auth):
        require(auth["user"], "incident:create", payload.environment)
        if (payload.service == "payment-api") != (payload.environment == "Sandbox"):
            raise HTTPException(422, "The Payment API sandbox service is available only in the Sandbox environment.")
        if payload.environment == "Sandbox" and payload.service != "payment-api":
            raise HTTPException(422, "Only the approved Payment API sandbox service is registered in the Sandbox environment.")

        project = None
        if payload.repository:
            # Check the repository can really be read before a task is created on it.
            code = Projects.load().resolve({"service": payload.service, "repository": payload.repository.model_dump()}).code
            if not code.paths():
                raise HTTPException(422, code.problem or "The repository has no readable source files.")
            project = profile_project(code)

        def create(state: dict):
            if payload.service != "payment-api" and not any(service["id"] == payload.service for service in state["services"]):
                # A new application: add it to the catalog so tasks, errors and reports can be filtered by it.
                state["services"].append({
                    "id": payload.service, "name": payload.service, "type": "Service", "health": "Healthy", "environment": payload.environment,
                    "latency": 0, "errorRate": 0, "rps": 0, "observedAt": now(), "evidence": [], "changes": [], "incidents": [],
                    "position": {"x": 700, "y": 115}, "connected": True,
                })
            record = {**redact(payload.model_dump()), "id": identifier("INC"), "status": "New", "owner": auth["user"]["name"], "commander": auth["user"]["name"], "slaMinutes": 60 if payload.severity == "Critical" else 240 if payload.severity == "High" else 1440, "workflowStatus": "Idle", "workflowGeneration": 0, "outcome": "", "recovery": None, "synthetic": False}
            state["incidents"].append(record)
            if payload.service == "payment-api":
                state["changes"].append({
                    "id": identifier("CHG"),
                    "incidentId": record["id"],
                    "title": "Restore Payment API connection pool",
                    "status": "Draft",
                    "risk": "Low",
                    "owner": auth["user"]["name"],
                    "environment": "Sandbox",
                    "branch": "sandbox/payment-pool-recovery",
                    "commit": f"sandbox-{identifier('COM')}",
                    "files": ["Payment API sandbox configuration"],
                    "diff": "PAYMENT_DB_POOL_SIZE: 5 -> 20; keep release v3.8.1 active.",
                    "rollback": "Set release to previous and pool size to 20 in the isolated Payment API sandbox; verify Feature X is absent.",
                    "plan": ["Confirm the measured pool exhaustion evidence", "Apply pool size 20 through the sandbox control adapter", "Repeat the calibrated workload and inspect Feature X"],
                    "justification": "Restore the previous connection-pool capacity while preserving the v3.8.1 summary endpoint.",
                    "approvalId": None,
                    "gates": [],
                    "sandboxAction": {"release": "3.8.1", "pool_size": 20},
                    "sandboxRollbackAction": {"release": "previous", "pool_size": 20},
                })
            record["sourceUploads"] = []
            if project:
                record["project"] = project
            if payload.error:
                record_errors(state, record, payload.error, "", now(), identifier)  # a pasted stack trace is tracked like an uploaded log
            audit(state, auth["user"], "Incident created", record["id"], record, next_state="New")
            return record
        return database.mutate(create)

    @application.post("/api/v1/incidents/{incident_id}/actions")
    def action(incident_id: str, payload: ActionInput, request: Request, background: BackgroundTasks, auth: Auth):
        key = request.headers.get("Idempotency-Key", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key):
            raise HTTPException(422, "An idempotency key of 8-100 safe characters is required.")
        cache_key = f"{auth['user']['id']}:{incident_id}:{key}"
        result = database.mutate(lambda state: act(state, incident_id, payload, auth["user"], key))
        operation_id = result.get("sandboxOperationId")
        if operation_id:
            with sandbox_operation_lock:
                state = database.read()
                operation = next((item for item in state.get("sandboxOperations", []) if item["id"] == operation_id), None)
                if operation is None:
                    raise HTTPException(500, "The Payment API sandbox operation record is unavailable.")
                if operation["status"] == "PENDING":
                    try:
                        execution = application.state.sandbox_control.apply_configuration(
                            operation["requested"]["release"],
                            operation["requested"]["pool_size"],
                            actor_id=auth["user"]["id"],
                        )
                    except Exception as error:
                        execution = {"status": "MANUAL_INTERVENTION_REQUIRED", "error": f"Sandbox control failed ({type(error).__name__}); inspect the adapter audit before retrying."}
                    result = database.mutate(
                        lambda current: record_payment_sandbox_result(current, operation_id, execution, auth["user"], cache_key)
                    )
                else:
                    result = state.get("idempotency", {}).get(cache_key, {}).get("result", result)
            if result.get("sandboxOperationStatus") != "SUCCEEDED":
                raise HTTPException(503, result.get("message", "The Payment API sandbox operation was not verified. No success is implied."))
        if result["launch"]:
            background.add_task(run_demo_workflow, database, incident_id, result["generation"], config.demo_step_seconds)
        return result

    def launch_mission(background: BackgroundTasks, result: dict) -> None:
        if result.get("launch"):
            background.add_task(run_mission, database, result["missionId"], result["runToken"], application.state.mission_brain, config.demo_step_seconds, application.state.mission_tools)

    # ---------------- Payment API sandbox (local, real, measurable) ----------------

    def local_sandbox() -> LocalPaymentSandbox:
        control = application.state.sandbox_control
        if not isinstance(control, LocalPaymentSandbox):
            raise HTTPException(409, "The local Payment API sandbox is not enabled (PAYMENT_SANDBOX_MODE is not 'local').")
        return control

    def sandbox_incident(state: dict, incident_id: str | None) -> dict | None:
        if incident_id:
            incident = find(state, "incidents", incident_id)
            if not is_payment_sandbox(incident):
                raise HTTPException(422, "Measurements can only be attached to a Payment API sandbox incident.")
            return incident
        return next((item for item in state["incidents"] if is_payment_sandbox(item) and item["status"] not in {"Closed", "Resolved"}), None)

    class SandboxRunInput(StrictModel):
        incidentId: str | None = Field(None, max_length=40)

    @application.get("/api/v1/sandbox/payment")
    def sandbox_status(auth: Auth):
        require(auth["user"], "read")
        status = application.state.sandbox_control.status() if hasattr(application.state.sandbox_control, "status") else {"mode": "container"}
        return {**status, "measurements": database.read().get("sandboxMeasurements", [])[-10:]}

    @application.post("/api/v1/sandbox/payment/start")
    def sandbox_start(auth: Auth):
        require(auth["user"], "workflow:run", "Sandbox")
        try:
            status = local_sandbox().start(actor_id=auth["user"]["id"])
        except SandboxError as error:
            raise HTTPException(503, str(error)) from None
        database.mutate(lambda state: audit(state, auth["user"], "Payment sandbox started", "payment-api", next_state="v3.8.1 / pool 5"))
        return status

    @application.post("/api/v1/sandbox/payment/reset")
    def sandbox_reset(auth: Auth):
        require(auth["user"], "workflow:run", "Sandbox")
        result = local_sandbox().apply_configuration("3.8.1", 5, actor_id=auth["user"]["id"])
        if result["status"] != "SUCCEEDED":
            raise HTTPException(503, result["error"])
        database.mutate(lambda state: audit(state, auth["user"], "Payment sandbox reset to the faulty release", "payment-api", next_state="v3.8.1 / pool 5"))
        return local_sandbox().status()

    @application.post("/api/v1/sandbox/payment/workload")
    def sandbox_workload(payload: SandboxRunInput, auth: Auth):
        require(auth["user"], "workflow:run", "Sandbox")
        sandbox = local_sandbox()
        try:
            measurement = sandbox.run_workload(50)
        except SandboxError as error:
            raise HTTPException(409, str(error)) from None
        log_lines = read_recent_errors(sandbox)

        def record(state: dict) -> dict:
            incident = sandbox_incident(state, payload.incidentId)
            ids = record_measurement(state, incident, measurement, log_lines, auth["user"], "manual run")
            return {"measurement": measurement, "evidenceIds": ids, "incidentId": incident["id"] if incident else None}

        return database.mutate(record)

    class ResetInput(StrictModel):
        mode: Literal["demo", "fresh", "real"] = "demo"

    @application.post("/api/v1/admin/demo-reset")
    def demo_reset(auth: Auth, payload: ResetInput = ResetInput()):
        """Restore the realistic demo stories or clean the workspace to a fresh slate.
        Backs up the current data first. Demo mode only.
        """
        require(auth["user"], "admin:write")
        if config.mode != "demo":
            raise HTTPException(403, "Demo data can only be reset in demo mode.")
        if config.workspace == "real" and payload.mode != "real":
            raise HTTPException(409, "This deployment keeps real records only: demonstration data cannot be loaded into it.")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        folder = Path(database.engine.url.database).parent if database.engine.dialect.name == "sqlite" and database.engine.url.database not in (None, "", ":memory:") else Path("data")
        backup = database.backup(folder / "backups" / f"agentica-{stamp}.db")  # next to the database, so it survives restarts
        is_fresh = payload.mode == "fresh"
        target_state = real_workspace(config.mode) if payload.mode == "real" else fresh_workspace() if is_fresh else seed_workspace(True)
        ensure_services(target_state, Projects.load(), now())
        database.reset(target_state)
        knowledge_search.refresh(lambda: database.read()["knowledge"])
        action_name = {"real": "Real workspace initialized", "fresh": "Fresh workspace initialized"}.get(payload.mode, "Demo data reset")
        next_state = {"real": "Real workspace (no demonstration records)", "fresh": "Fresh workspace (demo activities cleared)"}.get(payload.mode, "Fresh demo stories")
        database.mutate(lambda state: audit(state, auth["user"], action_name, "workspace", next_state=next_state, evidence=str(backup or "")))
        control = application.state.sandbox_control
        if isinstance(control, LocalPaymentSandbox):
            control.stop()
        msg = {"real": "Real workspace ready: no demonstration records.", "fresh": "Fresh workspace ready: all demo activities cleared."}.get(payload.mode, "Demo data restored.") + (f" Previous data backed up to {backup}." if backup else "")
        return {"message": msg, "backup": str(backup) if backup else None}

    @application.post("/api/v1/incidents/{incident_id}/missions", status_code=201)
    def create_mission(incident_id: str, background: BackgroundTasks, auth: Auth):
        result = database.mutate(lambda state: start_mission(state, incident_id, auth["user"], application.state.mission_brain))
        launch_mission(background, result)
        return result

    @application.post("/api/v1/missions/{mission_id}/decision")
    def mission_decision(mission_id: str, payload: DecisionInput, background: BackgroundTasks, auth: Auth):
        result = database.mutate(lambda state: decide(state, mission_id, payload, auth["user"]))
        launch_mission(background, result)
        remembered = next((item.get("knowledgeId") for item in database.read().get("missions", []) if item["id"] == mission_id), None)
        if remembered:
            knowledge_search.refresh(lambda: database.read()["knowledge"], [remembered])  # organizational memory goes into the search index
        return result

    @application.post("/api/v1/missions/{mission_id}/cancel")
    def mission_cancel(mission_id: str, auth: Auth):
        return database.mutate(lambda state: cancel_mission(state, mission_id, auth["user"]))

    @application.post("/api/v1/missions/{mission_id}/resume")
    def mission_resume(mission_id: str, background: BackgroundTasks, auth: Auth):
        result = database.mutate(lambda state: resume_mission(state, mission_id, auth["user"]))
        launch_mission(background, result)
        return result

    @application.post("/api/v1/incidents/{incident_id}/assessment")
    def model_assessment(incident_id: str, payload: AssessmentInput, request: Request, auth: Auth):
        state = database.read()
        incident = find(state, "incidents", incident_id)
        require(auth["user"], "workflow:run", incident["environment"])
        evidence = [record for record in state["evidence"] if record["incidentId"] == incident_id][:8]
        if not evidence:
            raise HTTPException(409, "Attach evidence before requesting an assessment.")
        try:
            authorize_model_context(config, incident, evidence)
        except DataPolicyError as error:
            database.mutate(lambda current: audit(current, auth["user"], "AI data access denied", incident_id, incident, outcome="Classification policy denied"))
            raise HTTPException(403, str(error)) from None
        key = request.headers.get("Idempotency-Key", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key):
            raise HTTPException(422, "An idempotency key is required.")
        cache_key = f"model:{auth['user']['id']}:{incident_id}:{key}"

        def reserve(current: dict):
            cache = current.setdefault("modelRequests", {})
            if cache_key in cache:
                raise HTTPException(409, "This assessment request was already attempted. Inspect its audit outcome before starting a new request.")
            cache[cache_key] = {"executionId": identifier("EXE"), "incidentId": incident_id, "requestedById": auth["user"]["id"], "status": "Running", "timestamp": now(), "lastActivity": now(), "dataClassification": strongest_classification(incident, *evidence), "evidenceIds": [record["id"] for record in evidence]}
            audit(current, auth["user"], "Model assessment requested", incident_id, incident, next_state="Read-only model request")
        database.mutate(reserve)
        try:
            assessment = Assessment.model_validate(application.state.provider.assess(incident, evidence))
            validate_references(assessment, evidence)
        except Exception as error:
            failure_category = "INVALID_OUTPUT" if isinstance(error, ValidationError) else "PROVIDER_FAILURE"
            message = str(error) if isinstance(error, ProviderError) else "Provider failure or invalid output. No findings or workflow success were recorded."

            def failure(current: dict):
                current["modelRequests"][cache_key].update(status="Failed", lastActivity=now(), failureId=identifier("FAIL"), errorCategory=failure_category, error="Provider request failed or output was rejected. Inspect configuration and authorized provider diagnostics before retrying.")
                audit(current, auth["user"], "Model assessment failed", incident_id, incident, outcome="Integration or model failure")
            database.mutate(failure)
            raise HTTPException(503, message) from None

        def record(current: dict):
            ids = []
            for candidate in assessment.hypotheses:
                hypothesis_id = identifier("HYP")
                ids.append(hypothesis_id)
                current["hypotheses"].append(redact({"id": hypothesis_id, "incidentId": incident_id, "title": candidate.title, "status": candidate.status, "confidence": candidate.confidence, "supports": candidate.supporting_evidence, "contradicts": candidate.contradicting_evidence, "missing": candidate.missing_evidence, "nextStep": candidate.next_experiment, "agent": "Microsoft Foundry / read-only assessment", "timestamp": now(), "dataClassification": strongest_classification(incident, *evidence)}))
            current["modelRequests"][cache_key].update(status="Completed", lastActivity=now(), hypothesisIds=ids)
            audit(current, auth["user"], "Model assessment recorded", incident_id, incident, next_state="Unverified hypotheses", evidence=",".join(ids))
            return {"message": "Model hypotheses recorded for human review. No workflow stage, approval or deployment was changed.", "summary": redact(assessment.summary), "limitations": redact(assessment.limitations), "hypothesisIds": ids}
        return database.mutate(record)

    @application.post("/api/v1/incidents/{incident_id}/evidence", status_code=201)
    def add_evidence(incident_id: str, payload: EvidenceInput, auth: Auth):
        def add(state: dict):
            incident = find(state, "incidents", incident_id)
            require(auth["user"], "evidence:add", incident["environment"])
            record = {**redact(payload.model_dump()), "id": identifier("EVD"), "incidentId": incident_id, "service": incident["service"], "environment": incident["environment"], "synthetic": False}
            record["dataClassification"] = strongest_classification(incident, record)
            record.update(evidence_provenance(record, payload.model_dump_json().encode("utf-8"), auth["user"], "application/json", "validated-input-record"))
            state["evidence"].append(record)
            audit(state, auth["user"], "Evidence attached", record["id"], incident, evidence=record["id"])
            return record
        return database.mutate(add)

    @application.post("/api/v1/incidents/{incident_id}/evidence/upload", status_code=201)
    async def upload(incident_id: str, auth: Auth, file: UploadFile = File(...), data_classification: DataClassification = Form("Internal", alias="dataClassification")):
        incident = find(database.read(), "incidents", incident_id)
        require(auth["user"], "evidence:add", incident["environment"])
        filename = file.filename or ""
        if not filename or len(filename) > 180 or any(character in filename for character in ("/", "\\", "\x00", ":")) or filename.startswith("."):
            raise HTTPException(422, "Unsafe filename. Provide a plain file name without path components.")
        extension = filename.rsplit(".", 1)[-1].lower()
        code_extensions = {"py", "java", "kt", "ts", "tsx", "js", "jsx", "php", "go", "cs", "sql", "sh", "html", "css"}
        allowed_extensions = {"txt", "log", "json", "jsonl", "csv", "yml", "yaml", "xml", "md", "zip"} | code_extensions
        if extension not in allowed_extensions:
            raise HTTPException(415, "Supported: logs (.log .txt .json .jsonl .csv .xml), source and configuration files, or a .zip of logs or of a whole project. Executable binaries are not accepted.")
        if extension == "zip":
            return await upload_archive(incident_id, auth, file, filename, data_classification)
        media_type = (file.content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
        allowed_types = {
            "txt": {"text/plain"},
            "log": {"text/plain"},
            "json": {"application/json", "text/json", "text/plain"},
            "csv": {"text/csv", "application/csv", "application/vnd.ms-excel", "text/plain"},
            "yml": {"text/yaml", "application/x-yaml", "text/plain", "application/yaml"},
            "yaml": {"text/yaml", "application/x-yaml", "text/plain", "application/yaml"},
            "xml": {"text/xml", "application/xml", "text/plain"},
            "py": {"text/x-python", "text/plain"},
            "java": {"text/x-java-source", "text/plain"},
            "ts": {"text/typescript", "text/plain", "application/typescript"},
            "js": {"text/javascript", "text/plain", "application/javascript"},
            "sql": {"application/sql", "text/sql", "text/plain"},
            "md": {"text/markdown", "text/plain"},
            "sh": {"text/x-shellscript", "text/plain"},
            "jsonl": {"application/jsonl", "application/x-ndjson", "application/json", "text/plain"},
            "html": {"text/html", "text/plain"},
            "css": {"text/css", "text/plain"},
        }
        if media_type not in allowed_types.get(extension, {"text/plain"}) | {"application/octet-stream"}:
            await file.close()
            raise HTTPException(415, "The declared file type does not match an allowed evidence format.")
        content = await file.read(config.max_upload_bytes + 1)
        await file.close()
        if not content or len(content) > config.max_upload_bytes:
            raise HTTPException(413, "Evidence must be nonempty and no larger than 2 MB.")
        try:
            text = content.decode("utf-8-sig")
            if "\x00" in text:
                raise ValueError("Binary content")
            raw_text = text
            parsed = json.loads(text) if extension == "json" else list(csv.DictReader(io.StringIO(text))) if extension == "csv" else None
            if parsed is not None:
                text = json.dumps(redact(parsed), indent=2)
        except (UnicodeDecodeError, ValueError, csv.Error):
            raise HTTPException(422, "The file is not valid UTF-8 text or structured data.") from None
        evidence_id = identifier("EVD")

        def attach(state: dict):
            current = find(state, "incidents", incident_id)
            require(auth["user"], "evidence:add", current["environment"])
            ev_type = "Log" if extension in {"log", "txt", "jsonl"} else "Data" if extension in {"json", "csv"} else "Configuration" if extension in {"yml", "yaml", "xml"} else "Code" if extension in code_extensions else "Document"
            record = {"id": evidence_id, "incidentId": incident_id, "title": f"Attached file: {filename}", "type": ev_type, "source": f"upload:{filename}", "timestamp": now(), "service": current["service"], "environment": current["environment"], "classification": "Unverified", "excerpt": redact(text), "reason": "User-supplied error or diagnostic evidence. Content was parsed, validated, and redacted before storage.", "traceId": "", "fileName": filename, "sha256": hashlib.sha256(content).hexdigest(), "synthetic": False}
            record["dataClassification"] = strongest_classification(current, {"dataClassification": data_classification})
            record.update(evidence_provenance(record, content, auth["user"], media_type, "uploaded-bytes"))
            state["evidence"].append(record)
            records = parsed if isinstance(parsed, list) else [parsed] if isinstance(parsed, dict) else []
            for log in records[:200]:
                if not isinstance(log, dict) or not log.get("message") or not log.get("timestamp"):
                    continue
                try:
                    original_time = str(log["timestamp"])
                    parsed_time = datetime.fromisoformat(original_time.replace("Z", "+00:00"))
                    if parsed_time.tzinfo is None:
                        continue
                except ValueError:
                    continue
                level = str(log.get("level", log.get("severity", "INFO"))).upper()
                state["logs"].append({"id": identifier("LOG"), "timestamp": original_time, "level": level if level in {"ERROR", "WARN", "INFO", "DEBUG"} else "INFO", "service": current["service"], "environment": current["environment"], "message": redact(str(log["message"]))[:8000], "traceId": redact(str(log.get("traceId", log.get("trace_id", ""))))[:200], "source": record["source"], "attributes": {"originalSeverity": redact(level), "sourceRecord": json.dumps(redact(log))[:12000]}, "evidenceId": evidence_id, "dataClassification": record["dataClassification"]})
            if ev_type in {"Log", "Data"}:
                record["errorGroups"] = [issue["id"] for issue in record_errors(state, current, raw_text, evidence_id, now(), identifier)]
            if ev_type == "Log":
                record["logRecords"] = add_log_records(state, current, raw_text, evidence_id, record["source"], record["dataClassification"])
            if ev_type in {"Code", "Configuration"}:
                # A source file is also kept as the task's source, so agents can read it in full and a fix can be built against it.
                current.setdefault("sourceUploads", []).append({"id": evidence_id, "name": filename, "kind": "file", "files": 1, "sha256": record["sha256"], "at": now()})
                current["project"] = profile_project(Projects.load().resolve(current).code)
            audit(state, auth["user"], "Evidence file imported", evidence_id, current, evidence=evidence_id)
            return record
        if extension in code_extensions | {"yml", "yaml", "xml"}:
            task_storage.save(incident_id, evidence_id, {filename: raw_text})
        return database.mutate(attach)

    def add_log_records(state: dict, incident: dict, text: str, evidence_id: str, source: str, classification: str) -> int:
        """Every timestamped or levelled line of an uploaded log, for the Observability log view. Missing times stay marked."""
        uploaded_at = now()
        added = 0
        for line in parse_log_lines(text):
            stamp = line["timestamp"]
            attributes: dict = {}
            if stamp:
                stamp = stamp.replace(" ", "T", 1).replace(",", ".")
                if not re.search(r"(Z|[+-]\d{2}:?\d{2})$", stamp):
                    stamp += "Z"
                    attributes["timezone"] = "not in the log line; shown as UTC"
            else:
                stamp = uploaded_at
                attributes["timestamp"] = "the log line has none; upload time shown"
            if line["requestId"]:
                attributes["requestId"] = redact(line["requestId"])[:120]
            state["logs"].append({"id": identifier("LOG"), "timestamp": stamp, "level": line["level"], "service": incident["service"], "environment": incident["environment"],
                                  "message": redact(line["message"])[:8000], "traceId": redact(line["requestId"])[:200], "source": source, "attributes": attributes,
                                  "evidenceId": evidence_id, "dataClassification": classification, "synthetic": False})
            added += 1
        state["logs"] = state["logs"][-20000:]
        return added

    async def upload_archive(incident_id: str, auth: dict, file: UploadFile, filename: str, data_classification: str):
        """A ZIP of logs or of a whole project. It is inspected in memory and never unpacked to disk."""
        content = await file.read(config.max_project_zip_bytes + 1)
        await file.close()
        if not content or len(content) > config.max_project_zip_bytes:
            raise HTTPException(413, f"A project archive must be nonempty and no larger than {config.max_project_zip_bytes // 1_048_576} MB.")
        try:
            inspected = inspect_zip(content)
        except UnsafeArchive as problem:
            raise HTTPException(422, str(problem)) from None
        sources, logs = inspected["sources"], inspected["logs"]
        if not sources and not logs:
            raise HTTPException(422, "The archive has no readable source files or logs.")
        evidence_id = identifier("EVD")
        if sources:
            task_storage.save(incident_id, evidence_id, sources)

        def attach(state: dict):
            current = find(state, "incidents", incident_id)
            require(auth["user"], "evidence:add", current["environment"])
            groups: list[str] = []
            base = {"incidentId": incident_id, "timestamp": now(), "service": current["service"], "environment": current["environment"], "classification": "Unverified", "traceId": "", "synthetic": False}
            for name, text in logs.items():
                log_id = identifier("EVD")
                log_record = {**base, "id": log_id, "title": f"Log from {filename}: {name}"[:180], "type": "Log", "source": f"upload:{filename}:{name}"[:500], "excerpt": redact(text[:200_000]),
                              "reason": "Log file found inside an uploaded archive. Content was redacted before storage.", "fileName": name, "sha256": hashlib.sha256(text.encode()).hexdigest()}
                log_record["dataClassification"] = strongest_classification(current, {"dataClassification": data_classification})
                log_record.update(evidence_provenance(log_record, text.encode(), auth["user"], "text/plain", "uploaded-archive-member"))
                log_record["errorGroups"] = [issue["id"] for issue in record_errors(state, current, text, log_id, now(), identifier)]
                log_record["logRecords"] = add_log_records(state, current, text, log_id, log_record["source"], log_record["dataClassification"])
                groups += log_record["errorGroups"]
                state["evidence"].append(log_record)
            if sources:
                current.setdefault("sourceUploads", []).append({"id": evidence_id, "name": filename, "kind": "zip", "files": len(sources), "sha256": hashlib.sha256(content).hexdigest(), "at": now()})
                current["project"] = profile_project(Projects.load().resolve(current).code)
            listing = "\n".join(list(sources)[:150]) + (f"\n… and {len(sources) - 150} more files" if len(sources) > 150 else "")
            record = {**base, "id": evidence_id, "title": f"Uploaded archive: {filename}", "type": "Code" if sources else "Document", "source": f"upload:{filename}",
                      "excerpt": f"{len(sources)} source and configuration files, {len(logs)} log files, {inspected['skipped']} entries not read (binary, too large, vendored or not source).\n{listing}",
                      "reason": "Archive inspected in memory without unpacking; unsafe paths, links and encrypted entries are refused.", "fileName": filename,
                      "sha256": hashlib.sha256(content).hexdigest(), "sourceFiles": len(sources), "logFiles": len(logs), "errorGroups": list(dict.fromkeys(groups))}
            record["dataClassification"] = strongest_classification(current, {"dataClassification": data_classification})
            record.update(evidence_provenance(record, content, auth["user"], "application/zip", "uploaded-bytes"))
            state["evidence"].append(record)
            audit(state, auth["user"], "Project archive imported", evidence_id, current, evidence=evidence_id)
            return record
        return database.mutate(attach)

    @application.get("/api/v1/incidents/{incident_id}/readiness")
    def readiness(incident_id: str, auth: Auth):
        """What this task has and what is still missing before a code correction can be produced."""
        require(auth["user"], "read")
        state = database.read()
        incident = find(state, "incidents", incident_id)
        code = Projects.load().resolve(incident, application.state.sandbox_control if is_payment_sandbox(incident) else None).code
        files = len(code.paths())
        evidence = [record for record in state["evidence"] if record["incidentId"] == incident_id]
        groups = [issue for issue in state.get("errors", []) if incident_id in issue["incidentIds"]]
        missing: list[str] = []
        if not evidence:
            missing.append("An error log, a stack trace or another piece of evidence.")
        if not files:
            missing.append(code.problem or "The source code: upload the affected file or a project ZIP, or connect the GitHub repository.")
        if not evidence:
            message = "Attach an error log or describe the error so the investigation has something to work from."
        elif not files:
            message = (f"Your logs have been analysed ({len(groups)} error group{'s' if len(groups) != 1 else ''} found). " if groups else "The evidence is attached. ") + \
                "The relevant source code is not included. Upload the affected file or a project ZIP, or connect the GitHub repository, so a code correction can be generated and checked. Without it the agents can diagnose from the logs but cannot change any code."
        else:
            message = f"Ready: evidence is attached and {files} source file{'s' if files != 1 else ''} can be read from {code.label}."
        return {"incidentId": incident_id, "evidence": len(evidence), "errorGroups": len(groups), "hasSource": bool(files), "sourceFiles": files, "source": code.label if files else "",
                "canOpenPullRequest": bool(files and getattr(code, "pull_requests", False) and getattr(code, "token", "")), "project": incident.get("project"), "missing": missing, "message": message}

    # -- GitHub lookups for picking a repository, branch, commit and folder (read-only) --------------

    def github_lookup(action):
        try:
            return action(GitHubBrowser(Projects.load()))
        except GitHubLookupError as problem:
            raise HTTPException(422, str(problem)) from None

    @application.get("/api/v1/github/repositories")
    def github_repositories(auth: Auth, q: str = ""):
        require(auth["user"], "incident:create")
        return github_lookup(lambda browser: browser.repositories(q[:140]))

    @application.get("/api/v1/github/repositories/{owner}/{name}/branches")
    def github_branches(owner: str, name: str, auth: Auth):
        require(auth["user"], "incident:create")
        return github_lookup(lambda browser: browser.branches(f"{owner}/{name}"))

    @application.get("/api/v1/github/repositories/{owner}/{name}/commits")
    def github_commits(owner: str, name: str, auth: Auth, ref: str = ""):
        require(auth["user"], "incident:create")
        return github_lookup(lambda browser: browser.commits(f"{owner}/{name}", ref[:200]))

    @application.get("/api/v1/github/repositories/{owner}/{name}/folders")
    def github_folders(owner: str, name: str, auth: Auth, ref: str = ""):
        require(auth["user"], "incident:create")
        return github_lookup(lambda browser: browser.folders(f"{owner}/{name}", ref[:200]))

    @application.patch("/api/v1/errors/{error_id}")
    def update_error(error_id: str, payload: ErrorStatusInput, auth: Auth):
        def update(state: dict):
            issue = find(state, "errors", error_id)
            require(auth["user"], "incident:update", issue["environment"])
            previous = issue["status"]
            issue.update(status=payload.status, statusBy=auth["user"]["name"], statusAt=now(), statusNote=redact(payload.note))
            audit(state, auth["user"], "Error issue status changed", error_id, previous=previous, next_state=payload.status)
            return issue
        return database.mutate(update)

    @application.get("/api/v1/errors/{error_id}/source")
    def error_source(error_id: str, auth: Auth):
        """Where this error's stack trace points in the connected source code (or why that cannot be established)."""
        require(auth["user"], "read")
        state = database.read()
        issue = find(state, "errors", error_id)
        incident = next((item for item in reversed(state["incidents"]) if item["id"] in issue["incidentIds"]), None)
        if incident is None:
            return {"matches": [], "note": "This error is not linked to a task, so there is no source code to look in."}
        return correlate(issue, Projects.load().resolve(incident).code)

    @application.post("/api/v1/incidents/import", status_code=201)
    async def import_tickets(auth: Auth, file: UploadFile = File(...)):
        require(auth["user"], "incident:create")
        filename = file.filename or ""
        if any(character in filename for character in ("/", "\\", "\x00", ":")) or not filename.lower().endswith((".json", ".csv")):
            raise HTTPException(415, "Select a ticket JSON or CSV file with a safe filename.")
        content = await file.read(config.max_upload_bytes + 1)
        await file.close()
        if len(content) > config.max_upload_bytes:
            raise HTTPException(413, "Import exceeds 2 MB.")
        try:
            text = content.decode("utf-8-sig")
            records = json.loads(text) if filename.lower().endswith(".json") else list(csv.DictReader(io.StringIO(text)))
            records = records if isinstance(records, list) else [records]
            if not 1 <= len(records) <= 50:
                raise ValueError("Expected 1-50 records")
            inputs = [IncidentInput.model_validate(record) for record in records]
        except (ValueError, ValidationError, UnicodeDecodeError, csv.Error):
            raise HTTPException(422, "Import rejected. Provide 1-50 valid incident records with title, description, severity, environment, service, impact and timezone-aware detectedAt. No records were imported.") from None

        def import_records(state: dict):
            created = []
            for payload in inputs:
                require(auth["user"], "incident:create", payload.environment)
                find(state, "services", payload.service)
                record = {**redact(payload.model_dump()), "source": "Ticket import", "id": identifier("INC"), "status": "New", "owner": auth["user"]["name"], "commander": auth["user"]["name"], "slaMinutes": 240, "workflowStatus": "Idle", "workflowGeneration": 0, "outcome": "", "recovery": None, "synthetic": False}
                state["incidents"].append(record)
                created.append(record["id"])
                audit(state, auth["user"], "Ticket imported", record["id"], record)
            return {"message": f"Imported {len(created)} tickets.", "ids": created}
        return database.mutate(import_records)

    @application.post("/api/v1/incidents/{incident_id}/tests", status_code=201)
    def record_test(incident_id: str, payload: RecordedTestInput, auth: Auth):
        require(auth["user"], "validation:run", "Staging")
        if payload.passed + payload.failed == 0:
            raise HTTPException(422, "Record at least one executed check.")

        def record(state: dict):
            incident = find(state, "incidents", incident_id)
            require(auth["user"], "validation:run", incident["environment"])
            real = state.get("workspaceKind") == "real"
            # Real workspace: tests run in the owning team's pipeline after a fix is proposed or approved, and are recorded here.
            allowed = {"Root Cause Identified", "Awaiting Approval", "Approved", "Monitoring", "Fix Proposed", "Testing"} if real else {"Fix Proposed", "Testing", "Root Cause Identified"}
            if incident["status"] not in allowed:
                raise HTTPException(409, "A proposed fix is required before recording validation.")
            result = {**payload.model_dump(exclude={"source"}), "id": identifier("TEST"), "incidentId": incident_id, "category": "Manually recorded", "status": "Passed" if payload.failed == 0 else "Failed", "flaky": 0, "coverage": None, "environment": "Staging", "timestamp": now(), "cases": [], "synthetic": False, "source": "Manually recorded, not executed by BEHAVE KYNDRYL: " + redact(payload.source)}
            state["tests"].append(result)
            if real:
                result["environment"] = incident["environment"]  # recorded against the incident's own environment; the status follows the mission
            else:
                incident["status"] = "Testing"
            audit(state, auth["user"], "Test evidence recorded", result["id"], incident, evidence=result["id"])
            return result
        return database.mutate(record)

    @application.patch("/api/v1/security/{finding_id}")
    def review_security(finding_id: str, payload: ReviewInput, auth: Auth):
        require(auth["user"], "security:review")

        def review(state: dict):
            finding = find(state, "security", finding_id)
            if finding["severity"] == "Critical" and payload.status == "Accepted risk":
                raise HTTPException(409, "Critical findings cannot bypass the mandatory security gate through risk acceptance.")
            previous = finding["status"]
            finding.update(status=payload.status, reviewReason=redact(payload.reason))
            audit(state, auth["user"], "Security finding reviewed", finding_id, previous=previous, next_state=payload.status)
            return finding
        return database.mutate(review)

    @application.post("/api/v1/knowledge", status_code=201)
    def create_knowledge(payload: KnowledgeInput, auth: Auth):
        require(auth["user"], "incident:update")

        def create(state: dict):
            for service_id in payload.services:
                find(state, "services", service_id)
            for incident_id in payload.incidents:
                incident = find(state, "incidents", incident_id)
                require(auth["user"], "incident:update", incident["environment"])
            record = {**redact(payload.model_dump()), "id": identifier("KB"), "owner": auth["user"]["name"], "ownerId": auth["user"]["id"], "version": "0.1", "reviewedAt": now(), "approved": False, "source": "Human-authored local draft"}
            state["knowledge"].append(record)
            audit(state, auth["user"], "Knowledge draft created", record["id"])
            return record
        created = database.mutate(create)
        knowledge_search.refresh(lambda: database.read()["knowledge"], [created["id"]])
        return created

    @application.post("/api/v1/knowledge/{record_id}/review")
    def review_knowledge(record_id: str, payload: KnowledgeReview, auth: Auth):
        require(auth["user"], "admin:write")

        def review(state: dict):
            record = find(state, "knowledge", record_id)
            if record.get("ownerId") == auth["user"]["id"] or record["owner"] == auth["user"]["name"]:
                raise HTTPException(403, "Knowledge approval requires a different human reviewer.")
            if record["approved"]:
                raise HTTPException(409, "This record is already approved.")
            if payload.decision == "approve" and record["type"] == "Incident report":
                linked = [find(state, "incidents", incident_id) for incident_id in record["incidents"]]
                if not linked or not all(incident["status"] == "Closed" and incident["recovery"] for incident in linked):
                    raise HTTPException(409, "An authoritative incident report requires a closed incident and recorded recovery evidence.")
            record.update(approved=payload.decision == "approve", reviewedAt=now(), version="1.0" if payload.decision == "approve" else "0.1", reviewReason=redact(payload.reason),
                          reviewedBy=auth["user"]["name"])
            audit(state, auth["user"], "Knowledge review recorded", record_id, previous="Draft", next_state="Approved" if record["approved"] else "Draft")
            return record
        reviewed = database.mutate(review)
        knowledge_search.refresh(lambda: database.read()["knowledge"], [record_id])  # approved records become searchable by the agents
        return reviewed

    @application.get("/api/v1/admin/access")
    def access_catalog(auth: Auth):
        require(auth["user"], "admin:write")
        return {"roles": [persona(role) for role in PERSONAS], "mode": config.mode, "identitySource": "Local synthetic personas" if config.mode == "demo" else "Entra app-role claims"}

    @application.put("/api/v1/admin/policy")
    def update_policy(payload: PolicyInput, auth: Auth):
        require(auth["user"], "admin:write")

        def update(state: dict):
            previous = json.dumps(state["policy"])
            state["policy"] = payload.model_dump()
            audit(state, auth["user"], "Policy updated", "workspace-policy", previous=previous, next_state=json.dumps(state["policy"]))
            return state["policy"]
        return database.mutate(update)

    @application.post("/api/v1/repositories/analyses", status_code=201)
    def analyze_repository(payload: RepositoryInput, auth: Auth):
        require(auth["user"], "workflow:run", payload.environment)
        scanned: tuple[list[dict], int, str] | None = None
        if payload.source == "repository":
            # Read the real repository (public, or connected by an administrator) and run the static rules on its files.
            match = re.match(r"^(?:https?://github\.com/)?([A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$", payload.url.strip())
            if not match:
                raise HTTPException(422, "Give a GitHub repository as owner/name or https://github.com/owner/name.")
            ref = payload.commit if payload.commit and payload.commit != "c7f4e21" else payload.branch
            code = Projects.load().resolve({"service": "", "repository": {"repo": match.group(1), "ref": ref, "path": ""}}).code
            if not code.paths():
                raise HTTPException(422, code.problem or "The repository has no readable source files.")
            findings_found, files_scanned = scan_repository(code, list(payload.scope))
            scanned = (findings_found, files_scanned, code.label)
        elif payload.source == "incident":
            # Scan whatever source this incident has: an uploaded ZIP or file, or its repository.
            target = find(database.read(), "incidents", payload.incidentId or "")
            require(auth["user"], "workflow:run", target["environment"])
            code = Projects.load().resolve(target).code
            if not code.paths():
                raise HTTPException(422, code.problem or "No source code is connected to this incident. Upload a file or ZIP, or pick a repository.")
            findings_found, files_scanned = scan_repository(code, list(payload.scope))
            scanned = (findings_found, files_scanned, code.label)
        elif payload.source == "fixture":
            if config.workspace == "real":
                raise HTTPException(409, "This workspace keeps real records only: the example fixture is not available.")
            if config.mode != "demo":
                raise HTTPException(409, "Synthetic repository replay is available only in the demo workspace.")
            if payload.stack != "Java / Spring Boot":
                raise HTTPException(422, "The supplied fixture is Java / Spring Boot only. Other stacks require an authorized repository adapter.")

        def analyze(state: dict):
            incident = next((item for item in state.get("incidents", []) if item["id"] == payload.incidentId), None) if payload.incidentId else None
            if incident:
                require(auth["user"], "workflow:run", incident["environment"])
                if payload.source == "fixture" and incident["id"] == "INC-1041":
                    raise HTTPException(409, "The checkout fixture is linked only to synthetic incident INC-1042. It cannot supply findings for another incident.")
            elif payload.incidentId == "INC-1041" and payload.source == "fixture":
                raise HTTPException(409, "The checkout fixture is linked only to synthetic incident INC-1042. It cannot supply findings for another incident.")

            if payload.source == "fixture":
                all_fixture_findings = [
                    {"id": "REPO-41", "title": "Connection pool budget reduced", "severity": "High", "category": "Configuration", "file": "src/main/resources/application-production.yml", "line": 18, "confidence": .91, "evidence": ["EVD-304"], "guidance": "Compare the approved pool size with the aggregate database connection budget before proposing a change.", "validation": "Replay an equivalent bounded workload and measure connection acquisition latency."},
                    {"id": "REPO-42", "title": "Concurrency regression coverage gap", "severity": "Medium", "category": "Tests", "file": "src/test/java/CheckoutServiceTest.java", "line": 24, "confidence": .86, "evidence": ["EVD-307"], "guidance": "Add bounded concurrent checkout regression cases and explicit connection-budget assertions.", "validation": "Required regression checks pass for the exact proposed commit."},
                    {"id": "REPO-43", "title": "Database timeout propagated as generic 503", "severity": "Low", "category": "Code paths", "file": "src/main/java/CheckoutService.java", "line": 84, "confidence": .74, "evidence": ["EVD-301", "EVD-303"], "guidance": "Retain correlation IDs and distinguish acquisition timeouts from upstream payment failures.", "validation": "Error-path contract checks preserve a safe error response and diagnostic correlation."},
                ]
                findings = [finding for finding in all_fixture_findings if finding["category"] in payload.scope]
                source_label = "Read-only synthetic source fixture"
                status_label = "Completed (demo)"
                limitations_msg = "Predefined example findings, not executed static analysis. No repository URL was accessed, no archive extracted and no code executed."
                audit_action = "Synthetic source analysis replayed"
            else:
                findings, files_scanned, label = scanned
                findings = redact(findings)
                source_label = label
                status_label = "Completed (static rules)"
                limitations_msg = (
                    f"Static rules ran on {files_scanned} real files of {label} across {len(payload.scope)} scope(s). "
                    "Findings are pattern matches with file and line, not proof: read each line in context. "
                    "No code was run and no AI model was used; start an agent mission for a diagnosis and a fix."
                )
                audit_action = "Repository scanned with static rules"

            record = {
                "id": identifier("ANL"),
                "incidentId": payload.incidentId,
                "timestamp": now(),
                "source": source_label,
                "branch": payload.branch,
                "commit": payload.commit,
                "stack": payload.stack,
                "scope": payload.scope,
                "status": status_label,
                "findings": findings,
                "limitations": limitations_msg,
            }
            state.setdefault("analyses", []).append(record)
            audit(state, auth["user"], audit_action, record["id"], incident)
            if scanned:
                record["securityFindings"] = record_security_findings(state, findings, scanned[2], incident, record["id"])
            return record

        return database.mutate(analyze)

    def record_security_findings(state: dict, findings: list[dict], source: str, incident: dict | None, analysis_id: str) -> list[str]:
        """Security matches from a real repository scan become findings on the Security page (deduplicated, reopened if seen again)."""
        scanner = {"Hardcoded credential or token detected": "Secret scanning", "Hardcoded bearer token": "Secret scanning",
                   "Private key reference in repository file": "Secret scanning", "Basic auth credentials embedded in URL": "Secret scanning",
                   "Container runs as root user": "Container scanning"}
        ids = []
        for finding in findings:
            if finding["category"] != "Security":
                continue
            key = f"{source}|{finding['file']}|{finding['line']}|{finding['title']}"
            record = next((item for item in state["security"] if item.get("key") == key), None)
            if record is None:
                record = {"id": identifier("SEC"), "key": key, "title": finding["title"], "category": scanner.get(finding["title"], "Static analysis"),
                          "severity": finding["severity"], "service": incident["service"] if incident else source.removeprefix("GitHub ").split("@")[0],
                          "status": "Open", "incidentId": incident["id"] if incident else "", "description": finding["evidence"][0],
                          "reference": f"{analysis_id} / built-in rule", "file": finding["file"], "line": finding["line"], "guidance": finding["guidance"],
                          "source": source, "firstSeen": now(), "synthetic": False}
                state["security"].append(record)
            elif record["status"] == "Resolved":
                record["status"] = "Open"  # found again after being marked resolved
            record.update(lastSeen=now(), reference=f"{analysis_id} / built-in rule")
            ids.append(record["id"])
        return ids

    class GitHubAnalysisInput(StrictModel):
        fileName: str = Field(min_length=1, max_length=200)
        content: str = Field(min_length=1, max_length=200000)
        repoName: str = Field("custom/repository", max_length=200)
        scope: list[str] = Field(default_factory=lambda: ["architecture", "security", "workflow", "reliability"])

    @application.post("/api/v1/repositories/github-analysis", status_code=200)
    def analyze_github_repo_file(payload: GitHubAnalysisInput, auth: Auth):
        """Analyze a GitHub repository file across Architecture, Security, Workflow, and Reliability."""
        require(auth["user"], "workflow:run")
        result = analyze_github_file(payload.fileName, payload.content, payload.repoName, payload.scope, getattr(application.state, "mission_brain", None))
        database.mutate(lambda state: audit(state, auth["user"], "GitHub repository file analyzed", payload.fileName, next_state=f"Score {result['score']}/100", evidence=f"{result['stats']['total']} findings"))
        return result

    @application.post("/api/v1/repositories/github-analysis/pdf")
    def analyze_github_repo_file_pdf(payload: GitHubAnalysisInput, auth: Auth):
        """Generate and stream a comprehensive Repository Forensic Deep Analysis PDF report."""
        require(auth["user"], "workflow:run")
        result = analyze_github_file(payload.fileName, payload.content, payload.repoName, payload.scope, getattr(application.state, "mission_brain", None))
        pdf_bytes = generate_repo_analysis_pdf(result)
        database.mutate(lambda state: audit(state, auth["user"], "GitHub analysis PDF exported", payload.fileName))
        clean_name = re.sub(r"[^A-Za-z0-9._-]+", "_", payload.fileName)[:80] or "file"
        return Response(
            pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{clean_name}-analysis-report.pdf"'}
        )

    @application.get("/api/v1/incidents/{incident_id}/resolution-report")
    def incident_resolution_report(incident_id: str, auth: Auth):
        """Generate a detailed Post-Incident Review (PIR) and resolution report confirming if attached error files are resolved."""
        require(auth["user"], "export")
        state = database.read()
        incident = find(state, "incidents", incident_id)
        report = generate_resolution_report(incident, state)
        database.mutate(lambda s: audit(s, auth["user"], "Resolution report viewed", incident_id, next_state="Report generated"))
        return report

    @application.get("/api/v1/incidents/{incident_id}/resolution-report/pdf")
    def incident_resolution_report_pdf(incident_id: str, auth: Auth):
        """Generate and stream a publication-quality Post-Incident Review (PIR) PDF report."""
        require(auth["user"], "export")
        state = database.read()
        incident = find(state, "incidents", incident_id)
        mission = pick_mission(state, incident_id)
        pdf_bytes = generate_mission_report_pdf(incident, mission, state) if mission else generate_incident_resolution_pdf(incident, state)
        database.mutate(lambda s: audit(s, auth["user"], "Resolution report PDF exported", incident_id))
        return Response(
            pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{incident_id}-resolution-report.pdf"'}
        )

    @application.post("/api/v1/reports/export")
    def export(payload: ExportInput, auth: Auth):
        require(auth["user"], "export")
        database.mutate(lambda state: audit(state, auth["user"], "Report exported", payload.incidentId or "workspace", next_state=payload.format))
        state = database.read()
        incidents = [record for record in state["incidents"] if (not payload.incidentId or record["id"] == payload.incidentId) and (payload.environment == "All environments" or record["environment"] == payload.environment)]
        if payload.format == "csv":
            output = io.StringIO()
            columns = ["id", "title", "severity", "status", "service", "environment", "detectedAt", "owner", "synthetic"]
            writer = csv.DictWriter(output, fieldnames=columns)
            writer.writeheader()
            for record in incidents:
                values = {key: str(record[key]) for key in columns}
                writer.writerow({key: "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value for key, value in values.items()})
            return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="Behave-Kyndryl-incidents.csv"'})
        incident_ids = {record["id"] for record in incidents}
        report = {"mode": state["mode"], "generatedAt": now(), "snapshotAt": state["snapshotAt"], "notice": "Synthetic workspace data is not production performance. Manually entered records retain their own provenance.", "environment": payload.environment, "incidents": incidents, "evidence": [record for record in state["evidence"] if record["incidentId"] in incident_ids], "changes": [record for record in state["changes"] if record["incidentId"] in incident_ids], "tests": [record for record in state["tests"] if record["incidentId"] in incident_ids], "audit": [record for record in state["audit"] if record["correlationId"] in incident_ids]}
        return Response(json.dumps(report, indent=2), media_type="application/json", headers={"Content-Disposition": 'attachment; filename="Behave-Kyndryl-incident-report.json"'})

    static_root = Path(config.static_dir).resolve()
    if (static_root / "index.html").is_file():
        # Serve the built React site from the same origin as the API (cloud deployment).
        @application.get("/{full_path:path}", include_in_schema=False)
        def website(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(404, "Not found")
            candidate = (static_root / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(static_root):
                return FileResponse(candidate)
            return FileResponse(static_root / "index.html")

    return application


app = create_app()