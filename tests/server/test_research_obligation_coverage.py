from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import sqlite3

import pytest

from server.services.research_graph.branch.obligation_coverage import (
    validate_obligation_coverage_submission,
)
from server.services.research_evidence_registry import ensure_schema
from tools.cli.release.research_obligations import (
    current_edge_scope,
    normalize_evidence_use,
    project_requirement_coverage,
)


_WIRE_FIELDS = {
    "requirement_id", "obligation_refs", "obligation_statuses",
    "evidence_uses", "scope_revalidation", "node_required",
    "edge_required", "satisfaction",
}

_FACTOR_REF = "factor:v2:" + "a" * 43
_OTHER_FACTOR_REF = "factor:v2:" + "b" * 43


def _graph():
    return {
        "graph_id": "factor-research",
        "version": 10,
        "requirement_catalog": {
            "requirements": [{
                "requirement_id": "mechanism_chain",
                "title_zh": "机制链",
                "gate_policy": "plan_before_exit",
            }],
        },
    }


def _node():
    return {
        "node_id": "factor_semantics",
        "entry_requirement_refs": ["mechanism_chain"],
    }


def _edge():
    return {
        "edge_id": "factor_semantics__validation_design",
        "from_node": "factor_semantics",
        "to_node": "validation_design",
        "obligation_requirement_refs": ["mechanism_chain"],
    }


def _checkpoint(status: str = "discharged"):
    return {
        "contract_hash": "1" * 64,
        "methodology_hash": "2" * 64,
        "trial_plan_hash": "",
        "claims": [{
            "claim_id": "claim-current",
            "scope": {"factor_ref": _FACTOR_REF},
            "evidence_state": "supported_in_scope",
        }],
        "obligations": [{
            "obligation_id": "o1",
            "status": status,
            "requirement_refs": ["mechanism_chain"],
            "scope": {"factor_ref": _FACTOR_REF},
            "claim_ids": ["claim-current"],
            "contract_hash": "1" * 64,
            "methodology_hash": "2" * 64,
        }],
    }


def _use(
    obligation_id: str = "o1",
    requirement_id: str = "mechanism_chain",
    *,
    factor_ref: str = _FACTOR_REF,
):
    return normalize_evidence_use({
        "evidence_ref": "evidence:diagnostic:sha256:" + "a" * 64,
        "evidence_title_zh": "当前因子证据",
        "obligation_ref": f"obligation:{obligation_id}",
        "requirement_refs": [requirement_id],
        "rationale_zh": "该片段在当前因子范围内支持义务",
        "qualification": "eligible",
        "scope_match": {
            "scope_compatibility": "compatible",
            "matched_by": ["factor_ref"],
            "conflicts": [],
            "limitations": [],
            "requested_scope": {
                "factor_refs": [factor_ref],
                "contract_hash": "1" * 64,
                "methodology_hash": "2" * 64,
            },
        },
    })


def _submission(status: str = "discharged"):
    checkpoint = _checkpoint(status)
    requirement = {
        **_graph()["requirement_catalog"]["requirements"][0],
        "scope_policy": {
            "required_scope": current_edge_scope(checkpoint),
        },
    }
    projected = project_requirement_coverage(
        requirements=[requirement],
        obligations=checkpoint["obligations"],
        evidence_uses=[_use()],
        edge_required_ids={"mechanism_chain"},
        node_required_ids={"mechanism_chain"},
        enforce_evidence=True,
    )
    value = {
        "schema_version": 2,
        "branch_ref": "graph-branch:instance:branch",
        "graph_ref": "factor-research@v10",
        "current_node": "factor_semantics",
        "context_ref": "sha256:" + "1" * 64,
        "checkpoint_ref": "trace:checkpoint",
        "edge_id": "factor_semantics__validation_design",
        "target_node": "validation_design",
        "coverage": [{key: deepcopy(projected[0][key]) for key in _WIRE_FIELDS}],
    }
    value["coverage_hash"] = "sha256:" + hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()
    ).hexdigest()
    value["prepared_git_commit"] = "a" * 40
    return value


def _validate(
    submitted,
    *,
    checkpoint=None,
    graph=None,
    edge=None,
    allow_missing=False,
):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    for use in {
        item["use_id"]: item
        for row in submitted.get("coverage") or []
        for item in row.get("evidence_uses") or []
    }.values():
        conn.execute(
            "INSERT INTO research_evidence_objects VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                use["evidence_ref"], "diagnostic", "a" * 64, "{}",
                json.dumps({
                    "factor_refs": use["scope_match"]["requested_scope"][
                        "factor_refs"
                    ],
                    "contract_hash": "1" * 64,
                    "methodology_hash": "2" * 64,
                }),
                "alice", 1.0,
            ),
        )
        conn.execute(
            "INSERT INTO research_evidence_admissions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "admission:" + "b" * 64, use["evidence_ref"],
                "workspace:workspace", "graph-branch:instance:branch",
                use["qualification"], use["rationale_zh"], "alice", 1.0,
            ),
        )
    return validate_obligation_coverage_submission(
        submitted=submitted,
        instance_id="instance",
        branch_id="branch",
        graph=graph or _graph(),
        current_node=_node(),
        edge=edge or _edge(),
        checkpoint=checkpoint or _checkpoint(),
            expected_checkpoint_ref="trace:checkpoint",
            conn=conn,
            owner="alice",
            allow_missing=allow_missing,
        )


