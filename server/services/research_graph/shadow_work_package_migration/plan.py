"""Deterministic dry-run manifest for split shadow Work Packages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.data.sqlite.db import connect_sqlite

from .projection import (
    INSTANCE_TABLES,
    canonical_hash,
    instance_projection,
    validate_shadow,
)


def plan_shadow_work_package_migration(
    *,
    db_path: str | Path,
    owner: str,
    source_work_package_id: str,
    retained_instance_id: str,
    retired_instance_ids: list[str],
) -> dict[str, Any]:
    if not retired_instance_ids:
        raise ValueError("at least one retired shadow instance is required")
    ids = [retained_instance_id, *retired_instance_ids]
    if len(ids) != len(set(ids)):
        raise ValueError("shadow migration instance ids must be unique")
    with connect_sqlite(db_path, foreign_keys=True) as conn:
        rows = [instance_projection(conn, item) for item in ids]
        source = conn.execute(
            """
            SELECT * FROM research_work_packages
            WHERE owner=? AND work_package_id=?
            """,
            (owner, source_work_package_id),
        ).fetchone()
        if source is None:
            raise ValueError("source Work Package was not found")
        for row in rows:
            validate_shadow(
                row,
                owner=owner,
                source_work_package_id=source_work_package_id,
                workspace_id=str(source["workspace_id"]),
            )
        retained, retired = rows[0], rows[1:]
        if int(retained["trace_count"]) <= 1:
            raise ValueError("retained shadow has no unique continuation progress")
        for row in retired:
            if int(row["trace_count"]) != 1:
                raise ValueError(
                    "retired shadow contains unique continuation progress"
                )
            if int(row["graph_object_count"]) != 0:
                raise ValueError("retired shadow owns Graph objects")
            if int(row["adjudication_count"]) != 0:
                raise ValueError("retired shadow owns adjudication receipts")
        projection = {
            "schema_version": 1,
            "owner": owner,
            "source_work_package_id": source_work_package_id,
            "workspace_id": str(source["workspace_id"]),
            "retained": retained,
            "retired": retired,
            "expected_statement_count": (
                len(retired) * (len(INSTANCE_TABLES) + 3) + 2
            ),
        }
    return {**projection, "plan_hash": canonical_hash(projection)}
