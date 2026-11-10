import csv
import hashlib
import io
import json
import re
import secrets
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic
from typing import Annotated, Literal

import jwt
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field, ValidationError
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from .data_governance import DataPolicyError, authorize_model_context, evidence_provenance, strongest_classification
from .domain import ActionInput, DataClassification, EvidenceInput, IncidentInput, PERSONAS, PolicyInput, ReviewInput, Settings, StrictModel, now, persona, redact
from .payment_sandbox import PaymentSandboxControl, PaymentSandboxControlAdapter
from .providers import Assessment, ProviderError, configured_provider, validate_references
from .seed import seed_workspace
from .store import Store
from .workflow import act, audit, change_gates, find, identifier, record_payment_sandbox_result, require, run_demo_workflow


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
    source: Literal["fixture", "repository"]
    url: str = Field("", max_length=500)
    branch: str = Field("main", min_length=1, max_length=120)
    commit: str = Field("c7f4e21", min_length=3, max_length=100)
    stack: str = Field("Java / Spring Boot", min_length=2, max_length=100)
    environment: Literal["Development", "Staging", "Production"] = "Staging"
    scope: list[Literal["Configuration", "Code paths", "Dependencies", "Tests", "Security"]] = Field(min_length=1, max_length=5)
    incidentId: str = "INC-1042"
    permissionConfirmed: Literal[True]


