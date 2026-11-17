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
