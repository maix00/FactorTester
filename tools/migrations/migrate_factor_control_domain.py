"""Apply or restore one explicit formula-identity control-domain plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


def _database_url(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "FACTORTESTER_CONTROL_DATABASE_URL":
            url = value.strip()
            if url:
                return url
    raise ValueError("control database URL is unavailable")


def _rows(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    rows = value.get("rows") if isinstance(value, dict) else None
    if not isinstance(rows, list) or not all(isinstance(item, dict) for item in rows):
        raise ValueError("factor control-domain migration plan is invalid")
    return rows


def apply_plan(
    *, plan_path: Path, environment_path: Path, restore: bool = False,
) -> int:
    rows = _rows(plan_path)
    with psycopg.connect(_database_url(environment_path)) as connection:
        for item in rows:
            expected = int(item["expected_revision"])
            if restore:
                payload = item["old_payload"]
                deleted = bool(item["old_deleted"])
                current_revision = expected + 1
                next_revision = expected
            else:
                payload = item["new_payload"]
                deleted = bool(item["new_deleted"])
                current_revision = expected
                next_revision = expected + 1
            cursor = connection.execute(
                "UPDATE control_account_domain_entities "
                "SET payload=%s, deleted=%s, revision=%s, updated_at=now() "
                "WHERE principal=%s AND entity_type=%s AND entity_id=%s "
                "AND revision=%s",
                (
                    Jsonb(payload), deleted, next_revision,
                    item["principal"], item["entity_type"], item["entity_id"],
                    current_revision,
                ),
            )
            if cursor.rowcount != 1:
                current = connection.execute(
                    "SELECT payload, deleted FROM control_account_domain_entities "
                    "WHERE principal=%s AND entity_type=%s AND entity_id=%s",
                    (item["principal"], item["entity_type"], item["entity_id"]),
                ).fetchone()
                if current and current[0] == payload and bool(current[1]) == deleted:
                    # The exact plan may be replayed by a later release after a
                    # successful one-time migration.  Matching target content
                    # is already complete even if another writer advanced the
                    # monotonic revision meanwhile.
                    continue
                action = "restore" if restore else "migration"
                raise RuntimeError(
                    f"control-domain {action} revision changed for "
                    f"{item['entity_type']}:{item['entity_id']}"
                )
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument(
        "--environment", default=Path("/run/secrets/control-db.env"), type=Path,
    )
    parser.add_argument("--restore", action="store_true")
    arguments = parser.parse_args(argv)
    count = apply_plan(
        plan_path=arguments.plan,
        environment_path=arguments.environment,
        restore=arguments.restore,
    )
    print(json.dumps({
        "restored" if arguments.restore else "migrated": count,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
