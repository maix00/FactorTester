"""Read-only summary of legacy grants before Keycloak migration."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def inventory(path: str | Path) -> dict[str, object]:
    """Aggregate rules without creating a database or exposing subjects/refs.

    A reported conflict requires policy review: the effective decision can
    also depend on membership of several subjects and on subtree rules.
    """
    uri = Path(path).expanduser().resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        rows = db.execute(
            "SELECT resource_type, action, scope, effect, COUNT(*) "
            "FROM permission_entries GROUP BY resource_type, action, scope, effect "
            "ORDER BY resource_type, action, scope, effect"
        ).fetchall()
        conflicts = db.execute(
            "SELECT COUNT(*) FROM (SELECT 1 FROM permission_entries "
            "GROUP BY subject, resource_type, resource_ref, action, scope "
            "HAVING COUNT(DISTINCT effect) > 1)"
        ).fetchone()[0]
        wildcard = db.execute(
            "SELECT COUNT(*) FROM permission_entries WHERE resource_ref='*'"
        ).fetchone()[0]
    return {
        "total": sum(row[4] for row in rows),
        "groups": [dict(zip(("resource_type", "action", "scope", "effect", "count"), row))
                   for row in rows],
        "conflicting_exact_rules": conflicts,
        "wildcard_rules": wildcard,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", help="Existing legacy permissions SQLite database")
    args = parser.parse_args()
    print(json.dumps(inventory(args.database), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
