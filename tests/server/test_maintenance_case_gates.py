from __future__ import annotations

import sqlite3

import pytest

from server.services.maintenance_cases import (
    MaintenanceCaseStore,
    approve_gate,
    consume_gate_effect,
    consume_case_effect_in_connection,
    open_gate,
    record_gate_grill,
    record_gate_review,
    record_gate_validation,
)
from server.services.maintenance_cases import store as store_module
from tools.data.sqlite.db import connect_sqlite


def _write_count(statements: list[str]) -> int:
    return sum(
        statement.lstrip().upper().startswith(
            ("INSERT", "UPDATE", "DELETE", "REPLACE")
        )
        for statement in statements
    )


def test_gate_uses_one_case_row_and_consumes_exact_effect_once(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "maintenance.sqlite"
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
    store = MaintenanceCaseStore(db_path)
    statements.clear()

    case = open_gate(
        store,
        owner_user_id="alice",
        coordinator_agent_id="agent:gate-coordinator",
        proposal_ref="proposal:factor-change-1",
        proposer_identity_ref="identity:proposer-1",
        action="activate-factor-change",
        target_hash="a" * 64,
        conversation_ref="auth-conversation:thread-1",
        proposal_evidence_refs=["artifact:proposal-1"],
    )
    assert _write_count(statements) == 2
    assert case["status"] == "claimed"
    assert case["affected_refs"] == [
        "proposal:factor-change-1",
        "gate-proposer:identity:proposer-1",
        "gate-action:activate-factor-change",
        "gate-target-hash:" + "a" * 64,
        "artifact:proposal-1",
    ]
    assert case["conversation_ref"] == "auth-conversation:thread-1"

    statements.clear()
    reviewed = record_gate_review(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        coordinator_agent_id="agent:gate-coordinator",
        reviewer_identity_ref="identity:reviewer-1",
        disposition="approved",
        evidence_refs=["artifact:review-1"],
    )
    assert _write_count(statements) == 1
    assert reviewed["case_id"] == case["case_id"]
    assert reviewed["status"] == "claimed"

    statements.clear()
    validated = record_gate_validation(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        coordinator_agent_id="agent:gate-coordinator",
        validation_summary_hash="d" * 64,
    )
    assert _write_count(statements) == 1
    assert (
        "gate-validation:" + "d" * 64 + ":passed"
        in validated["change_refs"]
    )
    assert validated["status"] == "claimed"
    with pytest.raises(ValueError, match="validation"):
        record_gate_review(
            store,
            owner_user_id="alice",
            case_id=case["case_id"],
            coordinator_agent_id="agent:gate-coordinator",
            reviewer_identity_ref="identity:reviewer-1",
            disposition="approved",
            evidence_refs=["artifact:late-review-evidence"],
        )

    statements.clear()
    grilled = record_gate_grill(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        coordinator_agent_id="agent:gate-coordinator",
        disposition="approved",
        grill_ref="conversation-result:grill-1",
    )
    assert _write_count(statements) == 1
    assert "gate-grill:conversation-result:grill-1:approved" in (
        grilled["change_refs"]
    )
    with pytest.raises(ValueError, match="progress is frozen"):
        record_gate_validation(
            store,
            owner_user_id="alice",
            case_id=case["case_id"],
            coordinator_agent_id="agent:gate-coordinator",
            validation_summary_hash="d" * 64,
        )
    assert store.load_case(
        owner_user_id="alice",
        case_id=case["case_id"],
    )["status"] == "blocked"

    statements.clear()
    approved = approve_gate(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        coordinator_agent_id="agent:gate-coordinator",
        action="activate-factor-change",
        target_hash="a" * 64,
        approval_ref="approval:exact-action-hash-1",
    )
    assert _write_count(statements) == 1
    assert approved["case_id"] == case["case_id"]
    assert approved["status"] == "blocked"
    assert approve_gate(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        coordinator_agent_id="agent:gate-coordinator",
        action="activate-factor-change",
        target_hash="a" * 64,
        approval_ref="approval:exact-action-hash-1",
    ) == approved

    with pytest.raises(sqlite3.OperationalError):
        with connect_sqlite(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            consume_case_effect_in_connection(
                conn,
                owner_user_id="alice",
                case_id=case["case_id"],
                agent_id="agent:gate-coordinator",
                effect_ref="effect:rolled-back",
                change_refs=["gate-effect:effect:rolled-back"],
            )
            conn.execute(
                "INSERT INTO graph_write_that_fails VALUES (1)"
            )
    assert store.load_case(
        owner_user_id="alice",
        case_id=case["case_id"],
    )["status"] == "blocked"

    statements.clear()
    consumed = consume_gate_effect(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        coordinator_agent_id="agent:gate-coordinator",
        action="activate-factor-change",
        target_hash="a" * 64,
        effect_ref="effect:activation-1",
    )
    assert _write_count(statements) == 1
    assert consumed["status"] == "resolved"
    assert consumed["latest_result_ref"] == "effect:activation-1"
    assert "gate-effect:effect:activation-1" in consumed["change_refs"]
    assert not any(
        key in consumed
        for key in ("proposal", "review", "grill", "diff", "log", "source")
    )

    statements.clear()
    with pytest.raises(ValueError, match="already consumed"):
        consume_gate_effect(
            store,
            owner_user_id="alice",
            case_id=case["case_id"],
            coordinator_agent_id="agent:gate-coordinator",
            action="activate-factor-change",
            target_hash="a" * 64,
            effect_ref="effect:activation-1",
        )
    assert _write_count(statements) == 0

    with connect_sqlite(db_path) as conn:
        tables = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        count = conn.execute(
            "SELECT COUNT(*) FROM research_maintenance_cases"
        ).fetchone()[0]
    assert tables == {"research_maintenance_cases"}
    assert count == 1


def test_gate_disagreement_requires_three_independent_reviewers(
    tmp_path,
) -> None:
    store = MaintenanceCaseStore(tmp_path / "maintenance.sqlite")
    with pytest.raises(ValueError, match="authenticated conversation"):
        open_gate(
            store,
            owner_user_id="alice",
            coordinator_agent_id="agent:gate-coordinator",
            proposal_ref="proposal:factor-change-2",
            proposer_identity_ref="identity:proposer-1",
            action="activate-factor-change",
            target_hash="b" * 64,
            conversation_ref="conversation:unauthenticated",
        )

    case = open_gate(
        store,
        owner_user_id="alice",
        coordinator_agent_id="agent:gate-coordinator",
        proposal_ref="proposal:factor-change-2",
        proposer_identity_ref="identity:proposer-1",
        action="activate-factor-change",
        target_hash="b" * 64,
        conversation_ref="auth-conversation:thread-2",
    )
    with pytest.raises(ValueError, match="independent from proposer"):
        record_gate_review(
            store,
            owner_user_id="alice",
            case_id=case["case_id"],
            coordinator_agent_id="agent:gate-coordinator",
            reviewer_identity_ref="identity:proposer-1",
            disposition="approved",
            evidence_refs=[],
        )
    with pytest.raises(ValueError, match="reserved"):
        record_gate_review(
            store,
            owner_user_id="alice",
            case_id=case["case_id"],
            coordinator_agent_id="agent:gate-coordinator",
            reviewer_identity_ref="identity:reviewer-spoof",
            disposition="approved",
            evidence_refs=[
                "gate-validation:" + "9" * 64 + ":passed",
            ],
        )

    first = record_gate_review(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        coordinator_agent_id="agent:gate-coordinator",
        reviewer_identity_ref="identity:reviewer-1",
        disposition="disagreed",
        evidence_refs=["artifact:counterexample-1"],
    )
    assert record_gate_review(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        coordinator_agent_id="agent:gate-coordinator",
        reviewer_identity_ref="identity:reviewer-1",
        disposition="disagreed",
        evidence_refs=["artifact:counterexample-1"],
    ) == first
    with pytest.raises(ValueError, match="cannot change"):
        record_gate_review(
            store,
            owner_user_id="alice",
            case_id=case["case_id"],
            coordinator_agent_id="agent:gate-coordinator",
            reviewer_identity_ref="identity:reviewer-1",
            disposition="approved",
            evidence_refs=[],
        )

    record_gate_review(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        coordinator_agent_id="agent:gate-coordinator",
        reviewer_identity_ref="identity:reviewer-2",
        disposition="approved",
        evidence_refs=["artifact:review-2"],
    )
    with pytest.raises(ValueError, match="approval majority"):
        approve_gate(
            store,
            owner_user_id="alice",
            case_id=case["case_id"],
            coordinator_agent_id="agent:gate-coordinator",
            action="activate-factor-change",
            target_hash="b" * 64,
            approval_ref="approval:too-early",
        )

    record_gate_review(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        coordinator_agent_id="agent:gate-coordinator",
        reviewer_identity_ref="identity:reviewer-3",
        disposition="approved",
        evidence_refs=["artifact:review-3"],
    )
    with pytest.raises(ValueError, match="does not match"):
        approve_gate(
            store,
            owner_user_id="alice",
            case_id=case["case_id"],
            coordinator_agent_id="agent:gate-coordinator",
            action="activate-factor-change",
            target_hash="c" * 64,
            approval_ref="approval:wrong-hash",
        )
    with pytest.raises(ValueError, match="validation"):
        approve_gate(
            store,
            owner_user_id="alice",
            case_id=case["case_id"],
            coordinator_agent_id="agent:gate-coordinator",
            action="activate-factor-change",
            target_hash="b" * 64,
            approval_ref="approval:without-validation",
        )
    record_gate_validation(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        coordinator_agent_id="agent:gate-coordinator",
        validation_summary_hash="e" * 64,
    )
    record_gate_grill(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        coordinator_agent_id="agent:gate-coordinator",
        disposition="approved",
        grill_ref="conversation-result:grill-2",
    )
    approved = approve_gate(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        coordinator_agent_id="agent:gate-coordinator",
        action="activate-factor-change",
        target_hash="b" * 64,
        approval_ref="approval:exact-action-hash-2",
    )

    assert approved["status"] == "blocked"
    assert sum(
        ref.startswith("gate-reviewer:")
        for ref in approved["change_refs"]
    ) == 3
    assert "gate-grill:conversation-result:grill-2:approved" in (
        approved["change_refs"]
    )
    assert "gate-approval:approval:exact-action-hash-2" in (
        approved["change_refs"]
    )


def test_nonapproved_grill_fails_closed(tmp_path) -> None:
    store = MaintenanceCaseStore(tmp_path / "maintenance.sqlite")
    case = open_gate(
        store,
        owner_user_id="alice",
        coordinator_agent_id="agent:gate-coordinator",
        proposal_ref="proposal:factor-change-3",
        proposer_identity_ref="identity:proposer-1",
        action="activate-factor-change",
        target_hash="f" * 64,
        conversation_ref="auth-conversation:thread-3",
    )
    record_gate_review(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        coordinator_agent_id="agent:gate-coordinator",
        reviewer_identity_ref="identity:reviewer-1",
        disposition="approved",
        evidence_refs=[],
    )
    record_gate_validation(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        coordinator_agent_id="agent:gate-coordinator",
        validation_summary_hash="1" * 64,
    )

    grilled = record_gate_grill(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        coordinator_agent_id="agent:gate-coordinator",
        disposition="frozen",
        grill_ref="conversation-result:grill-frozen",
    )

    assert grilled["status"] == "rejected"
    assert "gate-grill:conversation-result:grill-frozen:frozen" in (
        grilled["change_refs"]
    )
    with pytest.raises(ValueError, match="approved grill"):
        approve_gate(
            store,
            owner_user_id="alice",
            case_id=case["case_id"],
            coordinator_agent_id="agent:gate-coordinator",
            action="activate-factor-change",
            target_hash="f" * 64,
            approval_ref="approval:must-not-exist",
        )
