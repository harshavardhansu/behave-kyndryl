"""Test-wide safety: never let a developer's local .env turn tests into paid AI calls, reach a real
GitHub account, or write uploads into the developer's data folder.

Environment variables take priority over the .env file in pydantic-settings, so
blanking the AI connection settings here keeps every test on the free, simulated
planner unless a test passes explicit settings of its own.
"""

import os

import pytest

for name in (
    "AZURE_AI_PROJECT_ENDPOINT",
    "AZURE_AI_MODEL_DEPLOYMENT",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_CLIENT_SECRET",
    "AGENTICA_GITHUB_TOKEN",
    "AGENTICA_PROJECTS_FILE",
):
    os.environ[name] = ""
os.environ["AGENTICA_GITHUB_USE_CLI"] = "false"  # tests never borrow a real GitHub login


@pytest.fixture(autouse=True)
def isolated_connectors(tmp_path, monkeypatch):
    """Each test gets its own upload folder and starts without another test's application settings."""
    from backend import connectors

    monkeypatch.setenv("AGENTICA_TASK_STORAGE_DIR", str(tmp_path / "tasks"))
    connectors._settings.clear()
    connectors._cli_token.clear()
    yield
    connectors._settings.clear()
