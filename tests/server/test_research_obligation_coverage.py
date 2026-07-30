from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from server.services.research_graph.branch.obligation_coverage import (
    validate_obligation_coverage_submission,
)


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
        "obligations": [{
            "obligation_id": "o1",
            "status": status,
            "requirement_refs": ["mechanism_chain"],
        }],
    }


def _submission(status: str = "discharged"):
    satisfaction = (
        "satisfied" if status == "discharged"
        else "limited" if status in {"bounded", "serviced"}
        else "missing"
    )
    value = {
        "schema_version": 1,
        "branch_ref": "graph-branch:instance:branch",
        "graph_ref": "factor-research@v10",
        "current_node": "factor_semantics",
        "context_ref": "sha256:" + "1" * 64,
        "checkpoint_ref": "trace:checkpoint",
        "edge_id": "factor_semantics__validation_design",
        "target_node": "validation_design",
        "coverage": [{
            "requirement_id": "mechanism_chain",
            "obligation_refs": ["obligation:o1"],
            "obligation_statuses": [status],
            "node_required": True,
            "edge_required": True,
            "satisfaction": satisfaction,
        }],
    }
    value["coverage_hash"] = "sha256:" + hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()
    ).hexdigest()
    value["prepared_git_commit"] = "a" * 40
    return value


def _validate(submitted, *, checkpoint=None):
    return validate_obligation_coverage_submission(
        submitted=submitted,
        instance_id="instance",
        branch_id="branch",
        graph=_graph(),
        current_node=_node(),
        edge=_edge(),
        checkpoint=checkpoint or _checkpoint(),
        expected_checkpoint_ref="trace:checkpoint",
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
        "schema_version": 1,
        "branch_ref": "graph-branch:instance:branch",
        "graph_ref": "factor-research@v10",
        "current_node": "factor_semantics",
        "context_ref": "sha256:" + "1" * 64,
        "checkpoint_ref": "trace:checkpoint",
        "edge_id": "factor_semantics__validation_design",
        "target_node": "validation_design",
        "coverage": [{
            "requirement_id": "mechanism_chain",
            "obligation_refs": ["obligation:node-open"],
            "obligation_statuses": ["open"],
            "node_required": True,
            "edge_required": False,
            "satisfaction": "pending",
        }, {
            "requirement_id": "edge_gate",
            "obligation_refs": ["obligation:edge-discharged"],
            "obligation_statuses": ["discharged"],
            "node_required": False,
            "edge_required": True,
            "satisfaction": "satisfied",
        }],
    }
    value["coverage_hash"] = "sha256:" + hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()
    ).hexdigest()
    value["prepared_git_commit"] = "a" * 40

    accepted = validate_obligation_coverage_submission(
        submitted=value,
        instance_id="instance",
        branch_id="branch",
        graph=graph,
        current_node=_node(),
        edge=edge,
        checkpoint=checkpoint,
        expected_checkpoint_ref="trace:checkpoint",
    )

    assert [item["requirement_id"] for item in accepted["coverage"]] == [
        "mechanism_chain", "edge_gate",
    ]
