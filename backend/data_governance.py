import hashlib

from .domain import Settings, now


CLASSIFICATIONS = ("Public", "Internal", "Confidential", "Restricted")


class DataPolicyError(ValueError):
    pass


def sensitivity(record: dict) -> str:
    value = record.get("dataClassification", "Internal")
    return value if value in CLASSIFICATIONS else "Restricted"


def strongest_classification(*records: dict) -> str:
    return max((sensitivity(record) for record in records), key=CLASSIFICATIONS.index, default="Internal")


def authorize_model_context(settings: Settings, incident: dict, evidence: list[dict]) -> None:
    classifications = {sensitivity(record) for record in [incident, *evidence]}
    if "Restricted" in classifications:
        raise DataPolicyError("Restricted data cannot be sent to an AI provider. An approved restricted-data policy and enforcement controls are not configured.")
    if not classifications <= set(settings.ai_allowed_classifications):
        raise DataPolicyError("AI data access denied by the configured classification policy. Configure AGENTICA_AI_ALLOWED_CLASSIFICATIONS only after organizational approval.")


def evidence_provenance(record: dict, original: bytes, actor: dict, media_type: str, hash_scope: str) -> dict:
    derivative = record["excerpt"].encode("utf-8")
    return {
        "collectedById": actor["id"],
        "collectedAt": now(),
        "sizeBytes": len(original),
        "mediaType": media_type,
        "sha256": hashlib.sha256(original).hexdigest(),
        "hashScope": hash_scope,
        "derivativeSha256": hashlib.sha256(derivative).hexdigest(),
        "redactionStatus": "CHECKED_BY_PATTERN_FILTER",
        "originalRetained": False,
        "storageReference": f"database:evidence:{record['id']}",
        "malwareScanStatus": "NOT CONFIGURED",
    }