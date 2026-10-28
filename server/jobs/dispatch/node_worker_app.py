"""Remote worker bootstrap: private node metadata cache, no Manager Job DB."""
import os
from pathlib import Path
import settings

root = Path(os.environ["TR_NODE_STATE_DIR"]).expanduser().resolve()
root.mkdir(parents=True, exist_ok=True, mode=0o700)
settings.CACHE_DB_PATH = root / "metadata.sqlite"
settings.CACHE_DIR = root

from .worker_app import app  # noqa: E402,F401
