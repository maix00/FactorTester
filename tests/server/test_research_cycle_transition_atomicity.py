"""Persistence invariants for Research Cycle transitions."""

from __future__ import annotations

import hashlib

import orjson
import pytest

import settings as Settings
from server.services import agent_flow
from server.services.research_graph.branch import transition
from server.services.research_graph.branch.research_cycle import (
    prepare_research_cycle_trace,
)
from server.services.research_graph.research_cycle.adjudication import (
    validate_adjudication_decision,
    validate_adjudication_proposal,
)
from server.services.research_graph.graph_objects import (
    create_graph_object_schema,
    load_graph_objects,
)
from server.services.research_graph.research_cycle.trace_replay import (
    verify_research_cycle_trace,
)
from tests.server.data_contract_fixtures import initialize
from tools.data.sqlite.db import connect_sqlite


def _prepare(path, monkeypatch) -> dict:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    monkeypatch.setenv("AGENT_FLOW_DB_PATH", str(path.with_suffix(".agents")))
    agent_flow.clear_store_cache()
    initialize(path)
    with connect_sqlite(path) as conn:
        create_graph_object_schema(conn)
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


def test_eventful_bootstrap_persists_replayable_unknown_base(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "eventful-bootstrap.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    monkeypatch.setenv("AGENT_FLOW_DB_PATH", str(path.with_suffix(".agents")))
    agent_flow.clear_store_cache()
    checkpoint = _checkpoint()
    events, _ = _adjudication_events()

    trace_event, projected = prepare_research_cycle_trace(
        update={
            "schema_version": 1,
            "parent_trace_ref": "",
            "initial_checkpoint": checkpoint,
            "expected_base_hash": checkpoint["projection_hash"],
            "events": events,
        },
        previous_checkpoint=None,
        latest_trace_id="",
    )

    assert trace_event["bootstrap_checkpoint"] is True
    assert trace_event["initial_checkpoint"] == checkpoint
    assert verify_research_cycle_trace(
        previous_checkpoint=None,
        previous_trace_id="",
        event=trace_event,
        projected_checkpoint=projected,
    ) == projected


def _reclassification_events() -> tuple[list[dict], str]:
    invocation = agent_flow.get_store().reserve_invocation(
        owner_user_id="alice",
        agent_id="research:entry-reclassification",
        actor_role="researcher",
        authority_scope="local_research",
        purpose="map an existing obligation to a new Graph requirement",
        runtime_id="pytest",
        model_id="test-model",
        max_input_tokens=10,
        max_output_tokens=10,
        agent_principal_hash=hashlib.sha256(
            b"reclassification-principal"
        ).hexdigest(),
        lineage_hash=hashlib.sha256(
            b"reclassification-lineage"
        ).hexdigest(),
    )
    agent_flow.get_store().settle_invocation(
        owner_user_id="alice",
        invocation_id=invocation["invocation_id"],
        input_tokens=1,
        output_tokens=1,
        provider_request_id="entry-reclassification-test",
    )
    proposal = validate_adjudication_proposal({
        "schema_version": 2,
        "proposal_id": "proposal-reclassify-entry-requirement",
        "proposer_invocation_id": invocation["invocation_id"],
        "contract_hash": "1" * 64,
        "trial_plan_hash": "2" * 64,
        "methodology_hash": "3" * 64,
        "evidence_refs": ["evidence:semantic-mapping-review"],
        "claim_evidence_delta": [],
        "claim_delta_noop_reason": (
            "requirement classification changes no empirical Claim state"
        ),
        "obligation_delta": [{
            "obligation_id": "obligation-1",
            "from_state": "open",
            "to_state": "open",
            "criterion_ref": "graph-requirement:requirement-new",
            "from_requirement_refs": ["requirement-old"],
            "to_requirement_refs": [
                "requirement-old",
                "requirement-new",
            ],
        }],
        "decision_warrant": {
            "finding_refs": ["evidence:semantic-mapping-review"],
            "rule_refs": ["graph-requirement:requirement-new"],
            "inference_type": "semantic",
            "preregistered": False,
            "alternative_refs": [],
            "limitation_refs": [],
            "reentry_predicates": [],
            "required_authority": "human_audit",
        },
        "recommended_action": "continue_execution",
    })
    decision = validate_adjudication_decision({
        "schema_version": 1,
        "decision_id": "decision-reclassify-entry-requirement",
        "proposal_hash": proposal["proposal_hash"],
        "disposition": "accepted",
        "authority_class": "human_audit",
        "authority_ref": "human-audit:entry-reclassification-test",
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

    def executemany(self, sql, parameters):
        return self.conn.executemany(sql, parameters)


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
    with connect_sqlite(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM research_graph_objects"
        ).fetchone()[0] == 0


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


def test_successful_transition_colds_events_and_replays_exact_checkpoint(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "cold-events.sqlite"
    checkpoint = _prepare(path, monkeypatch)
    events, invocation_id = _adjudication_events()

    result = transition.advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="verify-semantics",
        evidence=_evidence(checkpoint, events, invocation_id),
    )

    trace_id = result["report_checkpoint"]["checkpoint_ref"].removeprefix(
        "trace:"
    )
    with connect_sqlite(path) as conn:
        row = conn.execute(
            "SELECT evidence_json FROM research_graph_trace WHERE trace_id=?",
            (trace_id,),
        ).fetchone()
        persisted = orjson.loads(row["evidence_json"])
        cycle = persisted["research_cycle"]
        assert "events" not in cycle
        assert len(cycle["event_receipts"]) == 2
        assert cycle["accepted_deltas"] == {
            "obligation_deltas": [{
                "obligation_id": "obligation-1",
                "from_state": "open",
                "to_state": "discharged",
            }],
            "claim_deltas": [{
                "claim_id": "claim-1",
                "from_state": "unknown",
                "to_state": "contradicted",
            }],
        }
        objects = load_graph_objects(
            conn,
            "alice",
            "instance-1",
            [cycle["events_ref"]],
            expected_kinds={
                cycle["events_ref"]: "research_cycle_event_bundle",
            },
        )
    replayed = verify_research_cycle_trace(
        previous_checkpoint=checkpoint,
        previous_trace_id="trace-bootstrap",
        event=cycle,
        projected_checkpoint=persisted["research_cycle_checkpoint"],
        resolved_events=objects[cycle["events_ref"]]["events"],
    )

    assert replayed == persisted["research_cycle_checkpoint"]
    assert len(row["evidence_json"].encode()) < 32 * 1024


def test_transition_reclassifies_before_mapping_the_same_entry_requirement(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "reclassify-entry.sqlite"
    checkpoint = _prepare(path, monkeypatch)
    checkpoint["obligations"][0]["requirement_refs"] = ["requirement-old"]
    checkpoint.pop("projection_hash")
    from server.services.research_graph.research_cycle.replay import (
        validate_research_cycle_checkpoint,
    )

    checkpoint = validate_research_cycle_checkpoint(checkpoint)
    with connect_sqlite(path) as conn:
        graph = orjson.loads(conn.execute(
            """
            SELECT graph_json FROM research_graph_versions
            WHERE graph_id='factor-research' AND version=1
            """
        ).fetchone()["graph_json"])
        graph["schema_version"] = 2
        graph["nodes"][0]["entry_requirement_refs"] = ["requirement-new"]
        graph["requirement_catalog"] = {
            "catalog_revision": 1,
            "categories": [],
            "requirements": [
                {
                    "requirement_id": "requirement-old",
                    "revision": 1,
                    "gate_policy": "resolve_before_exit",
                },
                {
                    "requirement_id": "requirement-new",
                    "revision": 1,
                    "gate_policy": "resolve_before_exit",
                },
            ],
        }
        conn.execute(
            """
            UPDATE research_graph_versions SET graph_json=?
            WHERE graph_id='factor-research' AND version=1
            """,
            (orjson.dumps(graph).decode(),),
        )
        conn.execute(
            """
            UPDATE research_graph_trace SET evidence_json=?
            WHERE trace_id='trace-bootstrap'
            """,
            (orjson.dumps({
                "research_cycle_checkpoint": checkpoint,
                "evidence_refs": [],
            }).decode(),),
        )
    events, invocation_id = _reclassification_events()
    evidence = _evidence(checkpoint, events, invocation_id)
    evidence["entry_requirement_assessments"] = [{
        "requirement_id": "requirement-new",
        "applicability": {
            "status": "applicable",
            "reason_zh": "现有义务语义覆盖新增的试验设计要求。",
            "fact_refs": ["evidence:semantic-mapping-review"],
        },
        "coverage": {
            "decision": "map_existing",
            "obligation_refs": ["obligation:obligation-1"],
        },
        "resolution": {
            "route": "trial",
            "reuse_status": "none",
            "validation_refs": [],
        },
        "entry_effect": {
            "status": "pass_limited",
            "limitation_refs": ["limitation:trial-still-required"],
        },
    }]

    result = transition.advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="verify-semantics",
        evidence=evidence,
    )

    trace_id = result["report_checkpoint"]["checkpoint_ref"].removeprefix(
        "trace:"
    )
    with connect_sqlite(path) as conn:
        persisted = orjson.loads(conn.execute(
            "SELECT evidence_json FROM research_graph_trace WHERE trace_id=?",
            (trace_id,),
        ).fetchone()["evidence_json"])
    obligation = persisted["research_cycle_checkpoint"]["obligations"][0]
    assert obligation["requirement_refs"] == [
        "requirement-old",
        "requirement-new",
    ]
    receipt = persisted["entry_requirement_assessment_receipts"][0]
    assert receipt["requirement_id"] == "requirement-new"
    assert receipt["obligation_refs"] == ["obligation:obligation-1"]
    assert persisted["entry_resolution_delta"]["items"] == [{
        "change_kind": "unchanged",
        "requirement_id": "requirement-new",
            "resolution_status": "assessed_limited",
    }]
