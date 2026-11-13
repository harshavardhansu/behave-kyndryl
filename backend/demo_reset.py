"""Reset the local demo database to the realistic demo stories.

Usage (with the backend stopped):  python -m backend.demo_reset
The current database is backed up to data/backups/ first. While the backend is
running, use Administration -> "Reset demo data" instead.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

from .domain import Settings
from .seed import fresh_workspace, seed_workspace
from .store import Store


def main() -> None:
    settings = Settings()
    if settings.mode != "demo":
        raise SystemExit("Refusing to reset: AGENTICA_MODE is not 'demo'.")
    store = Store(settings.database_url)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = store.backup(Path("data") / "backups" / f"agentica-{stamp}.db")

    is_fresh = any(arg in sys.argv for arg in ("--fresh", "--clean", "fresh", "clean"))
    target = fresh_workspace() if is_fresh else seed_workspace(True)
    store.reset(target)

    if is_fresh:
        print("Fresh workspace ready: all demo activities cleared." + (f" Backup: {backup}" if backup else ""))
    else:
        print("Demo data restored." + (f" Backup: {backup}" if backup else ""))


if __name__ == "__main__":
    main()
