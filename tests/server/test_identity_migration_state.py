"""Manager projection identity migration tests."""

from __future__ import annotations

import sqlite3

from server.manager.storage.identity_migration_state import (
    migrate_manager_state_identity,
)
from server.manager.storage.job_index import ManagerJobIndex
from server.manager.storage.local_run_projection import LocalRunProjection


def test_manager_state_migration_renames_and_coalesces_job_projection(tmp_path):
    root = tmp_path / "manager-state"
    index = ManagerJobIndex(root / "job-index.sqlite", server_id="local")
    index.upsert(
        "legacy-user",
        [{
            "job_id": "job-1",
            "port": 8141,
            "owner": "legacy-user",
            "server_context": {"owner": "legacy-user"},
            "updated_at": "20",
        }],
    )
    index.record_run_routing(
        run_id="run-1",
        principal="legacy-user",
        origin_server_id="local",
        execution_server_id="local",
        execution_port=8141,
    )
    index.upsert(
        "canonical-user",
        [{
            "job_id": "job-1",
            "port": 8141,
            "owner": "canonical-user",
            "updated_at": "10",
        }],
    )

    result = migrate_manager_state_identity(
        root,
        old_username="legacy-user",
        new_username="canonical-user",
    )

    assert result["jobs"] == 1
    assert result["routing"] == 1
    rows = index.list("canonical-user")
    assert len(rows) == 1
    assert rows[0]["owner"] == "canonical-user"
    assert rows[0]["server_context"]["owner"] == "canonical-user"

    with sqlite3.connect(root / "job-index.sqlite") as db:
        assert db.execute(
            "select principal from run_routing where run_id='run-1'"
        ).fetchone()[0] == "canonical-user"


def test_manager_state_migration_renames_local_run_projection(tmp_path):
    root = tmp_path / "manager-state"
    projection = LocalRunProjection(
        root / "local-run-projection.sqlite", server_id="local",
    )
    projection.upsert(
        "legacy-user",
        {"local_job_id": "local-1", "updated_at": 10, "owner": "legacy-user"},
    )

    result = migrate_manager_state_identity(
        root,
        old_username="legacy-user",
        new_username="canonical-user",
    )

    assert result["local_runs"] == 1
    assert projection.page("legacy-user")["total"] == 0
    assert projection.page("canonical-user")["total"] == 1
