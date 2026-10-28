#!/usr/bin/env python3
"""Back up and remove legacy SQLite/JSON/mirror authority paths.

Dry-run by default.  Actual removal requires --confirm and a backup dir.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

TABLES = (
    "account_product_groups",
    "factor_family_catalog",
    "factor_family_catalog_params",
    "factor_family_sources",
    "factor_family_source_metadata",
    "strategy_library_entries",
    "strategy_library_revisions",
    "strategy_library_shares",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--public-research", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args(argv)
    with sqlite3.connect(args.db) as conn:
        counts = {}
        for table in TABLES:
            try:
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.OperationalError:
                counts[table] = None
    research = args.public_research
    mirrors = research / "mirrors"
    size = sum(path.stat().st_size for path in mirrors.rglob("*") if path.is_file()) if mirrors.is_dir() else 0
    report = {"db": str(args.db), "tables": counts,
              "publications": (research / "publications.json").exists(),
              "mirror_bytes": size, "confirmed": args.confirm}
    if not args.confirm:
        print(json.dumps(report, indent=2))
        return 0
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = args.backup_dir / f"legacy-authority-{stamp}"
    target.mkdir(parents=True, exist_ok=False)
    shutil.copy2(args.db, target / args.db.name)
    if research.exists():
        shutil.copytree(research, target / "public-research")
    with sqlite3.connect(args.db) as conn:
        for table in TABLES:
            try:
                conn.execute(f"DROP TABLE IF EXISTS {table}")
            except sqlite3.OperationalError:
                pass
        conn.execute("DELETE FROM account_domain_entities WHERE entity_type IN ('factor_family','product_group')")
        conn.commit()
    shutil.rmtree(mirrors, ignore_errors=True)
    (research / "publications.json").unlink(missing_ok=True)
    print(json.dumps({"backup": str(target), "removed": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
