import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DataClassification = Literal["Public", "Internal", "Confidential", "Restricted"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    mode: Literal["demo", "production"] = Field("demo", validation_alias="AGENTICA_MODE")
    database_url: str = "sqlite:///./data/agentica.db"
    demo_step_seconds: float = Field(1.2, validation_alias="AGENTICA_DEMO_STEP_SECONDS", ge=0, le=30)
    max_upload_bytes: int = Field(2_097_152, validation_alias="AGENTICA_MAX_UPLOAD_BYTES", ge=1024, le=10_485_760)
    allowed_origins: str = Field("http://127.0.0.1:5173,http://localhost:5173", validation_alias="AGENTICA_ALLOWED_ORIGINS")
    azure_ai_project_endpoint: str = ""
    azure_ai_model_deployment: str = ""
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    auth_audience: str = Field("", validation_alias="AGENTICA_AUTH_AUDIENCE")
    object_storage_configuration: str = ""
    ai_allowed_classifications: list[Literal["Public", "Internal", "Confidential"]] = Field(default_factory=list, validation_alias="AGENTICA_AI_ALLOWED_CLASSIFICATIONS")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


SENSITIVE_KEY = re.compile(r"password|secret|token|authorization|api[_-]?key|private[_-]?key|cookie", re.I)
SECRET_PATTERNS = (
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "[REDACTED PRIVATE KEY]"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+=*"), r"\1[REDACTED]"),
    (re.compile(r"(?i)((?:api[_-]?key|password|secret|access[_-]?token|authorization)\s*[=:]\s*[\"']?)[^\s\"',;}]+"), r"\1[REDACTED]"),
    (re.compile(r"\b(?:ghp_|github_pat_|sk-)[A-Za-z0-9_\-]{16,}\b"), "[REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"), "[REDACTED JWT]"),
    (re.compile(r"(https?://)[^/@\s]+:[^/@\s]+@"), r"\1[REDACTED]@"),
)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "[REDACTED]" if SENSITIVE_KEY.search(str(key)) else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        for pattern, replacement in SECRET_PATTERNS:
            value = pattern.sub(replacement, value)
    return value


Environment = Literal["Production", "Staging", "Development", "Sandbox"]
Severity = Literal["Critical", "High", "Medium", "Low"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class IncidentInput(StrictModel):
    title: str = Field(min_length=8, max_length=160)
    description: str = Field(min_length=20, max_length=8000)
    severity: Severity
    environment: Environment
    service: str = Field(min_length=1, max_length=100)
    impact: str = Field(min_length=8, max_length=3000)
    source: Literal["Manual report", "Monitoring alert", "Repository analysis", "Application testing", "Telemetry import", "Ticket import"] = "Manual report"
    dataClassification: DataClassification = "Internal"
    error: str = Field("", max_length=6000)
    steps: str = Field("", max_length=4000)
    expected: str = Field("", max_length=2000)
    actual: str = Field("", max_length=2000)
    correlationId: str = Field("", max_length=200)
    detectedAt: str

    @field_validator("detectedAt")
    @classmethod
    def timestamp_with_timezone(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("An explicit time zone is required.")
        if parsed > datetime.now(timezone.utc):
            raise ValueError("First observed time cannot be in the future.")
        return value


class ActionInput(StrictModel):
    action: Literal["start-investigation", "pause", "resume", "cancel", "retry", "generate-fix", "run-validation", "request-approval", "approve", "reject", "deploy", "rollback", "verify", "close", "reopen", "assign", "escalate"]
    reason: str = Field("", max_length=3000)
    confirmation: str = Field("", max_length=100)
    owner: str = Field("", max_length=100)


class EvidenceInput(StrictModel):
    title: str = Field(min_length=5, max_length=180)
    excerpt: str = Field(min_length=10, max_length=20_000)
    source: str = Field(min_length=2, max_length=500)
    type: Literal["Log", "Metric", "Trace", "Change", "Observation", "Test", "Document"] = "Observation"
    classification: Literal["Observed", "Inferred", "Unverified"] = "Unverified"
    dataClassification: DataClassification = "Internal"
    timestamp: str
    traceId: str = Field("", max_length=200)
    reason: str = Field("", max_length=3000)

    @field_validator("timestamp")
    @classmethod
    def timestamp_with_timezone(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("An explicit time zone is required.")
        return value


class ReviewInput(StrictModel):
    status: Literal["Open", "Investigating", "Resolved", "Accepted risk"]
    reason: str = Field(min_length=10, max_length=2000)


class PolicyInput(StrictModel):
    minimumPassRate: int = Field(100, ge=95, le=100)
    retentionDays: int = Field(30, ge=7, le=365)
    maxTaskSeconds: int = Field(120, ge=10, le=300)
    maxRetries: int = Field(2, ge=0, le=3)
    requireSeparateApprover: Literal[True] = True
    blockCriticalFindings: Literal[True] = True
    productionApprovalRequired: Literal[True] = True


ROLE_PERMISSIONS: dict[str, set[str]] = {
    "Viewer": {"read", "export"},
    "Developer": {"read", "export", "incident:create", "incident:update", "evidence:add", "workflow:run", "validation:run", "approval:request"},
    "QA Engineer": {"read", "export", "incident:create", "evidence:add", "validation:run"},
    "SRE / Operator": {"read", "export", "incident:create", "incident:update", "evidence:add", "workflow:run", "validation:run", "approval:request", "change:deploy", "recovery:record", "incident:close"},
    "Security Analyst": {"read", "export", "evidence:add", "security:review"},
    "Incident Manager": {"read", "export", "incident:create", "incident:update", "evidence:add", "workflow:run", "validation:run", "approval:request", "change:deploy", "recovery:record", "incident:close"},
    "Change Approver": {"read", "export", "approval:decide"},
    "Administrator": {"read", "export", "incident:create", "incident:update", "evidence:add", "workflow:run", "validation:run", "approval:request", "approval:decide", "change:deploy", "recovery:record", "incident:close", "security:review", "admin:write"},
}

PERSONAS = {
    "Incident Manager": ("alex-morgan", "Alex Morgan", "AM"),
    "Change Approver": ("sam-rivera", "Sam Rivera", "SR"),
    "Administrator": ("taylor-chen", "Taylor Chen", "TC"),
    "Viewer": ("jordan-lee", "Jordan Lee", "JL"),
    "Developer": ("maya-patel", "Maya Patel", "MP"),
    "QA Engineer": ("olivia-brooks", "Olivia Brooks", "OB"),
    "SRE / Operator": ("james-wilson", "James Wilson", "JW"),
    "Security Analyst": ("noah-kim", "Noah Kim", "NK"),
}


def persona(role: str) -> dict:
    identifier, name, initials = PERSONAS[role]
    environments = ["Development", "Staging"] if role in {"Developer", "QA Engineer"} else ["Development", "Staging", "Production", "Sandbox"]
    return {"id": identifier, "name": name, "initials": initials, "role": role, "permissions": sorted(ROLE_PERMISSIONS[role]), "environments": environments}