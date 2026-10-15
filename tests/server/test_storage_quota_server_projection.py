from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from server.manager.storage.control_db import PostgresControlStore


def test_job_quota_server_projection_keeps_identity_and_observation_time() -> None:
    observed = datetime(2026, 10, 15, 2, 0, tzinfo=timezone.utc)

    class Connection:
        def execute(self, sql, args):
            assert "FROM quota_server_usage WHERE principal=%s" in sql
            assert args == ("alice",)
            return self

        def fetchall(self):
            return [{
                "server_id": "remote-a", "artifact_bytes": 13,
                "input_bytes": 5, "output_bytes": 8,
                "artifact_count": 2, "input_count": 1, "output_count": 1,
                "updated_at": observed,
            }]

    @contextmanager
    def connection():
        yield Connection()

    store = object.__new__(PostgresControlStore)
    store.ensure_schema = lambda: None
    store._connection = connection
    assert store.usage_by_server("alice") == [{
        "storage_server_id": "remote-a", "artifact_bytes": 13,
        "input_bytes": 5, "output_bytes": 8,
        "artifact_count": 2, "input_count": 1, "output_count": 1,
        "observed_at": "2026-10-15T02:00:00+00:00",
    }]
