"""One-way schema upgrade for report-tree receipt references."""

from __future__ import annotations

import sqlite3


_TABLE = "research_report_item_checkpoints"
_INDEX = "idx_report_item_checkpoints_branch_node"


def migrate_report_checkpoint_receipts(conn: sqlite3.Connection) -> None:
    """Replace the retired Journal reference column on existing instances."""
    columns = {
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({_TABLE})").fetchall()
    }
    if "report_artifact_ref" in columns:
        return
    if "journal_artifact_ref" not in columns:
        raise ValueError("report receipt schema is invalid")
    conn.execute(
        """
        CREATE TABLE research_report_item_checkpoints_next (
            checkpoint_hash TEXT PRIMARY KEY,
            instance_id TEXT NOT NULL,
            branch_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            fragment_hash TEXT NOT NULL,
            report_items_json TEXT NOT NULL,
            report_artifact_ref TEXT NOT NULL,
            actor TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO research_report_item_checkpoints_next (
            checkpoint_hash, instance_id, branch_id, node_id, fragment_hash,
            report_items_json, report_artifact_ref, actor, created_at
        )
        SELECT checkpoint_hash, instance_id, branch_id, node_id, fragment_hash,
               report_items_json, journal_artifact_ref, actor, created_at
        FROM research_report_item_checkpoints
        """
    )
    conn.execute(f"DROP TABLE {_TABLE}")
    conn.execute(
        "ALTER TABLE research_report_item_checkpoints_next "
        f"RENAME TO {_TABLE}"
    )
    conn.execute(
        f"CREATE INDEX {_INDEX} ON {_TABLE} "
        "(instance_id, branch_id, node_id, created_at)"
    )
