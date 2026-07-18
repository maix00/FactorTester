from __future__ import annotations

import hashlib
import sqlite3

import orjson
import pytest

from server.services.graph_governance_migration import (
    migrate_graph_governance,
)
from server.services.maintenance_cases.schema import create_schema
from server.services.maintenance_cases.store import open_case_in_connection
from tools.data.sqlite.db import connect_sqlite


_LEGACY_TABLES = {
    "research_graph_validations",
    "research_graph_proposals",
    "research_graph_reviews",
    "research_graph_audits",
    "human_activation_authorizations",
    "research_capability_approvals",
    "research_graph_server_secrets",
}


def _create_legacy_governance(path) -> None:
    with connect_sqlite(path) as conn:
        conn.executescript(
            """
            CREATE TABLE research_graph_versions (
                graph_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                PRIMARY KEY (graph_id, version)
            );
            CREATE TABLE research_graph_validations (
                validation_id TEXT PRIMARY KEY,
                graph_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                actor TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE research_graph_proposals (
                proposal_id TEXT PRIMARY KEY,
                graph_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                proposer TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                change_diff_json TEXT NOT NULL,
                evidence_refs_json TEXT NOT NULL,
                token_estimate INTEGER NOT NULL,
                created_at REAL NOT NULL,
                owner_user_id TEXT NOT NULL,
                proposer_execution_id TEXT NOT NULL
            );
            CREATE TABLE research_graph_reviews (
                review_id TEXT PRIMARY KEY,
                proposal_id TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                disposition TEXT NOT NULL,
                scope_drift INTEGER NOT NULL,
                semantic_uncertainty INTEGER NOT NULL,
                evidence_refs_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                owner_user_id TEXT NOT NULL,
                reviewer_execution_id TEXT NOT NULL
            );
            CREATE TABLE research_graph_audits (
                audit_id TEXT PRIMARY KEY,
                graph_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                actor TEXT NOT NULL,
                disposition TEXT NOT NULL,
                grill_evidence_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE human_activation_authorizations (
                authorization_id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL,
                graph_id TEXT NOT NULL,
                graph_version INTEGER NOT NULL,
                graph_hash TEXT NOT NULL,
                proposal_id TEXT NOT NULL,
                diff_hash TEXT NOT NULL,
                nonce_hash TEXT NOT NULL UNIQUE,
                authorized_by TEXT NOT NULL,
                human_attestation TEXT NOT NULL,
                expires_at REAL NOT NULL,
                consumed_at REAL,
                created_at REAL NOT NULL
            );
            CREATE TABLE research_capability_approvals (
                approval_id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                descriptor_hash TEXT NOT NULL,
                product_group TEXT NOT NULL,
                actor TEXT NOT NULL,
                evidence_refs_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE research_capability_receipts (
                receipt_id TEXT PRIMARY KEY,
                resolver_attestation TEXT NOT NULL
            );
            CREATE TABLE research_graph_server_secrets (
                secret_id INTEGER PRIMARY KEY,
                secret BLOB NOT NULL
            );
            """
        )


