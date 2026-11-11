"""Reset the local demo database to the realistic demo stories.

Usage (with the backend stopped):  python -m backend.demo_reset
The current database is backed up to data/backups/ first. While the backend is
running, use Administration -> "Reset demo data" instead.
"""

from datetime import datetime, timezone
from pathlib import Path

from .domain import Settings
from .seed import seed_workspace
from .store import Store


def main() -> None:
    settings = Settings()
    if settings.mode != "demo":
        raise SystemExit("Refusing to reset: AGENTICA_MODE is not 'demo'.")
    store = Store(settings.database_url)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = store.backup(Path("data") / "backups" / f"agentica-{stamp}.db")
    store.reset(seed_workspace(True))
    print("Demo data restored." + (f" Backup: {backup}" if backup else ""))


if __name__ == "__main__":
    main()
