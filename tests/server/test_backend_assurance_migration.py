from __future__ import annotations

import hashlib
import sqlite3

import orjson
import pytest

from server.services.backend_assurance_migration import (
    migrate_backend_assurance,
)


def _hash(value) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def _create_legacy_database(path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE research_jobs (
                job_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                owner TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                source_revision TEXT NOT NULL DEFAULT '',
                job_spec_json TEXT NOT NULL,
                job_spec_hash TEXT NOT NULL,
                execution_plan_json TEXT,
                execution_plan_hash TEXT NOT NULL DEFAULT '',
                result_summary_json TEXT,
                error_json TEXT,
                worker_exitcode INTEGER
            );
            CREATE TABLE research_runs (
                run_id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                run_spec_hash TEXT NOT NULL,
                run_spec_json TEXT NOT NULL
            );
            CREATE TABLE research_job_artifacts (
                job_id TEXT NOT NULL,
                name TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                state TEXT NOT NULL
            );
            CREATE TABLE research_backend_assurance_receipts (
                receipt_id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                job_id TEXT NOT NULL UNIQUE,
                attempt_id INTEGER NOT NULL,
                graph_id TEXT NOT NULL,
                graph_version INTEGER NOT NULL,
                graph_hash TEXT NOT NULL,
                instance_id TEXT NOT NULL,
                branch_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                runspec_hash TEXT NOT NULL,
                execution_plan_hash TEXT NOT NULL,
                backend_revision TEXT NOT NULL,
                policy_hash TEXT NOT NULL,
                terminal_status TEXT NOT NULL,
                disposition TEXT NOT NULL,
                checks_bitmap INTEGER NOT NULL,
                anomaly_codes_json TEXT NOT NULL,
                result_summary_hash TEXT NOT NULL,
                artifact_manifest_hash TEXT NOT NULL,
                implementation_execution_id TEXT NOT NULL DEFAULT '',
                verifier_execution_id TEXT NOT NULL DEFAULT '',
                verifier_disposition TEXT NOT NULL DEFAULT '',
                evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                server_attestation TEXT NOT NULL,
                created_at REAL NOT NULL,
                verified_at REAL
            );
            """
        )


def _insert_job(
    path,
    *,
    job_id: str,
    status: str,
    with_receipt: bool,
) -> None:
    run_id = f"run-{job_id}"
    run_spec = {"run_id": run_id}
    job_spec = {"run_id": run_id, "run_spec": run_spec}
    plan = {"runner": "test", "steps": ["compute"]}
    result = {"success": True} if status == "succeeded" else None
    error = {"code": "failed"} if status == "failed" else None
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO research_runs VALUES (?, 'alice', ?, ?)
            """,
            (run_id, _hash(run_spec), orjson.dumps(run_spec).decode()),
        )
        conn.execute(
            """
            INSERT INTO research_jobs VALUES (
                ?, ?, 'alice', ?, 1, 'revision-1', ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                job_id,
                run_id,
                status,
                orjson.dumps(job_spec).decode(),
                _hash(job_spec),
                orjson.dumps(plan).decode(),
                _hash(plan),
                orjson.dumps(result).decode() if result is not None else None,
                orjson.dumps(error).decode() if error is not None else None,
                0 if status == "succeeded" else 1,
            ),
        )
        if not with_receipt:
            return
        conn.execute(
            """
            INSERT INTO research_backend_assurance_receipts VALUES (
                'receipt-1', 'alice', ?, ?, 1, 'graph-1', 1, ?,
                'instance-1', 'branch-1', 'node-1', ?, ?, 'revision-1',
                ?, 'succeeded', 'trusted', 63, '[]', ?, ?, 'impl-old',
                '', '', '[]', 'attestation', 10.0, NULL
            )
            """,
            (
                run_id,
                job_id,
                "a" * 64,
                _hash(run_spec),
                _hash(plan),
                "b" * 64,
                _hash(result),
                _hash([]),
            ),
        )


def test_migrates_legacy_receipt_to_job_assurance_and_drops_old_table(
    tmp_path,
) -> None:
    db_path = tmp_path / "batch2.sqlite"
    _create_legacy_database(db_path)
    _insert_job(
        db_path,
        job_id="trusted",
        status="succeeded",
        with_receipt=True,
    )
    _insert_job(
        db_path,
        job_id="active",
        status="running",
        with_receipt=False,
    )

    report = migrate_backend_assurance(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        trusted = conn.execute(
            "SELECT * FROM research_jobs WHERE job_id='trusted'"
        ).fetchone()
        active = conn.execute(
            "SELECT * FROM research_jobs WHERE job_id='active'"
        ).fetchone()
        old_table = conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type='table'
              AND name='research_backend_assurance_receipts'
            """
        ).fetchone()
    assurance = orjson.loads(trusted["terminal_assurance_json"])
    assert report["legacy_receipts_migrated"] == 1
    assert report["terminal_jobs_backfilled"] == 0
    assert report["maintenance_cases_migrated"] == 0
    assert report["legacy_table_dropped"] == 1
    assert report["schema_tables_before"] == 4
    assert report["schema_tables_after"] == 4
    assert report["sql_reads"] > 0
    assert report["sql_writes"] > 0
    assert report["sql_transactions"] == 1
    assert report["latency_ms"] >= 0
    assert "14f4b7f8" in report["rollback_target"]
    assert assurance["disposition"] == "trusted"
    assert set(assurance) == {
        "policy_hash",
        "backend_revision",
        "run_spec_hash",
        "checks_bitmap",
        "anomaly_codes",
        "result_summary_hash",
        "artifact_manifest_hash",
        "disposition",
    }
    assert trusted["run_spec_hash"] == assurance["run_spec_hash"]
    assert active["run_spec_hash"] == _hash({
        "run_id": "run-active",
    })
    assert active["terminal_assurance_json"] is None
    assert old_table is None