def _seed_ready_gate(path, *, consumed: bool = True) -> None:
    graph_hash = hashlib.sha256(b"graph-v2").hexdigest()
    change_diff = {"old_hash": "old", "new_hash": graph_hash}
    diff_hash = hashlib.sha256(
        orjson.dumps(change_diff, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
    validation = {
        "replay_passed": True,
        "shadow_passed": True,
        "capability_resolution_complete": True,
        "unaffected_jobs_preserved": True,
        "token_efficiency_passed": True,
    }
    with connect_sqlite(path) as conn:
        conn.execute(
            "INSERT INTO research_graph_versions VALUES (?, ?, ?)",
            ("factor-research", 2, graph_hash),
        )
        conn.execute(
            "INSERT INTO research_graph_proposals VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "proposal-1",
                "factor-research",
                2,
                "proposer-invocation",
                "L4",
                orjson.dumps(change_diff).decode(),
                orjson.dumps(["artifact:proposal-evidence"]).decode(),
                100,
                1.0,
                "alice",
                "proposer-invocation",
            ),
        )
        conn.execute(
            "INSERT INTO research_graph_reviews VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "review-1",
                "proposal-1",
                "reviewer-invocation",
                "approved",
                0,
                0,
                orjson.dumps(["artifact:review-evidence"]).decode(),
                2.0,
                "alice",
                "reviewer-invocation",
            ),
        )
        conn.execute(
            "INSERT INTO research_graph_validations VALUES (?, ?, ?, ?, ?, ?)",
            (
                "validation-1",
                "factor-research",
                2,
                "validation-agent",
                orjson.dumps(validation).decode(),
                3.0,
            ),
        )
        conn.execute(
            "INSERT INTO research_graph_audits VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "audit-1",
                "factor-research",
                2,
                "human-auditor",
                "approved",
                orjson.dumps([{"question": "full body must not migrate"}]).decode(),
                4.0,
            ),
        )
        conn.execute(
            "INSERT INTO human_activation_authorizations VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "authorization-1",
                "alice",
                "factor-research",
                2,
                graph_hash,
                "proposal-1",
                diff_hash,
                "n" * 64,
                "alice",
                "legacy-hmac-body",
                1000.0,
                5.0 if consumed else None,
                4.5,
            ),
        )
        conn.execute(
            "INSERT INTO research_capability_approvals VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "capability-approval-1",
                "alice",
                "research.test",
                "d" * 64,
                "equities",
                "alice",
                "[]",
                2.0,
            ),
        )
        conn.execute(
            "INSERT INTO research_capability_receipts VALUES (?, ?)",
            ("capability-receipt-1", "opaque-legacy-attestation"),
        )
        conn.execute(
            "INSERT INTO research_graph_server_secrets VALUES (?, ?)",
            (1, b"same-owner-secret"),
        )


def _tables(path) -> set[str]:
    with sqlite3.connect(path) as conn:
        return {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }


def test_consumed_governance_projects_to_one_resolved_gate_and_drops_legacy(
    tmp_path,
) -> None:
    path = tmp_path / "graph.sqlite"
    _create_legacy_governance(path)
    _seed_ready_gate(path, consumed=True)

    report = migrate_graph_governance(db_path=path)

    assert report["approval_gate_cases_migrated"] == 1
    assert report["consumed_authorizations_migrated"] == 1
    assert report["unconsumed_authorization_ids"] == []
    assert report["capability_approvals_dropped"] == 1
    assert report["capability_receipts_preserved"] == 1
    assert report["legacy_tables_dropped"] == 7
    assert report["schema_tables_before"] == 9
    assert report["schema_tables_after"] == 3
    assert report["sql_reads"] > 0
    assert report["sql_writes"] > 0
    assert report["sql_transactions"] == 1
    assert report["latency_ms"] >= 0
    assert "595845dd" in report["rollback_target"]
    assert _tables(path).isdisjoint(_LEGACY_TABLES)
    assert "research_capability_receipts" in _tables(path)
    with connect_sqlite(path) as conn:
        case = conn.execute(
            "SELECT * FROM research_maintenance_cases"
        ).fetchone()
        receipt = conn.execute(
            "SELECT resolver_attestation FROM research_capability_receipts"
        ).fetchone()
    assert case["kind"] == "approval_gate"
    assert case["status"] == "resolved"
    affected = orjson.loads(case["affected_refs_json"])
    changes = orjson.loads(case["change_refs_json"])
    assert len(affected) <= 16
    assert len(changes) <= 16
    assert any(ref.startswith("gate-approval:legacy-authorization:") for ref in changes)
    assert all("full body must not migrate" not in ref for ref in changes)
    assert case["conversation_ref"] == ""
    assert receipt["resolver_attestation"] == "opaque-legacy-attestation"


