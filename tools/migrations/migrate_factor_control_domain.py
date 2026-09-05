"""Apply or restore one explicit formula-identity control-domain plan."""

from __future__ import annotations

import argparse
import json
import hashlib
import os
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
    plan = json.loads(plan_path.read_text())
    if plan.get("plan_hash"):
        from tools.migrations.repair_factor_catalog_sync import verify_plan
        verify_plan(plan)
    receipt = []
    with psycopg.connect(_database_url(environment_path)) as connection:
        # Match normal writers: allocate revisions in commit order, including
        # restores. Rewinding a row revision would hide it behind pull cursors.
        connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("factortester:account-domain:revision",))
        connection.execute(
            "SELECT setval('control_account_domain_revision_seq', GREATEST("
            "(SELECT last_value FROM control_account_domain_revision_seq), "
            "(SELECT coalesce(max(revision), 1) FROM control_account_domain_entities)), true)", ()
        )
        seen = set()
        for item in sorted(rows, key=lambda value: (value["principal"], value["entity_type"], value["entity_id"])):
            key = (item["principal"], item["entity_type"], item["entity_id"])
            if key in seen:
                raise ValueError("duplicate control-domain plan identity")
            seen.add(key)
            connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("factortester:account-domain:" + ":".join(key),))
            current = connection.execute(
                "SELECT payload, deleted, revision FROM control_account_domain_entities "
                "WHERE principal=%s AND entity_type=%s AND entity_id=%s FOR UPDATE", key,
            ).fetchone()
            target = item["old_payload"] if restore else item["new_payload"]
            deleted = bool(item["old_deleted"] if restore else item["new_deleted"])
            target = target or {}
            if current and current[0] == target and bool(current[1]) == deleted:
                revision = int(current[2])
            else:
                expected_payload = item["new_payload"] if restore else item["old_payload"]
                expected_deleted = bool(item["new_deleted"] if restore else item["old_deleted"])
                matches = (current is None and expected_payload is None) or (
                    current is not None and current[0] == expected_payload and bool(current[1]) == expected_deleted
                    and (restore or int(current[2]) == int(item["expected_revision"]))
                )
                if not matches:
                    raise RuntimeError(f"control-domain plan precondition changed for {key[1]}:{key[2]}")
                revision = int(connection.execute("SELECT nextval('control_account_domain_revision_seq')", ()).fetchone()[0])
                connection.execute(
                    "INSERT INTO control_account_domain_entities(principal, entity_type, entity_id, payload, deleted, revision, origin_manager_id) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT(principal, entity_type, entity_id) DO UPDATE SET payload=excluded.payload, "
                    "deleted=excluded.deleted, revision=excluded.revision, updated_at=now()",
                    (*key, Jsonb(target), deleted, revision, str(item.get("origin_manager_id") or "catalog-recovery")),
                )
            receipt.append({"principal": key[0], "entity_type": key[1], "entity_id": key[2], "revision": revision})
    receipt_path = plan_path.with_suffix(plan_path.suffix + (".restore-receipt.json" if restore else ".receipt.json"))
    encoded = json.dumps({"plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(), "rows": receipt}, sort_keys=True)
    fd = os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(encoded)
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