def test_server_recomputes_and_accepts_exact_coverage():
    value = _validate(_submission())
    assert value["coverage"][0]["satisfaction"] == "satisfied"


def test_server_rejects_client_status_or_hash_drift():
    value = _submission()
    value["coverage"][0]["obligation_statuses"] = ["bounded"]
    with pytest.raises(ValueError, match="accepted server projection"):
        _validate(value)
    value = _submission()
    value["coverage_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        _validate(value)


def test_server_rejects_stale_identity_and_missing_coverage():
    value = _submission()
    value["checkpoint_ref"] = "trace:older"
    with pytest.raises(ValueError, match="checkpoint_ref is stale"):
        _validate(value)
    value = _submission("open")
    with pytest.raises(ValueError, match="missing obligation coverage"):
        _validate(value, checkpoint=_checkpoint("open"))


def test_server_accepts_limited_coverage():
    value = _validate(
        _submission("bounded"),
        checkpoint=_checkpoint("bounded"),
    )
    assert value["coverage"][0]["satisfaction"] == "limited"


def test_human_override_allows_missing_but_not_projection_drift():
    submitted = _submission("open")
    accepted = _validate(
        submitted,
        checkpoint=_checkpoint("open"),
        allow_missing=True,
    )
    assert accepted["coverage"][0]["satisfaction"] == "missing"

    submitted["coverage"][0]["obligation_refs"] = []
    with pytest.raises(ValueError, match="accepted server projection"):
        _validate(
            submitted,
            checkpoint=_checkpoint("open"),
            allow_missing=True,
        )


def test_human_override_cannot_reuse_another_factor_scope():
    checkpoint = _checkpoint("bounded")
    checkpoint["obligations"][0]["claim_ids"] = []
    checkpoint["obligations"][0]["scope"] = {}
    requirement = {
        **_graph()["requirement_catalog"]["requirements"][0],
        "scope_policy": {
            "required_scope": current_edge_scope(checkpoint),
        },
    }
    projected = project_requirement_coverage(
        requirements=[requirement],
        obligations=checkpoint["obligations"],
        evidence_uses=[_use(factor_ref=_OTHER_FACTOR_REF)],
        edge_required_ids={"mechanism_chain"},
        node_required_ids={"mechanism_chain"},
        enforce_evidence=True,
    )
    submitted = _submission("bounded")
    submitted["coverage"] = [{
        key: deepcopy(projected[0][key]) for key in _WIRE_FIELDS
    }]
    unhashed = {
        key: value for key, value in submitted.items()
        if key not in {"coverage_hash", "prepared_git_commit"}
    }
    submitted["coverage_hash"] = "sha256:" + hashlib.sha256(
        json.dumps(
            unhashed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    with pytest.raises(ValueError, match="stale or unbound obligation scope"):
        _validate(
            submitted,
            checkpoint=checkpoint,
            allow_missing=True,
        )


def test_edge_obligation_and_node_entry_requirements_are_a_union():
    graph = _graph()
    graph["requirement_catalog"]["requirements"].append({
        "requirement_id": "edge_gate",
        "title_zh": "Edge 专属义务",
        "gate_policy": "plan_before_exit",
    })
    edge = {
        **_edge(),
        "obligation_requirement_refs": ["edge_gate"],
    }
    checkpoint = {
        "obligations": [{
            "obligation_id": "node-open",
            "status": "open",
            "requirement_refs": ["mechanism_chain"],
        }, {
            "obligation_id": "edge-discharged",
            "status": "discharged",
            "requirement_refs": ["edge_gate"],
        }],
    }
    value = {
        "schema_version": 2,
        "branch_ref": "graph-branch:instance:branch",
        "graph_ref": "factor-research@v10",
        "current_node": "factor_semantics",
        "context_ref": "sha256:" + "1" * 64,
        "checkpoint_ref": "trace:checkpoint",
        "edge_id": "factor_semantics__validation_design",
        "target_node": "validation_design",
        "coverage": [],
    }
    checkpoint.update({
        "contract_hash": "1" * 64,
        "methodology_hash": "2" * 64,
        "trial_plan_hash": "",
        "claims": [{
            "claim_id": "claim-current",
            "scope": {"factor_ref": _FACTOR_REF},
            "evidence_state": "supported_in_scope",
        }],
    })
    for obligation in checkpoint["obligations"]:
        obligation.update({
            "scope": {"factor_ref": _FACTOR_REF},
            "claim_ids": ["claim-current"],
            "contract_hash": "1" * 64,
            "methodology_hash": "2" * 64,
        })
    requirements = []
    for requirement in graph["requirement_catalog"]["requirements"]:
        requirements.append({
            **requirement,
            "scope_policy": {
                "required_scope": current_edge_scope(checkpoint),
            },
        })
    projected = project_requirement_coverage(
        requirements=requirements,
        obligations=checkpoint["obligations"],
        evidence_uses=[_use("edge-discharged", "edge_gate")],
        edge_required_ids={"edge_gate"},
        node_required_ids={"mechanism_chain"},
        enforce_evidence=True,
    )
    value["coverage"] = [
        {key: deepcopy(row[key]) for key in _WIRE_FIELDS}
        for row in projected
    ]
    value["coverage_hash"] = "sha256:" + hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()
    ).hexdigest()
    value["prepared_git_commit"] = "a" * 40

    accepted = _validate(
        value, checkpoint=checkpoint, graph=graph, edge=edge,
    )

    assert [item["requirement_id"] for item in accepted["coverage"]] == [
        "mechanism_chain", "edge_gate",
    ]
