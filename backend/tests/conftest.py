"""Test-wide safety: never let a developer's local .env turn tests into paid AI calls.

Environment variables take priority over the .env file in pydantic-settings, so
blanking the AI connection settings here keeps every test on the free, simulated
planner unless a test passes explicit settings of its own.
"""

import os

for name in (
    "AZURE_AI_PROJECT_ENDPOINT",
    "AZURE_AI_MODEL_DEPLOYMENT",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
):
    os.environ[name] = ""
