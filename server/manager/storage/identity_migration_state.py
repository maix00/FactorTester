"""Migrate Manager-local task projections after an account rename."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from tools.data.sqlite.db import connect_sqlite


_OWNER_KEYS = frozenset({
    "owner",
    "owner_username",
    "principal",
    "username",
})


def _rewrite_owner_fields(value: Any, old_username: str, new_username: str) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                new_username
                if key in _OWNER_KEYS and str(item or "") == old_username
                else _rewrite_owner_fields(item, old_username, new_username)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _rewrite_owner_fields(item, old_username, new_username)
            for item in value
        ]
    return value


def _rewrite_json(
    raw: object,
    old_username: str,
    new_username: str,
) -> tuple[str, bool]:
    try:
        value = json.loads(str(raw or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return str(raw or ""), False
    rewritten = _rewrite_owner_fields(value, old_username, new_username)
    encoded = json.dumps(
        rewritten,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return encoded, encoded != str(raw or "")


def _numeric(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _migrate_job_rows(
    db: sqlite3.Connection,
    *,
    table: str,
    principal_column: str,
    payload_column: str,
    key_columns: tuple[str, ...],
    old_username: str,
    new_username: str,
) -> int:
    """Rename projection rows and coalesce a stale old/new duplicate."""
    columns = {
        str(row[1])
        for row in db.execute(f'PRAGMA table_info("{table}")').fetchall()
    }
    required = {principal_column, payload_column, *key_columns}
    if not required.issubset(columns):
        return 0
    select_columns = [*key_columns, payload_column]
    if "updated_order" in columns:
        select_columns.append("updated_order")
    elif "updated_at" in columns:
        select_columns.append("updated_at")
    rows = db.execute(
        f'''SELECT {", ".join(f'"{item}"' for item in select_columns)}
            FROM "{table}" WHERE "{principal_column}"=?''',
        (old_username,),
    ).fetchall()
    changed = 0
    for row in rows:
        key_values = [row[column] for column in key_columns]
        where_key = " AND ".join(
            f'"{column}"=?' for column in key_columns
        )
        target = db.execute(
            f'''SELECT {", ".join(f'"{item}"' for item in select_columns)}
                FROM "{table}" WHERE "{principal_column}"=?
                AND {where_key}''',
            (new_username, *key_values),
        ).fetchone()
        rewritten, payload_changed = _rewrite_json(
            row[payload_column], old_username, new_username,
        )
        if target is not None:
            old_order = _numeric(
                row["updated_order"] if "updated_order" in columns
                else row["updated_at"] if "updated_at" in columns else 0
            )
            new_order = _numeric(
                target["updated_order"] if "updated_order" in columns
                else target["updated_at"] if "updated_at" in columns else 0
            )
            if old_order > new_order:
                db.execute(
                    f'''UPDATE "{table}" SET "{payload_column}"=?
                        WHERE "{principal_column}"=? AND {where_key}''',
                    (rewritten, new_username, *key_values),
                )
            db.execute(
                f'''DELETE FROM "{table}" WHERE "{principal_column}"=?
                    AND {where_key}''',
                (old_username, *key_values),
            )
            changed += 1
            continue
        assignments = [f'"{principal_column}"=?']
        values: list[object] = [new_username]
        if payload_changed:
            assignments.append(f'"{payload_column}"=?')
            values.append(rewritten)
        db.execute(
            f'''UPDATE "{table}" SET {", ".join(assignments)}
                WHERE "{principal_column}"=? AND {where_key}''',
            (*values, old_username, *key_values),
        )
        changed += 1
    return changed


def _migrate_event_payloads(
    db: sqlite3.Connection,
    *,
    old_username: str,
    new_username: str,
) -> int:
    try:
        rows = db.execute(
            "SELECT event_id, audience, payload FROM control_events"
        ).fetchall()
    except sqlite3.OperationalError:
        return 0
    changed = 0
    for row in rows:
        audience = str(row[1] or "[]")
        try:
            audience_value = json.loads(audience)
        except (TypeError, ValueError, json.JSONDecodeError):
            audience_value = []
        if isinstance(audience_value, list):
            audience_value = [
                new_username if str(item or "") == old_username else item
                for item in audience_value
            ]
        new_audience = json.dumps(
            audience_value, ensure_ascii=False, separators=(",", ":"),
        )
        new_payload, payload_changed = _rewrite_json(
            row[2], old_username, new_username,
        )
        if new_audience == audience and not payload_changed:
            continue
        db.execute(
            "UPDATE control_events SET audience=?, payload=? WHERE event_id=?",
            (new_audience, new_payload, str(row[0])),
        )
        changed += 1
    return changed


def migrate_manager_state_identity(
    state_root: str | Path,
    *,
    old_username: str,
    new_username: str,
) -> dict[str, int]:
    """Rename account ownership in Manager-local projections.

    This does not touch source artifacts or research evidence.  It only
    updates the local task summary/index metadata that is safe to rebuild and
    is otherwise capable of retaining a pre-migration principal forever.
    Missing state databases are ignored so the one-time account migration can
    be run against Managers with different enabled features.
    """
    root = Path(state_root).expanduser().resolve()
    counts = {"jobs": 0, "local_runs": 0, "routing": 0, "events": 0}
    job_index = root / "job-index.sqlite"
    if job_index.is_file():
        with connect_sqlite(job_index) as db:
            db.execute("BEGIN IMMEDIATE")
            counts["jobs"] = _migrate_job_rows(
                db,
                table="jobs",
                principal_column="principal",
                payload_column="payload",
                key_columns=("port", "job_id"),
                old_username=old_username,
                new_username=new_username,
            )
            try:
                counts["routing"] = db.execute(
                    "UPDATE run_routing SET principal=? WHERE principal=?",
                    (new_username, old_username),
                ).rowcount
            except sqlite3.OperationalError:
                counts["routing"] = 0
            counts["events"] = _migrate_event_payloads(
                db, old_username=old_username, new_username=new_username,
            )
            db.commit()
    local_runs = root / "local-run-projection.sqlite"
    if local_runs.is_file():
        with connect_sqlite(local_runs) as db:
            db.execute("BEGIN IMMEDIATE")
            counts["local_runs"] = _migrate_job_rows(
                db,
                table="local_runs",
                principal_column="principal",
                payload_column="payload_json",
                key_columns=("local_job_id",),
                old_username=old_username,
                new_username=new_username,
            )
            db.commit()
    return counts

