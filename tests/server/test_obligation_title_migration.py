from __future__ import annotations

from copy import deepcopy

import orjson

from server.services.research_graph.branch.schema import (
    create_instance_branch_schema,
)
from server.services.research_graph.graph_objects import (
    create_graph_object_schema,
)
from server.services.research_graph.obligation_title_migration import (
    migrate_checkpoint,
    migrate_events,
    migrate_obligation_titles,
)
from server.services.research_graph.protocol import json_hash
from server.services.research_graph.research_cycle import (
    validate_adjudication_decision,
    validate_adjudication_proposal,
    validate_research_cycle_checkpoint,
)
from tools.data.sqlite.db import connect_sqlite


def _checkpoint(*, obligations=None):
    return validate_research_cycle_checkpoint({
        "schema_version": 1,
        "contract_hash": "1" * 64,
        "trial_plan_hash": "",
        "methodology_hash": "2" * 64,
        "claims": [{
            "schema_version": 1,
            "claim_id": "claim-one",
            "contract_hash": "1" * 64,
            "claim_ref": "claim:one",
            "claim_type": "bounded_predictive_relationship",
            "scope": {},
            "evidence_state": "unknown",
            "evidence_refs": [],
        }],
        "obligations": obligations or [],
        "pending_adjudications": [],
        "pending_closure": None,
    })


def _obligation():
    return {
        "schema_version": 1,
        "obligation_id": "obligation-one",
        "contract_hash": "1" * 64,
        "claim_ids": ["claim-one"],
        "obligation_kind": "semantic_validation",
        "title_zh": "信号语义验证",
        "epistemic_question": "Is the signal semantics valid?",
        "scope": {},
        "discharge_criterion": {"method": "semantic audit"},
        "status": "open",
        "materiality": "decision_blocking",
        "methodology_hash": "2" * 64,
        "created_event_ref": "trace:one",
    }


def _legacy_checkpoint():
    checkpoint = _checkpoint(obligations=[_obligation()])
    checkpoint = deepcopy(checkpoint)
    checkpoint["obligations"][0].pop("title_zh")
    checkpoint.pop("projection_hash")
    checkpoint["projection_hash"] = json_hash(checkpoint)
    return checkpoint


def test_checkpoint_migration_restores_reviewed_title_and_hash():
    migrated = migrate_checkpoint(
        _legacy_checkpoint(),
        titles={"obligation-one": "信号语义验证"},
    )

    assert migrated["obligations"][0]["title_zh"] == "信号语义验证"
    assert migrated["projection_hash"] != _legacy_checkpoint()[
        "projection_hash"
    ]


def test_event_migration_rebinds_decision_to_rehashed_creation():
    before = _checkpoint()
    proposal = validate_adjudication_proposal({
        "schema_version": 1,
        "proposal_id": "proposal-one",
        "contract_hash": "1" * 64,
        "trial_plan_hash": "",
        "methodology_hash": "2" * 64,
        "evidence_refs": ["evidence:one"],
        "claim_evidence_delta": [],
        "claim_delta_noop_reason": "no empirical Claim change",
        "obligation_delta": [{
            "obligation_id": "obligation-one",
            "from_state": "absent",
            "to_state": "open",
            "criterion_ref": "criterion:one",
            "obligation": _obligation(),
        }],
        "decision_warrant": {
            "finding_refs": ["evidence:one"],
            "rule_refs": ["criterion:one"],
            "inference_type": "semantic",
            "preregistered": False,
            "alternative_refs": [],
            "limitation_refs": [],
            "reentry_predicates": [],
            "required_authority": "independent_reviewer",
        },
    })
    legacy = deepcopy(proposal)
    legacy.pop("proposal_hash")
    legacy["obligation_delta"][0]["obligation"].pop("title_zh")
    legacy["proposal_hash"] = json_hash(legacy)
    decision = validate_adjudication_decision({
        "schema_version": 1,
        "decision_id": "decision-one",
        "proposal_hash": legacy["proposal_hash"],
        "disposition": "accepted",
        "authority_class": "independent_reviewer",
        "authority_ref": "review:one",
        "methodology_hash": "2" * 64,
    })

    events, after = migrate_events(
        before,
        [{
            "event_type": "adjudication_proposed",
            "proposal": legacy,
        }, {
            "event_type": "adjudication_decided",
            "decision": decision,
        }],
        titles={"obligation-one": "信号语义验证"},
    )

    new_hash = events[0]["proposal"]["proposal_hash"]
    assert new_hash != legacy["proposal_hash"]
    assert events[1]["decision"]["proposal_hash"] == new_hash
    assert after["obligations"][0]["title_zh"] == "信号语义验证"


def test_database_migration_is_transactional_and_idempotent(tmp_path):
    path = tmp_path / "research.sqlite"
    checkpoint = _legacy_checkpoint()
    evidence = {
        "research_cycle": {
            "schema_version": 1,
            "parent_trace_ref": "",
            "bootstrap_checkpoint": True,
            "checkpoint_before_hash": checkpoint["projection_hash"],
            "events": [],
        },
        "research_cycle_checkpoint": checkpoint,
    }
    with connect_sqlite(path) as conn:
        create_instance_branch_schema(conn)
        create_graph_object_schema(conn)
        conn.execute(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id, from_node, to_node,
                evidence_json, telemetry_json, actor, created_at
            ) VALUES (
                'trace-one', 'instance-one', 'branch-one', 'bootstrap',
                'node-one', 'node-one', ?, '{}', 'agent', 1
            )
            """,
            (orjson.dumps(evidence).decode(),),
        )

    first = migrate_obligation_titles(
        db_path=path,
        titles={"obligation-one": "信号语义验证"},
    )
    second = migrate_obligation_titles(
        db_path=path,
        titles={"obligation-one": "信号语义验证"},
    )

    assert first["trace_rows_updated"] == 1
    assert second["trace_rows_updated"] == 0
    with connect_sqlite(path) as conn:
        stored = orjson.loads(conn.execute(
            "SELECT evidence_json FROM research_graph_trace"
        ).fetchone()["evidence_json"])
    assert stored["research_cycle_checkpoint"]["obligations"][0][
        "title_zh"
    ] == "信号语义验证"
