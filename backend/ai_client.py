"""Azure OpenAI / Foundry connection and spend controls.

Two ways to sign in:
- API key: AZURE_OPENAI_ENDPOINT (https://<resource>.openai.azure.com/openai/v1) + AZURE_OPENAI_API_KEY
- Microsoft Entra ID: AZURE_AI_PROJECT_ENDPOINT (services.ai.azure.com/api/projects/...) via DefaultAzureCredential

``AIBudget`` keeps AI spend small and visible: a daily call limit, an answer
cache so identical requests are never paid for twice, and a usage meter that
the workspace snapshot exposes to the UI.
"""

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import urlparse

from .domain import Settings, now
from .store import Store


class AIUnavailable(Exception):
    """Raised when an AI call cannot or must not be made. The message is safe to show."""


def key_mode(settings: Settings) -> bool:
    return bool(settings.azure_openai_endpoint and settings.azure_openai_api_key.get_secret_value())


def ai_configured(settings: Settings) -> bool:
    return bool(settings.azure_ai_model_deployment and (key_mode(settings) or settings.azure_ai_project_endpoint))


def validate_openai_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or not (host.endswith(".openai.azure.com") or host.endswith(".services.ai.azure.com"))
        or not parsed.path.rstrip("/").endswith("/openai/v1")
        or parsed.username or parsed.password or parsed.query or parsed.fragment
    ):
        raise AIUnavailable("Invalid Azure OpenAI endpoint. Use https://<resource>.openai.azure.com/openai/v1.")
    return endpoint.rstrip("/") + "/"


@contextmanager
def openai_client(settings: Settings) -> Iterator[object]:
    """Yield an OpenAI-compatible client for the configured Azure resource."""
    if key_mode(settings):
        from openai import OpenAI

        client = OpenAI(
            base_url=validate_openai_endpoint(settings.azure_openai_endpoint),
            api_key=settings.azure_openai_api_key.get_secret_value(),
            timeout=30.0,
            max_retries=1,
        )
        try:
            yield client
        finally:
            client.close()
        return
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    with DefaultAzureCredential(managed_identity_client_id=settings.azure_client_id or None, exclude_interactive_browser_credential=True, process_timeout=5) as credential:
        with AIProjectClient(endpoint=settings.azure_ai_project_endpoint, credential=credential) as project:
            with project.get_openai_client() as client:
                yield client.with_options(timeout=30.0, max_retries=1)


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class AIBudget:
    """Daily call limit, answer cache and usage meter, persisted in the workspace."""

    CACHE_LIMIT = 150

    def __init__(self, store: Store, settings: Settings):
        self.store = store
        self.settings = settings

    @staticmethod
    def cache_key(purpose: str, payload: dict, model: str) -> str:
        encoded = json.dumps({"purpose": purpose, "model": model, "payload": payload}, sort_keys=True, default=str)
        return hashlib.sha256(encoded.encode()).hexdigest()

    def _usage(self, state: dict) -> dict:
        usage = state.get("aiUsage") or {}
        if usage.get("date") != _today():
            totals = usage.get("totals", {"calls": 0, "inputTokens": 0, "outputTokens": 0, "cacheHits": 0})
            usage = {"date": _today(), "calls": 0, "inputTokens": 0, "outputTokens": 0, "cacheHits": 0, "totals": totals, "recent": usage.get("recent", [])}
        usage["limit"] = self.settings.ai_daily_call_limit
        usage["model"] = self.settings.azure_ai_model_deployment
        state["aiUsage"] = usage
        return usage

    def cached(self, key: str) -> dict | None:
        state = self.store.read()
        return (state.get("aiCache") or {}).get(key)

    def reserve(self) -> None:
        """Count a call before it is made, so the limit holds even if the call fails."""

        def operation(state: dict) -> bool:
            usage = self._usage(state)
            if usage["calls"] >= usage["limit"]:
                return False
            usage["calls"] += 1
            usage["totals"]["calls"] += 1
            return True

        if not self.store.mutate(operation):
            raise AIUnavailable(f"Daily AI call limit reached ({self.settings.ai_daily_call_limit}). The free simulated planner is used until tomorrow (UTC).")

    def record(self, purpose: str, key: str, result: dict, input_tokens: int, output_tokens: int) -> None:
        def operation(state: dict) -> None:
            usage = self._usage(state)
            usage["inputTokens"] += input_tokens
            usage["outputTokens"] += output_tokens
            usage["totals"]["inputTokens"] += input_tokens
            usage["totals"]["outputTokens"] += output_tokens
            usage["recent"] = (usage.get("recent", []) + [{"at": now(), "purpose": purpose, "inputTokens": input_tokens, "outputTokens": output_tokens}])[-20:]
            cache = state.setdefault("aiCache", {})
            cache[key] = result
            while len(cache) > self.CACHE_LIMIT:
                cache.pop(next(iter(cache)))

        self.store.mutate(operation)

    def hit(self) -> None:
        def operation(state: dict) -> None:
            usage = self._usage(state)
            usage["cacheHits"] += 1
            usage["totals"]["cacheHits"] += 1

        self.store.mutate(operation)
