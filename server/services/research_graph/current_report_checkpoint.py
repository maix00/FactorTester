"""Append-only report-item receipts for the current Graph node."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

import settings as Settings
from tools.data.sqlite.db import connect_sqlite

from .branch.schema import ensure_instance_branch_schema


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ITEM_FIELDS = {
    "report_requirement_id", "subject_ref", "content_kind", "item_hash",
}
MAX_ITEMS = 64
MAX_ARTIFACT_REF_BYTES = 512


def append_current_report_checkpoint(
    *, instance_id: str, branch_id: str, owner: str, node_id: str,
    report_submission: Any, journal_artifact_ref: str,
) -> dict[str, Any]:
    """Record validated item identities without advancing or rewriting a trace."""
    fragment_hash, items = _validate_submission(report_submission)
    artifact_ref = _artifact_ref(journal_artifact_ref)
    receipt = {
        "schema_version": 1,
        "instance_id": instance_id,
        "branch_id": branch_id,
        "node_id": node_id,
        "fragment_hash": fragment_hash,
        "report_items": items,
        "journal_artifact_ref": artifact_ref,
    }
    checkpoint_hash = _hash(receipt)
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_instance_branch_schema(conn)
        # Schema backfill may open an implicit transaction on older databases.
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        branch = conn.execute(
            """
            SELECT b.current_node
            FROM research_graph_instances AS i
            JOIN research_graph_branches AS b ON b.instance_id=i.instance_id
            WHERE i.instance_id=? AND b.branch_id=? AND i.owner=?
            """,
            (instance_id, branch_id, owner),
        ).fetchone()
        if branch is None:
            raise KeyError("graph branch not found")
        if str(branch["current_node"]) != node_id:
            raise ValueError("report checkpoint node is no longer current")
        conn.execute(
            """
            INSERT OR IGNORE INTO research_report_item_checkpoints (
                checkpoint_hash, instance_id, branch_id, node_id,
                fragment_hash, report_items_json, journal_artifact_ref,
                actor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                checkpoint_hash, instance_id, branch_id, node_id,
                fragment_hash, _canonical(items).decode("utf-8"),
                artifact_ref, owner, now,
            ),
        )
        row = conn.execute(
            """
            SELECT created_at FROM research_report_item_checkpoints
            WHERE checkpoint_hash=?
            """,
            (checkpoint_hash,),
        ).fetchone()
    return {
        "schema_version": 1,
        "checkpoint_ref": f"report-checkpoint:sha256:{checkpoint_hash}",
        "node_id": node_id,
        "fragment_hash": fragment_hash,
        "item_hashes": [item["item_hash"] for item in items],
        "coverage": [
            {
                "report_requirement_id": item["report_requirement_id"],
                "subject_ref": item["subject_ref"],
                "content_kind": item["content_kind"],
            }
            for item in items
        ],
        "journal_artifact_ref": artifact_ref,
        "created_at": float(row["created_at"]),
    }


def _validate_submission(value: Any) -> tuple[str, list[dict[str, str]]]:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("report_submission schema_version must be 1")
    fragment_hash = str(value.get("fragment_hash") or "")
    if not _SHA256.fullmatch(fragment_hash):
        raise ValueError("report_submission fragment_hash must be sha256")
    raw_items = value.get("items")
    if (
        not isinstance(raw_items, list) or not raw_items
        or len(raw_items) > MAX_ITEMS
    ):
        raise ValueError("report_submission items are invalid")
    items: list[dict[str, str]] = []
    identities: set[tuple[str, str]] = set()
    for raw in raw_items:
        if not isinstance(raw, dict) or set(raw) != _ITEM_FIELDS:
            raise ValueError("report item fields are invalid")
        item = {field: str(raw.get(field) or "") for field in _ITEM_FIELDS}
        if (
            not all(item.values())
            or not _SHA256.fullmatch(item["item_hash"])
            or item["content_kind"] not in {
                "narrative", "markdown", "latex", "list", "table",
            }
        ):
            raise ValueError("report item is invalid")
        identity = (item["report_requirement_id"], item["subject_ref"])
        if identity in identities:
            raise ValueError("report item coverage is duplicated")
        identities.add(identity)
        items.append(item)
    items.sort(key=lambda item: (
        item["report_requirement_id"], item["subject_ref"],
    ))
    projected_hash = _hash(items)
    if projected_hash != fragment_hash:
        raise ValueError("report_submission fragment_hash mismatch")
    return fragment_hash, items


def _artifact_ref(value: Any) -> str:
    ref = str(value or "")
    if (
        not ref.startswith(("artifact:", "journal-artifact:"))
        or len(ref.encode("utf-8")) > MAX_ARTIFACT_REF_BYTES
        or any(char.isspace() for char in ref)
    ):
        raise ValueError("journal_artifact_ref is invalid")
    return ref


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
