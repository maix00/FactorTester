"""Server-owned factor semantics on the existing semantics edge."""

from __future__ import annotations

import orjson
import pytest

import settings as Settings
from server.services.research_graph.branch import (
    factor_semantics as factor_semantics_service,
)
from server.services.research_graph.branch.transition import (
    advance_graph_branch,
)
from server.services.research_graph.protocol import MAX_PERSISTED_TRACE_BYTES
from tests.server.data_contract_fixtures import initialize
from tools.data.sqlite.db import connect_sqlite


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
    initialize(path)
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
                }],
            },
            "analyses": {},
            "ui": {},
        },
    }


def _evidence() -> dict:
    return {
        "factor_semantics_request": {"configuration_revision": 3},
        "factor_revision_manifests_bound": False,
        "selected_factor_semantics_resolved": False,
        "causal_semantics_valid": True,
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
    monkeypatch.setattr(
        factor_semantics_service.factor_revisions,
        "freeze_factor_revisions",
        lambda configuration, **_kwargs: configuration,
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
    assert envelope["facts"]["factor_revision_count"] == 1
    assert envelope["facts"]["factor_family_refs"] == ["alice:Alpha"]
    assert envelope["facts"]["factor_revision_set_hash"]
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
