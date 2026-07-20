"""Atomic offline migration from legacy Graph governance into approval Gates."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
from pathlib import Path
import sqlite3
from typing import Any

import orjson

from server.services.migration_telemetry import MigrationTelemetry
from server.services.maintenance_cases.schema import create_schema
from server.services.maintenance_cases.store import open_case_in_connection
from tools.data.sqlite.db import connect_sqlite


_LEGACY_TABLES = (
    "research_graph_validations",
    "research_graph_proposals",
    "research_graph_reviews",
    "research_graph_audits",
    "human_activation_authorizations",
    "research_capability_approvals",
    "research_graph_server_secrets",
)
_VALIDATION_GATES = (
    "replay_passed",
    "shadow_passed",
    "capability_resolution_complete",
    "unaffected_jobs_preserved",
    "token_efficiency_passed",
)
_MIGRATION_AGENT = "legacy-governance-migration"


def migrate_graph_governance(
    *,
    db_path: str | Path,
    failure_injector: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Convert bounded Gate references and delete all legacy owners atomically."""
    telemetry = MigrationTelemetry()
    with connect_sqlite(Path(db_path)) as conn:
        conn.set_trace_callback(telemetry.trace)
        tables = _table_names(conn)
        before_count = len(tables)
        present = set(_LEGACY_TABLES).intersection(tables)
        capability_receipts = _count_rows(
            conn,
            "research_capability_receipts",
            tables=tables,
        )
        if not present:
            return _empty_report(capability_receipts) | _release_report(
                telemetry=telemetry,
                before_count=before_count,
                after_count=before_count,
            )
        missing = set(_LEGACY_TABLES) - present
        if missing:
            raise ValueError(
                "legacy Graph governance schema is incomplete: "
                + ", ".join(sorted(missing))
            )
        conn.execute("BEGIN IMMEDIATE")
        try:
            projections = _prepare_projections(conn)
            capability_approvals = _count_rows(
                conn,
                "research_capability_approvals",
                tables=tables,
            )
            create_schema(conn)
            migrated = [
                _write_projection(conn, projection)
                for projection in projections
            ]
            if failure_injector is not None:
                failure_injector("after_case_projection")
            for table in _LEGACY_TABLES:
                conn.execute(f"DROP TABLE {table}")
            if failure_injector is not None:
                failure_injector("after_legacy_drop")
            after_count = len(_table_names(conn))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {
        "approval_gate_cases_migrated": len(migrated),
        "consumed_authorizations_migrated": sum(
            int(projection["consumed_authorization_id"] != "")
            for projection in projections
        ),
        "unconsumed_authorization_ids": sorted(
            authorization_id
            for projection in projections
            for authorization_id in projection["unconsumed_authorization_ids"]
        ),
        "capability_approvals_dropped": capability_approvals,
        "capability_receipts_preserved": capability_receipts,
        "legacy_tables_dropped": len(_LEGACY_TABLES),
    } | _release_report(
        telemetry=telemetry,
        before_count=before_count,
        after_count=after_count,
    )


