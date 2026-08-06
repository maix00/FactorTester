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
