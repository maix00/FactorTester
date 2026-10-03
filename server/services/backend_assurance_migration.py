"""Atomic cutover from legacy receipts to terminal Job evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
from typing import Any

import orjson

from server.jobs.assurance import (
    BackendAssuranceValidator,
    TerminalAssuranceSummary,
    canonical_hash,
)
from server.services.migration_telemetry import (
    MigrationTelemetry,
    table_count,
)
from server.services.maintenance_cases.schema import create_schema
from server.services.maintenance_cases.store import open_case_in_connection
from tools.data.sqlite.db import connect_sqlite


_LEGACY_TABLE = "research_backend_assurance_receipts"
_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


def migrate_backend_assurance(
    db_path: str | Path,
) -> dict[str, Any]:
    """Convert all legacy backend assurance facts in one SQLite transaction."""
    telemetry = MigrationTelemetry()
    with connect_sqlite(db_path, foreign_keys=True) as conn:
        conn.set_trace_callback(telemetry.trace)
        conn.execute("BEGIN IMMEDIATE")
        return migrate_backend_assurance_in_transaction(
            conn, telemetry=telemetry,
        )


def migrate_backend_assurance_in_transaction(
    conn: sqlite3.Connection,
    *,
    telemetry: MigrationTelemetry | None = None,
) -> dict[str, Any]:
    """Migrate receipts using a caller-owned transaction and connection.

    The one-shot legacy-schema cutover invokes this helper inside its own
    backup-backed transaction. Keeping the conversion in the same transaction
    prevents a failed schema cutover from leaving Job assurance half-migrated.
    """
    if not conn.in_transaction:
        raise RuntimeError("backend assurance migration requires an active transaction")
    telemetry = telemetry or MigrationTelemetry()
    report = {
        "legacy_receipts_migrated": 0,
        "terminal_jobs_backfilled": 0,
        "maintenance_cases_migrated": 0,
        "legacy_table_dropped": 0,
    }
    conn.set_trace_callback(telemetry.trace)
    before_count = table_count(conn)
    _ensure_target_schema(conn)
    _backfill_job_run_spec_hashes(conn)
    legacy_exists = _table_exists(conn, _LEGACY_TABLE)
    receipts = (
        conn.execute(
            f"SELECT * FROM {_LEGACY_TABLE} ORDER BY receipt_id"
        ).fetchall()
        if legacy_exists
        else []
    )
    for receipt in receipts:
        job, run = _validate_legacy_receipt(conn, receipt)
        assurance = _legacy_assurance(receipt)
        _store_assurance(
            conn,
            job=job,
            run_spec_hash=str(run["run_spec_hash"]),
            assurance=assurance,
        )
        if _migrate_maintenance_case(conn, receipt):
            report["maintenance_cases_migrated"] += 1
        report["legacy_receipts_migrated"] += 1

    report["terminal_jobs_backfilled"] = _backfill_terminal_jobs(
        conn,
        excluded_job_ids={
            str(receipt["job_id"]) for receipt in receipts
        },
    )
    if legacy_exists:
        conn.execute(f"DROP TABLE {_LEGACY_TABLE}")
        report["legacy_table_dropped"] = 1
    after_count = table_count(conn)
    return report | {
        "schema_tables_before": before_count,
        "schema_tables_after": after_count,
        "rollback_target": (
            "restore pre-migration database backup and parent commit 14f4b7f8"
        ),
    } | telemetry.report()


def _ensure_target_schema(conn: sqlite3.Connection) -> None:
    columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(research_jobs)").fetchall()
    }
    if not columns:
        raise ValueError("research_jobs table is required")
    if "run_spec_hash" not in columns:
        conn.execute(
            "ALTER TABLE research_jobs "
            "ADD COLUMN run_spec_hash TEXT NOT NULL DEFAULT ''"
        )
    if "terminal_assurance_json" not in columns:
        conn.execute(
            "ALTER TABLE research_jobs ADD COLUMN terminal_assurance_json TEXT"
        )
    create_schema(conn)


def _validate_legacy_receipt(
    conn: sqlite3.Connection,
    receipt: sqlite3.Row,
) -> tuple[sqlite3.Row, sqlite3.Row]:
    job = conn.execute(
        "SELECT * FROM research_jobs WHERE job_id=?",
        (receipt["job_id"],),
    ).fetchone()
    if job is None:
        raise ValueError(
            f"legacy backend assurance orphan job: {receipt['job_id']}"
        )
    comparisons = (
        ("owner", str(job["owner"]), str(receipt["owner_user_id"])),
        ("run", str(job["run_id"]), str(receipt["run_id"])),
        ("attempt", int(job["attempt"]), int(receipt["attempt_id"])),
        ("status", str(job["status"]), str(receipt["terminal_status"])),
        (
            "execution plan",
            str(job["execution_plan_hash"] or ""),
            str(receipt["execution_plan_hash"]),
        ),
        (
            "backend revision",
            str(job["source_revision"] or "unattested"),
            str(receipt["backend_revision"]),
        ),
    )
    for label, actual, legacy in comparisons:
        if actual != legacy:
            raise ValueError(
                f"legacy backend assurance {label} conflict: "
                f"{receipt['receipt_id']}"
            )
    if str(job["status"]) not in _TERMINAL_STATUSES:
        raise ValueError(
            f"legacy backend assurance references nonterminal job: "
            f"{receipt['receipt_id']}"
        )
    run = conn.execute(
        """
        SELECT * FROM research_runs
        WHERE run_id=? AND owner=?
        """,
        (receipt["run_id"], receipt["owner_user_id"]),
    ).fetchone()
    if run is None or str(run["run_spec_hash"]) != str(
        receipt["runspec_hash"]
    ):
        raise ValueError(
            f"legacy backend assurance run context conflict: "
            f"{receipt['receipt_id']}"
        )
    result_summary = _loads(job["result_summary_json"])
    actual_result_summary_hash = (
        canonical_hash(result_summary)
        if result_summary is not None
        else ""
    )
    if actual_result_summary_hash != str(receipt["result_summary_hash"]):
        raise ValueError(
            f"legacy backend assurance result summary conflict: "
            f"{receipt['receipt_id']}"
        )
    artifacts = conn.execute(
        """
        SELECT name, content_hash, size_bytes, state
        FROM research_job_artifacts
        WHERE job_id=? ORDER BY name
        """,
        (receipt["job_id"],),
    ).fetchall()
    artifact_manifest = [
        {
            "name": str(item["name"]),
            "content_hash": str(item["content_hash"]),
            "size_bytes": int(item["size_bytes"]),
            "state": str(item["state"]),
        }
        for item in artifacts
    ]
    if canonical_hash(artifact_manifest) != str(
        receipt["artifact_manifest_hash"]
    ):
        raise ValueError(
            f"legacy backend assurance artifact manifest conflict: "
            f"{receipt['receipt_id']}"
        )
    return job, run


def _legacy_assurance(receipt: sqlite3.Row) -> dict[str, Any]:
    disposition = {
        "trusted": "trusted",
        "not_usable": "not_usable",
        "verifier_required": "maintenance_required",
    }.get(str(receipt["disposition"]))
    if disposition is None:
        raise ValueError(
            f"invalid legacy backend assurance disposition: "
            f"{receipt['disposition']}"
        )
    summary = TerminalAssuranceSummary(
        policy_hash=str(receipt["policy_hash"]),
        backend_revision=str(receipt["backend_revision"]),
        run_spec_hash=str(receipt["runspec_hash"]),
        checks_bitmap=int(receipt["checks_bitmap"]),
        anomaly_codes=tuple(
            str(code)
            for code in (_loads(receipt["anomaly_codes_json"], []) or [])
        ),
        result_summary_hash=str(receipt["result_summary_hash"]),
        artifact_manifest_hash=str(receipt["artifact_manifest_hash"]),
        disposition=disposition,
    )
    return summary.to_dict()


def _migrate_maintenance_case(
    conn: sqlite3.Connection,
    receipt: sqlite3.Row,
) -> bool:
    if str(receipt["disposition"]) != "verifier_required":
        return False
    anomaly_codes = [
        str(code)
        for code in (_loads(receipt["anomaly_codes_json"], []) or [])
    ]
    evidence_refs = [
        str(ref)
        for ref in (_loads(receipt["evidence_refs_json"], []) or [])
    ]
    implementation_id = str(
        receipt["implementation_execution_id"] or ""
    )
    verifier_id = str(receipt["verifier_execution_id"] or "")
    verifier_disposition = str(
        receipt["verifier_disposition"] or ""
    )
    verified_at = receipt["verified_at"]
    if verifier_disposition:
        if verifier_disposition not in {
            "confirmed_reliable",
            "backend_change_proposed",
            "research_input_issue",
        }:
            raise ValueError(
                "invalid legacy Backend Reviewer disposition: "
                f"{verifier_disposition}"
            )
        if not verifier_id or verified_at is None:
            raise ValueError(
                "verified legacy receipt requires verifier invocation "
                f"and timestamp: {receipt['receipt_id']}"
            )
    elif verifier_id or verified_at is not None:
        raise ValueError(
            "unverified legacy receipt has partial verifier evidence: "
            f"{receipt['receipt_id']}"
        )

    affected_refs = [
        f"job:{receipt['job_id']}",
        f"legacy-backend-assurance:{receipt['receipt_id']}",
    ]
    if implementation_id:
        affected_refs.append(f"agent-invocation:{implementation_id}")
    if verifier_id:
        affected_refs.append(f"agent-invocation:{verifier_id}")
    change_refs = [
        f"assurance-policy:{receipt['policy_hash']}",
        *(f"anomaly-code:{code}" for code in anomaly_codes),
        *evidence_refs,
        "server-attestation-sha256:"
        + hashlib.sha256(
            str(receipt["server_attestation"]).encode()
        ).hexdigest(),
    ]
    if verifier_disposition:
        change_refs.append(
            f"verifier-disposition:{verifier_disposition}"
        )
    identity = {
        "source": "legacy-backend-assurance",
        "receipt_id": str(receipt["receipt_id"]),
        "job_id": str(receipt["job_id"]),
    }
    case = open_case_in_connection(
        conn,
        owner_user_id=str(receipt["owner_user_id"]),
        kind="backend_anomaly",
        descriptor_hash=hashlib.sha256(
            orjson.dumps(identity, option=orjson.OPT_SORT_KEYS)
        ).hexdigest(),
        affected_refs=affected_refs,
        change_refs=change_refs,
        conversation_ref=(
            f"legacy-backend-assurance:{receipt['receipt_id']}"
        ),
        now=float(receipt["created_at"]),
    )
    if verifier_disposition:
        assert verified_at is not None
        verified_at_value = float(verified_at)
        target_status = {
            "confirmed_reliable": "resolved",
            "backend_change_proposed": "blocked",
            "research_input_issue": "rejected",
        }[verifier_disposition]
        closed_at = (
            None if target_status == "blocked" else verified_at_value
        )
        conn.execute(
            """
            UPDATE research_maintenance_cases
            SET status=?, claimed_agent_id=?, latest_result_ref=?,
                updated_at=?, claimed_at=?, closed_at=?
            WHERE case_id=?
            """,
            (
                target_status,
                verifier_id,
                f"agent-invocation:{verifier_id}",
                verified_at_value,
                verified_at_value,
                closed_at,
                case["case_id"],
            ),
        )
    return True


def _store_assurance(
    conn: sqlite3.Connection,
    *,
    job: sqlite3.Row,
    run_spec_hash: str,
    assurance: dict[str, Any],
) -> None:
    existing = _loads(job["terminal_assurance_json"])
    if existing is not None:
        if existing != assurance:
            raise ValueError(
                f"terminal assurance conflict: {job['job_id']}"
            )
        return
    conn.execute(
        """
        UPDATE research_jobs
        SET run_spec_hash=?, terminal_assurance_json=?
        WHERE job_id=?
        """,
        (
            run_spec_hash,
            _dumps(assurance),
            job["job_id"],
        ),
    )


def _backfill_job_run_spec_hashes(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT j.job_id, j.run_spec_hash AS job_run_spec_hash,
               r.run_spec_hash AS owned_run_spec_hash
        FROM research_jobs AS j
        JOIN research_runs AS r
          ON r.run_id=j.run_id AND r.owner=j.owner
        ORDER BY j.job_id
        """
    ).fetchall()
    for row in rows:
        existing = str(row["job_run_spec_hash"] or "")
        owned = str(row["owned_run_spec_hash"])
        if existing and existing != owned:
            raise ValueError(
                f"job run spec hash conflict: {row['job_id']}"
            )
        if not existing:
            conn.execute(
                """
                UPDATE research_jobs SET run_spec_hash=?
                WHERE job_id=?
                """,
                (owned, row["job_id"]),
            )


