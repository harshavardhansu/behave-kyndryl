"""Unit tests for newly added capabilities:
1. File upload support for diagnostic and code files.
2. Incident resolution report generation and error verification.
3. GitHub repository file deep analysis.
"""

import io
import pytest
from starlette.testclient import TestClient

from backend.domain import Settings
from backend.seed import seed_workspace
from backend.store import Store
from backend.app import create_app


@pytest.fixture
def test_app():
    settings = Settings(database_url="sqlite:///:memory:")
    store = Store(settings.database_url)
    store.initialize(seed_workspace(True))
    app = create_app(settings=settings, store=store)
    return app


@pytest.fixture
def client(test_app):
    return TestClient(test_app)


def login(client, role="Incident Manager"):
    res = client.post("/api/v1/auth/demo", json={"role": role})
    csrf = res.json()["csrf"]
    client.headers["X-CSRF-Token"] = csrf
    return csrf


def test_github_analysis_endpoint(client):
    login(client)
    payload = {
        "fileName": "workflow.yml",
        "repoName": "kyndryl/sample-repo",
        "content": "jobs:\n  deploy:\n    runs-on: ubuntu-latest\n    steps:\n    - uses: actions/checkout@master\n",
        "scope": ["workflow", "security"]
    }
    response = client.post("/api/v1/repositories/github-analysis", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "score" in data
    assert "findings" in data
    assert any("actions/checkout@master" in f["detail"] for f in data["findings"])
    assert "reportMarkdown" in data


def test_incident_resolution_report_endpoint(client):
    login(client)
    response = client.get("/api/v1/incidents/INC-1042/resolution-report")
    assert response.status_code == 200
    data = response.json()
    assert data["incidentId"] == "INC-1042"
    assert "reportMarkdown" in data
    assert "errorResolutionStatus" in data


def test_expanded_file_upload_support(client):
    login(client)
    # Upload YAML config file
    yaml_content = b"spring:\n  datasource:\n    hikari:\n      maximum-pool-size: 25\n"
    res = client.post(
        "/api/v1/incidents/INC-1042/evidence/upload",
        files={"file": ("config.yml", io.BytesIO(yaml_content), "text/yaml")},
    )
    assert res.status_code == 201
    record = res.json()
    assert record["type"] == "Configuration"
    assert "config.yml" in record["title"]


def test_repository_analysis_scans_the_real_files(client, monkeypatch):
    """The Repositories page reads the actual repository and reports rule matches with file and line, never templates."""
    from backend import connectors
    from backend.tests.test_fix_delivery import FakeGitHub

    login(client)
    invalid_payload = {"source": "repository", "url": "https://example.invalid/private/repo", "scope": ["Configuration", "Security"], "permissionConfirmed": True}
    assert client.post("/api/v1/repositories/analyses", json=invalid_payload).status_code == 422  # not GitHub: nothing is fetched

    github = FakeGitHub({"app/settings.py": 'API_KEY = "abcdefghijklmnop1234"\nDEBUG = True\n', "Dockerfile": "FROM python:3.13\nCOPY . .\n", "README.md": "hello\n"})
    original = connectors.GitHubCode.__init__

    def fake_init(self, repo, ref="", path="", api="https://api.github.com", token="", client=None, pull_requests=False):
        assert token == "" and ref == "a1b2c3d"  # a typed-in repository never uses the server token; the chosen commit is read
        original(self, repo, ref, path, api, token=token, client=github.client, pull_requests=pull_requests)

    monkeypatch.setattr(connectors.GitHubCode, "__init__", fake_init)
    monkeypatch.setattr(github, "handle", _with_ref_tarball(github.handle))
    valid_payload = {"source": "repository", "url": "https://github.com/northstar/payment-service", "branch": "main", "commit": "a1b2c3d", "stack": "Python",
                     "environment": "Staging", "scope": ["Configuration", "Code paths", "Dependencies", "Tests", "Security"], "incidentId": "INC-1042", "permissionConfirmed": True}
    response = client.post("/api/v1/repositories/analyses", json=valid_payload)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "Completed (static rules)" and "GitHub northstar/payment-service" in data["source"]
    assert "real files" in data["limitations"] and "SIMULATED" not in data["limitations"]
    secret = next(finding for finding in data["findings"] if finding["category"] == "Security" and finding["file"] == "app/settings.py")
    assert secret["line"] == 1 and secret["evidence"][0].startswith("app/settings.py:1")
    assert "abcdefghijklmnop1234" not in response.text  # the matched secret is redacted from the stored record
    assert any(finding["file"] == "Dockerfile" for finding in data["findings"])


def _with_ref_tarball(handle):
    import httpx

    def wrapped(request: httpx.Request):
        if "/tarball/" in request.url.path and not request.url.path.endswith("/tarball/main"):
            request = httpx.Request(request.method, str(request.url).rsplit("/tarball/", 1)[0] + "/tarball/main", headers=request.headers)
        return handle(request)
    return wrapped


def test_pdf_report_endpoints(client):
    login(client)
    # 1. Incident Resolution Report PDF
    res = client.get("/api/v1/incidents/INC-1042/resolution-report/pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF-")
    assert len(res.content) > 1000

    # 2. GitHub Analysis Report PDF
    payload = {
        "fileName": "workflow.yml",
        "repoName": "kyndryl/sample-repo",
        "content": "jobs:\n  deploy:\n    runs-on: ubuntu-latest\n    steps:\n    - uses: actions/checkout@master\n",
        "scope": ["workflow", "security"],
    }
    res_pdf = client.post("/api/v1/repositories/github-analysis/pdf", json=payload)
    assert res_pdf.status_code == 200
    assert res_pdf.headers["content-type"] == "application/pdf"
    assert res_pdf.content.startswith(b"%PDF-")
    assert len(res_pdf.content) > 1000




def test_backend_serves_the_built_site_without_shadowing_the_api(tmp_path):
    from fastapi.testclient import TestClient

    from backend.app import create_app
    from backend.domain import Settings
    from backend.store import Store

    (tmp_path / "index.html").write_text("<html>site</html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("nope")
    application = create_app(Settings(AGENTICA_MODE="demo", AGENTICA_STATIC_DIR=str(tmp_path)), Store("sqlite:///:memory:"))
    with TestClient(application) as client:
        assert client.get("/").text == "<html>site</html>"
        assert client.get("/incidents/INC-1042").text == "<html>site</html>"  # client-side routes get the app
        assert client.get("/assets/app.js").text == "console.log(1)"
        assert "nope" not in client.get("/../secret.txt").text and "nope" not in client.get("/%2e%2e/secret.txt").text
        assert client.get("/api/v1/health").json()["status"] == "ok"
        assert client.get("/api/v1/does-not-exist").status_code == 404


def test_demo_mode_on_a_cloud_host_requires_platform_sign_in():
    from fastapi.testclient import TestClient

    from backend.app import create_app
    from backend.domain import Settings
    from backend.store import Store

    def client(**extra):
        settings = Settings(AGENTICA_MODE="demo", AGENTICA_STATIC_DIR="/nonexistent", **extra)
        return TestClient(create_app(settings, Store("sqlite:///:memory:")), base_url="https://demo.example.net")

    with client() as plain:  # not listed: still loopback-only
        assert plain.get("/api/v1/health").status_code == 403
    with client(AGENTICA_DEMO_HOSTS="demo.example.net") as listed_without_auth:  # listing alone is not enough
        assert listed_without_auth.get("/api/v1/health").status_code == 403
    with client(AGENTICA_DEMO_HOSTS="demo.example.net", AGENTICA_REQUIRE_PLATFORM_AUTH=True) as cloud:
        assert cloud.get("/api/v1/health").status_code == 200  # the platform health probe
        assert cloud.post("/api/v1/auth/demo", json={"role": "Administrator"}).status_code == 401  # no signed-in user
        signed_in = {"X-MS-CLIENT-PRINCIPAL-ID": "00000000-0000-0000-0000-000000000001", "X-MS-CLIENT-PRINCIPAL-NAME": "user@example.net"}
        assert cloud.post("/api/v1/auth/demo", json={"role": "Incident Manager"}, headers=signed_in).status_code == 200
    with client(AGENTICA_DEMO_HOSTS="demo.example.net", AGENTICA_REQUIRE_PLATFORM_AUTH=True) as cloud:
        other = TestClient(cloud.app, base_url="https://evil.example.org")
        assert other.get("/api/v1/health").status_code == 403  # other host names stay blocked
