"""Offline deletion is reversible before claim and guarded at reconnect."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from server.manager.services.startup_storage_inventory import (
    apply_deferred_output_cleanups,
)
from server.manager.storage.control_db import PostgresControlStore


def _store_with_usage():
    observed = datetime(2026, 10, 15, 2, tzinfo=timezone.utc)
    state = {"usage": {"output_bytes": 70, "output_count": 2,
                       "updated_at": observed}, "request": None}

    class Connection:
        row = None

        def execute(self, sql, args):
            if "FROM quota_server_usage" in sql and "FOR UPDATE" in sql:
                self.row = state["usage"] if args == (
                    "alice", "remote", observed.isoformat(),
                ) else None
            elif "SELECT requests.*" in sql:
                row = state["request"]
                self.row = ({**row, "credit_bytes": 70} if row and
                            row["status"] in {"pending", "executing"} else None)
            elif "INSERT INTO quota_deferred_output_cleanups" in sql:
                state["request"] = {
                    "request_id": args[0], "principal": args[1],
                    "server_id": args[2], "snapshot_output_bytes": args[3],
                    "snapshot_output_count": args[4],
                    "snapshot_observed_at": observed,
                    "status": "pending", "created_at": observed,
                    "claimed_at": None, "finished_at": None,
                    "deleted_artifacts": 0, "freed_bytes": 0, "error": "",
                }
                self.row = {**state["request"], "credit_bytes": 70}
            elif "SET status='cancelled'" in sql:
                row = state["request"]
                self.row = None
                if (row and row["principal"] == args[0]
                        and row["request_id"] == args[1]
                        and row["status"] == "pending"):
                    row["status"] = "cancelled"
                    self.row = {**row, "credit_bytes": 0}
            elif "WITH selected AS" in sql:
                row = state["request"]
                self.row = None
                if row and row["server_id"] == args[0] and row["status"] == "pending":
                    row["status"] = "executing"
                    self.row = {**row, "credit_bytes": 0}
            elif "SET status=%s" in sql:
                row = state["request"]
                self.row = None
                if (row and row["server_id"] == args[4]
                        and row["request_id"] == args[5]
                        and row["status"] == "executing"):
                    row.update(status=args[0], deleted_artifacts=args[1],
                               freed_bytes=args[2], error=args[3])
                    self.row = {**row, "credit_bytes": 0}
            elif "AS used_bytes" in sql:
                credit = 70 if state["request"] and state["request"]["status"] in {"pending", "executing"} else 0
                self.row = {"used_bytes": 80 - credit}
            else:
                raise AssertionError(sql)
            return self

        def fetchone(self):
            return self.row

    @contextmanager
    def connection():
        yield Connection()

    store = object.__new__(PostgresControlStore)
    store.ensure_schema = lambda: None
    store._connection = connection
    return store, state, observed.isoformat()


def test_queue_refunds_on_cancel_and_cannot_cancel_after_claim() -> None:
    store, _state, observed = _store_with_usage()
    assert store.unified_usage_bytes("alice") == 80
    request = store.queue_deferred_output_cleanup(
        principal="alice", server_id="remote", expected_bytes=70,
        expected_count=2, observed_at=observed,
    )
    assert request["credit_bytes"] == 70
    assert store.unified_usage_bytes("alice") == 10
    assert store.queue_deferred_output_cleanup(
        principal="alice", server_id="remote", expected_bytes=70,
        expected_count=2, observed_at=observed,
    )["request_id"] == request["request_id"]
    with pytest.raises(ValueError, match="snapshot changed"):
        store.queue_deferred_output_cleanup(
            principal="alice", server_id="remote", expected_bytes=71,
            expected_count=2, observed_at=observed,
        )
    with pytest.raises(ValueError, match="unavailable"):
        store.cancel_deferred_output_cleanup(
            principal="bob", request_id=request["request_id"],
        )
    assert store.cancel_deferred_output_cleanup(
        principal="alice", request_id=request["request_id"],
    )["status"] == "cancelled"
    assert store.unified_usage_bytes("alice") == 80
    replacement = store.queue_deferred_output_cleanup(
        principal="alice", server_id="remote", expected_bytes=70,
        expected_count=2, observed_at=observed,
    )
    assert replacement["request_id"] != request["request_id"]
    assert store.claim_deferred_output_cleanup(server_id="remote")["status"] == "executing"
    assert store.unified_usage_bytes("alice") == 10
    with pytest.raises(ValueError, match="already executing"):
        store.cancel_deferred_output_cleanup(
            principal="alice", request_id=replacement["request_id"],
        )
    finished = store.finish_deferred_output_cleanup(
        server_id="remote", request_id=replacement["request_id"],
        status="completed", deleted_artifacts=2, freed_bytes=70,
    )
    assert finished["status"] == "completed"
    assert finished["freed_bytes"] == 70


@pytest.mark.parametrize("count,bytes_,created_at,expected", [
    (2, 70, 1, "completed"), (3, 70, 1, "needs_review"),
    (2, 71, 1, "needs_review"), (2, 70, 1_792_030_000, "needs_review"),
])
def test_reconnect_executes_only_unchanged_terminal_outputs(
    monkeypatch, tmp_path, count: int, bytes_: int,
    created_at: float, expected: str,
) -> None:
    request = {"request_id": "a" * 32, "principal": "alice",
               "server_id": "remote", "snapshot_output_count": 2,
               "snapshot_output_bytes": 70,
               "snapshot_observed_at": "2026-10-15T02:00:00+00:00"}
    events = []

    class Store:
        def claim_deferred_output_cleanup(self, *, server_id):
            assert server_id == "remote"
            return request if not events else None

        def finish_deferred_output_cleanup(self, **kwargs):
            events.append(kwargs)

    class Repo:
        def storage_inventory(self, *, owner):
            assert owner == "alice"
            return {"cleanup_preview": {"artifact_count": count,
                                        "bytes": bytes_, "token": "f" * 64,
                                        "max_created_at": created_at}}

        def mark_cleanup_outputs_deleted(self, **kwargs):
            events.append(("deleted", kwargs))
            return [{"relative_path": "gone", "size_bytes": 70}]

        def storage_usage(self, **kwargs):
            return 0

    monkeypatch.setattr("server.jobs.repository.JobRepository", Repo)
    monkeypatch.setattr(
        "server.manager.services.job_storage_control.artifact_root",
        lambda: tmp_path,
    )
    result = apply_deferred_output_cleanups(
        SimpleNamespace(control_store=Store(), server_id="remote"),
    )
    assert result[expected] == 1
    assert events[-1]["status"] == expected
    assert len(events) == (2 if expected == "completed" else 1)
