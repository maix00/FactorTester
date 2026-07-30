"""Atomic application and verification of a shadow ownership manifest."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.data.sqlite.db import connect_sqlite

from .plan import plan_shadow_work_package_migration
from .projection import INSTANCE_TABLES, canonical_hash


def apply_shadow_work_package_migration(
    *,
    db_path: str | Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
    supplied_hash = str(plan.get("plan_hash") or "")
    canonical = {key: value for key, value in plan.items() if key != "plan_hash"}
    if supplied_hash != canonical_hash(canonical):
        raise ValueError("shadow migration plan hash is invalid")
    fresh = plan_shadow_work_package_migration(
        db_path=db_path,
        owner=str(plan["owner"]),
        source_work_package_id=str(plan["source_work_package_id"]),
        retained_instance_id=str(plan["retained"]["instance_id"]),
        retired_instance_ids=[
            str(item["instance_id"]) for item in plan["retired"]
        ],
    )
    if fresh != plan:
        raise ValueError("shadow migration database projection changed")
    retired_ids = [str(item["instance_id"]) for item in plan["retired"]]
    with connect_sqlite(db_path, foreign_keys=True) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = conn.execute(
                """
                UPDATE research_graph_instances SET work_package_id=?
                WHERE instance_id=? AND owner=? AND mode='shadow'
                """,
                (
                    plan["source_work_package_id"],
                    plan["retained"]["instance_id"],
                    plan["owner"],
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("retained shadow binding changed")
            deleted = _delete_retired(conn, plan=plan, ids=retired_ids)
            _verify_applied(conn, plan=plan, retired_ids=retired_ids)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    if integrity != "ok":
        raise RuntimeError("SQLite integrity_check failed after migration")
    return {
        "status": "applied",
        "plan_hash": supplied_hash,
        "retained_instance_id": plan["retained"]["instance_id"],
        "work_package_id": plan["source_work_package_id"],
        "retired_instance_ids": retired_ids,
        "deleted_rows": deleted,
        "integrity_check": integrity,
    }


def _delete_retired(
    conn, *, plan: dict[str, Any], ids: list[str],
) -> dict[str, int]:
    deleted: dict[str, int] = {}
    for table in (*INSTANCE_TABLES, "research_graph_branches",
                  "research_graph_instances"):
        deleted[table] = sum(
            int(conn.execute(
                f"DELETE FROM {table} WHERE instance_id=?", (item,),
            ).rowcount)
            for item in ids
        )
    work_packages = [
        str(plan["retained"]["old_work_package_id"]),
        *[str(item["old_work_package_id"]) for item in plan["retired"]],
    ]
    deleted["research_work_packages"] = sum(
        int(conn.execute(
            """
            DELETE FROM research_work_packages
            WHERE owner=? AND work_package_id=?
            """,
            (plan["owner"], item),
        ).rowcount)
        for item in work_packages
    )
    return deleted


def _verify_applied(
    conn, *, plan: dict[str, Any], retired_ids: list[str],
) -> None:
    retained = conn.execute(
        """
        SELECT work_package_id FROM research_graph_instances
        WHERE instance_id=? AND owner=?
        """,
        (plan["retained"]["instance_id"], plan["owner"]),
    ).fetchone()
    if retained is None or str(retained["work_package_id"]) != str(
        plan["source_work_package_id"]
    ):
        raise ValueError("retained shadow was not rebound")
    for item in retired_ids:
        if conn.execute(
            "SELECT 1 FROM research_graph_instances WHERE instance_id=?",
            (item,),
        ).fetchone():
            raise ValueError("retired shadow instance still exists")
    old_ids = [
        str(plan["retained"]["old_work_package_id"]),
        *[str(item["old_work_package_id"]) for item in plan["retired"]],
    ]
    placeholders = ",".join("?" for _ in old_ids)
    if conn.execute(
        f"""
        SELECT 1 FROM research_work_packages
        WHERE owner=? AND work_package_id IN ({placeholders})
        """,
        (plan["owner"], *old_ids),
    ).fetchone():
        raise ValueError("obsolete shadow Work Package still exists")
