from __future__ import annotations

from copy import deepcopy

import pytest

import settings as Settings
from server.jobs.repository import JobRepository
from server.services import research_graphs, research_runs
from server.services.research_graph.protocol import graph_content_hash
from server.services.research_graph.history_recovery import (
    canonical_history_artifacts,
    inspect_history_recovery,
    recover_history,
)
from tests.server.trial_plan_fixtures import run_spec
from tools.migrations.recover_research_graph_history import main


def test_canonical_history_artifacts_have_exact_audited_identity() -> None:
    artifacts = canonical_history_artifacts()

    assert [
        (
            item.version,
            item.content_hash,
            len(item.graph_json),
            item.lifecycle,
            item.parent_version,
            len(item.graph["nodes"]),
            len(item.graph["edges"]),
        )
        for item in artifacts
    ] == [
        (
            1,
            "d8d76b80fbca0342d3b8477e1594bfd7"
            "da1dab2924c7d2d078bf64e8ba44d64e",
            6974,
            "observed",
            0,
            13,
            13,
        ),
        (
            2,
            "95a82ea250f1502b7ce7706f85a66373"
            "8afc08f5ec7f8bcebc71d7082f6bf689",
            22130,
            "draft",
            1,
            14,
            19,
        ),
        (
            3,
            "ae7bbc1ad50b22e75c6f781ced3510cd"
            "05de250f966bbb402e7bba999421c3b2",
            24696,
            "draft",
            2,
            14,
            21,
        ),
    ]


def _graph(version: int) -> dict:
    graph = {
        "schema_version": 1,
        "graph_id": "factor-research",
        "version": version,
        "parent_version": version - 1,
        "lifecycle": "draft",
        "research_semantics": "product_neutral",
        "entry_node": "node",
        "nodes": [{
            "node_id": "node",
            "kind": "research",
            "purpose": f"test v{version}",
            "enforcement": "deterministic",
            "required_capabilities": [],
            "conditional_capabilities": [],
        }],
        "edges": [],
        "capability_descriptors": {},
        "provenance": {"source": "test"},
    }
    graph["content_hash"] = graph_content_hash(graph)
    return graph


