"""Create or update the 14 Behave Kyndryl agents in your Azure AI Foundry project.

Usage (after `az login`, with the backend stopped or running):
    python -m backend.foundry_provision            # create what is missing
    python -m backend.foundry_provision --force    # recreate every agent
    python -m backend.foundry_provision logs root-cause   # only some roles

Safe to run repeatedly: agents whose instructions did not change are skipped.
"""

import sys

from .ai_client import AIUnavailable
from .domain import Settings
from .foundry_runtime import FoundryAgentService
from .store import Store


def main() -> None:
    settings = Settings()
    args = [item for item in sys.argv[1:] if not item.startswith("--")]
    store = Store(settings.database_url)
    try:
        results = FoundryAgentService(settings, store).provision(args or None, force="--force" in sys.argv)
    except AIUnavailable as error:
        raise SystemExit(f"Could not sync agents: {error}")
    for item in results:
        print(f"{item['action']:>9}  {item['name']}  v{item['version']}")
    print(f"Done: {len(results)} agents checked in project {settings.azure_ai_project_endpoint.rstrip('/').split('/')[-1]}.")


if __name__ == "__main__":
    main()
