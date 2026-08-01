"""Persistent reuse of market-data capability snapshots."""

from __future__ import annotations

import hashlib
import json

import settings as Settings
from server.services import data_availability as service
from server.services.research_evidence_catalog import (
    create_evidence,
    put_source_capture,
    put_source_fragment,
)
from server.services.research_graph.branch.transition import advance_graph_branch
from tests.server.data_contract_fixtures import initialize, profile


def _scope() -> dict:
    return {
        "product_names": ["A.DCE"],
        "source_names": ["Local"],
        "frequency_names": ["MIN1"],
        "probe": False,
        "expanded": False,
    }


def test_repeated_scope_reads_one_materialized_profile(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "cache.sqlite")
    calls = []

    def inspect(**_kwargs):
        calls.append(1)
        return profile()

    monkeypatch.setattr(service, "_inspect_scope", inspect)

    first = service.availability_for_scope(**_scope())
    second = service.availability_for_scope(**_scope())

    assert first == second
    assert calls == [1]
    assert service.load_availability_profile(
        service.profile_reference(first)
    ) == first


def test_node_advance_reuses_terminal_evidence_profile(tmp_path, monkeypatch) -> None:
    path = tmp_path / "graphs.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    initialize(path)
    monkeypatch.setattr(service, "_inspect_scope", lambda **_kwargs: profile())
    frozen = service.availability_for_scope(**_scope())
    profile_ref = service.profile_reference(frozen)
    output = json.dumps({"profile_ref": profile_ref, **frozen}, sort_keys=True)
    source = put_source_capture(
        owner="alice",
        source_kind="terminal",
        identity={"execution_id": "availability-1", "argv": ["factortester", "products", "availability"]},
        content_hash=hashlib.sha256(output.encode()).hexdigest(),
        audit={"returncode": 0},
    )
    fragment = put_source_fragment(
        owner="alice",
        source_ref=source["source_ref"],
        selector={"stream": "stdout", "json_pointer": "/profile_ref", "return_code": 0},
        fragment_hash=hashlib.sha256(output.encode()).hexdigest(),
        title_zh="分钟数据能力快照",
        summary_zh="终端查询冻结了分钟数据源、字段与覆盖范围",
        preview={"json": {"profile_ref": profile_ref}},
    )
    evidence = create_evidence(
        owner="alice",
        evidence_kind="data_contract",
        fragment_refs=[fragment["fragment_ref"]],
        title_zh="分钟数据契约",
        description_zh="终端查询返回并冻结分钟数据能力快照",
        claim_summary="The frozen profile records the requested minute-data scope.",
        applicability={
            "contract_hash": "1" * 64,
            "methodology_hash": "2" * 64,
            "source_refs": [profile_ref],
        },
        identity_refs={
            "contract_hash": "1" * 64,
            "methodology_hash": "2" * 64,
        },
        limitations=[],
        conflicts=[],
    )

    result = advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="data_contract__factor_semantics",
        evidence={"evidence_refs": [evidence["evidence_ref"]]},
    )

    assert result["current_node"] == "factor_semantics"