@pytest.fixture()
def recovery_db(tmp_path, monkeypatch):
    path = tmp_path / "graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    research_graphs.ensure_schema()
    JobRepository().ensure_schema()
    for version in range(4, 10):
        research_graphs.register_graph(_graph(version), actor="test-curator")
    with research_graphs.connect_sqlite(path) as conn:
        conn.execute(
            """
            INSERT INTO active_research_graphs (
                graph_id, version, activated_by, activated_at
            ) VALUES ('factor-research', 8, 'alice', 8.0)
            """
        )
    instance = research_graphs.create_graph_instance(
        graph_id="factor-research",
        owner="alice",
        product_group="equities",
        workspace_id="workspace-1",
        capability_resolution={
            "node_id": "node",
            "bindings": [],
            "gaps": [],
            "triggered_conditional_bindings": [],
            "undetermined_conditions": [],
        },
    )
    branch = instance["branches"][0]
    with research_graphs.connect_sqlite(path) as conn:
        conn.execute(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id, from_node,
                to_node, evidence_json, actor, created_at
            ) VALUES (
                'trace-1', ?, ?, 'test-edge', 'node', 'node',
                '{}', 'alice', 9.0
            )
            """,
            (instance["instance_id"], branch["branch_id"]),
        )
    run = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-1",
        configuration_revision=1,
        run_spec=run_spec(),
    )
    with research_graphs.connect_sqlite(path) as conn:
        conn.execute(
            """
            INSERT INTO research_jobs (
                job_id, run_id, owner, workspace_id, kind, status,
                job_spec_json, job_spec_hash, entitlement_json,
                created_at, updated_at
            ) VALUES (
                'job-1', ?, 'alice', 'workspace-1', 'factor_research',
                'succeeded', '{}', ?, '{}', 10.0, 10.0
            )
            """,
            (run["run_id"], "a" * 64),
        )
    return path


def test_recovery_is_atomic_and_preserves_all_existing_state(
    recovery_db,
    tmp_path,
) -> None:
    dry_run = inspect_history_recovery(db_path=recovery_db)
    assert dry_run["status"] == "ready"
    before = deepcopy(dry_run["preserved_snapshot"])
    backup = tmp_path / "backup.sqlite"

    result = recover_history(
        db_path=recovery_db,
        backup_path=backup,
        expected_plan_hash=dry_run["plan_hash"],
    )

    assert result["applied"] is True
    assert result["inserted_versions"] == [1, 2, 3]
    assert result["preserved_snapshot"] == before
    assert backup.exists()
    with research_graphs.connect_sqlite(recovery_db) as conn:
        rows = conn.execute(
            """
            SELECT version, parent_version, content_hash, graph_json,
                   created_by
            FROM research_graph_versions
            WHERE graph_id='factor-research' ORDER BY version
            """
        ).fetchall()
    assert [int(row["version"]) for row in rows] == list(range(1, 10))
    assert [int(row["parent_version"]) for row in rows[:4]] == [0, 1, 2, 3]
    artifacts = canonical_history_artifacts()
    assert [
        str(rows[index]["graph_json"]).encode()
        for index in range(3)
    ] == [item.graph_json for item in artifacts]
    assert [
        str(rows[index]["created_by"]) for index in range(3)
    ] == [
        f"history-recovery:{item.source_commit}" for item in artifacts
    ]


def test_private_cli_defaults_to_a_read_only_dry_run(
    recovery_db,
    capsys,
) -> None:
    assert main(["--db", str(recovery_db)]) == 0

    output = capsys.readouterr().out
    assert '"status":"ready"' in output
    with research_graphs.connect_sqlite(recovery_db) as conn:
        assert conn.execute(
            """
            SELECT COUNT(*) FROM research_graph_versions
            WHERE graph_id='factor-research' AND version BETWEEN 1 AND 3
            """
        ).fetchone()[0] == 0


def test_private_cli_requires_reviewed_plan_hash_for_apply(
    recovery_db,
    tmp_path,
) -> None:
    with pytest.raises(
        SystemExit,
        match="expected-plan-hash is required",
    ):
        main([
            "--db", str(recovery_db),
            "--apply",
            "--backup", str(tmp_path / "backup.sqlite"),
        ])


def test_recovery_write_api_requires_reviewed_plan_hash(
    recovery_db,
    tmp_path,
) -> None:
    with pytest.raises(ValueError, match="expected_plan_hash is required"):
        recover_history(
            db_path=recovery_db,
            backup_path=tmp_path / "backup.sqlite",
        )


def test_recovery_is_idempotent_without_another_backup(
    recovery_db,
    tmp_path,
) -> None:
    plan = inspect_history_recovery(db_path=recovery_db)
    recover_history(
        db_path=recovery_db,
        backup_path=tmp_path / "first.sqlite",
        expected_plan_hash=plan["plan_hash"],
    )
    unused_backup = tmp_path / "unused.sqlite"
    repeated_plan = inspect_history_recovery(db_path=recovery_db)

    repeated = recover_history(
        db_path=recovery_db,
        backup_path=unused_backup,
        expected_plan_hash=repeated_plan["plan_hash"],
    )

    assert repeated["applied"] is False
    assert repeated["status"] == "already_recovered"
    assert not unused_backup.exists()


def test_recovery_rolls_back_every_version_on_failure(
    recovery_db,
    tmp_path,
) -> None:
    plan = inspect_history_recovery(db_path=recovery_db)

    def fail_after_v2(point: str) -> None:
        if point == "after_v2":
            raise RuntimeError("injected recovery failure")

    with pytest.raises(RuntimeError, match="injected recovery failure"):
        recover_history(
            db_path=recovery_db,
            backup_path=tmp_path / "backup.sqlite",
            expected_plan_hash=plan["plan_hash"],
            failure_injector=fail_after_v2,
        )

    with research_graphs.connect_sqlite(recovery_db) as conn:
        assert conn.execute(
            """
            SELECT COUNT(*) FROM research_graph_versions
            WHERE graph_id='factor-research' AND version BETWEEN 1 AND 3
            """
        ).fetchone()[0] == 0


def test_recovery_rejects_partial_or_conflicting_history(
    recovery_db,
    tmp_path,
) -> None:
    artifact = canonical_history_artifacts()[0]
    with research_graphs.connect_sqlite(recovery_db) as conn:
        conn.execute(
            """
            INSERT INTO research_graph_versions (
                graph_id, version, lifecycle, parent_version, content_hash,
                graph_json, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'bad-import', 1.0)
            """,
            (
                "factor-research",
                1,
                artifact.lifecycle,
                artifact.parent_version,
                artifact.content_hash,
                artifact.graph_json.decode(),
            ),
        )

    plan = inspect_history_recovery(db_path=recovery_db)
    assert plan["status"] == "blocked"
    assert plan["blocking_reason"] == "Graph v1-v3 recovery is partial"
    with pytest.raises(ValueError, match="partial"):
        recover_history(
            db_path=recovery_db,
            backup_path=tmp_path / "backup.sqlite",
            expected_plan_hash=plan["plan_hash"],
        )


def test_recovery_rejects_a_complete_but_noncanonical_history(
    recovery_db,
    tmp_path,
) -> None:
    artifacts = canonical_history_artifacts()
    with research_graphs.connect_sqlite(recovery_db) as conn:
        for artifact in artifacts:
            graph_json = (
                artifact.graph_json.decode() + " "
                if artifact.version == 2
                else artifact.graph_json.decode()
            )
            conn.execute(
                """
                INSERT INTO research_graph_versions (
                    graph_id, version, lifecycle, parent_version,
                    content_hash, graph_json, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'bad-import', 1.0)
                """,
                (
                    "factor-research",
                    artifact.version,
                    artifact.lifecycle,
                    artifact.parent_version,
                    artifact.content_hash,
                    graph_json,
                ),
            )

    plan = inspect_history_recovery(db_path=recovery_db)
    assert plan["status"] == "blocked"
    assert "conflicts" in plan["blocking_reason"]
    with pytest.raises(ValueError, match="conflicts"):
        recover_history(
            db_path=recovery_db,
            backup_path=tmp_path / "backup.sqlite",
            expected_plan_hash=plan["plan_hash"],
        )
