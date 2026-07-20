"""Persistence invariants for Research Cycle transitions."""

from __future__ import annotations

import hashlib

import orjson
import pytest

import settings as Settings
from server.services import agent_flow
from server.services.research_graph.branch import transition
from server.services.research_graph.research_cycle.adjudication import (
    validate_adjudication_decision,
    validate_adjudication_proposal,
)
from tests.server.data_contract_fixtures import initialize
from tools.data.sqlite.db import connect_sqlite


def _prepare(path, monkeypatch) -> dict:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    monkeypatch.setenv("AGENT_FLOW_DB_PATH", str(path.with_suffix(".agents")))
    agent_flow.clear_store_cache()
    initialize(path)
    checkpoint = _checkpoint()
    graph = {
        "graph_id": "factor-research",
        "version": 1,
        "lifecycle": "active",
        "content_hash": "c" * 64,
        "entry_node": "factor_semantics",
        "nodes": [{
            "node_id": "factor_semantics",
            "kind": "research",
            "required_capabilities": [],
        }],
        "edges": [{
            "edge_id": "verify-semantics",
            "from_node": "factor_semantics",
            "to_node": "factor_semantics",
            "guard": {
                "identity_hash_valid": True,
                "causal_timing_valid": True,
                "research_cycle_delta_applied": True,
            },
            "required_evidence": [],
        }],
    }
    evidence = orjson.dumps({
        "research_cycle_checkpoint": checkpoint,
        "evidence_refs": [],
    }).decode()
    with connect_sqlite(path) as conn:
        conn.execute(
            "UPDATE research_graph_versions SET graph_json=?",
            (orjson.dumps(graph).decode(),),
        )
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_node='factor_semantics',
                current_trial_plan_hash=?,
                latest_trace_id='trace-bootstrap'
            WHERE branch_id='branch-1'
            """,
            (checkpoint["trial_plan_hash"],),
        )
        conn.execute(
            """
            UPDATE research_graph_trace SET evidence_json=?
            WHERE trace_id='trace-bootstrap'
            """,
            (evidence,),
        )
    return checkpoint


def _checkpoint() -> dict:
    from server.services.research_graph.research_cycle.replay import (
        validate_research_cycle_checkpoint,
    )

    return validate_research_cycle_checkpoint({
        "schema_version": 1,
        "contract_hash": "1" * 64,
        "trial_plan_hash": "2" * 64,
        "methodology_hash": "3" * 64,
        "claims": [{
            "schema_version": 1,
            "claim_id": "claim-1",
            "contract_hash": "1" * 64,
            "claim_ref": "factor-claim:1",
            "claim_type": "bounded_predictive_relationship",
            "scope": {"sample": "confirmation"},
            "evidence_state": "unknown",
            "evidence_refs": [],
        }],
        "obligations": [{
            "schema_version": 1,
            "obligation_id": "obligation-1",
            "contract_hash": "1" * 64,
            "claim_ids": ["claim-1"],
            "obligation_kind": "preregistered_test",
            "epistemic_question": "Does the preregistered test reject?",
            "scope": {"sample": "confirmation"},
            "discharge_criterion": {"rule_ref": "trial-plan:1#reject"},
            "status": "open",
            "materiality": "decision_blocking",
            "methodology_hash": "3" * 64,
            "created_event_ref": "trace:bootstrap",
        }],
        "pending_adjudications": [],
        "pending_closure": None,
    })


def _adjudication_events() -> tuple[list[dict], str]:
    invocation = agent_flow.get_store().reserve_invocation(
        owner_user_id="alice",
        agent_id="research:atomicity",
        actor_role="researcher",
        authority_scope="local_research",
        purpose="apply preregistered result",
        runtime_id="pytest",
        model_id="test-model",
        max_input_tokens=10,
        max_output_tokens=10,
        agent_principal_hash=hashlib.sha256(b"principal").hexdigest(),
        lineage_hash=hashlib.sha256(b"lineage").hexdigest(),
    )
    agent_flow.get_store().settle_invocation(
        owner_user_id="alice",
        invocation_id=invocation["invocation_id"],
        input_tokens=1,
        output_tokens=1,
        provider_request_id="atomicity-test",
    )
    proposal = validate_adjudication_proposal({
        "schema_version": 1,
        "proposal_id": "proposal-1",
        "proposer_invocation_id": invocation["invocation_id"],
        "contract_hash": "1" * 64,
        "trial_plan_hash": "2" * 64,
        "methodology_hash": "3" * 64,
        "evidence_refs": ["evidence:failed-test"],
        "claim_evidence_delta": [{
            "claim_id": "claim-1",
            "from_state": "unknown",
            "to_state": "contradicted",
            "evidence_grade": "preregistered",
            "scope": {"sample": "confirmation"},
        }],
        "obligation_delta": [{
            "obligation_id": "obligation-1",
            "from_state": "open",
            "to_state": "discharged",
            "criterion_ref": "trial-plan:1#reject",
        }],
        "decision_warrant": {
            "finding_refs": ["evidence:failed-test"],
            "rule_refs": ["trial-plan:1#reject"],
            "inference_type": "preregistered",
            "preregistered": True,
            "alternative_refs": [],
            "limitation_refs": [],
            "reentry_predicates": [],
            "required_authority": "preregistered_rule",
        },
    })
    decision = validate_adjudication_decision({
        "schema_version": 1,
        "decision_id": "decision-1",
        "proposal_hash": proposal["proposal_hash"],
        "disposition": "accepted",
        "authority_class": "preregistered_rule",
        "authority_ref": "trial-plan:1#reject",
        "methodology_hash": "3" * 64,
    })
    return [
        {"event_type": "adjudication_proposed", "proposal": proposal},
        {"event_type": "adjudication_decided", "decision": decision},
    ], invocation["invocation_id"]


def _evidence(
    checkpoint: dict,
    events: list[dict],
    invocation_id: str,
    *,
    timing_valid: bool = True,
) -> dict:
    return {
        "identity_hash_valid": True,
        "causal_timing_valid": timing_valid,
        "agent_invocation_ids": [invocation_id],
        "research_cycle": {
            "schema_version": 1,
            "parent_trace_ref": "trace:trace-bootstrap",
            "expected_base_hash": checkpoint["projection_hash"],
            "events": events,
        },
    }


def _state(path) -> tuple[int, str, dict]:
    with connect_sqlite(path) as conn:
        row = conn.execute(
            """
            SELECT latest_trace_id,
                   (SELECT COUNT(*) FROM research_graph_trace
                    WHERE branch_id='branch-1') AS trace_count
            FROM research_graph_branches WHERE branch_id='branch-1'
            """
        ).fetchone()
        trace = conn.execute(
            "SELECT evidence_json FROM research_graph_trace WHERE trace_id=?",
            (row["latest_trace_id"],),
        ).fetchone()
    checkpoint = orjson.loads(
        trace["evidence_json"]
    )["research_cycle_checkpoint"]
    return row["trace_count"], row["latest_trace_id"], checkpoint


class _FailTraceInsert:
    def __init__(self, conn) -> None:
        self.conn = conn

    def __enter__(self):
        self.conn.__enter__()
        return self

    def __exit__(self, *args):
        return self.conn.__exit__(*args)

    def execute(self, sql, parameters=()):
        if sql.lstrip().upper().startswith("INSERT INTO RESEARCH_GRAPH_TRACE"):
            raise RuntimeError("injected trace insert failure")
        return self.conn.execute(sql, parameters)


def test_trace_insert_failure_rolls_back_paired_delta_and_branch_update(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "atomic.sqlite"
    checkpoint = _prepare(path, monkeypatch)
    events, invocation_id = _adjudication_events()
    before = _state(path)
    real_connect = transition.connect_sqlite
    monkeypatch.setattr(
        transition,
        "connect_sqlite",
        lambda *args, **kwargs: _FailTraceInsert(
            real_connect(*args, **kwargs)
        ),
    )

    with pytest.raises(RuntimeError, match="injected trace insert failure"):
        transition.advance_graph_branch(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            edge_id="verify-semantics",
            evidence=_evidence(checkpoint, events, invocation_id),
        )

    assert _state(path) == before


def test_failed_identity_timing_guard_leaves_trace_and_checkpoint_unchanged(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "guard.sqlite"
    checkpoint = _prepare(path, monkeypatch)
    events, invocation_id = _adjudication_events()
    before = _state(path)

    with pytest.raises(ValueError, match="causal_timing_valid"):
        transition.advance_graph_branch(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            edge_id="verify-semantics",
            evidence=_evidence(
                checkpoint,
                events,
                invocation_id,
                timing_valid=False,
            ),
        )

    assert _state(path) == before
