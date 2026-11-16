"""What is really connected, checked live rather than declared.

The Administration page and the workspace snapshot show these statuses. Each one comes from a real
check (an agent registry read, a search index call, a Key Vault metadata call with the app's identity,
the tracing exporter), never from a hard-coded label. Results are cached for a few minutes so the
checks do not run on every page load.
"""

import time
from threading import Lock, Thread
from typing import Any

import httpx

from . import knowledge_search, telemetry
from .connectors import Projects
from .domain import Settings

CACHE_SECONDS = 300
_cache: dict[str, tuple[float, dict]] = {}
_lock = Lock()


_running: set[str] = set()


def _cached(key: str, check) -> dict:
    """The last checked value; a stale or missing one is re-checked in the background so pages never wait."""
    with _lock:
        hit = _cache.get(key)
        fresh = hit is not None and time.monotonic() - hit[0] < CACHE_SECONDS
        if fresh:
            return hit[1]
        start = key not in _running
        if start:
            _running.add(key)

    def run() -> None:
        try:
            value = check()
            with _lock:
                _cache[key] = (time.monotonic(), value)
        finally:
            with _lock:
                _running.discard(key)

    if start:
        Thread(target=run, name=f"status-{key}", daemon=True).start()
    return hit[1] if hit else {"status": "Checking", "detail": "Checking the connection now; refresh in a moment."}


def forget() -> None:
    with _lock:
        _cache.clear()


def key_vault(settings: Settings) -> dict:
    """List secret *names* with the app's own identity: proves access without reading any secret value."""
    if not settings.key_vault_uri:
        return {"status": "Not configured", "detail": "No Key Vault is set (AGENTICA_KEY_VAULT_URI)."}

    def check() -> dict:
        try:
            from .ai_client import entra_credential

            token = entra_credential(settings).get_token("https://vault.azure.net/.default").token
            response = httpx.get(f"{settings.key_vault_uri.rstrip('/')}/secrets", params={"api-version": "7.4", "maxresults": 25},
                                 headers={"Authorization": f"Bearer {token}"}, timeout=10)
            if response.status_code != 200:
                return {"status": "Error", "detail": f"Key Vault answered {response.status_code} to the app's identity."}
            names = sorted(item["id"].rsplit("/", 1)[-1] for item in response.json().get("value", []))
            return {"status": "Connected", "detail": f"{len(names)} secrets held, read with the app's own identity (no stored key): {', '.join(names)}. Values are never shown."}
        except Exception as error:  # noqa: BLE001 - a status page must not fail
            return {"status": "Error", "detail": f"{type(error).__name__} while checking the vault."}

    return _cached("key-vault", check)


def search_service(settings: Settings) -> dict:
    index = knowledge_search.current()
    if index is None:
        return {"status": "Not configured", "detail": "Knowledge is searched locally by keyword (AZURE_SEARCH_ENDPOINT is not set)."}

    def check() -> dict:
        try:
            count = len(index.indexed_ids())
            return {"status": "Connected", "detail": f"Index '{index.index}' holds {count} knowledge records; agents search the approved ones (Entra authentication, no key)."}
        except Exception as error:  # noqa: BLE001
            return {"status": "Error", "detail": f"{type(error).__name__}: {str(error)[:160]}"}

    return _cached("search", check)


def statuses(settings: Settings, state: dict, agents_ready: int, ai_configured: bool) -> list[dict]:
    """The integration list for a real workspace, each with a status that was actually checked."""
    projects = Projects.load()
    github = [entry for entry in projects.entries.values() if (entry.get("code") or {}).get("type") == "github"]
    with_prs = [entry for entry in github if (entry.get("code") or {}).get("pull_requests") is True]
    vault, search = key_vault(settings), search_service(settings)
    rows: list[dict[str, Any]] = [
        {"id": "foundry", "name": "Azure AI Foundry agents", "category": "AI provider",
         "status": "Connected" if agents_ready and ai_configured else "Not configured",
         "description": f"{agents_ready} specialist agents provisioned in Azure AI Foundry Agent Service; the Orchestrator picks a team per incident." if agents_ready else "No Foundry agents are provisioned; missions use the labelled simulated planner.",
         "required": ["AZURE_AI_PROJECT_ENDPOINT", "AZURE_AI_MODEL_DEPLOYMENT", "Managed identity"]},
        {"id": "github", "name": "GitHub (read-only connector)", "category": "Repository", "status": "Connected",
         "description": f"Any public repository can be read per task; {len(github)} connected by an administrator, {len(with_prs)} with pull requests on. Fixes are never pushed to a base branch.",
         "required": ["projects.json", "AGENTICA_GITHUB_TOKEN for private repositories and pull requests"]},
        {"id": "search", "name": "Azure AI Search (organizational memory)", "category": "Knowledge", "status": search["status"], "description": search["detail"],
         "required": ["AZURE_SEARCH_ENDPOINT", "Search Index Data Contributor role for the app identity"]},
        {"id": "keyvault", "name": "Azure Key Vault", "category": "Secrets", "status": vault["status"], "description": vault["detail"],
         "required": ["AGENTICA_KEY_VAULT_URI", "Key Vault Secrets User role for the app identity"]},
        {"id": "tracing", "name": "Application Insights tracing", "category": "Observability",
         "status": "Connected" if telemetry.enabled() else "Not configured",
         "description": "Agent runs, tool calls and Tool Gateway decisions are traced (metadata only: no prompts, code or logs)." if telemetry.enabled() else "APPLICATIONINSIGHTS_CONNECTION_STRING is not set; the audit trail still records everything.",
         "required": ["APPLICATIONINSIGHTS_CONNECTION_STRING"]},
        {"id": "gateway", "name": "Tool Gateway", "category": "Governance", "status": "Active",
         "description": f"3 registered outside actions, each re-checked against the persisted human approval; {len(state.get('gateway', []))} requests logged so far.",
         "required": []},
        {"id": "entra", "name": "Microsoft Entra ID", "category": "Identity", "status": "Connected" if settings.require_platform_auth or settings.mode == "production" else "Local personas",
         "description": "Sign-in is enforced in front of the app; the app reaches Foundry, Search and Key Vault with its managed identity." if settings.require_platform_auth else "Local development: persona sign-in, no Entra front door.",
         "required": []},
        {"id": "telemetry", "name": "Live monitoring connectors", "category": "Telemetry", "status": "Not configured",
         "description": "No monitoring system is connected. Logs, stack traces and errors come from what people upload or paste on a task.",
         "required": ["A log or metrics connector (e.g. Log Analytics, Splunk, Datadog)"]},
        {"id": "runner", "name": "Isolated test runner", "category": "Execution", "status": "Not configured",
         "description": "Uploaded code is never executed, so no test or build result is claimed for it. Only the Payment API sandbox is measured.",
         "required": ["Isolated runner (e.g. Azure Container Apps jobs)"]},
        {"id": "scanner", "name": "Security scanning", "category": "Security", "status": "Built-in rules",
         "description": "Repository scans run built-in static rules (secrets, containers, debug settings, workflows) on real files. No external SAST/SCA scanner is connected.",
         "required": []},
        {"id": "itsm", "name": "Ticket intake", "category": "Intake", "status": "Built-in",
         "description": "Incidents are created in the app or imported from JSON/CSV ticket files. No ServiceNow or Jira connector is connected.",
         "required": []},
    ]
    return rows
