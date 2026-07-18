from __future__ import annotations

import sqlite3

import orjson
import pytest

import settings as Settings
from cli_anything.factortester_research.core.graph import build_draft_graph
from server.services import research_graphs
from server.services.research_graph.branch import context as branch_context
from server.services.research_graph.branch.migration import (
    migrate_graph_branch_projection,
)
from server.services.research_graph.branch.projection import (
    normalize_capability_resolution,
    serialize_capability_resolution,
)
from tools.data.sqlite.db import connect_sqlite


_DROPPED_TABLES = {
    "research_graph_node_resolutions",
    "research_capability_receipts",
}
_DROPPED_BRANCH_COLUMNS = {
    "cumulative_input_tokens",
    "cumulative_output_tokens",
    "cumulative_cache_read_tokens",
    "cumulative_skill_document_tokens",
    "cumulative_artifact_summary_tokens",
    "cumulative_reviewer_tokens",
    "skill_document_load_count",
    "skill_context_cache_hits",
    "trace_count",
    "aggregate_version",
}


def _create_legacy_branch_schema(path) -> dict:
    graph = build_draft_graph()
    entry_node = graph["entry_node"]
    descriptor = graph["capability_descriptors"][
        "research-hypothesis.preregister"
    ]
    resolution = {
        "node_id": entry_node,
        "bindings": [{
            "capability_id": "research-hypothesis.preregister",
            **descriptor,
        }],
        "gaps": [],
        "triggered_conditional_bindings": [],
        "triggered_conditional_gaps": [],
        "undetermined_conditions": [],
    }
    with connect_sqlite(path) as conn:
        conn.executescript(
            """
            CREATE TABLE research_graph_versions (
                graph_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                lifecycle TEXT NOT NULL,
                parent_version INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                graph_json TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (graph_id, version)
            );
            CREATE TABLE active_research_graphs (
                graph_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                activated_by TEXT NOT NULL,
                activated_at REAL NOT NULL
            );
            CREATE TABLE research_graph_instances (
                instance_id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                graph_id TEXT NOT NULL,
                graph_version INTEGER NOT NULL,
                product_group TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                capability_resolution_json TEXT NOT NULL,
                token_budget INTEGER,
                mode TEXT NOT NULL DEFAULT 'live',
                shadow_run_id TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            );
            CREATE INDEX idx_research_graph_instances_owner
            ON research_graph_instances(owner, created_at);
            CREATE TABLE research_graph_branches (
                branch_id TEXT PRIMARY KEY,
                instance_id TEXT NOT NULL,
                label TEXT NOT NULL,
                current_node TEXT NOT NULL,
                status TEXT NOT NULL,
                cumulative_input_tokens INTEGER NOT NULL DEFAULT 0,
                cumulative_output_tokens INTEGER NOT NULL DEFAULT 0,
                cumulative_cache_read_tokens INTEGER NOT NULL DEFAULT 0,
                cumulative_skill_document_tokens INTEGER NOT NULL DEFAULT 0,
                cumulative_artifact_summary_tokens INTEGER NOT NULL DEFAULT 0,
                cumulative_reviewer_tokens INTEGER NOT NULL DEFAULT 0,
                skill_document_load_count INTEGER NOT NULL DEFAULT 0,
                skill_context_cache_hits INTEGER NOT NULL DEFAULT 0,
                evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                omitted_evidence_count INTEGER NOT NULL DEFAULT 0,
                latest_trace_id TEXT NOT NULL DEFAULT '',
                trace_count INTEGER NOT NULL DEFAULT 0,
                aggregate_version INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX idx_research_graph_branches_instance
            ON research_graph_branches(instance_id, created_at);
            CREATE TABLE research_graph_node_resolutions (
                instance_id TEXT NOT NULL,
                branch_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                resolution_json TEXT NOT NULL,
                semantic_cache_key TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (instance_id, branch_id, node_id)
            );
            CREATE TABLE research_capability_receipts (
                receipt_id TEXT PRIMARY KEY,
                resolver_attestation TEXT NOT NULL
            );
            CREATE TABLE research_graph_trace (
                trace_id TEXT PRIMARY KEY,
                instance_id TEXT NOT NULL,
                branch_id TEXT NOT NULL,
                edge_id TEXT NOT NULL,
                from_node TEXT NOT NULL,
                to_node TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                telemetry_json TEXT NOT NULL DEFAULT '{}',
                actor TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX idx_research_graph_trace_branch
            ON research_graph_trace(instance_id, branch_id, created_at);
            """
        )
        conn.execute(
            """
            INSERT INTO research_graph_versions
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                graph["graph_id"],
                graph["version"],
                graph["lifecycle"],
                graph["parent_version"],
                graph["content_hash"],
                orjson.dumps(graph).decode(),
                "fixture",
                1.0,
            ),
        )
        conn.execute(
            "INSERT INTO active_research_graphs VALUES (?, ?, ?, ?)",
            (graph["graph_id"], graph["version"], "fixture", 1.0),
        )
        conn.execute(
            """
            INSERT INTO research_graph_instances
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "instance-1",
                "alice",
                graph["graph_id"],
                graph["version"],
                "equities",
                "workspace-1",
                "{}",
                999,
                "live",
                "",
                1.0,
            ),
        )
        conn.execute(
            """
            INSERT INTO research_graph_branches
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                "branch-1",
                "instance-1",
                "primary",
                entry_node,
                "running",
                100,
                20,
                10,
                5,
                4,
                3,
                1,
                2,
                '["artifact:one"]',
                0,
                "trace-1",
                1,
                1,
                1.0,
                2.0,
            ),
        )
        conn.execute(
            """
            INSERT INTO research_graph_node_resolutions
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "instance-1",
                "branch-1",
                entry_node,
                orjson.dumps(resolution).decode(),
                "legacy-resolution",
                1.0,
            ),
        )
        conn.execute(
            "INSERT INTO research_capability_receipts VALUES (?, ?)",
            ("receipt-1", "legacy"),
        )
        conn.execute(
            """
            INSERT INTO research_graph_trace
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "trace-1",
                "instance-1",
                "branch-1",
                "fixture-edge",
                entry_node,
                entry_node,
                orjson.dumps({
                    "evidence_refs": ["artifact:one"],
                    "trial_plan_hash": "a" * 64,
                }).decode(),
                orjson.dumps({"input_tokens": 100}).decode(),
                "alice",
                2.0,
            ),
        )
    return {"graph": graph, "resolution": resolution}


def _tables(path) -> set[str]:
    with connect_sqlite(path) as conn:
        return {
            str(row["name"])
            for row in conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        }


def test_forward_migration_is_atomic_replayable_and_restart_safe(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "legacy-branch.sqlite"
    fixture = _create_legacy_branch_schema(path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    with pytest.raises(
        RuntimeError,
        match="migrate_graph_branch_projection",
    ):
        research_graphs.ensure_schema()
    statements: list[str] = []
    original_connect = connect_sqlite

    def traced_connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(
        "server.services.research_graph.branch.migration.connect_sqlite",
        traced_connect,
    )
    report = migrate_graph_branch_projection(db_path=path)
    first_migration_statements = list(statements)
    statements.clear()
    repeated = migrate_graph_branch_projection(db_path=path)

    assert report["instances_migrated"] == 1
    assert report["branches_migrated"] == 1
    assert report["node_resolution_rows_projected"] == 1
    assert report["capability_receipt_rows_dropped"] == 1
    assert report["schema_tables_removed"] == 2
    assert report["transactions"] == 1
    assert "3045e844" in report["rollback_target"]
    assert report["latency_ms"] >= 0
    assert repeated["transactions"] == 0
    assert _DROPPED_TABLES.isdisjoint(_tables(path))
    assert sum(
        statement.lstrip().upper().startswith("BEGIN IMMEDIATE")
        for statement in first_migration_statements
    ) == 1
    assert sum(
        statement.lstrip().upper().startswith(("SELECT ", "PRAGMA "))
        for statement in first_migration_statements
    ) == 14
    assert sum(
        statement.lstrip().upper().startswith((
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "REPLACE ",
            "CREATE ",
            "ALTER ",
            "DROP ",
        ))
        for statement in first_migration_statements
    ) == 16
    assert sum(
        statement.lstrip().upper().startswith("COMMIT")
        for statement in first_migration_statements
    ) == 1

    with original_connect(path) as conn:
        branch = conn.execute(
            "SELECT * FROM research_graph_branches"
        ).fetchone()
        trace = conn.execute(
            "SELECT * FROM research_graph_trace WHERE trace_id='trace-1'"
        ).fetchone()
        branch_columns = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(research_graph_branches)"
            ).fetchall()
        }
    assert _DROPPED_BRANCH_COLUMNS.isdisjoint(branch_columns)
    assert orjson.loads(
        branch["current_capability_resolution_json"]
    ) == fixture["resolution"]
    assert branch["current_trial_plan_hash"] == "a" * 64
    assert branch["evidence_refs_json"] == '["artifact:one"]'
    assert orjson.loads(trace["telemetry_json"]) == {"input_tokens": 100}

    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    research_graphs._clear_graph_cache_for_current_db()
    research_graphs.ensure_schema()
    monkeypatch.setattr(
        research_graphs.agent_flow,
        "get_store",
        lambda: pytest.fail("routine Graph context read Agent Flow"),
    )
    context_statements: list[str] = []

    def traced_runtime_connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        conn.set_trace_callback(context_statements.append)
        return conn

    monkeypatch.setattr(
        branch_context,
        "connect_sqlite",
        traced_runtime_connect,
    )
    context = research_graphs.build_graph_branch_context(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
    )
    context_only_statements = list(context_statements)
    context_statements.clear()
    next_packet = research_graphs.build_graph_branch_next(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
    )
    assert context["node"]["node_id"] == fixture["graph"]["entry_node"]
    assert context["branch"]["trial_plan_hash"] == "a" * 64
    assert "token_telemetry" not in context
    assert next_packet["next_bytes"] <= 6000
    assert not any(
        "RESEARCH_GRAPH_TRACE" in statement.upper()
        for statement in context_only_statements + context_statements
    )
    assert not any(
        "PRAGMA " in statement.upper()
        for statement in context_only_statements + context_statements
    )
    assert sum(
        statement.lstrip().upper().startswith("SELECT ")
        for statement in context_only_statements
    ) <= 2
    assert sum(
        statement.lstrip().upper().startswith("SELECT ")
        for statement in context_statements
    ) == 1
    assert not any(
        statement.lstrip().upper().startswith(
            ("INSERT ", "UPDATE ", "DELETE ", "REPLACE ")
        )
        for statement in context_only_statements + context_statements
    )


def test_failed_migration_rolls_back_to_complete_legacy_fixture(
    tmp_path,
) -> None:
    path = tmp_path / "rollback.sqlite"
    _create_legacy_branch_schema(path)

    with pytest.raises(RuntimeError, match="injected"):
        migrate_graph_branch_projection(
            db_path=path,
            failure_injector=lambda stage: (
                (_ for _ in ()).throw(RuntimeError("injected"))
                if stage == "after_target_write"
                else None
            ),
        )

    assert _DROPPED_TABLES.issubset(_tables(path))
    with connect_sqlite(path) as conn:
        assert "token_budget" in {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(research_graph_instances)"
            ).fetchall()
        }
        assert conn.execute(
            "SELECT COUNT(*) FROM research_graph_branches"
        ).fetchone()[0] == 1


@pytest.mark.parametrize(
    "resolution",
    [
        {"node_id": "node", "skill_name": "forbidden"},
        {
            "node_id": "node",
            "cache": {"nested": {"implementation_id": "forbidden"}},
        },
    ],
)
def test_branch_resolution_rejects_skill_identity_recursively(
    resolution,
) -> None:
    with pytest.raises(ValueError, match="not Skill identity"):
        normalize_capability_resolution(
            resolution,
            node_id="node",
        )


def test_branch_resolution_has_a_hard_serialized_size_limit() -> None:
    with pytest.raises(ValueError, match="exceeds 4096 bytes"):
        serialize_capability_resolution(
            {
                "node_id": "node",
                "gaps": [{
                    "capability_id": "gap",
                    "reason": "x" * 5000,
                }],
            },
            node_id="node",
        )


def test_branch_resolution_drops_runtime_cache_and_provider_state() -> None:
    projected = normalize_capability_resolution(
        {
            "node_id": "node",
            "bindings": [],
            "cache": {"key": "runtime-dependent"},
            "catalog_hash": "c" * 64,
            "provider_conformance_hash": "e" * 64,
        },
        node_id="node",
    )

    assert set(projected) == {
        "node_id",
        "bindings",
        "gaps",
        "triggered_conditional_bindings",
        "triggered_conditional_gaps",
        "undetermined_conditions",
    }
