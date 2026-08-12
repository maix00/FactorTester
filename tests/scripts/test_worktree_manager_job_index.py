from __future__ import annotations

import sqlite3

import pytest

from scripts import worktree_manager_job_index as job_index


def test_manager_job_index_closes_connections_after_each_operation(
    tmp_path, monkeypatch,
) -> None:
    real_connect = job_index.sqlite3.connect
    connections: list[sqlite3.Connection] = []

    def tracked_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(job_index.sqlite3, "connect", tracked_connect)
    index = job_index.ManagerJobIndex(tmp_path / "jobs.sqlite")

    index.upsert("user@1", [{
        "job_id": "job-1",
        "port": 8141,
        "updated_at": "2026-08-06T00:00:00Z",
    }])
    assert index.list("user@1")
    assert index.ports_for("user@1", "job-1") == [8141]

    assert len(connections) == 4
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")


def test_manager_job_index_lists_newest_distinct_jobs_across_principals(tmp_path) -> None:
    index = job_index.ManagerJobIndex(tmp_path / "jobs.sqlite")
    index.upsert("__public_jobs__", [{
        "job_id": "job-1", "port": 8141, "updated_at": "2026-08-06T00:00:00Z",
    }])
    index.upsert("user@1", [{
        "job_id": "job-1", "port": 8141, "updated_at": "2026-08-06T00:01:00Z",
    }, {
        "job_id": "job-2", "port": 8176, "updated_at": "2026-08-06T00:02:00Z",
    }])

    assert index.list_all() == [{
        "job_id": "job-2", "port": 8176, "updated_at": "2026-08-06T00:02:00Z",
    }, {
        "job_id": "job-1", "port": 8141, "updated_at": "2026-08-06T00:01:00Z",
    }]


def test_manager_job_index_orders_numeric_and_iso_timestamps_consistently(tmp_path) -> None:
    index = job_index.ManagerJobIndex(tmp_path / "jobs.sqlite")
    index.upsert("user@1", [
        {"job_id": "numeric-old", "port": 8141, "updated_at": 10.0},
        {"job_id": "iso-new", "port": 8176, "updated_at": "2026-08-06T00:00:00Z"},
    ])

    assert [item["job_id"] for item in index.list("user@1")] == [
        "iso-new", "numeric-old",
    ]


def test_manager_job_index_pages_one_account_across_ports(tmp_path) -> None:
    index = job_index.ManagerJobIndex(tmp_path / "jobs.sqlite")
    index.upsert("user@1", [
        {"job_id": "job-old", "port": 8141, "updated_at": "2026-08-06T00:00:00Z"},
        {"job_id": "job-new", "port": 8176, "updated_at": "2026-08-06T00:02:00Z"},
        # The same job can be observed on more than one port; retain the
        # newest summary rather than showing a duplicate row.
        {"job_id": "job-old", "port": 8176, "updated_at": "2026-08-06T00:03:00Z"},
    ])

    first = index.page("user@1", page=1, limit=1)
    second = index.page("user@1", page=2, limit=1)

    assert first["total"] == 2
    assert first["jobs"] == [{
        "job_id": "job-old", "port": 8176, "updated_at": "2026-08-06T00:03:00Z",
    }]
    assert second["jobs"] == [{
        "job_id": "job-new", "port": 8176, "updated_at": "2026-08-06T00:02:00Z",
    }]


def test_manager_job_index_scopes_events_and_applies_them_idempotently(tmp_path) -> None:
    origin = job_index.ManagerJobIndex(
        tmp_path / "origin.sqlite", server_id="origin",
    )
    routing = origin.record_run_routing(
        run_id="run-1",
        principal="alice",
        origin_server_id="origin",
        execution_server_id="peer",
        execution_port=8000,
        execution_branch="main",
        execution_revision="abc123",
    )
    assert routing is not None

    origin.upsert("alice", [{
        "job_id": "job-1",
        "run_id": "run-1",
        "port": 8000,
        "server_id": "peer",
        "updated_at": "2026-08-06T00:01:00Z",
    }])
    related = origin.events_for_peer("peer")
    assert [item["event_type"] for item in related["events"]] == [
        "run.routed", "job.updated",
    ]

    peer = job_index.ManagerJobIndex(
        tmp_path / "peer.sqlite", server_id="peer",
    )
    assert peer.apply_events(related["events"]) == 2
    assert peer.apply_events(related["events"]) == 0
    value = peer.list("alice")[0]
    assert value["origin_server_id"] == "origin"
    assert value["execution_server_id"] == "peer"
    assert peer.list("__public_jobs__")[0]["job_id"] == "job-1"


def test_manager_job_index_does_not_send_local_only_events_to_peer(tmp_path) -> None:
    index = job_index.ManagerJobIndex(tmp_path / "jobs.sqlite", server_id="local")
    index.record_run_routing(
        run_id="run-local",
        principal="alice",
        origin_server_id="local",
        execution_server_id="local",
        execution_port=8000,
    )

    assert index.events_for_peer("remote")["events"] == []
