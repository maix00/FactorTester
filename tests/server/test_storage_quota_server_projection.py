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


def test_protected_metadata_inventory_excludes_tombstones_in_authority_query() -> None:
    class Connection:
        def execute(self, sql, args):
            assert "FROM control_account_domain_entities" in sql
            assert "NOT deleted" in sql
            assert args == ("alice",)
            return self

        def fetchall(self):
            return [
                {"entity_type": "factor_family", "item_count": 2, "bytes": 300},
                {"entity_type": "factor_source_version", "item_count": 1, "bytes": 40},
                {"entity_type": "product_group", "item_count": 3, "bytes": 90},
            ]

    @contextmanager
    def connection():
        yield Connection()

    store = object.__new__(PostgresControlStore)
    store._connection = connection
    assert store.protected_entity_metadata_usage("alice") == {
        "factors": {"bytes": 340, "item_count": 3},
        "product_groups": {"bytes": 90, "item_count": 3},
        "strategies": {"bytes": 0, "item_count": 0},
        "other": {"bytes": 0, "item_count": 0},
    }


def test_profile_snapshot_is_complete_and_preserves_observation_order() -> None:
    observed = datetime(2026, 10, 15, 2, 0, tzinfo=timezone.utc)
    statements = []

    class Connection:
        def execute(self, sql, args):
            statements.append((sql, args))
            return self

        def fetchall(self):
            return [{
                "server_id": "offline-a", "research_reports_bytes": 3,
                "profile_uploads_bytes": 5, "profile_workspaces_bytes": 7,
                "research_reports_count": 1, "profile_uploads_count": 2,
                "profile_workspaces_count": 1, "observed_at": observed,
            }]

    @contextmanager
    def connection():
        yield Connection()

    store = object.__new__(PostgresControlStore)
    store.ensure_schema = lambda: None
    store._connection = connection
    inventory = {"bytes": 15, "observed_at": observed.timestamp(),
                 "categories": {
                     "research_reports": {"bytes": 3, "file_count": 1},
                     "profile_uploads": {"bytes": 5, "file_count": 2},
                     "profile_workspaces": {"bytes": 7, "file_count": 1},
                 }}
    store.record_profile_usage(server_id="offline-a", principal="alice", inventory=inventory)
    assert "WHERE quota_profile_usage.observed_at <= EXCLUDED.observed_at" in statements[0][0]
    assert statements[0][1] == ("offline-a", "alice", 3, 5, 7, 1, 2, 1,
                                 observed.timestamp())
    assert store.profile_usage_by_server("alice") == [{
        "storage_server_id": "offline-a", "status": "last_observed",
        "inventory": {"bytes": 15, "observed_at": observed.isoformat(),
                      "categories": inventory["categories"]},
    }]


def test_unified_quota_uses_job_profile_and_account_domain_without_double_counting():
    class Connection:
        def execute(self, sql, args):
            assert "SUM(artifact_bytes)" in sql
            assert "SUM(research_reports_bytes + profile_uploads_bytes" in sql
            assert "SUM(OCTET_LENGTH(payload::text))" in sql
            assert "quota_deferred_output_cleanups" in sql
            assert args == ("alice",) * 4
            return self

        def fetchone(self):
            return {"used_bytes": 100 + 20 + 3}

    @contextmanager
    def connection():
        yield Connection()

    store = object.__new__(PostgresControlStore)
    store.ensure_schema = lambda: None
    store._connection = connection
    assert store.unified_usage_bytes("alice") == 123