def _prepare_projections(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    proposals = conn.execute(
        """
        SELECT * FROM research_graph_proposals
        ORDER BY created_at, proposal_id
        """
    ).fetchall()
    proposal_ids = {str(row["proposal_id"]) for row in proposals}
    orphan_reviews = conn.execute(
        """
        SELECT proposal_id FROM research_graph_reviews
        WHERE proposal_id NOT IN (
            SELECT proposal_id FROM research_graph_proposals
        )
        LIMIT 1
        """
    ).fetchone()
    if orphan_reviews is not None:
        raise ValueError(
            "orphan legacy Graph review: " + str(orphan_reviews["proposal_id"])
        )
    governed_versions = {
        (str(row["graph_id"]), int(row["version"]))
        for table in ("research_graph_validations", "research_graph_audits")
        for row in conn.execute(
            f"SELECT DISTINCT graph_id, version FROM {table}"
        ).fetchall()
    }
    proposed_versions = {
        (str(row["graph_id"]), int(row["version"]))
        for row in proposals
    }
    orphan_versions = governed_versions - proposed_versions
    if orphan_versions:
        graph_id, version = sorted(orphan_versions)[0]
        raise ValueError(
            f"legacy governance facts lack a proposal: {graph_id}:{version}"
        )
    orphan_authorization = conn.execute(
        """
        SELECT proposal_id FROM human_activation_authorizations
        WHERE proposal_id NOT IN (
            SELECT proposal_id FROM research_graph_proposals
        )
        LIMIT 1
        """
    ).fetchone()
    if orphan_authorization is not None:
        raise ValueError(
            "orphan legacy authorization: "
            + str(orphan_authorization["proposal_id"])
        )
    if not proposal_ids and governed_versions:
        raise ValueError("legacy governance facts cannot be projected")
    return [_prepare_projection(conn, proposal) for proposal in proposals]


def _prepare_projection(
    conn: sqlite3.Connection,
    proposal: sqlite3.Row,
) -> dict[str, Any]:
    proposal_id = str(proposal["proposal_id"])
    graph_id = str(proposal["graph_id"])
    version = int(proposal["version"])
    owner = str(proposal["owner_user_id"] or "")
    if not owner:
        owners = {
            str(row["owner_user_id"])
            for row in conn.execute(
                """
                SELECT owner_user_id FROM human_activation_authorizations
                WHERE proposal_id=?
                """,
                (proposal_id,),
            ).fetchall()
            if str(row["owner_user_id"])
        }
        if len(owners) == 1:
            owner = owners.pop()
    if not owner:
        raise ValueError(f"legacy proposal owner is missing: {proposal_id}")
    graph = conn.execute(
        """
        SELECT content_hash FROM research_graph_versions
        WHERE graph_id=? AND version=?
        """,
        (graph_id, version),
    ).fetchone()
    if graph is None:
        raise ValueError(f"legacy proposal graph version is missing: {proposal_id}")
    target_hash = str(graph["content_hash"])
    _require_sha256("graph content hash", target_hash)
    proposer = str(
        proposal["proposer_execution_id"] or proposal["proposer"] or ""
    )
    if not proposer:
        raise ValueError(f"legacy proposal identity is missing: {proposal_id}")

    reviews = conn.execute(
        """
        SELECT * FROM research_graph_reviews
        WHERE proposal_id=? ORDER BY created_at, review_id
        """,
        (proposal_id,),
    ).fetchall()
    if len(reviews) > 3:
        raise ValueError(f"legacy proposal has more than three reviews: {proposal_id}")
    review_refs = [_review_ref(row, owner=owner) for row in reviews]
    validation_ref, validation_passed = _latest_validation_ref(
        conn,
        graph_id=graph_id,
        version=version,
    )
    audit_ref, audit_approved = _latest_audit_ref(
        conn,
        graph_id=graph_id,
        version=version,
    )
    authorizations = conn.execute(
        """
        SELECT * FROM human_activation_authorizations
        WHERE proposal_id=? ORDER BY created_at, authorization_id
        """,
        (proposal_id,),
    ).fetchall()
    consumed = [row for row in authorizations if row["consumed_at"] is not None]
    if len(consumed) > 1:
        raise ValueError(
            f"legacy proposal has multiple consumed authorizations: {proposal_id}"
        )
    change_diff = orjson.loads(proposal["change_diff_json"])
    diff_hash = _json_hash(change_diff)
    for authorization in authorizations:
        if (
            str(authorization["owner_user_id"]) != owner
            or str(authorization["graph_id"]) != graph_id
            or int(authorization["graph_version"]) != version
            or str(authorization["graph_hash"]) != target_hash
            or str(authorization["diff_hash"]) != diff_hash
        ):
            raise ValueError(
                f"legacy authorization target conflict: "
                f"{authorization['authorization_id']}"
            )
    consumed_id = (
        str(consumed[0]["authorization_id"]) if consumed else ""
    )
    if consumed_id and not (
        _review_ready(reviews) and validation_passed and audit_approved
    ):
        raise ValueError(
            f"consumed authorization lacks ready Gate facts: {consumed_id}"
        )
    unconsumed_ids = [
        str(row["authorization_id"])
        for row in authorizations
        if row["consumed_at"] is None
    ]
    proposal_ref = f"legacy-proposal:{proposal_id}"
    action = "activate_graph_version"
    affected_refs = [
        proposal_ref,
        f"gate-proposer:{proposer}",
        f"gate-action:{action}",
        f"gate-target-hash:{target_hash}",
    ]
    change_refs = [
        f"legacy-proposal-diff:{diff_hash}",
        *review_refs,
        *([validation_ref] if validation_ref else []),
        *([audit_ref] if audit_ref else []),
        *(
            f"legacy-authorization-unconsumed:{authorization_id}"
            for authorization_id in unconsumed_ids
        ),
    ]
    if consumed_id:
        change_refs.extend([
            f"gate-approval:legacy-authorization:{consumed_id}",
            f"gate-effect:legacy-activation:{graph_id}:{version}",
        ])
    identity = {
        "migration": "legacy-graph-governance@1",
        "owner_user_id": owner,
        "proposal_id": proposal_id,
        "action": action,
        "target_hash": target_hash,
    }
    return {
        "owner_user_id": owner,
        "descriptor_hash": _json_hash(identity),
        "affected_refs": affected_refs,
        "change_refs": change_refs,
        "created_at": float(proposal["created_at"]),
        "consumed_at": (
            float(consumed[0]["consumed_at"]) if consumed else None
        ),
        "consumed_authorization_id": consumed_id,
        "unconsumed_authorization_ids": unconsumed_ids,
    }


def _write_projection(
    conn: sqlite3.Connection,
    projection: dict[str, Any],
) -> dict[str, Any]:
    existing = conn.execute(
        """
        SELECT * FROM research_maintenance_cases
        WHERE owner_user_id=? AND descriptor_hash=?
        """,
        (
            projection["owner_user_id"],
            projection["descriptor_hash"],
        ),
    ).fetchone()
    if existing is not None:
        expected_status = (
            "resolved"
            if projection["consumed_at"] is not None
            else "open"
        )
        if (
            str(existing["kind"]) != "approval_gate"
            or str(existing["status"]) != expected_status
            or str(existing["conversation_ref"]) != ""
            or orjson.loads(existing["affected_refs_json"])
            != projection["affected_refs"]
            or orjson.loads(existing["change_refs_json"])
            != projection["change_refs"]
        ):
            raise ValueError("Maintenance Case migration collision")
        return dict(existing)
    case = open_case_in_connection(
        conn,
        owner_user_id=projection["owner_user_id"],
        kind="approval_gate",
        descriptor_hash=projection["descriptor_hash"],
        affected_refs=projection["affected_refs"],
        change_refs=projection["change_refs"],
        conversation_ref="",
        now=projection["created_at"],
    )
    if projection["consumed_at"] is None:
        return case
    effect_ref = next(
        ref
        for ref in projection["change_refs"]
        if ref.startswith("gate-effect:")
    )
    row = conn.execute(
        """
        UPDATE research_maintenance_cases
        SET status='resolved', claimed_agent_id=?, latest_result_ref=?,
            claimed_at=?, updated_at=?, closed_at=?
        WHERE case_id=? AND status='open'
        RETURNING *
        """,
        (
            _MIGRATION_AGENT,
            effect_ref,
            projection["created_at"],
            projection["consumed_at"],
            projection["consumed_at"],
            case["case_id"],
        ),
    ).fetchone()
    return dict(row)


def _review_ref(row: sqlite3.Row, *, owner: str) -> str:
    if str(row["owner_user_id"] or "") not in {"", owner}:
        raise ValueError(f"legacy review owner conflict: {row['review_id']}")
    reviewer = str(
        row["reviewer_execution_id"] or row["reviewer"] or ""
    )
    if not reviewer:
        raise ValueError(f"legacy review identity is missing: {row['review_id']}")
    disposition = str(row["disposition"])
    if bool(row["scope_drift"]) or bool(row["semantic_uncertainty"]):
        disposition = "disagreed"
    if disposition not in {"approved", "disagreed", "rejected"}:
        raise ValueError(f"invalid legacy review disposition: {row['review_id']}")
    reviewer_hash = hashlib.sha256(reviewer.encode()).hexdigest()
    return f"gate-review:{reviewer_hash}:{disposition}"


def _latest_validation_ref(
    conn: sqlite3.Connection,
    *,
    graph_id: str,
    version: int,
) -> tuple[str, bool]:
    row = conn.execute(
        """
        SELECT * FROM research_graph_validations
        WHERE graph_id=? AND version=?
        ORDER BY created_at DESC, validation_id DESC LIMIT 1
        """,
        (graph_id, version),
    ).fetchone()
    if row is None:
        return "", False
    evidence = orjson.loads(row["evidence_json"])
    passed = isinstance(evidence, dict) and all(
        evidence.get(gate) is True for gate in _VALIDATION_GATES
    )
    return (
        f"gate-validation:{_json_hash(evidence)}:"
        f"{'passed' if passed else 'failed'}",
        passed,
    )


def _latest_audit_ref(
    conn: sqlite3.Connection,
    *,
    graph_id: str,
    version: int,
) -> tuple[str, bool]:
    row = conn.execute(
        """
        SELECT * FROM research_graph_audits
        WHERE graph_id=? AND version=?
        ORDER BY created_at DESC, audit_id DESC LIMIT 1
        """,
        (graph_id, version),
    ).fetchone()
    if row is None:
        return "", False
    disposition = str(row["disposition"])
    if disposition not in {"approved", "rejected", "quarantined", "frozen"}:
        raise ValueError(f"invalid legacy audit disposition: {row['audit_id']}")
    return (
        f"gate-grill:legacy-audit:{row['audit_id']}:{disposition}",
        disposition == "approved",
    )


def _review_ready(reviews: list[sqlite3.Row]) -> bool:
    dispositions = [
        "disagreed"
        if bool(row["scope_drift"]) or bool(row["semantic_uncertainty"])
        else str(row["disposition"])
        for row in reviews
    ]
    disagreement = any(value != "approved" for value in dispositions)
    required = 3 if disagreement else 1
    return (
        len(dispositions) >= required
        and dispositions.count("approved") > len(dispositions) // 2
    )


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _count_rows(
    conn: sqlite3.Connection,
    table: str,
    *,
    tables: set[str],
) -> int:
    if table not in tables:
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def _require_sha256(field: str, value: str) -> None:
    if (
        len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be sha256")


def _empty_report(capability_receipts: int) -> dict[str, Any]:
    return {
        "approval_gate_cases_migrated": 0,
        "consumed_authorizations_migrated": 0,
        "unconsumed_authorization_ids": [],
        "capability_approvals_dropped": 0,
        "capability_receipts_preserved": capability_receipts,
        "legacy_tables_dropped": 0,
    }


def _release_report(
    *,
    telemetry: MigrationTelemetry,
    before_count: int,
    after_count: int,
) -> dict[str, Any]:
    report = telemetry.report()
    return {
        "schema_tables_before": before_count,
        "schema_tables_after": after_count,
        "rollback_target": (
            "restore pre-migration database backup and parent commit 595845dd"
        ),
    } | report
