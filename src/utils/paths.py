"""Resolution of the single global nebula.db location.

The database holds all configuration, so its own path is the one setting that
cannot live inside it. It is resolved, in priority order, from:

1. the ``NEBULA_DB_PATH`` environment variable (used by tests for isolation),
2. a small pointer file the UI can edit (changes need an app restart),
3. a per-user default under the XDG data directory.
"""

import os
from pathlib import Path

ENV_VAR = "NEBULA_DB_PATH"
POINTER_FILE = Path.home() / ".config" / "nebula_archiver" / "db_path"
DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "nebula_archiver" / "nebula.db"


def get_db_path() -> Path:
    """Resolve the absolute path to the global nebula.db."""
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env)
    if POINTER_FILE.exists():
        text = POINTER_FILE.read_text().strip()
        if text:
            return Path(text)
    return DEFAULT_DB_PATH


def set_db_path(path: str | Path) -> None:
    """Persist a new db location to the pointer file (effective next restart)."""
    POINTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    POINTER_FILE.write_text(str(path))