def test_backfills_unreceipted_terminal_once_without_opening_case(
    tmp_path,
) -> None:
    db_path = tmp_path / "batch2.sqlite"
    _create_legacy_database(db_path)
    _insert_job(
        db_path,
        job_id="historical-failure",
        status="failed",
        with_receipt=False,
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE research_jobs
            SET source_revision='', execution_plan_json=NULL,
                execution_plan_hash=''
            WHERE job_id='historical-failure'
            """
        )

    first = migrate_backend_assurance(db_path)
    with sqlite3.connect(db_path) as conn:
        assurance_raw = conn.execute(
            """
            SELECT terminal_assurance_json FROM research_jobs
            WHERE job_id='historical-failure'
            """
        ).fetchone()[0]
        case_count = conn.execute(
            "SELECT COUNT(*) FROM research_maintenance_cases"
        ).fetchone()[0]
    second = migrate_backend_assurance(db_path)
    with sqlite3.connect(db_path) as conn:
        assurance_retry = conn.execute(
            """
            SELECT terminal_assurance_json FROM research_jobs
            WHERE job_id='historical-failure'
            """
        ).fetchone()[0]

    assurance = orjson.loads(assurance_raw)
    assert first["terminal_jobs_backfilled"] == 1
    assert "legacy_evidence_unavailable" in assurance["anomaly_codes"]
    assert set(assurance) == {
        "policy_hash",
        "backend_revision",
        "run_spec_hash",
        "checks_bitmap",
        "anomaly_codes",
        "result_summary_hash",
        "artifact_manifest_hash",
        "disposition",
    }
    assert case_count == 0
    assert second["legacy_receipts_migrated"] == 0
    assert second["terminal_jobs_backfilled"] == 0
    assert second["maintenance_cases_migrated"] == 0
    assert second["legacy_table_dropped"] == 0
    assert second["schema_tables_before"] == second["schema_tables_after"]
    assert second["sql_transactions"] == 1
    assert assurance_retry == assurance_raw


@pytest.mark.parametrize(
    ("verifier_disposition", "expected_status"),
    [
        ("confirmed_reliable", "resolved"),
        ("backend_change_proposed", "blocked"),
        ("research_input_issue", "rejected"),
    ],
)
def test_maps_verified_legacy_anomaly_to_bounded_maintenance_case(
    tmp_path,
    verifier_disposition,
    expected_status,
) -> None:
    db_path = tmp_path / f"{verifier_disposition}.sqlite"
    _create_legacy_database(db_path)
    _insert_job(
        db_path,
        job_id="verified",
        status="succeeded",
        with_receipt=True,
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE research_backend_assurance_receipts
            SET disposition='verifier_required',
                anomaly_codes_json='["worker_exitcode_mismatch"]',
                verifier_execution_id='verifier-old',
                verifier_disposition=?,
                evidence_refs_json='["evidence:legacy-check"]',
                verified_at=20.0
            """,
            (verifier_disposition,),
        )

    report = migrate_backend_assurance(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        case = conn.execute(
            "SELECT * FROM research_maintenance_cases"
        ).fetchone()
        assurance = orjson.loads(conn.execute(
            """
            SELECT terminal_assurance_json FROM research_jobs
            WHERE job_id='verified'
            """
        ).fetchone()[0])
    affected_refs = orjson.loads(case["affected_refs_json"])
    change_refs = orjson.loads(case["change_refs_json"])
    assert report["maintenance_cases_migrated"] == 1
    assert assurance["disposition"] == "maintenance_required"
    assert "legacy" not in assurance
    assert case["status"] == expected_status
    assert "job:verified" in affected_refs
    assert "agent-invocation:impl-old" in affected_refs
    assert "agent-invocation:verifier-old" in affected_refs
    assert f"verifier-disposition:{verifier_disposition}" in change_refs
    assert "evidence:legacy-check" in change_refs


@pytest.mark.parametrize(
    ("column", "conflicting_value"),
    [
        ("execution_plan_hash", "c" * 64),
        ("backend_revision", "revision-conflict"),
        ("result_summary_hash", "d" * 64),
        ("artifact_manifest_hash", "e" * 64),
    ],
)
def test_context_conflict_aborts_the_entire_cutover(
    tmp_path,
    column,
    conflicting_value,
) -> None:
    db_path = tmp_path / f"{column}.sqlite"
    _create_legacy_database(db_path)
    _insert_job(
        db_path,
        job_id="conflict",
        status="succeeded",
        with_receipt=True,
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"""
            UPDATE research_backend_assurance_receipts
            SET {column}=?
            """,
            (conflicting_value,),
        )

    with pytest.raises(ValueError, match="conflict"):
        migrate_backend_assurance(db_path)

    with sqlite3.connect(db_path) as conn:
        job_columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(research_jobs)"
            ).fetchall()
        }
        old_table = conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type='table'
              AND name='research_backend_assurance_receipts'
            """
        ).fetchone()
        case_table = conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type='table'
              AND name='research_maintenance_cases'
            """
        ).fetchone()
    assert "terminal_assurance_json" not in job_columns
    assert "run_spec_hash" not in job_columns
    assert old_table is not None
    assert case_table is None


