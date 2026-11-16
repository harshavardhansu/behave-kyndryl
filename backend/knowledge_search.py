"""Organizational memory, searched through Azure AI Search.

The knowledge base holds runbooks, guides and the resolution records that agent missions write when
they finish (see ``mission._remember``). Every record is indexed in Azure AI Search; the Knowledge
agent searches the **approved** ones there (full-text BM25 ranking, title weighted, boosted for the
affected service), so what one incident taught is found for the next.

- Authentication is Microsoft Entra ID only (the app's managed identity in Azure, the signed-in user
  locally): no search key exists anywhere.
- Without a configured search service, or if a call fails, a local keyword search over the same
  records is used, and every answer says which one produced it.
"""

import logging
import re
import threading
import time
from typing import Any, Callable

import httpx

from .domain import Settings, redact

API_VERSION = "2024-07-01"
SCOPE = "https://search.azure.com/.default"
log = logging.getLogger("behave.knowledge")

INDEX_FIELDS = [
    {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
    {"name": "title", "type": "Edm.String", "searchable": True},
    {"name": "body", "type": "Edm.String", "searchable": True},
    {"name": "type", "type": "Edm.String", "filterable": True, "facetable": True},
    {"name": "services", "type": "Collection(Edm.String)", "filterable": True},
    {"name": "incidents", "type": "Collection(Edm.String)", "filterable": True},
    {"name": "fingerprints", "type": "Collection(Edm.String)", "filterable": True},
    {"name": "approved", "type": "Edm.Boolean", "filterable": True},
    {"name": "verified", "type": "Edm.Boolean", "filterable": True},
    {"name": "source", "type": "Edm.String"},
    {"name": "owner", "type": "Edm.String"},
    {"name": "reviewedAt", "type": "Edm.String", "sortable": True},
]
SCORING = {"name": "service-boost", "text": {"weights": {"title": 3, "body": 1}},
           "functions": [{"type": "tag", "fieldName": "services", "boost": 3, "interpolation": "linear", "tag": {"tagsParameter": "service"}}],
           "functionAggregation": "sum"}


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _document(record: dict) -> dict:
    return {
        "@search.action": "mergeOrUpload", "id": str(record["id"]), "title": str(record.get("title", ""))[:500],
        "body": redact(str(record.get("body", "")))[:30000], "type": str(record.get("type", "")),
        "services": [str(item) for item in record.get("services", [])][:20], "incidents": [str(item) for item in record.get("incidents", [])][:20],
        "fingerprints": [str(item) for item in record.get("fingerprints", [])][:20], "approved": bool(record.get("approved")),
        "verified": bool(record.get("verified")), "source": str(record.get("source", ""))[:300], "owner": str(record.get("owner", ""))[:120],
        "reviewedAt": str(record.get("reviewedAt", "")),
    }


def local_search(knowledge: list[dict], query: str, service: str = "", top: int = 3) -> list[dict]:
    """Keyword scoring over the approved records (the fallback when Azure AI Search is not available)."""
    words = [word for word in re.split(r"\W+", query.lower()) if len(word) > 2]
    hits = []
    for article in knowledge:
        if not article.get("approved"):
            continue
        haystack = f"{article.get('title', '')} {article.get('body', '')}".lower()
        score = sum(word in haystack for word in words) + (1 if service in article.get("services", []) else 0)
        if score > 1 or (score and service in article.get("services", [])):
            hits.append((score, article))
    hits.sort(key=lambda pair: -pair[0])
    return [{"id": a["id"], "title": a.get("title"), "type": a.get("type"), "verified": bool(a.get("verified")), "score": float(score),
             "text": _clip(a.get("body", ""), 700)} for score, a in hits[:top]]


class KnowledgeIndex:
    """The knowledge index in Azure AI Search, called over REST with an Entra token."""

    def __init__(self, endpoint: str, index: str, credential_factory: Callable[[], Any], client: Callable[[], httpx.Client] | None = None):
        self.endpoint = endpoint.rstrip("/")
        self.index = index
        self._credential_factory = credential_factory
        self._credential = None
        self._token: tuple[str, float] | None = None
        self._client = client or (lambda: httpx.Client(timeout=15))
        self._ready = False
        self._lock = threading.Lock()
        self.problem = ""

    def _bearer(self) -> str:
        if self._token and self._token[1] - time.time() > 120:
            return self._token[0]
        if self._credential is None:
            self._credential = self._credential_factory()
        token = self._credential.get_token(SCOPE)
        self._token = (token.token, float(token.expires_on))
        return token.token

    def _call(self, method: str, path: str, body: dict | None = None, ok: tuple[int, ...] = (200, 201, 204)) -> dict:
        headers = {"Authorization": f"Bearer {self._bearer()}", "Content-Type": "application/json"}
        with self._client() as client:
            response = client.request(method, f"{self.endpoint}{path}", params={"api-version": API_VERSION}, json=body, headers=headers)
        if response.status_code not in ok:
            message = ""
            try:
                message = response.json().get("error", {}).get("message", "")
            except ValueError:
                pass
            raise RuntimeError(f"Azure AI Search answered {response.status_code}: {message[:200]}")
        return response.json() if response.content else {}

    def ensure_index(self) -> None:
        if self._ready:
            return
        with self._lock:
            if not self._ready:
                self._call("PUT", f"/indexes('{self.index}')", {"name": self.index, "fields": INDEX_FIELDS, "scoringProfiles": [SCORING]})
                self._ready = True

    def upsert(self, records: list[dict]) -> int:
        if not records:
            return 0
        self.ensure_index()
        for start in range(0, len(records), 500):
            self._call("POST", f"/indexes('{self.index}')/docs/search.index", {"value": [_document(record) for record in records[start:start + 500]]})
        return len(records)

    def delete(self, ids: list[str]) -> int:
        if not ids:
            return 0
        self.ensure_index()
        self._call("POST", f"/indexes('{self.index}')/docs/search.index", {"value": [{"@search.action": "delete", "id": str(item)} for item in ids]})
        return len(ids)

    def indexed_ids(self) -> set[str]:
        self.ensure_index()
        found = self._call("POST", f"/indexes('{self.index}')/docs/search.post.search", {"search": "*", "select": "id", "top": 1000})
        return {str(item["id"]) for item in found.get("value", [])}

    def sync(self, knowledge: list[dict]) -> dict:
        """Make the index match the knowledge base exactly."""
        present = {str(record["id"]) for record in knowledge}
        stale = sorted(self.indexed_ids() - present)
        return {"indexed": self.upsert(knowledge), "removed": self.delete(stale)}

    def search(self, query: str, service: str = "", top: int = 3) -> list[dict]:
        words = " ".join(word for word in re.split(r"[^\w.-]+", query) if len(word) > 1)[:400]
        if not words:
            return []
        self.ensure_index()
        body: dict[str, Any] = {"search": words, "searchMode": "any", "queryType": "simple", "top": top, "filter": "approved eq true",
                                "select": "id,title,type,body,services,verified,source", "scoringProfile": "service-boost"}
        if service and "," not in service:
            body["scoringParameters"] = [f"service-{service}"]
        found = self._call("POST", f"/indexes('{self.index}')/docs/search.post.search", body)
        return [{"id": item["id"], "title": item.get("title"), "type": item.get("type"), "verified": bool(item.get("verified")),
                 "score": round(float(item.get("@search.score", 0)), 3), "text": _clip(item.get("body", ""), 700)} for item in found.get("value", [])]


_index: dict[str, KnowledgeIndex | None] = {"value": None}


def configure(settings: Settings) -> KnowledgeIndex | None:
    """Use Azure AI Search when AZURE_SEARCH_ENDPOINT is set (Entra authentication, no key)."""
    if not settings.azure_search_endpoint:
        _index["value"] = None
        return None
    from .ai_client import entra_credential

    _index["value"] = KnowledgeIndex(settings.azure_search_endpoint, settings.azure_search_index, lambda: entra_credential(settings))
    return _index["value"]


def current() -> KnowledgeIndex | None:
    return _index["value"]


def search(knowledge: list[dict], query: str, service: str = "", top: int = 3) -> dict:
    """Search approved knowledge: Azure AI Search when configured, else (or on failure) local keyword search."""
    index = current()
    if index is not None:
        try:
            return {"retrieval": "Azure AI Search (BM25, boosted for the affected service)", "articles": index.search(query, service, top)}
        except Exception as error:  # noqa: BLE001 - the local search still answers, and says why
            index.problem = f"{type(error).__name__}: {error}"[:200]
            log.warning("Azure AI Search failed, using local search: %s", index.problem)
            return {"retrieval": f"local keyword search (Azure AI Search unavailable: {index.problem})", "articles": local_search(knowledge, query, service, top)}
    return {"retrieval": "local keyword search (Azure AI Search is not configured)", "articles": local_search(knowledge, query, service, top)}


def refresh(read_knowledge: Callable[[], list[dict]], ids: list[str] | None = None) -> None:
    """Update the index in the background: the given records, or a full sync when ``ids`` is None."""
    index = current()
    if index is None:
        return

    def work() -> None:
        try:
            knowledge = read_knowledge()
            if ids is None:
                result = index.sync(knowledge)
                log.warning("Knowledge index synced: %d records, %d removed.", result["indexed"], result["removed"])
            else:
                index.upsert([record for record in knowledge if record["id"] in set(ids)])
            index.problem = ""
        except Exception as error:  # noqa: BLE001 - reported in the logs and the status endpoint
            index.problem = f"{type(error).__name__}: {error}"[:200]
            log.warning("Knowledge index update failed: %s", index.problem)

    threading.Thread(target=work, name="knowledge-index", daemon=True).start()
