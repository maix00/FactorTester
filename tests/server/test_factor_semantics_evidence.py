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


_FACTOR_REF = (
    "factor:v1:profile-maxa:cHVibGljX2ZhY3RvcnMvTW1SYXRlT2ZDaGcucHk:"
    "TW1SYXRlT2ZDaGd8UDpbQ0FdfE46MjBkfCRGOjFk:"
    + "3" * 40 + ":" + "4" * 40
)

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
                "factor_revision_manifests_bound": True,
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


def _configuration(*, status: str = "resolved") -> dict:
    return {
        "configuration_id": "configuration-1",
        "revision": 3,
        "fingerprint": "f" * 64,
        "payload": {
            "schema_version": 1,
            "shared": {
                "factor_families": [{"alias": "alice:Alpha"}],
                "factors": [],
                "factor_revision_manifests": [{
                    "schema_version": 1,
                    "factor_family_ref": "alice:Alpha",
                    "factor_alias_hash": "a" * 64,
                    "manifest_hash": "b" * 64,
                    "resolution_status": status,
                    "column_refs": ["CLOSE_ADJUSTED", "VOLUME"],
                }],
            },
            "analyses": {},
            "ui": {},
        },
    }


def _evidence() -> dict:
    return {
        "factor_subject_refs": [_FACTOR_REF],
        "factor_revision_manifests_bound": False,
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
                    "factor:v1:profile-maxa:cGF0aA:b3RoZXI:"
                    + "c" * 40 + ":" + "d" * 40
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
    other = _FACTOR_REF.replace(
        "TW1SYXRlT2ZDaGd8UDpbQ0FdfE46MjBkfCRGOjFk",
        "U2dDQ1N8TjoybXwkeFJldg",
    )

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
            "report components; the server validates and freezes them once"
        ),
    }


def test_factor_semantics_edge_binds_source_free_server_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graphs.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _prepare(path)
    monkeypatch.setattr(
        factor_semantics_service.research_configurations,
        "load_workspace_configuration",
        lambda **_kwargs: _configuration(),
    )
    selected: list[list[str]] = []
    monkeypatch.setattr(
        factor_semantics_service.factor_revisions,
        "freeze_factor_revisions",
        lambda configuration, **kwargs: (
            selected.append(kwargs["selected_factor_aliases"]) or configuration
        ),
    )

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
    assert envelope["facts"]["configuration_revision"] == 3
    assert selected == [["MmRateOfChg|P:[CA]|N:20d|$F:1d"]]
    assert envelope["facts"]["factor_subject_refs"] == [_FACTOR_REF]
    assert envelope["facts"]["factor_revision_count"] == 1
    assert envelope["facts"]["factor_family_refs"] == ["alice:Alpha"]
    assert envelope["facts"]["factor_revision_set_hash"]
    assert envelope["facts"]["required_market_fields"] == [
        "CLOSE_ADJUSTED",
        "VOLUME",
    ]
    assert "factor_revision_refs" not in envelope["facts"]
    assert "source_code" not in orjson.dumps(envelope).decode()


def test_many_factor_revisions_are_bound_by_set_hash_not_trace_copy(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graphs.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _prepare(path)
    configuration = _configuration()
    configuration["payload"]["shared"]["factor_revision_manifests"] = [
        {
            "schema_version": 1,
            "factor_family_ref": "alice:Alpha",
            "factor_alias_hash": f"{index:064x}",
            "manifest_hash": f"{index + 1000:064x}",
            "resolution_status": "resolved",
        }
        for index in range(100)
    ]
    monkeypatch.setattr(
        factor_semantics_service.research_configurations,
        "load_workspace_configuration",
        lambda **_kwargs: configuration,
    )
    monkeypatch.setattr(
        factor_semantics_service.factor_revisions,
        "freeze_factor_revisions",
        lambda selected, **_kwargs: selected,
    )

    advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="factor_semantics__validation_design",
        evidence=_evidence(),
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


def test_unresolved_selected_factor_semantics_cannot_advance(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graphs.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _prepare(path)
    monkeypatch.setattr(
        factor_semantics_service.research_configurations,
        "load_workspace_configuration",
        lambda **_kwargs: _configuration(status="family_contract_only"),
    )
    monkeypatch.setattr(
        factor_semantics_service.factor_revisions,
        "freeze_factor_revisions",
        lambda configuration, **_kwargs: configuration,
    )

    with pytest.raises(
        ValueError,
        match="selected_factor_semantics_resolved",
    ):
        advance_graph_branch(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            edge_id="factor_semantics__validation_design",
            evidence=_evidence(),
        )