def create_app(settings: Settings | None = None, store: Store | None = None, sandbox_control: PaymentSandboxControl | None = None) -> FastAPI:
    config = settings or Settings()
    if config.mode == "production":
        if make_url(config.database_url).get_backend_name() != "postgresql" or (store is not None and store.engine.dialect.name != "postgresql"):
            raise RuntimeError("Production requires PostgreSQL. SQLite is limited to local demonstration and isolated testing.")
        if not config.azure_tenant_id or not config.auth_audience:
            raise RuntimeError("Production requires AZURE_TENANT_ID and AGENTICA_AUTH_AUDIENCE; demo authentication is disabled.")
    database = store or Store(config.database_url)
    database.initialize(seed_workspace(config.mode == "demo"))
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
        database.mutate(recover)
        yield

    application = FastAPI(title="BEHAVE KYNDRYL API", version="1.0.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    application.state.store = database
    application.state.settings = config
    application.state.provider = configured_provider(config)
    application.state.sandbox_control = sandbox_control or PaymentSandboxControlAdapter()
    sandbox_operation_lock = Lock()
    rate_buckets: dict[str, deque] = defaultdict(deque)
    jwks = jwt.PyJWKClient(f"https://login.microsoftonline.com/{config.azure_tenant_id}/discovery/v2.0/keys", cache_keys=True, timeout=5) if config.mode == "production" else None

    @application.middleware("http")
    async def guard(request: Request, call_next):
        host = request.url.hostname or ""
        if config.mode == "demo" and host not in {"localhost", "127.0.0.1", "::1", "testserver"}:
            return JSONResponse(status_code=403, content={"detail": "Demo access is restricted to loopback hosts."})
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
        result = {"status": "ok", "database": "AVAILABLE", "mode": config.mode, "execution": "synthetic only" if config.mode == "demo" else "disabled until adapters configured"}
        try:
            database.check_health()
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
        response.set_cookie("agentica_session", token, httponly=True, samesite="strict", max_age=28_800, path="/api")
        database.mutate(lambda state: audit(state, result["user"], "Demo identity selected", payload.role))
        return result

    @application.get("/api/v1/auth/session")
    def session(auth: Auth):
        return auth

    @application.post("/api/v1/auth/logout")
    def logout(request: Request, response: Response, auth: Auth):
        database.delete_session(hashlib.sha256(request.cookies.get("agentica_session", "").encode()).hexdigest())
        response.delete_cookie("agentica_session", path="/api")
        database.mutate(lambda state: audit(state, auth["user"], "Signed out", auth["user"]["id"]))
        return {"message": "Signed out."}

    @application.get("/api/v1/workspace")
    def snapshot(auth: Auth):
        require(auth["user"], "read")
        state = database.read()
        state.pop("idempotency", None)
        for change in state["changes"]:
            change["gates"] = change_gates(state, change)
        for integration in state["integrations"]:
            if integration["id"] == "foundry":
                integration["dataPolicy"] = {"allowedClassifications": config.ai_allowed_classifications, "restrictedDataAllowed": False}
                if "AGENTICA_AI_ALLOWED_CLASSIFICATIONS" not in integration["required"]:
                    integration["required"].append("AGENTICA_AI_ALLOWED_CLASSIFICATIONS")
                if config.azure_ai_project_endpoint and config.azure_ai_model_deployment:
                    integration["status"] = "Configured, not verified" if config.ai_allowed_classifications else "Blocked by data policy"
            if integration["id"] == "entra" and config.mode == "production":
                integration["status"] = "Configured, not verified"
        state["audit"].sort(key=lambda event: event["timestamp"], reverse=True)
        state["incidents"].sort(key=lambda incident: incident["detectedAt"], reverse=True)
        return state

    @application.post("/api/v1/incidents", status_code=201)
    def create_incident(payload: IncidentInput, auth: Auth):
        require(auth["user"], "incident:create", payload.environment)
        if (payload.service == "payment-api") != (payload.environment == "Sandbox"):
            raise HTTPException(422, "The Payment API sandbox service is available only in the Sandbox environment.")
        if payload.environment == "Sandbox" and payload.service != "payment-api":
            raise HTTPException(422, "Only the approved Payment API sandbox service is registered in the Sandbox environment.")

        def create(state: dict):
            if payload.service != "payment-api":
                find(state, "services", payload.service)
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
        if extension not in {"txt", "log", "json", "csv"}:
            raise HTTPException(415, "Supported evidence: UTF-8 .txt, .log, .json and .csv. Archives and executable files are not accepted.")
        media_type = (file.content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
        allowed_types = {"txt": {"text/plain"}, "log": {"text/plain"}, "json": {"application/json", "text/json", "text/plain"}, "csv": {"text/csv", "application/csv", "application/vnd.ms-excel", "text/plain"}}
        if media_type not in allowed_types[extension] | {"application/octet-stream"}:
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
            parsed = json.loads(text) if extension == "json" else list(csv.DictReader(io.StringIO(text))) if extension == "csv" else None
            if parsed is not None:
                text = json.dumps(redact(parsed), indent=2)
        except (UnicodeDecodeError, ValueError, csv.Error):
            raise HTTPException(422, "The file is not valid UTF-8 text or structured data.") from None
        evidence_id = identifier("EVD")

        def attach(state: dict):
            current = find(state, "incidents", incident_id)
            require(auth["user"], "evidence:add", current["environment"])
            record = {"id": evidence_id, "incidentId": incident_id, "title": f"Imported evidence: {filename}", "type": "Log" if extension in {"log", "json", "csv"} else "Document", "source": f"upload:{filename}", "timestamp": now(), "service": current["service"], "environment": current["environment"], "classification": "Unverified", "excerpt": redact(text), "reason": "User-supplied untrusted evidence. Original timestamps inside records are preserved; the record timestamp is the ingestion time. Content was redacted before storage.", "traceId": "", "fileName": filename, "sha256": hashlib.sha256(content).hexdigest(), "synthetic": False}
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
            audit(state, auth["user"], "Evidence file imported", evidence_id, current, evidence=evidence_id)
            return record
        return database.mutate(attach)

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
            if incident["status"] not in {"Fix Proposed", "Testing", "Root Cause Identified"}:
                raise HTTPException(409, "A proposed fix is required before recording validation.")
            result = {**payload.model_dump(exclude={"source"}), "id": identifier("TEST"), "incidentId": incident_id, "category": "Manually recorded", "status": "Passed" if payload.failed == 0 else "Failed", "flaky": 0, "coverage": None, "environment": "Staging", "timestamp": now(), "cases": [], "synthetic": False, "source": "Manually recorded, not executed by BEHAVE KYNDRYL: " + redact(payload.source)}
            state["tests"].append(result)
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
        return database.mutate(create)

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
            record.update(approved=payload.decision == "approve", reviewedAt=now(), version="1.0" if payload.decision == "approve" else "0.1", reviewReason=redact(payload.reason))
            audit(state, auth["user"], "Knowledge review recorded", record_id, previous="Draft", next_state="Approved" if record["approved"] else "Draft")
            return record
        return database.mutate(review)

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
        if payload.source == "repository":
            raise HTTPException(503, "Repository adapter not configured. No URL was accessed. Configure a read-only application identity and repository allowlist before analysis.")
        if config.mode != "demo":
            raise HTTPException(409, "Synthetic repository replay is available only in the demo workspace.")
        if payload.stack != "Java / Spring Boot":
            raise HTTPException(422, "The supplied fixture is Java / Spring Boot only. Other stacks require an authorized repository adapter.")

        def analyze(state: dict):
            incident = find(state, "incidents", payload.incidentId)
            require(auth["user"], "workflow:run", incident["environment"])
            if incident["id"] != "INC-1042" or not incident["synthetic"]:
                raise HTTPException(409, "The checkout fixture is linked only to synthetic incident INC-1042. It cannot supply findings for another incident.")
            findings = [
                {"id": "REPO-41", "title": "Connection pool budget reduced", "severity": "High", "category": "Configuration", "file": "src/main/resources/application-production.yml", "line": 18, "confidence": .91, "evidence": ["EVD-304"], "guidance": "Compare the approved pool size with the aggregate database connection budget before proposing a change.", "validation": "Replay an equivalent bounded workload and measure connection acquisition latency."},
                {"id": "REPO-42", "title": "Concurrency regression coverage gap", "severity": "Medium", "category": "Tests", "file": "src/test/java/CheckoutServiceTest.java", "line": 24, "confidence": .86, "evidence": ["EVD-307"], "guidance": "Add bounded concurrent checkout regression cases and explicit connection-budget assertions.", "validation": "Required regression checks pass for the exact proposed commit."},
                {"id": "REPO-43", "title": "Database timeout propagated as generic 503", "severity": "Low", "category": "Code paths", "file": "src/main/java/CheckoutService.java", "line": 84, "confidence": .74, "evidence": ["EVD-301", "EVD-303"], "guidance": "Retain correlation IDs and distinguish acquisition timeouts from upstream payment failures.", "validation": "Error-path contract checks preserve a safe error response and diagnostic correlation."},
            ]
            record = {"id": identifier("ANL"), "incidentId": payload.incidentId, "timestamp": now(), "source": "Read-only synthetic source fixture", "branch": payload.branch, "commit": "c7f4e21", "stack": payload.stack, "scope": payload.scope, "status": "Completed (demo)", "findings": [finding for finding in findings if finding["category"] in payload.scope], "limitations": "Predefined example findings, not executed static analysis. No repository URL was accessed, no archive extracted and no code executed."}
            state.setdefault("analyses", []).append(record)
            audit(state, auth["user"], "Synthetic source analysis replayed", record["id"], incident)
            return record
        return database.mutate(analyze)

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
            return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="BEHAVE KYNDRYL-incidents.csv"'})
        incident_ids = {record["id"] for record in incidents}
        report = {"mode": state["mode"], "generatedAt": now(), "snapshotAt": state["snapshotAt"], "notice": "Synthetic workspace data is not production performance. Manually entered records retain their own provenance.", "environment": payload.environment, "incidents": incidents, "evidence": [record for record in state["evidence"] if record["incidentId"] in incident_ids], "changes": [record for record in state["changes"] if record["incidentId"] in incident_ids], "tests": [record for record in state["tests"] if record["incidentId"] in incident_ids], "audit": [record for record in state["audit"] if record["correlationId"] in incident_ids]}
        return Response(json.dumps(report, indent=2), media_type="application/json", headers={"Content-Disposition": 'attachment; filename="BEHAVE KYNDRYL-incident-report.json"'})

    return application


app = create_app()