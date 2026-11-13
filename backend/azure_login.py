"""Sign in to Microsoft Entra ID with a device code and remember it locally (no passwords or keys in files).

Run once on the computer that runs the backend:

    python -m backend.azure_login

It prints a short code and a web address. Open the address in any browser (even on another
laptop), enter the code and sign in with the Azure account that can use your Foundry project.
The refresh token is kept in ``data/azure-token-cache.json`` (not committed to git, owner-only
permissions) and is renewed automatically, so the backend can call Azure AI Foundry afterwards.
"""

import json
import os
import sys
import time
from pathlib import Path

CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"  # Microsoft's public Azure CLI client
SCOPE = "https://ai.azure.com/.default"
CACHE_PATH = Path(os.getenv("AZURE_TOKEN_CACHE", "data/azure-token-cache.json"))


def _load_cache():
    import msal

    cache = msal.SerializableTokenCache()
    if CACHE_PATH.exists():
        cache.deserialize(CACHE_PATH.read_text(encoding="utf-8"))
    return cache


def _save_cache(cache) -> None:
    if cache.has_state_changed:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(cache.serialize(), encoding="utf-8")
        os.chmod(CACHE_PATH, 0o600)


def _app(tenant: str, cache):
    import msal

    return msal.PublicClientApplication(CLIENT_ID, authority=f"https://login.microsoftonline.com/{tenant or 'organizations'}", token_cache=cache)


class CachedUserCredential:
    """A token credential (``get_token``) backed by the locally remembered device-code sign-in."""

    def __init__(self, tenant: str):
        self.tenant = tenant

    def get_token(self, *scopes, **_kwargs):
        from azure.core.credentials import AccessToken
        from azure.core.exceptions import ClientAuthenticationError

        cache = _load_cache()
        app = _app(self.tenant, cache)
        accounts = app.get_accounts()
        result = app.acquire_token_silent(list(scopes) or [SCOPE], account=accounts[0]) if accounts else None
        _save_cache(cache)
        if not result or "access_token" not in result:
            raise ClientAuthenticationError("Not signed in to Azure. Run `python -m backend.azure_login` to sign in again.")
        return AccessToken(result["access_token"], int(time.time()) + int(result.get("expires_in", 3000)))

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def signed_in() -> bool:
    return CACHE_PATH.exists() and bool(_app("", _load_cache()).get_accounts())


def main() -> None:
    from .domain import Settings

    tenant = Settings().azure_tenant_id
    cache = _load_cache()
    app = _app(tenant, cache)
    flow = app.initiate_device_flow(scopes=[SCOPE])
    if "user_code" not in flow:
        raise SystemExit(f"Could not start the sign-in: {flow.get('error_description', flow)}")
    print(f"OPEN: {flow['verification_uri']}", flush=True)
    print(f"CODE: {flow['user_code']}", flush=True)
    print("Waiting for you to finish signing in (up to 15 minutes)...", flush=True)
    result = app.acquire_token_by_device_flow(flow)
    _save_cache(cache)
    if "access_token" not in result:
        raise SystemExit(f"Sign-in failed: {result.get('error_description', result)}")
    claims = result.get("id_token_claims", {})
    print(f"SIGNED IN as {claims.get('preferred_username', 'unknown')} (tenant {claims.get('tid', '?')}). Saved to {CACHE_PATH}.", flush=True)


if __name__ == "__main__":
    sys.exit(main())