def _backfill_terminal_jobs(
    conn: sqlite3.Connection,
    *,
    excluded_job_ids: set[str],
) -> int:
    validator = BackendAssuranceValidator()
    rows = conn.execute(
        """
        SELECT * FROM research_jobs
        WHERE status IN ('succeeded', 'failed', 'cancelled')
          AND terminal_assurance_json IS NULL
        ORDER BY job_id
        """
    ).fetchall()
    migrated = 0
    for job in rows:
        if str(job["job_id"]) in excluded_job_ids:
            continue
        run = conn.execute(
            """
            SELECT * FROM research_runs WHERE run_id=? AND owner=?
            """,
            (job["run_id"], job["owner"]),
        ).fetchone()
        run_spec_hash = str(run["run_spec_hash"]) if run is not None else ""
        artifacts = conn.execute(
            """
            SELECT name, content_hash, size_bytes, state
            FROM research_job_artifacts
            WHERE job_id=? ORDER BY name
            """,
            (job["job_id"],),
        ).fetchall()
        manifest = [dict(row) for row in artifacts]
        summary = validator.evaluate(
            terminal_status=str(job["status"]),
            backend_revision=str(job["source_revision"] or ""),
            run_spec_hash=run_spec_hash,
            job_spec=dict(_loads(job["job_spec_json"], {}) or {}),
            job_spec_hash=str(job["job_spec_hash"]),
            execution_plan=_loads(job["execution_plan_json"]),
            execution_plan_hash=str(job["execution_plan_hash"] or ""),
            result_summary=_loads(job["result_summary_json"]),
            error=_loads(job["error_json"]),
            worker_exitcode=job["worker_exitcode"],
            artifact_manifest=manifest,
        )
        assurance = summary.to_dict()
        missing_evidence = (
            not str(job["source_revision"] or "")
            or not str(job["execution_plan_hash"] or "")
            or not run_spec_hash
        )
        if missing_evidence:
            assurance["anomaly_codes"] = list(dict.fromkeys([
                *assurance["anomaly_codes"],
                "legacy_evidence_unavailable",
            ]))
        _store_assurance(
            conn,
            job=job,
            run_spec_hash=run_spec_hash,
            assurance=assurance,
        )
        migrated += 1
    return migrated


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        """
        SELECT 1 FROM sqlite_master WHERE type='table' AND name=?
        """,
        (table,),
    ).fetchone() is not None


def _loads(value: str | bytes | None, default: Any = None) -> Any:
    return orjson.loads(value) if value else default


def _dumps(value: Any) -> str:
    return orjson.dumps(value, option=orjson.OPT_SORT_KEYS).decode()