def test_case_insert_fault_rolls_back_job_and_legacy_drop(
    tmp_path,
) -> None:
    db_path = tmp_path / "fault.sqlite"
    _create_legacy_database(db_path)
    _insert_job(
        db_path,
        job_id="fault",
        status="succeeded",
        with_receipt=True,
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE research_backend_assurance_receipts
            SET disposition='verifier_required',
                anomaly_codes_json='["worker_exitcode_mismatch"]'
            """
        )
        conn.execute(
            """
            CREATE TABLE research_maintenance_cases (
                case_id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                descriptor_hash TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN (
                        'open', 'claimed', 'blocked', 'resolved', 'rejected'
                    )
                ),
                affected_refs_json TEXT NOT NULL,
                change_refs_json TEXT NOT NULL,
                conversation_ref TEXT NOT NULL DEFAULT '',
                claimed_agent_id TEXT NOT NULL DEFAULT '',
                latest_result_ref TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                claimed_at REAL,
                closed_at REAL,
                CHECK (
                    (
                        status IN ('resolved', 'rejected')
                        AND closed_at IS NOT NULL
                    )
                    OR (
                        status NOT IN ('resolved', 'rejected')
                        AND closed_at IS NULL
                    )
                ),
                UNIQUE (owner_user_id, descriptor_hash)
            )
            """
        )
        conn.execute(
            """
            CREATE TRIGGER reject_maintenance_case
            BEFORE INSERT ON research_maintenance_cases
            BEGIN
                SELECT RAISE(ABORT, 'injected case failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="injected case failure"):
        migrate_backend_assurance(db_path)

    with sqlite3.connect(db_path) as conn:
        job_columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(research_jobs)"
            ).fetchall()
        }
        old_table = conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type='table'
              AND name='research_backend_assurance_receipts'
            """
        ).fetchone()
        case_count = conn.execute(
            "SELECT COUNT(*) FROM research_maintenance_cases"
        ).fetchone()[0]
    assert "terminal_assurance_json" not in job_columns
    assert "run_spec_hash" not in job_columns
    assert old_table is not None
    assert case_count == 0
