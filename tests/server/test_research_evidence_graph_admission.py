from __future__ import annotations

import orjson
import pytest

import settings as Settings
from server.services.research_evidence_registry import admit_evidence, put_evidence
from server.services.research_evidence_catalog import (
    finalize_lifecycle_transition,
    prepare_lifecycle_transition,
)
from server.services.research_graph.branch.transition import advance_graph_branch
from tests.server.data_contract_fixtures import initialize
from tools.data.sqlite.db import connect_sqlite


def _graph() -> dict:
    return {
        "graph_id": "factor-research", "version": 1, "lifecycle": "active",
        "content_hash": "c" * 64, "entry_node": "data_contract",
        "nodes": [
            {"node_id": "data_contract", "kind": "research", "required_capabilities": []},
            {"node_id": "factor_semantics", "kind": "research", "required_capabilities": []},
        ],
        "edges": [{
            "edge_id": "data__semantics", "from_node": "data_contract",
            "to_node": "factor_semantics",
            "guard": {
                "admitted_evidence_bound": True,
                "admitted_evidence_eligible": True,
            },
            "required_evidence": ["admitted_evidence"],
        }],
    }


def _envelope() -> dict:
    return {
        "schema_version": 2, "envelope_id": "data-contract:replay-1",
        "evidence_kind": "data_contract", "source_refs": ["source:local"],
        "identity_refs": {"contract_hash": "1" * 64, "methodology_hash": "2" * 64},
        "facts": {}, "metric_refs": [], "artifact_refs": [],
        "hypotheses_tested": 0, "stop_condition": None,
        "limitations": [], "conflicts": [],
    }


def _prepare(path) -> dict:
    initialize(path)
    with connect_sqlite(path) as conn:
        conn.execute(
            "UPDATE research_graph_versions SET graph_json=? "
            "WHERE graph_id='factor-research' AND version=1",
            (orjson.dumps(_graph()).decode(),),
        )
    return put_evidence(
        owner="alice", envelope=_envelope(),
        applicability={"contract_hash": "1" * 64, "methodology_hash": "2" * 64},
    )


def _admission(record: dict, *, qualification: str = "eligible", branch: str = "branch-1") -> dict:
    return admit_evidence(
        owner="alice", evidence_ref=record["evidence_ref"],
        environment_ref="workspace:workspace-1",
        subject_ref=f"graph-branch:instance-1:{branch}",
        qualification=qualification,
    )


def _advance(record: dict, admission: dict) -> dict:
    return advance_graph_branch(
        instance_id="instance-1", branch_id="branch-1", owner="alice",
        edge_id="data__semantics", evidence={"admitted_evidence": [{
            "evidence_ref": record["evidence_ref"],
            "admission_ref": admission["admission_ref"],
        }]},
    )


def test_transition_binds_eligible_registry_evidence_without_copying_envelope(
    tmp_path, monkeypatch,
) -> None:
    path = tmp_path / "graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    record = _prepare(path)

    result = _advance(record, _admission(record))

    assert result["current_node"] == "factor_semantics"
    with connect_sqlite(path) as conn:
        trace = orjson.loads(conn.execute(
            "SELECT evidence_json FROM research_graph_trace "
            "WHERE branch_id='branch-1' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()["evidence_json"])
    bound = trace["admitted_evidence"]
    assert bound == [{
        "evidence_ref": record["evidence_ref"],
        "admission_ref": _admission(record)["admission_ref"],
        "evidence_kind": "data_contract",
        "envelope_hash": record["envelope_hash"],
        "qualification": "eligible",
        "applicability_hash": bound[0]["applicability_hash"],
    }]
    assert "source_refs" not in orjson.dumps(bound).decode()
    assert record["evidence_ref"] in trace["evidence_refs"]


def test_transition_rejects_cross_branch_or_limited_admission(tmp_path, monkeypatch) -> None:
    path = tmp_path / "graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    record = _prepare(path)
    with pytest.raises(ValueError, match="not valid for this Graph branch"):
        _advance(record, _admission(record, branch="branch-other"))
    with pytest.raises(ValueError, match="admitted_evidence_eligible"):
        _advance(record, _admission(record, qualification="limited"))


def test_excluded_evidence_rejects_new_admission_and_existing_reuse(
    tmp_path, monkeypatch,
) -> None:
    path = tmp_path / "graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    record = _prepare(path)
    admission = _admission(record)
    prepared = prepare_lifecycle_transition(
        owner="alice",
        evidence_ref=record["evidence_ref"],
        action="exclude",
        reason_zh="该证据的适用范围与当前研究合同不一致",
        profile_ref="profile:maxa",
        agent_id="research-maxa",
        instance_id="instance-1",
        branch_id="branch-1",
        parent_id="node-data-contract",
    )
    finalize_lifecycle_transition(
        owner="alice",
        transition_ref=prepared["transition_ref"],
        report_receipt={
            "submission_sequence": 1,
            "component_id": "evidence-exclusion-one",
            "git_commit": "a" * 40,
            "ledger_generation": 1,
            "ledger_projection_hash": "b" * 64,
        },
    )

    with pytest.raises(ValueError, match="excluded Evidence"):
        _admission(record)
    with pytest.raises(ValueError, match="excluded Evidence"):
        _advance(record, admission)
