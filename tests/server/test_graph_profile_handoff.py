from __future__ import annotations

import orjson
import pytest

import settings as Settings
from server.services.research_graph.branch.handoff import (
    handoff_graph_branch,
)
from server.services.research_graph.branch.repository import (
    branch_payload,
)
from tests.server.data_contract_fixtures import checkpoint, initialize
from tools.data.sqlite.db import connect_sqlite


def _prepare(tmp_path, monkeypatch):
    path = tmp_path / "handoff.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", str(path))
    initialize(path)
    projection_hash = checkpoint()["projection_hash"]
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            UPDATE research_graph_instances
            SET created_by_profile_ref=?, current_owner_profile_ref=?
            WHERE instance_id=?
            """,
            ("profile:maxa", "profile:maxa", "instance-1"),
        )
    return path, projection_hash


def test_profile_handoff_commits_trace_and_owner_cas(tmp_path, monkeypatch):
    path, projection_hash = _prepare(tmp_path, monkeypatch)
    value = handoff_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        source_profile_ref="profile:maxa",
        destination_profile_ref="profile:maxb",
        expected_checkpoint_ref="trace:trace-bootstrap",
        expected_checkpoint_hash=projection_hash,
        authorization_ref="approval:handoff-1",
        source_display_name="MaxA",
        destination_display_name="MaxB",
    )
    assert value["current_owner_profile_ref"] == "profile:maxb"
    assert value["acting_profile_ref"] == "profile:maxa"
    assert value["checkpoint_hash"] == projection_hash

    with connect_sqlite(path) as conn:
        instance = conn.execute(
            "SELECT current_owner_profile_ref FROM research_graph_instances "
            "WHERE instance_id='instance-1'"
        ).fetchone()
        trace = conn.execute(
            "SELECT edge_id, acting_profile_ref, evidence_json "
            "FROM research_graph_trace WHERE trace_id=?",
            (value["trace_ref"].removeprefix("trace:"),),
        ).fetchone()
    assert instance["current_owner_profile_ref"] == "profile:maxb"
    assert trace["edge_id"] == "__profile_handoff__"
    assert trace["acting_profile_ref"] == "profile:maxa"
    evidence = orjson.loads(trace["evidence_json"])
    assert evidence["profile_handoff"]["authorization_ref"] == (
        "approval:handoff-1"
    )
    assert evidence["research_cycle_checkpoint"]["projection_hash"] == (
        projection_hash
    )


def test_profile_handoff_is_idempotent_and_rejects_stale_owner(
    tmp_path, monkeypatch
):
    _, projection_hash = _prepare(tmp_path, monkeypatch)
    kwargs = dict(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        source_profile_ref="profile:maxa",
        destination_profile_ref="profile:maxb",
        expected_checkpoint_ref="trace:trace-bootstrap",
        expected_checkpoint_hash=projection_hash,
        authorization_ref="approval:handoff-1",
    )
    first = handoff_graph_branch(**kwargs)
    retry = handoff_graph_branch(**kwargs)
    assert retry["trace_ref"] == first["trace_ref"]

    with pytest.raises(PermissionError):
        handoff_graph_branch(
            **{
                **kwargs,
                "destination_profile_ref": "profile:maxc",
                "authorization_ref": "approval:handoff-2",
            }
        )


def test_branch_payload_exposes_profile_ownership(tmp_path, monkeypatch):
    path, _ = _prepare(tmp_path, monkeypatch)
    with connect_sqlite(path) as conn:
        row = conn.execute(
            """
            SELECT i.*, b.* FROM research_graph_instances i
            JOIN research_graph_branches b ON b.instance_id=i.instance_id
            WHERE i.instance_id='instance-1' AND b.branch_id='branch-1'
            """
        ).fetchone()
    payload = branch_payload(row)
    assert payload["created_by_profile_ref"] == "profile:maxa"
    assert payload["current_owner_profile_ref"] == "profile:maxa"
