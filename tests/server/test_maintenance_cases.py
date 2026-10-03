from __future__ import annotations

import sqlite3

import pytest

from server.services.maintenance_cases import (
    MaintenanceCaseStore,
    backend_anomaly_descriptor_hash,
    create_schema,
    migrate_backend_anomaly_rows,
    open_backend_anomaly,
    record_backend_verifier_result,
)
from server.services.maintenance_cases import store as store_module
from server.services.maintenance_cases.queue import load_agent_case_queue
from server.services.agent_flow import resume as resume_module
from tools.data.sqlite.db import connect_sqlite


def test_open_duplicate_is_restart_safe_and_writes_nothing(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "maintenance.sqlite"
    first_store = MaintenanceCaseStore(db_path)
    created = first_store.open_case(
        owner_user_id="alice",
        kind="backend_anomaly",
        descriptor_hash="a" * 64,
        affected_refs=["job:job-1"],
        change_refs=["policy:policy-1"],
        conversation_ref="conversation:case-1",
    )

    statements: list[str] = []
    connect = store_module.connect_maintenance_cases

    def traced_connect(path):
        connection = connect(path)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(
        store_module,
        "connect_maintenance_cases",
        traced_connect,
    )
    restarted_store = MaintenanceCaseStore(db_path)
    statements.clear()
    duplicate = restarted_store.open_case(
        owner_user_id="alice",
        kind="backend_anomaly",
        descriptor_hash="a" * 64,
        affected_refs=["job:job-1"],
        change_refs=["policy:policy-1"],
        conversation_ref="conversation:case-1",
    )

    assert duplicate == created
    assert sum(
        statement.lstrip().upper().startswith(
            ("INSERT", "UPDATE", "DELETE", "REPLACE")
        )
        for statement in statements
    ) == 0


def test_claim_block_resolve_and_reject_are_material_transitions(
    tmp_path,
) -> None:
    store = MaintenanceCaseStore(tmp_path / "maintenance.sqlite")
    case = store.open_case(
        owner_user_id="alice",
        kind="capability_gap",
        descriptor_hash="b" * 64,
        affected_refs=["report:report-1"],
        change_refs=[],
    )
    claimed = store.claim_case(
        owner_user_id="alice",
        case_id=case["case_id"],
        agent_id="server-maintenance-agent",
    )
    assert claimed["status"] == "claimed"
    assert claimed["claimed_agent_id"] == "server-maintenance-agent"
    assert store.claim_case(
        owner_user_id="alice",
        case_id=case["case_id"],
        agent_id="server-maintenance-agent",
    ) == claimed

    blocked = store.block_case(
        owner_user_id="alice",
        case_id=case["case_id"],
        agent_id="server-maintenance-agent",
        result_ref="conversation-result:needs-source-access",
        change_refs=["capability:backend-source-access"],
    )
    assert blocked["status"] == "blocked"
    assert blocked["latest_result_ref"] == (
        "conversation-result:needs-source-access"
    )
    assert store.block_case(
        owner_user_id="alice",
        case_id=case["case_id"],
        agent_id="server-maintenance-agent",
        result_ref="conversation-result:needs-source-access",
        change_refs=["capability:backend-source-access"],
    ) == blocked

    resolved = store.resolve_case(
        owner_user_id="alice",
        case_id=case["case_id"],
        agent_id="server-maintenance-agent",
        result_ref="job:new-attempt",
        change_refs=["commit:fix-1", "test:regression-1"],
    )
    assert resolved["status"] == "resolved"
    assert resolved["closed_at"] is not None
    assert resolved["change_refs"] == [
        "capability:backend-source-access",
        "commit:fix-1",
        "test:regression-1",
    ]
    assert store.resolve_case(
        owner_user_id="alice",
        case_id=case["case_id"],
        agent_id="server-maintenance-agent",
        result_ref="job:new-attempt",
        change_refs=["commit:fix-1", "test:regression-1"],
    ) == resolved

    rejected_case = store.open_case(
        owner_user_id="alice",
        kind="context_optimization",
        descriptor_hash="c" * 64,
        affected_refs=["agent:research-1"],
        change_refs=[],
    )
    store.claim_case(
        owner_user_id="alice",
        case_id=rejected_case["case_id"],
        agent_id="server-maintenance-agent",
    )
    rejected = store.reject_case(
        owner_user_id="alice",
        case_id=rejected_case["case_id"],
        agent_id="server-maintenance-agent",
        result_ref="conversation-result:false-positive",
        change_refs=["diagnostic:context-cost-1"],
    )
    assert rejected["status"] == "rejected"
    assert rejected["closed_at"] is not None


def test_backend_anomaly_adapter_keeps_only_bounded_references(
    tmp_path,
) -> None:
    store = MaintenanceCaseStore(tmp_path / "maintenance.sqlite")
    first_hash = backend_anomaly_descriptor_hash(
        job_id="job-1",
        policy_hash="d" * 64,
        anomaly_codes=["manifest_mismatch", "implausible_result"],
    )
    reordered_hash = backend_anomaly_descriptor_hash(
        job_id="job-1",
        policy_hash="d" * 64,
        anomaly_codes=["implausible_result", "manifest_mismatch"],
    )
    assert reordered_hash == first_hash

    case = open_backend_anomaly(
        store,
        owner_user_id="alice",
        job_id="job-1",
        policy_hash="d" * 64,
        anomaly_codes=["manifest_mismatch", "implausible_result"],
        conversation_ref="conversation:backend-review-1",
    )
    assert case["descriptor_hash"] == first_hash
    assert case["affected_refs"] == ["job:job-1"]
    assert case["change_refs"] == [
        "assurance-policy:" + "d" * 64,
        "anomaly-code:implausible_result",
        "anomaly-code:manifest_mismatch",
    ]
    store.claim_case(
        owner_user_id="alice",
        case_id=case["case_id"],
        agent_id="server-maintenance-agent",
    )
    reviewed = record_backend_verifier_result(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        agent_id="server-maintenance-agent",
        disposition="backend_change_proposed",
        evidence_refs=["job-result:summary", "artifact:manifest"],
        result_ref="agent-invocation:review-1",
    )
    assert reviewed["status"] == "blocked"
    assert reviewed["latest_result_ref"] == "agent-invocation:review-1"
    assert reviewed["change_refs"][-3:] == [
        "verifier-disposition:backend_change_proposed",
        "job-result:summary",
        "artifact:manifest",
    ]
    assert not any(
        key in reviewed
        for key in ("job", "log", "source", "diff", "evidence")
    )


@pytest.mark.parametrize(
    ("disposition", "expected_status"),
    [
        ("confirmed_reliable", "resolved"),
        ("backend_change_proposed", "blocked"),
        ("research_input_issue", "rejected"),
    ],
)
def test_backend_reviewer_disposition_has_one_case_lifecycle_meaning(
    tmp_path,
    disposition,
    expected_status,
) -> None:
    store = MaintenanceCaseStore(tmp_path / f"{disposition}.sqlite")
    case = open_backend_anomaly(
        store,
        owner_user_id="alice",
        job_id="job-1",
        policy_hash="d" * 64,
        anomaly_codes=["manifest_mismatch"],
    )
    store.claim_case(
        owner_user_id="alice",
        case_id=case["case_id"],
        agent_id="server-maintenance-agent",
    )

    reviewed = record_backend_verifier_result(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        agent_id="server-maintenance-agent",
        disposition=disposition,
        evidence_refs=["artifact:review"],
        result_ref="agent-invocation:review-1",
    )

    assert reviewed["status"] == expected_status


def test_schema_and_migration_helpers_keep_one_restart_safe_owner(
    tmp_path,
) -> None:
    db_path = tmp_path / "maintenance.sqlite"
    store = MaintenanceCaseStore(db_path)
    rows = [{
        "owner_user_id": "alice",
        "job_id": "job-1",
        "policy_hash": "e" * 64,
        "anomaly_codes": ["hash_conflict"],
        "conversation_ref": "conversation:1",
    }]
    first = migrate_backend_anomaly_rows(store=store, rows=rows)
    restarted = MaintenanceCaseStore(db_path)
    duplicate = migrate_backend_anomaly_rows(store=restarted, rows=rows)

    assert duplicate == first
    assert restarted.list_cases(
        owner_user_id="alice",
        status="open",
    ) == first
    with connect_sqlite(db_path) as conn:
        tables = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert tables == {"research_maintenance_cases"}


def test_cases_are_owner_scoped_and_schema_creation_is_transactional(
    tmp_path,
) -> None:
    db_path = tmp_path / "maintenance.sqlite"
    store = MaintenanceCaseStore(db_path)
    alice = store.open_case(
        owner_user_id="alice",
        kind="backend_anomaly",
        descriptor_hash="f" * 64,
        affected_refs=["job:1"],
        change_refs=[],
    )
    bob = store.open_case(
        owner_user_id="bob",
        kind="backend_anomaly",
        descriptor_hash="f" * 64,
        affected_refs=["job:1"],
        change_refs=[],
    )
    assert bob["case_id"] != alice["case_id"]
    assert store.list_cases(owner_user_id="alice") == [alice]
    with pytest.raises(KeyError, match="Maintenance Case not found"):
        store.load_case(
            owner_user_id="alice",
            case_id=bob["case_id"],
        )
    with pytest.raises(KeyError, match="Maintenance Case not found"):
        store.claim_case(
            owner_user_id="alice",
            case_id=bob["case_id"],
            agent_id="server-maintenance-agent",
        )

    rollback_db = tmp_path / "rollback.sqlite"
    with connect_sqlite(rollback_db) as conn:
        conn.execute("BEGIN")
        create_schema(conn)
        conn.rollback()
        table = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='research_maintenance_cases'
            """
        ).fetchone()
    assert table is None


def test_agent_queue_returns_first_case_and_true_remaining_count(
    tmp_path,
) -> None:
    db_path = tmp_path / "maintenance.sqlite"
    store = MaintenanceCaseStore(db_path)
    cases = [
        store.open_case(
            owner_user_id="alice",
            kind="backend_anomaly",
            descriptor_hash=f"{index:064x}",
            affected_refs=[f"job:job-{index}"],
            change_refs=[f"diagnostic:diagnostic-{index}"],
        )
        for index in range(20)
    ]

    queue = load_agent_case_queue(
        db_path=db_path,
        owner_user_id="alice",
        agent_id="server-maintenance-agent",
    )

    assert queue == {
        "cases": [{
            "case_id": cases[0]["case_id"],
            "kind": "backend_anomaly",
            "status": "open",
            "descriptor_hash": f"{0:064x}",
            "affected_refs": ["job:job-0"],
            "remaining_affected_ref_count": 0,
            "change_refs": ["diagnostic:diagnostic-0"],
            "remaining_change_ref_count": 0,
            "claimed_agent_id": "",
        }],
        "remaining_case_count": 19,
    }


def test_maintenance_resume_compacts_one_case_long_reference_lists(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "maintenance.sqlite"
    store = MaintenanceCaseStore(db_path)
    affected_refs = [
        f"job:job-{index}:" + "a" * 480
        for index in range(8)
    ]
    change_refs = [
        f"diagnostic:diagnostic-{index}:" + "b" * 470
        for index in range(8)
    ]
    store.open_case(
        owner_user_id="alice",
        kind="backend_anomaly",
        descriptor_hash="f" * 64,
        affected_refs=affected_refs,
        change_refs=change_refs,
    )
    monkeypatch.setattr(
        resume_module.Settings,
        "CACHE_DB_PATH",
        db_path,
    )

    packet = resume_module.build_agent_resume_packet(
        owner="alice",
        agent_id="server-maintenance-agent",
        role="server_maintenance",
    )

    case = packet["maintenance"]["cases"][0]
    assert case["affected_refs"] == affected_refs[:1]
    assert case["remaining_affected_ref_count"] == 7
    assert case["change_refs"] == change_refs[:1]
    assert case["remaining_change_ref_count"] == 7


def test_research_resume_uses_workspace_and_report_branch_authority(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        resume_module,
        "load_workspace_factor_summary",
        lambda *, workspace_id, owner: {
            "workspace_id": workspace_id,
            "owner": owner,
        },
    )

    packet = resume_module.build_agent_resume_packet(
        owner="alice",
        agent_id="research-agent",
        role="research",
        workspace_id="workspace-1",
    )

    assert packet["research"] == {
        "workspace_id": "workspace-1",
        "factor_summary": {
            "workspace_id": "workspace-1",
            "owner": "alice",
        },
        "authoritative_state": ["agent_conversation", "report_branch", "jobs"],
        "next_action": "resume_from_agent_conversation_and_open_report_branch",
    }
    assert "graph" not in str(packet).lower()


def test_research_resume_requires_workspace_id() -> None:
    with pytest.raises(ValueError, match="research resume requires workspace_id"):
        resume_module.build_agent_resume_packet(
            owner="alice",
            agent_id="research-agent",
            role="research",
        )


@pytest.mark.parametrize(
    ("status", "claimed_agent_id", "claimed_at", "closed_at"),
    [
        ("open", "agent-1", None, None),
        ("open", "", 10.0, None),
        ("claimed", "", 10.0, None),
        ("claimed", "agent-1", None, None),
        ("blocked", "", 10.0, None),
        ("blocked", "agent-1", None, None),
        ("resolved", "", 10.0, 20.0),
        ("resolved", "agent-1", None, 20.0),
        ("rejected", "", 10.0, 20.0),
        ("rejected", "agent-1", None, 20.0),
    ],
)
def test_schema_rejects_rows_without_lifecycle_ownership(
    tmp_path,
    status,
    claimed_agent_id,
    claimed_at,
    closed_at,
) -> None:
    db_path = tmp_path / "maintenance.sqlite"
    with connect_sqlite(db_path) as conn:
        create_schema(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO research_maintenance_cases (
                    case_id, owner_user_id, kind, descriptor_hash, status,
                    affected_refs_json, change_refs_json, claimed_agent_id,
                    created_at, updated_at, claimed_at, closed_at
                ) VALUES (?, 'alice', 'backend_anomaly', ?, ?, '[]', '[]',
                          ?, 1.0, 1.0, ?, ?)
                """,
                (
                    f"case-{status}-{claimed_agent_id}-{claimed_at}",
                    (
                        status
                        + claimed_agent_id
                        + str(claimed_at)
                    ).encode().hex().ljust(64, "0")[:64],
                    status,
                    claimed_agent_id,
                    claimed_at,
                    closed_at,
                ),
            )
