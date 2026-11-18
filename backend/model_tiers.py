"""Model tiers: the agents whose judgment decides the outcome run on an advanced reasoning model,
the agents that gather and summarise run on a fast, low-cost model.

- Advanced (AZURE_AI_MODEL_DEPLOYMENT_ADVANCED): Orchestrator, Root Cause, Remediation, Security,
  Validation and Risk: they choose the team, name the cause, write the fix and judge whether it is safe.
- Fast (AZURE_AI_MODEL_DEPLOYMENT): Intake, Logs, Observability, Repository, Knowledge, Testing,
  Release and Summary.

Without an advanced deployment every agent uses the fast one. The site shows the tier, never the
deployment name (``public_text``).
"""

import re

from .domain import Settings

ADVANCED_ROLES = frozenset({"orchestrator", "root-cause", "remediation", "security", "validation", "risk"})
LABELS = {"advanced": "Advanced reasoning model", "fast": "Fast model"}
_REASONING = re.compile(r"^(?:gpt-(?:[5-9]|\d{2,})|o[134])", re.I)  # GPT-5 and later, and the o-series


def tiered(settings: Settings) -> bool:
    advanced = settings.azure_ai_model_deployment_advanced
    return bool(advanced and advanced != settings.azure_ai_model_deployment)


def tier(settings: Settings, role: str | None) -> str:
    return "advanced" if tiered(settings) and (role or "orchestrator") in ADVANCED_ROLES else "fast"


def deployment(settings: Settings, role: str | None) -> str:
    """The model deployment a role runs on. ``None`` is the Orchestrator (team planning)."""
    return settings.azure_ai_model_deployment_advanced if tier(settings, role) == "advanced" else settings.azure_ai_model_deployment


def label(settings: Settings, role: str | None) -> str:
    return LABELS[tier(settings, role)] if tiered(settings) else "Azure OpenAI model"


def reasoning_effort(model: str) -> str | None:
    """Reasoning models think before answering; 'low' keeps a mission quick and inside the token budget."""
    return "low" if _REASONING.match(model) and "chat" not in model.lower() else None


def output_tokens(settings: Settings, model: str) -> int:
    """Reasoning tokens count against the output budget, so reasoning models get room for them."""
    return settings.ai_max_output_tokens + (2000 if reasoning_effort(model) else 0)


def summary(settings: Settings) -> str:
    if not tiered(settings):
        return "Azure OpenAI model"
    return f"Azure OpenAI: advanced reasoning model for {len(ADVANCED_ROLES)} key agents, fast model for the rest"


_MODEL_NAME = re.compile(r"\b(?:gpt|o[134])-[0-9A-Za-z.\-]*[0-9A-Za-z]\b")


def public_text(settings: Settings, text: str) -> str:
    """Replace model deployment names in text shown on the site with the tier they belong to."""
    advanced = settings.azure_ai_model_deployment_advanced if tiered(settings) else ""

    def name(match: re.Match) -> str:
        return "advanced reasoning model" if advanced and match.group(0) == advanced else "fast model"

    return _MODEL_NAME.sub(name, text)