def test_unconsumed_authorization_is_reported_but_never_becomes_approval(
    tmp_path,
) -> None:
    path = tmp_path / "graph.sqlite"
    _create_legacy_governance(path)
    _seed_ready_gate(path, consumed=False)

    report = migrate_graph_governance(db_path=path)
    repeated = migrate_graph_governance(db_path=path)

    assert report["unconsumed_authorization_ids"] == ["authorization-1"]
    assert report["consumed_authorizations_migrated"] == 0
    assert repeated["approval_gate_cases_migrated"] == 0
    assert repeated["consumed_authorizations_migrated"] == 0
    assert repeated["unconsumed_authorization_ids"] == []
    assert repeated["capability_approvals_dropped"] == 0
    assert repeated["capability_receipts_preserved"] == 1
    assert repeated["legacy_tables_dropped"] == 0
    assert repeated["schema_tables_before"] == repeated["schema_tables_after"]
    assert repeated["sql_transactions"] == 0
    with connect_sqlite(path) as conn:
        cases = conn.execute(
            "SELECT * FROM research_maintenance_cases"
        ).fetchall()
    assert len(cases) == 1
    assert cases[0]["status"] == "open"
    changes = orjson.loads(cases[0]["change_refs_json"])
    assert "legacy-authorization-unconsumed:authorization-1" in changes
    assert not any(ref.startswith("gate-approval:") for ref in changes)
    assert cases[0]["conversation_ref"] == ""


@pytest.mark.parametrize(
    "failure_point",
    ["after_case_projection", "after_legacy_drop"],
)
def test_injected_failure_rolls_back_cases_and_legacy_deletion(
    tmp_path,
    failure_point,
) -> None:
    path = tmp_path / f"{failure_point}.sqlite"
    _create_legacy_governance(path)
    _seed_ready_gate(path, consumed=True)

    def inject(point: str) -> None:
        if point == failure_point:
            raise RuntimeError("injected migration failure")

    with pytest.raises(RuntimeError, match="injected migration failure"):
        migrate_graph_governance(
            db_path=path,
            failure_injector=inject,
        )

    assert _LEGACY_TABLES <= _tables(path)
    with connect_sqlite(path) as conn:
        maintenance_exists = conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='research_maintenance_cases'
            """
        ).fetchone()
        if maintenance_exists is not None:
            assert conn.execute(
                "SELECT COUNT(*) FROM research_maintenance_cases"
            ).fetchone()[0] == 0


def test_authorization_target_conflict_rolls_back_everything(tmp_path) -> None:
    path = tmp_path / "conflict.sqlite"
    _create_legacy_governance(path)
    _seed_ready_gate(path, consumed=True)
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            UPDATE human_activation_authorizations
            SET graph_hash=?
            WHERE authorization_id='authorization-1'
            """,
            ("f" * 64,),
        )

    with pytest.raises(ValueError, match="authorization target conflict"):
        migrate_graph_governance(db_path=path)

    assert _LEGACY_TABLES <= _tables(path)
    assert "research_maintenance_cases" not in _tables(path)


def test_existing_case_collision_rolls_back_legacy_deletion(tmp_path) -> None:
    path = tmp_path / "case-conflict.sqlite"
    _create_legacy_governance(path)
    _seed_ready_gate(path, consumed=True)
    with connect_sqlite(path) as conn:
        graph_hash = conn.execute(
            """
            SELECT content_hash FROM research_graph_versions
            WHERE graph_id='factor-research' AND version=2
            """
        ).fetchone()["content_hash"]
        descriptor_hash = hashlib.sha256(orjson.dumps(
            {
                "migration": "legacy-graph-governance@1",
                "owner_user_id": "alice",
                "proposal_id": "proposal-1",
                "action": "activate_graph_version",
                "target_hash": graph_hash,
            },
            option=orjson.OPT_SORT_KEYS,
        )).hexdigest()
        create_schema(conn)
        open_case_in_connection(
            conn,
            owner_user_id="alice",
            kind="approval_gate",
            descriptor_hash=descriptor_hash,
            affected_refs=["conflicting:case"],
            change_refs=[],
        )

    with pytest.raises(ValueError, match="migration collision"):
        migrate_graph_governance(db_path=path)

    assert _LEGACY_TABLES <= _tables(path)
    with connect_sqlite(path) as conn:
        case = conn.execute(
            "SELECT * FROM research_maintenance_cases"
        ).fetchone()
    assert orjson.loads(case["affected_refs_json"]) == ["conflicting:case"]
