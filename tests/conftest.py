from pathlib import Path
from contextlib import closing
import sys
import os
from tempfile import TemporaryDirectory

import pytest


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SKILL = ROOT / "skills/cli-anything-factortester-research/SKILL.md"
PACKAGED_SKILL = (
    ROOT
    / "tools/cli/agent-harness/cli_anything/factortester_research/skills/SKILL.md"
)
HARNESS_SOURCE = ROOT / "tools/cli/agent-harness"
_SESSION_STORAGE = pytest.StashKey[TemporaryDirectory]()

# The repository test suite exercises both release wheels, but GTHT is
# deliberately not a FactorTester runtime.  Make the source-only Harness
# available to tests without installing either wheel into that environment.
if str(HARNESS_SOURCE) not in sys.path:
    sys.path.insert(0, str(HARNESS_SOURCE))


def pytest_sessionstart(session: pytest.Session) -> None:
    """Isolate fallback database access before collecting application modules."""
    if PACKAGED_SKILL.read_bytes() != CANONICAL_SKILL.read_bytes():
        raise pytest.UsageError(
            "the packaged research Skill differs from its canonical source; "
            "merge intended changes into skills/cli-anything-factortester-research/"
            "SKILL.md, then run tools/cli/agent-harness/scripts/sync_skill.py --write"
        )
    import settings
    from scripts import data_dir
    import sqlite3
    import pandas as pd

    # Existing tests use the configured product catalog and public families.
    # Freeze only those fixtures, never accounts, sessions or private objects.
    with closing(sqlite3.connect(f"file:{settings.CACHE_DB_PATH}?mode=ro", uri=True)) as source:
        products = pd.read_sql_query('SELECT * FROM local_cnfutures_products', source)
        families = {
            table: pd.read_sql_query(
                f"SELECT * FROM {table} WHERE source_kind='public' AND owner_username=''",
                source,
            )
            for table in ("factor_family_sources", "factor_family_source_metadata")
        }

    # Manager session/account fallbacks also use this default. Without a
    # session boundary, tests with their own ManagerState can still reach the
    # live database declared in .settings (including a running container).
    storage = TemporaryDirectory(prefix="factortester-pytest-")
    session.config.stash[_SESSION_STORAGE] = storage
    settings.CACHE_DIR = Path(storage.name)
    settings.CACHE_DB_PATH = settings.CACHE_DIR / "unifieddata.sqlite"
    data_dir.CACHE_DB_PATH = settings.CACHE_DB_PATH
    from tools.data.sqlite.factor_source_store import _ensure_schema
    with closing(sqlite3.connect(settings.CACHE_DB_PATH)) as target:
        products.to_sql("local_cnfutures_products", target, index=False)
        _ensure_schema(target)
        for table, frame in families.items():
            frame.to_sql(table, target, if_exists="append", index=False)
    # Fresh Python/Conda workers do not inherit patched module constants.
    # Bootstrap this test-only path before they import settings; production
    # path resolution and .settings remain unchanged.
    bootstrap = settings.CACHE_DIR / "bootstrap"
    bootstrap.mkdir()
    (bootstrap / "sitecustomize.py").write_text(
        "from pathlib import Path\nfrom scripts import data_dir\n"
        f"data_dir.CACHE_DB_PATH = Path({str(settings.CACHE_DB_PATH)!r})\n",
    )
    os.environ["PYTHONPATH"] = os.pathsep.join([
        str(bootstrap), str(ROOT), os.environ.get("PYTHONPATH", ""),
    ])
