from __future__ import annotations

import orjson

import settings as Settings
from server.services.research_graph.branch.capability_detour import (
    load_or_reconstruct,
)
from server.services.research_graph.branch.continuation import (
    continue_graph_branch,
    preview_graph_continuation,
)
from tests.server.test_graph_version_continuation import (
    _pause_legacy_branch_without_bound_job,
    _prepare,
    _upgrade_active_target_to_schema_v2,
)
from tools.data.sqlite.db import connect_sqlite


def test_continuation_hash_binds_reconstructed_detour_identity(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _prepare(path)
    _pause_legacy_branch_without_bound_job(path)
    _upgrade_active_target_to_schema_v2(path)

    preview = preview_graph_continuation(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=2,
        job_id="",
    )
    detour = preview["descriptor"]["capability_detour"]

    assert detour["resume_node"] == "authoritative_backtest"
    assert detour["origin_trace_id"] == "trace-legacy-gap"
    assert detour["report_container"]["kind"] == "special"

    continued = continue_graph_branch(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=2,
        job_id="",
        expected_target_hash=preview["target_hash"],
    )
    branch = continued["branches"][0]
    with connect_sqlite(path) as conn:
        inherited = load_or_reconstruct(
            conn,
            instance_id=continued["instance_id"],
            branch_id=branch["branch_id"],
        )
        evidence = orjson.loads(conn.execute(
            """
            SELECT evidence_json FROM research_graph_trace
            WHERE instance_id=? AND branch_id=?
            """,
            (continued["instance_id"], branch["branch_id"]),
        ).fetchone()["evidence_json"])

    assert inherited == detour
    assert evidence["graph_continuation"]["capability_detour"] == detour
