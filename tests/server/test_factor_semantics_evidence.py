"""Server-owned factor semantics on the existing semantics edge."""

from __future__ import annotations

import orjson
import pytest

import settings as Settings
from server.services import research_graphs
from server.services.research_graph.branch import (
    factor_semantics as factor_semantics_service,
)
from server.services.research_graph.branch.transition import (
    advance_graph_branch,
)
from server.services.research_graph.protocol import MAX_PERSISTED_TRACE_BYTES
from tests.server.data_contract_fixtures import checkpoint, initialize
from tools.data.sqlite.db import connect_sqlite
from tools.factors.formula_identity import freeze_factor_identity


def _factor_ref(identity: str) -> str:
    return freeze_factor_identity(
        owner_ref="profile:maxa",
        family_alias=identity.split("|", 1)[0],
        factor_alias=identity,
        family_formula_fingerprint="3" * 64,
        self_formula_fingerprint="4" * 64,
        params={},
    )["ref"]


_FACTOR_REF = _factor_ref("MmRateOfChg|P:[CA]|N:20d|$F:1d")

def _factor_graph() -> dict:
    return {
        "graph_id": "factor-research",
        "version": 1,
        "lifecycle": "active",
        "content_hash": "d" * 64,
        "entry_node": "factor_semantics",
        "nodes": [
            {
                "node_id": "factor_semantics",
                "kind": "research",
                "required_capabilities": [],
            },
            {
                "node_id": "validation_design",
                "kind": "research",
                "required_capabilities": [],
            },
        ],
        "edges": [{
            "edge_id": "factor_semantics__validation_design",
            "from_node": "factor_semantics",
            "to_node": "validation_design",
            "guard": {
                "frozen_factor_formulas_bound": True,
                "selected_factor_semantics_resolved": True,
                "causal_semantics_valid": True,
            },
            "required_evidence": [],
            "server_action": "bind_factor_semantics",
        }],
    }


def _prepare(path) -> None:
    initialize(path, factor_ref=_FACTOR_REF)
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            UPDATE research_graph_versions SET graph_json=?
            WHERE graph_id='factor-research' AND version=1
            """,
            (orjson.dumps(_factor_graph()).decode(),),
        )
        conn.execute(
            """
            UPDATE research_graph_branches SET current_node='factor_semantics'
            WHERE branch_id='branch-1'
            """
        )


def _evidence() -> dict:
    return {
        "factor_subject_refs": [_FACTOR_REF],
        "frozen_factor_formulas_bound": False,
        "selected_factor_semantics_resolved": False,
        "causal_semantics_valid": True,
    }


def test_factor_subject_uses_explicit_current_report_binding() -> None:
    current = checkpoint()
    current["obligations"][0]["scope"]["factor_ref"] = _FACTOR_REF
    evidence = {
        "factor_subject_refs": [_FACTOR_REF],
        "obligation_coverage_submission": {"coverage": [{
            "evidence_uses": [{"scope_match": {"requested_scope": {
                "factor_refs": [
                    _factor_ref("Other|N:5d")
                ],
            }}}],
        }]},
    }

    assert factor_semantics_service._transition_factor_subject_refs(
        checkpoint=current,
        evidence=evidence,
    ) == [_FACTOR_REF]


def test_factor_subject_rejects_a_different_frozen_family() -> None:
    current = checkpoint()
    current["obligations"][0]["scope"]["factor_ref"] = _FACTOR_REF
    other = _factor_ref("SgCCS|N:2m|$Rev")

    with pytest.raises(ValueError, match="accepted research subject"):
        factor_semantics_service._transition_factor_subject_refs(
            checkpoint=current,
            evidence={"factor_subject_refs": [other]},
        )


def test_factor_subject_does_not_fall_back_to_checkpoint_or_coverage() -> None:
    current = checkpoint()
    evidence = {
        "obligation_coverage_submission": {"coverage": [{
            "evidence_uses": [{"scope_match": {"requested_scope": {
                "factor_refs": [_FACTOR_REF],
            }}}],
        }]},
    }

    with pytest.raises(ValueError, match="explicit factor_subject_refs"):
        factor_semantics_service._transition_factor_subject_refs(
            checkpoint=current,
            evidence=evidence,
        )


def test_factor_semantics_edge_discloses_automatic_binding(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graphs.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _prepare(path)

    packet = research_graphs.build_graph_branch_edge_info(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="factor_semantics__validation_design",
    )

    assert packet["edge"]["action_contract"] == {
        "mode": "automatic",
        "factor_subject_source": "current_report_requirement_bindings",
        "submission": (
            "node advance sends the typed factors bound to this transition's "
            "report components; the server validates their exact frozen "
            "identities"
        ),
    }


def test_factor_semantics_edge_binds_source_free_server_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graphs.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _prepare(path)
    result = advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="factor_semantics__validation_design",
        evidence=_evidence(),
    )

    assert result["current_node"] == "validation_design"
    with connect_sqlite(path) as conn:
        row = conn.execute(
            """
            SELECT evidence_json FROM research_graph_trace
            WHERE trace_id=(SELECT latest_trace_id
                            FROM research_graph_branches
                            WHERE branch_id='branch-1')
            """
        ).fetchone()
    trace = orjson.loads(row["evidence_json"])
    assert "factor_semantics_request" not in trace
    envelope = trace["server_evidence"]["factor_semantics"]
    assert envelope["identity_refs"] == {
        "contract_hash": "1" * 64,
        "methodology_hash": "2" * 64,
    }
    assert "configuration_revision" not in envelope["facts"]
    assert envelope["source_refs"] == [_FACTOR_REF]
    assert envelope["facts"]["factor_subject_refs"] == [_FACTOR_REF]
    assert envelope["facts"]["factor_revision_count"] == 1
    assert "factor_family_refs" not in envelope["facts"]
    assert envelope["facts"]["factor_revision_set_hash"]
    assert "required_market_fields" not in envelope["facts"]
    assert "factor_revision_refs" not in envelope["facts"]
    assert "source_code" not in orjson.dumps(envelope).decode()


def test_many_factor_revisions_are_bound_by_set_hash_not_trace_copy(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graphs.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _prepare(path)
    refs = [_factor_ref(f"MmRateOfChg|N:{index}d") for index in range(100)]

    advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="factor_semantics__validation_design",
        evidence={**_evidence(), "factor_subject_refs": refs},
    )

    with connect_sqlite(path) as conn:
        row = conn.execute(
            """
            SELECT evidence_json FROM research_graph_trace
            WHERE trace_id=(SELECT latest_trace_id
                            FROM research_graph_branches
                            WHERE branch_id='branch-1')
            """
        ).fetchone()
    assert len(row["evidence_json"].encode()) <= MAX_PERSISTED_TRACE_BYTES
    assert '"factor_revision_refs"' not in row["evidence_json"]
