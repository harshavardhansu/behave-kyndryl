"""Public judge site: the cloud host opens without platform sign-in, and workspace-damaging actions are refused."""
from starlette.testclient import TestClient

from backend.app import create_app
from backend.domain import Settings
from backend.store import Store

HOST = "judges.example.azurecontainerapps.io"


def make_client(**extra):
    settings = Settings(AGENTICA_MODE="demo", AGENTICA_DEMO_HOSTS=HOST, AGENTICA_ALLOWED_ORIGINS=f"https://{HOST}",
                        database_url="sqlite:///:memory:", **extra)
    return TestClient(create_app(settings, Store("sqlite:///:memory:")), base_url=f"https://{HOST}")


def admin(client):
    response = client.post("/api/v1/auth/demo", json={"role": "Administrator"})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf"]}


def test_cloud_host_stays_closed_without_sign_in_or_judge_mode():
    with make_client() as client:
        assert client.get("/api/v1/health").status_code == 403
    with make_client(AGENTICA_REQUIRE_PLATFORM_AUTH=True) as client:
        assert client.post("/api/v1/auth/demo", json={"role": "Viewer"}).status_code == 401   # no platform user


def test_judge_mode_opens_the_role_picker_without_platform_sign_in():
    with make_client(AGENTICA_PUBLIC_DEMO=True) as client:
        headers = admin(client)
        assert client.get("/api/v1/workspace").status_code == 200
        assert client.post("/api/v1/reports/export", json={"format": "json"}, headers=headers).status_code == 200


def test_judge_mode_refuses_actions_that_would_damage_the_shared_workspace():
    with make_client(AGENTICA_PUBLIC_DEMO=True) as client:
        headers = admin(client)
        reset = client.post("/api/v1/admin/demo-reset", json={"mode": "fresh"}, headers=headers)
        assert reset.status_code == 403 and "public judge site" in reset.json()["detail"]
        policy = client.get("/api/v1/workspace").json()["policy"]
        assert client.put("/api/v1/admin/policy", json=policy, headers=headers).status_code == 403
        assert client.post("/api/v1/foundry/agents/sync", json={}, headers=headers).status_code == 403


def test_judge_mode_never_opens_pull_requests(monkeypatch):
    from backend.connectors import Projects

    settings = {"type": "github", "repo": "example/app", "pull_requests": True}
    monkeypatch.setenv("AGENTICA_PUBLIC_DEMO", "false")
    assert Projects([])._code(settings).pull_requests is True
    monkeypatch.setenv("AGENTICA_PUBLIC_DEMO", "true")
    assert Projects([])._code(settings).pull_requests is False


def test_static_files_for_agents_are_served_and_missing_files_are_404(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>app</title>")
    (tmp_path / ".well-known").mkdir()
    (tmp_path / ".well-known" / "ard.json").write_text('{"entries": []}')
    (tmp_path / "llms.txt").write_text("# BEHAVE Kyndryl\n")
    settings = Settings(AGENTICA_MODE="demo", AGENTICA_STATIC_DIR=str(tmp_path), database_url="sqlite:///:memory:")
    with TestClient(create_app(settings, Store("sqlite:///:memory:"))) as client:
        ard = client.get("/.well-known/ard.json")
        assert ard.status_code == 200 and ard.json() == {"entries": []}
        assert client.get("/llms.txt").text.startswith("# BEHAVE Kyndryl")
        assert client.get("/sitemap.xml").status_code == 404          # a missing file is not the app's HTML
        assert "<title>app</title>" in client.get("/war-room").text     # app routes still get the single-page app


def test_unchanged_workspace_snapshot_comes_back_as_an_empty_304():
    with make_client(AGENTICA_PUBLIC_DEMO=True) as client:
        admin(client)
        first = client.get("/api/v1/workspace")
        assert first.status_code == 200 and first.json()["incidents"] is not None
        tag = first.headers["etag"]
        assert first.headers["cache-control"] == "private, no-cache"
        again = client.get("/api/v1/workspace", headers={"If-None-Match": tag})
        assert again.status_code == 304 and again.content == b""
        assert client.get("/api/v1/workspace", headers={"If-None-Match": '"stale"'}).status_code == 200


def test_key_agents_run_on_the_advanced_tier_and_the_site_shows_tiers_not_model_names():
    from backend import model_tiers

    settings = Settings(AGENTICA_MODE="demo", database_url="sqlite:///:memory:",
                        azure_ai_model_deployment="fast-1-mini", azure_ai_model_deployment_advanced="gpt-9.9")
    assert model_tiers.deployment(settings, "root-cause") == "gpt-9.9"
    assert model_tiers.deployment(settings, None) == "gpt-9.9"            # the Orchestrator plans the team
    assert model_tiers.deployment(settings, "logs") == "fast-1-mini"
    assert model_tiers.reasoning_effort("gpt-9.9") == "low" and model_tiers.reasoning_effort("fast-1-mini") is None
    text = model_tiers.public_text(settings, "AI-GENERATED / Azure OpenAI gpt-4.1-mini; root cause by gpt-9.9")
    assert "gpt" not in text and "fast model" in text and "advanced reasoning model" in text
    single = Settings(AGENTICA_MODE="demo", database_url="sqlite:///:memory:", azure_ai_model_deployment="gpt-4.1-mini")
    assert model_tiers.deployment(single, "root-cause") == "gpt-4.1-mini"  # no advanced deployment: one model for all
